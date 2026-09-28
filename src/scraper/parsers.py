import logging
import re
from typing import List, Dict, Any, Optional
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

def parse_hangeul_live_students(html: str) -> List[Dict[str, Any]]:
    """Parse live student records from students.php."""
    import re
    soup = BeautifulSoup(html, "html.parser")
    students = []
    
    table = soup.find("table")
    if not table:
        return []
        
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) >= 9:
            sl = tds[1].get_text(strip=True)
            stu_id = tds[2].get_text(strip=True)
            name_raw = tds[3].get_text(strip=True)
            # Clean email obfuscation
            name = re.sub(r'\[email\s*protected\]', '', name_raw).strip()
            uni = tds[4].get_text(strip=True)
            prog = tds[5].get_text(strip=True)
            docs = tds[6].get_text(strip=True)
            payment = tds[7].get_text(strip=True)
            stage = tds[8].get_text(strip=True)
            applied = tds[9].get_text(strip=True) if len(tds) > 9 else ""
            
            if sl.isdigit():
                students.append({
                    "id": stu_id if stu_id != "—" else f"HNG-SL-{sl}",
                    "student_name": name,
                    "target_university": uni if uni != "—" else "Pending Allocation",
                    "program": prog,
                    "target_intake": "March 2027",
                    "status": stage,
                    "payment_status": payment,
                    "docs_status": docs,
                    "applied_date": applied
                })
    return students


def normalize_target_date(target_date: Optional[str]) -> Optional[str]:
    """Normalize any target date string to match portal 'DD Mon YYYY' format (e.g. '09 Sep 2026')."""
    if not target_date:
        return None
    import re
    from datetime import datetime, timedelta
    t_clean = target_date.strip()
    t_low = t_clean.lower()
    now = datetime.now()

    if t_low in ["today", "today's"]:
        return now.strftime("%d %b %Y")
    if t_low in ["yesterday", "yesterday's"]:
        return (now - timedelta(days=1)).strftime("%d %b %Y")

    cleaned = re.sub(r'/(?:report|consultations|inquiries)\b', '', t_clean, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(?:report|consultation|requests?|for|of|on|please|show|give|me)\b', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned_suffix = re.sub(r'(\d+)(st|nd|rd|th)\b', r'\1', cleaned, flags=re.IGNORECASE).strip()

    formats = [
        '%d %b %Y', '%d %B %Y', '%d %b', '%d %B',
        '%b %d %Y', '%B %d %Y', '%b %d', '%B %d',
        '%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y',
        '%d-%m', '%d/%m'
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned_suffix, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=now.year)
            return dt.strftime("%d %b %Y")
        except ValueError:
            pass

    m = re.search(r'\b(\d{1,2})\s*([A-Za-z]{3,9})(?:\s*(\d{2,4}))?\b', cleaned_suffix)
    if m:
        day = int(m.group(1))
        month_str = m.group(2)[:3].capitalize()
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100:
            year += 2000
        try:
            dt = datetime.strptime(f'{day:02d} {month_str} {year}', '%d %b %Y')
            return dt.strftime("%d %b %Y")
        except ValueError:
            pass

    return target_date.strip()


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
    return None if len(table.find_all("tr")) > 1 else []


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
        rows.append({
            "name": name,
            "contact": text(contact_cell).replace("[email protected]", "").strip(),
            "city": text(place, ".city") or text(place),
            "program": text(place, ".prog") or text(cell(cols, "program")),
            "consultant": consultant,
            "details": text(details).replace("View", "").strip(),
            "received": received,
            "received_date": day or received,
            "status": status,
            "handled_by": by.get_text(" ", strip=True) if by else consultant,
            "remarks": remark_box.get_text(" ", strip=True) if remark_box else text(cell(cols, "remarks")),
        })
    return rows


def parse_consultation_requests(html: str, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Parse consultation requests table from consult_requests.php, optionally filtered by date."""
    target_str = normalize_target_date(target_date)
    return [r for r in consultation_rows(html)
            if not target_str or target_str.lower() in r["received"].lower()]


def parse_verified_students(html: str, target_date: Optional[str] = "today") -> List[Dict[str, Any]]:
    """Parse students whose payments were verified on target_date from students.php.

    A field the row does not show is "" (never a stand-in value): "amount" is the verified
    income (else the amount paid), "method" the payment method alone ("Cash", "bKash"), and
    "uid" the portal's own student id from the row's edit link."""
    return scan_verified_students(html, target_date)["verified"]


_VERIFIED_MARK_RE = re.compile(r"Payment verified by\b", re.I)
_APPLIED_ON_RE = re.compile(r"Applied On\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})")


def _target_day(target_date: Optional[str]):
    """"today" / "yesterday" / any date normalize_target_date reads -> a date, or None."""
    from datetime import datetime, timedelta
    t_low = (target_date or "today").lower().strip()
    now = datetime.now()
    if t_low == "today":
        return now.date()
    if t_low == "yesterday":
        return (now - timedelta(days=1)).date()
    try:
        return datetime.strptime(normalize_target_date(target_date) or "", "%d %b %Y").date()
    except ValueError:
        return None


def scan_verified_students(html: str, target_date: Optional[str] = "today") -> Dict[str, Any]:
    """One students.php page -> {"verified": the students verified on target_date (as
    parse_verified_students), "students": how many student rows (edit links) the page has,
    "markers": how many rows carry a "Payment verified by" line on any date}.

    The two counts let the reader tell "nobody was verified that day" from "this page's layout is
    not recognised" (student rows, but no verification line anywhere), which would otherwise read
    as a confident 0. The portal writes the verification time without a year ("27 Sep, 17:19"):
    a time that does carry a year must match the target's, and a row whose "Applied On" date is
    after the target day cannot have been verified on it. A caller asking for a day more than a
    year back must still say "not available" itself (src/bot/brief.py verified_day_problem)."""
    from datetime import datetime
    out: Dict[str, Any] = {"verified": [], "students": 0, "markers": 0}
    table = BeautifulSoup(html, "html.parser").find("table")
    if not table:
        return out
    out["students"] = len({a["href"] for a in table.find_all("a", href=re.compile(r"student_edit\.php\?id=\d+"))})
    day = _target_day(target_date)
    date_regex = rf"0?{day.day}\s+{day:%b}" if day else None

    verified = out["verified"]
    for tr in table.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        if not _VERIFIED_MARK_RE.search(text):
            continue
        out["markers"] += 1
        if date_regex is None:
            continue
        # The verifier: anything up to the "·" (names with hyphens or apostrophes, "Md. Al-Amin").
        m_ver = re.search(rf"Payment verified by\s+([^·\n]{{1,80}}?)\s*·\s*({date_regex}[a-z]*)(?:\s+(\d{{4}}))?([^<\n]*)",
                          text, re.IGNORECASE)
        if m_ver:
            if m_ver.group(3) and int(m_ver.group(3)) != day.year:
                continue
            applied = _APPLIED_ON_RE.search(text)
            if applied:
                try:
                    if datetime.strptime(applied.group(1), "%d %b %Y").date() > day:
                        continue            # verified before the student applied: another year's date
                except ValueError:
                    pass
            name_m = re.search(r"Full Name\s+([A-Za-z][A-Za-z\s\.\-'’]*?)\s*(?=\bDOB\b|\bGender\b|$)", text)
            stu_id_m = re.search(r"HNG-\d{4}-\d+", text)
            prog_m = re.search(r"Program\s+([A-Za-z\s\(\)\']+?)(?:Preferred|$)", text)
            amt_m = re.search(r"Verified income:\s*([\d,]+\.?\d*\s*BDT)", text)
            paid_m = re.search(r"Paid:\s*([\d,]+\.?\d*\s*BDT)\s*([A-Za-z][A-Za-z\s\-]*?)?\s*(?:Verified|$)", text)
            edit_a = tr.find("a", href=re.compile(r"student_edit\.php\?id=\d+"))

            raw_time = (m_ver.group(2) + m_ver.group(4)).strip()
            clean_time_m = re.search(rf"({date_regex}(?:,\s*\d{{1,2}}:\d{{2}})?)", raw_time, re.IGNORECASE)
            clean_time = clean_time_m.group(1) if clean_time_m else raw_time[:15]

            verified.append({
                "student_id": stu_id_m.group(0) if stu_id_m else "",
                "uid": re.search(r"id=(\d+)", edit_a["href"]).group(1) if edit_a else "",
                "name": name_m.group(1).strip() if name_m else "",
                "program": prog_m.group(1).strip() if prog_m else "",
                "amount": amt_m.group(1) if amt_m else (paid_m.group(1) if paid_m else ""),
                "method": (paid_m.group(2) or "").strip() if paid_m else "",
                "verified_by": m_ver.group(1).strip(),
                "verified_time": clean_time
            })
    return out


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
    """"Application period · 21 Sep–05 Oct · 10:00 · SEJONG UNIVERSITY · today" -> its parts."""
    type_el = line.find("span") if line is not None else None
    out = {"type": _cal_text(type_el), "date_range": "", "time": "", "where": "", "today": False}
    for part in (p.strip() for p in _cal_text(line).split("·")):
        if not part or part == out["type"]:
            continue
        if part.lower() == "today":
            out["today"] = True
        elif not out["date_range"] and _CAL_RANGE_RE.fullmatch(part):
            out["date_range"] = part
        elif not out["time"] and _CAL_TIME_RE.fullmatch(part):
            out["time"] = part
        else:
            out["where"] = part
    return out


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
    return {"title": _cal_text(title_el), **parts, "progress": progress,
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
    return {"date": " ".join(_cal_text(x) for x in date_el.find_all("div")) if date_el else "",
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

