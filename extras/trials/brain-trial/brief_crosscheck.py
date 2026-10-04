"""Independent cross-check of the factual daily brief (brief_verify.txt) against the live portal.

Read-only: GET requests only, plus the portal login itself (guardrails 1 and 7). It uses its own
HTTP session and its own regex parsing of the raw HTML; none of the bot's parsers (src/scraper)
or its brief code (src/bot/brief.py) are imported. Only the portal address and the login come
from the bot's settings. students.php only, never signed_students.php (guardrail 6). Pending
payments and window applications under review are derived and compared separately (guardrail 2).

    python brief_crosscheck.py [brief_verify.txt] [--json OUT.json]

Prints one line per claim (brief value, independent value, match) and the lines of the brief that
no data backs; --json also writes them as JSON.
"""
import json
import re
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

BOT = Path(r"C:\Hangeul\BOT")
sys.path.insert(0, str(BOT))
from src.config import settings  # noqa: E402  (portal address and login only)

HERE = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Dhaka")
BASE = settings.HANGEUL_BASE_URL.rstrip("/")
RESULTS_JSON = BOT / "data" / "verification" / "results.json"
MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
DONE_STATUSES = ("consulted", "file_opened")


# ----------------------------------------------------------------------------- portal session

class Portal:
    """One read-only session. get() refuses anything but a GET of a portal page."""

    def __init__(self):
        self.c = httpx.Client(follow_redirects=True, verify=False,
                              timeout=httpx.Timeout(120.0, connect=15.0),
                              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                       "Accept": "text/html,application/xhtml+xml"})
        self.log = []

    def login(self):
        page = self.c.get(f"{BASE}/login.php").text
        m = (re.search(r'name=["\']_csrf["\'][^>]*value=["\']([^"\']+)', page)
             or re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']_csrf', page))
        if not m:
            raise RuntimeError("no _csrf on login.php")
        r = self.c.post(f"{BASE}/login.php", data={"_csrf": m.group(1),
                                                   "username": settings.HANGEUL_USERNAME,
                                                   "password": settings.HANGEUL_PASSWORD})
        if "login.php" in str(r.url):
            raise RuntimeError("login rejected")
        self.log.append(("LOGIN", "login.php", r.status_code))

    def get(self, path: str) -> str:
        assert "signed_students" not in path, "guardrail 6"
        t = time.perf_counter()
        r = self.c.get(f"{BASE}/{path}")
        if "login.php" in str(r.url):
            raise RuntimeError(f"{path}: sent to the login page")
        r.raise_for_status()
        self.log.append(("GET", path, r.status_code, round(time.perf_counter() - t, 1)))
        return r.content.decode("utf-8", errors="replace")


def strip_tags(html: str) -> str:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#160;", " ")
            .replace("&quot;", '"').replace("&#039;", "'").replace("&middot;", "·"))
    return re.sub(r"\s+", " ", text).strip()


def portal_date(text: str):
    m = re.fullmatch(r"\s*(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})\s*", text or "")
    return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))) if m and m.group(2) in MONTHS else None


# ----------------------------------------------------------------------------- independent reads

def read_consultations(p: Portal, today: date) -> dict:
    html = p.get("consult_requests.php")
    chips = {k: int(n) for k, n in re.findall(
        r'<a class="st-([a-z_]+)[^"]*"\s+href="\?status=\1"[^>]*>.*?<span class="n">(\d+)</span>', html, re.S)}
    shown = re.search(r"<b>(\d+)</b>\s*requests", html)
    rows = []
    for chunk in re.split(r'(?=<tr class="rowlink")', html)[1:]:
        chunk = chunk[:chunk.find("</tr>")]
        rid = re.search(r'consult_request_view\.php\?id=(\d+)', chunk)
        d = re.search(r'<span class="d">([^<]*)</span>\s*<span class="t">([^<]*)</span>', chunk)
        sel = re.search(r'<select name="set_status".*?</select>', chunk, re.S)
        chosen = re.findall(r'<option value="([a-z_]+)"\s+selected', sel.group(0)) if sel else []
        badge = re.search(r'class="stbadge"[^>]*>\s*<span class="dot"></span>\s*([^<]+?)\s*</span>', chunk)
        by = re.search(r'<div class="cr-by"[^>]*>(?:\s*<i[^>]*></i>)?\s*([^<]+?)\s*</div>', chunk)
        cons = re.search(r'<span class="cr-cons">(?:\s*<i[^>]*></i>)?\s*([^<]+?)\s*</span>', chunk)
        rows.append({
            "id": rid.group(1) if rid else "",
            "date": d.group(1).strip() if d else "", "time": d.group(2).strip() if d else "",
            "status": chosen[0] if len(chosen) == 1 else "?",
            "badge": badge.group(1).strip() if badge else "",
            "last_updated_by": by.group(1).strip() if by else "",
            "consultant": cons.group(1).strip() if cons else "",
        })
    dates = [portal_date(r["date"]) for r in rows]
    today_s = today.strftime("%d %b %Y")
    day = [r for r in rows if r["date"] == today_s]
    st = Counter(r["status"] for r in day)
    done_rows = [r for r in day if r["status"] in DONE_STATUSES]
    every = Counter(r["status"] for r in rows)
    badge_vs_select = sum(1 for r in rows
                          if r["badge"].lower().replace(" ", "_") != r["status"])
    return {
        "chips": chips, "shown_on_page": int(shown.group(1)) if shown else None,
        "rows_parsed": len(rows), "unreadable_dates": sum(1 for d in dates if d is None),
        "oldest_row_date": min(d for d in dates if d).isoformat() if any(dates) else None,
        "newest_row_date": max(d for d in dates if d).isoformat() if any(dates) else None,
        "badge_vs_selected_disagree": badge_vs_select,
        "today": {"received": len(day), "by_status": dict(st),
                  "done": len(done_rows),
                  "done_by_last_updated_by": dict(Counter(r["last_updated_by"] or "Unassigned" for r in done_rows)),
                  "done_by_assigned_consultant": dict(Counter(r["consultant"] or "Unassigned" for r in done_rows)),
                  "received_by_assigned_consultant": dict(Counter(r["consultant"] or "Unassigned" for r in day)),
                  "rows": day},
        "latest_on_page": {"count": len(rows), "done": sum(every[s] for s in DONE_STATUSES),
                           "by_status": dict(every)},
    }


def _money(text):
    m = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    return float(m.group(0).replace(",", "")) if m else None


def read_students(p: Portal, today: date) -> dict:
    first = p.get("students.php")
    m = re.search(r"Page\s+1\s+of\s+(\d+)", first)
    pages = int(m.group(1)) if m else 1
    htmls = [first] + [p.get(f"students.php?pg={k}") for k in range(2, pages + 1)]
    students, marks, verified_today, latest = {}, 0, [], []
    for html in htmls:
        for chunk in re.split(r'(?=<tr class="stu-row")', html)[1:]:
            uid = re.search(r'data-uid="(\d+)"', chunk)
            if not uid:
                continue
            uid = uid.group(1)
            name = re.search(r'<strong class="pii stu-name">([^<]*)</strong>', chunk)
            prog_cell = re.search(r'<td class="c-prog"[^>]*>(.*?)<div', chunk, re.S)
            prog_item = re.search(r"<label>Program</label><span>([^<]*)</span>", chunk)
            pay_cell = re.search(r'<td class="c-pay"[^>]*>(.*?)</td>', chunk, re.S)
            applied = re.search(r"<label>Applied On</label><span>([^<]*)</span>", chunk)
            by = re.search(r"Payment verified by\s*<strong>([^<]*)</strong>\s*(?:·|&middot;|\W)\s*"
                           r"(\d{1,2})\s+([A-Z][a-z]{2})(?:\s+(\d{4}))?,?\s*(\d{1,2}:\d{2})?", chunk)
            paid = re.search(r'class="pf paid"[^>]*>.*?Paid:\s*([\d,]+(?:\.\d+)?\s*BDT)', chunk, re.S)
            method = re.search(r'class="pf method"[^>]*>(?:\s*<i[^>]*></i>)?\s*([^<]+?)\s*</span>', chunk)
            income = re.search(r"Verified income:\s*([\d,]+(?:\.\d+)?\s*BDT)", chunk)
            rec = {"uid": uid, "name": strip_tags(name.group(1)) if name else "",
                   "program": strip_tags(prog_item.group(1)) if prog_item else (strip_tags(prog_cell.group(1)) if prog_cell else ""),
                   "payment_badge": strip_tags(pay_cell.group(1)) if pay_cell else "",
                   "applied_on": applied.group(1).strip() if applied else ""}
            if by:
                marks += 1
                rec.update({"verified_by": strip_tags(by.group(1)), "verified_day": int(by.group(2)),
                            "verified_month": by.group(3), "verified_year": by.group(4) or "",
                            "verified_clock": by.group(5) or "",
                            "paid": paid.group(1) if paid else "", "method": method.group(1).strip() if method else "",
                            "verified_income": income.group(1) if income else ""})
                latest.append(rec)
                same_day = rec["verified_day"] == today.day and MONTHS.get(rec["verified_month"]) == today.month
                year_ok = not rec["verified_year"] or int(rec["verified_year"]) == today.year
                if same_day and year_ok and uid not in {v["uid"] for v in verified_today}:
                    verified_today.append(rec)
            students.setdefault(uid, rec)

    def key(r):          # most recent verification first; the portal gives no year, assume this one
        return (MONTHS.get(r["verified_month"], 0), r["verified_day"], r["verified_clock"])
    latest.sort(key=key, reverse=True)
    amounts = [_money(v["verified_income"] or v["paid"]) for v in verified_today]
    return {"pages": pages, "students": len(students), "rows_with_verified_by_line": marks,
            "verified_today": verified_today,
            "verified_today_total_bdt": sum(a for a in amounts if a is not None) if verified_today else 0.0,
            "most_recent_verifications": [{k: r[k] for k in ("name", "verified_by", "verified_day",
                                                              "verified_month", "verified_clock")}
                                          for r in latest[:3]],
            "payment_badges": dict(Counter(s["payment_badge"] for s in students.values()))}


def read_pending(p: Portal) -> dict:
    html = p.get("students.php?status=pending")
    badge = None
    for a in re.findall(r'<a[^>]*href="[^"]*students\.php\?status=pending"[^>]*>(.*?)</a>', html, re.S):
        m = re.search(r"Pending Payments?\s*(\d+)", strip_tags(a), re.I)
        if m:
            badge = int(m.group(1))
    rows = re.findall(r'<tr class="stu-row".*?</tr>', html, re.S)
    badges = Counter(strip_tags(re.search(r'<td class="c-pay"[^>]*>(.*?)</td>', r, re.S).group(1)) for r in rows)
    return {"badge": badge, "rows_listed": len(rows), "row_payment_badges": dict(badges),
            "paged": bool(re.search(r"Page\s+\d+\s+of\s+[2-9]", html))}


def read_window_apps(p: Portal) -> dict:
    out = {}
    for label, path in (("filtered_under_review", "window_applications.php?status=under_review"),
                        ("all", "window_applications.php")):
        html = p.get(path)
        table = html[html.find("<table"):html.find("</table>")] if "<table" in html else ""
        pills = [strip_tags(x) for x in re.findall(r'<span class="status-pill[^"]*"[^>]*>(.*?)</span>', table, re.S)]
        total = re.search(r"Applications\s*(?:<[^>]+>\s*)*(\d+)", html)
        out[label] = {"rows": len(pills), "statuses": dict(Counter(pills)),
                      "says_no_match": "No applications match" in table,
                      "applications_heading": int(total.group(1)) if total else None}
    ur = sum(n for s, n in out["all"]["statuses"].items() if re.sub(r"[\s_]+", " ", s.lower()) == "under review")
    out["under_review_in_full_list"] = ur
    out["under_review_filtered_rows"] = sum(
        n for s, n in out["filtered_under_review"]["statuses"].items() if re.sub(r"[\s_]+", " ", s.lower()) == "under review")
    return out


def read_dashboard(p: Portal) -> dict:
    html = p.get("index.php")
    group, tiles = "", []
    for m in re.finditer(r'<h2 class="ds-t">(.*?)</h2>|<a href="([^"]*)" class="stat-card[^"]*">(.*?)</a>', html, re.S):
        if m.group(1) is not None:
            group = strip_tags(m.group(1))
            continue
        num = re.search(r'<span class="stat-num">(.*?)</span>', m.group(3), re.S)
        lbl = re.search(r'<span class="stat-lbl">(.*?)</span>', m.group(3), re.S)
        if num and lbl:
            tiles.append({"group": group, "label": strip_tags(lbl.group(1)), "text": strip_tags(num.group(1)),
                          "href": m.group(2)})
    return {"tiles": tiles}


def read_calendar(p: Portal) -> dict:
    html = p.get("calendar.php")
    k = html.find('id="todayReminders"')
    if k < 0:
        return {"error": "no todayReminders card"}
    end = html.find('<div class="cal-card', k + 10)
    card = html[k:end if end > 0 else len(html)]
    stated = re.search(r"(\d+)\s+items?", strip_tags(card[:card.find("</div>")]))
    items = []
    for chunk in re.split(r'(?=<div class="rm-item)', card)[1:]:
        title = re.search(r'class="rm-title">(.*?)</a>', chunk, re.S)
        kind = re.search(r'<span style="color:[^"]*;font-weight:700">(.*?)</span>', chunk, re.S)
        text = strip_tags(chunk)
        rng = re.search(r"·\s*(\d{1,2} [A-Z][a-z]{2}\s*[–—-]\s*\d{1,2} [A-Z][a-z]{2})", text)
        left = re.search(r"(\d+)\s+days?\s+left", text)
        items.append({"title": strip_tags(title.group(1)) if title else "",
                      "type": strip_tags(kind.group(1)) if kind else "",
                      "range": re.sub(r"\s*[–—-]\s*", "–", rng.group(1)) if rng else "",
                      "days_left": int(left.group(1)) if left else None})
    return {"heading_count": int(stated.group(1)) if stated else None, "items": items,
            "by_type": dict(Counter(i["type"] for i in items))}


def read_documents() -> dict:
    store = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    docs = [v for v in (store.get("documents") or {}).values() if isinstance(v, dict)]
    fields = [v for v in (store.get("fields") or {}).values() if isinstance(v, dict)]
    return {"students": len(docs), "verdicts": dict(Counter(d.get("verdict") or "no verdict" for d in docs)),
            "latest_document_check": max((str(d.get("checked") or "") for d in docs), default=""),
            "latest_field_check": max((str(d.get("checked") or "") for d in fields), default=""),
            "results_json_modified": datetime.fromtimestamp(RESULTS_JSON.stat().st_mtime).isoformat(timespec="seconds")}


# ----------------------------------------------------------------------------- the brief's claims

def plain(md: str) -> str:
    text = re.sub(r"(?<!\\)[*_]", "", md)
    return re.sub(r"\\([_*`\[])", r"\1", text)


NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
NUMBER_WORDS.update({"no": 0, "none": 0})


def compare(brief_text: str, ind: dict) -> dict:
    lines = plain(brief_text).splitlines()
    checks, unbacked, used = [], [], set()

    def add(claim, brief_value, independent_value, match=None, note=""):
        if match is None:
            match = str(brief_value) == str(independent_value)
        checks.append({"claim": claim, "brief_value": str(brief_value),
                       "independent_value": str(independent_value), "match": bool(match), "note": note})

    def find(pattern, flags=0):
        for i, line in enumerate(lines):
            m = re.search(pattern, line, flags)
            if m:
                used.add(i)
                return m
        return None

    con, stu, pen, win, dash, cal, doc = (ind[k] for k in ("consultations", "students", "pending", "window",
                                                           "dashboard", "calendar", "documents"))
    today = con["today"]

    # header
    m = find(r"HANGEUL DAILY BRIEF — (\d{1,2} \w+ \d{4}), (\d{2}:\d{2}) \(Asia/Dhaka\)")
    if m:
        add("Brief date (Asia/Dhaka)", m.group(1), ind["today_long"])
    find(r"^Facts only, read live from the portal")

    # 1) consultations
    find(r"^1\) CONSULTATIONS TODAY")
    m = find(r"Received: (\d+)\s+\|\s+Done: (\d+) \((\d+) consulted, (\d+) file opened\)")
    if m:
        add("Consultation requests received today", m.group(1), today["received"])
        add("Consultations done today (Consulted + File Opened)", m.group(2), today["done"])
        add("Marked Consulted today", m.group(3), today["by_status"].get("consulted", 0))
        add("Marked File Opened today", m.group(4), today["by_status"].get("file_opened", 0))
    elif find(r"None received today"):
        add("Consultation requests received today", 0, today["received"])
    m = find(r"New / pending: (\d+)\s+\|\s+No answer: (\d+)\s+\|\s+Wrong number: (\d+)")
    if m:
        add("Requests still New today", m.group(1), today["by_status"].get("new", 0))
        add("No answer today", m.group(2), today["by_status"].get("no_answer", 0))
        add("Wrong number today", m.group(3), today["by_status"].get("wrong_number", 0))
    other = {s: n for s, n in today["by_status"].items()
             if s not in ("consulted", "file_opened", "new", "no_answer", "wrong_number")}
    m = find(r"Other status: (.+)")
    add("Other statuses today", m.group(1) if m else "(none shown)", other or "(none)",
        match=(bool(m) == bool(other)))
    m = find(r"Done by: (.+)")
    if m:
        said = {n.strip(): int(c) for n, c in re.findall(r"([^,]+?) (\d+)(?:,|$)", m.group(1))}
        ind_by = {k.upper(): v for k, v in today["done_by_last_updated_by"].items()}
        add("Done today by counsellor (status last updated by)", said, today["done_by_last_updated_by"],
            match={k.upper(): v for k, v in said.items()} == ind_by,
            note=f"assigned consultant of those rows: {today['done_by_assigned_consultant']}")
    elif today["done"]:
        add("Done today by counsellor", "(not shown)", today["done_by_last_updated_by"], match=False)
    m = find(r"All time \(the latest (\d+) requests on the page\): (\d+) done, (\d+) new, (\d+) no answer, (\d+) wrong number")
    if m:
        lp = con["latest_on_page"]
        add("Requests on the page (the latest N)", m.group(1), f"{lp['count']} rows parsed; page says {con['shown_on_page']}",
            match=int(m.group(1)) == lp["count"] == con["shown_on_page"])
        for label, val, key in (("done", m.group(2), None), ("new", m.group(3), "new"),
                                ("no answer", m.group(4), "no_answer"), ("wrong number", m.group(5), "wrong_number")):
            sub = lp["done"] if key is None else lp["by_status"].get(key, 0)
            chip = (sum(con["chips"].get(s, 0) for s in DONE_STATUSES) if key is None else con["chips"].get(key))
            add(f"'All time' {label} (brief counts the latest {m.group(1)} rows only)", val,
                f"latest-{lp['count']} rows: {sub}; portal's own all-time chip (All {con['chips'].get('all')}): {chip}",
                match=int(val) == sub == chip,
                note="matches the latest-500 subset" if int(val) == sub else "")

    # 2) verified students
    find(r"^2\) PAYMENT-VERIFIED STUDENTS TODAY")
    vt = stu["verified_today"]
    if find(r"^• None today$"):
        add("Payment-verified students today", 0, len(vt),
            note=f"scanned {stu['pages']} pages / {stu['students']} students / {stu['rows_with_verified_by_line']} "
                 f"'Payment verified by' lines; most recent: {stu['most_recent_verifications'][:1]}")
    else:
        m = find(r"^• (\d+) students?(?:\s+\|\s+Total: ([\d,\.]+) BDT)?")
        if m:
            add("Payment-verified students today", m.group(1), len(vt))
            if m.group(2):
                add("Total verified today (BDT)", m.group(2), f"{stu['verified_today_total_bdt']:,.2f}")
        for i, line in enumerate(lines):
            mm = re.match(r"\s+(\d+)\. (.+)$", line)
            if mm:
                used.add(i)
                n = int(mm.group(1))
                v = vt[n - 1] if n <= len(vt) else None
                expect = (" — ".join(x for x in (v["name"], v["program"], f"{v['verified_income'] or v['paid']} {v['method']}".strip(),
                                                 f"verified by {v['verified_by']} at {v['verified_clock']}") if x)
                          if v else "(no such student)")
                add(f"Verified student #{n}", mm.group(2), expect)

    # 3) portal figures
    find(r"^3\) PORTAL FIGURES")
    tile = {(t["label"], t["href"]): t["text"] for t in dash["tiles"]}
    m = find(r"Pending payments: (\S+) \(students\.php\?status=pending\)(?:; the dashboard tile says (\d+))?")
    if m:
        add("Pending payments (students.php?status=pending)", m.group(1),
            f"{pen['badge']} (badge); {pen['rows_listed']} rows {pen['row_payment_badges']}",
            match=str(pen["badge"]) == m.group(1) == str(pen["rows_listed"]))
    m = find(r"Window applications under review: (\S+) \(window_applications\.php\)(?:; the dashboard tile says (\d+))?")
    if m:
        add("Window applications under review (separate figure)", m.group(1),
            f"filtered page: {win['under_review_filtered_rows']} rows (says 'no match': "
            f"{win['filtered_under_review']['says_no_match']}); full list {win['all']['statuses']}; "
            f"dashboard tile {tile.get(('Under review', 'window_applications.php?status=under_review'))}",
            match=m.group(1) == str(win["under_review_filtered_rows"]) == str(win["under_review_in_full_list"]))
    find(r"two separate figures, never added together")
    for i, line in enumerate(lines):
        mm = re.match(r"• Dashboard, (.+?): (.+)$", line)
        if mm:
            used.add(i)
            for item in mm.group(2).split(" · "):
                lab, num = item.rsplit(" ", 1)
                same = [t for t in dash["tiles"] if t["group"] == mm.group(1) and t["label"] == lab]
                add(f"Dashboard tile '{mm.group(1)} / {lab}'", num, same[0]["text"] if len(same) == 1 else f"{len(same)} tiles",
                    match=len(same) == 1 and same[0]["text"] == num)
    skipped = [t for t in dash["tiles"] if t["label"] not in ("Pending payment", "Under review")]
    listed = sum(len(re.match(r"• Dashboard, .+?: (.+)$", ln).group(1).split(" · "))
                 for ln in lines if ln.startswith("• Dashboard, "))
    add("Dashboard tiles listed (all but the two above)", listed, len(skipped))

    # 4) calendar
    find(r"^4\) TODAY'S CALENDAR REMINDERS")
    m = find(r"^• (\d+) reminders?: (.+)$")
    if m:
        add("Calendar reminders today", m.group(1), f"{len(cal['items'])} (card heading says {cal['heading_count']})",
            match=int(m.group(1)) == len(cal["items"]) == cal["heading_count"])
        said = {k.strip(): int(n) for k, n in re.findall(r"([^,]+?) (\d+)(?:,|$)", m.group(2))}
        add("Calendar reminders by type", said, cal["by_type"], match=said == cal["by_type"])
    elif find(r"None today"):
        add("Calendar reminders today", 0, len(cal["items"]))
    by_title = {i["title"]: i for i in cal["items"]}
    for i, line in enumerate(lines):
        mm = re.match(r"\s+- (.+)$", line)
        if mm:
            used.add(i)
            parts = mm.group(1).split(" — ")
            it = by_title.get(parts[0])
            expect = (" — ".join([it["title"], it["type"], it["range"]] + ([f"{it['days_left']} day{'s' if it['days_left'] != 1 else ''} left"]
                                                                           if it["days_left"] is not None else []))
                      if it else "(no such reminder today)")
            add(f"Reminder '{parts[0]}'", mm.group(1), expect)
    m = find(r"… and (\d+) more")
    if m:
        listed_n = sum(1 for ln in lines if re.match(r"\s+- ", ln))
        add("Reminders not listed ('and N more')", m.group(1), len(cal["items"]) - listed_n)

    # 5) document check
    find(r"^5\) DOCUMENT CHECK \(from the last automated check, not live\)")
    m = find(r"^• (\d+) students: (.+)$")
    if m:
        add("Document check: students", m.group(1), doc["students"])
        said = {k.strip(): int(n) for k, n in re.findall(r"([A-Z ]+?) (\d+)(?:,|$)", m.group(2))}
        add("Document check: verdicts", said, doc["verdicts"], match=said == doc["verdicts"])
    m = find(r"^• Last check: (.+)$")
    if m:
        want = datetime.fromisoformat(doc["latest_document_check"]).strftime("%d %b %Y, %H:%M")
        add("Document check: last check time", m.group(1), want,
            note=f"latest document verdict time; latest field check {doc['latest_field_check']}, "
                 f"results.json written {doc['results_json_modified']}")

    # the LLM summary
    m = find(r"Summary by the local AI, its numbers checked against the facts: (.+)$")
    summary = {"text": m.group(1) if m else None, "clauses": []}
    if m:
        pairs = [("pending payment", pen["badge"]), ("window application", win["under_review_filtered_rows"]),
                 ("under review", win["under_review_filtered_rows"]),
                 ("file opened", today["by_status"].get("file_opened", 0)),
                 ("no answer", today["by_status"].get("no_answer", 0)),
                 ("wrong number", today["by_status"].get("wrong_number", 0)),
                 ("reminder", len(cal["items"])), ("verified", len(vt)),
                 ("still new", today["by_status"].get("new", 0)), ("are new", today["by_status"].get("new", 0)),
                 ("received", today["received"]), ("request", today["received"]),
                 ("done", today["done"]), ("marked consulted", today["by_status"].get("consulted", 0)),
                 ("consultations were done", today["done"]), ("consulted", today["by_status"].get("consulted", 0))]
        for clause in re.split(r"(?<=[.!?])\s+|,\s*|\s+and\s+|;\s*", m.group(1)):
            if not clause.strip():
                continue
            nums = [int(x) for x in re.findall(r"\b\d+\b", clause)]
            nums += [NUMBER_WORDS[w] for w in re.findall(r"[a-z]+", clause.lower()) if w in NUMBER_WORDS]
            about = next(((k, v) for k, v in pairs if k in clause.lower()), None)
            ok = bool(nums) and about is not None and all(n == about[1] for n in nums)
            summary["clauses"].append({"clause": clause.strip(), "numbers": nums,
                                       "about": about[0] if about else None,
                                       "independent": about[1] if about else None, "match": ok})
            add(f"LLM summary clause: {clause.strip()!r}", nums, about[1] if about else "(no matching fact)",
                match=ok)

    # lines no data backs, and words that must never appear
    for i, line in enumerate(lines):
        if i not in used and line.strip():
            unbacked.append(line)
    red_flags = []
    for pat, why in ((r"\b[A-Z]{0,2}\d{7,10}\b", "passport-number-like token"), (r"\b\d{4}-\d{2}-\d{2}\b", "ISO date (DOB?)"),
                     (r"(?i)\bvisas?\b", "visa"), (r"(?i)conversion|%", "conversion/percent"),
                     (r"(?i)prepared by|operations team|\bytd\b", "template filler"),
                     (r"(?i)scanned image|matched\b", "passport-match claim"), (r"(?i)\bsent\b", "'sent' filler")):
        for line in lines:
            if re.search(pat, line):
                red_flags.append({"why": why, "line": line})
    return {"checks": checks, "unbacked_lines": unbacked, "red_flags": red_flags, "summary": summary}


def main():
    args = sys.argv[1:]
    out_json = None
    if "--json" in args:
        k = args.index("--json")
        out_json = Path(args[k + 1])
        del args[k:k + 2]
    brief_path = Path(args[0]) if args else HERE / "brief_verify.txt"
    brief_text = brief_path.read_text(encoding="utf-8")

    now = datetime.now(TZ)
    today = now.date()
    p = Portal()
    p.login()
    ind = {"read_at": now.isoformat(timespec="seconds"), "today_long": today.strftime("%d %B %Y")}
    ind["consultations"] = read_consultations(p, today)
    ind["students"] = read_students(p, today)
    ind["pending"] = read_pending(p)
    ind["window"] = read_window_apps(p)
    ind["dashboard"] = read_dashboard(p)
    ind["calendar"] = read_calendar(p)
    ind["documents"] = read_documents()
    ind["finished_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    ind["requests"] = p.log
    result = compare(brief_text, ind)

    for c in result["checks"]:
        print(f"[{'OK ' if c['match'] else 'BAD'}] {c['claim']}: brief={c['brief_value']} | independent={c['independent_value']}"
              + (f"  ({c['note']})" if c["note"] else ""))
    print("\nLines not backed by a check:", *([f"  {x}" for x in result["unbacked_lines"]] or ["  (none)"]), sep="\n")
    print("\nRed-flag patterns:", *([f"  {x}" for x in result["red_flags"]] or ["  (none)"]), sep="\n")
    print("\nToday's consultation rows (independent):",
          *[f"  {r}" for r in ind["consultations"]["today"]["rows"]], sep="\n")
    print("\nRequests:", *(f"  {x}" for x in p.log), sep="\n")
    if out_json:
        ind["students"]["verified_today"] = [{k: v for k, v in s.items()} for s in ind["students"]["verified_today"]]
        out_json.write_text(json.dumps({"independent": ind, **result}, indent=2, ensure_ascii=False, default=str),
                            encoding="utf-8")


if __name__ == "__main__":
    main()
