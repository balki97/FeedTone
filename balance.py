"""Optional static listening gain; never changes authored tone or engine state."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading

VERSION = 1
ROOT = Path(__file__).resolve().parent


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def correction(analysis):
    """Gentle half-distance correction with a synthetic-DI peak headroom cap."""
    if not isinstance(analysis,dict) or not {'rms_dbfs','peak_dbfs'} <= analysis.keys():
        raise ValueError('Invalid listening analysis')
    rms, peak = analysis['rms_dbfs'], analysis['peak_dbfs']
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (rms, peak)):
        raise ValueError('Invalid listening analysis')
    if analysis.get('silent'):
        return 0.0
    return min(6.0, max(-6.0, (-24.0-rms)*0.5), -3.0-peak)


class Balance:
    def __init__(self, config_root, python_executable, *, analyzer=None, root=ROOT):
        self.root = Path(root)
        self.path = Path(config_root)/'balance.json'
        self.cache = Path(config_root)/'balance-cache'
        self.python = str(python_executable)
        self.analyzer = analyzer
        self.lock = threading.RLock()
        self._fingerprint = None

    def _read(self):
        if not self.path.exists():
            return {'version': VERSION, 'enabled': True, 'trim_db': 0.0, 'songs': {}, 'tones': {}}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != VERSION:
            raise ValueError('Unsupported listening settings file')
        if not {'enabled','trim_db','songs','tones'} <= data.keys() or not isinstance(data['songs'],dict) or not isinstance(data['tones'],dict):
            raise ValueError('Invalid listening settings file')
        if not isinstance(data.get('song_volumes',{}),dict):
            raise ValueError('Invalid song-volume settings')
        for value in data.get('song_volumes',{}).values():
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=100:
                raise ValueError('Invalid saved song volume')
        return data

    @staticmethod
    def _db(value, limit):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value)>limit:
            raise ValueError('Listening trim must be finite and within +/-'+str(limit)+' dB')
        return float(value)

    @staticmethod
    def _scope(song, tone):
        for value in (song, tone):
            if value is not None and (not isinstance(value, str) or not value or len(value)>16384):
                raise ValueError('Invalid listening settings scope')
        return song, tone

    def settings(self, song=None, tone=None):
        self._scope(song, tone)
        with self.lock:
            data = self._read()
            enabled = data['enabled']
            if not isinstance(enabled, bool):
                raise ValueError('Invalid listening mode')
            return {'version': VERSION, 'enabled': enabled,
                    'trim_db': self._db(data['trim_db'],18),
                    'song_trim_db': self._db(data['songs'].get(song,0),12),
                    'song_volume': data.get('song_volumes', {}).get(song),
                    'tone_trim_db': self._db(data['tones'].get(tone,0),12)}

    @staticmethod
    def _write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as file:
                file.write(_json(data)+'\n')
                file.flush()
                os.fsync(file.fileno())
            os.replace(name,path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def update(self, changes, song=None, tone=None):
        self._scope(song, tone)
        if not isinstance(changes,dict) or set(changes)-{'enabled','trim_db','song_trim_db','tone_trim_db','song_volume'}:
            raise ValueError('Unknown listening setting')
        with self.lock:
            data = self._read()
            for key,value in changes.items():
                if key=='enabled':
                    if not isinstance(value,bool):
                        raise ValueError('enabled must be boolean')
                    data[key]=value
                elif key=='trim_db':
                    data[key]=self._db(value,18)
                elif key == 'song_volume':
                    if song is None:
                        raise ValueError('Select a song before changing its volume')
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
                        raise ValueError('Song volume must be between 0 and 100')
                    data.setdefault('song_volumes', {})[song] = float(value)
                else:
                    scope = song if key=='song_trim_db' else tone
                    if scope is None:
                        raise ValueError('Select a song or tone before changing its trim')
                    data['songs' if key=='song_trim_db' else 'tones'][scope]=self._db(value,12)
            self._write(self.path,data)
            return self.settings(song,tone)

    def fingerprint(self):
        if self._fingerprint is None:
            digest=hashlib.sha256(b'feed-tone-static-listening-v1')
            paths=[self.root/'balance_analyzer.py', self.root/'balance.py']
            for folder,pattern in [('engine','*.py'),('native','*.dll'),('data','*')]:
                paths.extend(sorted((self.root/folder).glob(pattern)))
            for path in paths:
                if path.is_file():
                    digest.update(str(path.relative_to(self.root)).encode())
                    digest.update(path.read_bytes())
            self._fingerprint=digest.hexdigest()
        return self._fingerprint

    def analyze(self, definition):
        identity=hashlib.sha256((self.fingerprint()+_json(definition)).encode()).hexdigest()
        destination=self.cache/(identity+'.json')
        with self.lock:
            if destination.is_file():
                result=json.loads(destination.read_text(encoding='utf-8'))
            elif self.analyzer is not None:
                result=self.analyzer(copy.deepcopy(definition))
                correction(result)
                self._write(destination,result)
            else:
                self.cache.mkdir(parents=True,exist_ok=True)
                descriptor,name=tempfile.mkstemp(prefix='.tone-',suffix='.json',dir=self.cache)
                try:
                    with os.fdopen(descriptor,'w',encoding='utf-8') as file:
                        file.write(_json(definition))
                    script=('import sys;sys.path.insert(0,'+repr(str(self.root))+');'
                            'from engine.runtime import configure_dependencies;configure_dependencies();'
                            'from balance_analyzer import main;main()')
                    process=subprocess.run([self.python,'-c',script,name],cwd=self.root,capture_output=True,
                        timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    if process.returncode:
                        raise RuntimeError('Static listening analysis could not render this rig')
                    result=json.loads(process.stdout)
                    correction(result)
                    self._write(destination,result)
                finally:
                    os.unlink(name)
            correction(result)
            return {**result,'cache_key':identity}

    def apply(self, prepared, definition, song=None, tone=None):
        settings=self.settings(song,tone)
        manual=sum(settings[k] for k in ('trim_db','song_trim_db','tone_trim_db'))
        info={**settings,'manual_db':manual,'auto_db':0.0,'analysis':None,'status':'off'}
        if settings['enabled']:
            try:
                info['analysis']=self.analyze(definition)
                info['auto_db']=correction(info['analysis'])
                info['status']='ready'
            except (ValueError,OSError,RuntimeError,subprocess.SubprocessError) as exc:
                info.update(status='unavailable',reason=str(exc))
        requested=manual+info['auto_db']
        total=requested
        if info['analysis'] and not info['analysis'].get('silent'):
            total=min(total,-3.0-info['analysis']['peak_dbfs'])
        peak_limited=total<requested
        host_limited=total>20*math.log10(16)
        total=min(total,20*math.log10(16))
        auto_capped = bool(info['analysis'] and not info['analysis'].get('silent') and
            info['auto_db'] < min(6.0,max(-6.0,(-24.0-info['analysis']['rms_dbfs'])*.5)))
        info.update(total_db=total,post_gain=min(16.0,10**(total/20)),
                    headroom_limited=peak_limited or auto_capped,host_gain_limited=host_limited)
        result=copy.deepcopy(prepared)
        chain=result['native_preset']['chain']
        if len(chain)!=1:
            raise ValueError('Listening gain requires the complete single-slot tone engine')
        chain[0]['postGain']=info['post_gain']
        result['balance']=info
        return result
