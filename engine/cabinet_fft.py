from .runtime import kernel_path
"""Our compiled float32 FFT, radix schedule and packed spectral processing."""
import ctypes
from pathlib import Path
import sys

import numpy as np

_P = ctypes.POINTER(ctypes.c_float)
_U = ctypes.c_uint32
_library = None
path = kernel_path('CabinetFFT')
if path.exists():
    _library = ctypes.CDLL(str(path))
    _library.ft_cab_tables.argtypes = [_P]*4
    _library.ft_cab_process.argtypes = [_P, _P, _P, _P, _U, ctypes.POINTER(_U), _P, _P, ctypes.c_float, ctypes.c_float]
    _library.ft_cab_tables.restype = _library.ft_cab_process.restype = ctypes.c_int


def available():
    return _library is not None


def _ptr(array):
    return array.ctypes.data_as(_P)


class CompiledCabinet:
    def __init__(self, spectra, dry_gain, wet_gain):
        if _library is None:
            raise RuntimeError('Independent cabinet FFT kernel is unavailable')
        spectra = np.asarray(spectra)
        if spectra.ndim != 2 or spectra.shape[1] != 129 or not 1 <= len(spectra) <= 4096:
            raise ValueError('Invalid cabinet FFT dimensions')
        self.spectra = np.stack((spectra.real, spectra.imag), axis=-1).astype(np.float32)
        if not np.isfinite(self.spectra).all() or np.any(self.spectra[:, -1]):
            raise ValueError('Invalid cabinet FFT coefficients')
        self.dry_gain, self.wet_gain = dry_gain, wet_gain
        self.tables = np.zeros((4, 128, 2), np.float32)
        if not _library.ft_cab_tables(*[_ptr(table) for table in self.tables]):
            raise RuntimeError('Independent cabinet FFT initialization failed')
        self.ring = np.zeros_like(self.spectra)
        self.work = np.zeros(1040, np.float32)
        self.reset()

    def reset(self):
        self.ring.fill(0)
        self.work.fill(0)
        self.position = _U(0)

    def process(self, audio):
        audio = np.ascontiguousarray(audio, np.float32)
        if audio.shape != (128, 1) or not np.isfinite(audio).all():
            raise ValueError('Cabinet FFT requires 128 finite mono frames')
        output = np.empty_like(audio)
        if not _library.ft_cab_process(_ptr(audio), _ptr(output), _ptr(self.spectra), _ptr(self.ring),
                                       len(self.spectra), ctypes.byref(self.position), _ptr(self.tables),
                                       _ptr(self.work), self.dry_gain, self.wet_gain):
            raise RuntimeError('Independent cabinet FFT rejected the audio format')
        if not np.isfinite(output).all():
            raise ValueError('Cabinet FFT produced nonfinite output')
        return output
