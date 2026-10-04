# Verify rendered Chatterbox samples: open, duration, sample rate, loudness, not silent.
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

OUT_DIR = Path(r"C:\Hangeul\JARVIS\voice-samples")
files = sorted(OUT_DIR.glob("real__chatterbox__*.wav"))
results = []
for f in files:
    r = {"file": str(f)}
    try:
        data, sr = sf.read(str(f), dtype="float32", always_2d=True)
        mono = data.mean(axis=1)
        dur = len(mono) / sr
        peak = float(np.max(np.abs(mono))) if len(mono) else 0.0
        rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
        rms_db = 20 * np.log10(rms + 1e-12)
        # fraction of 50 ms frames that are effectively silent
        hop = int(0.05 * sr)
        frames = [mono[i:i + hop] for i in range(0, len(mono) - hop, hop)]
        fr_db = np.array([20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12) for x in frames])
        silent_frac = float(np.mean(fr_db < -50)) if len(fr_db) else 1.0
        ok = (dur > 0.5) and (8000 <= sr <= 48000) and (peak > 0.01) and (rms_db > -45) and (dur < 40)
        r.update(sr=sr, channels=data.shape[1], duration_s=round(dur, 2), peak=round(peak, 3),
                 rms_dbfs=round(float(rms_db), 1), silent_frac=round(silent_frac, 2), ok=bool(ok))
    except Exception as e:  # noqa: BLE001
        r.update(ok=False, error=repr(e))
    results.append(r)
    print(json.dumps(r, ensure_ascii=False))

Path(r"C:\Hangeul\JARVIS\voice-trials\chatterbox\verify_results.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
bad = [r for r in results if not r.get("ok")]
print(f"{len(results)} files, {len(bad)} failed")
sys.exit(1 if bad else 0)
