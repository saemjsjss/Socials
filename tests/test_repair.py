"""The repairs the independent verifiers asked for (28 Sep 2026), each pinned where it was wrong:

  the date questions      a date that cannot be read, typed in answer to "which date?", asks again
                          (/verified_date, /inquiries_date, /crosscheck_date, /crosscheck_range)
  /admitted               the university is the cell's own .stu-uni line; its application lines
                          ("Applied: X · Program") are shown apart, and the breakdown is by university
  /verified, /report      a row's "Paid" and "Verified income" shown apart when they differ, and the
                          total said for what it adds up
  /crosscheck, /passports "checked by OCR just now" only for the scans OCR really read
  /calendar, /deadlines   "08 Oct · 14:00 – 23 Oct 2026" is a range; every timeline row is listed (or
                          "...and N more"); two portal events with one title stay two (by id, with their
                          programs); /deadlines <words> asks for deadlines only
  portal_sync             a Student ID given in the same sync as a name correction is one edit
  missing_info_report     a report that cannot be built says so in Telegram

Every portal page is synthetic, laid out like the live pages (Sep 2026). Nothing reaches the
network or Telegram.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_repair.py -q
"""
import asyncio
import json
import sys
from datetime import date
from types import SimpleNamespace

import pytest

from test_foundation import (  # noqa: F401  (the portal fixture is used by name)
    BACHELOR, KLP, TODAY, dashboard, page, portal, report_of, row, run, verified,
)
from src.bot import ask, brief, telegram_bot
from src.scraper import parsers
from src.scraper.client import PortalUnavailable
from src.sheets import auto_sync, missing_report
from src.sheets import progress_builder as pb


def say(text, user_data):
    """A typed message (no command) in a chat whose user_data is `user_data`."""
    chat, _ = run(telegram_bot.handle_natural_language_message, text, None, user_data)
    return report_of(chat)


# --------------------------------------------------------------------------- the date questions

def test_a_date_typed_after_an_unreadable_one_answers_the_verified_question(portal):
    portal.pages["students.php"] = page(verified(5, 1, "KHAN LUBNA", "12 Sep, 11:00", applied="1 Sep 2026"))
    ud = {}
    run(telegram_bot.verified_date_command, "/verified_date", [], ud)
    assert ud == {"awaiting_date_for": "verified"}
    text = say("31 Sep", ud)
    assert "I couldn't read “31 Sep” as a date (31 Sep: September has 30 days)" in text
    assert "Please send a date like `12 Sep 2026`" in text
    assert ud == {"awaiting_date_for": "verified"}                 # the question is still open
    text = say("12 Sep 2026", ud)
    assert "Student Payment Verifications — 12 September 2026" in text and "KHAN LUBNA" in text
    assert "I can't answer that from the portal yet" not in text and ud == {}
    # Words that are no date try do not keep the question open.
    ud = {"awaiting_date_for": "verified"}
    assert "as a date" in say("show me the pending payments", ud) and ud == {}


def test_the_inquiries_crosscheck_and_range_questions_are_asked_again(portal, monkeypatch):
    reports, checks = [], []

    async def inquiries_report(update, raw_input, waiting, strict):
        reports.append(raw_input)
        await update.message.reply_text("inquiries report")

    async def crosscheck_run(update, query, waiting, title):
        checks.append((query["kind"], query.get("first"), query.get("last")))
        await update.message.reply_text("cross-check report")

    monkeypatch.setattr(telegram_bot, "_send_inquiries_report", inquiries_report)
    monkeypatch.setattr(telegram_bot, "_crosscheck_run", crosscheck_run)

    ud = {}
    run(telegram_bot.inquiries_date_command, "/inquiries_date", [], ud)
    assert "September has 30 days" in say("31 Sep", ud) and ud == {"awaiting_date_for": "inquiries"}
    say("12 Sep 2026", ud)
    assert reports == ["12 Sep 2026"] and ud == {}

    run(telegram_bot.crosscheck_date_command, "/crosscheck_date", [], ud)
    assert "September has 30 days" in say("31 Sep", ud) and ud == {"awaiting_date_for": "crosscheck"}
    say("12 Sep 2026", ud)
    assert checks == [("date", date(2026, 9, 12), date(2026, 9, 12))] and ud == {}

    run(telegram_bot.crosscheck_range_command, "/crosscheck_range", [], ud)
    assert "couldn't read two dates" in say("1 Sep to 31 Sep", ud) and ud == {"awaiting_date_for": "crosscheck_range"}
    say("1 Sep 2026 to 15 Sep 2026", ud)
    assert checks[-1] == ("date", date(2026, 9, 1), date(2026, 9, 15)) and ud == {}


def test_a_free_text_question_with_a_bad_date_does_not_open_a_date_question(portal):
    ud = {}
    assert "September has 30 days" in say("how many students were verified on 31 Sep", ud)
    assert ud == {}                             # no question was asked, so none is left open


# --------------------------------------------------------------------------- /admitted

def uni_cell(university, *applications):
    lines = "".join(f'<div class="upr"><span class="badge uni-pill" title="University application status">'
                    f'<i class="fas fa-paper-plane"></i> {a}</span></div>' for a in applications)
    return f'<div class="stu-uni">{university}</div>{lines}'


def test_the_university_is_the_cells_own_line_and_applications_are_apart(portal):
    admitted = "Admitted / Completed"
    portal.pages.update({
        "index.php": dashboard(3),
        "students.php": page(
            row(1, 1, "KHAN LUBNA", hng="HNG-2026-905", program=BACHELOR, stage=admitted,
                uni=uni_cell("KYUNGSUNG UNIVERSITY", "Applied: Kyungsung University · Bachelor's Degree")),
            row(2, 2, "HAMID TOUFIQ", hng="HNG-2026-906", program=BACHELOR, stage=admitted,
                uni=uni_cell("Kyungsung University")),
            row(3, 3, "KHALED ROMEL", hng="HNG-2026-907", program=BACHELOR, stage=admitted,
                uni=uni_cell("HANYANG UNIVERSITY", "Applied: Hanyang University · Bachelor's Degree",
                             "Pending: Kyungsung University · Bachelor's Degree")),
            row(4, 4, "ARIF JAMAL", hng="HNG-2026-908", uni=uni_cell("—"))),
    })
    students = parsers.parse_students_page(portal.pages["students.php"])["students"]
    assert [s["target_university"] for s in students] == [
        "KYUNGSUNG UNIVERSITY", "Kyungsung University", "HANYANG UNIVERSITY", ""]
    assert students[2]["applications"] == ["Applied: Hanyang University · Bachelor's Degree",
                                           "Pending: Kyungsung University · Bachelor's Degree"]
    assert students[1]["applications"] == [] and students[3]["applications"] == []

    text = report_of(run(telegram_bot.admitted_command, "/admitted", [])[0])
    assert "• *Universities:* KYUNGSUNG UNIVERSITY (2), HANYANG UNIVERSITY (1)" in text   # one university, one entry
    assert "🏛 *Univ:* KYUNGSUNG UNIVERSITY | *Prog:*" in text
    assert "📝 *Applications:* Applied: Kyungsung University · Bachelor's Degree" in text
    assert ("📝 *Applications:* Applied: Hanyang University · Bachelor's Degree; "
            "Pending: Kyungsung University · Bachelor's Degree") in text
    assert "Univ:* KYUNGSUNG UNIVERSITY Applied" not in text
    # The search still covers the application lines.
    text = report_of(run(telegram_bot.admitted_command, "/admitted Kyungsung", ["Kyungsung"])[0])
    assert "• *Matching* “Kyungsung”: `3`" in text


# --------------------------------------------------------------------------- paid and verified income

def test_paid_and_verified_income_are_shown_apart_when_they_differ(portal):
    portal.pages["students.php"] = page(
        row(7, 1, "MONDAL KASHEM", hng="HNG-2026-901", by="MAHIRA JANAN", when="12 Sep, 18:03", applied="1 Sep 2026",
            paid="8,160.00 BDT", method="bKash", income="8,000.00 BDT"),
        verified(8, 2, "KHAN LUBNA", "12 Sep, 11:00", amount="20,000.00 BDT", method="Cash", applied="1 Sep 2026"))
    text = report_of(run(telegram_bot.verified_date_command, "/verified_date 12 Sep 2026", ["12", "Sep", "2026"])[0])
    assert "*Payment:* `Paid 8,160.00 BDT bKash (verified income 8,000.00 BDT)`" in text
    assert "*Payment:* `20,000.00 BDT Cash`" in text                # the same figure twice: once
    assert "*Total Verified Revenue:* `৳ 28,000.00 BDT` (the sum of the verified income)" in text
    assert "8,000.00 BDT bKash`" not in text                        # never income beside the paid method

    got = parsers.verified_on_day(parsers.parse_students_page(portal.pages["students.php"])["students"],
                                  date(2026, 9, 12))
    assert (got[0]["paid"], got[0]["verified_income"], got[0]["amount"]) == ("8,160.00 BDT", "8,000.00 BDT",
                                                                              "8,000.00 BDT")
    lines = "\n".join(brief.section_verified(got, "12 Sep 2026", False)[0])
    assert "MONDAL KASHEM — KOREAN LANGUAGE PROGRAM (KLP) — Paid 8,160.00 BDT bKash (verified income 8,000.00 BDT)" in lines
    assert "Total: 28,000.00 BDT" in lines


def test_a_total_over_paid_amounts_only_says_so(portal):
    portal.pages["students.php"] = page(
        row(7, 1, "OLDER ROW", hng="HNG-2026-911", by="MAHIRA JANAN", when="12 Sep, 18:03", applied="1 Sep 2026",
            paid="8,000.00 BDT", method="bKash"))
    text = report_of(run(telegram_bot.verified_date_command, "/verified_date 12 Sep 2026", ["12", "Sep", "2026"])[0])
    assert "`৳ 8,000.00 BDT` (the sum of the amounts paid)" in text and "*Payment:* `8,000.00 BDT bKash`" in text


# --------------------------------------------------------------------------- the OCR claim

def card(status, verdict="✅ 100% Match across All Fields"):
    return {"id": "527", "hng": "HNG-2026-959", "name": "KHAN LUBNA", "program": KLP, "dob": "", "pass_no": "",
            "pass_exp": "", "passport_status": "", "passport_file": "passport_527_1.jpg", "has_pass_doc": True,
            "has_rcpt_doc": True, "payment": "", "verifier": "", "ver_time": "", "fields": {},
            "status": status, "verdict": verdict}


def test_checked_by_ocr_is_said_only_of_the_scans_ocr_read():
    unread = card("PORTAL_UNREADABLE", "❌ Couldn't read the portal: the student's profile could not be read. "
                                        "The passport was not checked.")
    text = telegram_bot._format_crosscheck_results([unread], "Student ID #527", checked=330)
    assert "checked by OCR just now" not in text
    assert "Read live from all 330 students on students.php; no scan could be checked by OCR (see the card)." in text
    text = telegram_bot._format_crosscheck_results([card("MATCH"), unread, card("OCR_UNAVAILABLE", "OCR down")],
                                                   "27 September 2026", checked=330)
    assert "1 of the 3 scans were checked by OCR just now, 2 could not be checked (see their cards)" in text
    text = telegram_bot._format_crosscheck_results([card("MATCH"), card("MISMATCH", "⚠️ Discrepancy")],
                                                   "27 September 2026", checked=330)
    assert "each scan was checked by OCR just now" in text

    students = [{"files": ["passport_527_1.jpg"], "details": {}}]
    text = telegram_bot.format_passports_report(students, [unread], "28 September 2026", "28 Sep 2026, 10:00")
    assert "OCR check" not in text
    text = telegram_bot.format_passports_report(students, [card("MATCH"), unread], "28 September 2026",
                                                "28 Sep 2026, 10:00")
    assert "1 of the 2 verdicts come from an OCR check of the scan made just now" in text
    text = telegram_bot.format_passports_report(students, [card("MATCH")], "28 September 2026", "28 Sep 2026, 10:00")
    assert "each verdict comes from an OCR check of the scan made just now" in text


# --------------------------------------------------------------------------- the calendar

# The live calendar.php of 28 Sep 2026: its month's event list (var EV), today's 11 reminders and
# the 15 rows of the 45-day timeline, laid out as the page lays them out (forms and tokens left out).
EV = [
    (10, "KYUNGDONG UNIVERSITY- APPLICATION START", "period", None, "2026-08-25", "2026-09-04", 0, "EAP PROGRAM"),
    (3, "HANYANG UNIVERSITY - APPLICATION OPEN", "period", "HANYANG UNIVERSITY", "2026-09-01", "2026-09-18", 0,
     "BACHELOR PROGRAM"),
    (6, "FAR EAST UNIVERSITY- APPLICATION OPEN", "period", "FAR EAST UNIVERSITY", "2026-09-01", "2026-10-09", 0,
     "EAP PROGRAM"),
    (7, "MOKWON UNIVERSITY- APPLICATION OPEN", "period", "MOKWON UNIVERSITY", "2026-09-01", "2026-10-10", 0, "EAP PROGRAM"),
    (9, "THE UNIVERSITY OF SUWON- APPLICATION OPEN", "period", "THE UNIVERSITY OF SUWON", "2026-09-01", "2026-10-30", 0,
     "EAP PROGRAM"),
    (12, "HANYANG UNIVERSITY ERICA - APPLICATION OPEN", "period", "HANYANG UNIVERSITY ERICA", "2026-09-01",
     "2026-10-16", 0, ""),
    (4, "SEJONG UNIVERSITY - APPLICATION OPEN", "period", "SEJONG UNIVERSITY", "2026-09-07", "2026-09-21", 0,
     "MASTER'S PROGRAM"),
    (8, "SEJONG UNIVERSITY - APPLICATION OPEN", "period", "SEJONG UNIVERSITY", "2026-09-07", "2026-09-21", 0,
     "BACHELOR PROGRAM"),
    (2, "KYUNGSUNG UNIVERSITY - APPLICATION OPEN", "period", "KYUNGSUNG UNIVERSITY", "2026-09-11", "2026-09-21", 0,
     "BACHELOR PROGRAM"),
    (11, "KYUNGSUNG UNIVERSITY - APPLICATION OPEN", "period", "KYUNGSUNG UNIVERSITY", "2026-09-11", "2026-09-21", 0,
     "MASTER'S"),
    (13, "HANYANG BACHELOR", "dhl", "Hanyang University", "2026-09-20", "2026-09-22", 1, ""),
    (23, "Jeonbuk National University - Application open", "period", "Jeonbuk National University", "2026-09-21",
     "2026-10-02", 0, "The documents must be sent via DHL within the application period."),
    (24, "Seoul National University of Science & Technology -Application open", "period",
     "Seoul National University of Science and Technology", "2026-09-21", "2026-10-02", 0,
     "The documents must be sent via DHL within the application period."),
    (19, "SEJONG DHL", "dhl", "Sejong University", "2026-09-26", "2026-09-28", 0, ""),
    (20, "SEOUL TECH DHL", "dhl", "Seoul National University of Science and Technology", "2026-09-26", "2026-09-28", 0, ""),
    (21, "JEONBUK NATIONAL UNIVERSITY DHL", "dhl", "Jeonbuk National University", "2026-09-26", "2026-10-05", 0, ""),
    (22, "KOREA UNIVERSITY DHL", "dhl", "Korea University", "2026-09-26", "2026-09-28", 0, ""),
    (16, "KYUNGSUNG UNIVERSITY", "period", "2ND ROUND APPLICATION", "2026-09-28", "2026-10-12", 0, ""),
]
DHL, PERIOD = "DHL to send", "Application period"
SEOUL_TECH = "Seoul National University of Science and Technology"
REMINDERS = [   # (id, title, type, "range · time · where", progress, note)
    (19, "SEJONG DHL", DHL, "26 Sep–28 Sep · 14:00 · Sejong University", "", ""),
    (20, "SEOUL TECH DHL", DHL, f"26 Sep–28 Sep · 14:00 · {SEOUL_TECH}", "", ""),
    (21, "JEONBUK NATIONAL UNIVERSITY DHL", DHL, "26 Sep–05 Oct · 14:00 · Jeonbuk National University", "", ""),
    (22, "KOREA UNIVERSITY DHL", DHL, "26 Sep–28 Sep · 14:00 · Korea University", "", ""),
    (23, "Jeonbuk National University - Application open", PERIOD, "21 Sep–02 Oct · 14:00 · Jeonbuk National University",
     "64% of window elapsed · 4 days left", "The documents must be sent via DHL within the application period."),
    (24, "Seoul National University of Science &amp; Technology -Application open", PERIOD,
     f"21 Sep–02 Oct · 14:00 · {SEOUL_TECH}", "64% of window elapsed · 4 days left",
     "The documents must be sent via DHL within the application period."),
    (6, "FAR EAST UNIVERSITY- APPLICATION OPEN", PERIOD, "01 Sep–09 Oct · FAR EAST UNIVERSITY",
     "71% of window elapsed · 11 days left", "EAP PROGRAM"),
    (7, "MOKWON UNIVERSITY- APPLICATION OPEN", PERIOD, "01 Sep–10 Oct · MOKWON UNIVERSITY",
     "69% of window elapsed · 12 days left", "EAP PROGRAM"),
    (16, "KYUNGSUNG UNIVERSITY", PERIOD, "28 Sep–12 Oct · 12:49 · 2ND ROUND APPLICATION",
     "0% of window elapsed · 14 days left", ""),
    (12, "HANYANG UNIVERSITY ERICA - APPLICATION OPEN", PERIOD, "01 Sep–16 Oct · HANYANG UNIVERSITY ERICA",
     "60% of window elapsed · 18 days left", ""),
    (9, "THE UNIVERSITY OF SUWON- APPLICATION OPEN", PERIOD, "01 Sep–30 Oct · THE UNIVERSITY OF SUWON",
     "46% of window elapsed · 32 days left", "EAP PROGRAM"),
]
TIMELINE = [    # (id, day, month, title, type, "dates · where" as the ev-sub writes them, note, status)
    (6, 1, "Sep", "FAR EAST UNIVERSITY- APPLICATION OPEN", PERIOD, "01 Sep – 09 Oct 2026 · FAR EAST UNIVERSITY",
     "EAP PROGRAM", "Closes in 11 days"),
    (7, 1, "Sep", "MOKWON UNIVERSITY- APPLICATION OPEN", PERIOD, "01 Sep – 10 Oct 2026 · MOKWON UNIVERSITY",
     "EAP PROGRAM", "Closes in 12 days"),
    (9, 1, "Sep", "THE UNIVERSITY OF SUWON- APPLICATION OPEN", PERIOD,
     "01 Sep – 30 Oct 2026 · THE UNIVERSITY OF SUWON", "EAP PROGRAM", "Closes in 32 days"),
    (12, 1, "Sep", "HANYANG UNIVERSITY ERICA - APPLICATION OPEN", PERIOD,
     "01 Sep – 16 Oct 2026 · HANYANG UNIVERSITY ERICA", "", "Closes in 18 days"),
    (23, 21, "Sep", "Jeonbuk National University - Application open", PERIOD,
     "21 Sep · <b>14:00</b> – 02 Oct 2026 · Jeonbuk National University",
     "The documents must be sent via DHL within the application period.", "Closes in 4 days"),
    (24, 21, "Sep", "Seoul National University of Science &amp; Technology -Application open", PERIOD,
     f"21 Sep · <b>14:00</b> – 02 Oct 2026 · {SEOUL_TECH}",
     "The documents must be sent via DHL within the application period.", "Closes in 4 days"),
    (19, 26, "Sep", "SEJONG DHL", DHL, "26 Sep · <b>14:00</b> – 28 Sep 2026 · Sejong University", "", "Today"),
    (20, 26, "Sep", "SEOUL TECH DHL", DHL, f"26 Sep · <b>14:00</b> – 28 Sep 2026 · {SEOUL_TECH}", "", "Today"),
    (21, 26, "Sep", "JEONBUK NATIONAL UNIVERSITY DHL", DHL,
     "26 Sep · <b>14:00</b> – 05 Oct 2026 · Jeonbuk National University", "", "In 7 days"),
    (22, 26, "Sep", "KOREA UNIVERSITY DHL", DHL, "26 Sep · <b>14:00</b> – 28 Sep 2026 · Korea University", "", "Today"),
    (16, 28, "Sep", "KYUNGSUNG UNIVERSITY", PERIOD, "28 Sep · <b>12:49</b> – 12 Oct 2026 · 2ND ROUND APPLICATION", "",
     "Closes in 14 days"),
    (5, 7, "Oct", "GACHON UNIVERSITY - APPLICATION OPEN", PERIOD, "07 Oct – 14 Oct 2026 · GACHON UNIVERSITY",
     "MASTER'S PROGRAM", "Opens in 9 days"),
    (1, 8, "Oct", "DANKOOK UNIVERSITY- APLLICATION OPEN", PERIOD,
     "08 Oct · <b>14:00</b> – 23 Oct 2026 · DANKOOK UNIVERSITY", "BACHELOR PROGRAM", "Opens in 10 days"),
    (17, 10, "Oct", "EULJI UNIVERSITY APPLICATION", PERIOD, "10 Oct – 20 Oct 2026 · EULJI UNIVERSITY", "",
     "Opens in 12 days"),
    (18, 15, "Oct", "SOODO INTERNATIONAL UNIVERSITY APPLICATION", PERIOD,
     "15 Oct – 20 Oct 2026 · SOODO INTERNATIONAL UNIVERSITY", "", "Opens in 17 days"),
]


def rm_item(eid, title, kind, sub, progress, note):
    bar = (f'<div style="margin-top:6px"><div style="font-size:10.5px;color:#64748b">{progress}</div></div>'
           if progress else "")
    note = f'<div style="font-size:11.5px;color:#475569;margin-top:2px">{note}</div>' if note else ""
    parts = " · ".join(p.strip() for p in sub.split("·"))
    return ('<div class="rm-item"><span><i class="fas fa-truck-fast"></i></span><div style="flex:1;min-width:0">'
            f'<a class="rm-title" href="calendar.php?ym=2026-09&amp;view=month&amp;edit={eid}">{title}</a>'
            f'<div style="font-size:11.5px;color:#64748b;margin-top:2px"><span style="font-weight:700">{kind}</span>'
            f"\n              · {parts}               </div>{bar}{note}</div>"
            f'<form method="post"><input name="id" type="hidden" value="{eid}"/><button class="rm-done">Done</button>'
            "</form></div>")


def ev_row(eid, day, month, title, kind, sub, note, status):
    note = f'<div style="font-size:11.5px;color:#475569;margin-top:2px">{note}</div>' if note else ""
    return (f'<div class="ev-row"><div class="li-date" style="width:40px"><div class="d">{day}</div>'
            f'<div class="w">{month}</div></div><span class="ev-ic"><i class="fas fa-calendar-days"></i></span>'
            f'<div class="ev-main"><a class="ev-title" href="calendar.php?ym=2026-09&amp;view=month&amp;edit={eid}" '
            f'title="{title}">{title}</a><div class="ev-sub"><span style="font-weight:700">{kind}</span> · {sub}</div>'
            f'{note} </div><span class="st soon">{status}</span><div class="acts">'
            f'<a class="ib" href="calendar.php?ym=2026-09&amp;view=month&amp;edit={eid}" title="Edit"></a></div></div>')


def live_calendar(timeline=TIMELINE):
    ev = [{"id": i, "title": t, "type": k, "uni": u, "start": s, "end": e, "done": d, "notes": n}
          for i, t, k, u, s, e, d, n in EV]
    reminders = "".join(rm_item(*r) for r in REMINDERS)
    upcoming = "".join(ev_row(*u) for u in timeline)
    return ('<div class="cal-layout">'
            '<div class="cal-card"><div class="sec-h"><i></i>Reminders for today<small>· Monday, 28 Sep 2026 · '
            f'{len(REMINDERS)} items</small></div>{reminders}</div>'
            '<div class="cal-card"><div class="sec-h">Upcoming <small>· next 45 days</small></div>'
            f"<div>{upcoming}</div></div></div><script>var EV = {json.dumps(ev)};\nvar CAL_Y = 2026;</script>")


@pytest.fixture
def calendar(portal):
    portal.pages["calendar.php"] = live_calendar()
    return portal


def test_a_timeline_time_is_followed_by_the_end_date():
    cal = parsers.parse_calendar_events(live_calendar())
    by = {u["title"]: u for u in cal["upcoming_events"]}
    dankook, jeonbuk = by["DANKOOK UNIVERSITY- APLLICATION OPEN"], by["Jeonbuk National University - Application open"]
    assert (dankook["id"], dankook["date_range"], dankook["university"]) == ("1", "08 Oct – 23 Oct 2026",
                                                                            "DANKOOK UNIVERSITY")
    assert (jeonbuk["date_range"], jeonbuk["university"]) == ("21 Sep – 02 Oct 2026", "Jeonbuk National University")
    assert parsers._cal_sub(None)["date_range"] == ""
    items, ok = ask.calendar_items(live_calendar(), TODAY)
    item = next(i for i in items if i.title.startswith("DANKOOK"))
    assert ok and (item.start, item.end, item.id) == (date(2026, 10, 8), date(2026, 10, 23), "1")


def test_todays_view_lists_the_whole_timeline(calendar):
    text = report_of(run(telegram_bot.calendar_command, "/calendar", [])[0])
    assert "Reminders for today (11 items)" in text
    assert "📌 *Upcoming (15 on the 45-day timeline):*" in text
    for title in ("GACHON UNIVERSITY - APPLICATION OPEN", "DANKOOK UNIVERSITY- APLLICATION OPEN",
                  "EULJI UNIVERSITY APPLICATION", "SOODO INTERNATIONAL UNIVERSITY APPLICATION", "KOREA UNIVERSITY DHL"):
        assert title in text
    assert "(`21 Sep – 02 Oct 2026`) — Closes in 4 days" in text and "(`21 Sep`)" not in text
    assert "(`08 Oct – 23 Oct 2026`) — Opens in 10 days" in text
    assert "more (search one" not in text
    # A longer timeline is cut at CALENDAR_UPCOMING_MAX, and says how many more there are.
    many = TIMELINE + [(100 + n, 20, "Oct", f"EXTRA UNIVERSITY {n}", PERIOD, "20 Oct – 25 Oct 2026 · X", "", "Opens")
                       for n in range(10)]
    text = telegram_bot.format_calendar_report(parsers.parse_calendar_events(live_calendar(many)))
    assert "📌 *Upcoming (25 on the 45-day timeline):*" in text and "_…and 5 more" in text
    assert "EXTRA UNIVERSITY 4" in text and "EXTRA UNIVERSITY 5" not in text


def calendar_reply(text, args):
    return report_of(run(telegram_bot.calendar_command, text, args)[0])


def test_two_events_with_one_title_stay_two_with_their_programs(calendar):
    text = calendar_reply("/calendar 11 Sep", ["11", "Sep"])
    assert "• Calendar items: `9`" in text
    assert text.count("*SEJONG UNIVERSITY - APPLICATION OPEN*") == 2
    assert "*SEJONG UNIVERSITY - APPLICATION OPEN* (MASTER'S PROGRAM)" in text
    assert "*SEJONG UNIVERSITY - APPLICATION OPEN* (BACHELOR PROGRAM)" in text
    assert "*KYUNGSUNG UNIVERSITY - APPLICATION OPEN* (MASTER'S)" in text
    assert "*KYUNGSUNG UNIVERSITY - APPLICATION OPEN* (BACHELOR PROGRAM)" in text
    # An event open on the day asked, whose end only the timeline gives (after its time).
    text = calendar_reply("/calendar 20 Oct", ["20", "Oct"])
    assert "• Calendar items: `4`" in text and "DANKOOK UNIVERSITY- APLLICATION OPEN" in text


@pytest.mark.parametrize("args, count, titles", [
    (["today"], 3, ["SEJONG DHL", "SEOUL TECH DHL", "KOREA UNIVERSITY DHL"]),
    (["next", "week"], 3, ["JEONBUK NATIONAL UNIVERSITY DHL", "FAR EAST UNIVERSITY", "MOKWON UNIVERSITY"]),
    (["21", "Sep"], 4, ["SEJONG UNIVERSITY - APPLICATION OPEN", "KYUNGSUNG UNIVERSITY - APPLICATION OPEN"]),
    (["Sejong"], 3, ["SEJONG UNIVERSITY - APPLICATION OPEN", "SEJONG DHL"]),
])
def test_deadlines_with_words_are_deadlines_only(calendar, args, count, titles):
    text = calendar_reply("/deadlines " + " ".join(args), args)
    assert text.startswith("📅 *Deadlines") and f": `{count}`" in text.splitlines()[1]
    for title in titles:
        assert title in text
    assert "HANYANG UNIVERSITY ERICA" not in text and "Calendar items" not in text


def test_the_deadlines_counts_say_where_they_stand(calendar):
    text = calendar_reply("/deadlines today", ["today"])
    assert "• Deadlines still open: `3`" in text
    text = calendar_reply("/deadlines 21 Sep", ["21", "Sep"])
    assert "• Deadlines already passed: `4`" in text
    text = calendar_reply("/calendar DHL", ["DHL"])
    assert "• DHL shipments still to send: `4`" in text
    from src.bot import voice
    assert "DHL shipments still to send: 4" in voice.answer_facts(text)
    # Bare /deadlines is today's view, as /calendar and /events are.
    assert "Reminders for today (11 items)" in calendar_reply("/deadlines", [])


# --------------------------------------------------------------------------- the portal sync

def rec(sid="", name="HASAN MD", mobile="8801711111111", passport="PENDING", dob="2004-05-06"):
    return {"Student ID": sid, "Full Name": name, "Mobile": mobile, "Passport No": passport, "DOB": dob}


def snap(*recs):
    out = {}
    for r in recs:
        out[auto_sync._row_key(r)] = {"name": r["Full Name"], "hash": auto_sync._digest(r), "rec": r}
    return out


def test_an_id_given_with_a_name_correction_is_one_edit_not_a_join_and_a_leave():
    before = snap(rec(), rec("HNG-2026-905", "HAMID TOUFIQ", "8801722222222", "B07654321"))
    after = snap(rec("HNG-2026-961", "HASAN MD RAIYAN"), rec("HNG-2026-905", "HAMID TOUFIQ", "8801722222222", "B07654321"))
    assert auto_sync.sheet_changes(before, after) == ([], [], ["HASAN MD RAIYAN (Student ID, Full Name)"])
    # ... or with the mobile corrected: the same name and date of birth.
    after = snap(rec("HNG-2026-961", mobile="8801799999999"))
    assert auto_sync.sheet_changes(snap(rec()), after) == ([], [], ["HASAN MD (Student ID, Mobile)"])
    # Different students who share a phone (and "MD"), or share nothing, stay a join and a leave.
    after = snap(rec("HNG-2026-962", "KHALED MD ROMEL"))
    assert auto_sync.sheet_changes(snap(rec()), after) == (["KHALED MD ROMEL"], ["HASAN MD"], [])
    after = snap(rec("HNG-2026-963", "HASAN MD", "8801733333333", dob="2001-01-01"))
    assert auto_sync.sheet_changes(snap(rec()), after) == (["HASAN MD"], ["HASAN MD"], [])


# --------------------------------------------------------------------------- the 09:05 report

@pytest.fixture
def telegram(monkeypatch):
    sent = []
    monkeypatch.setattr(missing_report, "send", lambda lines, xlsx: sent.append((list(lines), xlsx)))
    return sent


@pytest.mark.parametrize("broken, reason", [
    ("sheets", "RuntimeError: Google login required"),
    ("portal", "students.php?export=csv: the portal did not answer in time (ReadTimeout)"),
])
def test_a_daily_missing_report_that_cannot_be_built_says_so(monkeypatch, telegram, capsys, broken, reason):
    def no_sheets():
        raise RuntimeError("Google login required")

    def no_portal():
        raise PortalUnavailable("students.php?export=csv: the portal did not answer in time (ReadTimeout)",
                                unreachable=True)

    if broken == "sheets":
        monkeypatch.setattr(missing_report, "read_sheets", no_sheets)
    else:
        monkeypatch.setattr(missing_report, "read_sheets", lambda: {"KLP|MARCH 2027": [{"Student ID": "HNG-2026-905"}]})
        monkeypatch.setattr(pb, "direct_students", no_portal)
    monkeypatch.setattr(sys, "argv", ["missing_report"])
    with pytest.raises(SystemExit) as exit_:
        missing_report.main()
    assert exit_.value.code == 1
    notice = (f"❌ Couldn't build today's missing-information report: {reason}. It will run again tomorrow "
              "at 09:05 (or send /missing).")
    assert telegram == [([notice], None)] and capsys.readouterr().out.strip() == notice


def test_the_failure_notice_goes_as_one_plain_message(monkeypatch):
    posts = []

    class Http:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, data=None, files=None):
            posts.append((url.rsplit("/", 1)[-1], data, files))
            return SimpleNamespace(status_code=200, text="")

    import httpx
    from src.config import settings
    monkeypatch.setattr(httpx, "Client", Http)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123:test")
    monkeypatch.setattr(settings, "TELEGRAM_BRIEF_CHAT_IDS", "111111111")
    missing_report.send(["❌ Couldn't build today's missing-information report: x."], None)
    assert [(name, data["text"]) for name, data, _ in posts] == [
        ("sendMessage", "❌ Couldn't build today's missing-information report: x.")]
