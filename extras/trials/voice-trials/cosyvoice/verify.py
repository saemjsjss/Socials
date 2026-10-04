"""Verify every real__cosyvoice__*.wav: opens, duration, sample rate, not silent, plus a Whisper ASR
round-trip (character error rate vs. the intended text) to catch garbled / hallucinated renders.
Runs Whisper on CPU so it never competes with the production bot for VRAM."""
import glob
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from synth_texts import EN, KR_NEUTRAL, KR_AEGYO, REF_KO_TEXT, REF_EN_TEXT  # noqa: E402

TEXTS = {"en": EN, "kr-neutral": KR_NEUTRAL, "kr-aegyo": KR_AEGYO, "ref": REF_KO_TEXT,
         "ref_sft_ko_female": REF_KO_TEXT, "ref_sft_en_female": REF_EN_TEXT}
EN_KINDS = {"en", "ref_sft_en_female"}
PAT = sys.argv[1] if len(sys.argv) > 1 else r"C:\Hangeul\JARVIS\voice-samples\real__cosyvoice__*.wav"
WHISPER = sys.argv[2] if len(sys.argv) > 2 else "small"


from textmetrics import cer  # noqa: E402


import whisper  # noqa: E402

asr = whisper.load_model(WHISPER, device="cpu", download_root=os.path.join(HERE, "whisper_models"))
results = []
for path in sorted(glob.glob(PAT)):
    name = os.path.basename(path)
    kind = name[:-4].split("__")[-1]
    rec = {"file": path}
    try:
        data, sr = sf.read(path, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        dur = len(data) / sr
        rms = float(np.sqrt(np.mean(data ** 2))) if len(data) else 0.0
        peak = float(np.max(np.abs(data))) if len(data) else 0.0
        # pause analysis on 20 ms frames: a frame is 'silent' if its RMS < 3% of the file's 95th-pct frame RMS
        hop = int(sr * 0.02)
        fr = np.sqrt(np.mean(data[: len(data) // hop * hop].reshape(-1, hop) ** 2, axis=1))
        thr = 0.03 * np.percentile(fr, 95)
        voiced = np.where(fr >= thr)[0]
        lead = voiced[0] * 0.02 if len(voiced) else dur
        trail = (len(fr) - 1 - voiced[-1]) * 0.02 if len(voiced) else dur
        longest, run = 0, 0
        for v in (fr[voiced[0]:voiced[-1] + 1] < thr) if len(voiced) else []:
            run = run + 1 if v else 0
            longest = max(longest, run)
        rec.update(sr=sr, dur_s=round(dur, 2), rms=round(rms, 4), peak=round(peak, 3),
                   lead_sil_s=round(float(lead), 2), trail_sil_s=round(float(trail), 2),
                   longest_pause_s=round(longest * 0.02, 2),
                   ok=bool(dur > 0.5 and sr >= 16000 and rms > 0.005))
        lang = "en" if kind in EN_KINDS else "ko"
        audio = whisper.load_audio(path)
        hyp = asr.transcribe(audio, language=lang, fp16=False, temperature=0.0)["text"].strip()
        rec.update(asr=hyp, cer=round(cer(TEXTS.get(kind, ""), hyp), 3) if kind in TEXTS else None)
    except Exception as e:
        rec.update(ok=False, error=repr(e))
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    results.append(rec)

with open(os.path.join(HERE, "verify_results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
