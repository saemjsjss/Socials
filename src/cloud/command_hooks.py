"""What the bot's command handlers publish to Supabase: the rows they already parsed, after the reply.

A handler that reads the portal keeps what each read returned in a plain dict while it works,

    reads = {}
    students = await admin_client.read_students()
    command_hooks.seen(reads, students=students)       # the read's result and the time it was read
    ...                                                 # the reply is built and sent exactly as before
    command_hooks.publish(reads)                        # after the reply: returns at once

and publish() hands it on without waiting: a background task (a strong reference is kept) builds the
records (src.cloud.records) in a worker thread and calls handoff.submit("command", batches,
failed_reads), which writes the handoff file and starts the publisher process without awaiting it
(src.cloud.handoff). So a reply is never delayed, changed or stopped by publishing: nothing here is
awaited by a handler, nothing raises into one, and a build that fails is one log line (its type
only: an exception text can quote student data). Nothing at all happens (no dict entries, no task,
no file) unless publishing is on (handoff.enabled()), and never in mock mode: the demo data is not
the portal's (R1).

What seen() keeps, and what it becomes (one handoff per command, job "command"):

  students       read_students() of every page, no filter (it raises unless the list was read
                 whole): student (scope all, complete) and verification per stamp day (complete
                 within records.verification_window(today) only when every stamp could be read;
                 else partial, and the failed read says why)
  page           read_students(all_pages=False), /students: student (scope all, partial)
  verified       (day, read_verified_students(day)): verification (scope day, complete). Only for a
                 day src.dates.yearless_day_problem allows (the handler asks it before reading)
  consultations  read_consultation_day(day): consultation (scope day, complete only when the portal
                 listed every request of the day) and consultation_day (scope all, never complete)
  totals         read_consultation_totals(): consultation_totals (complete)
  totals_error   why the totals could not be read (a failed read: no row)
  inquiries_report  the /inquiries report text as sent: report "inquiries_report|<day>" (partial:
                 one day's report never deletes another's) and its report_section rows (complete)
  facts          ask.dashboard_facts of index.php: dashboard_fact (complete only when every tile
                 group and card is on the page: records.dashboard_complete)
  dashboard      client.get_dashboard(): its tiles as dashboard_fact (partial: tiles only, no
                 cards); its "error" is a failed read
  pending        (every student parsed from every page of students.php?status=pending, the
                 badge): pending_payment (complete: the reader raises unless every page was read)
  calendar       ask.calendar_items of calendar.php (layout recognised): calendar_item (never
                 complete: the page shows only this month and the next 45 days)
  cards          cross-check cards audited by telegram_bot._audit_cards (audited() adds each
                 card's full audit result, the form compared, the time and the profile it read):
                 passport_audit (scope all, partial; audits that checked nothing are left out) and
                 student_profile (scope uid, complete) for each profile read during the audit

A failed read keeps nothing, so it never becomes rows=[] with complete=True (that would empty a
scope): the rule of src.cloud.records.batch.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

logger = logging.getLogger("hangeul.cloud")

JOB = "command"
STAMP_PROBLEM = "students.php: a verification stamp could not be read (layout not recognised)"

_tasks: Set["asyncio.Task[Any]"] = set()


def active() -> bool:
    """Whether a command's reads are published: publishing is on (SUPABASE_URL,
    SUPABASE_SECRET_KEY and CLOUD_PUBLISH_ENABLED) and the bot reads the live portal, not mock data."""
    try:
        from src.cloud import handoff
        if not handoff.enabled():
            return False
        from src.scraper.client import admin_client
        return getattr(admin_client, "mock_mode", True) is False
    except Exception:
        return False


def now() -> datetime:
    """Now in the business time zone (the read time kept with each read)."""
    from src.cloud.records import now as _now
    return _now()


def seen(reads: Optional[Dict[str, Any]], **values: Any) -> None:
    """Keep what reads returned in `reads`, with the time, for publish(). None values are not kept.
    Does nothing while publishing is off. Never raises."""
    try:
        if reads is None or not active():
            return
        values = {k: v for k, v in values.items() if v is not None}
        if not values:
            return
        at = now()
        reads.update(values)
        reads.setdefault("at", {}).update({k: at for k in values})
        if "today" not in reads:
            from src.dates import local_today
            reads["today"] = local_today()
    except Exception as e:
        logger.warning("Supabase publish failed (%s): a read could not be kept (%s)", JOB, type(e).__name__)


def profile_of(uid: Any) -> Optional[Dict[str, Any]]:
    """The student_edit.php profile the portal client holds for `uid` right now (the client keeps
    the last one it read, admin_client._profile_cache), or None. Never raises."""
    try:
        from src.scraper.client import admin_client
        cache = getattr(admin_client, "_profile_cache", None)
        found = cache.get(str(uid).strip()) if isinstance(cache, dict) else None
        return found if isinstance(found, dict) else None
    except Exception:
        return None


def audited(card: Dict[str, Any], result: Any, form: Dict[str, Any], before: Optional[Dict[str, Any]]) -> None:
    """After one card's audit (telegram_bot._audit_cards): keep the whole result, the form it was
    compared with, the time, and the profile the audit read (the one the client holds now, when it
    is another than `before`, the one it held before the audit: an audit whose profile read failed
    leaves the old one, which is not this read). Does nothing while publishing is off."""
    try:
        if not active() or not isinstance(result, Mapping):
            return
        after = profile_of(card.get("id"))
        card["audit"] = {"result": dict(result), "form": form, "at": now(),
                         "profile": after if after is not None and after is not before else None}
    except Exception as e:
        logger.warning("Supabase publish failed (%s): an audit could not be kept (%s)", JOB, type(e).__name__)


def publish(reads: Optional[Mapping[str, Any]], job: str = JOB) -> Optional["asyncio.Future[Any]"]:
    """Hand what `reads` holds to the publisher, without waiting: -> the background task (None when
    there is nothing to do). The reply must already be sent. Never raises."""
    try:
        if not reads or not active():
            return None
        return _background(_build_and_submit, dict(reads), job)
    except Exception as e:
        logger.warning("Supabase publish failed (%s): the handoff could not be started (%s)", job, type(e).__name__)
        return None


def _background(fn, *args) -> Optional["asyncio.Future[Any]"]:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:                               # no event loop: a thread of its own
        threading.Thread(target=fn, args=args, name="cloud-handoff", daemon=True).start()
        return None
    task = loop.create_task(asyncio.to_thread(fn, *args), name="cloud-handoff")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def drain(timeout: Optional[float] = None) -> None:
    """Wait for the handoffs this event loop started (tests, or a clean shutdown)."""
    loop = asyncio.get_running_loop()
    pending = [t for t in list(_tasks) if not t.done() and t.get_loop() is loop]
    if pending:
        await asyncio.wait(pending, timeout=timeout)


def _build_and_submit(reads: Dict[str, Any], job: str):
    try:
        batches, failed = build(reads)
    except Exception as e:
        logger.warning("Supabase publish failed (%s): the records could not be built (%s)", job, type(e).__name__)
        return None
    from src.cloud import handoff
    return handoff.submit(job, batches, failed)


# --------------------------------------------------------------------------- reads -> batches

def build(reads: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The batches (src.cloud.records.batch / batches) and failed reads of what a command read (see
    the module docstring). Batches with no rows that delete nothing are left out."""
    from src.cloud import records
    at: Mapping[str, Any] = reads.get("at") or {}
    today: Optional[date] = reads.get("today")
    out: List[Dict[str, Any]] = []
    failed: List[str] = []

    students = reads.get("students")
    if students is not None:
        batches, why = student_list(students, today, at.get("students"))
        out += batches
        failed += why
    if reads.get("page") is not None:
        out.append(records.batch("student", "all", records.students(reads["page"], at.get("page")), False))
    if reads.get("verified") is not None:
        day, verified = reads["verified"]
        out.append(verification_day(day, verified, today, at.get("verified")))
    if reads.get("consultations") is not None:
        out += consultation_batches(reads["consultations"], at.get("consultations"))
        if reads.get("inquiries_report"):
            out += inquiries_report(reads["consultations"], reads["inquiries_report"], reads.get("totals"),
                                    at.get("inquiries_report"))
    if reads.get("totals"):
        rec = records.consultation_totals(reads["totals"], at.get("totals"))
        if rec is not None:
            out.append(records.batch("consultation_totals", "all", [rec], True))
    if reads.get("totals_error"):
        failed.append(_failed("consult_requests.php?status=file_opened", reads["totals_error"]))
    if reads.get("facts") is not None:
        facts = list(reads["facts"])
        out.append(records.batch("dashboard_fact", "all", records.dashboard_facts(facts, at.get("facts")),
                                 records.dashboard_complete(facts)))
    if reads.get("dashboard") is not None:
        dash = reads["dashboard"]
        tiles = dash.get("tiles") if isinstance(dash, Mapping) else None
        if tiles:
            out.append(records.batch("dashboard_fact", "all",
                                     records.dashboard_facts(tile_facts(tiles), at.get("dashboard")), False))
        elif isinstance(dash, Mapping) and dash.get("error"):
            failed.append(_failed("index.php", dash["error"]))
    if reads.get("pending") is not None:
        rows, badge = reads["pending"]
        out.append(records.batch("pending_payment", "all", records.pending_payments(rows, badge, at.get("pending")),
                                 True))
    if reads.get("calendar") is not None:
        out.append(records.batch("calendar_item", "all", records.calendar_items(reads["calendar"], at.get("calendar")),
                                 False))
    if reads.get("cards") is not None:
        out += audit_batches(reads["cards"], students or [])
    return [b for b in out if b["rows"] or b["complete"]], failed


def _failed(page: str, why: Any) -> str:
    why = str(why or "not read").strip()
    return why if why.startswith(page) else f"{page}: {why}"


def stamps_readable(students: Sequence[Mapping[str, Any]]) -> bool:
    """Whether the list's verification stamps can be read (telegram_bot._stamp_guard's rule): a
    list with students has "Payment verified by" lines, and every line's date is readable."""
    from src.dates import parse_stamp
    lines = [s for s in students if s.get("verified_line")]
    return (not students or bool(lines)) and all(parse_stamp(s.get("verified_stamp") or "") for s in lines)


def student_list(students: Sequence[Mapping[str, Any]], today: Optional[date],
                 read_at: Any = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """A whole students.php list (read_students(), every page) -> the student batch (complete) and
    the verification batches per stamp day (complete within the last year when every stamp could
    be read), and the failed read when a stamp could not be."""
    from src.cloud import records
    out = [records.batch("student", "all", records.students(students, read_at), True)]
    ok = stamps_readable(students)
    if today is not None:
        out.append(records.batches("verification", records.verifications(students, today, read_at), ok,
                                   records.verification_window(today) if ok else None))
    return out, ([] if ok else [STAMP_PROBLEM])


def verification_day(day: date, verified: Sequence[Mapping[str, Any]], today: Optional[date],
                     read_at: Any = None) -> Dict[str, Any]:
    """read_verified_students(day)'s list -> the day's verification batch, complete (each uid once)
    when the yearless stamps can be dated on that day."""
    from src.cloud import records
    from src.dates import yearless_day_problem
    rows, keys = [], set()
    for v in verified or []:
        rec = records.verification(v, day, read_at)
        if rec is not None and rec["key"] not in keys:
            keys.add(rec["key"])
            rows.append(rec)
    complete = today is not None and yearless_day_problem(day, today) is None
    return records.batch("verification", day.isoformat(), rows, complete)


def consultation_batches(on_day: Mapping[str, Any], read_at: Any = None) -> List[Dict[str, Any]]:
    """read_consultation_day(day) -> the day's consultation batch (complete when every request of
    the day is listed) and its consultation_day counts (never complete: one day is not every day)."""
    from src.cloud import records
    iso = records.iso_day(on_day.get("day"))
    if not iso:
        return []
    rows, complete = records.consultations(on_day, read_at)
    out = [records.batch("consultation", iso, rows, complete)]
    counts = records.consultation_day(on_day, read_at)
    if counts is not None:
        out.append(records.batch("consultation_day", "all", [counts], False))
    return out


def inquiries_report(on_day: Mapping[str, Any], text: str, totals: Optional[Mapping[str, Any]],
                     read_at: Any = None) -> List[Dict[str, Any]]:
    """The /inquiries report as sent -> report "inquiries_report|<day>" (with the day's counts and
    the all-time totals in data) and one report_section per block of the text."""
    from src.cloud import records
    iso = records.iso_day(on_day.get("day"))
    if not iso or not str(text or "").strip():
        return []
    facts: Dict[str, Any] = {"day": iso, "counts": dict(on_day.get("counts") or {}),
                             "listed": len(on_day.get("rows") or []), "complete": bool(on_day.get("complete"))}
    if totals:
        facts["totals"] = dict(totals)
    source = "inquiries_report"
    whole = records.report("inquiries_report", iso, text, facts, source, read_at, iso)
    sections = records.report_sections("inquiries_report", iso, records.split_sections(text), source, read_at, iso)
    return [records.batch("report", "inquiries_report", [whole], False),
            records.batch("report_section", f"inquiries_report|{iso}", sections, True)]


def tile_facts(tiles: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """get_dashboard()'s tiles as the facts ask.dashboard_facts makes of them (group, label, value,
    text, note ""), so a tile has one record whichever read it came from."""
    return [{"group": t.get("group") or "Dashboard", "label": t["label"], "value": t.get("value"),
             "text": t.get("text") or "", "note": ""}
            for t in tiles or [] if isinstance(t, Mapping) and t.get("label")]


def audit_batches(cards: Sequence[Mapping[str, Any]], students: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Audited cross-check cards -> passport_audit (scope all, partial: one check never covers every
    scan) and one student_profile per profile the audits read (its own scope, complete)."""
    from src.cloud import records
    by_uid = {str(s.get("uid")): s for s in students if s.get("uid")}
    audits, profiles, seen_uids = [], [], set()
    for c in cards or []:
        a = c.get("audit") if isinstance(c, Mapping) else None
        if not a or not c.get("passport_file"):
            continue
        uid = str(c.get("id") or "")
        rec = records.passport_audit(uid, c["passport_file"], a.get("result") or {}, a.get("at"),
                                     student=by_uid.get(uid), form=a.get("form"))
        if rec is not None and all(r["key"] != rec["key"] for r in audits):    # one audit a scan
            audits.append(rec)
        profile = a.get("profile")
        if isinstance(profile, Mapping) and "_csrf" not in profile and uid not in seen_uids:
            p = records.student_profile(uid, profile, a.get("at"))    # never the legacy full-page read
            if p is not None:
                seen_uids.add(uid)
                profiles.append(records.batch("student_profile", p["scope"], [p], True))
    out = [records.batch("passport_audit", "all", audits, False)] if audits else []
    return out + profiles
