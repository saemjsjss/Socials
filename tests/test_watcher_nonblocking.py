"""Tests that the 30-minute passport watcher no longer freezes the bot.

The watcher (src/bot/scheduler.py) audits every student's passport scan with EasyOCR on the
CPU. That OCR used to run synchronously inside the bot's asyncio event loop, so for ~3.5
minutes every half hour no Telegram update (Jennie's voice notes included) was handled. The
audit now hands the OCR/MRZ/image work to a worker thread (src/scraper/client.py,
asyncio.to_thread) while the portal GETs stay async. These tests prove that the loop keeps
ticking while an audit grinds, that the result is exactly what the old synchronous call
returned, that the shared EasyOCR reader is loaded once and never used by two threads at
once, that a new scan two audits fetch together is saved once and whole, and that the
watcher still sends the same alerts, keeps the same cache and stays read-only on the portal.

Nothing here touches the network, the real EasyOCR model, Telegram or the production
folders: the portal is a fake that records every request, the OCR reader is a stub that
burns CPU like the real one, and the passports folder and the alert cache live in tmp_path.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_watcher_nonblocking.py -q
"""
import asyncio
import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

from src.config import settings  # noqa: E402
from src.bot import scheduler  # noqa: E402
from src.scraper import client as client_mod  # noqa: E402
from src.scraper import ocr_validator as ocr  # noqa: E402
from src.scraper.client import admin_client  # noqa: E402

BASE = "https://portal.test/admin"
ADMIN_ID = "111111111"
MAX_GAP_S = 0.5     # the loop must never go quieter than this while an audit runs
BURN_S = 0.4        # CPU seconds each fake readtext() burns in the timing tests
PAGE_H, PAGE_W = 400, 300
RESULT_KEYS = {"student_id", "status", "is_valid", "fields", "mrz_data", "visual_data",
               "discrepancies", "verdict"}


# --------------------------------------------------------------------------- fake students

def mrz_lines(surname, given, passport_no, dob, expiry, sex="M"):
    """The two ICAO 9303 MRZ lines of a passport, with real check digits."""
    def yymmdd(d):
        return d[2:4] + d[5:7] + d[8:10]
    cd = ocr.compute_icao_check_digit
    b, e = yymmdd(dob), yymmdd(expiry)
    line1 = f"P<BGD{surname}<<{given.replace(' ', '<')}".ljust(44, "<")
    line2 = f"{passport_no}{cd(passport_no)}BGD{b}{cd(b)}{sex}{e}{cd(e)}".ljust(44, "<")
    return [line1, line2]


# Invented people. marker = the pixel value that tells the fake reader which scan it sees.
STUDENTS = {
    "9001": {   # everything matches -> no alert
        "doc": "passport_9001_1700000001.png", "marker": 11,
        "profile": {"name": "KARIM HASAN", "dob": "2004-03-10", "passport_no": "A00012345",
                    "passport_expiry": "2034-12-04", "father_name": "ABDUL HASAN",
                    "mother_name": "SALMA BEGUM", "address": "NOYAPARA, SADAR",
                    "district": "SYLHET"},
        "mrz": mrz_lines("HASAN", "KARIM", "A00012345", "2004-03-10", "2034-12-04"),
        "visual": ["PEOPLE'S REPUBLIC OF BANGLADESH", "Father's Name: ABDUL HASAN",
                   "Mother's Name: SALMA BEGUM", "Permanent Address: NOYAPARA, SADAR",
                   "SYLHET"],
    },
    "9002": {   # portal DOB is one day off the MRZ -> DISCREPANCY alert
        "doc": "passport_9002_1700000002.png", "marker": 22,
        "profile": {"name": "NADIA ISLAM", "dob": "2005-05-12", "passport_no": "A00067890",
                    "passport_expiry": "2035-10-03", "father_name": "RAFIQUL ISLAM",
                    "mother_name": "NASRIN AKTER", "address": "KAZIR DEWRI, KOTWALI",
                    "district": "CHATTOGRAM"},
        "mrz": mrz_lines("ISLAM", "NADIA", "A00067890", "2005-05-11", "2035-10-03", "F"),
        "visual": ["PEOPLE'S REPUBLIC OF BANGLADESH", "Father's Name: RAFIQUL ISLAM",
                   "Mother's Name: NASRIN AKTER", "Permanent Address: KAZIR DEWRI, KOTWALI",
                   "CHATTOGRAM"],
    },
    "9003": {   # an admission flyer uploaded as the passport -> INVALID_DOCUMENT alert
        "doc": "passport_9003_1700000003.png", "marker": 33,
        "profile": {"name": "TAMIM AZAD", "dob": "2003-01-01", "passport_no": "A00055555",
                    "passport_expiry": "2033-01-01"},
        "mrz": ["ADMISSION OPEN", "SPRING INTAKE 2027"],
        "visual": ["STUDY IN KOREA"],
    },
    "9004": {   # no passport uploaded at all -> MISSING_DOCUMENT, never alerted by the watcher
        "doc": None, "marker": None,
        "profile": {"name": "RUMA AKTER", "dob": "2006-06-06"},
    },
}
MARKERS = {s["marker"]: s for s in STUDENTS.values() if s["marker"]}
DOCS = {s["doc"]: s["marker"] for s in STUDENTS.values() if s["doc"]}


def row_form(sid):
    """form_data the way the watcher builds it from the students.php row."""
    p = STUDENTS[sid]["profile"]
    return {"name": p.get("name", ""), "dob": p.get("dob", ""),
            "passport_no": p.get("passport_no", ""),
            "passport_expiry": p.get("passport_expiry", "")}


def students_page():
    rows = ["<tr><th>Student</th><th>Docs</th></tr>"]
    for sid, s in STUDENTS.items():
        p = s["profile"]
        text = (f"Full Name {p['name']} DOB {p.get('dob', '')} "
                f"Passport No {p.get('passport_no', '')} "
                f"Passport Expiry {p.get('passport_expiry', '')}")
        links = f'<a href="student_edit.php?id={sid}">Edit</a>'
        if s["doc"]:
            links = f'<a href="view_doc.php?f={s["doc"]}">Passport</a> ' + links
        rows.append(f"<tr><td>{text}</td><td>{links}</td></tr>")
    return "<html><body><table>" + "".join(rows) + "</table></body></html>"


def edit_page(sid):
    inputs = "".join(f'<input name="{k}" value="{v}">'
                     for k, v in STUDENTS[sid]["profile"].items())
    return f"<html><body><form>{inputs}</form></body></html>"


def scan_png(marker):
    """A noisy page (well over the 1000-byte minimum); column 0 carries the marker, so every
    crop the OCR code cuts from it still says which scan it came from."""
    rng = np.random.default_rng(marker)
    img = rng.integers(0, 256, size=(PAGE_H, PAGE_W, 3), dtype=np.uint8)
    img[:, 0, :] = marker
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


# --------------------------------------------------------------------------- fakes

def burn(seconds):
    """Busy CPU work in pure Python: holds the GIL the way EasyOCR's Python parts do."""
    end = time.perf_counter() + seconds
    n = 0
    while time.perf_counter() < end:
        n += 1
    return n


class BurningReader:
    """Stands in for easyocr.Reader: burns CPU, then 'reads' the fake scan it was given.
    Records which threads called readtext() and how many were inside it at once."""

    def __init__(self, burn_s=BURN_S):
        self.burn_s = burn_s
        self.calls = 0
        self.inside = 0
        self.max_inside = 0
        self.threads = set()
        self._count = threading.Lock()

    def readtext(self, img, detail=0):
        assert detail == 0
        with self._count:
            self.calls += 1
            self.inside += 1
            self.max_inside = max(self.max_inside, self.inside)
            self.threads.add(threading.get_ident())
        try:
            burn(self.burn_s)
            scan = MARKERS[int(img[0, 0, 0])]
            # The MRZ crop is the bottom 30 % of the page, the visual crop the top 65 %.
            return list(scan["mrz"] if img.shape[0] < PAGE_H // 2 else scan["visual"])
        finally:
            with self._count:
                self.inside -= 1


class FakePortal:
    """The admin portal as the httpx.AsyncClient the client uses. Records every request."""

    def __init__(self):
        self.requests = []

    async def get(self, url, **kwargs):
        self.requests.append(("GET", url))
        await asyncio.sleep(0.005)   # a real round trip gives the loop back
        text, content, status = "", b"", 404
        if url == f"{BASE}/students.php":
            text, status = students_page(), 200
        elif url.startswith(f"{BASE}/student_edit.php?id="):
            sid = url.split("id=", 1)[1]
            if sid in STUDENTS:
                text, status = edit_page(sid), 200
        elif url.startswith(f"{BASE}/view_doc.php?f="):
            fn = url.split("f=", 1)[1]
            if fn in DOCS:
                content, status = scan_png(DOCS[fn]), 200
        if text:
            content = text.encode()
        return SimpleNamespace(status_code=status, url=url, text=text, content=content)

    async def post(self, url, **kwargs):   # the watcher must never write to the portal
        self.requests.append(("POST", url))
        raise AssertionError(f"POST to the read-only portal: {url}")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})


@pytest.fixture
def env(monkeypatch, tmp_path):
    reader = BurningReader()
    portal = FakePortal()
    bot = FakeBot()
    monkeypatch.setattr(ocr, "get_ocr_reader", lambda: reader)
    monkeypatch.setattr(client_mod, "BOT_ROOT", tmp_path)          # passports -> tmp_path
    monkeypatch.setattr(admin_client, "client", portal)
    monkeypatch.setattr(admin_client, "base_url", BASE)
    monkeypatch.setattr(admin_client, "is_authenticated", True)     # never log in
    monkeypatch.setattr(admin_client, "_profile_cache", {}, raising=False)
    monkeypatch.setattr(scheduler, "ALERTED_CACHE_FILE",
                        str(tmp_path / "data" / "alerted_passport_issues.json"))
    monkeypatch.setattr(settings, "TELEGRAM_ADMIN_CHAT_ID", ADMIN_ID)
    return SimpleNamespace(reader=reader, portal=portal, bot=bot,
                           app=SimpleNamespace(bot=bot), tmp=tmp_path)


async def with_ticker(coro, every=0.01):
    """Await coro while a second coroutine tries to tick every 10 ms, the way the bot's
    other handlers (a voice note, a typed question) wait for their turn on the loop.
    Returns (result, gaps between ticks in seconds, seconds the coro took)."""
    gaps = []
    done = asyncio.Event()

    async def ticker():
        last = time.perf_counter()
        while not done.is_set():
            await asyncio.sleep(every)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0)          # let the ticker start before the audit does
    t0 = time.perf_counter()
    try:
        result = await coro
    finally:
        took = time.perf_counter() - t0
        done.set()
        await task
    return result, gaps, took


# --------------------------------------------------------------------------- one audit

def test_audit_keeps_the_event_loop_running(env):
    main = threading.get_ident()
    result, gaps, took = asyncio.run(with_ticker(
        admin_client.audit_student_passport("9001", row_form("9001"), STUDENTS["9001"]["doc"])))

    assert result["status"] == "MATCH" and result["is_valid"] is True
    assert env.reader.calls == 2                       # MRZ + visual zone
    assert took >= 2 * BURN_S                          # it really did the CPU work...
    assert max(gaps) < MAX_GAP_S, f"loop froze for {max(gaps):.2f} s"
    assert len(gaps) >= 20                             # ...while the loop kept ticking
    assert main not in env.reader.threads              # the OCR ran on a worker thread


def test_control_the_same_audit_run_on_the_loop_freezes_it(env):
    """The old behaviour, reproduced: the same OCR called straight from a coroutine.
    Proves the ticker in the test above would have seen the freeze."""
    sid = "9001"
    asyncio.run(admin_client.audit_student_passport(sid, row_form(sid), STUDENTS[sid]["doc"]))
    local = os.path.join(env.tmp, "passports", f"{sid}_{STUDENTS[sid]['doc']}")

    async def old_way():
        return ocr.validate_passport_data(sid, row_form(sid), local, live_audit=True)

    _, gaps, _ = asyncio.run(with_ticker(old_way()))
    assert max(gaps) >= 2 * BURN_S * 0.9


@pytest.mark.parametrize("sid, status", [
    ("9001", "MATCH"),
    ("9002", "DISCREPANCY"),
    ("9003", "INVALID_DOCUMENT"),
    ("9004", "MISSING_DOCUMENT"),
])
def test_audit_result_is_what_the_synchronous_call_returned(env, sid, status):
    env.reader.burn_s = 0.02
    form = row_form(sid)
    doc = STUDENTS[sid]["doc"]
    new = asyncio.run(admin_client.audit_student_passport(sid, form, doc))

    # The old code called validate_passport_data right there on the loop, with the form the
    # audit had just merged the live profile into and the scan it had just saved.
    local = os.path.join(env.tmp, "passports", f"{sid}_{doc}") if doc else None
    if local:
        assert os.path.getsize(local) > 1000
    old = ocr.validate_passport_data(sid, dict(form), local, live_audit=True)

    assert new == old
    assert set(new) == RESULT_KEYS
    assert new["student_id"] == sid and new["status"] == status
    if status == "MATCH":
        assert new["is_valid"] and not new["discrepancies"]
        assert {f["status"] for f in new["fields"].values()} == {"MATCH"}
    else:
        assert not new["is_valid"] and new["discrepancies"]
    if sid == "9002":
        assert new["fields"]["dob"]["status"] == "MISMATCH"
        assert any("DOB mismatch" in d for d in new["discrepancies"])


def test_concurrent_audits_never_share_the_ocr_reader(env):
    """A /crosscheck while the watcher runs: both audits go to worker threads, and the lock
    keeps them from using the one EasyOCR reader at the same time."""
    env.reader.burn_s = 0.2
    sids = ["9001", "9002", "9003"]

    async def together():
        return await asyncio.gather(*(
            admin_client.audit_student_passport(s, row_form(s), STUDENTS[s]["doc"]) for s in sids))

    results, gaps, _ = asyncio.run(with_ticker(together()))
    assert [r["status"] for r in results] == ["MATCH", "DISCREPANCY", "INVALID_DOCUMENT"]
    assert env.reader.calls == 5
    assert env.reader.max_inside == 1
    assert max(gaps) < MAX_GAP_S


def test_two_audits_of_a_new_upload_save_the_scan_once(env, monkeypatch):
    """The watcher and a /crosscheck (or a voice note routed to it) reach the same new upload
    together. Both find no scan on disk and both fetch it, but only the first saves it, under a
    temporary name that is then renamed: the second never truncates and rewrites a scan an OCR
    thread may be reading, and no thread ever finds half a scan."""
    env.reader.burn_s = 0.05
    sid, doc = "9002", STUDENTS["9002"]["doc"]
    passports = os.path.join(env.tmp, "passports")
    opened = []
    real_open = open

    def spy_open(file, mode="r", *args, **kwargs):
        opened.append((os.path.basename(file), mode))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(client_mod, "open", spy_open, raising=False)

    async def together():
        return await asyncio.gather(*(
            admin_client.audit_student_passport(sid, row_form(sid), doc) for _ in range(2)))

    results, gaps, _ = asyncio.run(with_ticker(together()))

    downloads = [url for _, url in env.portal.requests if "view_doc.php" in url]
    assert len(downloads) == 2                      # both audits found no scan and fetched it...
    writes = [name for name, mode in opened if "w" in mode]
    assert writes == [f".{sid}_{doc}.part"]         # ...but it was saved once, never in place
    assert sorted(os.listdir(passports)) == [f"{sid}_{doc}"]      # no .part left behind
    with real_open(os.path.join(passports, f"{sid}_{doc}"), "rb") as f:
        assert f.read() == scan_png(STUDENTS[sid]["marker"])
    assert [r["status"] for r in results] == ["DISCREPANCY", "DISCREPANCY"]
    assert results[0] == results[1]
    assert max(gaps) < MAX_GAP_S


def test_easyocr_reader_is_loaded_once_even_when_threads_race(monkeypatch):
    built = []

    class SlowReader:
        def __init__(self, langs, gpu=True, verbose=True):
            built.append({"langs": langs, "gpu": gpu})
            time.sleep(0.2)          # the real model takes ~1.5 s to load

    monkeypatch.setitem(sys.modules, "easyocr", SimpleNamespace(Reader=SlowReader))
    monkeypatch.setattr(ocr, "_reader", None)
    with ThreadPoolExecutor(4) as pool:
        readers = list(pool.map(lambda _: ocr.get_ocr_reader(), range(4)))

    assert built == [{"langs": ["en"], "gpu": False}]      # once, and still on the CPU
    assert all(r is readers[0] for r in readers)


# --------------------------------------------------------------------------- the watcher

def run_watcher(env):
    """One watcher cycle, exactly as APScheduler runs it, with a ticker alongside."""
    env.bot.sent.clear()
    env.portal.requests.clear()
    env.reader.threads.clear()
    _, gaps, took = asyncio.run(with_ticker(scheduler.check_new_passport_uploads(env.app)))
    with open(scheduler.ALERTED_CACHE_FILE, encoding="utf-8") as f:
        alerted = set(json.load(f))
    return SimpleNamespace(sent=list(env.bot.sent), requests=list(env.portal.requests),
                           alerted=alerted, gaps=gaps, took=took,
                           threads=set(env.reader.threads))


def test_watcher_sends_the_same_alerts_without_freezing_the_loop(env, monkeypatch):
    main = threading.get_ident()
    new = run_watcher(env)

    assert max(new.gaps) < MAX_GAP_S, f"loop froze for {max(new.gaps):.2f} s"
    assert new.took >= 5 * BURN_S                  # 9001 and 9002: 2 reads each, 9003: 1
    assert main not in new.threads
    assert new.alerted == {"9002", "9003"}
    assert [m["chat_id"] for m in new.sent] == [ADMIN_ID, ADMIN_ID]
    assert "`ID 9002`" in new.sent[0]["text"] and "DOB mismatch" in new.sent[0]["text"]
    assert "`DISCREPANCY`" in new.sent[0]["text"]
    assert "`ID 9003`" in new.sent[1]["text"] and "`INVALID_DOCUMENT`" in new.sent[1]["text"]
    assert all(m["parse_mode"] == "Markdown" for m in new.sent)
    assert {method for method, _ in new.requests} == {"GET"}      # read-only portal
    assert all(url.startswith(BASE) for _, url in new.requests)

    # The old behaviour, for comparison: the same cycle with the OCR run inline on the loop.
    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    os.remove(scheduler.ALERTED_CACHE_FILE)
    shutil.rmtree(os.path.join(env.tmp, "passports"))
    admin_client._profile_cache.clear()
    with monkeypatch.context() as m:
        m.setattr(client_mod.asyncio, "to_thread", inline)
        old = run_watcher(env)

    assert max(old.gaps) >= 2 * BURN_S * 0.9       # the freeze the owner saw in the logs
    assert old.threads == {main}
    assert new.sent == old.sent                    # same alerts, same words
    assert new.alerted == old.alerted              # same cache
    assert new.requests == old.requests            # same portal GETs, same order

    # Next cycle: the cache still stops repeat alerts; only the clean student is re-audited.
    again = run_watcher(env)
    assert again.sent == []
    assert again.alerted == {"9002", "9003"}
    assert max(again.gaps) < MAX_GAP_S
