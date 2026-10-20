"""Independent source reconstruction of amplifier EQ compression path 1."""
import math

import numpy as np

from . import kernels


_CURVE = (1., 2.2387, 2.0893, 1.4791, 1.0233, .7674, .5957, .4732,
          .3936, .335, .2884, .2512, .2239, .1995, .1841, .1679,
          .1585, .1496, .1334, .1259, .1259)
_NORMALIZATION_DB = (-8., -7., -6., -6., -6., -6., -6., -5., -2., 0.)
_TONE_FREQUENCIES = ((150., 100., 17500.), (300., 100., 20000.),
                     (300., 300., 10000.), (300., 150., 12000.),
                     (200., 100., 14000.), (300., 150., 16000.),
                     (400., 200., 18000.), (1000., 100., 20000.),
                     (2000., 200., 20000.), (1500., 150., 20000.))


def _one_pole(sample_rate, frequency, highpass=False):
    normalized = min(.4583333333333333, max(.00020833333333333333335, frequency/sample_rate))
    tangent = math.tan(normalized*math.pi)
    inverse = 1/(1+tangent)
    if highpass:
        return inverse, -inverse, 0., (tangent-1)*inverse, 0.
    return inverse*tangent, inverse*tangent, (tangent-1)*inverse


class AmpCompression:
    def __init__(self, mode, drive, tone, asymmetry, sample_rate=48000, channels=1):
        if channels not in (1, 2) or not 8000 <= sample_rate <= 192000:
            raise ValueError('Unsupported amplifier compression audio format')
        self.sample_rate, self.channels = sample_rate, channels
        self.state = np.zeros((channels, 0x498//4), dtype=np.float32)
        self.configure(mode, drive, tone, asymmetry)

    def configure(self, mode, drive, tone, asymmetry):
        if not isinstance(mode, (int, np.integer)) or not 0 <= mode < 10:
            raise NotImplementedError('Amplifier compression mode is not reconstructed')
        if not all(math.isfinite(v) and 0 <= v <= 100 for v in (drive, tone, asymmetry)):
            raise ValueError('Amplifier compression controls must lie between 0 and 100')
        drive, tone, asymmetry = map(float, np.asarray((drive, tone, asymmetry), dtype=np.float32))
        d = drive*.01
        threshold = 10**-2.4000000000000004
        exponent = 1/(1+9*d)-1
        table = np.array([(1+(n/256)*(1/threshold))**exponent for n in range(256)], dtype=np.float32)
        location = d*20
        index = int(location)
        curve = _CURVE[index]
        if index < 20:
            curve += (location-index)*(_CURVE[index+1]-curve)
        power = (1/threshold)**exponent
        makeup = 10**((20*math.log10(curve*(1+d*(1/power-1)))+_NORMALIZATION_DB[mode]*d)*.05)
        shaped = math.sqrt(d) if d > 0 else d
        if mode == 0:
            release_ms, attack_ms = shaped*7.800000000000001+4.35, .85-shaped*.5
        elif mode == 1:
            release_ms, attack_ms = shaped*17.1+1.15, .25-shaped*.15
        elif mode == 2:
            release_ms, attack_ms = 2.35-shaped*.9500000000000002, .35-shaped*.09999999999999998
        elif mode == 3:
            release_ms, attack_ms = .95-shaped*.19999999999999996, .25-shaped*.15
        elif mode == 4:
            release_ms, attack_ms = 8.25-shaped*7.9, .25
        elif mode == 5:
            release_ms, attack_ms = 2.15-shaped*1.9, .5-shaped*.3
        elif mode == 6:
            release_ms = attack_ms = .7-shaped*.5499999999999999
        elif mode == 7:
            release_ms = attack_ms = .35-shaped*.24999999999999997
        elif mode == 8:
            release_ms = attack_ms = .25-shaped*.2
        else:
            release_ms = attack_ms = .1-shaped*.09000000000000001
        attack = min(1., 1/(self.sample_rate*attack_ms*.001))
        release = min(1., 1/(self.sample_rate*release_ms*.001))
        fastest = min(1., 1/(self.sample_rate*.01*.001))
        base, minimum, maximum = _TONE_FREQUENCIES[mode]
        frequency = minimum+((base+(maximum-base)*tone*.01)-minimum)*d
        state = self.state
        state[:, 2] = threshold
        state[:, 3] = 18
        state[:, 4:7] = _one_pole(self.sample_rate, frequency)
        state[:, 7], state[:, 8], state[:, 9] = release, attack, fastest-attack
        state[:, 11] = 0
        state[:, 12:17] = _one_pole(self.sample_rate, 20, highpass=True)
        state[:, 17] = 1
        state[:, 20], state[:, 24], state[:, 27] = 1, 1, makeup
        state[:, 28] = asymmetry*.01*-2
        state[:, 35], state[:, 36], state[:, 37] = 1, 1, 0
        state[:, 38:] = table
        self.mode, self.drive, self.tone, self.asymmetry = int(mode), drive, tone, asymmetry

    def reset(self):
        # The containing amplifier EQ's Reset does not clear subpath histories.
        pass

    def process(self, audio):
        result = np.asarray(audio, dtype=np.float32)
        if result.ndim != 2 or result.shape[1] != self.channels or not np.isfinite(result).all():
            raise ValueError('Compression audio must be finite frames by channels')
        result = result.copy()
        if len(result) and kernels.amp_compression(result, self.state):
            return result
        f = np.float32
        for ch, state in enumerate(self.state):
            for i in range(len(result)):
                source = f(result[i, ch]*state[20])
                envelope = f(min(abs(source), f(1))-state[2])
                envelope = max(envelope, f(0))
                filtered = f(f(f(state[22]*state[5])+f(envelope*state[4]))*f(.5))
                filtered = f(filtered-f(state[23]*state[6]))
                state[21], state[22], state[23] = source, envelope, filtered
                location = f(filtered*f(255))
                index = int(location)
                if not -38 <= index < 255:
                    raise ArithmeticError(f'Compression detector left its state-backed lookup range: {index}')
                fraction = f(float(location)-math.floor(float(location)))
                delta = f(f(state[39+index]*fraction)-f(f(fraction-state[24])*state[38+index]))
                delta = f(delta-state[25])
                coefficient = state[8] if delta < 0 else state[7]
                coefficient = f(f(filtered*state[9])+coefficient)
                gain = f(f(coefficient*delta)+state[25])
                state[25] = gain
                wet = f(f(gain*source)*state[27])
                asymmetric = state[28] if wet < state[11] else f(0)
                wet = f(f(asymmetric*wet)+wet)
                wet = min(f(1), max(f(-1), wet))
                filtered = f(f(state[29]*state[13])+f(state[12]*wet))
                filtered = f(f(state[30]*state[14])+filtered)
                filtered = f(filtered-f(state[31]*state[15]))
                filtered = f(filtered-f(state[32]*state[16]))
                state[30], state[29], state[32], state[31] = state[29], wet, state[31], filtered
                result[i, ch] = f(f(state[37]*source)+f(state[36]*f(filtered*state[35])))
        return result
