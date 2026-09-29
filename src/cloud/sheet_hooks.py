"""What the sheet jobs hand to Supabase once their own work is done.

The four subprocess jobs call one function here as their very last step, after Drive, Sheets,
the .xlsx files and Telegram:

  src.sheets.auto_sync (every 15 min)            after_sync             job portal_sync
  src.sheets.missing_report (09:05)              after_missing_daily    job missing_report
                                                 after_missing_failed   (the report could not be built)
  src.sheets.missing_report --program (/missing) after_missing_program  job missing_report
  src.sheets.stage_report --intake (/stage)      after_stage            job stage_report
  src.sheets.passport_issue --refresh (08:30)    after_issue_refresh    job issue_refresh

Each builds the records from what the job already read (src.cloud.records; nothing is read from
the portal again, nothing re-parsed but the edit pages' forms, by the client's own
_profile_fields) and hands them over with src.cloud.handoff.submit, which writes one file and
starts the publisher process without waiting for it. So the job never waits for Supabase and
never embeds: auto_sync has torch on the GPU after the document check, and a button report's
answer is its stdout, which the bot reads when the process exits (the publisher never holds that
pipe). The *_batches / missing_* functions are the pure builders, for tests.

hand_over() never raises, never prints (a button report's stdout is its reply) and does nothing
at all while publishing is off (handoff.enabled() False: nothing is even built). A failure is one
log line, "Supabase publish failed (<job>): ...", with no student data in it; the job's work and
its messages are exactly what they are without Supabase.

Completeness (R2, R5): a batch is complete only for a whole read. A read that failed sends no
batch and adds a plain reason to failed_reads (the hg_runs row is then "partial"); a complete batch
is never sent without rows (an empty list from a page whose layout changed must not empty a scope).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger("hangeul.cloud")

JOB_SYNC = "portal_sync"
JOB_MISSING = "missing_report"
JOB_STAGE = "stage_report"
JOB_ISSUE = "issue_refresh"

# Passports of the document check whose records Supabase never accepted (a publish that failed,
# or the checks made before publishing began), sent a few a run beside the ones just checked.
CATCH_UP_PASSPORTS = 6

Batches = List[Dict[str, Any]]
Built = Tuple[Batches, List[str]]


# --------------------------------------------------------------------------- the one call

def on() -> bool:
    """Whether publishing is on (so the jobs keep what they read for it); False on any doubt."""
    try:
        from src.cloud import handoff
        return bool(handoff.enabled())
    except Exception:
        return False


def hand_over(job: str, build: Callable[[], Built]) -> Optional[Path]:
    """Build a job's batches (build() -> (batches, failed_reads)) and hand them to the publisher
    process (handoff.submit); batches without rows are left out. -> the handoff file, or None
    (publishing off, nothing to send, or a failure: one log line). Never raises, never prints."""
    try:
        from src.cloud import handoff
        if not handoff.enabled():
            return None
        batches, failed = build()
        return handoff.submit(job, [b for b in batches if b and b.get("rows")], failed)
    except Exception as e:
        logger.warning("Supabase publish failed (%s): the records could not be built (%s)", job, type(e).__name__)
        return None


_URL_RE = re.compile(r"https?://\S+")


def reason(what: str, e: Optional[BaseException]) -> str:
    """A failed read as a short plain reason for hg_runs: the portal's own words for a portal
    failure, else only the error's type (an exception text can quote anything, a student's
    value included), never a URL."""
    if e is None:
        return f"{what}: not read"
    why = f"could not be read ({type(e).__name__})"
    try:
        import asyncio

        import httpx
        from src.scraper.client import PortalUnavailable, portal_error_reason
        if isinstance(e, (PortalUnavailable, asyncio.TimeoutError, httpx.TimeoutException, httpx.TransportError)):
            why = portal_error_reason(e)
    except Exception:
        pass
    return f"{what}: {_URL_RE.sub('<url>', why)[:200]}"


def _at(ts: Optional[float]) -> str:
    """An epoch time as the records' read_at (Asia/Dhaka, ISO); None is now."""
    from src.cloud import records
    if ts is None:
        return records.as_read_at(None)
    return records.as_read_at(datetime.fromtimestamp(ts, records.now().tzinfo))


def _today() -> str:
    from src.cloud import records
    return records.now().date().isoformat()


def line_sections(lines: Iterable[str]) -> List[Tuple[str, List[str]]]:
    """A summary's lines as sections: each line that starts at the margin opens one, the indented
    lines under it ("   • 1 new: ...") are its lines."""
    out: List[Tuple[str, List[str]]] = []
    for line in lines or []:
        for text in str(line).split("\n"):
            if not text.strip():
                continue
            if out and text[:1].isspace():
                out[-1][1].append(text.strip())
            else:
                out.append((text.strip(), []))
    return out


def _report(name: str, when: str, text: str, facts: Mapping[str, Any], source: str, read_at: str,
            sections: Sequence[Any]) -> Batches:
    """A report whole (its day's record, never complete: other days' reports stay) and its sections
    (complete: the report as built now is all of it)."""
    from src.cloud import records
    whole = records.report(name, when, text, facts, source, read_at)
    parts = records.report_sections(name, when, sections, source, read_at)
    return [records.batch("report", whole["scope"], [whole], False),
            records.batch("report_section", whole["key"], parts, True)]


def _notification(text: str, sent_at: Optional[float], source: str, title: str = "") -> Dict[str, Any]:
    from src.cloud import records
    rec = records.notification(text, _at(sent_at), source, title)
    return records.batch("notification", rec["scope"], [rec], False)


# --------------------------------------------------------------------------- auto_sync (portal_sync)

def store_readable(path: Path) -> bool:
    """Whether results.json can be read as it is now (a missing file is a fresh start, which is the
    truth; an unreadable one makes auto_verify start from an empty store, which is not)."""
    try:
        return isinstance(json.loads(Path(path).read_text(encoding="utf-8")), dict)
    except FileNotFoundError:
        return True
    except Exception:
        return False


def sync_batches(cloud: Mapping[str, Any]) -> Built:
    """One portal sync run (auto_sync.run_once) -> its batches and failed reads. `cloud` is what the
    run kept for it:
      run_at        epoch seconds, the run's start (the CSV export is its first read)
      export        progress_builder's CSV rows (None when the export was not read), sheets_error
      documents     verified_docs.run_local's list of every verified student (None when not
                    read), documents_at, docs_error
      title, lines  the sync summary as built (sent or not)
      sent          [(title, lines, epoch)] for each notice Telegram accepted
      verify        auto_verify.run's result (None when it did not run), verify_error, store_ok
    """
    from src.cloud import records
    run_at = _at(cloud.get("run_at"))
    out: Batches = []
    failed: List[str] = []

    rows = cloud.get("export")
    if rows:
        whole = {"Student ID", "Full Name"} <= set(rows[0])
        out.append(records.batch("student_export", "all", records.student_exports(rows, run_at), whole))
        if not whole:
            failed.append("students.php?export=csv: no Student ID and Full Name header")
    else:
        failed.append(reason("students.php?export=csv", cloud.get("sheets_error")) if rows is None
                      else "students.php?export=csv: no rows")

    docs = cloud.get("documents")
    if docs:
        out.append(records.batch("student_documents", "all",
                                 records.student_documents(docs, _at(cloud.get("documents_at"))), True))
    elif docs is None:
        failed.append(reason("students.php?source=direct&filter_docs=verified", cloud.get("docs_error")))
    else:
        failed.append("students.php?source=direct&filter_docs=verified: no student listed")

    lines = list(cloud.get("lines") or [])
    title = str(cloud.get("title") or "")
    if lines:
        text = f"{title}\n\n" + "\n".join(lines) if title else "\n".join(lines)
        out += _report("sync_summary", run_at, text, {"lines": lines}, "auto_sync", run_at, line_sections(lines))

    if cloud.get("verify") is not None:
        b, f = verify_batches(cloud["verify"], bool(cloud.get("store_ok", True)))
        out += b
        failed += f
    elif cloud.get("verify_error") is not None:
        failed.append(f"document check: could not run ({type(cloud['verify_error']).__name__})")

    for sent_title, sent_lines, at in cloud.get("sent") or []:
        out.append(_notification("\n".join(sent_lines), at, "auto_sync", sent_title))
    return out, failed


def _folder_files(folder: Optional[Path]) -> Dict[str, Tuple[int, int]]:
    """{file: (size, mtime)} of a student's document folder now (auto_verify's own file parts)."""
    out: Dict[str, Tuple[int, int]] = {}
    if folder is None or not Path(folder).is_dir():
        return out
    for f in Path(folder).iterdir():
        if f.is_file() and not f.name.startswith("."):
            st = f.stat()
            out[f.name] = (st.st_size, int(st.st_mtime))
    return out


def _page_texts(passport: str, name: str, folders: Mapping[str, Any], failed: List[str]) -> List[Dict[str, Any]]:
    """The doc_page_text records of one passport's OCR text cache (data/verification/text/<P>.json)."""
    from src.cloud import records
    from src.verify import auto_verify as av
    path = av.TEXT_DIR / f"{passport}.json"
    if not path.exists():
        return []
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            raise ValueError("not an object")
    except Exception as e:
        failed.append(f"an OCR text cache file: unreadable ({type(e).__name__})")
        return []
    folder = (folders.get(passport) or (None,))[0]
    read_at = _at(path.stat().st_mtime)
    return records.doc_page_texts(passport, cache, name, _folder_files(folder), read_at)


def verify_batches(result: Mapping[str, Any], store_ok: bool = True, folders: Optional[Mapping[str, Any]] = None) -> Built:
    """auto_verify.run's result -> the document check's batches: doc_verdict, field_check and
    doc_page_text of the passports it just checked (and a few that Supabase never accepted), each
    passport its own complete scope; then, from the whole store (results.json, the whole truth of
    the check), doc_check (complete), field_correction (append-only) and the DOCUMENT CHECK and
    FIELD CHECK reports. `store_ok` False (results.json was unreadable, so auto_verify started from
    an empty store): the store-wide kinds are not sent."""
    from src.cloud import records
    from src.sheets.passport_issue import passport_key
    store = result.get("store") or {}
    docs = {p: e for p, e in (store.get("documents") or {}).items() if isinstance(e, Mapping)}
    fields = {p: e for p, e in (store.get("fields") or {}).items() if isinstance(e, Mapping)}
    out: Batches = []
    failed: List[str] = []

    passports = list(dict.fromkeys(str(c.get("passport")) for c in result.get("checked") or []
                                   if isinstance(c, Mapping) and c.get("passport")))
    if store_ok:
        try:
            from src.cloud import publish
            known = publish.known_scopes("doc_verdict") | publish.known_scopes("field_check")
        except Exception:
            known = None
        if known is not None:
            never = [p for p in sorted(set(docs) | set(fields)) if p not in passports
                     and (passport_key(p) or p) not in known
                     and ((docs.get(p) or {}).get("rows") or (fields.get(p) or {}).get("rows"))]
            passports += never[:CATCH_UP_PASSPORTS]

    if passports and folders is None:
        try:
            from src.verify import doc_verifier as dv
            folders = dv.student_folders()
        except Exception:
            folders = {}
    verdicts, checks, texts = [], [], []
    for p in passports:
        if p in docs:
            verdicts += records.doc_verdicts(p, docs[p])
        if p in fields:
            checks += records.field_checks(p, fields[p])
        name = (docs.get(p) or fields.get(p) or {}).get("student") or ""
        texts += _page_texts(p, name, folders or {}, failed)
    # Each passport's details before the store-wide kinds: a run cut short never leaves doc_check
    # newer than the rows it counts.
    out += [records.batches("doc_verdict", verdicts, True), records.batches("field_check", checks, True),
            records.batches("doc_page_text", texts, True)]

    if not store_ok:
        failed.append("results.json: unreadable before the document check (it started from an empty store)")
        return out, failed
    if docs:
        out.append(records.batch("doc_check", "all", records.doc_checks(docs, fields), True))
    out.append(records.batch("field_correction", "all", records.field_corrections(store.get("corrections") or []), False))
    for maker in (records.document_check_report, records.field_check_report):
        whole, sections = maker(store)
        if whole is not None:
            out.append(records.batch("report", whole["scope"], [whole], False))
            out.append(records.batch("report_section", whole["key"], sections, True))
    return out, failed


# --------------------------------------------------------------------------- missing_report

_MISSING_COLUMNS = ("program", "intake", "student_id", "full_name", "mobile", "missing_count", "missing_fields")


def missing_daily(lines: Sequence[str], rows: Sequence[Sequence[Any]], sent_at: Optional[float]) -> Built:
    """The 09:05 report (build_report's lines as sent, and its rows: every student with the fields
    missing) -> report "missing_report|<day>", one section per incomplete student, and the
    notification when Telegram accepted it."""
    from src.cloud import records
    text = "\n".join(lines)
    whole, sections = records.missing_report(_today(), rows, text, records.as_read_at(None), "missing_report")
    out = [records.batch("report", whole["scope"], [whole], False),
           records.batch("report_section", whole["key"], sections, True)]
    if sent_at is not None:
        out.append(_notification(text, sent_at, "missing_report"))
    return out, []


def missing_failed(notice: str, sent_at: Optional[float], error: BaseException) -> Built:
    """The daily report could not be built: the failure notice as sent (a notification) and why."""
    out = [_notification(notice, sent_at, "missing_report")] if sent_at is not None else []
    return out, [reason("progress sheets or the portal", error)]


def missing_program(program_key: str, text: str, data: Mapping[str, Any],
                    index: Optional[Mapping[str, Any]]) -> Built:
    """The /missing button's list for one program (program_report's text as printed, from the
    sheets' rows `data` and the portal records `index` it was built from) -> report
    "missing_program:<KEY>|<day>" (with every student's missing fields in data, as
    build_report counts them) and a section per intake."""
    from src.cloud import records
    from src.sheets import missing_report as mr
    from src.sheets import progress_builder as pb
    read_at = records.as_read_at(None)
    mine = {sk: recs for sk, recs in (data or {}).items() if str(sk).split("|", 1)[0] == program_key}
    _, rows = mr.build_report(mine, dict(index or {}))
    rows = [r for r in rows if r[1] != "(no intake)" or pb.program_key_of({"Program": r[0]}) == program_key]
    items = [dict(zip(_MISSING_COLUMNS, [("" if v is None else v) for v in r])) for r in rows]
    return _report(f"missing_program:{program_key}", _today(), text, {"program": program_key, "rows": items},
                   "missing_report --program", read_at, records.split_sections(text)), []


# --------------------------------------------------------------------------- stage_report

def stage_batches(program_key: str, intake: str, text: str, reads: Mapping[str, Any]) -> Built:
    """One /stage report (the text as printed, and what stage_report read: the matched list records,
    the progress pages, the students by stage) -> student_progress of the pages read (never
    complete: one program and intake is not every student) and report
    "stage_report:<KEY>:<INTAKE>|<day>" with a section per stage."""
    from src.cloud import records
    read_at = records.as_read_at(None)
    pages = dict(reads.get("pages") or {})
    by_stage = dict(reads.get("by_stage") or {})
    listed = {str(s["uid"]): s for s in reads.get("matched") or [] if isinstance(s, Mapping) and s.get("uid")}
    out: Batches = []
    progress = records.student_progress(pages, listed, read_at)
    if progress:
        out.append(records.batch("student_progress", "all", progress, False))
    students = []
    for stage, pairs in by_stage.items():
        for row, s in pairs:
            item = {"student_id": row.get("Student ID", ""), "full_name": row.get("Full Name", ""), "stage": stage}
            uid = str(s.get("uid")) if isinstance(s, Mapping) and s.get("uid") else ""
            if uid:
                item["uid"] = uid
                page = pages.get(uid)
                if isinstance(page, Mapping) and "error" not in page:
                    item.update(progress_pct=page.get("pct"), progress_stage=page.get("stage"),
                                progress_status=page.get("status"))
                elif isinstance(page, Mapping):
                    item["progress_error"] = page.get("error")
            students.append(item)
    facts = {"program": program_key, "intake": intake, "counts": {st: len(p) for st, p in by_stage.items()},
             "students": students}
    out += _report(f"stage_report:{program_key}:{intake}", _today(), text, facts, "stage_report", read_at,
                   records.split_sections(text))
    return out, []


# --------------------------------------------------------------------------- passport_issue --refresh

def issue_batches(by_passport: Mapping[str, Any], pages: Optional[Mapping[str, Tuple[str, float]]],
                  complete: bool) -> Built:
    """The issue-date refresh -> passport_issue (the file it wrote: complete after a refresh of every
    student, i.e. with no --limit) and student_profile of every edit page it read
    (HangeulAdminClient._profile_fields, each uid its own complete scope)."""
    from src.cloud import records
    from src.scraper.client import HangeulAdminClient
    out: Batches = []
    issues = records.passport_issues(by_passport or {}, records.as_read_at(None))
    if issues:
        out.append(records.batch("passport_issue", "all", issues, bool(complete)))
    profiles = []
    for uid, (html, at) in (pages or {}).items():
        rec = records.student_profile(uid, HangeulAdminClient._profile_fields(html), _at(at))
        if rec is not None:
            profiles.append(rec)
    if profiles:
        out.append(records.batches("student_profile", profiles, True))
    return out, []


# --------------------------------------------------------------------------- what the jobs call

def after_sync(cloud: Mapping[str, Any]) -> Optional[Path]:
    """auto_sync.run_once, last of all."""
    return hand_over(JOB_SYNC, lambda: sync_batches(cloud))


def after_missing_daily(lines: Sequence[str], rows: Sequence[Sequence[Any]], sent_at: Optional[float]) -> Optional[Path]:
    """missing_report's daily run, after the text and the Excel file went to Telegram."""
    return hand_over(JOB_MISSING, lambda: missing_daily(lines, rows, sent_at))


def after_missing_failed(notice: str, sent_at: Optional[float], error: BaseException) -> Optional[Path]:
    """missing_report's daily run when the report could not be built, after the notice was sent."""
    return hand_over(JOB_MISSING, lambda: missing_failed(notice, sent_at, error))


def after_missing_program(program_key: str, text: str, data: Mapping[str, Any],
                          index: Optional[Mapping[str, Any]]) -> Optional[Path]:
    """missing_report --program, after the list was printed (the button's reply)."""
    return hand_over(JOB_MISSING, lambda: missing_program(program_key, text, data, index))


def after_stage(program_key: str, intake: str, text: str, reads: Mapping[str, Any]) -> Optional[Path]:
    """stage_report --program --intake, after the report was printed (the button's reply)."""
    return hand_over(JOB_STAGE, lambda: stage_batches(program_key, intake, text, reads))


def after_issue_refresh(by_passport: Mapping[str, Any], pages: Optional[Mapping[str, Tuple[str, float]]],
                        complete: bool) -> Optional[Path]:
    """passport_issue --refresh, after data/passport_issue.json was written."""
    return hand_over(JOB_ISSUE, lambda: issue_batches(by_passport, pages, complete))
