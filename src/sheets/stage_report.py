"""
Stage report per program + intake (used by the Telegram /stage menu).

Reads the live portal, read-only: the students (Direct only, the same students as the progress
sheets), their program and intake come from students.php?export=csv; each student's stage comes
from the student list itself, the "Stage · Applied" column of every students.php page (the stage
the portal stores, the same as the row's own stage select); each student's status and progress %
come from their own progress page, progress.php?uid=N (its ring and "Current stage" block), read
just now. The CSV's "Current Stage", "Current Status" and "Progress %" are not used: they are
stale for many students (Sep 2026: 64 of 329 statuses and 89 of 329 % disagreed with the
progress pages, and both pending-payment applicants showed "Payment Verified" as their stage).

CLI (run from the BOT folder):
  python -m src.sheets.stage_report --program KLP                      # list its intakes (JSON)
  python -m src.sheets.stage_report --program KLP --intake "MARCH 2027"  # stage report
  python -m src.sheets.stage_report --program KLP --intake NONE          # students with no intake
A portal that cannot be read gives {"error": why} (intake list) or a "Couldn't read the portal"
line (report), never an empty list or a stage made up.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from src.sheets import progress_builder as pb

# The portal's stage pipeline, in order (from the students.php stage filter).
STAGE_ORDER = [
    "Application Received", "Payment Verified", "Documents Under Review", "Documents Verified",
    "University Applied", "Admission & Tuition", "VIN Application", "Embassy Submission",
    "Visa Result", "Admitted / Completed", "Accepted",
]
NO_INTAKE = "NONE"
NOT_FOUND = "⚠️ Stage not found on the student list"


def read_listed_students() -> List[Dict[str, Any]]:
    """Every student on every students.php page (parse_students_page records: "status" is the
    stage), read with a portal session of its own. Raises PortalUnavailable when the list cannot be
    read whole."""
    from src.scraper.client import HangeulAdminClient

    async def read():
        client = HangeulAdminClient()
        try:
            return await client.read_students()
        finally:
            await client.close()
    return pb._run_async(read())


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _digits(text: str) -> str:
    return re.sub(r"\D", "", str(text or ""))[-10:]


PROGRESS_READERS = 4          # progress pages read at a time (read-only GETs)


def read_progress(uids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Each student's own progress page, progress.php?uid=N (read-only GETs, with a portal session
    of its own, PROGRESS_READERS at a time) -> {uid: {"pct", "stage", "status"}
    (parsers.parse_progress_page) or {"error": why it could not be read}}. Once the portal stops
    answering (a timeout, a refused connection, a failed login), the pages left are not asked for:
    they get the same reason."""
    from src.scraper.client import HangeulAdminClient, PortalUnavailable, portal_error_reason
    from src.scraper.parsers import StudentListLayoutError, parse_progress_page

    async def read():
        client = HangeulAdminClient()
        out: Dict[str, Dict[str, Any]] = {}
        gone: List[str] = []                 # why the portal stopped answering, once it has
        gate = asyncio.Semaphore(PROGRESS_READERS)

        async def one(uid: str) -> None:
            async with gate:
                if gone:
                    out[uid] = {"error": gone[0]}
                    return
                try:
                    html = await client.fetch_html("progress.php", timeout=30.0, params={"uid": uid})
                    out[uid] = await asyncio.to_thread(parse_progress_page, html)
                except StudentListLayoutError as e:
                    out[uid] = {"error": str(e)}
                except Exception as e:
                    out[uid] = {"error": portal_error_reason(e)}
                    if isinstance(e, PortalUnavailable) and (e.unreachable or "log in" in e.reason):
                        gone.append(e.reason)

        try:
            if uids:
                await one(uids[0])           # the login, once, before the rest go side by side
                await asyncio.gather(*(one(u) for u in uids[1:]))
            return out
        finally:
            await client.close()
    return pb._run_async(read())


def match_listed(rows: List[Dict[str, str]], listed: List[Dict[str, Any]]) -> List[Optional[Dict[str, Any]]]:
    """Each CSV row's student on the student list: matched by Student ID, else (a student without
    an ID yet) by name, with the mobile number to tell apart two students of one name. None for a
    row the list does not have (reported as not found, never guessed)."""
    by_id = {s["student_id"].upper(): s for s in listed if s.get("student_id")}
    claimed = {pb.clean_value(r.get("Student ID", "")).upper() for r in rows} & set(by_id)
    out = []
    for r in rows:
        sid = pb.clean_value(r.get("Student ID", "")).upper()
        s = by_id.get(sid) if sid else None
        if s is None:
            name = _norm(r.get("Full Name", ""))
            same = [x for x in listed if name and _norm(x.get("student_name", "")) == name
                    and (x.get("student_id") or "").upper() not in claimed]
            if len(same) > 1:
                mobile = _digits(r.get("Mobile", ""))
                same = [x for x in same if mobile and _digits((x.get("details") or {}).get("Mobile", "")) == mobile]
            s = same[0] if len(same) == 1 else None
        out.append(s)
    return out


def _stage_of(s: Optional[Dict[str, Any]]) -> Optional[str]:
    return None if s is None else ((s.get("status") or "").strip() or "(no stage)")


def attach_stages(rows: List[Dict[str, str]], listed: List[Dict[str, Any]]) -> List[Tuple[Dict[str, str], Optional[str]]]:
    """Each CSV row with its stage from the student list (match_listed); None for a row the list
    does not have."""
    return [(r, _stage_of(s)) for r, s in zip(rows, match_listed(rows, listed))]


def program_students(program_key: str) -> List[Dict[str, str]]:
    return [s for s in pb.direct_students() if pb.program_key_of(s) == program_key]


def intakes_for(program_key: str) -> List[Dict[str, object]]:
    """[{"intake": "MARCH 2027", "count": 46}, ...] plus a NONE entry for blank intakes."""
    c = Counter(pb.normalize_intake(s.get("Intake", "")) or NO_INTAKE for s in program_students(program_key))
    named = sorted((i for i in c if i != NO_INTAKE), key=_intake_sort_key)
    out = [{"intake": i, "count": c[i]} for i in named]
    if c.get(NO_INTAKE):
        out.append({"intake": NO_INTAKE, "count": c[NO_INTAKE]})
    return out


def _intake_sort_key(intake: str):
    months = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
              "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]
    parts = intake.split()
    try:
        return (int(parts[-1]), months.index(parts[0]))
    except (ValueError, IndexError):
        return (9999, 99)


def _progress_words(page: Optional[Dict[str, Any]], stage: str) -> str:
    """A student's line's status and % from their progress page: "Verified — 22%"; the page's own
    stage first when it is not the stage the list stores ("progress page: Documents Under Review ·
    Submitted — 33%"); "progress page not read" when it could not be read."""
    if page is None:
        return ""
    if "error" in page:
        return "progress page not read"
    status = page.get("status") or ""
    if _norm(page.get("stage")) != _norm(stage):
        status = "progress page: " + " · ".join(x for x in (page.get("stage"), status) if x)
    return " — ".join(x for x in (status, f"{page['pct']}%") if x)


def stage_report(program_key: str, intake: str, listed: Optional[List[Dict[str, Any]]] = None,
                 progress: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    """The stage report of one program + intake. `listed` is the student list (students.php, every
    page) and `progress` each listed student's progress page by uid (read_progress); each is read
    live when not given. Raises PortalUnavailable when the student list cannot be read; a progress
    page that cannot be read leaves its line without a status (and the report says how many)."""
    cfg = pb.PROGRAMS[program_key]
    want = "" if intake == NO_INTAKE else pb.normalize_intake(intake)
    rows = [s for s in program_students(program_key) if pb.normalize_intake(s.get("Intake", "")) == want]
    label = "NO INTAKE SET" if intake == NO_INTAKE else want
    out = [f"📊 Stages — {cfg['name']} {label}",
           f"(live from the portal, {time.strftime('%d %b %Y %H:%M')}) — {len(rows)} students"]
    if not rows:
        out.append("\nNo students.")
        return "\n".join(out)

    matched = match_listed(rows, read_listed_students() if listed is None else listed)
    uids = list(dict.fromkeys(s["uid"] for s in matched if s is not None and s.get("uid")))
    pages = read_progress(uids) if progress is None else progress
    by_stage: Dict[str, List[Tuple[Dict[str, str], Optional[Dict[str, Any]]]]] = {}
    for r, s in zip(rows, matched):
        by_stage.setdefault(_stage_of(s) or NOT_FOUND, []).append((r, s))
    order = sorted(by_stage, key=lambda st: STAGE_ORDER.index(st) if st in STAGE_ORDER else
                   (100 if st == NOT_FOUND else 99))

    out.append("")
    for st in order:
        out.append(f"• {st}: {len(by_stage[st])}")
    for st in order:
        out.append(f"\n🔹 {st} ({len(by_stage[st])})")
        for r, s in sorted(by_stage[st], key=lambda x: x[0].get("Student ID", "")):
            page = pages.get(s["uid"]) if s is not None and s.get("uid") else None
            if page is None and s is not None and s.get("uid"):
                page = {"error": "not read"}
            extra = _progress_words(page, st)
            out.append(f"   {r.get('Student ID') or '(no ID)'} {r.get('Full Name', '')}"
                       + (f" — {extra}" if extra else ""))
    unread = [pages.get(u) or {"error": "not read"} for u in uids]
    unread = [p["error"] for p in unread if "error" in p]
    if unread:
        why = Counter(unread).most_common(1)[0][0]
        out.append(f"\n⚠️ {len(unread)} of the {len(uids)} progress pages could not be read ({why}): "
                   "those lines show no status or %.")
    if len(unread) < len(uids):
        out.append("\nStatus and % from each student's own progress page (progress.php), read just now.")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage report for one program + intake.")
    ap.add_argument("--program", required=True, help="KLP | EAP | BACHELOR | MASTER")
    ap.add_argument("--intake", help='e.g. "MARCH 2027", or NONE; leave out to list intakes')
    args = ap.parse_args()
    key = args.program.strip().upper()
    if key not in pb.PROGRAMS:
        raise SystemExit(f"Unknown program {key!r}. Choose one of: {', '.join(pb.PROGRAMS)}")
    from src.scraper.client import portal_error_reason
    if args.intake:
        intake = args.intake.strip().upper()
        try:
            print(stage_report(key, intake))
        except Exception as e:
            label = "(no intake set)" if intake == NO_INTAKE else pb.normalize_intake(intake)
            print(f"❌ Couldn't read the portal: {portal_error_reason(e)}.\n"
                  f"Stages for {pb.PROGRAMS[key]['name']} {label}: not available right now. "
                  "Please try again in a minute.")
    else:
        try:
            print(json.dumps(intakes_for(key)))
        except Exception as e:
            print(json.dumps({"error": portal_error_reason(e)}))


if __name__ == "__main__":
    main()
