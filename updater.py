"""GitHub release updates, verified and installed only after the host exits."""
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

REPOSITORY = 'balki97/FeedTone'
API = 'https://api.github.com/repos/' + REPOSITORY + '/releases/latest'
DOWNLOAD = 'https://github.com/' + REPOSITORY + '/releases/download/'
MAX_DOWNLOAD = 350 * 1024 * 1024


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('Invalid release version')
    return tuple(map(int, value.lstrip('v').split('.')))


def fetch(url, limit=MAX_DOWNLOAD):
    request = urllib.request.Request(url, headers={'User-Agent': 'FeedTone-updater', 'Accept': 'application/vnd.github+json' if url == API else 'application/octet-stream'})
    with urllib.request.urlopen(request, timeout=20) as response:
        result = response.read(limit + 1)
    if len(result) > limit:
        raise ValueError('Update exceeds download limit')
    return result


def validate_archive(archive_path, destination, expected_version):
    """Extract a complete, hash-bound runtime; reject extra or escaping members."""
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) > 15000 or len(set(name.casefold() for name in names)) != len(names):
            raise ValueError('Duplicate or excessive update entries')
        if sum(info.file_size for info in infos) > 1500 * 1024 * 1024:
            raise ValueError('Update expands beyond its size limit')
        for info in infos:
            path = PurePosixPath(info.filename)
            if (path.is_absolute() or len(path.parts) < 2 or path.parts[0] != 'feedtone'
                    or any(part in ('', '.', '..') or part.endswith((' ', '.')) or ':' in part for part in path.parts)
                    or '\\' in info.filename or (info.external_attr >> 16) & 0o170000 == 0o120000
                    or path.suffix.lower() in ('.exe', '.psarc', '.feedpak', '.wem', '.bin')):
                raise ValueError('Unsafe update member')
            if any(part.split('.')[0].upper() in {'CON','PRN','AUX','NUL','CONIN$','CONOUT$','CLOCK$',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))} for part in path.parts):
                raise ValueError('Reserved update path')
        manifest = json.loads(archive.read('feedtone/package-manifest.json'))
        files = manifest.get('files', {})
        if manifest.get('version') != expected_version or not isinstance(files, dict) or not files:
            raise ValueError('Update manifest version mismatch')
        expected = {'feedtone/' + name for name in files} | {'feedtone/package-manifest.json'}
        if set(names) != expected:
            raise ValueError('Update contains unlisted or missing files')
        for name, digest in files.items():
            content = archive.read('feedtone/' + name)
            if not isinstance(digest, str) or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError('Update file checksum mismatch')
        plugin = json.loads(archive.read('feedtone/plugin.json'))
        if plugin.get('id') != 'feedtone' or plugin.get('version') != expected_version:
            raise ValueError('Unexpected update identity')
        archive.extractall(destination)
        if os.name != 'nt':
            for info in infos:
                mode=(info.external_attr>>16)&0o777
                if mode:
                    (Path(destination)/info.filename).chmod(0o755 if mode&0o111 else 0o644)
    return Path(destination) / 'feedtone'


def install_staged(staged, target):
    staged, target = Path(staged).resolve(), Path(target).resolve()
    if staged.name != 'feedtone' or target.parent == target or staged == target or target in staged.parents or staged in target.parents:
        raise ValueError('Unexpected update directories')
    current = json.loads((target/'plugin.json').read_text(encoding='utf-8'))
    if current.get('id') != 'feedtone':
        raise ValueError('Unexpected installed plugin')
    manifest = json.loads((staged/'plugin.json').read_text(encoding='utf-8'))
    if manifest.get('id') != 'feedtone':
        raise ValueError('Unexpected staged plugin')
    # Stage beside the target so the final directory swap stays on one volume.
    replacement = Path(tempfile.mkdtemp(prefix='.feedtone-update-', dir=target.parent)) / 'feedtone'
    shutil.copytree(staged, replacement)
    backup = target.parent/'.feedtone-backups'/str(time.time_ns())/target.name
    backup.parent.mkdir(parents=True, exist_ok=True)
    try:
        if target.exists():
            os.replace(target, backup)
        try:
            os.replace(replacement, target)
        except BaseException:
            if backup.exists():
                os.replace(backup, target)
            raise
    finally:
        shutil.rmtree(replacement.parent, ignore_errors=True)
    return backup


def wait_process(pid):
    if os.name != 'nt':
        if int(pid) <= 1:
            return
        while True:
            try:
                os.kill(int(pid), 0)
            except ProcessLookupError:
                return
            time.sleep(.25)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000, False, int(pid))
    if handle:
        try:
            kernel.WaitForSingleObject(handle, 0xffffffff)
        finally:
            kernel.CloseHandle(handle)


class Updater:
    def __init__(self, root, config, python, fetcher=fetch, launcher=None):
        self.root, self.config, self.python = Path(root), Path(config), str(python)
        self.fetcher, self.launcher = fetcher, launcher
        self.lock = threading.Lock()
        self.local = json.loads((self.root/'plugin.json').read_text(encoding='utf-8'))['version']
        self.settings_path = self.config/'updates.json'
        self.auto = True
        if self.settings_path.exists():
            self.auto = json.loads(self.settings_path.read_text(encoding='utf-8')).get('automatic', True) is True
        self.state = {'local_version':self.local, 'remote_version':None, 'status':'idle', 'error':None, 'update_available':False}
        last_result = self.config/'last-update.json'
        if last_result.exists():
            result = json.loads(last_result.read_text(encoding='utf-8'))
            if result.get('ok') is False:
                self.state['previous_error'] = str(result.get('error', 'Previous update failed'))[:300]
        self.release = None
        self.checked = 0

    def settings(self, automatic):
        if not isinstance(automatic, bool):
            raise ValueError('Automatic checking must be true or false')
        self.config.mkdir(parents=True, exist_ok=True)
        temporary = self.settings_path.with_suffix('.tmp')
        with self.lock:
            if self.state['status'] == 'pending':
                raise ValueError('An update is already scheduled for exit')
            temporary.write_text(json.dumps({'automatic':automatic}), encoding='utf-8')
            os.replace(temporary, self.settings_path)
            self.auto = automatic
        return self.snapshot()

    def snapshot(self):
        with self.lock:
            return {**self.state, 'automatic':self.auto}

    def start(self, operation):
        with self.lock:
            if self.state['status'] in ('checking','downloading','pending'):
                return self.snapshot_unlocked()
            self.state.update(status='checking' if operation == 'check' else 'downloading', error=None)
        threading.Thread(target=self._run, args=(operation,), daemon=True).start()
        return self.snapshot()

    def snapshot_unlocked(self):
        return {**self.state, 'automatic':self.auto}

    def _run(self, operation):
        try:
            if operation == 'check':
                release = json.loads(self.fetcher(API, 1024*1024))
                remote = release.get('tag_name')
                newer = version(remote) > version(self.local)
                if release.get('draft') or release.get('prerelease'):
                    raise ValueError('Only stable releases are installed automatically')
                with self.lock:
                    self.release, self.checked = release, time.monotonic()
                    self.state.update(remote_version=remote.lstrip('v'), update_available=newer, status='ready')
                if newer and self.auto:
                    with self.lock:
                        self.state['status'] = 'downloading'
                    self.prepare()
            else:
                self.prepare()
        except Exception as exc:
            with self.lock:
                self.checked = time.monotonic()
                self.state.update(status='error', error=str(exc)[:300])

    def prepare(self):
        if not self.release or version(self.release['tag_name']) <= version(self.local):
            raise ValueError('Check for a newer stable release first')
        tag = self.release['tag_name']
        if not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
            raise ValueError('Unsupported release tag')
        remote = tag[1:]
        name = f'FeedTone-{remote}.zip'
        assets = {asset['name']:asset['browser_download_url'] for asset in self.release.get('assets', [])}
        for filename in (name, name+'.sha256'):
            if assets.get(filename) != DOWNLOAD+tag+'/'+filename:
                raise ValueError('Unexpected release asset URL')
        digest = self.fetcher(assets[name+'.sha256'], 4096).decode('ascii').split()[0]
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid release checksum')
        content = self.fetcher(assets[name], MAX_DOWNLOAD)
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError('Release checksum mismatch')
        self.config.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='update-', dir=self.config))
        archive = stage/'release.zip'
        archive.write_bytes(content)
        staged = validate_archive(archive, stage, remote)
        helper = stage/'apply_update.py'
        shutil.copy2(Path(__file__), helper)
        command = [self.python, str(helper), '--apply', str(staged), str(self.root.resolve()), str(os.getpid()), str(os.getppid())]
        if self.launcher:
            self.launcher(command)
        else:
            flags = {'creationflags':subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS} if os.name=='nt' else {'start_new_session':True}
            subprocess.Popen(command, **flags,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        with self.lock:
            self.state.update(status='pending', pending_version=remote)


if __name__ == '__main__' and len(sys.argv) == 6 and sys.argv[1] == '--apply':
    staged, target, server, parent = sys.argv[2:]
    result_path = Path(staged).parent.parent/'last-update.json'
    try:
        wait_process(server)
        wait_process(parent)
        for attempt in range(30):
            try:
                backup = install_staged(staged, target)
                result = {'ok':True,'backup':str(backup)}
                break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError('Update files remained locked; please retry after closing FeedBack.')
    except Exception as exc:
        result = {'ok':False,'error':str(exc)[:300]}
    result_path.write_text(json.dumps(result),encoding='utf-8')
