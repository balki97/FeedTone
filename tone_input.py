"""Read authored reference tone metadata from a FeedPak without extracting it."""
from __future__ import annotations

import hashlib
import json
import math
import stat
import zipfile
import zlib
from pathlib import Path, PurePosixPath

import yaml

SCHEMA = "feedback.feedtone.input.v1"
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 20000
MAX_ARRANGEMENTS = 256


class ToneInputError(ValueError):
    """The package cannot provide safe, complete original tone metadata."""


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ToneInputError("Package paths must be nonempty relative POSIX paths")
    if any(ord(c) < 32 for c in value) or ":" in value:
        raise ToneInputError(f"Unsafe package path: {value!r}")
    parts = value.split("/")
    if any(part in ("", ".", "..") or part.endswith((" ", ".")) for part in parts):
        raise ToneInputError(f"Unsafe package path: {value!r}")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$", *(f"COM{i}" for i in "123456789¹²³"),
                *(f"LPT{i}" for i in "123456789¹²³")}
    if any(part.split(".", 1)[0].upper() in reserved for part in parts):
        raise ToneInputError(f"Unsafe device path: {value!r}")
    if PurePosixPath(value).is_absolute():
        raise ToneInputError(f"Unsafe package path: {value!r}")
    return value


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ToneInputError(f"Duplicate metadata key: {key!r}")
        result[key] = value
    return result


class _ManifestLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ToneInputError("YAML aliases are not allowed in package metadata")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        pairs = []
        for key, value in node.value:
            key = self.construct_object(key, deep=deep)
            if not isinstance(key, str):
                raise ToneInputError("Manifest keys must be strings")
            pairs.append((key, self.construct_object(value, deep=deep)))
        return _unique_pairs(pairs)


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ToneInputError(f"{label} must be a finite number")
    try:
        valid = math.isfinite(float(value))
    except (ValueError, OverflowError):
        valid = False
    if not valid:
        raise ToneInputError(f"{label} must be a finite number")


def _json(data: bytes):
    def invalid(value):
        raise ToneInputError(f"Non-finite JSON number: {value}")
    value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_pairs,
                       parse_constant=invalid)
    # Decimal overflow such as 1e999 is accepted by json.loads unless checked.
    def check(item):
        if isinstance(item, float) and not math.isfinite(item):
            raise ToneInputError("Non-finite JSON number")
        if isinstance(item, dict):
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
    check(value)
    return value


def _sections(document):
    values = document.get('sections') or []
    if not isinstance(values, list) or len(values) > 10000:
        raise ToneInputError('Invalid song sections')
    result = []
    for value in values:
        if not isinstance(value, dict):
            raise ToneInputError('Invalid song section')
        time = value.get('time', value.get('start_time', 0))
        _finite(time, 'Section time')
        if float(time) < 0 or not isinstance(value.get('name', ''), str):
            raise ToneInputError('Invalid song section')
        result.append({'start': float(time), 'label': value.get('name', 'Section'),
                       'number': str(value.get('number', ''))[:20]})
    return sorted(result, key=lambda item: item['start'])


def _arrangement(entry, document):
    if not isinstance(document, dict):
        raise ToneInputError("Arrangement JSON must be an object")
    tones = document.get("tones")
    if tones is None:
        tones = {}
    if not isinstance(tones, dict):
        raise ToneInputError("Arrangement tones must be an object")
    definitions = tones.get("definitions", [])
    changes = tones.get("changes", [])
    if not isinstance(definitions, list) or not isinstance(changes, list):
        raise ToneInputError("Tone definitions and changes must be lists")
    for definition in definitions:
        if not isinstance(definition, dict) or not isinstance(definition.get("GearList"), dict):
            raise ToneInputError("Every original tone definition must contain its GearList object")
        if "Volume" in definition:
            # Some shipped tones contain malformed numeric strings. Preserve
            # those for inspection/editing; the engine validates each tone
            # before playback instead of hiding every other arrangement.
            if not isinstance(definition["Volume"], str):
                _finite(definition["Volume"], "Authored tone Volume")
        for gear in definition["GearList"].values():
            if not isinstance(gear, dict):
                raise ToneInputError("Original GearList entries must be objects")
            knobs = gear.get("KnobValues", {})
            if not isinstance(knobs, dict):
                raise ToneInputError("Original KnobValues must be an object")
            for value in knobs.values():
                _finite(value, "Original knob value")
    base = tones.get("base")
    if base is not None and not isinstance(base, str):
        raise ToneInputError("Tone base must be a string or null")
    if "base_rig" in tones and not isinstance(tones["base_rig"], str):
        raise ToneInputError("Tone base_rig must be a string")
    for change in changes:
        if not isinstance(change, dict) or "t" not in change:
            raise ToneInputError("Every tone change must contain its authored t value")
        _finite(change["t"], "Tone change time")
        for key in ("name", "rig"):
            if key in change and not isinstance(change[key], str):
                raise ToneInputError(f"Tone change {key} must be a string")
        if not change.get("name") and not change.get("rig"):
            raise ToneInputError("Tone change must identify its name or rig")
    result = {"id": entry["id"], "name": entry.get("name", entry["id"]),
              "definitions": definitions, "base": base, "changes": changes, "sections": _sections(document)}
    if "base_rig" in tones:
        result["base_rig"] = tones["base_rig"]
    return result


def _read_package(read):
    manifest = yaml.load(read("manifest.yaml").decode("utf-8-sig"), Loader=_ManifestLoader)
    if not isinstance(manifest, dict):
        raise ToneInputError("Package manifest must be an object")
    entries = manifest.get("arrangements")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_ARRANGEMENTS:
        raise ToneInputError(f"Manifest must list 1 to {MAX_ARRANGEMENTS} arrangements")
    for key in ("title", "artist"):
        if not isinstance(manifest.get(key, ""), str):
            raise ToneInputError(f"Manifest {key} must be a string")
    duration = manifest.get('duration', 0)
    _finite(duration, 'Song duration')
    shared = _sections(_json(read(_relative_path(manifest['song_timeline'])))) if manifest.get('song_timeline') else None
    arrangements = []
    ids, paths = set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
            raise ToneInputError("Each arrangement must have a nonempty string id")
        if "name" in entry and not isinstance(entry["name"], str):
            raise ToneInputError("Arrangement name must be a string")
        path = _relative_path(entry.get("file"))
        if entry["id"].casefold() in ids or path.casefold() in paths:
            raise ToneInputError("Duplicate arrangement id or file")
        ids.add(entry["id"].casefold())
        paths.add(path.casefold())
        arrangement = _arrangement(entry, _json(read(path)))
        if shared is not None:
            arrangement['sections'] = shared
        arrangements.append(arrangement)
    return {"schema": SCHEMA, "title": manifest.get("title", ""),
            "artist": manifest.get("artist", ""), "duration": max(0, float(duration)), "arrangements": arrangements}


def read_tones(path: Path) -> dict:
    """Return raw, arrangement-scoped definitions/timeline; never remap controls.

    Input is a FeedPak ZIP or unpacked package directory. No package is unpacked,
    written, or imported as code. Raw PSARC is intentionally unsupported.
    """
    path = Path(path).expanduser().resolve()
    if not path.is_dir() and path.suffix.lower() != ".feedpak":
        raise ToneInputError("Select a converted FeedPak song package")
    total = 0

    def bounded(stream):
        nonlocal total
        data = stream.read(MAX_MEMBER_BYTES + 1)
        total += len(data)
        if len(data) > MAX_MEMBER_BYTES or total > MAX_METADATA_BYTES:
            raise ToneInputError("Package tone metadata exceeds size limits")
        return data

    try:
        if path.is_dir():
            def read(name):
                candidate = path.joinpath(*_relative_path(name).split("/"))
                resolved = candidate.resolve()
                if not resolved.is_relative_to(path):
                    raise ToneInputError("Package metadata path escapes its directory")
                # Reject links even when their current targets happen to be inside.
                if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                       for p in (candidate, *candidate.parents) if p != path and p.is_relative_to(path)):
                    raise ToneInputError("Linked package metadata is not allowed")
                if not candidate.is_file():
                    raise ToneInputError(f"Package metadata file is missing or not regular: {name}")
                with candidate.open("rb") as stream:
                    return bounded(stream)
            result = _read_package(read)
        else:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_ENTRIES:
                    raise ToneInputError("Package contains too many ZIP entries")
                files, seen = {}, set()
                for info in infos:
                    original = info.orig_filename
                    name = _relative_path(original[:-1] if info.is_dir() else original)
                    if original != info.filename:
                        raise ToneInputError("ZIP path was altered by filename normalization")
                    if name.casefold() in seen:
                        raise ToneInputError(f"Duplicate ZIP entry: {name}")
                    seen.add(name.casefold())
                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                        raise ToneInputError("Linked or special ZIP entries are not allowed")
                    if info.flag_bits & 1:
                        raise ToneInputError("Encrypted ZIP entries are not supported")
                    if not info.is_dir():
                        files[name] = info

                def read(name):
                    name = _relative_path(name)
                    info = files.get(name)
                    if info is None:
                        raise ToneInputError(f"Package metadata file is missing: {name}")
                    if info.file_size > MAX_MEMBER_BYTES:
                        raise ToneInputError("Package metadata member exceeds size limit")
                    with archive.open(info) as stream:
                        return bounded(stream)
                result = _read_package(read)
        canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False,
                               separators=(",", ":")).encode("utf-8")
        result["source"] = {"path": str(path), "format": "feedpak-directory" if path.is_dir() else "feedpak",
                            "tone_metadata_sha256": hashlib.sha256(canonical).hexdigest()}
        return result
    except ToneInputError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError, OverflowError, RuntimeError, EOFError, zlib.error,
            zipfile.BadZipFile, zipfile.LargeZipFile, yaml.YAMLError) as exc:
        raise ToneInputError(f"Cannot read original package tone metadata: {exc}") from exc
