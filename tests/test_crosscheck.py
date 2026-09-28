"""The passport cross-check commands and the OCR verdicts they print.

  /crosscheck, /audit, /crosscheck_today, /crosscheck_date, /crosscheck_range, /crosscheck_between,
  /crosscheck_period: students picked by their own "Payment verified by NAME · 27 Sep, 17:19"
  stamp from every page of students.php (never the transfer-intake options' "2027 SEPTEMBER" or
  the "Applied On" date), a portal ID, an HNG ID or a name (month words only as whole words, so
  "Kumar" is a name), each passport scan checked by OCR, the report split between students' cards.
  /passports, /passport_audit: live counts and today's live checks, never the 10 Sep registry.
  src/scraper/ocr_validator.py: every turn of the page tried before "couldn't read the MRZ", MRZ
  line lengths and check digits before any field is trusted, "possible OCR misread, check by eye"
  instead of a confirmed discrepancy on a doubtful read, and verdicts that name what was not found.
  src/scraper/client.py audit_student_passport: the profile and the scan read through the one
  session path, never an old saved scan in place of the portal's.

Every portal page is synthetic (tests/test_foundation.py's builders, invented names); the OCR
engine is a stub that reads marked test images; nothing reaches the network or Telegram.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_crosscheck.py -q
"""
import asyncio
import os
import re
import sys
from datetime import date
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

from src.bot import replies, telegram_bot  # noqa: E402
from src.scraper import client as client_module, ocr_validator as ocr  # noqa: E402
from src.scraper.client import admin_client  # noqa: E402
from test_foundation import (  # noqa: E402,F401  (portal is a fixture)
    BACHELOR, always_login, page, portal, report_of, row, run, student_reads, verified,
)


# --------------------------------------------------------------------------- the student list

def with_details(html_row: str, **items) -> str:
    """A row() with more details-row fields ("Passport No", "Passport Status"...)."""
    extra = "".join(f'<div class="det-item"><label>{k.replace("_", " ")}</label><span>{v}</span></div>'
                    for k, v in items.items())
    return html_row.replace('<div class="det">', f'<div class="det">{extra}', 1)


def without_scan(html_row: str, uid: int) -> str:
    return html_row.replace(f'<a href="view_doc.php?f=passport_{uid}_1700000000.jpeg">Passport</a>', "")


def the_list():
    """Page 1 (newest applications) and page 2. Every row carries the transfer-intake select whose
    options read "... JUNE 2027 SEPTEMBER 2027": the old '27 sep' substring test matched them all."""
    return {
        "students.php": page(
            with_details(verified(917, 1, "RAHIM UDDIN", "27 Sep, 17:19", applied="27 Sep 2026"),
                         Passport_No="A00012345", Passport_Expiry="2034-12-04"),
            verified(916, 2, "NUSRAT JAHAN", "27 Sep, 17:06", amount="8,000.00 BDT", method="bKash",
                     by="NOSHIN SAMAD", program=BACHELOR, applied="27 Sep 2026"),
            verified(915, 3, "GHOSH ANUP KUMAR", "26 Sep, 12:00", applied="20 Sep 2026"),
            verified(914, 4, "JANE RAHMAN", "16 Sep, 09:51", applied="15 Sep 2026"),
            verified(913, 5, "EIGHTEENTH STUDENT", "18 Sep, 11:00", applied="18 Sep 2026"),
            with_details(without_scan(row(969, 6, "PENDING TAHIRA", pay="Pending", stage="Application Received",
                                          applied="28 Sep 2026"), 969), Passport_Status="NO — WILL APPLY"),
            pg=1, pages=2, total=10),
        "students.php?pg=2": page(
            verified(432, 7, "DEB BIKASH TEST", "10 Sep, 10:00", applied="1 Sep 2026"),
            verified(431, 8, "HABIB FAHMID TEST", "10 Sep, 11:00", applied="1 Sep 2026"),
            row(447, 9, "KHANOM TAHIRA TEST", hng="HNG-2026-947", by="MAHIRA JANAN", when="12 Sep, 10:00", paid="20,000.00 BDT", method="Cash", income="20,000.00 BDT", applied="1 Sep 2026"),
            verified(112, 10, "PATRA KUMAR TEST", "08 Sep, 09:00", applied="1 Sep 2026"),
            pg=2, pages=2, total=10),
    }


VERDICT = "✅ Match: Name, DOB, Passport No, Expiry · ℹ️ Not on the scan: Father, Mother, Address"


@pytest.fixture
def audits(monkeypatch):
    """audit_student_passport as a recorder (no OCR, no portal): the students it was asked to check."""
    calls = []

    async def audit(student_id, form_data, doc_filename=None, force_live=True):
        calls.append((student_id, dict(form_data), doc_filename))
        return {"student_id": student_id, "status": "MATCH", "is_valid": True, "discrepancies": [], "uncertain": [],
                "fields": {"father_name": {"doc": "", "status": "NOT_IN_SCAN", "verdict": "Not visible on scan"}},
                "verdict": VERDICT}
    monkeypatch.setattr(admin_client, "audit_student_passport", audit)
    return calls


def checked(calls):
    return [c[0] for c in calls]


# --------------------------------------------------------------------------- what is asked for

@pytest.mark.parametrize("text, expect", [
    ("/crosscheck", ("date", date(2026, 9, 28))), ("today", ("date", date(2026, 9, 28))),
    ("/crosscheck 27 Sep 2026", ("date", date(2026, 9, 27))), ("yesterday", ("date", date(2026, 9, 27))),
    ("Crosscheck 12 Sep 2026", ("date", date(2026, 9, 12))), ("2026-09-14", ("date", date(2026, 9, 14))),
    ("527", ("uid", "527")), ("#432", ("uid", "432")), ("student 412", ("uid", "412")), ("id: 527", ("uid", "527")),
    ("cross check father name of 527", ("uid", "527")), ("HNG-2026-931", ("hng", "HNG-2026-931")),
    ("Kumar", ("name", "Kumar")), ("Junaira", ("name", "Junaira")), ("Jane", ("name", "Jane")),
    ("/audit Fahmid", ("name", "Fahmid")), ("crosscheck student Tahira please", ("name", "Tahira")),
])
def test_what_a_crosscheck_asks_for(portal, text, expect):
    q = telegram_bot._crosscheck_query(text)
    assert (q["kind"], q.get("day") or q.get("uid") or q.get("hng") or q.get("name")) == expect


@pytest.mark.parametrize("text, date_only, why", [
    ("31 Sep", False, "September has 30 days"), ("/crosscheck 31 Sep 2026", False, "September 2026 has 30 days"),
    ("in sep", False, "it names a month but no day of it"), ("Kumar", True, "there is no date in it"),
    ("29 Feb 2026", True, "February 2026 has 28 days"),
])
def test_a_date_that_cannot_be_read_is_an_error_never_today(portal, audits, text, date_only, why):
    q = telegram_bot._crosscheck_query(text, date_only=date_only)
    assert q["kind"] == "error" and "couldn't read" in q["reply"] and why in q["reply"]
    handler = telegram_bot.crosscheck_date_command if date_only else telegram_bot.crosscheck_command
    chat, _ = run(handler, text, text.split())
    assert len(chat) == 1 and "couldn't read" in chat[0].text and why in chat[0].text
    assert portal.asked == [] and audits == []                       # nothing read, nothing checked


# --------------------------------------------------------------------------- picked by the stamp, every page

def test_a_day_is_picked_by_the_verification_stamp_only(portal, audits):
    portal.pages.update(the_list())
    chat, _ = run(telegram_bot.crosscheck_date_command, "/crosscheck_date 27 Sep 2026", ["27", "Sep", "2026"])
    text = report_of(chat)
    # Every row has "2027 SEPTEMBER" in its intake select: the old substring test took all of them.
    assert checked(audits) == ["917", "916"]
    assert "Cross-Check — 27 September 2026*" in text and "Total Records Audited:* `2`" in text
    assert "MAHIRA JANAN (27 Sep, 17:19)" in text and "NOSHIN SAMAD (27 Sep, 17:06)" in text
    assert " E)" not in text and "17:19 E" not in text                         # no stray 'E' of "Edit Info"
    assert student_reads(portal.asked) == ["students.php", "students.php?pg=2"]
    assert all(method == "GET" for method, _ in portal.asked)
    assert "Read live from all 10 students on students.php" in text
    assert len(chat) == 1 and chat[0].edits == 2                               # "⏳" -> progress -> report


def test_the_card_shows_the_portals_own_values(portal, audits):
    portal.pages.update(the_list())
    text = report_of(run(telegram_bot.crosscheck_command, "/crosscheck 917", ["917"])[0])
    assert "*1. RAHIM UDDIN* (ID: `917` · `HNG-2026-917`)" in text
    assert "*Payment:* `20,000.00 BDT Cash`" in text
    assert "Pass `A00012345` | Exp `2034-12-04` | DOB `2000-01-01`" in text
    assert f"*Audit Verdict:* {VERDICT}" in text
    assert audits[0][1] == {"name": "RAHIM UDDIN", "dob": "2000-01-01", "passport_no": "A00012345",
                            "passport_expiry": "2034-12-04"}
    assert audits[0][2] == "passport_917_1700000000.jpeg"


@pytest.mark.parametrize("args, uids", [
    ("10 Sep 2026", ["432", "431"]),             # page 2: the old page-1 read said "none"
    ("8 Sep", ["112"]),                          # never "18 Sep" or "28 Sep"
    ("12 Sep", ["447"]),
    ("28 Sep 2026", []),
])
def test_every_page_is_read_and_days_match_on_whole_tokens(portal, audits, args, uids):
    portal.pages.update(the_list())
    chat, _ = run(telegram_bot.crosscheck_command, f"/crosscheck {args}", args.split())
    assert checked(audits) == uids
    if not uids:
        assert "No payment-verified students found for 28 September 2026" in report_of(chat)
        assert "All 10 students on students.php were read live" in report_of(chat)


def test_crosscheck_today_says_none_only_after_reading_every_page(portal, audits):
    portal.pages.update(the_list())
    chat, _ = run(telegram_bot.crosscheck_today_command, "/crosscheck_today", [])
    assert "No payment-verified students found for 28 September 2026" in report_of(chat)
    assert student_reads(portal.asked) == ["students.php", "students.php?pg=2"] and audits == []


@pytest.mark.parametrize("handler, text, uids, header", [
    ("crosscheck_range_command", "26 Sep 2026 to 27 Sep 2026", ["915", "916", "917"], "26 Sep 2026 → 27 Sep 2026"),
    ("crosscheck_period_command", "2026-09-14 to 2026-09-15", [], None),         # 914 applied 15 Sep, verified 16 Sep
    ("crosscheck_range_command", "15 Sep 2026 to 16 Sep 2026", ["914"], "15 Sep 2026 → 16 Sep 2026"),
    ("crosscheck_between_command", "10 Sep 2026 to 12 Sep 2026", ["432", "431", "447"], None),
])
def test_a_range_is_picked_by_the_stamp_in_day_and_time_order(portal, audits, handler, text, uids, header):
    portal.pages.update(the_list())
    chat, _ = run(telegram_bot.crosscheck_range_command, f"/{handler} {text}", text.split())
    report = report_of(chat)
    assert checked(audits) == uids
    if header:
        assert f"Cross-Check — {header}*" in report
    if not uids:
        assert "No payment-verified students found between 14 Sep 2026 → 15 Sep 2026" in report


def test_a_range_says_what_it_cannot_answer(portal, audits):
    portal.pages.update(the_list())
    chat, _ = run(telegram_bot.crosscheck_range_command, "/crosscheck_range 31 Sep 2026 to 5 Oct 2026",
                  "31 Sep 2026 to 5 Oct 2026".split())
    assert "couldn't read two dates there (31 Sep 2026: September 2026 has 30 days)" in chat[0].text
    chat, _ = run(telegram_bot.crosscheck_range_command, "/crosscheck_range 27 Sep 2025 to 5 Oct 2025",
                  "27 Sep 2025 to 5 Oct 2025".split())
    assert "not available" in chat[0].text and "cannot be told apart from 27 Sep 2026" in chat[0].text
    assert portal.asked == [] and audits == []
    # An end after today stops at today (the stamps have no year: a later day is last year's).
    chat, _ = run(telegram_bot.crosscheck_range_command, "/crosscheck_range 27 Sep 2026 to 30 Sep 2026",
                  "27 Sep 2026 to 30 Sep 2026".split())
    assert "27 Sep 2026 → 28 Sep 2026 (today)" in report_of(chat) and checked(audits) == ["916", "917"]


def test_a_day_a_year_back_is_not_available(portal, audits):
    portal.pages.update(the_list())
    chat, _ = run(telegram_bot.crosscheck_date_command, "/crosscheck_date 27 Sep 2025", ["27", "Sep", "2025"])
    assert "not available" in chat[0].text and "cannot be told apart from 27 Sep 2026" in chat[0].text
    assert portal.asked == [] and audits == []


# --------------------------------------------------------------------------- IDs and names

@pytest.mark.parametrize("args, uids", [
    ("432", ["432"]), ("student 431", ["431"]), ("HNG-2026-947", ["447"]),
    ("Kumar", ["915", "112"]),                   # "kumar" has "mar" in it: still a name, on both pages
    ("Tahira", ["969", "447"]), ("Fahmid", ["431"]), ("Jane", ["914"]),
])
def test_ids_and_names_are_found_on_every_page(portal, audits, args, uids):
    portal.pages.update(the_list())
    chat, _ = run(telegram_bot.crosscheck_command, f"/audit {args}", args.split())
    assert checked(audits) == [u for u in uids if u != "969"]      # 969 has no scan: nothing to check
    text = report_of(chat)
    assert f"Total Records Audited:* `{len(uids)}`" in text
    if "969" in uids:
        assert "— (no payment verification on the portal)" in text
        assert "⏳ None uploaded (Passport Status: NO — WILL APPLY)" in text
        assert "Pending Passport Scan (no scan uploaded on the portal)" in text


def test_no_match_says_every_student_was_read(portal, audits):
    portal.pages.update(the_list())
    text = report_of(run(telegram_bot.crosscheck_command, "/crosscheck 9999", ["9999"])[0])
    assert "No student found matching ID `9999`* (all 10 students on students.php were read live)" in text
    text = report_of(run(telegram_bot.crosscheck_command, "/crosscheck Zzzqqq", ["Zzzqqq"])[0])
    assert "No student found matching Name `Zzzqqq`*" in text and audits == []


def test_a_name_many_students_share_checks_the_first_ten_and_lists_the_rest(portal, audits):
    rows = [verified(100 + i, i, f"RAHMAN STUDENT {i:02d}", "20 Sep, 10:00", applied="1 Sep 2026") for i in range(1, 14)]
    portal.pages["students.php"] = page(*rows)
    text = report_of(run(telegram_bot.crosscheck_command, "/crosscheck Rahman", ["Rahman"])[0])
    assert len(audits) == telegram_bot.CROSSCHECK_NAME_MAX == 10
    assert "13 students match; the first 10 are checked below" in text
    assert "RAHMAN STUDENT 13 (`113`)" in text


# --------------------------------------------------------------------------- the portal and long replies

def test_an_expired_session_is_renewed_not_read_as_no_students(portal, audits, monkeypatch):
    portal.pages.update(the_list())
    expired, logins = {"n": 1}, []

    def handler(request):
        key = request.url.path.rsplit("/", 1)[-1] + (f"?{request.url.query.decode()}" if request.url.query else "")
        assert request.method == "GET"
        if request.url.path.endswith("login.php"):
            return httpx.Response(200, text="<form><input name='_csrf' value='t'></form>")
        if expired["n"]:
            expired["n"] -= 1
            return httpx.Response(302, headers={"Location": "https://hangeul.com.bd/admin/login.php"})
        return httpx.Response(200, text=portal.pages[key])

    async def login(*args, **kwargs):
        logins.append(True)
        admin_client.is_authenticated = True
        return {"success": True}
    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                                                   follow_redirects=True))
    monkeypatch.setattr(admin_client, "login", login)
    text = report_of(run(telegram_bot.crosscheck_command, "/crosscheck 527", ["917"])[0])
    assert len(logins) == 1 and checked(audits) == ["917"] and "RAHIM UDDIN" in text


@pytest.mark.parametrize("failure, reason", [
    ("refused", "couldn't log in to the portal: simulated bad credentials"),
    ("login page", "kept sending its login page"),
    ("no stamps", "no 'Payment verified by' line"),
])
def test_a_failed_read_is_said_never_none_found(portal, audits, monkeypatch, failure, reason):
    if failure == "refused":
        async def refused(*args, **kwargs):
            return {"success": False, "error": "simulated bad credentials"}
        monkeypatch.setattr(admin_client, "is_authenticated", False)
        monkeypatch.setattr(admin_client, "login", refused)
    elif failure == "login page":
        async def fresh(*args, **kwargs):
            admin_client.is_authenticated = True
            return {"success": True}
        monkeypatch.setattr(admin_client, "login", fresh)
        monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(always_login),
                                                                       follow_redirects=True))
    else:
        portal.pages["students.php"] = page(row(1, 1, "A"), row(2, 2, "B"))
    for handler, args in ((telegram_bot.crosscheck_today_command, []), (telegram_bot.crosscheck_command, ["527"]),
                          (telegram_bot.crosscheck_range_command, "26 Sep 2026 to 27 Sep 2026".split())):
        if failure == "no stamps" and args == ["527"]:
            continue                                  # an ID needs no stamps
        text = report_of(run(handler, "/x", args)[0])
        assert text.startswith("❌ Couldn't read the portal:") and reason in text
        assert "No payment-verified" not in text and "No student found" not in text
    assert audits == []


def test_a_long_report_is_split_between_students_cards(portal, audits, monkeypatch):
    rows = [verified(2000 + i, i, f"STUDENT NUMBER {i:02d} WITH A LONG FULL NAME", "27 Sep, 10:00",
                     program=BACHELOR, applied="20 Sep 2026") for i in range(1, 31)]
    portal.pages["students.php"] = page(*rows)
    chat, _ = run(telegram_bot.crosscheck_command, "/crosscheck 27 Sep 2026", "27 Sep 2026".split())
    assert len(chat) > 1 and all(replies.telegram_len(m.text) <= replies.CHUNK_CHARS for m in chat)
    for m in chat:                                    # every message holds whole cards only
        cards = re.findall(r"^\*\d+\. ", m.text, re.M)
        assert len(cards) == m.text.count("Audit Verdict:*")
    text = report_of(chat)
    assert all(f"STUDENT NUMBER {i:02d}" in text for i in range(1, 31)) and len(audits) == 30


def test_the_crosscheck_date_prompt_and_its_typed_answer(portal, audits):
    portal.pages.update(the_list())
    chat, context = run(telegram_bot.crosscheck_date_command, "/crosscheck_date", [])
    assert context.user_data["awaiting_date_for"] == "crosscheck" and "_(" not in chat[0].text
    chat, _ = run(telegram_bot.handle_natural_language_message, "27 Sep 2026", None, context.user_data)
    assert checked(audits) == ["917", "916"]
    chat, context = run(telegram_bot.crosscheck_date_command, "/crosscheck_date", [])
    chat, _ = run(telegram_bot.handle_natural_language_message, "Kumar", None, context.user_data)
    assert "couldn't read" in chat[0].text and checked(audits) == ["917", "916"]


# --------------------------------------------------------------------------- /passports

def test_passports_is_live_never_the_old_registry(portal, audits, monkeypatch):
    portal.pages.update(the_list())
    portal.pages["students.php?pg=2"] = portal.pages["students.php?pg=2"].replace("08 Sep, 09:00", "28 Sep, 09:00")
    assert not hasattr(ocr, "AUDIT_REGISTRY") and not hasattr(telegram_bot, "AUDIT_REGISTRY")
    for command in ("/passports", "/passport_audit"):
        text = report_of(run(telegram_bot.passports_command, command, [])[0])
        assert "Students on the portal:* `10`" in text and "With a passport scan uploaded:* `9`" in text
        assert "Without a passport scan:* `1`" in text and "NO — WILL APPLY `1`" in text
        assert "Payment-verified today (28 September 2026):* `1`" in text and "PATRA KUMAR TEST" in text
        assert VERDICT in text
        for stale in ("10 Sep 2026", "`47`", "214", "FORKAN", "Admission ad banner"):
            assert stale not in text
    assert checked(audits) == ["112", "112"]


def test_passports_says_when_nobody_was_verified_today_or_the_portal_cannot_be_read(portal, audits):
    portal.pages.update(the_list())
    text = report_of(run(telegram_bot.passports_command, "/passports", [])[0])
    assert "Payment-verified today (28 September 2026):* `0`" in text and "no scan was checked" in text
    portal.pages.clear()
    text = report_of(run(telegram_bot.passports_command, "/passports", [])[0])
    assert text.startswith("❌ Couldn't read the portal:") and "Passport scans: not available" in text
    assert audits == []


# --------------------------------------------------------------------------- OCR: the stub engine

cd = ocr.compute_icao_check_digit
PAGE_H, PAGE_W = 400, 300


def mrz(surname, given, pno, dob, exp, sex="M"):
    """A passport's two MRZ lines, 44 characters each, with real check digits."""
    def yymmdd(d):
        return d[2:4] + d[5:7] + d[8:10]
    b, e = yymmdd(dob), yymmdd(exp)
    line1 = f"P<BGD{surname}<<{given.replace(' ', '<')}".ljust(44, "<")
    body = f"{pno}{cd(pno)}BGD{b}{cd(b)}{sex}{e}{cd(e)}{'<' * 14}0"
    return [line1, body + cd(body[0:10] + body[13:20] + body[21:43])]


class StubReader:
    """easyocr.Reader for marked test pages: the marker column (the left edge of the page as it
    reads) says which page it is and how it is turned; `reads[marker]` is the text the page shows
    read the right way up, anything else reads as noise. A page stored turned needs the OCR code to
    turn it by `upright[marker]` degrees (clockwise). `calls` records the turns the code tried."""

    def __init__(self):
        self.reads, self.upright, self.calls, self.shapes = {}, {}, [], []

    @staticmethod
    def turn_of(img):
        """(marker, how far the image is turned clockwise from the page as it reads)."""
        for turn, edge in ((0, img[:, 0, 0]), (90, img[0, :, 0]), (270, img[-1, :, 0]), (180, img[:, -1, 0])):
            if int(edge.min()) == int(edge.max()) and int(edge[0]) >= 100:
                return int(edge[0]), turn
        raise AssertionError("not a test page")

    def readtext(self, img, detail=1):
        assert detail == 1
        marker, net = self.turn_of(img)
        self.calls.append((net + self.upright.get(marker, 0)) % 360)
        self.shapes.append(img.shape[:2])
        texts = self.reads[marker] if net == 0 else ["~ ~ ~"]
        out = []
        for i, t in enumerate(texts):
            conf = 0.9
            if isinstance(t, tuple):
                t, conf = t
            out.append(([[5, 25 * i], [295, 25 * i], [295, 25 * i + 15], [5, 25 * i + 15]], t, conf))
        return out


@pytest.fixture
def engine(monkeypatch, tmp_path):
    reader = StubReader()
    monkeypatch.setattr(ocr, "get_ocr_reader", lambda: reader)
    counter = {"n": 100}

    def scan(texts, upright=0):
        counter["n"] += 1
        marker = counter["n"]
        rng = np.random.default_rng(marker)
        img = rng.integers(0, 90, size=(PAGE_H, PAGE_W, 3), dtype=np.uint8)
        img[:, 0, :] = marker
        # The page as stored: turned back from the way it reads, so reading it needs `upright`.
        back = {0: None, 90: cv2.ROTATE_90_COUNTERCLOCKWISE, 270: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180}[upright]
        if back is not None:
            img = cv2.rotate(img, back)
        path = str(tmp_path / f"scan_{marker}.png")
        assert cv2.imwrite(path, img)
        reader.reads[marker], reader.upright[marker] = list(texts), upright
        return path
    return type("Engine", (), {"reader": reader, "scan": staticmethod(scan)})


FORM = {"name": "KARIM HASAN", "dob": "2004-03-10", "passport_no": "A00012345", "passport_expiry": "2034-12-04",
        "father_name": "ABDUL HASAN", "mother_name": "SALMA BEGUM", "address": "NOYAPARA, SADAR", "district": "SYLHET"}
PASSPORT = mrz("HASAN", "KARIM", "A00012345", "2004-03-10", "2034-12-04")
PRINTED = ["PEOPLE'S REPUBLIC OF BANGLADESH", "Father's Name: ABDUL HASAN", "Mother's Name: SALMA BEGUM",
           "Permanent Address: NOYAPARA, SADAR", "SYLHET"]


def check(engine, texts, form=None, upright=0):
    return ocr.validate_passport_data("9001", dict(form or FORM), engine.scan(texts, upright))


def test_a_full_match_needs_all_seven_fields(engine):
    res = check(engine, PRINTED + PASSPORT)
    assert res["status"] == "MATCH" and res["is_valid"] and not res["discrepancies"] and not res["uncertain"]
    assert res["verdict"].startswith("✅ 100% Match across All Fields")
    assert engine.reader.calls == [0] and engine.reader.shapes == [(PAGE_H, PAGE_W)]   # the whole page, once


def test_fields_not_on_the_scan_are_named_never_all_fields(engine):
    res = check(engine, ["PEOPLE'S REPUBLIC OF BANGLADESH"] + PASSPORT)
    assert res["status"] == "MATCH" and "All Fields" not in res["verdict"]
    assert res["verdict"] == "✅ Match: Name, DOB, Passport No, Expiry · ℹ️ Not on the scan: Father, Mother, Address"
    res = check(engine, PRINTED[:2] + PASSPORT)
    assert res["verdict"] == ("✅ Match: Name, DOB, Passport No, Expiry, Father · "
                              "ℹ️ Not on the scan: Mother, Address")


@pytest.mark.parametrize("upright", [90, 180, 270])
def test_a_turned_scan_is_read_after_turning_it(engine, upright):
    res = check(engine, PRINTED + PASSPORT, upright=upright)
    assert res["status"] == "MATCH" and res["mrz_data"]["rotation"] == upright
    order = [0, 270, 90, 180]
    assert engine.reader.calls == order[:order.index(upright) + 1]


def test_an_mrz_high_on_the_page_is_found(engine):
    """A phone photo with the MRZ at 55% of the height: the old reader only looked at the bottom 30%."""
    res = check(engine, PASSPORT + PRINTED + ["footer", "more footer", "table", "floor"])
    assert res["status"] == "MATCH" and res["fields"]["father_name"]["status"] == "MATCH"


def test_no_mrz_at_any_turn_is_unreadable_not_not_a_passport(engine):
    res = check(engine, ["ADMISSION OPEN", "SPRING INTAKE 2027", "STUDY IN KOREA"])
    assert res["status"] == "MRZ_UNREADABLE" and not res["is_valid"]
    assert engine.reader.calls == [0, 270, 90, 180]
    note = "couldn't read the MRZ (the photo may be rotated or blurred, or it may not be a passport)"
    assert note in res["discrepancies"][0] and note in res["verdict"]
    assert "not a valid passport" not in str(res) and "Invalid Document" not in res["verdict"]


def test_a_file_that_is_no_picture_is_said_so(engine, tmp_path):
    path = tmp_path / "passport_1_1.jpg"
    path.write_bytes(b"\x00" * 5000)
    res = ocr.validate_passport_data("1", dict(FORM), str(path))
    assert res["status"] == "SCAN_UNREADABLE" and "couldn't open the uploaded file" in res["verdict"]
    assert engine.reader.calls == []


def test_mrz_lines_are_validated_before_any_field_is_trusted():
    line1, line2 = PASSPORT
    assert ocr.parse_mrz_line1(line1)["line1_ok"] and len(line1) == 44
    got = ocr.parse_mrz_line2(line2)
    assert got["line2_ok"] and got["passport_no"] == "A00012345" and got["dob"] == "2004-03-10"
    assert not ocr.parse_mrz_line1(line1[:36])["line1_ok"]                     # 36 of 44 characters
    assert not ocr.parse_mrz_line1(line1.replace("<<<<", "<<K<", 1))["line1_ok"]   # filler read as a letter
    bad_dob = line2[:19] + str((int(line2[19]) + 1) % 10) + line2[20:]
    got = ocr.parse_mrz_line2(bad_dob)
    assert not got["dob_ok"] and got["passport_no_ok"] and got["expiry_ok"] and not got["line2_ok"]
    assert ocr.parse_mrz_line2("4" + line2[1:])["passport_no"] == "A00012345"  # 'A' read as 4, repaired
    short = ocr.parse_mrz_line2(line2[:4] + line2[5:])                         # a digit dropped in the number
    assert not short["passport_no_ok"] and short["dob_ok"] and short["expiry_ok"]
    assert ocr.parse_mrz_date("261399") == ""                                   # month 13


def test_a_field_whose_check_digit_fails_is_check_by_eye_not_a_mismatch(engine):
    line1, line2 = PASSPORT
    broken = line2[:19] + str((int(line2[19]) + 1) % 10) + line2[20:]          # DOB check digit misread
    res = check(engine, PRINTED + [line1, broken], form={**FORM, "dob": "2004-03-11"})
    assert res["fields"]["dob"]["status"] == "NOT_READ" and res["status"] == "CHECK_BY_EYE"
    assert not res["discrepancies"] and any("DOB: couldn't read it reliably" in u for u in res["uncertain"])
    # The same portal DOB against a check-digit-valid MRZ: a confirmed mismatch.
    res = check(engine, PRINTED + PASSPORT, form={**FORM, "dob": "2004-03-11"})
    assert res["status"] == "DISCREPANCY" and "DOB mismatch: Portal has '2004-03-11', MRZ has '2004-03-10'" in res["discrepancies"]


def test_a_one_letter_name_difference(engine):
    portal = {**FORM, "name": "KARIM HASSAN"}
    # A valid MRZ read with fair confidence spells it HASAN: a real discrepancy.
    res = check(engine, ["PEOPLE'S REPUBLIC OF BANGLADESH"] + PASSPORT, form=portal)
    assert res["fields"]["name"]["status"] == "TYPO" and res["status"] == "TYPO"
    assert "Name spelling issue: Portal has 'KARIM HASSAN', MRZ has 'HASAN KARIM'" in res["discrepancies"]
    # The same with a low-confidence line 1: possible OCR misread, not a discrepancy.
    res = check(engine, ["PEOPLE'S REPUBLIC OF BANGLADESH", (PASSPORT[0], 0.1), PASSPORT[1]], form=portal)
    assert res["fields"]["name"]["status"] == "OCR_UNCERTAIN" and not res["discrepancies"]
    assert res["status"] == "CHECK_BY_EYE" and "Possible OCR misread, check by eye" in res["verdict"]
    # A failed read (line 1 not 44 characters) likewise.
    res = check(engine, ["PEOPLE'S REPUBLIC OF BANGLADESH", PASSPORT[0][:36], PASSPORT[1]], form=portal)
    assert res["fields"]["name"]["status"] == "OCR_UNCERTAIN" and not res["discrepancies"]
    # A valid MRZ, but the printed name reads like the portal: the MRZ reading is the doubtful one.
    res = check(engine, ["Surname HASSAN", "Given name KARIM"] + PASSPORT, form=portal)
    assert res["fields"]["name"]["status"] == "OCR_UNCERTAIN" and "printed name reads as on the portal" in res["verdict"]


def test_a_badly_read_mrz_name_is_not_a_discrepancy(engine):
    portal = {**FORM, "name": "TALUKDAR SYEDA RUBINA"}
    line1 = "P<BGDTALUKDAR<<KSYEDASRUBINA<24426"                        # 34 characters, filler read as letters
    passport = [line1, mrz("TALUKDAR", "SYEDA RUBINA", "A00012345", "2004-03-10", "2034-12-04")[1]]
    res = check(engine, PRINTED + passport, form=portal)
    assert res["fields"]["name"]["status"] == "MATCH"                         # the '<' misread as K and S
    res = check(engine, PRINTED + ["P<BGDTALUKDAR<<QWXTRPLMNB<<<<", passport[1]], form=portal)
    assert res["fields"]["name"]["status"] == "NOT_READ" and not res["discrepancies"]
    assert "Couldn't read the name reliably from the MRZ, check by eye" in res["verdict"]


def test_parent_names_are_check_by_eye_unless_nothing_matches(engine):
    res = check(engine, PRINTED[:2] + ["Mother's Name: SALMA BEGIM"] + PRINTED[3:] + PASSPORT)
    assert res["fields"]["mother_name"]["status"] == "OCR_UNCERTAIN" and res["status"] == "CHECK_BY_EYE"
    assert not res["discrepancies"] and "Mother's Name: Possible OCR misread, check by eye" in res["verdict"]
    res = check(engine, PRINTED[:2] + ["Mother's Name: RUMANA KHATUN"] + PRINTED[3:] + PASSPORT)
    assert res["fields"]["mother_name"]["status"] == "MISMATCH" and res["status"] == "DISCREPANCY"
    assert "Mother's Name discrepancy: Portal has 'SALMA BEGUM', Doc has 'RUMANA KHATUN'" in res["discrepancies"]


def test_a_name_line_that_was_not_read_is_never_not_on_the_scan(engine):
    res = check(engine, PRINTED + [PASSPORT[1]])                       # line 2 only
    assert res["fields"]["name"]["status"] == "NOT_READ" and res["status"] == "CHECK_BY_EYE"
    assert "Couldn't read MRZ line 1 (the name), check by eye" in res["verdict"]
    assert res["fields"]["dob"]["status"] == "MATCH"                    # line 2 still counts, by its check digits


def test_a_blank_portal_field_is_never_a_match(engine):
    res = check(engine, PRINTED + PASSPORT, form={**FORM, "dob": "", "passport_no": "", "father_name": ""})
    assert {res["fields"][k]["status"] for k in ("dob", "passport_no", "father_name")} == {"MISSING_PORTAL"}
    assert "ℹ️ Blank on the portal: DOB, Passport No, Father" in res["verdict"]


# --------------------------------------------------------------------------- audit_student_passport

PNG = cv2.imencode(".png", np.full((60, 60, 3), 200, dtype=np.uint8))[1].tobytes() + b"\x00" * 2000
EDIT = ("<form><input name='_csrf' value='x'><input name='name' value='KARIM HASAN'>"
        "<input name='father_name' value='ABDUL HASAN'><select name='program'><option>EAP</option>"
        "<option selected>KLP</option><option>MASTERS</option></select></form>")


@pytest.fixture
def audit_env(monkeypatch, tmp_path):
    seen, validated = [], []
    state = {"expired": 0, "doc": PNG, "edit": EDIT}

    def handler(request):
        path = request.url.path.rsplit("/", 1)[-1]
        seen.append((request.method, path + (f"?{request.url.query.decode()}" if request.url.query else "")))
        assert request.method == "GET"
        if path == "login.php":
            return httpx.Response(200, text="<form><input name='_csrf' value='t'></form>")
        if path == "view_doc.php" and state["expired"]:
            state["expired"] -= 1
            return httpx.Response(302, headers={"Location": "https://portal.test/admin/login.php"})
        if path == "student_edit.php":
            return httpx.Response(200, text=state["edit"]) if state["edit"] else httpx.Response(404)
        if path == "view_doc.php":
            return httpx.Response(200, content=state["doc"])
        return httpx.Response(404)

    async def login(*args, **kwargs):
        admin_client.is_authenticated = True
        return {"success": True}

    def validate(student_id, form_data, image_path=None, live_audit=True):
        validated.append((student_id, dict(form_data), image_path))
        return {"status": "MATCH", "path": image_path}
    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                                                   follow_redirects=True))
    monkeypatch.setattr(admin_client, "base_url", "https://portal.test/admin")
    monkeypatch.setattr(admin_client, "is_authenticated", True)
    monkeypatch.setattr(admin_client, "login", login)
    monkeypatch.setattr(client_module, "BOT_ROOT", tmp_path)
    monkeypatch.setattr(client_module, "validate_passport_data", validate)
    return type("Env", (), {"seen": seen, "validated": validated, "state": state, "tmp": tmp_path})


def test_the_scan_download_renews_an_expired_session(audit_env):
    audit_env.state["expired"] = 1
    res = asyncio.run(admin_client.audit_student_passport("9001", {"name": "X"}, "passport_9001_17.png"))
    saved = os.path.join(audit_env.tmp, "passports", "9001_passport_9001_17.png")
    assert res["status"] == "MATCH" and res["path"] == saved and open(saved, "rb").read() == PNG
    assert audit_env.validated[0][1]["father_name"] == "ABDUL HASAN" and audit_env.validated[0][1]["program"] == "KLP"
    assert ("GET", "login.php") in audit_env.seen and all(m == "GET" for m, _ in audit_env.seen)


def test_a_web_page_instead_of_the_scan_is_never_saved_or_checked(audit_env):
    audit_env.state["doc"] = b"<!DOCTYPE html><html><body>" + b"x" * 3000 + b"</body></html>"
    res = asyncio.run(admin_client.audit_student_passport("9001", {}, "passport_9001_17.png"))
    assert res["status"] == "PORTAL_UNREADABLE" and "web page instead of the passport scan" in res["verdict"]
    assert not os.path.exists(os.path.join(audit_env.tmp, "passports", "9001_passport_9001_17.png"))
    assert audit_env.validated == [] and res["discrepancies"] == []


def test_an_unreadable_profile_is_said_never_blank_fields(audit_env):
    audit_env.state["edit"] = ""
    res = asyncio.run(admin_client.audit_student_passport("9001", {}, "passport_9001_17.png"))
    assert res["status"] == "PORTAL_UNREADABLE" and "student_edit.php?id=9001" in res["verdict"]
    assert "HTTP 404" in res["verdict"] and audit_env.validated == []


def test_an_old_saved_scan_is_never_checked_in_place_of_the_portals(audit_env):
    folder = os.path.join(audit_env.tmp, "passports")
    os.makedirs(folder)
    with open(os.path.join(folder, "9001_passport_9001_1600000000.jpg"), "wb") as f:
        f.write(PNG)                                       # an earlier upload, no longer on the portal
    asyncio.run(admin_client.audit_student_passport("9001", {}, None))
    assert audit_env.validated[0][2] is None                # MISSING_DOCUMENT, not the old file


def test_a_file_name_that_could_leave_the_folder_is_refused(audit_env):
    res = asyncio.run(admin_client.audit_student_passport("9001", {}, "../../evil.png"))
    assert res["status"] == "PORTAL_UNREADABLE" and audit_env.validated == []
