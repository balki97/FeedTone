"""Registry of reconstructed source DSP; unavailable families raise."""
import numpy as np

from .amplifier import AmpEqualizer, MultibandDistortion
from .basic import make_effect as make_basic
from .compressor import Compressor
from .filter import DynamicFilter
from .tremolo import Tremolo
from .delay import TrashDelay
from .dual_delay import DualDelay
from .phaser import TrashPhaser
from .multipitch import MultiPitch
from .pitch import Pitch
from .reverb import FDNReverb
from .chorus import Chorus
from .room_reverb import RoomReverb


def make_effect(plugin_id, parameters, sample_rate=48000, channels=1, initial_parameters=None):
    if plugin_id == TrashPhaser.plugin_id:
        return TrashPhaser(parameters, sample_rate, channels, initial_parameters)
    if plugin_id == MultiPitch.plugin_id:
        return MultiPitch(parameters, sample_rate, channels, initial_parameters)
    if plugin_id == Pitch.plugin_id:
        return Pitch(parameters, sample_rate, channels, initial_parameters)
    if plugin_id == FDNReverb.plugin_id:
        return FDNReverb(parameters, sample_rate, channels, initial_parameters)
    if plugin_id == Chorus.plugin_id:
        return Chorus(parameters, sample_rate, channels, initial_parameters)
    if plugin_id == RoomReverb.plugin_id:
        return RoomReverb(parameters, sample_rate, channels, initial_parameters)
    if plugin_id == DynamicFilter.plugin_id:
        return DynamicFilter(parameters, sample_rate, channels, initial_parameters)
    if plugin_id == Tremolo.plugin_id:
        return Tremolo(parameters, sample_rate, channels, initial_parameters)
    if plugin_id == 0x6e1003:
        return AmpEqualizer(parameters, sample_rate, channels, initial_parameters)
    if plugin_id == TrashDelay.plugin_id:
        return TrashDelay(parameters, sample_rate, channels, initial_parameters)
    if plugin_id == DualDelay.plugin_id:
        return DualDelay(parameters, sample_rate, channels, initial_parameters)
    if plugin_id == Compressor.plugin_id:
        effect = Compressor(parameters, sample_rate, channels)
    elif plugin_id == 0x91033:
        return MultibandDistortion(parameters, sample_rate, channels, initial_parameters)
    else:
        return make_basic(plugin_id, parameters, sample_rate, channels, initial_parameters)
    for identity, value in (initial_parameters or {}).items():
        effect.set_parameter(identity, value)
    if isinstance(effect, Compressor):
        effect.previous_gain = np.float32(10**(effect.gain*float(np.float32(.05))))
        effect._initialize()
    return effect
