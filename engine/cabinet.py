"""Independent packed-spectrum convolution; no original native code is loaded.

Recovered equations: REA0xe84c00,0xe84a80. FFT numerical parity is bounded,
not bit-exact; see research/CABINET.md.
"""
import hashlib
import json
import math
import struct
from pathlib import Path

import numpy as np
from .cabinet_fft import CompiledCabinet, available


class SpectraBank:
    def __init__(self, directory):
        directory = Path(directory)
        self.manifest = json.loads((directory / 'cabinets.json').read_text())
        archive = directory / 'cabinets.npz'
        if self.manifest.get('schema') != 'feedback.cabinet-spectra.v1':
            raise ValueError('Unsupported cabinet coefficient data')
        if hashlib.sha256(archive.read_bytes()).hexdigest() != self.manifest['archive_sha256']:
            raise ValueError('Cabinet coefficient archive differs from its manifest')
        self.archive = np.load(archive, allow_pickle=False)

    def get(self, identity):
        record = self.manifest['resources'][str(identity)]
        raw = self.archive[str(identity)]
        if raw.dtype != np.dtype('<f4') or list(raw.shape) != record['shape'] or raw.shape[1:] != (129, 2):
            raise ValueError('Invalid cabinet coefficient dimensions')
        if hashlib.sha256(raw.tobytes()).hexdigest() != record['coefficients_sha256']:
            raise ValueError('Cabinet coefficients differ from their manifest')
        if not np.isfinite(raw).all() or np.any(raw[:, -1]):
            raise ValueError('Invalid cabinet spectrum')
        return raw[..., 0].astype(np.float64) + 1j * raw[..., 1].astype(np.float64)

    def close(self):
        self.archive.close()


class PackedWetPath:
    def __init__(self, spectra):
        self.spectra = np.asarray(spectra, dtype=np.complex128)
        if self.spectra.ndim != 2 or self.spectra.shape[1] != 129 or not len(self.spectra):
            raise ValueError('Expected nonempty 256-point real spectra')
        if not np.isfinite(self.spectra).all() or np.any(self.spectra[:, -1]):
            raise ValueError('Invalid packed spectral values')
        self.reset()

    def reset(self):
        self.ring = np.zeros_like(self.spectra)
        self.index = 0

    def process(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        if samples.shape != (128,) or not np.isfinite(samples).all():
            raise ValueError('Cabinets require 128 finite mono samples')
        transformed = np.fft.rfft(np.pad(samples.astype(np.float64), (0, 128)))
        products = transformed * self.spectra
        remaining = len(self.ring)-self.index
        self.ring[self.index:] += products[:remaining]
        self.ring[:self.index] += products[remaining:]
        output = np.fft.irfft(self.ring[self.index], n=256)[128:].copy()
        self.ring[self.index] = 0
        self.index = (self.index + 1) % len(self.ring)
        return output


class Cabinet:
    plugin_id = 0x7f0003

    def __init__(self, parameters, spectra, sample_rate=48000, channels=1):
        if len(parameters) != 48 or sample_rate != 48000 or channels != 1:
            raise ValueError('Independent cabinet currently supports 48kHz mono only')
        values = struct.unpack('<11fI', parameters)
        if not all(math.isfinite(v) for v in values[:-1]) or values[:2] != (0.0, 0.0) or values[-1] != 1:
            raise ValueError('Cabinet delay or routing mode is not reconstructed')
        exponent = float(np.float32(0.05))
        self.dry_gain = float(np.float32(math.pow(10, values[9] * exponent)))
        self.wet_gain = float(np.float32(math.pow(10, values[10] * exponent)))
        self.compiled = CompiledCabinet(spectra, self.dry_gain, self.wet_gain) if available() else None
        self.wet = None if self.compiled else PackedWetPath(spectra)
        self.channels = 1

    def reset(self):
        (self.compiled or self.wet).reset()

    def process(self, audio):
        audio = np.asarray(audio, dtype=np.float32)
        if audio.shape != (128, 1) or not np.isfinite(audio).all():
            raise ValueError('Cabinet requires 128 finite mono frames')
        if self.compiled is not None:
            return self.compiled.process(audio)
        wet = self.wet.process(audio[:, 0])
        return (wet * self.wet_gain + audio[:, 0].astype(np.float64) * self.dry_gain).astype(np.float32)[:, None]

    def set_parameter(self, identity, value):
        raise NotImplementedError('Live cabinet parameter ramps are not yet reconstructed')

    def rtpc_updates(self):
        return []
