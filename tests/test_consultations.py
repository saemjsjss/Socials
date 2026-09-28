"""consult_requests.php is read by column NAME, so a portal layout change cannot silently turn
every count into 0 again (Sep 2026: the table went from 8+ fixed columns to 7 named ones)."""
from src.scraper.parsers import consultation_rows, parse_consultation_requests

HEADER = ("<tr><th>Student</th><th>Consultant</th><th>City &amp; program</th><th>Received</th>"
          "<th>Status</th><th>Remarks</th><th>Update status</th></tr>")


def _row(name, status, day, by=None, consultant="Staff One"):
    by_html = f'<div class="cr-by"><i></i>{by}</div>' if by else ""
    return (
        "<tr>"
        f'<td><div class="cr-who"><span class="cr-av">A</span><a class="cr-name">{name}<i></i></a></div>'
        '<div class="cr-contact"><a class="ph"><i></i>01700000000</a></div></td>'
        f'<td><span class="cr-cons"><i></i>{consultant}</span></td>'
        '<td><div class="cr-loc"><span class="city"><i></i>Dhaka</span>'
        '<span class="prog"><i></i>Bachelor\'s Degree</span></div>'
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


def _page(*rows):
    return f"<html><body><table>{HEADER}{''.join(rows)}</table></body></html>"


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
    assert rows[1]["handled_by"] == "Staff One"                   # no .cr-by: the consultant


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
