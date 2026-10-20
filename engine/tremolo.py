from .runtime import kernel_path
"""Independent tremolo/ring modulation for the current catalog waveforms."""
import math
import struct
import ctypes
from pathlib import Path
import sys

import numpy as np

from .basic import _audio

f = np.float32
_library = None
path = kernel_path('TremoloKernels')
if path.exists():
    _library = ctypes.CDLL(str(path))
    _pointer = ctypes.POINTER(ctypes.c_float)
    _library.ft_tremolo.argtypes = [_pointer, ctypes.c_uint32, ctypes.c_uint32, _pointer, _pointer,
                                   ctypes.c_uint32] + [ctypes.c_float]*8
    _library.ft_tremolo.restype = ctypes.c_int


def _sin_polynomial(value):
    square = f(value*value)
    result = f(f(.008306325)-f(square*f(.00018363654)))
    result = f(f(result*square)-f(.16664828))
    result = f(f(result*square)+f(.9999966))
    return f(result*value)


class Tremolo:
    plugin_id = 0x830003

    def __init__(self, parameters, sample_rate=48000, channels=1, initial_parameters=None):
        if len(parameters) != 38 or sample_rate != 48000 or channels not in (1, 2):
            raise ValueError('Tremolo requires a 38-byte profile and 48kHz mono/stereo')
        self.sample_rate, self.channels = sample_rate, channels
        self.values = list(struct.unpack('<2fI3fI2fBB', parameters))
        for identity, value in (initial_parameters or {}).items():
            self._assign(identity, value)
        self._validate()
        self._initialize()
        self.dirty = False

    def _validate(self):
        if not all(math.isfinite(v) for v in self.values):
            raise ValueError('Nonfinite tremolo parameters')
        depth, rate, waveform, smooth, duty, phase, mode, spread, gain, _, _ = self.values
        if waveform not in (0, 1, 2) or mode != 0:
            raise NotImplementedError('Tremolo waveform or phase allocation is not reconstructed')
        if not 0 <= depth <= 100 or not 0 <= rate < self.sample_rate/2 or not 0 <= smooth <= 100 or not 0 <= duty <= 100:
            raise ValueError('Unsupported tremolo timing or depth')
        if rate == 0 and waveform and smooth:
            raise NotImplementedError('This zero-rate smoothed waveform produces nonfinite reference audio')

    def _initialize(self):
        depth, rate, wave, smooth, duty, phase, mode, spread, gain, _, _ = self.values
        self.depth = f(f(depth)*f(.01))
        self.previous_depth = self.depth
        self.gain = f(10**(gain*float(f(.05))))
        self.previous_gain = self.gain
        self.duty = f(f(duty)*f(.01))
        self.wave = wave
        self.step = f(f(rate)/f(self.sample_rate))
        period = f(2*math.pi) if not wave else f(1)
        if not wave:
            self.step = f(self.step*period)
        phases = [phase] if self.channels == 1 else [phase, f(f(phase)+f(spread))]
        self.phase = np.array([f(f(f(period*f(p))*f(1/360))+f(.25 if wave == 1 else 0)) for p in phases], np.float32)
        self.phase = np.fmod(self.phase, period).astype(np.float32)
        self.smoothed = np.zeros(self.channels, np.float32)
        smoothing = float(f(f(smooth)*f(.01)))
        if not smoothing:
            self.b, self.a = f(1), f(0)
        else:
            cutoff = math.exp(-math.log(self.sample_rate*.5/rate)*smoothing) if rate else 0
            value = 2-math.cos(cutoff*.5*float(f(2*math.pi)))
            pole = math.sqrt(value*value-1)-value
            self.a, self.b = f(pole), f(pole+1)

    def _assign(self, identity, value):
        if not 1 <= identity <= 11 or not math.isfinite(value):
            raise ValueError('Invalid tremolo parameter')
        self.values[identity-1] = int(value) if identity in (3, 7, 10, 11) else float(f(value))

    def set_parameter(self, identity, value):
        candidate = list(self.values)
        self._assign(identity, value)
        try:
            self._validate()
        except (ValueError, NotImplementedError):
            self.values = candidate
            raise
        if identity in (1, 2, 3, 4, 5, 9):
            self.dirty = True
        if identity in (10, 11) and candidate != self.values:
            self.values = candidate
            raise NotImplementedError('Live tremolo channel allocation flags are not yet verified')

    def reset(self):
        # REA bytes at0xf26140 are MOV EAX,1; RET: oscillator history survives.
        pass

    def rtpc_updates(self):
        return []

    def process(self, audio):
        result = _audio(audio, self.channels)
        if len(result) != 128:
            raise ValueError('Tremolo requires 128-frame source quanta')
        period, pi, half_pi = f(2*math.pi), f(math.pi), f(math.pi/2)
        if self.dirty:
            old_wave = self.wave
            phases, smoothed = self.phase.copy(), self.smoothed.copy()
            previous_depth, previous_gain = self.previous_depth, self.previous_gain
            self._initialize()
            self.previous_depth, self.previous_gain = previous_depth, previous_gain
            self.smoothed = smoothed
            self.phase = phases
            if old_wave == 0 and self.wave != 0:
                self.phase = f(self.phase*f(.15915494))
            elif old_wave != 0 and self.wave == 0:
                self.phase = f(self.phase*f(2*math.pi))
            self.step = f(f(self.values[1])*f(1/self.sample_rate))
            if not self.wave:
                self.step = f(self.step*period)
            self.dirty = False
        step = max(self.step, f(1e-8))
        if _library is not None:
            status = _library.ft_tremolo(result.ctypes.data_as(_pointer), len(result), self.channels,
                                self.phase.ctypes.data_as(_pointer), self.smoothed.ctypes.data_as(_pointer), self.wave,
                                self.step, self.b, self.a, self.duty, self.previous_depth, self.depth,
                                self.previous_gain, self.gain)
            if not status:
                raise RuntimeError('Tremolo kernel rejected the audio format')
            self.previous_depth, self.previous_gain = self.depth, self.gain
            return result
        depth_step = f(f(self.depth-self.previous_depth)/f(len(result)))
        gain_step = f(f(self.gain-self.previous_gain)/f(len(result)))
        for channel in range(self.channels):
            phase, smoothed = self.phase[channel], self.smoothed[channel]
            depth, gain = self.previous_depth, self.gain
            inverse = f(f(1)/step)
            boundaries = (half_pi, pi, f(pi+half_pi), period) if not self.wave else (f(.5) if self.wave == 1 else self.duty, f(1))
            i = 0
            while i < len(result):
                for section, boundary in enumerate(boundaries):
                    count = min(len(result)-i, max(0, math.ceil((float(boundary)-float(phase))*float(inverse))))
                    for _ in range(count):
                        depth, gain = f(depth+depth_step), f(gain+gain_step)
                        phase = f(phase+step)
                        if self.wave == 0:
                            angle = phase if section == 0 else f(pi-phase) if section == 1 else f(phase-pi) if section == 2 else f(period-phase)
                            value = _sin_polynomial(angle)
                            if section >= 2:
                                value = -value
                            wave = f(f(value+f(1))*f(.5))
                            level = f(f(wave*depth)+f(f(1)-depth))
                        else:
                            wave = (f(phase*f(2)) if section == 0 else f(f(f(1)-phase)*f(2))) if self.wave == 1 else f(section == 0)
                            smoothed = f(f(f(wave*depth)*self.b)-f(self.a*smoothed))
                            level = f(f(f(1)-depth)+smoothed)
                        result[i, channel] = f(f(level*gain)*result[i, channel])
                        i += 1
                if phase >= (period if not self.wave else f(1)):
                    phase = f(phase-(period if not self.wave else f(1)))
            if self.step:
                self.phase[channel], self.smoothed[channel] = phase, smoothed
        self.previous_depth, self.previous_gain = self.depth, self.gain
        return result
