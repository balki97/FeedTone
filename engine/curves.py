"""Independent source implementation of the original x86 RTPC conversion.

Observed in REA procedures 0xea9250, 0xea8a30 and 0xea8ef0. This is a
source implementation used by both tone planning and audio control updates.
SSE operations round to float32, x87 operations use binary64 precision.
"""
from __future__ import annotations

import math
import struct
from typing import Mapping, Sequence


def _f32(value: float) -> float:
    try:
        return struct.unpack('<f', struct.pack('<f', value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)


def _bits(value: float) -> int:
    return struct.unpack('<I', struct.pack('<f', value))[0]


def _float(bits: int) -> float:
    return struct.unpack('<f', struct.pack('<I', bits & 0xffffffff))[0]


def _finite(value: float) -> float:
    value = _f32(float(value))
    if not math.isfinite(value):
        raise ValueError('RTPC values must be finite float32 numbers')
    return value


def interpolate(t: float, y0: float, y1: float, code: int) -> float:
    """Original interpolation codes; t is the normalized interval position."""
    t, y0, y1 = _finite(t), _finite(y0), _finite(y1)
    if code == 9:
        return y0
    if code == 0:
        q = 1.0 - t
        return _f32(y1 + (y0 - y1) * ((q * q) * q))
    if code == 1 or code == 3:
        phase = _f32(t * (1.5707963705062866 if code == 1 else 3.1415927410125732))
        reverse = code == 3 and t > 0.5
        if reverse:
            phase = _f32(3.1415927410125732 - phase)
        q = _f32(phase * phase)
        factor = 1.0 if code == 1 else 0.5
        weight = (((0.008306325413286686 * factor - 0.00018363654089625925 * factor * q)
                   * q - 0.1666482836008072 * factor) * q + 0.9999966025352478 * factor) * phase
        if reverse:
            weight = 1.0 - weight
    elif code == 2:
        weight = ((3.0 - t) * t) * 0.5
    elif code == 4:
        weight = t
    elif code == 5:
        phase = _f32(t * 3.1415927410125732)
        q = _f32(phase * phase)
        weight = ((0.00048483398859389126 * q - 0.0196138396859169) * q
                  + 0.24767479300498962) * q + 0.0006967021618038416
    elif code == 6:
        weight = ((1.0 + t) * t) * 0.5
    elif code == 7:
        phase = _f32(t * 1.5707963705062866)
        q = _f32(phase * phase)
        complement = ((0.04148774966597557 - 0.0012712094467133284 * q) * q
                      - 0.49991244077682495) * q + 0.9999933242797852
        return _f32(y1 + (y0 - y1) * complement)
    elif code == 8:
        weight = (t * t) * t
    else:
        raise ValueError('Unsupported RTPC interpolation code')
    return _f32(y0 + (y1 - y0) * weight)


def scale(value: float, code: int) -> float:
    """Observed scaling codes. Codes 0 and 1 are native identity branches."""
    value = _finite(value)
    if code in (0, 1):
        return value
    if code == 2:
        if value <= -1.0:
            return -4096.0
        if value >= 1.0:
            return 4096.0
        operand = _f32(1.0 + value if value < 0.0 else 1.0 - value)
        bits = _bits(operand)
        mantissa = _float((bits & 0x7fffff) + 0x3f800000)
        ratio = (mantissa - 1.0) / (mantissa + 1.0)
        logarithm = ((ratio + ratio) * (ratio * ratio * 0.3333333432674408 + 1.0)
                     + ((bits >> 23 & 255) - 127.0) * 0.6931471824645996)
        return _f32(logarithm * (0.4342944920063019 if value < 0 else -0.4342944920063019) * 20.0)
    if code not in (3, 4):
        raise ValueError('Unsupported RTPC scaling code')
    if code == 4:
        value = _f32(value * 0.05000000074505806)
    if value < -37.0:
        return 0.0
    packed = math.trunc(27866352.0 * value + 1065353216.0) & 0xffffffff
    exponent = _float(packed & 0xff800000)
    mantissa = _float((packed & 0x7fffff) + 0x3f800000)
    result = _f32(mantissa * 0.3251897692680359)
    result = _f32(result + 0.02080577239394188)
    result = _f32(result * mantissa)
    result = _f32(result + 0.6530434489250183)
    return _f32(result * exponent)


def evaluate_curve(curve: Mapping, raw_value: float) -> float:
    """Evaluate the exact catalog curve schema using raw authored knob units.

    Never normalize a 0..100 knob before calling this. One knob can target
    several curves/parameters; callers must apply every explicit binding.
    """
    raw_value = _finite(raw_value)
    points: Sequence = curve['points']
    if not 1 <= len(points) <= 4096:
        raise ValueError('RTPC curves require 1..4096 points')
    parsed = []
    previous = -math.inf
    for point in points:
        x, y = _finite(point['x']), _finite(point['y'])
        code = int(point['interpolation_provisional'])
        if x < previous or code not in range(10):
            raise ValueError('RTPC points must be ordered and use a supported interpolation')
        parsed.append((x, y, code))
        previous = x
    value = parsed[-1][1]
    for i, (x, y, code) in enumerate(parsed):
        if raw_value <= x:
            value = y
            break
        if i + 1 < len(parsed) and raw_value < parsed[i + 1][0]:
            nx, ny, _ = parsed[i + 1]
            t = _f32(_f32(raw_value - x) / _f32(nx - x))
            if code == 4:
                value = _f32(_f32(t * _f32(ny - y)) + y)
            else:
                value = interpolate(t, y, ny, code)
            break
    return scale(value, int(curve['scaling_provisional']))
