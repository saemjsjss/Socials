"""Aegyo (cute) Korean samples for Jennie: MeloTTS KR stock voice, a playful script, then
brighter prosody (sdp_ratio), a slightly faster speed and a raised pitch. Offline, CPU."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HOME", os.path.join(HERE, "hf_cache"))
os.environ.setdefault("NLTK_DATA", os.path.join(HERE, "nltk_data"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, os.path.join(HERE, "src"))

import g2pkk.g2pkk as _g2pkk_mod  # noqa: E402
import mecab as _mecab  # noqa: E402

_g2pkk_mod.G2p.check_mecab = lambda self: None
_g2pkk_mod.G2p.get_mecab = lambda self: _mecab.MeCab()

import librosa  # noqa: E402
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from melo.api import TTS  # noqa: E402

OUT = r"C:\Hangeul\JARVIS\voice-samples"
TEXT = ("짜잔! 제니예요! 방금 포털 동기화가 끝났어용. 새로 서류 검증된 학생이 한 명 있구요, "
        "진행 시트 일곱 개 모두 최신 상태예요! 헤헤, 또 궁금한 거 있으세용?")

# (name, speed, pitch semitones, sdp_ratio): from "style only" up to "very cute"
VARIANTS = [
    ("1_style-only", 1.00, 0.0, 0.2),
    ("2_bright", 1.08, 2.0, 0.5),
    ("3_cute", 1.12, 3.5, 0.6),
    ("4_very-cute", 1.15, 5.0, 0.6),
]

model = TTS(language="KR", device="cpu")
sid = model.hps.data.spk2id["KR"]
sr = model.hps.data.sampling_rate
for name, speed, steps, sdp in VARIANTS:
    audio = model.tts_to_file(TEXT, sid, output_path=None, speed=speed, sdp_ratio=sdp, quiet=True)
    audio = np.asarray(audio, dtype=np.float32)
    if steps:
        audio = librosa.effects.pitch_shift(audio, sr=sr, n_steps=steps)
    peak = float(np.max(np.abs(audio))) or 1.0
    audio = audio / peak * 0.8                      # even loudness across variants
    path = os.path.join(OUT, f"aegyo__{name}__kr.wav")
    sf.write(path, audio, sr, subtype="PCM_16")
    print(f"{name:14} speed={speed} pitch=+{steps} sdp={sdp}  {len(audio) / sr:5.1f}s  -> {path}", flush=True)
