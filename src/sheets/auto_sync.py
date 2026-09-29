"""
Automatic portal -> progress sheets + verified-documents sync (run by the bot scheduler).

Each run:
  1. Progress sheets — compares each program's students on the portal with the previous
     run (data/sheet_state.json).  Only a program whose data changed (student added,
     removed, or any field edited) gets its main tab rebuilt; university tabs are
     never touched.
  2. Documents — downloads students who became document-verified since the last run into
     <DOCS_ROOT>\\<PROGRAM>\\<NAME (PASSPORT)>\\ and shrinks any file over 2 MB (original
     backed up).  DOCS_ROOT defaults to the VERIFIED STUDENT DOCUMENTS folder beside the
     BOT folder; see .env.example.
  3. Review — sends a short Telegram summary of what changed (nothing is sent when
     nothing changed).
  4. Verification — every student whose documents or portal record changed is checked
     against the program guidelines (document check) and against the progress sheet
     (field check); both Excel reports are refreshed. See src/verify/auto_verify.py.

Portal access is read-only (GET) throughout.

CLI (run from the BOT folder):
  python -m src.sheets.auto_sync              # one sync run
  python -m src.sheets.auto_sync --no-notify  # same, without the Telegram message
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import time
from typing import Dict, List, Optional, Tuple

from src.config import settings
from src.sheets import progress_builder as pb
from src.sheets import verified_docs as vd

logger = logging.getLogger(__name__)

DATA_DIR = pb.BOT_ROOT / "data"
STATE_PATH = DATA_DIR / "sheet_state.json"
LOCK_PATH = DATA_DIR / "auto_sync.lock"
DOCS_ROOT = settings.docs_root()
LOCK_STALE_SECONDS = 2 * 3600
MAX_NAMES = 8  # names listed per section in the Telegram summary


def _pid_alive(pid: int) -> bool:
    """Is that process still running?  A lock left behind by a process that died must not
    block the next run until it goes stale."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259                                     # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _lock_held(path) -> bool:
    """True only when another *live* run holds this lock."""
    if not path.exists():
        return False
    if time.time() - path.stat().st_mtime >= LOCK_STALE_SECONDS:
        return False
    try:
        pid = int(path.read_text(encoding="utf-8", errors="replace").strip() or 0)
    except ValueError:
        return True                      # unreadable but fresh — leave it alone
    if _pid_alive(pid):
        return True
    logger.info("clearing a lock left by process %s, which is no longer running", pid)
    path.unlink(missing_ok=True)
    return False


def _fresh_portal_client() -> None:
    """Each step runs its own event loop and closes the portal client when done, so
    give the next step a new one."""
    from src.scraper import client as mod
    mod.admin_client = mod.HangeulAdminClient()


# --- 1) progress sheets ----------------------------------------------------------------
def _passport_no(rec: Dict[str, str]) -> str:
    """The row's passport number when it is one: a placeholder such as "PENDING" (no digit in it),
    which many students without a passport share, is no identity."""
    v = re.sub(r"\s+", "", pb.clean_value(rec.get("Passport No", ""))).upper()
    return v if len(v) >= 6 and re.search(r"\d", v) else ""


def _name_mobile(rec: Dict[str, str]) -> str:
    name, mobile = pb._norm_key(rec.get("Full Name", "")), pb._norm_key(rec.get("Mobile", ""))
    return name + mobile if name and mobile else ""


def _row_key(rec: Dict[str, str]) -> str:
    v = pb.clean_value(rec.get("Student ID", "")).upper()
    if v:
        return f"Student ID:{v}"
    v = _passport_no(rec)
    if v:
        return f"Passport No:{v}"
    return "NAME:" + pb._norm_key(rec.get("Full Name", "")) + pb._norm_key(rec.get("Mobile", ""))


def _snapshot(cfg: Dict) -> Dict[str, Dict[str, str]]:
    cols = pb.columns_for(cfg)
    headers = [h for h, _ in cols]
    out = {}
    for s in pb.fetch_roster(cfg):
        rec = dict(zip(headers, pb.build_row(s, cols)))
        key, n = _row_key(rec), 1
        while key in out:                  # two rows with one key must not overwrite each other
            n += 1
            key = f"{_row_key(rec)}#{n}"
        out[key] = rec
    return out


def _digest(rec: Dict[str, str]) -> str:
    return hashlib.sha1(json.dumps(rec, sort_keys=True).encode("utf-8")).hexdigest()


def _same_student(old: Dict[str, str], new: Dict[str, str]) -> int:
    """How surely two rows are one student whose row key changed (a Student ID given at payment
    verification, a passport number filled in or corrected): 3 = the same Student ID, 2 = the same
    passport number, 1 = the same name and mobile, 0 = not the same student."""
    for rank, ident in ((3, lambda r: pb.clean_value(r.get("Student ID", "")).upper()),
                        (2, _passport_no), (1, _name_mobile)):
        a, b = ident(old), ident(new)
        if a and a == b:
            return rank
    return 0


# Name words many students share: one of these alone does not make two names alike.
_COMMON_NAME_WORDS = {"md", "mst", "most", "mohammad", "mohammed", "muhammad", "mohammod", "mohamed", "sk",
                      "sheikh", "shaikh", "syed", "sayed", "kazi", "mir", "mia", "miah",
                      # the commonest Bangladeshi surnames: siblings and strangers share them
                      "rahman", "islam", "hossain", "hossen", "hussain", "uddin", "akter", "akhter",
                      "khatun", "ahmed", "ahmad", "hasan", "hassan", "haque", "hoque", "alam",
                      "begum", "sarker", "sarkar", "chowdhury", "khan", "ali", "miah", "sultana",
                      "karim", "rana", "mondal", "biswas", "das", "roy", "saha"}


def _mobile(rec: Dict[str, str]) -> str:
    digits = re.sub(r"\D", "", pb.clean_value(rec.get("Mobile", "")))
    return digits[-10:] if len(digits) >= 10 else ""


def _likely_same(old: Dict[str, str], new: Dict[str, str]) -> float:
    """How alike two rows are when they share no exact identity (_same_student), for a student
    whose Student ID arrived in the same sync as a corrected name or mobile: the same mobile and a
    name at least 0.6 alike or sharing a telling word ("HASAN MD" -> "HASAN MD RAIYAN"), or the same
    name and date of birth (the mobile corrected). 0 when neither."""
    from difflib import SequenceMatcher
    a, b = pb.clean_value(old.get("Full Name", "")).upper(), pb.clean_value(new.get("Full Name", "")).upper()
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    words_a, words_b = re.findall(r"[a-z]+", a.lower()), re.findall(r"[a-z]+", b.lower())
    shared = {w for w in words_a if len(w) >= 3 and w not in _COMMON_NAME_WORDS} & set(words_b)
    # Alike by the words that tell people apart: "RAHMAN MST SHIULY" and "RAHMAN MD ALAM" share
    # only a surname (siblings on one mobile), "MD MASHIUL" -> "MD MASHIOL" is a spelling fix.
    tell_a = " ".join(w for w in words_a if w not in _COMMON_NAME_WORDS)
    tell_b = " ".join(w for w in words_b if w not in _COMMON_NAME_WORDS)
    tell_ratio = SequenceMatcher(None, tell_a, tell_b).ratio() if tell_a and tell_b else 0.0
    completed = set(words_a) <= set(words_b) or set(words_b) <= set(words_a)   # "HASAN MD" -> "HASAN MD RAIYAN"
    mobile = _mobile(old)
    dob = pb.clean_value(old.get("DOB", ""))
    new_dob = pb.clean_value(new.get("DOB", ""))
    if dob and new_dob and dob != new_dob:
        return 0.0                  # two dates of birth: two people (a family shares one mobile)
    if mobile and mobile == _mobile(new) and (tell_ratio >= 0.7 or shared or completed):
        return 1.0 + ratio
    if dob and dob == pb.clean_value(new.get("DOB", "")) and pb._norm_key(a) == pb._norm_key(b):
        return 1.0
    return 0.0


def _changed_columns(old: Dict[str, str], new: Dict[str, str]) -> str:
    cols = [c for c in new if new.get(c, "") != old.get(c, "")]
    return f"{', '.join(cols[:4])}{'…' if len(cols) > 4 else ''}"


def sheet_changes(prev: Dict[str, Dict], cur: Dict[str, Dict]) -> Tuple[List[str], List[str], List[str]]:
    """(new, removed, edited) between two snapshots {row key: {"name", "hash", "rec"}}. A row whose
    key changed is the same student, not one leaving and one joining, when it shares the Student
    ID, a real passport number, or name and mobile with a row that went (surest match first, each
    row paired once); failing those, when it shares the mobile and a like name, or the name and
    date of birth (_likely_same: a Student ID given in the same sync as a name or mobile corrected).
    It is reported as edited, with the columns that changed, or not at all when nothing in it
    changed."""
    added = [k for k in cur if k not in prev]
    removed = [k for k in prev if k not in cur]
    paired_old, paired_new, edited = set(), set(), []
    for score in (_same_student, _likely_same):
        candidates = [(score(prev[o].get("rec") or {}, cur[n]["rec"]), j, i, o, n)
                      for j, n in enumerate(added) if n not in paired_new
                      for i, o in enumerate(removed) if o not in paired_old]
        for rank, _, _, o, n in sorted((c for c in candidates if c[0] > 0), key=lambda c: (-c[0], c[1], c[2])):
            if o in paired_old or n in paired_new:
                continue
            paired_old.add(o)
            paired_new.add(n)
            if prev[o].get("hash") != cur[n]["hash"]:
                edited.append((n, prev[o].get("rec") or {}))
    for k in cur:
        if k in prev and prev[k]["hash"] != cur[k]["hash"]:
            edited.append((k, prev[k].get("rec") or {}))
    order = {k: i for i, k in enumerate(cur)}
    edited.sort(key=lambda e: order[e[0]])
    return ([cur[k]["name"] for k in added if k not in paired_new],
            [prev[k]["name"] for k in removed if k not in paired_old],
            [f"{cur[k]['name']} ({_changed_columns(old, cur[k]['rec'])})" for k, old in edited])


def sync_sheets(state: Dict) -> List[str]:
    """Rebuild every program + intake sheet whose students changed. Returns report lines."""
    lines: List[str] = []
    prev_all = state.get("sheets", {})
    new_all = {}
    targets = {f"{t['key']}|{t['intake']}": t for t in pb.all_targets()}
    # an intake tracked before but now empty (everyone moved) is rebuilt empty once
    for sk in prev_all:
        if "|" in sk and sk not in targets and prev_all[sk]:
            key, intake = sk.split("|", 1)
            if key in pb.PROGRAMS:
                targets[sk] = pb.target(key, intake)
    for sk, cfg in targets.items():
        snap = _snapshot(cfg)
        cur = {k: {"name": r.get("Full Name", ""), "hash": _digest(r), "rec": r} for k, r in snap.items()}
        prev = prev_all.get(sk)
        new_all[sk] = cur
        added, removed, changed = sheet_changes(prev, cur) if prev is not None else ([], [], [])
        if prev is not None and not (added or removed or changed):
            # portal unchanged — but the main tab may have been edited by hand
            # (cells cleared/typed over). It must mirror the portal, so restore it.
            drift = pb.sheet_drift(cfg)
            if drift > 0:
                pb.build_target(cfg)
                lines.append(f"🛠 {pb.sheet_title(cfg)}: {drift} cell(s) had been changed by hand on the "
                             "sheet — restored from the portal (the main tab always mirrors the portal; "
                             "type notes in your own tabs instead)")
            continue

        pb.build_target(cfg)
        title = pb.sheet_title(cfg)
        if prev is None:
            lines.append(f"📄 {title}: sheet ready ({len(cur)} students) — change tracking started")
            continue
        lines.append(f"📄 {title}: sheet updated — now {len(cur)} students")
        for label, items in (("new", added), ("removed", removed), ("edited", changed)):
            if items:
                shown = "; ".join(items[:MAX_NAMES]) + (f"; +{len(items) - MAX_NAMES} more" if len(items) > MAX_NAMES else "")
                lines.append(f"   • {len(items)} {label}: {shown}")
    state["sheets"] = {k: v for k, v in new_all.items() if v}  # forget intakes that emptied
    return lines


# --- 2) verified documents -------------------------------------------------------------
def sync_docs(cloud: Optional[Dict] = None) -> List[str]:
    """Download the newly verified students' documents -> the summary lines. `cloud` (when
    publishing to Supabase is on) keeps the verified list that was read, for the end of the run."""
    started = time.time()
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(vd.run_local(DOCS_ROOT))
    finally:
        loop.close()
    if cloud is not None:
        cloud["documents"], cloud["documents_at"] = result.get("students"), started
    return doc_lines(result)


def doc_lines(result: Dict[str, list]) -> List[str]:
    """The summary lines for verified_docs.run_local's result: first downloads ("newly verified")
    apart from students whose portal files changed and were fetched again, of whom only those who
    got new files are listed (a re-download that saved nothing is no news)."""
    lines: List[str] = []

    def entry(prog, name, n_files, shrunk, new_word=""):
        files = f"{n_files} {new_word}file(s)" if n_files else "no new files (already on this PC)"
        return (f"   • {name} — {prog}, {files}"
                + (f", {len(shrunk)} compressed to under 2 MB" if shrunk else ""))

    if result.get("saved"):
        lines.append(f"📁 {len(result['saved'])} newly verified student(s) — documents saved:")
        for prog, name, n_files, shrunk in result["saved"][:MAX_NAMES * 2]:
            lines.append(entry(prog, name, n_files, shrunk))
    changed = [r for r in result.get("redownloaded") or [] if r[2]]
    if changed:
        lines.append(f"📁 {len(changed)} student(s) changed their documents on the portal — new files saved:")
        for prog, name, n_files, shrunk in changed[:MAX_NAMES * 2]:
            lines.append(entry(prog, name, n_files, shrunk, "new "))
    for name, err in result.get("failed") or []:
        lines.append(f"⚠️ Could not download documents for {name}: {err[:120]} (will retry next run)")
    return lines


# --- 3) verification of what was downloaded ----------------------------------------------
def verify_docs(cloud: Optional[Dict] = None) -> List[str]:
    """Check the documents of every student whose folder or portal record changed, and
    refresh DOCUMENT CHECK.xlsx / FIELD CHECK.xlsx. Slow (OCR), so each pass takes a few
    students and the rest wait for the next pass. `cloud` (when publishing to Supabase is on)
    keeps the check's result, and whether results.json could be read before it."""
    from src.verify import auto_verify as av
    if cloud is not None:
        from src.cloud.sheet_hooks import store_readable
        cloud["store_ok"] = store_readable(av.STORE_PATH)
    result = av.run(budget=av.DEFAULT_BUDGET)
    if cloud is not None:
        cloud["verify"] = result
    return av.summary_lines(result)


# --- 4) Telegram review ----------------------------------------------------------------
SYNC_TITLE = "🔄 Portal sync — changes found"
CHECK_TITLE = "🔍 Document check"


def notify(lines: List[str], title: str = SYNC_TITLE) -> bool:
    """Send `title` and the lines as plain text to every brief recipient, split between lines
    under Telegram's limit (src.bot.replies.split_text). -> whether Telegram accepted every piece
    for at least one recipient (the text was sent as it is)."""
    import httpx
    from src.bot.replies import split_text
    token = settings.TELEGRAM_BOT_TOKEN
    ids = settings.brief_recipient_ids()
    if not token or not ids:
        logger.warning("Telegram not configured — summary not sent")
        return False
    chunks = split_text(f"{title}\n\n" + "\n".join(lines))
    sent = False
    with httpx.Client(timeout=30) as http:
        for chat in ids:
            accepted = 0
            for chunk in chunks:
                try:
                    resp = http.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                     data={"chat_id": chat, "text": chunk, "disable_web_page_preview": True})
                    if resp.status_code >= 400:
                        logger.warning("Telegram refused the summary for %s: HTTP %s %s", chat,
                                       resp.status_code, resp.text[:200])
                    else:
                        accepted += 1
                except Exception as e:
                    logger.warning("Telegram send to %s failed: %s", chat, e)
            sent = sent or accepted == len(chunks)
    return sent


# --- run ---------------------------------------------------------------------------------
# Google outages (HTTP 5xx), rate limits and dropped connections are normal and usually
# gone by the next run, so a step is retried first, and only a problem that survives
# several runs in a row is worth a Telegram message.
RETRIES = 3
RETRY_WAIT = 20          # seconds between attempts
REPORT_AFTER_FAILURES = 3  # consecutive failed runs (~45 min) before telling the user


def _with_retries(step, label: str):
    """Run a step, retrying transient failures. Raises the last error if all fail.
    Each attempt starts from a fresh portal session (a failed one may be half-closed)."""
    for attempt in range(1, RETRIES + 1):
        try:
            _fresh_portal_client()
            return step()
        except Exception as e:
            if attempt == RETRIES:
                raise
            logger.warning("%s attempt %d/%d failed (%s) — retrying in %ds",
                           label, attempt, RETRIES, e, RETRY_WAIT)
            time.sleep(RETRY_WAIT)


def _failure_line(state: Dict, key: str, label: str, err: Exception) -> List[str]:
    """Count consecutive failures; report only once the trouble persists."""
    fails = state.get("failures", {})
    n = fails.get(key, 0) + 1
    fails[key] = n
    state["failures"] = fails
    logger.error("%s failed (%d in a row): %s", label, n, err)
    if n < REPORT_AFTER_FAILURES:
        print(f"   {label} failed ({n} in a row, not reported yet): {err}")
        return []
    return [f"⚠️ {label} has failed {n} times in a row: {err}"]


def _failure_cleared(state: Dict, key: str, label: str) -> List[str]:
    """After a reported outage recovers, say so once."""
    fails = state.get("failures", {})
    n = fails.pop(key, 0)
    state["failures"] = fails
    return [f"✅ {label} is working again (it had failed {n} times in a row)."] \
        if n >= REPORT_AFTER_FAILURES else []


def run_once(send: bool = True, verify: bool = True) -> List[str]:
    DATA_DIR.mkdir(exist_ok=True)
    if _lock_held(LOCK_PATH):
        print("Another sync is still running — skipped.")
        return []
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
    # What this run read and sent, kept for the Supabase copy made at its very end (None while
    # publishing is off: then nothing is kept and nothing is built).
    cloud: Optional[Dict] = None
    try:
        from src.cloud import sheet_hooks
        if sheet_hooks.on():
            cloud = {"run_at": time.time(), "title": SYNC_TITLE, "sent": []}
    except Exception as e:
        logger.warning("Supabase publish failed (portal_sync): the publish layer could not load (%s)",
                       type(e).__name__)
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
        lines: List[str] = []
        try:
            lines += _with_retries(lambda: sync_sheets(state), "Progress-sheet update")
            lines += _failure_cleared(state, "sheets", "Progress-sheet update")
        except Exception as e:
            lines += _failure_line(state, "sheets", "Progress-sheet update", e)
            if cloud is not None:
                cloud["sheets_error"] = e
        finally:
            STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        try:
            lines += _with_retries(lambda: sync_docs(cloud), "Document download")
            lines += _failure_cleared(state, "docs", "Document download")
        except Exception as e:
            lines += _failure_line(state, "docs", "Document download", e)
            if cloud is not None:
                cloud["docs_error"] = e
        finally:
            STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        stamp = time.strftime("%Y-%m-%d %H:%M")
        print(f"[{stamp}] " + ("\n".join(lines) if lines else "no changes"))
        if cloud is not None:
            cloud["lines"] = list(lines)
        if lines and send:
            if notify(lines) and cloud is not None:
                cloud["sent"].append((SYNC_TITLE, list(lines), time.time()))

        # Verification is slow, so it runs after the sync summary has already gone out
        # and reports separately. A problem here must never fail the sync.
        if verify:
            try:
                vlines = verify_docs(cloud)
            except Exception as e:
                logger.warning("Document check could not run: %s", e)
                vlines = []
                if cloud is not None:
                    cloud["verify_error"] = e
            if vlines:
                print(chr(10).join(vlines))
                if send:
                    if notify(vlines, title=CHECK_TITLE) and cloud is not None:
                        cloud["sent"].append((CHECK_TITLE, list(vlines), time.time()))
                lines += vlines
        # Last of all, when the sheets, the documents and Telegram are done: hand what was read
        # to the Supabase publisher (its own process; this run never waits for it).
        if cloud is not None:
            cloud["export"] = pb._ALL_STUDENTS_CACHE
            sheet_hooks.after_sync(cloud)
        return lines
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s  %(message)s")
    ap = argparse.ArgumentParser(description="Sync portal changes into progress sheets and document folders.")
    ap.add_argument("--no-notify", action="store_true", help="don't send the Telegram summary")
    ap.add_argument("--no-verify", action="store_true", help="skip the document check")
    args = ap.parse_args()
    run_once(send=not args.no_notify, verify=not args.no_verify)


if __name__ == "__main__":
    main()
