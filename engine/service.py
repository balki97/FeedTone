"""Private pipe service belonging to this plugin's own VST transport."""
import json
from pathlib import Path
import struct
import sys

import numpy as np

from .graph import ToneGraph
from .resample import Resampler

MAGIC = 0x53534652
_NATIVE = Path(__file__).resolve().parents[1]/'native'
_REQUIRED_KERNELS = ('DSPKernels.dll', 'FilterKernels.dll', 'TremoloKernels.dll',
                     'AmpKernels.dll', 'CabinetFFT.dll', 'DelayKernels.dll',
                     'PhaserKernels.dll', 'PitchKernels.dll', 'PitchFFT.dll', 'ReverbKernels.dll',
                     'ChorusKernels.dll', 'RoomKernels.dll')


def require_kernels():
    from .runtime import kernel_path
    missing = [name for name in _REQUIRED_KERNELS if not kernel_path(name.removesuffix('.dll')).is_file()]
    if missing:
        raise RuntimeError('Standalone DSP package is incomplete: ' + ', '.join(missing))


def _read(stream, count):
    result = bytearray()
    while len(result) < count:
        chunk = stream.read(count-len(result))
        if not chunk:
            raise EOFError('Audio transport closed')
        result.extend(chunk)
    return result


def serve(definition, source, sink):
    graph = ToneGraph(definition)
    channels = 2
    rate = 48000
    incoming = outgoing = None
    pending = np.empty((0, 1), np.float32)
    output = np.zeros((128, 2), np.float32)
    pending_controls = {}

    def reply(op, frames=0, payload=b''):
        sink.write(struct.pack('<8I', MAGIC, 1, op, 0, frames, channels, rate, 128 if rate == 48000 else 192))
        sink.write(payload)
        sink.flush()

    try:
        reply(0)
        while True:
            magic, version, op, first, second = struct.unpack('<5I', _read(source, 20))
            if magic != MAGIC or version != 1:
                raise ValueError('Invalid audio transport header')
            if op == 7:
                if first not in (44100, 48000) or second not in (1, 2):
                    raise ValueError('Audio transport requires 44.1 or 48 kHz mono/stereo')
                rate, channels = first, second
                incoming = Resampler(rate, 48000, 1) if rate != 48000 else None
                outgoing = Resampler(48000, rate, 2, delay=32 * 48000 / rate) if rate != 48000 else None
                graph.close()
                graph = ToneGraph(definition)
                pending = np.empty((0, 1), np.float32)
                output = np.zeros((128, 2), np.float32)
                pending_controls.clear()
                reply(op)
            elif op == 1:
                if not 0 < first <= 65536 or second:
                    raise ValueError('Invalid audio transport frame count')
                audio = np.frombuffer(_read(source, first*channels*4), dtype='<f4').reshape(first, channels)
                mono = audio[:, :1] if channels == 1 else audio[:, :1] * .5 + audio[:, 1:2] * .5
                converted = incoming.process(mono) if incoming else mono
                pending = np.concatenate((pending, converted))
                while len(pending) >= 128:
                    block = graph.process(pending[:128])
                    output = np.concatenate((output, outgoing.process(block) if outgoing else block))
                    pending = pending[128:]
                    for identity, value in pending_controls.items():
                        graph.set_control(identity, value)
                    pending_controls.clear()
                if len(output) < first:
                    raise RuntimeError('Audio transport output underrun')
                rendered, output = output[:first], output[first:]
                reply(op, first, rendered[:, :channels].astype('<f4').tobytes())
            elif op == 2:
                if second != 8:
                    raise ValueError('Invalid control payload')
                value = struct.unpack('<d', _read(source, 8))[0]
                if not np.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError('Control must be normalized to 0..1')
                if len(pending):
                    pending_controls[first] = value
                else:
                    graph.set_control(first, value)
                reply(op)
            elif op == 3:
                graph.reset()
                if incoming:
                    incoming.reset()
                    outgoing.reset()
                pending = np.empty((0, 1), np.float32)
                output = np.zeros((128, 2), np.float32)
                pending_controls.clear()
                reply(op)
            elif op == 4:
                reply(op)
                break
            else:
                raise ValueError('Unknown audio transport operation')
    finally:
        graph.close()


def main():
    require_kernels()
    with open(sys.argv[1], encoding='utf-8') as file:
        definition = json.load(file)
    if len(sys.argv) > 2 and sys.argv[2] == '--validate':
        graph = ToneGraph(definition)
        try:
            graph.process(np.zeros((128, 1), np.float32))
        finally:
            graph.close()
        return
    serve(definition, sys.stdin.buffer, sys.stdout.buffer)


if __name__ == '__main__':
    main()
