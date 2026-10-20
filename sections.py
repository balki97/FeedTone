"""Personal tone/mix ranges, isolated from source packages.

SectionStore(config_dir).get/save/delete use a relative filename and arrangement
ID as their scope. Save replaces that scope's ordered list; later list entries
win overlapping [start, end) ranges. resolve() supports arbitrary seeking.
No rig/tone existence is inferred here; routes must validate those selections.

Each range has stable id/start/end, optional label, and at least one setting:
tone_key OR rig_id, guitar_trim_db (-12..12 dB), song_volume (0..100 percent).
Times are finite seconds with 0 <= start < end. Maximum 500 ranges per scope.
Absent scopes return []; malformed stored scopes raise ValueError. Save/delete
return the resulting validated list. No optimistic revision protocol is implied.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import tempfile
import threading

MAX_RANGES = 500
MAX_BYTES = 2 * 1024 * 1024
_FIELDS = {'id', 'start', 'end', 'tone_key', 'rig_id', 'guitar_trim_db', 'song_volume', 'label'}


def _text(value, name, limit):
    if not isinstance(value, str) or not value.strip() or '\0' in value or len(value) > limit:
        raise ValueError(f'{name} must be a nonempty string of at most {limit} characters')
    return value


def _number(value, name, low=0, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a finite number')
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f'{name} must be a finite number') from None
    if not math.isfinite(number) or number < low or (high is not None and number > high):
        raise ValueError(f'{name} is outside its finite allowed range')
    return number


def _scope(filename, arrangement_id):
    filename = _text(filename, 'filename', 4096).replace('\\', '/')
    if filename.startswith('/') or PureWindowsPath(filename).drive or ':' in filename or any(p in ('', '.', '..') for p in filename.split('/')):
        raise ValueError('filename must be a relative path without traversal')
    return filename, _text(arrangement_id, 'arrangement_id', 256)


def validate_ranges(ranges):
    if not isinstance(ranges, list) or len(ranges) > MAX_RANGES:
        raise ValueError(f'ranges must be a list containing at most {MAX_RANGES} entries')
    result, ids = [], set()
    for value in ranges:
        if not isinstance(value, dict) or set(value) - _FIELDS:
            raise ValueError('Range contains unknown fields or is not an object')
        entry = {'id': _text(value.get('id'), 'range id', 120),
                 'start': _number(value.get('start'), 'start'),
                 'end': _number(value.get('end'), 'end')}
        if entry['id'] in ids or entry['start'] >= entry['end']:
            raise ValueError('Range IDs must be unique and start must be before end')
        ids.add(entry['id'])
        if 'tone_key' in value and 'rig_id' in value:
            raise ValueError('Choose tone_key or rig_id, not both')
        if not any(k in value for k in ('tone_key', 'rig_id', 'guitar_trim_db', 'song_volume')):
            raise ValueError('Range needs a tone, rig, guitar trim or song volume')
        for key in ('tone_key', 'rig_id'):
            if key in value:
                entry[key] = _text(value[key], key, 512)
        if 'guitar_trim_db' in value:
            entry['guitar_trim_db'] = _number(value['guitar_trim_db'], 'guitar_trim_db', -12, 12)
        if 'song_volume' in value:
            entry['song_volume'] = _number(value['song_volume'], 'song_volume', 0, 100)
        if 'label' in value:
            if not isinstance(value['label'], str) or len(value['label']) > 120 or '\0' in value['label']:
                raise ValueError('label must be at most 120 characters')
            entry['label'] = value['label']
        result.append(entry)
    return result


def resolve(ranges, time):
    """Return the last saved matching range, or None; end is exclusive."""
    time = _number(time, 'time', -math.inf)
    for entry in reversed(validate_ranges(ranges)):
        if entry['start'] <= time < entry['end']:
            return entry
    return None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate stored JSON key')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('Nonfinite stored JSON')


class SectionStore:
    def __init__(self, config_dir):
        self.config_dir = Path(config_dir).resolve()
        self.root = self.config_dir / 'sections'
        self._lock = threading.RLock()

    def _path(self, filename, arrangement_id):
        filename, arrangement_id = _scope(filename, arrangement_id)
        token = hashlib.sha256(json.dumps([filename, arrangement_id], ensure_ascii=False).encode('utf-8')).hexdigest()
        path = self.root / (token + '.json')
        if not self.root.resolve().is_relative_to(self.config_dir) or path.is_symlink():
            raise ValueError('Section storage escapes its config directory')
        return path, filename, arrangement_id

    def get(self, filename, arrangement_id):
        with self._lock:
            path, filename, arrangement_id = self._path(filename, arrangement_id)
            try:
                with path.open('rb') as stream:
                    payload = stream.read(MAX_BYTES + 1)
            except FileNotFoundError:
                return []
            if len(payload) > MAX_BYTES:
                raise ValueError('Stored sections exceed the size limit')
            try:
                data = json.loads(payload, object_pairs_hook=_object, parse_constant=_reject_constant)
            except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
                raise ValueError('Stored sections are malformed') from exc
            if not isinstance(data, dict) or set(data) != {'schema', 'filename', 'arrangement_id', 'ranges'} or data.get('schema') != 'feedtone.sections.v1' or (data.get('filename'), data.get('arrangement_id')) != (filename, arrangement_id):
                raise ValueError('Stored sections have the wrong schema or scope')
            return validate_ranges(data['ranges'])

    def save(self, filename, arrangement_id, ranges):
        with self._lock:
            path, filename, arrangement_id = self._path(filename, arrangement_id)
            ranges = validate_ranges(ranges)
            self.get(filename, arrangement_id)  # Do not silently overwrite a corrupt existing file.
            payload = json.dumps({'schema': 'feedtone.sections.v1', 'filename': filename,
                'arrangement_id': arrangement_id, 'ranges': ranges}, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
            if len(payload) > MAX_BYTES:
                raise ValueError('Sections exceed the size limit')
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='wb', dir=self.root, prefix='.sections-', suffix='.tmp', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return ranges

    def delete(self, filename, arrangement_id, range_id):
        with self._lock:
            range_id = _text(range_id, 'range id', 120)
            ranges = self.get(filename, arrangement_id)
            updated = [value for value in ranges if value['id'] != range_id]
            return self.save(filename, arrangement_id, updated) if len(updated) != len(ranges) else ranges
