"""Download every student's passport scan that is not saved yet into passports\\, read-only:
the list comes from every page of students.php (admin_client.read_students, the shared reader),
each scan through the one session path (admin_client.portal_get, which logs in again when the
session expired). A web page sent instead of a scan (a login page) is never saved.

Run from the BOT folder:
    .venv\\Scripts\\python.exe download_passports.py
"""
import asyncio
import os

from inspect_passports import passport_students
from src.scraper.client import admin_client, portal_error_reason

os.makedirs('passports', exist_ok=True)


async def download_all_passports():
    try:
        students = passport_students(await admin_client.read_students())
    except Exception as e:
        print(f"Couldn't read the portal: {portal_error_reason(e)}")
        return
    downloaded = 0
    print(f"Total students to process: {len(students)} (every page of students.php read)")

    for s in students:
        fname = s['doc_url'].split('f=')[-1]
        local_path = os.path.join('passports', f"{s['id']}_{fname}")
        if not os.path.exists(local_path):
            try:
                res = await admin_client.portal_get(s['doc_url'], timeout=60.0)
                content = res.content or b""
                if content[:200].lstrip()[:1] == b"<" or b"<html" in content[:1000].lower():
                    print(f"Failed ID {s['id']}: the portal sent a web page instead of the scan")
                elif len(content) > 100:
                    with open(local_path, 'wb') as f:
                        f.write(content)
                    downloaded += 1
                    print(f"Downloaded ID {s['id']}: {fname} ({len(content)} bytes)")
                else:
                    print(f"Failed ID {s['id']}: only {len(content)} bytes")
            except Exception as e:
                print(f"Error ID {s['id']}: {portal_error_reason(e)}")
        else:
            print(f"Already cached ID {s['id']}: {local_path}")

    print(f"Done. Downloaded {downloaded} new files.")

if __name__ == '__main__':
    asyncio.run(download_all_passports())
