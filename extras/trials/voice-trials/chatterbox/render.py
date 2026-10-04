# Render Jennie trial samples with Chatterbox Multilingual (Resemble AI, MIT).
# - HF cache kept inside this trial folder
# - shared GPU: cooperative lock file + free-VRAM check (>= 4.5 GB) before using CUDA
import os
import sys
import json
import time
import inspect
from pathlib import Path

ROOT = Path(r"C:\Hangeul\JARVIS\voice-trials\chatterbox")
os.environ["HF_HOME"] = str(ROOT / "hf")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
# spacy_pkuseg (Chinese segmenter, loaded eagerly by the MTL tokenizer) otherwise caches to ~/.pkuseg
os.environ["PKUSEG_HOME"] = str(ROOT / "pkuseg_home")

import numpy as np
import soundfile as sf
import torch

LOCK = Path(r"C:\Hangeul\JARVIS\voice-trials\gpu.lock")
OUT_DIR = Path(r"C:\Hangeul\JARVIS\voice-samples")
REF = ROOT / "ref" / "melotts_kr_ref_24k.wav"
MIN_FREE_GB = 4.5
STALE_S = 20 * 60
ENGINE = "chatterbox"

T3_MODEL = os.environ.get("CB_T3_MODEL", "v3")
FORCE_CPU = os.environ.get("CB_FORCE_CPU") == "1"
ONLY = os.environ.get("CB_ONLY")  # optional substring filter on output names

TEXTS = {
    "en": ("en", "Good evening! The portal sync just finished. One new student was document-verified, "
                 "and all seven progress sheets are up to date. Anything else I can check for you?"),
    "kr-neutral": ("ko", "안녕하세요. 방금 포털 동기화가 끝났습니다. 새로 서류 검증된 학생이 한 명 있고, "
                         "진행 시트 일곱 개가 모두 최신 상태입니다."),
    "kr-aegyo": ("ko", "짜잔! 제니예요! 방금 포털 동기화가 끝났어용. 새로 서류 검증된 학생이 한 명 있구요, "
                       "진행 시트 일곱 개 모두 최신 상태예요! 헤헤, 또 궁금한 거 있으세용?"),
}

# (voice_tag, prompt_path, setting_suffix, text_kind, exaggeration, cfg_weight)
JOBS = []
for voice, prompt in (("default", None), ("meloref", REF)):
    JOBS.append((voice, prompt, "", "en", 0.5, 0.5))
    JOBS.append((voice, prompt, "", "kr-neutral", 0.5, 0.5))
    for ex, cfg in ((0.5, 0.5), (0.8, 0.3), (1.1, 0.2)):
        JOBS.append((voice, prompt, f"-ex{ex}-cfg{cfg}", "kr-aegyo", ex, cfg))
# The default built-in voice is an English speaker; the model card advises cfg_weight=0
# to reduce accent carry-over when the prompt language differs from the target language.
JOBS.append(("default", None, "-cfg0", "kr-neutral", 0.5, 0.0))


def log(*a):
    print(*a, flush=True)


def try_acquire_lock():
    """Return True if we now hold the lock, False if someone else holds a fresh one."""
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, ENGINE.encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            age = time.time() - LOCK.stat().st_mtime
            owner = LOCK.read_text(errors="replace").strip()
        except FileNotFoundError:
            return False
        if owner == ENGINE:
            log("found our own leftover lock; reclaiming")
            LOCK.touch()
            return True
        if age > STALE_S:
            log(f"lock held by '{owner}' is stale ({age/60:.1f} min); removing")
            try:
                LOCK.unlink()
            except FileNotFoundError:
                pass
            return False
        log(f"GPU lock held by '{owner}' ({age/60:.1f} min old); waiting")
        return False


def release_lock():
    try:
        if LOCK.exists() and LOCK.read_text(errors="replace").strip() == ENGINE:
            LOCK.unlink()
            log("released gpu.lock")
    except Exception as e:  # noqa: BLE001
        log("lock release error:", e)


def get_gpu(max_wait_s=45 * 60):
    """Acquire lock + ensure >= MIN_FREE_GB free VRAM. Returns 'cuda' or 'cpu'."""
    if FORCE_CPU or not torch.cuda.is_available():
        return "cpu"
    t0 = time.time()
    while time.time() - t0 < max_wait_s:
        if try_acquire_lock():
            free, total = torch.cuda.mem_get_info()
            free_gb = free / 1024 ** 3
            log(f"VRAM free {free_gb:.2f} GB / {total/1024**3:.2f} GB")
            if free_gb >= MIN_FREE_GB:
                return "cuda"
            log(f"not enough free VRAM (< {MIN_FREE_GB} GB); releasing lock and retrying in 60 s")
            release_lock()
            time.sleep(60)
        else:
            time.sleep(20)
    log("GPU not available within wait budget -> falling back to CPU")
    return "cpu"


def main():
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = get_gpu()
    log("device:", device)
    results = []
    try:
        kw = {}
        if "t3_model" in inspect.signature(ChatterboxMultilingualTTS.from_pretrained).parameters:
            kw["t3_model"] = T3_MODEL
        t = time.perf_counter()
        model = ChatterboxMultilingualTTS.from_pretrained(device=device, **kw)
        load_s = time.perf_counter() - t
        log(f"model loaded in {load_s:.1f} s ({kw})  sr={model.sr}")
        if device == "cuda":
            torch.cuda.reset_peak_memory_stats()

        for voice, prompt, suffix, kind, ex, cfg in JOBS:
            name = f"real__{ENGINE}__{voice}{suffix}__{kind}.wav"
            if ONLY and ONLY not in name:
                continue
            lang, text = TEXTS[kind]
            if device == "cuda":
                LOCK.touch()  # keep our lock fresh so others don't treat it as stale
            torch.manual_seed(1234)
            if device == "cuda":
                torch.cuda.manual_seed_all(1234)
                torch.cuda.synchronize()
            t = time.perf_counter()
            wav = model.generate(
                text,
                language_id=lang,
                audio_prompt_path=str(prompt) if prompt else None,
                exaggeration=ex,
                cfg_weight=cfg,
            )
            if device == "cuda":
                torch.cuda.synchronize()
            synth_s = time.perf_counter() - t
            audio = wav.squeeze().detach().cpu().numpy().astype(np.float32)
            out = OUT_DIR / name
            sf.write(str(out), audio, model.sr, subtype="PCM_16")
            dur = len(audio) / model.sr
            r = dict(file=str(out), voice=voice, kind=kind, lang=lang, exaggeration=ex, cfg_weight=cfg,
                     device=device, synth_s=round(synth_s, 2), duration_s=round(dur, 2),
                     rtf=round(synth_s / max(dur, 1e-6), 3))
            log(json.dumps(r, ensure_ascii=False))
            results.append(r)

        peak = None
        if device == "cuda":
            peak = torch.cuda.max_memory_reserved() / 1024 ** 3
            log(f"peak VRAM reserved by this process: {peak:.2f} GB")
    finally:
        if device == "cuda":
            release_lock()

    summ = ROOT / "render_results.json"
    prev = []
    if summ.exists() and ONLY:
        prev = [p for p in json.loads(summ.read_text(encoding="utf-8"))["samples"]
                if p["file"] not in {r["file"] for r in results}]
    summ.write_text(json.dumps({"device": device, "t3_model": kw.get("t3_model"), "load_s": round(load_s, 1),
                                "peak_vram_gb": round(peak, 2) if peak else None,
                                "samples": prev + results}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
