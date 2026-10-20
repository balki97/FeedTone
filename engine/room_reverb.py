from .runtime import kernel_path
"""Independent RoomVerb (0x760003) with exact catalogue topology metadata."""
import ctypes
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import struct

import numpy as np


@lru_cache(maxsize=1)
def _kernel():
    path = kernel_path('RoomKernels')
    if not path.is_file():
        raise RuntimeError('Independent RoomKernels.dll is unavailable')
    library = ctypes.CDLL(str(path))
    library.ft_room_abi.argtypes = []
    library.ft_room_abi.restype = ctypes.c_uint32
    if library.ft_room_abi() != 1:
        raise RuntimeError('Independent RoomVerb ABI mismatch')
    library.ft_room_state_size.argtypes = []
    library.ft_room_state_size.restype = ctypes.c_uint32
    pointer = ctypes.POINTER(ctypes.c_float)
    library.ft_room_initialize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), pointer]
    library.ft_room_parameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_float]
    library.ft_room_reset.argtypes = [ctypes.c_void_p, pointer]
    library.ft_room_process.argtypes = [ctypes.c_void_p, pointer, pointer]
    library.ft_room_total.argtypes = [ctypes.c_void_p]
    library.ft_room_total.restype = ctypes.c_uint32
    for name in ('initialize', 'parameter', 'reset', 'process'):
        getattr(library, 'ft_room_'+name).restype = ctypes.c_int
    return library


@lru_cache(maxsize=1)
def _topologies():
    path = Path(__file__).resolve().parents[1]/'data/room_reverb.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 'feedback.room-reverb.topology.v1':
        raise ValueError('Unsupported RoomVerb topology metadata')
    return data['profiles']


def _pointer(array):
    if array.dtype != np.float32 or not array.flags.c_contiguous:
        raise ValueError('RoomVerb requires contiguous float32 buffers')
    return array.ctypes.data_as(ctypes.POINTER(ctypes.c_float))


def _check(result):
    if result != 1:
        raise ValueError('Independent RoomVerb kernel rejected its input')


def _gain(value):
    return np.float32(math.pow(10, float(value)*float(np.float32(.05))))


class RoomReverb:
    plugin_id = 0x760003

    def __init__(self, parameters, sample_rate=48000, channels=1, initial_parameters=None):
        if len(parameters) != 186 or sample_rate != 48000 or channels not in (1, 2):
            raise ValueError('RoomVerb requires 186 source bytes and 48 kHz mono/stereo')
        identity = hashlib.sha256(parameters).hexdigest()
        topology = _topologies().get(identity)
        if topology is None or topology['filter_count'] != 0 or not topology['early_enabled']:
            raise ValueError('This exact RoomVerb source topology has not been reconstructed')
        self.channels, self.sample_rate = channels, sample_rate
        self.source = list(struct.unpack_from('<20f', parameters))
        self.values = {10: self.source[0], 11: self.source[1], 15: self.source[2],
                       60: self.source[17], 61: self.source[18], 62: self.source[19]}
        self._validate()
        updates = dict(initial_parameters or {})
        for identity, value in updates.items():
            if identity not in self.values or not math.isfinite(value):
                raise ValueError('Unsupported initial RoomVerb control')
            self.values[identity] = float(np.float32(value))
        self._validate()
        self.library = _kernel()
        size = self.library.ft_room_state_size()
        if not 1 <= size <= 65536:
            raise RuntimeError('Invalid independent RoomVerb state size')
        self.state = ctypes.create_string_buffer(size)
        config = [channels, topology['count'], *[x['length'] for x in topology['allpass']],
                  topology['earliest_delay'], topology['late_delay'], topology['early']['length'],
                  *[len(x) for x in topology['early']['taps']]]
        gains = []
        for taps in topology['early']['taps']:
            config += [tap['position'] for tap in taps]+[0]*(64-len(taps))
            gains += [tap['gain'] for tap in taps]+[0]*(64-len(taps))
        units = topology['fdn']
        config += [n for unit in units for n in unit['lengths']]+[0]*(16-len(units)*4)
        config += [unit['extra_delay'] for unit in units]+[0]*(4-len(units))
        floats = np.array([self.values[10], self.values[11], self.values[15],
                           *[_gain(self.values[i]-(3 if i == 62 else 0)) for i in (60, 61, 62)], self.source[3],
                           topology['normalization'], topology['dc'],
                           _gain(struct.unpack_from('<f', parameters, 134)[0]),
                           *[x['gain'] for x in topology['allpass']], *gains], np.float32)
        _check(self.library.ft_room_initialize(self.state, (ctypes.c_uint32*len(config))(*config), _pointer(floats)))
        total = self.library.ft_room_total(self.state)
        if not 1 <= total <= 4_000_000:
            raise ValueError('RoomVerb topology exceeds its buffer bound')
        self.memory = np.zeros(total, np.float32)

    def _validate(self):
        if not all(math.isfinite(v) for v in self.values.values()):
            raise ValueError('RoomVerb requires finite controls')
        if not .01 <= self.values[10] <= 60 or not .1 <= self.values[11] <= 20:
            raise ValueError('Invalid RoomVerb decay/damping')
        if not 0 <= self.values[15] <= 100:
            raise ValueError('Invalid RoomVerb diffusion')
        if not all(-200 <= self.values[i] <= 24 for i in (60, 61, 62)):
            raise ValueError('Invalid RoomVerb mix gain')

    def set_parameter(self, identity, value):
        if identity not in self.values or not math.isfinite(value):
            raise ValueError('Unsupported RoomVerb control')
        old = self.values[identity]
        self.values[identity] = float(np.float32(value))
        try:
            self._validate()
        except ValueError:
            self.values[identity] = old
            raise
        _check(self.library.ft_room_parameter(self.state, identity,
               _gain(self.values[identity]-(3 if identity == 62 else 0)) if identity >= 60 else self.values[identity]))

    def reset(self):
        _check(self.library.ft_room_reset(self.state, _pointer(self.memory)))

    def process(self, audio):
        audio = np.asarray(audio, np.float32)
        if audio.shape != (128, self.channels) or not np.isfinite(audio).all():
            raise ValueError('RoomVerb requires 128 finite frames')
        result = np.array(audio, np.float32, order='C', copy=True)
        _check(self.library.ft_room_process(self.state, _pointer(self.memory), _pointer(result)))
        if not np.isfinite(result).all():
            raise ValueError('Independent RoomVerb produced nonfinite audio')
        return result

    def rtpc_updates(self):
        return []
