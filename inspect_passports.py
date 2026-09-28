"""List every student with a passport scan uploaded, read live (read-only) from every page of
students.php through the shared reader (admin_client.read_students). A portal that cannot be
read is said so, never an empty list.

Run from the BOT folder:
    .venv\\Scripts\\python.exe inspect_passports.py
"""
import asyncio
import sys

from src.scraper.client import admin_client, portal_error_reason

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def passport_students(records):
    """The students.php records with a passport_... upload (the newest when there are several, as
    the passport watcher picks it), as the fields this listing prints."""
    from src.bot.scheduler import passport_scan
    students = []
    for s in records:
        scan = passport_scan(s)
        if not scan:
            continue
        d = s.get("details") or {}
        students.append({
            'id': s.get("uid") or 'N/A',
            'name': d.get("Full Name") or s.get("student_name") or '',
            'surname': d.get("Surname", ""),
            'given_name': d.get("Given Name", ""),
            'dob': d.get("DOB", ""),
            'passport_no': d.get("Passport No", ""),
            'expiry': d.get("Passport Expiry", ""),
            'doc_url': f"view_doc.php?f={scan}",
        })
    return students


async def list_students():
    try:
        records = await admin_client.read_students()
    except Exception as e:
        print(f"Couldn't read the portal: {portal_error_reason(e)}")
        return
    students = passport_students(records)
    print(f"Found {len(students)} of {len(records)} students with uploaded passports on students.php "
          f"(every page read):\n")
    for idx, s in enumerate(students):
        print(f"{idx+1:2d}. [ID {s['id']}] {s['name'] or '—'} | Pass: {s['passport_no'] or '—'} | "
              f"Exp: {s['expiry'] or '—'} | DOB: {s['dob'] or '—'}")
        print(f"    URL: {s['doc_url']}")

if __name__ == '__main__':
    asyncio.run(list_students())
