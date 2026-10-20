from .runtime import kernel_path
"""Independent six-band filter/waveshaper (0x7e0003), reconstructed with REA.

This source uses observed equations; it loads no original executable bytes.
Numerical accuracy and unsupported boundaries are documented in research/FILTER.md.
"""
import ctypes
import math
import os
from pathlib import Path
import struct
import sys

import numpy as np

from .basic import _audio, _fast_pow10

f = np.float32
_F32 = ctypes.POINTER(ctypes.c_float)
_library = None
_path = kernel_path('FilterKernels')
if _path.is_file() and os.environ.get('FEEDBACK_FILTER_PYTHON_ONLY') != '1':
    _library = ctypes.CDLL(str(_path))
    _library.ft_filter_abi.argtypes = []
    _library.ft_filter_abi.restype = ctypes.c_uint32
    if _library.ft_filter_abi() != 1:
        raise RuntimeError('Independent filter kernel ABI mismatch')
    _library.ft_filter_biquad.argtypes = [_F32, ctypes.c_uint32, _F32, _F32]
    _library.ft_filter_shape.argtypes = [_F32, ctypes.c_uint32, _F32]
    _library.ft_filter_mix_dc.argtypes = [_F32, _F32, _F32, ctypes.c_uint32, _F32, _F32]
    for _name in ('ft_filter_biquad', 'ft_filter_shape', 'ft_filter_mix_dc'):
        getattr(_library, _name).restype = ctypes.c_int


def _pointer(array):
    if array.dtype != np.float32 or not array.flags.c_contiguous:
        raise ValueError('Filter kernel requires contiguous float32 arrays')
    return array.ctypes.data_as(_F32)


def _checked(value):
    if value != 1:
        raise RuntimeError('Independent filter kernel rejected its input')


def _fast_exp(value, scale=12102203.0):
    if value < -37:
        return f(0)
    encoded = float(value) * scale + 1065353216
    bits = 0 if encoded >= 2**63 else int(encoded) & 0xffffffff
    mantissa = f(struct.unpack('<f', struct.pack('<I', (bits & 0x7fffff) + 0x3f800000))[0])
    power = f(struct.unpack('<f', struct.pack('<I', bits & 0xff800000))[0])
    return f(f(f(f(f(mantissa*f(.32518977))+f(.020805772))*mantissa)+f(.65304345))*power)


def _coefficients(kind, gain, frequency, q, sample_rate):
    frequency = min(frequency, float(f(f(sample_rate)*f(.5)*f(.9))))
    angle = frequency * float(f(2*math.pi)) / sample_rate
    if kind in (3, 4):
        tangent = math.tan(frequency*float(f(math.pi))/sample_rate)
        k = f(1/tangent) if kind == 3 else f(tangent)
        square = f(k*k)
        summed, root = f(square+f(1)), f(k*f(math.sqrt(2)))
        b0 = f(f(1)/f(summed+root))
        b1, b2, a0 = f(b0*f(2 if kind == 3 else -2)), b0, f(1)
        a1 = f(f(f(1)-square)*f(b0*f(2))) if kind == 3 else f(-f(f(square-f(1))*f(b0*f(-2))))
        a2 = f(f(summed-root)*b0)
    elif kind in (5, 6):
        alpha = math.sin(angle)/(q+q)
        a0, a1, a2 = f(1+alpha), f(-2*math.cos(angle)), f(1-alpha)
        b0, b1, b2 = (f(alpha), f(0), f(-alpha)) if kind == 5 else (f(1), a1, f(1))
    else:
        amplitude = _fast_pow10(f(f(gain)*f(.025)))
        cosine = f(math.cos(angle))
        if kind == 1:
            alpha = f(math.sin(angle)/(q+q))
            plus, minus = f(alpha*amplitude), f(alpha/amplitude)
            b0, b1, b2 = f(plus+f(1)), f(cosine*f(-2)), f(f(1)-plus)
            a0, a1, a2 = f(minus+f(1)), b1, f(f(1)-minus)
        else:
            plus, minus = f(amplitude+f(1)), f(amplitude-f(1))
            mc, pc = f(minus*cosine), f(plus*cosine)
            alpha = f(math.sqrt(float(amplitude))*math.sin(angle)*math.sqrt(2))
            if kind == 0:
                numerator, denominator = f(plus-mc), f(mc+plus)
                b0, b1, b2 = f(f(numerator+alpha)*amplitude), f(f(f(minus-pc)*amplitude)*f(2)), f(amplitude*f(numerator-alpha))
                a0, a1, a2 = f(denominator+alpha), f(f(pc+minus)*f(-2)), f(denominator-alpha)
            else:
                numerator, denominator = f(mc+plus), f(plus-mc)
                b0, b1, b2 = f(f(numerator+alpha)*amplitude), f(f(f(pc+minus)*amplitude)*f(-2)), f(f(numerator-alpha)*amplitude)
                a0, a1, a2 = f(denominator+alpha), f(f(minus-pc)*f(2)), f(denominator-alpha)
    inverse = f(f(1)/a0)
    return np.array([f(inverse*b0), f(inverse*b1), f(inverse*b2), -f(inverse*a1), -f(inverse*a2)], np.float32)


class _Biquad:
    def __init__(self, channels):
        self.state = np.zeros((channels, 4), np.float32)

    def configure(self, coefficients):
        b0, b1, b2, a1, a2 = coefficients
        v1 = f(f(b0*a1)+b1)
        v2 = f(f(f(v1*a1)+b2)+f(b0*a2))
        t = f(f(b1*a1)+b2)
        u = f(f(t*a1)+f(b1*a2))
        a12 = f(a1*a2)
        square = f(a1*a1)
        b2a12 = f(f(b2*a1)*a1)
        self.matrix = np.array([
            [b0, b0, b0, b0], [0, 0, 0, v1], [0, 0, v1, v2],
            [0, v1, v2, f(f(f(a12*b0)+f(v2*a1))+f(b1*a2))],
            [b1, t, u, f(f(f(u*a1)+f(b2*a2))+f(f(b1*a2)*a1))],
            [b2, f(b2*a1), f(b2a12+f(b2*a2)), f(f(f(f(b2*f(2))*a2)+b2a12)*a1)],
            [a1, f(square+a2), f(f(f(a2*f(2))+square)*a1), f(f(f(f(f(a2*f(3))+square)*a1)*a1)+f(a2*a2))],
            [a2, a12, f(f(a12*a1)+f(a2*a2)), f(f(f(f(a2*f(2))*a2)+f(a12*a1))*a1)]
        ], np.float32)
        self.coefficients = coefficients

    def process(self, audio):
        result = audio.copy()
        if _library is not None:
            _checked(_library.ft_filter_biquad(_pointer(result), audio.shape[1], _pointer(self.matrix), _pointer(self.state)))
            return result
        m = self.matrix
        for channel in range(audio.shape[1]):
            x1, x2, y1, y2 = self.state[channel]
            for offset in range(0, len(audio), 4):
                x = audio[offset:offset+4, channel]
                # Original aligned four-lane SSE evaluation, retaining its sum grouping.
                out = f(f(m[7]*y2)+f(m[6]*y1))
                out = f(out+f(m[1]*x[2]))
                out = f(out+f(f(m[0]*x)+f(f(m[5]*x2)+f(m[4]*x1))))
                out = f(out+f(f(m[3]*x[0])+f(m[2]*x[1])))
                result[offset:offset+4, channel] = out
                x1, x2, y1, y2 = x[3], x[2], out[3], out[2]
            self.state[channel] = x1, x2, y1, y2
        return result


class DynamicFilter:
    plugin_id = 0x7e0003

    def __init__(self, parameters, sample_rate=48000, channels=1, initial_parameters=None):
        if len(parameters) != 126 or sample_rate != 48000 or channels not in (1, 2):
            raise ValueError('Dynamic filter requires 126 bytes, 48 kHz mono or stereo')
        self.channels, self.sample_rate = channels, sample_rate
        self.bands = [list(struct.unpack_from('<IfffB', parameters, i*17)) for i in range(6)]
        self.tail = list(struct.unpack_from('<I5f', parameters, 102))
        self.filters = [_Biquad(channels) for _ in range(6)]
        for identity, value in (initial_parameters or {}).items():
            self._set(int(identity), value)
        self._configure()
        self.previous = self.tail.copy()
        self.reset()

    def _validate(self):
        for kind, gain, frequency, q, enabled in self.bands:
            if kind not in range(7) or not all(math.isfinite(v) for v in (gain, frequency, q)) or not -200 <= gain <= 100 or frequency <= 0 or q <= 0:
                raise ValueError('Invalid dynamic filter band')
        if self.tail[0] not in range(5) or not all(math.isfinite(v) for v in self.tail[1:]):
            raise ValueError('Invalid waveshaper parameters')
        if not all(0 <= value <= 100 for value in (self.tail[1], self.tail[2], self.tail[3], self.tail[5])):
            raise ValueError('Waveshaper controls and wet mix require 0..100')
        if not -200 <= self.tail[4] <= 100:
            raise ValueError('Output gain is outside the reconstructed range')

    def _configure(self):
        self._validate()
        for band, effect in zip(self.bands, self.filters):
            coefficients = _coefficients(*band[:4], self.sample_rate)
            if not np.isfinite(coefficients).all():
                raise ValueError('Filter coefficients are nonfinite')
            effect.configure(coefficients)

    def _set(self, identity, value):
        if not isinstance(identity, int) or not math.isfinite(value):
            raise ValueError('Invalid dynamic filter parameter')
        if 0 <= identity < 60 and identity % 10 < 5:
            band, field = divmod(identity, 10)
            if field == 0:
                if value != int(value):
                    raise ValueError('Filter kind must be an integer')
                value = int(value)
            elif field == 4:
                value = int(value != 0)
            else:
                value = float(f(value))
            self.bands[band][field] = value
        elif 60 <= identity <= 65:
            if identity == 60 and value != int(value):
                raise ValueError('Waveshaper kind must be an integer')
            self.tail[identity-60] = int(value) if identity == 60 else float(f(value))
        else:
            raise ValueError('Unknown dynamic filter parameter')

    def set_parameter(self, identity, value):
        bands, tail = [band.copy() for band in self.bands], self.tail.copy()
        try:
            self._set(identity, value)
            self._configure()
        except (ValueError, OverflowError):
            self.bands, self.tail = bands, tail
            self._configure()
            raise

    def reset(self):
        for effect in self.filters:
            effect.state.fill(0)
        self.dc = np.zeros((self.channels, 2), np.float32)

    def _shape(self, audio):
        mode, drive, shape, rectification, gain, mix = self.tail
        _, old_drive, old_shape, old_rectification, old_gain, old_mix = self.previous
        frames = len(audio)
        start = f(4*25**(old_drive*float(f(.01)))-3)
        stop = f(4*25**(drive*float(f(.01)))-3)
        before = _fast_pow10(-f(f(old_drive)*f(.01)))
        after = _fast_pow10(-f(f(drive)*f(.01)))
        if mode == 1:
            start = f(f(f(f(old_shape)*f(.01))*f(.3333333)+f(.6666666))*start)
            stop = f(f(f(f(shape)*f(.01))*f(.3333333)+f(.6666666))*stop)
        drive_step, gain_step = f(f(stop-start)/f(frames)), f(f(after-before)/f(frames))
        result = audio.copy()
        factor = _fast_exp(f(f(shape*f(.03))+f(2)), 8388608) if mode == 3 else f(0)
        reference = _fast_exp(f(factor*f(-.2))) if mode == 3 else f(0)
        low = f(f(f(50)-f(min(rectification, 50)))*f(-.02))
        high = f(f(f(rectification)-f(50))*f(.02))
        old_low = f(f(f(50)-f(min(old_rectification, 50)))*f(-.02))
        old_high = f(f(f(old_rectification)-f(50))*f(.02))
        a_step, b_step = f(f(low-old_low)/f(frames)), f(f(high-old_high)/f(frames))
        if _library is not None:
            config = np.array([mode, start, drive_step, before, gain_step, factor, reference,
                               2 if rectification > 50 else 1 if rectification else 0,
                               old_low, old_high, a_step, b_step], np.float32)
            _checked(_library.ft_filter_shape(_pointer(result), self.channels, _pointer(config)))
            return result
        if mode:
            for channel in range(self.channels):
                level, attenuation = start, before
                for i, sample in enumerate(audio[:, channel]):
                    value = f(sample*level)
                    if mode == 1:
                        magnitude = abs(value)
                        knee = f(f(2)-f(magnitude*f(3)))
                        shaped = f(f(f(3)-f(knee*knee))*f(.3333333))
                        if magnitude > f(.6666666): shaped = f(1)
                        if magnitude <= f(.3333333): shaped = f(magnitude*f(2))
                        if value <= 0: shaped = -shaped
                    elif mode == 2:
                        # x87 keeps the input/drive product unrounded for this exponential.
                        shaped = f(f(1)-_fast_exp(-abs(float(sample)*float(level))))
                        if value >= 0: shaped = -shaped
                    elif mode == 3:
                        delta = f(value-f(-.2))
                        shaped = f(f(1)/factor) if value == f(-.2) else f(delta/f(f(1)-_fast_exp(f(-f(delta*factor)))))
                        shaped = f(shaped+f(f(-.2)/f(f(1)-reference)))
                        shaped = f(1) if not shaped < f(1) else f(-1) if not shaped > f(-1) else shaped
                    else:
                        shaped = f(min(1, max(-1, value)))
                    result[i, channel] = f(shaped*attenuation)
                    level, attenuation = f(level+drive_step), f(attenuation+gain_step)
        if rectification:
            a, b = old_low, old_high
            for i in range(frames):
                sample = result[i].copy()
                clipped = np.maximum(sample, a)
                if rectification > 50:
                    clipped = np.where(sample <= 0, f(clipped-f(sample*b)), clipped)
                result[i] = clipped
                a, b = f(a+a_step), f(b+b_step)
        return result

    def process(self, audio):
        source = _audio(audio, self.channels)
        if source.shape != (128, self.channels):
            raise ValueError('Dynamic filter currently requires aligned 128-frame blocks')
        result = source
        for band, effect in zip(self.bands[:3], self.filters[:3]):
            if band[4]: result = effect.process(result)
        result = self._shape(result)
        for band, effect in zip(self.bands[3:], self.filters[3:]):
            if band[4]: result = effect.process(result)
        gain = f(10**(self.tail[4]*float(f(.05))))
        old_gain = f(10**(self.previous[4]*float(f(.05))))
        dry = f(f(f(100)-f(self.tail[5]))*f(.01))
        old_dry = f(f(f(100)-f(self.previous[5]))*f(.01))
        wet_a, wet_b = f(old_gain*f(f(1)-old_dry)), f(gain*f(f(1)-dry))
        dry_a, dry_b = f(old_gain*old_dry), f(gain*dry)
        step_a, step_b = f(f(wet_b-wet_a)/f(128)), f(f(dry_b-dry_a)/f(128))
        coefficient = f(f(1)-f(f(251.32742)/f(self.sample_rate)))
        output = np.empty_like(source)
        if _library is not None:
            gains = np.array([wet_a, step_a, dry_a, step_b, coefficient], np.float32)
            _checked(_library.ft_filter_mix_dc(_pointer(result), _pointer(source), _pointer(output),
                                               self.channels, _pointer(gains), _pointer(self.dc)))
        else:
            for i in range(128):
                value = f(f(result[i]*wet_a)+f(source[i]*dry_a))
                out = f(f(self.dc[:, 1]*coefficient)+f(value-self.dc[:, 0]))
                output[i] = out
                self.dc[:, 0], self.dc[:, 1] = value, out
                wet_a, dry_a = f(wet_a+step_a), f(dry_a+step_b)
        self.previous = self.tail.copy()
        if not np.isfinite(output).all():
            raise ValueError('Dynamic filter produced nonfinite audio')
        return output

    def rtpc_updates(self):
        return []
