"""The handoff: how every job gives its records to the publisher process.

The bot process (the watcher, the brief, command answers) must stay light and keep its loop free
(01 §5, R12), and a button report must print its answer and exit; so no job embeds or uploads
itself. It builds its records (src.cloud.records) and calls

    submit(job, batches, failed_reads)

which writes one small JSON file, data/cloud/pending/<time>-<job>.json (.part + os.replace), and
starts `python -m src.cloud.publish --from <file>` without waiting for it: the venv's console
python.exe (never pythonw), UTF-8, no window, stdin closed and its output appended to
hangeul_sync.log (never the caller's pipe: a button report's parent reads that pipe to its end),
CUDA hidden, and its own time limit (the publisher stops itself after CHILD_TIMEOUT seconds). The
publisher deletes the file when it is done, sent or failed (D6: no queue beyond the hash state);
files left by a publisher that was killed are removed after STALE_HOURS.

submit() never raises and returns at once; it does nothing at all (no file, no process) unless
publishing is on (SUPABASE_URL, SUPABASE_SECRET_KEY and CLOUD_PUBLISH_ENABLED). Check enabled()
first to skip building records when it is off.

The file:
  {"version": 1, "job": "passport_watcher", "created_at": "2026-09-29T18:21:04+06:00",
   "failed_reads": ["calendar.php: the portal did not answer in time"],
   "batches": [records.batch(...) or records.batches(...), ...]}
a batch being {"kind", "scope", "complete", "rows": [records], "all_keys"?: [...]} (one scope)
or {"kind", "scope": null, "complete", "rows", "scope_range"?: [lo, hi]} (each row's own scope).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.cloud.publish import CHILD_TIMEOUT, CLOUD_DIR, enabled  # noqa: F401 (enabled is part of the API)
from src.config import BOT_ROOT

logger = logging.getLogger("hangeul.cloud")

PENDING_DIR = CLOUD_DIR / "pending"
LOG_PATH = BOT_ROOT / "hangeul_sync.log"
STALE_HOURS = 6
CREATE_NO_WINDOW = 0x08000000
FORMAT_VERSION = 1

_children: List[subprocess.Popen] = []


def _slug(job: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(job or "command"))[:40] or "command"


def _prune() -> None:
    """Remove handoff files a publisher never finished (it was killed: stop.bat, a power cut)."""
    cutoff = time.time() - STALE_HOURS * 3600
    for f in PENDING_DIR.glob("*.json*"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def write(job: str, batches: Sequence[Dict[str, Any]], failed_reads: Sequence[str] = ()) -> Path:
    """Write one handoff file atomically -> its path."""
    from src.cloud.records import jsonable, now
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    _prune()
    at = now()
    doc = {"version": FORMAT_VERSION, "job": str(job or "command"), "created_at": at.isoformat(timespec="seconds"),
           "failed_reads": [str(x) for x in failed_reads or []],
           "batches": jsonable([b for b in batches or [] if b])}
    path = PENDING_DIR / f"{at:%Y%m%d-%H%M%S-%f}-{_slug(job)}.json"
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    os.replace(part, path)
    return path


def _python() -> str:
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):         # background mode: its console-less twin
        exe = exe[:-len("pythonw.exe")] + "python.exe"
    return exe


def child_env() -> Dict[str, str]:
    """The publisher process's environment: this one, UTF-8, the Hugging Face hub offline, and
    CUDA hidden with CUDA_VISIBLE_DEVICES=-1 (embed.NO_GPU; an empty value would not reach it on
    Windows, and torch would see the GPU)."""
    from src.cloud.embed import NO_GPU
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "CUDA_VISIBLE_DEVICES": NO_GPU, "HF_HUB_OFFLINE": "1"}


def start(args: Sequence[str], log) -> subprocess.Popen:
    """`python <args>` as the publisher is started (scheduler._run_module's settings): the venv's
    console python.exe, the bot folder, child_env(), stdin closed, output to `log`, no window."""
    return subprocess.Popen([_python(), *args], cwd=str(BOT_ROOT), stdin=subprocess.DEVNULL, stdout=log,
                            stderr=log, env=child_env(), close_fds=True,
                            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)


def spawn(path: Path, timeout: float = CHILD_TIMEOUT) -> subprocess.Popen:
    """Start the publisher on `path`, not waiting for it."""
    with open(LOG_PATH, "a", encoding="utf-8") as log:
        proc = start(["-m", "src.cloud.publish", "--from", str(path), "--timeout", str(int(timeout))], log)
    _children[:] = [p for p in _children if p.poll() is None]
    _children.append(proc)                           # a reference, so it is not reaped mid-run
    return proc


def submit(job: str, batches: Sequence[Optional[Dict[str, Any]]], failed_reads: Sequence[str] = ()) -> Optional[Path]:
    """Hand a job's batches to the publisher process and return at once (see the module
    docstring). -> the handoff file, or None when publishing is off, there is nothing to send, or
    the file could not be written or the process not started (one log line). Never raises."""
    try:
        if not enabled():
            return None
        batches = [b for b in batches or [] if b]
        if not batches:
            return None
        path = write(job, batches, failed_reads)
        try:
            spawn(path)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path
    except Exception as e:
        logger.warning("Supabase publish failed (%s): the handoff could not be written or started (%s)",
                       job, type(e).__name__)
        return None


async def submit_async(job: str, batches: Sequence[Optional[Dict[str, Any]]],
                       failed_reads: Sequence[str] = ()) -> Optional[Path]:
    """submit() off the event loop (the file of a full student list is ~1 MB): for the bot process."""
    return await asyncio.to_thread(submit, job, batches, failed_reads)
