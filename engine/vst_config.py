"""Binary sidecar writer shared by wrapper packaging and interface tests."""
import math
import struct
from pathlib import Path


def write_configuration(destination, *, title, vendor, application, command_line, cwd,
                        component_uid, controller_uid, parameters, harness=False):
    def text(value, capacity=4097):
        if not isinstance(value, str) or "\0" in value:
            raise ValueError("Configuration strings must be text without NULs")
        raw = value.encode("utf-16le")
        if len(raw) // 2 >= capacity:
            raise ValueError("Configuration text exceeds its field capacity")
        return struct.pack("<I", len(raw) // 2) + raw

    if not title or len(component_uid) != 16 or len(controller_uid) != 16 or component_uid == controller_uid:
        raise ValueError("A display title and distinct 16-byte class IDs are required")
    if not harness and (not application or not command_line):
        raise ValueError("Production wrappers require an explicit service application and command")
    if len(parameters) > 256:
        raise ValueError("At most 256 source parameters are supported")
    payload = struct.pack("<6I16s16s", 0x46545352, 1, int(harness), len(parameters), 1, 0,
                          component_uid, controller_uid)
    payload += text(title, 128) + text(vendor, 64) + text(str(application)) + text(command_line) + text(str(cwd))
    ids = set()
    for parameter in parameters:
        identity = parameter["id"]
        steps = parameter.get("step_count", 0)
        initial = float(parameter["default_normalized"])
        minimum, maximum = float(parameter["minimum"]), float(parameter["maximum"])
        if identity in ids or not 0 <= identity <= 0xffffffff or not 0 <= steps <= 0x7fffffff:
            raise ValueError("Parameter IDs must be unique and step counts nonnegative")
        if not all(map(math.isfinite, (initial, minimum, maximum))) or not 0 <= initial <= 1 or minimum > maximum:
            raise ValueError("Invalid source parameter range or default")
        ids.add(identity)
        payload += struct.pack("<IIddd", identity, steps, initial, minimum, maximum)
        label = parameter.get('label')
        # Slot names distinguish e.g. an amp's Gain from a pedal's Gain in hosts.
        name = (parameter.get('slot', '') + ' / ' + label).strip(' /') if label else parameter['name']
        unit = parameter.get('units', '')
        unit = {'number': '', 'enum': '', 'db': 'dB', 'hz': 'Hz', 'khz': 'kHz'}.get(unit, unit)
        payload += text(name, 128) + text(unit, 128)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination
