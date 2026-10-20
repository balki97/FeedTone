from .runtime import kernel_path
"""Independent mixed-radix FFT used by the pitch vocoder."""
import ctypes
from pathlib import Path

import numpy as np

_P = ctypes.POINTER(ctypes.c_float)
_U = ctypes.c_uint32
_path = kernel_path('PitchFFT')
_library = ctypes.CDLL(str(_path)) if _path.exists() else None
if _library:
    _library.ft_pitch_fft_tables.argtypes = [_U]+[_P]*4
    _library.ft_pitch_forward.argtypes = _library.ft_pitch_inverse.argtypes = [_U]+[_P]*5
    _library.ft_pitch_window.argtypes = [_U, _P, _P]


def _ptr(a):
    return a.ctypes.data_as(_P)


class PitchFFT:
    def __init__(self, size):
        if _library is None:
            raise RuntimeError('Build independent native/PitchFFT.dll first')
        self.size = size
        self.forward_table = np.empty((size//2, 2), np.float32)
        self.inverse_table = np.empty_like(self.forward_table)
        self.super_forward = np.empty((size//4, 2), np.float32)
        self.super_inverse = np.empty_like(self.super_forward)
        self.work = np.empty_like(self.forward_table)
        if not _library.ft_pitch_fft_tables(size, *map(_ptr, (self.forward_table, self.inverse_table, self.super_forward, self.super_inverse))):
            raise ValueError('Unsupported pitch FFT size')

    def forward(self, audio):
        audio = np.ascontiguousarray(audio, np.float32)
        if audio.shape != (self.size,) or not np.isfinite(audio).all():
            raise ValueError('Pitch FFT requires a finite mono frame')
        result = np.empty((self.size//2+1, 2), np.float32)
        if not _library.ft_pitch_forward(self.size, *map(_ptr, (audio, result, self.work, self.forward_table, self.super_forward))):
            raise ArithmeticError('Pitch FFT forward failed')
        return result

    def inverse(self, pairs):
        pairs = np.ascontiguousarray(pairs, np.float32)
        if pairs.shape != (self.size//2+1, 2) or not np.isfinite(pairs).all():
            raise ValueError('Pitch FFT requires finite complex pairs')
        result = np.empty(self.size, np.float32)
        if not _library.ft_pitch_inverse(self.size, *map(_ptr, (pairs, result, self.work, self.inverse_table, self.super_inverse))):
            raise ArithmeticError('Pitch FFT inverse failed')
        return result


def window(size):
    if _library is None:
        raise RuntimeError('Build independent native/PitchFFT.dll first')
    values = np.empty(size, np.float32)
    energy = ctypes.c_float()
    if not _library.ft_pitch_window(size, _ptr(values), ctypes.byref(energy)):
        raise ValueError('Unsupported pitch window size')
    normalization = np.float32(np.float32(1)/np.float32(np.float32(energy.value*np.float32(4))/np.float32(size)))
    return values, np.float32(values*normalization)
