"""STT choice benchmark for the Jennie voice service: large-v3-turbo vs large-v3 (GPU fp16),
and the CPU int8 fallback candidates (large-v3-turbo vs medium).

Same decoding settings as service.py (beam 5, VAD filter, language auto-detect).
Scores every clip by character error rate against the text it was rendered from, and times it.
Writes bench_stt.json + bench_stt.log beside this script.

usage:  .venv\\Scripts\\python.exe bench_stt.py            (all configs)
        .venv\\Scripts\\python.exe bench_stt.py cpu        (CPU configs only)
"""
import json
import os
import re
import statistics
import sys
import threading
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TQDM_DISABLE", "1")

import torch  # noqa: E402  (first: puts torch\lib - cuBLAS / cuDNN - on the DLL path for CTranslate2)
from faster_whisper import WhisperModel  # noqa: E402
from faster_whisper.audio import decode_audio  # noqa: E402

SAMPLES = r"C:\Hangeul\JARVIS\voice-samples"
MODEL_DIRS = {
    "large-v3-turbo": os.path.join(HERE, r"models\hf\hub\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"),
    "large-v3": r"C:\Hangeul\JARVIS\voice-trials\whisper\hf_home\hub\models--Systran--faster-whisper-large-v3",
    "medium": r"C:\Hangeul\JARVIS\voice-trials\whisper\hf_home\hub\models--Systran--faster-whisper-medium",
}
CPU_THREADS = 6
GPU_MIN_FREE_GB = 4.0

EN_A = ("Good evening! The portal sync just finished. One new student was document-verified, "
        "and all seven progress sheets are up to date. Anything else I can check for you?")
EN_B = ("Good evening. The portal sync finished a minute ago: one new student was "
        "document-verified, and all seven progress sheets are up to date. Shall I read "
        "you today's missing-information report?")
KR_NEUTRAL = ("안녕하세요. 방금 포털 동기화가 끝났습니다. 새로 서류 검증된 학생이 한 명 있고, "
              "진행 시트 일곱 개가 모두 최신 상태입니다.")
KR_AEGYO = ("짜잔! 제니예요! 방금 포털 동기화가 끝났어용. 새로 서류 검증된 학생이 한 명 있구요, "
            "진행 시트 일곱 개 모두 최신 상태예요! 헤헤, 또 궁금한 거 있으세용?")

# (file, reference text, language) - several different voices per language
CLIPS = [
    ("real__cosyvoice__v2-zeroshot-krfemale__kr-aegyo.wav", KR_AEGYO, "ko"),
    ("real__cosyvoice__v2-crosslingual-krfemale__kr-aegyo.wav", KR_AEGYO, "ko"),
    ("real__cosyvoice__v3-zeroshot-krfemale__kr-aegyo.wav", KR_AEGYO, "ko"),
    ("real__chatterbox__meloref-ex0.5-cfg0.5__kr-aegyo.wav", KR_AEGYO, "ko"),
    ("aegyo__1_style-only__kr.wav", KR_AEGYO, "ko"),
    ("aegyo__3_cute__kr.wav", KR_AEGYO, "ko"),
    ("aegyo__4_very-cute__kr.wav", KR_AEGYO, "ko"),
    ("real__cosyvoice__v2-zeroshot-krfemale__kr-neutral.wav", KR_NEUTRAL, "ko"),
    ("real__cosyvoice__v3-zeroshot-krfemale__kr-neutral.wav", KR_NEUTRAL, "ko"),
    ("real__chatterbox__default-cfg0__kr-neutral.wav", KR_NEUTRAL, "ko"),
    ("real__chatterbox__meloref__kr-neutral.wav", KR_NEUTRAL, "ko"),
    ("melotts__kr__kr.wav", KR_NEUTRAL, "ko"),
    ("piper__ko_kr-kss-medium__kr.wav", KR_NEUTRAL, "ko"),
    ("real__cosyvoice__v2-crosslingual-krfemale__en.wav", EN_A, "en"),
    ("real__cosyvoice__v2-zeroshot-enfemale__en.wav", EN_A, "en"),
    ("kokoro__af_heart__en.wav", EN_B, "en"),
    ("kokoro__bm_george__en.wav", EN_B, "en"),
    ("melotts__en-india__en.wav", EN_B, "en"),
    ("melotts__en-us__en.wav", EN_B, "en"),
    ("piper__en_gb-cori-high__en.wav", EN_B, "en"),
    ("piper__en_gb-northern_english_male-medium__en.wav", EN_B, "en"),
]

_EN_NUM = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
           "6": "six", "7": "seven", "8": "eight", "9": "nine"}
_KR_NUM = [(re.compile(r"7\s*개"), "일곱개"), (re.compile(r"1\s*명"), "한명")]


def normalize(text, lang):
    """Numerals written as digits are a formatting choice, not a hearing error."""
    t = unicodedata.normalize("NFC", text).lower()
    if lang == "en":
        t = re.sub(r"\b(\d)\b", lambda m: _EN_NUM[m.group(1)], t)
    else:
        for rx, rep in _KR_NUM:
            t = rx.sub(rep, t)
    t = "".join(" " if unicodedata.category(ch)[0] in ("P", "S") else ch for ch in t)
    return " ".join(t.split()) if lang == "en" else re.sub(r"\s+", "", t)


def cer(ref, hyp, lang):
    r, h = normalize(ref, lang), normalize(hyp, lang)
    prev = list(range(len(h) + 1))
    for i, cr in enumerate(r, 1):
        cur = [i]
        for j, ch in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (cr != ch)))
        prev = cur
    return prev[-1] / max(1, len(r))


def snapshot(repo_dir):
    snaps = os.path.join(repo_dir, "snapshots")
    for name in sorted(os.listdir(snaps)):
        if os.path.exists(os.path.join(snaps, name, "model.bin")):
            return os.path.join(snaps, name)
    raise FileNotFoundError(repo_dir)


class VramSampler:
    """Lowest device-wide free VRAM seen while running (torch.cuda.mem_get_info every 50 ms)."""

    def __init__(self):
        self.min_free = None
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            free, _ = torch.cuda.mem_get_info()
            self.min_free = free if self.min_free is None else min(self.min_free, free)
            time.sleep(0.05)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join()


LOG = open(os.path.join(HERE, "bench_stt.log"), "a", encoding="utf-8")


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()


def gb(b):
    return round(b / 1024 ** 3, 2)


def run_config(name, device, compute):
    path = snapshot(MODEL_DIRS[name])
    row = {"model": name, "device": device, "compute": compute}
    free0 = torch.cuda.mem_get_info()[0] if device == "cuda" else None
    t0 = time.perf_counter()
    model = WhisperModel(path, device=device, compute_type=compute,
                         cpu_threads=CPU_THREADS if device == "cpu" else 0, local_files_only=True)
    row["load_s"] = round(time.perf_counter() - t0, 2)
    # warm-up on one clip (not scored)
    warm = decode_audio(os.path.join(SAMPLES, CLIPS[0][0]))
    list(model.transcribe(warm, beam_size=5, vad_filter=True, condition_on_previous_text=False)[0])
    if device == "cuda":
        row["vram_after_load_gb"] = gb(free0 - torch.cuda.mem_get_info()[0])
    results = []
    sampler = VramSampler() if device == "cuda" else None
    if sampler:
        sampler.__enter__()
    try:
        for fname, ref, lang in CLIPS:
            audio = decode_audio(os.path.join(SAMPLES, fname))
            dur = len(audio) / 16000
            t = time.perf_counter()
            segs, info = model.transcribe(audio, beam_size=5, vad_filter=True, condition_on_previous_text=False)
            text = "".join(s.text for s in segs).strip()
            dt = time.perf_counter() - t
            c = cer(ref, text, lang)
            results.append({"file": fname, "lang": lang, "detected": info.language,
                            "lang_prob": round(info.language_probability, 3), "dur_s": round(dur, 2),
                            "stt_s": round(dt, 2), "rtf": round(dt / dur, 3), "cer": round(c, 4), "text": text})
            log(f"  {name:15s} {device:4s} {c:6.3f} {info.language}({info.language_probability:.2f}) "
                f"{dt:5.2f}s/{dur:5.1f}s  {fname}")
    finally:
        if sampler:
            sampler.__exit__()
    if device == "cuda":
        row["vram_peak_gb"] = gb(free0 - sampler.min_free)
        # unload / reload cost (the service unloads the GPU model between requests)
        t = time.perf_counter()
        model.model.unload_model(to_cpu=False)
        row["unload_s"] = round(time.perf_counter() - t, 2)
        row["vram_after_unload_gb"] = gb(free0 - torch.cuda.mem_get_info()[0])
        t = time.perf_counter()
        model.model.load_model()
        row["reload_s"] = round(time.perf_counter() - t, 2)
        model.model.unload_model(to_cpu=True)
        t = time.perf_counter()
        model.model.load_model()
        row["reload_from_ram_s"] = round(time.perf_counter() - t, 2)
    for lang in ("ko", "en"):
        rs = [r for r in results if r["lang"] == lang]
        row[f"cer_{lang}_mean"] = round(statistics.mean(r["cer"] for r in rs), 4)
        row[f"cer_{lang}_median"] = round(statistics.median(r["cer"] for r in rs), 4)
        row[f"wrong_lang_{lang}"] = sum(1 for r in rs if r["detected"] != lang)
    row["rtf_median"] = round(statistics.median(r["rtf"] for r in results), 3)
    twelve = [r for r in results if 10.5 <= r["dur_s"] <= 13.5]
    row["median_s_on_11-13s_clips"] = round(statistics.median(r["stt_s"] for r in twelve), 2) if twelve else None
    row["results"] = results
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    summary = {k: v for k, v in row.items() if k != "results"}
    log("SUMMARY", json.dumps(summary))
    return row


def main():
    only_cpu = len(sys.argv) > 1 and sys.argv[1] == "cpu"
    configs = [("large-v3-turbo", "cpu", "int8"), ("medium", "cpu", "int8")]
    if not only_cpu and torch.cuda.is_available():
        free = torch.cuda.mem_get_info()[0] / 1024 ** 3
        log(f"free VRAM {free:.2f} GB")
        if free >= GPU_MIN_FREE_GB:
            configs = [("large-v3-turbo", "cuda", "float16"), ("large-v3", "cuda", "float16")] + configs
        else:
            log("GPU configs skipped: not enough free VRAM")
    log(time.strftime("%Y-%m-%d %H:%M:%S"), "configs:", configs)
    rows = [run_config(*c) for c in configs]
    with open(os.path.join(HERE, "bench_stt.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    log("wrote bench_stt.json")


if __name__ == "__main__":
    main()
