"""Source-defined designer models and atomic user-owned rigs/overrides."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import uuid


def fingerprint(definition):
    return hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


class Designer:
    def __init__(self, engine, directory):
        self.engine = engine
        self.path = Path(directory) / 'designer.json'
        self.lock = threading.RLock()
        self._catalog = None

    def catalog(self):
        if self._catalog is not None:
            return self._catalog
        slots = [{'id': name, 'types': ['Amps' if name == 'Amp' else 'Cabinets' if name == 'Cabinet'
                                      else 'Racks' if name.startswith('Rack') else 'Pedals']}
                 for name in self.engine._data('routing')['slot_order']]
        devices = []
        appearance = self.engine._data('device_appearance')['devices']
        artwork = json.loads((Path(__file__).parent / 'data/device_images.json').read_text(encoding='utf-8'))
        branding = json.loads((Path(__file__).parent / 'data/device_image_branding.json').read_text(encoding='utf-8'))
        for key, device in self.engine._data('devices')['devices'].items():
            allowed = [s['id'] for s in slots if device['type'] in s['types']]
            plan = self.engine.inspect_tone({'Volume': -12, 'GearList': {
                allowed[0]: {'Key': key, 'Type': device['type']}}})
            behavior = {c['name']: c.get('behavior', 'active') for c in plan['controls']}
            controls = []
            for knob in device['knobs']:
                source = knob['source']
                editable = all(k in source for k in ('RTPC', 'MinValue', 'MaxValue', 'DefaultValue')) and knob['rtpc_id'] is not None
                choices = [{'label': label, 'value': float(value)}
                           for label, value in source.get('EnumValues', {}).items()]
                controls.append({'name': source.get('RTPC'), 'label': source.get('Name', 'Source placeholder'),
                                 'minimum': source.get('MinValue'), 'maximum': source.get('MaxValue'),
                                 'default': source.get('DefaultValue'), 'step': source.get('ValueStep'),
                                 'unit': source.get('UnitType'), 'choices': choices, 'editable': editable,
                                 'behavior': behavior.get(source.get('RTPC'), 'metadata-only'), 'source': source})
            visual = appearance.get(key, {})
            fields = visual.get('fields', {})
            color = fields.get('PersonalityColor')
            color = '#' + color if isinstance(color, str) and re.fullmatch('[0-9a-fA-F]{6}', color) else None
            image_key = artwork['devices'][key]
            image = artwork['images'][image_key]
            devices.append({'key': key, 'name': device['name'], 'type': device['type'],
                            'category': device['category'], 'slots': allowed, 'controls': controls,
                            'associated_cab_key': device.get('associated_cab_key'),
                            'appearance': {'color': color, 'fields': fields, 'knobs': visual.get('knobs', []),
                                           'image': {'url': '/api/plugins/feedtone/device-images/' + image_key,
                                                     'dimensions': image['dimensions'],
                                                     'badges': [] if branding.get('baked') else branding['images'][image_key]['regions']}},
                            'renderable': plan['renderable'], 'issues': plan['issues']})
        self._catalog = {'devices': devices, 'slots': slots,
                         'volume': {'minimum': -36, 'maximum': 0, 'default': -12, 'unit': 'dB',
                                    'zero_effective': -36,
                                    'note': 'Source behavior: zero selects the -36 fallback; negative values follow the original volume curve.'},
                         'step_policy': 'Source step is UI guidance; continuous authored values are preserved. Explicit enum choices are discrete.'}
        return self._catalog

    @staticmethod
    def _number(value, label):
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError(label + ' must be numeric')
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(label + ' must be numeric') from exc
        if not math.isfinite(result):
            raise ValueError(label + ' must be finite')
        return result

    def validate(self, definition, original=None):
        if not isinstance(definition, dict):
            raise ValueError('definition must be an object')
        try:
            payload = json.dumps(definition, allow_nan=False)
            if len(payload.encode()) > 262144:
                raise ValueError('Tone definition exceeds 256 KiB')
            value = json.loads(payload)
        except (TypeError, RecursionError) as exc:
            raise ValueError('Tone metadata must be finite JSON') from exc
        if original is not None:
            value = {**copy.deepcopy(original), **value}
        gears = value.get('GearList')
        if not isinstance(gears, dict):
            raise ValueError('Tone requires a GearList object')
        custom = self.engine.chain_order(value) is not None
        slots = {s['id']: s['types'] for s in self.catalog()['slots']}
        catalog = self.engine._data('devices')['devices']
        raw_volume = value.get('Volume', 0)
        old_volume = original.get('Volume', 0) if original else None
        unchanged_volume = original is not None and fingerprint(raw_volume) == fingerprint(old_volume)
        try:
            volume = self._number(raw_volume, 'Volume')
        except ValueError:
            if not unchanged_volume:
                raise
            volume = None
        if volume is not None and not unchanged_volume and original is not None:
            try:
                unchanged_volume = volume == self._number(old_volume, 'Original Volume')
            except ValueError:
                pass
        if volume is not None and not -36 <= volume <= 0 and not unchanged_volume:
            raise ValueError('Edited Volume must be between -36 and 0')
        for field in ('Name', 'ToneName'):
            if field in value and (not isinstance(value[field], str) or len(value[field]) > 512):
                raise ValueError(field + ' must be a string of at most 512 characters')
        for slot, gear in gears.items():
            old = (original or {}).get('GearList', {}).get(slot, {})
            unchanged_gear = original is not None and slot in original.get('GearList', {}) and fingerprint(gear) == fingerprint(old)
            if slot not in slots or not isinstance(gear, dict):
                if unchanged_gear:
                    continue
                raise ValueError('Unknown or invalid gear slot: ' + str(slot))
            key = gear.get('Key') or gear.get('PedalKey')
            if not isinstance(key, str) or key not in catalog:
                if unchanged_gear:
                    continue
                raise ValueError('Unknown source device: ' + str(key))
            device = catalog[key]
            if (not custom and device['type'] not in slots[slot]) or gear.get('Type', device['type']) != device['type']:
                if unchanged_gear:
                    continue
                raise ValueError('Device type does not match gear slot: ' + slot)
            if gear.get('Key') and gear.get('PedalKey') and gear['Key'] != gear['PedalKey']:
                raise ValueError('Conflicting device keys')
            if not isinstance(old, dict) or (old.get('Key') or old.get('PedalKey')) != key:
                old = {}
            # Preserve non-DSP metadata for a retained source device. Knobs remain
            # the explicit edited map, so removing a value restores its default.
            gears[slot] = gear = {**copy.deepcopy(old), **gear}
            supplied = gear.get('KnobValues', {})
            if not isinstance(supplied, dict):
                raise ValueError('KnobValues must be an object')
            knobs = {k['source'].get('RTPC'): k['source'] for k in device['knobs'] if k['source'].get('RTPC') is not None}
            for name, scalar in supplied.items():
                old_knobs = old.get('KnobValues', {})
                unchanged_scalar = (isinstance(old_knobs, dict) and name in old_knobs
                                    and fingerprint(scalar) == fingerprint(old_knobs[name]))
                if name not in knobs:
                    if unchanged_scalar:
                        # Preserve unknown imported metadata without interpreting
                        # it as an alias or effect. The engine decides whether
                        # the complete edited definition can actually render.
                        continue
                    raise ValueError('Unknown control for ' + key + ': ' + str(name))
                try:
                    numeric = self._number(scalar, name)
                except ValueError:
                    if unchanged_scalar:
                        continue
                    raise
                source = knobs[name]
                unchanged = unchanged_scalar
                if not unchanged and name in old_knobs:
                    try:
                        unchanged = numeric == self._number(old_knobs[name], name)
                    except ValueError:
                        pass
                if 'MinValue' in source and 'MaxValue' in source and not source['MinValue'] <= numeric <= source['MaxValue'] and not unchanged:
                    raise ValueError('Control outside source range: ' + name)
                choices = source.get('EnumValues')
                if choices and numeric not in [float(x) for x in choices.values()] and not unchanged:
                    raise ValueError('Control must use a source enum choice: ' + name)
        return value

    def _read(self):
        if not self.path.exists():
            return {'version': 1, 'rigs': {}, 'overrides': {}}
        if self.path.stat().st_size > 16777216:
            raise ValueError('Designer settings exceed 16 MiB')
        try:
            state = json.loads(self.path.read_text(encoding='utf8'))
        except (OSError, ValueError) as exc:
            raise ValueError('Designer settings cannot be read; existing settings were retained') from exc
        if not isinstance(state, dict) or state.get('version') != 1 or any(not isinstance(state.get(k), dict) for k in ('rigs', 'overrides')):
            raise ValueError('Unsupported designer settings; existing settings were retained')
        for key, entry in state['rigs'].items():
            if (not isinstance(entry, dict) or entry.get('id') != key
                    or not isinstance(entry.get('name'), str) or not isinstance(entry.get('definition'), dict)):
                raise ValueError('Invalid saved rig; existing settings were retained')
        for entry in state['overrides'].values():
            if (not isinstance(entry, dict) or not isinstance(entry.get('source_hash'), str)
                    or not isinstance(entry.get('definition'), dict)):
                raise ValueError('Invalid saved override; existing settings were retained')
        return state

    def _write(self, state):
        raw = json.dumps(state, ensure_ascii=False, allow_nan=False, indent=2).encode('utf8')
        if len(raw) > 16777216:
            raise ValueError('Designer settings exceed 16 MiB')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.designer-', suffix='.tmp', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def scope(filename, arrangement, tone):
        return json.dumps([filename, arrangement, tone], separators=(',', ':'))

    def effective(self, scope, original):
        with self.lock:
            entry = self._read()['overrides'].get(scope)
        digest = fingerprint(original)
        if entry is not None and (not isinstance(entry, dict) or entry.get('source_hash') != digest):
            return {'definition': copy.deepcopy(original), 'has_override': False, 'stale_override': True, 'source_hash': digest}
        return {'definition': self.validate(entry['definition'], original) if entry else copy.deepcopy(original),
                'has_override': entry is not None, 'stale_override': False, 'source_hash': digest}

    def save_override(self, scope, original, definition, source_hash):
        if source_hash != fingerprint(original):
            raise ValueError('Original tone changed; reload before saving')
        definition = self.validate(definition, original)
        with self.lock:
            state = self._read()
            state['overrides'][scope] = {'source_hash': source_hash, 'definition': definition}
            self._write(state)
        return self.effective(scope, original)

    def reset(self, scope):
        with self.lock:
            state = self._read()
            state['overrides'].pop(scope, None)
            self._write(state)

    def rigs(self):
        with self.lock:
            return list(self._read()['rigs'].values())

    def save_rig(self, name, definition, identity=None, original=None):
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError('Rig name must contain 1 to 200 characters')
        if identity is not None and (not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity)):
            raise ValueError('Invalid saved rig id')
        with self.lock:
            state = self._read()
            if identity is not None and identity not in state['rigs']:
                raise ValueError('Saved rig was not found')
            baseline = original if original is not None else state['rigs'].get(identity, {}).get('definition')
            definition = self.validate(definition, baseline)
            identity = identity or uuid.uuid4().hex
            entry = {'id': identity, 'name': name.strip(), 'definition': definition}
            state['rigs'][identity] = entry
            self._write(state)
        return entry

    def delete_rig(self, identity):
        with self.lock:
            state = self._read()
            if identity not in state['rigs']:
                raise ValueError('Saved rig was not found')
            del state['rigs'][identity]
            self._write(state)
