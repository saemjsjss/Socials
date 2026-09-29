"""What the command handlers and the free-text answers publish to Supabase (src/cloud/command_hooks.py).

What is pinned here:
  hooks       /verified*, /inquiries*, /crosscheck* (and /passports), /admitted, /calendar with words,
              /stats, /students, /alerts and the free-text answers hand the rows they already parsed
              to the publisher: the right kind, scope and complete flag, one handoff file per
              command (job "command"), and Supabase ends up holding them (publish.process_file)
  complete    only a whole read is complete: every page of students.php (no filter), a day the
              portal listed whole, a dashboard with every tile group and card; /students (page 1),
              the dashboard's tiles alone, a capped day, the calendar and the cross-check audits are
              partial; a list whose verification stamps cannot be read publishes its verifications
              as partial; a failed read publishes nothing (never rows=[] with complete=True)
  the reply   is the same with publishing on or off; it never waits for the handoff (a slow one
              runs after the handler returned); a Supabase failure (500, timeout, refused key) or a
              build that fails changes nothing the bot sends and is one log line with no student
              data in it; nothing at all happens while publishing is off or in mock mode

Every portal page is synthetic (the other test files' builders, invented names); Supabase is the
fake of tests/test_cloud.py; nothing reaches the network, Telegram, Ollama or a real Supabase.
"""
import asyncio
import json
import logging
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

from test_cloud import cloud, cloud_warnings, state  # noqa: E402,F401  (cloud is a fixture)
from test_consultations import _row as consult_row  # noqa: E402
from test_crosscheck import audits, the_list, VERDICT  # noqa: E402,F401  (audits is a fixture)
from test_foundation import (  # noqa: E402,F401  (portal is a fixture)
    TODAY, admitted_portal, fake_update, page, portal, report_of, row, verified,
)
from test_freetext import calendar_html, dashboard_page, pending_pages, window_page  # noqa: E402
from test_inquiries import TOTALS, TOTALS_KEY, day_key, day_page, inquiry_portal  # noqa: E402

from src.bot import ask, telegram_bot  # noqa: E402
from src.cloud import command_hooks, handoff, publish, records  # noqa: E402
from src.config import settings  # noqa: E402
from src.llm.ollama_client import ollama_client  # noqa: E402
from src.scraper.client import admin_client  # noqa: E402

SCAN = "passport_{}_1700000000.jpeg"
DASHBOARD_FACTS = len(ask.dashboard_facts(dashboard_page()))      # its tiles and its five cards' figures


@pytest.fixture(autouse=True)
def pinned_today(monkeypatch):
    """28 Sep 2026 in Dhaka (src.bot.ask imported local_today by name, so it is pinned too)."""
    from src import dates
    monkeypatch.setattr(dates, "local_today", lambda: TODAY)
    monkeypatch.setattr(ask, "local_today", lambda: TODAY)


def hooked(handler, text="", args=None, user_data=None):
    """Run a handler as Telegram does, then wait for the handoff it started (the bot never waits)."""
    update, context, chat = fake_update(text, args, user_data)

    async def go():
        await handler(update, context)
        await command_hooks.drain(timeout=60)
    asyncio.run(go())
    return chat


def ask_bot(text):
    return hooked(telegram_bot.handle_natural_language_message, text)


def handoffs(cloud):
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in cloud.spawned]
    assert all(d["job"] == "command" and d["version"] == 1 for d in docs)
    return docs


def shape(cloud):
    """(kind, scope, complete, keys) of every batch handed over."""
    return [(b["kind"], b["scope"], b["complete"], sorted(r["key"] for r in b["rows"]))
            for d in handoffs(cloud) for b in d["batches"]]


def kinds(cloud):
    return [(k, s, c) for k, s, c, _ in shape(cloud)]


def batch_of(cloud, kind):
    found = [b for d in handoffs(cloud) for b in d["batches"] if b["kind"] == kind]
    assert len(found) == 1, (kind, len(found))
    return found[0]


def process(cloud):
    for p in list(cloud.spawned):
        assert publish.process_file(p) == 0
        assert not p.exists()


def same_reply_either_way(monkeypatch, handler, text="", args=None):
    """The reply with publishing off and on: they must be the same."""
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    off = hooked(handler, text, args).shown()
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    on = hooked(handler, text, args).shown()
    assert on == off
    return "\n".join(on)


# --------------------------------------------------------------------------- off, mock, the gate

def test_nothing_is_kept_or_started_while_publishing_is_off(portal, audits):
    portal.pages.update(the_list())
    reads = {}
    text = asyncio.run(telegram_bot.build_crosscheck_report(
        {"kind": "uid", "uid": "917"}, None, reads=reads))
    assert "RAHIM UDDIN" in text and reads == {}                   # conftest: publishing is off
    chat = hooked(telegram_bot.verified_date_command, "/verified_date 27 Sep 2026", ["27", "Sep", "2026"])
    assert "Total Students Verified:* `2`" in report_of(chat)
    assert not command_hooks.active() and command_hooks.publish({"page": []}) is None
    assert not command_hooks._tasks and not (BOT_ROOT / "data" / "cloud" / "pending").exists()


def test_mock_mode_publishes_nothing(cloud, portal, monkeypatch):
    monkeypatch.setattr(admin_client, "mock_mode", True)
    chat = hooked(telegram_bot.stats_command, "/stats", [])
    assert "Quick Stats" in report_of(chat)
    assert cloud.spawned == [] and not command_hooks.active()


# --------------------------------------------------------------------------- /verified

def test_verified_publishes_the_days_verifications_complete(cloud, portal, monkeypatch):
    portal.pages.update(the_list())
    text = same_reply_either_way(monkeypatch, telegram_bot.verified_date_command, "/verified_date 27 Sep 2026",
                                 ["27", "Sep", "2026"])
    assert "Total Students Verified:* `2`" in text
    assert shape(cloud) == [("verification", "2026-09-27", True, ["916", "917"])]
    b = batch_of(cloud, "verification")
    assert b["rows"][0]["day"] == "2026-09-27" and b["rows"][0]["data"]["verified_by"]
    process(cloud)
    assert cloud.fake.keys("verification", "2026-09-27") == ["916", "917"]
    assert next(iter(cloud.fake.runs.values()))["job"] == "command"
    # The day read again, whole: a student no longer verified that day is deleted from it.
    cloud.spawned.clear()
    listing = the_list()
    listing["students.php"] = listing["students.php"].replace("27 Sep, 17:06", "26 Sep, 17:06")
    portal.pages.update(listing)
    hooked(telegram_bot.verified_date_command, "/verified_date 27 Sep 2026", ["27", "Sep", "2026"])
    process(cloud)
    assert cloud.fake.keys("verification", "2026-09-27") == ["917"]


def test_verified_that_was_not_read_publishes_nothing(cloud, portal):
    chat = hooked(telegram_bot.verified_date_command, "/verified_date 27 Sep 2026", ["27", "Sep", "2026"])
    assert report_of(chat).startswith("❌ Couldn't read the portal")
    chat = hooked(telegram_bot.verified_date_command, "/verified_date 27 Sep 2025", ["27", "Sep", "2025"])
    assert "not available" in report_of(chat)                     # a yearless day: not even read
    chat = hooked(telegram_bot.verified_date_command, "/verified_date 31 Sep", ["31", "Sep"])
    assert "couldn't read" in report_of(chat)
    assert cloud.spawned == []


# --------------------------------------------------------------------------- /inquiries

def test_inquiries_publish_the_day_its_counts_the_totals_and_the_report(cloud, portal, monkeypatch):
    inquiry_portal(portal)
    text = same_reply_either_way(monkeypatch, telegram_bot.inquiries_today_command, "/inquiries_today", [])
    got = kinds(cloud)
    assert got == [("consultation", "2026-09-28", True), ("consultation_day", "all", False),
                   ("report", "inquiries_report", False), ("report_section", "inquiries_report|2026-09-28", True),
                   ("consultation_totals", "all", True)]
    assert len(batch_of(cloud, "consultation")["rows"]) == 5
    assert shape(cloud)[1][3] == ["2026-09-28"] and shape(cloud)[4][3] == ["all"]
    report = batch_of(cloud, "report")["rows"][0]
    assert report["key"] == "inquiries_report|2026-09-28" and report["content"] == text      # the text as sent
    assert report["data"]["facts"]["totals"] == TOTALS and report["data"]["facts"]["complete"] is True
    sections = batch_of(cloud, "report_section")["rows"]
    assert len(sections) >= 3 and sections[0]["content"].startswith("📞 *Consultancy Inquiries Report")
    assert handoffs(cloud)[0]["failed_reads"] == []
    process(cloud)
    assert len(cloud.fake.keys("consultation", "2026-09-28")) == 5
    assert cloud.fake.keys("consultation_totals") == ["all"] and cloud.fake.keys("report") == ["inquiries_report|2026-09-28"]


def test_a_capped_day_is_partial_and_totals_not_read_are_a_failed_read(cloud, portal):
    inquiry_portal(portal)
    del portal.pages[TOTALS_KEY]
    rows = [consult_row(f"S{i}", "Consulted", "22 Sep 2026", by="Sadia") for i in range(500)]
    counts = {"All": 520, "New": 0, "No Answer": 0, "Wrong Number": 0, "Consulted": 520, "File Opened": 0}
    portal.pages[day_key("2026-09-22")] = day_page("2026-09-22", *rows, counts=counts)
    chat = hooked(telegram_bot.inquiries_date_command, "/inquiries_date 22 Sep", ["22", "Sep"])
    assert "• *Inquiries Received:* `520`" in report_of(chat)
    assert kinds(cloud) == [("consultation", "2026-09-22", False), ("consultation_day", "all", False),
                            ("report", "inquiries_report", False),
                            ("report_section", "inquiries_report|2026-09-22", True)]     # no totals row
    assert handoffs(cloud)[0]["failed_reads"] == [
        "consult_requests.php?status=file_opened: consult_requests.php: the portal answered HTTP 404"]
    process(cloud)
    sync = [b for b in cloud.fake.syncs() if b["p_kind"] == "consultation"]
    assert {b["p_all_keys"] for b in sync} == {None}                              # 500 rows, no deletes
    assert sum(len(b["p_rows"]) for b in sync) == 500 and max(len(b["p_rows"]) for b in sync) <= 200
    assert next(iter(cloud.fake.runs.values()))["status"] == "partial"


def test_inquiries_that_were_not_read_publish_nothing(cloud, portal):
    chat = hooked(telegram_bot.inquiries_today_command, "/inquiries_today", [])
    assert report_of(chat).startswith("❌ Couldn't read the portal")
    hooked(telegram_bot.inquiries_date_command, "/inquiries_date 12 Oct 2026", ["12", "Oct", "2026"])
    assert cloud.spawned == []


# --------------------------------------------------------------------------- /crosscheck, /passports

def test_crosscheck_publishes_the_whole_list_its_verifications_and_the_audits(cloud, portal, audits, monkeypatch):
    portal.pages.update(the_list())
    text = same_reply_either_way(monkeypatch, telegram_bot.crosscheck_date_command, "/crosscheck_date 27 Sep 2026",
                                 ["27", "Sep", "2026"])
    assert VERDICT in text
    assert kinds(cloud) == [("student", "all", True), ("verification", None, True), ("passport_audit", "all", False)]
    assert len(batch_of(cloud, "student")["rows"]) == 10
    assert batch_of(cloud, "verification")["scope_range"] == ["2025-09-29", "2026-09-28"]
    audit = batch_of(cloud, "passport_audit")
    assert sorted(r["key"] for r in audit["rows"]) == ["916|" + SCAN.format(916), "917|" + SCAN.format(917)]
    rec = next(r for r in audit["rows"] if r["key"].startswith("917|"))
    assert rec["data"]["result"]["status"] == "MATCH" and rec["data"]["form"]["passport_no"] == "A00012345"
    assert rec["student_hng_id"] == "HNG-2026-917" and rec["student_uid"] == 917
    process(cloud)
    assert len(cloud.fake.keys("student")) == 10 and cloud.fake.keys("verification", "2026-09-27") == ["916", "917"]
    assert cloud.fake.keys("passport_audit") == ["916|" + SCAN.format(916), "917|" + SCAN.format(917)]
    # The same cross-check again: every row is already there, so nothing is sent (the hash state).
    sent = sum(len(b["p_rows"]) for b in cloud.fake.syncs())
    cloud.spawned.clear()
    hooked(telegram_bot.crosscheck_date_command, "/crosscheck_date 27 Sep 2026", ["27", "Sep", "2026"])
    process(cloud)
    assert sum(len(b["p_rows"]) for b in cloud.fake.syncs()) == sent


@pytest.mark.parametrize("outcome", ["PORTAL_UNREADABLE", "OCR_UNAVAILABLE", "raise"])
def test_an_audit_that_checked_nothing_is_not_published(cloud, portal, monkeypatch, outcome):
    portal.pages.update(the_list())

    async def audit(student_id, form_data, doc_filename=None, force_live=True):
        if outcome == "raise":
            raise RuntimeError("the OCR thread died")
        return {"student_id": student_id, "status": outcome, "is_valid": False, "fields": {},
                "discrepancies": [], "uncertain": [], "verdict": "❌ Couldn't read the portal: x"}
    monkeypatch.setattr(admin_client, "audit_student_passport", audit)
    hooked(telegram_bot.crosscheck_command, "/crosscheck 917", ["917"])
    assert kinds(cloud) == [("student", "all", True), ("verification", None, True)]


def test_the_profile_an_audit_read_is_published_and_no_other(cloud, portal, monkeypatch):
    portal.pages.update(the_list())
    monkeypatch.setattr(admin_client, "_profile_cache", {}, raising=False)
    stale = {"full_name": "OLD READ", "passport_number": "A00012345"}
    admin_client._profile_cache["916"] = stale

    async def audit(student_id, form_data, doc_filename=None, force_live=True):
        if student_id == "917":            # this audit read the profile: a new one in the client
            admin_client._profile_cache["917"] = {"full_name": "RAHIM UDDIN", "father_name": "TEST FATHER",
                                                  "passport_number": "A00012345", "id": "917"}
        return {"student_id": student_id, "status": "MATCH", "is_valid": True, "fields": {},
                "discrepancies": [], "uncertain": [], "verdict": VERDICT}
    monkeypatch.setattr(admin_client, "audit_student_passport", audit)
    hooked(telegram_bot.crosscheck_date_command, "/crosscheck_date 27 Sep 2026", ["27", "Sep", "2026"])
    got = [(k, s, c, keys) for k, s, c, keys in shape(cloud) if k == "student_profile"]
    assert got == [("student_profile", "917", True, ["917"])]              # 916's is an older read
    rec = batch_of(cloud, "student_profile")["rows"][0]
    assert rec["data"]["father_name"] == "TEST FATHER" and rec["passport_no"] == "A00012345"
    # A profile of the legacy full-page read (it keeps _csrf) is never published.
    cloud.spawned.clear()

    async def legacy(student_id, form_data, doc_filename=None, force_live=True):
        admin_client._profile_cache[student_id] = {"_csrf": "x", "full_name": "RAHIM UDDIN"}
        return {"student_id": student_id, "status": "MATCH", "is_valid": True, "fields": {},
                "discrepancies": [], "uncertain": [], "verdict": VERDICT}
    monkeypatch.setattr(admin_client, "audit_student_passport", legacy)
    hooked(telegram_bot.crosscheck_command, "/crosscheck 917", ["917"])
    assert "student_profile" not in [k for k, _, _ in kinds(cloud)]


def test_a_list_whose_stamps_cannot_be_read_has_partial_verifications(cloud, portal, audits):
    portal.pages["students.php"] = page(verified(917, 1, "TEST STUDENT ONE", "sometime"),
                                        verified(918, 2, "TEST STUDENT TWO", "27 Sep, 10:00", applied="20 Sep 2026"))
    hooked(telegram_bot.crosscheck_command, "/crosscheck 918", ["918"])
    assert kinds(cloud) == [("student", "all", True), ("verification", None, False), ("passport_audit", "all", False)]
    assert "scope_range" not in batch_of(cloud, "verification")
    assert handoffs(cloud)[0]["failed_reads"] == [command_hooks.STAMP_PROBLEM]
    process(cloud)
    assert [b["p_all_keys"] for b in cloud.fake.syncs() if b["p_kind"] == "verification"] == [None]


def test_a_list_that_cannot_be_read_whole_publishes_nothing(cloud, portal, audits):
    listing = the_list()
    del listing["students.php?pg=2"]                   # page 2 answers 404: a PortalUnavailable
    portal.pages.update(listing)
    chat = hooked(telegram_bot.crosscheck_date_command, "/crosscheck_date 27 Sep 2026", ["27", "Sep", "2026"])
    assert "Couldn't read the portal" in report_of(chat) and audits == []
    assert cloud.spawned == []


def test_a_stamp_guard_that_fails_still_publishes_the_list_it_read(cloud, portal, audits):
    portal.pages["students.php"] = page(row(1, 1, "TEST A"), row(2, 2, "TEST B"))      # no stamp on any row
    chat = hooked(telegram_bot.crosscheck_date_command, "/crosscheck_date 27 Sep 2026", ["27", "Sep", "2026"])
    assert "Couldn't read the portal" in report_of(chat)
    assert kinds(cloud) == [("student", "all", True)]             # no verification: none to send, none deleted
    assert handoffs(cloud)[0]["failed_reads"] == [command_hooks.STAMP_PROBLEM]


def test_passports_publish_the_list_and_todays_audits(cloud, portal, audits, monkeypatch):
    listing = the_list()
    listing["students.php"] = page(verified(918, 1, "TODAY STUDENT", "28 Sep, 09:00", applied="28 Sep 2026"),
                                   row(919, 2, "OTHER STUDENT"), pg=1, pages=2, total=6)
    portal.pages.update(listing)
    text = same_reply_either_way(monkeypatch, telegram_bot.passports_command, "/passports", [])
    assert "Payment-verified today (28 September 2026):* `1`" in text
    assert kinds(cloud) == [("student", "all", True), ("verification", None, True), ("passport_audit", "all", False)]
    assert shape(cloud)[2][3] == ["918|" + SCAN.format(918)]


# --------------------------------------------------------------------------- /students, /stats, /admitted

def test_students_publish_page_one_as_a_partial_list(cloud, portal):
    admitted_portal(portal)
    hooked(telegram_bot.students_command, "/students", [])
    assert shape(cloud) == [("student", "all", False, ["10", "11"])]
    process(cloud)
    assert [b["p_all_keys"] for b in cloud.fake.syncs()] == [None]
    cloud.spawned.clear()
    portal.pages["students.php"] = page()                           # the portal's own empty list
    hooked(telegram_bot.students_command, "/students", [])
    assert cloud.spawned == []                                     # nothing to send, nothing deleted


def test_stats_publishes_the_tiles_as_partial_facts_the_same_records_as_the_dashboard(cloud, portal, monkeypatch):
    portal.pages["index.php"] = dashboard_page()
    same_reply_either_way(monkeypatch, telegram_bot.stats_command, "/stats", [])
    (kind, scope, complete, keys), = shape(cloud)
    assert (kind, scope, complete, len(keys)) == ("dashboard_fact", "all", False, 11)
    tile = next(r for r in batch_of(cloud, "dashboard_fact")["rows"] if r["key"] == "Direct / legacy pipeline|Total students")
    cloud.spawned.clear()
    ask_bot("how many students are on the portal")                  # the whole page: tiles and cards
    (kind, scope, complete, keys), = shape(cloud)
    assert (kind, complete, len(keys)) == ("dashboard_fact", True, DASHBOARD_FACTS)
    same = next(r for r in batch_of(cloud, "dashboard_fact")["rows"] if r["key"] == tile["key"])
    assert same["content_hash"] == tile["content_hash"]            # one tile, one record, whoever read it


def test_a_dashboard_that_cannot_be_read_publishes_nothing(cloud, portal):
    chat = hooked(telegram_bot.stats_command, "/stats", [])
    assert "not available" in report_of(chat)
    ask_bot("how many students are on the portal")
    assert cloud.spawned == []


def test_admitted_publishes_the_whole_list_and_the_tiles(cloud, portal, monkeypatch):
    admitted_portal(portal)
    text = same_reply_either_way(monkeypatch, telegram_bot.admitted_command, "/admitted", [])
    assert "RAHMAN KIM ADMITTED" in text
    # No row of this list has a "Payment verified by" line: its stamps cannot be told apart from a
    # changed layout, so no verification is published and the read says why.
    assert shape(cloud) == [("student", "all", True, ["10", "11", "12", "13"]),
                            ("dashboard_fact", "all", False,
                             ["Direct / legacy pipeline|Admitted", "Direct / legacy pipeline|Total students"])]
    assert handoffs(cloud)[0]["failed_reads"] == [command_hooks.STAMP_PROBLEM]
    process(cloud)
    assert cloud.fake.keys("student") == ["10", "11", "12", "13"]


# --------------------------------------------------------------------------- /calendar

def test_calendar_questions_publish_the_items_never_complete(cloud, portal, monkeypatch):
    portal.pages["calendar.php"] = calendar_html()
    same_reply_either_way(monkeypatch, telegram_bot.calendar_command, "/calendar next week", ["next", "week"])
    (kind, scope, complete, keys), = shape(cloud)
    assert (kind, scope, complete) == ("calendar_item", "all", False) and keys == ["1", "2", "3", "4", "5", "6", "7", "8"]
    process(cloud)
    assert [b["p_all_keys"] for b in cloud.fake.syncs()] == [None]
    cloud.spawned.clear()
    portal.pages["calendar.php"] = "<html>changed</html>"               # layout not recognised
    chat = hooked(telegram_bot.calendar_command, "/calendar next week", ["next", "week"])
    assert "Couldn't read the portal" in report_of(chat) and cloud.spawned == []


def test_the_bare_calendar_view_publishes_nothing(cloud, portal):
    """/calendar alone reads calendar.php through the legacy get_calendar_events, whose items are
    not ask.calendar_items' merged ones (no event list): the hourly job publishes the calendar."""
    portal.pages["calendar.php"] = calendar_html()
    chat = hooked(telegram_bot.calendar_command, "/calendar", [])
    assert "Reminders for today" in report_of(chat) and cloud.spawned == []


# --------------------------------------------------------------------------- free-text answers

@pytest.fixture
def live_pages(portal):
    portal.pages.update({
        "index.php": dashboard_page(),
        "window_applications.php?status=under_review": window_page("Under Review", "Submitted"),
        "students.php": page(row(10, 1, "KIM SEOYEON", intake="MARCH 2027", applied="28 Sep 2026"),
                             verified(11, 2, "KARIM MIA", "27 Sep, 10:00", applied="27 Sep 2026"),
                             pg=1, pages=2, total=4),
        "students.php?pg=2": page(row(12, 3, "ALAM EAP", intake="DECEMBER 2026", applied="21 Sep 2026"),
                                  row(13, 4, "RAHMAN OLD", intake="MARCH 2027", applied="20 Sep 2026"),
                                  pg=2, pages=2, total=4),
        **pending_pages(),
    })
    return portal


@pytest.mark.parametrize("said, expected", [
    ("show pending payments", [("pending_payment", "all", True, ["501", "577", "579"])]),
    ("how many students in March 2027 intake", [("student", "all", True, ["10", "11", "12", "13"]),
                                                ("verification", None, True, ["11"])]),
    ("how many students registered yesterday", [("student", "all", True, ["10", "11", "12", "13"]),
                                                ("verification", None, True, ["11"])]),
])
def test_free_text_answers_publish_what_they_read(cloud, live_pages, monkeypatch, said, expected):
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    off = ask_bot(said).shown()
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    assert ask_bot(said).shown() == off
    assert shape(cloud) == expected
    process(cloud)
    kind, scope = expected[0][0], expected[0][1]
    assert cloud.fake.keys(kind, scope) == expected[0][3]


@pytest.mark.parametrize("said", ["documents waiting for verification", "applications under review",
                                  "any urgent alerts", "what is the office phone policy"])
def test_free_text_dashboard_answers_publish_the_whole_dashboard(cloud, live_pages, monkeypatch, said):
    async def no_pick(query, lines):
        return []
    monkeypatch.setattr(ollama_client, "answer_agent_query", no_pick)
    ask_bot(said)
    (kind, scope, complete, keys), = shape(cloud)
    assert (kind, scope, complete, len(keys)) == ("dashboard_fact", "all", True, DASHBOARD_FACTS)


def test_alerts_publish_the_dashboard(cloud, live_pages):
    chat = hooked(telegram_bot.alerts_command, "/alerts", [])
    assert "Needs attention" in report_of(chat)
    assert kinds(cloud) == [("dashboard_fact", "all", True)]


def test_a_dashboard_without_every_card_is_partial(cloud, portal):
    html = dashboard_page()
    portal.pages["index.php"] = html[:html.index('<section class="card"><div class="card-head"><h2 class="card-title">'
                                                 '<i></i> Top universities')]
    ask_bot("how many students are on the portal")
    assert kinds(cloud) == [("dashboard_fact", "all", False)]      # a missing card cannot be told from none


def test_pending_payments_that_cannot_be_read_whole_publish_nothing(cloud, portal):
    first = pending_pages()["students.php?status=pending"]
    portal.pages["students.php?status=pending"] = first               # page 2 answers 404
    chat = ask_bot("show pending payments")
    assert "Couldn't read the portal" in report_of(chat)
    assert cloud.spawned == []


# --------------------------------------------------------------------------- the reply never depends on it

def test_the_reply_never_waits_for_the_handoff(cloud, portal, monkeypatch):
    portal.pages.update(the_list())
    gate, entered = threading.Event(), threading.Event()
    real = handoff.submit

    def slow(job, batches, failed_reads=()):
        entered.set()
        gate.wait(30)
        return real(job, batches, failed_reads)
    monkeypatch.setattr(handoff, "submit", slow)
    update, context, chat = fake_update("/verified_date 27 Sep 2026", ["27", "Sep", "2026"])

    async def go():
        started = time.monotonic()
        await telegram_bot.verified_date_command(update, context)
        assert time.monotonic() - started < 10
        assert "Total Students Verified:* `2`" in report_of(chat)    # the reply went out, whole
        assert await asyncio.to_thread(entered.wait, 10)             # the handoff runs meanwhile...
        assert cloud.spawned == [] and not gate.is_set()             # ...and the handler did not wait for it
        gate.set()
        await command_hooks.drain(timeout=30)
    asyncio.run(go())
    assert len(cloud.spawned) == 1


@pytest.mark.parametrize("failure, reason", [
    (lambda req: httpx.Response(500, json={"code": "XX000", "message": "row 917: TEST"}), "HTTP 500 XX000 (Supabase server error)"),
    (lambda req: httpx.ReadTimeout("timed out", request=req), "Supabase did not answer in time (ReadTimeout)"),
    (lambda req: httpx.Response(401, json={"code": "42501"}), "HTTP 401 42501 (the key was refused)"),
])
def test_a_supabase_failure_changes_nothing_the_bot_sends(cloud, portal, monkeypatch, caplog, failure, reason):
    portal.pages.update(the_list())
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    off = hooked(telegram_bot.verified_date_command, "/verified_date 27 Sep 2026", ["27", "Sep", "2026"]).shown()
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    cloud.fake.fail = failure
    caplog.set_level(logging.INFO)
    chat = hooked(telegram_bot.verified_date_command, "/verified_date 27 Sep 2026", ["27", "Sep", "2026"])
    process(cloud)                                               # the publisher meets the failure later
    assert chat.shown() == off
    assert [r.getMessage() for r in cloud_warnings(caplog)] == [f"Supabase publish failed (hg_runs): {reason}"]
    assert "RAHIM" not in caplog.text and "NUSRAT" not in caplog.text and state() is None


def test_a_build_that_fails_is_one_line_and_the_reply_stands(cloud, portal, monkeypatch, caplog):
    portal.pages.update(the_list())
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    off = hooked(telegram_bot.verified_date_command, "/verified_date 27 Sep 2026", ["27", "Sep", "2026"]).shown()
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)

    def broken(v, day, read_at=None):
        raise ValueError(f"cannot build {v.get('name')}")
    monkeypatch.setattr(records, "verification", broken)
    chat = hooked(telegram_bot.verified_date_command, "/verified_date 27 Sep 2026", ["27", "Sep", "2026"])
    assert chat.shown() == off and cloud.spawned == []
    assert [r.getMessage() for r in cloud_warnings(caplog)] == \
        ["Supabase publish failed (command): the records could not be built (ValueError)"]
    assert "RAHIM" not in caplog.text


def test_a_handoff_outside_an_event_loop_runs_in_a_thread_of_its_own(cloud, monkeypatch):
    monkeypatch.setattr(admin_client, "mock_mode", False)
    reads = {}
    command_hooks.seen(reads, page=[{"uid": "500", "student_name": "TEST A", "details": {}}])
    assert command_hooks.publish(reads) is None                   # no loop: a thread, not a task
    deadline = time.monotonic() + 10
    while not cloud.spawned and time.monotonic() < deadline:
        time.sleep(0.05)
    assert shape(cloud) == [("student", "all", False, ["500"])]
