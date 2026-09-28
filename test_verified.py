"""Print today's payment-verified students, read live (read-only) from every page of
students.php: the same read /verified_today uses (admin_client.get_verified_students). Amounts
and methods are only what the rows show; a portal that cannot be read is said so, never 0.

Run from the BOT folder:
    .venv\\Scripts\\python.exe test_verified.py
"""
import asyncio
import sys

from src.dates import local_today, yearless_day_problem
from src.scraper.client import admin_client, portal_error_reason

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


async def main() -> int:
    day = local_today()
    problem = yearless_day_problem(day, local_today())
    if problem:
        print(f"Verified on {day:%d %b %Y}: not available ({problem})")
        return 1
    try:
        verified = await admin_client.get_verified_students(target_date=day)
    except Exception as e:
        print(f"Couldn't read the portal: {portal_error_reason(e)}")
        return 1
    print(f"Verified Today ({day:%d %b %Y}, every page read): {len(verified)}")
    for item in verified:
        print(item)
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
