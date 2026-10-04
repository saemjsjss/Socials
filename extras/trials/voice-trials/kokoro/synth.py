"""Render the English test sentence with Kokoro-82M British voices on CPU and verify each WAV."""
import json
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

torch.set_num_threads(6)  # Ryzen 5 8600G: 6 cores / 12 threads

from kokoro import KPipeline  # noqa: E402

REPO = "hexgrad/Kokoro-82M"
OUT_DIR = Path(r"C:\Hangeul\JARVIS\voice-samples")
OUT_DIR.mkdir(parents=True, exist_ok=True)
SR = 24000

TEXT_EN = (
    "Good evening. The portal sync finished a minute ago: one new student was "
    "document-verified, and all seven progress sheets are up to date. "
    "Shall I read you today's missing-information report?"
)

VOICES = sys.argv[1:] or ["bm_george", "bm_lewis", "bm_fable", "bm_daniel", "bf_emma"]

t0 = time.perf_counter()
pipeline = KPipeline(lang_code="b", repo_id=REPO, device="cpu")
load_s = time.perf_counter() - t0
print(f"pipeline load: {load_s:.2f}s  torch={torch.__version__} threads={torch.get_num_threads()}")

# Warm-up so the first voice's timing is not inflated by lazy init.
for _ in pipeline("Warm up.", voice="bm_george"):
    pass

results = []
for voice in VOICES:
    t1 = time.perf_counter()
    chunks, phonemes = [], []
    for gs, ps, audio in pipeline(TEXT_EN, voice=voice, speed=1.0):
        phonemes.append(ps)
        chunks.append(audio.numpy() if hasattr(audio, "numpy") else np.asarray(audio))
    synth_s = time.perf_counter() - t1
    wav = np.concatenate(chunks)
    out = OUT_DIR / f"kokoro__{voice}__en.wav"
    sf.write(out, wav, SR, subtype="PCM_16")

    # Verify with stdlib wave
    with wave.open(str(out), "rb") as w:
        frames, rate, ch = w.getnframes(), w.getframerate(), w.getnchannels()
    dur = frames / rate
    peak = float(np.max(np.abs(wav)))
    ok = frames > 0 and rate == SR and ch == 1 and peak > 0.01
    r = {
        "voice": voice, "file": str(out), "sample_rate": rate, "channels": ch,
        "duration_s": round(dur, 2), "synth_s": round(synth_s, 2),
        "rtf": round(synth_s / dur, 3) if dur else None, "peak": round(peak, 3),
        "chunks": len(chunks), "ok": ok,
    }
    results.append(r)
    print(json.dumps(r))
    print("   phonemes:", " | ".join(phonemes))

(Path(__file__).parent / "results.json").write_text(json.dumps(
    {"load_s": round(load_s, 2), "results": results}, indent=1), encoding="utf-8")
