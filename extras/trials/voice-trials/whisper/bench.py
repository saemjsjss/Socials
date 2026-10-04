"""STT latency benchmark: one ~12 s clip, faster-whisper medium / large-v3, CPU int8 and (if allowed) GPU fp16.

Reports model load time and warm transcribe time (median of 3, language auto-detect).
"""
import json
import os
import statistics
import time

import common
from common import GpuLock, audio_seconds, gpu_free_mib, log, model_path

CLIPS = [
    (r"C:\Hangeul\JARVIS\voice-samples\real__chatterbox__default-cfg0__kr-neutral.wav", "ko"),
    (r"C:\Hangeul\JARVIS\voice-samples\real__cosyvoice__v3-crosslingual-krfemale__en.wav", "en"),
]
REPS = 3


def bench_one(model_name, device, compute_type, beam, cpu_threads=6):
    from faster_whisper import WhisperModel
    t0 = time.perf_counter()
    m = WhisperModel(model_path(model_name), device=device, compute_type=compute_type,
                     cpu_threads=cpu_threads if device == "cpu" else 0)
    load_s = time.perf_counter() - t0
    out = []
    for clip, lang in CLIPS:
        dur = audio_seconds(clip)
        # warm-up
        segs, info = m.transcribe(clip, language=None, beam_size=beam, condition_on_previous_text=False)
        "".join(s.text for s in segs)
        times = []
        for _ in range(REPS):
            t = time.perf_counter()
            segs, info = m.transcribe(clip, language=None, beam_size=beam, condition_on_previous_text=False)
            text = "".join(s.text for s in segs)
            times.append(time.perf_counter() - t)
        med = statistics.median(times)
        row = {"model": model_name, "device": device, "compute": compute_type, "beam": beam,
               "clip": os.path.basename(clip), "clip_s": round(dur, 2), "load_s": round(load_s, 2),
               "median_s": round(med, 2), "rtf": round(med / dur, 3), "lang": info.language}
        log(json.dumps(row, ensure_ascii=False))
        out.append(row)
    del m
    return out


def main():
    rows = []
    for mn in ("medium", "large-v3"):
        rows += bench_one(mn, "cpu", "int8", beam=5)
    rows += bench_one("large-v3", "cpu", "int8", beam=1)

    lock = GpuLock("whisper-bench")
    free = gpu_free_mib()
    if free >= 3072 and not os.path.exists(common.GPU_LOCK) and lock.acquire():
        log(f"GPU: {free} MiB free, lock acquired")
        try:
            for mn in ("medium", "large-v3"):
                rows += bench_one(mn, "cuda", "float16", beam=5)
            rows += bench_one("large-v3", "cuda", "float16", beam=1)
            rows += bench_one("large-v3", "cuda", "int8_float16", beam=5)
        finally:
            lock.release()
    else:
        log(f"GPU skipped (free={free} MiB, lock_exists={os.path.exists(common.GPU_LOCK)})")

    with open(os.path.join(common.ROOT, "bench.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    log("wrote bench.json")


if __name__ == "__main__":
    main()
