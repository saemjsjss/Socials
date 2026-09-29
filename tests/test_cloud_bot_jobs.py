"""The Supabase copy of the bot's own scheduled jobs (src/cloud/bot_jobs.py, src/cloud/full_picture.py).

What is pinned here:
  the passport watcher  after it saved its memory it hands over the whole list it read (student,
                        complete), this run's audits (passport_audit, complete with every scan the
                        list shows as the key list) and its memory (passport_alert, complete); a list
                        it could not read whole hands over nothing
  the 18:05 brief       after it was sent it hands over the brief as sent (report, report_section,
                        brief_fact) and its portal reads (consultation, consultation_day,
                        verification, consultation_totals, dashboard_fact), each only when that read
                        succeeded and complete only when that read was whole; pending payments,
                        window applications and calendar items are figures in the report's data
  both                  Supabase down, a slow handoff or a bug in the records never changes what the
                        job sends or remembers, and costs one log line; the records are built off
                        the event loop; nothing happens while publishing is off or in mock mode
  the full picture      the hourly job: every page of spec step 4, GET only, with the right kind,
                        scope and complete flag; a partial read deletes nothing; once the portal does
                        not answer the other pages are not tried; nothing is read while publishing
                        is off, in mock mode, in a quiet window or while another publisher runs; its
                        scheduler job runs hourly, one at a time, off the sync's and watcher's beat

Nothing reaches the network, Supabase, Telegram or the portal: the portal is the foundation's and the
brief's fakes, Supabase is test_cloud's FakeSupabase (the `cloud` fixture starts no process).
"""
import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_foundation import TODAY, page, portal, row, verified  # noqa: E402,F401  (portal is a fixture)
from test_jobs import Bot, bad, scan_row, watcher  # noqa: E402,F401  (watcher is a fixture)
from test_brief import FakeBot, consult_day_key, full_portal, write_store  # noqa: E402
from test_brief import portal as brief_portal  # noqa: E402,F401  (the brief's portal fixture, by another name)
from test_cloud import cloud, cloud_warnings  # noqa: E402,F401  (cloud is a fixture: FakeSupabase)
from test_consultations import _row as consult_row  # noqa: E402
from test_inquiries import TOTALS_KEY, day_key, day_page, totals_page  # noqa: E402

from src.bot import brief, scheduler  # noqa: E402
from src.cloud import backfill, bot_jobs, full_picture, handoff, publish, records  # noqa: E402
from src.config import settings  # noqa: E402
from src.scraper.client import admin_client  # noqa: E402

DHAKA = ZoneInfo("Asia/Dhaka")


def handed(cloud, job):
    """The one handoff file the job wrote (the fixture's launcher starts nothing) -> (path, its JSON)."""
    assert len(cloud.spawned) == 1, cloud.spawned
    path = cloud.spawned[0]
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["job"] == job and doc["version"] == 1
    return path, doc


def shape(doc):
    return [(b["kind"], b["scope"], b["complete"]) for b in doc["batches"]]


def kind(doc, name):
    found = [b for b in doc["batches"] if b["kind"] == name]
    assert len(found) == 1, name
    return found[0]


def slow_submit(monkeypatch, seconds=1.5):
    real = handoff.submit

    def slow(job, batches, failed_reads=()):
        time.sleep(seconds)
        return real(job, batches, failed_reads)
    monkeypatch.setattr(handoff, "submit", slow)


async def timed(coro):
    started = time.perf_counter()
    await coro
    return time.perf_counter() - started


# --------------------------------------------------------------------------- the passport watcher

def two_scans_page():
    """Two students; the second also still lists an older passport upload."""
    older = '<a href="view_doc.php?f=passport_502_1690000000.jpg">Old passport</a><a href="student_edit.php'
    return page(scan_row(501, 1, "TEST KARIM"),
                scan_row(502, 2, "TEST NADIA").replace('<a href="student_edit.php', older, 1))


def run_watcher(bot):
    asyncio.run(scheduler.check_new_passport_uploads(SimpleNamespace(bot=bot)))
    return json.loads(Path(scheduler.ALERTED_CACHE_FILE).read_text(encoding="utf-8"))["scans"]


def test_the_watcher_hands_over_its_list_its_audits_and_its_memory(cloud, watcher):
    watcher.portal.pages["students.php"] = two_scans_page()
    watcher.results["502"] = bad(502, "DOB mismatch for 502")
    bot = Bot()
    memory = run_watcher(bot)
    assert len(bot.sent) == 1 and "`ID 502`" in bot.sent[0]["text"]          # the watcher's own work, as ever

    path, doc = handed(cloud, "passport_watcher")
    assert shape(doc) == [("student", "all", True), ("passport_audit", "all", True), ("passport_alert", "all", True)]
    assert doc["failed_reads"] == []
    students, audits, alerts = (kind(doc, k) for k in ("student", "passport_audit", "passport_alert"))
    assert [r["key"] for r in students["rows"]] == ["501", "502"]
    assert sorted(r["key"] for r in audits["rows"]) == ["501|passport_501_1790000000.jpg",
                                                        "502|passport_502_1790000000.jpg"]
    # Every scan the complete list shows is kept, the older upload still listed included.
    assert audits["all_keys"] == ["501|passport_501_1790000000.jpg", "502|passport_502_1690000000.jpg",
                                  "502|passport_502_1790000000.jpg"]
    audit = next(r for r in audits["rows"] if r["key"].startswith("502|"))
    assert audit["data"]["result"]["discrepancies"] == ["DOB mismatch for 502"]
    assert audit["data"]["form"]["passport_no"] == "A00000502" and audit["student_hng_id"] == "HNG-2026-502"
    assert sorted(r["key"] for r in alerts["rows"]) == sorted(memory)

    assert publish.process_file(path) == 0 and not path.exists()
    assert cloud.fake.keys("student") == ["501", "502"]
    assert cloud.fake.keys("passport_audit") == ["501|passport_501_1790000000.jpg", "502|passport_502_1790000000.jpg"]
    assert cloud.fake.keys("passport_alert") == sorted(memory)
    alert = cloud.fake.records[("passport_alert", "502|passport_502_1790000000.jpg")]
    assert alert["data"]["sent"] is True and alert["data"]["alert"].startswith("• *Student:* *TEST NADIA*")
    run = next(iter(cloud.fake.runs.values()))
    assert run["job"] == "passport_watcher" and run["status"] == "ok"

    # The next run finds nothing new: its handoff holds the list and the memory, and nothing is sent.
    cloud.spawned.clear()
    calls = len(cloud.fake.syncs())
    run_watcher(Bot())
    path, doc = handed(cloud, "passport_watcher")
    assert [len(b["rows"]) for b in doc["batches"]] == [2, 0, 2]
    publish.process_file(path)
    assert len(cloud.fake.syncs()) == calls


def test_a_replaced_scan_loses_its_audit_and_its_alert(cloud, watcher):
    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "TEST KARIM"), scan_row(502, 2, "TEST NADIA"))
    watcher.results["502"] = bad(502)
    run_watcher(Bot())
    publish.process_file(cloud.spawned.pop())
    assert "502|passport_502_1790000000.jpg" in cloud.fake.keys("passport_alert")

    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "TEST KARIM"),
                                                scan_row(502, 2, "TEST NADIA", upload=1790009999, ext="pdf"))
    watcher.results.pop("502")
    run_watcher(Bot())
    publish.process_file(cloud.spawned.pop())
    assert cloud.fake.keys("passport_audit") == ["501|passport_501_1790000000.jpg", "502|passport_502_1790009999.pdf"]
    assert cloud.fake.keys("passport_alert") == ["501|passport_501_1790000000.jpg", "502|passport_502_1790009999.pdf"]
    assert ("delete", "passport_audit", "502|passport_502_1790000000.jpg") in cloud.fake.changes


@pytest.mark.parametrize("pages", [
    {"students.php": page(*[scan_row(500 + i, i + 1, f"S{i}") for i in range(50)])},             # no pager
    {"students.php": page(scan_row(501, 1, "TEST KARIM"), pg=1, pages=2, total=51)},              # page 2: 404
])
def test_a_watcher_that_cannot_read_the_whole_list_hands_over_nothing(cloud, watcher, pages):
    watcher.portal.pages.update(pages)
    asyncio.run(scheduler.check_new_passport_uploads(SimpleNamespace(bot=Bot())))
    assert watcher.audits == [] and cloud.spawned == [] and cloud.fake.calls == []


def test_scans_that_could_not_be_checked_are_a_failed_read_never_an_audit(cloud, watcher):
    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "TEST KARIM"), scan_row(502, 2, "TEST NADIA"))
    watcher.results["502"] = {"status": "PORTAL_UNREADABLE", "is_valid": False, "discrepancies": [],
                              "verdict": "the passport scan could not be downloaded: timed out"}
    run_watcher(Bot())
    _, doc = handed(cloud, "passport_watcher")
    assert [r["key"] for r in kind(doc, "passport_audit")["rows"]] == ["501|passport_501_1790000000.jpg"]
    assert doc["failed_reads"] == ["student_edit.php / view_doc.php: 1 passport scan(s) could not be checked "
                                   "(tried again next run)"]


def _without_times(memory):
    return {k: {f: v for f, v in e.items() if f not in ("checked", "sent_at")} for k, e in memory.items()}


@pytest.mark.parametrize("trouble", ["supabase down", "slow handoff", "records bug"])
def test_the_watcher_sends_and_remembers_the_same_whatever_supabase_does(cloud, watcher, monkeypatch, caplog,
                                                                          trouble):
    watcher.portal.pages["students.php"] = two_scans_page()
    watcher.results["502"] = bad(502, "Passport No mismatch")
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)          # the reference: no Supabase at all
    reference = Bot()
    expected = run_watcher(reference)
    assert cloud.spawned == []
    Path(scheduler.ALERTED_CACHE_FILE).unlink()
    watcher.audits.clear()

    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    if trouble == "supabase down":
        cloud.fake.fail = lambda req: httpx.Response(503)
    elif trouble == "slow handoff":
        monkeypatch.setattr(bot_jobs, "HANDOFF_WAIT", 0.3)
        slow_submit(monkeypatch)
    else:
        def broken(*args, **kwargs):
            raise RuntimeError("a bug")
        monkeypatch.setattr(records, "students", broken)
    caplog.set_level(logging.INFO)
    bot = Bot()
    seconds = asyncio.run(timed(scheduler.check_new_passport_uploads(SimpleNamespace(bot=bot))))
    for path in list(cloud.spawned):
        publish.process_file(path)
    memory = json.loads(Path(scheduler.ALERTED_CACHE_FILE).read_text(encoding="utf-8"))["scans"]

    assert [m["text"] for m in bot.sent] == [m["text"] for m in reference.sent]
    assert _without_times(memory) == _without_times(expected)
    assert "Passport audit check: 2 scans on the portal, 2 audited" in caplog.text
    assert "Error in check_new_passport_uploads" not in caplog.text
    lines = [r.getMessage() for r in cloud_warnings(caplog)]
    assert lines == [{"supabase down": "Supabase publish failed (hg_runs): HTTP 503 (Supabase server error)",
                      "slow handoff": "Supabase publish failed (passport_watcher): the handoff took over 0.3 s "
                                      "(the job itself was done)",
                      "records bug": "Supabase publish failed (passport_watcher): its records could not be "
                                     "built (RuntimeError)"}[trouble]]
    if trouble == "slow handoff":
        assert seconds < 1.2                                     # the job did not wait for it
        assert cloud.fake.keys("student") == ["501", "502"]      # the handoff still went, late
    else:
        assert publish.STATE_PATH.exists() is False              # nothing was accepted: nothing advanced


def test_the_watcher_builds_its_records_off_the_event_loop(cloud, watcher, monkeypatch):
    on_main = []
    real = bot_jobs.watcher_batches

    def spy(*args):
        on_main.append(threading.current_thread() is threading.main_thread())
        return real(*args)
    monkeypatch.setattr(bot_jobs, "watcher_batches", spy)
    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "TEST KARIM"))
    run_watcher(Bot())
    assert on_main == [False] and len(cloud.spawned) == 1


# --------------------------------------------------------------------------- the 18:05 brief

def send_brief(bot):
    asyncio.run(scheduler.send_daily_briefing(SimpleNamespace(bot=bot)))


def test_the_brief_hands_over_itself_and_what_it_read(cloud, brief_portal):
    brief_portal.pages.update(full_portal())
    write_store(brief_portal.store)
    bot = FakeBot()
    send_brief(bot)
    assert len(bot.messages) == 1

    path, doc = handed(cloud, "daily_brief")
    assert shape(doc) == [("report", "brief", False), ("report_section", "brief|2026-09-28", True),
                          ("brief_fact", "2026-09-28", True), ("consultation", "2026-09-28", True),
                          ("consultation_day", "all", False), ("verification", "2026-09-28", True),
                          ("consultation_totals", "all", True), ("dashboard_fact", "all", False)]
    assert doc["failed_reads"] == []
    (report,) = kind(doc, "report")["rows"]
    assert report["key"] == "brief|2026-09-28" and report["content"] == bot.messages[0]["text"]
    assert report["read_at"] == "2026-09-28T18:05:00+06:00" and report["day"] == "2026-09-28"
    figures = report["data"]["facts"]
    facts = [r["data"]["fact"] for r in kind(doc, "brief_fact")["rows"]]
    assert figures["lines"] == facts and facts[0] == "Consultation requests received today: 7"
    assert figures["pending_payments"] == {"count": 2, "listed": 2, "badge": 2}
    assert figures["window_apps_under_review"] == 1
    assert [r["title"] for r in figures["calendar_today"]] == ["Alpha University DHL",
                                                               "Gamma University - Application open",
                                                               "SEJONG *UNIVERSITY*"]
    assert figures["document_check"]["students"] == 4 and figures["document_check"]["verdicts"]["FAIL"] == 2
    sections = kind(doc, "report_section")["rows"]
    assert [s["data"]["heading"] for s in sections][1:6] == [
        "*1) CONSULTATIONS TODAY*", "*2) PAYMENT-VERIFIED STUDENTS TODAY*", "*3) PORTAL FIGURES (live now)*",
        "*4) TODAY'S CALENDAR REMINDERS*", "*5) DOCUMENT CHECK (from the last automated check, not live)*"]
    assert len(kind(doc, "consultation")["rows"]) == 7
    assert kind(doc, "consultation_day")["rows"][0]["data"]["counts"]["All"] == 7
    assert [r["key"] for r in kind(doc, "verification")["rows"]] == ["501", "350"]
    tiles = kind(doc, "dashboard_fact")["rows"]
    assert "Direct / legacy pipeline|Total students" in {r["key"] for r in tiles} and len(tiles) == 11
    assert not {b["kind"] for b in doc["batches"]} & {"pending_payment", "window_application", "calendar_item"}

    assert publish.process_file(path) == 0
    assert cloud.fake.keys("report") == ["brief|2026-09-28"] and len(cloud.fake.keys("brief_fact")) == len(facts)
    assert cloud.fake.keys("verification", "2026-09-28") == ["350", "501"]
    assert cloud.fake.keys("consultation_totals") == ["all"]
    run = next(iter(cloud.fake.runs.values()))
    assert run["job"] == "daily_brief" and run["status"] == "ok"


def test_a_dashboard_tile_is_the_same_record_whichever_job_read_it():
    """The brief reads the tiles (get_dashboard), the full picture the tiles and cards
    (ask.dashboard_facts): a tile must hash the same both ways, or each would overwrite the other."""
    from test_brief import INDEX
    from src.bot.ask import dashboard_facts
    from src.scraper.parsers import parse_hangeul_live_dashboard
    reads = {"day": date(2026, 9, 28), "today": date(2026, 9, 28), "dashboard": parse_hangeul_live_dashboard(INDEX)}
    from_brief = kind({"batches": bot_jobs.brief_reads(reads, "2026-09-28T18:05:00+06:00")}, "dashboard_fact")["rows"]
    from_page = records.dashboard_facts(dashboard_facts(INDEX))
    assert [(r["key"], r["content_hash"]) for r in from_brief] == [(r["key"], r["content_hash"]) for r in from_page]


def test_a_brief_read_that_failed_publishes_nothing_of_it_and_is_named(cloud, brief_portal):
    pages = full_portal()
    del pages[consult_day_key("28 Sep 2026")]                      # 404
    del pages["students.php?pg=2"]                                 # the list cannot be read whole
    pages["index.php"] = "<html>no tiles here</html>"
    brief_portal.pages.update(pages)
    send_brief(FakeBot())
    path, doc = handed(cloud, "daily_brief")
    assert shape(doc) == [("report", "brief", False), ("report_section", "brief|2026-09-28", True),
                          ("brief_fact", "2026-09-28", True), ("consultation_totals", "all", True)]
    assert doc["failed_reads"] == [
        "consult_requests.php?status=all (the day): consult_requests.php: the portal answered HTTP 404",
        "students.php: students.php: the portal answered HTTP 404"]
    publish.process_file(path)
    assert next(iter(cloud.fake.runs.values()))["status"] == "partial"
    assert cloud.fake.keys("consultation") == [] and cloud.fake.keys("verification") == []


def test_a_brief_the_portal_did_not_answer_for_is_the_brief_alone(cloud, brief_portal, monkeypatch):
    def down(request):
        raise httpx.ReadTimeout("", request=request)
    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(down)))
    send_brief(FakeBot())
    _, doc = handed(cloud, "daily_brief")
    assert [b["kind"] for b in doc["batches"]] == ["report", "report_section", "brief_fact"]
    assert doc["failed_reads"][0] == "consult_requests.php?status=all (the day): the portal did not answer"
    assert len(doc["failed_reads"]) == 7
    assert all(f.endswith("not read: the portal did not answer") for f in doc["failed_reads"][1:])


def test_a_capped_day_and_a_tile_read_are_never_complete():
    rows = [{"name": f"TEST LEAD {i}", "contact": f"0170000{i:04d}", "received": "26 Sep 2026 10:15",
             "received_date": "26 Sep 2026", "status": "New"} for i in range(500)]
    reads = {"day": date(2026, 9, 26), "today": date(2026, 9, 28), "at": datetime(2026, 9, 28, 18, 5, tzinfo=DHAKA),
             "consultations": {"day": date(2026, 9, 26), "counts": {"All": 600, "New": 600}, "rows": rows,
                               "complete": False},
             "verified": None, "consultation totals": None, "pending payments": None, "window applications": None,
             "dashboard": {"error": "index.php: the portal answered HTTP 500"}, "calendar": None, "is_today": False,
             "why": {}, "errors": {"verified students": KeyError("TEST STUDENT NAME")}}
    batches, failed = bot_jobs.brief_batches(brief.Brief("*brief*\n\n*1) X*\n• 1", ["A fact: 1"], reads))
    assert [(b["kind"], b["scope"], b["complete"]) for b in batches[3:]] == [
        ("consultation", "2026-09-26", False), ("consultation_day", "all", False)]
    assert len(batches[3]["rows"]) == 500
    assert failed == ["students.php: not read (KeyError)",                     # never the error's words
                      "students.php?status=pending: the pending count could not be read",
                      "window_applications.php?status=under_review: no table with a Status column (layout not recognised)",
                      "index.php: index.php: the portal answered HTTP 500"]
    assert "TEST STUDENT NAME" not in json.dumps(failed)


def test_a_brief_built_by_hand_is_published_as_itself():
    """A Brief without reads (Jennie's tests build them by hand): the brief, its sections and facts."""
    batches, failed = bot_jobs.brief_batches(brief.Brief("📋 *HANGEUL DAILY BRIEF*\n\n*1) CONSULTATIONS TODAY*\n"
                                                         "• Received: 5", ["Consultation requests received today: 5"]))
    assert [b["kind"] for b in batches] == ["report", "report_section", "brief_fact"] and failed == []
    assert batches[0]["rows"][0]["data"]["facts"] == {"lines": ["Consultation requests received today: 5"]}


def test_a_day_the_stamps_cannot_tell_apart_publishes_no_verification():
    reads = {"day": date(2025, 9, 28), "today": date(2026, 9, 28), "verified": [{"uid": "501", "name": "TEST A"}]}
    assert bot_jobs.brief_reads(reads, None) == []


@pytest.mark.parametrize("trouble", ["supabase down", "slow handoff"])
def test_the_brief_is_the_same_and_on_time_whatever_supabase_does(cloud, brief_portal, monkeypatch, caplog, trouble):
    brief_portal.pages.update(full_portal())
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    reference = FakeBot()
    send_brief(reference)
    assert cloud.spawned == []

    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    if trouble == "supabase down":
        cloud.fake.fail = lambda req: httpx.ReadTimeout("timed out", request=req)
    else:
        monkeypatch.setattr(bot_jobs, "HANDOFF_WAIT", 0.3)
        slow_submit(monkeypatch)
    bot = FakeBot()
    seconds = asyncio.run(timed(scheduler.send_daily_briefing(SimpleNamespace(bot=bot))))
    for path in list(cloud.spawned):
        publish.process_file(path)
    assert bot.messages == reference.messages
    lines = [r.getMessage() for r in cloud_warnings(caplog)]
    assert lines == [{"supabase down": "Supabase publish failed (hg_runs): Supabase did not answer in time (ReadTimeout)",
                      "slow handoff": "Supabase publish failed (daily_brief): the handoff took over 0.3 s "
                                      "(the job itself was done)"}[trouble]]
    if trouble == "slow handoff":
        assert seconds < 1.2


def test_a_brief_that_was_not_sent_or_is_demo_data_is_not_published(cloud, brief_portal, monkeypatch):
    brief_portal.pages.update(full_portal())

    class Refusing(FakeBot):
        async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
            raise RuntimeError("Telegram is down")
    send_brief(Refusing())
    assert cloud.spawned == []

    async def composed(day=None, with_summary=True):
        return brief.Brief("📋 *HANGEUL DAILY BRIEF*\n\n*1) X*\n• 1", ["A fact: 1"])
    monkeypatch.setattr(scheduler, "compose_brief", composed)
    monkeypatch.setattr(admin_client, "mock_mode", True)
    bot = FakeBot()
    send_brief(bot)
    assert len(bot.messages) == 1 and cloud.spawned == []


def test_nothing_is_built_while_publishing_is_off():
    built = []
    assert asyncio.run(bot_jobs.hand_over("daily_brief", lambda: built.append(1) or ([], []))) is None
    assert built == []


# --------------------------------------------------------------------------- the hourly full picture

def full_picture_pages():
    from test_freetext import calendar_html, dashboard_page, pending_pages, window_page
    return {
        "students.php": page(verified(425, 1, "TEST STUDENT ONE", "27 Sep, 17:19", applied="12 Sep 2026"),
                             row(426, 2, "TEST STUDENT TWO"), pg=1, pages=2, total=3),
        "students.php?pg=2": page(row(427, 3, "TEST STUDENT THREE"), pg=2, pages=2, total=3),
        **pending_pages(),
        day_key("2026-09-27"): day_page("2026-09-27"),
        day_key("2026-09-28"): day_page("2026-09-28", consult_row("TEST LEAD A", "New", "28 Sep 2026")),
        TOTALS_KEY: totals_page(),
        "window_applications.php?status=under_review": window_page("Under Review", "submitted"),
        "index.php": dashboard_page(),
        "calendar.php": calendar_html(),
    }


FULL_SHAPE = [("student", "all", True), ("verification", None, True), ("pending_payment", "all", True),
              ("consultation", "2026-09-27", True), ("consultation", "2026-09-28", True),
              ("consultation_day", "all", False), ("consultation_totals", "all", True),
              ("window_application", "all", True), ("dashboard_fact", "all", True), ("calendar_item", "all", False)]


def test_the_full_picture_reads_every_page_of_step_4_get_only(portal):
    pages = full_picture_pages()
    portal.pages.update(pages)
    batches, failed = asyncio.run(full_picture.collect(admin_client, TODAY))
    assert failed == []
    assert [(b["kind"], b["scope"], b["complete"]) for b in batches] == FULL_SHAPE
    assert {m for m, _ in portal.asked} == {"GET"}
    assert sorted({key for _, key in portal.asked}) == sorted(pages)             # every page, none other
    assert [r["key"] for r in batches[0]["rows"]] == ["425", "426", "427"]
    assert batches[1]["scope_range"] == ["2025-09-29", "2026-09-28"]
    assert [r["key"] for r in batches[2]["rows"]] == ["579", "577", "501"]


def test_the_full_picture_publishes_them_in_one_run(cloud, portal, monkeypatch):
    portal.pages.update(full_picture_pages())
    monkeypatch.setattr(settings, "MOCK_MODE", False)
    monkeypatch.setattr(backfill, "quiet_reason", lambda *a, **k: None)
    assert full_picture.run(TODAY, client=admin_client) == 0
    assert cloud.fake.keys("student") == ["425", "426", "427"] and cloud.fake.keys("verification", "2026-09-27") == ["425"]
    assert cloud.fake.keys("pending_payment") == ["501", "577", "579"]
    assert len(cloud.fake.keys("consultation", "2026-09-28")) == 1 and cloud.fake.keys("consultation_totals") == ["all"]
    assert cloud.fake.keys("window_application") == ["Student 0|Window 0"] and cloud.fake.keys("calendar_item")
    (run,) = cloud.fake.runs.values()
    assert run["job"] == "full_picture" and run["status"] == "ok"
    # A student gone from a later complete read is deleted (and their verification's day emptied);
    # a partial read deletes nothing.
    portal.pages["students.php"] = page(verified(426, 2, "TEST STUDENT TWO", "28 Sep, 09:00", applied="12 Sep 2026"),
                                        pg=1, pages=2, total=2)
    portal.pages["students.php?pg=2"] = page(row(427, 3, "TEST STUDENT THREE"), pg=2, pages=2, total=2)
    full_picture.run(TODAY, client=admin_client)
    assert cloud.fake.keys("student") == ["426", "427"] and cloud.fake.keys("verification") == ["426"]
    del portal.pages["students.php?pg=2"]
    full_picture.run(TODAY, client=admin_client)
    assert cloud.fake.keys("student") == ["426", "427"]
    assert list(cloud.fake.runs.values())[-1]["status"] == "partial"


def test_a_partial_read_in_the_full_picture_is_never_complete(portal):
    pages = full_picture_pages()
    del pages["students.php?pg=2"]                                   # page 2 of 2: 404
    del pages["students.php?status=pending&pg=2"]
    portal.pages.update(pages)
    batches, failed = asyncio.run(full_picture.collect(admin_client, TODAY))
    kinds = [b["kind"] for b in batches]
    assert "student" not in kinds and "verification" not in kinds and "pending_payment" not in kinds
    assert failed == ["students.php: students.php: the portal answered HTTP 404",
                      "students.php?status=pending: students.php: the portal answered HTTP 404"]
    assert kinds == ["consultation", "consultation", "consultation_day", "consultation_totals",
                     "window_application", "dashboard_fact", "calendar_item"]


def test_once_the_portal_does_not_answer_the_other_pages_are_not_tried():
    asked = []

    def down(request):
        asked.append(request.url.path.rsplit("/", 1)[-1])
        raise httpx.ConnectTimeout("", request=request)
    client = full_picture.PortalSession()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(down))
    client.is_authenticated, client.mock_mode = True, False
    batches, failed = asyncio.run(full_picture.collect(client, TODAY))
    assert batches == [] and asked == ["students.php"]
    assert failed[0] == "students.php: students.php: the portal did not answer in time (ConnectTimeout)"
    assert len(failed) == 7 and all("not read: the portal did not answer" in f for f in failed[1:])


def test_the_full_picture_reads_nothing_when_it_may_not_run(cloud, portal, monkeypatch, caplog):
    portal.pages.update(full_picture_pages())
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(settings, "MOCK_MODE", False)
    monkeypatch.setattr(backfill, "quiet_reason", lambda *a, **k: None)
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    assert full_picture.run(TODAY, client=admin_client) == 0 and "publishing is off" in caplog.text
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    monkeypatch.setattr(settings, "MOCK_MODE", True)
    assert full_picture.run(TODAY, client=admin_client) == 0 and "mock mode" in caplog.text
    monkeypatch.setattr(settings, "MOCK_MODE", False)
    monkeypatch.setattr(backfill, "quiet_reason", lambda *a, **k: "18:00-18:10 is a quiet window (a scheduled job runs then)")
    assert full_picture.run(TODAY, client=admin_client) == 0
    assert "Full picture skipped: 18:00-18:10 is a quiet window" in caplog.text
    monkeypatch.setattr(backfill, "quiet_reason", lambda *a, **k: None)
    monkeypatch.setattr(full_picture, "LOCK_WAIT", 0.2)
    fd = publish._os_lock(publish.LOCK_PATH, 0)                        # the backfill is running
    try:
        assert full_picture.run(TODAY, client=admin_client) == 0 and "holds the publish lock" in caplog.text
    finally:
        publish._os_unlock(fd)
    assert portal.asked == [] and cloud.fake.calls == []


def test_the_quiet_windows_just_before_them_and_a_running_sync_are_seen(tmp_path):
    def at(hh, mm):
        return datetime(2026, 9, 28, hh, mm, tzinfo=DHAKA)
    for hh, mm in ((18, 5), (8, 30), (9, 0), (8, 39)):
        assert full_picture.skip_reason(at(hh, mm), tmp_path).endswith("is a quiet window (a scheduled job runs then)")
    assert full_picture.skip_reason(at(17, 57), tmp_path) == ("18:00-18:10 is a quiet window (a scheduled job runs "
                                                              "then), less than 5 minutes from now")
    for hh, mm in ((17, 54), (18, 10), (18, 13), (8, 40), (9, 10), (12, 0)):
        assert full_picture.skip_reason(at(hh, mm), tmp_path) is None
    (tmp_path / "auto_sync.lock").write_text(str(os.getpid()), encoding="utf-8")
    assert full_picture.skip_reason(at(12, 0), tmp_path) == "a portal sync is running (data/auto_sync.lock)"


def test_the_real_full_picture_process_does_nothing_while_publishing_is_off():
    if (BOT_ROOT / ".env").exists() or any(k in os.environ for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY",
                                                                     "CLOUD_PUBLISH_ENABLED")):
        pytest.skip("this checkout has a .env (or Supabase settings in the environment): the child could publish")
    out = subprocess.run([sys.executable, "-m", "src.cloud.full_picture"], cwd=str(BOT_ROOT), capture_output=True,
                         text=True, timeout=120, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert out.returncode == 0, out.stderr[-500:]
    assert "Full picture skipped: publishing is off." in out.stderr


def test_nothing_the_bot_process_imports_for_supabase_imports_torch():
    code = ("import sys; import src.bot.scheduler, src.cloud.bot_jobs, src.cloud.full_picture; "
            "print('torch' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=str(BOT_ROOT), capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip() == "False"


# --------------------------------------------------------------------------- its scheduler job

class RecordingScheduler:
    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, **kwargs):
        self.jobs[kwargs["id"]] = (func, trigger, kwargs)

    def start(self):
        pass


def fire_times(trigger, n):
    now = datetime.now(DHAKA)
    times, previous = [], None
    for _ in range(n):
        previous = trigger.get_next_fire_time(previous, now)
        times.append(previous)
    return times


def test_the_full_picture_job_runs_hourly_one_at_a_time_off_the_other_jobs_beat(monkeypatch):
    from apscheduler.triggers.interval import IntervalTrigger
    fake = RecordingScheduler()
    monkeypatch.setattr(scheduler, "scheduler", fake)
    monkeypatch.setattr(settings, "ENABLE_SCHEDULED_REPORTS", True)
    scheduler.setup_scheduler(SimpleNamespace(bot=Bot()))
    func, trigger, kwargs = fake.jobs["cloud_full_picture"]
    assert func is scheduler.run_full_picture and isinstance(trigger, IntervalTrigger)
    assert trigger.interval == timedelta(minutes=60)
    assert kwargs["max_instances"] == 1 and kwargs["coalesce"] is True
    ours = fire_times(trigger, 24)
    others = fire_times(fake.jobs["portal_sync"][1], 96) + fire_times(fake.jobs["passport_upload_watcher"][1], 48)
    assert min(abs((a - b).total_seconds()) for a in ours for b in others) >= 7 * 60


def test_the_full_picture_process_is_started_only_when_it_may_run(monkeypatch, caplog):
    started = []

    async def run_module(module, label):
        started.append((module, label))
    monkeypatch.setattr(scheduler, "_run_module", run_module)
    caplog.set_level(logging.INFO)
    asyncio.run(scheduler.run_full_picture())                     # publishing is off (conftest)
    assert started == []
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "sb_secret_" + "Fak3KeyForTests0nly" * 2)
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    monkeypatch.setattr(backfill, "quiet_reason", lambda *a, **k: "a portal sync is running (data/auto_sync.lock)")
    asyncio.run(scheduler.run_full_picture())
    assert started == [] and "Full picture publish skipped: a portal sync is running" in caplog.text
    monkeypatch.setattr(backfill, "quiet_reason", lambda *a, **k: None)
    asyncio.run(scheduler.run_full_picture())
    assert started == [("src.cloud.full_picture", "Full picture publish")]
