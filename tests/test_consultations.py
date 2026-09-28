"""consult_requests.php is read by column NAME, so a portal layout change cannot silently turn
every count into 0 again (Sep 2026: the table went from 8+ fixed columns to 7 named ones)."""
import re
from collections import Counter

from src.scraper.parsers import consultation_rows, consultation_view, parse_consultation_requests

HEADER = ("<tr><th>Student</th><th>Consultant</th><th>City &amp; program</th><th>Received</th>"
          "<th>Status</th><th>Remarks</th><th>Update status</th></tr>")


def _row(name, status, day, by=None, consultant="Staff One", city="Dhaka", program="Bachelor's Degree"):
    by_html = f'<div class="cr-by" title="Last updated by"><i></i>{by}</div>' if by else ""
    return (
        "<tr>"
        f'<td><div class="cr-who"><span class="cr-av">A</span><a class="cr-name">{name}<i></i></a></div>'
        '<div class="cr-contact"><a class="ph"><i></i>01700000000</a></div></td>'
        f'<td><span class="cr-cons"><i></i>{consultant}</span></td>'
        f'<td><div class="cr-loc"><span class="city"><i></i>{city}</span>'
        f'<span class="prog"><i></i>{program}</span></div>'
        '<details class="crd"><summary>View details</summary><div class="crd-body">'
        '<div class="kv"><b>DOB</b><span>2000-01-01</span></div></div></details></td>'
        f'<td><span class="d">{day}</span><span class="t">10:15</span></td>'
        f'<td><span class="stbadge"><span class="dot"></span>{status}</span>{by_html}</td>'
        '<td><form><textarea class="rmk" name="remarks">called twice</textarea></form></td>'
        '<td><div class="cr-acts"><form class="cr-inline"><select class="stsel" name="set_status">'
        "<option>New</option><option>No Answer</option><option>Wrong Number</option>"
        "<option>Consulted</option><option>File Opened</option></select></form></div></td>"
        "</tr>"
    )


TAB_VALUES = {"All": "all", "New": "new", "No Answer": "no_answer", "Wrong Number": "wrong_number",
              "Consulted": "consulted", "File Opened": "file_opened"}
EMPTY_ROW = ('<tr class="cr-empty-row"><td class="cr-empty" colspan="7"><div class="cr-empty-in"><span class="ic">'
             '<i class="fas fa-inbox"></i></span><b>No consultation requests yet.</b>'
             "<span>Try a different search, consultant or date range.</span></div></td></tr>")


def _statuses(rows):
    return re.findall(r'<span class="stbadge"><span class="dot"></span>([^<]+)</span>', "".join(rows))


def _page(*rows, counts=None, status="all", day_from="", day_to="", listed=None):
    """consult_requests.php laid out like the live page (Sep 2026): the status tabs with their own
    counts (by default the listed rows' own, as under a date filter; `counts` for the all-time
    ones), the GET search form showing its filter, the "N requests · newest first" caption, and the
    table (the portal's own "No consultation requests yet." row when it is empty)."""
    if counts is None:
        counts = Counter(_statuses(rows))
        counts["All"] = len(rows)
    query = f"&from={day_from}&to={day_to}" if day_from or day_to else ""
    tabs = "".join(f'<a class="st-{v}{" on" if v == status else ""}" href="?status={v}{query}"><span class="dot">'
                   f'</span>{label} <span class="n">{counts.get(label, 0)}</span></a>' for label, v in TAB_VALUES.items())
    form = (f'<form class="cr-search" method="get"><input type="hidden" name="status" value="{status}">'
            '<input name="q" value=""><select name="cons"><option value="">All consultants</option></select>'
            f'<input type="date" name="from" value="{day_from}"><input type="date" name="to" value="{day_to}"></form>')
    caption = f'<span><b>{len(rows) if listed is None else listed}</b> requests · newest first</span>'
    body = "".join(rows) or EMPTY_ROW
    return (f'<html><body><nav class="cr-tabs" aria-label="Filter by status">{tabs}</nav>{form}{caption}'
            f"<table>{HEADER}{body}</table></body></html>")


def test_new_layout_reads_every_field():
    html = _page(_row("Student A", "Consulted", "28 Sep 2026", by="Counsellor B"),
                 _row("Student C", "New", "27 Sep 2026"))
    rows = consultation_rows(html)
    assert [r["status"] for r in rows] == ["Consulted", "New"]     # not the <select> options
    first = rows[0]
    assert first["name"] == "Student A"
    assert first["city"] == "Dhaka" and first["program"] == "Bachelor's Degree"
    assert first["consultant"] == "Staff One" and first["handled_by"] == "Counsellor B"
    assert first["received"] == "28 Sep 2026 10:15" and first["received_date"] == "28 Sep 2026"
    assert first["remarks"] == "called twice"
    # No .cr-by: nobody has handled it yet. The assigned consultant is not its handler.
    assert rows[1]["handled_by"] == "" and rows[1]["consultant"] == "Staff One"


def test_the_portals_dash_is_no_city_or_program():
    rows = consultation_rows(_page(_row("A", "New", "27 Sep 2026", city="—", program="—"),
                                   _row("B", "New", "27 Sep 2026", city="Sylhet")))
    assert (rows[0]["city"], rows[0]["program"]) == ("", "") and rows[1]["city"] == "Sylhet"


def test_a_name_behind_cloudflares_email_protection_is_what_a_browser_shows():
    hidden = "42" + "".join(f"{ord(ch) ^ 0x42:02x}" for ch in "student.one@example.com")
    row = _row("PLACEHOLDER", "Consulted", "20 Aug 2026", by="X").replace(
        "PLACEHOLDER", f'<span class="__cf_email__" data-cfemail="{hidden}">[email&#160;protected]</span>')
    rows = consultation_rows(_page(row))
    assert rows[0]["name"] == "student.one@example.com"                # never "[email protected]"
    broken = row.replace(hidden, "zz")
    assert consultation_rows(_page(broken))[0]["name"] == "[email\xa0protected]"   # left as the page has it


def test_a_view_gives_its_own_status_counts_filter_and_caption():
    totals = {"All": 999, "New": 8, "No Answer": 153, "Wrong Number": 40, "Consulted": 792, "File Opened": 6}
    view = consultation_view(_page(_row("A", "File Opened", "13 Sep 2026", by="X"), counts=totals, status="file_opened"))
    assert view["tabs"] == totals and view["status"] == "file_opened"
    assert (view["from"], view["to"], view["listed"]) == ("", "", 1) and len(view["rows"]) == 1

    day = consultation_view(_page(_row("A", "Consulted", "08 Sep 2026", by="X"), _row("B", "New", "08 Sep 2026"),
                                  day_from="2026-09-08", day_to="2026-09-08"))
    assert day["tabs"] == {"All": 2, "New": 1, "No Answer": 0, "Wrong Number": 0, "Consulted": 1, "File Opened": 0}
    assert (day["status"], day["from"], day["to"], day["listed"]) == ("all", "2026-09-08", "2026-09-08", 2)

    empty = consultation_view(_page(day_from="2026-01-01", day_to="2026-01-01"))
    assert empty["rows"] == [] and empty["tabs"]["All"] == 0          # the portal's own "none" row: a real 0


def test_a_view_it_cannot_read_says_so():
    good = _page(_row("A", "New", "08 Sep 2026"))
    assert consultation_view(good.replace('class="cr-tabs"', 'class="tabs2"'))["tabs"] is None
    assert consultation_view(good.replace('<span class="n">1</span>', '<span class="n">many</span>'))["tabs"] is None
    unreadable = good.replace("<th>Student</th>", "<th>Who</th>")
    assert consultation_view(unreadable)["rows"] is None                # rows there, none readable
    assert consultation_view("<nav class='cr-tabs'></nav>")["rows"] is None


def test_date_filter_uses_the_received_column():
    html = _page(_row("A", "Consulted", "28 Sep 2026"), _row("B", "New", "27 Sep 2026"),
                 _row("C", "No Answer", "28 Sep 2026"))
    assert [r["name"] for r in parse_consultation_requests(html, target_date="28 Sep 2026")] == ["A", "C"]
    assert len(parse_consultation_requests(html)) == 3


def test_columns_found_by_name_even_when_moved():
    moved = HEADER.replace("<th>Consultant</th>", "").replace("<th>Status</th>", "<th>Status</th><th>Consultant</th>")
    row = _row("A", "File Opened", "28 Sep 2026")
    cells = row.split("</td>")
    # move the consultant cell to just after the status cell, like the moved header
    reordered = "</td>".join([cells[0], cells[2], cells[3], cells[4], cells[1], cells[5], cells[6], cells[7]])
    rows = consultation_rows(f"<table>{moved}{reordered}</table>")
    assert rows and rows[0]["status"] == "File Opened" and rows[0]["consultant"] == "Staff One"


def test_unknown_layout_gives_no_rows_rather_than_wrong_ones():
    assert consultation_rows("<table><tr><th>Foo</th><th>Bar</th></tr><tr><td>1</td><td>2</td></tr></table>") == []
    assert consultation_rows("<p>no table</p>") == []
