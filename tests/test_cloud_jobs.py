"""The sheet jobs' copy to Supabase (src/cloud/sheet_hooks.py and the four subprocess jobs).

What is pinned here:
  portal sync     the CSV export (student_export, complete only when its header came whole), the
  (auto_sync)     verified-documents list (student_documents), the summary (report sync_summary and
                  its sections) and each notice Telegram accepted (notification); after the document
                  check, the checked passports' doc_verdict, field_check and doc_page_text (each
                  passport its own complete scope) and, from the whole store, doc_check,
                  field_correction and the DOCUMENT CHECK / FIELD CHECK reports
  missing report  the daily report and a section per incomplete student, the text as sent; a report
                  that could not be built: its notice and the reason; /missing's list per program
  /stage          student_progress of the pages read (never complete: one intake is not everyone)
                  and the report
  issue refresh   the issue dates (complete only without --limit) and every profile read
  every job       one handoff file at its very end, after Drive, Sheets and Telegram; it never waits
                  for the publisher; a read that failed sends no batch (its reason goes to the run);
                  Supabase down, a slow publisher or a hook that breaks changes nothing the job does,
                  prints or sends
Nothing reaches the network: the portal, Telegram and Supabase are fakes, every file is in tmp_path.
"""
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_cloud import REAL_SPAWN, cloud, cloud_warnings, state  # noqa: E402,F401  (cloud is a fixture)
from test_foundation import KLP, page, portal, row  # noqa: E402,F401  (portal is a fixture)
from test_jobs import PROGRESS_PAGE, csv_rows, with_details  # noqa: E402

from src.cloud import handoff, publish, records, sheet_hooks  # noqa: E402
from src.config import settings  # noqa: E402
from src.scraper import client as client_module  # noqa: E402
from src.scraper.client import PortalUnavailable  # noqa: E402
from src.sheets import auto_sync, missing_report, passport_issue, stage_report  # noqa: E402
from src.sheets import progress_builder as pb  # noqa: E402
from src.sheets import verified_docs as vd  # noqa: E402
from src.verify import auto_verify as av  # noqa: E402
from src.verify import doc_verifier as dv  # noqa: E402

PASSPORT = "A01234567"
NAME = "TEST STUDENT ONE"
SCAN = "passport_425_1790000000.jpg"


# --------------------------------------------------------------------------- fakes

@contextmanager
def telegram(status=200, log=None):
    """The jobs' raw Bot API calls (httpx.Client inside notify / send), answered with `status`:
    yields the posts. Only for the job's run: the publisher's own httpx.Client stays real."""
    posts = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, data=None, files=None):
            posts.append({"url": url.rsplit("/", 1)[-1], "data": dict(data or {}), "file": bool(files)})
            if log is not None:
                log.append(("telegram", url.rsplit("/", 1)[-1]))
            return SimpleNamespace(status_code=status, text="ok" if status < 400 else "Bad Request: chat not found")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "Client", Client)
        mp.setattr(settings, "TELEGRAM_BOT_TOKEN", "123:test")
        mp.setattr(settings, "TELEGRAM_BRIEF_CHAT_IDS", "111111111")
        yield posts


def handed(cloud_):
    """The one handoff file the job wrote -> (its document, {kind: [batches]})."""
    assert len(cloud_.spawned) == 1, cloud_.spawned
    doc = json.loads(cloud_.spawned[0].read_text(encoding="utf-8"))
    kinds = {}
    for b in doc["batches"]:
        kinds.setdefault(b["kind"], []).append(b)
    return doc, kinds


def keys(batch):
    return sorted(r["key"] for r in batch["rows"])


def stamped(text):
    return re.sub(r"\[\d{4}-\d\d-\d\d \d\d:\d\d\] ", "[time] ", text)


# --------------------------------------------------------------------------- the portal sync

STORE = {
    "documents": {PASSPORT: {"fingerprint": "f1", "checked": "2026-09-29T09:10:00", "student": NAME,
                             "program": "KLP", "verdict": "REVIEW",
                             "rows": [{"doc": "01 Passport", "file": SCAN, "verdict": "PASS",
                                       "detail": "PASS: valid until 2034-01-01"},
                                      {"doc": "CROSS-CHECK name", "file": "", "verdict": "FLAG",
                                       "detail": "FLAG: not matched on 2 readable documents"},
                                      {"doc": "CROSS-CHECK name", "file": "", "verdict": "PASS",
                                       "detail": "PASS: the father's name is on every document"}]}},
    "fields": {PASSPORT: {"fingerprint": "g1", "checked": "2026-09-29T09:10:00", "student": NAME, "program": "KLP",
                          "rows": [{"field": "DOB", "portal": "2000-01-01", "result": "MATCH",
                                    "detail": "found on 01 Passport"}]}},
    "corrections": [],
}
CHECKED = [{"student": NAME, "passport": PASSPORT, "program": "KLP", "verdict": "REVIEW", "differs": 0, "corrected": 0}]


@pytest.fixture
def sync(monkeypatch, tmp_path):
    """auto_sync.run_once over fakes: one KLP MARCH 2027 sheet (a first run: "sheet ready"), the CSV
    export (.export), the verified list (.documents), and a document check of one student (.result,
    results.json, its OCR text cache and document folder in tmp_path). Set .export / .documents to
    an exception to make that read fail."""
    world = SimpleNamespace(built=[], export=csv_rows(
        ("Direct", "HNG-2026-012", NAME, "01711111111", KLP, "MARCH 2027", "Payment Verified", "", "", PASSPORT),
        ("B2B", "", "TEST STUDENT TWO", "01722222222", KLP, "MARCH 2027", "", "", "", "PENDING")))
    world.documents = [{"uid": "425", "name": NAME, "passport": PASSPORT, "program": KLP,
                        "docs": f"photo_425_1790000000.jpg|{SCAN}"}]
    world.result = {"checked": CHECKED, "waiting": 0, "skipped": [], "store": STORE}
    # How many students the last whole students.php list counted (the hash state's, as the watcher
    # and the full picture publish it): what proves the export whole (records.export_complete).
    world.listed = 2
    monkeypatch.setattr(sheet_hooks, "listed_students", lambda: world.listed)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(auto_sync, "DATA_DIR", data)
    monkeypatch.setattr(auto_sync, "STATE_PATH", data / "sheet_state.json")
    monkeypatch.setattr(auto_sync, "LOCK_PATH", data / "auto_sync.lock")
    monkeypatch.setattr(auto_sync, "RETRY_WAIT", 0)
    monkeypatch.setattr(auto_sync, "_fresh_portal_client", lambda: None)

    cfg = {**pb.PROGRAMS["KLP"], "key": "KLP", "intake": "MARCH 2027"}
    student = {"Source": "Direct", "Student ID": "HNG-2026-012", "Full Name": NAME, "Mobile": "01711111111",
               "Passport No": PASSPORT, "Program": KLP, "Intake": "MARCH 2027", "Passport Issue Date": ""}

    def all_targets():
        if isinstance(world.export, Exception):
            raise world.export
        pb._ALL_STUDENTS_CACHE = world.export        # what fetch_all_students keeps
        return [cfg]

    monkeypatch.setattr(pb, "_ALL_STUDENTS_CACHE", None)
    monkeypatch.setattr(pb, "all_targets", all_targets)
    monkeypatch.setattr(pb, "fetch_roster", lambda c: [dict(student)])
    monkeypatch.setattr(pb, "build_target", lambda c, dry_run=False: world.built.append(c["intake"]))
    monkeypatch.setattr(pb, "sheet_drift", lambda c: 0)

    async def run_local(root, limit=0, skip_drive_done=True):
        if isinstance(world.documents, Exception):
            raise world.documents
        return {"saved": [(pb.PROGRAMS["KLP"]["name"], f"{NAME} ({PASSPORT})", 2, [])], "redownloaded": [],
                "failed": [], "students": world.documents}

    monkeypatch.setattr(vd, "run_local", run_local)

    verification = tmp_path / "verification"
    (verification / "text").mkdir(parents=True)
    monkeypatch.setattr(av, "STORE_PATH", verification / "results.json")
    monkeypatch.setattr(av, "TEXT_DIR", verification / "text")
    av.STORE_PATH.write_text(json.dumps(STORE), encoding="utf-8")
    folder = tmp_path / "docs" / pb.PROGRAMS["KLP"]["name"] / f"{NAME} ({PASSPORT})"
    folder.mkdir(parents=True)
    scan = folder / SCAN
    scan.write_bytes(b"x" * 1234)
    os.utime(scan, (1790000000, 1790000000))
    (av.TEXT_DIR / f"{PASSPORT}.json").write_text(json.dumps({
        f"{SCAN}:1234:1790000000:6": {"text": "PEOPLE'S REPUBLIC OF BANGLADESH PASSPORT TEST STUDENT ONE",
                                      "sizes": [[800, 600]]},
        f"PAGES:{SCAN}:1234:1790000000:20": {"pages": ["PEOPLE'S REPUBLIC OF BANGLADESH PASSPORT TEST STUDENT ONE"],
                                             "sideways": []}}), encoding="utf-8")
    monkeypatch.setattr(dv, "student_folders", lambda: {PASSPORT: (folder, folder.name)})
    monkeypatch.setattr(av, "run", lambda budget=6, only=None, recheck=False: world.result)
    return world


def test_the_sync_hands_over_what_it_read_and_sent_at_its_very_end(sync, cloud):
    with telegram() as posts:
        lines = auto_sync.run_once()
    assert [p["data"]["text"].split("\n")[0] for p in posts] == ["🔄 Portal sync — changes found", "🔍 Document check"]
    doc, kinds = handed(cloud)
    assert doc["job"] == "portal_sync" and doc["failed_reads"] == []

    export, = kinds["student_export"]
    assert (export["scope"], export["complete"]) == ("all", True)
    assert keys(export) == ["NAME:teststudenttwo8801722222222", "Student ID:HNG-2026-012"]
    assert export["rows"][0]["data"]["stale_columns"] == ["Current Stage", "Current Status", "Progress %"]
    documents, = kinds["student_documents"]
    assert (documents["scope"], documents["complete"], keys(documents)) == ("all", True, ["425"])

    summary = lines[:3]                    # the sheet, the documents saved; then the check's own lines
    assert summary[0].startswith("📄 ") and summary[1].startswith("📁 ") and lines[3].startswith("🔍 ")
    report, = [b for b in kinds["report"] if b["scope"] == "sync_summary"]
    assert report["complete"] is False and report["rows"][0]["key"].startswith("sync_summary|")
    assert report["rows"][0]["content"] == posts[0]["data"]["text"]           # the text as sent
    assert report["rows"][0]["data"]["facts"]["lines"] == summary
    section = [b for b in kinds["report_section"] if b["scope"] == report["rows"][0]["key"]][0]
    assert section["complete"] is True
    assert [r["data"]["heading"] for r in section["rows"]] == summary[:2]
    assert section["rows"][1]["data"]["lines"] == [f"• {NAME} ({PASSPORT}) — {pb.PROGRAMS['KLP']['name']}, 2 file(s)"]

    # the document check: each checked passport its own complete scope, then the whole store
    for kind, want in (("doc_verdict", [f"{PASSPORT}|01 Passport", f"{PASSPORT}|CROSS-CHECK name",
                                        f"{PASSPORT}|CROSS-CHECK name#2"]),
                       ("field_check", [f"{PASSPORT}|DOB"]), ("doc_page_text", [f"{PASSPORT}|{SCAN}|p1"])):
        b, = kinds[kind]
        assert (b["scope"], b["complete"], keys(b)) == (None, True, want), kind
        assert {r["scope"] for r in b["rows"]} == {PASSPORT}
    order = [b["kind"] for b in doc["batches"]]
    assert order.index("doc_verdict") < order.index("doc_check")        # details before the counts
    check, = kinds["doc_check"]
    assert (check["scope"], check["complete"], keys(check)) == ("all", True, [PASSPORT])
    assert "field_correction" not in kinds                               # none noticed yet
    assert {b["scope"] for b in kinds["report"]} == {"sync_summary", "document_check", "field_check"}
    notices = kinds["notification"]
    assert [b["complete"] for b in notices] == [False, False]
    assert [b["rows"][0]["content"].split("\n")[0] for b in notices] == ["🔄 Portal sync — changes found",
                                                                           "🔍 Document check"]
    assert all(b["scope"] == b["rows"][0]["day"] for b in notices)

    # the publisher's side: Supabase gets each kind in its scope, and the file is gone
    assert publish.process_file(cloud.spawned[0]) == 0 and not cloud.spawned[0].exists()
    assert cloud.fake.keys("student_export") == keys(export)
    assert cloud.fake.keys("doc_verdict", PASSPORT) == keys(kinds["doc_verdict"][0])
    assert cloud.fake.keys("doc_page_text", PASSPORT) == [f"{PASSPORT}|{SCAN}|p1"]
    run, = cloud.fake.runs.values()
    assert (run["job"], run["status"]) == ("portal_sync", "ok")


def test_a_read_that_failed_sends_no_batch_and_its_reason_goes_to_the_run(sync, cloud):
    sync.export = PortalUnavailable("the portal did not answer in time", unreachable=True)
    with telegram():
        auto_sync.run_once(verify=False)
    doc, kinds = handed(cloud)
    assert "student_export" not in kinds and "student_documents" in kinds
    assert doc["failed_reads"] == ["students.php?export=csv: the portal did not answer in time"]
    publish.process_file(cloud.spawned[0])
    assert list(cloud.fake.runs.values())[0]["status"] == "partial"

    cloud.spawned.clear()
    sync.export = csv_rows(("Direct", "HNG-2026-012", NAME, "01711111111", KLP, "MARCH 2027", "", "", "", PASSPORT))
    sync.listed = 1                                                      # the list counts one student now
    sync.documents = RuntimeError(f"a Drive error about {NAME}")      # its text never reaches the run
    auto_sync.STATE_PATH.unlink()
    with telegram():
        auto_sync.run_once(verify=False)
    doc, kinds = handed(cloud)
    assert "student_documents" not in kinds and kinds["student_export"][0]["complete"] is True
    assert doc["failed_reads"] == ["students.php?source=direct&filter_docs=verified: could not be read (RuntimeError)"]
    assert NAME not in json.dumps(doc["failed_reads"])


def test_an_export_without_its_header_or_an_empty_list_is_never_complete(sync, cloud):
    sync.export = [{"Name": NAME, "Phone": "01711111111"}]              # not the export's columns
    sync.documents = []                                                  # a list page that shows nobody
    with telegram():
        auto_sync.run_once(verify=False)
    doc, kinds = handed(cloud)
    assert kinds["student_export"][0]["complete"] is False
    assert "student_documents" not in kinds                              # never an empty complete scope
    assert doc["failed_reads"] == ["students.php?export=csv: no Student ID and Full Name header",
                                   "students.php?source=direct&filter_docs=verified: no student listed"]
    publish.process_file(cloud.spawned[0])
    body = [b for b in cloud.fake.syncs() if b["p_kind"] == "student_export"][0]
    assert body["p_all_keys"] is None                                    # nothing deleted


def test_a_notice_counts_as_sent_only_once_telegram_accepted_it(sync, cloud):
    with telegram(status=400) as posts:
        auto_sync.run_once()
    assert len(posts) == 2                                               # it was tried, and refused
    doc, kinds = handed(cloud)
    assert "notification" not in kinds
    assert "sync_summary" in {b["scope"] for b in kinds["report"]}        # the report was still built

    cloud.spawned.clear()
    auto_sync.STATE_PATH.unlink()
    auto_sync.run_once(send=False)                                       # --no-notify
    doc, kinds = handed(cloud)
    assert "notification" not in kinds and "sync_summary" in {b["scope"] for b in kinds["report"]}


def test_supabase_down_changes_nothing_the_sync_does_prints_or_sends(sync, cloud, monkeypatch, capsys, caplog):
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    with telegram() as off_posts:
        off_lines = auto_sync.run_once()
    off_out = stamped(capsys.readouterr().out)
    assert cloud.spawned == [] and not handoff.PENDING_DIR.exists()     # off: no file, no process
    built_off = list(sync.built)

    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    auto_sync.STATE_PATH.unlink()
    cloud.fake.fail = lambda request: httpx.Response(500, json={"code": "XX000", "message": f"row {NAME}"})
    with telegram() as on_posts:
        on_lines = auto_sync.run_once()
    assert (on_lines, on_posts, stamped(capsys.readouterr().out)) == (off_lines, off_posts, off_out)
    assert sync.built == built_off * 2

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="hangeul.cloud"):
        assert publish.process_file(cloud.spawned[0]) == 0
    warnings = cloud_warnings(caplog)
    assert len(warnings) == 1 and "HTTP 500" in warnings[0].getMessage()
    assert NAME not in caplog.text
    assert state() is None                                               # nothing advanced: all again next run


def test_the_sync_never_waits_for_the_publisher(sync, cloud, monkeypatch):
    events = []

    class Popen:
        def __init__(self, args, **kwargs):
            events.append(("publisher", args, kwargs))

        def poll(self):
            return None                                                  # a slow publisher: still running

        def wait(self, *args, **kwargs):
            raise AssertionError("the job must never wait for the publisher")

        communicate = wait

    monkeypatch.setattr(handoff, "spawn", REAL_SPAWN)
    monkeypatch.setattr(handoff, "_children", [])
    monkeypatch.setattr(handoff.subprocess, "Popen", Popen)
    with telegram(log=events):
        lines = auto_sync.run_once()
    assert lines and [e[0] for e in events] == ["telegram", "telegram", "publisher"]   # Telegram first
    args, kwargs = events[-1][1], events[-1][2]
    assert args[1:4] == ["-m", "src.cloud.publish", "--from"] and Path(args[4]).exists()
    assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "-1" and kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] not in (None, subprocess.PIPE) and kwargs["stderr"] not in (None, subprocess.PIPE)


def test_a_hook_that_breaks_is_one_line_and_the_sync_goes_on(sync, cloud, monkeypatch, caplog):
    with telegram() as expected:
        want = auto_sync.run_once()
    cloud.spawned.clear()
    auto_sync.STATE_PATH.unlink()

    def broken(*args, **kwargs):
        raise RuntimeError(f"bad row for {NAME}")

    monkeypatch.setattr(records, "student_exports", broken)
    caplog.clear()
    with telegram() as posts:
        assert auto_sync.run_once() == want
    assert posts == expected and cloud.spawned == []
    warnings = cloud_warnings(caplog)
    assert [w.getMessage() for w in warnings] == [
        "Supabase publish failed (portal_sync): the records could not be built (RuntimeError)"]


def test_an_unreadable_store_sends_only_the_passports_just_checked(sync, cloud):
    av.STORE_PATH.write_text("{ not json", encoding="utf-8")            # auto_verify starts from an empty store
    fresh = {"documents": {PASSPORT: STORE["documents"][PASSPORT]}, "fields": {}, "corrections": []}
    sync.result = {"checked": CHECKED, "waiting": 0, "skipped": [], "store": fresh}
    with telegram():
        auto_sync.run_once()
    doc, kinds = handed(cloud)
    assert "doc_verdict" in kinds and "doc_check" not in kinds
    assert {b["scope"] for b in kinds["report"]} == {"sync_summary"}      # no DOCUMENT/FIELD CHECK from it
    assert "results.json: unreadable before the document check (it started from an empty store)" in doc["failed_reads"]


def test_a_check_that_could_not_run_is_a_failed_read(sync, cloud, monkeypatch):
    def fault(budget=6, only=None, recheck=False):
        raise RuntimeError("the rules failed: a code fault")

    monkeypatch.setattr(av, "run", fault)
    with telegram() as posts:
        auto_sync.run_once()
    assert len(posts) == 1                                               # the sync summary still went
    doc, kinds = handed(cloud)
    assert "doc_verdict" not in kinds and "doc_check" not in kinds
    assert doc["failed_reads"] == ["document check: could not run (RuntimeError)"]


def test_passports_supabase_never_accepted_are_sent_a_few_a_run(cloud, monkeypatch, tmp_path):
    monkeypatch.setattr(sheet_hooks, "CATCH_UP_PASSPORTS", 1)
    monkeypatch.setattr(av, "TEXT_DIR", tmp_path / "text")
    entry = STORE["documents"][PASSPORT]
    store = {"documents": {"B01234567": dict(entry), "C01234567": dict(entry)}, "fields": {}, "corrections": []}
    result = {"checked": [], "waiting": 0, "store": store}

    def scopes(batches):
        return sorted({r["scope"] for b in batches if b["kind"] == "doc_verdict" for r in b["rows"]})

    first, _ = sheet_hooks.verify_batches(result, True, folders={})
    assert scopes(first) == ["B01234567"]
    publish.publish_batches("portal_sync", first)
    second, _ = sheet_hooks.verify_batches(result, True, folders={})
    assert scopes(second) == ["C01234567"]
    publish.publish_batches("portal_sync", second)
    third, _ = sheet_hooks.verify_batches(result, True, folders={})
    assert scopes(third) == []                                           # both are in Supabase now
    assert cloud.fake.keys("doc_verdict", "B01234567") and cloud.fake.keys("doc_verdict", "C01234567")


def test_nothing_is_kept_or_built_while_publishing_is_off(sync, cloud, monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "")
    seen = []
    monkeypatch.setattr(sheet_hooks, "sync_batches", lambda c: seen.append(c) or ([], []))
    with telegram() as posts:
        assert auto_sync.run_once()
    assert len(posts) == 2 and seen == [] and cloud.spawned == [] and not handoff.PENDING_DIR.exists()


# --------------------------------------------------------------------------- the missing-information report

def sheet_rec(sid, name, **more):
    r = {f: "x" for f in missing_report.REQUIRED}
    r.update({"Student ID": sid, "Full Name": name, "Program": KLP, "Study Status": "HSC PASSED",
              "Mobile": "8801711111111"}, **more)
    return r


@pytest.fixture
def sheets(monkeypatch, tmp_path):
    """The progress sheets (read_sheets) and the CSV export behind the missing report."""
    world = SimpleNamespace(data={"KLP|MARCH 2027": [sheet_rec("HNG-2026-012", NAME, Email=""),
                                                    sheet_rec("HNG-2026-913", "TEST STUDENT TWO")]})
    monkeypatch.setattr(pb, "fetch_all_students", lambda: [
        {"Source": "Direct", "Student ID": "HNG-2026-012", "Full Name": NAME, "Mobile": "01711111111",
         "Program": KLP, "Intake": "MARCH 2027"},
        {"Source": "Direct", "Student ID": "", "Full Name": "NO INTAKE STUDENT", "Mobile": "01733333333",
         "Program": KLP, "Intake": ""}])
    monkeypatch.setattr(missing_report, "read_sheets", lambda: world.data)
    monkeypatch.setattr(missing_report, "REPORT_DIR", tmp_path / "missing_reports")
    return world


def run_main(module, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", [module.__name__.rsplit(".", 1)[-1], *argv])
    module.main()


def pin_job_clock(monkeypatch, at):
    """The job's own clock at `at` too (missing_report reads time.time() for the send time and
    time.strftime for its heading), not only records.now: else the notice's day is the PC's."""
    import time as real_time
    epoch = at.timestamp()
    monkeypatch.setattr(missing_report, "time", SimpleNamespace(
        time=lambda: epoch,
        strftime=lambda fmt, *t: real_time.strftime(fmt, *(t or (real_time.localtime(epoch),)))))


def test_the_daily_missing_report_hands_over_the_report_its_sections_and_the_text_sent(sheets, cloud, monkeypatch):
    at = records.datetime(2026, 9, 29, 9, 5, 12, tzinfo=records._zone())
    monkeypatch.setattr(records, "now", lambda: at)
    pin_job_clock(monkeypatch, at)
    with telegram() as posts:
        run_main(missing_report, monkeypatch)
    assert [p["url"] for p in posts] == ["sendMessage", "sendDocument"]
    doc, kinds = handed(cloud)
    assert doc["job"] == "missing_report" and doc["failed_reads"] == []
    report, = kinds["report"]
    assert (report["scope"], report["complete"], keys(report)) == ("missing_report", False,
                                                                     ["missing_report|2026-09-29"])
    assert report["rows"][0]["content"] == posts[0]["data"]["text"]                  # the text as sent
    assert {r["full_name"] for r in report["rows"][0]["data"]["facts"]["rows"]} == {
        NAME, "TEST STUDENT TWO", "NO INTAKE STUDENT"}                               # complete students too
    sections, = kinds["report_section"]
    assert (sections["scope"], sections["complete"]) == ("missing_report|2026-09-29", True)
    assert [r["content"] for r in sections["rows"]] == [
        f"{pb.PROGRAMS['KLP']['name']} MARCH 2027 — HNG-2026-012 {NAME} — 1 missing: Email",
        f"{KLP} (no intake) — NO INTAKE STUDENT — 1 missing: Intake"]
    notice, = kinds["notification"]
    assert (notice["scope"], notice["rows"][0]["content"]) == ("2026-09-29", posts[0]["data"]["text"])
    publish.process_file(cloud.spawned[0])
    assert cloud.fake.keys("report_section", "missing_report|2026-09-29") == [
        "missing_report|2026-09-29|1", "missing_report|2026-09-29|2"]


def test_supabase_down_changes_nothing_the_daily_report_sends(sheets, cloud, monkeypatch, caplog):
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    with telegram() as off:
        run_main(missing_report, monkeypatch)
    assert cloud.spawned == []
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    cloud.fake.fail = lambda request: httpx.ConnectTimeout("timed out")
    with telegram() as on:
        run_main(missing_report, monkeypatch)
    assert on == off and len(cloud.spawned) == 1
    caplog.clear()
    publish.process_file(cloud.spawned[0])
    warnings = cloud_warnings(caplog)
    assert len(warnings) == 1 and "did not answer in time" in warnings[0].getMessage()
    assert state() is None


def test_a_daily_report_that_could_not_be_built_hands_over_its_notice_and_why(sheets, cloud, monkeypatch):
    def broken():
        raise RuntimeError("Google login required")

    monkeypatch.setattr(missing_report, "read_sheets", broken)
    with telegram() as posts, pytest.raises(SystemExit) as exit_:
        run_main(missing_report, monkeypatch)
    assert exit_.value.code == 1 and len(posts) == 1
    doc, kinds = handed(cloud)
    assert set(kinds) == {"notification"}
    assert kinds["notification"][0]["rows"][0]["content"].startswith("❌ Couldn't build today's missing-information report")
    assert doc["failed_reads"] == ["progress sheets or the portal: could not be read (RuntimeError)"]


def test_the_missing_button_prints_the_same_and_hands_over_its_program_list(sheets, cloud, monkeypatch, capsys):
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    run_main(missing_report, monkeypatch, "--program", "KLP")
    off = capsys.readouterr()
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    run_main(missing_report, monkeypatch, "--program", "KLP")
    on = capsys.readouterr()
    assert on.out == off.out and "🗂 MARCH 2027 — 1 of 2 incomplete" in on.out   # the reply is untouched
    doc, kinds = handed(cloud)
    report, = kinds["report"]
    assert report["scope"] == "missing_program:KLP" and report["complete"] is False
    assert report["rows"][0]["content"] == on.out.strip()
    assert [r["full_name"] for r in report["rows"][0]["data"]["facts"]["rows"]] == [
        NAME, "TEST STUDENT TWO", "NO INTAKE STUDENT"]
    sections, = kinds["report_section"]
    assert sections["complete"] is True and sections["scope"] == report["rows"][0]["key"]
    assert any(r["data"]["heading"] == "🗂 MARCH 2027 — 1 of 2 incomplete" for r in sections["rows"])


def test_a_missing_button_that_could_not_read_hands_over_nothing(sheets, cloud, monkeypatch, capsys):
    def broken():
        raise RuntimeError("Google login required")

    monkeypatch.setattr(missing_report, "read_sheets", broken)
    run_main(missing_report, monkeypatch, "--program", "KLP")
    assert capsys.readouterr().out.startswith("❌ Couldn't read the progress sheets or the portal")
    assert cloud.spawned == []


# --------------------------------------------------------------------------- /stage

@pytest.fixture
def stage(monkeypatch):
    """/stage over fakes: two KLP MARCH 2027 students on the export and the list, one progress page
    read and one not."""
    monkeypatch.setattr(pb, "fetch_all_students", lambda: csv_rows(
        ("Direct", "HNG-2026-555", NAME, "01711111111", KLP, "MARCH 2027", "Payment Verified", "", "33"),
        ("Direct", "HNG-2026-556", "TEST STUDENT TWO", "01722222222", KLP, "MARCH 2027", "", "", "")))

    class Client:
        def __init__(self):
            pass

        async def read_students(self, params=None, *, all_pages=True):
            return [{"uid": "425", "student_id": "HNG-2026-555", "student_name": NAME, "status": "Documents Verified",
                     "details": {"Mobile": "01711111111"}},
                    {"uid": "426", "student_id": "HNG-2026-556", "student_name": "TEST STUDENT TWO",
                     "status": "Payment Verified", "details": {}}]

        async def fetch_html(self, path, timeout=60.0, params=None):
            if params["uid"] == "426":
                raise PortalUnavailable("progress.php: HTTP 500")
            return PROGRESS_PAGE.format(pct=44, stage="Documents Verified", status="Verified")

        async def close(self):
            pass

    monkeypatch.setattr(client_module, "HangeulAdminClient", Client)


def test_the_stage_report_prints_the_same_and_hands_over_progress_never_complete(stage, cloud, monkeypatch, capsys):
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    run_main(stage_report, monkeypatch, "--program", "KLP", "--intake", "march 2027")
    off = capsys.readouterr()
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    run_main(stage_report, monkeypatch, "--program", "KLP", "--intake", "march 2027")
    on = capsys.readouterr()
    assert stamped_stage(on.out) == stamped_stage(off.out) and "Verified — 44%" in on.out
    doc, kinds = handed(cloud)
    assert doc["job"] == "stage_report"
    progress, = kinds["student_progress"]
    assert (progress["scope"], progress["complete"], keys(progress)) == ("all", False, ["425"])   # 426: not read
    row_ = progress["rows"][0]
    assert (row_["student_hng_id"], row_["data"]["pct"], row_["data"]["student_name"]) == ("HNG-2026-555", 44, NAME)
    report, = kinds["report"]
    assert report["scope"] == "stage_report:KLP:MARCH 2027" and report["complete"] is False
    facts = report["rows"][0]["data"]["facts"]
    assert facts["counts"] == {"Documents Verified": 1, "Payment Verified": 1}
    assert {s["uid"]: s.get("progress_pct", s.get("progress_error")) for s in facts["students"]} == {
        "425": 44, "426": "progress.php: HTTP 500"}
    sections, = kinds["report_section"]
    assert sections["complete"] is True and sections["scope"] == report["rows"][0]["key"]
    publish.process_file(cloud.spawned[0])
    assert cloud.fake.keys("student_progress") == ["425"]


def stamped_stage(text):
    return re.sub(r"\(live from the portal, [^)]*\)", "(live)", text)


def test_a_stage_report_that_cannot_read_the_portal_hands_over_nothing(stage, cloud, monkeypatch, capsys):
    def down():
        raise PortalUnavailable("students.php: the portal did not answer in time", unreachable=True)

    monkeypatch.setattr(stage_report, "read_listed_students", down)
    run_main(stage_report, monkeypatch, "--program", "KLP", "--intake", "MARCH 2027")
    assert capsys.readouterr().out.startswith("❌ Couldn't read the portal")
    assert cloud.spawned == []


def test_a_stage_hook_that_breaks_changes_nothing_printed(stage, cloud, monkeypatch, capsys, caplog):
    monkeypatch.setattr(records, "student_progress", lambda *a, **k: 1 / 0)
    run_main(stage_report, monkeypatch, "--program", "KLP", "--intake", "MARCH 2027")
    out = capsys.readouterr()
    assert out.out.startswith("📊 Stages — ") and "Supabase" not in out.out    # stdout is the reply
    assert cloud.spawned == []
    assert [w.getMessage() for w in cloud_warnings(caplog)] == [
        "Supabase publish failed (stage_report): the records could not be built (ZeroDivisionError)"]


# --------------------------------------------------------------------------- the issue-date refresh

def edit_page(uid, name, passport, issued):
    return ('<form method="POST"><input type="hidden" name="_csrf" value="csrf-token-1">'
            f'<input type="hidden" name="id" value="{uid}"><input name="full_name" value="{name}">'
            f'<input name="passport_number" value="{passport}">'
            f'<input type="date" name="passport_issue_date" value="{issued}">'
            '<input type="password" name="password" value=""><select name="gender"><option>MALE</option>'
            '<option selected>FEMALE</option></select></form>')


@pytest.fixture
def issues(portal, monkeypatch, tmp_path):
    monkeypatch.setattr(passport_issue, "CACHE_PATH", tmp_path / "passport_issue.json")
    portal.pages["students.php"] = page(
        with_details(row(1, 1, NAME, hng="HNG-2026-905"), Passport_No=PASSPORT),
        with_details(row(2, 2, "TEST STUDENT TWO", hng="HNG-2026-906"), Passport_No="PENDING"),
        with_details(row(3, 3, "TEST STUDENT THREE", hng="HNG-2026-907"), Passport_No="B07654321"))
    portal.pages["student_edit.php?id=1"] = edit_page(1, NAME, PASSPORT, "2024-01-02")
    portal.pages["student_edit.php?id=3"] = edit_page(3, "TEST STUDENT THREE", "B07654321", "2023-05-05")
    return portal


def test_the_refresh_hands_over_the_issue_dates_and_every_profile_it_read(issues, cloud, monkeypatch):
    run_main(passport_issue, monkeypatch, "--refresh")
    assert json.loads(passport_issue.CACHE_PATH.read_text(encoding="utf-8")) == {
        "by_passport": {PASSPORT: "2024-01-02", "B07654321": "2023-05-05"}}
    assert {m for m, _ in issues.asked} == {"GET"}
    doc, kinds = handed(cloud)
    assert doc["job"] == "issue_refresh"
    dates, = kinds["passport_issue"]
    assert (dates["scope"], dates["complete"], keys(dates)) == ("all", True, [PASSPORT, "B07654321"])
    profiles, = kinds["student_profile"]
    assert (profiles["scope"], profiles["complete"], keys(profiles)) == (None, True, ["1", "3"])
    one = [r for r in profiles["rows"] if r["key"] == "1"][0]
    assert one["scope"] == "1" and one["passport_no"] == PASSPORT and one["student_name"] == NAME
    assert one["data"]["gender"] == "FEMALE" and "_csrf" not in one["data"] and "password" not in one["data"]
    publish.process_file(cloud.spawned[0])
    assert cloud.fake.keys("student_profile", "3") == ["3"] and cloud.fake.keys("passport_issue") == keys(dates)


def test_a_refresh_with_a_limit_is_not_complete(issues, cloud, monkeypatch):
    run_main(passport_issue, monkeypatch, "--refresh", "--limit", "1")
    doc, kinds = handed(cloud)
    dates, = kinds["passport_issue"]
    assert dates["complete"] is False and keys(dates) == [PASSPORT]     # the others are not deleted


def test_while_publishing_is_off_the_refresh_keeps_no_page(issues, cloud, monkeypatch):
    kept = []
    real = passport_issue.refresh
    monkeypatch.setattr(passport_issue, "refresh", lambda limit=0, pages=None: kept.append(pages) or real(limit, pages))
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    run_main(passport_issue, monkeypatch, "--refresh")
    assert kept == [None] and cloud.spawned == [] and passport_issue.CACHE_PATH.exists()


def test_a_refresh_that_fails_hands_over_nothing(issues, cloud, monkeypatch):
    del issues.pages["students.php"]                                     # the list cannot be read
    with pytest.raises(PortalUnavailable):
        run_main(passport_issue, monkeypatch, "--refresh")
    assert cloud.spawned == [] and not passport_issue.CACHE_PATH.exists()


# --------------------------------------------------------------------------- the builders

def test_the_summary_lines_become_sections_with_their_indented_lines():
    assert sheet_hooks.line_sections(["📄 KLP MARCH 2027: sheet updated — now 2 students", "   • 1 new: A",
                                      "   • 1 edited: B (Mobile)", "✅ Document download is working again."]) == [
        ("📄 KLP MARCH 2027: sheet updated — now 2 students", ["• 1 new: A", "• 1 edited: B (Mobile)"]),
        ("✅ Document download is working again.", [])]


def test_a_failed_read_reason_holds_no_url_and_no_exception_text():
    assert sheet_hooks.reason("students.php", PortalUnavailable("students.php: HTTP 502")) == \
        "students.php: students.php: HTTP 502"
    assert sheet_hooks.reason("x", httpx.ConnectError("https://portal.test/a?b=c")) == \
        "x: could not connect to the portal (ConnectError)"
    assert sheet_hooks.reason("x", ValueError(f"{NAME} 01711111111")) == "x: could not be read (ValueError)"
    assert sheet_hooks.reason("x", None) == "x: not read"


def test_every_record_a_job_hands_over_is_one_supabase_accepts(sync, cloud):
    with telegram():
        auto_sync.run_once()
    doc, _ = handed(cloud)
    for b in doc["batches"]:
        for r in b["rows"]:
            assert r["key"] and r["source"] and r["content_hash"] and isinstance(r["data"], dict)
            assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+06:00", r["read_at"]), r["read_at"]
            assert b["scope"] is None or r["scope"] == b["scope"]
    publish.process_file(cloud.spawned[0])
    assert all(v["status"] == "ok" for v in cloud.fake.runs.values())
