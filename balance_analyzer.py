"""Offline deterministic DI probe, executed only by the embedded audio Python."""
import json
import math
from pathlib import Path
import sys

import numpy as np
from engine.graph import ToneGraph


def reference_di():
    rate=48000
    frames=rate*3
    signal=np.zeros(frames,np.float64)
    # Six independently decaying plucks, plus a chord: repeatable harmonic DI.
    frequencies=(82.4069,110.0,146.8324,195.9977,246.9417,329.6276)
    for index,frequency in enumerate(frequencies):
        start=int(index*.24*rate)
        t=np.arange(frames-start,dtype=np.float64)/rate
        pluck=sum(np.sin(2*np.pi*frequency*k*t+(k%3)*.19)/(k*k) for k in range(1,9))
        signal[start:]+=.11*pluck*np.exp(-t*4.5)
    start=int(1.6*rate)
    t=np.arange(frames-start,dtype=np.float64)/rate
    for frequency in frequencies:
        signal[start:]+=.025*np.sin(2*np.pi*frequency*t)*np.exp(-t*5)
    # Last half-second is a release tail, excluded from active RMS but in peak.
    signal[int(2.5*rate):]=0
    return signal.astype(np.float32).reshape(-1,1)


def analyze(definition):
    source=reference_di()
    rendered=np.empty((len(source),2),np.float32)
    graph=ToneGraph(definition)
    try:
        for offset in range(0,len(source),128):
            rendered[offset:offset+128]=graph.process(source[offset:offset+128])
    finally:
        graph.close()
    if not np.isfinite(rendered).all():
        raise ValueError('Static listening analysis produced nonfinite samples')
    peak=float(np.max(np.abs(rendered)))
    active=rendered[:120000].astype(np.float64)
    rms=float(np.sqrt(np.mean(active*active)))
    db=lambda value:20*math.log10(max(value,1e-12))
    return {'version':1,'sample_rate':48000,'frames':len(source),'rms_dbfs':db(rms),
            'peak_dbfs':db(peak),'target_dbfs':-24.0,'silent':peak<1e-7,
            'di_rms_dbfs':db(float(np.sqrt(np.mean(source[:120000].astype(np.float64)**2)))),
            'di_peak_dbfs':db(float(np.max(np.abs(source)))),
            'method':'static-six-string-harmonic-plucks-v1','probe_seconds':3,
            'limitation':'Synthetic DI estimate; not a real-time limiter or input calibration'}


def main():
    definition=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    print(json.dumps(analyze(definition),allow_nan=False))


if __name__=='__main__':
    main()
