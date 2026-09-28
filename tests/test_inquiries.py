"""/inquiries_today, /inquiries_date, /consultations, /inquiries and their free-text routes.

The portal's consult_requests.php lists only its newest 500 requests, so a count over its rows is
neither an all-time total nor any day older than about three weeks. These commands therefore read
each day with the page's own GET date filter (?status=all&from=DAY&to=DAY, as its tab links use it)
and take every figure from the status tabs' own counts, the all-time ones from a status tab opened
without a filter. Dates match exactly (8 Sep is never 18 or 28 Sep), a date that cannot be read is
an error (never today), and a portal that cannot be read says so (never 0).

Every page is synthetic (tests/test_consultations.py lays it out like the live page); nothing
reaches the network or Telegram.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_inquiries.py -q
"""
import asyncio
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

from src.bot import replies, telegram_bot  # noqa: E402
from src.scraper.client import PortalUnavailable, admin_client  # noqa: E402
from test_consultations import _page as consult_page, _row as consult_row  # noqa: E402
from test_foundation import Chat, Message, always_login, portal, report_of, run  # noqa: E402,F401

TOTALS = {"All": 999, "New": 8, "No Answer": 153, "Wrong Number": 40, "Consulted": 792, "File Opened": 6}
TOTALS_KEY = "consult_requests.php?status=file_opened"


def day_key(iso):
    return f"consult_requests.php?status=all&from={iso}&to={iso}"


def day_page(iso, *rows, **kw):
    return consult_page(*rows, day_from=iso, day_to=iso, **kw)


def totals_page(totals=None):
    return consult_page(consult_row("Old File", "File Opened", "13 Sep 2026", by="Sadia"),
                        counts=totals or TOTALS, status="file_opened")


TODAY_ROWS = (
    consult_row("Student A", "Consulted", "28 Sep 2026", by="Arshia Janan", consultant="Arshia Janan"),
    consult_row("Student B", "Consulted", "28 Sep 2026", by="Arshia Janan", consultant="Mahira Janan"),
    consult_row("Student C", "New", "28 Sep 2026", consultant="Mahira Janan", city="—"),
    consult_row("Student D", "No Answer", "28 Sep 2026", by="Fahmid Kaisar", consultant="Fahmid Kaisar"),
    consult_row("Student E", "Wrong Number", "28 Sep 2026", by="Fahmid Kaisar"),
)


def inquiry_portal(portal):
    """The portal with its all-time tab counts and today's (28 Sep 2026) filtered view."""
    portal.pages[TOTALS_KEY] = totals_page()
    portal.pages[day_key("2026-09-28")] = day_page("2026-09-28", *TODAY_ROWS)
    return portal


def consult_reads(asked):
    return [key for _, key in asked if key.startswith("consult_requests.php")]


# --------------------------------------------------------------------------- the figures

def test_today_takes_the_day_from_the_date_filter_and_totals_from_the_status_tabs(portal):
    inquiry_portal(portal)
    chat, _ = run(telegram_bot.inquiries_today_command, "/inquiries_today", [])
    text = report_of(chat)
    assert text.startswith("📞 *Consultancy Inquiries Report — 28 September 2026*")
    # All-time: the portal's own tab counts, never len(rows) of its newest-500 list.
    assert "• *Total Inquiries on Portal:* `999`" in text
    assert "• *Total All-Time Done:* `798` (792 Consulted, 6 Files Opened)" in text
    assert "• *Still New:* `8` | *No Answer:* `153` | *Wrong Number:* `40`" in text
    for line in ("• *Inquiries Received:* `5`", "• *Inquiries Done:* `2`", "   ├ ✅ *Consulted:* `2`",
                 "   └ 📁 *File Opened:* `0`", "• *Pending / New:* `1`",
                 "• *No Answer / Other:* `2` (1 No Answer, 1 Wrong Number)",
                 "• *Consultations Handled by:* Arshia Janan: 2"):
        assert line in text, line
    assert consult_reads(portal.asked) == [day_key("2026-09-28"), TOTALS_KEY]
    assert all(method == "GET" for method, _ in portal.asked)
    assert chat[0].edits == 1 and len(chat) == 1          # the ⏳ message became the report


def test_by_is_said_only_for_a_handled_request_and_a_dash_city_is_na(portal):
    inquiry_portal(portal)
    text = report_of(run(telegram_bot.inquiries_today_command, "/inquiries_today", [])[0])
    log = text.split("📋 *Inquiries Log:*")[1]
    assert "*1. Student A* \\[Bachelor's Degree]" in log
    assert "✅ Status: `Consulted` (by Arshia Janan) | City: Dhaka" in log
    # Nobody has touched a New request: its consultant is only assigned, and "—" is no city.
    assert "⏳ Status: `New` (assigned to Mahira Janan) | City: N/A" in log
    assert "📵 Status: `No Answer` (last updated by Fahmid Kaisar) | City: Dhaka" in log
    assert "(by Mahira Janan)" not in log and "City: —" not in log


@pytest.mark.parametrize("args, iso", [
    (["8", "Sep", "2026"], "2026-09-08"), (["08/09/2026"], "2026-09-08"), (["2026-09-26"], "2026-09-26"),
    (["yesterday"], "2026-09-27"), (["5", "Sep"], "2026-09-05"), (["20", "Aug", "2026"], "2026-08-20"),
])
def test_a_day_is_read_with_the_portals_own_date_filter(portal, args, iso):
    inquiry_portal(portal)
    d = date.fromisoformat(iso)
    rows = [consult_row(f"Student {i}", "Consulted", f"{d:%d %b %Y}", by="Sadia") for i in range(3)]
    portal.pages[day_key(iso)] = day_page(iso, *rows, consult_row("Late", "New", f"{d:%d %b %Y}"))
    text = report_of(run(telegram_bot.inquiries_date_command, "/inquiries_date " + " ".join(args), args)[0])
    assert f"Report — {d:%d %B %Y}*" in text
    assert "• *Inquiries Received:* `4`" in text and "• *Inquiries Done:* `3`" in text
    assert "• *Total Inquiries on Portal:* `999`" in text
    assert consult_reads(portal.asked) == [day_key(iso), TOTALS_KEY]


def test_8_sep_is_never_18_or_28_sep(portal):
    inquiry_portal(portal)
    # A date filter that sent other days' requests is refused, never counted for 8 Sep.
    portal.pages[day_key("2026-09-08")] = day_page("2026-09-08", consult_row("A", "Consulted", "08 Sep 2026", by="X"),
                                                   consult_row("B", "Consulted", "18 Sep 2026", by="X"),
                                                   consult_row("C", "New", "28 Sep 2026"))
    text = report_of(run(telegram_bot.inquiries_date_command, "/inquiries_date 8 Sep 2026", ["8", "Sep", "2026"])[0])
    assert text.startswith("❌ Couldn't read the portal:") and "listed 2 request(s) from another day" in text
    assert "Inquiries Received" not in text
    # And a date a year back is that year's, not this year's 8 Sep.
    portal.pages[day_key("2025-09-08")] = day_page("2025-09-08")
    text = report_of(run(telegram_bot.inquiries_date_command, "/inquiries_date 8 Sep 2025", ["8", "Sep", "2025"])[0])
    assert "• *Inquiries Received:* `0`" in text and "No new consultation requests were recorded on 08 September 2025" in text


def test_a_day_with_no_requests_is_a_real_zero_only_from_the_portals_own_empty_list(portal):
    inquiry_portal(portal)
    portal.pages[day_key("2026-09-01")] = day_page("2026-09-01")
    text = report_of(run(telegram_bot.inquiries_date_command, "/inquiries_date 1 Sep", ["1", "Sep"])[0])
    assert "• *Inquiries Received:* `0`" in text
    assert "ℹ️ *No new consultation requests were recorded on 01 September 2026.*" in text


# --------------------------------------------------------------------------- dates that cannot be read

@pytest.mark.parametrize("handler, text, args", [
    (telegram_bot.inquiries_date_command, "/inquiries_date 31 Sep", ["31", "Sep"]),
    (telegram_bot.inquiries_date_command, "/inquiries_date 31 Sep 2026", ["31", "Sep", "2026"]),
    (telegram_bot.consultations_command, "/consultations 29 Feb 2026", ["29", "Feb", "2026"]),
    (telegram_bot.inquiries_command, "/inquiries foo", ["foo"]),
    (telegram_bot.inquiries_date_command, "/inquiries_date last week", ["last", "week"]),
])
def test_a_date_that_cannot_be_read_is_an_error_never_today(portal, handler, text, args):
    inquiry_portal(portal)
    chat, _ = run(handler, text, args)
    assert len(chat) == 1 and "couldn't read" in chat[0].text and "Report — 28 September" not in chat[0].text
    assert "`/inquiries_date 12 Sep 2026`" in chat[0].text
    assert portal.asked == []                                 # nothing read, no stand-in day
    if "31 Sep" in text:
        assert "September has 30 days" in chat[0].text or "September 2026 has 30 days" in chat[0].text


def test_a_day_to_come_is_not_available(portal):
    inquiry_portal(portal)
    text = report_of(run(telegram_bot.inquiries_date_command, "/inquiries_date 5 Oct 2026", ["5", "Oct", "2026"])[0])
    assert "not available (a date in the future)" in text and portal.asked == []


def test_the_date_prompt_and_its_typed_answer(portal):
    inquiry_portal(portal)
    portal.pages[day_key("2026-09-26")] = day_page("2026-09-26", consult_row("A", "Consulted", "26 Sep 2026", by="X"))
    for handler in (telegram_bot.inquiries_date_command, telegram_bot.consultations_command, telegram_bot.inquiries_command):
        chat, context = run(handler, "/inquiries_date", [])
        assert context.user_data["awaiting_date_for"] == "inquiries" and "specific date" in chat[0].text
    chat, _ = run(telegram_bot.handle_natural_language_message, "26 Sep 2026", None, context.user_data)
    assert "Report — 26 September 2026*" in report_of(chat) and "• *Inquiries Received:* `1`" in report_of(chat)
    # A typed answer that is no date is said so, not answered with today's report.
    chat, context = run(telegram_bot.inquiries_date_command, "/inquiries_date", [])
    chat, _ = run(telegram_bot.handle_natural_language_message, "whenever", None, context.user_data)
    assert "couldn't read “whenever” as a date" in report_of(chat)


# --------------------------------------------------------------------------- the portal cannot be read

@pytest.mark.parametrize("failure, reason", [
    ("expired", None),
    ("cannot renew", "kept sending its login page after a fresh login"),
    ("refused login", "couldn't log in to the portal: simulated bad credentials"),
    ("unreachable", "did not answer in time"),
    ("maintenance", "status tabs (All, New, ...) and their counts were not found"),
    ("filter ignored", "did not apply the date filter for 28 Sep 2026"),
    ("rows unreadable", "says it lists 5 requests for 28 Sep 2026 but 4 could be read"),
    ("statuses disagree", "do not match its own status counts"),
])
def test_a_portal_that_cannot_be_read_says_so_never_zero(portal, monkeypatch, failure, reason):
    inquiry_portal(portal)
    logins = []
    if failure in ("expired", "cannot renew"):
        # The session expired: the portal sends its login page (once, or every time).
        left = {"n": 1 if failure == "expired" else 99}
        pages = dict(portal.pages)

        def handler(request):
            key = request.url.path.rsplit("/", 1)[-1] + (f"?{request.url.query.decode()}" if request.url.query else "")
            portal.asked.append((request.method, key))
            assert request.method == "GET"
            if request.url.path.endswith("login.php"):
                return httpx.Response(200, text="<form><input name='_csrf' value='t'></form>")
            if left["n"]:
                left["n"] -= 1
                return httpx.Response(302, headers={"Location": "https://hangeul.com.bd/admin/login.php"})
            return httpx.Response(200, text=pages[key])

        async def fresh_login(*args, **kwargs):
            logins.append(True)
            admin_client.is_authenticated = True
            return {"success": True}
        monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                                                       follow_redirects=True))
        monkeypatch.setattr(admin_client, "login", fresh_login)
    elif failure == "refused login":
        async def refused(*args, **kwargs):
            return {"success": False, "error": "simulated bad credentials"}
        monkeypatch.setattr(admin_client, "is_authenticated", False)
        monkeypatch.setattr(admin_client, "login", refused)
    elif failure == "unreachable":
        def down(request):
            raise httpx.ReadTimeout("", request=request)
        monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(down)))
    elif failure == "maintenance":
        portal.pages[day_key("2026-09-28")] = "<html><body>Scheduled maintenance</body></html>"
    elif failure == "filter ignored":           # the portal sent its whole list instead of the day
        portal.pages[day_key("2026-09-28")] = consult_page(*TODAY_ROWS)
    elif failure == "rows unreadable":
        portal.pages[day_key("2026-09-28")] = day_page("2026-09-28", *TODAY_ROWS[:4], listed=5).replace(
            '<span class="n">4</span>', '<span class="n">5</span>', 1)
    else:
        portal.pages[day_key("2026-09-28")] = day_page("2026-09-28", *TODAY_ROWS).replace(
            '<span class="dot"></span>Wrong Number</span>', '<span class="dot"></span>Rescheduled</span>')
    chat, _ = run(telegram_bot.inquiries_today_command, "/inquiries_today", [])
    text = report_of(chat)
    if failure == "expired":                   # logged in again once, and answered
        assert len(logins) == 1 and "• *Inquiries Received:* `5`" in text and "`999`" in text
        return
    assert text.startswith("❌ Couldn't read the portal:"), text
    assert reason in text and "Consultancy inquiries for 28 September 2026: not available right now." in text
    assert "Received" not in text and "`0`" not in text


def test_all_time_figures_that_cannot_be_read_are_not_available_the_day_still_shown(portal):
    inquiry_portal(portal)
    del portal.pages[TOTALS_KEY]
    text = report_of(run(telegram_bot.inquiries_today_command, "/inquiries_today", [])[0])
    assert "• All-time figures: not available (couldn't read the portal's status counts: " in text
    assert "Total Inquiries on Portal" not in text and "• *Inquiries Received:* `5`" in text
    # A page that opened another tab, or a date filter, gives no all-time figures either.
    portal.pages[TOTALS_KEY] = consult_page(consult_row("A", "New", "13 Sep 2026"), counts=TOTALS, status="new")
    with pytest.raises(PortalUnavailable, match="may not be all-time"):
        asyncio.run(admin_client.read_consultation_totals())
    portal.pages[TOTALS_KEY] = totals_page()
    assert asyncio.run(admin_client.read_consultation_totals()) == TOTALS


def test_a_day_the_portal_lists_only_partly_keeps_its_own_counts(portal):
    inquiry_portal(portal)
    rows = [consult_row(f"S{i}", "Consulted", "22 Sep 2026", by="Sadia") for i in range(500)]
    counts = {"All": 520, "New": 0, "No Answer": 0, "Wrong Number": 0, "Consulted": 520, "File Opened": 0}
    portal.pages[day_key("2026-09-22")] = day_page("2026-09-22", *rows, counts=counts)
    got = asyncio.run(admin_client.read_consultation_day(date(2026, 9, 22)))
    assert got["counts"]["All"] == 520 and len(got["rows"]) == 500 and got["complete"] is False
    text = report_of(run(telegram_bot.inquiries_date_command, "/inquiries_date 22 Sep", ["22", "Sep"])[0])
    assert "• *Inquiries Received:* `520`" in text
    assert "• *Consultations Handled by:* Sadia: 500 (among the 500 the portal lists)" in text
    assert "...and 510 more inquiries received on 22 September 2026." in text


# --------------------------------------------------------------------------- Telegram

def test_a_long_report_is_split_and_markdown_trouble_is_resent_plain(portal, monkeypatch):
    inquiry_portal(portal)
    monkeypatch.setattr(telegram_bot, "INQUIRIES_LOG_MAX", 200)
    rows = [consult_row(f"STUDENT_{i:03d} WITH A LONG *FULL* NAME", "Consulted", "24 Sep 2026", by="Sadia_R",
                        program="KOREAN LANGUAGE PROGRAM (KLP)") for i in range(120)]
    portal.pages[day_key("2026-09-24")] = day_page("2026-09-24", *rows)
    chat, _ = run(telegram_bot.inquiries_date_command, "/inquiries_date 24 Sep", ["24", "Sep"])
    assert len(chat) > 1 and all(replies.telegram_len(m.text) <= replies.CHUNK_CHARS for m in chat)
    text = report_of(chat)
    assert all(f"STUDENT_{i:03d}" in text for i in range(120))
    assert "*1. STUDENT_000 WITH A LONG ∗FULL∗ NAME*" in text            # no '*' of its own inside bold
    assert "(by Sadia\\_R)" in text
    # A piece Telegram refuses for its Markdown goes again as plain text.
    update_chat = Chat()
    message = Message(update_chat, refuse_markdown=True)
    asyncio.run(replies.reply_long(message, "*1. Name* \\[KLP]"))
    assert [(m.text, m.parse_mode) for m in update_chat] == [("1. Name [KLP]", None)]


# --------------------------------------------------------------------------- free text

@pytest.mark.parametrize("said, iso", [
    ("Total consultancy inquires and how many were done today", "2026-09-28"),
    ("how many consultations today", "2026-09-28"),
    ("how many consultations yesterday", "2026-09-27"),
    ("how many consultations on 27 Sep 2026", "2026-09-27"),
    ("how many consultations on 3 Sep 2026", "2026-09-03"),
    ("consultancy inquiries for 8 sep", "2026-09-08"),
])
def test_free_text_inquiry_questions_read_the_day_they_name(portal, said, iso):
    inquiry_portal(portal)
    d = date.fromisoformat(iso)
    portal.pages.setdefault(day_key(iso), day_page(iso, consult_row("A", "Consulted", f"{d:%d %b %Y}", by="X")))
    text = report_of(run(telegram_bot.handle_natural_language_message, said, None)[0])
    assert f"Report — {d:%d %B %Y}*" in text
    assert consult_reads(portal.asked) == [day_key(iso), TOTALS_KEY]


def test_free_text_that_is_no_inquiry_date_is_not_read_as_one(portal, monkeypatch):
    inquiry_portal(portal)
    routed = []

    async def recorder(update, context):
        routed.append(context.user_data.get("override_text"))
    monkeypatch.setattr(telegram_bot, "report_command", recorder)
    # "Janan" is no January: not an inquiry date (the old substring test sent it to /inquiries_date).
    run(telegram_bot.handle_natural_language_message, "consultations handled by Arshia Janan", None)
    assert routed == ["consultations handled by Arshia Janan"] and consult_reads(portal.asked) == []
    # A date-like word that cannot be read is said so, never today's report.
    for said in ("how many consultations on 31 Sep", "consultations last week"):
        text = report_of(run(telegram_bot.handle_natural_language_message, said, None)[0])
        assert "couldn't read" in text and "Report —" not in text
    assert consult_reads(portal.asked) == []
