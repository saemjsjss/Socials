"""
Office attendance, read from the Google Sheet the office PC updates
("Attendance — Live (auto-updated from office PC)").

Used by the 09:05 daily report: who arrived, at what time, and who was late.

CLI (run from the BOT folder):
  python -m src.sheets.attendance          # today's attendance as it will be reported
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Dict, List, Optional, Tuple

from src.sheets import progress_builder as pb

logger = logging.getLogger(__name__)

SHEET_ID = "1IoQjAd87ggii9JBofHSzR61MLN6BBUVPfhwLvg3v0vY"
TODAY_TAB = "Today"
OFFICE_START = dt.time(9, 0)      # anything after this counts as late
GRACE_MINUTES = 0                 # set e.g. 10 to allow 09:10 without being "late"


def _parse_time(v: str) -> Optional[dt.time]:
    m = re.match(r"\s*(\d{1,2})[:.](\d{2})", str(v or ""))
    if not m:
        return None
    try:
        return dt.time(int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def read_today() -> Tuple[str, List[Dict[str, object]]]:
    """(sheet's own date label, [{name, in, out, punches, late_by}])"""
    _, sheets = pb._services()
    grid = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"'{TODAY_TAB}'").execute().get("values", [])
    label = ""
    rows: List[Dict[str, object]] = []
    header_seen = False
    for r in grid:
        if not r or not str(r[0]).strip():
            continue
        first = str(r[0]).strip()
        if first.lower().startswith("daily attendance"):
            label = " ".join(str(c) for c in r[1:] if c).strip()
            continue
        if first.lower() == "name":
            header_seen = True
            continue
        if not header_seen:
            continue
        name = first
        t_in = _parse_time(r[1] if len(r) > 1 else "")
        t_out = _parse_time(r[2] if len(r) > 2 else "")
        punches = str(r[3]).strip() if len(r) > 3 else ""
        late_by = None
        if t_in:
            start = dt.datetime.combine(dt.date.today(), OFFICE_START) + dt.timedelta(minutes=GRACE_MINUTES)
            arrived = dt.datetime.combine(dt.date.today(), t_in)
            if arrived > start:
                late_by = int((arrived - start).total_seconds() // 60)
        rows.append({"name": name, "in": t_in, "out": t_out, "punches": punches, "late_by": late_by})
    return label, rows


def report_lines() -> List[str]:
    """The attendance section of the daily report."""
    try:
        label, rows = read_today()
    except Exception as e:
        logger.warning("attendance sheet unavailable: %s", e)
        return ["🕘 Attendance: could not read the attendance sheet right now."]
    if not rows:
        return ["🕘 Attendance: nobody has checked in yet."]

    present = [r for r in rows if r["in"]]
    late = sorted([r for r in present if r["late_by"]], key=lambda r: -int(r["late_by"]))
    on_time = sorted([r for r in present if not r["late_by"]], key=lambda r: r["in"])
    missing = [r for r in rows if not r["in"]]

    out = [f"🕘 Attendance {label or dt.date.today():%s}".replace("%s", "") if False else
           f"🕘 Attendance — {label or dt.date.today().isoformat()}",
           f"{len(present)} in, {len(late)} late (office starts {OFFICE_START:%H:%M})"]
    if late:
        out.append("⏰ Late:")
        for r in late:
            out.append(f"   • {r['name']} — {r['in']:%H:%M} ({r['late_by']} min late)")
    if on_time:
        out.append("✅ On time:")
        for r in on_time:
            out.append(f"   • {r['name']} — {r['in']:%H:%M}")
    if missing:
        out.append(f"❌ No check-in yet: {', '.join(str(r['name']) for r in missing)}")
    unnamed = [r["name"] for r in rows if re.fullmatch(r"ID\s*\d+", str(r["name"]).strip(), re.I)]
    if unnamed:
        out.append(f"ℹ️ Not named on the device yet: {', '.join(unnamed)}")
    return out


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    print("\n".join(report_lines()))


if __name__ == "__main__":
    main()
