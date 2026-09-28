"""
Stage report per program + intake (used by the Telegram /stage menu).

Reads the live portal, read-only: the students (Direct only, the same students as the progress
sheets), their program, intake, status and progress % come from students.php?export=csv; each
student's stage comes from the student list itself, the "Stage · Applied" column of every
students.php page (the stage the portal stores, the same as the row's own stage select). The
CSV's "Current Stage" is not used: it disagrees with the stored stage for some students (both
pending-payment applicants show "Payment Verified" there, Sep 2026).

CLI (run from the BOT folder):
  python -m src.sheets.stage_report --program KLP                      # list its intakes (JSON)
  python -m src.sheets.stage_report --program KLP --intake "MARCH 2027"  # stage report
  python -m src.sheets.stage_report --program KLP --intake NONE          # students with no intake
A portal that cannot be read gives {"error": why} (intake list) or a "Couldn't read the portal"
line (report), never an empty list or a stage made up.
"""
from __future__ import annotations

import argparse
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


def attach_stages(rows: List[Dict[str, str]], listed: List[Dict[str, Any]]) -> List[Tuple[Dict[str, str], Optional[str]]]:
    """Each CSV row with its stage from the student list: matched by Student ID, else (a student
    without an ID yet) by name, with the mobile number to tell apart two students of one name.
    A row the list does not have gets None (reported as not found, never guessed)."""
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
        stage = None if s is None else ((s.get("status") or "").strip() or "(no stage)")
        out.append((r, stage))
    return out


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


def stage_report(program_key: str, intake: str, listed: Optional[List[Dict[str, Any]]] = None) -> str:
    """The stage report of one program + intake. `listed` is the student list (students.php, every
    page); read live when not given. Raises PortalUnavailable when it cannot be read."""
    cfg = pb.PROGRAMS[program_key]
    want = "" if intake == NO_INTAKE else pb.normalize_intake(intake)
    rows = [s for s in program_students(program_key) if pb.normalize_intake(s.get("Intake", "")) == want]
    label = "NO INTAKE SET" if intake == NO_INTAKE else want
    out = [f"📊 Stages — {cfg['name']} {label}",
           f"(live from the portal, {time.strftime('%d %b %Y %H:%M')}) — {len(rows)} students"]
    if not rows:
        out.append("\nNo students.")
        return "\n".join(out)

    by_stage: Dict[str, List[Dict[str, str]]] = {}
    for s, stage in attach_stages(rows, read_listed_students() if listed is None else listed):
        by_stage.setdefault(stage or NOT_FOUND, []).append(s)
    order = sorted(by_stage, key=lambda st: STAGE_ORDER.index(st) if st in STAGE_ORDER else
                   (100 if st == NOT_FOUND else 99))

    out.append("")
    for st in order:
        out.append(f"• {st}: {len(by_stage[st])}")
    for st in order:
        out.append(f"\n🔹 {st} ({len(by_stage[st])})")
        for s in sorted(by_stage[st], key=lambda x: x.get("Student ID", "")):
            status = s.get("Current Status", "").strip()
            pct = s.get("Progress %", "").strip()
            extra = " — ".join(x for x in (status, f"{pct}%" if pct else "") if x)
            out.append(f"   {s.get('Student ID') or '(no ID)'} {s.get('Full Name', '')}"
                       + (f" — {extra}" if extra else ""))
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
