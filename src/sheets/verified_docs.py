"""
Copy every document-verified student's files from the portal into Google Drive.

Source: students.php?source=direct&filter_docs=verified (all pages) — read-only GETs.
For each student the portal's own "download all" ZIP (download_docs.php?uid=N&zip=1) is
fetched, unzipped in memory, and each file is uploaded to

    ALL STUDENTS / VERIFIED STUDENT DOCUMENTS / <PROGRAM> / <FULL NAME> (<PASSPORT NO>) /

where <PROGRAM> is one of the four program folders (KLP, EAP, BACHELOR'S, MASTER'S).

Re-runnable: a student folder that finished completely is skipped; a half-finished one
only gets the files it is missing.  Nothing is ever deleted or overwritten.

CLI (run from the BOT folder):
  python -m src.sheets.verified_docs            # copy all verified students
  python -m src.sheets.verified_docs --list     # just list who would be copied
  python -m src.sheets.verified_docs --limit 2  # try the first 2 students only
  python -m src.sheets.verified_docs --local "..\\VERIFIED STUDENT DOCUMENTS"   # save on this PC
"""
from __future__ import annotations

import argparse
import asyncio
import io
import logging
import mimetypes
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from src.config import settings
from src.sheets.progress_builder import PARENT_FOLDER_ID, PROGRAMS, _services, program_matches

logger = logging.getLogger(__name__)

LIST_PATH = "students.php?source=direct&filter_docs=verified"
TARGET_FOLDER_NAME = "VERIFIED STUDENT DOCUMENTS"
FOLDER_MIME = "application/vnd.google-apps.folder"


# --- portal side (read-only) -------------------------------------------------------
def _parse_rows(html: str) -> List[Dict[str, str]]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=re.compile(r"download_docs\.php\?uid=\d+")):
        uid = re.search(r"uid=(\d+)", a["href"]).group(1)
        parts = a.find_parent("tr").get_text(" | ", strip=True).split(" | ")

        def after(label: str) -> str:
            if label in parts:
                i = parts.index(label) + 1
                return parts[i].strip() if i < len(parts) else ""
            return ""

        # The portal puts the upload time in every document's filename
        # (passport_492_1789796548.jpeg), so the set of names is a fingerprint of what
        # the student currently has uploaded.  Replace a document and the name changes.
        row = a.find_parent("tr")
        docs = sorted({m.group(1).rsplit("/", 1)[-1]
                       for m in re.finditer(r"view_doc\.php\?f=([^\"&'\s]+)", str(row))})

        out.append({"uid": uid, "name": after("Full Name"), "passport": after("Passport No"),
                    "program": after("Program"), "docs": "|".join(docs)})
    return out


async def fetch_verified_students(client) -> List[Dict[str, str]]:
    students: Dict[str, Dict[str, str]] = {}
    page, pages = 1, 1
    while page <= pages:
        resp = await client.client.get(f"{client.base_url}/{LIST_PATH}&pg={page}", timeout=60.0)
        if "login.php" in str(resp.url):
            await client.login()
            continue
        m = re.search(r"Page \d+ of (\d+)", resp.text)
        pages = int(m.group(1)) if m else page
        for s in _parse_rows(resp.text):
            students.setdefault(s["uid"], s)
        page += 1
    return list(students.values())


def program_folder(s: Dict[str, str]) -> str:
    """One of the four program folders (same names as the progress sheets)."""
    for cfg in PROGRAMS.values():
        if program_matches(s.get("program", ""), cfg["match_tokens"]):
            return cfg["name"]
    return "OTHER PROGRAMS"


def folder_name(s: Dict[str, str]) -> str:
    name = re.sub(r"\s+", " ", s["name"] or f"UID {s['uid']}").strip()
    return f"{name} ({s['passport']})" if s["passport"] else name


# --- Drive side --------------------------------------------------------------------
def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _find_folder(drive, name: str, parent: str):
    found = drive.files().list(
        q=(f"name = '{_q(name)}' and '{parent}' in parents and mimeType = '{FOLDER_MIME}' "
           "and trashed = false"),
        fields="files(id, appProperties)", supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute().get("files", [])
    return found[0] if found else None


def _find_or_create_folder(drive, name: str, parent: str):
    found = _find_folder(drive, name, parent)
    if found:
        return found
    return drive.files().create(
        body={"name": name, "parents": [parent], "mimeType": FOLDER_MIME},
        fields="id, appProperties", supportsAllDrives=True,
    ).execute()


def _existing_names(drive, folder_id: str) -> set:
    names, token = set(), None
    while True:
        resp = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false", fields="nextPageToken, files(name)",
            pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        names.update(f["name"] for f in resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            return names


def _upload(drive, folder_id: str, filename: str, data: bytes) -> None:
    from googleapiclient.http import MediaIoBaseUpload
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=True)
    drive.files().create(body={"name": filename, "parents": [folder_id]}, media_body=media,
                         fields="id", supportsAllDrives=True).execute()


# --- main job ----------------------------------------------------------------------
async def run(limit: int = 0, list_only: bool = False) -> None:
    from src.scraper.client import admin_client as client
    try:
        await client.login()
        students = await fetch_verified_students(client)
        print(f"{len(students)} verified student(s) on the portal.")
        if limit:
            students = students[:limit]
        if list_only:
            for s in students:
                print(f"  {program_folder(s)} / {folder_name(s)}")
            return

        drive, _ = _services()
        target = _find_or_create_folder(drive, TARGET_FOLDER_NAME, PARENT_FOLDER_ID)
        print(f"Drive folder: https://drive.google.com/drive/folders/{target['id']}")

        prog_ids: Dict[str, str] = {}
        done = skipped = failed = 0
        for n, s in enumerate(students, 1):
            name = folder_name(s)
            try:
                prog = program_folder(s)
                if prog not in prog_ids:
                    prog_ids[prog] = _find_or_create_folder(drive, prog, target["id"])["id"]
                parent = prog_ids[prog]
                # a folder from an earlier run that sat directly in the target folder is
                # moved into its program folder instead of being copied again
                loose = _find_folder(drive, name, target["id"])
                if loose and not _find_folder(drive, name, parent):
                    drive.files().update(fileId=loose["id"], addParents=parent,
                                         removeParents=target["id"], supportsAllDrives=True).execute()
                folder = _find_or_create_folder(drive, name, parent)
                if (folder.get("appProperties") or {}).get("hangeul_docs_complete") == "1":
                    skipped += 1
                    continue
                resp = await client.client.get(
                    f"{client.base_url}/download_docs.php", params={"uid": s["uid"], "zip": 1},
                    timeout=300.0)
                if "zip" not in resp.headers.get("content-type", ""):
                    raise RuntimeError(f"portal returned {resp.status_code} "
                                       f"{resp.headers.get('content-type')} instead of a ZIP")
                have = _existing_names(drive, folder["id"])
                added = 0
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                    for info in z.infolist():
                        fname = info.filename.rsplit("/", 1)[-1]
                        if info.is_dir() or not fname or fname in have:
                            continue
                        _upload(drive, folder["id"], fname, z.read(info))
                        added += 1
                drive.files().update(fileId=folder["id"],
                                     body={"appProperties": {"hangeul_docs_complete": "1"}},
                                     supportsAllDrives=True).execute()
                done += 1
                print(f"[{n}/{len(students)}] {name}: {added} file(s) uploaded")
            except Exception as e:
                failed += 1
                print(f"[{n}/{len(students)}] {name}: FAILED - {e}")
        print(f"\nFinished: {done} copied, {skipped} already complete, {failed} failed.")
        if failed:
            print("Run again to retry the failed ones (finished folders are skipped).")
    finally:
        await client.close()


async def _download_zip(client, uid: str) -> bytes:
    resp = await client.client.get(f"{client.base_url}/download_docs.php",
                                   params={"uid": uid, "zip": 1}, timeout=300.0)
    if "zip" not in resp.headers.get("content-type", ""):
        raise RuntimeError(f"portal returned {resp.status_code} "
                           f"{resp.headers.get('content-type')} instead of a ZIP")
    return resp.content


def _safe_path_part(s: str) -> str:
    """Windows can't have \\ / : * ? " < > | in names, or end them with a dot/space."""
    return re.sub(r'[\\/:*?"<>|]', "-", s).strip().rstrip(". ") or "UNNAMED"


def _drive_complete_names() -> set:
    """Student folders already finished in Drive (by an earlier Drive run)."""
    drive, _ = _services()
    names, token = set(), None
    while True:
        resp = drive.files().list(
            q=(f"mimeType = '{FOLDER_MIME}' and trashed = false and "
               "appProperties has { key='hangeul_docs_complete' and value='1' }"),
            fields="nextPageToken, files(name)", pageToken=token,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        names.update(f["name"] for f in resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            return names


LOCAL_DONE_MARKER = ".download_complete"

# Files above this are shrunk after download; the untouched original is copied to
# BACKUP_ROOT first (same sub-path).
MAX_FILE_BYTES = 2 * 1024 * 1024
_TARGET_BYTES = int(1.95 * 1024 * 1024)
BACKUP_ROOT = settings.docs_originals_root()
_A4 = (595, 842)


def _shrink_pdf(src: Path) -> Optional[bytes]:
    """Re-render each page as a JPEG on an A4-sized page, from ~150 dpi down, until the
    whole file fits.  (A4 page sizing also fixes scans saved with giant page sizes.)"""
    import pymupdf
    from PIL import Image
    doc = pymupdf.open(str(src))
    try:
        for long_px, quality in [(1754, 70), (1600, 65), (1400, 60), (1240, 55), (1100, 50), (950, 45)]:
            out = pymupdf.open()
            for p in doc:
                zoom = long_px / max(p.rect.width, p.rect.height)
                pix = p.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=quality, optimize=True)
                w, h = _A4 if p.rect.height >= p.rect.width else _A4[::-1]
                s = min(w / p.rect.width, h / p.rect.height)
                page = out.new_page(width=p.rect.width * s, height=p.rect.height * s)
                page.insert_image(page.rect, stream=buf.getvalue())
            data = out.tobytes(deflate=True, garbage=4)
            out.close()
            if len(data) <= _TARGET_BYTES:
                return data
        return None
    finally:
        doc.close()


def _shrink_image(src: Path) -> Optional[bytes]:
    from PIL import Image
    with Image.open(src) as im:
        im = im.convert("RGB")
        for long_px in (2400, 2000, 1600, 1300):
            scaled = im.copy()
            scaled.thumbnail((long_px, long_px))
            for quality in (80, 70, 60, 50):
                buf = io.BytesIO()
                scaled.save(buf, "JPEG", quality=quality, optimize=True)
                if buf.tell() <= _TARGET_BYTES:
                    return buf.getvalue()
    return None


def shrink_large_files(folder: Path, root: Path) -> List[str]:
    """Bring every file over 2 MB in `folder` under 2 MB (original backed up first).
    Returns a line per file handled, for the run report."""
    import shutil
    report = []
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.name == LOCAL_DONE_MARKER or f.stat().st_size <= MAX_FILE_BYTES:
            continue
        before = f.stat().st_size
        ext = f.suffix.lower()
        try:
            if ext == ".pdf":
                data = _shrink_pdf(f)
            elif ext in (".jpg", ".jpeg", ".png"):
                data = _shrink_image(f)
            else:
                report.append(f"{f.name}: {before / 1048576:.1f} MB, type not supported - left as is")
                continue
        except Exception as e:
            report.append(f"{f.name}: could not compress ({e}) - left as is")
            continue
        if data is None:
            report.append(f"{f.name}: {before / 1048576:.1f} MB, could not get under 2 MB - left as is")
            continue
        backup = BACKUP_ROOT / f.relative_to(root)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(f, backup)
        dest = f.with_suffix(".jpg") if ext == ".png" else f  # shrunk images are JPEG
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        if dest != f:
            f.unlink()
        report.append(f"{dest.name}: {before / 1048576:.1f} MB -> {len(data) / 1048576:.2f} MB")
    return report


async def run_local(root: Path, limit: int = 0, skip_drive_done: bool = True) -> Dict[str, list]:
    """Same as run(), but saves into a folder on this PC:
    <root>/<PROGRAM>/<FULL NAME> (<PASSPORT NO>)/<files>.  Files over 2 MB are shrunk.
    Returns {"saved": [(program, name, n_files, shrink_report)], "failed": [(name, error)]}."""
    from src.scraper.client import admin_client as client
    try:
        await client.login()
        students = await fetch_verified_students(client)
        print(f"{len(students)} verified student(s) on the portal.")
        if limit:
            students = students[:limit]
        in_drive = _drive_complete_names() if skip_drive_done else set()
        if in_drive:
            print(f"{len(in_drive)} already complete in Google Drive - not downloaded again.")
        print(f"Saving to: {root}")

        result: Dict[str, list] = {"saved": [], "failed": []}
        done = skipped = drive_skipped = failed = 0
        for n, s in enumerate(students, 1):
            name = folder_name(s)
            if name in in_drive:
                drive_skipped += 1
                continue
            folder = root / _safe_path_part(program_folder(s)) / _safe_path_part(name)
            # Skip only when the portal still lists exactly the documents that were
            # downloaded.  The marker records the portal's own filenames, which carry
            # the upload time — so a student who replaces a rejected document is fetched
            # again instead of being trusted forever.
            marker = folder / LOCAL_DONE_MARKER
            if marker.exists():
                try:
                    was = marker.read_text(encoding="utf-8").strip()
                except Exception:
                    was = ""
                now = s.get("docs", "")
                if was and was != "ok" and was == now:
                    skipped += 1
                    continue
                if was in ("", "ok"):        # downloaded before this check existed
                    marker.write_text(now, encoding="utf-8")
                    skipped += 1
                    continue
                print(f"[{n}/{len(students)}] {name}: documents changed on the portal — "
                      "downloading again")
            try:
                data = await _download_zip(client, s["uid"])
                folder.mkdir(parents=True, exist_ok=True)
                added = 0
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for info in z.infolist():
                        fname = _safe_path_part(info.filename.rsplit("/", 1)[-1])
                        dest = folder / fname
                        if info.is_dir() or dest.exists():
                            continue
                        tmp = dest.with_name(dest.name + ".part")
                        tmp.write_bytes(z.read(info))
                        tmp.replace(dest)
                        added += 1
                shrunk = shrink_large_files(folder, root)
                # record what the portal held at this moment, so a later upload is noticed
                (folder / LOCAL_DONE_MARKER).write_text(s.get("docs", "ok") or "ok",
                                                        encoding="utf-8")
                done += 1
                result["saved"].append((program_folder(s), name, added, shrunk))
                print(f"[{n}/{len(students)}] {name}: {added} file(s) saved")
                for line in shrunk:
                    print(f"      compressed {line}")
            except Exception as e:
                failed += 1
                result["failed"].append((name, str(e)))
                print(f"[{n}/{len(students)}] {name}: FAILED - {e}")
        print(f"\nFinished: {done} saved, {skipped} already on this PC, "
              f"{drive_skipped} already in Drive, {failed} failed.")
        if failed:
            print("Run again to retry the failed ones (finished folders are skipped).")
        return result
    finally:
        await client.close()


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s  %(message)s")
    ap = argparse.ArgumentParser(description="Copy verified students' portal documents to Drive or this PC.")
    ap.add_argument("--list", action="store_true", help="only list the students")
    ap.add_argument("--limit", type=int, default=0, help="only the first N students")
    ap.add_argument("--local", metavar="FOLDER", help="save on this PC instead of Drive, e.g. "
                    f"\"{settings.docs_root()}\"")
    ap.add_argument("--include-drive-done", action="store_true",
                    help="with --local: also download students already finished in Drive")
    args = ap.parse_args()
    loop = asyncio.new_event_loop()
    try:
        if args.local and not args.list:
            loop.run_until_complete(run_local(Path(args.local), limit=args.limit,
                                              skip_drive_done=not args.include_drive_done))
        else:
            loop.run_until_complete(run(limit=args.limit, list_only=args.list))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
