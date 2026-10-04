"""Independent WAV check (soundfile) + median F0 estimate to hint at voice register."""
import glob
import json
import os

import librosa
import numpy as np
import soundfile as sf

rows = []
for path in sorted(glob.glob(r"C:\Hangeul\JARVIS\voice-samples\melotts__*.wav")):
    info = sf.info(path)
    y, sr = sf.read(path, dtype="float32")
    rms = float(np.sqrt(np.mean(y ** 2)))
    y16 = librosa.resample(y, orig_sr=sr, target_sr=16000)
    f0, voiced, _ = librosa.pyin(y16, fmin=60, fmax=400, sr=16000, frame_length=1024)
    f0v = f0[voiced & ~np.isnan(f0)]
    rows.append(dict(file=os.path.basename(path), sr=info.samplerate, ch=info.channels,
                     subtype=info.subtype, duration_s=round(info.duration, 2), rms=round(rms, 4),
                     median_f0_hz=round(float(np.median(f0v)), 1) if len(f0v) else None))
for r in rows:
    print(json.dumps(r))
