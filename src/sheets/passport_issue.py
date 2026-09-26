"""
Passport issue dates.

The portal keeps "Passport Issue Date" on the student edit page (field
passport_issue_date) but does NOT include it in the students CSV export, so it has to be
read per student.  That is 300+ read-only page fetches, far too slow for the 15-minute
sync, so the dates are cached here and refreshed once a day (or on demand).

  python -m src.sheets.passport_issue --refresh      # re-read every student
  python -m src.sheets.passport_issue                # show what is cached
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from typing import Dict

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


async def _fetch_async(limit: int = 0) -> Dict[str, str]:
    from bs4 import BeautifulSoup
    from src.scraper.client import admin_client as c
    out: Dict[str, str] = {}
    try:
        await c.login()
        # the list pages give the internal id for each student
        uids, page, pages = {}, 1, 1
        while page <= pages:
            r = await c.client.get(f"{c.base_url}/students.php?pg={page}", timeout=60)
            m = re.search(r"Page \d+ of (\d+)", r.text)
            pages = int(m.group(1)) if m else page
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=re.compile(r"student_edit\.php\?id=\d+")):
                uid = re.search(r"id=(\d+)", a["href"]).group(1)
                tr = a.find_parent("tr")
                if not tr:
                    continue
                parts = tr.get_text(" | ", strip=True).split(" | ")
                if "Passport No" in parts:
                    i = parts.index("Passport No") + 1
                    if i < len(parts) and parts[i].strip():
                        uids.setdefault(parts[i].strip().upper(), uid)
            page += 1
        items = list(uids.items())[:limit] if limit else list(uids.items())
        for n, (pas, uid) in enumerate(items, 1):
            resp = await c.client.get(f"{c.base_url}/student_edit.php?id={uid}", timeout=60)
            m = re.search(r'name="passport_issue_date"[^>]*value="([^"]*)"', resp.text)
            if m and m.group(1).strip():
                out[pas] = m.group(1).strip()
            if n % 50 == 0:
                print(f"   read {n}/{len(items)} students", flush=True)
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
