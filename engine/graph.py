"""128-frame tone graph with block-boundary RTPC feedback."""
import numpy as np

from . import ROOT, inspect_tone
from .effects import make_effect
from .cabinet import Cabinet, SpectraBank
from .curves import evaluate_curve


def _upmix_center(audio):
    # The source mixer accumulates the centered mono signal into an initially
    # silent stereo bus. The addition matters for the sign of exact zero.
    centered = audio * np.float32(0.7071067690849304)
    return np.repeat(np.float32(0) + centered, 2, axis=1)


class ToneGraph:
    def __init__(self, definition):
        self.plan = inspect_tone(definition)
        if not self.plan['renderable']:
            raise ValueError('Unsupported tone graph: ' + str(self.plan['unsupported_plugin_ids'] + self.plan['issues']))
        self.rtpc = {int(k): v for k, v in self.plan['rtpc'].items()}
        self.initial_rtpc = dict(self.rtpc)
        self.scoped_rtpc = {scope: {int(k): v for k, v in values.items()} for scope, values in self.plan.get('scoped_rtpc', {}).items()}
        self.initial_scoped_rtpc = {scope: dict(values) for scope, values in self.scoped_rtpc.items()}
        self.bank = None
        self.effects = []
        try:
            stereo = False
            for stage in self.plan['stages']:
                profile = stage['profile']
                parameters = bytes.fromhex(profile['parameter_block_hex'])
                if self.scoped_rtpc:
                    stereo = stereo or stage['pool'] == 'stereo'
                    stage['pool'] = 'stereo' if stereo else 'mono'
                channels = 1 if stage['pool'] == 'mono' else 2
                if stage['plugin_id'] == '0x7f0003':
                    if self.bank is None:
                        self.bank = SpectraBank(ROOT / 'data')
                    effect = (StereoCabinet if channels == 2 else Cabinet)(parameters, self.bank.get(profile['media'][0]['source_id']))
                else:
                    effect = make_effect(int(stage['plugin_id'], 16), parameters, 48000, channels,
                                         initial_parameters={int(k): v for k, v in stage['initial_parameters'].items()})
                self.effects.append((stage, effect))
        except BaseException:
            self.close()
            raise

    def set_control(self, identity, normalized):
        if not isinstance(identity, int) or not 0 <= identity <= len(self.plan['controls']):
            raise ValueError('Unknown source control')
        if not np.isfinite(normalized) or not 0 <= normalized <= 1:
            raise ValueError('Source control must be normalized to 0..1')
        is_volume = identity == len(self.plan['controls'])
        control = self.plan['volume_control'] if is_volume else self.plan['controls'][identity]
        value = float(np.float32(control['minimum'] + normalized * (control['maximum'] - control['minimum'])))
        # The original tone balance uses -36 dB when its supplied level is nonnegative.
        scope = control['slot'] if not is_volume and self.scoped_rtpc else None
        rtpc = self.scoped_rtpc[scope] if scope else self.rtpc
        initial = self.initial_scoped_rtpc[scope] if scope else self.initial_rtpc
        rtpc[control['rtpc_id']] = -36.0 if is_volume and value >= 0 else value
        initial[control['rtpc_id']] = rtpc[control['rtpc_id']]
        self._apply({control['rtpc_id']}, scope)

    def _apply(self, changed, scope=None):
        for stage, effect in self.effects:
            if stage.get('control_scope') != scope:
                continue
            rtpc = self.scoped_rtpc[scope] if scope else self.rtpc
            for curve in stage['profile']['curves']:
                if curve['rtpc_id'] in changed:
                    effect.set_parameter(curve['plugin_parameter_id'], evaluate_curve(curve, rtpc.get(curve['rtpc_id'], 0.0)))

    def process(self, mono):
        audio = np.asarray(mono, dtype=np.float32)
        if audio.shape != (128, 1) or not np.isfinite(audio).all():
            raise ValueError('Graph requires 128 finite mono frames')
        updates = {}
        for stage, effect in self.effects:
            if stage['pool'] == 'stereo' and audio.shape[1] == 1:
                audio = _upmix_center(audio)
            audio = effect.process(audio)
            for update in effect.rtpc_updates():
                identity, value = update['rtpc_id'], update['value']
                scoped = updates.setdefault(stage.get('control_scope'), {})
                scoped[identity] = max(value, scoped.get(identity, -np.inf))
        for scope, values in updates.items():
            (self.scoped_rtpc[scope] if scope else self.rtpc).update(values)
            self._apply(set(values), scope)
        if audio.shape[1] == 1:
            audio = _upmix_center(audio)
        if not np.isfinite(audio).all():
            raise ValueError('DSP produced nonfinite audio')
        return audio

    def close(self):
        if self.bank is not None:
            self.bank.close()
            self.bank = None

    def reset(self):
        for _, effect in self.effects:
            effect.reset()
        self.rtpc = dict(self.initial_rtpc)
        self._apply(set(self.rtpc))
        self.scoped_rtpc = {scope: dict(values) for scope, values in self.initial_scoped_rtpc.items()}
        for scope, values in self.scoped_rtpc.items():
            self._apply(set(values), scope)


class StereoCabinet:
    def __init__(self, parameters, spectra):
        self.channels = [Cabinet(parameters, spectra), Cabinet(parameters, spectra)]

    def process(self, audio):
        return np.column_stack([effect.process(audio[:, index:index+1])[:, 0]
                                for index, effect in enumerate(self.channels)])

    def reset(self):
        for effect in self.channels:
            effect.reset()

    def rtpc_updates(self):
        return []
