from .runtime import kernel_path
"""Independent current-catalog Wwise chorus/flanger reconstruction."""
import ctypes
from functools import lru_cache
import math
from pathlib import Path
import struct

import numpy as np

f = np.float32


class _Channel(ctypes.Structure):
    _fields_ = [('position', ctypes.c_uint32)] + [(name, ctypes.c_float) for name in
               ('feedback', 'forward', 'direct', 'phase', 'smooth')]


@lru_cache(maxsize=1)
def _kernel():
    path = kernel_path('ChorusKernels')
    if not path.is_file():
        raise RuntimeError('Independent ChorusKernels.dll is unavailable')
    library = ctypes.CDLL(str(path))
    pointer = ctypes.POINTER(ctypes.c_float)
    library.ft_chorus.argtypes = [pointer, pointer, ctypes.POINTER(_Channel)] + [ctypes.c_uint32]*4 + [ctypes.c_float]*7 + [ctypes.c_uint32] + [ctypes.c_float]*2 + [ctypes.c_uint32] + [ctypes.c_float]*4
    library.ft_chorus.restype = ctypes.c_int
    return library


class Chorus:
    plugin_id = 0x7d0003
    _format = '<6fI3fI3f3B'
    _ids = {0: 0, 1: 13, 2: 16, 5: 1, 6: 2, 7: 3, 8: 6, 9: 5, 10: 4,
            14: 14, 16: 12, 17: 15, 18: 7, 19: 8, 20: 9, 21: 10, 22: 11}

    def __init__(self, parameters, sample_rate=48000, channels=1, initial_parameters=None):
        if len(parameters) != 59 or sample_rate != 48000 or channels not in (1, 2):
            raise ValueError('Chorus requires 59 bytes, 48 kHz mono/stereo')
        self.values = list(struct.unpack(self._format, parameters))
        for identity, value in (initial_parameters or {}).items():
            self._assign(identity, value)
        self._validate()
        self.channels, self.sample_rate = channels, sample_rate
        self.library = _kernel()
        self.states = [_Channel() for _ in range(channels)]
        self._configure(initial=True)
        self.previous = self.values.copy()
        self.dirty = False

    def _assign(self, identity, value):
        if identity not in self._ids or not math.isfinite(value):
            raise ValueError('Invalid chorus parameter')
        index = self._ids[identity]
        self.values[index] = int(value) if index in (6, 10, 14, 15, 16) else float(f(value))

    def _validate(self):
        if not all(math.isfinite(v) for v in self.values):
            raise ValueError('Nonfinite chorus parameters')
        delay, direct, forward, feedback, depth, rate, wave, smooth, duty, phase, mode, spread, gain, mix, enabled, center, lfe = self.values
        if not 0 <= delay <= 1000 or not 0 <= depth <= 100 or not 0 <= rate < 24000:
            raise ValueError('Unsupported chorus delay, depth or rate')
        if not 0 <= smooth <= 100 or not 0 <= duty <= 100 or not 0 <= mix <= 100:
            raise ValueError('Unsupported chorus modulation or mix')
        if wave not in (0, 1, 2) or mode not in (0, 1, 2):
            raise NotImplementedError('Unverified chorus waveform/phase allocation')
        if any(v not in (0, 1) for v in (enabled, center, lfe)):
            raise ValueError('Chorus flags must be booleans')
        if not all(-1 <= v <= 1 for v in (direct, forward, feedback)) or not -60 <= gain <= 24:
            raise ValueError('Unsupported chorus gain')
        if wave and smooth and rate == 0:
            raise NotImplementedError('Zero-rate smoothed waveform is unverified')

    @staticmethod
    def _fraction(value):
        return f(f(value)*f(.01))

    @staticmethod
    def _gain(value):
        return f(10**(value*float(f(.05))))

    def _configure(self, initial=False):
        v = self.values
        delay = (max(8, int(v[0]*float(f(.001))*48000))+3) & ~3
        rebuild = initial or v[0] != self.previous[0]
        allocate_lfo = initial or v[14] != self.previous[14]
        if rebuild:
            self.delay, self.length = delay, delay*2+1024
            self.rings = [np.zeros(self.length, np.float32) for _ in range(self.channels)]
            for state in self.states:
                state.position = 0
                state.feedback, state.forward, state.direct = v[3], v[2], v[1]
        self.depth = self._fraction(v[4]) if v[14] else f(0)
        self.extent = min(12288, int(float(self.depth)*delay) & ~3)
        if self.extent >= delay:
            self.extent -= 4
        old_wave = getattr(self, 'wave', v[6])
        self.wave = v[6]
        period = f(2*math.pi) if self.wave == 0 else f(1)
        self.step = f(f(v[5])/f(48000)) if initial or allocate_lfo else f(f(v[5])*f(1/48000))
        if self.wave == 0:
            self.step = f(self.step*period)
        smoothing = float(self._fraction(v[7]))
        if not smoothing:
            self.a, self.b = f(0), f(1)
        else:
            cutoff = math.exp(-math.log(24000/v[5])*smoothing) if v[5] else 0
            k = 2-math.cos(cutoff*.5*float(f(2*math.pi)))
            pole = math.sqrt(k*k-1)-k
            self.a, self.b = f(pole), f(pole+1)
        for channel, state in enumerate(self.states):
            if allocate_lfo:
                angle = f(v[9]+(v[11] if channel and v[10] in (0, 2) else 0))
                phase = f(f(f(period*angle)*f(1/360))+f(.25 if self.wave == 1 else 0))
                state.phase, state.smooth = float(f(np.fmod(phase, period))), 0
            elif old_wave != self.wave:
                state.phase = f(f(state.phase)*f(.15915494 if old_wave == 0 else 2*math.pi)) if old_wave == 0 or self.wave == 0 else state.phase
        self.duty = self._fraction(v[8])

    @property
    def parameters(self):
        return struct.pack(self._format, *self.values)

    def set_parameter(self, identity, value):
        old = self.values.copy()
        self._assign(identity, value)
        try:
            self._validate()
        except (ValueError, NotImplementedError):
            self.values = old
            raise
        if identity not in (20, 21, 22):
            self.dirty = True

    def reset(self):
        for state, ring in zip(self.states, self.rings):
            state.position = 0
            ring.fill(0)

    def rtpc_updates(self):
        return []

    def process(self, audio):
        array = np.asarray(audio, np.float32)
        if array.shape != (128, self.channels) or not np.isfinite(array).all():
            raise ValueError('Chorus expects 128 finite frames per configured channel')
        if self.dirty:
            self._configure()
            self.dirty = False
        previous_depth = self._fraction(self.previous[4]) if self.previous[14] else f(0)
        old_gain, gain = self._gain(self.previous[12]), self._gain(self.values[12])
        old_dry = f(f(100-self.previous[13])*f(.01))
        dry = f(f(100-self.values[13])*f(.01))
        output = np.empty_like(array)
        pointer = ctypes.POINTER(ctypes.c_float)
        for channel, (state, ring) in enumerate(zip(self.states, self.rings)):
            block = np.array(array[:, channel], dtype=np.float32, copy=True, order='C')
            status = self.library.ft_chorus(block.ctypes.data_as(pointer), ring.ctypes.data_as(pointer), ctypes.byref(state),
                128, self.length, self.delay, self.extent, self.values[3], self.values[2], self.values[1],
                self.step, self.b, self.a, self.duty, self.wave, previous_depth, self.depth, self.values[14],
                f(old_gain*f(1-old_dry)), f(gain*f(1-dry)), f(old_gain*old_dry), f(gain*dry))
            if status != 1:
                raise RuntimeError('Independent chorus kernel rejected audio')
            output[:, channel] = block
        self.previous = self.values.copy()
        return output
