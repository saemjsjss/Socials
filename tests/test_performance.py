"""/performance_today, /performance_month (and /perf_today, /perf_month, /performance [month]), and
their free-text routes: the whole team's performance for today or for this month so far.

What is pinned here: the team figures are the portal's own status counts under its date filter for
the window, and the payments verified by each row's own stamp, read from every students.php page
ONCE for the window; each person's consultations done and follow-ups are counted from the rows'
"Last updated by", requests assigned from the Consultant column, payments verified from the stamp's
name (names matched without regard to case); a month whose requests are more than the list shows is
read again in parts, never double-counted; a yearless stamp that cannot be this year's is never
counted; a part that cannot be read says so while the other part is still shown (never a 0); the
reply is split under Telegram's limit and resent as plain text when its Markdown is refused; both
commands are in the menu and the cheat-sheet; the free-text routes are whole words and do not take
other routes' questions; and the root staging copy of telegram_bot.py is byte-identical.

Every portal page is synthetic (laid out like the live pages, Sep 2026); today is 28 Sep 2026 in
Dhaka. Nothing reaches the network or Telegram.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_performance.py -q
"""
import asyncio
import filecmp
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from telegram.error import BadRequest

from test_consultations import _page as consult_page, _row as consult_row
from test_foundation import (  # noqa: F401  (the portal fixture is used by name)
    BACHELOR, TODAY, Message, Sent, fake_update, page, portal, report_of, row, run, verified,
)
from src.bot import ask, performance, replies, telegram_bot
from src.config import settings
from src.scraper import parsers
from src.scraper.client import admin_client

BOT_ROOT = Path(__file__).resolve().parent.parent
MONTH_FIRST = "2026-09-01"
TODAY_ISO = "2026-09-28"


def range_key(first, last):
    return f"consult_requests.php?status=all&from={first}&to={last}"


def range_page(first, last, *rows, **kw):
    return consult_page(*rows, day_from=first, day_to=last, **kw)


def consult_reads(asked):
    return [key for _, key in asked if key.startswith("consult_requests.php")]


def student_reads(asked):
    return [key for _, key in asked if key.startswith("students.php")]


# --------------------------------------------------------------------------- synthetic portal

TODAY_ROWS = (
    consult_row("Student A", "Consulted", "28 Sep 2026", by="Arshia Janan", consultant="Arshia Janan"),
    consult_row("Student B", "Consulted", "28 Sep 2026", by="Arshia Janan", consultant="Mahira Janan"),
    consult_row("Student C", "File Opened", "28 Sep 2026", by="Fahmid Kaisar", consultant="Fahmid Kaisar"),
    consult_row("Student D", "No Answer", "28 Sep 2026", by="Fahmid Kaisar", consultant="Fahmid Kaisar"),
    consult_row("Student E", "Wrong Number", "28 Sep 2026", by="Mahira Janan", consultant="Mahira Janan"),
    consult_row("Student F", "New", "28 Sep 2026", consultant="Mahira Janan"),
    consult_row("Student G", "New", "28 Sep 2026", consultant="—"),
    consult_row("Student H", "Consulted", "28 Sep 2026", consultant="Sumona Halder"),      # no "Last updated by"
)


def student_pages():
    """Two pages of students.php: verified today by MAHIRA JANAN (twice, one on page 2) and SUMONA
    HALDER; and stamps that are not today's or cannot be this year's."""
    return {
        "students.php": page(
            verified(917, 1, "RAHIM UDDIN", "28 Sep, 10:00", by="MAHIRA JANAN", applied="27 Sep 2026"),
            verified(916, 2, "NUSRAT JAHAN", "28 Sep, 11:30", amount="8,000.00 BDT", method="bKash",
                     by="SUMONA HALDER", program=BACHELOR, applied="27 Sep 2026"),
            verified(910, 3, "EARLIER ONE", "27 Sep, 11:00", by="MAHIRA JANAN", applied="20 Sep 2026"),
            row(969, 4, "PENDING APPLICANT", pay="Pending", stage="Application Received", applied="28 Sep 2026"),
            pg=1, pages=2, total=10),
        "students.php?pg=2": page(
            verified(300, 5, "PAGE TWO TODAY", "28 Sep, 09:00", amount="12,000.00 BDT", by="MAHIRA JANAN",
                     applied="1 Sep 2026"),
            verified(301, 6, "FIRST OF MONTH", "01 Sep, 12:00", amount="5,000.00 BDT", by="FAHMID KAISAR",
                     applied="1 Sep 2026"),
            verified(302, 7, "TWELFTH", "12 Sep, 10:00", by="Owner", applied="1 Sep 2026"),
            verified(303, 8, "LAST MONTH", "28 Aug, 09:00", by="FAHMID KAISAR", applied="1 Aug 2026"),
            # "30 Sep" is still to come this month: that stamp is last year's.
            verified(304, 9, "LAST YEAR THIRTIETH", "30 Sep, 09:00", by="FAHMID KAISAR", applied="1 Aug 2026"),
            # Verified "10 Sep" but applied on 20 Sep 2026: that stamp is last year's 10 Sep.
            verified(305, 10, "LAST YEAR TENTH", "10 Sep, 09:00", by="FAHMID KAISAR", applied="20 Sep 2026"),
            pg=2, pages=2, total=10),
    }


def perf_portal(portal):
    portal.pages[range_key(TODAY_ISO, TODAY_ISO)] = range_page(TODAY_ISO, TODAY_ISO, *TODAY_ROWS)
    portal.pages.update(student_pages())
    return portal


def blocks(text):
    """The per-person blocks: {name: the block's lines}, in the report's order."""
    people = text.split("👥 *By Person*")[1].split("\n\n")[0].splitlines()[1:]
    found, name = {}, None
    for line in people:
        if line.startswith("*") and ". " in line:
            name = line.split(". ", 1)[1].rstrip("*")
            found[name] = []
        elif name and line.startswith("   "):
            found[name].append(line.strip())
    return found


# --------------------------------------------------------------------------- today

def test_today_team_totals_and_every_persons_counts_are_exact(portal):
    perf_portal(portal)
    chat, _ = run(telegram_bot.performance_today_command, "/performance_today", [])
    text = report_of(chat)
    assert text.startswith("📈 *Team Performance — Today, 28 September 2026*")
    for line in ("• *Received:* `8`", "• *Done:* `4` (3 Consulted, 1 File Opened)",
                 "• *Still New:* `2` | *No Answer:* `1` | *Wrong Number:* `1`",
                 "• *Students Verified:* `3`", "• *Total:* `৳ 40,000.00 BDT` (verified income)"):
        assert line in text, line
    people = blocks(text)
    # Sorted by activity (done + follow-ups + payments verified), then by requests assigned.
    assert list(people) == ["Mahira Janan", "Fahmid Kaisar", "Arshia Janan", "Sumona Halder"]
    assert people["Mahira Janan"] == ["├ ✅ Consultations done: `0`",
                                       "├ 📵 Follow-ups: No Answer `0` · Wrong Number `1`",
                                       "├ 📋 Requests assigned: `3`",
                                       "└ 💳 Payments verified: `2` (৳ 32,000.00 BDT)"]
    assert people["Fahmid Kaisar"] == ["├ ✅ Consultations done: `1` (0 Consulted, 1 File Opened)",
                                      "├ 📵 Follow-ups: No Answer `1` · Wrong Number `0`",
                                      "├ 📋 Requests assigned: `2`", "└ 💳 Payments verified: `0`"]
    assert people["Arshia Janan"][0] == "├ ✅ Consultations done: `2`"
    assert people["Arshia Janan"][2] == "├ 📋 Requests assigned: `1`"
    assert people["Sumona Halder"][-1] == "└ 💳 Payments verified: `1` (৳ 8,000.00 BDT)"
    # A request nobody's name is on is said so, never credited, and no "Unassigned" person.
    assert "• Done with no name on the portal: `1`" in text
    assert "• Requests assigned to no consultant: `1`" in text and "Unassigned" not in text
    assert "MAHIRA JANAN" not in text                       # one person, the name as the portal writes it
    assert "EARLIER ONE" not in text and "RAHIM" not in text  # no student names in the report
    # One read of the day, and every page of students.php once; nothing but GETs.
    assert consult_reads(portal.asked) == [range_key(TODAY_ISO, TODAY_ISO)]
    assert student_reads(portal.asked) == ["students.php", "students.php?pg=2"]
    assert all(method == "GET" for method, _ in portal.asked)
    assert len(chat) == 1 and chat[0].edits == 1              # the ⏳ message became the report
    assert "all 10 students of the student list" in text


def test_the_waiting_message_says_what_is_read(portal, monkeypatch):
    perf_portal(portal)
    seen = []
    real = performance.build_performance_report

    async def spy(kind, today=None):
        seen.append(kind)
        return await real(kind, today)
    monkeypatch.setattr(performance, "build_performance_report", spy)
    update, context, chat = fake_update("/perf_today", [])
    status = []
    original = update.message.reply_text

    async def reply_text(text, parse_mode=None, **kw):
        status.append(text)
        return await original(text, parse_mode=parse_mode, **kw)
    update.message.reply_text = reply_text
    asyncio.run(telegram_bot.performance_today_command(update, context))
    assert seen == ["today"] and status[0].startswith("⏳ _Reading today's team performance live from the portal")


# --------------------------------------------------------------------------- this month

def month_page():
    """The month's requests under the date filter, one of them in a status the portal has its own
    tab for besides the five known ones ("Rescheduled")."""
    rows = (consult_row("M1", "Consulted", "28 Sep 2026", by="Arshia Janan", consultant="Arshia Janan"),
            consult_row("M2", "No Answer", "20 Sep 2026", by="Arshia Janan", consultant="Arshia Janan"),
            consult_row("M3", "Consulted", "12 Sep 2026", by="Fahmid Kaisar", consultant="Fahmid Kaisar"),
            consult_row("M4", "Rescheduled", "05 Sep 2026", by="Fahmid Kaisar", consultant="Fahmid Kaisar"),
            consult_row("M5", "New", "01 Sep 2026", consultant="Sumona Halder"))
    tab = (f'<a class="st-rescheduled" href="?status=rescheduled&from={MONTH_FIRST}&to={TODAY_ISO}">'
           '<span class="dot"></span>Rescheduled <span class="n">1</span></a>')
    return range_page(MONTH_FIRST, TODAY_ISO, *rows).replace("</nav>", tab + "</nav>")


def test_the_month_is_the_first_to_today_and_stamps_are_read_once_for_it(portal):
    portal.pages.update(student_pages())
    portal.pages[range_key(MONTH_FIRST, TODAY_ISO)] = month_page()
    chat, _ = run(telegram_bot.performance_month_command, "/performance_month", [])
    text = report_of(chat)
    assert text.startswith("📈 *Team Performance — This Month, 01–28 September 2026*")
    assert "• *Received:* `5`" in text and "• *Other statuses:* Rescheduled `1`" in text
    # 28 Sep (three), 27 Sep, 12 Sep and 1 Sep; never 28 Aug, "30 Sep" (last year's: still to come)
    # or the "10 Sep" of a student who applied on 20 Sep (last year's too).
    assert "• *Students Verified:* `6`" in text
    assert "• *Total:* `৳ 85,000.00 BDT` (verified income)" in text
    people = blocks(text)
    assert people["Fahmid Kaisar"][-1] == "└ 💳 Payments verified: `1` (৳ 5,000.00 BDT)"
    assert "├ ✏️ Other status updates: Rescheduled `1`" in people["Fahmid Kaisar"]
    assert people["Owner"][-1] == "└ 💳 Payments verified: `1` (৳ 20,000.00 BDT)"
    assert people["MAHIRA JANAN"][-1] == "└ 💳 Payments verified: `3` (৳ 52,000.00 BDT)"
    assert people["Arshia Janan"][:2] == ["├ ✅ Consultations done: `1`",
                                            "├ 📵 Follow-ups: No Answer `1` · Wrong Number `0`"]
    # The window's own date filter once, and every page of students.php once for the whole month.
    assert consult_reads(portal.asked) == [range_key(MONTH_FIRST, TODAY_ISO)]
    assert student_reads(portal.asked) == ["students.php", "students.php?pg=2"]


def test_the_verified_window_reader_counts_each_student_once_on_their_stamps_day(portal):
    portal.pages.update(student_pages())
    got = asyncio.run(admin_client.read_verified_window(date(2026, 9, 1), date(2026, 9, 28)))
    assert got["students"] == 10
    assert sorted((v["uid"], v["day"].isoformat(), v["verified_by"]) for v in got["verified"]) == [
        ("300", "2026-09-28", "MAHIRA JANAN"), ("301", "2026-09-01", "FAHMID KAISAR"),
        ("302", "2026-09-12", "Owner"), ("910", "2026-09-27", "MAHIRA JANAN"),
        ("916", "2026-09-28", "SUMONA HALDER"), ("917", "2026-09-28", "MAHIRA JANAN")]
    # A stamp with its own year is that year's.
    students = [{"verified_stamp": "12 Sep 2025, 10:00", "applied_on": "1 Sep 2025, 10:00", "uid": "1"},
                {"verified_stamp": "12 Sep, 10:00", "applied_on": "1 Sep 2026, 10:00", "uid": "2"}]
    assert [v["uid"] for v in parsers.verified_between(students, date(2026, 9, 1), date(2026, 9, 28))] == ["2"]
    with pytest.raises(ValueError):
        asyncio.run(admin_client.read_verified_window(date(2026, 9, 28), date(2026, 9, 1)))


def test_a_window_a_year_back_is_not_available_for_payments(portal):
    portal.pages.update(student_pages())
    first, last = date(2025, 9, 1), date(2025, 9, 28)
    portal.pages[range_key(first, last)] = range_page(first.isoformat(), last.isoformat())
    reads = asyncio.run(performance.read_performance(first, last, TODAY))
    text = performance.format_performance_report("month", first, last, reads)
    assert "• ℹ️ Payments verified: not available (the portal writes verification times without a year" in text
    assert "*Students Verified:*" not in text and student_reads(portal.asked) == []
    assert "• *Received:* `0`" in text                                 # a real 0: the portal's own empty list


# --------------------------------------------------------------------------- more requests than the list shows

def cut_month(changed=False):
    """The month's requests, 10 in all, of which the list shows the newest 6 (down into 15 Sep); the
    days from 1 Sep to 15 Sep read on their own hold the other 5 (6 when the list `changed`)."""
    first_rows = (consult_row("K1", "Consulted", "28 Sep 2026", by="Arshia Janan", consultant="Arshia Janan"),
                  consult_row("K2", "Consulted", "28 Sep 2026", by="Arshia Janan", consultant="Arshia Janan"),
                  consult_row("K3", "New", "28 Sep 2026", consultant="Fahmid Kaisar"),
                  consult_row("K4", "Consulted", "20 Sep 2026", by="Fahmid Kaisar", consultant="Fahmid Kaisar"),
                  consult_row("K5", "No Answer", "20 Sep 2026", by="Fahmid Kaisar", consultant="Fahmid Kaisar"),
                  consult_row("C1", "Consulted", "15 Sep 2026", by="Firoza Ara Shampa",
                              consultant="Firoza Ara Shampa"))
    counts = {"All": 10, "New": 2, "No Answer": 2, "Wrong Number": 0, "Consulted": 6, "File Opened": 0}
    rest_rows = (consult_row("C1", "Consulted", "15 Sep 2026", by="Firoza Ara Shampa",
                             consultant="Firoza Ara Shampa"),
                 consult_row("C2", "New", "15 Sep 2026", consultant="Firoza Ara Shampa"),
                 consult_row("R1", "Consulted", "03 Sep 2026", by="Arshia Janan", consultant="Arshia Janan"),
                 consult_row("R2", "Consulted", "03 Sep 2026", by="Firoza Ara Shampa",
                             consultant="Firoza Ara Shampa"),
                 consult_row("R3", "No Answer", "03 Sep 2026", by="Arshia Janan", consultant="Arshia Janan"))
    if changed:                                   # a request came in for 3 Sep between the two reads
        rest_rows += (consult_row("R4", "Consulted", "03 Sep 2026", by="Arshia Janan", consultant="Arshia Janan"),)
    return {range_key(MONTH_FIRST, TODAY_ISO): range_page(MONTH_FIRST, TODAY_ISO, *first_rows, counts=counts),
            range_key(MONTH_FIRST, "2026-09-15"): range_page(MONTH_FIRST, "2026-09-15", *rest_rows)}


def test_a_month_longer_than_the_list_is_read_in_parts_and_never_counted_twice(portal):
    portal.pages.update(student_pages())
    portal.pages.update(cut_month())
    got = asyncio.run(admin_client.read_consultation_range(date(2026, 9, 1), date(2026, 9, 28)))
    assert got["counts"]["All"] == 10 and len(got["rows"]) == 10 and got["complete"] and got["reads"] == 2
    assert [r["name"] for r in got["rows"]] == ["K1", "K2", "K3", "K4", "K5", "C1", "C2", "R1", "R2", "R3"]
    portal.asked.clear()
    text = report_of(run(telegram_bot.performance_month_command, "/performance_month", [])[0])
    assert "• *Received:* `10`" in text and "• *Done:* `6` (6 Consulted, 0 File Opened)" in text
    people = blocks(text)
    assert people["Arshia Janan"][:3] == ["├ ✅ Consultations done: `3`",
                                            "├ 📵 Follow-ups: No Answer `1` · Wrong Number `0`",
                                            "├ 📋 Requests assigned: `4`"]
    # The 15 Sep request the first page showed is counted once, from the read of 1-15 Sep.
    assert people["Firoza Ara Shampa"][:3] == ["├ ✅ Consultations done: `2`",
                                                "├ 📵 Follow-ups: No Answer `0` · Wrong Number `0`",
                                                "├ 📋 Requests assigned: `3`"]
    assert consult_reads(portal.asked) == [range_key(MONTH_FIRST, TODAY_ISO), range_key(MONTH_FIRST, "2026-09-15")]


def test_parts_that_do_not_add_up_are_read_again_then_said_honestly(portal):
    portal.pages.update(student_pages())
    portal.pages.update(cut_month(changed=True))                       # 5 kept + 6 is not the month's 10
    text = report_of(run(telegram_bot.performance_month_command, "/performance_month", [])[0])
    assert "• ❌ Consultations: couldn't read the portal: consult\\_requests.php counts 10 requests for " \
           "01 Sep 2026 – 28 Sep 2026, but read in parts they are 11 (the list changed while it was read)." in text
    assert len(consult_reads(portal.asked)) == 4                        # read once more before giving up
    assert "*Received:*" not in text and "Consultations done" not in text
    assert "• *Students Verified:* `6`" in text                         # the part that was read is still shown


def test_a_single_day_longer_than_the_list_keeps_its_own_counts(portal):
    portal.pages.update(student_pages())
    rows = [consult_row(f"S{i}", "Consulted", "28 Sep 2026", by="Sumona Halder", consultant="Sumona Halder")
            for i in range(6)]
    counts = {"All": 9, "New": 0, "No Answer": 0, "Wrong Number": 0, "Consulted": 9, "File Opened": 0}
    portal.pages[range_key(TODAY_ISO, TODAY_ISO)] = range_page(TODAY_ISO, TODAY_ISO, *rows, counts=counts)
    text = report_of(run(telegram_bot.performance_today_command, "/performance_today", [])[0])
    assert "• *Received:* `9`" in text and "• *Done:* `9` (9 Consulted, 0 File Opened)" in text
    assert "⚠️ _The portal lists 6 of the 9 requests (one day holds more than its list shows)" in text
    assert blocks(text)["Sumona Halder"][0] == "├ ✅ Consultations done: `6`"


# --------------------------------------------------------------------------- a part that cannot be read

def test_a_failed_consultation_read_still_shows_the_verifications_and_says_so(portal):
    portal.pages.update(student_pages())                                # no consult_requests.php page: HTTP 404
    chat, _ = run(telegram_bot.performance_today_command, "/performance_today", [])
    text = report_of(chat)
    assert "• ❌ Consultations: couldn't read the portal: consult\\_requests.php: the portal answered HTTP 404." in text
    assert "*Received:*" not in text and "Consultations done" not in text and "Requests assigned" not in text
    assert "_Consultation figures per person: not available (the consultation requests could not be read)._" in text
    assert "• *Students Verified:* `3`" in text and "• *Total:* `৳ 40,000.00 BDT` (verified income)" in text
    people = blocks(text)                                               # the names as the stamps write them
    assert people == {"MAHIRA JANAN": ["└ 💳 Payments verified: `2` (৳ 32,000.00 BDT)"],
                      "SUMONA HALDER": ["└ 💳 Payments verified: `1` (৳ 8,000.00 BDT)"]}


def test_a_failed_student_read_still_shows_the_consultations_and_says_so(portal):
    portal.pages[range_key(TODAY_ISO, TODAY_ISO)] = range_page(TODAY_ISO, TODAY_ISO, *TODAY_ROWS)
    portal.pages["students.php"] = page(row(1, 1, "A"), row(2, 2, "B"))   # no stamp on any row: layout unknown
    text = report_of(run(telegram_bot.performance_today_command, "/performance_today", [])[0])
    assert "• ❌ Payments verified: couldn't read the portal: students.php: 2 student rows but no " \
           "'Payment verified by' line on any of them (layout not recognised)." in text
    assert "*Students Verified:*" not in text and "💳" not in text
    assert "• *Received:* `8`" in text and blocks(text)["Arshia Janan"][0] == "├ ✅ Consultations done: `2`"


def test_a_consultant_column_that_names_nobody_is_not_available_not_zero(portal):
    portal.pages.update(student_pages())
    rows = [consult_row(f"S{i}", "Consulted", "28 Sep 2026", by="Arshia Janan", consultant="—") for i in range(3)]
    portal.pages[range_key(TODAY_ISO, TODAY_ISO)] = range_page(TODAY_ISO, TODAY_ISO, *rows)
    text = report_of(run(telegram_bot.performance_today_command, "/performance_today", [])[0])
    assert "• Requests assigned: not available (no request names a consultant; the column was not read)" in text
    assert "📋" not in text and "assigned to no consultant" not in text
    assert blocks(text)["Arshia Janan"] == ["├ ✅ Consultations done: `3`",
                                              "├ 📵 Follow-ups: No Answer `0` · Wrong Number `0`",
                                              "└ 💳 Payments verified: `0`"]


@pytest.mark.parametrize("failure, reason", [
    ("unreachable", "could not connect to the portal (ConnectError)"),
    ("refused login", "couldn't log in to the portal: simulated bad credentials"),
])
def test_a_portal_that_cannot_be_read_says_so_for_both_parts_never_zero(portal, monkeypatch, failure, reason):
    perf_portal(portal)
    if failure == "unreachable":
        def down(request):
            raise httpx.ConnectError("unreachable", request=request)
        monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(down)))
    else:
        async def refused(*args, **kwargs):
            return {"success": False, "error": "simulated bad credentials"}
        monkeypatch.setattr(admin_client, "is_authenticated", False)
        monkeypatch.setattr(admin_client, "login", refused)
    text = report_of(run(telegram_bot.performance_today_command, "/performance_today", [])[0])
    assert text.count(reason) == 2
    assert "• ❌ Consultations: couldn't read the portal:" in text and "• ❌ Payments verified: couldn't read" in text
    assert "• not available (neither part could be read)" in text and "`0`" not in text


# --------------------------------------------------------------------------- Telegram

class PickySent(Sent):
    async def edit_text(self, text, parse_mode=None, **kwargs):
        if parse_mode == "Markdown":
            raise BadRequest("Can't parse entities: can't find end of the entity starting at byte offset 7")
        return await super().edit_text(text, parse_mode=parse_mode, **kwargs)


class PickyMessage(Message):
    """Takes the "⏳" note, but refuses the report's Markdown (as Telegram does for a bad entity)."""

    async def reply_text(self, text, parse_mode=None, **kwargs):
        if parse_mode == "Markdown" and not text.startswith("⏳"):
            raise BadRequest("Can't parse entities: can't find end of the entity starting at byte offset 7")
        return PickySent(self.chat, text, parse_mode)


def test_a_report_whose_markdown_is_refused_is_resent_as_plain_text(portal):
    perf_portal(portal)
    update, context, chat = fake_update("/performance_today", [])
    update.message = PickyMessage(chat)
    asyncio.run(telegram_bot.performance_today_command(update, context))
    assert len(chat) == 1 and chat[0].parse_mode is None and chat[0].edits == 1
    assert chat[0].text.startswith("📈 Team Performance — Today, 28 September 2026")
    assert "• Received: 8" in chat[0].text and "*" not in chat[0].text


def test_a_long_report_is_split_under_telegrams_limit(portal):
    staff = [f"Counsellor Number {i:02d} With A Long Name" for i in range(80)]
    rows = [consult_row(f"S{i}", "Consulted", "28 Sep 2026", by=name, consultant=name) for i, name in enumerate(staff)]
    portal.pages[range_key(TODAY_ISO, TODAY_ISO)] = range_page(TODAY_ISO, TODAY_ISO, *rows)
    portal.pages.update(student_pages())
    chat, _ = run(telegram_bot.performance_today_command, "/performance_today", [])
    assert len(chat) > 1 and all(replies.telegram_len(m.text) <= replies.CHUNK_CHARS for m in chat)
    assert chat[0].edits == 1 and all(m.parse_mode == "Markdown" for m in chat)
    text = report_of(chat)
    assert all(f"*{n}. " in text for n in range(1, 83)) and all(name in text for name in staff)
    for piece in chat.shown():
        ok, error, rendered, _ = parse_legacy_markdown(piece)
        assert ok, error
    # No person's block is cut between two messages' Markdown entities.
    assert all(piece.count("*") % 2 == 0 and piece.count("`") % 2 == 0 for piece in chat.shown())


def test_every_report_is_valid_legacy_markdown(portal):
    perf_portal(portal)
    portal.pages[range_key(MONTH_FIRST, TODAY_ISO)] = month_page()
    for command in (telegram_bot.performance_today_command, telegram_bot.performance_month_command):
        for piece in run(command, "/x", [])[0].shown():
            ok, error, rendered, _ = parse_legacy_markdown(piece)
            assert ok, error
            assert replies.telegram_len(rendered) <= replies.TELEGRAM_LIMIT
    for fixed in (telegram_bot.get_commands_cheatsheet_text(),
                  ask.performance_other_reply(ask.performance_route("performance yesterday", TODAY)),
                  performance.waiting_text("month", date(2026, 9, 1), TODAY)):
        assert parse_legacy_markdown(fixed)[0], fixed


def test_an_unknown_sender_is_refused_with_their_chat_id(portal):
    perf_portal(portal)
    for command in (telegram_bot.performance_today_command, telegram_bot.performance_month_command,
                    telegram_bot.performance_command):
        update, context, chat = fake_update("/performance_today", [])
        update.effective_chat = SimpleNamespace(id=999)
        asyncio.run(command(update, context))
        assert chat.shown() == ["⛔ Unauthorized access. Your Chat ID is: `999`"]
    assert portal.asked == []


# --------------------------------------------------------------------------- menu, aliases, cheat-sheet

def test_both_commands_are_in_the_menu_the_handlers_and_the_cheat_sheet(monkeypatch):
    menus = []

    class App:
        bot = SimpleNamespace()

        def create_task(self, coroutine, update=None, name=None):
            coroutine.close()

    async def set_my_commands(commands, **kwargs):
        menus.append(commands)

    async def ok(*args, **kwargs):
        return SimpleNamespace(message_id=1)
    app = App()
    app.bot.set_my_commands, app.bot.send_message, app.bot.pin_chat_message = set_my_commands, ok, ok
    asyncio.run(telegram_bot.post_init(app))
    menu = {c.command: c.description for c in menus[0]}
    assert len(menu) == 13 and list(menu)[-2:] == ["performance_today", "performance_month"]
    assert "today" in menu["performance_today"] and "this month" in menu["performance_month"]
    assert all(len(d) <= 256 for d in menu.values())

    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:TEST-TOKEN-NOT-REAL")
    monkeypatch.setattr(settings, "ENABLE_SCHEDULED_REPORTS", False)    # no scheduler in tests
    built = telegram_bot.build_telegram_application()
    by_name = {name: h.callback for group in built.handlers.values() for h in group
               for name in getattr(h, "commands", ())}
    assert by_name["performance_today"] is by_name["perf_today"] is telegram_bot.performance_today_command
    assert by_name["performance_month"] is by_name["perf_month"] is telegram_bot.performance_month_command
    assert by_name["performance"] is telegram_bot.performance_command

    sheet = telegram_bot.get_commands_cheatsheet_text()
    assert "1️⃣1️⃣ `/performance_today`\n└ *Whole team's performance today" in sheet
    assert "1️⃣2️⃣ `/performance_month`\n└ *Whole team's performance this month (1st → today), per person*" in sheet
    assert "/performance\\_today" in ask.CANT_ANSWER and "/performance\\_month" in ask.CANT_ANSWER


@pytest.mark.parametrize("args, expect", [
    ([], "📈 *Team Performance — Today, 28 September 2026*"),
    (["today"], "📈 *Team Performance — Today, 28 September 2026*"),
    (["month"], "📈 *Team Performance — This Month, 01–28 September 2026*"),
    (["this", "month"], "📈 *Team Performance — This Month, 01–28 September 2026*"),
    (["last", "week"], "📈 Team performance is read for *today* (/performance\\_today) or for *this month*"),
    (["31", "Sep"], "I couldn't read the date there: 31 sep: September has 30 days"),
])
def test_the_performance_alias_reads_its_words(portal, args, expect):
    perf_portal(portal)
    portal.pages[range_key(MONTH_FIRST, TODAY_ISO)] = month_page()
    text = report_of(run(telegram_bot.performance_command, "/performance " + " ".join(args), args)[0])
    assert expect in text
    if "Team Performance —" not in expect:
        assert portal.asked == []                                       # nothing read for a window it cannot give


# --------------------------------------------------------------------------- free text

@pytest.mark.parametrize("text, topic", [
    ("performance today", "today"), ("today's performance", "today"), ("How did the team do today?", "today"),
    ("team performance", "today"), ("how is the team doing", "today"), ("staff activity today", "today"),
    ("this month's performance", "month"), ("monthly performance", "month"), ("performance this month", "month"),
    ("how did the team do this month", "month"), ("performance for September", "month"),
    ("team's performance month to date", "month"), ("performance so far this month", "month"),
])
def test_performance_questions_route_to_the_report(text, topic):
    route = ask.classify(text, TODAY)
    assert (route.kind, route.topic) == ("performance", topic), text


@pytest.mark.parametrize("text, what", [
    ("performance yesterday", "day"), ("last month's performance", "window"), ("performance last week", "window"),
    ("how did the team do on 12 Sep", "day"), ("performance over the past 3 months", "words"),
    ("performance on 31 Sep", "problem"),
])
def test_performance_questions_about_other_days_get_no_stand_in_window(text, what):
    route = ask.classify(text, TODAY)
    assert route.kind == "performance" and route.topic == "", text
    assert getattr(route, what), text


@pytest.mark.parametrize("text, kind", [
    ("consultations today", "inquiries"), ("how many consultations were done today", "inquiries"),
    ("consultations handled by Arshia Janan", "inquiries"), ("Total verified students today", "verified"),
    ("summary for today", "report"), ("show pending payments", "pending"), ("any deadlines this week", "calendar"),
    ("applications under review", "window_review"), ("students across all programs", "dashboard"),
    ("the team's deadlines this month", "calendar"), ("performing arts", "unknown"), ("pin the menu", "pin"),
])
def test_other_questions_keep_their_own_routes(text, kind):
    assert ask.classify(text, TODAY).kind == kind, text


@pytest.fixture
def recorded(monkeypatch):
    ran = []

    def recorder(name):
        async def command(update, context):
            ran.append(name)
            await update.message.reply_text(f"{name} answered")
        return command
    for name in ("performance_today_command", "performance_month_command", "inquiries_today_command",
                 "verified_today_command", "report_command"):
        monkeypatch.setattr(telegram_bot, name, recorder(name))
    return ran


@pytest.mark.parametrize("said, command", [
    ("performance today", "performance_today_command"), ("today's performance", "performance_today_command"),
    ("how did the team do today", "performance_today_command"),
    ("this month's performance", "performance_month_command"), ("monthly performance", "performance_month_command"),
    ("performance this month", "performance_month_command"),
    ("consultations today", "inquiries_today_command"), ("verified students today", "verified_today_command"),
])
def test_free_text_reaches_the_right_command(portal, recorded, said, command):
    run(telegram_bot.handle_natural_language_message, said, None)
    assert recorded == [command]


def test_free_text_about_another_day_is_told_what_can_be_read(portal, recorded):
    chat, _ = run(telegram_bot.handle_natural_language_message, "how did the team do yesterday", None)
    assert recorded == [] and portal.asked == []
    assert chat.shown() == ["📈 Team performance is read for *today* (/performance\\_today) or for *this month*, "
                            "from its 1st to today (/performance\\_month), and you asked about Sun 27 Sep 2026.\n"
                            "For one day's consultations or payments, use /inquiries\\_date or /verified\\_date."]


# --------------------------------------------------------------------------- the staging copy (R24)

def test_the_root_staging_copies_are_byte_identical():
    for root, src in (("telegram_bot.py", "src/bot/telegram_bot.py"), ("config.py", "src/config.py"),
                      ("progress_builder.py", "src/sheets/progress_builder.py")):
        assert filecmp.cmp(BOT_ROOT / root, BOT_ROOT / src, shallow=False), root


# --------------------------------------------------------------------------- Telegram's legacy Markdown

def parse_legacy_markdown(text: str):
    """Telegram's parse_mode="Markdown" (v1), as tdlib parses it (a copy of the command audit's
    tg_markdown.py re-implementation): -> (ok, error or None, rendered text, entities)."""
    out, ents = [], []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and text[i + 1] in "_*`[":
            out.append(text[i + 1])
            i += 2
            continue
        if c not in "_*`[":
            out.append(c)
            i += 1
            continue
        begin = i
        end_ch = "]" if c == "[" else c
        is_pre = False
        i += 1
        if c == "`" and text[i:i + 2] == "``":
            is_pre = True
            i += 2
            j = i
            while j < n and text[j] not in " \n`":
                j += 1
            if j < n and text[j] == "\n":
                i = j + 1
            end_ch = "`"
        start_len = len("".join(out))
        while i < n and (text[i] != end_ch or (is_pre and text[i + 1:i + 3] != "``")):
            out.append(text[i])
            i += 1
        if i >= n:
            return False, f"Can't find end of the entity starting at offset {begin}", None, ents
        cur_len = len("".join(out))
        if cur_len != start_len:
            kind = {"_": "italic", "*": "bold", "`": "pre" if is_pre else "code", "[": "text_link"}[c]
            if c == "[" and i + 1 < n and text[i + 1] == "(":
                i += 2
                url_begin = i
                while i < n and text[i] != ")":
                    i += 1
                if i >= n:
                    return False, f"Can't find end of a URL at offset {url_begin}", None, ents
            ents.append((kind, start_len, cur_len - start_len))
        if is_pre:
            i += 2
        i += 1
    return True, None, "".join(out), ents
