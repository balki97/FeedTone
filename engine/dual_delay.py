"""Independent Wwise paired-ring delay (0x870003), reconstructed with REA."""
import math
import struct

import numpy as np

from .filter import _Biquad, _coefficients

f = np.float32


def _ramp(start, end):
    if start == end:
        return np.full(128, start, np.float32)
    step = f(f(end-start)/f(128))
    values = np.empty(128, np.float32)
    lanes = np.empty(4, np.float32)
    lanes[0] = start
    for i in range(1, 4):
        lanes[i] = f(lanes[i-1]+step)
    advance = f(step*f(4))
    for i in range(0, 128, 4):
        values[i:i+4] = lanes
        lanes = f(lanes+advance)
    return values


def _mix_ramp(start, end):
    if start == end:
        return np.full(128, start, np.float32)
    step = f(f(end-start)/f(128))
    values = np.empty(128, np.float32)
    current = start
    for i in range(0, 128, 4):
        values[i] = current
        values[i+1] = f(current+step)
        values[i+2] = f(values[i+1]+step)
        values[i+3] = f(values[i+2]+step)
        current = f(values[i+3]+step)
    return values


class DualDelay:
    plugin_id = 0x870003
    _indices = {2: 12, 3: 13, 4: 14, 5: 8, 6: 9, 7: 10, 8: 11,
                9: 6, 10: 0, 11: 1, 12: 2, 13: 7, 14: 3, 15: 4, 16: 5}

    def __init__(self, parameters, sample_rate=48000, channels=1, initial_parameters=None):
        if len(parameters) != 62 or sample_rate != 48000 or channels not in (1, 2):
            raise ValueError('Dual delay requires 62 bytes and 48 kHz mono/stereo')
        words = list(struct.unpack('<I3fI3fI6f2B', parameters))
        self.channels, self.sample_rate = channels, sample_rate
        self.values = [words[i] for i in (1, 2, 3, 5, 6, 7, 0, 4, 8, 9, 10, 11, 12, 13, 14)]
        self.feedback, self.cross = words[15:17]
        self._validate()
        for identity, value in (initial_parameters or {}).items():
            self.set_parameter(identity, value)
        self.current = self._converted()
        self.previous = self.current.copy()
        self.filters = [_Biquad(1), _Biquad(1)]
        self._resize()
        self.dirty = set()
        self.filter_dirty = True

    def _validate(self):
        if not all(math.isfinite(v) for v in self.values):
            raise ValueError('Dual delay requires finite parameters')
        for i in (0, 3):
            if not 0 <= self.values[i] <= 10:
                raise ValueError('Delay seconds must be in 0..10')
        for i in (6, 7):
            if self.values[i] != int(self.values[i]) or not 0 <= self.values[i] <= 3:
                raise ValueError('Unsupported delay input selection')
        if self.values[8] != int(self.values[8]) or not 0 <= self.values[8] <= 7:
            raise ValueError('Unsupported delay filter')
        # The source curve's approximate power function can return 19.9886 Hz at the 20 Hz endpoint.
        if not 1 <= self.values[10] <= 20000 or not .1 <= self.values[11] <= 20:
            raise ValueError('Invalid delay filter frequency/Q')
        if self.feedback not in (0, 1) or self.cross not in (0, 1):
            raise ValueError('Invalid delay feedback switches')
        for i in (1, 2, 4, 5, 12, 13):
            if not -200 <= self.values[i] <= 24:
                raise ValueError('Invalid delay gain')
        if not -100 <= self.values[14] <= 100 or not -96 <= self.values[9] <= 96:
            raise ValueError('Invalid delay filter gain/balance')

    def set_parameter(self, identity, value):
        if identity not in (0, 1) and identity not in self._indices:
            raise ValueError('Unknown dual delay parameter')
        if not math.isfinite(value):
            raise ValueError('Dual delay parameters must be finite')
        old_values, old_flags = self.values.copy(), (self.feedback, self.cross)
        if identity == 0:
            self.cross = int(value != 0)
        elif identity == 1:
            self.feedback = int(value != 0)
        else:
            self.values[self._indices[identity]] = float(f(value))
        try:
            self._validate()
        except ValueError:
            self.values, (self.feedback, self.cross) = old_values, old_flags
            raise
        if hasattr(self, 'dirty'):
            self.dirty.add(identity)

    def _converted(self):
        values = np.array(self.values, np.float32)
        for i in (1, 2, 4, 5, 12, 13):
            values[i] = f(math.pow(10, float(values[i])*float(f(.05))))
        if not self.feedback:
            values[[1, 4]] = 0
        if not self.cross:
            values[[2, 5]] = 0
        values[[0, 3]] = np.maximum(values[[0, 3]], f(128/self.sample_rate))
        return values

    def _resize(self):
        self.rings = [np.zeros((math.floor(float(self.current[i])*self.sample_rate)+3)&~3, np.float32)
                      for i in (0, 3)]
        self.positions = [0, 0]
        for effect in self.filters:
            effect.state.fill(0)

    def reset(self):
        for ring in self.rings:
            ring.fill(0)
        self.positions = [0, 0]
        for effect in self.filters:
            effect.state.fill(0)

    @staticmethod
    def _select(audio, side, selection):
        if selection in (0, 2):
            return audio[:, min(side, audio.shape[1]-1)].copy()
        if selection == 1:
            return audio[:, min(side, audio.shape[1]-1)].copy()
        return np.zeros(128, np.float32)

    def process(self, audio):
        audio = np.asarray(audio, np.float32)
        if audio.shape != (128, self.channels) or not np.isfinite(audio).all():
            raise ValueError('Dual delay requires 128 finite frames')
        self.current = self._converted()
        if self.dirty & {10, 14}:
            self._resize()
        if self.dirty & {5, 6, 7, 8}:
            self.filter_dirty = True
        self.dirty.clear()
        old, new = self.previous, self.current
        read = []
        indices = []
        for ring, position in zip(self.rings, self.positions):
            index = (position+np.arange(128)) % len(ring)
            indices.append(index)
            read.append(ring[index].copy())
        incoming = [self._select(audio, side, int(new[6+side])) for side in (0, 1)]
        feedback = [_ramp(old[i], new[i]) for i in (1, 4)]
        cross = [_ramp(old[i], new[i]) for i in (2, 5)]
        write = [f(f(cross[1]*read[1]+incoming[0])+f(feedback[0]*read[0])),
                 f(f(cross[0]*read[0]+incoming[1])+f(feedback[1]*read[1]))]
        if int(new[8]):
            if self.filter_dirty:
                coefficients = _coefficients(int(new[8])-1, float(new[9]), float(new[10]), float(new[11]), self.sample_rate)
                for effect in self.filters:
                    effect.configure(coefficients)
            write = [effect.process(samples[:, None])[:, 0] for effect, samples in zip(self.filters, write)]
        self.filter_dirty = False
        for side in (0, 1):
            self.rings[side][indices[side]] = write[side]
            self.positions[side] = (self.positions[side]+128) % len(self.rings[side])
        dry, wet = _mix_ramp(old[12], new[12]), _mix_ramp(old[13], new[13])
        if self.channels == 1:
            result = f(f(f(audio[:, 0]*dry)+f(read[0]*wet))+f(read[1]*wet))[:, None]
        else:
            result = f(f(audio*dry[:, None])+f(np.column_stack(read)*wet[:, None]))
        self.previous = new.copy()
        if not np.isfinite(result).all():
            raise ValueError('Independent dual delay produced nonfinite audio')
        return result

    def rtpc_updates(self):
        return []
