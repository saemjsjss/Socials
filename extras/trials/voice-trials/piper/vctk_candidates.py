"""Render a few VCTK male-speaker candidates into the trials folder and estimate pitch.

Used only to pick one VCTK speaker for the final sample set. CPU only.
"""
import time
import wave
from pathlib import Path

import numpy as np
from piper import PiperVoice, SynthesisConfig

HERE = Path(__file__).parent
VOICES = HERE / "voices"
OUT = HERE / "candidates"
OUT.mkdir(exist_ok=True)

TEXT = ("Good evening. The portal sync finished a minute ago: one new student was "
        "document-verified, and all seven progress sheets are up to date. Shall I read "
        "you today's missing-information report?")

CANDIDATES = ["p226", "p227", "p232", "p243", "p254", "p258", "p273", "p274"]


def median_f0(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        x = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32)
    x /= 32768.0
    frame, hop = int(0.04 * sr), int(0.01 * sr)
    lo, hi = int(sr / 400), int(sr / 60)
    f0s = []
    for i in range(0, len(x) - frame, hop):
        seg = x[i:i + frame]
        if np.sqrt(np.mean(seg ** 2)) < 0.03:
            continue
        seg = seg - seg.mean()
        ac = np.correlate(seg, seg, mode="full")[frame - 1:]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > 0.5:
            f0s.append(sr / lag)
    return float(np.median(f0s)) if f0s else float("nan")


voice = PiperVoice.load(VOICES / "en_GB-vctk-medium.onnx")
print("config inference defaults:", voice.config.length_scale, voice.config.noise_scale,
      voice.config.noise_w_scale)
sid_map = voice.config.speaker_id_map
for spk in CANDIDATES:
    path = OUT / f"vctk_{spk}.wav"
    t0 = time.perf_counter()
    with wave.open(str(path), "wb") as wf:
        voice.synthesize_wav(TEXT, wf, syn_config=SynthesisConfig(speaker_id=sid_map[spk]))
    dt = time.perf_counter() - t0
    with wave.open(str(path), "rb") as wf:
        dur = wf.getnframes() / wf.getframerate()
    print(f"{spk}: id={sid_map[spk]:3d} dur={dur:5.2f}s synth={dt:4.2f}s median_f0={median_f0(path):6.1f}Hz")
