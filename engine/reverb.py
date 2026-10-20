from .runtime import kernel_path
"""Independent four/eight-line Wwise FDN reverb (0x730003)."""
import ctypes
from functools import lru_cache
import math
from pathlib import Path
import struct

import numpy as np


@lru_cache(maxsize=1)
def _kernel():
    path = kernel_path('ReverbKernels')
    if not path.is_file():
        raise RuntimeError('Independent ReverbKernels.dll is unavailable')
    library = ctypes.CDLL(str(path))
    library.ft_reverb_abi.argtypes = []
    library.ft_reverb_abi.restype = ctypes.c_uint32
    if library.ft_reverb_abi() != 1:
        raise RuntimeError('Independent reverb kernel ABI mismatch')
    library.ft_reverb_state_size.argtypes = []
    library.ft_reverb_state_size.restype = ctypes.c_uint32
    pointer = ctypes.POINTER(ctypes.c_float)
    library.ft_reverb_initialize.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                           ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32, pointer]
    library.ft_reverb_parameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_float]
    library.ft_reverb_reset.argtypes = [ctypes.c_void_p, pointer, pointer]
    library.ft_reverb_process.argtypes = [ctypes.c_void_p, pointer, pointer, pointer]
    for name in ('initialize', 'parameter', 'reset', 'process'):
        getattr(library, 'ft_reverb_'+name).restype = ctypes.c_int
    return library


def _pointer(array):
    if array.dtype != np.float32 or not array.flags.c_contiguous:
        raise ValueError('Reverb requires contiguous float32 buffers')
    return array.ctypes.data_as(ctypes.POINTER(ctypes.c_float))


def _check(result):
    if result != 1:
        raise ValueError('Independent reverb kernel rejected its input')


def _prime(length):
    length |= 1
    while any(length % divisor == 0 for divisor in range(3, math.isqrt(length)+1, 2)):
        length += 2
    return length


class FDNReverb:
    plugin_id = 0x730003

    def __init__(self, parameters, sample_rate=48000, channels=1, initial_parameters=None):
        if len(parameters) < 29 or sample_rate != 48000 or channels not in (1, 2):
            raise ValueError('FDN reverb requires a source block and 48 kHz mono/stereo')
        decay, damping, count, dry, wet, predelay, lfe, mode = struct.unpack_from('<2fI3fBI', parameters)
        if count not in (4, 8) or mode != 1 or len(parameters) != 29+count*4:
            raise ValueError('Only authored four/eight-line FDN source layouts are reconstructed')
        self.sample_rate, self.channels, self.count = sample_rate, channels, count
        self.values = {0: decay, 1: damping, 3: dry, 4: wet, 5: predelay}
        self.times = list(struct.unpack_from('<'+'f'*count, parameters, 29))
        self._validate()
        for identity, value in (initial_parameters or {}).items():
            self.set_parameter(identity, value)
        self.library = _kernel()
        size = self.library.ft_reverb_state_size()
        if not 1 <= size <= 2048:
            raise RuntimeError('Invalid independent reverb state layout')
        self.state = ctypes.create_string_buffer(size)
        self._initialize()

    def _validate(self):
        if not all(math.isfinite(v) for v in list(self.values.values())+self.times):
            raise ValueError('Reverb requires finite parameters')
        if not .01 <= self.values[0] <= 60 or not .1 <= self.values[1] <= 20:
            raise ValueError('Invalid reverb decay/damping')
        if not 0 <= self.values[5] <= 2 or not all(.1 <= v <= 1000 for v in self.times):
            raise ValueError('Invalid reverb delay time')
        if not all(-200 <= self.values[i] <= 24 for i in (3, 4)):
            raise ValueError('Invalid reverb mix gain')

    def _initialize(self):
        lengths = sorted(_prime(math.floor(48000*float(t)*.001)) for t in self.times)
        self.rings = np.zeros(sum(lengths), np.float32)
        predelay = math.floor(48000*self.values[5])
        self.predelay = np.zeros(max(1, predelay), np.float32)
        previous = getattr(self, 'previous_mix', (self._gain(3), self._gain(4)))
        values = np.array([self.values[0], self.values[1], self._gain(3), self._gain(4), *previous], np.float32)
        _check(self.library.ft_reverb_initialize(self.state, self.count, self.channels,
               (ctypes.c_uint32*self.count)(*lengths), predelay, _pointer(values)))

    def _gain(self, identity):
        return np.float32(math.pow(10, self.values[identity]*float(np.float32(.05))))

    def set_parameter(self, identity, value):
        if identity not in self.values or not math.isfinite(value):
            raise ValueError('Unsupported FDN reverb control')
        old = self.values[identity]
        self.values[identity] = float(np.float32(value))
        try:
            self._validate()
        except ValueError:
            self.values[identity] = old
            raise
        if hasattr(self, 'state'):
            if identity == 5:
                self._initialize()
            else:
                _check(self.library.ft_reverb_parameter(self.state, identity,
                       self._gain(identity) if identity in (3, 4) else self.values[identity]))

    def reset(self):
        _check(self.library.ft_reverb_reset(self.state, _pointer(self.rings), _pointer(self.predelay)))

    def process(self, audio):
        audio = np.asarray(audio, np.float32)
        if audio.shape != (128, self.channels) or not np.isfinite(audio).all():
            raise ValueError('FDN reverb requires 128 finite frames')
        result = np.array(audio, np.float32, order='C', copy=True)
        _check(self.library.ft_reverb_process(self.state, _pointer(self.rings), _pointer(self.predelay), _pointer(result)))
        if not np.isfinite(result).all():
            raise ValueError('Independent reverb produced nonfinite output')
        self.previous_mix = (self._gain(3), self._gain(4))
        return result

    def rtpc_updates(self):
        return []
