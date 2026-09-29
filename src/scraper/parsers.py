import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup

logger = logging.getLogger("hangeul.parsers")


def _label_key(text: str) -> str:
    """A label compared by meaning: case, spacing, punctuation and a plural last word do not
    matter, so "Pending payment", "pending  Payments" and "Pending-payment" are the same."""
    words = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split()
    if words and len(words[-1]) > 3 and words[-1].endswith("s") and not words[-1].endswith(("ss", "us", "is")):
        words[-1] = words[-1][:-1]
    return " ".join(words)


def _int_or_none(text: str) -> Optional[int]:
    """A tile's figure as a number ("1,234" -> 1234), or None when it is not a plain number."""
    t = (text or "").strip()
    return int(t.replace(",", "")) if re.fullmatch(r"\d[\d,]*", t) else None

def extract_csrf_token(html: str) -> Optional[str]:
    """Extract CSRF token from HTML form inputs."""
    soup = BeautifulSoup(html, "html.parser")
    
    # Check for name="_csrf"
    csrf_input = soup.find("input", {"name": "_csrf"})
    if csrf_input and csrf_input.get("value"):
        return csrf_input.get("value")
        
    # Check for name="csrf_token" or similar variants
    for name in ["csrf_token", "token", "_token", "csrf"]:
        input_tag = soup.find("input", {"name": name})
        if input_tag and input_tag.get("value"):
            return input_tag.get("value")
            
    # Check meta tags
    meta_tag = soup.find("meta", {"name": "csrf-token"})
    if meta_tag and meta_tag.get("content"):
        return meta_tag.get("content")
        
    return None

def parse_tables(html: str) -> List[Dict[str, Any]]:
    """Parse all HTML tables into structured records."""
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    results = []
    
    for idx, table in enumerate(tables):
        table_id = table.get("id") or f"table_{idx+1}"
        headers = []
        
        # Extract headers from <th> or the first <tr>
        thead = table.find("thead")
        if thead:
            headers = [th.get_text(strip=True) for th in thead.find_all("th")]
        if not headers:
            first_row = table.find("tr")
            if first_row:
                headers = [th.get_text(strip=True) for th in first_row.find_all(["th", "td"])]
                
        # Clean header names
        cleaned_headers = [h if h else f"col_{i+1}" for i, h in enumerate(headers)]
        
        # Extract rows
        rows = []
        tbody = table.find("tbody") or table
        for tr in tbody.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells or (cells and [c.get_text(strip=True) for c in cells] == headers):
                continue
                
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            if any(cell_texts):  # Skip completely empty rows
                row_dict = {}
                for i, cell_val in enumerate(cell_texts):
                    key = cleaned_headers[i] if i < len(cleaned_headers) else f"col_{i+1}"
                    row_dict[key] = cell_val
                rows.append(row_dict)
                
        results.append({
            "table_id": table_id,
            "columns": cleaned_headers,
            "row_count": len(rows),
            "rows": rows
        })
        
    return results

def parse_dashboard_metrics(html: str) -> Dict[str, Any]:
    """Parse statistics cards, counts, and KPI elements from dashboard HTML."""
    soup = BeautifulSoup(html, "html.parser")
    metrics = {}
    
    # Search common card structures (.card, .stat, .metric, .box, .counter)
    cards = soup.find_all(class_=lambda c: c and any(w in c.lower() for w in ["card", "stat", "metric", "counter", "widget"]))
    for card in cards:
        title_tag = card.find(["h3", "h4", "h5", "h6", "label", "span", "p"])
        val_tag = card.find(class_=lambda c: c and any(w in c.lower() for w in ["value", "count", "num", "number", "bold"]))
        if not val_tag:
            # Look for large text / numbers inside card
            val_candidates = card.find_all(["h2", "h1", "b", "strong"])
            if val_candidates:
                val_tag = val_candidates[0]
                
        if title_tag and val_tag and title_tag != val_tag:
            key = title_tag.get_text(strip=True)
            val = val_tag.get_text(strip=True)
            if key and val:
                metrics[key] = val
                
    # Search for alert boxes or warning messages
    alerts = []
    alert_elements = soup.find_all(class_=lambda c: c and any(w in c.lower() for w in ["alert", "notice", "error", "warning"]))
    for a in alert_elements:
        text = a.get_text(strip=True)
        if text:
            alerts.append(text)
            
# summary key -> (the dashboard tile's label, a part of the page the tile links to). The label is
# what the portal prints; the link tells apart the two "Docs to review" tiles (window documents in
# review_queue.php, student documents in students.php). Nothing is relabelled: "Accepted" is the
# accepted window applications, not visas (the dashboard has no visa figure).
_DASHBOARD_TILES = {
    "open_windows": ("Open windows", "admission_windows"),
    "draft_windows": ("Draft windows", "admission_windows"),
    "submitted_window_apps": ("Submitted apps", "window_applications"),
    "window_apps_under_review": ("Under review", "window_applications"),
    "window_docs_to_review": ("Docs to review", "review_queue"),
    "window_apps_accepted": ("Accepted", "window_applications"),
    "total_students": ("Total students", "students.php"),
    "pending_payment": ("Pending payment", "students.php"),
    "verified_students": ("Verified", "students.php"),
    "students_docs_to_review": ("Docs to review", "students.php"),
    "admitted": ("Admitted", "students.php"),
}


def _dashboard_tiles(soup) -> List[Dict[str, Any]]:
    """Every figure tile on index.php: {"group", "label", "value" (int or None), "text", "href"}."""
    tiles = []
    cards = soup.find_all(class_="stat-card")
    for card in cards:
        num, lbl = card.find(class_="stat-num"), card.find(class_="stat-lbl")
        if not (num and lbl):
            continue
        link = card if card.get("href") else card.find_parent("a")
        row = card.find_parent(class_="stats-row")
        sec = row.find_previous_sibling(class_="dash-sec") if row else None
        head = (sec.select_one(".ds-t") or sec) if sec else None
        text = num.get_text(strip=True)
        tiles.append({"group": head.get_text(" ", strip=True) if head else "",
                      "label": lbl.get_text(" ", strip=True), "value": _int_or_none(text), "text": text,
                      "href": (link.get("href") if link else "") or ""})
    if not cards:       # an older layout: numbers and labels side by side in a row
        for row in soup.find_all(class_="stats-row"):
            nums = [n.get_text(strip=True) for n in row.find_all(class_="stat-num")]
            lbls = [x.get_text(" ", strip=True) for x in row.find_all(class_="stat-lbl")]
            tiles += [{"group": "", "label": lb, "value": _int_or_none(n), "text": n, "href": ""}
                      for n, lb in zip(nums, lbls)]
    return tiles


def _tile_value(tiles: List[Dict[str, Any]], label: str, href_part: str) -> Optional[int]:
    """The figure of the tile with this label (case, spaces and a plural do not matter); when two
    summary keys share a label, the tile's link decides. None when no single tile matches."""
    key = _label_key(label)
    same = [t for t in tiles if _label_key(t["label"]) == key]
    shared = sum(1 for lab, _ in _DASHBOARD_TILES.values() if _label_key(lab) == key) > 1
    if len(same) == 1 and not shared:
        return same[0]["value"]
    linked = [t for t in same if href_part in t["href"]]
    return linked[0]["value"] if len(linked) == 1 else None


def parse_hangeul_live_dashboard(html: str) -> Dict[str, Any]:
    """The live figures on index.php, exactly as its tiles show them.

    Tiles are matched by label without regard to case or spacing (the portal prints "Total
    students", "Pending payment"...). A figure the page does not show is None, never a stand-in
    number: the brief and /stats then say "not available"."""
    from datetime import datetime
    soup = BeautifulSoup(html, "html.parser")
    tiles = _dashboard_tiles(soup)

    # label -> figure as printed. A label used by two tiles ("Docs to review") gets its group too.
    counts: Dict[str, int] = {}
    for t in tiles:
        counts[_label_key(t["label"])] = counts.get(_label_key(t["label"]), 0) + 1
    stats = {}
    for t in tiles:
        name = t["label"]
        if counts[_label_key(name)] > 1:
            name = f"{name} ({t['group'] or t['href'] or 'tile'})"
        stats[name] = t["text"]

    summary: Dict[str, Any] = {key: _tile_value(tiles, label, hint)
                               for key, (label, hint) in _DASHBOARD_TILES.items()}
    # The older names some commands still read: the same tiles, never other figures.
    summary["total_applicants"] = summary["total_students"]
    summary["pending_document_verification"] = summary["students_docs_to_review"]

    # Recent activities from window activity
    recent_activity = []
    for a in soup.find_all("a", href=lambda h: h and "window_application_view" in h):
        txt = a.get_text(" · ", strip=True)
        recent_activity.append(txt)

    return {
        "status": "success",
        "portal": "Hangeul Korean Language & Visa - Live Portal",
        "last_synced": datetime.now().isoformat(),
        "summary": summary,
        "live_stats": stats,
        "tiles": tiles,
        "recent_activity": recent_activity[:5]
    }

# --------------------------------------------------------------------------- students.php

# The stage the portal's own dashboard counts as "Admitted": its Admitted tile links to
# students.php?stage=Admitted+%2F+Completed (index.php, Sep 2026). A student's stage is the first
# line of the list's "Stage · Applied" column (the same as the row's own stage select).
ADMITTED_STAGE = "Admitted / Completed"

# The list's columns, found by the header's own names ('', SL, Student, University,
# Program · Intake, Docs, Payment, Stage · Applied, ''), never by position.
_STUDENT_COLUMNS = (("sl", ("sl",)), ("student", ("student",)), ("university", ("universit",)),
                    ("program", ("program",)), ("docs", ("doc",)), ("payment", ("payment",)),
                    ("stage", ("stage",)))
_REQUIRED_STUDENT_COLUMNS = ("sl", "student", "program", "stage")
_PAGER_RE = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)(?:\s*·\s*([\d,]+)\s+students?)?", re.I)
_UID_RE = re.compile(r"student_edit\.php\?id=(\d+)")
_EMAIL_HIDDEN_RE = re.compile(r"\[email\s*protected\]", re.I)
_HNG_RE = re.compile(r"HNG-\d{4}-\d+")
_STAMP_TEXT = r"\d{1,2}\s+[A-Za-z]{3,9}\.?(?:\s+\d{4})?(?:,\s*\d{1,2}:\d{2})?"
_VERIFIED_BY_RE = re.compile(rf"Payment verified by\s+([^·\n]{{1,80}}?)\s*·\s*({_STAMP_TEXT})", re.I)
_PAID_RE = re.compile(r"Paid:\s*([\d,]+\.?\d*\s*BDT)\s*([A-Za-z][A-Za-z\s\-]*?)?\s*(?:Verified|$)")
_INCOME_RE = re.compile(r"Verified income:\s*([\d,]+\.?\d*\s*BDT)")


class StudentListLayoutError(ValueError):
    """students.php was read but its layout is not the one the parser knows (no table, a header
    without the Student / Stage columns, rows it cannot read): the caller says "not available"."""


def _blank(text: str) -> str:
    """The portal's "—" (nothing there) as "", any other text as it is."""
    text = re.sub(r"\s+", " ", text or "").strip()
    return "" if text in ("—", "-", "–") else text


def student_pager(html: str) -> Dict[str, Optional[int]]:
    """The list's pager, "Page 1 of 7 · 330 students" -> {"page": 1, "pages": 7, "total": 330};
    each None when the page does not say (a list of one page has no pager)."""
    m = _PAGER_RE.search(html or "")
    if not m:
        return {"page": None, "pages": None, "total": None}
    return {"page": int(m.group(1)), "pages": int(m.group(2)),
            "total": int(m.group(3).replace(",", "")) if m.group(3) else None}


def student_uids(html: str) -> List[str]:
    """The portal user ids of the students on one students.php page, in order, each once (from each
    row's student_edit.php?id=N link). A regex, not a parse: cheap enough for every page read."""
    return list(dict.fromkeys(_UID_RE.findall(html or "")))


def _student_details(tr) -> Dict[str, Any]:
    """The fields of one student's details row (the .xp-row under the list row)."""
    text = tr.get_text(" ", strip=True) if tr is not None else ""
    details: Dict[str, str] = {}
    files: List[str] = []
    uid = ""
    by = stamp = paid = method = income = ""
    stamp_text = text
    if tr is not None:
        for item in tr.select(".det-item"):
            label, value = item.find("label"), item.find("span")
            if label is not None and value is not None:
                details.setdefault(label.get_text(" ", strip=True), _blank(value.get_text(" ", strip=True)))
        html = str(tr)
        m = _UID_RE.search(html) or re.search(r"showDel\((\d+)", html) or re.search(r"progress\.php\?uid=(\d+)", html)
        uid = m.group(1) if m else ""
        files = list(dict.fromkeys(re.findall(r"view_doc\.php\?f=([^\"'&\s<>]+)", html)))

        def pf(selector: str, label: str = "") -> str:
            el = tr.select_one(selector)
            return el.get_text(" ", strip=True).replace(label, "", 1).strip() if el is not None else ""

        paid, method, income = pf(".pf.paid", "Paid:"), pf(".pf.method"), pf(".pf.verified", "Verified income:")
        pf_by = tr.select_one(".pf-by")
        if pf_by is not None:                # the stamp's own element, not any text in the row
            stamp_text = pf_by.get_text(" ", strip=True)
            strong = pf_by.find(["strong", "b"])
            by = strong.get_text(" ", strip=True) if strong is not None else ""
    # "Payment verified by NAME · 27 Sep, 17:19"
    m = _VERIFIED_BY_RE.search(stamp_text)
    if m:
        by, stamp = by or m.group(1).strip(), m.group(2).strip()
    if not paid:
        m = _PAID_RE.search(text)
        if m:
            paid, method = m.group(1), method or (m.group(2) or "").strip()
    if not income:
        m = _INCOME_RE.search(text)
        income = m.group(1) if m else ""
    applied = details.get("Applied On") or details.get("Applied on") or ""
    if not applied:
        m = re.search(r"Applied On\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4}(?:,\s*\d{1,2}:\d{2})?)", text, re.I)
        applied = m.group(1) if m else ""
    return {"uid": uid, "details": details, "files": files, "details_text": text,
            "verified_line": bool(re.search(r"Payment verified by\b", stamp_text, re.I)),
            "verified_by": by, "verified_stamp": stamp, "paid": paid, "method": method,
            "verified_income": income, "applied_on": applied}


def parse_students_page(html: str) -> Dict[str, Any]:
    """One students.php page, read by the header's column names -> {"students": [...], "empty":
    bool (the list's own "No students found" row), "page", "pages", "total" (student_pager)}.

    Each student is one list row (.stu-row) and its details row (.xp-row) under it:
      uid           the portal user id (student_edit.php?id=N), "" when the row has no link
      student_id    the HNG id ("HNG-2026-931"), "" before one is given; "id" is the same (older name)
      student_name  the Student column's name; sl, the row's SL number
      target_university, program, target_intake, docs_status, payment_status: the columns as
                    shown ("" where the portal shows "—"; the university is the cell's own .stu-uni
                    line); status = the stage ("Payment Verified"), applied_date = the day under it
                    ("28 Sep 2026")
      applications  the University cell's application lines, each as shown ("Applied: Kyungsung
                    University · Bachelor's Degree"); [] when it has none
      details       {label: value} of the details row's fields (first of each label), files (the
                    view_doc.php files: passport_..., receipt_...), details_text (its text)
      verified_by, verified_stamp ("27 Sep, 17:19" as printed, no year), paid, method,
                    verified_income, applied_on ("27 Sep 2026, 17:16"): "" when absent;
                    verified_line: whether the row has a "Payment verified by" line at all (so a
                    line whose stamp cannot be read is told apart from no line)
    Nothing is filled in: a field the portal does not show is "". Raises StudentListLayoutError
    when the page has no student table, its header lacks the SL / Student / Program / Stage
    columns, or it has rows none of which can be read."""
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find("table")
    if table is None:
        raise StudentListLayoutError("students.php has no student table")
    rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    header = next((tr for tr in rows if tr.find("th") is not None), None)
    if header is None:
        raise StudentListLayoutError("the student table has no header row")
    names = [_label_key(c.get_text(" ", strip=True)) for c in header.find_all(["th", "td"], recursive=False)]
    col: Dict[str, int] = {}
    for key, words in _STUDENT_COLUMNS:
        for i, name in enumerate(names):
            if i not in col.values() and any(name.startswith(w) for w in words):
                col[key] = i
                break
    missing = [k for k in _REQUIRED_STUDENT_COLUMNS if k not in col]
    if missing:
        raise StudentListLayoutError(f"the student table's header has no {', '.join(missing)} column "
                                     f"(it reads {[n for n in names if n]})")

    students: List[Dict[str, Any]] = []
    empty = unread = 0
    current = None
    for tr in rows:
        if tr is header:
            continue
        cls = tr.get("class") or []
        cells = tr.find_all(["td", "th"], recursive=False)
        sl_text = cells[col["sl"]].get_text(strip=True) if len(cells) > col["sl"] else ""
        if len(cells) == len(names) and sl_text.isdigit():
            current = _student_row(cells, col, sl_text)
            students.append(current)
        elif "xp-row" in cls or (current is not None and current.get("_open") and len(cells) == 1):
            if current is not None and current.get("_open"):
                current.update(_student_details(tr))
                current["_open"] = False
        elif "empty-row" in cls or (len(cells) == 1 and re.search(r"\bno\s+students?\b", tr.get_text(" "), re.I)):
            empty += 1
        elif cells and any(c.get_text(strip=True) for c in cells):
            unread += 1
    for s in students:
        if s.pop("_open", False):
            s.update(_student_details(None))
    if unread:
        raise StudentListLayoutError(f"the student table has {unread} row(s) the parser cannot read")
    return {"students": students, "empty": bool(empty) and not students, **student_pager(html)}


def _main_and_sub(c) -> Tuple[str, str]:
    """A cell's own text and the small line under it (.stu-sub): "KLP" / "MARCH 2027", or
    "Payment Verified" / "28 Sep 2026". Without a .stu-sub, its first two lines."""
    if c is None:
        return "", ""
    sub = c.select_one(".stu-sub")
    if sub is not None:
        own = " ".join(t.strip() for t in c.find_all(string=True, recursive=False) if t.strip())
        return _blank(own), _blank(sub.get_text(" ", strip=True))
    lines = list(c.stripped_strings)
    return (_blank(lines[0]) if lines else ""), (_blank(lines[1]) if len(lines) > 1 else "")


def _student_row(cells, col: Dict[str, int], sl: str) -> Dict[str, Any]:
    """The list row's own columns (see parse_students_page)."""
    def cell(key):
        i = col.get(key)
        return cells[i] if i is not None and i < len(cells) else None

    def text(key) -> str:
        c = cell(key)
        return _blank(c.get_text(" ", strip=True)) if c is not None else ""

    student = cell("student")
    name_el = student.select_one(".stu-name") if student is not None else None
    if name_el is not None:
        name = _blank(_EMAIL_HIDDEN_RE.sub("", name_el.get_text(" ", strip=True)))
    else:
        lines = [_blank(_EMAIL_HIDDEN_RE.sub("", s)) for s in (student.stripped_strings if student is not None else [])]
        name = next((s for s in lines if s and not _HNG_RE.fullmatch(s)), "")
    hng = _HNG_RE.search(student.get_text(" ", strip=True)) if student is not None else None
    program, intake = _main_and_sub(cell("program"))
    stage, applied = _main_and_sub(cell("stage"))
    # The University cell: the university itself (.stu-uni), then one .upr line per university
    # application ("Applied: Kyungsung University · Bachelor's Degree"), which are other data.
    uni_cell = cell("university")
    uni_el = uni_cell.select_one(".stu-uni") if uni_cell is not None else None
    university = _blank(uni_el.get_text(" ", strip=True)) if uni_el is not None else text("university")
    applications = [t for t in (_blank(u.get_text(" ", strip=True)) for u in uni_cell.select(".upr")) if t] \
        if uni_el is not None else []
    return {
        "uid": "", "sl": sl, "student_id": hng.group(0) if hng else "", "id": hng.group(0) if hng else "",
        "student_name": name, "target_university": university, "applications": applications,
        "program": program, "target_intake": intake,
        "docs_status": text("docs"), "payment_status": text("payment"),
        "status": stage, "applied_date": applied,
        "_open": True,
    }


def parse_hangeul_live_students(html: str) -> List[Dict[str, Any]]:
    """The students on one students.php page (parse_students_page's "students"): read by the
    header's column names, with the real intake and stage, and "" where the portal shows nothing.
    Raises StudentListLayoutError when the page's layout is not recognised."""
    return parse_students_page(html)["students"]


def is_admitted(student: Dict[str, Any], stage: str = ADMITTED_STAGE) -> bool:
    """Whether a parse_students_page student is at the admitted stage (the dashboard's Admitted
    tile's stage, ADMITTED_STAGE), compared without regard to case or spacing."""
    return _label_key(student.get("status", "")) == _label_key(stage)


def student_matches(student: Dict[str, Any], query: str) -> bool:
    """Whether a student's name, HNG id, university, program, intake or one of their university
    application lines contains `query` (case and spacing do not matter): the local search
    /admitted uses, since the portal's own search does not cover universities or programs."""
    q = re.sub(r"\s+", " ", (query or "")).strip().lower()
    if not q:
        return True
    fields = [student.get(k, "") for k in ("student_name", "student_id", "target_university", "program",
                                            "target_intake")] + list(student.get("applications") or [])
    return any(q in re.sub(r"\s+", " ", str(f)).lower() for f in fields)


def parse_progress_page(html: str) -> Dict[str, Any]:
    """progress.php?uid=N (one student's own progress page) -> {"pct": the ring's overall progress
    (22), "stage": its "Current stage" ("Payment Verified"), "status": the status under it
    ("Verified", "Pending verification")}. Raises StudentListLayoutError when the page has no
    progress ring with a % and a current stage (its layout is not recognised)."""
    soup = BeautifulSoup(html or "", "html.parser")
    ring = soup.select_one(".pg-ring")
    pct = re.search(r"(\d{1,3})\s*%", ring.get_text(" ", strip=True)) if ring is not None else None
    stage_el, status_el = soup.select_one(".pg-now .pg-stage"), soup.select_one(".pg-now .pg-status")
    if pct is None or stage_el is None:
        raise StudentListLayoutError("progress.php shows no progress ring with a % and a current stage")
    return {"pct": int(pct.group(1)), "stage": _blank(stage_el.get_text(" ", strip=True)),
            "status": _blank(status_el.get_text(" ", strip=True)) if status_el is not None else ""}


def normalize_target_date(target_date) -> Optional[str]:
    """A user's date (text, or a date) as the portal writes it, 'DD Mon YYYY' ("09 Sep 2026"), read
    by the one strict parser (src.dates.parse_user_date). None only for an empty input; raises
    ValueError for a text that is not a readable date ("31 Sep"), never a stand-in day."""
    from datetime import date as _date
    from src.dates import parse_user_date, user_date_problem
    if not target_date:
        return None
    if isinstance(target_date, _date):
        return target_date.strftime("%d %b %Y")
    day = parse_user_date(str(target_date), prefer_past=True)
    if day is None:
        raise ValueError(f"not a date: {target_date!r} ({user_date_problem(str(target_date), prefer_past=True)})")
    return day.strftime("%d %b %Y")


def _consult_columns(header: List[str]) -> Dict[str, int]:
    """Column index by meaning, from the header row's names."""
    idx: Dict[str, int] = {}
    for i, h in enumerate(h.lower() for h in header):
        if "update" in h:                       # "Update status" holds forms, never data
            continue
        for key, words in (("name", ("student", "name")), ("contact", ("contact", "phone")),
                           ("city", ("city",)), ("program", ("program",)),
                           ("consultant", ("consultant",)), ("details", ("detail",)),
                           ("received", ("received", "date")), ("status", ("status",)),
                           ("remarks", ("remark",))):
            if key not in idx and any(w in h for w in words):
                idx[key] = i
    return idx


def consultation_rows(html: str) -> List[Dict[str, Any]]:
    """Every row of the consult_requests.php table, read by the header's column names.

    The portal changed this table on its own (Sep 2026: 8+ columns became Student, Consultant,
    City & program, Received, Status, Remarks, Update status); the old fixed column positions
    then matched nothing and every count silently read 0.  Reading by header name, and by the
    cells' own classes (.cr-name, .stbadge, .city, .prog, .d/.t, .cr-by), keeps working when
    columns move.  The Remarks/Update-status forms are only ever read, never submitted."""
    table = BeautifulSoup(html, "html.parser").find("table")
    return _consultation_table_rows(table) if table else []


def consultation_table(html: str) -> Optional[List[Dict[str, Any]]]:
    """consultation_rows, or None when the page has no table, or a table with rows in a layout the
    parser does not recognise; [] when the table is empty. One parse of the ~2 MB page, so a
    caller can run it all in a worker thread."""
    table = BeautifulSoup(html, "html.parser").find("table")
    if table is None:
        return None
    rows = _consultation_table_rows(table)
    if rows:
        return rows
    return None if _consultation_data_rows(table) else []


def _consultation_data_rows(table) -> list:
    """The table's rows below the header, bar the portal's own "No consultation requests yet." row."""
    return [tr for tr in table.find_all("tr")[1:]
            if not (tr.select_one(".cr-empty") or "cr-empty-row" in (tr.get("class") or []))]


# The request statuses, spelt as the portal's status tabs and row badges spell them.
CONSULT_STATUSES = ("New", "No Answer", "Wrong Number", "Consulted", "File Opened")


def _consultation_tabs(soup) -> Tuple[Optional[Dict[str, int]], Optional[str]]:
    """The status tabs' own counts (<nav class="cr-tabs">: "All 999", "New 8", ...) by the tab's
    label, "All" included, and the open tab's status value ("all", "new", "file_opened"...).
    (None, None) when there are no such tabs, no "All" tab, or a count that is not a number."""
    nav = soup.select_one("nav.cr-tabs")
    if nav is None:
        return None, None
    counts: Dict[str, int] = {}
    current = None
    for a in nav.find_all("a"):
        n = a.select_one(".n")
        count = _int_or_none(n.get_text(" ", strip=True)) if n else None
        if count is None:
            return None, None
        label = " ".join(s.strip() for s in a.find_all(string=True, recursive=False) if s.strip())
        if not label:
            label = re.sub(r"\s*\d[\d,]*\s*$", "", a.get_text(" ", strip=True)).strip()
        counts[label] = count
        value = next((c[3:] for c in (a.get("class") or []) if c.startswith("st-")), None)
        if "on" in (a.get("class") or []) or a.get("aria-current"):
            current = value
    if "All" not in counts:
        return None, None
    return counts, current


def consultation_view(html: str) -> Dict[str, Any]:
    """One view of consult_requests.php (the whole list, a status tab, or the date filter that the
    page's own tab links and GET search form use: ?status=all&from=YYYY-MM-DD&to=YYYY-MM-DD), read
    in one parse so a caller can run it in a worker thread.

    -> {"rows": the listed rows (consultation_rows' records; [] for the page's own "No
                consultation requests" row; None when the table is missing or its rows are in a
                layout not recognised),
        "tabs": the status tabs' counts by label ({"All": 999, "New": 8, "No Answer": 153,
                "Wrong Number": 40, "Consulted": 792, "File Opened": 6}; None when not found).
                They count every request the date filter lets through, whichever tab is open,
                while the list under them shows at most the newest few hundred,
        "status": the open tab's value ("all", "file_opened"...), or None,
        "from", "to": the dates the page's search form says it filtered on ("" for none; None
                when it has no search form),
        "listed": the caption's count of listed rows ("<b>500</b> requests · newest first"), or
                None when it has no such caption}"""
    soup = BeautifulSoup(html, "html.parser")
    tabs, current = _consultation_tabs(soup)
    table = soup.find("table")
    rows: Optional[List[Dict[str, Any]]] = None
    if table is not None:
        rows = _consultation_table_rows(table)
        if not rows and _consultation_data_rows(table):
            rows = None                          # rows there, none of them readable
    form = soup.select_one("form.cr-search")
    echo = None
    if form is not None:
        echo = {i.get("name"): (i.get("value") or "").strip() for i in form.find_all("input") if i.get("name")}
    caption = re.search(r"<b>\s*(\d[\d,]*)\s*</b>\s*requests?\s*·\s*newest first", html)
    return {"rows": rows, "tabs": tabs, "status": current,
            "from": None if echo is None else echo.get("from", ""),
            "to": None if echo is None else echo.get("to", ""),
            "listed": _int_or_none(caption.group(1)) if caption else None}


def _cf_email(hexstr: str) -> str:
    """The address behind Cloudflare's email protection (<span class="__cf_email__"
    data-cfemail="HEX">[email protected]</span>, which a browser decodes), or "" when unreadable."""
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except (ValueError, TypeError):
        return ""


def _decode_cf_emails(tag) -> None:
    """Put back, in place, what a browser shows for each Cloudflare-protected address in `tag`
    (a request whose name is an email address otherwise reads "[email protected]")."""
    for span in tag.select(".__cf_email__[data-cfemail]") if tag is not None else []:
        shown = _cf_email(span.get("data-cfemail", ""))
        if shown:
            span.string = shown


def _no_dash(value: str) -> str:
    """"" for the portal's "no value" placeholders ("—", "-", "–"), else the value itself."""
    return "" if (value or "").strip() in ("—", "-", "–", "--") else (value or "")


def _consultation_table_rows(table) -> List[Dict[str, Any]]:
    trs = table.find_all("tr")
    if not trs:
        return []
    col = _consult_columns([c.get_text(" ", strip=True) for c in trs[0].find_all(["th", "td"])])
    if "name" not in col or "status" not in col:
        return []

    def cell(cols, key):
        i = col.get(key)
        return cols[i] if i is not None and i < len(cols) else None

    def text(tag, selector=None):
        """The tag's text, or its first `selector` match's text ("" when absent)."""
        if tag is None:
            return ""
        if selector:
            part = tag.select_one(selector)
            return part.get_text(" ", strip=True) if part else ""
        return tag.get_text(" ", strip=True)

    rows = []
    for tr in trs[1:]:
        cols = tr.find_all(["td", "th"])
        if len(cols) <= max(col["name"], col["status"]):
            continue
        name_cell, status_cell = cell(cols, "name"), cell(cols, "status")
        _decode_cf_emails(name_cell.select_one(".cr-name") if name_cell else None)
        name = text(name_cell, ".cr-name") or text(name_cell)
        if not name:
            continue
        badge = status_cell.select_one(".stbadge") if status_cell else None
        status = badge.get_text(" ", strip=True) if badge else text(status_cell)
        consultant = text(cell(cols, "consultant"), ".cr-cons") or text(cell(cols, "consultant"))
        consultant = consultant if consultant and consultant != "—" else "Unassigned"
        by = status_cell.select_one(".cr-by") if status_cell else None
        place = cell(cols, "city")
        received_cell = cell(cols, "received")
        day = text(received_cell, ".d")
        clock = text(received_cell, ".t")
        received = f"{day} {clock}".strip() if day else text(received_cell)
        contact_cell = cell(cols, "contact") or (name_cell.select_one(".cr-contact") if name_cell else None)
        remark_box = cell(cols, "remarks").select_one("textarea") if cell(cols, "remarks") else None
        details = (place.select_one(".crd-body") if place else None) or cell(cols, "details")
        # The request's own id: the hidden "id" of the row's (never submitted) forms, when every
        # form that has one agrees on one number; "" otherwise.
        form_ids = {str(i.get("value") or "").strip() for i in tr.select('form input[type="hidden"][name="id"]')}
        rows.append({
            "id": next(iter(form_ids)) if len(form_ids) == 1 and next(iter(form_ids)).isdigit() else "",
            "name": name,
            "contact": text(contact_cell).replace("[email protected]", "").strip(),
            # The portal writes "—" for a city or program nobody gave: that is no value, not a place.
            "city": _no_dash(text(place, ".city") or text(place)),
            "program": _no_dash(text(place, ".prog") or text(cell(cols, "program"))),
            "consultant": consultant,
            "details": text(details).replace("View", "").strip(),
            "received": received,
            "received_date": day or received,
            "status": status,
            # The row's own "Last updated by" name (.cr-by), "" when it has none: a request nobody
            # has touched yet has no handler, only its assigned consultant.
            "handled_by": by.get_text(" ", strip=True) if by else "",
            "remarks": remark_box.get_text(" ", strip=True) if remark_box else text(cell(cols, "remarks")),
        })
    return rows


def parse_consultation_requests(html: str, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Parse consultation requests table from consult_requests.php, optionally filtered by date."""
    target_str = normalize_target_date(target_date)
    return [r for r in consultation_rows(html)
            if not target_str or target_str.lower() in r["received"].lower()]


def parse_verified_students(html: str, target_date="today") -> List[Dict[str, Any]]:
    """Parse students whose payments were verified on target_date from one students.php page.

    A field the row does not show is "" (never a stand-in value): "amount" is the verified
    income (else the amount paid), "method" the payment method alone ("Cash", "bKash"), and
    "uid" the portal's own student id from the row's edit link. Raises StudentListLayoutError
    for a page whose layout is not recognised, ValueError for a target date that is not a date."""
    return scan_verified_students(html, target_date)["verified"]


def target_day(target_date):
    """A date, or "today" / "yesterday" / any text src.dates.parse_user_date reads -> a date.
    Raises ValueError for anything else: an unreadable day is never read as "no matches"."""
    from datetime import date as _date
    from src.dates import parse_user_date, user_date_problem
    if isinstance(target_date, _date):
        return target_date
    day = parse_user_date(str(target_date or "today"), prefer_past=True)
    if day is None:
        raise ValueError(f"not a date: {target_date!r} ({user_date_problem(str(target_date), prefer_past=True)})")
    return day


def verification(student: Dict[str, Any], day) -> Optional[Dict[str, Any]]:
    """The payment verification of one parse_students_page student when it is on `day` (a date),
    as {"student_id", "uid", "name", "program", "amount", "paid", "verified_income", "method",
    "verified_by", "verified_time"}, else None. "amount" is the verified income, else the amount
    paid (what a day's total adds up); "paid" and "verified_income" are the row's own two figures
    ("" when absent), shown apart when they differ (payment_text).

    The stamp is the row's own "Payment verified by NAME · 27 Sep, 17:19", matched on whole day
    and month tokens with the year rules of src.dates.stamp_on_day (a stamp with a year must have
    the day's; a student who applied after `day` cannot have been verified on it). The portal
    writes no year, so the caller must first reject a day a year or more back
    (src.dates.yearless_day_problem, as the daily brief does)."""
    from src.dates import parse_portal_date, parse_stamp, stamp_on_day
    stamp = parse_stamp(student.get("verified_stamp", ""))
    if stamp is None:
        return None
    applied = parse_portal_date(student.get("applied_on", "")) or parse_portal_date(student.get("applied_date", ""))
    if not stamp_on_day(stamp, day, applied):
        return None
    return {
        "student_id": student.get("student_id", ""),
        "uid": student.get("uid", ""),
        "name": student.get("student_name", "") or student.get("details", {}).get("Full Name", ""),
        "program": student.get("program", "") or student.get("details", {}).get("Program", ""),
        "amount": student.get("verified_income") or student.get("paid") or "",
        "paid": student.get("paid", ""),
        "verified_income": student.get("verified_income", ""),
        "method": student.get("method", ""),
        "verified_by": student.get("verified_by", ""),
        "verified_time": stamp.text,
    }


def _money(text: str) -> str:
    return re.sub(r"\s+", "", text or "").upper()


def payment_text(v: Dict[str, Any]) -> str:
    """One verification's payment as the portal row shows it: "8,000.00 BDT bKash"; when the row's
    "Paid" and "Verified income" differ, both, each with its own label: "Paid 8,160.00 BDT bKash
    (verified income 8,000.00 BDT)" (the method goes with what was paid). "" when the row shows
    no payment."""
    paid, income, method = v.get("paid") or "", v.get("verified_income") or "", v.get("method") or ""
    if paid and income and _money(paid) != _money(income):
        return f"Paid {' '.join(x for x in (paid, method) if x)} (verified income {income})"
    return " ".join(x for x in (v.get("amount") or income or paid, method) if x)


def verified_on_day(students: List[Dict[str, Any]], day) -> List[Dict[str, Any]]:
    """The students (parse_students_page records, e.g. every page's) whose payment was verified on
    `day`, in list order (see verification)."""
    return [v for v in (verification(s, day) for s in students) if v is not None]


def scan_verified_students(html: str, target_date="today") -> Dict[str, Any]:
    """One students.php page -> {"verified": the students verified on target_date (as
    parse_verified_students), "students": how many student rows the page has, "markers": how many
    rows carry a "Payment verified by" stamp on any date}.

    The two counts let the reader tell "nobody was verified that day" from "this page's layout is
    not recognised" (student rows, but no verification stamp anywhere), which would otherwise read
    as a confident 0. Rows are read by parse_students_page (it raises StudentListLayoutError for a
    page it does not recognise) and matched by verification: whole-token day and month, a stamp's
    own year when it has one, never before the student applied. A caller asking for a day a year
    or more back must still say "not available" itself (src.dates.yearless_day_problem)."""
    day = target_day(target_date)
    students = parse_students_page(html)["students"]
    return {"verified": verified_on_day(students, day), "students": len(students),
            "markers": sum(1 for s in students if s.get("verified_line"))}


def _header_index(tr) -> Dict[str, int]:
    """Column index by label key ("sl", "student", "status"...) from a header row."""
    return {_label_key(c.get_text(" ", strip=True)): i for i, c in enumerate(tr.find_all(["th", "td"]))}


def parse_pending_payments(html: str) -> Optional[Dict[str, Any]]:
    """students.php?status=pending -> {"count", "listed", "badge"}, or None when it cannot be read.

    "listed" counts the student rows on the page (a number in the SL column, found by the
    header's name); "badge" is the portal's own "Pending Payments N" count. The badge wins when
    both are there (the list is paged at 50); a paged list with no badge is not counted at all."""
    soup = BeautifulSoup(html, "html.parser")
    badge = None
    for a in soup.find_all("a", href=re.compile(r"status=pending")):
        m = re.search(r"pending\s+payments?\D{0,5}(\d+)", a.get_text(" ", strip=True), re.I)
        if m:
            badge = int(m.group(1))
            break
    listed = None
    table = soup.find("table")
    trs = table.find_all("tr") if table else []
    col = _header_index(trs[0]) if trs else {}
    if "sl" in col:
        sl = col["sl"]
        listed = 0
        for tr in trs[1:]:
            tds = tr.find_all(["td", "th"], recursive=False) or tr.find_all(["td", "th"])
            if len(tds) > sl and tds[sl].get_text(strip=True).isdigit():
                listed += 1
    pages = re.search(r"Page \d+ of (\d+)", html)
    if badge is None and (listed is None or (pages and int(pages.group(1)) > 1)):
        return None
    return {"count": badge if badge is not None else listed, "listed": listed, "badge": badge}


def parse_window_applications(html: str) -> Optional[List[Dict[str, str]]]:
    """window_applications.php rows by the header's column names: {"student", "window", "status"}.
    None when the page has no table with a Status column (layout not recognised); [] when the
    table is there but empty (its "no applications" row has too few cells to be a row)."""
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        col = _header_index(trs[0]) if trs else {}
        if "status" not in col:
            continue
        rows = []
        for tr in trs[1:]:
            tds = tr.find_all(["td", "th"])
            if len(tds) <= col["status"]:
                continue
            cell = tds[col["status"]]
            pill = cell.select_one(".status-pill") or cell

            def txt(key):
                i = col.get(key)
                return tds[i].get_text(" ", strip=True) if i is not None and i < len(tds) else ""

            rows.append({"student": txt("student"), "window": txt("window"),
                         "status": pill.get_text(" ", strip=True)})
        return rows
    return None


def count_under_review(rows: List[Dict[str, str]]) -> int:
    """Window applications whose status is "under review" ("under_review", "Under Review"...)."""
    return sum(1 for r in rows if _label_key(r.get("status", "")) == "under review")


_CAL_RANGE_RE = re.compile(r"\d{1,2}\s+[A-Za-z]{3}(?:\s+\d{4})?(?:\s*[–—-]\s*\d{1,2}\s+[A-Za-z]{3}(?:\s+\d{4})?)?")
_CAL_TIME_RE = re.compile(r"\d{1,2}:\d{2}")
_CAL_TIME_END_RE = re.compile(r"(\d{1,2}:\d{2})\s*[–—-]\s*(\d{1,2}\s+[A-Za-z]{3}(?:\s+\d{4})?)")
_CAL_PROGRESS_RE = re.compile(r"\d+\s*%|\bdays?\s+left\b", re.I)
_CAL_EMPTY_RE = re.compile(r"\bno\s+(?:reminders?|items?|events?|tasks?)\b|\bnothing\s+(?:due|for\s+today|today)\b"
                           r"|\ball\s+(?:done|clear)\b", re.I)
_CAL_PROGRAM_RE = re.compile(r"\b(?:program(?:me)?s?|klp|eap|bachelor'?s?|master'?s?|degree|language|phd|diploma)\b", re.I)


def _cal_text(tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip() if tag is not None else ""


def _cal_card(soup, heading: str):
    """The card under the section heading that starts with `heading` ("Reminders for today")."""
    for h in soup.select(".sec-h"):
        if _label_key(_cal_text(h)).startswith(_label_key(heading)):
            return h.find_parent(class_="cal-card") or h.parent
    return None


def _cal_sub(line) -> Dict[str, Any]:
    """"Application period · 21 Sep–05 Oct · 10:00 · SEJONG UNIVERSITY · today" -> its parts. The
    timeline writes an event with a start time as "08 Oct · 14:00 – 23 Oct 2026": the time, then
    the end date, which joins the start into the range "08 Oct – 23 Oct 2026"."""
    type_el = line.find("span") if line is not None else None
    out = {"type": _cal_text(type_el), "date_range": "", "time": "", "where": "", "today": False}
    for part in (p.strip() for p in _cal_text(line).split("·")):
        if not part or part == out["type"]:
            continue
        time_end = _CAL_TIME_END_RE.fullmatch(part)
        if part.lower() == "today":
            out["today"] = True
        elif not out["date_range"] and _CAL_RANGE_RE.fullmatch(part):
            out["date_range"] = part
        elif not out["time"] and _CAL_TIME_RE.fullmatch(part):
            out["time"] = part
        elif not out["time"] and time_end:
            out["time"] = time_end.group(1)
            if out["date_range"] and not re.search(r"[–—-]", out["date_range"]):
                out["date_range"] = f"{out['date_range']} – {time_end.group(2)}"
            elif not out["date_range"]:
                out["date_range"] = f"– {time_end.group(2)}"
        else:
            out["where"] = part
    return out


def _cal_id(tag) -> str:
    """The portal's own id of a calendar entry: its edit link's "edit=N" (the Mark done form's
    hidden id otherwise); "" when it shows none."""
    if tag is None:
        return ""
    for a in tag.find_all("a", href=True):
        m = re.search(r"[?&]edit=(\d+)", a["href"])
        if m:
            return m.group(1)
    hidden = tag.find("input", attrs={"name": "id"})
    return str(hidden.get("value") or "").strip() if hidden is not None else ""


def _cal_reminder(item) -> Dict[str, Any]:
    """One "Reminders for today" entry: its title link, then (in the same block) the type/date
    line, an optional progress line ("64% of window elapsed · 7 days left") and an optional note
    (a program such as "EAP PROGRAM", or free text)."""
    title_el = item.select_one(".rm-title, .rm-t") or item.find("a")
    block = title_el.parent if title_el is not None else item
    sub, progress, notes = None, "", []
    for div in block.find_all("div", recursive=False):
        text = _cal_text(div)
        if not text:
            continue
        if sub is None and div.find("span") is not None and "·" in text:
            sub = div
        elif not progress and _CAL_PROGRESS_RE.search(text):
            progress = text
        else:
            notes.append(text)
    parts = _cal_sub(sub)
    left = re.search(r"(\d+)\s+days?\s+left", progress, re.I)
    note = " ".join(notes)
    return {"id": _cal_id(item), "title": _cal_text(title_el), **parts, "progress": progress,
            "days_left": int(left.group(1)) if left else None,
            "program": note if _CAL_PROGRAM_RE.search(note) else "", "note": note}


def _cal_upcoming(row) -> Dict[str, Any]:
    """One "Upcoming" row: date tile, title, type/date/place line, optional program, status."""
    date_el = row.select_one(".li-date")
    main = row.select_one(".ev-main") or row
    sub_el = main.select_one(".ev-sub")
    parts = _cal_sub(sub_el)
    notes = [_cal_text(d) for d in main.find_all("div", recursive=False) if d is not sub_el and _cal_text(d)]
    note = " ".join(notes)
    return {"id": _cal_id(row),
            "date": " ".join(_cal_text(x) for x in date_el.find_all("div")) if date_el else "",
            "type": parts["type"], "title": _cal_text(main.select_one(".ev-title") or main.find("a")),
            "university": parts["where"], "date_range": parts["date_range"],
            "program": note if _CAL_PROGRAM_RE.search(note) else "", "note": note,
            "status": _cal_text(row.select_one(".st"))}


def parse_calendar_events(html: str) -> Dict[str, Any]:
    """calendar.php -> today's reminders and the upcoming timeline, read by the page's own
    section headings and classes (the "Reminders for today" card's .rm-item entries, the
    "Upcoming" card's .ev-row entries). The same reminders repeat in a pop-up (.rm-row), which is
    not read, so nothing counts twice. An entry with no title is dropped, never counted.

    -> {"today_reminders", "upcoming_events", "layout_ok" (the reminders were read: entries were
        found, or the card itself says there are none), "upcoming_ok", "skipped_untitled",
        "heading_count" (the "· N items" the page states)}

    A reminders card with no entries it recognises is a real "none today" only when it says so
    ("· 0 items", "No reminders"); otherwise its entries' layout changed, which must read as
    "not available", never as 0."""
    soup = BeautifulSoup(html, "html.parser")
    card = _cal_card(soup, "Reminders for today")
    items = card.select(".rm-item") if card is not None else soup.select(".rm-item")
    heading_count = None
    says_none = False
    if card is not None:
        stated = re.search(r"(\d+)\s+items?\b", _cal_text(card.select_one(".sec-h")), re.I)
        heading_count = int(stated.group(1)) if stated else None
        says_none = heading_count == 0 or bool(_CAL_EMPTY_RE.search(_cal_text(card)))

    reminders = [_cal_reminder(i) for i in items]
    titled = [r for r in reminders if r["title"]]

    up_card = _cal_card(soup, "Upcoming")
    rows = up_card.select(".ev-row") if up_card is not None else soup.select(".ev-row")
    upcoming = [e for e in (_cal_upcoming(r) for r in rows) if e["title"]]

    return {
        "today_reminders": titled,
        "upcoming_events": upcoming,
        "layout_ok": bool(items) or says_none,
        "upcoming_ok": up_card is not None or bool(rows),
        "skipped_untitled": len(reminders) - len(titled),
        "heading_count": heading_count,
    }

