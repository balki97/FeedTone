from .runtime import kernel_path
"""Independent dual-voice pitch vocoder; validation status is in research/PITCH.md."""
import ctypes
import math
from pathlib import Path
import struct

import numpy as np

from .basic import Equalizer
from .pitch_fft import PitchFFT, window as _exact_window


_F = ctypes.POINTER(ctypes.c_float)
_U = ctypes.POINTER(ctypes.c_uint32)
_path = kernel_path('PitchKernels')
_library = ctypes.CDLL(str(_path)) if _path.exists() else None
if _library:
    _library.ft_pitch_abi.restype = ctypes.c_uint32
    if _library.ft_pitch_abi() != 1:
        raise RuntimeError('Pitch kernel ABI mismatch')
    _library.ft_pitch_resample.argtypes = [_F, ctypes.c_uint32, ctypes.c_float, _F, ctypes.c_uint32, _F, _F, _U, _U]
    _library.ft_pitch_cartesian.argtypes = [_F, ctypes.c_uint32]
    _library.ft_pitch_polar.argtypes = [_F, ctypes.c_uint32]
    _library.ft_pitch_interpolate.argtypes = [_F, _F, _F, _F, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_float, ctypes.c_uint32]
    _library.ft_multipitch.argtypes = [_F, _F, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, _F, ctypes.c_uint32, _F, _U, ctypes.c_float]
    _library.ft_pitch_mix.argtypes = [_F, _F, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]


def _pointer(array):
    if array.dtype != np.float32 or not array.flags.c_contiguous:
        raise ValueError('Pitch kernel requires contiguous float32 arrays')
    return array.ctypes.data_as(_F)


def _check(result):
    if result != 1:
        raise ArithmeticError('Independent pitch kernel rejected its input')


def _mix(dry, wet, old_dry, new_dry, old_wet, new_wet):
    _check(_library.ft_pitch_mix(_pointer(dry), _pointer(wet), len(dry), dry.shape[1], old_dry, new_dry, old_wet, new_wet))


def _window(size):
    return _exact_window(size)


class _VoiceChannel:
    def __init__(self, size, ratio, window, synthesis):
        self.size, self.hop, self.ratio = size, size//4, ratio
        self.fft = PitchFFT(size)
        self.window, self.synthesis = window, synthesis
        self.capacity = size+size//4
        self.input = np.zeros(self.capacity, dtype=np.float32)
        self.input_read = self.input_write = 0
        self.input_count = self.capacity
        self.resample_position = ctypes.c_float(0)
        self.resample_previous = ctypes.c_float(0)
        self.spectra = [None, None]
        self.current = 0
        self.phase = np.zeros(size//2+1, dtype=np.float32)
        self.fraction = np.float32(0)
        self.initialize_phase = True
        self.skip = 0
        self.output = np.zeros(size, dtype=np.float32)
        self.output_read = self.output_write = self.output_count = 0

    def _advance(self, count):
        count = min(count, self.input_count)
        self.input_read = (self.input_read+count) % self.capacity
        self.input_count -= count
        return count

    def _push(self, audio):
        free = self.capacity-self.input_count
        if not len(audio) or not free:
            return 0
        samples = np.empty(free, dtype=np.float32)
        produced, consumed = ctypes.c_uint32(0), ctypes.c_uint32(0)
        _check(_library.ft_pitch_resample(_pointer(audio), len(audio), self.ratio, _pointer(samples), free,
                                         ctypes.byref(self.resample_position), ctypes.byref(self.resample_previous),
                                         ctypes.byref(produced), ctypes.byref(consumed)))
        count = produced.value
        first = min(count, self.capacity-self.input_write)
        self.input[self.input_write:self.input_write+first] = samples[:first]
        self.input[:count-first] = samples[first:count]
        self.input_write = (self.input_write+count) % self.capacity
        self.input_count += count
        return consumed.value

    def _analyze(self):
        if self.input_count < self.size:
            return None
        first = min(self.size, self.capacity-self.input_read)
        frame = np.concatenate((self.input[self.input_read:self.input_read+first], self.input[:self.size-first]))
        self._advance(self.hop)
        frame = np.float32(frame*self.window)
        spectrum = self.fft.forward(frame)
        _check(_library.ft_pitch_cartesian(_pointer(spectrum), len(spectrum)))
        return spectrum

    def _synthesize(self):
        spectrum = np.empty((self.size//2+1, 2), dtype=np.float32)
        _check(_library.ft_pitch_interpolate(_pointer(self.spectra[self.current]), _pointer(self.spectra[1-self.current]),
                                            _pointer(self.phase), _pointer(spectrum), self.size, self.hop,
                                            self.fraction, self.initialize_phase))
        self.initialize_phase = False
        _check(_library.ft_pitch_polar(_pointer(spectrum), len(spectrum)))
        frame = self.fft.inverse(spectrum)
        frame = np.float32(frame*np.float32(1/self.size))
        frame = np.float32(frame*self.synthesis)
        first = self.size-self.output_write
        self.output[self.output_write:] = np.float32(self.output[self.output_write:]+frame[:first])
        self.output[:self.output_write] = np.float32(self.output[:self.output_write]+frame[first:])
        self.output_write = (self.output_write+self.hop) % self.size
        self.output_count += self.hop
        self.fraction = np.float32(self.fraction+np.float32(1/self.ratio))
        if self.fraction >= 1:
            advance = math.floor(float(self.fraction))
            self.spectra[self.current] = None
            if advance < 2:
                self.current = 1-self.current
            else:
                self.spectra[1-self.current] = None
                skip = (advance-2)*self.hop
                self.skip = skip-self._advance(skip)
            self.fraction = np.float32(float(self.fraction)-advance)

    def process(self, audio):
        result = np.zeros(len(audio), dtype=np.float32)
        used = rendered = 0
        for _ in range(100):
            if used == len(audio) and rendered == len(audio):
                return result
            skip = min(self.skip, len(audio)-used)
            used += skip
            self.skip -= skip
            if used < len(audio):
                used += self._push(audio[used:])
            for index in (self.current, 1-self.current):
                if self.spectra[index] is None:
                    self.spectra[index] = self._analyze()
            if self.spectra[0] is not None and self.spectra[1] is not None and self.output_count == 0:
                self._synthesize()
            count = min(len(audio)-rendered, self.output_count)
            first = min(count, self.size-self.output_read)
            result[rendered:rendered+first] = self.output[self.output_read:self.output_read+first]
            self.output[self.output_read:self.output_read+first] = 0
            result[rendered+first:rendered+count] = self.output[:count-first]
            self.output[:count-first] = 0
            self.output_read = (self.output_read+count) % self.size
            self.output_count -= count
            rendered += count
        raise ArithmeticError('Pitch pipeline could not consume its complete quantum')


class Pitch:
    plugin_id = 0x8a0003

    def __init__(self, parameters, sample_rate=48000, channels=1, initial_parameters=None):
        if _library is None:
            raise RuntimeError('Build the independent native/PitchKernels.dll first')
        if len(parameters) != 68 or sample_rate != 48000 or channels not in (1, 2):
            raise ValueError('Pitch requires its 68-byte block and 48 kHz mono/stereo')
        self.sample_rate, self.channels = sample_rate, channels
        self.voices = [list(struct.unpack_from('<B2fI3f', parameters, i*25)) for i in range(2)]
        self.mode, self.dry_db, self.wet_db, self.size, self.process_lfe, self.align_dry = struct.unpack_from('<I2fIBB', parameters, 50)
        self._ready = False
        self._validate()
        for parameter_id, value in (initial_parameters or {}).items():
            self.set_parameter(parameter_id, value)
        self._initialize()
        self._ready = True

    def _validate(self):
        if not 0 <= self.mode <= 6 or not 512 <= self.size <= 16384 or self.size % 4:
            raise ValueError('Pitch channel mode or window size is unsupported')
        if not all(math.isfinite(v) and -200 <= v <= 100 for v in (self.dry_db, self.wet_db)):
            raise ValueError('Invalid pitch mix gain')
        for enabled, cents, gain, kind, filter_gain, frequency, q in self.voices:
            if not all(math.isfinite(v) for v in (cents, gain, filter_gain, frequency, q)) or not -2400 <= cents <= 2400 or not 0 <= kind <= 7 or frequency <= 0 or q <= 0:
                raise ValueError('Invalid pitch voice parameters')

    def _selected(self):
        mask = (4 if self.channels == 1 else 3)
        selection = (mask, 4, 3, 7, 0x33, 0x37, 1)[self.mode]
        return [bool(selection & (4 if self.channels == 1 else 1 << channel)) for channel in range(self.channels)]

    def _new_filter(self, voice):
        _, _, _, kind, gain, frequency, q = voice
        mapped = {0: 0, 1: 4, 2: 6, 3: 5, 4: 0, 5: 1, 6: 2, 7: 3}[kind]
        parameters = struct.pack('<IfffB', mapped, gain, frequency, q, bool(kind))
        parameters += struct.pack('<IfffB', 6, 0, 1000, 1, 0)*2+struct.pack('<fB', 0, 0)
        return Equalizer(parameters, channels=self.channels)

    def _initialize(self, reset_dry=True):
        self._validate()
        self.selected = self._selected()
        window, synthesis = _window(self.size)
        self.voice_processors = []
        self.filters = []
        for voice in self.voices:
            ratio = np.float32(2**(voice[1]*float(np.float32(1/1200))))
            self.voice_processors.append([_VoiceChannel(self.size, ratio, window, synthesis) for _ in range(self.channels)] if voice[0] else None)
            self.filters.append(self._new_filter(voice))
        if reset_dry or not hasattr(self, 'dry_delay'):
            self.dry_delay = np.zeros((self.size, self.channels), dtype=np.float32)
            self.dry_position = 0
        if not self._ready:
            self.previous_dry = self._gain(self.dry_db)
            self.previous_wet = self._gain(self.wet_db)
            self.previous_voice = [self._gain(v[2]) for v in self.voices]

    @staticmethod
    def _gain(db):
        return np.float32(10**(db*float(np.float32(.05))))

    def reset(self):
        self._initialize()

    def set_parameter(self, parameter_id, value):
        if not 0 <= parameter_id <= 19 or not math.isfinite(value):
            raise ValueError('Invalid pitch parameter')
        before = (self.mode, self.process_lfe, self.align_dry, self.dry_db, self.wet_db, self.size, [v.copy() for v in self.voices])
        value = float(np.float32(value))
        if parameter_id < 6:
            name = ('mode', 'process_lfe', 'align_dry', 'dry_db', 'wet_db', 'size')[parameter_id]
            setattr(self, name, int(value) if parameter_id in (0, 5) else (int(value != 0) if parameter_id in (1, 2) else value))
        else:
            voice_index, field = (0, parameter_id-6) if parameter_id < 13 else (1, parameter_id-13)
            self.voices[voice_index][field] = int(value != 0) if field == 0 else (int(value) if field == 3 else value)
        try:
            self._validate()
        except ValueError:
            self.mode, self.process_lfe, self.align_dry, self.dry_db, self.wet_db, self.size, self.voices = before
            raise
        if not self._ready:
            return
        if parameter_id in (0, 1, 5, 6, 7, 13, 14):
            self._initialize(reset_dry=parameter_id not in (7, 14))
        elif parameter_id == 2:
            self.dry_delay.fill(0)
            self.dry_position = 0
        elif parameter_id in (9, 10, 11, 12, 16, 17, 18, 19):
            index = 0 if parameter_id < 13 else 1
            voice = self.voices[index]
            mapped = {0: 0, 1: 4, 2: 6, 3: 5, 4: 0, 5: 1, 6: 2, 7: 3}[voice[3]]
            for identity, setting in enumerate((mapped, voice[4], voice[5], voice[6], int(bool(voice[3])))):
                self.filters[index].set_parameter(identity, setting)

    def process(self, audio):
        audio = np.asarray(audio, dtype=np.float32)
        if audio.shape != (128, self.channels) or not np.isfinite(audio).all():
            raise ValueError('Pitch processes finite 128-frame audio quanta')
        dry = audio.copy()
        wet = np.zeros_like(dry)
        for index, processors in enumerate(self.voice_processors):
            if processors is None:
                continue
            voice = np.zeros_like(dry)
            for channel, processor in enumerate(processors):
                if self.selected[channel]:
                    voice[:, channel] = processor.process(audio[:, channel].copy())
            voice = self.filters[index].process(voice)
            _mix(wet, voice, 1, 1, self.previous_voice[index], self._gain(self.voices[index][2]))
        if self.mode == 6 and self.channels == 2:
            wet[:, 1] = wet[:, 0]
        if self.align_dry and any(v[0] for v in self.voices) and any(self.selected):
            count = len(dry)
            first = min(count, self.size-self.dry_position)
            delayed = np.concatenate((self.dry_delay[self.dry_position:self.dry_position+first], self.dry_delay[:count-first]))
            self.dry_delay[self.dry_position:self.dry_position+first] = dry[:first]
            self.dry_delay[:count-first] = dry[first:]
            self.dry_position = (self.dry_position+count) % self.size
            dry = delayed
        _mix(dry, wet, self.previous_dry, self._gain(self.dry_db), self.previous_wet, self._gain(self.wet_db))
        self.previous_dry, self.previous_wet = self._gain(self.dry_db), self._gain(self.wet_db)
        self.previous_voice = [self._gain(v[2]) for v in self.voices]
        return dry

    def rtpc_updates(self):
        return []


def make_effect(plugin_id, parameters, sample_rate=48000, channels=1, initial_parameters=None):
    if plugin_id != Pitch.plugin_id:
        raise ValueError("Unsupported pitch family")
    return Pitch(parameters, sample_rate, channels, initial_parameters)
