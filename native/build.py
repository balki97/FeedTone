"""Build the native part of the FeedBack plugin on its target platform."""
import argparse
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine.runtime import native_root,platform_key,configure_dependencies
SOURCES={'DSPKernels':'dsp_kernels.c','FilterKernels':'filter_kernels.c','TremoloKernels':'tremolo_kernels.c','AmpKernels':'amp_kernels.c','CabinetFFT':'cabinet_fft.c','DelayKernels':'delay_kernels.c','PhaserKernels':'phaser_kernels.c','PitchKernels':'pitch_kernels.c','PitchFFT':'pitch_fft.c','ReverbKernels':'reverb_kernels.c','ChorusKernels':'chorus_kernels.c','RoomKernels':'room_kernels.c'}

def build():
    if sys.platform=='win32':
        raise RuntimeError('Use the component PowerShell builds on Windows')
    cc=shutil.which('clang') or shutil.which('cc')
    if not cc:raise RuntimeError('A C compiler is required to build the native plugin')
    output=native_root();output.mkdir(parents=True,exist_ok=True)
    flags=(["-mmacosx-version-min=11.0"] if sys.platform=='darwin' else [])+['-O2','-fPIC','-ffp-contract=off','-fno-fast-math','-fvisibility=hidden']
    link=['-dynamiclib'] if sys.platform=='darwin' else ['-shared']
    suffix='.dylib' if sys.platform=='darwin' else '.so'
    for name,source in SOURCES.items():
        subprocess.run([cc,*flags,*link,str(ROOT/'native'/source),'-o',str(output/(name+suffix)),'-lm'],check=True)
    bundle=output/'FeedTone.vst3'
    directory=bundle/'Contents'/('MacOS' if sys.platform=='darwin' else ('aarch64-linux' if platform.machine() in ('arm64','aarch64') else 'x86_64-linux'))
    directory.mkdir(parents=True,exist_ok=True)
    binary=directory/('FeedTone' if sys.platform=='darwin' else 'FeedTone.so')
    subprocess.run([cc,*flags,'-O1',*link,str(ROOT/'native/source/bridge.c'),'-o',str(binary),'-lpthread',*(['-ldl'] if sys.platform=='linux' else [])],check=True)
    if sys.platform=='darwin':
        (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'FeedTone','CFBundleIdentifier':'org.feedforge.feedtone','CFBundleName':'FeedTone','CFBundlePackageType':'BNDL','CFBundleVersion':'1.0.0','CFBundleShortVersionString':'1.0.0'}))
        subprocess.run(['codesign','--force','--sign','-','--timestamp=none',str(bundle)],check=True)
    print(platform_key(),output)

def verify():
    configure_dependencies()
    import numpy as np
    from engine import _data,prepare_preset
    from engine.graph import ToneGraph
    from pedalboard import load_plugin
    slots={'Pedals':'PrePedal1','Amps':'Amp','Cabinets':'Cabinet','Racks':'Rack1'}
    checked=0
    for key,device in _data('devices')['devices'].items():
        definition={'Volume':-12,'GearList':{slots[device['type']]:{'Key':key,'Type':device['type'],'KnobValues':{}}}}
        graph=ToneGraph(definition)
        result=graph.process(np.full((128,1),.001,np.float32));graph.close()
        assert result.shape==(128,2) and np.isfinite(result).all(),key
        checked+=1
    definition={'Volume':-12,'GearList':{'PrePedal1':{'Key':'Pedal_EQ8','Type':'Pedals','KnobValues':{}}}}
    signal=(np.sin(np.arange(4096,dtype=np.float32)*.03)*.01).astype(np.float32)
    with tempfile.TemporaryDirectory(prefix='Feed Tone café ') as temporary:
        preset=prepare_preset(definition,title='FeedTone verification',cache_root=Path(temporary),python_executable=sys.executable)
        plugin=load_plugin(preset['native_preset']['chain'][0]['path'])
        output=plugin(signal,48000,buffer_size=113)
        assert np.isfinite(output).all() and np.max(np.abs(output))>0
        # The host compensates the transport latency.
        graph=ToneGraph(definition)
        expected=np.concatenate([graph.process(signal[i:i+128,None]) for i in range(0,4096,128)])
        graph.close()
        rendered=output.T if output.ndim==2 else output[:,None]
        if rendered.shape[1]==1:rendered=np.repeat(rendered,2,axis=1)
        error=float(np.max(np.abs(rendered-expected)))
        assert error<1e-6,error
    print(json.dumps({'platform':platform_key(),'devices_rendered':checked,'vst_audio_error':error,'unicode_path':True}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--verify',action='store_true');args=parser.parse_args()
    build()
    if args.verify:verify()
