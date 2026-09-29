"""Typed (and spoken) questions in plain words: src/bot/ask.py, the routing in
telegram_bot.handle_natural_language_message and /calendar's query handling, the LLM's fact pick
(ollama_client.answer_agent_query) and Jennie's spoken answers (src/bot/voice.py).

What is pinned here: questions are read on whole words and real dates ("across" is no "cross",
"shipping" no "pin", "Janan" no January, "summary" no March, "doctor" no October, "daughter" no
August); every data question reaches the live read that answers it; a span of days such as "this
week" is real date logic (today to Sunday); a question the portal cannot answer gets "I can't
answer that from the portal yet", never an LLM guess; a portal that cannot be read is said plainly;
the LLM only picks facts, shown word for word; and Jennie says only the figures an answer states,
for the day it is for.

Every portal page is synthetic (laid out like the live pages, Sep 2026). Nothing reaches the
network, Telegram, the voice service or Ollama.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_freetext.py -q
"""
import asyncio
import json
import re
from datetime import date

import pytest

from test_foundation import (  # noqa: F401  (the portal fixture is used by name)
    ADMIN_ID, BACHELOR, KLP, TODAY, page, pin_today, portal, report_of, row, run,
)
from src.bot import ask, replies, telegram_bot, voice
from src.llm.ollama_client import ollama_client

EAP = "EAP (ENGLISH FOR ACADEMIC PURPOSE)"


# --------------------------------------------------------------------------- synthetic pages

def _tile(href, num, label):
    return (f'<a class="stat-card kpi" href="{href}"><span class="kpi-txt"><span class="stat-num">{num}</span>'
            f'<span class="stat-lbl">{label}</span></span></a>')


def _sec(title):
    return f'<div class="dash-sec"><div class="ds-txt"><h2 class="ds-t">{title}</h2></div></div>'


def _card(title, body):
    return f'<section class="card"><div class="card-head"><h2 class="card-title"><i></i> {title}</h2></div>{body}</section>'


def _wf(label, count, note=""):
    span = f"<span>{note}</span>" if note else ""
    return (f'<a class="wf-item" href="students.php"><div class="wf-icon"><i></i></div>'
            f'<div class="wf-info"><strong>{label}</strong>{span}</div><div class="wf-count">{count}</div></a>')


def _pipe(label, count):
    return (f'<a class="wf-item pipe-row" href="students.php?stage=x"><span class="pipe-main"><span class="pipe-top">'
            f'<strong>{label}</strong><span class="pipe-c">{count}</span></span></span></a>')


def dashboard_page(total=330, pending=2, under_review=0, visa_result=0):
    return ('<div class="dash">' + _sec("Admissions flow") + '<div class="stats-row">'
            + _tile("admission_windows.php?status=active", 3, "Open windows")
            + _tile("admission_windows.php?status=draft", 0, "Draft windows")
            + _tile("window_applications.php?status=submitted", 0, "Submitted apps")
            + _tile("window_applications.php?status=under_review", under_review, "Under review")
            + _tile("review_queue.php", 44, "Docs to review")
            + _tile("window_applications.php?status=accepted", 3, "Accepted") + "</div>"
            + _sec("Direct / legacy pipeline") + '<div class="stats-row">'
            + _tile("students.php", total, "Total students")
            + _tile("students.php?status=pending", pending, "Pending payment")
            + _tile("students.php?status=verified", total - pending, "Verified")
            + _tile("students.php?filter_docs=unverified", 11, "Docs to review")
            + _tile("students.php?stage=Admitted+%2F+Completed", 0, "Admitted") + "</div></div>"
            + _card("Needs attention", '<div class="card-body flush">'
                    + _wf("Payment verification", pending, "Students waiting for payment approval")
                    + _wf("Document review", 11, "Documents waiting for verification")
                    + _wf("Rejected documents", 13, "Awaiting student re-upload") + "</div>")
            + _card("At a glance", '<div class="glance-grid">'
                    '<div class="gl"><span class="gl-v">24</span><span class="gl-l">Applied this week</span></div>'
                    '<div class="gl"><span class="gl-v">114</span><span class="gl-l">Applied this month</span></div>'
                    '<div class="gl"><span class="gl-v">146</span><span class="gl-l">Docs approved</span></div>'
                    '<div class="gl"><span class="gl-v">170</span><span class="gl-l">Total docs</span></div></div>')
            + _card("Application pipeline", '<div class="card-body flush pipe">' + _pipe("Payment Verified", 158)
                    + _pipe("Documents Under Review", 20) + _pipe("University Applied", 45)
                    + _pipe("Embassy Submission", 0) + _pipe("Visa Result", visa_result)
                    + _pipe("Admitted / Completed", 0) + "</div>")
            + _card("Applications by program", '<div class="dash-list">' + _wf(KLP, 216) + _wf(BACHELOR, 56)
                    + _wf(EAP, 30) + _wf("MASTER'S DEGREE", 28) + "</div>")
            + _card("Top universities", '<div class="dash-list">' + _wf("Hanyang University", 171)
                    + _wf("KYUNGSUNG UNIVERSITY", 14) + _wf("SEJONG UNIVERSITY", 6) + "</div>"))


def pending_pages():
    badge = '<nav><a href="students.php?status=pending">Pending Payments <span class="b">3</span></a></nav>'
    first = page(row(579, 1, "HAZARI TOMAL", pay="Pending", stage="Application Received", applied="28 Sep 2026",
                     uni="HANYANG UNIVERSITY"),
                 row(577, 2, "UDDIN MD KOWSAR", pay="Pending", program=EAP, intake="DECEMBER 2026",
                     stage="Application Received", applied="28 Sep 2026"),
                 pg=1, pages=2, total=3).replace("<body>", "<body>" + badge)
    second = page(row(501, 3, "KARIM LATE PAYER", pay="Pending", applied="20 Sep 2026", stage="Application Received"),
                  pg=2, pages=2, total=3)
    return {"students.php?status=pending": first, "students.php?status=pending&pg=2": second}


def window_page(*statuses):
    head = "<tr><th></th><th>Student</th><th>Window</th><th>Status</th><th>Docs</th></tr>"
    rows = "".join(f'<tr><td></td><td>Student {i}</td><td>Window {i}</td><td><span class="status-pill">{s}</span>'
                   f"</td><td>3/5</td></tr>" for i, s in enumerate(statuses)) or '<tr><td colspan="5">None</td></tr>'
    return f"<table>{head}{rows}</table>"


def rm_item(title, kind, sub, progress="", eid=""):
    bar = f'<div style="margin-top:6px"><div style="font-size:10.5px">{progress}</div></div>' if progress else ""
    href = f"calendar.php?ym=2026-09&amp;view=month&amp;edit={eid}" if eid else "calendar.php"
    return ('<div class="rm-item"><span><i></i></span><div style="flex:1;min-width:0">'
            f'<a href="{href}" class="rm-title">{title}</a>'
            f'<div style="font-size:11.5px"><span style="font-weight:700">{kind}</span> {sub}</div>{bar}</div>'
            '<form><button class="rm-done">Complete</button></form></div>')


def ev_row(day, month, title, kind, sub, status, eid="", note=""):
    href = f"calendar.php?ym=2026-09&amp;view=month&amp;edit={eid}" if eid else "calendar.php"
    note = f'<div style="font-size:11.5px;color:#475569;margin-top:2px">{note}</div>' if note else ""
    return (f'<div class="ev-row"><div class="li-date"><div class="d">{day}</div><div class="w">{month}</div></div>'
            f'<span class="ev-ic"><i></i></span><div class="ev-main"><a class="ev-title" href="{href}">{title}</a>'
            f'<div class="ev-sub"><span style="font-weight:700">{kind}</span> {sub}</div>{note}</div>'
            f'<span class="st ok">{status}</span></div>')


EV = [
    {"id": 1, "type": "dhl", "title": "SEJONG DHL", "uni": "Sejong University", "start": "2026-09-26",
     "end": "2026-09-28", "time": "14:00", "done": 0},
    {"id": 2, "type": "dhl", "title": "JEONBUK DHL", "uni": "Jeonbuk University", "start": "2026-09-26",
     "end": "2026-10-05", "time": "14:00", "done": 0},
    {"id": 3, "type": "period", "title": "Jeonbuk University - Application open", "uni": "Jeonbuk University",
     "start": "2026-09-21", "end": "2026-10-02", "time": "14:00", "done": 0},
    {"id": 4, "type": "period", "title": "HANYANG UNIVERSITY - APPLICATION OPEN", "uni": "HANYANG UNIVERSITY",
     "start": "2026-09-01", "end": "2026-09-18", "time": "", "done": 0},
    {"id": 5, "type": "dhl", "title": "HANYANG BACHELOR", "uni": "Hanyang University", "start": "2026-09-20",
     "end": "2026-09-22", "time": "14:00", "done": 1},
    {"id": 6, "type": "period", "title": "FAR EAST UNIVERSITY- APPLICATION OPEN", "uni": "FAR EAST UNIVERSITY",
     "start": "2026-09-01", "end": "2026-10-09", "time": "", "done": 0},
]


def calendar_html(ev=EV, with_ev=True):
    # Each entry carries its event's own id in its edit link, as the portal's do (the EV list's "id").
    reminders = (rm_item("SEJONG DHL", "DHL to send", "· 26 Sep–28 Sep · 14:00 · Sejong University", eid=1)
                 + rm_item("JEONBUK DHL", "DHL to send", "· 26 Sep–05 Oct · 14:00 · Jeonbuk University", eid=2)
                 + rm_item("Jeonbuk University - Application open", "Application period",
                           "· 21 Sep–02 Oct · 14:00 · Jeonbuk University", "64% of window elapsed · 4 days left",
                           eid=3)
                 + rm_item("FAR EAST UNIVERSITY- APPLICATION OPEN", "Application period",
                           "· 01 Sep–09 Oct · FAR EAST UNIVERSITY", "71% of window elapsed · 11 days left", eid=6))
    upcoming = (ev_row(21, "Sep", "Jeonbuk University - Application open", "Application period",
                       "· 21 Sep · <b>14:00</b> – 02 Oct 2026 · Jeonbuk University", "Closes in 4 days", eid=3)
                + ev_row(26, "Sep", "SEJONG DHL", "DHL to send", "· 26 Sep · Sejong University", "Today", eid=1)
                + ev_row(26, "Sep", "JEONBUK DHL", "DHL to send", "· 26 Sep · Jeonbuk University", "In 7 days", eid=2)
                # Next month's events are only on the 45-day timeline, never in the month's event list.
                + ev_row(7, "Oct", "GACHON UNIVERSITY - APPLICATION OPEN", "Application period",
                         "· 07 Oct – 14 Oct 2026 · GACHON UNIVERSITY", "Opens in 9 days", eid=7)
                + ev_row(8, "Oct", "DANKOOK UNIVERSITY DHL", "DHL to send", "· 08 Oct · DANKOOK UNIVERSITY",
                         "In 10 days", eid=8))
    script = f"<script>var EV = {json.dumps(ev)};\nvar X = 1;</script>" if with_ev else ""
    return ('<div class="cal-layout">'
            '<div class="cal-card"><div class="sec-h"><i></i>Reminders for today<small>· Monday, 28 Sep 2026 · 4 items'
            f'</small></div>{reminders}</div>'
            f'<div class="cal-card"><div class="sec-h">Upcoming <small>· next 45 days</small></div><div>{upcoming}</div></div>'
            f"</div>{script}")


@pytest.fixture
def live(portal):
    """The synthetic portal with every page the free-text answers read."""
    portal.pages.update({
        "index.php": dashboard_page(),
        "calendar.php": calendar_html(),
        "window_applications.php?status=under_review": window_page(),
        "students.php": page(row(10, 1, "KIM SEOYEON", intake="MARCH 2027", applied="28 Sep 2026"),
                             row(11, 2, "KARIM MIA", program=BACHELOR, intake="March 2027", applied="27 Sep 2026"),
                             pg=1, pages=2, total=4),
        "students.php?pg=2": page(row(12, 3, "ALAM EAP", program=EAP, intake="DECEMBER 2026", applied="21 Sep 2026"),
                                  row(13, 4, "RAHMAN OLD", intake="MARCH 2027", applied="20 Sep 2026"),
                                  pg=2, pages=2, total=4),
        **pending_pages(),
    })
    return portal


def ask_bot(text, user_data=None):
    chat, context = run(telegram_bot.handle_natural_language_message, text, None, user_data)
    return report_of(chat), context, chat


@pytest.fixture
def commands(monkeypatch):
    """The bot's own commands replaced by recorders: which one a question reaches, with what."""
    ran = []

    def recorder(name):
        async def command(update, context):
            ran.append((name, context.user_data.get("override_text"), context.user_data.get("override_query")))
            await update.message.reply_text(f"{name} answered")
        return command

    for name in ("verified_today_command", "verified_date_command", "verified_command", "inquiries_today_command",
                 "inquiries_date_command", "crosscheck_today_command", "crosscheck_date_command",
                 "crosscheck_range_command", "crosscheck_command", "pin_command", "admitted_command",
                 "calendar_command", "passports_command", "report_command", "stats_command", "missing_command",
                 "stage_command"):
        monkeypatch.setattr(telegram_bot, name, recorder(name))
    return ran


# --------------------------------------------------------------------------- whole words, real dates

@pytest.mark.parametrize("text, kind", [
    ("how many students across all programs", "dashboard"),      # "across" is no "cross"
    ("students across all programs", "dashboard"),
    ("any DHL shipping due this week", "calendar"),              # "shipping" is no "pin"
    ("DHL shipping status", "calendar"),
    ("keep typing the menu", "pin"),                             # "menu" as a whole word is
    ("is the doctor in", "unknown"),                             # "doctor" is no October
    ("my daughter wants to apply", "unknown"),                   # "daughter" is no August
    ("summary for today", "report"),                             # "summary" is no March
    ("Janan's consultations", "inquiries"),                     # "Janan" is no January
    ("who is admitted to hanyang?", "admitted"),
    ("which universities have admission open", "calendar"),      # "admission" is no "admitted"
    ("crosscheck please", "crosscheck"),
    ("cross-check student 412", "crosscheck"),
    ("show pending payments", "pending"),
    ("documents waiting for verification", "dashboard"),         # documents, not /verified
    ("applications under review", "window_review"),
    ("how many students in March 2027 intake", "intake"),
    ("report for 07 Sep 2026", "report"),                        # a date, not the SEPTEMBER 2026 intake
    ("any passport issues today?", "passports"),
    ("hello", "hello"),
    ("what is the office phone policy", "unknown"),
])
def test_questions_are_read_on_whole_words(text, kind):
    assert ask.classify(text, TODAY).kind == kind


@pytest.mark.parametrize("text, day, problem", [
    ("how many consultations yesterday", date(2026, 9, 27), None),
    ("how many consultations on 3 Sep 2026", date(2026, 9, 3), None),
    ("how many consultations on 8 Sep", date(2026, 9, 8), None),
    ("Janan's consultations", None, None),                      # no date: today
    ("how many students were verified on the 12th of September", date(2026, 9, 12), None),
    ("verified students on 31 Sep", None, "31 sep: September has 30 days"),
    ("who was verified in sep", None, "it names a month but no day of it"),
])
def test_the_day_a_question_names(text, day, problem):
    route = ask.classify(text, TODAY)
    assert (route.day, route.problem) == (day, problem) and route.window is None


@pytest.mark.parametrize("text, first, last", [
    ("any deadlines this week", date(2026, 9, 28), date(2026, 10, 4)),      # today (a Monday) to Sunday
    ("deadlines next week", date(2026, 10, 5), date(2026, 10, 11)),
    ("events in the next 10 days", date(2026, 9, 28), date(2026, 10, 7)),
    ("deadlines in october", date(2026, 10, 1), date(2026, 10, 31)),
    ("anything on friday", date(2026, 10, 2), date(2026, 10, 2)),
    ("deadlines between today and 5 Oct", date(2026, 9, 28), date(2026, 10, 5)),
    ("what is due on 2 Oct", date(2026, 10, 2), date(2026, 10, 2)),
    ("coming up", date(2026, 9, 28), None),
])
def test_date_windows_are_real_dates(text, first, last):
    window, problem = ask.date_window(text, TODAY)
    assert problem is None and (window.first, window.last) == (first, last)


def test_a_week_on_another_day_runs_from_today_to_sunday():
    thursday = date(2026, 10, 1)
    window, _ = ask.date_window("any deadlines this week", thursday)
    assert (window.first, window.last) == (thursday, date(2026, 10, 4))
    window, _ = ask.date_window("how many applied this week", thursday, forward=False)
    assert (window.first, window.last) == (date(2026, 9, 28), thursday)
    assert ask.date_window("deadlines on 31 Sep", TODAY) == (None, "31 sep: September has 30 days")
    assert ask.date_window("deadlines for Hanyang", TODAY) == (None, None)


# --------------------------------------------------------------------------- routing to the commands

@pytest.mark.parametrize("said, expected", [
    ("how many students were verified today", ("verified_today_command", None, None)),
    ("how many students were verified on 12 Sep 2026",
     ("verified_date_command", "how many students were verified on 12 Sep 2026", None)),
    ("how many consultations yesterday", ("inquiries_date_command", "27 Sep 2026", None)),
    ("how many consultations today", ("inquiries_today_command", None, None)),
    ("Janan's consultations", ("inquiries_today_command", None, None)),
    ("how many consultations on 3 Sep 2026", ("inquiries_date_command", "03 Sep 2026", None)),
    ("how many consultations on 31 Sep", ("inquiries_date_command", "how many consultations on 31 Sep", None)),
    ("summary for today", ("report_command", "summary for today", None)),
    ("any deadlines this week", ("calendar_command", "any deadlines this week", None)),
    ("DHL shipping status", ("calendar_command", "DHL shipping status", None)),
    ("any DHL shipping due this week", ("calendar_command", "any DHL shipping due this week", None)),
    ("show me the menu", ("pin_command", None, None)),
    ("who is admitted to hanyang?", ("admitted_command", None, "hanyang")),
    ("students with missing information", ("missing_command", None, None)),
    ("show student stages", ("stage_command", None, None)),
    ("any passport issues today?", ("crosscheck_today_command", None, None)),
    ("which students have passport problems", ("crosscheck_today_command", None, None)),
    ("passport problems on 12 Sep 2026", ("crosscheck_date_command", "12 Sep 2026", None)),
    ("cross check payments for 3 September", ("crosscheck_date_command", "cross check payments for 3 September", None)),
    ("crosscheck please", ("crosscheck_date_command", None, None)),
    ("stats", ("stats_command", None, None)),
])
def test_each_question_reaches_its_command(portal, commands, said, expected):
    ask_bot(said)
    assert commands == [expected]


def test_the_old_substring_traps_never_misroute(portal, commands):
    """"across" once went to the cross-check (and its date prompt ate the next message), "shipping"
    to /pin (which pinned the cheat-sheet), "summary" to a March report."""
    text, context, _ = ask_bot("how many students across all programs")
    assert commands == [] and "awaiting_date_for" not in context.user_data
    ask_bot("any DHL shipping due this week")
    assert commands == [("calendar_command", "any DHL shipping due this week", None)]
    assert not any(name == "pin_command" for name, _, _ in commands)


def test_a_span_of_days_for_a_one_day_answer_asks_which_day(portal, commands):
    text, context, _ = ask_bot("how many consultations last week")
    assert commands == [] and context.user_data["awaiting_date_for"] == "inquiries"
    assert "counted one day at a time" in text and "last week (Mon 21 Sep – Sun 27 Sep 2026)" in text
    # The next message is the day.
    ask_bot("25 Sep", context.user_data)
    assert commands == [("inquiries_date_command", "25 Sep", None)]
    # A passport check or a cross-check over a span is the range cross-check (up to today).
    ask_bot("passport problems last week")
    assert commands[-1] == ("crosscheck_range_command", "21 Sep 2026 to 27 Sep 2026", None)
    ask_bot("cross-check last week")
    assert commands[-1] == ("crosscheck_range_command", "21 Sep 2026 to 27 Sep 2026", None)
    ask_bot("cross-check student 412 last week")
    assert commands[-1] == ("crosscheck_command", "cross-check student 412 last week", None)


def test_the_report_route_fires_only_for_real_report_requests(monkeypatch):
    pin_today(monkeypatch)
    for text in ("how many students today", "how many were done", "who came yesterday", "8 Sep",
                 "what happened in march", "how many consultations today"):
        assert telegram_bot.parse_user_report_intent(text) == (False, "", ""), text
    assert telegram_bot.parse_user_report_intent("summary for today") == (True, "28 Sep 2026", "28 September 2026")
    assert telegram_bot.parse_user_report_intent("report for 07 Sep 2026") == (True, "07 Sep 2026", "07 September 2026")
    assert telegram_bot.parse_user_report_intent("daily brief 31 Sep") == (True, "", "")   # report_command says so


# --------------------------------------------------------------------------- the live answers

def test_pending_payments_are_read_from_every_page_with_names(live):
    text, _, chat = ask_bot("who has pending payment")
    assert "• Pending payments: `3` (students.php?status=pending, every page read)" in text
    assert "HAZARI TOMAL" in text and "UDDIN MD KOWSAR" in text and "KARIM LATE PAYER" in text
    assert "The portal's own Pending Payments count says 3 too." in text
    assert "separate figure, never added" in text and "Under review" not in text      # guardrail 2
    assert [k for m, k in live.asked if k.startswith("students")] == [
        "students.php?status=pending", "students.php?status=pending&pg=2"]
    assert len(chat) == 1 and chat[0].edits == 1                     # the "🤔" note became the answer


def test_window_applications_under_review_are_their_own_figure(live):
    live.pages["window_applications.php?status=under_review"] = window_page("Under Review", "Under Review", "Accepted")
    text, _, _ = ask_bot("applications under review")
    assert "• Window applications under review: `2`" in text
    assert "⚠️ The dashboard's Under review tile says 0." in text
    assert "Pending payments are a separate figure" in text and "`3`" not in text


@pytest.mark.parametrize("said, shown, absent", [
    ("what is the total number of students", ["• Total students (Direct / legacy pipeline): `330`",
                                              f"{KLP} `216`"], ["262"]),
    ("total applicants on record", ["Total students (Direct / legacy pipeline): `330`"], ["262"]),
    ("students across all programs", [f"• {KLP} (Applications by program): `216`",
                                      "• MASTER'S DEGREE (Applications by program): `28`",
                                      "• Total students (Direct / legacy pipeline): `330`"], []),
    ("how many KLP students", [f"• {KLP} (Applications by program): `216`"], ["BACHELOR"]),
    ("which university has the most students", ["• *Most students:* Hanyang University (`171`)"], ["1565"]),
    ("registrations this week", ["• Applied this week (At a glance): `24`"], ["31", "month"]),
    ("how many students registered this month", ["• Applied this month (At a glance): `114`"], ["week"]),
    ("documents waiting for review", ["• Docs to review (Direct / legacy pipeline): `11`",
                                      "• Docs to review (Admissions flow): `44`",
                                      "• Documents Under Review (Application pipeline): `20`"], ["21"]),
    ("how many rejected documents", ["Rejected documents — Awaiting student re-upload (Needs attention): `13`"], []),
    ("visas approved so far this year", ["I can't answer that from the portal yet: it has no count of approved visas.",
                                         "• Visa Result (Application pipeline): `0` students at that stage now",
                                         "• Accepted (Admissions flow): `3` accepted admission-window applications, not visas"],
     ["Visas Approved"]),
    ("how many students at the University Applied stage", ["• University Applied (Application pipeline): `45`"],
     ["Payment Verified"]),
    ("how many open windows", ["• Open windows (Admissions flow): `3`"], ["Draft"]),
    ("total verified students so far", ["• Verified (Direct / legacy pipeline): `328`"], []),
])
def test_dashboard_questions_are_answered_from_its_live_figures(live, said, shown, absent):
    text, _, _ = ask_bot(said)
    for part in shown:
        assert part in text, part
    for part in absent:
        assert part not in text, part
    assert "Read live from the portal dashboard" in text


def test_intakes_and_application_dates_are_counted_from_every_page(live):
    text, _, _ = ask_bot("how many students in March 2027 intake")
    assert "• Students in the MARCH 2027 intake: `3`" in text              # "March 2027" is the same intake
    assert f"{KLP} `2`" in text and f"{BACHELOR} `1`" in text
    assert "every page of the student list (4 students)" in text
    text, _, _ = ask_bot("how many EAP students in December 2026 intake")
    assert "• Students in EAP in the DECEMBER 2026 intake: `1`" in text
    text, _, _ = ask_bot("how many students applied last week")
    assert "*Students who applied — last week (Mon 21 Sep – Sun 27 Sep 2026)*" in text
    assert "• Students who applied: `2`" in text
    text, _, _ = ask_bot("how many students applied today")
    assert "*Students who applied — today (Mon 28 Sep 2026)*" in text and "• Students who applied: `1`" in text


@pytest.mark.parametrize("said", ["show pending payments", "what is the total number of students",
                                  "how many students in March 2027 intake", "applications under review",
                                  "any deadlines this week"])
def test_a_portal_that_cannot_be_read_is_said_plainly_never_zero(portal, said):
    text, _, _ = ask_bot(said)                     # no page is there: every read answers 404
    assert text.startswith("❌ Couldn't read the portal:") and "not available right now" in text
    assert "`0`" not in text and "None on the calendar" not in text


def test_a_question_with_no_answer_on_the_portal_is_said_honestly(live, monkeypatch):
    asked = []

    async def pick(query, facts):
        asked.append((query, facts))
        return []                                  # the LLM finds no fact that answers it

    monkeypatch.setattr(ollama_client, "answer_agent_query", pick)
    text, _, _ = ask_bot("what is the office phone policy")
    assert text.startswith("🤷 I can't answer that from the portal yet.")
    assert "/verified\\_today" in text and "/calendar" in text
    # The LLM saw one live figure a line, no raw inquiry dicts, contacts or remarks.
    (query, facts), = asked
    assert "Total students (Direct / legacy pipeline): 330" in facts and all(":" in f for f in facts)
    assert not any(re.search(r"contact|remark|phone|@", f, re.I) for f in facts)


def test_the_facts_the_llm_picks_are_shown_word_for_word(live, monkeypatch):
    async def pick(query, facts):
        return [f for f in facts if f.startswith("Hanyang University")]

    monkeypatch.setattr(ollama_client, "answer_agent_query", pick)
    text, _, _ = ask_bot("how many students chose hanyang")
    assert "• Hanyang University (Top universities): `171`" in text
    assert "each figure is the portal's own" in text


# --------------------------------------------------------------------------- /calendar

def test_deadlines_this_week_apply_real_dates(live):
    text, _, _ = ask_bot("any deadlines this week")
    assert "📅 *Deadlines — this week (Mon 28 Sep – Sun 04 Oct 2026)*" in text
    assert "• Deadlines still open: `2`" in text
    assert "*SEJONG DHL* — DHL to send · Sejong University · 26 Sep–28 Sep — due *today* (Mon 28 Sep)" in text
    assert "closes Fri 02 Oct (4 days left)" in text
    assert "FAR EAST" not in text and "HANYANG" not in text and "GACHON" not in text
    assert "_The next one after that: JEONBUK DHL, due Mon 05 Oct (7 days left)._" in text
    assert "any this week" not in text and "No calendar events found" not in text


def test_dhl_questions_and_searches(live):
    text, _, _ = ask_bot("DHL shipping status")
    assert "• DHL shipments still to send: `3`" in text and "DANKOOK UNIVERSITY DHL" in text     # from the 45-day timeline
    assert "due Thu 08 Oct (10 days left)" in text
    assert "_Marked done: HANYANG BACHELOR (due 22 Sep)._" in text
    text, _, _ = ask_bot("any DHL shipping due this week")
    assert "• DHL shipments still to send: `1`" in text and "SEJONG DHL" in text and "JEONBUK DHL, due Mon 05 Oct" in text
    chat, _ = run(telegram_bot.calendar_command, "/calendar Hanyang", ["Hanyang"])
    text = report_of(chat)
    assert "matching “hanyang”" in text and "HANYANG UNIVERSITY - APPLICATION OPEN" in text
    assert "closed Fri 18 Sep" in text and "HANYANG BACHELOR" not in text           # done: not listed
    chat, _ = run(telegram_bot.calendar_command, "/calendar deadlines in october", ["deadlines", "in", "october"])
    text = report_of(chat)
    assert "October 2026" in text and "GACHON UNIVERSITY - APPLICATION OPEN" in text and "closes Wed 14 Oct" in text


def test_calendar_items_merge_the_three_lists():
    items, ok = ask.calendar_items(calendar_html(), TODAY)
    by = {i.title: i for i in items}
    assert ok and by["JEONBUK DHL"].end == date(2026, 10, 5) and by["SEJONG DHL"].end == date(2026, 9, 28)
    assert by["GACHON UNIVERSITY - APPLICATION OPEN"][3:5] == (date(2026, 10, 7), date(2026, 10, 14))
    assert by["DANKOOK UNIVERSITY DHL"].end == date(2026, 10, 8)                  # "In 10 days"
    assert by["HANYANG BACHELOR"].done and len(items) == len(by)                  # each item once
    # Without the month's event list, the reminders and the timeline still give the dates.
    items, ok = ask.calendar_items(calendar_html(with_ev=False), TODAY)
    by = {i.title: i for i in items}
    assert ok and by["Jeonbuk University - Application open"].end == date(2026, 10, 2)
    assert by["JEONBUK DHL"].end == date(2026, 10, 5)
    assert ask.calendar_items("<html>changed</html>", TODAY) == ([], False)


def test_calendar_query_errors_and_the_default_view(live):
    chat, _ = run(telegram_bot.calendar_command, "/calendar 31 Sep", ["31", "Sep"])
    assert "I couldn't read “31 Sep” as a date (31 sep: September has 30 days)" in report_of(chat)
    assert not any(k.startswith("calendar") for _, k in live.asked)           # no read for a bad date
    chat, _ = run(telegram_bot.calendar_command, "/calendar", [])
    text = report_of(chat)
    assert "⚡ *Reminders for today (4 items):*" in text and "No calendar events found" not in text
    chat, _ = run(telegram_bot.calendar_command, "/deadlines", [])
    assert "⚡ *Reminders for today (4 items):*" in report_of(chat)
    live.pages["calendar.php"] = "<html>a new layout</html>"
    chat, _ = run(telegram_bot.calendar_command, "/calendar this week", ["this", "week"])
    assert report_of(chat).startswith("❌ Couldn't read the portal: calendar.php: its layout was not recognised")


# --------------------------------------------------------------------------- the LLM's fact pick

class _Brain:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    async def chat(self, messages, format=None, num_predict=None, timeout=None):
        self.calls.append({"messages": messages, "format": format, "num_predict": num_predict})
        return self.answer


FACTS = ["Total students (Direct / legacy pipeline): 330", "Open windows (Admissions flow): 3",
         "Hanyang University (Top universities): 171"]


def test_the_llm_only_picks_facts_by_number(monkeypatch):
    brain = _Brain('{"facts": [3, 9, 3], "answered": true}')
    monkeypatch.setattr(ollama_client, "chat", brain.chat)
    assert asyncio.run(ollama_client.answer_agent_query("hanyang students?", FACTS)) == [FACTS[2]]
    call = brain.calls[0]
    assert call["num_predict"] == 60 and call["format"]["required"] == ["facts", "answered"]
    assert "1. Total students (Direct / legacy pipeline): 330" in call["messages"][1]["content"]
    for answer, expected in (('{"facts": [1], "answered": false}', []), ("no JSON at all", None),
                             ('{"facts": "one"}', None), (None, None)):
        monkeypatch.setattr(ollama_client, "chat", _Brain(answer).chat)
        assert asyncio.run(ollama_client.answer_agent_query("q", FACTS)) == expected


def test_facts_that_do_not_fit_the_context_skip_the_llm(monkeypatch):
    brain = _Brain('{"facts": [1], "answered": true}')
    monkeypatch.setattr(ollama_client, "chat", brain.chat)
    many = [f"Figure number {n} (Somewhere): {n}" for n in range(3000)]
    assert asyncio.run(ollama_client.answer_agent_query("q", many)) is None and brain.calls == []


def test_the_fallback_without_the_llm_only_names_whole_labels():
    assert ollama_client._answer_query_fallback("how many open windows?", FACTS) == [FACTS[1]]
    assert ollama_client._answer_query_fallback("how many windows", FACTS) == []
    assert ollama_client._answer_query_fallback("total students please", FACTS) == [FACTS[0]]
    assert ollama_client._answer_query_fallback("anything", []) == []


# --------------------------------------------------------------------------- Jennie

VERIFIED_12 = ("✅ *Student Payment Verifications — 12 September 2026*\n• *Total Students Verified:* `10`\n"
               "• *Total Verified Revenue:* `৳ 152,000.00 BDT`\n\n📋 *Verified Student Records:*\n*1. A B*\n"
               "   ├ 💰 *Payment:* `20,000.00 BDT Cash`\n*2. C D*\n   ├ 💰 *Payment:* `8,000.00 BDT Cash`")
INQUIRIES = ("📞 *Consultancy Inquiries Report — 27 September 2026*\n• *Total Inquiries on Portal:* `999`\n"
             "📅 *Performance on 27 September 2026:*\n• *Inquiries Received:* `21`\n• *Inquiries Done:* `17`\n"
             "   ├ ✅ *Consulted:* `17`\n• *Consultations Handled by:* Noshin Samad: 7, Fahmid Kaisar: 5")


def test_the_facts_an_answer_states():
    assert voice.answer_facts(VERIFIED_12) == ["Total Students Verified: 10", "Total Verified Revenue: 152,000.00 BDT"]
    assert voice.answer_facts(INQUIRIES) == ["Total Inquiries on Portal: 999", "Inquiries Received: 21",
                                             "Inquiries Done: 17", "Consulted: 17"]
    assert voice.answer_facts("ℹ️ *No student payments were verified on 12 September 2026.*") == [
        "Students whose payment was verified: 0"]
    assert voice.answer_facts("⚡ *Reminders for today (11 items):*") == ["Reminders for today: 11"]
    assert voice.answer_facts("• Students in the MARCH 2027 intake: `177`") == ["Students in the MARCH 2027 intake: 177"]
    assert voice.answer_facts("❌ Couldn't read the portal: login failed.\nVerified: not available right now.") == []
    assert voice.answer_facts("📅 Please enter the *specific date* (e.g. `12 Sep 2026`)") == []


@pytest.mark.parametrize("said, day, problem", [
    ("Yay! 10 students were verified on 12 September!", date(2026, 9, 12), None),
    ("Yay! 10 students were verified today!", date(2026, 9, 12), "another day"),       # the wrong day
    ("No students verified today, hehe!", date(2026, 9, 12), "another day"),
    ("Yay! 152,000 taka was verified on 12 September!", date(2026, 9, 12), None),
    ("Yay! 152 students were verified on 12 September!", date(2026, 9, 12), "numbers not in the facts"),
    ("Yay! 152,000 students were verified on 12 September!", date(2026, 9, 12), "is not the figure"),
    ("Yay, I checked it for you!", date(2026, 9, 12), "no figure"),
    ("Yay! 10 students were verified and Lina checked them!", date(2026, 9, 12), "words the facts do not use"),
])
def test_jennie_says_only_the_figures_of_the_facts_for_their_own_day(said, day, problem):
    facts = voice.answer_facts(VERIFIED_12)
    got = voice._fact_problem(said, facts, "how many students were verified on 12 Sep", "en", day, TODAY)
    assert (got is None) if problem is None else (got is not None and problem in got), got


def test_consultations_bind_to_the_inquiry_figures():
    facts = voice.answer_facts(INQUIRIES)
    q = "how many consultations yesterday"
    yesterday = date(2026, 9, 27)
    assert voice._fact_problem("Yay! 21 consultations came in yesterday!", facts, q, "en", yesterday, TODAY) is None
    assert voice._fact_problem("Yay! 17 consultations were done yesterday!", facts, q, "en", yesterday, TODAY) is None
    assert voice._fact_problem("Yay! 999 consultations were done yesterday!", facts, q, "en", yesterday, TODAY)
    # The brain's Korean is never taken for an answer from the portal: it cannot be checked.
    assert voice._fact_problem("짜잔! 어제 상담 요청은 21건이에용!", facts, q, "ko", yesterday, TODAY)


def test_korean_answers_are_built_from_the_headline_fact():
    facts = voice.answer_facts(INQUIRIES)
    assert voice._korean_line(facts, date(2026, 9, 27), TODAY) == "짜잔! 어제 상담 요청은 21건이에용!"
    assert voice._korean_line(["Students whose payment was verified: 0"], date(2026, 9, 12), TODAY) == \
        "9월 12일 검증된 학생은 없어용!"
    assert voice._korean_line(["Deadlines: 5"], (TODAY, date(2026, 10, 4)), TODAY) == "짜잔! 이번 주 마감은 5건이에용!"
    assert voice._korean_line(["Pending payments: 2"], None, TODAY) == "짜잔! 지금 결제 대기 중인 학생은 2명이에용!"
    assert voice._korean_line(["Reminders for today: 11"], None, TODAY) == "짜잔! 오늘 일정은 11개예용!"
    assert voice._korean_line(["Students in the MARCH 2027 intake: 177"], None, TODAY) == \
        "짜잔! 2027년 3월 인테이크 학생은 177명이에용!"
    assert voice._korean_line(["Hanyang University (Top universities): 171"], None, TODAY) == ""


def test_a_korean_answer_with_no_korean_words_is_left_to_the_text(monkeypatch):
    async def brain(*args, **kwargs):
        raise AssertionError("the brain's Korean is never used for an answer from the portal")

    monkeypatch.setattr(ollama_client, "chat", brain)
    speech = asyncio.run(voice.spoken_reply("한양대 학생 몇 명?", "ko",
                                            "• Hanyang University (Top universities): `171`", [], day=None))
    assert speech == voice._FALLBACK[("ko", True)]


def test_no_example_day_or_figure_leaks_into_the_reply_rules():
    for system in (voice._REPLY_SYSTEM_EN, voice._REPLY_SYSTEM_KO):
        assert "no students today" not in system and "오늘 서류 검증된 학생은 2명" not in system
        assert "never another day" in system


def test_a_spoken_answer_is_for_the_day_it_was_asked(monkeypatch):
    said = iter(["No students verified today, hehe!", "Yay! 10 students were verified today!"])
    prompts = []

    async def brain(messages, format=None, num_predict=None, timeout=None):
        prompts.append(messages[-1]["content"])
        return next(said)

    monkeypatch.setattr(ollama_client, "chat", brain)
    monkeypatch.setattr(voice, "_now", lambda: __import__("datetime").datetime(2026, 9, 28, 10, 0))
    speech = asyncio.run(voice.spoken_reply("how many on the 12th of September", "en", VERIFIED_12, [],
                                            day=date(2026, 9, 12)))
    # Both of the brain's lines named "today" for 12 Sep: the headline fact is said instead.
    assert speech == "Okie! Total Students Verified on the twelfth of September: ten, hehe!"
    assert "The day: on 12 September" in prompts[0] and "- Total Students Verified: 10" in prompts[0]
    assert "SARKER" not in prompts[0] and "Payment:" not in prompts[0]           # only the facts, no rows


def test_voice_passport_questions_take_the_live_crosscheck(monkeypatch):
    ran = []

    async def recorder(update, context):
        ran.append(context.user_data.get("override_text"))
        await update.message.reply_text("ℹ️ *No payment-verified students found for 28 September 2026 to cross-check.*")

    async def static_passports(update, context):
        raise AssertionError("the hardcoded /passports text must not answer a voice question")

    monkeypatch.setattr(telegram_bot, "crosscheck_today_command", recorder)
    monkeypatch.setattr(telegram_bot, "passports_command", static_passports)
    from types import SimpleNamespace
    sent = []

    class Msg:
        async def reply_text(self, text, **kw):
            sent.append(text)
            return self

    update = SimpleNamespace(message=Msg(), effective_chat=SimpleNamespace(id=ADMIN_ID))
    context = SimpleNamespace(user_data={}, bot=SimpleNamespace())
    routed = {"command": "passports", "date": None, "english_query": "Which students have passport problems?"}
    assert asyncio.run(voice._dispatch(routed, update, context, "which students have passport problems")) == (
        "crosscheck_today", voice._now().date())
    assert voice.answer_facts(sent[0]) == ["Payment-verified students cross-checked: 0"]


def test_every_live_answer_fits_telegram(live, monkeypatch):
    many = "".join(row(1000 + n, n + 1, f"PENDING STUDENT NUMBER {n} WITH A LONG NAME", pay="Pending",
                       stage="Application Received", applied="28 Sep 2026") for n in range(50))
    live.pages["students.php?status=pending"] = page(many, pg=1, pages=1, total=50)
    live.pages.pop("students.php?status=pending&pg=2")
    text, _, chat = ask_bot("show pending payments")
    assert all(replies.telegram_len(m.text) <= replies.TELEGRAM_LIMIT for m in chat)
    assert "• Pending payments: `50`" in text and f"_...and {50 - ask.MAX_NAMES_LISTED} more._" in text
