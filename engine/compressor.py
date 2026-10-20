"""Independent RMS compressor, REA 0xe82550/0xe82850."""
import numpy as np

from .basic import Gate, _audio, _fast_db, _fast_pow10, _gain_ramp
from . import kernels


class Compressor(Gate):
    plugin_id = 0x6c0003

    def process(self, audio):
        result = _audio(audio, self.channels)
        if not len(result):
            return result
        f = np.float32
        attack, release = self._coefficient(self.attack), self._coefficient(self.release)
        if kernels.compressor(self, result, attack, release):
            gain = f(10**(self.gain*float(f(.05))))
            _gain_ramp(result, self.previous_gain, gain)
            self.previous_gain = gain
            return result
        ratio = f(f(1)/f(self.ratio)-f(1))
        for i, frame in enumerate(result):
            squared = f(frame*frame)
            if self.active_linked:
                summed = f(0)
                for value in squared:
                    summed = f(summed+value)
                powers = (f(f(summed*f(1/self.channels))+f(1e-25)),)
            else:
                powers = f(squared+f(1e-25))
            levels = np.empty(self.groups, dtype=np.float32)
            for group, power in enumerate(powers):
                self.power[group] = f(f(f(self.power[group]-power)*self.power_coefficient)+power)
                over = f(max(_fast_db(self.power[group])*.5-self.threshold, 0))
                coefficient = attack if over >= self.reduction[group] else release
                self.reduction[group] = f(f(f(self.reduction[group]-over)*coefficient)+over)
                exponent = f(f(self.reduction[group]*ratio)*f(.05))
                levels[group] = _fast_pow10(exponent)
            result[i] = f(frame*(levels[0] if self.active_linked else levels))
        gain = f(10**(self.gain*float(f(.05))))
        _gain_ramp(result, self.previous_gain, gain)
        self.previous_gain = gain
        return result
