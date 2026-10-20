"""Standalone tone planning. DSP imports stay out of FeedBack's web process."""
import hashlib
import json
import logging
import math
import re
import shutil
import struct
import subprocess
import tempfile
import sys
import shlex
from .runtime import vst_path, native_root, platform_key, configure_dependencies
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@lru_cache
def _data(name):
    return json.loads((ROOT / 'data' / (name + '.json')).read_text(encoding='utf-8'))


def _f32(value):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('Tone values must be numeric') from exc
    if not math.isfinite(value):
        raise ValueError('Tone values must be finite')
    try:
        return struct.unpack('<f', struct.pack('<f', value))[0]
    except OverflowError as exc:
        raise ValueError('Tone value exceeds the source float32 range') from exc


_VOLUME_PREFIX = re.compile(r'^[\x09-\x0d ]*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?)')


def _parse_source_volume(value):
    """The observed C-locale MSVCR100 atof prefix, followed by source float32."""
    if isinstance(value, str):
        match = _VOLUME_PREFIX.match(value)
        value = float(match[1].replace('d', 'e').replace('D', 'e')) if match else 0.0
    return _f32(value)


def _control_exception(device, source):
    for entry in _data('control_exceptions')['entries']:
        if (entry['device'] == device['key'] and entry['manifest_sha256'] == device['source']['sha256']
                and entry['source'] == source):
            return entry['kind']
    return None


@lru_cache
def _imported_control_exceptions():
    data = _data('imported_control_exceptions')
    if any(hashlib.sha256((ROOT/'data'/(name+'.json')).read_bytes()).hexdigest() != data[field]
           for name, field in (('devices', 'catalog_sha256'),
                               ('profile_selection', 'profile_selection_sha256'))):
        return {}
    return {(entry['device'], entry['name'], entry['manifest_sha256']): entry
            for entry in data['entries']}


def coverage():
    counts = {}
    for profile in _data('devices')['profiles'].values():
        identity = profile['plugin_id']
        counts[identity] = counts.get(identity, 0) + 1
    implemented = {'0x810003': 'meter: native block tests bit-exact',
                   '0x690003': 'three-band EQ: native reference fixtures bit-exact',
                   '0x6e0003': 'lookahead limiter: native reference fixtures bit-exact',
                   '0x6d0003': 'noise gate: native reference fixtures bit-exact',
                   '0x6c0003': 'RMS compressor: all eight profiles mono/stereo reference fixtures bit-exact',
                   '0x91033': 'multiband distortion: all 52 profiles mono/stereo reference fixtures bit-exact',
                   '0x7e0003': 'six-band filter/waveshaper: all catalog mono/stereo reference fixtures bit-exact',
                   '0x830003': 'tremolo: all nine profiles and authored defaults mono/stereo reference fixtures bit-exact',
                   '0x6e1003': 'amplifier EQ: all 86 catalog profiles mono/stereo reference fixtures bit-exact',
                   '0x41033': 'Trash delay: all nine fully wet mono/stereo profiles and five-second automation fixtures bit-exact',
                   '0x870003': 'dual delay: all three source profiles and initialized-control/automation fixtures bit-exact',
                   '0x61033': 'phaser: all six authored profiles and lifecycle fixtures bit-exact; synthetic mixed-model controls have bounded rounding differences',
                   '0x880003': 'delay pitch: all source profiles, routing modes and live-control fixtures bit-exact',
                   '0x8a0003': 'dual-voice pitch: all five profiles, seven FFT windows, routing modes and live-control fixtures bit-exact',
                   '0x730003': 'FDN reverb: all three profiles, six-second wet tails, automation and reset fixtures bit-exact',
                   '0x7d0003': 'chorus/flanger: all 26 profiles, long LFO cycles and lifecycle fixtures bit-exact',
                   '0x760003': 'room reverb: all five profiles, six-second early/late paths, authored controls and reset fixtures bit-exact',
                   '0x7f0003': 'mono cabinet: all 444 native reference fixtures bit-exact with bundled FFT kernel'}
    return {'standalone': True, 'experimental': True, 'full_parity_verified': False,
            'devices': len(_data('devices')['devices']),
            'profiles': sum(counts.values()), 'cabinet_resources': 358,
            'runtime': {'platform': platform_key(), 'python': 'FeedBack embedded Python 3.12', 'sample_rate': 48000},
            'families': [{'plugin_id': key, 'profiles': count,
                          'implementation': implemented.get(key, 'not implemented'),
                          'implemented': key in implemented} for key, count in sorted(counts.items())],
            'limits': ['Whole-game output and input calibration are not verified.',
                       'Unsupported effects prevent loading the entire tone.',
                       'Original tone metadata is required in the FeedPak.']}


def chain_order(definition):
    order = definition.get('ChainOrder')
    if order is None:
        return None
    slots = _data('routing')['slot_order']
    if (not isinstance(order, list) or len(order) != len(slots)
            or any(not isinstance(slot, str) for slot in order) or set(order) != set(slots)):
        raise ValueError('ChainOrder must contain every chain position exactly once')
    return order


def _custom_plan(definition, order):
    gears = definition['GearList']
    if set(gears) - set(order):
        raise ValueError('Unknown custom chain position')
    result = inspect_tone({'Volume': definition.get('Volume', 0), 'GearList': {}})
    tail = result['stages']
    result['stages'] = []
    result['scoped_rtpc'] = {}
    for slot in order:
        if slot not in gears:
            continue
        gear = gears[slot]
        if not isinstance(gear, dict):
            raise ValueError('Gear entries must be objects')
        device = _data('devices')['devices'].get(gear.get('Key') or gear.get('PedalKey'))
        if device is None:
            result['issues'].append('Unknown device in ' + slot)
            continue
        canonical = {'Amps': 'Amp', 'Cabinets': 'Cabinet', 'Pedals': 'PrePedal1', 'Racks': 'Rack1'}[device['type']]
        plan = inspect_tone({'Volume': definition.get('Volume', 0), 'GearList': {canonical: gear}})
        result['issues'].extend(plan['issues'])
        result['unsupported_plugin_ids'].extend(plan['unsupported_plugin_ids'])
        result['scoped_rtpc'][slot] = plan['rtpc']
        for control in plan['controls']:
            result['controls'].append({**control, 'id': len(result['controls']), 'slot': slot})
        result['metadata_controls'].extend(plan['metadata_controls'])
        result['stages'].extend({**stage, 'slot': slot, 'control_scope': slot}
                                for stage in plan['stages'] if stage['device'] is not None)
    result['stages'].extend(tail)
    if len(result['controls']) >= 256:
        result['issues'].append('Custom chain exceeds 255 device controls')
    result['volume_control']['id'] = len(result['controls'])
    result['renderable'] = not result['issues'] and not result['unsupported_plugin_ids']
    return result


def inspect_tone(definition):
    from .curves import evaluate_curve
    if not isinstance(definition, dict) or not isinstance(definition.get('GearList'), dict):
        raise ValueError('Tone requires an original GearList object')
    order = chain_order(definition)
    if order is not None:
        return _custom_plan(definition, order)
    catalog, selection = _data('devices'), _data('profile_selection')
    rtpc = {int(k): v for k, v in _data('rtpc_defaults')['values'].items()}
    volume = _parse_source_volume(definition.get('Volume', 0))
    volume = volume if volume < 0 else -36.0
    rtpc[655737159] = volume
    stages, controls, metadata_controls, issues, unknown = [], [], [], [], set()
    pools = {'mono': [], 'stereo': []}
    slots = _data('routing')['slot_order']
    for slot in definition['GearList']:
        if slot not in slots:
            issues.append('Unknown gear slot: ' + slot)
    for slot in slots:
        gear = definition['GearList'].get(slot)
        if gear is None:
            continue
        if not isinstance(gear, dict):
            raise ValueError('Gear entries must be objects')
        key = gear.get('Key') or gear.get('PedalKey')
        device = catalog['devices'].get(key)
        if device is None:
            issues.append('Unknown device: ' + str(key))
            continue
        declared_type = gear.get('Type', device['type'])
        if declared_type != device['type']:
            issues.append('Gear type differs from source device: ' + key)
        pool = 'stereo' if declared_type == 'Racks' else 'mono'
        supplied = gear.get('KnobValues', {})
        if not isinstance(supplied, dict):
            raise ValueError('KnobValues must be an object')
        knobs, placeholders = {}, set()
        for knob in device['knobs']:
            source = knob['source']
            if (not all(field in source for field in ('RTPC', 'DefaultValue', 'MinValue', 'MaxValue'))
                    or knob['rtpc_id'] is None):
                if _control_exception(device, source) == 'metadata-only':
                    entry = {'device': key, 'slot': slot, 'source': source}
                    name = source.get('RTPC')
                    if name is not None:
                        placeholders.add(name)
                        if name in supplied:
                            entry['supplied_value'] = _f32(supplied[name])
                    metadata_controls.append(entry)
                else:
                    issues.append('Unresolved source control on device: ' + key)
                continue
            knobs[source['RTPC']] = knob
        for name in supplied:
            if name not in knobs and name not in placeholders:
                orphan = _imported_control_exceptions().get((key, name, device['source']['sha256']))
                if orphan is None:
                    issues.append('Unknown control: ' + str(name))
                else:
                    value = _f32(supplied[name])
                    rtpc[orphan['rtpc_id']] = value
                    metadata_controls.append({'device': key, 'slot': slot, 'source': {'RTPC': name},
                                              'supplied_value': value, 'rtpc_id': orphan['rtpc_id'],
                                              'behavior': 'authored-orphan'})
        for name, knob in knobs.items():
            source = knob['source']
            value = _f32(supplied.get(name, source['DefaultValue']))
            rtpc[knob['rtpc_id']] = value
            # The original setter forwards supplied finite RTPCs without a UI
            # range clamp. Keep imported values representable in normalized VST state.
            controls.append({'id': len(controls), 'rtpc_id': knob['rtpc_id'], 'name': name,
                             'label': source.get('Name', name),
                             'units': '' if source.get('UnitType') == 'number' else source.get('UnitType', ''),
                             'source_step': source.get('ValueStep'), 'source_type': source.get('Type'),
                             'choices': [{'label': label, 'value': value}
                                         for label, value in source.get('EnumValues', {}).items()],
                             'minimum': min(source['MinValue'], value),
                             'maximum': max(source['MaxValue'], value),
                             'source_minimum': source['MinValue'], 'source_maximum': source['MaxValue'],
                             'value': value, 'slot': slot})
        for effect in device['effects']:
            profile_key = selection['devices'].get(key, {}).get(str(effect['shareset_id']), effect['profile_key'])
            profile = selection['profiles'].get(profile_key) or catalog['profiles'][profile_key]
            pools[pool].append({'slot': slot, 'device': key, 'pool': pool, 'profile_key': profile_key,
                                'profile': profile})
    for pool in pools:
        if len(pools[pool]) > 40:
            issues.append('Original effect pool capacity exceeded: ' + pool)
        stages.extend(pools[pool])
    for identity in (3369694784, 265864380):
        profile = _data('gain')['profiles'][str(identity)]
        stages.append({'slot': 'ToneBalance' if identity == 3369694784 else 'FixedParent',
                       'device': None, 'pool': 'stereo', 'profile_key': 'gain:' + str(identity),
                       'profile': profile})
    subscribed = {c['rtpc_id'] for stage in stages for c in stage['profile']['curves']}
    for control in controls:
        control['subscribed'] = control['rtpc_id'] in subscribed
        if not control['subscribed']:
            gear = definition['GearList'][control['slot']]
            key = gear.get('Key') or gear.get('PedalKey')
            device = catalog['devices'][key]
            source = next(k['source'] for k in device['knobs'] if k['source'].get('RTPC') == control['name'])
            if key == 'Rack_StudioWahFilter' or _control_exception(device, source) == 'authored-inert':
                control['behavior'] = 'authored-inert'
            else:
                issues.append('Unresolved control subscription: ' + control['name'])
    supported = {f['plugin_id'] for f in coverage()['families'] if f['implemented']}
    for stage in stages:
        profile = stage['profile']
        identity = profile['plugin_id']
        if identity not in supported:
            unknown.add(identity)
        if identity == '0x7f0003' and (stage['pool'] != 'mono' or profile['curves']):
            issues.append('Cabinet routing or live controls are not reconstructed')
        stage['plugin_id'] = identity
        stage['initial_parameters'] = {str(c['plugin_parameter_id']): evaluate_curve(c, rtpc.get(c['rtpc_id'], 0.0))
                                       for c in profile['curves']}
    volume_control = {'id': len(controls), 'rtpc_id': 655737159, 'name': 'ToneVolume',
                      'label': 'Tone level', 'slot': 'Tone', 'units': 'db',
                      'minimum': min(-36.0, volume), 'maximum': 0.0,
                      'source_minimum': -36.0, 'source_maximum': 0.0, 'value': volume}
    return {'renderable': not unknown and not issues, 'unsupported_plugin_ids': sorted(unknown),
            'stages': stages, 'controls': controls, 'metadata_controls': metadata_controls, 'issues': issues, 'volume': volume,
            'volume_control': volume_control,
            'rtpc': {str(k): v for k, v in rtpc.items()}, 'sample_rate': 48000, 'quantum': 128,
            'full_parity_verified': False}


def prepare_preset(definition, *, title, cache_root, python_executable):
    from .vst_config import write_configuration
    from .vst_state import encode_original_vst_state
    plan = inspect_tone(definition)
    if not plan['renderable']:
        raise ValueError('Tone uses unsupported DSP: ' + ', '.join(plan['unsupported_plugin_ids'] + plan['issues']))
    python = Path(python_executable).resolve()
    if not python.is_file():
        raise ValueError('FeedBack Python runtime is unavailable')
    payload = json.dumps(definition, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    configuration = json.dumps({'root': str(ROOT), 'python': str(python), 'title': title,
                                'plan': plan}, sort_keys=True, allow_nan=False).encode()
    implementation = (ROOT/'engine/runtime.py').read_bytes() + b''.join(p.read_bytes() for p in sorted((ROOT/'engine').glob('*.py')))
    implementation += b''.join(p.read_bytes() for p in sorted(p for p in native_root().iterdir() if p.is_file() and p.suffix in ('.dll','.so','.dylib')))
    wrapper = b''.join(p.read_bytes() for p in sorted(vst_path().rglob('*')) if p.is_file()) if vst_path().is_dir() else vst_path().read_bytes()
    identity = hashlib.sha256(configuration + implementation + wrapper).hexdigest()
    cache_root = Path(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    destination = cache_root / identity
    if not destination.exists():
        temporary = Path(tempfile.mkdtemp(prefix='.building-', dir=cache_root))
        try:
            (shutil.copytree if vst_path().is_dir() else shutil.copy2)(vst_path(), temporary / 'FeedTone.vst3')
            (temporary / 'tone.json').write_bytes(payload)
            script = ('import sys;sys.path.insert(0,' + repr(str(ROOT)) + ');'
                      'from engine.runtime import configure_dependencies;configure_dependencies();'
                      'from engine.service import main;main()')
            try:
                check = subprocess.run([str(python), '-c', script, str(temporary/'tone.json'), '--validate'],
                                       cwd=ROOT, capture_output=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ValueError('Standalone audio runtime could not prepare this tone') from exc
            if check.returncode:
                logging.getLogger(__name__).warning('Tone initialization failed: %s', check.stderr.decode('utf-8', errors='replace')[-1500:])
                raise ValueError('Standalone engine could not initialize this tone; the current audio chain was retained')
            command = (subprocess.list2cmdline if sys.platform=='win32' else shlex.join)([str(python), '-c', script, str(destination / 'tone.json')])
            parameters = []
            for control in [*plan['controls'], plan['volume_control']]:
                width = control['maximum'] - control['minimum']
                parameters.append(dict(control, default_normalized=(control['value']-control['minimum'])/width if width else 0))
            uid = hashlib.sha256(b'feedtone.component' + payload).digest()[:16]
            controller = hashlib.sha256(b'feedtone.controller' + payload).digest()[:16]
            config_directory = temporary
            write_configuration(config_directory / 'feedtone-vst.config.bin', title=title[:100], vendor='FeedForge',
                                application=str(python), command_line=command, cwd=str(ROOT),
                                component_uid=uid, controller_uid=controller, parameters=parameters)
            try:
                temporary.rename(destination)
            except FileExistsError:
                if not destination.is_dir():
                    raise
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    normalized = [(c['value']-c['minimum'])/(c['maximum']-c['minimum']) if c['maximum'] != c['minimum'] else 0
                  for c in [*plan['controls'], plan['volume_control']]]
    preset = {'version': 1, 'noiseGate': {'enabled': False, 'thresholdDb': -60, 'releaseMs': 100, 'depthDb': -60},
              'tonePolish': {'enabled': False},
              'chain': [{'type': 0, 'name': title, 'path': str(destination / 'FeedTone.vst3'),
               'format': 'vst3', 'bypassed': False, 'slot': 'full_chain', 'rs_gear': 'feedtone-tone',
               'state': encode_original_vst_state(normalized)}]}
    return {'native_preset': preset, 'coverage': plan}
