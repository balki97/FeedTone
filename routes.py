"""FeedBack routes for original tone metadata and standalone engine presets."""
from pathlib import Path
import json
import time
import re
import sys
import threading

from fastapi import Body, HTTPException
from fastapi.responses import FileResponse


def setup(app, context):
    tone_input = context["load_sibling"]("tone_input")
    engine = context["load_sibling"]("engine")
    config_root = Path(context["config_dir"]) / "feedtone"
    cache_root = config_root / "cache"
    python = str(context.get("python_executable") or sys.executable)
    designer_instance = None
    designer_lock = threading.Lock()
    balance_instance = None
    balance_lock = threading.Lock()
    sections_instance = None
    updater_instance = None
    updater_lock = threading.Lock()

    def updates():
        nonlocal updater_instance
        with updater_lock:
            if updater_instance is None:
                module = context['load_sibling']('updater')
                options = {'fetcher': context['update_fetcher']} if context.get('update_fetcher') else {}
                updater_instance = module.Updater(Path(__file__).parent, config_root, python, **options)
        return updater_instance

    @app.get('/api/plugins/feedtone/updates')
    def update_status():
        manager = updates()
        if manager.auto and (not manager.checked or time.monotonic() - manager.checked > 21600):
            manager.start('check')
        return manager.snapshot()

    @app.post('/api/plugins/feedtone/updates/check')
    def check_update():
        return updates().start('check')

    @app.post('/api/plugins/feedtone/updates/settings')
    def update_settings(data: dict = Body(...)):
        result = guarded(lambda: updates().settings(data.get('automatic')))
        return updates().start('check') if result['automatic'] else result

    @app.post('/api/plugins/feedtone/updates/install')
    def install_update():
        return updates().start('install')

    def sections():
        nonlocal sections_instance
        if sections_instance is None:
            sections_instance = context['load_sibling']('sections').SectionStore(cache_root.parent)
        return sections_instance

    def balance():
        nonlocal balance_instance
        with balance_lock:
            if balance_instance is None:
                module = context['load_sibling']('balance')
                balance_instance = module.Balance(cache_root.parent, python,
                    analyzer=context.get('balance_analyzer'))
        return balance_instance

    def designer():
        nonlocal designer_instance
        with designer_lock:
            if designer_instance is None:
                module = context["load_sibling"]("designer")
                designer_instance = module.Designer(engine, cache_root.parent)
        return designer_instance

    def guarded(operation):
        try:
            return operation()
        except (ValueError, OSError, RuntimeError, ImportError) as exc:
            raise HTTPException(400, str(exc)) from exc

    def song(filename):
        try:
            relative = tone_input._relative_path(filename)
            root = Path(context["get_dlc_dir"]()).resolve()
            path = root.joinpath(*relative.split("/"))
            if not path.resolve().is_relative_to(root):
                raise HTTPException(400, "Song path escapes the DLC folder")
            if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                   for p in (path, *path.parents) if p != root and p.is_relative_to(root)):
                raise HTTPException(400, "Linked song paths are not allowed")
            if not path.exists():
                raise HTTPException(404, "Song file is not available locally")
            if not path.is_dir() and path.suffix.lower() not in (".feedpak",):
                raise HTTPException(400, "Select a FeedPak containing original tone metadata")
            return tone_input.read_tones(path)
        except tone_input.ToneInputError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(400, "Cannot read song from the DLC folder") from exc

    def identify(definition):
        return [definition.get(key) for key in ("Key", "ToneKey", "key", "Name", "ToneName", "name")
                if isinstance(definition.get(key), str) and definition[key]]

    def source_key(value):
        # Observed MSVCR100 _stricmp under the C locale folds ASCII bytes only.
        return value.split('\0', 1)[0].translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))

    def inspect(definition):
        try:
            return engine.inspect_tone(definition)
        except (ValueError, OSError, RuntimeError, ImportError) as exc:
            return {"renderable": False, "unsupported_plugin_ids": [], "stages": [],
                    "issues": [str(exc)], "status": "unavailable"}

    def resolve(data):
        filename, arrangement_id, key = (data.get(name) for name in ("filename", "arrangement_id", "tone_key"))
        if not all(isinstance(value, str) and value and len(value) <= 4096
                   for value in (filename, arrangement_id, key)):
            raise HTTPException(400, "filename, arrangement_id, and tone_key must be nonempty strings")
        result = song(filename)
        arrangements = [a for a in result["arrangements"] if a["id"] == arrangement_id]
        if len(arrangements) != 1:
            raise HTTPException(404, "Original arrangement id was not found")
        definitions = arrangements[0]["definitions"]
        explicit = re.fullmatch(r"definition:(0|[1-9][0-9]*)", key)
        if explicit:
            index = int(explicit.group(1))
            matches = [definitions[index]] if index < len(definitions) else []
        else:
            # Original manifest lookup returns the first C-locale _stricmp match.
            exact = [definition for definition in definitions if isinstance(definition.get('Key'), str)
                     and source_key(definition['Key']) == source_key(key)]
            matches = exact[:1] if exact else [definition for definition in definitions if key in identify(definition)]
        if not matches:
            raise HTTPException(404, "Original tone was not found in this arrangement")
        if len(matches) != 1:
            raise HTTPException(409, "Tone name is ambiguous; use the explicit definition handle")
        definition = matches[0]
        index = next(i for i, item in enumerate(definitions) if item is definition)
        return result, arrangement_id, "definition:" + str(index), definition

    @app.get("/api/plugins/feedtone/status")
    def status():
        try:
            coverage = engine.coverage()
        except (ValueError, OSError, RuntimeError, ImportError) as exc:
            coverage = {"status": "unavailable", "error": str(exc), "renderable": False}
        return {"experimental": True, "default_enabled": False, "engine": coverage,
                "input_formats": ["feedpak", "feedpak-directory"],
                "raw_archives_supported": False}

    @app.get("/api/plugins/feedtone/song")
    def get_song(filename: str):
        result = song(filename)
        for arrangement in result["arrangements"]:
            arrangement["tone_plans"] = [{"tone_key": f"definition:{i}",
                                          "original_key": definition.get('Key'),
                                          "aliases": identify(definition),
                                          "plan": inspect(definition)}
                                         for i, definition in enumerate(arrangement["definitions"])]
        if (cache_root.parent / "designer.json").exists():
            for arrangement in result["arrangements"]:
                for index, entry in enumerate(arrangement["tone_plans"]):
                    scope = designer().scope(tone_input._relative_path(filename), arrangement["id"], entry["tone_key"])
                    effective = guarded(lambda: designer().effective(scope, arrangement["definitions"][index]))
                    entry.update(has_override=effective["has_override"], stale_override=effective["stale_override"])
                    if effective["has_override"]:
                        entry["original_plan"] = entry["plan"]
                        entry["plan"] = inspect(effective["definition"])
                    elif effective["stale_override"]:
                        entry["original_plan"] = entry["plan"]
                        entry["plan"] = {"renderable": False, "issues": ["Saved override is stale; reload or reset it"]}
        return result

    @app.post("/api/plugins/feedtone/preset")
    def preset(data: dict = Body(...)):
        result, arrangement_id, key, original = resolve(data)
        effective = {"definition": original, "has_override": False, "stale_override": False}
        if (cache_root.parent / "designer.json").exists():
            scope = designer().scope(tone_input._relative_path(data["filename"]), arrangement_id, key)
            effective = guarded(lambda: designer().effective(scope, original))
        if effective["stale_override"]:
            raise HTTPException(409, "Original tone changed; reset or reload the saved override before playback")
        definition = effective["definition"]
        plan = inspect(definition)
        if not plan.get("renderable"):
            raise HTTPException(409, {"message": "This complete original tone is not supported yet; existing audio remains unchanged",
                                      "plan": plan})
        try:
            prepared = engine.prepare_preset(definition, title=result["title"], cache_root=cache_root,
                                             python_executable=python)
        except (ValueError, OSError, RuntimeError, ImportError) as exc:
            raise HTTPException(409, {"message": "Original tone preset could not be prepared; existing audio remains unchanged",
                                      "reason": str(exc)}) from exc
        if not isinstance(prepared, dict) or not isinstance(prepared.get("native_preset"), dict):
            raise HTTPException(500, "Engine returned no complete native preset")
        prepared = guarded(lambda: balance().apply(prepared, definition,
            tone_input._relative_path(data['filename']),
            json.dumps([tone_input._relative_path(data['filename']), arrangement_id, key],separators=(',',':'))))
        return {**prepared, "arrangement_id": arrangement_id, "tone_key": key,
                "has_override": effective["has_override"], "definition": definition}

    @app.get("/api/plugins/feedtone/designer/catalog")
    def designer_catalog():
        return guarded(lambda: designer().catalog())

    @app.get('/api/plugins/feedtone/device-images/{image_key}')
    def device_image(image_key: str):
        if not re.fullmatch(r'gear_[a-z0-9_]+', image_key):
            raise HTTPException(404, 'Device image was not found')
        image = Path(__file__).parent / 'data' / 'device-images' / (image_key + '.png')
        if not image.is_file():
            raise HTTPException(404, 'Device image was not found')
        return FileResponse(image, media_type='image/png', headers={'Cache-Control': 'public, max-age=86400'})

    def tone_context(data):
        result, arrangement, key, original = resolve(data)
        scope = designer().scope(tone_input._relative_path(data["filename"]), arrangement, key)
        return result, arrangement, key, original, scope

    def edit_baseline(data):
        if any(k in data for k in ("filename", "arrangement_id", "tone_key", "source_hash")):
            _, _, _, original, scope = tone_context(data)
            effective = guarded(lambda: designer().effective(scope, original))
            if data.get("source_hash") != effective["source_hash"]:
                raise HTTPException(409, "Original tone changed; reload before editing")
            return original
        identity = data.get("rig_id")
        if identity is not None:
            matches = [entry for entry in guarded(lambda: designer().rigs()) if entry['id'] == identity]
            if len(matches) != 1:
                raise HTTPException(404, "Saved rig was not found")
            return matches[0]['definition']
        return None

    def balance_scope(data):
        if data.get('filename') and not data.get('tone_key'):
            song(data['filename'])
            return tone_input._relative_path(data['filename']), None
        if any(k in data for k in ('filename','arrangement_id','tone_key')):
            _, arrangement, key, _ = resolve(data)
            filename = tone_input._relative_path(data['filename'])
            return filename, json.dumps([filename,arrangement,key],separators=(',',':'))
        if data.get('rig_id') is not None:
            identity=data['rig_id']
            if not any(rig['id']==identity for rig in guarded(lambda: designer().rigs())):
                raise HTTPException(404,'Saved rig was not found')
            mix_song = data.get('song_filename')
            if mix_song is not None:
                song(mix_song)
                mix_song = tone_input._relative_path(mix_song)
            return mix_song,'rig:'+identity
        if data.get('song_filename'):
            song(data['song_filename'])
            return tone_input._relative_path(data['song_filename']),None
        return None,None

    @app.get('/api/plugins/feedtone/balance')
    def get_balance(filename: str = None, arrangement_id: str = None, tone_key: str = None, rig_id: str = None):
        data={k:v for k,v in locals().items() if v is not None}
        song_scope,tone_scope=balance_scope(data)
        return guarded(lambda: balance().settings(song_scope,tone_scope))

    @app.post('/api/plugins/feedtone/balance')
    def set_balance(data: dict = Body(...)):
        allowed={'filename','arrangement_id','tone_key','rig_id','enabled','trim_db','song_trim_db','tone_trim_db','song_volume'}
        if set(data)-allowed:
            raise HTTPException(400,'Unknown listening setting')
        song_scope,tone_scope=balance_scope(data)
        changes={k:v for k,v in data.items() if k not in ('filename','arrangement_id','tone_key','rig_id')}
        return guarded(lambda: balance().update(changes,song_scope,tone_scope))

    def section_scope(filename, arrangement_id):
        loaded = song(filename)
        if not any(entry['id'] == arrangement_id for entry in loaded['arrangements']):
            raise HTTPException(404, 'Song arrangement was not found')
        return tone_input._relative_path(filename)

    @app.get('/api/plugins/feedtone/sections')
    def get_sections(filename: str, arrangement_id: str):
        filename = section_scope(filename, arrangement_id)
        return {'ranges': guarded(lambda: sections().get(filename, arrangement_id))}

    @app.post('/api/plugins/feedtone/sections')
    def save_sections(data: dict = Body(...)):
        if set(data) != {'filename', 'arrangement_id', 'ranges'}:
            raise HTTPException(400, 'Section changes need filename, arrangement_id and ranges')
        filename, arrangement_id = data['filename'], data['arrangement_id']
        filename = section_scope(filename, arrangement_id)
        ranges = guarded(lambda: context['load_sibling']('sections').validate_ranges(data['ranges']))
        if not isinstance(ranges, list) or len(ranges) > 500:
            raise HTTPException(400, 'Sections must be a list of at most 500 ranges')
        rig_ids = {item['id'] for item in guarded(lambda: designer().rigs())}
        for item in ranges:
            if not isinstance(item, dict):
                raise HTTPException(400, 'A section must be an object')
            if 'tone_key' in item:
                resolve({'filename': filename, 'arrangement_id': arrangement_id, 'tone_key': item['tone_key']})
            if 'rig_id' in item and item['rig_id'] not in rig_ids:
                raise HTTPException(404, 'A saved section rig was not found')
        return {'ranges': guarded(lambda: sections().save(filename, arrangement_id, ranges))}

    @app.get("/api/plugins/feedtone/designer/tone")
    def designer_tone(filename: str, arrangement_id: str, tone_key: str):
        data = {"filename": filename, "arrangement_id": arrangement_id, "tone_key": tone_key}
        _, arrangement, key, original, scope = tone_context(data)
        effective = guarded(lambda: designer().effective(scope, original))
        return {**effective, "interpreted_volume": inspect(effective['definition']).get('volume'), "original_definition": original,
                "arrangement_id": arrangement, "tone_key": key}

    @app.post("/api/plugins/feedtone/designer/prepare")
    def designer_prepare(data: dict = Body(...)):
        original = edit_baseline(data)
        definition = guarded(lambda: designer().validate(data.get("definition"), original))
        plan = inspect(definition)
        if not plan.get("renderable"):
            raise HTTPException(409, {"message": "Edited tone is unsupported; existing audio remains unchanged", "plan": plan})
        title = data.get("title", definition.get("Name", "Designer rig"))
        if not isinstance(title, str) or len(title) > 512:
            raise HTTPException(400, "title must be a string of at most 512 characters")
        try:
            prepared = engine.prepare_preset(definition, title=title, cache_root=cache_root, python_executable=python)
        except (ValueError, OSError, RuntimeError, ImportError) as exc:
            raise HTTPException(409, {"message": "Edited tone could not be prepared; existing audio remains unchanged", "reason": str(exc)}) from exc
        if not isinstance(prepared, dict) or not isinstance(prepared.get("native_preset"), dict):
            raise HTTPException(500, "Engine returned no complete native preset")
        song_scope,tone_scope=balance_scope(data)
        prepared=guarded(lambda: balance().apply(prepared,definition,song_scope,tone_scope))
        return {**prepared, "definition": definition}

    @app.post("/api/plugins/feedtone/designer/override")
    def designer_override(data: dict = Body(...)):
        _, arrangement, key, original, scope = tone_context(data)
        effective = guarded(lambda: designer().effective(scope, original))
        if data.get("source_hash") != effective["source_hash"]:
            raise HTTPException(409, "Original tone changed; reload before saving")
        return {**guarded(lambda: designer().save_override(scope, original, data.get("definition"), data.get("source_hash"))),
                "arrangement_id": arrangement, "tone_key": key}

    @app.post("/api/plugins/feedtone/designer/reset")
    def designer_reset(data: dict = Body(...)):
        _, arrangement, key, original, scope = tone_context(data)
        guarded(lambda: designer().reset(scope))
        return {**guarded(lambda: designer().effective(scope, original)), "original_definition": original,
                "arrangement_id": arrangement, "tone_key": key}

    @app.get("/api/plugins/feedtone/designer/rigs")
    def designer_rigs():
        return {"rigs": [{**rig, "interpreted_volume": inspect(rig['definition']).get('volume')}
                         for rig in guarded(lambda: designer().rigs())]}

    @app.post("/api/plugins/feedtone/designer/rigs")
    def designer_save_rig(data: dict = Body(...)):
        baseline = edit_baseline(data)
        return guarded(lambda: designer().save_rig(data.get("name"), data.get("definition"), data.get("id"), baseline))

    @app.delete("/api/plugins/feedtone/designer/rigs/{identity}")
    def designer_delete_rig(identity: str):
        guarded(lambda: designer().delete_rig(identity))
        return {"deleted": True}
