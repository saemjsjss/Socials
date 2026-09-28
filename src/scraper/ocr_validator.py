"""Passport scan checks: the portal's entries against the uploaded scan, read live by local OCR.

How a scan is read (read_passport_scan)
    EasyOCR (on the CPU) reads the whole page, upright first; when no machine-readable zone (MRZ) is
    found it tries the page turned 270, 90 and 180 degrees (PDF pages are often stored sideways, and
    a phone photo puts the MRZ anywhere on the page, not only in its bottom third). The page whose
    MRZ was found also gives the printed text (father, mother, address, the printed passport number
    and name). When no turn of the page shows an MRZ, that is said as it is: the MRZ could not be
    read (a rotated or blurred photo, or not a passport), never "this is not a passport".

What is trusted (parse_mrz_line1, parse_mrz_line2)
    ICAO 9303 TD3: two lines of 44 characters. A line-2 field (passport number, date of birth,
    expiry) is used only when its own check digit agrees; the whole MRZ is "valid" when both lines
    have 44 characters, line 1 is well formed and every line-2 check digit (the composite too)
    agrees. The name (line 1) has no check digit of its own, so it is trusted only in a valid MRZ
    read with fair OCR confidence.

What the verdicts mean (validate_passport_data)
    discrepancies  confirmed differences between the portal and the passport (a check-digit-valid
                   MRZ field that differs, a blank expiry, a name the valid MRZ or the printed page
                   spells differently), plus a scan whose MRZ could not be read at all: things a
                   person must fix or look at. The passport watcher alerts on these.
    uncertain      "check by eye": a one-letter difference on a failed or low-confidence read
                   (possible OCR misread), a field whose check digit failed, a parent's name or an
                   address that only partly matches. Never presented as a portal error.
    verdict        says which fields match, which could not be found on the scan, and which are
                   blank on the portal: "All fields match" only when all seven really matched.

The pre-audited registry of 10 Sep 2026 (AUDIT_REGISTRY) that used to live here, and that /passports
printed as if it were current, is gone: every result comes from the live scan.
"""
import os
import re
import logging
import threading
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import cv2
import numpy as np

logger = logging.getLogger("hangeul.ocr")

MRZ_LINE_LEN = 44               # ICAO 9303 TD3 (passport): two lines of 44 characters
MRZ_MIN_CONF = 0.3              # below this OCR confidence a line-1 read is "low confidence"
OCR_WIDTH = 1600                # pages are read at most this wide...
OCR_MAX_SIDE = 2400             # ...and at most this long
# Upright first; PDF pages are mostly stored turned a quarter (read at 270), then the rest.
ROTATIONS = ((0, None), (270, cv2.ROTATE_90_COUNTERCLOCKWISE), (90, cv2.ROTATE_90_CLOCKWISE),
             (180, cv2.ROTATE_180))
MRZ_UNREADABLE_NOTE = ("couldn't read the MRZ (the photo may be rotated or blurred, or it may not be a "
                       "passport); please check the scan by eye")

FIELD_ORDER = ("name", "dob", "passport_no", "expiry", "father_name", "mother_name", "address")
FIELD_LABELS = {"name": "Name", "dob": "DOB", "passport_no": "Passport No", "expiry": "Expiry",
                "father_name": "Father", "mother_name": "Mother", "address": "Address"}

# Lazy-loaded EasyOCR reader instance
_reader = None

# Audits run in a worker thread (client.py hands validate_passport_data to asyncio.to_thread)
# so the bot's event loop keeps answering Telegram while EasyOCR grinds on the CPU. On the
# loop they could only ever run one at a time; this lock keeps it that way off the loop too:
# the shared EasyOCR reader is loaded once and never used by two threads at once, and a PDF
# scan's <name>_extracted.jpg is never being written by one audit while another reads it.
# Re-entrant, because validate_passport_data holds it while the helpers below take it again.
_ocr_lock = threading.RLock()


def get_ocr_reader():
    """Lazily load the EasyOCR reader with GPU support or CPU fallback."""
    global _reader
    if _reader is None:
        with _ocr_lock:
            if _reader is None:
                try:
                    import easyocr
                    logger.info("Initializing EasyOCR reader for passport verification...")
                    _reader = easyocr.Reader(['en'], gpu=False, verbose=False)
                    logger.info("EasyOCR reader initialized successfully.")
                except Exception as e:
                    logger.error(f"Failed to initialize EasyOCR: {e}")
                    _reader = None
    return _reader


def parse_mrz_date(yymmdd: str, is_expiry: bool = False) -> str:
    """A 6-digit MRZ date YYMMDD as YYYY-MM-DD, or "" when it is not a real calendar date."""
    if not yymmdd or len(yymmdd) < 6 or not yymmdd[:6].isdigit():
        return ""
    yy = int(yymmdd[:2])
    mm = int(yymmdd[2:4])
    dd = int(yymmdd[4:6])

    current_yy = datetime.now().year % 100
    if is_expiry:
        century = 2000 if yy <= current_yy + 40 else 1900
    else:
        century = 2000 if yy <= current_yy else 1900

    year = century + yy
    try:
        date(year, mm, dd)
    except ValueError:
        return ""
    return f"{year:04d}-{mm:02d}-{dd:02d}"


def compute_icao_check_digit(data: str) -> str:
    """Calculate standard ICAO Doc 9303 7-3-1 weighting check digit."""
    if not data:
        return "0"
    weights = [7, 3, 1]
    total = 0
    for idx, char in enumerate(data):
        if char.isdigit():
            val = int(char)
        elif char.isalpha():
            val = ord(char.upper()) - ord('A') + 10
        elif char == '<':
            val = 0
        else:
            val = 0
        total += val * weights[idx % 3]
    return str(total % 10)


def load_passport_image(image_path: str) -> Optional[np.ndarray]:
    """Load passport image from disk, automatically extracting pages if the file is a PDF."""
    if not image_path or not os.path.exists(image_path):
        return None

    if image_path.lower().endswith(".pdf"):
        base, _ = os.path.splitext(image_path)
        extracted_path = f"{base}_extracted.jpg"
        if os.path.exists(extracted_path) and os.path.getsize(extracted_path) > 1000:
            return cv2.imread(extracted_path)

        try:
            import pypdf
            reader = pypdf.PdfReader(image_path)
            for page in reader.pages:
                for image_file_object in page.images:
                    with open(extracted_path, "wb") as fp:
                        fp.write(image_file_object.data)
                    img = cv2.imread(extracted_path)
                    if img is not None:
                        return img
        except Exception as e:
            logger.warning(f"Failed to extract image from PDF {image_path}: {e}")

    return cv2.imread(image_path)


# --------------------------------------------------------------------------- reading the page

def _prepare(img: np.ndarray) -> np.ndarray:
    """The page at the size it is read: at most OCR_WIDTH wide and OCR_MAX_SIDE long."""
    h, w = img.shape[:2]
    if w > OCR_WIDTH:
        img = cv2.resize(img, (OCR_WIDTH, max(1, int(h * OCR_WIDTH / w))), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
    if max(h, w) > OCR_MAX_SIDE:
        s = OCR_MAX_SIDE / max(h, w)
        img = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    return img


def _ocr_items(reader, img: np.ndarray) -> List[Dict[str, Any]]:
    """EasyOCR's reading of one image as [{"text", "conf", "box": (x0, y0, x1, y1)}], in its order.
    A reader that gives bare strings gives items without a confidence or a box."""
    with _ocr_lock:
        raw = reader.readtext(img, detail=1)
    items = []
    for r in raw or []:
        if isinstance(r, str):
            items.append({"text": r, "conf": None, "box": None})
            continue
        box, text = r[0], r[1]
        conf = r[2] if len(r) > 2 else None
        try:
            xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
            bbox = (min(xs), min(ys), max(xs), max(ys))
        except Exception:
            bbox = None
        items.append({"text": str(text), "conf": float(conf) if conf is not None else None, "box": bbox})
    return items


def _clean_mrz(text: str) -> str:
    """OCR text as MRZ characters: upper case, no spaces, '«' as '<<', anything else dropped."""
    t = (text or "").upper().replace("«", "<<").replace("‹", "<")
    return re.sub(r"[^A-Z0-9<]", "", re.sub(r"\s+", "", t))


def _rows(items: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """The items grouped into text lines, top to bottom, each line left to right (a line the OCR
    cut into several pieces is one line again). Items without a box are a line each, in order."""
    if any(it["box"] is None for it in items):
        return [[it] for it in items]
    rows: List[Dict[str, Any]] = []
    for it in sorted(items, key=lambda i: (i["box"][1] + i["box"][3]) / 2):
        cy = (it["box"][1] + it["box"][3]) / 2
        h = max(1.0, it["box"][3] - it["box"][1])
        for row in rows:
            if abs(cy - row["cy"]) <= 0.5 * max(h, row["h"]):
                row["items"].append(it)
                break
        else:
            rows.append({"cy": cy, "h": h, "items": [it]})
    return [sorted(r["items"], key=lambda i: i["box"][0]) for r in rows]


_L1_RE = re.compile(r"P[<KC(]?([A-Z]{3})([A-Z0-9<]*)")
_NAME_DIGITS = str.maketrans("80152", "BOISZ")          # OCR digit confusions in the name field
_TO_DIGIT = str.maketrans("ODQUILZSBGT", "00001125867")  # ...and letter confusions in number fields
_TO_LETTER = str.maketrans("0158264", "OISBZGA")
_SWAPS = {'4': '1', '1': '4', 'O': '0', '0': 'O', 'B': '8', '8': 'B', 'S': '5', '5': 'S', 'Z': '2', '2': 'Z',
          'I': '1', 'D': '0', 'G': '6', '6': 'G'}


def parse_mrz_line1(text: str) -> Optional[Dict[str, Any]]:
    """MRZ line 1 ("P<BGDSURNAME<<GIVEN<NAMES<<<<...") -> {"line1", "line1_ok", "state", "surname",
    "given_name", "full_name", "name_tokens"}, or None when the text is no line 1. line1_ok: exactly
    44 characters, "P", a type, a 3-letter state, then a name of letters and '<' only, with the
    '<<' between surname and given names and nothing but '<' after it."""
    m = _L1_RE.search(text or "")
    if not m or m.start() > 2 or text.count("<") < 2:
        return None
    raw = text[m.start():]
    name_part = m.group(2)
    ok = (len(raw) == MRZ_LINE_LEN and bool(re.fullmatch(r"P[<A-Z][A-Z]{3}[A-Z<]{39}", raw))
          and "<<" in raw[5:]
          and bool(re.fullmatch(r"[A-Z]+(?:<[A-Z]+)*(?:<<[A-Z]+(?:<[A-Z]+)*)?<*", raw[5:])))
    name_part = name_part.translate(_NAME_DIGITS)
    name_part = re.sub(r"[^A-Z<]", "", name_part)
    if "<<" in name_part:
        sur, given = name_part.split("<<", 1)
    else:
        sur, given = name_part, ""
    surname = " ".join(t for t in sur.split("<") if t)
    given_name = " ".join(t for t in given.split("<") if t)
    return {"line1": raw, "line1_ok": ok, "state": m.group(1), "surname": surname, "given_name": given_name,
            "full_name": f"{surname} {given_name}".strip(),
            "name_tokens": [t for t in re.split(r"<+", name_part) if t]}


def _repair_doc_number(raw: str, chk: str) -> Tuple[str, bool]:
    """The passport number field and whether its check digit agrees, trying the usual OCR
    confusions (a Bangladeshi number's leading 'A' read as 4, 8 or 0; one confusable character)."""
    if compute_icao_check_digit(raw) == chk:
        return raw, True
    if raw and raw[0] in "480":
        cand = "A" + raw[1:]
        if compute_icao_check_digit(cand) == chk:
            return cand, True
    for i, c in enumerate(raw):
        if c in _SWAPS:
            cand = raw[:i] + _SWAPS[c] + raw[i + 1:]
            if compute_icao_check_digit(cand) == chk:
                return cand, True
    return raw, False


def _line2_at(seg: str) -> Dict[str, Any]:
    """The TD3 line-2 fields of `seg` read at their fixed positions, with each check digit tested."""
    def digits(s):
        return s.translate(_TO_DIGIT)

    doc_raw, doc_chk = seg[0:9], digits(seg[9:10])
    nat = seg[10:13].translate(_TO_LETTER)
    dob_raw, dob_chk = digits(seg[13:19]), digits(seg[19:20])
    sex = seg[20:21]
    exp_raw, exp_chk = digits(seg[21:27]), digits(seg[27:28])
    pers, pers_chk, comp = seg[28:42], seg[42:43], digits(seg[43:44])
    doc, doc_ok = _repair_doc_number(doc_raw, doc_chk) if len(doc_raw) == 9 and doc_chk.isdigit() else (doc_raw, False)
    dob = parse_mrz_date(dob_raw)
    exp = parse_mrz_date(exp_raw, is_expiry=True)
    dob_ok = bool(dob) and dob_chk.isdigit() and compute_icao_check_digit(dob_raw) == dob_chk
    exp_ok = bool(exp) and exp_chk.isdigit() and compute_icao_check_digit(exp_raw) == exp_chk
    full = len(seg) == MRZ_LINE_LEN
    pers_ok = full and (compute_icao_check_digit(pers) == pers_chk or (set(pers) <= {"<"} and pers_chk in "<0"))
    comp_ok = full and comp.isdigit() and compute_icao_check_digit(
        doc + doc_chk + dob_raw + dob_chk + exp_raw + exp_chk + pers + pers_chk) == comp
    return {
        "line2": seg, "passport_no": doc.replace("<", ""), "passport_no_ok": doc_ok, "check_digit": doc_chk,
        "nationality": nat, "dob": dob, "dob_raw": dob_raw, "dob_ok": dob_ok,
        "sex": "MALE" if sex == "M" else "FEMALE" if sex == "F" else "",
        "expiry": exp, "expiry_raw": exp_raw, "expiry_ok": exp_ok,
        "line2_ok": full and doc_ok and dob_ok and exp_ok and pers_ok and comp_ok,
        "checks": sum((doc_ok, dob_ok, exp_ok, comp_ok)),
    }


# The nationality followed by a date of birth, its check digit and the sex: where line 2's fields
# sit even when the OCR dropped or added a character in the passport number before them.
_L2_ANCHOR_RE = re.compile(r"(?=[A-Z<]{3}[0-9ODQUILZSBGT]{7}[MF<])")


def parse_mrz_line2(text: str) -> Optional[Dict[str, Any]]:
    """MRZ line 2 ("A123456784BGD0602051M3409047...") -> its fields (passport_no, dob, expiry, sex)
    each with an _ok flag (its own check digit agrees), "line2_ok" (44 characters and every check
    digit, the composite too) and "checks" (how many agree); None when no reading of the text has a
    single check digit that agrees. Stray characters in front of the line are skipped, and a
    passport number read a character short or long still leaves the dates readable."""
    text = text or ""
    if len(text) < 28:
        return None
    cands = [_line2_at(text[start:start + MRZ_LINE_LEN]) for start in range(0, min(4, len(text) - 27))]
    for m in _L2_ANCHOR_RE.finditer(text):
        at = m.start() - 10
        if at >= 0:
            cands.append(_line2_at(text[at:at + MRZ_LINE_LEN]))
        else:
            # A passport number read short: the dates can still be read, the number cannot.
            cand = _line2_at(("<" * -at + text)[:MRZ_LINE_LEN])
            if cand["passport_no_ok"]:
                cand.update(passport_no_ok=False, line2_ok=False, checks=cand["checks"] - 1)
            cands.append(cand)
    best = max(cands, key=lambda c: c["checks"])          # the first of the best: the plain reading
    return best if best["checks"] >= 1 else None


def _find_mrz(items: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Set[int]]:
    """The MRZ in one OCR reading of a page -> (its fields, the ids of the items it was read from),
    or (None, empty) when there is none: no line 1, and no line with a line-2 check digit that agrees."""
    rows = _rows(items)
    lines = [("".join(_clean_mrz(i["text"]) for i in row), row) for row in rows]
    l1, l1_at = None, None
    for idx, (_, row) in enumerate(lines):
        pieces = [_clean_mrz(i["text"]) for i in row]
        for k, piece in enumerate(pieces):              # line 1 may follow a stray piece on its row
            if not re.match(r"P[<KC(]?[A-Z]{3}", piece):
                continue
            text = "".join(pieces[k:])
            got = parse_mrz_line1(text) if len(text) >= 20 else None
            if got:
                confs = [i["conf"] for i in row[k:] if i["conf"] is not None]
                got["line1_conf"] = min(confs) if confs else None
                l1, l1_at = got, idx
                break
        if l1:
            break
    l2, l2_row = None, None
    if l1_at is not None:
        for text, row in lines[l1_at + 1:l1_at + 3]:
            got = parse_mrz_line2(text)
            if got:
                l2, l2_row = got, row
                break
    if l2 is None:
        for idx, (text, row) in enumerate(lines):
            if idx == l1_at:
                continue
            got = parse_mrz_line2(text)
            if got and got["checks"] >= 2 and (l2 is None or got["checks"] > l2["checks"]):
                l2, l2_row = got, row
    if l1 is None and l2 is None:
        return None, set()
    used = {id(i) for i in (lines[l1_at][1] if l1_at is not None else [])} | {id(i) for i in (l2_row or [])}
    mrz: Dict[str, Any] = {
        "line1": "", "line1_ok": False, "line1_conf": None, "surname": "", "given_name": "", "full_name": "",
        "name_tokens": [], "line2": "", "passport_no": "", "passport_no_ok": False, "check_digit": "",
        "dob": "", "dob_raw": "", "dob_ok": False, "expiry": "", "expiry_raw": "", "expiry_ok": False,
        "sex": "", "line2_ok": False, "checks": 0,
    }
    if l1:
        mrz.update(l1)
    if l2:
        mrz.update(l2)
    mrz["valid"] = bool(mrz["line1_ok"] and mrz["line2_ok"])
    return mrz, used


def read_passport_scan(image_path: str) -> Dict[str, Any]:
    """One OCR reading of a passport scan -> {"mrz": the MRZ fields or None, "printed": the page's
    other text pieces in reading order, "words": the words printed on the page, "rotation": the turn
    (degrees clockwise) the MRZ was read at, "tried": every turn read, "error": None, or "image" (the
    file cannot be opened as a picture or a PDF with one) or "ocr" (the OCR engine is not available)}.

    The whole page is read upright first, then turned 270, 90 and 180 degrees, until an MRZ is found."""
    out: Dict[str, Any] = {"mrz": None, "printed": [], "words": set(), "rotation": None, "tried": [], "error": None}
    img = load_passport_image(image_path)
    if img is None:
        out["error"] = "image"
        return out
    reader = get_ocr_reader()
    if not reader:
        out["error"] = "ocr"
        return out
    img = _prepare(img)
    first = None
    for angle, turn in ROTATIONS:
        page = img if turn is None else cv2.rotate(img, turn)
        try:
            items = _ocr_items(reader, page)
        except Exception as e:
            logger.error(f"OCR reading failed for {image_path} (turned {angle}): {e}")
            out["error"] = "ocr"
            return out
        out["tried"].append(angle)
        mrz, used = _find_mrz(items)
        if first is None:
            first = items
        if mrz:
            mrz["rotation"] = angle
            printed = [i["text"] for i in items if id(i) not in used]
            out.update(mrz=mrz, printed=printed, rotation=angle,
                       words={w for t in printed for w in re.findall(r"[A-Z]+", t.upper())})
            return out
    out["printed"] = [i["text"] for i in first or []]
    return out


def extract_mrz_from_image(image_path: str) -> Optional[Dict[str, Any]]:
    """The MRZ of a passport scan (read_passport_scan's "mrz"), or None when none could be read."""
    if not image_path or not os.path.exists(image_path):
        return None
    return read_passport_scan(image_path)["mrz"]


def parse_visual_text_lines(lines: List[str]) -> Dict[str, Any]:
    """
    Parse visual personal data and emergency contact text lines extracted from passport scans.
    """
    cleaned = [re.sub(r'\s+', ' ', l.strip()) for l in lines if l.strip()]
    father = ""
    mother = ""
    address = ""
    em_name = ""
    em_rel = ""
    
    # 1. Identify emergency contact section (comes after permanent address)
    em_idx = -1
    for idx, l in enumerate(cleaned):
        if re.search(r'emergency\s+contac', l, re.I) and not re.search(r'personal\s+data', l, re.I):
            em_idx = idx
            break
            
    if em_idx != -1:
        for k in range(em_idx, min(em_idx + 8, len(cleaned))):
            l = cleaned[k]
            if re.search(r'relationship', l, re.I):
                parts = re.split(r'[:\.]', l, maxsplit=1)
                if len(parts) > 1 and len(parts[1].strip()) > 2:
                    em_rel = parts[1].strip().upper()
                elif k + 1 < len(cleaned):
                    em_rel = cleaned[k+1].strip().upper()
            if re.search(r'\bnam[ea]s?\b', l, re.I) and not em_name:
                parts = re.split(r'[:\.]', l, maxsplit=1)
                if len(parts) > 1 and len(parts[1].strip()) > 3:
                    em_name = parts[1].strip()
                elif k + 1 < len(cleaned):
                    em_name = cleaned[k+1].strip()

    limit = em_idx if em_idx != -1 else len(cleaned)
    for i in range(limit):
        l = cleaned[i]
        # Father
        if not father and re.search(r'(?:father[\'’s\$\s]*nam|fathcn\W*nan|fath[a-z]*\s*[\'’s\$\.\s]*nam)', l, re.I):
            parts = re.split(r'[:\.]', l, maxsplit=1)
            v = []
            if len(parts) > 1 and len(parts[1].strip()) > 3:
                v.append(parts[1].strip())
            curr = i + 1
            while curr < limit and len(v) < 2:
                nxt = cleaned[curr]
                if re.search(r'(?:m[o0]th|kotn|guard|addr)', nxt, re.I) or nxt.lower().startswith('mo'):
                    break
                v.append(nxt)
                curr += 1
            if v:
                father = ' '.join(v)
                
        # Mother (handles OCR noise like 'Mo', 'ther$', 'Kotner & Narna')
        if not mother and (re.search(r'(?:m[o0]ther[\'’s\$\s]*nam|kotner|koth)', l, re.I) or l.lower() == 'mo'):
            parts = re.split(r'[:\.]', l, maxsplit=1)
            v = []
            if len(parts) > 1 and len(parts[1].strip()) > 3:
                v.append(parts[1].strip())
            curr = i + 1
            while curr < limit and re.search(r'^(?:ther[\$\.]*|name[\$\.]*)$', cleaned[curr], re.I):
                curr += 1
            while curr < limit and len(v) < 2:
                nxt = cleaned[curr]
                if re.search(r'(?:guard|addr|father)', nxt, re.I):
                    break
                v.append(nxt)
                curr += 1
            if v:
                mother = ' '.join(v)
                
        # Permanent Address
        if not address and re.search(r'perman[a-z]*\s+add?r', l, re.I):
            parts = re.split(r'[:\.]', l, maxsplit=1)
            v = []
            if len(parts) > 1 and len(parts[1].strip()) > 3:
                v.append(parts[1].strip())
            curr = i + 1
            while curr < limit and len(v) < 3:
                v.append(cleaned[curr])
                curr += 1
            if v:
                address = ' '.join(v)

    # Clean characters
    father = re.sub(r'[:;\.,\$]', ' ', father).strip()
    mother = re.sub(r'[:;\.,\$]', ' ', mother).strip()
    address = re.sub(r'[:;\$]', ' ', address).strip()

    # Look for visual passport number in the visual zone (e.g. A00990010)
    visual_pass_no = ""
    for l in cleaned:
        m_vp = re.search(r'\b([A-Z][0-9]{8})\b', l.upper())
        if m_vp and not visual_pass_no:
            visual_pass_no = m_vp.group(1)

    # Corroborate with Emergency Contact if Father/Mother was unclear
    if 'FATHER' in em_rel and em_name:
        if not father or 'VO' in father or len(father) < len(em_name):
            father = em_name
    if 'MOTHER' in em_rel and em_name:
        if not mother or len(mother) < len(em_name):
            mother = em_name

    has_emergency = bool(father or mother or address or em_name or (em_idx != -1))
    return {
        "father": father,
        "mother": mother,
        "address": address,
        "visual_passport_no": visual_pass_no,
        "has_emergency_page": has_emergency,
        "emergency_name": em_name,
        "emergency_rel": em_rel
    }


def extract_visual_fields_from_image(image_path: str) -> Dict[str, Any]:
    """The printed fields of a passport scan (father, mother, address, printed passport number),
    from the page as read_passport_scan turned it to find the MRZ."""
    default_res = {"father": "", "mother": "", "address": "", "visual_passport_no": "", "has_emergency_page": False}
    if not image_path or not os.path.exists(image_path):
        return default_res
    scan = read_passport_scan(image_path)
    if scan["error"]:
        return default_res
    return parse_visual_text_lines(scan["printed"])


# --------------------------------------------------------------------------- comparing names

_HONORIFICS = {"MD", "MST", "MR", "MRS", "MISS", "MOHAMMAD", "MOHAMMED", "MOSTAFA", "LATE"}
_FILLER_LIKE = set("<KCSLEX")       # what the MRZ filler '<' is often read as


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _split_merged(token: str, known: Set[str]) -> Optional[List[str]]:
    """A token that is known names run together, with the '<' between them read as a letter
    ("BELALKHOSSEN" -> BELAL, HOSSEN; "KSYEDASRUBINA" -> SYEDA, RUBINA), or one name with the
    trailing filler read as letters ("RUBINAKKK"); else None. A single name with extra letters in
    front of it ("SAHMED") is no split: that may be a real spelling."""
    n = len(token)
    best: Dict[int, Tuple[int, List[str], int]] = {0: (0, [], -1)}    # pos -> (skips, names, last name end)
    for i in range(n + 1):
        if i not in best:
            continue
        skips, names, last = best[i]
        for k in known:
            if len(k) >= 2 and token.startswith(k, i):
                j = i + len(k)
                cand = (skips, names + [k], j)
                if j not in best or (cand[0], -len(cand[1])) < (best[j][0], -len(best[j][1])):
                    best[j] = cand
        if i < n and token[i] in _FILLER_LIKE:
            cand = (skips + 1, names, last)
            if i + 1 not in best or (cand[0], -len(cand[1])) < (best[i + 1][0], -len(best[i + 1][1])):
                best[i + 1] = cand
    if n not in best or not best[n][1]:
        return None
    skips, names, last = best[n]
    if len(names) >= 2 or (len(names) == 1 and token.startswith(names[0])):
        return names
    return None


def _name_diff(portal_name: str, doc_name: str) -> Dict[str, Any]:
    """How a document's name differs from the portal's, token by token (honorifics like MD set
    aside): "match" (the same names, or one side has extra ones), "near" (every differing name is
    one letter off), or "far"; "overlap" (some name is the same), "differing" (the doc's names that
    differ)."""
    p_all = re.findall(r"[A-Z]+", (portal_name or "").upper())
    d_all = re.findall(r"[A-Z]+", (doc_name or "").upper())
    p_core = [t for t in p_all if t not in _HONORIFICS] or p_all
    d_core = [t for t in d_all if t not in _HONORIFICS] or d_all
    p_set = set(p_core)
    known = p_set | (set(p_all) & _HONORIFICS)          # "SADMANMDBELAL" splits at MD too
    d_split: List[str] = []
    for t in d_core:
        parts = None if t in p_set else _split_merged(t, known)
        d_split.extend(parts or [t])
    d_set = {t for t in d_split if t not in _HONORIFICS} or set(d_split)
    exact = p_set & d_set
    p_rest, d_rest = p_set - exact, d_set - exact
    if not p_rest or not d_rest:
        return {"kind": "match", "overlap": bool(exact), "differing": []}
    left = set(d_rest)
    near = True
    for t in sorted(p_rest):
        c = min(sorted(left), key=lambda x: _levenshtein(t, x), default=None)
        if c is None or _levenshtein(t, c) > 1:
            near = False
            break
        left.discard(c)
    return {"kind": "near" if near else "far", "overlap": bool(exact), "differing": sorted(d_rest)}


def compare_names(portal_name: str, doc_name: str, *, source: str = "scan", trusted: bool = False,
                  printed: Optional[Iterable[str]] = None) -> Tuple[str, str]:
    """Compare a portal name with the name a document shows -> (status, message).

    source "mrz": the MRZ name; `trusted` when it came from a valid MRZ read with fair confidence,
    `printed` the words printed on the page. source "scan": a name read from the printed page (a
    parent's), which no check digit protects.

      MATCH           the same names (a side with extra names, or MD/MST, still matches)
      TYPO, MISMATCH  a confirmed difference: the valid MRZ, or the printed page too, spells it so
      OCR_UNCERTAIN   a one-letter difference on a failed or low-confidence read, or a printed name
                      that only partly matches: a possible OCR misread, check by eye
      NOT_READ        the MRZ name was read too badly to compare: check by eye
      NOT_IN_SCAN / MISSING_PORTAL   nothing to compare on one side"""
    if not doc_name:
        return ("NOT_IN_SCAN", "Not visible on scan")
    if not portal_name:
        return ("MISSING_PORTAL", "Blank on the portal")
    if not re.findall(r"[A-Z]+", doc_name.upper()):
        return ("NOT_READ", "🔎 Couldn't read the name on the scan, check by eye")
    diff = _name_diff(portal_name, doc_name)
    if diff["kind"] == "match":
        return ("MATCH", "✅ Match")
    seen = f"(portal '{portal_name}', {'MRZ read as' if source == 'mrz' else 'scan reads'} '{doc_name}')"
    uncertain = ("OCR_UNCERTAIN", f"🔎 Possible OCR misread, check by eye {seen}")
    if source != "mrz":
        if diff["kind"] == "far" and not diff["overlap"]:
            return ("MISMATCH", f"❌ Mismatch (Portal: '{portal_name}', Doc: '{doc_name}')")
        if diff["kind"] == "far":
            return ("OCR_UNCERTAIN", f"🔎 Partly different, possible OCR misread, check by eye {seen}")
        return uncertain
    words = {w.upper() for w in (printed or ())}
    portal_core = {t for t in re.findall(r"[A-Z]+", portal_name.upper()) if t not in _HONORIFICS}
    if portal_core and portal_core <= words:
        # The page's printed name reads like the portal: the MRZ reading is the odd one out.
        return ("OCR_UNCERTAIN", f"🔎 Possible OCR misread, check by eye {seen}; the printed name reads as on the portal")
    confirmed = bool(diff["differing"]) and set(diff["differing"]) <= words
    if trusted or confirmed:
        how = "" if trusted else " (the printed name spells it the same way)"
        if diff["kind"] == "far" and not diff["overlap"]:
            return ("MISMATCH", f"❌ Mismatch (Portal: '{portal_name}', Doc: '{doc_name}'){how}")
        return ("TYPO", f"⚠️ Typo (Portal: '{portal_name}', Doc: '{doc_name}'){how}")
    if diff["kind"] == "near":
        return uncertain
    return ("NOT_READ", f"🔎 Couldn't read the name reliably from the MRZ, check by eye {seen}")


def compare_address(portal_addr: str, portal_dist: str, doc_addr: str) -> Tuple[str, str]:
    """
    Compare portal address & district against document address text.
    Returns: (status, message). A printed address that only partly matches is "check by eye".
    """
    if not doc_addr:
        return ("NOT_IN_SCAN", "Not visible on scan")
    if not portal_addr and not portal_dist:
        return ("MISSING_PORTAL", "Blank on the portal")

    full_portal = f"{portal_addr} {portal_dist}".upper()
    p_words = set(re.findall(r'[A-Z0-9]{3,}', full_portal))
    d_words = set(re.findall(r'[A-Z0-9]{3,}', doc_addr.upper()))

    overlap = p_words.intersection(d_words)
    dist_clean = portal_dist.upper().strip() if portal_dist else ""

    if (dist_clean and dist_clean in d_words) or len(overlap) >= 2:
        return ("MATCH", "✅ Match")
    elif len(overlap) >= 1:
        return ("PARTIAL_MATCH", f"🔎 Partly matches (found: {', '.join(sorted(overlap))}), check by eye")
    else:
        return ("MISMATCH", f"❌ Mismatch (Portal: '{portal_addr}', Doc: '{doc_addr}')")


# --------------------------------------------------------------------------- the audit

def _result(student_id, status, verdict, *, is_valid=False, fields=None, mrz=None, visual=None,
            discrepancies=None, uncertain=None) -> Dict[str, Any]:
    return {"student_id": student_id, "status": status, "is_valid": is_valid, "fields": fields or {},
            "mrz_data": mrz or {}, "visual_data": visual or {}, "discrepancies": discrepancies or [],
            "uncertain": uncertain or [], "verdict": verdict}


def unchecked_result(student_id: str, reason: str) -> Dict[str, Any]:
    """The result for a passport that could not be checked because the portal could not be read
    (the profile or the scan did not come): status PORTAL_UNREADABLE, no discrepancy (nothing was
    found wrong), and the reason in the verdict."""
    return _result(student_id, "PORTAL_UNREADABLE",
                   f"❌ Couldn't read the portal: {reason}. The passport was not checked.")


def build_verdict(fields: Dict[str, Dict[str, Any]], discrepancies: List[str], uncertain: List[str]) -> str:
    """One line on a checked passport: what differs, what to check by eye, which fields match, which
    could not be found on the scan and which are blank on the portal. "100% Match across All Fields"
    only when all seven fields matched."""
    def labels(*statuses):
        return [FIELD_LABELS[k] for k in FIELD_ORDER if fields.get(k, {}).get("status") in statuses]

    matched = labels("MATCH")
    parts = []
    if discrepancies:
        parts.append(f"⚠️ Discrepancy Found: {'; '.join(discrepancies)}")
    if uncertain:
        parts.append(f"🔎 Check by eye: {'; '.join(uncertain)}")
    if len(matched) == len(FIELD_ORDER):
        parts.append("✅ 100% Match across All Fields (Name, DOB, Passport No, Expiry, Father, Mother, Address)")
    elif matched:
        parts.append(f"✅ Match: {', '.join(matched)}")
    if labels("NOT_IN_SCAN"):
        parts.append(f"ℹ️ Not on the scan: {', '.join(labels('NOT_IN_SCAN'))}")
    if labels("MISSING_PORTAL"):
        parts.append(f"ℹ️ Blank on the portal: {', '.join(labels('MISSING_PORTAL'))}")
    return " · ".join(parts) or "ℹ️ Nothing could be compared"


def validate_passport_data(
    student_id: str,
    form_data: Dict[str, Any],
    image_path: Optional[str] = None,
    live_audit: bool = True
) -> Dict[str, Any]:
    """Cross-check a student's portal entries against the passport scan (see
    _validate_passport_data). Safe to call from any thread: audits run one at a time.
    Every audit reads the scan itself (live_audit is kept for old callers; there is no stored
    registry to fall back on)."""
    with _ocr_lock:
        return _validate_passport_data(student_id, form_data, image_path)


def _date_field(portal: str, read: str, ok: bool, label: str) -> Tuple[str, str]:
    """A portal date against the MRZ's: MATCH, MISMATCH (a check-digit-valid MRZ date that differs),
    NOT_READ (the check digit failed and the read does not equal the portal) or MISSING_PORTAL."""
    if not portal:
        return "MISSING_PORTAL", "Blank on the portal"
    if ok:
        if portal == read:
            return "MATCH", "✅ Match"
        return "MISMATCH", f"{label} mismatch: Portal has '{portal}', MRZ has '{read}'"
    if read and portal == read:
        return "MATCH", "✅ Match"
    return "NOT_READ", f"{label}: couldn't read it reliably from the MRZ (check digit failed), check by eye"


def _validate_passport_data(student_id: str, form_data: Dict[str, Any], image_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Comprehensive cross-check of student portal entries against the passport document, read live:
    - DOB, Passport Number, Expiry (MRZ line 2, each by its check digit), Full Name (MRZ line 1)
    - Father's Name, Mother's Name, Permanent Address (the printed page)
    """
    if not image_path or not os.path.exists(image_path):
        return _result(student_id, "MISSING_DOCUMENT", "⏳ Pending Passport Scan (No document on file)",
                       discrepancies=["No passport document scan uploaded on file"])

    scan = read_passport_scan(image_path)
    if scan["error"] == "ocr":
        return _result(student_id, "OCR_UNAVAILABLE",
                       "❌ Couldn't run the OCR engine on this computer, so the scan was not checked")
    if scan["error"] == "image":
        note = "couldn't open the uploaded file as a picture or a PDF with a picture in it; please check it by eye"
        return _result(student_id, "SCAN_UNREADABLE", f"🔎 Scan not readable: {note}", discrepancies=[note])
    mrz = scan["mrz"]
    if not mrz:
        return _result(student_id, "MRZ_UNREADABLE", f"🔎 MRZ not read: {MRZ_UNREADABLE_NOTE}",
                       mrz={"tried_rotations": scan["tried"]}, discrepancies=[MRZ_UNREADABLE_NOTE])

    visual = parse_visual_text_lines(scan["printed"])
    words = scan["words"]
    discrepancies: List[str] = []
    uncertain: List[str] = []

    # Passport Number: the MRZ's, trusted by its check digit
    f_pass = (form_data.get("passport_no") or form_data.get("passport_number", "") or "").strip().upper()
    doc_pass = mrz.get("passport_no", "").strip().upper()
    vis_pass = visual.get("visual_passport_no", "").strip().upper()
    chk_digit = mrz.get("check_digit", "")
    pass_ok = bool(mrz.get("passport_no_ok"))
    agrees_with_check = bool(f_pass) and chk_digit.isdigit() and compute_icao_check_digit(f_pass) == chk_digit
    if not f_pass:
        pass_status, pass_verdict = "MISSING_PORTAL", "Blank on the portal"
    elif doc_pass == f_pass or vis_pass == f_pass:
        pass_status, pass_verdict = "MATCH", "✅ Match"
    elif agrees_with_check and doc_pass and _levenshtein(f_pass, doc_pass) <= (1 if pass_ok else 2):
        # The portal's number fits the MRZ check digit and the read differs by an OCR slip
        # (e.g. the leading 'A' read as a digit of the same check value).
        pass_status, pass_verdict = "MATCH", "✅ Match (MRZ check digit)"
    elif pass_ok:
        pass_status = "MISMATCH"
        pass_verdict = f"Passport No mismatch: Portal has '{f_pass}', Doc has '{doc_pass}'"
        discrepancies.append(pass_verdict)
    else:
        pass_status = "NOT_READ"
        pass_verdict = "Passport No: couldn't read it reliably from the MRZ (check digit failed), check by eye"
        uncertain.append(pass_verdict)

    # DOB
    f_dob = (form_data.get("dob", "") or "").strip()
    dob_status, dob_verdict = _date_field(f_dob, mrz.get("dob", ""), bool(mrz.get("dob_ok")), "DOB")
    if dob_status == "MISMATCH":
        discrepancies.append(dob_verdict)
    elif dob_status == "NOT_READ":
        uncertain.append(dob_verdict)

    # Expiry
    f_exp = (form_data.get("passport_expiry", "") or "").strip()
    if not f_exp:
        exp_status = "INCOMPLETE"
        said = f"MRZ says {mrz['expiry']}" if mrz.get("expiry_ok") else "the MRZ expiry could not be read"
        exp_verdict = f"⚠️ Incomplete: Expiry date left blank on portal ({said})"
        discrepancies.append(exp_verdict)
    else:
        exp_status, exp_verdict = _date_field(f_exp, mrz.get("expiry", ""), bool(mrz.get("expiry_ok")), "Expiry")
        if exp_status == "MISMATCH":
            exp_status = "DATE_MISMATCH"
            discrepancies.append(exp_verdict)
        elif exp_status == "NOT_READ":
            uncertain.append(exp_verdict)

    # Name (MRZ line 1)
    f_name = (form_data.get("name") or form_data.get("full_name", "") or "").strip().upper()
    trusted = bool(mrz.get("valid")) and (mrz.get("line1_conf") is None or mrz["line1_conf"] >= MRZ_MIN_CONF)
    if not f_name:
        name_status, name_verdict = "MISSING_PORTAL", "Blank on the portal"
    elif not mrz.get("full_name"):
        # Every passport has the name line: not found means not read, never "not on the scan".
        name_status, name_verdict = "NOT_READ", "🔎 Couldn't read MRZ line 1 (the name), check by eye"
    else:
        name_status, name_verdict = compare_names(f_name, mrz["full_name"], source="mrz", trusted=trusted,
                                                  printed=words)
    if name_status in ["TYPO", "MISMATCH"]:
        discrepancies.append(f"Name spelling issue: Portal has '{f_name}', MRZ has '{mrz['full_name']}'"
                             + (" (the printed name spells it the same way)" if "printed name spells" in name_verdict else ""))
    elif name_status in ("OCR_UNCERTAIN", "NOT_READ"):
        uncertain.append(f"Name: {name_verdict.lstrip('🔎 ')}")

    # Father's and Mother's Name (the printed page)
    parents = {}
    for key, label in (("father_name", "Father's Name"), ("mother_name", "Mother's Name")):
        portal = (form_data.get(key, "") or "").strip()
        doc = visual.get(key.split("_")[0], "")
        status, verdict = compare_names(portal, doc, source="scan")
        if status == "MISMATCH":
            discrepancies.append(f"{label} discrepancy: Portal has '{portal}', Doc has '{doc}'")
        elif status in ("OCR_UNCERTAIN", "NOT_READ"):
            uncertain.append(f"{label}: {verdict.lstrip('🔎 ')}")
        parents[key] = (portal, doc, status, verdict)

    # Address
    f_addr = (form_data.get("address", "") or "").strip()
    f_dist = (form_data.get("district", "") or "").strip()
    addr_status, addr_verdict = compare_address(f_addr, f_dist, visual.get("address", ""))
    if addr_status == "MISMATCH":
        discrepancies.append(f"Address mismatch: Portal has '{f_addr}', Doc has '{visual['address']}'")
    elif addr_status == "PARTIAL_MATCH":
        uncertain.append(f"Address: {addr_verdict.lstrip('🔎 ')}")

    fields = {
        "name": {"portal": f_name, "doc": mrz.get("full_name", ""), "status": name_status, "verdict": name_verdict},
        "passport_no": {"portal": f_pass, "doc": doc_pass or vis_pass, "status": pass_status, "verdict": pass_verdict},
        "dob": {"portal": f_dob, "doc": mrz.get("dob", ""), "status": dob_status, "verdict": dob_verdict},
        "expiry": {"portal": f_exp, "doc": mrz.get("expiry", ""), "status": exp_status, "verdict": exp_verdict},
        "father_name": dict(zip(("portal", "doc", "status", "verdict"), parents["father_name"])),
        "mother_name": dict(zip(("portal", "doc", "status", "verdict"), parents["mother_name"])),
        "address": {"portal": f_addr, "district": f_dist, "doc": visual.get("address", ""), "status": addr_status,
                    "verdict": addr_verdict},
    }

    if discrepancies:
        status = "TYPO" if any("Typo" in d or "spelling" in d for d in discrepancies) else "DISCREPANCY"
    elif uncertain:
        status = "CHECK_BY_EYE"
    else:
        status = "MATCH"
    return _result(student_id, status, build_verdict(fields, discrepancies, uncertain), is_valid=not discrepancies,
                   fields=fields, mrz=mrz, visual=visual, discrepancies=discrepancies, uncertain=uncertain)
