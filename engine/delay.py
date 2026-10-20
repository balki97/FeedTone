from .runtime import kernel_path
"""Independent source implementation of the original 0x41033 delay family."""
import ctypes
from functools import lru_cache
import math
from pathlib import Path
import struct

import numpy as np


@lru_cache(maxsize=1)
def _kernel():
    path = kernel_path('DelayKernels')
    if not path.is_file():
        raise RuntimeError('Independent DelayKernels.dll is unavailable')
    library = ctypes.CDLL(str(path))
    library.ft_delay_abi.argtypes = []
    library.ft_delay_abi.restype = ctypes.c_uint32
    if library.ft_delay_abi() != 1:
        raise RuntimeError('Independent delay kernel ABI mismatch')
    library.ft_delay_state_size.argtypes = []
    library.ft_delay_state_size.restype = ctypes.c_uint32
    pointer = ctypes.POINTER(ctypes.c_float)
    library.ft_delay_initialize.argtypes = [ctypes.c_void_p, pointer, ctypes.c_uint32, ctypes.c_uint32]
    library.ft_delay_parameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_float]
    library.ft_delay_reset.argtypes = [ctypes.c_void_p, pointer]
    library.ft_delay_process.argtypes = [ctypes.c_void_p, pointer, pointer, ctypes.c_uint32]
    for name in ('ft_delay_initialize', 'ft_delay_parameter', 'ft_delay_reset', 'ft_delay_process'):
        getattr(library, name).restype = ctypes.c_int
    return library


def _pointer(array):
    if array.dtype != np.float32 or not array.flags.c_contiguous:
        raise ValueError('Delay kernels require contiguous float32 arrays')
    return array.ctypes.data_as(ctypes.POINTER(ctypes.c_float))


def _check(result):
    if result != 1:
        raise ValueError('Independent delay kernel rejected its parameters')


class TrashDelay:
    plugin_id = 0x41033
    # Authored logarithmic curves can evaluate slightly below their nominal 20 Hz endpoint.
    _ranges = ((0, 100), (0, 100), (1, 20000), (.2, 12), (1, 20000), (.2, 12),
               (10, 1000), (0, 200), (0, 1), (0, 3))

    def __init__(self, parameters, sample_rate=48000, channels=1, initial_parameters=None):
        if len(parameters) != 40 or sample_rate != 48000 or channels not in (1, 2):
            raise ValueError('Trash Delay requires 40 bytes, 48 kHz mono or stereo')
        self.values = list(struct.unpack('<9fI', parameters))
        for identity, value in (initial_parameters or {}).items():
            if not 0 <= int(identity) <= 9:
                raise ValueError('Unknown delay parameter')
            self.values[int(identity)] = value
        self._validate()
        self.channels, self.sample_rate = channels, sample_rate
        self.library = _kernel()
        size = self.library.ft_delay_state_size()
        if not 1 <= size <= 65536:
            raise RuntimeError('Invalid delay kernel state size')
        self.states = [ctypes.create_string_buffer(size) for _ in range(channels)]
        self.rings = [np.zeros(96001, np.float32) for _ in range(channels)]
        for state, ring in zip(self.states, self.rings):
            _check(self.library.ft_delay_initialize(state, _pointer(ring), len(ring), sample_rate))
            for identity, value in enumerate(self.values):
                _check(self.library.ft_delay_parameter(state, identity, value))

    def _validate(self):
        for value, (minimum, maximum) in zip(self.values, self._ranges):
            if not math.isfinite(value) or not float(np.float32(minimum)) <= value <= maximum:
                raise ValueError('Delay source parameter is outside its supported range')
        if self.values[9] != int(self.values[9]):
            raise ValueError('Delay model must be an integer')

    def set_parameter(self, identity, value):
        if not isinstance(identity, int) or not 0 <= identity <= 9:
            raise ValueError('Unknown delay parameter')
        previous = self.values[identity]
        self.values[identity] = float(np.float32(value))
        try:
            self._validate()
        except (ValueError, OverflowError):
            self.values[identity] = previous
            raise
        for state in self.states:
            _check(self.library.ft_delay_parameter(state, identity, value))

    def reset(self):
        for state, ring in zip(self.states, self.rings):
            _check(self.library.ft_delay_reset(state, _pointer(ring)))

    def process(self, audio):
        audio = np.asarray(audio, np.float32)
        if audio.shape != (128, self.channels) or not np.isfinite(audio).all():
            raise ValueError('Delay requires 128 finite frames by configured channels')
        result = np.empty_like(audio)
        for channel, (state, ring) in enumerate(zip(self.states, self.rings)):
            samples = np.array(audio[:, channel], dtype=np.float32, order='C', copy=True)
            _check(self.library.ft_delay_process(state, _pointer(ring), _pointer(samples), len(samples)))
            result[:, channel] = samples
        if not np.isfinite(result).all():
            raise ValueError('Independent delay produced nonfinite audio')
        return result

    def rtpc_updates(self):
        return []
