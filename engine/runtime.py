"""Platform resources for the FeedBack plugin; no external application is launched."""
from pathlib import Path
import platform
import sys

ROOT=Path(__file__).resolve().parents[1]

def platform_key():
    machine=platform.machine().lower()
    arch={'amd64':'x86_64','aarch64':'arm64'}.get(machine,machine)
    if sys.platform not in ('win32','linux','darwin') or arch not in ('x86_64','arm64'):
        raise RuntimeError('This FeedBack platform is not supported by the tone engine')
    return sys.platform+'-'+arch

def native_root():
    return ROOT/'native'/platform_key() if sys.platform!='win32' else ROOT/'native'

def kernel_path(name):
    return native_root()/(name+('.dll' if sys.platform=='win32' else '.dylib' if sys.platform=='darwin' else '.so'))

def vst_path():
    return native_root()/'FeedTone.vst3'

def vendor_path():
    if sys.version_info[:2] != (3,12):
        return None
    return ROOT/'vendor' if sys.platform=='win32' else ROOT/'vendor'/platform_key()

def configure_dependencies():
    vendor=vendor_path()
    if vendor is not None and vendor.is_dir():
        sys.path.insert(0,str(vendor))
