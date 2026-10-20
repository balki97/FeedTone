from .runtime import kernel_path
"""Optional kernels built solely from this project's independent C source."""
import ctypes
from pathlib import Path
import sys

import numpy as np


_F32 = ctypes.POINTER(ctypes.c_float)
_U32 = ctypes.POINTER(ctypes.c_uint32)
_I64 = ctypes.POINTER(ctypes.c_int64)
_library = None
path = kernel_path('DSPKernels')
if path.exists():
    _library = ctypes.CDLL(str(path))
    _library.ft_dsp_abi.restype = ctypes.c_uint32
    _library.ft_dsp_abi.argtypes = []
    if _library.ft_dsp_abi() != 1:
        raise RuntimeError('Independent DSP kernel ABI mismatch')
    _library.ft_limiter.argtypes = [_F32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_uint32, _F32, _U32, _F32, _F32, _I64,
                                  ctypes.c_uint32, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]
    _library.ft_equalizer.argtypes = [_F32, ctypes.c_uint32, ctypes.c_uint32, _F32, _F32]
    _library.ft_gate.argtypes = [_F32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                               _F32, _F32, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]
    if hasattr(_library, 'ft_compressor'):
        _library.ft_compressor.argtypes = _library.ft_gate.argtypes
        _library.ft_compressor.restype = ctypes.c_int
    _library.ft_rms_power.argtypes = [_F32, ctypes.c_uint32, ctypes.c_uint32, _F32]
    for name in ('ft_limiter', 'ft_equalizer', 'ft_gate', 'ft_rms_power'):
        getattr(_library, name).restype = ctypes.c_int
    if hasattr(_library, 'ft_amp_compression'):
        _library.ft_amp_compression.argtypes = [_F32, ctypes.c_uint32, ctypes.c_uint32, _F32]
        _library.ft_amp_compression.restype = ctypes.c_int


def available():
    return _library is not None


def _pointer(array):
    if array.dtype != np.float32 or not array.flags.c_contiguous:
        raise ValueError('Kernel arrays must be contiguous float32')
    return array.ctypes.data_as(_F32)


def _check(result):
    if result != 1:
        raise RuntimeError('Independent DSP kernel rejected its input')


def limiter(effect, audio):
    if _library is None:
        return False
    position = ctypes.c_uint32(effect.position)
    ratio = np.float32((1/effect.ratio-1)*.05)
    _check(_library.ft_limiter(_pointer(audio), len(audio), effect.channels, bool(effect.linked),
                              effect.latency_frames, _pointer(effect.delay), ctypes.byref(position),
                              _pointer(effect.reduction), _pointer(effect.peak), effect.countdown.ctypes.data_as(_I64),
                              effect.first, effect.threshold, ratio, effect.attack_coefficient, effect.release_coefficient))
    effect.position, effect.first = position.value, False
    return True


def equalizer(audio, coefficients, history):
    if _library is None:
        return False
    _check(_library.ft_equalizer(_pointer(audio), len(audio), audio.shape[1], _pointer(coefficients), _pointer(history)))
    return True


def gate(effect, audio, attack, release):
    if _library is None:
        return False
    ratio = np.float32(np.float32(effect.ratio)-np.float32(1))
    _check(_library.ft_gate(_pointer(audio), len(audio), effect.channels, effect.active_linked,
                           _pointer(effect.power), _pointer(effect.reduction), effect.threshold, ratio,
                           effect.power_coefficient, attack, release))
    return True


def rms_power(audio):
    if _library is None:
        return None
    result = np.empty(audio.shape[1], dtype=np.float32)
    _check(_library.ft_rms_power(_pointer(audio), len(audio), audio.shape[1], _pointer(result)))
    return result


def compressor(effect, audio, attack, release):
    if _library is None or not hasattr(_library, 'ft_compressor'):
        return False
    ratio = np.float32(np.float32(1)/np.float32(effect.ratio)-np.float32(1))
    _check(_library.ft_compressor(_pointer(audio), len(audio), effect.channels, effect.active_linked,
                                 _pointer(effect.power), _pointer(effect.reduction), effect.threshold,
                                 ratio, effect.power_coefficient, attack, release))
    return True


def amp_compression(audio, state):
    if _library is None or not hasattr(_library, 'ft_amp_compression'):
        return False
    if state.shape != (audio.shape[1], 0x498//4):
        raise ValueError('Compression state layout does not match channels')
    _check(_library.ft_amp_compression(_pointer(audio), len(audio), audio.shape[1], _pointer(state)))
    return True
