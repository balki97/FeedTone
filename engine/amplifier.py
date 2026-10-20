"""Independent amplifier stage decoding, distortion models and EQ mixing.

The distortion plugin includes its crossover. The amp EQ plugin includes all
seven embedded paths and the six cabinet-shaping presets used by this catalog.
No executable reference code or helper is used by this runtime module.
"""
from dataclasses import dataclass
import math
import struct

import numpy as np

from . import amp_kernels


@dataclass(frozen=True)
class DistortionStage:
    band: int
    stage: int
    controls: tuple[float, ...]
    model: int


@dataclass(frozen=True)
class MultibandParameters:
    stages: tuple[DistortionStage, ...]
    boundaries: tuple[float, float]

    @classmethod
    def decode(cls, parameters: bytes):
        """Decode plugin 0x91033's bank layout, verified at 0xf3ef80/0xf3fb00.

        Control meanings are deliberately left unnamed until their inner
        setters are recovered. No guessed nonlinear model is substituted.
        """
        if len(parameters) != 152:
            raise ValueError("Multiband distortion requires 152 parameter bytes")
        stages = []
        for index in range(6):
            *controls, model = struct.unpack_from('<5fI', parameters, index * 24)
            if not all(math.isfinite(value) for value in controls):
                raise ValueError("Nonfinite distortion control")
            stages.append(DistortionStage(index // 2, index % 2, tuple(controls), model))
        boundaries = struct.unpack_from('<2f', parameters, 144)
        if not all(math.isfinite(value) for value in boundaries):
            raise ValueError("Nonfinite band boundary control")
        return cls(tuple(stages), boundaries)

    def encode(self) -> bytes:
        return b''.join(struct.pack('<5fI', *stage.controls, stage.model)
                        for stage in self.stages) + struct.pack('<2f', *self.boundaries)


_DB_SCALE = 0.115129254758358
_MODEL_NORMALIZATION_DB = {0: 0, 1: -8, 4: 0, 5: -6, 6: -6, 7: -3, 9: -6, 10: 0}


def _f(value):
    return np.asarray(value, dtype=np.float32).astype(np.float64)


def _exp(value):
    return _f(np.exp(_f(value)))


class DistortionModel:
    """Recovered scalar distortion stage, without the amplifier crossover/EQ.

    Supported model IDs are the eight observed in the current amplifier catalog.
    Native x87 rounding and math-library differences remain measured separately;
    this class is not a complete amplifier or a full-chain parity assertion.
    """
    def __init__(self, stage: DistortionStage):
        if stage.model not in _MODEL_NORMALIZATION_DB:
            raise NotImplementedError(f"Unreconstructed distortion model {stage.model}")
        if len(stage.controls) != 5 or not all(math.isfinite(x) for x in stage.controls):
            raise ValueError("Distortion stage needs five finite controls")
        self.model = stage.model
        input_db, drive, self.shape, mix, output_db = map(float, np.asarray(stage.controls, dtype=np.float32))
        if not 0 <= drive <= 10 or not 0 <= self.shape <= 1 or not 0 <= mix <= 100:
            raise ValueError("Distortion drive, shape or mix out of range")
        self.input_gain = float(_exp(input_db * _DB_SCALE))
        self.drive_gain = float(_exp(_f(drive * 4) * _DB_SCALE))
        self.output_gain = float(_exp(output_db * _DB_SCALE))
        fraction = float(_f(mix / 100))
        self.dry_gain = float(_f(1 - fraction))
        self.wet_gain = float(_f(_exp(_MODEL_NORMALIZATION_DB[self.model] * _DB_SCALE) * fraction))

    def process(self, audio):
        source = np.asarray(audio, dtype=np.float32)
        if source.ndim not in (1, 2) or not np.isfinite(source).all():
            raise ValueError("Audio must be finite mono or channel-interleaved samples")
        if self.model == 0:
            return source.copy()
        x = _f(source.astype(np.float64) * self.input_gain)
        z = _f(x * self.drive_gain)
        wet_gain = self.wet_gain
        if self.model == 1:
            wet = _f(np.arctan(_f(x * self.drive_gain * 3.309999942779541)))
        elif self.model == 4:
            u = _f(z * 0.6863059997558594)
            positive = _exp(u)
            term = _f(_f(np.sqrt(np.abs(u))) * -0.75)
            term = _f(_exp(term) + 1)
            term = _f(term * -u)
            wet = _f((positive - _exp(term)) / (_exp(-u) + positive))
        elif self.model == 5:
            threshold = float(_exp(-1.2433959245681763))
            magnitude = np.abs(z)
            knee = _f(2 - magnitude * 3)
            curved = _f(np.sign(z) * (3 - knee * knee) / 3)
            wet = np.where(magnitude < threshold, _f(z * 2),
                           np.where(magnitude < threshold * 2, curved, np.sign(z)))
        elif self.model == 6:
            factor = float(_exp(_f(self.shape * 30) * _DB_SCALE))
            if factor == 1:
                wet = z
            else:
                v = _f(z * factor)
                wet = _f(np.where(v > 0, 1 - 1 / (1 + np.abs(v)),
                                  1 / (1 + np.abs(v)) - 1))
        elif self.model == 7:
            threshold = float(_exp(_f(self.shape * -48) * _DB_SCALE))
            wet_gain = float(_f(_exp(_f(self.shape * 35) * _DB_SCALE) * wet_gain))
            wet = np.clip(z, -threshold, threshold)
        elif self.model == 9:
            v = _f(1 + z - 0.032846998423337936)
            v = np.clip(v, -1, 1)
            power = _f(v ** 12)
            negative = _f(((-z - 0.032846998423337936) * 0.3333333432674408 +
                           (1 - power) + 0.009999999776482582) * -0.75 + 0.23499999940395355)
            positive = _f(z * 3.9375 + z * z * -6.1519999504089355)
            wet = np.where(z < -0.08905, negative,
                           np.where(z <= 0.320018, positive, 0.600350022315979))
        else:  # model 10 has a final polarity inversion, including the dry path.
            wet = _f(-np.sign(z) * _f(1 - _exp(-np.abs(z))))
        result = (wet * wet_gain + x * self.dry_gain) * self.output_gain
        if self.model == 10:
            result = -result
        return np.asarray(result, dtype=np.float32)


def mix_amp_eq(wet, dry, wet_start, wet_end, dry_start, dry_end):
    """Reconstructed 0xf4cd80 per-channel gain ramp; target is next block's start."""
    wet, dry = np.asarray(wet, dtype=np.float32), np.asarray(dry, dtype=np.float32)
    if wet.ndim not in (1, 2) or wet.shape != dry.shape:
        raise ValueError("Wet/dry audio shapes must match")
    if not np.isfinite(wet).all() or not np.isfinite(dry).all():
        raise ValueError("Nonfinite audio")
    gains = np.asarray([wet_start, wet_end, dry_start, dry_end], dtype=np.float32)
    if not np.isfinite(gains).all():
        raise ValueError("Nonfinite gain")
    a, target_a, b, target_b = gains
    count = len(wet)
    if not count:
        return wet.copy()
    if count <= 128 and amp_kernels.available():
        return amp_kernels.mix(wet, dry, *map(float, gains))
    step_a = np.float32((float(target_a) - float(a)) / count)
    step_b = np.float32((float(target_b) - float(b)) / count)
    result = np.empty_like(wet)
    for i in range(count):
        result[i] = np.float32(wet[i] * a) + np.float32(dry[i] * b)
        a, b = np.float32(a + step_a), np.float32(b + step_b)
    return result


class _FirstOrder:
    def __init__(self, frequency, high, channels, sample_rate):
        self.high, self.sample_rate = high, sample_rate
        self.state = np.zeros(channels, dtype=np.float64)
        self.configure(frequency)

    def configure(self, frequency):
        # Original prewarp divides by sample rate twice; standard bilinear
        # filter coefficients do not reproduce the original implementation.
        c = 1 / (math.tan(math.pi * frequency / self.sample_rate ** 2) * self.sample_rate)
        self.b0 = float(_f(c / (1 + c) if self.high else 1 / (1 + c)))
        self.b1 = -self.b0 if self.high else self.b0
        self.a1 = float(_f((1 - c) / (1 + c)))

    def process(self, audio):
        if amp_kernels.available():
            result, self.state = amp_kernels.first_order(audio, self.state, self.b0, self.b1, self.a1)
            return result
        result = np.empty_like(audio)
        bias = float(_f(1e-10))
        for index, sample in enumerate(audio):
            x = sample.astype(np.float64)
            y = _f(self.state + x * self.b0)
            state = _f(x * self.b1 - y.astype(np.float64) * self.a1 + bias)
            self.state = np.where((state > -bias) & (state < bias), 0, state)
            result[index] = y
        return result


class MultibandDistortion:
    """Independent 0x91033 processor for the verified 48 kHz/128-frame path.

    The current catalog uses fixed 20/20000 Hz crossover boundaries. Ordered
    positive boundaries below Nyquist are supported; boundary bypass modes and
    other quantum sizes are rejected until independently verified.
    """
    plugin_id = 0x91033

    def __init__(self, parameters, sample_rate=48000, channels=1, initial_parameters=None):
        if sample_rate != 48000 or channels not in (1, 2):
            raise ValueError("Multiband distortion requires 48 kHz mono or stereo")
        self.sample_rate, self.channels = sample_rate, channels
        self.parameters = bytes(parameters)
        for identity, value in (initial_parameters or {}).items():
            is_model = identity in (5, 11, 17, 23, 29, 35)
            if not 0 <= identity < 38 or not math.isfinite(value) or (is_model and value != int(value)):
                raise ValueError("Invalid initial multiband parameter")
            encoded = struct.pack('<I', int(value)) if is_model else struct.pack('<f', value)
            position = identity * 4
            self.parameters = self.parameters[:position] + encoded + self.parameters[position + 4:]
        self._configure()

    def _configure(self):
        decoded = MultibandParameters.decode(self.parameters)
        low, high = decoded.boundaries
        if not 0 < low <= high < self.sample_rate / 2:
            raise NotImplementedError("Crossover boundary bypass modes are unreconstructed")
        models = [DistortionModel(stage) for stage in decoded.stages]
        settings = [(low, False), (high, False), (low, True), (high, True)]
        if hasattr(self, 'filters'):
            for effect, (frequency, _) in zip(self.filters, settings):
                effect.configure(frequency)
        else:
            self.filters = [_FirstOrder(frequency, highpass, self.channels, self.sample_rate)
                            for frequency, highpass in settings]
        self.models = models

    def reset(self):
        # Original 0xf3f2e0 delegates to 0xf3faf0, whose body is a bare return.
        pass

    def rtpc_updates(self):
        return []

    def set_parameter(self, parameter_id, value):
        if not 0 <= parameter_id < 38 or not math.isfinite(value):
            raise ValueError("Invalid multiband parameter")
        is_model = parameter_id in (5, 11, 17, 23, 29, 35)
        if is_model and (value != int(value) or not 0 <= value <= 0xffffffff):
            raise ValueError("Invalid distortion model selector")
        replacement = struct.pack('<I', int(value)) if is_model else struct.pack('<f', value)
        previous = self.parameters
        position = parameter_id * 4
        self.parameters = previous[:position] + replacement + previous[position + 4:]
        try:
            self._configure()
        except (ValueError, NotImplementedError):
            self.parameters = previous
            raise

    def process(self, audio):
        source = np.asarray(audio, dtype=np.float32)
        if source.ndim != 2 or source.shape[1] != self.channels or not 1 <= len(source) <= 128:
            raise ValueError("Multiband audio requires 1..128 frames by configured channels")
        if not np.isfinite(source).all():
            raise ValueError("Nonfinite audio")
        frames = len(source)
        padded = np.zeros((128, self.channels), dtype=np.float32)
        padded[:frames] = source
        low = self.filters[0].process(padded)
        middle = self.filters[2].process(self.filters[1].process(padded))
        high = self.filters[3].process(padded)
        # The original render entry point invokes stage zero for each band.
        bands = [self.models[index * 2].process(samples).astype(np.float64)
                 for index, samples in enumerate((low, middle, high))]
        result = np.asarray(bands[0] + bands[1] + bands[2], dtype=np.float32)
        if not np.isfinite(result).all():
            raise ValueError("Distortion produced nonfinite audio")
        return result[:frames]


def _amp_filter_coefficients(kind, frequency, resonance, sample_rate, gain=0, *, damping=None, q=None, span=12):
    ratio = min(max(frequency / sample_rate, .00020833333333333335), .4583333333333333)
    k = math.tan(ratio * math.pi)
    squared = k * k
    if kind in ('highpass', 'lowpass'):
        damping = damping if damping is not None else (1 - math.sqrt(max(resonance * .01, 0)) * .8) * 1.414
        reciprocal = 1 / (k * damping + 1 + squared)
        b = [reciprocal, reciprocal * -2, reciprocal] if kind == 'highpass' else [
            reciprocal * squared, squared * 2 * reciprocal, reciprocal * squared]
        return np.asarray([*b, (squared * 2 - 2) * reciprocal,
                           ((1 - k * damping) + squared) * reciprocal], dtype=np.float32)
    if kind != 'peak':
        raise ValueError("Unknown amplifier filter type")
    q = q if q is not None else resonance * .01 * resonance * .01 * 9 + 1
    damping = (k + 1) / q
    level = 10 ** (gain * .05)
    numerator_constant = denominator_constant = 1.
    amount = abs(gain / span)
    if level < 1:
        level = 1 / level
        denominator_damping, numerator_damping = level * damping, damping
        denominator_constant = min(max(1 - amount + (ratio * denominator_damping + 1 - ratio) * amount, 1), level)
    else:
        denominator_damping, numerator_damping = damping, level * damping
        numerator_constant = min(max(1 - amount + (ratio * numerator_damping + 1 - ratio) * amount, 1), level)
    numerator_damping *= k
    denominator_damping *= k
    reciprocal = 1 / (denominator_damping + denominator_constant + squared)
    return np.asarray([(numerator_damping + numerator_constant + squared) * reciprocal,
                       (squared * 2 - numerator_constant * 2) * reciprocal,
                       ((numerator_constant - numerator_damping) + squared) * reciprocal,
                       (squared * 2 - denominator_constant * 2) * reciprocal,
                       ((denominator_constant - denominator_damping) + squared) * reciprocal], dtype=np.float32)


class _AmpBiquads:
    def __init__(self, coefficients, channels):
        self.coefficients = np.asarray(coefficients, dtype=np.float32)
        self.state = np.zeros((len(coefficients), 4, channels), dtype=np.float32)

    def configure(self, coefficients):
        self.coefficients = np.asarray(coefficients, dtype=np.float32)

    def process(self, audio):
        if amp_kernels.available():
            return amp_kernels.biquads(audio, self.coefficients, self.state)
        result = np.asarray(audio, dtype=np.float32).copy()
        for coefficients, state in zip(self.coefficients, self.state):
            b0, b1, b2, a1, a2 = coefficients
            for index, x in enumerate(result):
                x = x.copy()
                y = np.float32(state[0] * b1 + x * b0)
                y = np.float32(y + state[1] * b2)
                y = np.float32(y - state[2] * a1)
                y = np.float32(y - state[3] * a2)
                state[1], state[0] = state[0].copy(), x
                state[3], state[2] = state[2].copy(), y
                result[index] = y
        return result


def _amp_time_coefficient(milliseconds, sample_rate):
    count = milliseconds * .001 * sample_rate
    return np.float32(min(1, 1 / count) if count else 1)


class _AmpGate:
    def __init__(self, parameters, channels, sample_rate):
        self.sample_rate = sample_rate
        self.counter = np.zeros(channels, dtype=np.float32)
        self.level = np.zeros(channels, dtype=np.float32)
        self.configure(parameters)

    def configure(self, parameters):
        threshold, attenuation, attack, hold, release = parameters
        self.threshold = np.float32(10 ** (threshold * .05))
        self.attenuation = np.float32(10 ** (attenuation * .05))
        self.hold = np.float32(int(hold * .001 * self.sample_rate))
        self.attack = _amp_time_coefficient(attack, self.sample_rate)
        self.release = _amp_time_coefficient(release, self.sample_rate)

    def process(self, audio):
        result = np.empty_like(audio)
        for index, sample in enumerate(audio):
            below = np.abs(sample) < self.threshold
            target = np.where(below, self.attenuation, np.float32(1))
            counter = np.where(below, self.counter, self.hold) - np.float32(1)
            target = np.where(counter > 0, np.float32(1), target)
            self.counter = np.maximum(counter, np.float32(0))
            difference = np.float32(target - self.level)
            coefficient = np.where(difference > 0, self.attack, self.release)
            self.level = np.float32(np.float32(coefficient * difference) + self.level)
            result[index] = np.float32(sample * self.level)
        return result


class _AmpBitcrusher:
    def __init__(self, parameters, channels, sample_rate):
        self.sample_rate, self.channels = sample_rate, channels
        self.counter = np.zeros(channels, dtype=np.float32)
        self.held = np.zeros(channels, dtype=np.float32)
        self.filter = _AmpBiquads([[1, 0, 0, 0, 0]], channels)
        self.configure(parameters)

    def configure(self, parameters):
        depth, self.period, tone = parameters
        bits = (24, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 0)
        if depth not in range(len(bits)) or not 0 <= tone <= 100 or self.period < 0:
            raise ValueError("Invalid amplifier bitcrusher control")
        self.shift = 24 - bits[depth]
        self.quantization = np.float32(2. ** -self.shift)
        upper = 20000 - math.sqrt(tone * .01) * 19000
        a = 1 / (math.tan(math.pi * 20 / self.sample_rate) + 1)
        hp = (a, -a, (math.tan(math.pi * 20 / self.sample_rate) - 1) * a)
        k = math.tan(math.pi * min(upper / self.sample_rate, .4583333333333333))
        a = 1 / (k + 1)
        lp = (a * k, a * k, (k - 1) * a)
        self.filter.configure([[lp[0] * hp[0], hp[1] * lp[0] + lp[1] * hp[0],
                                hp[1] * lp[1], lp[2] + hp[2], hp[2] * lp[2]]])

    def process(self, audio):
        quantized = np.empty_like(audio)
        for index, sample in enumerate(audio):
            scaled = np.float32(np.float32(sample * np.float32(8388607)) * self.quantization)
            integer = np.trunc(np.float32(scaled + np.where(scaled > 0, np.float32(.5), np.float32(-.5)))).astype(np.int64)
            shifted = (integer << self.shift).astype(np.int32)
            level = np.float32(shifted.astype(np.float32) * np.float32(1.192093e-7))
            self.counter = np.maximum(np.float32(self.counter - np.float32(1)), np.float32(0))
            self.held = np.where(self.counter <= 0, level, self.held)
            self.counter = np.where(self.counter <= 0, np.float32(self.period), self.counter)
            quantized[index] = self.held
        return self.filter.process(quantized)


class _AmpNoise:
    def __init__(self, parameters, channels, sample_rate):
        self.sample_rate, self.channels = sample_rate, channels
        self.seed = 0xbf7c9
        self.counter = np.zeros(channels, dtype=np.float32)
        self.level = np.zeros(channels, dtype=np.float32)
        self.highpass = _AmpBiquads([[1, 0, 0, 0, 0]], channels)
        self.lowpass = _AmpBiquads([[1, 0, 0, 0, 0]], channels)
        self.configure(parameters)

    def configure(self, parameters):
        noise_db, low_frequency, high_frequency, threshold_db, reduced_db, release = parameters
        self.noise_gain = np.float32(10 ** ((noise_db - 6) * .05) if noise_db - 6 >= -143 else 0)
        self.threshold = np.float32(10 ** (threshold_db * .05))
        self.reduced = np.float32(10 ** (reduced_db * .05))
        self.attack = _amp_time_coefficient(1, self.sample_rate)
        self.release = _amp_time_coefficient(release, self.sample_rate)
        self.hold = np.float32(int(self.sample_rate * .001))
        self.highpass.configure([_amp_filter_coefficients('highpass', high_frequency, 0, self.sample_rate)])
        self.lowpass.configure([_amp_filter_coefficients('lowpass', low_frequency, 0, self.sample_rate)])

    def process(self, audio):
        noise = np.empty_like(audio)
        for channel in range(self.channels):
            for index in range(len(audio)):
                self.seed = (self.seed * 0x343fd + 0x269ec3) & 0xffffffff
                signed = self.seed if self.seed < 0x80000000 else self.seed - 0x100000000
                noise[index, channel] = np.float32(np.float32(signed) * np.float32(2.3283064365386963e-10))
        noise = np.float32(noise * self.noise_gain)
        noise = self.highpass.process(self.lowpass.process(noise))
        result = np.empty_like(audio)
        for index, sample in enumerate(audio):
            active = np.abs(sample) > self.threshold
            target = np.where(active, self.reduced, np.float32(1))
            counter = np.float32(np.where(active, self.hold, self.counter) - np.float32(1))
            target = np.where(counter > 0, self.reduced, target)
            self.counter = np.maximum(counter, np.float32(0))
            difference = np.float32(target - self.level)
            coefficient = np.where(difference > 0, self.release, self.attack)
            self.level = np.float32(np.float32(coefficient * difference) + self.level)
            result[index] = np.float32(sample + np.float32(noise[index] * self.level))
        return result


def _amp_shelf_coefficients(frequency, shape, gain, sample_rate):
    ratio = min(max(frequency / sample_rate, .00020833333333333335), .4583333333333333)
    k = math.tan(ratio * math.pi)
    squared = k * k
    level = 10 ** (gain * .05)
    tilt = -1.6 * shape ** .25
    emphasis = math.sqrt(abs(gain / 18)) * tilt * .5 + math.sqrt(2)
    if gain <= 0:
        numerator_level, denominator_level = 1., 1 / level
        numerator_linear = (math.sqrt(2) * .85 + .15) * k
        denominator_linear = (emphasis * .85 / math.sqrt(level) + .15) * k
    else:
        numerator_level, denominator_level = level, 1.
        numerator_linear = (emphasis * .85 * math.sqrt(level) + .15) * k
        denominator_linear = (math.sqrt(2) * .85 + .15) * k
    reciprocal = 1 / (denominator_linear + .85 + denominator_level * squared)
    return np.asarray([(numerator_linear + .85 + numerator_level * squared) * reciprocal,
                       (2 * squared * numerator_level - 1.7) * reciprocal,
                       ((.85 - numerator_linear) + numerator_level * squared) * reciprocal,
                       (2 * squared * denominator_level - 1.7) * reciprocal,
                       ((.85 - denominator_linear) + denominator_level * squared) * reciprocal], dtype=np.float32)


_AMP_PRESETS = {
    0: [('hp1', 56, 0, 0, False), ('shelf', 237, .75, 4.3, True),
        ('peak', 336, 6.8, 4.1, True), ('peak', 595, 12.8, 8.6, True),
        ('peak', 868, 9.3, -7.3, True), ('peak', 1000, 1, 0, True), ('lp2', 6000, 1.4, 0, False)],
    5: [('hp2', 99, 1.4, 0, False), ('peak', 290, 5, 18, True),
        ('peak', 780, 12, -3, True), ('peak', 999, 4, 4.5, True),
        ('peak', 1650, 16, 8.8, True), ('peak', 1000, 1, 0, True), ('lp2', 8760, .6, 0, False)],
    62: [('hp2', 113.85, .72, 0, False), ('peak', 339.34, 11.77, 18, True),
         ('peak', 697.48, 4.59, 11.36, True), ('peak', 2316.84, 16, -5.14, True),
         ('peak', 3720.43, 11.77, -18, True), ('peak', 9977.2, 11.77, -18, True), ('lp2', 3013.23, .65, 0, False)],
    64: [('hp2', 203.28, .25, 0, False), ('shelf', 40, .125, 7.29, True),
         ('peak', 885.72, 4.31, -4.93, True), ('peak', 1000, .4, -12, False),
         ('peak', 2442.16, 6.55, 6, True), ('peak', 4079, 5.96, 5.57, True), ('lp2', 12694.49, 1.41, 0, False)],
    65: [('hp2', 20, 1.41, 0, False), ('hp2', 20, 1.41, 0, False),
         ('peak', 120.69, 14.98, -12, True), ('peak', 582.53, 14.98, -5.57, True),
         ('peak', 4125.69, 16, 4.29, True), ('peak', 7057.47, 6.65, 3.64, True), ('lp2', 18187, 1.41, 0, False)],
    115: [('hp2', 145.96, .71, 0, False), ('peak', 231.71, 5.08, -12.21, True),
          ('peak', 367.01, 13.18, 9.64, True), ('peak', 1957.62, 8.65, -8.36, True),
          ('peak', 2442.16, 6.65, 6.21, True), ('lp2', 3237.88, 1.15, 0, False), ('lp2', 3237.88, 1.15, 0, False)],
}


class _AmpPresetShaper:
    def __init__(self, parameters, channels, sample_rate):
        self.sample_rate, self.channels = sample_rate, channels
        self.filter = _AmpBiquads([[1, 0, 0, 0, 0]] * 7, channels)
        self.configure(parameters)

    def configure(self, parameters):
        preset, amount = parameters
        if preset not in _AMP_PRESETS:
            raise NotImplementedError(f"Unreconstructed amplifier shaper preset {preset}")
        coefficients = []
        for kind, frequency, shape, gain, scaled in _AMP_PRESETS[preset]:
            if scaled:
                frequency *= amount * .01
            if kind == 'hp1':
                k = math.tan(math.pi * frequency / self.sample_rate)
                b0 = 1 / (k + 1)
                coefficient = [b0, -b0, 0, (k - 1) * b0, 0]
            elif kind == 'shelf':
                coefficient = _amp_shelf_coefficients(frequency, shape, gain, self.sample_rate)
            else:
                coefficient = _amp_filter_coefficients(
                    {'hp2': 'highpass', 'lp2': 'lowpass', 'peak': 'peak'}[kind], frequency,
                    0, self.sample_rate, gain, damping=shape, q=shape, span=18)
            coefficients.append(coefficient)
        self.filter.configure(coefficients)
        normalization = {0: -.9, 5: -8.7, 62: -5.3, 64: None, 65: -4.3, 115: -.5}[preset]
        self.gain = np.float32(1 if normalization is None else 10 ** (normalization * .05))

    def process(self, audio):
        return np.float32(self.filter.process(audio) * self.gain)


class AmpEqualizer:
    """Independent 0x6e1003 processor; unverified preset IDs fail explicitly."""
    plugin_id = 0x6e1003

    def __init__(self, parameters, sample_rate=48000, channels=1, initial_parameters=None):
        if len(parameters) != 139 or sample_rate != 48000 or channels not in (1, 2):
            raise ValueError("Amp EQ requires 139 bytes and 48 kHz mono/stereo")
        self.sample_rate, self.channels = sample_rate, channels
        self.parameters = bytes(parameters)
        for identity, value in (initial_parameters or {}).items():
            self.parameters = self._updated_parameters(self.parameters, identity, value)
        self.filters = {}
        self._configure()
        self.previous_input = self.input_gain
        self.previous_output = self.output_gain
        self.previous_mix = self.mix

    def _configure(self):
        p = self.parameters
        float_positions = (5, 9, 17, 21, 30, 34, 38, 47, 51, 55, 60, 64, 68, 72, 76, 80,
                           89, 94, 98, 102, 106, 110, 123, 127, 131, 135)
        if not all(math.isfinite(struct.unpack_from('<f', p, position)[0]) for position in float_positions):
            raise ValueError("Nonfinite amplifier parameter")
        self.enabled = [bool(p[index]) for index in (0, 25, 42, 59, 84, 93, 114)]
        input_db, output_db, self.mix = struct.unpack_from('<3f', p, 127)
        if not all(math.isfinite(x) for x in (input_db, output_db, self.mix)) or not 0 <= self.mix <= 100:
            raise ValueError("Invalid amplifier gain/mix")
        db_scale = float(np.float32(.05))
        self.input_gain, self.output_gain = np.float32(10 ** (input_db * db_scale)), np.float32(10 ** (output_db * db_scale))
        identity = np.asarray([1, 0, 0, 0, 0], dtype=np.float32)
        if self.enabled[0]:
            low_order, low_frequency, low_resonance, high_order, high_frequency, high_resonance = struct.unpack_from('<I2fI2f', p, 1)
            hp = _amp_filter_coefficients('highpass', high_frequency, high_resonance, self.sample_rate)
            lp = _amp_filter_coefficients('lowpass', low_frequency, low_resonance, self.sample_rate)
            coefficients = [hp, hp if high_order == 1 else identity, lp, lp if low_order == 1 else identity]
            if 0 in self.filters:
                self.filters[0].configure(coefficients)
            else:
                self.filters[0] = _AmpBiquads(coefficients, self.channels)
        if self.enabled[1]:
            from .amp_compression import AmpCompression
            mode, drive, tone, asymmetry = struct.unpack_from('<I3f', p, 26)
            if 1 in self.filters:
                self.filters[1].configure(mode, drive, tone, asymmetry)
            else:
                self.filters[1] = AmpCompression(mode, drive, tone, asymmetry,
                                                 sample_rate=self.sample_rate, channels=self.channels)
        if self.enabled[2]:
            kind, frequency, resonance, gain = struct.unpack_from('<I3f', p, 43)
            if kind not in (0, 1, 2):
                raise NotImplementedError("Unreconstructed amplifier EQ filter type")
            coefficient = _amp_filter_coefficients(('highpass', 'peak', 'lowpass')[kind], frequency, resonance, self.sample_rate, gain)
            if 2 in self.filters:
                self.filters[2].configure([coefficient])
            else:
                self.filters[2] = _AmpBiquads([coefficient], self.channels)
        for index, parameters, implementation in (
            (3, struct.unpack_from('<6f', p, 60), _AmpNoise),
            (4, struct.unpack_from('<If', p, 85), _AmpPresetShaper),
            (5, struct.unpack_from('<5f', p, 94), _AmpGate),
            (6, struct.unpack_from('<IIf', p, 115), _AmpBitcrusher),
        ):
            if self.enabled[index]:
                if index in self.filters:
                    self.filters[index].configure(parameters)
                else:
                    self.filters[index] = implementation(parameters, self.channels, self.sample_rate)

    def process(self, audio):
        from .basic import _gain_ramp
        source = np.asarray(audio, dtype=np.float32)
        if source.ndim != 2 or source.shape[1] != self.channels or not 1 <= len(source) <= 128 or not np.isfinite(source).all():
            raise ValueError("Amp EQ requires finite 1..128 frames by channels")
        wet = source.copy()
        _gain_ramp(wet, self.previous_input, self.input_gain)
        dry = wet.copy()
        for index in range(7):
            if self.enabled[index]:
                wet = self.filters[index].process(wet)
        previous_fraction = np.float32(np.float32(self.previous_mix) * np.float32(.01))
        fraction = np.float32(np.float32(self.mix) * np.float32(.01))
        wet_start = float(np.float32(self.previous_output * previous_fraction))
        wet_end = float(np.float32(self.output_gain * fraction))
        dry_start = float(np.float32(1 - previous_fraction))
        dry_end = float(np.float32(1 - fraction))
        result = mix_amp_eq(wet, dry, wet_start, wet_end, dry_start, dry_end)
        self.previous_input, self.previous_output, self.previous_mix = self.input_gain, self.output_gain, self.mix
        return result

    @staticmethod
    def _updated_parameters(parameters, parameter_id, value):
        if not math.isfinite(value):
            raise ValueError("Nonfinite amplifier parameter")
        flags = {0: 25, 10: 93, 20: 84, 30: 114, 50: 0, 60: 42, 70: 59}
        floats = {1: 26, 2: 30, 3: 34, 4: 38,
                  11: 94, 12: 98, 13: 102, 14: 106, 15: 110,
                  21: 85, 22: 89, 33: 123, 40: 127, 41: 131, 42: 135,
                  51: 1, 52: 5, 53: 9, 54: 13, 55: 17, 56: 21,
                  61: 43, 62: 47, 63: 51, 64: 55,
                  71: 60, 72: 64, 73: 68, 74: 72, 75: 76, 76: 80}
        p = bytearray(parameters)
        if parameter_id in flags:
            if value not in (0, 1):
                raise ValueError("Amplifier enable flag must be zero or one")
            p[flags[parameter_id]] = int(value)
        elif parameter_id in (1, 21, 51, 54, 61):
            if value != int(value) or not 0 <= value <= 0xffffffff:
                raise ValueError("Invalid amplifier mode selector")
            struct.pack_into('<I', p, floats[parameter_id], int(value))
        elif parameter_id in (31, 32):
            struct.pack_into('<i', p, 115 if parameter_id == 31 else 119, int(value))
        elif parameter_id in floats:
            struct.pack_into('<f', p, floats[parameter_id], value)
        else:
            raise ValueError("Unknown amplifier parameter")
        return bytes(p)

    def set_parameter(self, parameter_id, value):
        p = self._updated_parameters(self.parameters, parameter_id, value)
        # Validate before updating existing filter histories or gain ramps.
        AmpEqualizer(p, self.sample_rate, self.channels)
        self.parameters = bytes(p)
        self._configure()

    def reset(self):
        # Native 0xf482e0 is MOV EAX,1; RET and preserves every embedded history.
        pass

    def rtpc_updates(self):
        return []
