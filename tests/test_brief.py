"""The factual daily brief (src/bot/brief.py) and the readers behind it.

Every figure in the brief comes from a portal page read in code, so these tests feed synthetic
copies of the portal's pages (consult_requests.php, students.php and its pages, the pending list,
window_applications.php, index.php, calendar.php) through an httpx.MockTransport, and check the
brief counts them exactly, says "not available" when a page cannot be read (never a stand-in
number or a made-up section), keeps pending payments and window applications apart, escapes
portal text for Telegram Markdown with a plain-text fallback, splits long briefs between lines,
and only shows an LLM summary whose every number is in the facts. Nothing reaches the network.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_brief.py -q
"""
import asyncio
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from telegram.error import BadRequest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

from src.config import settings  # noqa: E402
from src.bot import brief, scheduler, telegram_bot, voice  # noqa: E402
from src.llm.ollama_client import ollama_client  # noqa: E402
from src.scraper import parsers  # noqa: E402
from src.scraper.client import admin_client  # noqa: E402
from test_consultations import _page as consult_page, _row as consult_row  # noqa: E402

NOW = datetime(2026, 9, 28, 18, 5, tzinfo=ZoneInfo("Asia/Dhaka"))
ADMIN_ID = 111111111


# --------------------------------------------------------------------------- synthetic portal pages

STUDENTS_HEAD = ("<tr><th></th><th>SL</th><th>Student</th><th>University</th><th>Program · Intake</th>"
                 "<th>Docs</th><th>Payment</th><th>Stage · Applied</th><th></th></tr>")


def student(uid, sl, name, program, paid="", method="", income="", by="", when=""):
    """One students.php entry as the portal lays it out: a .stu-row and its .xp-row details."""
    pay = f"Paid: {paid} {method} " if paid else ""
    pay += f"Verified income: {income} " if income else ""
    pay += f"Payment verified by {by} · {when}" if by else ""
    return (f'<tr class="stu-row"><td></td><td>{sl}</td><td>{name} [email&#160;protected]</td><td>—</td>'
            f"<td>{program}</td><td>All Missing</td><td>Verified</td><td>Applied</td><td></td></tr>"
            '<tr class="xp-row"><td colspan="9">'
            f"<div>Full Name {name} DOB 2000-01-01 Gender MALE</div>"
            f"<div>Program {program} Preferred University —</div>"
            f"<div>{pay}</div>"
            f'<a href="student_edit.php?id={uid}">Edit</a></td></tr>')


def students_page(*rows, page=1, pages=1, pending_badge=None):
    badge = (f'<a href="students.php?status=pending">Pending Payments <span class="badge">{pending_badge}</span></a>'
             if pending_badge is not None else "")
    return (f"<html><body><nav>{badge}</nav><table>{STUDENTS_HEAD}{''.join(rows)}</table>"
            f"<div class='pager'>Page {page} of {pages}</div></body></html>")


def window_page(*statuses):
    head = ("<tr><th></th><th>Student</th><th>Window</th><th>Status</th><th>Docs</th><th>Submitted</th>"
            "<th>Updated</th><th>Actions</th></tr>")
    rows = "".join(f'<tr><td></td><td>Student {i}</td><td>Window {i}</td><td><span class="status-pill s-{s}">{s}'
                   f"</span></td><td>3/5</td><td>20 Sep</td><td>27 Sep</td><td><a>View</a></td></tr>"
                   for i, s in enumerate(statuses)) or '<tr><td colspan="8">No applications found.</td></tr>'
    return f"<table>{head}{rows}</table>"


def tile(href, num, label):
    return (f'<a class="stat-card kpi" href="{href}"><span class="kpi-ic"><i></i></span><span class="kpi-txt">'
            f'<span class="stat-num">{num}</span><span class="stat-lbl">{label}</span></span></a>')


def dash_sec(title):
    return f'<div class="dash-sec"><div class="ds-txt"><h2 class="ds-t">{title}</h2><p class="ds-s">about it</p></div></div>'


INDEX = ('<div class="dash">' + dash_sec("Admissions flow") + '<div class="stats-row">'
         + tile("admission_windows.php?status=active", 3, "Open windows")
         + tile("admission_windows.php?status=draft", 0, "Draft windows")
         + tile("window_applications.php?status=submitted", 1, "Submitted apps")
         + tile("window_applications.php?status=under_review", 1, "Under review")
         + tile("review_queue.php", 44, "Docs to review")
         + tile("window_applications.php?status=accepted", 3, "Accepted") + "</div>"
         + dash_sec("Direct / legacy pipeline") + '<div class="stats-row">'
         + tile("students.php", 330, "Total students")
         + tile("students.php?status=pending", 2, "Pending payment")
         + tile("students.php?status=verified", 328, "Verified")
         + tile("students.php?filter_docs=unverified", 11, "Docs to review")
         + tile("students.php?stage=Admitted+%2F+Completed", 0, "Admitted") + "</div></div>")


def reminder(title, kind, sub, progress=None, note=None, today=False):
    """One "Reminders for today" entry, laid out like calendar.php (Sep 2026)."""
    colour = "#7c3aed" if kind == "DHL to send" else "#1565c0"
    today_tag = '<span style="color:#116329;font-weight:700">· today</span>' if today else ""
    bar = ('<div style="margin-top:6px"><div style="height:6px;background:#eef1f5;border-radius:100px">'
           '<div style="height:100%;width:64%;background:#dc2626"></div></div>'
           f'<div style="font-size:10.5px;color:#dc2626;font-weight:700;margin-top:3px">{progress}</div></div>'
           if progress else "")
    extra = f'<div style="font-size:11.5px;color:#475569;margin-top:2px">{note}</div>' if note else ""
    return ('<div class="rm-item"><span style="width:32px;height:32px"><i class="fas fa-calendar-days"></i></span>'
            '<div style="flex:1;min-width:0">'
            f'<a class="rm-title" href="calendar.php?ym=2026-09&amp;view=month&amp;edit=1">{title}</a>'
            f'<div style="font-size:11.5px;color:#64748b;margin-top:2px"><span style="color:{colour};font-weight:700">'
            f"{kind}</span> {sub} {today_tag}</div>{bar}{extra}</div>"
            '<form style="flex:none;margin:0"><input type="hidden" name="id" value="1">'
            '<button class="rm-done"><i class="fas fa-check"></i> Complete</button></form></div>')


def calendar_page(*items, stated=None):
    stated = len(items) if stated is None else stated
    upcoming = ('<div class="ev-row"><div class="li-date" style="width:40px"><div class="d">1</div><div class="w">Sep</div>'
                '</div><span class="ev-ic"><i></i></span><div class="ev-main">'
                '<a class="ev-title" href="calendar.php?edit=7">Beta University- APPLICATION OPEN</a>'
                '<div class="ev-sub"><span style="color:#1565c0;font-weight:700">Application period</span>'
                " · 01 Sep – 09 Oct 2026 · Beta University</div>"
                '<div style="font-size:11.5px;color:#475569;margin-top:2px">EAP PROGRAM</div></div>'
                '<span class="st ok">Closes in 11 days</span><div class="acts"><form><button class="ib ok">'
                "</button></form></div></div>")
    modal = ('<div class="rm-modal"><div class="rm-box"><div class="rm-head"><b>Reminders for today</b></div>'
             '<div class="rm-list"><a class="rm-row" href="calendar.php?edit=1"><div><div class="rm-t">Copy</div>'
             '<div class="rm-s"><span>DHL to send</span> · 26 Sep–28 Sep</div></div></a></div></div></div>')
    return ('<div class="cal-layout"><div style="min-width:0">'
            '<div class="cal-card" style="padding:16px"><div class="cal-grid"><a class="cal-bar s">'
            '<span class="t">ALPHA UNIVERSITY</span></a></div></div>'
            f'<div class="cal-card"><div class="sec-h"><i class="fas fa-bell"></i>Reminders for today'
            f"<small>· Monday, 28 Sep 2026 · {stated} items</small></div>{''.join(items)}</div>"
            '<div class="cal-card"><div class="sec-h">Completed <small>· 1 item</small></div>'
            '<div class="done-list"><div class="done-item"><div class="done-title">Old DHL</div></div></div></div>'
            f'<div class="cal-card"><div class="sec-h">Upcoming <small>· next 45 days</small></div><div>{upcoming}</div></div>'
            "</div><aside><div class=\"cal-card\"><div class=\"sb-h\">At a glance</div></div></aside></div>" + modal)


REMINDERS = (
    reminder("Alpha University DHL", "DHL to send", "· 26 Sep–28 Sep · 14:00 · Alpha University"),
    reminder("Gamma University - Application open", "Application period", "· 21 Sep–02 Oct · 14:00 · Gamma University",
             progress="64% of window elapsed · 4 days left", note="EAP PROGRAM"),
    reminder("SEJONG *UNIVERSITY*", "Application period", "· 28 Sep–12 Oct · 12:49 · Sejong",
             progress="0% elapsed · 14 days left", note="Send the documents by DHL.", today=True),
    reminder("", "DHL to send", "· 26 Sep–28 Sep · 14:00 · Nowhere"),          # no title: dropped
)

CONSULTS = consult_page(
    consult_row("Student A", "Consulted", "28 Sep 2026", by="Lina_Parvin"),
    consult_row("Student B", "Consulted", "28 Sep 2026", by="Lina_Parvin"),
    consult_row("Student C", "File Opened", "28 Sep 2026", by="Sadia"),
    consult_row("Student D", "New", "28 Sep 2026"),
    consult_row("Student E", "No Answer", "28 Sep 2026"),
    consult_row("Student F", "Wrong Number", "28 Sep 2026"),
    consult_row("Student G", "No Answer", "28 Sep 2026"),
    consult_row("Student H", "Consulted", "27 Sep 2026", by="Sadia"),
    consult_row("Student I", "New", "27 Sep 2026"),
)

KLP = "KOREAN LANGUAGE PROGRAM (KLP)"
VERIFIED_X = student(501, 330, "RAHIM UDDIN", KLP, "20,000.00 BDT", "Cash", "20,000.00 BDT",
                     "MAHIRA JANAN", "28 Sep, 10:15")


def full_portal():
    return {
        "consult_requests.php": CONSULTS,
        "students.php": students_page(
            VERIFIED_X,
            student(500, 329, "KARIM MIA", KLP, "20,000.00 BDT", "bKash", "20,000.00 BDT", "MAHIRA JANAN", "27 Sep, 17:19"),
            page=1, pages=2, pending_badge=2),
        "students.php?pg=2": students_page(
            VERIFIED_X,                                    # shifted onto page 2 while reading: counted once
            student(350, 280, "NUSRAT JAHAN", "BACHELOR'S DEGREE", "8,000.00 BDT", "bKash", "8,000.00 BDT",
                    "NOSHIN SAMAD", "28 Sep, 11:40"),
            page=2, pages=2, pending_badge=2),
        "students.php?status=pending": students_page(
            student(530, 332, "PENDING ONE", KLP), student(529, 331, "PENDING TWO", KLP), pending_badge=2),
        "window_applications.php?status=under_review": window_page("under_review", "accepted"),
        "index.php": INDEX,
        "calendar.php": calendar_page(*REMINDERS),
    }


# --------------------------------------------------------------------------- fixtures

class FakeBrain:
    """Stands in for ollama_client.chat: records each call, answers with `reply`."""

    def __init__(self):
        self.reply = None
        self.calls = []

    async def chat(self, messages, format=None, num_predict=None, timeout=None):
        self.calls.append({"system": messages[0]["content"], "user": messages[-1]["content"],
                           "num_predict": num_predict})
        return self.reply


@pytest.fixture
def portal(monkeypatch, tmp_path):
    """The portal as a dict of page -> HTML (a missing page answers 404), a fixed 'now' in Dhaka,
    a temporary document-check store, and a brain that says nothing unless told to."""
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
    monkeypatch.setattr(brief, "_now", lambda: NOW)
    monkeypatch.setattr(settings, "VERIFICATION_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "TELEGRAM_ADMIN_CHAT_ID", str(ADMIN_ID))
    brain = FakeBrain()
    monkeypatch.setattr(ollama_client, "chat", brain.chat)
    return SimpleNamespace(pages=pages, asked=asked, brain=brain, store=tmp_path / "results.json")


def write_store(path):
    docs = {"P1": {"verdict": "FAIL", "checked": "2026-09-28T11:55:00"},
            "P2": {"verdict": "FAIL", "checked": "2026-09-27T10:00:00"},
            "P3": {"verdict": "REVIEW", "checked": "2026-09-26T09:00:00"},
            "P4": {"verdict": "PASS", "checked": "2026-09-25T09:00:00"}}
    path.write_text(json.dumps({"documents": docs, "fields": {}, "corrections": []}), encoding="utf-8")


def compose(**kwargs):
    return asyncio.run(brief.compose_daily_brief(**kwargs))


def section(text, number):
    """The lines of section `number` ("1) ..." up to the next blank line)."""
    lines = text.split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith(f"*{number})"))
    end = next((i for i in range(start, len(lines)) if not lines[i].strip()), len(lines))
    return lines[start:end]


class FakeBot:
    def __init__(self, refuse_markdown=False, error="Can't parse entities: can't find end of the entity"):
        self.messages = []
        self.refuse_markdown = refuse_markdown
        self.error = error

    async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
        if parse_mode == "Markdown" and self.refuse_markdown:
            raise BadRequest(self.error)
        self.messages.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
        return SimpleNamespace(message_id=len(self.messages))


# --------------------------------------------------------------------------- the brief's figures

def test_every_count_is_exact(portal):
    portal.pages.update(full_portal())
    write_store(portal.store)
    text = compose()

    assert text.split("\n")[0] == "📋 *HANGEUL DAILY BRIEF* — 28 September 2026, 18:05 (Asia/Dhaka)"
    assert section(text, 1) == [
        "*1) CONSULTATIONS TODAY*",
        "• Received: 7  |  Done: 3 (2 consulted, 1 file opened)",
        "• New / pending: 1  |  No answer: 2  |  Wrong number: 1",
        "• Done by: Lina\\_Parvin 2, Sadia 1",
        "• The latest 9 requests on the page, 27 Sep–28 Sep 2026: 4 done, 2 new, 2 no answer, 1 wrong number",
    ]
    assert section(text, 2) == [
        "*2) PAYMENT-VERIFIED STUDENTS TODAY*",
        "• 2 students  |  Total: 28,000.00 BDT",
        "  1. RAHIM UDDIN — KOREAN LANGUAGE PROGRAM (KLP) — 20,000.00 BDT Cash — verified by MAHIRA JANAN at 10:15",
        "  2. NUSRAT JAHAN — BACHELOR'S DEGREE — 8,000.00 BDT bKash — verified by NOSHIN SAMAD at 11:40",
    ]
    assert section(text, 3) == [
        "*3) PORTAL FIGURES (live now)*",
        "• Pending payments: 2 (students.php?status=pending)",
        "• Window applications under review: 1 (window\\_applications.php)",
        "  _(two separate figures, never added together)_",
        "• Dashboard, Admissions flow: Open windows 3 · Draft windows 0 · Submitted apps 1 · Docs to review 44 · Accepted 3",
        "• Dashboard, Direct / legacy pipeline: Total students 330 · Verified 328 · Docs to review 11 · Admitted 0",
    ]
    assert section(text, 4) == [
        "*4) TODAY'S CALENDAR REMINDERS*",
        "• 3 reminders: Application period 2, DHL to send 1",
        "  (1 entry without a title skipped)",
        "  - Alpha University DHL — DHL to send — 26 Sep–28 Sep",
        "  - Gamma University - Application open — Application period — 21 Sep–02 Oct — 4 days left",
        "  - SEJONG \\*UNIVERSITY\\* — Application period — 28 Sep–12 Oct — 14 days left",
    ]
    assert section(text, 5) == [
        "*5) DOCUMENT CHECK (from the last automated check, not live)*",
        "• 4 students: FAIL 2, REVIEW 1, PASS 1",
        "• Last check: 28 Sep 2026, 11:55",
    ]
    assert "Summary" not in text                     # the brain said nothing: no summary line
    assert all(method == "GET" for method, _ in portal.asked)
    assert ("GET", "students.php?pg=2") in portal.asked     # every page of the student list


def test_missing_data_says_not_available_and_invents_nothing(portal):
    # Every page answers 404, there is no document-check store, and the brain is down.
    text = compose()
    for number in range(1, 6):
        body = section(text, number)[1:]
        assert body and all("not available" in line or line.startswith("  _(") for line in body), body
        for line in body:
            assert not re.search(r"\d", line), line          # not one stand-in number
    for invented in ("visa", "passport", "conversion", "intake", "prepared by", "ytd", "%"):
        assert invented not in text.lower()
    assert "Summary" not in text


def test_nothing_today_says_none_not_zero_rows(portal):
    pages = full_portal()
    pages["consult_requests.php"] = consult_page(consult_row("Old", "New", "20 Sep 2026"))
    pages["students.php"] = students_page(page=1, pages=1)
    pages["calendar.php"] = calendar_page()
    portal.pages.update(pages)
    text = compose()
    assert section(text, 1)[1] == "• None received today"
    assert section(text, 2) == ["*2) PAYMENT-VERIFIED STUDENTS TODAY*", "• None today"]
    assert section(text, 4) == ["*4) TODAY'S CALENDAR REMINDERS*", "• None today"]


def test_unreadable_calendar_is_not_available_not_counted(portal):
    pages = full_portal()
    pages["calendar.php"] = calendar_page(reminder("", "DHL to send", "· 26 Sep"), reminder("", "Other", "· 27 Sep"))
    portal.pages.update(pages)
    assert section(compose(), 4)[1] == "• not available (the page lists 2 but none could be read)"
    pages["calendar.php"] = "<div class='new-layout'>Reminders</div>"
    portal.pages.update(pages)
    assert section(compose(), 4)[1] == "• not available (the calendar page's layout was not recognised)"


def test_pending_payments_and_window_applications_are_never_summed(portal):
    portal.pages.update(full_portal())
    portal.brain.reply = "Two payments are pending."
    text = compose()
    part = section(text, 3)
    pending = [line for line in part if line.startswith("• Pending payments:")]
    review = [line for line in part if line.startswith("• Window applications under review:")]
    assert pending == ["• Pending payments: 2 (students.php?status=pending)"]
    assert review == ["• Window applications under review: 1 (window\\_applications.php)"]
    assert not any("3" in line for line in pending + review)
    # The dashboard tiles for the same two figures are not repeated as one more line either.
    assert not any("Pending payment " in line or "Under review " in line for line in part)
    # The facts the LLM sees keep them apart too.
    facts = portal.brain.calls[0]["user"]
    assert "- Pending payments: 2\n" in facts
    assert "- Window applications under review (a separate figure): 1" in facts
    assert "never combine" in portal.brain.calls[0]["system"]


def test_a_dashboard_tile_that_disagrees_is_shown_not_hidden(portal):
    pages = full_portal()
    pages["index.php"] = INDEX.replace(">2</span><span class=\"stat-lbl\">Pending payment", ">3</span><span class=\"stat-lbl\">Pending payment")
    del pages["window_applications.php?status=under_review"]
    portal.pages.update(pages)
    part = section(compose(), 3)
    assert part[1] == "• Pending payments: 2 (students.php?status=pending); the dashboard tile says 3"
    assert part[2] == "• Window applications under review: 1 (dashboard tile; window\\_applications.php could not be read)"


def test_a_past_day_counts_that_day_and_skips_the_calendar(portal):
    portal.pages.update(full_portal())
    text = compose(day=date(2026, 9, 27))
    assert text.startswith("📋 *HANGEUL BRIEF FOR 27 September 2026* — read 28 Sep 2026, 18:05")
    assert section(text, 1)[:2] == ["*1) CONSULTATIONS ON 27 SEP 2026*",
                                    "• Received: 2  |  Done: 1 (1 consulted, 0 file opened)"]
    assert section(text, 2)[1] == "• 1 student  |  Total: 20,000.00 BDT"
    assert section(text, 4)[1].startswith("• shown for today only")
    assert ("GET", "calendar.php") not in portal.asked


# --------------------------------------------------------------------------- the LLM summary

FACTS = ("- Consultation requests received today: 7\n- Consultations done today: 3 (3 consulted, 0 file opened)\n"
         "- Students whose payment was verified today: 2, together 28,000.00 BDT\n- Pending payments: 2")


@pytest.mark.parametrize("said, kept", [
    ("Seven requests came in today and 3 were done.", "Seven requests came in today and 3 were done."),
    ("**Two** payments were verified today, worth 28,000 BDT.", "Two payments were verified today, worth 28,000 BDT."),
    ("Summary: 7 requests, 3 done. Two payments verified. A third sentence 2.", "7 requests, 3 done. Two payments verified."),
    ("Conversion rate is 28.4% today.", None),              # a rate the facts never had
    ("Visas approved: 3.", None),                           # a topic the brief never reports
    ("Twelve requests came in today.", None),               # a number word not in the facts
    ("One student paid.", None),                            # a lone "one": 1 is not in these facts
    ("About a dozen requests today.", None),                # a vague number word
    ("5 requests are waiting.", None),                      # 2 + 3 added up
    ("", None),
    (None, None),
    ("7 requests came in and " * 20 + "3 were done.", None),  # one sentence, far too long
])
def test_the_summary_keeps_only_numbers_from_the_facts(said, kept):
    assert brief.check_summary(said, FACTS) == kept


def test_a_checked_summary_is_added_and_an_invented_one_dropped(portal):
    portal.pages.update(full_portal())
    portal.brain.reply = "Seven requests came in today and 3 were done; 2 payments were verified."
    text = compose()
    assert text.split("\n")[-1] == ("🤖 _Summary by the local AI, its numbers checked against the facts:_ "
                                    "Seven requests came in today and 3 were done; 2 payments were verified.")
    call = portal.brain.calls[0]
    assert call["num_predict"] == brief.SUMMARY_MAX_TOKENS
    assert len(call["system"]) + len(call["user"]) < 2500          # a small prompt: the facts only
    assert "RAHIM" not in call["user"]                             # no student names in the prompt

    portal.brain.reply = "Seven requests came in and the conversion rate was 42%."
    assert "Summary" not in compose()
    portal.brain.reply = "We had 9 requests today."                # 9 is only in the all-time line
    assert "Summary" not in compose()
    portal.brain.reply = None                                      # the brain is down
    assert "Summary" not in compose()
    assert compose(with_summary=False).count("\n") > 10


# --------------------------------------------------------------------------- Telegram

def unbalanced_markdown(text):
    """Lines whose unescaped * or _ markers do not pair up (Telegram would refuse the message)."""
    bad = []
    for line in text.split("\n"):
        bare = re.sub(r"\\[_*`\[]", "", line)
        if bare.count("*") % 2 or bare.count("_") % 2 or "`" in bare or "[" in bare:
            bad.append(line)
    return bad


def test_markdown_escaping_with_a_plain_text_fallback(portal):
    portal.pages.update(full_portal())
    portal.brain.reply = "Seven requests came in today and 3 were done."
    text = compose()
    assert "Lina\\_Parvin" in text and "SEJONG \\*UNIVERSITY\\*" in text
    assert unbalanced_markdown(text) == []
    assert unbalanced_markdown(compose(day=date(2026, 9, 27))) == []
    portal.pages.clear()
    assert unbalanced_markdown(compose()) == []                    # the "not available" brief too
    portal.pages.update(full_portal())

    bot = FakeBot()
    assert asyncio.run(brief._send_brief(bot, ADMIN_ID, text)) == 1
    assert bot.messages == [{"chat_id": ADMIN_ID, "text": text, "parse_mode": "Markdown"}]

    refused = FakeBot(refuse_markdown=True)
    asyncio.run(brief._send_brief(refused, ADMIN_ID, text))
    plain = refused.messages[0]
    assert plain["parse_mode"] is None and plain["text"] == brief.brief_plain(text)
    assert "Lina_Parvin" in plain["text"] and "SEJONG *UNIVERSITY*" in plain["text"]
    assert "\\" not in plain["text"] and "*1) CONSULTATIONS" not in plain["text"]
    assert "1) CONSULTATIONS TODAY" in plain["text"]

    other = FakeBot(refuse_markdown=True, error="Chat not found")
    with pytest.raises(BadRequest):                                # not a parse error: not hidden
        asyncio.run(brief._send_brief(other, ADMIN_ID, text))


def test_a_long_brief_is_split_between_lines():
    lines = [f"  - Reminder {i:03d} — Application period — 21 Sep–02 Oct — {i} days left" for i in range(300)]
    text = "\n".join(lines)
    chunks = brief.split_brief(text)
    assert len(chunks) > 1 and all(len(c) <= brief.CHUNK_CHARS < 4096 for c in chunks)
    assert "\n".join(chunks) == text                               # nothing lost, no line cut
    assert all(c.split("\n")[0] in lines and c.split("\n")[-1] in lines for c in chunks)

    words = " ".join(f"word{i}" for i in range(1500))              # one very long line: cut at spaces
    pieces = brief.split_brief(words)
    assert all(len(p) <= brief.CHUNK_CHARS for p in pieces) and " ".join(pieces) == words

    bot = FakeBot()
    assert asyncio.run(brief._send_brief(bot, ADMIN_ID, text)) == len(chunks)
    assert [m["text"] for m in bot.messages] == chunks


# --------------------------------------------------------------------------- the 18:05 job, /brief, /report

def test_the_daily_job_sends_the_factual_brief_then_the_spoken_one(portal, monkeypatch):
    portal.pages.update(full_portal())
    spoken = []

    async def send_spoken_brief(bot, chat_id, brief_text):
        spoken.append((chat_id, brief_text))
        return True

    monkeypatch.setattr(voice, "send_spoken_brief", send_spoken_brief)
    monkeypatch.setattr(settings, "JENNIE_VOICE_ENABLED", True)
    monkeypatch.setattr(settings, "JENNIE_SPOKEN_BRIEF", True)
    bot = FakeBot()
    asyncio.run(scheduler.send_daily_briefing(SimpleNamespace(bot=bot)))

    assert len(bot.messages) == 1 and bot.messages[0]["parse_mode"] == "Markdown"
    assert bot.messages[0]["text"].startswith("📋 *HANGEUL DAILY BRIEF*")
    assert "• Received: 7" in bot.messages[0]["text"]
    # Jennie gets the brief's facts, one figure a line: not the dates, clock times, tile figures or
    # all-time counts of the full text, which would let her say a number about the wrong thing.
    assert len(spoken) == 1 and spoken[0][0] == str(ADMIN_ID)
    said_from = spoken[0][1].split("\n")
    assert said_from[:2] == ["Consultation requests received today: 7", "Consultations done today: 3"]
    assert "Pending payments: 2" in said_from and "Calendar reminders for today: 3" in said_from
    for absent in ("28 Sep", "18:05", "330", "328", "44", "latest", "*", "DAILY BRIEF"):
        assert absent not in spoken[0][1], absent

    # A brief that cannot be composed sends nothing, and nothing is spoken.
    async def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "compose_brief", broken)
    bot, spoken[:] = FakeBot(), []
    asyncio.run(scheduler.send_daily_briefing(SimpleNamespace(bot=bot)))
    assert bot.messages == [] and spoken == []


class FakeMessage:
    def __init__(self, chat):
        self.chat = chat

    async def reply_text(self, text, parse_mode=None, **kwargs):
        self.chat.append({"text": text, "parse_mode": parse_mode})
        return SimpleNamespace(delete=self._delete)

    async def _delete(self):
        self.chat.append({"deleted": True})


def fake_update(chat, args=None):
    update = SimpleNamespace(message=FakeMessage(chat), effective_chat=SimpleNamespace(id=ADMIN_ID),
                             effective_user=SimpleNamespace(id=ADMIN_ID))
    context = SimpleNamespace(bot=FakeBot(), args=args, user_data={})
    return update, context


def test_brief_command_no_longer_fails_its_import(portal, monkeypatch):
    from src.bot.scheduler import _send_brief, compose_daily_brief       # the names /brief imports
    assert compose_daily_brief is brief.compose_daily_brief and _send_brief is brief._send_brief

    portal.pages.update(full_portal())
    chat = []
    update, context = fake_update(chat)
    asyncio.run(telegram_bot.brief_command(update, context))
    assert not any("Failed to compile brief" in m.get("text", "") for m in chat)
    assert len(context.bot.messages) == 1 and "• Received: 7" in context.bot.messages[0]["text"]
    assert {"deleted": True} in chat                                     # the "⏳ Reading…" note


def test_report_command_uses_the_factual_brief_as_a_reply(portal, monkeypatch):
    asked = []

    async def compose_daily_brief(day=None, with_summary=True):
        asked.append(day)
        return "📋 *HANGEUL BRIEF FOR 27 September 2026*\n*1) CONSULTATIONS ON 27 SEP 2026*\n• Received: 2"

    monkeypatch.setattr(brief, "compose_daily_brief", compose_daily_brief)
    chat = []
    update, context = fake_update(chat, args=["27", "Sep", "2026"])
    asyncio.run(telegram_bot.report_command(update, context))
    assert asked == [date(2026, 9, 27)]
    replies = [m for m in chat if "text" in m and m["text"].startswith("📋")]
    assert len(replies) == 1 and replies[0]["parse_mode"] == "Markdown"
    assert "Received: 2" in replies[0]["text"]
    assert {"deleted": True} in chat
    assert context.bot.messages == []           # a reply (the voice path captures replies), not a new message


# --------------------------------------------------------------------------- the dashboard reader

def test_dashboard_tiles_are_read_whatever_their_case_and_spacing():
    html = INDEX.replace(">Total students<", ">TOTAL   Students<").replace(">Pending payment<", ">pending Payments<")
    d = parsers.parse_hangeul_live_dashboard(html)
    s = d["summary"]
    assert s["total_students"] == s["total_applicants"] == 330
    assert s["pending_payment"] == 2 and s["window_apps_under_review"] == 1
    assert s["verified_students"] == 328 and s["admitted"] == 0
    # The two "Docs to review" tiles are told apart by where they link, never mixed up.
    assert s["window_docs_to_review"] == 44 and s["students_docs_to_review"] == s["pending_document_verification"] == 11
    assert d["live_stats"]["Docs to review (Admissions flow)"] == "44"
    assert d["live_stats"]["Docs to review (Direct / legacy pipeline)"] == "11"
    # "Accepted" is accepted window applications: nothing is relabelled a visa figure.
    assert s["window_apps_accepted"] == 3
    assert not any("visa" in key or "week" in key or "month" in key for key in s)


def test_a_missing_tile_is_none_never_a_placeholder():
    s = parsers.parse_hangeul_live_dashboard("<html><body>new layout</body></html>")["summary"]
    assert s and all(v is None for v in s.values())
    one = parsers.parse_hangeul_live_dashboard(tile("students.php", "—", "Total students"))["summary"]
    assert one["total_students"] is None                            # not a number: not available


def test_stats_and_fallback_answers_show_not_available_for_missing_figures(monkeypatch):
    live = parsers.parse_hangeul_live_dashboard(INDEX)
    text = telegram_bot.format_stats_report(live)
    assert "*Admissions flow*" in text and "• Accepted: `3`" in text and "• Total students: `330`" in text
    assert "Visa" not in text

    empty = parsers.parse_hangeul_live_dashboard("<p>changed</p>")
    assert "not available" in telegram_bot.format_stats_report(empty)
    assert "not available" in telegram_bot.format_stats_report({"error": "Authentication failed"})

    for ctx in ({"dashboard": empty}, {"dashboard": {}}, {}):
        for q in ("total students", "visa approved", "report today"):
            answer = ollama_client._answer_query_fallback(q, ctx)
            assert not re.search(r"\b(?:262|261)\b", answer), answer          # the old stand-ins
    brief_text = ollama_client._generate_structured_report_fallback(empty, [], [])
    assert "not available" in brief_text and "262" not in brief_text


# --------------------------------------------------------------------------- the calendar reader

def test_calendar_reminders_are_read_from_the_current_layout():
    cal = parsers.parse_calendar_events(calendar_page(*REMINDERS))
    assert cal["layout_ok"] and cal["upcoming_ok"] and cal["heading_count"] == 4
    assert cal["skipped_untitled"] == 1                                 # the untitled entry is dropped
    titles = [r["title"] for r in cal["today_reminders"]]
    assert titles == ["Alpha University DHL", "Gamma University - Application open", "SEJONG *UNIVERSITY*"]
    assert "Copy" not in titles                                         # the pop-up's copies are not counted
    dhl, gamma, sejong = cal["today_reminders"]
    assert dhl == {"title": "Alpha University DHL", "type": "DHL to send", "date_range": "26 Sep–28 Sep",
                   "time": "14:00", "where": "Alpha University", "today": False, "progress": "",
                   "days_left": None, "program": "", "note": ""}
    assert gamma["progress"] == "64% of window elapsed · 4 days left" and gamma["days_left"] == 4
    assert gamma["program"] == "EAP PROGRAM"
    assert sejong["today"] and sejong["days_left"] == 14 and sejong["program"] == ""
    assert sejong["note"] == "Send the documents by DHL."
    assert cal["upcoming_events"] == [{
        "date": "1 Sep", "type": "Application period", "title": "Beta University- APPLICATION OPEN",
        "university": "Beta University", "date_range": "01 Sep – 09 Oct 2026", "program": "EAP PROGRAM",
        "note": "EAP PROGRAM", "status": "Closes in 11 days"}]


def test_an_unknown_calendar_layout_reads_nothing_rather_than_empty_entries():
    cal = parsers.parse_calendar_events("<div class='cal-card'><a href='x'></a><a href='y'></a></div>")
    assert cal["today_reminders"] == [] and not cal["layout_ok"] and cal["skipped_untitled"] == 0
    report = telegram_bot.format_calendar_report(cal)
    assert "not available" in report


def test_the_calendar_command_lists_real_titles():
    report = telegram_bot.format_calendar_report(parsers.parse_calendar_events(calendar_page(*REMINDERS)))
    assert "Reminders for today (3 items)" in report and "Gamma University - Application open" in report
    assert "4 days left" in report and "(1 entry without a title was skipped)" in report


# --------------------------------------------------------------------------- the other readers

def test_verified_students_never_get_a_made_up_amount_or_name():
    row = student(7, 9, "", KLP, by="LINA PARVIN", when="28 Sep, 09:00")          # no name, nothing paid
    got = parsers.parse_verified_students(students_page(row), "28 Sep 2026")
    assert got == [{"student_id": "", "uid": "7", "name": "", "program": KLP, "amount": "", "method": "",
                    "verified_by": "LINA PARVIN", "verified_time": "28 Sep, 09:00"}]
    text = "\n".join(brief.section_verified(got, "28 Sep 2026", True)[0])
    assert "Total: not available (no amount on the rows)" in text and "20,000" not in text
    paid = parsers.parse_verified_students(students_page(VERIFIED_X), "28 Sep 2026")[0]
    assert paid["amount"] == "20,000.00 BDT" and paid["method"] == "Cash"


def test_pending_payments_reader():
    two = students_page(student(1, 2, "A", KLP), student(2, 1, "B", KLP), pending_badge=2)
    assert parsers.parse_pending_payments(two) == {"count": 2, "listed": 2, "badge": 2}
    assert parsers.parse_pending_payments(two.replace("Pending Payments", "Payments")) == {
        "count": 2, "listed": 2, "badge": None}                      # no badge: the rows are counted
    paged = students_page(student(1, 2, "A", KLP), page=1, pages=3)
    assert parsers.parse_pending_payments(paged) is None             # page 1 of 3 is not a count
    assert parsers.parse_pending_payments("<p>nothing</p>") is None


def test_window_applications_reader():
    rows = parsers.parse_window_applications(window_page("under_review", "Under Review", "accepted"))
    assert [r["status"] for r in rows] == ["under_review", "Under Review", "accepted"]
    assert parsers.count_under_review(rows) == 2
    assert parsers.parse_window_applications(window_page()) == []    # the "No applications" row is no row
    assert parsers.parse_window_applications("<table><tr><th>Foo</th></tr></table>") is None


# --------------------------------------------------------------------------- claims the summary and Jennie may make

# The live brief of 28 Sep 2026 (brief_dryrun.txt), as compose_brief's facts: one figure a line.
LIVE_FACTS = [
    "Consultation requests received today: 5", "Consultations done today: 2", "Marked Consulted today: 2",
    "Marked File Opened today: 0", "Requests still new today: 3", "No answer today: 0", "Wrong number today: 0",
    "Handled today by counsellor Arshia Janan: 2", "Students whose payment was verified today: 0",
    "Pending payments: 2", "Window applications under review (a separate figure): 0",
    "Calendar reminders for today: 11", "Calendar reminders for today of type Application period: 7",
    "Calendar reminders for today of type DHL to send: 4"]
PAID_FACTS = LIVE_FACTS[:8] + ["Students whose payment was verified today: 2",
                               "Total amount verified today: 40,000.00 BDT", "Pending payments: 3",
                               "Window applications under review (a separate figure): 0"]


@pytest.mark.parametrize("facts, said", [
    (LIVE_FACTS, "No consultations were done today and nobody called in."),     # 2 were done
    (LIVE_FACTS, "Both pending payments were cleared by Rahim."),               # a name and a status
    (LIVE_FACTS, "Rahim handled 2 consultations today."),                        # an invented name
    (LIVE_FACTS, "Arshia Janan handled 5 consultations."),                     # 5 is the received figure
    (LIVE_FACTS, "A couple of students paid today."),                            # 0 were verified
    (LIVE_FACTS, "Several students were verified today."),
    (LIVE_FACTS, "The fourth student was verified today."),                      # an ordinal
    (LIVE_FACTS, "The 4th student was verified today."),
    (LIVE_FACTS, "পাঁচ consultations and দশ reminders today."),                    # Bengali number words
    (LIVE_FACTS, "5.5 consultations today."),                                    # a decimal
    (LIVE_FACTS, "Eleven students were verified today."),                        # 11 is the calendar count
    (LIVE_FACTS, "2 payments were verified today."),                             # 2 is the pending figure
    (LIVE_FACTS, "2 consultations were not done."),                              # a negation
    (LIVE_FACTS, "Consultations are up from yesterday, 5 today."),               # a comparison
    (PAID_FACTS, "No consultations were done today and no payments were verified."),
    (PAID_FACTS, "Nobody paid today."),
    (PAID_FACTS, "Zero consultations today."),                                   # 0 is only other facts' 0
    (PAID_FACTS, "0 consultations were done today."),
    (PAID_FACTS, "5 consultations done today, 2 received."),                     # figures swapped
    (PAID_FACTS, "3 were done today."),                                          # 3 is the still-new figure
    (PAID_FACTS, "3 payments were verified today."),                             # 3 is the pending figure
    (PAID_FACTS, "2 payments are pending."),                                     # 2 is the verified figure
])
def test_a_claim_that_is_not_its_own_facts_figure_is_dropped(facts, said):
    assert brief.claims_problem(said, facts) is not None
    assert brief.check_summary(said, "\n".join(f"- {f}" for f in facts)) is None


@pytest.mark.parametrize("facts, said", [
    (LIVE_FACTS, "5 consultation requests received today. 2 consultations done today."),   # the live summary
    (LIVE_FACTS, "Today 5 consultation requests were received and 2 consultations were done."),
    (LIVE_FACTS, "Arshia Janan handled 2 consultations today, and 3 requests are still new."),
    (LIVE_FACTS, "No payments were verified today, and 2 payments are pending."),           # a true 0
    (LIVE_FACTS, "No window applications are under review."),
    (LIVE_FACTS, "5 inquiries came in today and 2 were done."),
    (LIVE_FACTS, "11 calendar reminders are due today, 7 of type Application period."),
    (PAID_FACTS, "2 payments were verified today, together 40,000.00 BDT, and 3 payments are pending."),
    (PAID_FACTS, "Pending payments: 3; window applications under review: 0."),
])
def test_a_claim_that_is_its_own_facts_figure_is_kept(facts, said):
    assert brief.claims_problem(said, facts) is None
    assert brief.check_summary(said, "\n".join(f"- {f}" for f in facts)) == said


@pytest.mark.parametrize("said", [
    "Eleven students verified today!",                  # 11 is the calendar count; 0 were verified
    "Yay! Twenty-eight students paid today!",           # 28 is only the date
    "Forty-four payments are pending, ookie!",          # 44 is a dashboard tile, not a fact
    "Three visas approved today!",                      # nothing reports visas
    "Hehe, Rahim did 2 consultations today!",           # an invented name
    "Yay, all 5 requests were done today!",             # "all": 2 of the 5 were done
])
def test_jennie_says_only_the_facts_own_figures(portal, said):
    portal.brain.reply = said
    assert asyncio.run(voice.spoken_brief("\n".join(LIVE_FACTS))) == voice._BRIEF_FALLBACK
    assert len(portal.brain.calls) == 2                  # asked once more, then the honest line
    assert "Today's facts" in portal.brain.calls[0]["user"] and "evening update" in portal.brain.calls[0]["system"]


def test_jennie_says_a_checked_figure(portal):
    portal.brain.reply = "Yay! 5 consultation requests came in today and 2 were done, hehe!"
    line = asyncio.run(voice.spoken_brief("\n".join(LIVE_FACTS)))
    assert line != voice._BRIEF_FALLBACK and "five" in line.lower() and "two" in line.lower()
    assert len(portal.brain.calls) == 1


# --------------------------------------------------------------------------- days the portal cannot answer for

def test_a_day_before_the_consultation_page_is_not_available_not_zero(portal):
    portal.pages.update(full_portal())                         # the page's oldest request: 27 Sep 2026
    composed = asyncio.run(brief.compose_brief(day=date(2026, 9, 1), with_summary=False))
    part = section(composed.text, 1)
    assert part[1] == "• not available (the consultation page only lists requests back to 27 Sep 2026)"
    assert "None received" not in composed.text
    assert composed.facts[0] == "Consultation requests received on the day: not available"


def test_a_full_consultation_page_leaves_its_oldest_day_unknown():
    rows = [{"received_date": "26 Sep 2026", "status": "New"}] + [
        {"received_date": "28 Sep 2026", "status": "New"}] * (brief.CONSULT_PAGE_LIMIT - 1)
    lines, facts = brief.section_consultations(rows, "26 Sep 2026", False)
    assert lines[1].startswith("• not available (the page's list of the latest 500 requests starts partway")
    assert facts == ["Consultation requests received on the day: not available"]
    lines, facts = brief.section_consultations(rows, "27 Sep 2026", False)   # inside the page: a real 0
    assert lines[1] == "• None received on 27 Sep 2026" and facts == ["Consultation requests received on the day: 0"]
    odd = rows + [{"received_date": "Today", "status": "New"}]              # a date the brief cannot read
    lines, facts = brief.section_consultations(odd, "28 Sep 2026", True)
    assert lines[1] == "• not available (1 request on the page has a date the brief cannot read)"


def test_a_day_a_year_back_is_not_matched_on_day_and_month(portal):
    portal.pages.update(full_portal())
    text = compose(day=date(2025, 9, 28))              # "28 Sep" on the portal is this year's 28 Sep
    part = section(text, 2)
    assert part == ["*2) PAYMENT-VERIFIED STUDENTS ON 28 SEP 2025*",
                    "• not available (the portal writes verification times without a year, so 28 Sep 2025 "
                    "cannot be told apart from 28 Sep 2026)"]
    assert "RAHIM" not in text and not any(key.startswith("students.php") and "status" not in key
                                           for _, key in portal.asked)
    assert brief.verified_day_problem(date(2025, 10, 1), date(2026, 9, 28)) is None      # 1 Oct 2026 is ahead
    assert brief.verified_day_problem(date(2024, 2, 29), date(2026, 9, 28)) is not None


def test_a_future_day_reads_nothing_it_cannot_know(portal):
    portal.pages.update(full_portal())
    text = compose(day=date(2026, 10, 5))
    assert section(text, 1)[1] == "• not available (a date in the future)"
    assert section(text, 2)[1] == "• not available (a date in the future)"
    assert ("GET", "consult_requests.php") not in portal.asked and ("GET", "students.php") not in portal.asked


def test_the_verified_reader_checks_the_year_and_the_applied_date():
    row = student(9, 1, "LATE STUDENT", KLP, "1,000.00 BDT", "Cash", "", "LINA PARVIN", "27 Sep, 10:00")
    applied = row.replace("<div>Program", "<div>Stage Applied On 12 Jul 2026</div><div>Program")
    assert len(parsers.parse_verified_students(students_page(applied), "27 Sep 2026")) == 1
    assert parsers.parse_verified_students(students_page(applied), "27 Sep 2025") == []   # before applying
    dated = student(9, 1, "OLD STUDENT", KLP, "1,000.00 BDT", "Cash", "", "LINA PARVIN", "27 Sep 2025, 10:00")
    assert parsers.parse_verified_students(students_page(dated), "27 Sep 2026") == []
    got = parsers.parse_verified_students(students_page(dated), "27 Sep 2025")
    assert len(got) == 1 and got[0]["verified_time"] == "27 Sep, 10:00"


@pytest.mark.parametrize("verifier", ["Md. Al-Amin", "Nur-E-Janan", "Sadia O'Neil", "Arshia Janan"])
def test_a_verifier_name_with_a_hyphen_or_apostrophe_still_counts(verifier):
    row = student(9, 1, "Nur-E-Alam", KLP, "8,000.00 BDT", "bKash", "8,000.00 BDT", verifier, "28 Sep, 11:40")
    got = parsers.parse_verified_students(students_page(row), "28 Sep 2026")
    assert [(g["verified_by"], g["name"]) for g in got] == [(verifier, "Nur-E-Alam")]


def test_the_verified_reader_says_not_available_when_its_layout_is_not_recognised(portal):
    pages = full_portal()
    pages["students.php"] = students_page(VERIFIED_X.replace("Payment verified by", "Checked by"))
    portal.pages.update(pages)
    assert section(compose(), 2)[1] == "• not available (the student list could not be read)"
    # A full first page with no "Page 1 of N": its later pages cannot be found, so no count.
    rows = [student(600 + i, i, f"STUDENT {i}", KLP) for i in range(brief_students_per_page())]
    pages["students.php"] = students_page(VERIFIED_X, *rows).replace("Page 1 of 1", "")
    portal.pages.update(pages)
    assert section(compose(), 2)[1] == "• not available (the student list could not be read)"
    # A short list with no page count is the whole list.
    pages["students.php"] = students_page(VERIFIED_X).replace("Page 1 of 1", "")
    portal.pages.update(pages)
    assert section(compose(), 2)[1] == "• 1 student  |  Total: 20,000.00 BDT"


def brief_students_per_page():
    from src.scraper import client
    return client.STUDENTS_PER_PAGE


# --------------------------------------------------------------------------- a slow or silent portal

def _silent_portal(monkeypatch, handler):
    asked = []

    def recording(request):
        asked.append(request.url.path.rsplit("/", 1)[-1])
        return handler(request)

    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(recording)))
    return asked


def test_a_portal_that_does_not_answer_skips_the_other_reads(portal, monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("", request=request)

    asked = _silent_portal(monkeypatch, timeout)
    started = time.perf_counter()
    text = compose()
    assert time.perf_counter() - started < 5
    assert asked == ["consult_requests.php"]                       # one try, then nothing more
    assert section(text, 1)[1] == "• not available (the portal did not answer)"
    assert section(text, 2)[1] == "• not available (not read: the portal did not answer)"
    assert section(text, 3)[1] == "• Pending payments: not available (the portal did not answer)"
    assert section(text, 4)[1] == "• not available (not read: the portal did not answer)"
    assert portal.brain.calls == []                                # no figure: nothing to sum up


def test_a_hanging_read_is_given_up_on_time(portal, monkeypatch):
    async def hang(request):
        await asyncio.sleep(30)

    asked = _silent_portal(monkeypatch, hang)
    monkeypatch.setattr(brief, "READ_TIMEOUT", 0.3)
    started = time.perf_counter()
    text = compose(with_summary=False)
    assert time.perf_counter() - started < 3 and asked == ["consult_requests.php"]
    assert "not available (the portal did not answer)" in text

    monkeypatch.setattr(brief, "PORTAL_BUDGET", 0.5)              # no time left for any read at all
    asked.clear()
    text = compose(with_summary=False)
    assert asked == [] and "not read: the portal reads ran out of time" in text


def test_fetch_html_gives_a_dead_host_a_short_connect_timeout(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, text="<table></table>")

    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(admin_client, "is_authenticated", True)
    asyncio.run(admin_client.fetch_html("consult_requests.php"))
    assert seen[0]["connect"] == 10.0 and seen[0]["read"] == 60.0


def test_a_calendar_timeout_is_not_available_not_zero_reminders(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("", request=request)

    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(timeout)))
    monkeypatch.setattr(admin_client, "is_authenticated", True)
    monkeypatch.setattr(admin_client, "mock_mode", False)
    cal = asyncio.run(admin_client.get_calendar_events())
    assert cal["error"] == "ReadTimeout" and cal["layout_ok"] is False and cal["today_reminders"] == []
    for query in (None, "/calendar Hanyang"):
        report = telegram_bot.format_calendar_report(cal, filter_query=query)
        assert "not available" in report and "(0 items)" not in report and "No calendar events" not in report
    assert "not available" in telegram_bot.format_calendar_report({"today_reminders": [], "error": ""})
    assert brief.section_calendar(cal, True) == (
        ["*4) TODAY'S CALENDAR REMINDERS*", "• not available (the calendar page could not be read)"],
        ["Calendar reminders for today: not available"])


def test_a_reminders_card_whose_entries_changed_is_not_read_as_none():
    changed = calendar_page(*REMINDERS).replace('class="rm-item"', 'class="rem-entry"').replace(" · 4 items", "")
    cal = parsers.parse_calendar_events(changed)
    assert cal["today_reminders"] == [] and not cal["layout_ok"]
    assert brief.section_calendar(cal, True)[0][1] == "• not available (the calendar page's layout was not recognised)"
    # The card itself saying there is nothing is a real "none today".
    quiet = calendar_page().replace(" · 0 items", "").replace(
        "</small></div>", "</small></div><div class='rm-empty'>No reminders for today</div>", 1)
    cal = parsers.parse_calendar_events(quiet)
    assert cal["layout_ok"] and brief.section_calendar(cal, True)[0][1] == "• None today"


# --------------------------------------------------------------------------- the event loop and the 18:05 job

def test_the_consultation_page_is_parsed_and_checked_off_the_event_loop(monkeypatch):
    from src.scraper import client as client_module

    def on_the_loop(*args, **kwargs):
        raise AssertionError("parsed on the event loop")

    monkeypatch.setattr(client_module, "BeautifulSoup", on_the_loop, raising=False)
    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="<table><tr><th>Foo</th></tr><tr><td>1</td></tr></table>"))))
    monkeypatch.setattr(admin_client, "is_authenticated", True)
    assert asyncio.run(admin_client.read_consultations()) is None       # rows in a layout not recognised
    assert parsers.consultation_table(CONSULTS)[0]["name"] == "Student A"
    assert parsers.consultation_table("<p>no table</p>") is None
    assert parsers.consultation_table(consult_page()) == []             # an empty table: a real 0


def test_the_daily_brief_job_survives_a_late_start(monkeypatch):
    jobs = {}

    class FakeScheduler:
        def add_job(self, func, trigger, **kwargs):
            jobs[kwargs["id"]] = kwargs

        def start(self):
            pass

    monkeypatch.setattr(scheduler, "scheduler", FakeScheduler())
    monkeypatch.setattr(settings, "ENABLE_SCHEDULED_REPORTS", True)
    scheduler.setup_scheduler(SimpleNamespace(bot=FakeBot()))
    job = jobs["daily_executive_briefing"]
    assert job["misfire_grace_time"] == 600 and job["coalesce"] is True and job["max_instances"] == 1
