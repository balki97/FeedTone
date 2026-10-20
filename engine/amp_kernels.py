from .runtime import kernel_path
"""Optional compiled loops built from our amplifier source equations."""
import ctypes
from pathlib import Path
import sys

import numpy as np

_library = None
_F32, _F64 = ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_double)
_U = ctypes.c_uint32
path = kernel_path('AmpKernels')
if path.exists():
    _library = ctypes.CDLL(str(path))
    _library.ft_amp_first.argtypes = [_F32, _F32, _U, _U, _F64] + [ctypes.c_double]*3
    _library.ft_amp_biquads.argtypes = [_F32, _U, _U, _F32, _F32, _U]
    _library.ft_amp_mix.argtypes = [_F32, _F32, _U, _U] + [ctypes.c_float]*4
    for name in ('ft_amp_first', 'ft_amp_biquads', 'ft_amp_mix'):
        getattr(_library, name).restype = ctypes.c_int


def available():
    return _library is not None


def _pointer(array, dtype=np.float32):
    if not array.flags.c_contiguous or array.dtype != dtype:
        raise ValueError('Kernel arrays must be contiguous with their declared dtype')
    return array.ctypes.data_as(_F32 if dtype == np.float32 else _F64)


def first_order(audio, state, b0, b1, a1):
    if _library is None:
        return None
    audio = np.ascontiguousarray(audio, np.float32)
    state = np.ascontiguousarray(state, np.float64)
    if audio.ndim != 2 or state.shape != (audio.shape[1],) or not 1 <= audio.shape[1] <= 2 or len(audio) > 128:
        raise ValueError('Invalid first-order kernel dimensions')
    output = np.empty_like(audio)
    if not _library.ft_amp_first(_pointer(output), _pointer(audio), len(audio), audio.shape[1], _pointer(state, np.float64), b0, b1, a1):
        raise RuntimeError('Amplifier kernel rejected input')
    return output, state


def biquads(audio, coefficients, state):
    if _library is None:
        return None
    audio = np.ascontiguousarray(audio, np.float32).copy()
    if audio.ndim != 2 or not 1 <= audio.shape[1] <= 2 or len(audio) > 128 or coefficients.ndim != 2 or coefficients.shape[1] != 5 or state.shape != (len(coefficients), 4, audio.shape[1]):
        raise ValueError('Invalid amplifier filter kernel dimensions')
    if not _library.ft_amp_biquads(_pointer(audio), len(audio), audio.shape[1], _pointer(coefficients), _pointer(state), len(coefficients)):
        raise RuntimeError('Amplifier kernel rejected input')
    return audio


def mix(wet, dry, wet_start, wet_end, dry_start, dry_end):
    if _library is None:
        return None
    wet = np.ascontiguousarray(wet, np.float32).copy()
    dry = np.ascontiguousarray(dry, np.float32)
    if wet.shape != dry.shape or wet.ndim not in (1, 2) or not 0 < len(wet) <= 128:
        raise ValueError('Invalid amplifier mixing dimensions')
    channels = 1 if wet.ndim == 1 else wet.shape[1]
    if not _library.ft_amp_mix(_pointer(wet), _pointer(dry), len(wet), channels, wet_start, wet_end, dry_start, dry_end):
        raise RuntimeError('Amplifier kernel rejected input')
    return wet
