"""Source implementations of independently reconstructed effects.

No original executable code is loaded. Evidence and current accuracy limits are
recorded in research/independent-basic.md. Each process call is one audio quantum.
"""
import math
import struct

import numpy as np

from . import kernels


def _audio(audio, channels):
    result = np.asarray(audio, dtype=np.float32)
    if result.ndim != 2 or result.shape[1] != channels:
        raise ValueError("Audio must have shape (frames, channels)")
    if not np.isfinite(result).all():
        raise ValueError("Audio contains nonfinite samples")
    return result.copy()


class Meter:
    """Wwise meter: transparent audio with block-rate peak/RMS envelope RTPC."""
    plugin_id = 0x810003

    def __init__(self, parameters, sample_rate=48000, channels=1):
        if len(parameters) != 25:
            raise ValueError("Meter requires a 25-byte parameter block")
        if channels not in (1, 2) or not 8000 <= sample_rate <= 192000:
            raise ValueError("Unsupported audio format")
        self.sample_rate, self.channels = sample_rate, channels
        self.attack, self.release, self.minimum, self.maximum, self.hold, self.mode, self.output_id = struct.unpack('<5fBI', parameters)
        self._validate()
        self.reset()

    def _validate(self):
        values = (self.attack, self.release, self.minimum, self.maximum, self.hold)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Meter parameters must be finite")
        if min(self.attack, self.release, self.hold) < 0 or self.minimum > self.maximum:
            raise ValueError("Invalid meter timing or bounds")
        if self.mode not in (0, 1):
            raise ValueError("Meter mode must be peak (0) or RMS (1)")

    def reset(self):
        self.elapsed = np.float32(0)
        self.target = self.level = np.float32(self.minimum)
        self.history = np.full(8, self.minimum, dtype=np.float32)
        self._updates = []

    def set_parameter(self, parameter_id, value):
        names = {0: 'attack', 1: 'release', 2: 'mode', 4: 'minimum', 5: 'maximum', 6: 'hold', 0x7fff: 'output_id'}
        if parameter_id not in names or not math.isfinite(value):
            raise ValueError("Invalid meter parameter")
        name = names[parameter_id]
        if name in ('mode', 'output_id'):
            if value != int(value) or not 0 <= value <= 0xffffffff:
                raise ValueError("Meter integer parameter out of range")
            value = int(value)
        else:
            value = float(np.float32(value))
        old = getattr(self, name)
        setattr(self, name, value)
        try:
            self._validate()
        except ValueError:
            setattr(self, name, old)
            raise

    def _measure(self, audio):
        if self.mode == 0:
            amplitude = float(np.max(np.abs(audio)))
        else:
            # Native RMS uses sequential scalar SSE additions, not pairwise sum.
            powers = kernels.rms_power(audio)
            if powers is None:
                powers = np.zeros(self.channels, dtype=np.float32)
                for frame in audio:
                    powers = np.float32(powers + np.float32(frame * frame))
                powers = np.float32(powers / np.float32(len(audio)))
            amplitude = float(np.float32(math.sqrt(float(np.max(powers)))))
        db = np.float32(20 * math.log10(amplitude)) if amplitude else np.float32(-np.inf)
        return np.float32(min(self.maximum, max(self.minimum, float(db))))

    def process(self, audio):
        result = _audio(audio, self.channels)
        if not len(result):
            return result
        measured = self._measure(result)
        elapsed = np.float32(len(result) / self.sample_rate)
        if measured > self.level:
            self.elapsed = np.float32(0)
            self.history.fill(self.minimum)
            if self.attack:
                measured = min(measured, np.float32(float(self.level) + len(result) / self.sample_rate / self.attack * 10))
            self.level = self.target = np.float32(measured)
        else:
            self.elapsed = np.float32(self.elapsed + elapsed)
            if self.elapsed < self.hold:
                index = int(np.float32(np.float32(np.float32(self.elapsed / np.float32(self.hold)) * np.float32(8)) + np.float32(.5))) - 1
                if index >= 0 and measured > self.history[index]:
                    self.history[index] = measured
                if measured > self.target:
                    self.target = measured
            else:
                index = 8
                for i, value in enumerate(self.history):
                    if measured <= value:
                        measured, index = value, i
                self.elapsed = np.float32(np.float32(8-index) * np.float32(np.float32(self.hold) * np.float32(1/9)))
                remaining = self.history[index+1:].copy()
                self.history.fill(self.minimum)
                self.history[:len(remaining)] = remaining
                self.target = measured
            if self.release:
                delta = np.float32(np.float32(elapsed / np.float32(self.release)) * np.float32(10))
                self.level = np.float32(max(self.target, np.float32(self.level - delta)))
            else:
                self.level = np.float32(self.target)
        self._updates.append(dict(rtpc_id=self.output_id, value=float(self.level), duration_ms=0, interpolation=4, value_meaning=1))
        return result

    def rtpc_updates(self):
        updates, self._updates = self._updates, []
        return updates


def _eq_coefficients(kind, gain, frequency, q, sample_rate):
    """Observed seven filter types, including native float32 coefficient steps."""
    f = np.float32
    frequency = min(frequency, float(f(f(sample_rate)*f(.5)*f(.9))))
    angle = frequency * float(f(2*math.pi)) / sample_rate
    if kind in (0, 1):
        tangent = math.tan(frequency*float(f(math.pi))/sample_rate)
        k = f(1/tangent) if kind == 0 else f(tangent)
        square = f(k*k)
        summed = f(square + f(1))
        root = f(k*f(math.sqrt(2)))
        b0 = f(f(1)/f(summed+root))
        b1 = f(b0*f(2 if kind == 0 else -2))
        b2 = b0
        a0 = f(1)
        a1 = f(f(f(1)-square)*b0*f(2)) if kind == 0 else f(-f(f(square-f(1))*b0*f(-2)))
        a2 = f(f(summed-root)*b0)
    elif kind in (2, 3):
        alpha = math.sin(angle)/(q+q)
        a0, a1, a2 = f(1+alpha), f(-2*math.cos(angle)), f(1-alpha)
        if kind == 2:
            b0, b1, b2 = f(alpha), f(0), f(-alpha)
        else:
            b0, b1, b2 = f(1), a1, f(1)
    else:
        amplitude = 10**(gain*float(f(.025)))
        a = f(amplitude)
        cosine = f(math.cos(angle))
        if kind == 6:
            alpha = f(math.sin(float(f(angle)))/(q+q))
            plus, minus = f(alpha*a), f(alpha/a)
            a0, a1, a2 = f(minus+f(1)), f(cosine*f(-2)), f(f(1)-minus)
            b0, b1, b2 = f(plus+f(1)), a1, f(f(1)-plus)
        else:
            plus, minus = f(a+f(1)), f(a-f(1))
            mc, pc = f(minus*cosine), f(plus*cosine)
            alpha = f(math.sin(angle)*math.sqrt(2)*math.sqrt(amplitude))
            if kind == 4:
                numerator, denominator = f(plus-mc), f(mc+plus)
                b0, b1, b2 = f(f(numerator+alpha)*a), f(f(f(minus-pc)*a)*f(2)), f(f(numerator-alpha)*a)
                a0, a1, a2 = f(denominator+alpha), f(f(pc+minus)*f(-2)), f(denominator-alpha)
            else:
                numerator, denominator = f(mc+plus), f(plus-mc)
                b0, b1, b2 = f(f(numerator+alpha)*a), f(f(f(pc+minus)*a)*f(-2)), f(f(numerator-alpha)*a)
                a0, a1, a2 = f(denominator+alpha), f(f(minus-pc)*f(2)), f(denominator-alpha)
    inverse = f(f(1)/a0)
    return np.array([f(inverse*b0), f(inverse*b1), f(inverse*b2), -f(inverse*a1), -f(inverse*a2)], dtype=np.float32)


def _gain_ramp(result, previous_gain, gain):
    f = np.float32
    if gain == previous_gain:
        result *= gain
    else:
        aligned = len(result)//4*4
        step = f(f(gain-previous_gain)/f(aligned)) if aligned else f(0)
        lanes = np.empty(4, dtype=np.float32)
        lanes[0] = previous_gain
        for i in range(1, 4):
            lanes[i] = f(lanes[i-1]+step)
        increment = f(step*f(4))
        for i in range(0, aligned, 4):
            result[i:i+4] *= lanes[:, None]
            lanes = f(lanes+increment)
        # Native remainder restarts at the previous block gain.
        level = previous_gain
        step = f(f(gain-level)/f(len(result)))
        for i in range(aligned, len(result)):
            result[i] *= level
            level = f(level+step)


class Equalizer:
    """Three serial biquads and the observed four-lane output gain ramp."""
    plugin_id = 0x690003

    def __init__(self, parameters, sample_rate=48000, channels=1):
        if len(parameters) != 56:
            raise ValueError("Equalizer requires a 56-byte parameter block")
        if channels not in (1, 2) or not 8000 <= sample_rate <= 192000:
            raise ValueError("Unsupported audio format")
        self.sample_rate, self.channels = sample_rate, channels
        self.bands = [list(struct.unpack_from('<IfffB', parameters, i*17)) for i in range(3)]
        self.gain, self.process_lfe = struct.unpack_from('<fB', parameters, 51)
        self._validate()
        self.coefficients = [_eq_coefficients(*band[:4], sample_rate) for band in self.bands]
        self.previous_gain = np.float32(10**(self.gain*float(np.float32(.05))))
        self.reset()

    def _validate(self):
        if not math.isfinite(self.gain) or not -200 <= self.gain <= 100:
            raise ValueError("Invalid equalizer output gain")
        for kind, gain, frequency, q, enabled in self.bands:
            if kind not in range(7) or not all(math.isfinite(v) for v in (gain, frequency, q)) or not -200 <= gain <= 100 or frequency <= 0 or q <= 0:
                raise ValueError("Invalid equalizer band")

    def reset(self):
        self.history = np.zeros((3, self.channels, 4), dtype=np.float32)

    def set_parameter(self, parameter_id, value):
        if not 0 <= parameter_id <= 16 or not math.isfinite(value):
            raise ValueError("Invalid equalizer parameter")
        if parameter_id < 15:
            band, field = divmod(parameter_id, 5)
            if field == 0 and value != int(value):
                raise ValueError("Filter kind must be an integer")
            converted = int(value) if field == 0 else (int(value != 0) if field == 4 else float(np.float32(value)))
            old = self.bands[band][field]
            self.bands[band][field] = converted
            try:
                self._validate()
                coefficients = _eq_coefficients(*self.bands[band][:4], self.sample_rate)
            except (ValueError, OverflowError):
                self.bands[band][field] = old
                raise
            self.coefficients[band] = coefficients
        elif parameter_id == 15:
            old, self.gain = self.gain, float(np.float32(value))
            try:
                self._validate()
            except ValueError:
                self.gain = old
                raise
        else:
            self.process_lfe = int(value != 0)

    def process(self, audio):
        result = _audio(audio, self.channels)
        if not len(result):
            return result
        f = np.float32
        for band, coeff, state in zip(self.bands, self.coefficients, self.history):
            if not band[4]:
                continue
            if kernels.equalizer(result, coeff, state):
                continue
            b0, b1, b2, a1, a2 = coeff
            for i, frame in enumerate(result):
                x1, x2, y1, y2 = state.T.copy()
                output = f(f(y1*a1) + f(f(y2*a2) + f(f(x1*b1) + f(f(x2*b2) + f(frame*b0)))))
                state[:, 1], state[:, 0] = x1, frame
                state[:, 3], state[:, 2] = y1, output
                result[i] = output
        gain = f(10**(self.gain*float(f(.05))))
        _gain_ramp(result, self.previous_gain, gain)
        self.previous_gain = gain
        return result

    def rtpc_updates(self):
        return []


def _fast_db(amplitude):
    f = np.float32
    bits = struct.unpack('<I', struct.pack('<f', amplitude))[0]
    mantissa = struct.unpack('<f', struct.pack('<I', (bits & 0x7fffff)+0x3f800000))[0]
    t = (mantissa-1)/(mantissa+1)
    polynomial = t*t*float(f(1/3))+1
    logarithm = ((bits >> 23 & 255)-127)*float(f(math.log(2)))+(t+t)*polynomial
    return logarithm*float(f(math.log10(math.e)))*20


def _fast_pow10(exponent):
    f = np.float32
    if exponent < -37:
        return f(0)
    bits = int(float(exponent)*27866352+1065353216)
    mantissa = f(struct.unpack('<f', struct.pack('<I', (bits & 0x7fffff)+0x3f800000))[0])
    scale = f(struct.unpack('<f', struct.pack('<I', bits & 0xff800000))[0])
    return f(f(f(f(f(mantissa*f(.32518977))+f(.020805772))*mantissa)+f(.65304345))*scale)


class Limiter:
    """Lookahead peak compressor/limiter used on the original parent bus."""
    plugin_id = 0x6e0003

    def __init__(self, parameters, sample_rate=48000, channels=1):
        if len(parameters) != 22:
            raise ValueError("Limiter requires a 22-byte parameter block")
        if channels not in (1, 2) or not 8000 <= sample_rate <= 192000:
            raise ValueError("Unsupported audio format")
        self.sample_rate, self.channels = sample_rate, channels
        self.threshold, self.ratio, self.lookahead, self.release, self.gain, self.process_lfe, self.linked = struct.unpack('<5fBB', parameters)
        self._validate()
        self.position = 0
        self.previous_gain = np.float32(10**(self.gain*float(np.float32(.05))))
        self._configure()
        self.reset()

    def _validate(self):
        if not all(math.isfinite(v) for v in (self.threshold, self.ratio, self.lookahead, self.release, self.gain)):
            raise ValueError("Limiter parameters must be finite")
        if self.ratio < 1 or not 0 < self.lookahead <= 1 or int(self.sample_rate*self.lookahead) < 1 or self.release <= 0 or not -200 <= self.gain <= 100:
            raise ValueError("Invalid limiter timing, ratio, or gain")

    def _configure(self):
        f = np.float32
        self.latency_frames = int(self.sample_rate*self.lookahead)
        if self.latency_frames < 1:
            raise ValueError("Limiter lookahead is less than one frame")
        self.attack_coefficient = f(math.exp(-2.2/(self.latency_frames*.5)))
        self.release_coefficient = f(math.exp(-2.2/(self.sample_rate*self.release)))
        self.groups = 1 if self.linked else self.channels
        self.delay = np.zeros((self.latency_frames, self.channels), dtype=np.float32)
        self.position = 0

    def reset(self):
        self.delay.fill(0)
        self.reduction = np.zeros(self.groups, dtype=np.float32)
        self.peak = np.zeros(self.groups, dtype=np.float32)
        self.countdown = np.zeros(self.groups, dtype=np.int64)
        self.first = True

    def set_parameter(self, parameter_id, value):
        names = ('threshold', 'ratio', 'lookahead', 'release', 'gain', 'process_lfe', 'linked')
        if not 0 <= parameter_id < len(names) or not math.isfinite(value):
            raise ValueError("Invalid limiter parameter")
        name = names[parameter_id]
        old = getattr(self, name)
        setattr(self, name, int(value != 0) if parameter_id >= 5 else float(np.float32(value)))
        try:
            self._validate()
            if parameter_id in (2, 5, 6):
                self._configure()
                self.reset()
            elif parameter_id == 3:
                self.release_coefficient = np.float32(math.exp(-2.2/(self.sample_rate*self.release)))
        except ValueError:
            setattr(self, name, old)
            raise

    def process(self, audio):
        result = _audio(audio, self.channels)
        if not len(result):
            return result
        f = np.float32
        if not kernels.limiter(self, result):
            self._process_python(result)
        # The original limiter shares the EQ's gain-ramp arithmetic.
        gain = f(10**(self.gain*float(f(.05))))
        _gain_ramp(result, self.previous_gain, gain)
        self.previous_gain = gain
        return result

    def _process_python(self, result):
        f = np.float32
        if self.first:
            scan = result[:self.latency_frames]
            for channel in range(self.channels):
                group = 0 if self.linked else channel
                for i, amplitude in enumerate(np.abs(scan[:, channel])):
                    if self.peak[group] < amplitude if self.linked and self.channels > 1 else self.peak[group] <= amplitude:
                        self.peak[group] = amplitude
                        self.countdown[group] = len(scan)-i
            self.first = False
        ratio_factor = f((1/self.ratio-1)*.05)
        overs = np.array([max(_fast_db(peak)-self.threshold, 0) for peak in self.peak], dtype=np.float32)
        for i, frame in enumerate(result):
            amplitudes = np.array([np.max(np.abs(frame))], dtype=np.float32) if self.linked else np.abs(frame).copy()
            delayed = self.delay[self.position].copy()
            self.delay[self.position] = frame
            self.position = (self.position+1) % self.latency_frames
            levels = np.empty(self.groups, dtype=np.float32)
            for group, amplitude in enumerate(amplitudes):
                if self.countdown[group] == 0 or self.peak[group] < amplitude:
                    self.peak[group] = amplitude
                    self.countdown[group] = self.latency_frames
                    overs[group] = f(max(_fast_db(amplitude)-self.threshold, 0))
                else:
                    self.countdown[group] -= 1
                over = overs[group]
                coefficient = self.attack_coefficient if over >= self.reduction[group] else self.release_coefficient
                self.reduction[group] = f(f(f(self.reduction[group]-over)*coefficient)+over)
                exponent = f(self.reduction[group]*ratio_factor)
                levels[group] = _fast_pow10(exponent)
            result[i] = f(delayed*(levels[0] if self.linked else levels))

    def rtpc_updates(self):
        return []


class Gate:
    """RMS-envelope downward expander with independently reconstructed math."""
    plugin_id = 0x6d0003

    def __init__(self, parameters, sample_rate=48000, channels=1):
        if len(parameters) != 22:
            raise ValueError("Gate requires a 22-byte parameter block")
        if channels not in (1, 2) or not 8000 <= sample_rate <= 192000:
            raise ValueError("Unsupported audio format")
        self.sample_rate, self.channels = sample_rate, channels
        self.threshold, self.ratio, self.attack, self.release, self.gain, self.process_lfe, self.linked = struct.unpack('<5fBB', parameters)
        self._validate()
        self.previous_gain = np.float32(10**(self.gain*float(np.float32(.05))))
        self._initialize()

    def _validate(self):
        if not all(math.isfinite(v) for v in (self.threshold, self.ratio, self.attack, self.release, self.gain)):
            raise ValueError("Gate parameters must be finite")
        if self.ratio < 1 or self.attack <= 0 or self.release <= 0 or not -200 <= self.gain <= 100:
            raise ValueError("Invalid gate ratio, timing, or gain")

    def _coefficient(self, seconds):
        return np.float32(math.exp(-float(np.float32(2.2))/(self.sample_rate*seconds)))

    def _initialize(self):
        self.active_linked = bool(self.linked and self.channels > 1)
        self.groups = 1 if self.linked else self.channels
        self.power_coefficient = np.float32(math.exp(-1/(self.sample_rate*float(np.float32(.02322)))))
        self.reset()

    def reset(self):
        self.power = np.zeros(self.groups, dtype=np.float32)
        self.reduction = np.zeros(self.groups, dtype=np.float32)

    def set_parameter(self, parameter_id, value):
        names = ('threshold', 'ratio', 'attack', 'release', 'gain', 'process_lfe', 'linked')
        if not 0 <= parameter_id < len(names) or not math.isfinite(value):
            raise ValueError("Invalid gate parameter")
        name = names[parameter_id]
        old = getattr(self, name)
        setattr(self, name, int(value != 0) if parameter_id >= 5 else float(np.float32(value)))
        try:
            self._validate()
        except ValueError:
            setattr(self, name, old)
            raise

    def process(self, audio):
        result = _audio(audio, self.channels)
        if not len(result):
            return result
        f = np.float32
        attack, release = self._coefficient(self.attack), self._coefficient(self.release)
        if not kernels.gate(self, result, attack, release):
            self._process_python(result, attack, release)
        gain = f(10**(self.gain*float(f(.05))))
        _gain_ramp(result, self.previous_gain, gain)
        self.previous_gain = gain
        return result

    def _process_python(self, result, attack, release):
        f = np.float32
        ratio = f(f(self.ratio)-f(1))
        for i, frame in enumerate(result):
            squared = f(frame*frame)
            if self.active_linked:
                summed = f(0)
                for value in squared:
                    summed = f(summed+value)
                powers = (f(f(summed*f(1/self.channels))+f(1e-25)),)
            else:
                powers = f(squared+f(1e-25))
            levels = np.empty(self.groups, dtype=np.float32)
            for group, power in enumerate(powers):
                self.power[group] = f(f(f(self.power[group]-power)*self.power_coefficient)+power)
                under = f(max(self.threshold-_fast_db(self.power[group])*.5, 0))
                coefficient = release if under >= self.reduction[group] else attack
                self.reduction[group] = f(f(f(self.reduction[group]-under)*coefficient)+under)
                exponent = f(-f(self.reduction[group]*ratio)*f(.05))
                levels[group] = _fast_pow10(exponent)
            result[i] = f(frame*(levels[0] if self.active_linked else levels))

    def rtpc_updates(self):
        return []


IMPLEMENTED_PLUGIN_IDS = frozenset((Meter.plugin_id, Equalizer.plugin_id, Limiter.plugin_id, Gate.plugin_id))


def make_effect(plugin_id, parameters, sample_rate=48000, channels=1, initial_parameters=None):
    if plugin_id == Meter.plugin_id:
        effect = Meter(parameters, sample_rate, channels)
    elif plugin_id == Equalizer.plugin_id:
        effect = Equalizer(parameters, sample_rate, channels)
    elif plugin_id == Limiter.plugin_id:
        effect = Limiter(parameters, sample_rate, channels)
    elif plugin_id == Gate.plugin_id:
        effect = Gate(parameters, sample_rate, channels)
    else:
        raise NotImplementedError(f"Independent DSP for plugin {plugin_id:#x} is not implemented")
    if initial_parameters:
        for parameter_id, value in initial_parameters.items():
            effect.set_parameter(parameter_id, value)
        if isinstance(effect, (Equalizer, Limiter, Gate)):
            effect.previous_gain = np.float32(10**(effect.gain*float(np.float32(.05))))
        if isinstance(effect, Gate):
            effect._initialize()
        effect.reset()
    return effect
