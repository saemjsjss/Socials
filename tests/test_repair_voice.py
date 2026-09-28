"""Jennie's repairs (28 Sep 2026, src/bot/voice.py): a date spoken that does not exist ("31
September", "the 45th", "February 30", 9월 31일) gets the command's own "I couldn't read that date",
never the figures of a day the brain made of it (nor today's); and a portal read that failed is
said as such in a sentence built in code, never worded by the brain as "no pending payments".

Everything is offline: the fakes and fixtures come from tests/test_voice.py and test_voice_fast.py.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_repair_voice.py -q
"""
import asyncio
from datetime import date

import pytest

from test_voice import ADMIN_ID, FakeVoice, llm, offline, service, voice_update  # noqa: F401  (fixtures)
from test_voice_fast import commands, route  # noqa: F401  (the commands fixture is used by name)
from src.bot import voice
from src.bot.replies import portal_error_reply
from src.scraper.client import PortalUnavailable

TODAY = date(2026, 9, 28)


@pytest.mark.parametrize("heard, routed, problem", [
    ("how many consultations on 31 September?", route("inquiries_date", "2026-09-30",
                                                      "How many consultations on September 30?"),
     "31 September: September has 30 days"),
    ("9월 31일 상담 몇 건이었어?", route("inquiries_date", "2026-09-30", "How many consultations on September 30?", "ko"),
     "9월 31일: September has 30 days"),
    ("구월 삼십일일 상담 몇 건이었어?", route("inquiries_date", "2026-09-30", "How many consultations on September 30?",
                                     "ko"), "구월 삼십일일: September has 30 days"),
    ("how many consultations on the 45th?", route("inquiries_date", "2026-09-23", "How many consultations on the 45th?"),
     "45th: no month has a day 45"),
    ("verified students on February 30", route("verified_date", "2026-09-23", "Verified students on February 30"),
     "February 30: February has 29 days"),
    ("verified students on February 30", route("verified_today", None, "How many students were verified today?"),
     "February 30: February has 29 days"),
    ("45일 상담 몇 건?", route("inquiries_date", "2026-09-15", "How many consultations on the 45th?", "ko"),
     "45일: no month has a day 45"),
])
def test_a_date_that_does_not_exist_is_never_replaced_by_another_day(llm, heard, routed, problem):
    llm.routes[heard] = routed
    got = asyncio.run(voice.route(heard))
    assert got["date"] is None and got["date_problem"] == problem


def test_the_date_error_is_the_answer_and_nothing_is_read(llm, commands):
    for heard, routed, shown in (
            ("how many consultations on 31 September?", route("inquiries_date", "2026-09-30"), "/inquiries_date"),
            ("how many consultations on the 45th?", route("inquiries_date", "2026-09-23"), "/inquiries_date"),
            ("verified students on February 30", route("verified_today"), "/verified_date"),
            ("cross-check the 45th", route("crosscheck", "2026-09-23"), "/crosscheck_date")):
        llm.routes[heard] = routed
        update, context, chat = voice_update(voice=FakeVoice())
        got = asyncio.run(voice.route(heard))
        ran = asyncio.run(voice._dispatch(got, update, context, heard))
        assert commands == [], heard                              # no command ran: no portal read
        assert ran[1] is None and ran[0].endswith(":date_error")
        text = chat.visible()[-1]
        assert text.startswith("⚠️ I couldn't read") and f"`{shown} 12 Sep 2026`" in text, text
        assert "23 Sep" not in text and "30 Sep" not in text


def test_a_bad_date_answering_the_bots_question_keeps_it_open(llm, commands):
    update, context, chat = voice_update(voice=FakeVoice())
    context.user_data["awaiting_date_for"] = "verified"
    llm.routes["31 September"] = route("verified_date", "2026-09-30", "31 September")
    ran = asyncio.run(voice._dispatch(asyncio.run(voice.route("31 September")), update, context, "31 September"))
    assert ran == ("verified:date_error", None) and commands == []
    assert context.user_data["awaiting_date_for"] == "verified"
    assert "September has 30 days" in chat.visible()[-1]


@pytest.mark.parametrize("heard, routed, day", [
    ("verified students on 12 September", route("verified_date", "2026-09-12", "Verified students on 12 September"),
     date(2026, 9, 12)),
    ("consultations on the 25th", route("inquiries_date", "2026-09-25", "Consultations on the 25th"), date(2026, 9, 25)),
    ("구월 이십오일 상담은?", route("inquiries_date", "2026-09-25", "Consultations on September 25?", "ko"),
     date(2026, 9, 25)),
    ("이십오일 상담은?", route("inquiries_date", "2026-09-25", "How many consultations?", "ko"), date(2026, 9, 25)),
    ("31일 상담 몇 건?", route("inquiries_date", "2026-08-31", "How many consultations?", "ko"), date(2026, 8, 31)),
    ("consultations two days ago", route("inquiries_date", "2026-09-26", "Consultations two days ago"),
     date(2026, 9, 26)),                                          # relative words: the brain's reading
    # The words name a date, the brain another: the words' own.
    ("verified students on 12 September", route("verified_date", "2026-09-13", "Verified students on 12 September"),
     date(2026, 9, 12)),
])
def test_a_real_date_is_kept(llm, heard, routed, day):
    llm.routes[heard] = routed
    got = asyncio.run(voice.route(heard))
    assert got["date"] == day and got["date_problem"] is None


def test_a_failed_read_is_said_in_words_built_here(llm):
    answer = portal_error_reply("Pending payments", PortalUnavailable(
        "students.php?status=pending: the portal did not answer in time (ReadTimeout)", unreachable=True))
    llm.reply_en = "Hehe, no pending payments right now! Try again in a minute, okay?"
    said = asyncio.run(voice.spoken_reply("show me the pending payments", "en", answer))
    assert said == "Sorry, I couldn't read the portal just now, so I can't say. Please try again in a minute."
    assert "reply" not in llm.kinds()                               # the brain was not asked to word it
    said = asyncio.run(voice.spoken_reply("결제 대기 보여줘", "ko", answer))
    assert said == "지금은 포털을 못 읽었어요. 잠시 후 다시 물어봐 주세용!"
    calendar = ("📅 *Hangeul Admin Calendar & Deadlines*\n\nℹ️ Today's reminders are not available right now "
                "(the calendar page could not be read).")
    assert asyncio.run(voice.spoken_reply("deadlines", "en", calendar)).startswith("Sorry, I couldn't read the portal")


@pytest.mark.parametrize("said", ["No pending payments right now!", "There are no verified students today.",
                                  "Zero payments are waiting.", "There aren't any pending payments."])
def test_saying_there_is_nothing_is_a_figure(said):
    assert voice._SAID_NOTHING_RE.search(said)


def test_the_dhl_fact_carries_its_status_into_what_jennie_says():
    reply = ("📅 *DHL shipments*\n• DHL shipments still to send: `4`\n1. *SEJONG DHL* — DHL to send — due *today*")
    facts = voice.answer_facts(reply)
    assert facts == ["DHL shipments still to send: 4"]
    assert voice._english_line(facts, None, TODAY) == "Okie! DHL shipments still to send: 4, hehe!"
    assert voice._korean_line(facts, None, TODAY) == "짜잔! 지금 아직 보낼 DHL은 4건이에용!"
