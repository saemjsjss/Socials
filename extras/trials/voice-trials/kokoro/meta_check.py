"""Licence metadata of installed packages, Kokoro language codes, sizes, and independent WAV re-check."""
import importlib.metadata as md
import os
from pathlib import Path

import soundfile as sf

for pkg in ["kokoro", "misaki", "espeakng-loader", "phonemizer-fork", "torch", "spacy", "en-core-web-sm", "soundfile"]:
    try:
        m = md.metadata(pkg)
        lic = m.get("License-Expression") or m.get("License") or ""
        classifiers = [c for c in (m.get_all("Classifier") or []) if "License" in c]
        print(f"{pkg} {m['Version']}: license={lic[:80]!r} classifiers={classifiers}")
    except Exception as e:
        print(pkg, "ERR", e)

import kokoro.pipeline as kp
print("LANG_CODES:", getattr(kp, "LANG_CODES", None))
src = Path(kp.__file__).read_text(encoding="utf-8")
print("mentions korean/ko:", [w for w in ("korean", "Korean", "'ko'", '"ko"') if w in src])


def du(p):
    return sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file()) / 1e6


base = Path(r"C:\Hangeul\JARVIS\voice-trials\kokoro")
print(f"hf_cache MB: {du(base / 'hf_cache'):.1f}")
print(f"venv MB: {du(base / '.venv'):.1f}")

print("--- soundfile re-check")
for f in sorted(Path(r"C:\Hangeul\JARVIS\voice-samples").glob("kokoro__*.wav")):
    info = sf.info(str(f))
    data, sr = sf.read(str(f))
    import numpy as np
    rms = float(np.sqrt(np.mean(data ** 2)))
    silent = float(np.mean(np.abs(data) < 0.005))
    print(f"{f.name}: {info.samplerate} Hz, {info.channels} ch, {info.duration:.2f}s, {info.subtype}, rms={rms:.3f}, near-silent frac={silent:.2f}, size={f.stat().st_size/1e3:.0f} KB")
