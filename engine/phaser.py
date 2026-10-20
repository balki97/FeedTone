from .runtime import kernel_path
"""Independent current-catalog iZotope phaser/filter reconstruction (0x61033)."""
import ctypes
from functools import lru_cache
import math
from pathlib import Path
import struct

import numpy as np


@lru_cache(maxsize=1)
def _kernel():
    path = kernel_path('PhaserKernels')
    if not path.is_file():
        raise RuntimeError('Independent PhaserKernels.dll is unavailable')
    library = ctypes.CDLL(str(path))
    library.ft_phaser_abi.restype = ctypes.c_uint32
    if library.ft_phaser_abi() != 3:
        raise RuntimeError('Independent phaser kernel ABI mismatch')
    # Compensated legacy trig and base-ten amplitude math are implemented in
    # the source-built kernel; no external CRT math is selected at runtime.
    library.ft_phaser_state_size.restype = ctypes.c_uint32
    library.ft_phaser_initialize.argtypes = [ctypes.c_void_p]
    library.ft_phaser_parameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_float]
    library.ft_phaser_reset.argtypes = [ctypes.c_void_p]
    library.ft_phaser_process.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_uint32]
    for name in ('initialize', 'parameter', 'reset', 'process'):
        getattr(library, 'ft_phaser_'+name).restype = ctypes.c_int
    return library


def _check(result):
    if result != 1:
        raise ValueError('Independent phaser kernel rejected its parameters')


class TrashPhaser:
    plugin_id = 0x61033

    def __init__(self, parameters, sample_rate=48000, channels=1, initial_parameters=None):
        if len(parameters) != 144 or sample_rate != 48000 or channels not in (1, 2):
            raise ValueError('Phaser requires 144 bytes, 48 kHz mono or stereo')
        self.values = []
        for i in range(36):
            self.values.append(struct.unpack_from('<I' if i % 12 in (0, 5, 6) else '<f', parameters, i*4)[0])
        for identity, value in (initial_parameters or {}).items():
            if not 0 <= int(identity) < 36:
                raise ValueError('Unknown phaser parameter')
            self.values[int(identity)] = value
        for i, value in enumerate(self.values):
            if not math.isfinite(value):
                raise ValueError('Phaser parameters must be finite')
            self.values[i] = int(value) if i % 12 in (0, 5, 6) else float(np.float32(value))
        self._validate(self.values)
        self.channels, self.sample_rate = channels, sample_rate
        self.library = _kernel()
        size = self.library.ft_phaser_state_size()
        if not 1 <= size <= 65536:
            raise RuntimeError('Invalid phaser kernel state size')
        self.states = [ctypes.create_string_buffer(size) for _ in range(channels)]
        for state in self.states:
            _check(self.library.ft_phaser_initialize(state))
            for identity, value in enumerate(self.values):
                _check(self.library.ft_phaser_parameter(state, identity, value))

    @staticmethod
    def _validate(values):
        for i, value in enumerate(values):
            if not math.isfinite(value):
                raise ValueError('Phaser parameters must be finite')
            k = i % 12
            if k == 0 and value not in (0, 6, 21):
                raise NotImplementedError('Unverified phaser filter model')
            if k == 5 and value not in (0, 1):
                raise NotImplementedError('Unverified phaser modulation mode')
            if k == 6 and value not in (0, 1, 2, 3, 4):
                raise NotImplementedError('Unverified phaser LFO shape')
            if k in (1, 8) and not 20 <= value <= 20000:
                raise ValueError('Phaser frequency must be 20–20000 Hz')
            if k in (2, 10) and not .1 <= value <= 20:
                raise ValueError('Phaser resonance must be 0.1–20')
            if k in (3, 11) and not 0 <= value <= 1:
                raise ValueError('Phaser shape must be 0–1')
            if k in (4, 9) and not -60 <= value <= 24:
                raise ValueError('Phaser gain must be -60–24 dB')
            if k == 7 and not 1 <= value <= 8000:
                raise ValueError('Phaser period must be 1–8000 ms')

    @property
    def parameters(self):
        return b''.join(struct.pack('<I' if i % 12 in (0, 5, 6) else '<f', value)
                        for i, value in enumerate(self.values))

    def set_parameter(self, identity, value):
        if not isinstance(identity, int) or not 0 <= identity < 36:
            raise ValueError('Unknown phaser parameter')
        value = float(np.float32(value))
        if identity % 12 in (0, 5, 6):
            if not math.isfinite(value):
                raise ValueError('Phaser parameters must be finite')
            value = int(value)
        candidate = self.values.copy()
        candidate[identity] = value
        self._validate(candidate)
        for state in self.states:
            _check(self.library.ft_phaser_parameter(state, identity, value))
        self.values = candidate

    def reset(self):
        for state in self.states:
            _check(self.library.ft_phaser_reset(state))

    def rtpc_updates(self):
        return []

    def process(self, audio):
        array = np.asarray(audio, dtype=np.float32)
        if array.ndim != 2 or array.shape[1] != self.channels or not 1 <= len(array) <= 128:
            raise ValueError('Phaser expects 1–128 frames with its configured channel count')
        if not np.isfinite(array).all():
            raise ValueError('Phaser audio must be finite')
        result = np.empty_like(array)
        for channel, state in enumerate(self.states):
            block = np.zeros(128, np.float32)
            block[:len(array)] = array[:, channel]
            _check(self.library.ft_phaser_process(state, block.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), 128))
            result[:, channel] = block[:len(array)]
        return result
