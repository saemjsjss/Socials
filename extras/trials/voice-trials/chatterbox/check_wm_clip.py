# Clipping count per sample + Perth watermark detection on the rendered files.
import os
from pathlib import Path

ROOT = Path(r"C:\Hangeul\JARVIS\voice-trials\chatterbox")
os.environ["HF_HOME"] = str(ROOT / "hf")

import numpy as np
import soundfile as sf
import librosa
import perth

files = sorted(Path(r"C:\Hangeul\JARVIS\voice-samples").glob("real__chatterbox__*.wav"))
wm = perth.PerthImplicitWatermarker()
for f in files:
    x, sr = sf.read(str(f), dtype="float32")
    clipped = int(np.sum(np.abs(x) >= 0.999))
    score = wm.get_watermark(x, sample_rate=sr)
    print(f"{f.name:60s} clipped={clipped:4d} ({clipped / len(x) * 100:.3f}%)  perth={float(np.mean(score)):.3f}")

# control: the MeloTTS source (no Perth watermark expected)
ref, rsr = librosa.load(r"C:\Hangeul\JARVIS\voice-samples\melotts__kr__kr.wav", sr=None)
print("control melotts__kr__kr.wav perth=", round(float(np.mean(wm.get_watermark(ref, sample_rate=rsr))), 3))
