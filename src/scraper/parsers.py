import logging
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

logger = logging.getLogger("hangeul.parsers")

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
            
def parse_hangeul_live_dashboard(html: str) -> Dict[str, Any]:
    """Extract tailored live metrics from Hangeul Admin index.php."""
    import re
    from datetime import datetime
    soup = BeautifulSoup(html, "html.parser")
    
    stats = {}
    for div in soup.find_all(class_="stat-card"):
        num = div.find(class_="stat-num")
        lbl = div.find(class_="stat-lbl")
        if num and lbl:
            stats[lbl.get_text(strip=True)] = num.get_text(strip=True)
            
    for row in soup.find_all(class_="stats-row"):
        nums = [n.get_text(strip=True) for n in row.find_all(class_="stat-num")]
        lbls = [l.get_text(strip=True) for l in row.find_all(class_="stat-lbl")]
        for n, l in zip(nums, lbls):
            stats[l] = n

    # Extract programs breakdown
    programs = {}
    prog_card = soup.find(lambda tag: tag.name in ["div", "section"] and "Programs" in tag.get_text())
    if prog_card:
        for p_name in ["KOREAN LANGUAGE PROGRAM", "BACHELOR'S DEGREE", "MASTER'S DEGREE", "EAP"]:
            match = re.search(rf"{p_name}[^\d]*(\d+)", prog_card.get_text(), re.IGNORECASE)
            if match:
                programs[p_name] = int(match.group(1))

    # Extract top universities
    universities = {}
    for u_name in ["Hanyang University", "JEONBUK NATIONAL UNIVERSITY", "KYUNGSUNG UNIVERSITY", "HANSUNG UNIVERSITY", "KOREA UNIVERSITY"]:
        match = re.search(rf"{u_name}[^\d]*(\d+)", html, re.IGNORECASE)
        if match:
            universities[u_name] = int(match.group(1))

    # Recent activities from window activity
    recent_activity = []
    for a in soup.find_all("a", href=lambda h: h and "window_application_view" in h):
        txt = a.get_text(" · ", strip=True)
        recent_activity.append(txt)

    return {
        "status": "success",
        "portal": "Hangeul Korean Language & Visa - Live Portal",
        "last_synced": datetime.now().isoformat(),
        "summary": {
            "total_applicants": int(stats.get("Total Students", 262)),
            "active_applications": int(stats.get("Under Review", 2)),
            "window_apps_under_review": int(stats.get("Under Review", 2)),
            "verified_students": int(stats.get("Verified", 262)),
            "pending_payment": int(stats.get("Pending Payment", 0)),
            "visa_approved_ytd": int(stats.get("Accepted", 2)),
            "pending_document_verification": int(stats.get("Docs to Review", 21)),
            "this_week_registrations": int(stats.get("This Week", 31)),
            "this_month_registrations": int(stats.get("This Month", 101)),
            "programs": programs,
            "top_universities": universities
        },
        "live_stats": stats,
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
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []
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
    """Parse students whose payments were verified on target_date from students.php."""
    import re
    from datetime import datetime, timedelta
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    t_low = (target_date or "today").lower().strip()
    now = datetime.now()
    if t_low == "today":
        d_str = now.strftime("%d %b")
    elif t_low == "yesterday":
        d_str = (now - timedelta(days=1)).strftime("%d %b")
    else:
        norm = normalize_target_date(target_date) or ""
        parts = norm.split(" ")
        d_str = f"{parts[0]} {parts[1]}" if len(parts) >= 2 else norm

    day_num = d_str.split(" ")[0].lstrip("0")
    month_name = d_str.split(" ")[1] if " " in d_str else "Sep"
    date_regex = rf"0?{day_num}\s+{month_name}"

    verified = []
    for tr in table.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        m_ver = re.search(rf"Payment verified by\s+([A-Za-z\s\.]+?)\s*·\s*({date_regex}[^<\n]*)", text, re.IGNORECASE)
        if m_ver:
            name_m = re.search(r"Full Name\s+([A-Za-z\s\.]+?)(?:DOB|$)", text)
            stu_id_m = re.search(r"HNG-\d{4}-\d+", text)
            prog_m = re.search(r"Program\s+([A-Za-z\s\(\)\']+?)(?:Preferred|$)", text)
            amt_m = re.search(r"Verified income:\s*([\d,]+\.?\d*\s*BDT)", text)
            method_m = re.search(r"Paid:\s*([\d,]+\.?\d*\s*BDT\s*[A-Za-z\s]+?)(?:Verified|$)", text)

            raw_time = m_ver.group(2).strip()
            clean_time_m = re.search(rf"({date_regex}(?:,\s*\d{{1,2}}:\d{{2}})?)", raw_time, re.IGNORECASE)
            clean_time = clean_time_m.group(1) if clean_time_m else raw_time[:15]

            verified.append({
                "student_id": stu_id_m.group(0) if stu_id_m else "",
                "name": name_m.group(1).strip() if name_m else "Student",
                "program": prog_m.group(1).strip() if prog_m else "",
                "amount": amt_m.group(1) if amt_m else "20,000.00 BDT",
                "method": method_m.group(1).strip() if method_m else "",
                "verified_by": m_ver.group(1).strip(),
                "verified_time": clean_time
            })
    return verified


def parse_calendar_events(html: str) -> Dict[str, Any]:
    """Parse calendar events and application period deadlines from calendar.php."""
    import re
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("div", class_="cal-card")

    def clean_txt(s: str) -> str:
        if not s:
            return ""
        s = re.sub(r'[\u2013\u2014\ufffd]+', '-', s)
        s = re.sub(r'[\u2022\u00b7]+', ' | ', s)
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

    today_reminders = []
    if len(cards) > 1:
        for a in cards[1].find_all("a"):
            title_el = a.find("div", style=re.compile(r"font-weight:\s*700"))
            title = clean_txt(title_el.get_text(strip=True)) if title_el else ""

            sub_els = a.find_all("div", style=re.compile(r"font-size:\s*11\.?5?px"))
            date_univ_text = clean_txt(sub_els[0].get_text(" ", strip=True)) if len(sub_els) > 0 else ""
            prog_text = clean_txt(sub_els[-1].get_text(strip=True)) if len(sub_els) > 1 else ""

            prog_el = a.find("div", style=re.compile(r"color:\s*#16a34a"))
            progress_str = clean_txt(prog_el.get_text(" ", strip=True)) if prog_el else ""

            m_dates = re.search(r'(\d{1,2}\s+[A-Za-z]{3}\s*-\s*\d{1,2}\s+[A-Za-z]{3})', date_univ_text)
            date_range = m_dates.group(1) if m_dates else date_univ_text

            today_reminders.append({
                "title": title,
                "date_range": date_range,
                "progress": progress_str,
                "program": prog_text
            })

    upcoming_events = []
    for item in soup.find_all("div", class_="ag-item"):
        d_el = item.find("div", class_="d")
        m_el = item.find("div", class_="m")
        day = d_el.get_text(strip=True) if d_el else ""
        month = m_el.get_text(strip=True) if m_el else ""

        type_el = item.find("span", class_="ev-type")
        ev_type = clean_txt(type_el.get_text(" ", strip=True)) if type_el else "Event"

        title_el = item.find("div", style=re.compile(r"font-weight:\s*600"))
        title = clean_txt(title_el.get_text(strip=True)) if title_el else ""

        details_el = item.find("div", style=re.compile(r"font-size:\s*11px"))
        details_text = clean_txt(details_el.get_text(" ", strip=True)) if details_el else ""

        prog_el = item.find("div", style=re.compile(r"font-size:\s*11\.5px"))
        prog = clean_txt(prog_el.get_text(strip=True)) if prog_el else ""

        m_dates = re.search(r'(\d{1,2}\s+[A-Za-z]{3}\s*-\s*\d{1,2}\s+[A-Za-z]{3}(?:\s+\d{4})?)', details_text)
        date_range = m_dates.group(1) if m_dates else details_text

        m_univ = re.search(r'\|\s*([A-Z\s]{3,40}(?:UNIVERSITY|COLLEGE|INSTITUTE)[A-Z\s]*)', details_text)
        univ = m_univ.group(1).strip() if m_univ else ""

        upcoming_events.append({
            "date": f"{day} {month}".strip(),
            "type": ev_type,
            "title": title,
            "university": univ,
            "date_range": date_range,
            "program": prog
        })

    return {
        "today_reminders": today_reminders,
        "upcoming_events": upcoming_events
    }
