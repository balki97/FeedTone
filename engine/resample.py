"""Streaming band-limited conversion at the device/48 kHz DSP boundary."""
import math

import numpy as np


class Resampler:
    def __init__(self, source_rate, target_rate, channels, delay=32):
        common = math.gcd(source_rate, target_rate)
        self.source = source_rate // common
        self.target = target_rate // common
        self.channels = channels
        self.delay = delay
        self.offsets = np.arange(-31, 33)
        phases = np.arange(self.target) / self.target
        distance = self.offsets[None, :] - phases[:, None]
        cutoff = min(1, target_rate / source_rate) * .94
        window = np.i0(8.6 * np.sqrt(np.maximum(0, 1 - (distance / 32) ** 2))) / np.i0(8.6)
        window[np.abs(distance) >= 32] = 0
        self.weights = np.sinc(cutoff * distance) * window
        self.weights /= self.weights.sum(axis=1, keepdims=True)
        self.reset()

    def reset(self):
        self.history = np.empty((0, self.channels), np.float32)
        self.received = self.emitted = 0

    def process(self, audio):
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 2 or audio.shape[1] != self.channels:
            raise ValueError('Invalid resampler channel count')
        start = self.received - len(self.history)
        samples = np.concatenate((self.history, audio))
        self.received += len(audio)
        end = (self.received * self.target + self.source - 1) // self.source
        positions = np.arange(self.emitted, end, dtype=np.int64)
        # Delay is fractional only on the return path, to report an integer host latency.
        ticks = positions * self.source - round(self.delay * self.target)
        centers, phases = np.divmod(ticks, self.target)
        indices = centers[:, None] + self.offsets - start
        valid = (indices >= 0) & (indices < len(samples))
        if len(samples):
            gathered = samples[np.clip(indices, 0, len(samples) - 1)]
            result = np.einsum('ntc,nt->nc', gathered, self.weights[phases] * valid).astype(np.float32)
        else:
            result = np.empty((0, self.channels), np.float32)
        self.history = samples[-(math.ceil(self.delay) + 34):].copy()
        self.emitted = end
        return result
