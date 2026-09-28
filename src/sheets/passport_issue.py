"""
Passport issue dates.

The portal keeps "Passport Issue Date" on the student edit page (field
passport_issue_date). The students CSV export used to leave it out (since Sep 2026 it has a
"Passport Issue Date" column, which the progress sheets use first), so it is read per
student.  That is 300+ read-only page fetches, far too slow for the 15-minute sync, so the
dates are cached here and refreshed once a day (or on demand).

The cache is keyed by passport number, taken from each student's own "Passport No" field on
students.php. A placeholder such as "PENDING" (students with no passport yet share it) is no
passport number and is left out, so no student is given another student's date; a number two
students share (one person registered twice) is kept only when the dates on their edit pages
do not disagree (a blank one aside). A refresh that cannot read the portal leaves the last
cache as it was (never an empty one).

  python -m src.sheets.passport_issue --refresh      # re-read every student
  python -m src.sheets.passport_issue                # show what is cached
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from typing import Dict, List

from src.sheets import progress_builder as pb

logger = logging.getLogger(__name__)

CACHE_PATH = pb.BOT_ROOT / "data" / "passport_issue.json"


def load() -> Dict[str, str]:
    """{passport number: issue date} as last fetched."""
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8")).get("by_passport", {})
        except Exception as e:
            logger.warning("issue-date cache unreadable: %s", e)
    return {}


def passport_key(value: str) -> str:
    """A "Passport No" value as the cache key, or "" when it is no passport number: blank, "—",
    or a placeholder without a digit ("PENDING")."""
    v = re.sub(r"\s+", "", value or "").upper()
    return v if len(v) >= 6 and re.search(r"\d", v) else ""


_ISSUE_RE = re.compile(r'name="passport_issue_date"[^>]*value="([^"]*)"')
MAX_UNREAD = 10      # edit pages that may time out before the refresh gives up (cache kept)


async def _fetch_async(limit: int = 0) -> Dict[str, str]:
    from src.scraper.client import PortalUnavailable, admin_client as c
    out: Dict[str, str] = {}
    try:
        # every page of the student list, read by column name: each student's uid and their own
        # "Passport No" field (raises PortalUnavailable when the list cannot be read whole)
        by_passport: Dict[str, List[str]] = {}
        for s in await c.read_students():
            pas = passport_key((s.get("details") or {}).get("Passport No", ""))
            if pas and s.get("uid"):
                by_passport.setdefault(pas, []).append(s["uid"])
        items = list(by_passport.items())[:limit] if limit else list(by_passport.items())
        previous, unread = load(), []
        for n, (pas, uids) in enumerate(items, 1):
            dates = set()
            for uid in uids:
                try:
                    html = await c.fetch_html("student_edit.php", params={"id": uid}, timeout=60)
                except PortalUnavailable as e:
                    if not e.unreachable or len(unread) >= MAX_UNREAD:
                        raise                      # a refused login, or the portal is down
                    unread.append(uid)
                    dates = None
                    break
                m = _ISSUE_RE.search(html)
                if m and m.group(1).strip():
                    dates.add(m.group(1).strip())
            if dates is None:                      # not read this time: keep the last date read
                if previous.get(pas):
                    out[pas] = previous[pas]
            elif len(dates) == 1:
                out[pas] = dates.pop()
            elif len(dates) > 1:
                logger.warning("passport number shared by %d students with different issue dates: "
                               "left out", len(uids))
            if n % 50 == 0:
                print(f"   read {n}/{len(items)} students", flush=True)
        if unread:
            print(f"   {len(unread)} edit page(s) did not answer; their last issue dates were kept", flush=True)
        return out
    finally:
        await c.close()


def refresh(limit: int = 0) -> Dict[str, str]:
    data = pb._run_async(_fetch_async(limit))
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps({"by_passport": data}, indent=1), encoding="utf-8")
    return data


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description="Passport issue dates from the portal (read-only).")
    ap.add_argument("--refresh", action="store_true", help="re-read every student's edit page")
    ap.add_argument("--limit", type=int, default=0, help="only the first N students")
    args = ap.parse_args()
    data = refresh(args.limit) if args.refresh else load()
    print(f"{len(data)} passport issue date(s) cached at {CACHE_PATH}")
    for k, v in list(data.items())[:10]:
        print(f"   {k}: {v}")


if __name__ == "__main__":
    main()
