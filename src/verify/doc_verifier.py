"""
Document verifier — checks a student's DOWNLOADED documents against the program
guidelines (src/verify/rules.py) and the portal's own record of that student.

It never touches the portal beyond the read-only student export the rest of the bot
already uses; all reading happens on the local files.

What it does per student:
  1. Works out which program they are on and which documents are required.
  2. Reads every file: PDF text layer first, OCR (easyocr) only when there is none.
  3. Runs the per-document rules (validity dates, amounts, notarisation, apostille,
     photo size, issue dates …) plus cross-checks against the portal record.
  4. Writes an Excel report: one row per document with verdict + reason, and a
     summary sheet for the whole run.

Verdicts: PASS · FLAG (needs a human eye) · FAIL · MISSING

CLI (run from the BOT folder):
  python -m src.verify.doc_verifier --student "NAHID SAFWANUL ISLAM"
  python -m src.verify.doc_verifier --passport A00990016
  python -m src.verify.doc_verifier --all                  # every downloaded student
  python -m src.verify.doc_verifier --all --since 2026-09-01
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import settings
from src.verify import page_checks as PC
from src.verify import rules as R

logger = logging.getLogger(__name__)

DOCS_ROOTS = [settings.docs_root(), settings.konyang_root()]   # an absent one is skipped
REPORT_DIR = settings.verification_dir()
TODAY = dt.date.today()

PASS, FLAG, FAIL, MISSING = "PASS", "FLAG", "FAIL", "MISSING"
NOTE = "NOTE"        # worth a glance, not a finding — never changes a verdict


# --- text extraction ---------------------------------------------------------------
_reader = None


def _ocr_reader():
    global _reader
    if _reader is None:
        import easyocr
        import torch
        _reader = easyocr.Reader(["en"], gpu=torch.cuda.is_available())
    return _reader


_MIN_PAGE_CHARS = 300      # a full certificate page reads well past this when upright


def _ocr_image(arr, turned=None) -> str:
    """OCR a page, turning it upright first if it was scanned sideways.

    Board certificates are printed landscape and scanned on their side; EasyOCR reads
    almost nothing off them until they are rotated.  Only pages that read poorly are
    retried, so upright pages cost nothing extra."""
    import cv2
    text = " ".join(_ocr_reader().readtext(arr, detail=0))
    if len(text) >= _MIN_PAGE_CHARS:
        return text
    best = text
    for rot in (cv2.ROTATE_90_COUNTERCLOCKWISE, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180):
        try:
            t = " ".join(_ocr_reader().readtext(cv2.rotate(arr, rot), detail=0))
        except Exception:
            continue
        if len(t) > len(best):
            best = t
            if turned is not None:
                turned.append(True)
        if len(best) >= _MIN_PAGE_CHARS:
            break
    return best


def read_pages(path: Path, max_pages: int = 20, sideways: Optional[List[int]] = None) -> List[str]:
    """The text of each page on its own, in order.  Needed where page ORDER matters — an
    e-Apostille and the certificate that follows it."""
    import pymupdf
    if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
        return [" ".join(_ocr_reader().readtext(str(path), detail=0))]
    try:
        doc = pymupdf.open(str(path))
    except Exception:
        return []
    out: List[str] = []
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            t = page.get_text().strip()
            if len(t) < 40:                      # a scan: no text layer to read
                import numpy as np
                pix = page.get_pixmap(dpi=200)
                a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                turned: List[bool] = []
                t = _ocr_image(a[:, :, :3], turned)
                if turned and sideways is not None:
                    sideways.append(i + 1)
            out.append(t)
    finally:
        doc.close()
    return out


def read_document(path: Path, max_pages: int = 20) -> Tuple[str, List[Tuple[int, int]]]:
    """All text in a file, plus each page's pixel size. Uses the PDF text layer when
    there is one; falls back to OCR for scans and images."""
    import pymupdf
    text, sizes = [], []
    if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
        from PIL import Image
        with Image.open(path) as im:
            sizes.append(im.size)
        text.append(" ".join(_ocr_reader().readtext(str(path), detail=0)))
        return "\n".join(text), sizes
    try:
        doc = pymupdf.open(str(path))
    except Exception as e:
        return f"[unreadable: {e}]", []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        sizes.append((round(page.rect.width), round(page.rect.height)))
        layer = page.get_text().strip()
        if len(layer) > 80:
            text.append(layer)
        else:
            pix = page.get_pixmap(dpi=150)
            import numpy as np
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            text.append(_ocr_image(arr[:, :, :3]))
    doc.close()
    return "\n".join(text), sizes


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def notarised(text: str, path: Optional[Path]) -> bool:
    """Notarisation is proved by the wording OR by a visible notary/wax seal."""
    if has_any(text, R.NOTARY_WORDS):
        return True
    return bool(path) and PC.seal_present(path)


def has_any(text: str, words: List[str]) -> bool:
    """Substring match, then a fuzzy pass: OCR turns 'advocate' into 'advocale',
    'notary' into 'nolary' and 'attested' into 'attarta'."""
    import difflib
    t = norm(text)
    if any(w in t for w in words):
        return True
    tokens = re.findall(r"[a-z]{4,}", t)
    for w in words:
        parts = w.split()
        if len(parts) > 1:                     # multi-word phrases: match the first word
            w = parts[0]
        if len(w) < 5:
            continue
        for tok in tokens:
            if abs(len(tok) - len(w)) <= 2 and difflib.SequenceMatcher(None, tok, w).ratio() >= 0.8:
                return True
    return False


# --- small parsers -----------------------------------------------------------------
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


_DIGIT_LOOKALIKE = str.maketrans({"I": "1", "l": "1", "S": "5", "s": "5", "O": "0",
                                  "o": "0", "B": "8", "Z": "2", "G": "6", "q": "9"})


def find_dates(text: str) -> List[dt.date]:
    """Every date we can recognise, in any of the formats these documents use."""
    out = []
    t = text.replace("\u2013", "-")
    for m in re.finditer(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b", t):           # 25-06-2008
        d, mo, y = (int(x) for x in m.groups())
        if d > 12 and mo <= 12:
            pass
        elif mo > 12:
            d, mo = mo, d
        try:
            out.append(dt.date(y, mo, d))
        except ValueError:
            pass
    for m in re.finditer(r"\b(\d{4})[./-](\d{1,2})[./-](\d{1,2})\b", t):           # 2026-09-15
        y, mo, d = (int(x) for x in m.groups())
        try:
            out.append(dt.date(y, mo, d))
        except ValueError:
            pass
    # "16 September 2026" and "15th Oct, 2004"
    for m in re.finditer(r"\b(\d{1,2})\s*(?:st|nd|rd|th)?[ ,.-]*"
                         r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[ ,.-]+(\d{4})", t, re.I):
        d, mon, y = m.group(1), m.group(2).lower(), m.group(3)
        try:
            out.append(dt.date(int(y), _MONTHS[mon], int(d)))
        except ValueError:
            pass
    for m in re.finditer(r"\b(\d{4})\.(\d{1,2})\.(\d{1,2})\b", t):              # 2026.09.15
        y, mo, d = (int(x) for x in m.groups())
        try:
            out.append(dt.date(y, mo, d))
        except ValueError:
            pass
    for m in re.finditer(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", t):              # 15.09.2026
        d, mo, y = (int(x) for x in m.groups())
        if mo > 12 >= d:
            d, mo = mo, d
        try:
            out.append(dt.date(y, mo, d))
        except ValueError:
            pass
    # "Sep 16, 2026" / "September 16 2026" — month first
    for m in re.finditer(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
                         r"[ ,.-]+(\d{1,2})(?:st|nd|rd|th)?[ ,.-]+(\d{4})", t, re.I):
        mon, d, y = m.group(1).lower(), m.group(2), m.group(3)
        try:
            out.append(dt.date(int(y), _MONTHS[mon], int(d)))
        except ValueError:
            pass
    # two-digit year: 15-09-26
    for m in re.finditer(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2})\b(?!\d)", t):
        d, mo, y = (int(x) for x in m.groups())
        if mo > 12 >= d:
            d, mo = mo, d
        year = 2000 + y if y <= (TODAY.year % 100) + 15 else 1900 + y
        try:
            out.append(dt.date(year, mo, d))
        except ValueError:
            pass
    # "ISth September 2026" — OCR reads 1 as I and 5 as S in an ordinal day.  Only the
    # day is allowed to carry look-alike letters, and only in the ordinal form, so this
    # cannot invent a date out of ordinary words.
    for m in re.finditer(r"\b([0-9IlSsOoBZGq]{1,2})\s*(?:st|nd|rd|th)[ ,.-]*"
                         r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[ ,.-]+(\d{4})",
                         t, re.I):
        day = m.group(1).translate(_DIGIT_LOOKALIKE)
        if not day.isdigit():
            continue
        try:
            out.append(dt.date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(day)))
        except (ValueError, KeyError):
            pass
    # digits printed one per box: "1 5  1 0  2 0 0 4" -> 15/10/2004
    for m in re.finditer(r"(?<!\d)(\d)[\s|]{0,3}(\d)[\s|]{0,4}(\d)[\s|]{0,3}(\d)[\s|]{0,4}"
                         r"(\d)[\s|]{0,3}(\d)[\s|]{0,3}(\d)[\s|]{0,3}(\d)(?!\d)", t):
        g = "".join(m.groups())
        try:
            cand = dt.date(int(g[4:]), int(g[2:4]), int(g[:2]))
        except ValueError:
            continue
        if 1900 <= cand.year <= TODAY.year + 15:
            out.append(cand)
    return out


def money_value(raw: str) -> Optional[float]:
    """'25,73,067.50' -> 2573067.5 ; '33,74,119,69' (OCR writes the decimal point as a
    comma) -> 3374119.69 ; '2,300,900.30' -> 2300900.3"""
    s = raw.strip()
    groups = s.split(",")
    if len(groups) >= 3 and "." not in s and len(groups[-1]) == 2:
        s = ",".join(groups[:-1]) + "." + groups[-1]
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def find_money_taka(text: str) -> List[int]:
    """Amounts in taka, in lakh grouping or western grouping."""
    out = []
    for m in re.finditer(r"\b(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d{6,9}(?:\.\d{1,2})?)\b", text):
        v = money_value(m.group(1))
        if v is not None and 100_000 <= v <= 100_000_000:
            out.append(int(v))
    return sorted(set(out), reverse=True)


def months_between(a: dt.date, b: dt.date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)


# --- per-document checks -----------------------------------------------------------
def check_passport(text: str, student: Dict[str, str], sizes, path: Optional[Path] = None) -> List[Tuple[str, str]]:
    out = []
    expiry = student.get("Passport Expiry", "")
    exp_date = None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", expiry or ""):
        exp_date = dt.date.fromisoformat(expiry)
    doc_dates = [d for d in find_dates(text) if d.year >= TODAY.year]
    if exp_date is None and doc_dates:
        exp_date = max(doc_dates)
    if exp_date:
        months = months_between(TODAY, exp_date)
        if months < 0:
            out.append((FAIL, f"passport expired on {exp_date}"))
        elif months < R.PASSPORT_MIN_MONTHS:
            out.append((FAIL, f"only {months} month(s) validity left (expires {exp_date}); "
                              "guideline requires at least 1 year — must be renewed"))
        else:
            out.append((PASS, f"valid until {exp_date} ({months} months left)"))
    else:
        out.append((FLAG, "could not read an expiry date from the scan"))
    pno = (student.get("Passport No") or "").upper()
    if pno:
        out.append((PASS, f"passport number {pno} found on the scan")
                   if pno.replace(" ", "") in re.sub(r"\s+", "", text.upper())
                   else (FLAG, f"portal passport number {pno} not found in the scan text"))
    # NOTE: seal-placement check disabled — it cannot yet separate the passport
    # image from the page reliably, so it flagged every scan. Being reworked.
    # out += PC.passport_seal_check(path) if path else []
    return out


def check_photo(text: str, student: Dict[str, str], sizes, path: Optional[Path] = None) -> List[Tuple[str, str]]:
    out = []
    if not path or not path.exists():
        return [(FLAG, "photo file could not be opened")]
    try:
        from PIL import Image, ImageStat
        with Image.open(path) as im:
            w, h = im.size
            ratio = w / h if h else 0
            if abs(ratio - R.PHOTO_RATIO) <= 0.06:
                out.append((PASS, f"{w}x{h}px, ratio matches 3.5x4.5 cm"))
            else:
                out.append((FLAG, f"{w}x{h}px, ratio {ratio:.2f} differs from 3.5x4.5 (0.78)"))
            if min(w, h) < 300:
                out.append((FLAG, f"low resolution ({w}x{h}px) — may print blurry"))
            rgb = im.convert("RGB")
            # sample the background ABOVE the head (top band + top corners); the lower
            # edges are the subject's shoulders and hair, not the backdrop
            band = [rgb.getpixel((x, y))
                    for y in range(0, max(2, h // 8), max(1, h // 40))
                    for x in range(0, w, max(1, w // 30))]
            corners = [rgb.getpixel((x, y))
                       for y in range(0, max(2, h // 4), max(1, h // 30))
                       for x in list(range(0, max(2, w // 10))) + list(range(w - max(2, w // 10), w))]
            sample = band + corners
            avg = tuple(sum(c[i] for c in sample) / len(sample) for i in range(3))
            if min(avg) > 190:                 # off-white is fine; only a dark background fails
                out.append((PASS, "background is white or near-white"))
            else:
                out.append((FAIL, f"background is not white (avg {tuple(int(a) for a in avg)}) — "
                                  "guideline requires a white background"))
            gray = rgb.convert("L")
            if ImageStat.Stat(gray).stddev[0] < 30:
                out.append((FLAG, "image looks flat/low contrast — check sharpness"))
    except Exception as e:
        out.append((FLAG, f"could not inspect the image ({e})"))
    if path.suffix.lower() not in R.PHOTO_FORMATS:
        out.append((FAIL, f"photo is {path.suffix} — reviewer requires JPG/JPEG"))
    if (student.get("Gender") or "").upper().startswith("F"):
        out.append((NOTE, "female applicant — worth a glance that both ears are visible"))
    return out


def check_birth_cert(text: str, student, sizes, path=None, others=None) -> List[Tuple[str, str]]:
    out = []
    if has_any(text, R.ONLINE_BIRTH_WORDS):
        out.append((PASS, "looks like an online birth registration certificate"))
    else:
        out.append((FLAG, "could not confirm it is an ONLINE birth certificate"))
    out.append((PASS, "notarised (wording or seal found)") if notarised(text, path)
               else (FAIL, "no notarisation found — guideline requires notarisation"))
    if not re.search(r"[a-z]", text.lower()):
        out.append((FLAG, "little English text — if the certificate is not in English it must be "
                          "translated on a lawyer pad and notarised"))
    # The date of birth must agree with the PASSPORT, not with what the portal says.
    passport_text = (others or {}).get("passport", "")
    here = set(find_dates(text))
    there = set(find_dates(passport_text))
    if not passport_text:
        out.append((FLAG, "no passport on file to check the date of birth against"))
    elif not here or not there:
        out.append((FLAG, "could not read a date of birth from one of the two scans — "
                          "compare the birth certificate and the passport by eye"))
    elif here & there:
        d = sorted(here & there)[0]
        out.append((PASS, f"date of birth {d} is the same on the birth certificate and the passport"))
    elif {x.year for x in here} & {x.year for x in there}:
        y = sorted({x.year for x in here} & {x.year for x in there})[0]
        out.append((PASS, f"year of birth {y} agrees with the passport; the day and month could "
                          "not be read (boxed digits often defeat OCR)"))
    else:
        out.append((FAIL, f"no date on the birth certificate matches any date on the passport "
                          f"(certificate: {', '.join(str(x) for x in sorted(here)[:3])})"))
    return out


def nid_numbers(text: str) -> List[str]:
    """NID and birth-registration numbers found in a scan.

    Bangladesh uses a 10-digit Smart NID, a 13 or 17-digit legacy NID, and a 17-digit
    birth registration number.  Cards print them in spaced groups ("123 456 7890") and
    OCR keeps the spaces, so digit runs are joined up before their length is judged.
    Mobile numbers sit on the same pages and look the same once joined, so anything
    starting 01 is left out: an 11-digit mobile clipped by OCR is otherwise a perfect
    10-digit Smart NID.
    """
    out = set()
    for run in re.findall(r"\d[\d\s.\-]{7,32}\d", text or ""):
        digits = re.sub(r"\D", "", run)
        for size in (17, 13, 10):
            if len(digits) == size:
                if digits in R.BOILERPLATE_NUMBERS:
                    break                       # printed on the form, not a person's
                if size <= 13 and digits.startswith("01"):
                    break                       # a mobile number
                if size == 13 and digits.startswith("880"):
                    break                       # a mobile number with the country code
                out.add(digits)
                break
    return sorted(out)


def check_nid(text: str, student, sizes, whose: str, path=None, others=None) -> List[Tuple[str, str]]:
    out = []
    out.append((PASS, "notarised (wording or seal found)") if notarised(text, path)
               else (FAIL, "no notarisation found — parents' NID must be notarised"))
    out.append((PASS, "on an advocate/lawyer pad") if has_any(text, R.LAWYER_PAD_WORDS)
               else (FLAG, "could not confirm the translation is on a lawyer pad"))

    # The name must agree with the PASSPORT — a Bangladeshi passport carries the holder's
    # name and both parents' names.
    key = {"father": "Father", "mother": "Mother", "student": "Full Name"}.get(whose, "Full Name")
    name = student.get(key, "")
    passport_text = (others or {}).get("passport", "")
    if name:
        first = norm(name).split()[0] if norm(name) else ""
        on_nid = bool(first and first in norm(text))
        on_passport = bool(first and first in norm(passport_text))
        if on_nid and on_passport:
            out.append((PASS, f"{whose}'s name '{name}' appears on both the NID and the passport"))
        elif on_nid and not passport_text:
            out.append((FLAG, f"{whose}'s name is on the NID, but there is no passport to check it against"))
        elif on_nid:
            out.append((FLAG, f"{whose}'s name '{name}' is on the NID but could not be found on "
                              "the passport — compare them by eye"))
        else:
            out.append((FLAG, f"{whose}'s name '{name}' not found in the NID scan text"))

    # Bangladesh issues two kinds of NID: a 10-digit Smart card and a 13-digit old one.
    # Both are valid, and a document may show either.  What must agree is the number on
    # the translation and the number on the original — so numbers are only ever compared
    # against numbers of the SAME length.  A 10-digit on one page and a 13-digit on the
    # other is two formats of one identity, not a mismatch.
    pages: List[str] = []
    if path is not None:
        try:
            pages = read_pages(path, max_pages=8)
        except Exception as e:
            logger.warning("could not read %s page by page: %s", path.name, e)
    per_page = [set(nid_numbers(t)) for t in pages]
    every = sorted({n for s in per_page for n in s}) or nid_numbers(text)

    if not every:
        out.append((FLAG, "no NID/birth-registration number could be read from the scan"))
    else:
        conflicts, agreed, alone = [], [], []
        for size in (10, 13, 17):
            pages_with = [s for s in ({n for n in page if len(n) == size} for page in per_page) if s]
            if len(pages_with) >= 2:
                shared = set.intersection(*pages_with)
                if shared:
                    agreed.append(sorted(shared)[0])
                else:
                    conflicts.append((size, [sorted(s)[0] for s in pages_with[:2]]))
            elif len(pages_with) == 1:
                alone.append(sorted(pages_with[0])[0])

        if conflicts:
            # Two different numbers of the same length is worth a human eye, but not a
            # verdict: OCR misreads a digit often enough that calling it a forgery would
            # be overstating the evidence.  The reviewer is given both numbers to compare.
            size, vals = conflicts[0]
            out.append((FLAG, f"the {size}-digit ID number reads {vals[0]} on one page and "
                              f"{vals[1]} on another — check the translation against the "
                              "original by eye"))
        elif agreed:
            out.append((PASS, "ID number " + ", ".join(agreed) +
                              " reads the same on the original and the translation"))
        else:
            kinds = ", ".join(f"{n} ({len(n)}-digit)" for n in every[:3])
            out.append((NOTE, f"ID number {kinds} read, but not on two pages in the same format, "
                              "so the original and the translation could not be compared"))
    return out


def issue_date(text: str) -> Optional[dt.date]:
    """The date a certificate was issued: taken from the 'Date'/'Ref'/'Memo' line, and
    never from a family member's date of birth. OCR often inserts stray dots
    ("302.083.2026"), so the digits near the label are also tried."""
    head = text[:1200]
    m = re.search(r"(date|ref|memo|serial)[^\n]{0,90}", head, re.I)
    if m:
        got = [d for d in find_dates(m.group(0)) if 0 <= (TODAY - d).days <= 3 * 365]
        if got:                       # a date on the header line, but never a birth date
            return max(got)
        digits = re.sub(r"\D", "", m.group(0))
        for i in range(len(digits) - 7):          # find DDMMYYYY inside the digit run
            chunk = digits[i:i + 8]
            try:
                d = dt.date(int(chunk[4:]), int(chunk[2:4]), int(chunk[:2]))
            except ValueError:
                continue
            if abs((TODAY - d).days) <= 3 * 365:
                return d
    recent = [d for d in find_dates(text) if 0 <= (TODAY - d).days <= 3 * 365]
    return max(recent) if recent else None


def check_family_cert(text: str, student, sizes, path=None) -> List[Tuple[str, str]]:
    out = []
    recent = issue_date(text)
    if recent:
        age = months_between(recent, TODAY)
        if age <= R.FAMILY_CERT_MAX_MONTHS:
            out.append((PASS, f"issued {recent} ({age} month(s) ago) — within the 3-month validity"))
        else:
            out.append((FAIL, f"issued {recent} ({age} months ago) — older than the 3-month validity"))
    else:
        out.append((FLAG, "could not read the issue date from the scan — check the 3-month validity by eye"))
    out.append((PASS, "issued by Union Parishad / City Corporation") if has_any(text, R.UNION_ISSUER_WORDS)
               else (FLAG, "issuer (Union Parishad / City Corporation) not recognised"))
    out.append((PASS, "notarised through an advocate (wording or seal found)") if notarised(text, path)
               else (FAIL, "no notarisation found — guideline requires an advocate's notarisation"))
    name = norm(student.get("Full Name", ""))
    first_chunk = norm(text)[:1200]
    if name:
        parts = [p for p in name.split() if len(p) > 2]
        out.append((PASS, "student's name appears at the top of the certificate")
                   if any(p in first_chunk for p in parts)
                   else (FLAG, "student's name not found near the top — it must be in the first row"))
    ids = len(re.findall(r"\b\d{10,17}\b", text))
    out.append((PASS, f"{ids} NID/birth-registration numbers listed") if ids >= 2
               else (FLAG, "few or no NID/birth numbers found — each member needs one"))
    return out


def check_academic(text: str, student, sizes, path=None, others=None) -> List[Tuple[str, str]]:
    out = []
    # The apostille QR is mandatory here, and each apostille must be followed by the
    # certificate and transcript for the qualification it covers.
    if path is not None:
        try:
            sideways: List[int] = []
            out += PC.academic_check(path, read_pages(path, sideways=sideways))
            if sideways:
                out.append((NOTE, "page(s) " + ", ".join(str(n) for n in sideways) +
                                  " are scanned sideways — they were turned upright to be read, "
                                  "but the student should upload them the right way up"))
        except Exception as e:
            out.append((FLAG, f"could not check the e-Apostille pages ({e})"))
    elif has_any(text, R.APOSTILLE_WORDS):
        out.append((PASS, "e-apostille wording found"))
    else:
        out.append((FAIL, "no e-apostille found — certificate and transcript must be "
                          "apostilled via mygov.bd"))
    if has_any(text, R.PROVISIONAL_WORDS):
        out.append((FAIL, "provisional certificate — not accepted; the original certificate is required"))
    out.append((PASS, "notarised (wording or seal found)") if notarised(text, path)
               else (FLAG, "no notarisation found on the photocopies"))
    # The student's and both parents' names must appear on the academic papers.
    for who, col in (("student", "Full Name"), ("father", "Father"), ("mother", "Mother")):
        name = (student.get(col) or "").strip()
        if not name:
            continue
        parts = [p for p in norm(name).split() if len(p) > 2]
        out.append((PASS, f"{who}'s name ({name}) appears on the academic papers")
                   if parts and any(p in norm(text) for p in parts)
                   else (FLAG, f"{who}'s name '{name}' not found on the academic papers"))
    for label, col in (("HSC", "HSC GPA"), ("SSC", "SSC GPA")):
        gpa = (student.get(col) or "").strip()
        if gpa:
            g = gpa.rstrip("0").rstrip(".")
            out.append((PASS, f"{label} GPA {gpa} matches the portal")
                       if (gpa in text or g in text)
                       else (FLAG, f"portal {label} GPA {gpa} not found in the certificate text"))
    return out


def looks_like_solvency(text: str) -> bool:
    return has_any(text, R.SOLVENCY_WORDS)


def looks_like_statement(text: str) -> bool:
    t = (text or "").lower()
    hits = sum(w in t for w in ("statement", "debit", "credit", "withdrawal", "deposit",
                                "transaction", "balance b/f", "closing balance"))
    return hits >= 2


def document_date(text: str) -> Optional[dt.date]:
    """The date the paper itself carries — the one beside a Date/Issued label if there is
    one, otherwise the latest date on the page."""
    d = issue_date(text)
    if d:
        return d
    dates = sorted(set(find_dates(text)))
    return dates[-1] if dates else None


def opening_balance(text: str) -> Optional[int]:
    """The balance a statement starts from.

    Bangladeshi banks label it differently — Opening Balance, Previous Balance, B/F,
    Brought Forward — and some print no label at all, in which case the balance on the
    first transaction row is the opening figure."""
    for label in R.OPENING_BALANCE_WORDS:
        m = re.search(re.escape(label).replace(r"\ ", r"\s*") + r"\D{0,40}?([\d,]{4,15}(?:\.\d{1,2})?)",
                      text or "", re.I)
        if m:
            v = money_value(m.group(1))
            if v is not None:
                return int(v)
    # no label: take the balance on the first transaction row
    for line in (text or "").splitlines():
        if not re.search(r"\d{1,2}[./-]\w{2,9}[./-]\d{2,4}", line):
            continue                      # not a transaction row
        figures = [money_value(x) for x in re.findall(r"[\d,]{4,15}(?:\.\d{1,2})?", line)]
        figures = [f for f in figures if f is not None and f >= 100]
        if figures:
            return int(figures[-1])       # the running balance is the last figure on the row
    return None


STATEMENT_DATE_LABELS = (
    r"generation\s*date(?:\s*/?\s*time)?", r"print(?:ed)?\s*date(?:\s*&?\s*time)?",
    r"statement\s*date", r"date\s*of\s*issue", r"issue\s*date", r"report\s*date",
    r"run\s*date", r"as\s*on", r"printed\s*on", r"statement\s*printed(?:\s*on)?",
)


def statement_date(pages: List[str]) -> Optional[dt.date]:
    """When the statement was generated — the label the bank prints at the top.

    A statement is full of transaction dates; the only one that means "this document was
    produced on" sits beside Generation Date / Print Date / as on.  Taking any other date
    compares the statement's period against the solvency certificate and reports a
    difference that is not there."""
    for page in pages:
        for label in STATEMENT_DATE_LABELS:
            m = re.search(label + r"\W{0,12}((?:\d{1,2}[\s./-]{1,2}\w{1,9}[\s./-]{1,2}\d{2,4})"
                                  r"|(?:\d{4}[./-]\d{1,2}[./-]\d{1,2}))", page or "", re.I)
            if m:
                found = find_dates(m.group(1))
                if found:
                    return found[0]
    for page in pages:
        m = re.search(r"(?:from\s*date|statement\s*period|period)\W{0,6}"
                      r"(?:\d{1,2}[\s./-]{1,2}\w{1,9}[\s./-]{1,2}\d{2,4})\s*(?:to|-|–)\s*"
                      r"((?:\d{1,2}[\s./-]{1,2}\w{1,9}[\s./-]{1,2}\d{2,4}))", page or "", re.I)
        if m:
            found = find_dates(m.group(1))
            if found:
                return found[0]          # the period end is the as-on date
    return None


def check_bank(text: str, student, sizes, program: str, path=None, others=None) -> List[Tuple[str, str]]:
    out = []
    need = R.MIN_BANK_TAKA[program]
    amounts = find_money_taka(text)
    if amounts:
        top = amounts[0]
        if top >= need:
            out.append((PASS, f"highest amount {top:,} BDT meets the {need:,} BDT minimum"))
        else:
            out.append((FAIL, f"highest amount found is {top:,} BDT — below the {need:,} BDT minimum "
                              f"for {program}"))
    else:
        out.append((FLAG, "no balance amount could be read"))
    # The USD total belongs on the solvency certificate; a statement never carries one.
    if looks_like_solvency(text):
        out.append((PASS, "solvency amount stated in USD") if has_any(text, R.USD_WORDS)
                   else (FLAG, "no USD equivalent found — the solvency certificate must state "
                               "the total in USD"))
    # Any seal and signature will do; only their complete absence is worth reporting.
    has_seal = has_any(text, R.SEAL_WORDS) or (PC.seal_present(path) if path else False)
    out.append((PASS, "carries a seal and signature") if has_seal
               else (FLAG, "no seal or signature of any kind found on the document"))
    opened = None
    m = re.search(r"(open(?:ing)?\s*date|a/c open|account opening date)\D{0,20}"
                  r"(\d{1,2}[./-]\w{3,9}[./-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{4})",
                  text, re.I)
    if m:
        d = find_dates(m.group(2))
        opened = d[0] if d else None
    if opened:
        age = months_between(opened, TODAY)
        if age >= R.BANK_MIN_ACCOUNT_MONTHS:
            out.append((PASS, f"account opened {opened} ({age} months old)"))
        else:
            out.append((FLAG, f"account opened {opened} — only {age} month(s) old; guideline prefers "
                              "6 months or more (embassies query new accounts)"))
    ctx = others if isinstance(others, dict) else {}
    sponsor = (student.get("Sponsor") or "").upper()
    who = {"FATHER": student.get("Father", ""), "MOTHER": student.get("Mother", "")}.get(sponsor, "")
    holder = who or student.get("Full Name", "")

    # The file always has the solvency certificate on page 1 and the statement from
    # page 2 onwards, so the two dates can be read from their own pages rather than
    # guessed out of one merged block of text.
    pages: List[str] = []
    if path is not None:
        try:
            pages = read_pages(path, max_pages=10)
        except Exception as e:
            logger.warning("could not read %s page by page: %s", path.name, e)
    if len(pages) >= 2:
        sol = document_date(pages[0])
        stm = statement_date(pages[1:])
        # FLAG, not FAIL: this rule produced false failures (HANDOFF §5.1) and its rewritten
        # date logic has not yet been proven against real statements (HANDOFF §8.1).
        if sol and stm:
            out.append((PASS, f"solvency certificate and statement both dated {sol}") if sol == stm
                       else (FLAG, f"the solvency certificate is dated {sol} but the statement was "
                                   f"generated on {stm} — they must carry the SAME date"))
        elif sol and not stm:
            out.append((NOTE, f"solvency certificate dated {sol}; the statement's generation "
                              "date could not be read from the scan — compare them by eye"))
        elif stm and not sol:
            out.append((NOTE, f"statement generated {stm}; no date could be read from the "
                              "solvency certificate — compare them by eye"))
        else:
            out.append((NOTE, "neither date could be read — check the solvency certificate and "
                              "the statement carry the same date"))
    elif pages:
        out.append((FLAG, "the bank file has only one page, so it cannot hold both a solvency "
                          "certificate and a statement"))

    if holder:
        ctx["_account_holder"] = holder
        parts = [p for p in norm(holder).split() if len(p) > 2]
        out.append((PASS, f"account appears to be in the name of {holder}")
                   if any(p in norm(text) for p in parts)
                   else (FLAG, f"expected account holder '{holder}' (sponsor: {sponsor or 'unknown'}) "
                               "not found in the document"))
    return out


def current_fiscal_year() -> str:
    """Bangladeshi fiscal year runs July-June, e.g. 2026-2027 from July 2026."""
    y = TODAY.year if TODAY.month >= 7 else TODAY.year - 1
    return f"{y}-{y + 1}"


def taxpayer_name(text: str) -> str:
    """The person a TIN certificate is issued to.

    Bangladeshi TIN certificates carry no "Taxpayer's Name" field.  The name appears in a
    sentence: "This is to Certify that MST. KEYA ANJUM is a Registered Taxpayer of
    National Board of Revenue ...".  Some also print it beside a label, so both are tried.
    """
    patterns = (
        r"certify\s+that\s+([A-Za-z.\s]{4,60}?)\s+is\s+a\s+registered\s+taxpayer",
        r"taxpayer'?s?\s*name\s*[:\-]?\s*([A-Za-z.\s]{4,60})",
        r"name\s+of\s+(?:the\s+)?taxpayer\s*[:\-]?\s*([A-Za-z.\s]{4,60})",
    )
    for pat in patterns:
        m = re.search(pat, text or "", re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip(" .")
    return ""


def proprietor_name(text: str) -> str:
    """The person a trade licence is issued to — "Name of Proprietor / Assesse"."""
    patterns = (
        r"name\s+of\s+proprietor\s*/?\s*(?:assesse|assessee)?\s*[:\-]?\s*([A-Za-z.\s]{4,60}?)"
        r"\s+name\s+of",
        r"name\s+of\s+proprietor\s*/?\s*(?:assesse|assessee)?\s*[:\-]?\s*([A-Za-z.\s]{4,60})",
        r"proprietor\s*[:\-]\s*([A-Za-z.\s]{4,60})",
    )
    for pat in patterns:
        m = re.search(pat, text or "", re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip(" .")
    return ""


def is_tin(text: str) -> bool:
    t = norm(text)
    return "taxpayers identification" in t or "tin certificate" in t or "etin" in t


def check_financial(text: str, student, sizes, path=None, others=None) -> List[Tuple[str, str]]:
    out = []
    t = norm(text)
    ctx = others if isinstance(others, dict) else {}
    sponsor = (student.get("Sponsor") or "").upper()
    holder = {"FATHER": student.get("Father", ""), "MOTHER": student.get("Mother", "")}.get(sponsor, "")
    if sponsor and sponsor not in ("FATHER", "MOTHER"):
        out.append((FLAG, f"portal sponsor is '{sponsor}' — only the applicant's parents may sponsor"))
    # It must be in the name of whoever holds the bank account.
    holder = ctx.get("_account_holder") or holder
    if holder and not is_tin(text):
        parts = [p for p in norm(holder).split() if len(p) > 2]
        out.append((PASS, f"issued in the bank account holder's name ({holder})")
                   if any(p in t for p in parts)
                   else (FLAG, f"bank account holder '{holder}' not found — the Trade Licence/TIN "
                               "should be in the same name as the bank account"))
    kinds = [k for k, w in (("trade licence", "trade licen"), ("TIN certificate", "taxpayer's identification"),
                            ("TIN certificate", "tin certificate"),
                            ("employment certificate", "employment"), ("salary", "salary"))
             if w in t]
    out.append((PASS, "contains: " + ", ".join(sorted(set(kinds)))) if kinds
               else (FLAG, "could not tell which financial document this is"))
    if "trade licen" in t:
        years = re.findall(r"20\d{2}\s*[-–]\s*20\d{2}", text)
        if not years:   # "1st July 2026 to 30th June 2027"
            m2 = re.search(r"(20\d{2})\s*(?:to|till|until|[-–])\s*(?:\d{1,2}\w{0,2}\s+\w+\s+)?(20\d{2})", text, re.I)
            if m2 and int(m2.group(2)) == int(m2.group(1)) + 1:
                years = [f"{m2.group(1)}-{m2.group(2)}"]
        fy = years[0] if years else None
        if fy:
            want = current_fiscal_year()
            norm_fy = re.sub(r"\s|–", lambda m: "" if m.group() != "–" else "-", fy)
            out.append((PASS, f"licence fiscal year {fy} is the current {want}") if norm_fy == want
                       else (FAIL, f"licence fiscal year {fy} is not the current fiscal year ({want})"))
        else:
            out.append((FLAG, "no fiscal year found on the trade licence"))
        m = re.search(r"business start(?:ing)? date\D{0,20}([\d./-]{6,12}|\d{1,2}\s+\w+\s+\d{4})", text, re.I)
        if m:
            d = find_dates(m.group(1))
            if d:
                yrs = (TODAY - d[0]).days / 365.25
                out.append((PASS, f"business started {d[0]} ({yrs:.1f} years ago)") if yrs >= 2
                           else (FLAG, f"business started {d[0]} — under 2 years; older businesses are "
                                       "viewed more positively"))
    if "trade licen" in t:
        out.append((PASS, "trade licence is notarised (wording or seal found)") if notarised(text, path)
                   else (FAIL, "trade licence is not notarised — notarisation is required for it"))
        ctx["_trade_text"] = (ctx.get("_trade_text") or "") + " " + t
    if is_tin(text):
        ctx["_tin_name"] = taxpayer_name(text) or ctx.get("_tin_name", "")

    # One person must hold the bank account, the TIN and the trade licence.  Matching the
    # known account-holder name against each document is far more reliable than trying to
    # lift a name out of two different layouts, so that is the primary test; where both
    # names can be read they are compared to each other as well.
    tin_name = taxpayer_name(text) or ctx.get("_tin_name", "")
    if tin_name:
        ctx["_tin_name"] = tin_name
    prop_name = proprietor_name(text) or ctx.get("_proprietor_name", "")
    if prop_name:
        ctx["_proprietor_name"] = prop_name

    if holder and not ctx.get("_financial_name_done"):
        ctx["_financial_name_done"] = True
        parts = [w for w in norm(holder).split() if len(w) > 2]
        here = norm(text)
        if parts and any(w in here for w in parts):
            out.append((PASS, f"the bank account holder ({holder}) is named on this document"))
        else:
            named = tin_name or prop_name
            out.append((FLAG, f"the bank account holder is '{holder}' but this document is in "
                              + (f"the name of '{named}'" if named else "another name")
                              + " — account, TIN and trade licence should be one person"))

    if tin_name and prop_name and not ctx.get("_tin_vs_trade_done"):
        ctx["_tin_vs_trade_done"] = True
        a = {w for w in norm(tin_name).split() if len(w) > 2}
        b = {w for w in norm(prop_name).split() if len(w) > 2}
        out.append((PASS, f"TIN and trade licence are both in the name of {tin_name}") if a & b
                   else (FLAG, f"the TIN names '{tin_name}' but the trade licence names "
                               f"'{prop_name}' — they should be the same person"))
    return out


def check_income_tax(text: str, student, sizes, program: str, path=None) -> List[Tuple[str, str]]:
    out = []
    amounts = find_money_taka(text)
    paid = [a for a in amounts if a >= R.MIN_TAX_PAID_TAKA]
    if program == "MASTER":
        wealth = [a for a in amounts if a >= R.MIN_NET_WEALTH_TAKA]
        out.append((PASS, f"net wealth figure {wealth[0]:,} BDT meets the 50 lakh guideline") if wealth
                   else (FLAG, "no net wealth of 50 lakh BDT or more found (Master's guideline)"))
    small = [a for a in find_money_taka(text) if a < 1_000_000]
    out.append((PASS, f"tax paid figure found ({small[0]:,} BDT)") if small
               else (FLAG, "no tax paid amount found — at least 10,000 BDT is expected"))
    out.append((PASS, "notarised (wording or seal found)") if notarised(text, path)
               else (FLAG, "income tax papers should be notarised through an advocate"))
    return out


# `p` is the documents already read for this student, so a check can compare against them
# (a birth certificate against the passport, a trade licence against the bank account).
CHECKS = {
    "passport": lambda t, s, z, p, prog, path: check_passport(t, s, z, path),
    "photo": lambda t, s, z, p, prog, path: check_photo(t, s, z, path),
    "birth_cert": lambda t, s, z, p, prog, path: check_birth_cert(t, s, z, path, p),
    "father_nid": lambda t, s, z, p, prog, path: check_nid(t, s, z, "father", path, p),
    "mother_nid": lambda t, s, z, p, prog, path: check_nid(t, s, z, "mother", path, p),
    "student_nid": lambda t, s, z, p, prog, path: check_nid(t, s, z, "student", path, p),
    "family_cert": lambda t, s, z, p, prog, path: check_family_cert(t, s, z, path),
    "academic": lambda t, s, z, p, prog, path: check_academic(t, s, z, path, p),
    "bank": lambda t, s, z, p, prog, path: check_bank(t, s, z, prog, path, p),
    "trade_license": lambda t, s, z, p, prog, path: check_financial(t, s, z, path, p),
    "income_tax": lambda t, s, z, p, prog, path: check_income_tax(t, s, z, prog, path),
}



# --- cross-document consistency (the reviewer's first rule) --------------------------
def name_tokens(name: str) -> List[str]:
    """Meaningful parts of a name: drops titles like MD / MST and initials."""
    skip = {"md", "mst", "most", "mohammad", "mohammed", "sk", "mr", "mrs", "late"}
    return [t for t in norm(name).split() if len(t) > 2 and t not in skip]


def readable(text: str) -> bool:
    """Whether OCR produced usable words. Bangladeshi passport data pages and heavy
    stamps often come out as noise, and a name must not be judged 'missing' on those."""
    words = re.findall(r"[A-Za-z]{3,}", text or "")
    if len(words) < 25:
        return False
    vowelly = sum(1 for w in words if re.search(r"[aeiou]", w, re.I))
    return vowelly / len(words) > 0.6


def name_in(text: str, name: str) -> Optional[bool]:
    """True/False if we can judge, None when the name is unknown."""
    toks = name_tokens(name)
    if not toks:
        return None
    t = norm(text)
    hits = sum(1 for tok in toks if tok in t)
    return hits >= max(1, len(toks) - 1)


def cross_checks(texts: Dict[str, str], student: Dict[str, str]) -> List[Dict[str, Any]]:
    texts = {k: v for k, v in texts.items() if not k.startswith("_") and isinstance(v, str)}
    """Names, DOB and numbers must agree across the identity documents; if they do not,
    an affidavit IN THE APPLICANT'S NAME is required."""
    rows: List[Dict[str, Any]] = []
    people = {"applicant": student.get("Full Name", ""), "father": student.get("Father", ""),
              "mother": student.get("Mother", "")}
    mismatches = []
    for who, name in people.items():
        if not name:
            continue
        missing, unreadable = [], []
        for key in R.IDENTITY_DOCS:
            if key not in texts:
                continue
            if who == "father" and key == "mother_nid":
                continue
            if who == "mother" and key == "father_nid":
                continue
            if who == "applicant" and key in ("father_nid", "mother_nid"):
                continue        # a parent's NID does not carry the applicant's name
            if not readable(texts[key]):
                unreadable.append(R.TITLES.get(key, key))
                continue
            if name_in(texts[key], name) is False:
                missing.append(R.TITLES.get(key, key))
        note = f" (too blurred to read: {', '.join(unreadable)})" if unreadable else ""
        if len(missing) >= 2:       # one document alone is usually an OCR failure
            mismatches.append(f"{who} '{name}' not matched on: {', '.join(missing)}")
            rows.append({"doc": "CROSS-CHECK name", "file": "", "verdict": FLAG,
                         "detail": f"FLAG: {who}'s name '{name}' could not be matched on "
                                   f"{len(missing)} documents: {', '.join(missing)} — check whether the "
                                   f"spelling really differs{note}"})
        elif missing:
            rows.append({"doc": "CROSS-CHECK name", "file": "", "verdict": PASS,
                         "detail": f"PASS: {who}'s name '{name}' consistent (not readable on "
                                   f"{missing[0]} alone){note}"})
        else:
            rows.append({"doc": "CROSS-CHECK name", "file": "", "verdict": PASS,
                         "detail": f"PASS: {who}'s name '{name}' consistent across the identity documents{note}"})

    dob = student.get("DOB", "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob or ""):
        d = dt.date.fromisoformat(dob)
        bad = [R.TITLES.get(k, k) for k in ("passport", "student_nid", "birth_cert", "family_cert")
               if k in texts and readable(texts[k]) and d not in find_dates(texts[k])]
        wrong = [k for k in bad if any(abs((x - d).days) < 4000 and x != d
                                       for x in find_dates(texts.get(k, "")))]
        rows.append({"doc": "CROSS-CHECK date of birth", "file": "", "verdict": FLAG if len(bad) >= 2 else PASS,
                     "detail": (f"FLAG: portal date of birth {d} could not be matched on: {', '.join(bad)}"
                                if len(bad) >= 2 else
                                f"PASS: date of birth {d} consistent" +
                                (f" (not readable on {bad[0]})" if bad else ""))})

    pno = (student.get("Passport No") or "").upper()
    if pno:
        seen = [R.TITLES.get(k, k) for k, t in texts.items() if pno in re.sub(r"\s+", "", t.upper())]
        rows.append({"doc": "CROSS-CHECK passport number", "file": "", "verdict": PASS if seen else FLAG,
                     "detail": (f"PASS: passport number {pno} appears on: {', '.join(seen)}" if seen
                                else f"FLAG: passport number {pno} not found on any document")})

    if mismatches:
        aff = texts.get("affidavit", "")
        if not aff:
            rows.append({"doc": "CROSS-CHECK affidavit", "file": "", "verdict": FLAG,
                         "detail": "FLAG: a name could not be matched across several documents and no "
                                   "affidavit is in the file — if the spellings really differ, an "
                                   "affidavit in the APPLICANT'S name is required (" +
                                   "; ".join(mismatches)[:200] + ")"})
        else:
            ok = name_in(aff, student.get("Full Name", ""))
            rows.append({"doc": "CROSS-CHECK affidavit", "file": "", "verdict": PASS if ok else FAIL,
                         "detail": ("PASS: affidavit is in the applicant's name and covers the name difference"
                                    if ok else
                                    "FAIL: affidavit does not appear to be in the applicant's name — an "
                                    "affidavit in the father's or mother's name is not accepted")})
    return rows


# --- per-student run ----------------------------------------------------------------
def classify(filename: str) -> Optional[str]:
    """Longest matching pattern wins, so "PASSPORT SIZE PHOTO.jpg" is a photo, not a
    passport, and "FATHER NID.pdf" is not mistaken for a student NID."""
    n = norm(filename)
    best, best_len = None, 0
    for key, pats in R.FILE_PATTERNS.items():
        for p in pats:
            if p in n and len(p) > best_len:
                best, best_len = key, len(p)
    return best


def verify_student(folder: Path, student: Dict[str, str], program: str) -> List[Dict[str, Any]]:
    files: Dict[str, List[Path]] = {}
    for f in sorted(folder.iterdir()):
        if f.name.startswith(".") or not f.is_file():
            continue
        key = classify(f.name)
        files.setdefault(key or "other", []).append(f)

    rows: List[Dict[str, Any]] = []
    texts: Dict[str, str] = {}
    for key in R.REQUIRED[program] + R.OPTIONAL:
        title = R.TITLES.get(key, key)
        if key not in files:
            if key in R.REQUIRED[program]:
                rows.append({"doc": title, "file": "", "verdict": MISSING,
                             "detail": "required by the guideline but not uploaded"})
            continue
        for path in files[key]:
            try:
                text, sizes = read_document(path)
            except Exception as e:
                rows.append({"doc": title, "file": path.name, "verdict": FLAG,
                             "detail": f"could not read the file ({e})"})
                continue
            texts[key] = texts.get(key, "") + "\n" + text
            checker = CHECKS.get(key)
            results = checker(text, student, sizes, texts, program, path) if checker else \
                [(PASS, "present (no automatic rule for this document)")]
            if key != "photo":          # the photo has its own image checks
                info = PC.inspect(path)
                results += PC.colour_check(info, key)
                results += PC.qr_check(info, required=key in R.QR_DOCS, text=text)
                results += PC.bangla_check(text)
            worst = FAIL if any(v == FAIL for v, _ in results) else \
                (FLAG if any(v == FLAG for v, _ in results) else PASS)
            rows.append({"doc": title, "file": path.name, "verdict": worst,
                         "detail": " | ".join(f"{v}: {d}" for v, d in results)})
    rows += cross_checks(texts, student)
    return rows


def student_verdict(rows: List[Dict[str, Any]]) -> str:
    if any(r["verdict"] == MISSING for r in rows):
        return "INCOMPLETE"
    if any(r["verdict"] == FAIL for r in rows):
        return "FAIL"
    if any(r["verdict"] == FLAG for r in rows):
        return "REVIEW"
    return "PASS"


# --- finding students and writing the report ---------------------------------------
def student_folders() -> Dict[str, Tuple[Path, str]]:
    """passport -> (folder, folder name) for every downloaded student."""
    out: Dict[str, Tuple[Path, str]] = {}
    for root in DOCS_ROOTS:
        if not root.exists():
            continue
        for prog_dir in root.iterdir():
            if not prog_dir.is_dir():
                continue
            kids = [p for p in prog_dir.iterdir() if p.is_dir()] or []
            targets = kids if kids else []
            if not targets and re.search(r"\(([^)]+)\)$", prog_dir.name):
                targets = [prog_dir]
            for d in targets:
                m = re.match(r"(.*?)\s*\(([^)]+)\)$", d.name)
                if m:
                    out.setdefault(m.group(2).upper(), (d, d.name))
    return out


def portal_students() -> Dict[str, Dict[str, str]]:
    from src.sheets import progress_builder as pb
    out = {}
    for s in pb.fetch_all_students():
        if s.get("Passport No"):
            out[s["Passport No"].upper()] = s
    return out


def program_of(student: Dict[str, str]) -> str:
    from src.sheets import progress_builder as pb
    return pb.program_key_of(student) or "KLP"


def write_report(all_rows: List[Dict[str, Any]], path: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    colours = {"PASS": "C6EFCE", "FLAG": "FFEB9C", "FAIL": "FFC7CE", "MISSING": "F2F2F2",
               "REVIEW": "FFEB9C", "INCOMPLETE": "F2F2F2"}
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Documents"
    ws.append(["Student", "Passport", "Program", "Student verdict", "Document", "File", "Verdict", "Details"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in all_rows:
        ws.append([r["student"], r["passport"], r["program"], r["student_verdict"],
                   r["doc"], r["file"], r["verdict"], r["detail"]])
        ws.cell(row=ws.max_row, column=7).fill = PatternFill("solid", fgColor=colours.get(r["verdict"], "FFFFFF"))
        ws.cell(row=ws.max_row, column=4).fill = PatternFill("solid", fgColor=colours.get(r["student_verdict"], "FFFFFF"))
    ws.freeze_panes = "A2"
    for col, w in zip("ABCDEFGH", (28, 13, 12, 15, 38, 34, 10, 120)):
        ws.column_dimensions[col].width = w

    ws2 = wb.create_sheet("Summary")
    ws2.append(["Student", "Passport", "Program", "Verdict", "Missing", "Fail", "Flag", "Pass"])
    for c in ws2[1]:
        c.font = Font(bold=True)
    seen = {}
    for r in all_rows:
        k = r["passport"]
        s = seen.setdefault(k, {"student": r["student"], "program": r["program"],
                                "verdict": r["student_verdict"], "MISSING": 0, "FAIL": 0, "FLAG": 0, "PASS": 0})
        s[r["verdict"]] = s.get(r["verdict"], 0) + 1
    for k, s in seen.items():
        ws2.append([s["student"], k, s["program"], s["verdict"], s["MISSING"], s["FAIL"], s["FLAG"], s["PASS"]])
        ws2.cell(row=ws2.max_row, column=4).fill = PatternFill("solid", fgColor=colours.get(s["verdict"], "FFFFFF"))
    ws2.freeze_panes = "A2"
    for col, w in zip("ABCDEFGH", (28, 13, 12, 14, 10, 8, 8, 8)):
        ws2.column_dimensions[col].width = w
    wb.save(path)
    return path


def run(passports: List[str], report_name: str = "") -> Tuple[Path, Dict[str, str]]:
    folders, portal = student_folders(), portal_students()
    all_rows, verdicts = [], {}
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    out = REPORT_DIR / (report_name or f"document_check_{stamp}.xlsx")
    for i, pas in enumerate(passports, 1):
        folder = folders.get(pas)
        student = portal.get(pas)
        if not folder or not student:
            logger.warning("skipping %s (folder=%s, portal=%s)", pas, bool(folder), bool(student))
            continue
        program = program_of(student)
        rows = verify_student(folder[0], student, program)
        v = student_verdict(rows)
        verdicts[pas] = v
        name = student.get("Full Name", folder[1])
        print(f"[{i}/{len(passports)}] {name} ({pas}) — {v}")
        for r in rows:
            all_rows.append({**r, "student": name, "passport": pas, "program": program, "student_verdict": v})
        # save after every student, so a run that is interrupted still leaves a usable report
        try:
            write_report(all_rows, out)
        except Exception as e:
            logger.warning("could not write the report yet: %s", e)
    write_report(all_rows, out)
    return out, verdicts


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s  %(message)s")
    ap = argparse.ArgumentParser(description="Verify downloaded student documents against the program guidelines.")
    ap.add_argument("--student", help="name (or part of it) of one student")
    ap.add_argument("--passport", help="passport number of one student")
    ap.add_argument("--all", action="store_true", help="every downloaded student")
    ap.add_argument("--program", help="only this program: KLP | EAP | BACHELOR | MASTER")
    ap.add_argument("--limit", type=int, default=0, help="stop after N students")
    ap.add_argument("--report", default="", help="report file name")
    args = ap.parse_args()

    folders, portal = student_folders(), portal_students()
    if args.passport:
        picks = [args.passport.strip().upper()]
    elif args.student:
        q = norm(args.student)
        picks = [p for p, (d, n) in folders.items() if q in norm(n)]
        if not picks:
            raise SystemExit(f"No downloaded student matches {args.student!r}")
    elif args.all or args.program:
        picks = sorted(folders)
        if args.program:
            key = args.program.strip().upper()
            picks = [p for p in picks if p in portal and program_of(portal[p]) == key]
    else:
        ap.print_help()
        return
    if args.limit:
        picks = picks[:args.limit]
    out, verdicts = run(picks, args.report)
    counts = {}
    for v in verdicts.values():
        counts[v] = counts.get(v, 0) + 1
    print(f"\nchecked {len(verdicts)} student(s): " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"report: {out}")


if __name__ == "__main__":
    main()
