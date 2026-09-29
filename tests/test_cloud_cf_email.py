"""Regression tests for the dry run's Cloudflare finding (29 Sep) and its minor one.

hangeul.com.bd is served through Cloudflare, whose e-mail obfuscation rewrites every address in a
page's HTML. The parsers stored the stand-in text instead: every student's details.Email and nearly
every consultation's contact was "[email protected]". What is pinned here:

  decode       parsers.decode_cf_emails puts every hidden address back as a browser shows it: the a
               and span forms (class __cf_email__, data-cfemail="HEX") become the address as plain
               text, a link to /cdn-cgi/l/email-protection#HEX gets a mailto href; a known synthetic
               address makes the round trip; a malformed or empty HEX leaves the element as it is;
               nothing is fetched; a form field's value attribute is kept as it is
  every page   each portal page parse decodes first (every BeautifulSoup construction in src/ is
               wrapped in decode_cf_emails): students.php (list and details), consult_requests.php
               (table and tabs), student_edit.php, progress.php, calendar.php, index.php and
               window_applications.php
  no stand-in  a stand-in that cannot be decoded is a filler to records (blanked, and named in
               blank_on_portal) and is left out of a longer text (a request's contact), so no
               record ever holds a fake address
  one line     with gte-small missing, the embedding process logs only the hangeul warning: the
               sentence_transformers / transformers / huggingface_hub loggers are kept at WARNING

Every address here is synthetic (example.com / example.org). Nothing reaches the network.
"""
import asyncio
import importlib.util
import json
import logging
import socket
import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_cloud import no_placeholder  # noqa: E402
from test_consultations import _page as consult_page, _row as consult_row  # noqa: E402
from test_foundation import page as students_page, portal, row as student_row  # noqa: E402,F401

from src.bot import ask  # noqa: E402
from src.cloud import embed, handoff, records  # noqa: E402
from src.scraper import parsers  # noqa: E402
from src.scraper.client import HangeulAdminClient, admin_client  # noqa: E402
from src.scraper.parsers import decode_cf_emails  # noqa: E402

T0 = "2026-09-29T10:00:00+06:00"
ADDRESS = "student.one@example.com"          # synthetic
OTHER = "lead.two@example.org"               # synthetic
STAND_IN_HTML = "[email&#160;protected]"     # what Cloudflare writes in the HTML
STAND_IN = "[email\xa0protected]"            # what a parser reads of it
CF_SCRIPT = ('<script data-cfasync="false" src="/cdn-cgi/scripts/5c5dd728/cloudflare-static/'
             'email-decode.min.js"></script>')
BAD_HEX = ("", "zz", "4", "42", "4g2302", "422302206c212", "5a", "5a5a")


def hide(address: str, key: int = 0x5A) -> str:
    """`address` as Cloudflare hides it: the key byte, then each UTF-8 byte XOR the key, in hex."""
    return f"{key:02x}" + "".join(f"{b ^ key:02x}" for b in address.encode("utf-8"))


def a_form(address: str = ADDRESS, hexstr=None) -> str:
    """An address in the page's text, as Cloudflare serves it."""
    h = hide(address) if hexstr is None else hexstr
    return f'<a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="{h}">{STAND_IN_HTML}</a>'


def span_form(address: str = ADDRESS, hexstr=None) -> str:
    h = hide(address) if hexstr is None else hexstr
    return f'<span class="__cf_email__" data-cfemail="{h}">{STAND_IN_HTML}</span>'


def link_form(address: str = ADDRESS, hexstr=None, text=None) -> str:
    """A mailto link, as Cloudflare serves it: the link to its protection page with the address
    hidden in the fragment, its text the span form (or the link's own words)."""
    h = hide(address) if hexstr is None else hexstr
    return f'<a href="/cdn-cgi/l/email-protection#{h}">{span_form(address, hexstr) if text is None else text}</a>'


def soup_of(html: str) -> BeautifulSoup:
    return decode_cf_emails(BeautifulSoup(html, "html.parser"))


# --------------------------------------------------------------------------- 1. the decoder

def test_a_known_address_makes_the_round_trip_with_any_key():
    assert parsers._cf_address("422302206c212d") == "a@b.co"          # worked by hand: key 0x42
    for key in (0x00, 0x01, 0x42, 0x5A, 0xA7, 0xFF):
        assert parsers._cf_address(hide(ADDRESS, key)) == ADDRESS, key
        assert parsers._cf_address(hide(ADDRESS, key).upper()) == ADDRESS, key
    assert parsers._cf_address(hide("émile.kim@example.com")) == "émile.kim@example.com"     # UTF-8


def test_the_a_form_becomes_the_address_as_plain_text():
    soup = soup_of(f'<div class="pii stu-mail">{a_form()}</div>{CF_SCRIPT}')
    div = soup.select_one(".stu-mail")
    assert div.get_text() == ADDRESS and div.find("a") is None
    assert "__cf_email__" not in str(soup) and "protected" not in str(soup)
    # joined to the text around it, one text as a browser shows it
    p = soup_of(f"<p>Email: {a_form()} (student)</p>").p
    assert p.get_text(strip=True) == f"Email: {ADDRESS} (student)" and len(list(p.strings)) == 1


def test_the_span_form_becomes_the_address_as_plain_text():
    soup = soup_of(f'<table><tr><td class="c">{span_form()}</td><td>{span_form(OTHER)}</td></tr></table>')
    assert [td.get_text() for td in soup.find_all("td")] == [ADDRESS, OTHER]
    assert soup.find("span") is None


def test_the_link_form_gets_a_mailto_href_and_its_text():
    soup = soup_of(f'<div class="cr-contact">{link_form(OTHER)}</div>')
    a = soup.find("a")
    assert a["href"] == f"mailto:{OTHER}" and a.get_text() == OTHER and a.find("span") is None
    own = soup_of(link_form(OTHER, text="Write to the student")).find("a")
    assert own["href"] == f"mailto:{OTHER}" and own.get_text() == "Write to the student"


@pytest.mark.parametrize("bad", BAD_HEX + (hide("no-at-sign.example.com"), hide("two words@example.com"),
                                           hide("tab\t@example.com")))
def test_a_malformed_or_empty_hex_leaves_the_element_as_the_page_has_it(bad):
    for markup in (a_form(hexstr=bad), span_form(hexstr=bad)):
        soup = soup_of(f"<div>{markup}</div>")
        assert soup.div.get_text() == STAND_IN and "__cf_email__" in str(soup), markup
    link = soup_of(link_form(hexstr=bad)).find("a")
    assert link["href"] == f"/cdn-cgi/l/email-protection#{bad}" and link.get_text() == STAND_IN
    # the class without any data-cfemail (students.php's test rows) is left alone too
    bare = f'<a class="__cf_email__" href="/cdn-cgi/l/email-protection">{STAND_IN_HTML}</a>'
    assert soup_of(bare).a.get_text() == STAND_IN


def test_decoding_needs_no_network_and_twice_is_once(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("decoding must not reach the network")
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    html = f"<div><p>{a_form()}</p><p>{link_form(OTHER)}</p><p>{span_form(hexstr='zz')}</p></div>{CF_SCRIPT}"
    once = soup_of(html)
    assert str(decode_cf_emails(once)) == str(soup_of(html))
    tag = BeautifulSoup(span_form(), "html.parser").span          # a tag passed on its own
    assert decode_cf_emails(tag).get_text() == ADDRESS
    assert decode_cf_emails(None) is None and decode_cf_emails("text") == "text"


def test_student_edit_form_values_are_kept_as_they_are(portal, monkeypatch):
    html = ('<html><body><form method="POST"><input type="hidden" name="_csrf" value="t0k3n">'
            '<input name="full_name" value="TEST STUDENT ONE">'
            f'<input name="email" value="{ADDRESS}">'
            f'<input name="guardian_email" value="{STAND_IN_HTML}">'
            f'<textarea name="notes">Write to {span_form(OTHER)} first</textarea>'
            '<select name="payment_status"><option>Verified</option><option selected>Pending</option></select>'
            f'</form><p>Questions? {a_form(OTHER)}</p></body></html>{CF_SCRIPT}')
    soup = soup_of(html)
    assert soup.find("input", attrs={"name": "email"})["value"] == ADDRESS                    # untouched
    assert soup.find("input", attrs={"name": "guardian_email"})["value"] == STAND_IN          # as served
    fields = HangeulAdminClient._profile_fields(html)
    assert fields == {"full_name": "TEST STUDENT ONE", "email": ADDRESS, "guardian_email": STAND_IN,
                      "notes": f"Write to {OTHER} first", "payment_status": "Pending"}
    # the older reader of the same page (the /sendmail fallback's)
    monkeypatch.setattr(admin_client, "_profile_cache", {}, raising=False)
    portal.pages["student_edit.php?id=425"] = html
    profile = asyncio.run(admin_client.get_student_full_profile("425"))
    assert profile["email"] == ADDRESS and profile["notes"] == f"Write to {OTHER} first"
    # a stand-in value is no address: blanked and named, never published as one
    r = records.student_profile("425", fields, T0)
    assert r["data"]["email"] == ADDRESS and r["data"]["guardian_email"] == ""
    assert r["data"]["blank_on_portal"] == ["guardian_email"] and "protected" not in r["content"]
    assert f"email: {ADDRESS}" in r["content"]


# --------------------------------------------------------------------------- 2. every page, end to end

def cf_student(uid=425, sl=1, name="TEST STUDENT ONE", hexstr=None, **kw) -> str:
    """test_foundation.row with the Student cell's address and a details Email as Cloudflare serves
    them (the a form, as students.php's live rows have it)."""
    html = student_row(uid, sl, name, hng=f"HNG-2026-{uid}", **kw)
    bare = f'<a class="__cf_email__" href="/cdn-cgi/l/email-protection">{STAND_IN_HTML}</a>'
    assert bare in html
    html = html.replace(bare, a_form(hexstr=hexstr))
    email = f'<div class="det-item"><label>Email</label><span>{a_form(hexstr=hexstr)}</span></div>'
    return html.replace('<div class="det">', '<div class="det">' + email, 1)


def test_students_php_list_and_details_read_the_real_address():
    (s,) = parsers.parse_students_page(students_page(cf_student()) + CF_SCRIPT)["students"]
    assert s["details"]["Email"] == ADDRESS and s["student_name"] == "TEST STUDENT ONE"
    assert s["student_id"] == "HNG-2026-425" and s["uid"] == "425"
    r = records.student(s, T0)
    assert r["data"]["details"]["Email"] == ADDRESS and "blank_on_portal" not in r["data"]
    assert f"Email {ADDRESS}." in r["content"]
    assert "protected" not in json.dumps(r, ensure_ascii=False)
    no_placeholder(r)
    (p,) = records.pending_payments(parsers.parse_students_page(students_page(cf_student(pay="Pending")))["students"], 1, T0)
    assert p["data"]["details"]["Email"] == ADDRESS and f"Email {ADDRESS}." in p["content"]


def test_a_student_cell_without_its_name_class_never_takes_the_address_for_the_name():
    html = cf_student().replace('<strong class="pii stu-name">TEST STUDENT ONE</strong>', "")
    html = html.replace('<div class="stu-tags">', '<strong class="pii">TEST STUDENT ONE</strong><div class="stu-tags">', 1)
    (s,) = parsers.parse_students_page(students_page(html))["students"]
    assert s["student_name"] == "TEST STUDENT ONE"


def test_a_students_address_that_cannot_be_decoded_is_no_value_and_is_named():
    for bad in ("zz", ""):
        (s,) = parsers.parse_students_page(students_page(cf_student(hexstr=bad)))["students"]
        assert records.is_filler(s["details"]["Email"])                   # the stand-in, as served
        r = records.student(s, T0)
        assert r["data"]["details"]["Email"] == "" and r["data"]["blank_on_portal"] == ["details.Email"]
        assert "protected" not in json.dumps(r, ensure_ascii=False) and "Email" not in r["content"]
        no_placeholder(r)
        (p,) = records.pending_payments(
            parsers.parse_students_page(students_page(cf_student(hexstr=bad, pay="Pending")))["students"], 1, T0)
        assert p["data"]["details"]["Email"] == "" and "details.Email" in p["data"]["blank_on_portal"]
        assert "protected" not in json.dumps(p, ensure_ascii=False)


def cf_request(name_markup: str, contact_markup: str, details_markup: str = "", rid: str = "9001", **kw) -> str:
    """test_consultations._row with its name, contact line and details as Cloudflare serves them."""
    html = consult_row("PLACEHOLDER", "Consulted", "28 Sep 2026", by="Counsellor B", **kw)
    html = html.replace("PLACEHOLDER", name_markup)
    html = html.replace('<a class="ph"><i></i>01700000000</a>',
                        f'<a class="ph" href="tel:01700000000"><i></i>01700000000</a> {contact_markup}')
    if details_markup:
        html = html.replace("<span>2000-01-01</span></div>",
                            f'<span>2000-01-01</span></div><div class="kv"><b>Email</b><span>{details_markup}</span></div>')
    return html.replace("<form>", f'<form><input type="hidden" name="id" value="{rid}">', 1)


def test_consult_requests_table_and_tabs_read_the_real_addresses():
    # a name typed as an address (inside the .cr-name link: the span form), the contact line's
    # mailto link (the link form) and an address in the details' text (the a form)
    row = cf_request(span_form(), link_form(OTHER), a_form(OTHER))
    html = consult_page(row) + CF_SCRIPT
    view = parsers.consultation_view(html)
    (got,) = view["rows"]
    assert got["name"] == ADDRESS and got["contact"] == f"01700000000 {OTHER}"
    assert got["details"] == f"DOB 2000-01-01 Email {OTHER}" and got["id"] == "9001"
    assert view["tabs"]["All"] == 1 and view["tabs"]["Consulted"] == 1
    assert parsers.consultation_rows(html) == [got] and parsers.consultation_table(html) == [got]
    r = records.consultation(got, "2026-09-28", T0)
    assert r["data"]["contact"] == f"01700000000 {OTHER}" and r["data"]["name"] == ADDRESS
    assert f"Consultation request from {ADDRESS} (01700000000 {OTHER})" in r["content"]
    assert "protected" not in json.dumps(r, ensure_ascii=False) and "blank_on_portal" not in r["data"]
    no_placeholder(r)


def test_a_request_whose_addresses_cannot_be_decoded_publishes_no_stand_in():
    row = cf_request(span_form(hexstr="zz"), link_form(OTHER, hexstr=""), a_form(hexstr="4"))
    (got,) = parsers.consultation_view(consult_page(row))["rows"]
    assert got["contact"] == "01700000000" and got["details"] == "DOB 2000-01-01 Email"
    assert got["name"] == STAND_IN                                         # left as the page has it
    r = records.consultation(got, "2026-09-28", T0)
    assert r["key"] == "9001" and r["data"]["name"] == "" and r["data"]["blank_on_portal"] == ["name"]
    assert "protected" not in json.dumps(r, ensure_ascii=False)
    assert r["content"].startswith("Consultation request (01700000000), received 28 Sep 2026 10:15.")


def test_the_other_portal_pages_decode_before_reading():
    progress = ('<div class="pg-ring"><b>22%</b></div><div class="pg-now"><div class="pg-stage">Payment Verified</div>'
                f'<div class="pg-status">Waiting for {span_form(OTHER)}</div></div>')
    assert parsers.parse_progress_page(progress)["status"] == f"Waiting for {OTHER}"
    calendar = ('<div class="cal-card"><div class="sec-h">Reminders for today · 1 items</div><div class="rm-item"><div>'
                '<a class="rm-title" href="calendar.php?edit=7">Call the embassy</a>'
                '<div><span>Task</span> · 28 Sep · today</div>'
                f'<div>Write to {a_form(OTHER)} about the visa</div></div></div></div>')
    (rem,) = parsers.parse_calendar_events(calendar)["today_reminders"]
    assert rem["note"] == f"Write to {OTHER} about the visa" and rem["id"] == "7"
    windows = ("<table><tr><th>Student</th><th>Window</th><th>Status</th></tr>"
               f'<tr><td>TEST STUDENT ONE {span_form()}</td><td>W1</td><td><span class="status-pill">Under Review</span></td></tr></table>')
    assert parsers.parse_window_applications(windows) == [
        {"student": f"TEST STUDENT ONE {ADDRESS}", "window": "W1", "status": "Under Review"}]
    index = ('<div class="dash-sec"><h2 class="ds-t">Direct / legacy pipeline</h2></div><div class="stats-row">'
             '<a class="stat-card" href="students.php"><span class="stat-num">5</span>'
             '<span class="stat-lbl">Total students</span></a></div>'
             '<div class="card"><div class="card-title">Needs attention</div><div class="wf-item"><div class="wf-info">'
             f'<strong>Unanswered e-mail</strong><span>from {a_form(OTHER)}</span></div>'
             '<div class="wf-count">2</div></div></div>')
    assert parsers.parse_hangeul_live_dashboard(index)["summary"]["total_students"] == 5
    note = [f.note for f in ask.dashboard_facts(index) if f.label == "Unanswered e-mail"]
    assert note == [f"from {OTHER}"]


def test_every_page_parse_in_src_decodes_right_after_building_its_soup():
    wrapped = []
    for path in sorted((BOT_ROOT / "src").rglob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "BeautifulSoup(" in line and "import" not in line:
                assert "decode_cf_emails(BeautifulSoup(" in line, f"{path.relative_to(BOT_ROOT)}:{n}: {line.strip()}"
                wrapped.append(path.name)
    # students.php, consult_requests.php, progress, calendar, index, window applications, the
    # login page and the generic crawl (parsers); student_edit.php twice (client); the index cards
    # (ask); the verified-documents list (verified_docs)
    assert wrapped.count("parsers.py") == 12 and wrapped.count("client.py") == 2
    assert wrapped.count("ask.py") == 1 and wrapped.count("verified_docs.py") == 1


def test_the_stand_in_alone_is_a_filler_and_an_address_is_not():
    for value in (STAND_IN, "[email protected]", " [EMAIL PROTECTED] ", "[email\xa0\xa0protected]"):
        assert records.is_filler(value, "Email") and records.is_filler(value, "contact"), repr(value)
    for value in (ADDRESS, "01700000000 [email protected]", "email protected by the office"):
        assert not records.is_filler(value, "Email"), value


# --------------------------------------------------------------------------- 3. one log line for a missing model

@pytest.fixture
def library_levels():
    """The model libraries' logger levels, put back after the test."""
    saved = {name: logging.getLogger(name).level for name in embed.QUIET_LOGGERS}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def test_the_model_libraries_log_nothing_under_warning(library_levels, caplog):
    logging.getLogger("sentence_transformers").setLevel(logging.NOTSET)
    logging.getLogger("transformers").setLevel(logging.ERROR)              # its own, stricter: kept
    logging.getLogger("huggingface_hub").setLevel(logging.INFO)
    embed.quiet_libraries()
    assert [logging.getLogger(n).level for n in embed.QUIET_LOGGERS] == [logging.WARNING, logging.ERROR, logging.WARNING]
    caplog.set_level(logging.INFO)                                         # the processes log at INFO
    logging.getLogger("sentence_transformers.base.model").info("No modules.json found for the model")
    logging.getLogger("huggingface_hub.file_download").info("a download note")
    logging.getLogger("sentence_transformers.base.model").warning("a real problem")
    assert [(r.name, r.levelname) for r in caplog.records] == [("sentence_transformers.base.model", "WARNING")]


def test_prepare_process_quiets_the_model_libraries(library_levels, monkeypatch):
    for key, value in (("CUDA_VISIBLE_DEVICES", embed.NO_GPU), ("HF_HUB_OFFLINE", "1"),
                       ("HF_HUB_DISABLE_PROGRESS_BARS", "1"), ("TQDM_DISABLE", "1"),
                       ("TRANSFORMERS_VERBOSITY", "error"), ("TOKENIZERS_PARALLELISM", "false")):
        monkeypatch.setenv(key, value)                                     # put back after the test
    for name in embed.QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)
    embed.prepare_process()
    assert all(logging.getLogger(n).level == logging.WARNING for n in embed.QUIET_LOGGERS)


MISSING_MODEL = r"""
import logging, os, socket, sys

def no_network(*args, **kwargs):
    raise OSError("this test reaches no network")
socket.socket.connect = socket.socket.connect_ex = no_network
socket.create_connection = socket.getaddrinfo = no_network
for k in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "SENTENCE_TRANSFORMERS_HOME", "TRANSFORMERS_CACHE", "HF_HOME"):
    os.environ.pop(k, None)
os.environ["HF_HOME"] = sys.argv[1]           # an empty cache: gte-small is not there
from src.cloud import embed
embed.prepare_process()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
try:
    embed.GteSmall().embed(["a text"])
except embed.EmbedError as e:
    logging.getLogger("hangeul.cloud").warning("Supabase publish failed (test): %s", e)
"""


@pytest.mark.skipif(importlib.util.find_spec("sentence_transformers") is None,
                    reason="sentence_transformers is not installed here")
def test_a_missing_model_costs_the_embedding_process_exactly_one_log_line(tmp_path):
    empty = tmp_path / "hf"
    empty.mkdir()
    log = tmp_path / "child.log"
    with open(log, "a", encoding="utf-8") as out:
        proc = handoff.start(["-c", MISSING_MODEL, str(empty)], out)     # as the publisher is started
    assert proc.wait(timeout=600) == 0, log.read_text(encoding="utf-8")[-1500:]
    lines = [x for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1, lines
    assert "[WARNING] hangeul.cloud: Supabase publish failed (test): gte-small could not be loaded" in lines[0]
    assert not any(empty.rglob("*.safetensors")) and not any(empty.rglob("*.bin"))   # nothing downloaded
