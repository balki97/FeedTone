"""Encode this bridge's state in the JUCE VST3 host's opaque container.

Format references: JUCE commit9971c75b2c9d28d8c79d017180bdb3ea58f21158,
MemoryBlock::toBase64Encoding, AudioProcessor::copyXmlToBinary and
VST3PluginInstanceHeadless::getStateInformation. Independent Python codec;
no JUCE implementation code or original game DSP is included.
"""
from __future__ import annotations

import math
import struct
from xml.etree import ElementTree

_ALPHABET = '.ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+'
_VALUES = {character: index for index, character in enumerate(_ALPHABET)}


def encode_juce_memory_block(raw: bytes) -> str:
    """JUCE's length-prefixed, least-significant-bit-first base64 variant."""
    bits = int.from_bytes(raw, 'little')
    return f'{len(raw)}.' + ''.join(_ALPHABET[(bits >> shift) & 63]
                                    for shift in range(0, len(raw) * 8, 6))


def decode_juce_memory_block(text: str) -> bytes:
    size, separator, payload = text.partition('.')
    if not separator or not size.isdecimal() or len(size) > 7:
        raise ValueError('Invalid JUCE memory-block length')
    length = int(size)
    if length > 1048576 or len(payload) != (length * 8 + 5) // 6:
        raise ValueError('Invalid JUCE memory-block payload size')
    try:
        bits = sum(_VALUES[character] << (index * 6) for index, character in enumerate(payload))
    except KeyError as error:
        raise ValueError('Invalid JUCE memory-block alphabet') from error
    if bits.bit_length() > length * 8:
        raise ValueError('Invalid JUCE memory-block padding')
    return bits.to_bytes(length, 'little')


def encode_original_vst_state(normalized_values) -> str:
    """Return a JUCE opaque state; values follow the sidecar's control order.

    This bridge assigns IDs0..N-1 in that same order. Both component and
    controller receive identical validated state, so audio and host UI agree.
    No plugin, process or native DSP needs to run when exporting this state.
    """
    values = [float(value) for value in normalized_values]
    if len(values) > 256 or any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
        raise ValueError('Original VST state requires up to256 normalized finite values')
    raw = struct.pack('<3I', 0x53545352, 1, len(values))
    raw += b''.join(struct.pack('<Id', identity, value) for identity, value in enumerate(values))
    encoded = encode_juce_memory_block(raw)
    xml = (f'<VST3PluginState><IComponent>{encoded}</IComponent>'
           f'<IEditController>{encoded}</IEditController></VST3PluginState>').encode('utf-8')
    return encode_juce_memory_block(struct.pack('<2I', 0x21324356, len(xml)) + xml + b'\0')


def decode_original_vst_state(opaque: str) -> list[float]:
    """Inspect states from this codec or actual JUCE savePreset captures."""
    raw = decode_juce_memory_block(opaque)
    if len(raw) < 9:
        raise ValueError('Truncated JUCE XML state')
    magic, length = struct.unpack_from('<2I', raw)
    if magic != 0x21324356 or len(raw) != length + 9 or raw[-1] != 0:
        raise ValueError('Invalid JUCE XML state container')
    root = ElementTree.fromstring(raw[8:-1])
    if root.tag != 'VST3PluginState':
        raise ValueError('Unexpected VST3 state root')
    states = [decode_juce_memory_block(root.findtext(tag, ''))
              for tag in ('IComponent', 'IEditController')]
    if states[0] != states[1] or len(states[0]) < 12:
        raise ValueError('Original component/controller states differ')
    state = states[0]
    magic, version, count = struct.unpack_from('<3I', state)
    if (magic, version) != (0x53545352, 1) or count > 256 or len(state) != 12 + count * 12:
        raise ValueError('Invalid original bridge state')
    values = []
    for index in range(count):
        identity, value = struct.unpack_from('<Id', state, 12 + index * 12)
        if identity != index or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('Invalid original bridge control')
        values.append(value)
    return values
