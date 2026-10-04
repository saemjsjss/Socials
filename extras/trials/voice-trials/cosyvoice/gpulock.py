"""Shared-GPU etiquette for the voice trials.

- Waits while another engine's gpu.lock exists (a lock older than 20 min is stale).
- Checks free VRAM in a *separate* process (torch.cuda.mem_get_info) so the caller can
  still decide to hide the GPU (CUDA_VISIBLE_DEVICES='') before importing torch.
- Creates gpu.lock (content = engine name) while we hold the GPU; release() deletes it.
"""
import os
import subprocess
import sys
import time

LOCK = r"C:\Hangeul\JARVIS\voice-trials\gpu.lock"
ENGINE = "cosyvoice"
STALE_S = 20 * 60
NEED_GB = 4.5
HERE = os.path.dirname(os.path.abspath(__file__))


def _free_gb():
    out = subprocess.run([sys.executable, os.path.join(HERE, "gpucheck.py")],
                         capture_output=True, text=True, timeout=180)
    try:
        free_b, total_b = [int(x) for x in out.stdout.strip().split()[-2:]]
        return free_b / 1024 ** 3, total_b / 1024 ** 3
    except Exception:
        print("[gpulock] gpucheck failed:", out.stdout, out.stderr, flush=True)
        return 0.0, 0.0


def _other_lock():
    """Return (holder, age_s) if someone else's non-stale lock exists, else None."""
    if not os.path.exists(LOCK):
        return None
    try:
        holder = open(LOCK, encoding="utf-8").read().strip()
    except Exception:
        holder = "?"
    age = time.time() - os.path.getmtime(LOCK)
    if holder == ENGINE:
        return None
    if age > STALE_S:
        print(f"[gpulock] lock by '{holder}' is stale ({age/60:.1f} min) - ignoring it", flush=True)
        return None
    return holder, age


def acquire(max_wait_s=15 * 60, poll_s=20):
    """Returns 'cuda' if we got the GPU (lock written), else 'cpu'."""
    t0 = time.time()
    while True:
        other = _other_lock()
        if other is None:
            free, total = _free_gb()
            print(f"[gpulock] free VRAM {free:.2f} / {total:.2f} GB (need {NEED_GB})", flush=True)
            if free >= NEED_GB:
                with open(LOCK, "w", encoding="utf-8") as f:
                    f.write(ENGINE)
                print("[gpulock] lock acquired", flush=True)
                return "cuda"
            reason = f"only {free:.2f} GB free"
        else:
            reason = f"lock held by '{other[0]}' ({other[1]/60:.1f} min old)"
        if time.time() - t0 > max_wait_s:
            print(f"[gpulock] gave up waiting ({reason}) - falling back to CPU", flush=True)
            return "cpu"
        print(f"[gpulock] waiting: {reason}", flush=True)
        time.sleep(poll_s)


def release():
    try:
        if os.path.exists(LOCK) and open(LOCK, encoding="utf-8").read().strip() == ENGINE:
            os.remove(LOCK)
            print("[gpulock] lock released", flush=True)
    except Exception as e:
        print("[gpulock] release error:", e, flush=True)
