"""Independent two-head, triangular-crossfade delay pitch shifter (0x880003)."""
import ctypes
import math
import struct

import numpy as np

from .pitch import Pitch, _check, _library, _mix, _pointer


class MultiPitch:
    plugin_id = 0x880003

    def __init__(self, parameters, sample_rate=48000, channels=1, initial_parameters=None):
        if _library is None or not hasattr(_library, 'ft_multipitch'):
            raise RuntimeError('Build independent PitchKernels.dll with delay pitch support')
        if len(parameters) != 38 or sample_rate != 48000 or channels not in (1, 2):
            raise ValueError('Delay pitch requires 38-byte parameters and 48kHz mono/stereo')
        self.sample_rate, self.channels = sample_rate, channels
        self.mode, self.dry_db, self.wet_db, self.delay_ms, self.process_lfe, self.align_dry, self.cents, self.kind, self.filter_gain, self.frequency, self.q = struct.unpack('<I3fBBfI3f', parameters)
        self._ready = False
        self._validate()
        for identity, value in (initial_parameters or {}).items():
            self.set_parameter(identity, value)
        self._initialize()
        self.previous_dry, self.previous_wet = Pitch._gain(self.dry_db), Pitch._gain(self.wet_db)
        self._ready = True

    def _validate(self):
        if not all(math.isfinite(v) for v in (self.mode, self.dry_db, self.wet_db, self.delay_ms, self.cents, self.filter_gain, self.frequency, self.q)):
            raise ValueError('Delay pitch parameters must be finite')
        if not 0 <= self.mode <= 5 or not 1 <= self.delay_ms <= 1000 or not -2400 <= self.cents <= 2400 or not 0 <= self.kind <= 7 or self.frequency <= 0 or self.q <= 0:
            raise ValueError('Delay pitch parameter out of supported range')

    def _initialize(self):
        length = math.floor(float(np.float32(np.float32(self.sample_rate*self.delay_ms)*np.float32(.001))))
        self.size = (length+3)&~3
        self.ring = np.zeros((self.channels, self.size), dtype=np.float32)
        self.phase = np.zeros(self.channels, dtype=np.float32)
        self.position = np.zeros(self.channels, dtype=np.uint32)
        self.mode = int(self.mode)
        self.selected = Pitch._selected(self)
        self.filter = Pitch._new_filter(self, (True, 0, 0, self.kind, self.filter_gain, self.frequency, self.q))
        self._configure_speed()
        self._initialize_dry()

    def _configure_speed(self):
        ratio = np.float32(2**(self.cents*float(np.float32(1/1200))))
        self.speed = np.float32(1-ratio)
        if ratio == 1:
            self.phase.fill(0)

    def _initialize_dry(self):
        duration = np.float32(self.delay_ms*np.float32(.001)) if self._ready else np.float32(np.float32(self.sample_rate*self.delay_ms)*np.float32(.001))
        frames = round(float(np.float32(duration*self.sample_rate))) if self._ready else round(float(duration))
        self.dry_delay = np.zeros((frames//2, self.channels), dtype=np.float32)
        self.dry_position = 0

    def reset(self):
        self.ring.fill(0)
        self.position.fill(0)
        self.filter.reset()
        self.dry_delay.fill(0)
        self.dry_position = 0

    def set_parameter(self, identity, value):
        if not 0 <= identity <= 10 or not math.isfinite(value):
            raise ValueError('Invalid delay pitch control')
        names = ('mode', 'process_lfe', 'align_dry', 'dry_db', 'wet_db', 'delay_ms', 'cents', 'kind', 'filter_gain', 'frequency', 'q')
        name = names[identity]
        before = getattr(self, name)
        value = float(np.float32(value))
        if identity in (1, 2):
            value = int(value != 0)
        elif identity in (0, 7):
            value = int(value)
        setattr(self, name, value)
        try:
            self._validate()
        except ValueError:
            setattr(self, name, before)
            raise
        if not self._ready:
            return
        if identity in (0, 1, 5):
            self._initialize()
        elif identity == 2:
            self._initialize_dry()
        elif identity == 6:
            self._configure_speed()
        elif identity >= 7:
            mapped = {0: 0, 1: 4, 2: 6, 3: 5, 4: 0, 5: 1, 6: 2, 7: 3}[self.kind]
            for control, setting in enumerate((mapped, self.filter_gain, self.frequency, self.q, bool(self.kind))):
                self.filter.set_parameter(control, setting)

    def process(self, audio):
        audio = np.asarray(audio, dtype=np.float32)
        if audio.shape != (128, self.channels) or not np.isfinite(audio).all():
            raise ValueError('Delay pitch requires finite 128-frame buffers')
        dry = audio.copy()
        wet = np.zeros_like(dry)
        mask = sum((1 << i) for i, selected in enumerate(self.selected) if selected)
        _check(_library.ft_multipitch(_pointer(dry), _pointer(wet), len(dry), self.channels, mask,
                                     _pointer(self.ring), self.size, _pointer(self.phase),
                                     self.position.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)), self.speed))
        wet = self.filter.process(wet)
        if self.align_dry:
            # Preserve all original channel histories, including channels excluded from wet processing.
            count, capacity = len(dry), len(self.dry_delay)
            delayed = np.empty_like(dry)
            used = 0
            while used < count:
                take = min(count-used, capacity-self.dry_position)
                delayed[used:used+take] = self.dry_delay[self.dry_position:self.dry_position+take]
                self.dry_delay[self.dry_position:self.dry_position+take] = dry[used:used+take]
                self.dry_position = (self.dry_position+take)%capacity
                used += take
            dry = delayed
        _mix(dry, wet, self.previous_dry, Pitch._gain(self.dry_db), self.previous_wet, Pitch._gain(self.wet_db))
        self.previous_dry, self.previous_wet = Pitch._gain(self.dry_db), Pitch._gain(self.wet_db)
        return dry

    def rtpc_updates(self):
        return []


def make_effect(plugin_id, parameters, sample_rate=48000, channels=1, initial_parameters=None):
    if plugin_id != MultiPitch.plugin_id:
        raise ValueError('Unsupported delay pitch family')
    return MultiPitch(parameters, sample_rate, channels, initial_parameters)

