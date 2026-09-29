"""Publishing records to Supabase: the hg_sync RPC, the hash state, the hg_runs rows.

    python -m src.cloud.publish --from data\\cloud\\pending\\<time>-<job>.json [--dry-run]

is the publisher process every job starts through src.cloud.handoff: it embeds and uploads the
handoff file's batches, then deletes the file (sent or failed: D6, no retry queue beyond the hash
state). It hides CUDA before anything can import torch, so gte-small runs on the CPU (R12).

publish(kind, scope, rows, complete) is the engine (the publisher process and the backfill run it):
  * rows are every record a read saw for that (kind, scope) (src.cloud.records); only those whose
    content_hash differs from data/cloud_state.json are embedded and sent (D9), at most 200 a call
    and at most MAX_BODY bytes of JSON a call (a record larger than that goes in a call of its
    own, with one log line of its size);
  * complete=True only for a whole read (R2, R5): the last call of the (kind, scope) then carries
    p_all_keys, the full key list, and Supabase deletes that scope's other records (D10); a partial
    or failed read sends p_all_keys null and deletes nothing;
  * the hash state advances only for rows Supabase accepted (an HTTP 2xx: hg_sync is one
    transaction), so a row that failed goes again next run; it is written with .part + os.replace.
    The keys a complete read no longer shows are forgotten only once the call that deleted them
    was accepted, and a scope's key digest (the "nothing changed" shortcut) is dropped before its
    first call and set again only after its last: a call Supabase took but never answered can
    never make a later read look already sent;
  * reads are published in the order they were made, whatever order the publishers get the lock
    in: a complete read older than the last complete read of its (kind, scope) deletes nothing, a
    record older than the version last sent is not sent, and a complete read never deletes a record
    that a newer read showed (the state keeps each record's read_at and each scope's last complete
    read time);
  * every chunk in Supabase has one embed_model: once the state records one, a process with
    another model publishes nothing (one log line) until the chunks are re-embedded;
  * it never raises: a failure is one log line "Supabase publish failed (<kind>): <short reason>",
    the reason built from the HTTP status and Postgres code only (a server message can quote a key,
    and keys hold passport numbers), and the job carries on. Once Supabase has not answered, or
    refused the key, or gte-small could not be loaded or used (an EmbedError), the rest of the run
    is skipped without more lines;
  * it does nothing unless SUPABASE_URL, SUPABASE_SECRET_KEY and CLOUD_PUBLISH_ENABLED are all set;
  * a dry run writes each request body, exactly as it would be sent, to data/cloud/dry_run/<run>/
    and leaves the hash state as it was.

Every publish belongs to a run: one hg_runs row (POST at the start with status null, PATCH at the
end with finished_at, status ok / partial / failed, the counts and a short note). One process
publishes at a time (data/cloud/publish.lock), so the hash state is never written by two.

The local state is {"version", "embed_model", "records": {"<kind>|<key>": {"h": content_hash,
"s": scope, "t": read_at}}, "scopes": {"<kind>|<scope>": digest of the keys of its last complete
publish}, "reads": {"<kind>|<scope>": read time of its last complete publish}}: the scope is kept
beside each hash so a complete read can forget the keys Supabase just deleted (otherwise an
identical record coming back later would never be sent again), and the read times order reads that
reach the publisher out of order (the watcher hands its list over up to 20 minutes after reading it).

hg_runs.counts: "upserted", "deleted" (Supabase's answers), "unchanged" (records the hash state
already had, plus those Supabase answered unchanged), "older" (records not sent because a newer
read of them was already sent), "sent", "failed_reads", "failed", "by_kind" ({kind: [upserted,
deleted, unchanged]}), "embedded", "chunks".
"""
from __future__ import annotations

import os
import sys

if __name__ == "__main__":          # the publisher process: no GPU, before torch can be imported
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"      # "" is dropped from a Windows environment (embed.NO_GPU)

import argparse
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

from src.config import BOT_ROOT, settings

logger = logging.getLogger("hangeul.cloud")

DATA_DIR = BOT_ROOT / "data"
STATE_PATH = DATA_DIR / "cloud_state.json"
CLOUD_DIR = DATA_DIR / "cloud"
DRY_RUN_DIR = CLOUD_DIR / "dry_run"
LOCK_PATH = CLOUD_DIR / "publish.lock"

MAX_ROWS = 200              # hg_sync refuses more
MAX_CHUNKS = 250            # chunks embedded at a time (384 numbers each, about 5 KB of JSON)
MAX_BODY = 1_000_000        # bytes of one hg_sync body: a call is split to stay at or under it
TIMEOUT = 30.0              # seconds per HTTP call
LOCK_WAIT = 20 * 60         # how long a publisher waits for another to finish
CHILD_TIMEOUT = 3600        # the publisher process stops itself after this long
STATE_VERSION = 1
DEFAULT_JOB = "command"

# Tests put an httpx.MockTransport here; None is the real network.
TRANSPORT: Optional[httpx.BaseTransport] = None
_DRY_RUN = False


def enabled() -> bool:
    """Publishing is on only when SUPABASE_URL, SUPABASE_SECRET_KEY and CLOUD_PUBLISH_ENABLED are
    all set (the secret key's value is never logged)."""
    return bool(str(settings.SUPABASE_URL or "").strip() and str(settings.SUPABASE_SECRET_KEY or "").strip()
                and settings.CLOUD_PUBLISH_ENABLED)


def set_dry_run(on: bool) -> None:
    """Every publish in this process from now on is a dry run (the backfill's --dry-run)."""
    global _DRY_RUN
    _DRY_RUN = bool(on)


def _dry(dry_run: Optional[bool]) -> bool:
    return _DRY_RUN if dry_run is None else bool(dry_run)


@dataclass
class Result:
    """What one publish(kind, scope, ...) did. `error` is the short reason logged, never data."""
    kind: str
    scope: str
    rows: int = 0            # records given
    changed: int = 0         # records whose hash differed (embedded and sent)
    upserted: int = 0
    unchanged: int = 0       # the hash state already had them, or Supabase answered "unchanged"
    deleted: int = 0
    calls: int = 0           # hg_sync calls made (or written, in a dry run)
    left_out: int = 0        # records refused before sending (no key, wrong scope...)
    older: int = 0           # records not sent: a newer read of them was sent already
    older_read: bool = False  # a complete read older than the last complete one: nothing deleted
    ok: bool = True
    skipped: str = ""        # why nothing was sent, when nothing was
    error: str = ""
    delegated: bool = False  # handed to the publisher process (src.cloud.handoff)


# --------------------------------------------------------------------------- hash state

def _empty_state() -> Dict[str, Any]:
    return {"version": STATE_VERSION, "embed_model": "", "records": {}, "scopes": {}, "reads": {}}


def load_state() -> Dict[str, Any]:
    """data/cloud_state.json, or an empty state when it is missing or unreadable (everything is then
    sent again: harmless, Supabase answers "unchanged" for rows it has)."""
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty_state()
    except Exception as e:
        logger.warning("Supabase hash state unreadable (%s); every record is sent again.", type(e).__name__)
        return _empty_state()
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION \
            or not isinstance(state.get("records"), dict) or not isinstance(state.get("scopes"), dict):
        return _empty_state()
    if not isinstance(state.get("reads"), dict):
        state["reads"] = {}
    return state


def save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    part = STATE_PATH.with_name(STATE_PATH.name + ".part")
    part.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(part, STATE_PATH)


def _split_state_key(key: str) -> Tuple[str, str]:
    kind, _, rest = key.partition("|")        # a record key may hold "|" itself: split on the first
    return kind, rest


def known_scopes(kind: str) -> set:
    """The scopes of `kind` the hash state holds records in (what Supabase was sent)."""
    return {v.get("s") for k, v in load_state()["records"].items()
            if _split_state_key(k)[0] == kind and isinstance(v, dict) and v.get("s")}


def known_keys(kind: str, scope: Optional[str] = None) -> set:
    """The keys of `kind` (in `scope`, when given) the hash state holds."""
    out = set()
    for k, v in load_state()["records"].items():
        kk, key = _split_state_key(k)
        if kk == kind and isinstance(v, dict) and (scope is None or v.get("s") == scope):
            out.add(key)
    return out


def _keys_digest(keys: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(keys))).encode("utf-8")).hexdigest()


def _when(value: Any) -> Optional[datetime]:
    """A read time as the records write it (ISO with its offset) -> an aware datetime; None for
    none, or for a text that is no such time (then it orders nothing)."""
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


# --------------------------------------------------------------------------- one publisher at a time

_mutex = threading.RLock()
_lock_depth = 0
_lock_fd: Optional[int] = None


def _os_lock(path: Path, wait: float) -> Optional[int]:
    """An OS lock on `path` (released by the OS if the process dies), waiting up to `wait` s."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + max(0.0, wait)
    while True:
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() >= deadline:
                os.close(fd)
                return None
            time.sleep(0.25)


def _os_unlock(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, 0)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextmanager
def publisher_lock(wait: float = LOCK_WAIT):
    """Hold data/cloud/publish.lock (re-entrant in one process) -> yields whether it was got."""
    global _lock_depth, _lock_fd
    with _mutex:
        if _lock_depth:
            _lock_depth += 1
            try:
                yield True
            finally:
                _lock_depth -= 1
            return
        fd = _os_lock(LOCK_PATH, wait)
        if fd is None:
            yield False
            return
        _lock_depth, _lock_fd = 1, fd
        try:
            yield True
        finally:
            _lock_depth, _lock_fd = 0, None
            _os_unlock(fd)


# --------------------------------------------------------------------------- runs (hg_runs)

def _now_iso() -> str:
    from src.cloud.records import as_read_at
    return as_read_at(None)


@dataclass
class Run:
    job: str
    dry: bool
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: str = field(default_factory=_now_iso)
    failed_reads: List[str] = field(default_factory=list)
    client: Optional[httpx.Client] = None
    posted: bool = False              # its hg_runs row exists (else p_run is null)
    down: str = ""                    # why Supabase is given up on for the rest of the run
    down_logged: bool = False         # the line saying so was written: the rest are silent
    publishes: int = 0
    failed: List[str] = field(default_factory=list)
    upserted: int = 0
    deleted: int = 0
    unchanged: int = 0
    older: int = 0
    sent: int = 0
    by_kind: Dict[str, List[int]] = field(default_factory=dict)
    embedded: int = 0
    chunks: int = 0
    embed_seconds: float = 0.0
    requests: int = 0                 # dry run: files written
    dry_dir: Optional[Path] = None
    started: float = field(default_factory=time.perf_counter)

    def fail(self, kind: str, reason: str) -> None:
        """One log line for a failure; after Supabase is given up on, the rest are silent."""
        self.failed.append(f"{kind}: {reason}")
        if self.down_logged:
            logger.debug("Supabase publish skipped (%s): %s", kind, reason)
            return
        self.down_logged = bool(self.down)
        logger.warning("Supabase publish failed (%s): %s", kind, reason)

    def write(self, label: str, body: bytes) -> Path:
        if self.dry_dir is None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.dry_dir = DRY_RUN_DIR / f"{stamp}-{re.sub(r'[^A-Za-z0-9_-]', '_', self.job)}-{self.id[:8]}"
            self.dry_dir.mkdir(parents=True, exist_ok=True)
        path = self.dry_dir / f"{self.requests:04d}-{label}.json"
        path.write_bytes(body)
        self.requests += 1
        return path


_current: Optional[Run] = None


def current_run() -> Optional[Run]:
    return _current


def current_job() -> str:
    return _current.job if _current is not None else DEFAULT_JOB


def _body(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _client() -> httpx.Client:
    key = str(settings.SUPABASE_SECRET_KEY or "").strip()
    return httpx.Client(base_url=str(settings.SUPABASE_URL).strip().rstrip("/"), timeout=TIMEOUT,
                        transport=TRANSPORT, follow_redirects=False,
                        headers={"apikey": key, "Authorization": f"Bearer {key}",
                                 "Content-Type": "application/json", "Accept": "application/json"})


_PG_CODE_RE = re.compile(r"^[A-Z0-9]{5,10}$")


def _reason(resp: httpx.Response) -> Tuple[str, bool]:
    """A refused request as (a short reason with no server text in it, whether to give up on
    Supabase for the rest of the run)."""
    code = ""
    try:
        body = resp.json()
        if isinstance(body, dict) and _PG_CODE_RE.match(str(body.get("code") or "")):
            code = f" {body['code']}"
    except Exception:
        pass
    status = resp.status_code
    if status in (401, 403):
        return f"HTTP {status}{code} (the key was refused)", True
    if status == 404:
        return f"HTTP 404{code} (hg_sync or hg_runs not found: is the Jeannie migration applied?)", True
    if status >= 500:
        return f"HTTP {status}{code} (Supabase server error)", True
    if status == 409:
        return f"HTTP 409{code} (conflict)", False
    return f"HTTP {status}{code} (refused)", False


def _request(r: Run, method: str, path: str, body: bytes, prefer: str = "") -> Tuple[bool, Any, str]:
    """-> (accepted, the JSON answer or None, the short reason when not accepted)."""
    if r.client is None:
        r.client = _client()
    try:
        resp = r.client.request(method, path, content=body,
                                headers={"Prefer": prefer} if prefer else None)
    except httpx.TimeoutException as e:
        r.down = f"Supabase did not answer in time ({type(e).__name__})"
        return False, None, r.down
    except httpx.HTTPError as e:
        r.down = f"could not connect to Supabase ({type(e).__name__})"
        return False, None, r.down
    if 200 <= resp.status_code < 300:
        try:
            return True, resp.json() if resp.content else None, ""
        except ValueError:
            return True, None, ""
    reason, give_up = _reason(resp)
    if give_up:
        r.down = reason
    return False, None, reason


def _start(r: Run) -> None:
    body = _body({"id": r.id, "job": r.job, "started_at": r.started_at, "counts": {}})
    if r.dry:
        r.write("POST-hg_runs", body)
        r.posted = True
        return
    if not str(settings.SUPABASE_URL).strip().lower().startswith("https://"):
        r.down = "SUPABASE_URL is not an https:// address"
        r.fail("hg_runs", r.down)
        return
    ok, _, reason = _request(r, "POST", "/rest/v1/hg_runs", body, prefer="return=minimal")
    r.posted = ok
    if not ok:
        r.fail("hg_runs", reason)


def _status(r: Run) -> str:
    if r.failed and (r.down or len(r.failed) >= max(1, r.publishes)):
        return "failed"
    if r.failed or r.failed_reads:
        return "partial"
    return "ok"


def _finish(r: Run) -> None:
    status = _status(r)
    note = "; ".join(x for x in (f"{len(r.failed_reads)} read(s) failed" if r.failed_reads else "",
                                 f"{len(r.failed)} publish(es) failed" if r.failed else "") if x) or None
    counts = {"upserted": r.upserted, "deleted": r.deleted, "unchanged": r.unchanged, "older": r.older,
              "sent": r.sent, "failed_reads": list(r.failed_reads), "failed": list(r.failed),
              "by_kind": r.by_kind, "embedded": r.embedded, "chunks": r.chunks}
    body = _body({"finished_at": _now_iso(), "status": status, "counts": counts, "note": note})
    seconds = time.perf_counter() - r.started
    if r.dry:
        r.write("PATCH-hg_runs", body)
        logger.info("Supabase dry run (%s): %d request(s) written to %s in %.1f s (%d record(s) embedded, "
                    "%d chunk(s), %.1f s embedding%s).", r.job, r.requests, r.dry_dir, seconds, r.embedded,
                    r.chunks, r.embed_seconds, _memory_note())
        return
    # The row is closed even when Supabase was given up on mid-run (a 5xx, a timeout, a refused
    # call, a model mismatch): one PATCH, so a run that failed never looks like one still going.
    # Once one failure was logged, this one's failing is not logged again (Run.fail).
    if r.posted:
        ok, _, reason = _request(r, "PATCH", f"/rest/v1/hg_runs?id=eq.{r.id}", body, prefer="return=minimal")
        if not ok:
            r.fail("hg_runs", reason)
    if r.publishes or r.failed:
        logger.info("Supabase publish (%s): %s, %d upserted, %d deleted, %d unchanged, %d row(s) sent, "
                    "%d failed, %d read(s) failed; %d record(s) embedded in %.1f s; %.1f s in all%s.",
                    r.job, status, r.upserted, r.deleted, r.unchanged, r.sent, len(r.failed),
                    len(r.failed_reads), r.embedded, r.embed_seconds, seconds, _memory_note())


@contextmanager
def run(job: str = DEFAULT_JOB, failed_reads: Sequence[str] = (), *, dry_run: Optional[bool] = None):
    """One job run: an hg_runs row around every publish inside it (nested runs join the outer one).
    Yields the Run, or None when publishing is off (then nothing happens)."""
    global _current
    if _current is not None:
        _current.failed_reads.extend(str(x) for x in failed_reads or [])
        yield _current
        return
    dry = _dry(dry_run)
    if not dry and not enabled():
        yield None
        return
    r = Run(job=str(job or DEFAULT_JOB), dry=dry, failed_reads=[str(x) for x in failed_reads or []])
    _current = r
    try:
        try:
            _start(r)
        except Exception as e:
            r.fail("hg_runs", f"internal error ({type(e).__name__})")
        yield r
    finally:
        _current = None
        try:
            _finish(r)
        except Exception as e:
            logger.warning("Supabase publish failed (hg_runs): internal error (%s)", type(e).__name__)
        if r.client is not None:
            r.client.close()


def _memory_note() -> str:
    """", peak memory 1.1 GB" for the log (Windows and POSIX), "" when it cannot be read."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            psapi, kernel = ctypes.WinDLL("psapi"), ctypes.WinDLL("kernel32")
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return ""
            peak = counters.PeakWorkingSetSize
        else:
            import resource
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        return f", peak memory {peak / 2 ** 30:.2f} GB"
    except Exception:
        return ""


# --------------------------------------------------------------------------- publishing

_ROW_FIELDS = ("student_uid", "student_hng_id", "student_name", "passport_no", "day")


def _normalise(kind: str, scope: str, rows: Iterable[Any]) -> Tuple[List[Dict[str, Any]], int]:
    """The rows Supabase would accept, each once, hashed again: -> (rows, how many were left out:
    not a record, no key, another kind or scope, no data object, no source)."""
    from src.cloud.records import as_read_at, clean_text, content_hash, jsonable
    out: Dict[str, Dict[str, Any]] = {}
    left = 0
    for row in rows or []:
        if not isinstance(row, dict):
            left += 1
            continue
        key = clean_text(str(row.get("key") or "")).strip()
        if not key or row.get("scope", scope) != scope or row.get("kind", kind) != kind \
                or not isinstance(row.get("data"), dict) or not str(row.get("source") or "").strip():
            left += 1
            continue
        if key in out:
            left += 1
            continue
        data = jsonable(row["data"])
        content = clean_text(str(row.get("content") or ""))
        clean = {"key": key}
        for f in _ROW_FIELDS:
            v = row.get(f)
            clean[f] = None if v in (None, "") else (v if f == "student_uid" and isinstance(v, int) else
                                                     clean_text(str(v)))
        if clean["student_uid"] is not None and not isinstance(clean["student_uid"], int):
            text = str(clean["student_uid"])
            clean["student_uid"] = int(text) if text.isdigit() and int(text) < 2 ** 31 else None
        clean.update(data=data, content=content, content_hash=content_hash(kind, key, scope, data, content),
                     source=clean_text(str(row["source"])), read_at=as_read_at(row.get("read_at")))
        out[key] = clean
    return list(out.values()), left


def _groups(rows: List[Tuple[Dict[str, Any], List[str]]]) -> List[List[Tuple[Dict[str, Any], List[str]]]]:
    """Rows with their chunk texts in groups of at most MAX_ROWS rows and MAX_CHUNKS chunks, each
    embedded at once (and sent in one call or more: _by_size)."""
    groups: List[List[Tuple[Dict[str, Any], List[str]]]] = []
    n_chunks = 0
    for item in rows:
        if not groups or len(groups[-1]) >= MAX_ROWS or (groups[-1] and n_chunks + len(item[1]) > MAX_CHUNKS):
            groups.append([])
            n_chunks = 0
        groups[-1].append(item)
        n_chunks += len(item[1])
    return groups


def _embedded(r: Run, group: List[Tuple[Dict[str, Any], List[str]]]) -> List[Dict[str, Any]]:
    """The payload rows of one call, each with its chunks' embeddings."""
    from src.cloud import embed
    emb = embed.get_embedder()
    texts = [t for _, parts in group for t in parts]
    started = time.perf_counter()
    vectors = emb.embed(texts) if texts else []
    r.embed_seconds += time.perf_counter() - started
    r.embedded += len(group)
    r.chunks += len(texts)
    if len(vectors) != len(texts):
        raise embed.EmbedError("the embedder returned another number of vectors than texts")
    out, i = [], 0
    for row, parts in group:
        chunks = []
        for n, text in enumerate(parts):
            chunks.append({"ord": n, "content": text, "embedding": [float(f"{x:.8g}") for x in vectors[i]],
                           "embed_model": emb.model_id})
            i += 1
        out.append(dict(row, chunks=chunks))
    return out


def _by_size(kind: str, head: Dict[str, Any], rows: List[Dict[str, Any]],
             keys: Optional[List[str]]) -> List[List[Dict[str, Any]]]:
    """One embedded group's payload rows as the calls that send them, in order, each call's body
    at most MAX_BODY bytes. `head` is the body's other fields (p_run, p_kind, p_scope); `keys` is
    the p_all_keys of the (kind, scope)'s last call, when this group ends a complete read (else
    None): the last call leaves room for it. The sizes are the exact bytes _body writes: the body
    with no rows, plus each row's own JSON and a comma between rows. A row larger than MAX_BODY
    goes in a call of its own (one log line of its size, never its content), and so does a key
    list that leaves no room for any row."""
    base = len(_body(dict(head, p_rows=[], p_all_keys=None)))
    sizes = [len(_body(row)) for row in rows]
    calls: List[List[int]] = []                 # the row indexes of each call, in order
    size, open_call = 0, False                  # the bytes of calls[-1], and whether rows may join it
    for i, n in enumerate(sizes):
        if base + n > MAX_BODY:
            logger.warning("Supabase publish (%s): one record makes a body of %d bytes, over the %d-byte cap; "
                           "it is sent in a call of its own.", kind, base + n, MAX_BODY)
            calls.append([i])
            open_call = False
        elif open_call and size + 1 + n <= MAX_BODY:
            calls[-1].append(i)
            size += 1 + n
        else:
            calls.append([i])
            size, open_call = base + n, True
    calls = calls or [[]]
    extra = len(_body(keys)) - len(b"null") if keys is not None else 0
    last = calls[-1]
    if keys is not None and base + sum(sizes[i] for i in last) + max(0, len(last) - 1) + extra > MAX_BODY:
        # The key list does not fit beside the last call's rows: the last call keeps the rows at
        # its end that fit with it (none, when the list alone is that large), the rest go before.
        room, tail = MAX_BODY - base - extra, []
        for i in reversed(last):
            need = sizes[i] + (1 if tail else 0)
            if need > room:
                break
            room -= need
            tail.insert(0, i)
        if base + extra > MAX_BODY:
            logger.warning("Supabase publish (%s): the key list alone makes a body of %d bytes, over the %d-byte "
                           "cap; it is sent in a call of its own.", kind, base + extra, MAX_BODY)
        calls[-1:] = [last[:len(last) - len(tail)], tail] if tail else [last, []] if last else [[]]
    return [[rows[i] for i in c] for c in calls]


def _can_embed_here() -> bool:
    from src.cloud import embed
    return embed.custom_embedder() or embed.cpu_only_process()


def publish(kind: str, scope: str, rows: Sequence[Dict[str, Any]], complete: bool, *,
            all_keys: Optional[Iterable[str]] = None, read_at: Any = None, dry_run: Optional[bool] = None,
            job: Optional[str] = None) -> Result:
    """Publish every record a read saw for one (kind, scope): see the module docstring. Never raises.
    `all_keys` (complete reads only): the whole key list when `rows` hold only some records
    (records.batch). `read_at`: when the read was made (what orders it against other reads of the
    scope); by default the earliest read_at of its rows. In a process that may not load the model
    (the bot, a job with torch on the GPU) the batch is handed to the publisher process instead
    (src.cloud.handoff.submit)."""
    res = Result(kind=str(kind), scope=str(scope))
    try:
        rows = list(rows or [])
        res.rows = len(rows)
        extra = None if all_keys is None else [str(k) for k in all_keys if k not in (None, "")]
        dry = _dry(dry_run)
        if not dry and not enabled():
            res.skipped = "publishing is off"
            return res
        if not isinstance(kind, str) or not kind.strip() or not isinstance(scope, str) or not scope.strip():
            res.ok, res.error = False, "no kind or scope"
            logger.warning("Supabase publish failed (%s): no kind or scope", kind)
            return res
        if not dry and not _can_embed_here():
            from src.cloud import handoff
            from src.cloud.records import batch
            path = handoff.submit(job or current_job(), [batch(kind, scope, rows, complete, extra, read_at)])
            res.delegated, res.skipped = path is not None, "handed to the publisher process"
            return res
        with run(job or DEFAULT_JOB, dry_run=dry) as r:
            if r is None:
                res.skipped = "publishing is off"
                return res
            return _publish(r, res, kind, scope, rows, bool(complete), extra, read_at)
    except Exception as e:
        res.ok, res.error = False, f"internal error ({type(e).__name__})"
        logger.warning("Supabase publish failed (%s): %s", kind, res.error)
        return res


def _publish(r: Run, res: Result, kind: str, scope: str, rows: List[Any], complete: bool,
             all_keys: Optional[List[str]] = None, read_at: Any = None) -> Result:
    from src.cloud import embed
    from src.cloud.records import as_read_at, clean_text
    r.publishes += 1
    valid, res.left_out = _normalise(kind, scope, rows)
    if res.left_out:
        complete = False               # a record could not be sent: its absence proves nothing
        logger.warning("Supabase publish (%s): %d record(s) left out (no key, another scope or no data); "
                       "nothing is deleted this time.", kind, res.left_out)
    listed = {v["key"] for v in valid} | {clean_text(k).strip() for k in all_keys or [] if str(k).strip()}
    times = [t for t in (_when(v["read_at"]) for v in valid) if t is not None]
    read = _when(as_read_at(read_at)) if read_at not in (None, "") else (min(times) if times else None)
    with publisher_lock() as got:
        if not got:
            res.ok, res.error = False, f"another publisher held the lock for over {LOCK_WAIT // 60} minutes"
            r.fail(kind, res.error)
            return res
        state = load_state()
        recs, scopes, reads = state["records"], state["scopes"], state["reads"]
        prefix = f"{kind}|"
        last_read = _when(reads.get(prefix + scope))
        if complete and read is not None and last_read is not None and read < last_read:
            # Handed over after a newer complete read of this scope was sent (the watcher hands
            # its list over up to 20 minutes after reading it): what it lacks proves nothing.
            complete, res.older_read = False, True
            logger.info("Supabase publish (%s): this read is older than the last complete one sent; "
                        "nothing is deleted this time.", kind)
        changed: List[Dict[str, Any]] = []
        for v in valid:
            e = recs.get(prefix + v["key"])
            e = e if isinstance(e, dict) else {}
            if (e.get("h"), e.get("s")) == (v["content_hash"], scope):
                continue
            sent_at, this = _when(e.get("t")), _when(v["read_at"])
            if sent_at is not None and this is not None and this < sent_at:
                res.older += 1         # a newer read of this record was sent: it is not rolled back
                continue
            changed.append(v)
        res.changed = len(changed)
        gone: List[str] = []
        keep = set()
        if complete:
            for k, e in recs.items():
                if not (k.startswith(prefix) and isinstance(e, dict) and e.get("s") == scope) \
                        or k[len(prefix):] in listed:
                    continue
                sent_at = _when(e.get("t"))
                if read is not None and sent_at is not None and sent_at > read:
                    keep.add(k[len(prefix):])     # a newer read showed it: this one cannot say it is gone
                else:
                    gone.append(k)
        keys = sorted(listed | keep)
        digest = _keys_digest(keys)
        same = len(valid) - res.changed - res.older
        tally = r.by_kind.setdefault(kind, [0, 0, 0])
        res.unchanged, r.unchanged, r.older, tally[2] = res.unchanged + same, r.unchanged + same, \
            r.older + res.older, tally[2] + same
        if not changed and not gone and (not complete or scopes.get(prefix + scope) == digest):
            res.skipped = "no changes"
            return res
        if r.down:
            res.ok, res.error = False, f"skipped ({r.down})"
            r.fail(kind, res.error)
            return res
        emb = embed.get_embedder()
        model = str(state.get("embed_model") or "")
        if model and model != emb.model_id:
            # hg_sync replaces a record's chunks only when its content_hash changes, so records that
            # did not change would keep the old model's vectors: nothing is sent at all.
            r.down = (f"Supabase holds chunks embedded with {model}, but this process embeds with "
                      f"{emb.model_id}: nothing is published until the chunks are re-embedded "
                      "(clear hg_records on the Jeannie side, then delete data/cloud_state.json)")
            res.ok, res.error = False, r.down
            r.fail(kind, res.error)
            return res
        try:
            items = [(v, emb.chunks(v["content"])) for v in changed]
        except embed.EmbedError as e:
            return _model_unavailable(r, res, kind, e)
        groups = _groups(items) or [[]]
        head = {"p_run": r.id if r.posted else None, "p_kind": kind, "p_scope": scope}
        before, dropped = None, False
        for i, group in enumerate(groups):
            try:
                payload_rows = _embedded(r, group)
            except embed.EmbedError as e:
                return _model_unavailable(r, res, kind, e)
            parts = _by_size(kind, head, payload_rows, keys if complete and i == len(groups) - 1 else None)
            for n, part in enumerate(parts):
                last = i == len(groups) - 1 and n == len(parts) - 1     # the (kind, scope)'s last call
                body = _body(dict(head, p_rows=part, p_all_keys=keys if complete and last else None))
                if r.dry:
                    r.write(f"rpc-hg_sync-{re.sub(r'[^A-Za-z0-9_]', '_', kind)}", body)
                    res.calls += 1
                    continue
                if not dropped:
                    # Until this (kind, scope) is sent whole, no key set may count as already applied:
                    # a call Supabase took but did not answer must not let a later read look sent.
                    before, dropped = scopes.pop(prefix + scope, None), True
                    if before is not None:
                        save_state(state)
                ok, answer, reason = _request(r, "POST", "/rest/v1/rpc/hg_sync", body)
                if not ok:
                    res.ok, res.error = False, reason
                    r.fail(kind, reason)
                    return res
                res.calls += 1
                answer = answer if isinstance(answer, dict) else {}
                up, de, un = (int(answer.get(k) or 0) for k in ("upserted", "deleted", "unchanged"))
                res.upserted, res.deleted, res.unchanged = res.upserted + up, res.deleted + de, res.unchanged + un
                r.upserted, r.deleted, r.unchanged, r.sent = r.upserted + up, r.deleted + de, r.unchanged + un, \
                    r.sent + len(part)
                tally[0], tally[1], tally[2] = tally[0] + up, tally[1] + de, tally[2] + un
                for row in part:               # accepted: the whole call is one transaction
                    recs[prefix + row["key"]] = {"h": row["content_hash"], "s": scope, "t": row["read_at"]}
                if last and complete:
                    for k in gone:             # Supabase deleted them: forgotten only now it said so
                        recs.pop(k, None)
                    scopes[prefix + scope] = digest
                    if read is not None:
                        reads[prefix + scope] = read.isoformat(timespec="seconds")
                elif last and before is not None:
                    scopes[prefix + scope] = before   # a partial read deletes nothing: the last complete stands
                state["embed_model"] = emb.model_id
                save_state(state)
        return res


def _model_unavailable(r: Run, res: Result, kind: str, e: Exception) -> Result:
    """gte-small could not be loaded or used (an EmbedError): this publish fails, and so does the
    rest of the run, which is skipped without more lines (D6: one line; the model would fail for
    every other kind too). Nothing was sent for it, so the hash state is not advanced."""
    res.ok, res.error = False, str(e)
    r.down = r.down or res.error
    r.fail(kind, res.error)
    return res


def publish_scopes(kind: str, rows: Sequence[Dict[str, Any]], complete: bool,
                   scope_range: Optional[Sequence[str]] = None, *, read_at: Any = None,
                   dry_run: Optional[bool] = None, job: Optional[str] = None) -> List[Result]:
    """Records of one kind in several scopes (each record's own "scope"), one publish per scope.
    With complete and scope_range (lo, hi): every scope the hash state knows in lo..hi that has no
    record now is published empty and complete (Supabase deletes what it holds there). `read_at`,
    when given, is the read time of every scope (an emptied scope has no row to take it from)."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows or []:
        if isinstance(row, dict) and isinstance(row.get("scope"), str) and row["scope"]:
            groups.setdefault(row["scope"], []).append(row)
    if complete and scope_range and len(scope_range) == 2:
        lo, hi = str(scope_range[0]), str(scope_range[1])
        for s in sorted(known_scopes(kind)):
            if lo <= s <= hi and s not in groups:
                groups[s] = []
    return [publish(kind, s, rs, complete, read_at=read_at, dry_run=dry_run, job=job) for s, rs in groups.items()]


def publish_batches(job: str, batches: Sequence[Dict[str, Any]], failed_reads: Sequence[str] = (), *,
                    dry_run: Optional[bool] = None) -> List[Result]:
    """Every batch of a handoff file (src.cloud.records.batch / batches) in one run. Never raises."""
    results: List[Result] = []
    try:
        if not _dry(dry_run) and not enabled():
            return results
        # One publisher process at a time, for the whole run (one model in memory, one writer of
        # the hash state); the publishes inside take the same lock again.
        with publisher_lock() as got:
            if not got:
                logger.warning("Supabase publish failed (%s): another publisher held the lock for over "
                               "%d minutes", job, LOCK_WAIT // 60)
                return results
            with run(job, failed_reads, dry_run=dry_run) as r:
                if r is None:
                    return results
                for b in batches or []:
                    if not isinstance(b, dict) or not b.get("kind"):
                        continue
                    kind, complete = str(b["kind"]), bool(b.get("complete"))
                    if b.get("scope") is None:
                        results += publish_scopes(kind, b.get("rows") or [], complete, b.get("scope_range"),
                                                  read_at=b.get("read_at"), dry_run=dry_run, job=job)
                    else:
                        results.append(publish(kind, str(b["scope"]), b.get("rows") or [], complete,
                                               all_keys=b.get("all_keys"), read_at=b.get("read_at"),
                                               dry_run=dry_run, job=job))
    except Exception as e:
        logger.warning("Supabase publish failed (%s): internal error (%s)", job, type(e).__name__)
    return results


# --------------------------------------------------------------------------- the publisher process

def process_file(path: Path, *, dry_run: bool = False) -> int:
    """Publish one handoff file (src.cloud.handoff) and delete it, sent or not. -> exit status."""
    path = Path(path)
    try:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("not an object")
        except Exception as e:
            logger.warning("Supabase publish failed (handoff): the handoff file could not be read (%s)",
                           type(e).__name__)
            return 1
        if not dry_run and not enabled():
            return 0
        publish_batches(str(doc.get("job") or DEFAULT_JOB), doc.get("batches") or [],
                        doc.get("failed_reads") or [], dry_run=dry_run)
        return 0
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _deadline(seconds: float, path: Path) -> threading.Timer:
    """Stop this process after `seconds` (a hung call or model must not live on): one log line,
    the handoff file deleted, the lock released by the OS."""
    def expire():
        logger.warning("Supabase publish failed (%s): the publisher ran over %d s and was stopped",
                       current_job(), int(seconds))
        try:
            path.unlink(missing_ok=True)
        finally:
            os._exit(3)
    timer = threading.Timer(max(1.0, seconds), expire)
    timer.daemon = True
    timer.start()
    return timer


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Publish a handoff file to Supabase (src.cloud.handoff).")
    ap.add_argument("--from", dest="path", required=True, help="the handoff file (data/cloud/pending/...)")
    ap.add_argument("--timeout", type=float, default=CHILD_TIMEOUT, help="stop after this many seconds")
    ap.add_argument("--dry-run", action="store_true", help="write the payloads to data/cloud/dry_run/")
    args = ap.parse_args(argv)
    from src.cloud import embed
    if not embed.custom_embedder():
        try:
            embed.prepare_process()            # CPU only, offline; a no-op when already done
        except embed.EmbedError as e:
            logger.warning("Supabase publish failed (handoff): %s", e)
            Path(args.path).unlink(missing_ok=True)
            return 2
    timer = _deadline(args.timeout, Path(args.path))
    try:
        return process_file(Path(args.path), dry_run=args.dry_run)
    finally:
        timer.cancel()


if __name__ == "__main__":
    from src.cloud import embed as _embed
    _embed.prepare_process()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from src.cloud import publish as _publisher      # the module itself, not this __main__ copy
    sys.exit(_publisher.main())
