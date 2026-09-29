"""The Supabase copy of what the bot's own scheduled jobs read and send (src/bot/scheduler.py).

  the 18:05 brief       after it was sent: the brief itself (report "brief|<day>", one
                        report_section per section, one brief_fact per fact) and what its portal
                        reads returned (brief.Brief.reads): the day's consultation requests and their
                        tab counts, the payments verified that day, the all-time consultation counts
                        and the dashboard's tiles
  the passport watcher  after it saved its memory: the whole student list it read (student,
                        complete: read_students() reads every page and checks the pager), this run's
                        passport audits (passport_audit: the audits of every scan the list still
                        shows are kept, those of scans it no longer shows are deleted) and its memory
                        (passport_alert: the alerts about the scans the list still shows are kept,
                        so a memory that was lost and is being rebuilt never deletes one)
  the full picture      once an hour, in its own process: src/cloud/full_picture.py

The bot process only builds the records and hands them over (hand_over): in a worker thread, so
its event loop stays free, through src.cloud.handoff.submit, which writes one file and starts the
publisher process without waiting for it (the embedding and the upload happen there, never in the
bot, which loads torch for the passport OCR). It runs after the job's own work is done, never raises, and
gives up waiting after HANDOFF_WAIT seconds, so nothing here can change what a job does or sends.
Nothing at all happens while publishing is off, or while the bot is in mock mode (demo figures).

What the brief reads but does not publish (the hourly full picture publishes them from whole reads):
  pending payments      read_pending_payments reads the first page only: no pending_payment rows
  window applications   read_window_apps_under_review keeps only the count
  calendar items        get_calendar_events returns the parsed reminders and timeline, not the page,
                        so ask.calendar_items (which also reads the page's event list: the full
                        dates, notes and done flags, and the month's other events) cannot run on it
Their figures (and the local document-check counts) go into the brief report's data instead.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.cloud import handoff, records

logger = logging.getLogger("hangeul.cloud")

Batches = List[Dict[str, Any]]
HANDOFF_WAIT = 30.0          # seconds a job waits for its records to be built and handed over

# The brief's reads (brief._PortalReads names) and the page each one is.
BRIEF_READS = (("consultations", "consult_requests.php?status=all (the day)"),
               ("verified students", "students.php"),
               ("consultation totals", "consult_requests.php?status=file_opened"),
               ("pending payments", "students.php?status=pending"),
               ("window applications", "window_applications.php?status=under_review"),
               ("dashboard", "index.php"),
               ("calendar", "calendar.php"))


def now():
    """The time now in the business time zone: a read time for the records."""
    return records.now()


def _mock() -> bool:
    from src.scraper.client import admin_client
    return bool(getattr(admin_client, "mock_mode", False))


async def hand_over(job: str, build: Callable[..., Tuple[Batches, List[str]]], *args: Any) -> Optional[Path]:
    """Build a job's batches (build(*args) -> (batches, failed reads)) in a worker thread and hand
    them to the publisher process (handoff.submit). -> the handoff file, or None: publishing is
    off, the bot is in mock mode, nothing to send, or a failure (one log line). Never raises; waits
    at most HANDOFF_WAIT seconds (the thread then finishes on its own)."""
    try:
        if not handoff.enabled():
            return None
        if _mock():
            logger.info("Supabase publish skipped (%s): the bot is in mock mode (demo figures).", job)
            return None

        def work() -> Optional[Path]:
            batches, failed = build(*args)
            return handoff.submit(job, batches, failed)

        return await asyncio.wait_for(asyncio.to_thread(work), timeout=HANDOFF_WAIT)
    except asyncio.TimeoutError:
        logger.warning("Supabase publish failed (%s): the handoff took over %g s (the job itself was done)",
                       job, HANDOFF_WAIT)
    except Exception as e:
        logger.warning("Supabase publish failed (%s): its records could not be built (%s)", job, type(e).__name__)
    return None


def _reason(e: BaseException) -> str:
    """A failed read as a short reason with no data in it: the portal reader's own words for a
    portal failure, else the exception's type only."""
    import httpx
    from src.scraper.client import PortalUnavailable, portal_error_reason
    if isinstance(e, (PortalUnavailable, asyncio.TimeoutError, httpx.HTTPError)):
        return portal_error_reason(e)
    return f"not read ({type(e).__name__})"


# --------------------------------------------------------------------------- the 18:05 brief

def brief_failures(reads: Optional[Mapping[str, Any]]) -> List[str]:
    """The brief's reads that failed or were skipped, as "<page>: <why>" (no student data)."""
    if not reads:
        return []
    why, errors = reads.get("why") or {}, reads.get("errors") or {}
    out = []
    for what, page in BRIEF_READS:
        if what in why:
            out.append(f"{page}: {why[what]}")
        elif what in errors:
            out.append(f"{page}: {_reason(errors[what])}")
        elif what == "pending payments" and reads.get(what) is None:
            out.append(f"{page}: the pending count could not be read")
        elif what == "window applications" and reads.get(what) is None:
            out.append(f"{page}: no table with a Status column (layout not recognised)")
        elif what == "dashboard" and isinstance(reads.get(what), Mapping) and "error" in reads[what]:
            out.append(f"{page}: {reads[what]['error']}")
        elif what == "calendar" and reads.get("is_today") and isinstance(reads.get(what), Mapping):
            cal = reads[what]
            if "error" in cal:
                out.append(f"{page}: {cal['error'] or 'not read'}")
            elif not cal.get("layout_ok"):
                out.append(f"{page}: layout not recognised")
    return out


def _brief_figures(facts: Sequence[str], reads: Mapping[str, Any], failed: Sequence[str]) -> Dict[str, Any]:
    """The brief report's data: its facts (one figure a line, what the summary was checked
    against) and the figures it read that are no kind of their own here."""
    out: Dict[str, Any] = {"lines": list(facts)}
    if not reads:
        return out
    out["pending_payments"] = reads.get("pending payments")          # {"count", "listed", "badge"}
    out["window_apps_under_review"] = reads.get("window applications")
    cal = reads.get("calendar")
    if reads.get("is_today") and isinstance(cal, Mapping) and "error" not in cal and cal.get("layout_ok"):
        out["calendar_today"] = list(cal.get("today_reminders") or [])
    if reads.get("documents") is not None:
        out["document_check"] = reads.get("documents")             # the local results, not live
    if failed:
        out["not_read"] = list(failed)
    return out


def brief_reads(reads: Optional[Mapping[str, Any]], read_at: Any) -> Batches:
    """The brief's portal reads as batches: each only when its read succeeded, complete only when
    that read was whole (never from a read that failed)."""
    out: Batches = []
    if not reads or reads.get("mock") or not isinstance(reads.get("day"), date):
        return out
    day, today = reads["day"], reads.get("today")
    iso = day.isoformat()
    on_day = reads.get("consultations")
    if isinstance(on_day, Mapping) and on_day.get("counts"):
        rows, complete = records.consultations(on_day, read_at)
        out.append(records.batch("consultation", iso, rows, complete))
        rec = records.consultation_day(on_day, read_at)
        if rec is not None:
            out.append(records.batch("consultation_day", "all", [rec], False))
    verified = reads.get("verified")
    if isinstance(verified, list) and isinstance(today, date) and day <= today:
        from src.dates import yearless_day_problem
        if yearless_day_problem(day, today) is None:
            rows = [records.verification(v, day, read_at) for v in verified]
            # Every page was read and the stamp guard held (read_verified_students raises
            # otherwise): the day's list is whole, [] included.
            out.append(records.batch("verification", iso, [r for r in rows if r], all(rows)))
    totals = reads.get("consultation totals")
    if isinstance(totals, Mapping) and totals:
        rec = records.consultation_totals(totals, read_at)
        if rec is not None:
            out.append(records.batch("consultation_totals", "all", [rec], True))
    dash = reads.get("dashboard")
    if isinstance(dash, Mapping) and "error" not in dash and dash.get("tiles"):
        # The tiles as ask.dashboard_facts makes them (records.tile_facts, shared with /stats), so a
        # tile is the same record whichever job read it. Tiles only (no cards): never complete.
        out.append(records.batch("dashboard_fact", "all",
                                 records.dashboard_facts(records.tile_facts(dash["tiles"]), read_at), False))
    return out


def brief_batches(composed: Any) -> Tuple[Batches, List[str]]:
    """The 18:05 brief (brief.Brief, as sent) -> (its batches, the reads that failed)."""
    from src import dates
    reads = getattr(composed, "reads", None) or {}
    day = reads.get("day") if isinstance(reads.get("day"), date) else dates.local_today()
    iso = day.isoformat()
    read_at = records.as_read_at(reads.get("at"))
    text, facts = composed.text, list(composed.facts or [])
    failed = brief_failures(reads)
    whole = records.report("brief", iso, text, _brief_figures(facts, reads, failed), "brief", read_at, iso)
    sections = records.report_sections("brief", iso, records.split_sections(text), "brief", read_at, iso)
    out = [records.batch("report", "brief", [whole], False),
           records.batch("report_section", f"brief|{iso}", sections, True),
           records.batch("brief_fact", iso, records.brief_facts(iso, facts, read_at), True)]
    return out + brief_reads(reads, read_at), failed


# --------------------------------------------------------------------------- the passport watcher

def profile_now(uid: Any) -> Optional[Dict[str, Any]]:
    """The student_edit.php profile the portal client holds for `uid` now (the one its last audit
    read: src.cloud.command_hooks.profile_of), or None; None too while publishing is off, so
    nothing is kept then. Never raises."""
    try:
        if not handoff.enabled():
            return None
        from src.cloud.command_hooks import profile_of
        return profile_of(uid)
    except Exception:
        return None


def keep_profile(profiles: List[Tuple[Any, Dict[str, Any], Any]], uid: Any,
                 before: Optional[Dict[str, Any]]) -> None:
    """After one watcher audit: keep (uid, profile, time) of the profile that audit read, i.e. the
    one the client holds now when it is another than `before` (an audit whose profile read failed
    leaves the old one, which is not this read). Never raises."""
    try:
        after = profile_now(uid)
        if after is not None and after is not before:
            profiles.append((uid, after, now()))
    except Exception:
        pass


def note_sent(accepted: Optional[List[Tuple[str, Any]]], text: str) -> None:
    """Keep (text, time) of an alert message Telegram accepted, for its notification record.
    Does nothing without a list or while publishing is off. Never raises."""
    try:
        if accepted is not None and handoff.enabled():
            accepted.append((text, now()))
    except Exception:
        pass


def listed_scans(students: Iterable[Mapping[str, Any]]) -> List[str]:
    """Every passport scan the student list shows now, as "uid|file" (the watcher audits each
    student's newest; an older scan still listed keeps its audit, e.g. from a cross-check)."""
    return sorted({f"{str(s.get('uid')).strip()}|{f}" for s in students if str(s.get("uid") or "").strip()
                   for f in s.get("files") or [] if str(f).startswith("passport_")})


# scheduler.passport_scan's rule (the upload time in the file name orders a student's scans), kept
# here so the backfill need not import the scheduler; a test pins the two together.
_UPLOAD_TIME_RE = re.compile(r"passport_\d+_(\d{9,11})\b")


def _upload_time(file_name: str) -> int:
    m = _UPLOAD_TIME_RE.search(file_name or "")
    return int(m.group(1)) if m else 0


def watched_scans(students: Iterable[Mapping[str, Any]]) -> List[str]:
    """The scans the watcher's memory is about, as "uid|file": each listed student's newest
    passport scan (scheduler.passport_scan), the only keys the memory keeps. An alert about any
    other scan is one the watcher has forgotten (the scan was replaced, or the student is gone)."""
    out = set()
    for s in students:
        uid = str(s.get("uid") or "").strip()
        scans = [f for f in s.get("files") or [] if str(f).startswith("passport_")]
        if uid and scans:
            out.add(f"{uid}|{max(scans, key=_upload_time)}")
    return sorted(out)


def watcher_batches(students: Sequence[Mapping[str, Any]], read_at: Any,
                    audits: Sequence[Tuple[Mapping[str, Any], str, Mapping[str, Any], Mapping[str, Any], Any]],
                    memory: Mapping[str, Any], unchecked: int = 0,
                    sent: Sequence[Tuple[str, Any]] = (),
                    profiles: Sequence[Tuple[Any, Mapping[str, Any], Any]] = ()) -> Tuple[Batches, List[str]]:
    """One watcher run -> (its batches, the reads that failed). `students` is its whole list
    (read_students: every page), `audits` this run's (student, scan, form, result, when) of the
    scans it checked and remembered, `memory` the watcher's memory as saved, `unchecked` how many
    scans could not be checked (tried again next run), `sent` the (text, time) of each alert
    message Telegram accepted (notification, as sent) and `profiles` the (uid, profile, time) of
    each student_edit.php profile the audits read (student_profile, its uid its own complete scope;
    never the legacy full-page read, which carries the form's _csrf).

    The alerts are complete over the scans the list shows (watched_scans): an alert is deleted
    only once the portal no longer lists its scan, never because the memory lacks it. A memory the
    watcher could not read restarts empty and is rebuilt over several runs (its budget is 20
    minutes); until a scan is audited again, the alert Supabase holds about it (its text, sent,
    sent_at) is the only copy left, and it stays. Every batch is dated by the list read (`read_at`),
    which the watcher hands over only after its audits."""
    rows = [records.passport_audit(s.get("uid"), scan, result, at, student=s, form=form)
            for s, scan, form, result, at in audits]
    out = [records.batch("student", "all", records.students(students, read_at), True, read_at=read_at),
           records.batch("passport_audit", "all", [r for r in rows if r], True, all_keys=listed_scans(students),
                         read_at=read_at),
           records.batch("passport_alert", "all", records.passport_alerts(memory), True,
                         all_keys=watched_scans(students), read_at=read_at)]
    latest: Dict[str, Any] = {}
    for uid, profile, at in profiles or ():
        if isinstance(profile, Mapping) and "_csrf" not in profile:
            rec = records.student_profile(uid, profile, at)
            if rec is not None:
                latest[rec["scope"]] = rec                       # the last read of a uid wins
    out += [records.batch("student_profile", scope, [rec], True) for scope, rec in latest.items()]
    for text, at in sent or ():
        if str(text or "").strip():
            rec = records.notification(text, at, "passport_watcher")
            out.append(records.batch("notification", rec["scope"], [rec], False))
    failed = ([f"student_edit.php / view_doc.php: {unchecked} passport scan(s) could not be checked "
               "(tried again next run)"] if unchecked else [])
    return out, failed
