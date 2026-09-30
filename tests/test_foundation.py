"""The shared foundation every command builds on, and the commands fixed with it.

  src/dates.py          the one strict reader of user dates, and the portal-stamp matcher
  src/bot/replies.py    long replies split under Telegram's limit, with a plain-text resend
  src/scraper/client.py one portal session path (PortalUnavailable), the all-pages students.php
                        reader, the verified and admitted readers
  src/scraper/parsers.py students.php read by the header's column names
  /verified_today, /verified_date, /verified, /verified_students (and their free-text routes),
  /admitted, /students, normalize_date_input.

Every portal page here is synthetic, laid out like the live students.php (Sep 2026): a .stu-row
with the Student / University / Program · Intake / Docs / Payment / Stage · Applied cells, and its
.xp-row with the details, the payment chips, the "Payment verified by NAME · 27 Sep, 17:19" stamp,
the stage and transfer-intake selects, and the edit link. Nothing reaches the network or Telegram.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_foundation.py -q
"""
import asyncio
import re
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from telegram.error import BadRequest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

from src import dates  # noqa: E402
from src.bot import ask, replies, telegram_bot  # noqa: E402
from src.config import settings  # noqa: E402
from src.scraper import client as client_module, parsers  # noqa: E402
from src.scraper.client import PortalUnavailable, admin_client  # noqa: E402

TODAY = date(2026, 9, 28)
ADMIN_ID = 111111111
KLP = "KOREAN LANGUAGE PROGRAM (KLP)"
BACHELOR = "BACHELOR'S DEGREE"


# --------------------------------------------------------------------------- synthetic students.php

HEAD = ('<thead><tr><th></th><th>SL</th><th>Student</th><th>University</th><th>Program · Intake</th>'
        '<th>Docs</th><th>Payment</th><th>Stage · Applied</th><th></th></tr></thead>')


def row(uid, sl, name, hng="", uni="—", program=KLP, intake="MARCH 2027", docs="All Missing", pay="Verified",
        stage="Payment Verified", applied="12 Jul 2026", by="", when="", paid="", method="", income=""):
    """One student as students.php lays it out: the list row and its details row."""
    tags = f'<span class="stu-sid">{hng}</span>' if hng else "<span>—</span>"
    stu_row = (f'<tr class="stu-row" onclick="toggleExp(\'exp{uid + 1000}\')"><td class="c-chk"><input class="bulk-chk"></td>'
               f'<td class="c-sl">{sl}</td><td class="c-stu"><strong class="pii stu-name">{name}</strong>'
               '<div class="pii stu-mail"><a class="__cf_email__" href="/cdn-cgi/l/email-protection">[email&#160;protected]</a>'
               f'</div><div class="stu-tags">{tags}</div></td><td class="c-uni">{uni}</td>'
               f'<td class="c-prog">{program}<div class="stu-sub" title="Intake"><i class="fas fa-calendar-days"></i> {intake}</div></td>'
               f'<td class="c-docs">{docs}</td><td class="c-pay">{pay}</td>'
               f'<td class="c-stage">{stage}<div class="stu-sub" title="Applied on"><i class="fas fa-clock"></i> {applied}</div></td>'
               '<td class="c-exp"><button class="xp-btn"><i class="fas fa-chevron-down"></i></button></td></tr>')
    dets = "".join(f'<div class="det-item"><label>{k}</label><span>{v}</span></div>' for k, v in (
        ("Full Name", name), ("DOB", "2000-01-01"), ("Program", program), ("Intake", intake),
        ("Payment Status", "verified" if by else "pending"), ("Applied On", f"{applied}, 10:00")))
    chips = (f'<span class="pf paid">Paid: {paid}</span>' if paid else "") + (
        f'<span class="pf method">{method}</span>' if method else "") + (
        f'<span class="pf verified">Verified income: {income}</span>' if income else "")
    stamp = (f'<div class="pf-by"><i class="fas fa-user-check"></i> <span>Payment verified by <strong>{by}</strong>'
             f" · {when}</span></div>" if by else "")
    # The row's stage and transfer-intake selects: their words ("Admitted / Completed",
    # "SEPTEMBER 2027") must never be read as the student's stage or as a date.
    selects = (f'<select name="stage"><option>Application Received</option><option selected>{stage}</option>'
               '<option>Admitted / Completed</option></select><select name="new_intake"><option>DECEMBER 2026</option>'
               "<option>MARCH 2027</option><option>JUNE 2027</option><option>SEPTEMBER 2027</option></select>")
    xp = (f'<tr class="xp-row"><td colspan="9"><div class="det">{dets}</div><div class="pay">{chips}{stamp}</div>'
          f'<a href="view_doc.php?f=passport_{uid}_1700000000.jpeg">Passport</a><form method="POST">{selects}</form>'
          f'<a href="student_edit.php?id={uid}">Edit</a><a href="progress.php?uid={uid}">Progress</a>'
          f'<button onclick="showDel({uid}, &quot;{name}&quot;)">Delete</button></td></tr>')
    return stu_row + xp


def page(*rows, pg=1, pages=1, total=None):
    body = "".join(rows) or '<tr class="empty-row"><td colspan="9">No students found Try a different filter</td></tr>'
    pager = ""
    if pages > 1 or total is not None:
        pager = (f'<div class="stu-pager">{"Prev " if pg > 1 else ""}Page {pg} of {pages}'
                 + (f" · {total} students" if total is not None else "") + ("Next" if pg < pages else "") + "</div>")
    return f'<html><body><table class="tbl stu-tbl">{HEAD}<tbody>{body}</tbody></table>{pager}</body></html>'


def verified(uid, sl, name, when, amount="20,000.00 BDT", method="Cash", by="MAHIRA JANAN", **kw):
    return row(uid, sl, name, hng=f"HNG-2026-{uid:03d}", by=by, when=when, paid=amount, method=method,
               income=amount, **kw)


def dashboard(admitted=0, href="students.php?stage=Admitted+%2F+Completed"):
    return ('<div class="dash-sec"><h2 class="ds-t">Direct / legacy pipeline</h2></div><div class="stats-row">'
            f'<a class="stat-card" href="students.php"><span class="stat-num">5</span><span class="stat-lbl">Total students</span></a>'
            f'<a class="stat-card" href="{href}"><span class="stat-num">{admitted}</span>'
            '<span class="stat-lbl">Admitted</span></a></div>')


# --------------------------------------------------------------------------- fixtures

@pytest.fixture
def portal(monkeypatch):
    """The portal as a dict of "page?query" -> HTML (a missing page answers 404); every request is
    recorded and must be a GET. Today is 28 Sep 2026 in Dhaka."""
    pages = {}
    asked = []

    def handler(request):
        key = request.url.path.rsplit("/", 1)[-1] + (f"?{request.url.query.decode()}" if request.url.query else "")
        asked.append((request.method, key))
        if request.method != "GET":
            raise AssertionError(f"the portal is read-only: {request.method} {key}")
        if key in pages:
            return httpx.Response(200, text=pages[key])
        return httpx.Response(404, text="not found")

    async def no_login(*args, **kwargs):
        raise AssertionError("tests must not log in to the portal")

    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(admin_client, "is_authenticated", True)
    monkeypatch.setattr(admin_client, "mock_mode", False)
    monkeypatch.setattr(admin_client, "login", no_login)
    pin_today(monkeypatch)
    monkeypatch.setattr(settings, "TELEGRAM_ADMIN_CHAT_ID", str(ADMIN_ID))
    return SimpleNamespace(pages=pages, asked=asked)


def pin_today(monkeypatch, today=TODAY):
    """Today is `today` in Dhaka for every reader of it: src.dates.local_today, and src.bot.ask's
    own name for it (ask imports local_today by name, so patching src.dates alone misses it)."""
    monkeypatch.setattr(dates, "local_today", lambda: today)
    monkeypatch.setattr(ask, "local_today", lambda: today)


class Sent:
    """A message the bot sent: it may be edited (Telegram refuses over 4096) or deleted."""

    def __init__(self, chat, text, parse_mode):
        self.chat, self.text, self.parse_mode, self.deleted, self.edits = chat, text, parse_mode, False, 0
        chat.append(self)

    async def edit_text(self, text, parse_mode=None, **kwargs):
        if replies.telegram_len(text) > replies.TELEGRAM_LIMIT:
            raise BadRequest("Message is too long")
        self.text, self.parse_mode, self.edits = text, parse_mode, self.edits + 1
        return self

    async def delete(self):
        self.deleted = True


class Chat(list):
    def shown(self):
        return [m.text for m in self if not m.deleted]


class Message:
    def __init__(self, chat, text="", refuse_markdown=False):
        self.chat, self.text, self.refuse_markdown = chat, text, refuse_markdown

    async def reply_text(self, text, parse_mode=None, **kwargs):
        if replies.telegram_len(text) > replies.TELEGRAM_LIMIT:
            raise BadRequest("Message is too long")
        if parse_mode == "Markdown" and self.refuse_markdown:
            raise BadRequest("Can't parse entities: can't find end of the entity starting at byte offset 7")
        return Sent(self.chat, text, parse_mode)


def fake_update(text="", args=None, user_data=None):
    chat = Chat()
    update = SimpleNamespace(message=Message(chat, text), effective_chat=SimpleNamespace(id=ADMIN_ID),
                             effective_user=SimpleNamespace(id=ADMIN_ID), callback_query=None)
    context = SimpleNamespace(args=args, user_data=user_data if user_data is not None else {}, bot=SimpleNamespace())
    return update, context, chat


def run(handler, text="", args=None, user_data=None):
    update, context, chat = fake_update(text, args, user_data)
    asyncio.run(handler(update, context))
    return chat, context


def student_reads(asked):
    return [key for method, key in asked if key.startswith("students.php")]


# --------------------------------------------------------------------------- user dates

@pytest.mark.parametrize("text, expected", [
    ("today", TODAY), ("yesterday", date(2026, 9, 27)), ("day before yesterday", date(2026, 9, 26)),
    ("8 Sep", date(2026, 9, 8)), ("8 Sep 2026", date(2026, 9, 8)), ("8th Sep", date(2026, 9, 8)),
    ("Sep 8", date(2026, 9, 8)), ("Sep 8, 2026", date(2026, 9, 8)), ("September 8th 2026", date(2026, 9, 8)),
    ("the 8th of September", date(2026, 9, 8)), ("08/09/2026", date(2026, 9, 8)), ("8-9-2026", date(2026, 9, 8)),
    ("8.9.26", date(2026, 9, 8)), ("08/09", date(2026, 9, 8)), ("2026-09-08", date(2026, 9, 8)),
    ("2026/09/08", date(2026, 9, 8)), ("12 Sept 2026", date(2026, 9, 12)), ("27 Sep 2025", date(2025, 9, 27)),
    ("29 Feb 2024", date(2024, 2, 29)), ("verified students 27 sep", date(2026, 9, 27)),
    ("/verified_date 12 Sep 2026", date(2026, 9, 12)), ("report for 07 Sep 2026", date(2026, 9, 7)),
    ("how many students were verified on the 12th of September", date(2026, 9, 12)),
    ("8 Sep 2026, 17:19", date(2026, 9, 8)),
])
def test_a_user_date_is_read_exactly(text, expected):
    assert dates.parse_user_date(text, TODAY) == expected


@pytest.mark.parametrize("text", [
    "31 Sep", "31 Sep 2026", "29 Feb 2026", "29 Feb", "0 Sep", "13/13/2026", "8 Sep 202", "Sep", "Sep 2026",
    "12th", "foo", "", "separately", "may I see the list", "last week", "1 Sep 2026 to 15 Sep 2026",
    "12 Sep today", "HNG-2026-931", "5.5 students", "10:15",
])
def test_an_impossible_or_missing_date_is_none_never_today(text):
    assert dates.parse_user_date(text, TODAY) is None


def test_month_words_count_only_as_whole_words_next_to_a_day():
    assert dates.parse_user_date("18 Sep", TODAY) == date(2026, 9, 18)          # never "8 Sep" inside it
    assert dates.parse_user_date("28 Sep 2026", TODAY) == date(2026, 9, 28)
    assert not dates.has_date_hint("verified students separately")              # "sep" inside a word
    assert not dates.has_date_hint("may I see")                                 # "may" is a word too
    assert dates.has_date_hint("verified in sep") and dates.has_date_hint("last week")


def test_a_date_without_a_year_can_mean_the_one_just_gone():
    new_year = date(2027, 1, 5)
    assert dates.parse_user_date("27 Dec", new_year) == date(2027, 12, 27)
    assert dates.parse_user_date("27 Dec", new_year, prefer_past=True) == date(2026, 12, 27)
    assert dates.parse_user_date("5 Jan", new_year, prefer_past=True) == date(2027, 1, 5)   # today itself


def test_why_a_date_cannot_be_read():
    assert dates.user_date_problem("31 Sep 2026", TODAY) == "31 Sep 2026: September 2026 has 30 days"
    assert dates.user_date_problem("29 Feb", TODAY) == "29 Feb: February 2026 has 28 days"
    assert dates.user_date_problem("in sep", TODAY) == "it names a month but no day of it"
    assert dates.user_date_problem("1 Sep to 5 Sep", TODAY).startswith("it names more than one date")
    assert dates.user_date_problem("8 Sep", TODAY) is None


def test_portal_stamps_match_whole_tokens_and_their_year():
    assert dates.parse_stamp("Payment verified by X · 27 Sep, 17:19") == dates.Stamp(27, 9, None, "17:19", "27 Sep, 17:19")
    assert dates.parse_stamp("27 Sep 2025, 10:00").text == "27 Sep, 10:00"
    assert dates.parse_stamp("31 Sep, 10:00") is None
    assert dates.stamp_on_day("08 Sep, 09:00", date(2026, 9, 8))
    for other in ("18 Sep, 09:00", "28 Sep, 09:00", "8 Oct, 09:00"):
        assert not dates.stamp_on_day(other, date(2026, 9, 8)), other
    assert not dates.stamp_on_day("27 Sep 2025, 10:00", date(2026, 9, 27))    # a stamp's own year
    assert dates.stamp_on_day("27 Sep 2025, 10:00", date(2025, 9, 27))
    # Verified before applying is impossible: that stamp is another year's.
    assert not dates.stamp_on_day("27 Sep, 10:00", date(2025, 9, 27), applied=date(2026, 7, 12))
    assert dates.parse_portal_date("Applied On 27 Sep 2026, 17:16") == date(2026, 9, 27)
    assert dates.parse_portal_date("27 Sep, 17:16") is None
    assert dates.yearless_day_problem(date(2025, 9, 27), TODAY).startswith("the portal writes verification times")
    assert dates.yearless_day_problem(date(2025, 10, 1), TODAY) is None
    assert dates.yearless_day_problem(date(2026, 9, 29), TODAY) == "a date in the future"


def test_normalize_date_input_never_falls_back_to_today(portal):
    n = telegram_bot.normalize_date_input
    assert n("31 Sep 2026") is None and n("in sep") is None and n("verified last week") is None
    assert n("/verified_date foo", strict=True) is None
    assert n("") == ("28 Sep 2026", "28 September 2026")                        # no date given: today
    assert n("/verified") == n("/verified_students@HangeulBot") == ("28 Sep 2026", "28 September 2026")
    assert n("how many students were verified") == ("28 Sep 2026", "28 September 2026")
    assert n("report for 07 Sep 2026") == ("07 Sep 2026", "07 September 2026")
    assert n("yesterday", strict=True) == ("27 Sep 2026", "27 September 2026")
    with pytest.raises(ValueError):
        parsers.normalize_target_date("31 Sep 2026")
    assert parsers.normalize_target_date("8 Sep") == "08 Sep 2026" and parsers.normalize_target_date("") is None


def test_every_caller_of_normalize_date_input_says_it_cannot_read_the_date(portal, monkeypatch):
    for handler, args in ((telegram_bot.report_command, ["31", "Sep"]), (telegram_bot.verified_command, ["31", "Sep"]),
                          (telegram_bot.verified_date_command, ["31", "Sep", "2026"])):
        chat, _ = run(handler, "/cmd 31 Sep", args)
        assert len(chat) == 1 and "couldn't read" in chat[0].text and "has 30 days" in chat[0].text
    assert "couldn't read" in asyncio.run(telegram_bot.build_inquiries_report("31 Sep 2026"))
    assert telegram_bot._parse_date_range("31 Sep 2026 to 5 Oct 2026") == (None, None, None)
    assert portal.asked == []                                                   # nothing was read


# --------------------------------------------------------------------------- long replies

def test_split_text_splits_between_lines_and_counts_like_telegram():
    lines = [f"🎓 *{i:03d}. STUDENT NAME* — 20,000.00 BDT Cash — verified by MAHIRA JANAN (27 Sep, 17:19)"
             for i in range(200)]
    text = "\n".join(lines)
    pieces = replies.split_text(text)
    assert len(pieces) > 1 and "\n".join(pieces) == text
    assert all(replies.telegram_len(p) <= replies.CHUNK_CHARS < replies.TELEGRAM_LIMIT for p in pieces)
    assert all(p.split("\n")[0] in lines and p.split("\n")[-1] in lines for p in pieces)
    assert replies.telegram_len("🎓") == 2 and replies.split_text("") == []
    emoji_line = "🎓" * 3000                                                   # 6000 units, no space
    assert all(replies.telegram_len(p) <= replies.CHUNK_CHARS for p in replies.split_text(emoji_line))
    assert telegram_bot._chunk_message("short") == ["short"]


def test_reply_long_edits_the_waiting_message_then_replies_and_falls_back_to_plain_text():
    text = "\n".join(f"*{i}. NAME_{i}* — `20,000.00 BDT`" for i in range(400))
    chat = Chat()
    message = Message(chat)
    status = asyncio.run(message.reply_text("⏳ _Gathering…_", parse_mode="Markdown"))
    sent = asyncio.run(replies.reply_long(message, text, edit=status))
    pieces = replies.split_text(text)
    assert sent == len(pieces) > 1
    assert chat[0] is status and status.text == pieces[0] and status.edits == 1
    assert [m.text for m in chat[1:]] == pieces[1:]
    assert all(m.parse_mode == "Markdown" for m in chat)

    refusing = Chat()
    asyncio.run(replies.reply_long(Message(refusing, refuse_markdown=True), "*1. NAME_1* — `x`"))
    assert [(m.text, m.parse_mode) for m in refusing] == [("1. NAME1 — x", None)]
    assert replies.markdown_to_plain("Lina\\_Parvin *bold* `code`") == "Lina_Parvin bold code"

    class Gone:
        async def edit_text(self, *args, **kwargs):
            raise BadRequest("Message to edit not found")
    lost = Chat()
    asyncio.run(replies.reply_long(Message(lost), "the report", edit=Gone()))
    assert [m.text for m in lost] == ["the report"]                             # sent instead, never lost

    with pytest.raises(BadRequest):                                             # other errors are not hidden
        async def chat_gone(piece, mode):
            raise BadRequest("Chat not found")
        asyncio.run(replies.send_pieces(chat_gone, "hello"))


def test_send_long_goes_through_bot_send_message():
    got = []

    class Bot:
        async def send_message(self, chat_id, text, parse_mode=None):
            got.append((chat_id, text, parse_mode))
    text = "\n".join("x" * 100 for _ in range(100))
    assert asyncio.run(replies.send_long(Bot(), 7, text)) == len(got) == 3
    assert all(c == 7 and m == "Markdown" and len(t) <= replies.CHUNK_CHARS for c, t, m in got)


def test_the_stock_error_replies():
    text = replies.date_error_reply("31 Sep 2026", "/verified_date")
    assert "couldn't read “31 Sep 2026” as a date (31 Sep 2026: September 2026 has 30 days)" in text
    assert "`/verified_date 12 Sep 2026`" in text
    assert "\\_" in replies.date_error_reply("my_date")                         # typed text is escaped
    err = replies.portal_error_reply("Verified students for 12 September 2026",
                                     PortalUnavailable("couldn't log in to the portal: refused"))
    assert err.startswith("❌ Couldn't read the portal: couldn't log in to the portal: refused.")
    assert "Verified students for 12 September 2026: not available right now." in err


# --------------------------------------------------------------------------- the portal session

def test_an_expired_session_logs_in_again_once(monkeypatch):
    calls, logins = [], []
    expired = {"n": 1}

    def handler(request):
        calls.append(request.url.path.rsplit("/", 1)[-1])
        if expired["n"]:
            expired["n"] -= 1
            return httpx.Response(302, headers={"Location": "https://hangeul.com.bd/admin/login.php"})
        if request.url.path.endswith("login.php"):
            return httpx.Response(200, text="<form><input name='_csrf' value='t'></form>")
        return httpx.Response(200, text="<table><tr><th>x</th></tr></table>")

    async def login(*args, **kwargs):
        logins.append(True)
        admin_client.is_authenticated = True
        return {"success": True}

    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                                                   follow_redirects=True))
    monkeypatch.setattr(admin_client, "is_authenticated", True)
    monkeypatch.setattr(admin_client, "login", login)
    assert "<table>" in asyncio.run(admin_client.fetch_html("index.php"))
    assert calls == ["index.php", "login.php", "index.php"] and len(logins) == 1

    # Still the login page after a fresh login: raised, never parsed as a page.
    calls.clear()
    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(always_login),
                                                                   follow_redirects=True))
    with pytest.raises(PortalUnavailable, match="kept sending its login page"):
        asyncio.run(admin_client.fetch_html("students.php"))
    assert len(logins) == 2 and not admin_client.is_authenticated


def always_login(request):
    """A portal whose every page redirects to its login page (the session cannot be renewed)."""
    if request.url.path.endswith("login.php"):
        return httpx.Response(200, text="<form><input name='_csrf' value='t'><table></table></form>")
    return httpx.Response(302, headers={"Location": "https://hangeul.com.bd/admin/login.php"})


def test_a_failed_login_is_raised_not_ignored(monkeypatch):
    async def refused(*args, **kwargs):
        return {"success": False, "error": "the portal refused the login (wrong username or password?)"}

    monkeypatch.setattr(admin_client, "is_authenticated", False)
    monkeypatch.setattr(admin_client, "login", refused)
    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: pytest.fail("no page is read without a session"))))
    with pytest.raises(PortalUnavailable, match="couldn't log in to the portal: the portal refused the login") as e:
        asyncio.run(admin_client.fetch_html("students.php"))
    assert not e.value.unreachable


def test_login_checks_where_the_post_ended(monkeypatch):
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, text="<form><input name='_csrf' value='tok'></form>")
        assert parse_qs(request.content.decode())["_csrf"] == ["tok"]
        return httpx.Response(200, text="<p>Welcome back</p>")                 # still login.php: refused
    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(admin_client, "mock_mode", False)
    monkeypatch.setattr(admin_client, "is_authenticated", False)
    result = asyncio.run(admin_client.login())
    assert result["success"] is False and not admin_client.is_authenticated

    def down(request):
        raise httpx.ConnectError("refused", request=request)
    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(down)))
    result = asyncio.run(admin_client.login())
    assert result["success"] is False and result["unreachable"] is True


def test_a_portal_that_does_not_answer_is_unreachable_and_an_error_status_is_not_a_page(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("", request=request)
    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(timeout)))
    monkeypatch.setattr(admin_client, "is_authenticated", True)
    with pytest.raises(PortalUnavailable) as e:
        asyncio.run(admin_client.fetch_html("students.php"))
    assert e.value.unreachable and "did not answer in time" in str(e.value)
    assert client_module.portal_error_reason(e.value) == str(e.value)

    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(500, text="<table>oops</table>"))))
    with pytest.raises(PortalUnavailable, match="HTTP 500"):
        asyncio.run(admin_client.fetch_html("students.php"))


def test_query_values_are_url_encoded(portal):
    portal.pages["students.php?q=Admission+%26+Tuition"] = page(row(1, 1, "A"))
    assert len(asyncio.run(admin_client.read_students({"q": "Admission & Tuition"}))) == 1
    assert portal.asked == [("GET", "students.php?q=Admission+%26+Tuition")]


# --------------------------------------------------------------------------- students.php, read by header

def test_a_student_row_is_read_by_the_headers_column_names():
    html = page(verified(917, 1, "RAHIM UDDIN", "27 Sep, 17:19", uni="HANYANG UNIVERSITY",
                         applied="27 Sep 2026"),
                row(969, 2, "PENDING APPLICANT", program="EAP (ENGLISH FOR ACADEMIC PURPOSE)", intake="DECEMBER 2026",
                    docs="—", pay="Pending", stage="Application Received", applied="28 Sep 2026"),
                pages=7, total=330)
    got = parsers.parse_students_page(html)
    assert (got["page"], got["pages"], got["total"], got["empty"]) == (1, 7, 330, False)
    badhon, tomal = got["students"]
    assert {k: badhon[k] for k in ("uid", "sl", "student_id", "id", "student_name", "target_university", "program",
                                   "target_intake", "docs_status", "payment_status", "status", "applied_date")} == {
        "uid": "917", "sl": "1", "student_id": "HNG-2026-917", "id": "HNG-2026-917",
        "student_name": "RAHIM UDDIN", "target_university": "HANYANG UNIVERSITY", "program": KLP,
        "target_intake": "MARCH 2027", "docs_status": "All Missing", "payment_status": "Verified",
        "status": "Payment Verified", "applied_date": "27 Sep 2026"}
    assert (badhon["verified_by"], badhon["verified_stamp"], badhon["paid"], badhon["method"],
            badhon["verified_income"], badhon["applied_on"]) == (
        "MAHIRA JANAN", "27 Sep, 17:19", "20,000.00 BDT", "Cash", "20,000.00 BDT", "27 Sep 2026, 10:00")
    assert badhon["files"] == ["passport_917_1700000000.jpeg"] and badhon["details"]["DOB"] == "2000-01-01"
    # Nothing made up: no "HNG-SL-2", no "Pending Allocation", no "March 2027" for everyone.
    assert (tomal["student_id"], tomal["target_university"], tomal["docs_status"], tomal["target_intake"],
            tomal["verified_by"], tomal["verified_stamp"]) == ("", "", "", "DECEMBER 2026", "", "")
    assert parsers.parse_hangeul_live_students(html) == got["students"]


def test_the_columns_are_found_by_name_wherever_they_are():
    html = page(row(5, 1, "KIM SEOYEON", hng="HNG-2026-901", uni="COUNSELOR WILL SUGGEST"))
    moved = html.replace("<th>University</th><th>Program · Intake</th>", "<th>Program · Intake</th><th>University</th>")
    moved = re.sub(r'(<td class="c-uni">.*?</td>)(<td class="c-prog">.*?</td>)', r"\2\1", moved)
    s = parsers.parse_students_page(moved)["students"][0]
    assert s["program"] == KLP and s["target_intake"] == "MARCH 2027" and s["target_university"] == "COUNSELOR WILL SUGGEST"


def test_an_unrecognised_student_list_raises_and_an_empty_one_is_empty():
    assert parsers.parse_students_page(page()) == {"students": [], "empty": True, "page": None, "pages": None,
                                                   "total": None}
    with pytest.raises(parsers.StudentListLayoutError):
        parsers.parse_students_page("<html>no table</html>")
    with pytest.raises(parsers.StudentListLayoutError, match="no stage column"):
        parsers.parse_students_page(page(row(1, 1, "A")).replace("Stage · Applied", "Phase"))
    with pytest.raises(parsers.StudentListLayoutError, match="cannot read"):
        parsers.parse_students_page(page(row(1, 1, "A")).replace('<td class="c-sl">1</td>', '<td class="c-sl">#</td>'))


def test_every_page_is_read_with_its_query_and_each_student_listed_once(portal):
    shared = row(3, 3, "SHIFTED ONTO PAGE TWO")
    portal.pages.update({
        "students.php?q=Kim": page(row(1, 1, "KIM A"), row(2, 2, "KIM B"), shared, pg=1, pages=2, total=4),
        "students.php?q=Kim&pg=2": page(shared, row(4, 4, "KIM D"), pg=2, pages=2, total=4)})
    got = asyncio.run(admin_client.read_students({"q": "Kim"}))
    assert [s["uid"] for s in got] == ["1", "2", "3", "4"]
    assert student_reads(portal.asked) == ["students.php?q=Kim", "students.php?q=Kim&pg=2"]
    assert all(method == "GET" for method, _ in portal.asked)


@pytest.mark.parametrize("pages, why", [
    ({"students.php": page(row(1, 1, "A"), pg=1, pages=2, total=3),
      "students.php?pg=2": page(row(2, 1, "B"), pg=2, pages=2, total=3)}, "says 3 students but its 2 pages hold 2"),
    ({"students.php": page(row(1, 1, "A"), pg=1, pages=2),
      "students.php?pg=2": page(row(1, 1, "A"), pg=1, pages=2)}, "sent page 1 when asked for page 2"),
    ({"students.php": page(*[row(i, i, f"S{i}") for i in range(1, 51)])}, "no 'Page 1 of N'"),
    ({"students.php": "<html>maintenance</html>"}, "no student table"),
    ({"students.php": page(row(1, 1, "A")).replace("Stage · Applied", "Phase")}, "no stage column"),
])
def test_a_list_that_cannot_be_read_whole_raises(portal, pages, why):
    portal.pages.update(pages)
    with pytest.raises(PortalUnavailable, match=re.escape(why)):
        asyncio.run(admin_client.read_students())


# --------------------------------------------------------------------------- /verified*

def two_pages_of_verified():
    """Page 1: the newest applications (two verified on 27 Sep, one on 18 Sep); page 2: older
    applications verified on 12 Sep, 8 Sep and 28 Sep, and one on "27 Sep" who applied later."""
    return {
        "students.php": page(
            verified(917, 1, "RAHIM UDDIN", "27 Sep, 17:19", applied="27 Sep 2026"),
            verified(916, 2, "NUSRAT JAHAN", "27 Sep, 17:06", amount="8,000.00 BDT", method="bKash",
                     by="NOSHIN SAMAD", program=BACHELOR, applied="27 Sep 2026"),
            verified(910, 3, "EIGHTEENTH STUDENT", "18 Sep, 11:00", applied="18 Sep 2026"),
            row(969, 4, "PENDING APPLICANT", pay="Pending", stage="Application Received", applied="28 Sep 2026"),
            pg=1, pages=2, total=8),
        "students.php?pg=2": page(
            verified(300, 5, "TWELFTH SEPTEMBER ONE", "12 Sep, 10:00", applied="1 Sep 2026"),
            verified(301, 6, "TWELFTH SEPTEMBER TWO", "12 Sep, 12:30", amount="12,000.00 BDT", applied="1 Sep 2026"),
            verified(302, 7, "EIGHTH STUDENT", "08 Sep, 09:00", applied="1 Sep 2026"),
            verified(303, 8, "TWENTY EIGHTH", "28 Aug, 09:00", applied="1 Aug 2026"),
            pg=2, pages=2, total=8),
    }


def report_of(chat):
    return "\n".join(chat.shown())


def test_verified_reads_every_page_of_the_student_list(portal):
    portal.pages.update(two_pages_of_verified())
    chat, _ = run(telegram_bot.verified_date_command, "/verified_date 12 Sep 2026", ["12", "Sep", "2026"])
    text = report_of(chat)
    # Both 12 Sep students sit on page 2: the old page-1-only read said "No student payments".
    assert "Total Students Verified:* `2`" in text and "৳ 32,000.00 BDT" in text
    assert "TWELFTH SEPTEMBER ONE" in text and "TWELFTH SEPTEMBER TWO" in text
    assert student_reads(portal.asked) == ["students.php", "students.php?pg=2"]
    assert len(chat) == 1 and chat[0].edits == 1                               # the "⏳" note became the report


def test_a_day_is_matched_on_whole_tokens(portal):
    portal.pages.update(two_pages_of_verified())
    text = report_of(run(telegram_bot.verified_date_command, "/verified_date 8 Sep", ["8", "Sep"])[0])
    assert "Total Students Verified:* `1`" in text and "EIGHTH STUDENT" in text
    assert "EIGHTEENTH" not in text and "TWENTY EIGHTH" not in text             # 18 Sep, 28 Aug are not 8 Sep
    text = report_of(run(telegram_bot.verified_command, "/verified 27 Sep 2026", ["27", "Sep", "2026"])[0])
    assert "Total Students Verified:* `2`" in text and "৳ 28,000.00 BDT" in text
    assert "20,000.00 BDT Cash" in text and "8,000.00 BDT bKash" in text and "NOSHIN SAMAD (27 Sep, 17:06)" in text


def test_today_with_nobody_verified_says_none_only_after_every_page_was_read(portal):
    portal.pages.update(two_pages_of_verified())
    chat, _ = run(telegram_bot.verified_today_command, "/verified_today", [])
    assert chat.shown() == ["ℹ️ *No student payments were verified on 28 September 2026.*"]
    assert student_reads(portal.asked) == ["students.php", "students.php?pg=2"]


def test_a_day_a_year_back_is_not_available_not_this_years_students(portal):
    portal.pages.update(two_pages_of_verified())
    chat, _ = run(telegram_bot.verified_date_command, "/verified_date 27 Sep 2025", ["27", "Sep", "2025"])
    assert len(chat) == 1 and "not available" in chat[0].text and "cannot be told apart from 27 Sep 2026" in chat[0].text
    assert "RAHIM" not in chat[0].text and portal.asked == []
    chat, _ = run(telegram_bot.verified_date_command, "/verified_date 5 Oct 2026", ["5", "Oct", "2026"])
    assert "not available (a date in the future)" in chat[0].text


@pytest.mark.parametrize("failure", ["unreachable", "login page", "refused login", "no table", "no stamps",
                                     "unreadable stamp"])
def test_a_failed_read_is_never_reported_as_no_payments(portal, monkeypatch, failure):
    if failure == "unreachable":
        def down(request):
            raise httpx.ConnectError("unreachable", request=request)
        monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(down)))
    elif failure == "login page":                   # the session expired and cannot be renewed
        monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(always_login),
                                                                       follow_redirects=True))

        async def fresh_login(*args, **kwargs):
            admin_client.is_authenticated = True
            return {"success": True}
        monkeypatch.setattr(admin_client, "login", fresh_login)
    elif failure == "refused login":
        async def refused(*args, **kwargs):
            return {"success": False, "error": "simulated bad credentials"}
        monkeypatch.setattr(admin_client, "is_authenticated", False)
        monkeypatch.setattr(admin_client, "login", refused)
    elif failure == "no table":
        portal.pages["students.php"] = "<html><body>Scheduled maintenance</body></html>"
    elif failure == "no stamps":
        portal.pages["students.php"] = page(row(1, 1, "A"), row(2, 2, "B"))
    else:                                           # the stamp's date written a new way
        portal.pages["students.php"] = page(verified(1, 1, "A", "27 Sep, 10:00"), verified(2, 2, "B", "2026-09-28 10:00"))
    chat, _ = run(telegram_bot.verified_today_command, "/verified_today", [])
    text = report_of(chat)
    assert text.startswith("❌ Couldn't read the portal:") and "No student payments" not in text
    assert "Verified students for 28 September 2026: not available right now." in text
    reason = {"unreachable": "could not connect to the portal", "login page": "kept sending its login page",
              "refused login": "couldn't log in to the portal: simulated bad credentials",
              "no table": "no student table", "no stamps": "no 'Payment verified by' line",
              "unreadable stamp": "1 verification line(s) with a date the bot cannot read"}[failure]
    assert reason in text


def test_a_long_report_is_split_under_telegrams_limit(portal):
    rows = [verified(1000 + i, i, f"STUDENT NUMBER {i:02d} WITH A LONG FULL NAME", "23 Jul, 10:00",
                     program=BACHELOR, applied="20 Jul 2026") for i in range(1, 63)]
    portal.pages["students.php"] = page(*rows[:50], pg=1, pages=2, total=62)
    portal.pages["students.php?pg=2"] = page(*rows[50:], pg=2, pages=2, total=62)
    chat, _ = run(telegram_bot.verified_date_command, "/verified_date 23 Jul 2026", ["23", "Jul", "2026"])
    assert len(chat) > 1 and all(replies.telegram_len(m.text) <= replies.CHUNK_CHARS for m in chat)
    text = report_of(chat)
    assert "Total Students Verified:* `62`" in text and "৳ 1,240,000.00 BDT" in text
    assert all(f"STUDENT NUMBER {i:02d}" in text for i in range(1, 63))
    assert chat[0].edits == 1 and all(m.parse_mode == "Markdown" for m in chat)


def test_no_amount_or_method_is_ever_made_up(portal):
    portal.pages["students.php"] = page(
        row(1, 1, "NO AMOUNT ROW", by="LINA PARVIN", when="27 Sep, 09:00", applied="1 Sep 2026"),
        verified(2, 2, "PAID ROW", "27 Sep, 10:00", amount="8,000.00 BDT", method="bKash", applied="1 Sep 2026"))
    text = report_of(run(telegram_bot.verified_date_command, "/verified_date 27 Sep 2026", ["27", "Sep", "2026"])[0])
    assert "৳ 8,000.00 BDT` (the sum of the verified income; the 1 with an amount on the portal, 1 without)" in text
    assert "20,000" not in text and "*Payment:* `—`" in text
    only = page(row(1, 1, "NO AMOUNT ROW", by="LINA PARVIN", when="27 Sep, 09:00", applied="1 Sep 2026"))
    portal.pages["students.php"] = only
    text = report_of(run(telegram_bot.verified_date_command, "/verified_date 27 Sep 2026", ["27", "Sep", "2026"])[0])
    assert "Total Verified Revenue:* not available (no amount on the portal rows)" in text


def test_the_verified_date_prompt_and_its_typed_answer(portal):
    portal.pages.update(two_pages_of_verified())
    chat, context = run(telegram_bot.verified_date_command, "/verified_date", [])
    prompt = chat[0].text
    assert context.user_data["awaiting_date_for"] == "verified"
    assert "(e.g. `12 Sep 2026`, `yesterday` or `2026-09-12`)" in prompt and "_(" not in prompt
    chat, _ = run(telegram_bot.handle_natural_language_message, "12 Sep 2026", None, context.user_data)
    assert "Total Students Verified:* `2`" in report_of(chat)


@pytest.mark.parametrize("said, expect", [
    ("Total verified students today", "No student payments were verified on 28 September 2026"),
    ("verified students 27 sep", "Student Payment Verifications — 27 September 2026"),
    ("how many students were verified on the 12th of September", "Student Payment Verifications — 12 September 2026"),
    ("how many students got verified", "No student payments were verified on 28 September 2026"),
    ("verified students separately", "No student payments were verified on 28 September 2026"),
    ("who was verified in sep", "couldn't read"),
    ("verified students on 31 Sep", "couldn't read"),
])
def test_free_text_verified_questions(portal, said, expect):
    portal.pages.update(two_pages_of_verified())
    chat, _ = run(telegram_bot.handle_natural_language_message, said, None)
    assert expect in report_of(chat)


def test_the_verified_reader_itself(portal):
    portal.pages.update(two_pages_of_verified())
    got = asyncio.run(admin_client.get_verified_students(date(2026, 9, 27)))
    assert [(g["uid"], g["name"], g["amount"], g["method"], g["verified_by"], g["verified_time"]) for g in got] == [
        ("917", "RAHIM UDDIN", "20,000.00 BDT", "Cash", "MAHIRA JANAN", "27 Sep, 17:19"),
        ("916", "NUSRAT JAHAN", "8,000.00 BDT", "bKash", "NOSHIN SAMAD", "27 Sep, 17:06")]
    with pytest.raises(ValueError):
        asyncio.run(admin_client.get_verified_students("31 Sep 2026"))
    # Verified "27 Sep" but applied on 28 Sep: another year's stamp, never counted for 27 Sep 2026.
    portal.pages["students.php"] = page(verified(9, 1, "LATE", "27 Sep, 10:00", applied="28 Sep 2026"))
    portal.pages.pop("students.php?pg=2")
    assert asyncio.run(admin_client.get_verified_students(date(2026, 9, 27))) == []


# --------------------------------------------------------------------------- /admitted and /students

def admitted_portal(portal, admitted_tile=1):
    portal.pages.update({
        "index.php": dashboard(admitted_tile),
        "students.php": page(
            row(10, 1, "KIM SEOYEON", hng="HNG-2026-901", intake="SEPTEMBER 2027"),
            row(11, 2, "KARIM MIA", hng="HNG-2026-902", uni="HANYANG UNIVERSITY", stage="Documents Verified"),
            pg=1, pages=2, total=4),
        "students.php?pg=2": page(
            row(12, 3, "RAHMAN KIM ADMITTED", hng="HNG-2026-903", uni="HANYANG UNIVERSITY", program=BACHELOR,
                stage="Admitted / Completed", intake="MARCH 2027"),
            row(13, 4, "ALAM TUITION", hng="HNG-2026-904", stage="Admission & Tuition"),
            pg=2, pages=2, total=4)})


@pytest.mark.parametrize("query, shown, absent", [
    (None, ["`1` — 1 of the 4 students on the portal is at the stage “Admitted / Completed”", "RAHMAN KIM ADMITTED",
            "`HNG-2026-903`", "HANYANG UNIVERSITY", "MARCH 2027", "The dashboard's Admitted tile says 1 too."],
     ["KIM SEOYEON", "KARIM MIA", "ALAM TUITION", "Pending Allocation", "March 2027"]),
    ("Kim", ["RAHMAN KIM ADMITTED", "Matching* “Kim”: `1`"], ["KIM SEOYEON"]),
    ("HANYANG UNIVERSITY", ["RAHMAN KIM ADMITTED"], ["KARIM MIA"]),
    ("bachelor", ["RAHMAN KIM ADMITTED"], []),
    ("KLP", ["No admitted students match “KLP”.", "1 of the 4 students"], ["RAHMAN"]),
    ("Admission & Tuition", ["No admitted students match “Admission & Tuition”."], ["ALAM"]),
])
def test_admitted_is_picked_by_stage_from_every_page(portal, query, shown, absent):
    admitted_portal(portal)
    chat, _ = run(telegram_bot.admitted_command, "/admitted", query.split() if query else [])
    text = report_of(chat)
    for part in shown:
        assert part in text, part
    for part in absent:
        assert part not in text, part
    # The portal ignores ?status=admitted; nothing of the query goes into a URL.
    assert student_reads(portal.asked) == ["students.php", "students.php?pg=2"]
    assert len(chat) == 1 and chat[0].edits == 1


def test_no_admitted_students_is_said_plainly_and_derived_from_the_rows(portal):
    admitted_portal(portal, admitted_tile=0)
    portal.pages["students.php?pg=2"] = page(row(12, 3, "NOT YET", stage="Visa Result"),
                                             row(13, 4, "ALAM TUITION", stage="Admission & Tuition"), pg=2, pages=2, total=4)
    text = report_of(run(telegram_bot.admitted_command, "/admitted", [])[0])
    assert text.startswith("ℹ️ *No admitted students on the portal right now.*")
    assert "0 of the 4 students on the portal are at the stage “Admitted / Completed”" in text
    assert "The dashboard's Admitted tile says 0 too." in text
    text = report_of(run(telegram_bot.admitted_command, "/admitted Kim", ["Kim"])[0])
    assert "No admitted students match “Kim”:* no student on the portal is admitted right now." in text


def test_a_dashboard_that_disagrees_is_shown_and_its_stage_is_used(portal):
    admitted_portal(portal, admitted_tile=5)
    text = report_of(run(telegram_bot.admitted_command, "/admitted", [])[0])
    assert "⚠️ The dashboard's Admitted tile says 5, but the student list shows 1 at that stage." in text
    portal.pages["index.php"] = dashboard(1, href="students.php?stage=Admission+%26+Tuition")
    got = asyncio.run(admin_client.get_admitted_students())
    assert got["stage"] == "Admission & Tuition" and [s["student_name"] for s in got["students"]] == ["ALAM TUITION"]
    portal.pages.pop("index.php")                                               # no dashboard: the known stage
    got = asyncio.run(admin_client.get_admitted_students())
    assert got["stage"] == parsers.ADMITTED_STAGE and got["tile"] is None and got["admitted"] == 1


def test_admitted_says_when_the_portal_cannot_be_read(portal):
    portal.pages["index.php"] = dashboard(0)
    text = report_of(run(telegram_bot.admitted_command, "/admitted", [])[0])
    assert text.startswith("❌ Couldn't read the portal: students.php: the portal answered HTTP 404")
    assert "Admitted students: not available right now." in text


@pytest.mark.parametrize("said, query", [
    ("who is admitted to hanyang?", "hanyang"), ("how many students are admitted", None),
    ("show admitted KLP students", "klp"),
])
def test_free_text_admitted_questions(portal, said, query):
    admitted_portal(portal)
    seen = []

    async def get_admitted_students(query=None):
        seen.append(query)
        return {"students": [], "admitted": 0, "checked": 4, "stage": parsers.ADMITTED_STAGE, "tile": 0, "query": query}
    portal_admitted = admin_client.get_admitted_students
    try:
        admin_client.get_admitted_students = get_admitted_students
        run(telegram_bot.handle_natural_language_message, said, None)
    finally:
        admin_client.get_admitted_students = portal_admitted
    assert seen == [query]


def test_students_shows_the_real_columns_or_why_it_could_not(portal):
    admitted_portal(portal)
    text = report_of(run(telegram_bot.students_command, "/students", [])[0])
    assert "*KIM SEOYEON* (SEPTEMBER 2027)" in text and "*Univ:* HANYANG UNIVERSITY | *Status:* `Documents Verified`" in text
    assert "*Univ:* — |" in text and "Pending Allocation" not in text and "HNG-SL" not in text
    assert student_reads(portal.asked) == ["students.php"]                      # the newest page only
    portal.pages.clear()
    text = report_of(run(telegram_bot.students_command, "/students", [])[0])
    assert text.startswith("❌ Couldn't read the portal:") and "The student list: not available" in text
