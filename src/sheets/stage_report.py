"""
Stage report per program + intake (used by the Telegram /stage menu).

Reads the live portal (read-only students.php?export=csv, Direct students only — the
same students as the progress sheets) and groups one program + intake's students by
their current stage.

CLI (run from E:\\BOT):
  python -m src.sheets.stage_report --program KLP                      # list its intakes (JSON)
  python -m src.sheets.stage_report --program KLP --intake "MARCH 2027"  # stage report
  python -m src.sheets.stage_report --program KLP --intake NONE          # students with no intake
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from typing import Dict, List

from src.sheets import progress_builder as pb

# The portal's stage pipeline, in order (from the students.php stage filter).
STAGE_ORDER = [
    "Application Received", "Payment Verified", "Documents Under Review", "Documents Verified",
    "University Applied", "Admission & Tuition", "VIN Application", "Embassy Submission",
    "Visa Result", "Admitted / Completed", "Accepted",
]
NO_INTAKE = "NONE"


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


def stage_report(program_key: str, intake: str) -> str:
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
    for s in rows:
        by_stage.setdefault(s.get("Current Stage", "").strip() or "(no stage)", []).append(s)
    order = sorted(by_stage, key=lambda st: STAGE_ORDER.index(st) if st in STAGE_ORDER else 99)

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
    if args.intake:
        print(stage_report(key, args.intake.strip().upper()))
    else:
        print(json.dumps(intakes_for(key)))


if __name__ == "__main__":
    main()
