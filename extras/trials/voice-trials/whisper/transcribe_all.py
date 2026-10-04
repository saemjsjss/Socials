"""Transcribe the Jennie voice samples with faster-whisper (language auto-detect) and score CER.

Usage: python transcribe_all.py [--device auto|cuda|cpu] [--model large-v3|medium]
"""
import argparse
import json
import os
import time

import common
from common import (EXPECTED, GpuLock, audio_seconds, cer, gpu_free_mib, log, model_path, normalize)

SAMPLES = r"C:\Hangeul\JARVIS\voice-samples"
FILES = [
    ("real__chatterbox__default__en.wav", "en"),
    ("real__chatterbox__meloref__en.wav", "en"),
    ("real__chatterbox__default__kr-neutral.wav", "kr-neutral"),
    ("real__chatterbox__default-cfg0__kr-neutral.wav", "kr-neutral"),
    ("real__chatterbox__meloref__kr-neutral.wav", "kr-neutral"),
    ("real__chatterbox__default-ex0.5-cfg0.5__kr-aegyo.wav", "kr-aegyo"),
    ("real__chatterbox__default-ex0.8-cfg0.3__kr-aegyo.wav", "kr-aegyo"),
    ("real__chatterbox__default-ex1.1-cfg0.2__kr-aegyo.wav", "kr-aegyo"),
    ("real__chatterbox__meloref-ex0.5-cfg0.5__kr-aegyo.wav", "kr-aegyo"),
    ("real__chatterbox__meloref-ex0.8-cfg0.3__kr-aegyo.wav", "kr-aegyo"),
    ("real__chatterbox__meloref-ex1.1-cfg0.2__kr-aegyo.wav", "kr-aegyo"),
    ("real__cosyvoice__300m-sft-korean-female__kr-neutral.wav", "kr-neutral"),
    ("real__cosyvoice__300m-sft-korean-female__kr-aegyo.wav", "kr-aegyo"),
    ("real__cosyvoice__300m-sft-english-female__en.wav", "en"),
    ("real__cosyvoice__v2-zeroshot-krfemale__kr-neutral.wav", "kr-neutral"),
    ("real__cosyvoice__v2-zeroshot-krfemale__kr-aegyo.wav", "kr-aegyo"),
    ("real__cosyvoice__v2-crosslingual-krfemale__kr-neutral.wav", "kr-neutral"),
    ("real__cosyvoice__v2-crosslingual-krfemale__kr-aegyo.wav", "kr-aegyo"),
    ("real__cosyvoice__v2-instruct-sajiao-krfemale__kr-aegyo.wav", "kr-aegyo"),
    ("real__cosyvoice__v2-instruct-happy-krfemale__kr-aegyo.wav", "kr-aegyo"),
    ("real__cosyvoice__v2-instruct-happy-laugh-krfemale__kr-aegyo.wav", "kr-aegyo"),
    ("real__cosyvoice__v2-crosslingual-krfemale__en.wav", "en"),
    ("real__cosyvoice__v2-zeroshot-enfemale__en.wav", "en"),
    ("real__cosyvoice__v3-zeroshot-krfemale__kr-neutral.wav", "kr-neutral"),
    ("real__cosyvoice__v3-zeroshot-krfemale__kr-aegyo.wav", "kr-aegyo"),
    ("real__cosyvoice__v3-instruct-happy-krfemale__kr-aegyo.wav", "kr-aegyo"),
    ("real__cosyvoice__v3-instruct-sajiao-krfemale__kr-aegyo.wav", "kr-aegyo"),
    ("real__cosyvoice__v3-crosslingual-krfemale__en.wav", "en"),
]


def load(model_name, device):
    from faster_whisper import WhisperModel
    ct = "float16" if device == "cuda" else "int8"
    return WhisperModel(model_path(model_name), device=device, compute_type=ct,
                        cpu_threads=0 if device == "cuda" else os.cpu_count() or 4)


def run(model, model_name, device):
    rows = []
    for name, kind in FILES:
        path = os.path.join(SAMPLES, name)
        if not os.path.exists(path):
            rows.append({"file": path, "expected_kind": kind, "transcript": "", "cer": 1.0,
                         "note": "FILE MISSING"})
            log("MISSING", name)
            continue
        dur = audio_seconds(path)
        t0 = time.perf_counter()
        segs, info = model.transcribe(path, language=None, beam_size=5, vad_filter=False,
                                      condition_on_previous_text=False)
        text = "".join(s.text for s in segs).strip()
        dt = time.perf_counter() - t0
        c = cer(text, kind, numerals=True)
        c_raw = cer(text, kind, numerals=False)
        exp_lang = "en" if kind == "en" else "ko"
        notes = [f"lang_prob={info.language_probability:.2f}", f"dur={dur:.1f}s", f"stt={dt:.2f}s"]
        if info.language != exp_lang:
            notes.append(f"WRONG LANGUAGE (expected {exp_lang})")
        if abs(c - c_raw) > 1e-9:
            notes.append(f"raw_cer_without_numeral_norm={c_raw:.3f}")
        rows.append({
            "file": path, "expected_kind": kind, "detected_language": info.language,
            "transcript": text, "cer": round(c, 4), "cer_raw": round(c_raw, 4),
            "lang_prob": round(info.language_probability, 3), "duration_s": round(dur, 2),
            "stt_s": round(dt, 2), "hyp_norm": normalize(text, kind), "note": "; ".join(notes),
        })
        log(f"{c:6.3f}  {info.language}({info.language_probability:.2f})  {dur:5.1f}s  {name}\n        {text}")
    out = os.path.join(common.ROOT, f"results_{model_name}_{device}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"model": model_name, "device": device, "results": rows}, f, ensure_ascii=False, indent=1)
    log("wrote", out)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="auto")
    ap.add_argument("--model", default="large-v3")
    a = ap.parse_args()
    device = a.device
    lock = GpuLock()
    if device in ("auto", "cuda"):
        free = gpu_free_mib()
        if free >= 3072 and not os.path.exists(common.GPU_LOCK) and lock.acquire():
            device = "cuda"
            log(f"GPU: {free} MiB free, lock acquired")
        else:
            log(f"GPU not used (free={free} MiB, lock_exists={os.path.exists(common.GPU_LOCK)})")
            device = "cpu"
    try:
        try:
            model = load(a.model, device)
            run(model, a.model, device)
        except Exception as e:  # e.g. unsupported GPU arch -> fall back to CPU int8
            if device != "cuda":
                raise
            log("CUDA path failed:", repr(e), "-> falling back to CPU int8")
            lock.release()
            model = load(a.model, "cpu")
            run(model, a.model, "cpu")
    finally:
        lock.release()


if __name__ == "__main__":
    main()
