"""Render MeloTTS voice samples (EN + KR) on CPU for the Jarvis voice trial.

Runs from C:\\Hangeul\\JARVIS\\voice-trials\\melotts with its own .venv.
Uses the patched MeloTTS checkout in ./src (lazy language imports, no Japanese deps).
"""
import os
import sys
import time
import json
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = r"C:\Hangeul\JARVIS\voice-samples"

# Keep all downloaded weights / NLTK data inside the trial folder.
os.environ.setdefault("HF_HOME", os.path.join(HERE, "hf_cache"))
os.environ.setdefault("NLTK_DATA", os.path.join(HERE, "nltk_data"))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.makedirs(os.environ["NLTK_DATA"], exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, os.path.join(HERE, "src"))

import nltk  # noqa: E402

for res_path, pkg in [
    ("taggers/averaged_perceptron_tagger", "averaged_perceptron_tagger"),
    ("taggers/averaged_perceptron_tagger_eng", "averaged_perceptron_tagger_eng"),
    ("corpora/cmudict", "cmudict"),
]:
    try:
        nltk.data.find(res_path)
    except LookupError:
        if os.environ.get("HF_HUB_OFFLINE") == "1":
            raise
        nltk.download(pkg, download_dir=os.environ["NLTK_DATA"], quiet=True)

# g2pkk on Windows insists on "eunjeon" (sdist only, needs MSVC) and would run a
# bare "pip install eunjeon" against whatever pip is on PATH. Point it at
# python-mecab-ko (has a cp312 win_amd64 wheel) instead.
import g2pkk.g2pkk as _g2pkk_mod  # noqa: E402
import mecab as _mecab  # noqa: E402

_g2pkk_mod.G2p.check_mecab = lambda self: None
_g2pkk_mod.G2p.get_mecab = lambda self: _mecab.MeCab()

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402

from melo.api import TTS  # noqa: E402

EN_TEXT = ("Good evening. The portal sync finished a minute ago: one new student was "
           "document-verified, and all seven progress sheets are up to date. Shall I read "
           "you today's missing-information report?")
KR_TEXT = ("안녕하세요. 방금 포털 동기화가 끝났습니다. 새로 서류 검증된 학생이 한 명 있고, "
           "진행 시트 일곱 개가 모두 최신 상태입니다.")

only = set(a.lower() for a in sys.argv[1:])  # optional filter: en / kr
results = []


def verify(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        ch = w.getnchannels()
        sw = w.getsampwidth()
    dur = n / float(sr) if sr else 0.0
    assert sr >= 16000 and dur > 0.5, (path, sr, dur)
    return sr, dur, ch, sw


def render(model, speaker_key, text, lang_tag, voice_id):
    spk_id = model.hps.data.spk2id[speaker_key]
    t0 = time.perf_counter()
    audio = model.tts_to_file(text, spk_id, output_path=None, speed=1.0, quiet=True)
    synth_s = time.perf_counter() - t0
    sr = model.hps.data.sampling_rate
    path = os.path.join(OUT_DIR, f"melotts__{voice_id}__{lang_tag}.wav")
    sf.write(path, np.asarray(audio, dtype=np.float32), sr, subtype="PCM_16")
    vsr, dur, ch, sw = verify(path)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    rec = dict(voice_id=voice_id, speaker=speaker_key, language=lang_tag, file=path,
               sample_rate=vsr, duration_s=round(dur, 2), channels=ch, sampwidth=sw,
               synth_s=round(synth_s, 2), rtf=round(synth_s / dur, 3), peak=round(peak, 3))
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    results.append(rec)


print("torch", torch.__version__, "threads", torch.get_num_threads(), "cuda_used=False", flush=True)

if not only or "en" in only:
    t0 = time.perf_counter()
    en = TTS(language="EN", device="cpu")
    print("EN model load s", round(time.perf_counter() - t0, 2), "speakers", dict(en.hps.data.spk2id), flush=True)
    # warm-up (loads bert-base-uncased, JIT paths) so timings below are steady-state
    t0 = time.perf_counter()
    en.tts_to_file("Warm up.", en.hps.data.spk2id["EN-BR"], output_path=None, quiet=True)
    print("EN warm-up s", round(time.perf_counter() - t0, 2), flush=True)
    for key, vid in [("EN-BR", "en-br"), ("EN-US", "en-us"), ("EN-Default", "en-default"),
                     ("EN-AU", "en-au"), ("EN_INDIA", "en-india")]:
        render(en, key, EN_TEXT, "en", vid)
    del en

if not only or "kr" in only:
    t0 = time.perf_counter()
    kr = TTS(language="KR", device="cpu")
    print("KR model load s", round(time.perf_counter() - t0, 2), "speakers", dict(kr.hps.data.spk2id), flush=True)
    t0 = time.perf_counter()
    kr.tts_to_file("안녕하세요.", kr.hps.data.spk2id["KR"], output_path=None, quiet=True)
    print("KR warm-up s", round(time.perf_counter() - t0, 2), flush=True)
    render(kr, "KR", KR_TEXT, "kr", "kr")

with open(os.path.join(HERE, "render_results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("DONE", len(results), "files", flush=True)
