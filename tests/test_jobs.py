"""The scheduled jobs and the sheet reports, each checked against synthetic data.

  passport watcher (src/bot/scheduler.py, every 30 min)  every students.php page; a scan known by its
      uid and file name (a re-upload is checked again, an unchanged scan never); every alert sent,
      grouped under Telegram's limit, and marked sent only once Telegram accepted it
  portal sync (src/sheets/auto_sync.py, every 15 min)    a student whose row key changed (an ID
      given, a passport number filled in) is "edited", never "new + removed"; the document-check
      message under its own title; first downloads apart from re-downloads (verified_docs.py)
  /stage (src/sheets/stage_report.py)       the stage from the student list, not the CSV export
  /missing (src/sheets/missing_report.py)   university fields read from the portal where the
      sheet has no such columns, "not checked" when that record is missing
  passport issue dates (src/sheets/passport_issue.py)    no placeholder passport number as a key,
      a failed read never empties the cache; the sheets use the export's own column first

Nothing reaches the network, Telegram, Google or the production data folders: the portal is the
foundation's fake (tests/test_foundation.py: row(), page(), the `portal` fixture), bots and HTTP
clients are fakes that record what they were given, and every file lives in tmp_path.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_jobs.py -q
"""
import asyncio
import csv
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from telegram.error import BadRequest, NetworkError

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_foundation import KLP, BACHELOR, page, portal, row  # noqa: E402,F401  (portal is a fixture)

from src.bot import replies, scheduler, telegram_bot  # noqa: E402
from src.config import settings  # noqa: E402
from src.scraper import client as client_module  # noqa: E402
from src.scraper.client import PortalUnavailable, admin_client  # noqa: E402
from src.sheets import auto_sync, missing_report, passport_issue, stage_report, verified_docs  # noqa: E402
from src.sheets import progress_builder as pb  # noqa: E402

ADMIN = "111111111"
MASTER = "MASTER'S DEGREE"


def with_details(html, **fields):
    """A foundation row() with more details-row fields (e.g. Passport_No="A01234567")."""
    items = "".join(f'<div class="det-item"><label>{k.replace("_", " ")}</label><span>{v or "—"}</span></div>'
                    for k, v in fields.items())
    return html.replace('<div class="det">', '<div class="det">' + items, 1)


def scan_row(uid, sl, name, upload=1790000000, ext="jpg", **kw):
    """A student whose passport upload is passport_<uid>_<upload>.<ext>."""
    html = with_details(row(uid, sl, name, hng=f"HNG-2026-{uid:03d}", **kw), Passport_No=f"A0{uid:07d}",
                        Passport_Expiry="2034-01-01")
    return html.replace(f"passport_{uid}_1700000000.jpeg", f"passport_{uid}_{upload}.{ext}")


# --------------------------------------------------------------------------- the passport watcher

class Bot:
    """Records every message; refuse=n refuses the n-th send (1-based) with `error`."""

    def __init__(self, refuse=(), error=None):
        self.sent, self.calls, self.refuse, self.error = [], 0, set(refuse), error

    async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
        self.calls += 1
        if replies.telegram_len(text) > replies.TELEGRAM_LIMIT:
            raise BadRequest("Message is too long")
        if self.calls in self.refuse:
            raise self.error
        self.sent.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})


@pytest.fixture
def watcher(portal, monkeypatch, tmp_path):
    """The portal fake plus a fake audit: results[uid] (default a clean MATCH), every call recorded."""
    audits, results = [], {}

    async def audit(uid, form, doc_filename=None, force_live=True):
        audits.append((uid, doc_filename, dict(form)))
        return results.get(uid) or {"status": "MATCH", "is_valid": True, "discrepancies": []}

    monkeypatch.setattr(admin_client, "audit_student_passport", audit)
    monkeypatch.setattr(admin_client, "base_url", "https://portal.test")
    monkeypatch.setattr(scheduler, "ALERTED_CACHE_FILE", str(tmp_path / "data" / "alerted_passport_issues.json"))
    monkeypatch.setattr(settings, "TELEGRAM_ADMIN_CHAT_ID", ADMIN)
    return SimpleNamespace(portal=portal, audits=audits, results=results)


def bad(uid, *issues, status="DISCREPANCY"):
    return {"status": status, "is_valid": False, "discrepancies": list(issues) or [f"DOB mismatch for {uid}"]}


def run_watcher(bot):
    asyncio.run(scheduler.check_new_passport_uploads(SimpleNamespace(bot=bot)))
    return json.loads(Path(scheduler.ALERTED_CACHE_FILE).read_text(encoding="utf-8"))["scans"]


def two_pages(n=60, **uploads):
    """n students with passport scans over two students.php pages (50 + the rest)."""
    rows = [scan_row(500 + i, i + 1, f"STUDENT {chr(65 + i % 26)}{i}", upload=uploads.get(str(500 + i), 1790000000 + i))
            for i in range(n)]
    return {"students.php": page(*rows[:50], pg=1, pages=2, total=n),
            "students.php?pg=2": page(*rows[50:], pg=2, pages=2, total=n)}


def test_watcher_reads_every_page_and_audits_each_scan_once(watcher):
    watcher.portal.pages.update(two_pages(60))
    bot = Bot()
    memory = run_watcher(bot)

    audited = {uid for uid, _, _ in watcher.audits}
    assert audited == {str(500 + i) for i in range(60)}          # page 2's ten students included
    assert [uid for uid, _, _ in watcher.audits][:2] == ["559", "558"]   # newest upload first
    assert set(memory) == {f"{500 + i}|passport_{500 + i}_{1790000000 + i}.jpg" for i in range(60)}
    assert bot.sent == []                                         # all clean: no message at all
    form = next(f for uid, _, f in watcher.audits if uid == "555")
    assert form["passport_no"] == "A00000555" and form["passport_expiry"] == "2034-01-01"
    assert {m for m, _ in watcher.portal.asked} == {"GET"}

    watcher.audits.clear()
    run_watcher(bot)                                              # nothing changed: nothing re-read
    assert watcher.audits == [] and bot.sent == []


def test_every_alert_is_sent_grouped_under_the_limit(watcher, caplog):
    watcher.portal.pages.update(two_pages(60))
    long_issue = "Name spelling issue: Portal has 'X', MRZ has 'Y' " * 6
    for i in range(0, 60, 2):                                     # 30 students with issues
        watcher.results[str(500 + i)] = bad(500 + i, long_issue, f"DOB mismatch {i}")
    bot = Bot()
    caplog.set_level("INFO", logger="hangeul.scheduler")
    memory = run_watcher(bot)

    assert 1 < len(bot.sent) < 30                                  # grouped, not one message each
    assert all(replies.telegram_len(m["text"]) <= replies.CHUNK_CHARS for m in bot.sent)
    text = "\n".join(m["text"] for m in bot.sent)
    for i in range(0, 60, 2):                                     # every alert went out, once
        assert text.count(f"`ID {500 + i}`") == 1
    assert bot.sent[0]["text"].startswith(f"🚨 *Automated Document Audit: 30 alerts* (part 1 of {len(bot.sent)})")
    assert all(e["sent"] for e in memory.values() if e["alert"])
    assert sum(1 for e in memory.values() if e["alert"]) == 30
    assert f"30 alert(s) sent in {len(bot.sent)} message(s), 0 not sent yet" in caplog.text

    again = Bot()
    run_watcher(again)
    assert again.sent == []                                       # never sent twice


def test_an_alert_telegram_refused_is_sent_on_the_next_run(watcher):
    watcher.portal.pages.update(two_pages(60))
    for i in range(0, 60, 2):
        watcher.results[str(500 + i)] = bad(500 + i, "x" * 400)
    down = Bot(refuse={2}, error=NetworkError("Telegram is down"))
    memory = run_watcher(down)
    first = [k for k, e in memory.items() if e["alert"] and e["sent"]]
    assert len(down.sent) == 1 and 0 < len(first) < 30            # message 1 went out, the rest wait
    assert all(f"`ID {k.split('|')[0]}`" in down.sent[0]["text"] for k in first)

    watcher.audits.clear()
    up = Bot()
    memory = run_watcher(up)
    assert watcher.audits == []                                   # sent from memory, no second OCR
    text = "\n".join(m["text"] for m in up.sent)
    assert all(e["sent"] for e in memory.values() if e["alert"])
    for k, e in memory.items():
        if e["alert"]:
            assert (f"`ID {e['uid']}`" in text) == (k not in first)


def test_markdown_refused_goes_as_plain_text_and_counts_as_sent(watcher):
    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "KARIM HASAN"))
    watcher.results["501"] = bad(501, "Father's Name discrepancy: Portal has 'A_B', Doc has 'A*B'")
    bot = Bot(refuse={1}, error=BadRequest("Can't parse entities: can't find end of the entity"))
    memory = run_watcher(bot)
    assert len(bot.sent) == 1 and bot.sent[0]["parse_mode"] is None
    assert "Portal has 'A_B', Doc has 'A*B'" in bot.sent[0]["text"]  # the validator's words, as they are
    assert memory["501|passport_501_1790000000.jpg"]["sent"] is True


def test_the_validators_own_words_go_into_the_alert(watcher):
    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "KARIM HASAN"))
    watcher.results["501"] = bad(501, "MRZ could not be read automatically, please check the scan by eye",
                                 status="OCR_UNREADABLE")
    bot = Bot()
    run_watcher(bot)
    text = bot.sent[0]["text"]
    assert text.startswith("🚨 *Automated Document Audit Alert*")
    assert "`OCR_UNREADABLE`" in text and "please check the scan by eye" in text
    assert "not a valid passport" not in text
    assert "[Edit Student #501](https://portal.test/student_edit.php?id=501)" in text


def test_a_reuploaded_passport_is_checked_again(watcher):
    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "KARIM HASAN", upload=1790000000))
    watcher.results["501"] = bad(501, "DOB mismatch")
    bot = Bot()
    run_watcher(bot)
    assert len(bot.sent) == 1

    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "KARIM HASAN", upload=1790009999, ext="pdf"))
    watcher.results["501"] = {"status": "MATCH", "is_valid": True, "discrepancies": []}
    watcher.audits.clear()
    memory = run_watcher(bot)
    assert watcher.audits == [("501", "passport_501_1790009999.pdf", watcher.audits[0][2])]
    assert list(memory) == ["501|passport_501_1790009999.pdf"]    # the replaced scan is forgotten
    assert len(bot.sent) == 1                                     # the new scan is clean: no alert


def test_the_old_uid_only_memory_is_not_trusted(watcher):
    """The old watcher saved every flagged uid before sending only 3 of them, so its list says
    nothing about what the admin was told: every current scan is checked once more."""
    Path(scheduler.ALERTED_CACHE_FILE).parent.mkdir(parents=True)
    Path(scheduler.ALERTED_CACHE_FILE).write_text(json.dumps(["501", "502"]), encoding="utf-8")
    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "KARIM HASAN"), scan_row(502, 2, "NADIA ISLAM"))
    watcher.results["502"] = bad(502, "DOB mismatch")
    bot = Bot()
    memory = run_watcher(bot)
    assert {uid for uid, _, _ in watcher.audits} == {"501", "502"}
    assert len(bot.sent) == 1 and "`ID 502`" in bot.sent[0]["text"]
    assert memory["502|passport_502_1790000000.jpg"]["sent"] is True


def test_a_portal_that_cannot_be_read_audits_and_sends_nothing(watcher, caplog):
    watcher.portal.pages["students.php"] = page(*[scan_row(500 + i, i + 1, f"S{i}") for i in range(50)])  # no pager
    bot = Bot()
    caplog.set_level("INFO", logger="hangeul.scheduler")
    asyncio.run(scheduler.check_new_passport_uploads(SimpleNamespace(bot=bot)))
    assert watcher.audits == [] and bot.sent == []
    assert not Path(scheduler.ALERTED_CACHE_FILE).exists()
    assert "couldn't read the portal" in caplog.text
    assert "no new discrepancies" not in caplog.text


def test_a_scan_that_could_not_be_downloaded_is_tried_again_never_alerted(watcher):
    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "KARIM HASAN"))
    watcher.results["501"] = {"status": "MISSING_DOCUMENT", "is_valid": False,
                              "discrepancies": ["No passport document scan uploaded on file"]}
    bot = Bot()
    memory = run_watcher(bot)
    assert bot.sent == [] and memory == {}
    watcher.results.pop("501")
    memory = run_watcher(bot)
    assert memory["501|passport_501_1790000000.jpg"]["status"] == "MATCH"


@pytest.mark.parametrize("unchecked", ["portal", "ocr"])
def test_a_scan_the_portal_would_not_serve_is_tried_again_never_remembered(watcher, unchecked):
    """audit_student_passport answers PORTAL_UNREADABLE (ocr_validator.unchecked_result) when the
    profile or the scan could not be read, and OCR_UNAVAILABLE when the OCR engine did not run:
    nothing was checked, so the next run checks it."""
    from src.scraper.ocr_validator import unchecked_result
    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "KARIM HASAN"))
    watcher.results["501"] = (
        unchecked_result("501", "the passport scan could not be downloaded: timed out") if unchecked == "portal"
        else {"status": "OCR_UNAVAILABLE", "is_valid": False, "discrepancies": [],
              "verdict": "❌ Couldn't run the OCR engine on this computer, so the scan was not checked"})
    bot = Bot()
    memory = run_watcher(bot)
    assert bot.sent == [] and memory == {}
    watcher.results.pop("501")
    watcher.audits.clear()
    memory = run_watcher(bot)
    assert [uid for uid, _, _ in watcher.audits] == ["501"]
    assert memory["501|passport_501_1790000000.jpg"]["status"] == "MATCH" and bot.sent == []


def test_a_run_stops_at_its_time_budget_and_the_rest_wait(watcher, monkeypatch):
    watcher.portal.pages["students.php"] = page(*[scan_row(500 + i, i + 1, f"S{i}", upload=1790000000 + i)
                                                   for i in range(5)])
    monkeypatch.setattr(scheduler, "WATCHER_BUDGET_SECONDS", -1)
    memory = run_watcher(Bot())
    assert watcher.audits == [] and memory == {}
    monkeypatch.setattr(scheduler, "WATCHER_BUDGET_SECONDS", 1200)
    memory = run_watcher(Bot())
    assert [uid for uid, _, _ in watcher.audits] == ["504", "503", "502", "501", "500"]
    assert len(memory) == 5


def test_the_watcher_job_runs_one_at_a_time(monkeypatch):
    jobs = {}

    class FakeScheduler:
        def add_job(self, func, trigger, **kwargs):
            jobs[kwargs["id"]] = kwargs

        def start(self):
            pass

    monkeypatch.setattr(scheduler, "scheduler", FakeScheduler())
    monkeypatch.setattr(settings, "ENABLE_SCHEDULED_REPORTS", True)
    scheduler.setup_scheduler(SimpleNamespace(bot=Bot()))
    assert jobs["passport_upload_watcher"]["max_instances"] == 1
    assert jobs["passport_upload_watcher"]["coalesce"] is True


# --------------------------------------------------------------------------- the portal sync

def rec(sid="", name="KHAN LUBNA", mobile="8801711111111", passport="A01234567", **more):
    return {"Student ID": sid, "Full Name": name, "Mobile": mobile, "Passport No": passport, **more}


def snap(*recs):
    out = {}
    for r in recs:
        key, n = auto_sync._row_key(r), 1
        while key in out:
            n += 1
            key = f"{auto_sync._row_key(r)}#{n}"
        out[key] = {"name": r["Full Name"], "hash": auto_sync._digest(r), "rec": r}
    return out


def test_a_student_given_an_id_is_edited_not_new_and_removed():
    before = snap(rec("", passport="A01234567"), rec("HNG-2026-905", "HAMID TOUFIQ", "8801722222222", "B07654321"))
    after = snap(rec("HNG-2026-940", passport="A01234567"),
                 rec("HNG-2026-905", "HAMID TOUFIQ", "8801722222222", "B07654321"))
    assert auto_sync.sheet_changes(before, after) == ([], [], ["KHAN LUBNA (Student ID)"])


def test_a_passport_filled_in_is_matched_by_name_and_mobile():
    before = snap(rec("", passport=""))
    after = snap(rec("", passport="A01234567"))
    assert auto_sync.sheet_changes(before, after) == ([], [], ["KHAN LUBNA (Passport No)"])


def test_real_joins_and_leaves_are_still_reported():
    before = snap(rec("HNG-2026-905", "HAMID TOUFIQ", "8801722222222", "B07654321"))
    after = snap(rec("HNG-2026-906", "KHALED ROMEL", "8801733333333", "C01111111"))
    assert auto_sync.sheet_changes(before, after) == (["KHALED ROMEL"], ["HAMID TOUFIQ"], [])


def test_a_placeholder_passport_is_no_identity():
    """Students with no passport yet share "PENDING": neither one key for both, nor a pair."""
    a = rec("", "MATIN RASEL", "8801744444444", "PENDING")
    b = rec("", "ARIF MD JAMAL", "8801755555555", "PENDING")
    assert len(snap(a, b)) == 2 and auto_sync._row_key(a) != auto_sync._row_key(b)
    c = rec("", "SOMEONE ELSE", "8801766666666", "PENDING")
    assert auto_sync.sheet_changes(snap(a), snap(c)) == (["SOMEONE ELSE"], ["MATIN RASEL"], [])
    # the old key ("Passport No:PENDING") in a saved state still pairs by name and mobile
    old = {"Passport No:PENDING": {"name": a["Full Name"], "hash": auto_sync._digest(a), "rec": a}}
    assert auto_sync.sheet_changes(old, snap(a)) == ([], [], [])


def test_sync_reports_a_payment_verification_as_one_edit(monkeypatch):
    cfg = {**pb.PROGRAMS["BACHELOR"], "key": "BACHELOR", "intake": "MARCH 2027"}
    cols = pb.columns_for(cfg)
    student = {"Student ID": "", "Full Name": "KHAN LUBNA", "Mobile": "01711111111", "Passport No": "A01234567",
               "Program": BACHELOR, "Intake": "March 2027", "Source": "Direct", "Passport Issue Date": ""}
    built = []
    monkeypatch.setattr(pb, "all_targets", lambda: [cfg])
    monkeypatch.setattr(pb, "fetch_roster", lambda c: [dict(student)])
    monkeypatch.setattr(pb, "build_target", lambda c, dry_run=False: built.append(c["intake"]))
    monkeypatch.setattr(pb, "sheet_drift", lambda c: 0)
    state = {}
    auto_sync.sync_sheets(state)                                  # first run: tracking starts
    old = dict(zip([h for h, _ in cols], pb.build_row(student, cols)))
    assert list(state["sheets"]["BACHELOR|MARCH 2027"]) == [auto_sync._row_key(old)]

    student["Student ID"] = "HNG-2026-940"                        # payment verified: an ID given
    lines = auto_sync.sync_sheets(state)
    assert lines == ["📄 BACHELOR'S DEGREE MARCH 2027: sheet updated — now 1 students",
                     "   • 1 edited: KHAN LUBNA (Student ID)"]
    assert built == ["MARCH 2027", "MARCH 2027"]
    assert auto_sync.sync_sheets(state) == []                     # and then nothing to report


class Http:
    """httpx.Client stand-in: records every POST, answers 200 (or `status`)."""
    posts = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, data=None, files=None):
        Http.posts.append({"url": url, "data": dict(data or {}), "file": files and list(files)})
        return SimpleNamespace(status_code=200, text="ok")


@pytest.fixture
def http(monkeypatch):
    Http.posts = []
    monkeypatch.setattr(httpx, "Client", Http)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123:test")
    monkeypatch.setattr(settings, "TELEGRAM_BRIEF_CHAT_IDS", ADMIN)
    return Http


def test_the_document_check_message_carries_its_own_title(http):
    auto_sync.notify(["🔍 Documents checked: 1", "• PODDAR MD SAGOR (EAP) — FAIL"], title="🔍 Document check")
    assert [p["data"]["text"] for p in http.posts] == [
        "🔍 Document check\n\n🔍 Documents checked: 1\n• PODDAR MD SAGOR (EAP) — FAIL"]
    assert "Portal sync" not in http.posts[0]["data"]["text"]


def test_a_failed_document_check_says_which_rule_failed():
    from src.verify import auto_verify
    rows = [{"doc": "Passport", "file": "p.jpg", "verdict": "PASS", "detail": "PASS: readable"},
            {"doc": "HSC certificate", "file": "h.pdf", "verdict": "FAIL",
             "detail": "PASS: readable | FAIL: GPA 4.50 differs from the portal's 5.00 | FLAG: faint stamp"}]
    result = {"checked": [{"student": "PODDAR MD SAGOR", "passport": "A01234567", "program": "EAP",
                           "verdict": "FAIL", "differs": 0, "corrected": 0},
                          {"student": "NO BANK", "passport": "B01234567", "program": "KLP",
                           "verdict": "INCOMPLETE", "differs": 0, "corrected": 0}],
              "store": {"documents": {"A01234567": {"rows": rows}, "B01234567": {"rows": [
                  {"doc": "Bank certificate", "file": "", "verdict": "MISSING",
                   "detail": "required by the guideline but not uploaded"}]}}}}
    lines = auto_verify.summary_lines(result)
    assert lines[1] == ("   • PODDAR MD SAGOR (EAP) — FAIL (HSC certificate: GPA 4.50 differs from "
                        "the portal's 5.00)")
    assert lines[2] == "   • NO BANK (KLP) — INCOMPLETE (Bank certificate: required by the guideline but not uploaded)"


def test_a_long_sync_summary_is_split_between_lines(http):
    lines = [f"   • {i} edited: STUDENT NUMBER {i} (Student ID, Passport No, Mobile)" for i in range(200)]
    auto_sync.notify(lines)
    texts = [p["data"]["text"] for p in http.posts]
    assert len(texts) > 1 and all(replies.telegram_len(t) <= replies.CHUNK_CHARS for t in texts)
    assert texts[0].startswith("🔄 Portal sync — changes found\n\n")
    assert "\n".join(texts).split("\n")[2:] == lines                # no line cut in two


def test_redownloads_are_not_newly_verified_and_empty_ones_are_dropped():
    result = {"saved": [("KOREAN LANGUAGE PROGRAM (KLP)", "NEW STUDENT (A01234567)", 5, [])],
              "redownloaded": [("KOREAN LANGUAGE PROGRAM (KLP)", "MD TANJIL BASHAR (B01234567)", 0, []),
                               ("EAP (ENGLISH FOR ACADEMIC PURPOSE)", "BANU NAZNIN (C01234567)", 1, [])],
              "failed": []}
    assert auto_sync.doc_lines(result) == [
        "📁 1 newly verified student(s) — documents saved:",
        "   • NEW STUDENT (A01234567) — KOREAN LANGUAGE PROGRAM (KLP), 5 file(s)",
        "📁 1 student(s) changed their documents on the portal — new files saved:",
        "   • BANU NAZNIN (C01234567) — EAP (ENGLISH FOR ACADEMIC PURPOSE), 1 new file(s)"]
    assert auto_sync.doc_lines({"saved": [], "redownloaded": [("KLP", "X", 0, [])], "failed": []}) == []


def zip_of(*names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(f"docs/{n}", b"x" * 10)
    return buf.getvalue()


def test_run_local_tells_a_redownload_from_a_first_download(monkeypatch, tmp_path):
    def listed(docs):
        rows = "".join(
            f'<tr><td><a href="download_docs.php?uid={uid}">ZIP</a> Full Name | {name} | Passport No | {pas} | '
            f'Program | {KLP}<a href="view_doc.php?f={d}">d</a></td></tr>' for uid, name, pas, d in docs)
        return f"<table>{rows}</table>"

    zips = {"1": zip_of("passport_1_100.jpg", "photo_1_100.jpg"), "2": zip_of("passport_2_100.jpg", "ssc_2_200.pdf")}

    class Client:
        client = SimpleNamespace()
        base_url = "https://portal.test"

        async def login(self):
            return {"success": True}

        async def read_student_pages(self, params):
            assert params == {"source": "direct", "filter_docs": "verified"}
            return [listed([("1", "NEW STUDENT", "A01234567", "passport_1_100.jpg"),
                            ("2", "OLD STUDENT", "B01234567", "ssc_2_200.pdf")])]

        async def close(self):
            pass

    async def get(url, params=None, timeout=None):
        return SimpleNamespace(status_code=200, headers={"content-type": "application/zip"}, content=zips[params["uid"]])

    Client.client.get = get
    monkeypatch.setattr(client_module, "admin_client", Client())
    old = tmp_path / "KOREAN LANGUAGE PROGRAM (KLP)" / "OLD STUDENT (B01234567)"
    old.mkdir(parents=True)
    (old / "passport_2_100.jpg").write_bytes(b"x")
    (old / verified_docs.LOCAL_DONE_MARKER).write_text("passport_2_100.jpg", encoding="utf-8")   # before the SSC upload

    result = asyncio.run(verified_docs.run_local(tmp_path, skip_drive_done=False))
    assert result["saved"] == [("KOREAN LANGUAGE PROGRAM (KLP)", "NEW STUDENT (A01234567)", 2, [])]
    assert result["redownloaded"] == [("KOREAN LANGUAGE PROGRAM (KLP)", "OLD STUDENT (B01234567)", 1, [])]
    assert auto_sync.doc_lines(result)[2] == "📁 1 student(s) changed their documents on the portal — new files saved:"


def test_the_verified_documents_list_fails_loudly_when_login_is_refused(portal, monkeypatch):
    async def refused(*args, **kwargs):
        return {"success": False, "error": "the portal refused the login (wrong username or password?)"}

    monkeypatch.setattr(admin_client, "is_authenticated", False)
    monkeypatch.setattr(admin_client, "login", refused)
    with pytest.raises(PortalUnavailable, match="refused the login"):
        asyncio.run(verified_docs.fetch_verified_students(admin_client))
    assert portal.asked == []                                     # no endless login-and-retry loop


def test_the_verified_documents_list_reads_every_page(portal):
    rows = [row(700 + i, i + 1, f"S{i}", hng=f"HNG-2026-{700 + i}").replace(
        "<a href=\"student_edit", f'<a href="download_docs.php?uid={700 + i}&zip=1">ZIP</a><a href="student_edit', 1)
        for i in range(55)]
    portal.pages["students.php?source=direct&filter_docs=verified"] = page(*rows[:50], pg=1, pages=2, total=55)
    portal.pages["students.php?source=direct&filter_docs=verified&pg=2"] = page(*rows[50:], pg=2, pages=2, total=55)
    students = asyncio.run(verified_docs.fetch_verified_students(admin_client))
    assert sorted(s["uid"] for s in students) == [str(700 + i) for i in range(55)]


# --------------------------------------------------------------------------- /stage

def csv_rows(*rows):
    head = ["Source", "Student ID", "Full Name", "Mobile", "Program", "Intake", "Current Stage", "Current Status",
            "Progress %", "Passport No"]
    return [dict(zip(head, r)) for r in rows]


@pytest.fixture
def export(monkeypatch):
    """The CSV export as pb.fetch_all_students() returns it (set .rows)."""
    box = SimpleNamespace(rows=[])
    monkeypatch.setattr(pb, "fetch_all_students", lambda: box.rows)
    return box


def listed(*students):
    return [{"uid": str(i), "student_id": sid, "student_name": name, "status": stage,
             "details": {"Mobile": mobile}} for i, (sid, name, stage, mobile) in enumerate(students, 1)]


def test_stage_comes_from_the_student_list_not_the_csv(export):
    export.rows = csv_rows(
        ("Direct", "", "MATIN RASEL", "01744444444", KLP, "MARCH 2027", "Payment Verified", "Pending verification", "11"),
        ("Direct", "HNG-2026-937", "SARKAR MD MILON", "01711111111", KLP, "MARCH 2027", "Application Received",
         "Pending verification", "22"),
        ("Direct", "HNG-2026-930", "BEPARI MD ROBIN", "01722222222", KLP, "MARCH 2027", "Payment Verified", "Verified", "22"),
        ("Direct", "HNG-2026-999", "NOT LISTED", "01733333333", KLP, "MARCH 2027", "Payment Verified", "", ""),
        ("Direct", "HNG-2026-911", "OTHER INTAKE", "01733333334", KLP, "DECEMBER 2026", "Payment Verified", "", ""))
    portal_list = listed(("", "MATIN RASEL", "Application Received", "+8801744444444"),
                         ("HNG-2026-937", "SARKAR MD MILON", "Payment Verified", ""),
                         ("HNG-2026-930", "BEPARI MD ROBIN", "Payment Verified", ""),
                         ("HNG-2026-911", "OTHER INTAKE", "Documents Verified", ""))
    # Each student's status and % are their own progress page's, never the CSV's stale ones.
    progress = {"1": {"pct": 11, "stage": "Application Received", "status": "Submitted"},
                "2": {"pct": 22, "stage": "Payment Verified", "status": "Verified"},
                "3": {"pct": 22, "stage": "Payment Verified", "status": "Verified"}}
    text = stage_report.stage_report("KLP", "MARCH 2027", listed=portal_list, progress=progress)
    assert "— 4 students" in text
    assert "• Application Received: 1\n• Payment Verified: 2\n• ⚠️ Stage not found on the student list: 1" in text
    assert "🔹 Application Received (1)\n   (no ID) MATIN RASEL — Submitted — 11%" in text
    assert ("🔹 Payment Verified (2)\n   HNG-2026-930 BEPARI MD ROBIN — Verified — 22%\n"
            "   HNG-2026-937 SARKAR MD MILON — Verified — 22%") in text
    assert "🔹 ⚠️ Stage not found on the student list (1)\n   HNG-2026-999 NOT LISTED" in text
    assert "Pending verification" not in text                      # the CSV's "Current Status"
    assert "Status and % from each student's own progress page (progress.php), read just now." in text


def test_two_students_of_one_name_are_told_apart_by_mobile():
    rows = csv_rows(("Direct", "", "MD RAHIM", "01744444444", KLP, "MARCH 2027", "", "", ""),
                    ("Direct", "", "MD RAHIM", "01755555555", KLP, "MARCH 2027", "", "", ""),
                    ("Direct", "", "MD KARIM", "", KLP, "MARCH 2027", "", "", ""))
    got = stage_report.attach_stages(rows, listed(("", "MD RAHIM", "Payment Verified", "01755555555"),
                                                  ("", "MD RAHIM", "Application Received", "01744444444"),
                                                  ("", "MD KARIM", "Documents Verified", ""),
                                                  ("", "MD KARIM", "Payment Verified", "")))
    assert [stage for _, stage in got] == ["Application Received", "Payment Verified", None]


def test_the_stage_report_reads_every_page_with_its_own_session(monkeypatch, export):
    export.rows = csv_rows(("Direct", "HNG-2026-555", "S55", "", KLP, "MARCH 2027", "Payment Verified",
                            "Not Started", "33"))
    made = []

    class Client:
        def __init__(self):
            made.append(self)
            self.closed, self.calls, self.pages = False, [], []

        async def read_students(self, params=None, *, all_pages=True):
            self.calls.append(all_pages)
            return listed(("HNG-2026-555", "S55", "Documents Verified", ""))

        async def fetch_html(self, path, timeout=60.0, params=None):
            self.pages.append((path, params))
            return PROGRESS_PAGE.format(pct=44, stage="Documents Verified", status="Verified")

        async def close(self):
            self.closed = True

    monkeypatch.setattr(client_module, "HangeulAdminClient", Client)
    text = stage_report.stage_report("KLP", "MARCH 2027")
    assert "• Documents Verified: 1" in text
    assert made[0].calls == [True] and made[0].closed
    # The progress page, read-only, with a session of its own: its status and %, not the CSV's.
    assert made[1].pages == [("progress.php", {"uid": "1"})] and made[1].closed
    assert "   HNG-2026-555 S55 — Verified — 44%" in text and "Not Started" not in text and "33%" not in text


# progress.php's summary block as the portal lays it out (Sep 2026).
PROGRESS_PAGE = ('<html><body><div class="pg-sum-top"><div class="pg-ring" style="--p:{pct}" title="Overall progress">'
                 '<b>{pct}%</b></div><div class="pg-now"><div class="pg-k">Current stage</div>'
                 '<div class="pg-stage">{stage}</div><div class="pg-status">{status}</div></div></div>'
                 '<ol><li class="tm-item done">1. Application Received Submitted</li></ol></body></html>')


def test_the_progress_page_is_read_by_its_own_classes():
    from src.scraper.parsers import StudentListLayoutError, parse_progress_page
    page_ = PROGRESS_PAGE.format(pct=22, stage="Payment Verified", status="Verified")
    assert parse_progress_page(page_) == {"pct": 22, "stage": "Payment Verified", "status": "Verified"}
    with pytest.raises(StudentListLayoutError):
        parse_progress_page("<html><body>a new layout</body></html>")


def test_a_progress_page_on_another_stage_or_not_read_is_said_so(export):
    export.rows = csv_rows(
        ("Direct", "HNG-2026-922", "ALPHA", "", KLP, "DECEMBER 2026", "", "Verified", "44"),
        ("Direct", "HNG-2026-923", "BETA", "", KLP, "DECEMBER 2026", "", "Verified", "44"),
        ("Direct", "HNG-2026-924", "GAMMA", "", KLP, "DECEMBER 2026", "", "Verified", "44"))
    portal_list = listed(("HNG-2026-922", "ALPHA", "Documents Verified", ""),
                         ("HNG-2026-923", "BETA", "Documents Verified", ""),
                         ("HNG-2026-924", "GAMMA", "Documents Verified", ""))
    progress = {"1": {"pct": 33, "stage": "Documents Under Review", "status": "Submitted"},
                "2": {"error": "progress.php: the portal did not answer in time (ReadTimeout)"},
                "3": {"pct": 44, "stage": "Documents Verified", "status": "Verified"}}
    text = stage_report.stage_report("KLP", "DECEMBER 2026", listed=portal_list, progress=progress)
    # The bucket is the stage the list stores (what the portal's filter and dashboard count); the
    # progress page's own, other stage is shown as the page's, never silently.
    assert "• Documents Verified: 3" in text
    assert "   HNG-2026-922 ALPHA — progress page: Documents Under Review · Submitted — 33%" in text
    assert "   HNG-2026-923 BETA — progress page not read" in text
    assert "   HNG-2026-924 GAMMA — Verified — 44%" in text
    assert ("⚠️ 1 of the 3 progress pages could not be read (progress.php: the portal did not answer in time "
            "(ReadTimeout)): those lines show no status or %.") in text


def test_reading_progress_pages_stops_once_the_portal_is_gone(monkeypatch):
    made = []

    class Client:
        def __init__(self):
            made.append(self)
            self.asked, self.closed = [], False

        async def fetch_html(self, path, timeout=60.0, params=None):
            self.asked.append(params["uid"])
            raise PortalUnavailable("progress.php: could not connect to the portal (ConnectError)", unreachable=True)

        async def close(self):
            self.closed = True

    monkeypatch.setattr(client_module, "HangeulAdminClient", Client)
    got = stage_report.read_progress([str(n) for n in range(1, 60)])
    assert made[0].asked == ["1"] and made[0].closed              # one try, not 59 timeouts in a row
    assert len(got) == 59 and all(p == {"error": "progress.php: could not connect to the portal (ConnectError)"}
                                  for p in got.values())


def test_a_stage_report_that_cannot_read_the_portal_says_so(monkeypatch, export, capsys):
    export.rows = csv_rows(("Direct", "HNG-2026-555", "S55", "", KLP, "MARCH 2027", "Payment Verified", "", ""))

    def down():
        raise PortalUnavailable("students.php: the portal did not answer in time (ReadTimeout)", unreachable=True)

    monkeypatch.setattr(stage_report, "read_listed_students", down)
    monkeypatch.setattr(sys, "argv", ["stage_report", "--program", "KLP", "--intake", "MARCH 2027"])
    stage_report.main()
    out = capsys.readouterr().out
    assert out.startswith("❌ Couldn't read the portal: students.php: the portal did not answer in time")
    assert "Stages for KOREAN LANGUAGE PROGRAM (KLP) MARCH 2027: not available right now" in out
    assert "Payment Verified" not in out

    def csv_down():
        raise RuntimeError("portal did not return the students CSV export")

    monkeypatch.setattr(pb, "fetch_all_students", csv_down)
    monkeypatch.setattr(sys, "argv", ["stage_report", "--program", "KLP"])
    stage_report.main()
    assert json.loads(capsys.readouterr().out) == {"error": "RuntimeError: portal did not return the students CSV export"}


def test_the_intake_menu_shows_why_it_could_not_load(monkeypatch):
    async def module(*args):
        return json.dumps({"error": "couldn't log in to the portal: the portal refused the login"})

    monkeypatch.setattr(telegram_bot, "_run_report_module", module)
    monkeypatch.setattr(telegram_bot, "is_authorized", lambda update: True)
    replies_sent = []

    class Msg:
        async def reply_text(self, text, **kwargs):
            replies_sent.append(text)
            return SimpleNamespace(delete=lambda: asyncio.sleep(0))

    async def answer(*args, **kwargs):
        return None

    query = SimpleNamespace(data="stage:KLP", message=Msg(), answer=answer)
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1), effective_chat=SimpleNamespace(id=1))
    asyncio.run(telegram_bot.stage_program_button(update, SimpleNamespace()))
    assert replies_sent[-1].startswith("❌ Couldn't read the portal: couldn't log in to the portal")


# --------------------------------------------------------------------------- /missing

def sheet_row(sid, name, program, status, mobile="8801711111111", **more):
    """A complete progress-sheet row (every REQUIRED field filled) with this Study Status."""
    r = {f: "x" for f in missing_report.REQUIRED}
    r.update({"Student ID": sid, "Full Name": name, "Program": program, "Study Status": status, "Mobile": mobile})
    r.update(more)
    return r


def portal_rec(sid, name, uni="", subject="", degree="", cgpa="", mobile="01711111111"):
    return {"Source": "Direct", "Student ID": sid, "Full Name": name, "Mobile": mobile, "Program": KLP,
            "Intake": "MARCH 2027", "Previous University": uni, "Subject": subject, "Degree": degree, "CGPA": cgpa}


def test_university_fields_of_klp_students_are_read_from_the_portal(export):
    export.rows = [portal_rec("HNG-2026-951", "SHIKDER MD FARHAN"),
                   portal_rec("HNG-2026-952", "DONE STUDENT", "DHAKA UNIVERSITY", "PHYSICS"),
                   portal_rec("HNG-2026-953", "GRADUATE", "DHAKA UNIVERSITY", "PHYSICS", "BSC", "")]
    data = {"KLP|MARCH 2027": [
        sheet_row("HNG-2026-951", "SHIKDER MD FARHAN", KLP, "CURRENTLY IN UNDERGRADUATE"),
        sheet_row("HNG-2026-952", "DONE STUDENT", KLP, "CURRENTLY IN UNDERGRADUATE"),
        sheet_row("HNG-2026-953", "GRADUATE", KLP, "UNDERGRADUATE COMPLETED"),
        sheet_row("HNG-2026-954", "HSC ONLY", KLP, "HSC PASSED"),
        sheet_row("HNG-2026-960", "NOT IN EXPORT", KLP, "CURRENTLY IN UNDERGRADUATE")]}
    text = missing_report.program_report("KLP", data=data)
    assert "University fields of KLP, EAP and Bachelor's students are read from the portal" in text
    assert "🗂 MARCH 2027 — 2 of 5 incomplete" in text
    assert "• HNG-2026-951 SHIKDER MD FARHAN — 2 missing: Previous University, Subject" in text
    assert "• HNG-2026-953 GRADUATE — 1 missing: CGPA" in text
    assert "DONE STUDENT" not in text and "HSC ONLY" not in text
    assert ("⚠️ University fields not checked for 1 student(s) (not found in the portal export): "
            "HNG-2026-960 NOT IN EXPORT") in text
    assert "Everyone complete" not in text


def test_a_program_with_every_row_complete_but_one_unchecked_is_not_called_complete(export):
    export.rows = []
    data = {"EAP|MARCH 2027": [sheet_row("HNG-2026-500", "NOT IN EXPORT", "EAP", "CURRENTLY IN UNDERGRADUATE")]}
    text = missing_report.program_report("EAP", data=data)
    assert "0 of 1 incomplete" in text and "Everyone complete" not in text
    assert "University fields not checked for 1 student(s)" in text


def test_masters_students_are_still_checked_on_their_own_sheet(export):
    export.rows = [portal_rec("HNG-2026-400", "MASTER STUDENT", "DHAKA UNIVERSITY", "PHYSICS", "BSC", "3.5")]
    rec_ = sheet_row("HNG-2026-400", "MASTER STUDENT", MASTER, "UNDERGRADUATE COMPLETED",
                     **{"Previous University": "", "Subject": "PHYSICS", "Degree": "BSC", "CGPA": "3.5"})
    index = missing_report.portal_index()
    assert missing_report.missing_fields(rec_, "MASTER", index) == ["Previous University"]   # the sheet's own blank
    assert missing_report.unchecked_fields(rec_, "MASTER", index) == []


def test_no_id_students_are_matched_by_name_and_mobile(export):
    export.rows = [portal_rec("", "NO ID YET", mobile="01799999999")]
    r = sheet_row("", "NO ID YET", KLP, "CURRENTLY IN UNDERGRADUATE", mobile="8801799999999")
    index = missing_report.portal_index()
    assert missing_report.missing_fields(r, "KLP", index) == ["Student ID", "Previous University", "Subject"]


def test_the_daily_report_counts_them_and_its_excel_file_is_only_captured(export, http, monkeypatch, tmp_path):
    export.rows = [portal_rec("HNG-2026-951", "SHIKDER MD FARHAN")]
    data = {"KLP|MARCH 2027": [sheet_row("HNG-2026-951", "SHIKDER MD FARHAN", KLP, "CURRENTLY IN UNDERGRADUATE")]}
    lines, rows = missing_report.build_report(data)
    assert "1 of 1 students have missing information." in lines[0]
    assert "   • HNG-2026-951 SHIKDER MD FARHAN — 2 missing: Previous University, Subject" in lines
    assert rows[0][5:] == (2, "Previous University, Subject")
    monkeypatch.setattr(missing_report, "REPORT_DIR", tmp_path)
    xlsx = missing_report.write_excel(rows)
    missing_report.send(lines + [f"line {i} " + "x" * 60 for i in range(100)], xlsx)
    texts = [p["data"]["text"] for p in http.posts if p["url"].endswith("/sendMessage")]
    docs = [p for p in http.posts if p["url"].endswith("/sendDocument")]
    assert len(texts) == 2 and all(replies.telegram_len(t) <= replies.CHUNK_CHARS for t in texts)
    assert len(docs) == 1 and docs[0]["url"].startswith("https://api.telegram.org/bot123:test/")   # the fake, not sent


def test_a_missing_report_that_cannot_read_says_so(monkeypatch, capsys):
    def broken():
        raise RuntimeError("Google login required")

    monkeypatch.setattr(missing_report, "read_sheets", broken)
    monkeypatch.setattr(sys, "argv", ["missing_report", "--program", "KLP"])
    missing_report.main()
    out = capsys.readouterr().out
    assert out.startswith("❌ Couldn't read the progress sheets or the portal: RuntimeError: Google login required")
    assert "not available right now" in out and "incomplete" not in out


# --------------------------------------------------------------------------- passport issue dates

def issue_page(uid, value):
    return f'<form><input type="date" name="passport_issue_date" value="{value}"></form>'


def test_issue_dates_skip_placeholder_passports_and_shared_numbers_that_disagree(portal, monkeypatch, tmp_path):
    monkeypatch.setattr(passport_issue, "CACHE_PATH", tmp_path / "passport_issue.json")
    rows = [with_details(row(1, 1, "HAS PASSPORT", hng="HNG-2026-905"), Passport_No="A01234567"),
            with_details(row(2, 2, "NO PASSPORT ONE", hng="HNG-2026-906"), Passport_No="PENDING"),
            with_details(row(3, 3, "NO PASSPORT TWO", hng="HNG-2026-907"), Passport_No="PENDING"),
            with_details(row(4, 4, "BLANK", hng="HNG-2026-908"), Passport_No=""),
            with_details(row(5, 5, "SHARED A", hng="HNG-2026-909"), Passport_No="B07654321"),
            with_details(row(6, 6, "SHARED B", hng="HNG-2026-006"), Passport_No="B07654321"),
            with_details(row(7, 7, "SAME DATE A", hng="HNG-2026-007"), Passport_No="C01111111"),
            with_details(row(8, 8, "SAME DATE B", hng="HNG-2026-008"), Passport_No="C01111111")]
    portal.pages["students.php"] = page(*rows)
    for uid, value in ((1, "2024-01-02"), (2, "PENDING"), (3, "2023-05-05"), (4, "2022-02-02"),
                       (5, "2021-01-01"), (6, "2021-09-09"), (7, "2020-03-03"), (8, "2020-03-03")):
        portal.pages[f"student_edit.php?id={uid}"] = issue_page(uid, value)
    out = asyncio.run(passport_issue._fetch_async())
    assert out == {"A01234567": "2024-01-02", "C01111111": "2020-03-03"}
    assert {m for m, _ in portal.asked} == {"GET"}
    assert not any("id=2" in k or "id=3" in k or "id=4" in k for _, k in portal.asked)


def test_a_refresh_that_cannot_log_in_keeps_the_last_cache(portal, monkeypatch, tmp_path):
    cache = tmp_path / "passport_issue.json"
    cache.write_text(json.dumps({"by_passport": {"A01234567": "2024-01-02"}}), encoding="utf-8")
    monkeypatch.setattr(passport_issue, "CACHE_PATH", cache)

    async def refused(*args, **kwargs):
        return {"success": False, "error": "the portal refused the login"}

    monkeypatch.setattr(admin_client, "is_authenticated", False)
    monkeypatch.setattr(admin_client, "login", refused)
    with pytest.raises(PortalUnavailable):
        passport_issue.refresh()
    assert json.loads(cache.read_text(encoding="utf-8")) == {"by_passport": {"A01234567": "2024-01-02"}}


def test_the_sheets_take_the_issue_date_from_the_export_first(monkeypatch):
    monkeypatch.setattr(pb, "_ISSUE_CACHE", {"PENDING": "PENDING", "A01234567": "2024-01-02"})
    assert pb.issue_date_for({"Passport No": "PENDING", "Passport Issue Date": ""}) == ""
    assert pb.issue_date_for({"Passport No": "A01234567", "Passport Issue Date": "2024-01-03"}) == "2024-01-03"
    assert pb.issue_date_for({"Passport No": "A01234567"}) == "2024-01-02"     # an export without the column
    assert pb.issue_date_for({"Passport No": "PENDING"}) == ""                 # never another student's value
