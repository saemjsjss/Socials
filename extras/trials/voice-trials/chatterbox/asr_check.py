# Intelligibility QA: transcribe each Chatterbox sample with Whisper large-v3-turbo (MIT) on CPU
# and compute character error rate vs the intended text (catches skipped / garbled words).
import os
import re
import json
import unicodedata
from pathlib import Path

ROOT = Path(r"C:\Hangeul\JARVIS\voice-trials\chatterbox")
os.environ["HF_HOME"] = str(ROOT / "hf")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import librosa
import torch
from transformers import pipeline

TEXTS = {
    "en": "Good evening! The portal sync just finished. One new student was document-verified, and all seven progress sheets are up to date. Anything else I can check for you?",
    "kr-neutral": "안녕하세요. 방금 포털 동기화가 끝났습니다. 새로 서류 검증된 학생이 한 명 있고, 진행 시트 일곱 개가 모두 최신 상태입니다.",
    "kr-aegyo": "짜잔! 제니예요! 방금 포털 동기화가 끝났어용. 새로 서류 검증된 학생이 한 명 있구요, 진행 시트 일곱 개 모두 최신 상태예요! 헤헤, 또 궁금한 거 있으세용?",
}


def norm(s):
    s = unicodedata.normalize("NFC", s).lower()
    s = s.replace("-", " ")
    s = re.sub(r"[^\w]", "", s)  # drop punctuation and spaces
    return s


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


asr = pipeline("automatic-speech-recognition", model="openai/whisper-large-v3-turbo",
               device="cpu", dtype=torch.float32)
out = []
for f in sorted(Path(r"C:\Hangeul\JARVIS\voice-samples").glob("real__chatterbox__*.wav")):
    kind = f.stem.split("__")[-1]
    lang = "english" if kind == "en" else "korean"
    audio, _ = librosa.load(str(f), sr=16000)
    res = asr({"raw": audio, "sampling_rate": 16000},
              generate_kwargs={"language": lang, "task": "transcribe"})
    hyp = res["text"].strip()
    ref = TEXTS[kind]
    cer = lev(norm(ref), norm(hyp)) / max(1, len(norm(ref)))
    r = {"file": f.name, "cer": round(cer, 3), "asr": hyp}
    out.append(r)
    print(json.dumps(r, ensure_ascii=False), flush=True)

(ROOT / "asr_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
