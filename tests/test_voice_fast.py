"""Tests for fast, conversational Jennie (src/bot/voice.py, src/llm/ollama_client.py, the brain
warm-up in src/bot/scheduler.py): the instant filler clip, one-call routing with per-chat memory,
direct dispatch to the bot's commands, the one-sentence reply, one set of Ollama options with the
model kept resident, and the timing line.

Everything is offline: the fakes and fixtures come from tests/test_voice.py.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_voice_fast.py -q
"""
import asyncio
import json
import logging
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from test_voice import (  # noqa: F401  (fixtures are used by name)
    ADMIN_ID, COLLEAGUE_ID, OGG, ROUTE_TODAY, FakeBot, FakeVoice, filler_audio, llm, offline, service,
    verified_today, voice_update,
)
from src.config import settings
from src.bot import brief, scheduler, telegram_bot, voice
from src.llm.ollama_client import KEEP_ALIVE, OllamaClient, ollama_client


def run_note(update, context):
    asyncio.run(voice.handle_voice_message(update, context))


def route(command, day=None, query="", language="en"):
    return {"command": command, "date": day, "english_query": query, "language": language}


# --------------------------------------------------------------------------- the filler clip

def test_filler_goes_out_first_in_the_language_of_the_last_turn(service, llm, verified_today):
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    # A chat nobody has spoken in yet gets Korean; the clip is the very first thing sent.
    kind, clip = chat.events[0]
    assert kind == "voice" and clip.startswith(b"OggS-filler-ko_")
    assert chat.events[1] == ("text", "🎧 heard: How many verified students today?")
    assert voice.last_language(ADMIN_ID) == "en"

    # That turn was English, so the next note's filler is English.
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    assert chat.events[0][0] == "voice" and chat.events[0][1].startswith(b"OggS-filler-en_")
    filler = context.bot.fillers()[0]
    assert filler["chat_id"] == ADMIN_ID and filler["duration"] == 2 and filler["filename"] == "jennie.ogg"


def test_nothing_waits_for_the_filler(service, llm, verified_today, monkeypatch):
    """A slow filler upload delays nothing: the whole answer, spoken reply included, is out first."""
    update, context, chat = voice_update(voice=FakeVoice())
    release = asyncio.Event
    state = {}
    send_voice = context.bot.send_voice

    async def slow_filler(chat_id, voice, **kwargs):
        if voice != OGG:
            await state["release"].wait()
        return await send_voice(chat_id, voice, **kwargs)

    context.bot.send_voice = slow_filler

    async def scenario():
        state["release"] = release()
        note = asyncio.create_task(voice.handle_voice_message(update, context))
        for _ in range(500):
            if context.bot.replies():
                break
            await asyncio.sleep(0.001)
        answered_first = bool(context.bot.replies()) and not context.bot.fillers()
        state["release"].set()
        await note
        return answered_first

    assert asyncio.run(scenario()) is True
    assert any("Student Payment Verifications" in t for t in chat.visible())
    assert len(context.bot.fillers()) == 1


def test_missing_fillers_are_skipped_then_rendered_after_the_note(service, llm, verified_today, offline):
    for clip in offline.iterdir():
        clip.unlink()
    update, context, chat = voice_update(voice=FakeVoice())

    async def note_then_background():
        await voice.handle_voice_message(update, context)
        assert voice._filler_job is not None           # started only after the note was answered
        await voice._filler_job

    asyncio.run(note_then_background())
    assert context.bot.fillers() == [] and len(context.bot.replies()) == 1
    assert chat.visible()[0].startswith("🎧 heard:")
    # The note's own speech came first; then one /tts per filler line, in the aegyo style.
    assert service.tts_payloads[0]["text"] == "Good news! two students were verified today."
    rendered = service.tts_payloads[1:]
    assert [p["text"] for p in rendered] == [line for _, _, line in voice._filler_wanted()]
    assert {p["style"] for p in rendered} == {"aegyo"}
    assert voice.missing_fillers() == []
    manifest = json.loads((offline / "fillers.json").read_text(encoding="utf-8"))
    assert manifest["ko_1.ogg"] == {"line": voice.FILLER_LINES["ko"][0], "duration": 3.4}
    assert (offline / "ko_1.ogg").read_bytes() == OGG

    # The next note gets one (the fake service renders every clip as the same OGG bytes).
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    assert len(context.bot.voices) == 2 and chat.events[0] == ("voice", OGG)


def test_filler_rendering_skips_silently_while_the_service_is_down(service, offline, caplog):
    for clip in offline.iterdir():
        clip.unlink()
    service.tts_failure = "refused"
    assert asyncio.run(voice.prepare_fillers()) == 0            # never raises
    assert len(voice.missing_fillers()) == 6
    assert not any(r.levelno >= logging.WARNING for r in caplog.records if r.name == "hangeul.voice")
    assert voice._pick_filler("ko") is None and voice._pick_filler("en") is None


def test_a_dragged_out_filler_is_never_sent(offline):
    manifest = json.loads((offline / "fillers.json").read_text(encoding="utf-8"))
    for name in ("ko_1.ogg", "ko_2.ogg"):
        manifest[name]["duration"] = 8.5                        # the voice engine rambled
    (offline / "fillers.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    picked = {voice._pick_filler("ko")["line"] for _ in range(40)}
    assert picked == {voice.FILLER_LINES["ko"][2]}


def test_a_changed_filler_line_is_rendered_again(offline, monkeypatch):
    monkeypatch.setitem(voice.FILLER_LINES, "en", ("Ooh, one sec~ let me check!", "Hehe, checking now!", "New line~"))
    assert voice.missing_fillers() == [("en", "en_3.ogg", "New line~")]
    assert {voice._pick_filler("en")["line"] for _ in range(40)} == {"Ooh, one sec~ let me check!", "Hehe, checking now!"}


def test_filler_reuses_telegrams_copy(service, llm, verified_today, monkeypatch):
    """After the first upload the clip is sent by Telegram's file id: nothing is uploaded again."""
    update, context, _ = voice_update(voice=FakeVoice())
    context.bot.file_ids = True
    run_note(update, context)
    sent = context.bot.fillers()[0]["voice"]
    assert isinstance(sent, bytes)
    clip = next(c for c in voice._filler_clips.values() if c["audio"] == sent)
    assert clip["file_id"] == "file-1"

    monkeypatch.setattr(voice, "_pick_filler", lambda language: clip)
    asyncio.run(voice._send_filler(context.bot, ADMIN_ID, "ko", voice._Timings()))
    assert context.bot.voices[-1]["voice"] == "file-1"

    # A file id Telegram no longer knows: the clip is uploaded again, once.
    async def reject_ids(chat_id, voice, **kwargs):
        if isinstance(voice, str):
            raise RuntimeError("Bad Request: wrong file identifier")
        context.bot.voices.append({"voice": voice})

    context.bot.send_voice = reject_ids
    asyncio.run(voice._send_filler(context.bot, ADMIN_ID, "ko", voice._Timings()))
    assert context.bot.voices[-1]["voice"] == sent and clip["file_id"] is None


# --------------------------------------------------------------------------- routing and dispatch

@pytest.fixture
def commands(monkeypatch):
    """Every command the router can reach, replaced by a recorder that answers in the chat."""
    ran = []

    def recorder(name):
        async def command(update, context):
            ran.append((name, context.user_data.get("override_text")))
            await update.message.reply_text(f"✅ *{name}* answered: `2`")
        return command

    for name in ("verified_today_command", "verified_date_command", "inquiries_today_command",
                 "inquiries_date_command", "calendar_command", "passports_command", "stats_command",
                 "missing_command", "crosscheck_today_command", "crosscheck_date_command",
                 "crosscheck_range_command", "crosscheck_command"):
        monkeypatch.setattr(telegram_bot, name, recorder(name))
    return ran


TODAY, YESTERDAY = date(2026, 9, 28), date(2026, 9, 27)


@pytest.mark.parametrize("routed, expected, ran_as, day", [
    (route("verified_today"), ("verified_today_command", None), "verified_today", TODAY),
    (route("verified_date", "2026-09-26"), ("verified_date_command", "26 Sep 2026"), "verified_date",
     date(2026, 9, 26)),
    (route("verified_date", "2026-09-28"), ("verified_today_command", None), "verified_today", TODAY),  # today
    (route("verified_date", None, "How many students were verified yesterday?"),
     ("verified_date_command", "27 Sep 2026"), "verified_date", YESTERDAY),
    (route("verified_date", None, "Verified students on a date"), ("verified_date_command", None),
     "verified_date", None),                                                     # the command asks which
    (route("inquiries_today"), ("inquiries_today_command", None), "inquiries_today", TODAY),
    (route("inquiries_date", "2026-09-20"), ("inquiries_date_command", "20 Sep 2026"), "inquiries_date",
     date(2026, 9, 20)),
    (route("inquiries_date", None, "How many consultations on September 20?"),     # the date from the words
     ("inquiries_date_command", "20 Sep 2026"), "inquiries_date", date(2026, 9, 20)),
    (route("calendar", None, "What deadlines are coming up?"), ("calendar_command", None), "calendar", None),
    (route("passports"), ("passports_command", None), "passports", None),
    (route("stats"), ("stats_command", None), "stats", None),
    (route("missing_report"), ("missing_command", None), "missing_report", None),
    (route("crosscheck", "2026-09-27"), ("crosscheck_date_command", "27 Sep 2026"), "crosscheck_date", YESTERDAY),
    (route("crosscheck", None, "Cross-check today's verified students"), ("crosscheck_today_command", None),
     "crosscheck_today", TODAY),
    (route("crosscheck", None, "Cross-check student 412"), ("crosscheck_command", "student 412"),
     "crosscheck_student", None),
    (route("crosscheck", None, "Cross-check from 1 Sep 2026 to 15 Sep 2026"),
     ("crosscheck_range_command", "01 Sep 2026 to 15 Sep 2026"), "crosscheck_range",
     (date(2026, 9, 1), date(2026, 9, 15))),
    (route("crosscheck", "2026-09-01", "Cross-check payments from September 1 to today"),
     ("crosscheck_range_command", "01 Sep 2026 to 28 Sep 2026"), "crosscheck_range", (date(2026, 9, 1), TODAY)),
    (route("crosscheck", "2026-09-10", "Cross-check between Sep 10 and Sep 12"),
     ("crosscheck_range_command", "10 Sep 2026 to 12 Sep 2026"), "crosscheck_range",
     (date(2026, 9, 10), date(2026, 9, 12))),
    # One date, with a "to" in the English: never a range from that date to today.
    (route("crosscheck", "2026-09-25", "Cross-check payments to records on 25 Sep 2026"),
     ("crosscheck_date_command", "25 Sep 2026"), "crosscheck_date", date(2026, 9, 25)),
    (route("crosscheck", "2026-09-25", "Compare payments to records for that day"),
     ("crosscheck_date_command", "25 Sep 2026"), "crosscheck_date", date(2026, 9, 25)),
    (route("crosscheck", None, "Compare payments to records for yesterday"),
     ("crosscheck_date_command", "27 Sep 2026"), "crosscheck_date", YESTERDAY),
])
def test_each_command_is_dispatched_directly(commands, routed, expected, ran_as, day):
    update, context, chat = voice_update(voice=FakeVoice())
    routed = {**routed, "date": voice._iso_day(routed["date"])}
    ran = asyncio.run(voice._dispatch(routed, update, context, "heard words"))
    assert commands == [expected] and ran == (ran_as, day)
    assert chat.visible() == [f"✅ *{expected[0]}* answered: `2`"]


def test_chat_dispatches_nothing(commands):
    update, context, chat = voice_update(voice=FakeVoice())
    assert asyncio.run(voice._dispatch(route("chat"), update, context, "thanks!")) == ("chat", None)
    assert commands == [] and chat.visible() == []


@pytest.mark.parametrize("words, expected", [
    ("Cross-check from 1 Sep 2026 to 15 Sep 2026", [date(2026, 9, 1), date(2026, 9, 15)]),
    ("between September 1st and today", [date(2026, 9, 1), TODAY]),
    ("on 2026-09-25", [date(2026, 9, 25)]),
    ("the day before yesterday", [date(2026, 9, 26)]),
    ("9월 1일부터 15일까지", [date(2026, 9, 1), date(2026, 9, 15)]),
    ("30일", [date(2026, 8, 30)]),                           # still to come this month: last month's
    ("Cross-check student 412", []),
    ("students in the junior program, marked for decision", []),   # not months
    ("on 30 Feb", []),
])
def test_dates_are_read_from_the_english_query(words, expected):
    assert voice._query_days(words, TODAY) == expected


def test_chat_runs_no_command_and_jennie_just_answers(service, llm, commands):
    service.text, service.language = "고마워 제니야, 수고했어!", "ko"
    llm.route_default = route("chat", None, "Thanks Jennie, good work!", "ko")
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    assert commands == []
    reply = llm.calls[-1]
    assert "(none, this is small talk)" in reply["user"] and "KOREAN" in reply["system"]
    # heard, Jennie's words as the text answer (the model's emoji stripped), and her voice.
    assert chat.visible() == ["🎧 heard: 고마워 제니야, 수고했어!", "💬 헤헤, 고마워용~"]
    assert service.tts_payloads == [{"text": "헤헤, 고마워용~", "language": "ko", "style": "aegyo"}]
    assert len(context.bot.replies()) == 1
    assert voice._history[ADMIN_ID][-1]["command"] == "chat"


def test_dated_follow_up_uses_the_chat_history(service, llm, commands):
    service.text, service.language = "오늘 검증된 학생 몇 명이야?", "ko"
    llm.routes["오늘 검증된 학생 몇 명이야?"] = route("verified_today", None, "Verified students today?", "ko")
    # The brain gets the follow-up right from the history; its date is checked against the words.
    llm.routes["그럼 어제는?"] = route("verified_date", "2026-09-21", "And yesterday?", "ko")
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    service.text = "그럼 어제는?"
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)

    assert commands == [("verified_today_command", None), ("verified_date_command", "27 Sep 2026")]
    second_route = [c for c in llm.calls if c["kind"] == "route"][1]
    assert "User: 오늘 검증된 학생 몇 명이야?" in second_route["user"]
    assert "Jennie (verified_today 2026-09-28): 짜잔! 오늘 검증된 학생은" in second_route["user"]
    assert "NEW utterance: 그럼 어제는?" in second_route["user"]
    assert "Today is Monday 2026-09-28" in second_route["system"]
    assert "Sunday 2026-09-27" in second_route["system"]
    turns = list(voice._history[ADMIN_ID])
    assert [t["command"] for t in turns] == ["verified_today", "verified_date"]
    assert turns[1]["date"] == "2026-09-27"


def test_english_follow_up_and_yesterday(service, llm, commands):
    llm.routes["How many consultations today?"] = route("inquiries_today", None, "Consultations today?")
    llm.routes["and yesterday?"] = route("inquiries_date", "2026-09-27", "And yesterday?")
    for heard in ("How many consultations today?", "and yesterday?"):
        service.text = heard
        update, context, chat = voice_update(voice=FakeVoice())
        run_note(update, context)
    assert commands == [("inquiries_today_command", None), ("inquiries_date_command", "27 Sep 2026")]


@pytest.mark.parametrize("words, expected", [
    ("그럼 어제는?", date(2026, 9, 27)),
    ("그저께는?", date(2026, 9, 26)),
    ("and yesterday?", date(2026, 9, 27)),
    ("the day before yesterday", date(2026, 9, 26)),
    ("지난 금요일 상담 몇 건이었어?", date(2026, 9, 25)),
    ("How many were verified last Thursday?", date(2026, 9, 24)),
    ("And on Monday?", date(2026, 9, 21)),                       # today is Monday: the one before
    ("오늘 검증된 학생", date(2026, 9, 28)),
    ("오늘이랑 어제 비교해줘", None),                             # two days named: the brain decides
    ("How many on September 20?", None),                         # a calendar date: the brain reads it
])
def test_relative_days_are_worked_out_in_code(words, expected):
    assert voice._spoken_day(words, date(2026, 9, 28)) == expected


@pytest.mark.parametrize("words, expected", [
    ("오늘 말고 25일 검증된 학생", None),                          # the calendar date wins over 오늘
    ("9월 1일부터 오늘까지 크로스체크 해줘", None),
    ("이십오일 상담은?", None),
    ("구월 이십일 오늘 말고", None),
    ("Not today, September 20", None),
    ("the 25th, not yesterday", None),
    ("일요일 상담 몇 건이었어?", date(2026, 9, 27)),               # 일요일 is a weekday, not a date
    ("그럼 어제는?", date(2026, 9, 27)),
    ("And last Friday?", date(2026, 9, 25)),
])
def test_a_relative_word_never_overrides_a_calendar_date(words, expected):
    assert voice._relative_day(words, TODAY) == expected


def test_the_brains_calendar_date_is_kept_when_a_relative_word_is_also_spoken(llm):
    llm.routes["오늘 말고 25일 검증된 학생"] = route("verified_date", "2026-09-25", "Verified students on the 25th", "ko")
    assert asyncio.run(voice.route("오늘 말고 25일 검증된 학생"))["date"] == date(2026, 9, 25)
    # Only relative words: the weekday arithmetic is still done in code (the brain said the 26th).
    llm.routes["지난 금요일 상담 몇 건이었어?"] = route("inquiries_date", "2026-09-26", "Consultations last Friday?", "ko")
    assert asyncio.run(voice.route("지난 금요일 상담 몇 건이었어?"))["date"] == date(2026, 9, 25)


def test_a_spoken_range_from_a_date_to_today_is_crosschecked_as_a_range(service, llm, commands):
    service.text, service.language = "9월 1일부터 오늘까지 크로스체크 해줘", "ko"
    llm.route_default = route("crosscheck", "2026-09-01", "Cross-check payments from September 1 to today", "ko")
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    assert commands == [("crosscheck_range_command", "01 Sep 2026 to 28 Sep 2026")]
    turn = voice._history[ADMIN_ID][-1]
    assert turn["command"] == "crosscheck_range" and turn["date"] == "2026-09-01 to 2026-09-28"


def test_a_spoken_range_answers_the_bots_range_question(service, llm, commands):
    """/crosscheck_range asked for a START and an END date: a spoken range answers it as a range."""
    service.text, service.language = "9월 1일부터 15일까지요", "ko"
    llm.route_default = route("crosscheck", "2026-09-01", "From September 1 to September 15", "ko")
    update, context, chat = voice_update(voice=FakeVoice())
    context.user_data["awaiting_date_for"] = "crosscheck_range"
    run_note(update, context)
    assert commands == [("crosscheck_range_command", "01 Sep 2026 to 15 Sep 2026")]
    assert "awaiting_date_for" not in context.user_data
    assert voice._history[ADMIN_ID][-1]["date"] == "2026-09-01 to 2026-09-15"

    # Two dates without a range word still answer the range question.
    service.text = "9월 1일, 9월 15일"
    llm.route_default = route("crosscheck", "2026-09-01", "September 1, September 15", "ko")
    update, context, chat = voice_update(voice=FakeVoice())
    context.user_data["awaiting_date_for"] = "crosscheck_range"
    run_note(update, context)
    assert commands[-1] == ("crosscheck_range_command", "01 Sep 2026 to 15 Sep 2026")

    # One date only: the words go to the range command as they are, never collapsed to one day.
    service.text = "9월 1일부터요"
    llm.route_default = route("crosscheck", "2026-09-01", "Starting from September 1", "ko")
    update, context, chat = voice_update(voice=FakeVoice())
    context.user_data["awaiting_date_for"] = "crosscheck_range"
    run_note(update, context)
    assert commands[-1] == ("crosscheck_range_command", "Starting from September 1")

    # A new request instead drops the question.
    service.text = "전체 통계 알려줘"
    llm.route_default = route("stats", None, "Show the overall statistics", "ko")
    update, context, chat = voice_update(voice=FakeVoice())
    context.user_data["awaiting_date_for"] = "crosscheck_range"
    run_note(update, context)
    assert commands[-1] == ("stats_command", None) and "awaiting_date_for" not in context.user_data


def test_unknown_or_broken_routing_falls_back_to_the_typed_routing(service, llm, verified_today, monkeypatch):
    seen = []
    typed = telegram_bot.handle_natural_language_message

    async def spy(update, context, query=None):
        seen.append(query)
        return await typed(update, context, query=query)

    monkeypatch.setattr(telegram_bot, "handle_natural_language_message", spy)
    llm.route_default = "this is not JSON at all"
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    assert seen == ["How many verified students today?"]       # the words as heard
    assert len(verified_today) == 1 and len(context.bot.replies()) == 1

    llm.route_default = {"command": "launch_rockets", "date": None, "english_query": "x", "language": "en"}
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    assert seen[-1] == "How many verified students today?" and len(verified_today) == 2


def test_a_failing_command_falls_back_with_the_english_query(service, llm, verified_today, monkeypatch):
    async def broken(update, context):
        raise RuntimeError("portal hiccup")

    monkeypatch.setattr(telegram_bot, "stats_command", broken)
    llm.route_default = route("stats", None, "How many verified students today?")
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)                                   # must not raise
    assert len(verified_today) == 1                             # the typed routing answered instead
    assert len(context.bot.replies()) == 1
    assert "override_text" not in context.user_data


def test_a_spoken_date_answers_the_bots_date_question(service, llm, commands, monkeypatch):
    """/verified_date asked "which date?"; a voice note naming one answers it."""
    service.text, service.language = "어제요", "ko"
    llm.route_default = route("verified_date", "2026-09-27", "Yesterday", "ko")
    update, context, chat = voice_update(voice=FakeVoice())
    context.user_data["awaiting_date_for"] = "verified"
    run_note(update, context)
    assert commands == [("verified_date_command", "27 Sep 2026")]
    assert "awaiting_date_for" not in context.user_data
    assert voice._history[ADMIN_ID][-1]["command"] == "verified_date"

    # The brain took the bare answer for small talk; the words still name the day.
    service.text = "그저께요"
    llm.route_default = route("chat", None, "The day before yesterday", "ko")
    update, context, chat = voice_update(voice=FakeVoice())
    context.user_data["awaiting_date_for"] = "inquiries"
    run_note(update, context)
    assert commands[-1] == ("inquiries_date_command", "26 Sep 2026")

    # Small talk while the bot waits for a date leaves the question open.
    service.text = "고마워요"
    update, context, chat = voice_update(voice=FakeVoice())
    context.user_data["awaiting_date_for"] = "verified"
    run_note(update, context)
    assert len(commands) == 2 and context.user_data["awaiting_date_for"] == "verified"


def test_the_memory_keeps_the_day_that_was_actually_asked_about(service, llm, commands):
    """The routed date can be None while the command still ran for a day (worked out from the words):
    the memory keeps that day, so "그 전날은?" has something to count back from."""
    service.text, service.language = "그저께요", "ko"
    llm.route_default = route("chat", None, "The day before yesterday", "ko")
    update, context, chat = voice_update(voice=FakeVoice())
    context.user_data["awaiting_date_for"] = "inquiries"
    run_note(update, context)
    assert commands == [("inquiries_date_command", "26 Sep 2026")]
    turn = voice._history[ADMIN_ID][-1]
    assert turn["command"] == "inquiries_date" and turn["date"] == "2026-09-26"

    service.text = "How many were verified yesterday?"
    llm.route_default = route("verified_date", None, "How many students were verified yesterday?")
    llm.routes["그 전날은?"] = route("verified_date", "2026-09-26", "And the day before?", "ko")
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    assert voice._history[ADMIN_ID][-1]["date"] == "2026-09-27"

    service.text = "그 전날은?"
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    follow_up = [c for c in llm.calls if c["kind"] == "route"][-1]
    assert "Jennie (inquiries_date 2026-09-26):" in follow_up["user"]
    assert "Jennie (verified_date 2026-09-27):" in follow_up["user"]
    assert commands[-1] == ("verified_date_command", "26 Sep 2026")


def test_history_is_kept_per_chat_and_capped(service, llm, verified_today):
    for n in range(voice.HISTORY_TURNS + 2):
        service.text = f"question number {n}"
        update, context, chat = voice_update(voice=FakeVoice())
        run_note(update, context)
    service.text = "colleague question"
    update, context, chat = voice_update(chat_id=COLLEAGUE_ID, voice=FakeVoice())
    run_note(update, context)

    mine, theirs = list(voice._history[ADMIN_ID]), list(voice._history[COLLEAGUE_ID])
    assert len(mine) == voice.HISTORY_TURNS
    assert [t["user"] for t in mine][-1] == f"question number {voice.HISTORY_TURNS + 1}"
    assert [t["user"] for t in theirs] == ["colleague question"]
    # The colleague's routing saw none of the admin's conversation.
    colleague_route = [c for c in llm.calls if c["kind"] == "route"][-1]
    assert "question number" not in colleague_route["user"] and "(none)" in colleague_route["user"]
    # The admin's last routing saw only the last PROMPT_TURNS turns.
    admin_route = [c for c in llm.calls if c["kind"] == "route"][-2]
    assert admin_route["user"].count("User: ") == voice.PROMPT_TURNS


# --------------------------------------------------------------------------- the spoken reply

def test_emojis_and_markup_are_stripped_from_what_jennie_says():
    ko = voice._speech_text("짜잔! 오늘 서류 검증된 학생은 2명이에요용~ 💖✨", "ko", 45)
    assert ko == "짜잔! 오늘 서류 검증된 학생은 두명이에요용~"
    en = voice._speech_text("**Yay!** 2 students were verified today, hehe! 🎉😊❤️ ♡ ⭐", "en", 120)
    assert en == "Yay! two students were verified today, hehe!"
    assert voice._plain("Okie 👍🏽 done ✅ 🇧🇩") == "Okie done"


def test_reply_is_one_short_sentence(service, llm, verified_today):
    llm.reply_en = ("Ta-da! 2 students were verified today, hehe! They paid 55,000 taka together, and Lina "
                    "checked both of them, and everyone is super happy about it, okie!")
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    spoken = service.tts_payloads[0]["text"]
    assert spoken == "Ta-da! two students were verified today, hehe!"
    assert len(spoken) <= voice.REPLY_MAX_CHARS["en"]
    # Too long: asked once more for a shorter line; still too long, it is cut at a sentence end.
    replies = [c for c in llm.calls if c["kind"] == "reply"]
    assert len(replies) == 2 and "(Too long: say it in ONE short sentence" in replies[1]["user"]


def test_a_too_long_korean_reply_is_asked_again_shorter(service, llm, verified_today, monkeypatch):
    """Cut to fit, a Korean sentence would lose its end, where the number is: ask again instead."""
    service.text, service.language = "오늘 검증된 학생 몇 명이야?", "ko"
    long_line = "짜잔! 오늘 서류랑 결제까지 전부 검증이 끝난 학생은 모두 합쳐서 2명이에용!"
    replies = iter([long_line, "짜잔! 오늘은 2명이에용!"])
    real = llm.chat

    async def brain(messages, format=None, **kwargs):
        if format is None:
            llm.calls.append({"kind": "reply", "system": messages[0]["content"], "user": messages[-1]["content"],
                              "format": None, "num_predict": kwargs.get("num_predict")})
            return next(replies)
        return await real(messages, format=format, **kwargs)

    monkeypatch.setattr(ollama_client, "chat", brain)
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    tries = [c for c in llm.calls if c["kind"] == "reply"]
    assert len(tries) == 2 and "at most 22 characters" in tries[1]["user"]
    assert service.tts_payloads[0]["text"] == "짜잔! 오늘은 두명이에용!"
    assert len(voice._speech_text(long_line, "ko", 10 ** 4)) > voice.REPLY_MAX_CHARS["ko"]


def test_small_talk_never_invents_a_number(service, llm, commands):
    """A data question the router took for small talk: a made-up figure is never spoken or shown."""
    service.text = "thanks jennie"
    llm.route_default = route("chat", None, "Thanks Jennie")
    llm.chat_en = "Hehe, you have 5 students today!"
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    tries = [c for c in llm.calls if c["kind"] == "reply"]
    assert len(tries) == 2 and "(Do not say any numbers.)" in tries[1]["user"]
    assert chat.visible() == ["🎧 heard: thanks jennie", f"💬 {voice._FALLBACK[('en', False)]}"]
    assert service.tts_payloads[0]["text"] == voice._FALLBACK[("en", False)]

    # A number the user said is fine.
    service.text = "I have 2 questions, Jennie"
    llm.chat_en = "Sure, ask me your 2 questions, hehe!"
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    assert chat.visible()[-1] == "💬 Sure, ask me your two questions, hehe!"


def test_a_number_not_in_the_answer_is_never_spoken(service, llm, verified_today):
    replies = iter(["Yay! Seventy-seven students were verified today, hehe!",      # invented
                    "Yay! 2 students were verified today, hehe!"])
    real = llm.chat

    async def brain(messages, format=None, **kwargs):
        if format is None:
            llm.calls.append({"kind": "reply", "system": messages[0]["content"], "user": messages[-1]["content"],
                              "format": None, "num_predict": kwargs.get("num_predict")})
            return next(replies)
        return await real(messages, format=format, **kwargs)

    ollama_client.chat = brain
    try:
        update, context, chat = voice_update(voice=FakeVoice())
        run_note(update, context)
    finally:
        ollama_client.chat = real
    tries = [c for c in llm.calls if c["kind"] == "reply"]
    assert len(tries) == 2 and "(The only numbers you may say:" in tries[1]["user"]
    assert service.tts_payloads[0]["text"] == "Yay! two students were verified today, hehe!"

    # Wrong twice: Jennie says where the answer is instead of a wrong number.
    llm.reply_en = "Yay! 99 students were verified today!"
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    assert service.tts_payloads[-1]["text"] == voice._FALLBACK[("en", True)]


def test_numbers_are_read_from_digits_and_words():
    assert voice._numbers_in("Ta-da! twenty-eight thousand taka, 2 students, one sec, 1,250.50") == {28000, 2, 1250, 50}
    assert voice._numbers_in("Seven inquiries, five done, three hundred and twelve in all") == {7, 5, 312}
    assert voice._numbers_in("Paid: 28,000.00 BDT") == {28000}              # a .00 is not a zero
    assert voice._facts_ok("짜잔! 어제는 7건이에용!", "Inquiries Received: 7")
    assert not voice._facts_ok("Yay! Three inquiries yesterday!", "Inquiries Received: 7 Done: 5")
    # Zero only when the answer itself says there is nothing.
    assert voice._facts_ok("Yay! zero payments today, hehe!", "No student payments were verified on 28 September 2026.")
    assert not voice._facts_ok("0명이에용", "Total Students Verified: 2")


@pytest.mark.parametrize("words, numbers", [
    ("짜잔! 오늘 검증된 학생은 세 명이에용!", {3}),
    ("열두 건이었어용", {12}),
    ("스무 명", {20}),
    ("스물다섯 명이에요", {25}),
    ("한 명", {1}),
    ("두 번 확인했어요", {2}),
    ("모두 세 명입니다", {3}),
    ("여섯 건으로 늘었어용", {6}),
    ("이십 건", {20}),
    ("삼백 타카", {300}),
    ("이만 오천 원이에요", {25000}),
    ("오 퍼센트", {5}),
    ("만 타카", {10000}),
    # Not numbers: 한번 ("have a look"), 한국 / 한글, 네~ (yes), 이 학생 / 이 건 (this), 사건 (an incident), 명단.
    ("한번 확인해 볼게용! 한국어 한글", set()),
    ("네~ 금방 알려드릴게용", set()),
    ("이 학생은 이 건만 남았어요", set()),
    ("사건이 없어요", set()),
    ("네 명단 보내드릴게요", set()),
])
def test_korean_number_words_are_read(words, numbers):
    assert voice._numbers_in(words) == numbers


def test_a_wrong_korean_number_or_none_is_caught():
    question = "오늘 검증된 학생 몇 명이야?"
    answer = "Total Students Verified Today: 5"
    assert not voice._facts_ok("짜잔! 오늘 검증된 학생은 세 명이에용!", answer, question)
    assert voice._facts_ok("짜잔! 오늘 검증된 학생은 다섯 명이에용!", answer, question)
    assert not voice._facts_ok("오늘 검증된 학생은 없어요용!", answer, question)
    assert not voice._facts_ok("Yay! No students were verified today!", answer, question)
    nothing = "No student payments were verified on 28 September 2026."
    assert voice._facts_ok("오늘 검증된 학생은 없어요용!", nothing, question)
    assert voice._facts_ok("Aww, no students today, hehe!", nothing, question)
    # A stray "not" in the answer no longer allows a zero.
    assert not voice._facts_ok("Yay! zero students!", "Total: 2 (Status: not audited)", question)
    # Small talk: 없어요 ("no worries") is not a number there.
    assert voice._facts_ok("걱정 없어용~", "", "고마워 제니야")


def test_the_timing_line_has_every_stage_and_no_words(service, llm, verified_today, caplog):
    caplog.set_level(logging.INFO, logger="hangeul.voice")
    service.text = "How many verified students today?"
    update, context, chat = voice_update(voice=FakeVoice())
    run_note(update, context)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Voice note from")]
    assert len(lines) == 1
    line = lines[0]
    assert line.startswith(f"Voice note from {ADMIN_ID}: 4.0s audio, en, verified_today | filler +")
    stages = [part.split()[0] for part in line.split(" | ", 1)[1].split(", ")]
    assert stages == ["filler", "download", "stt", "route", "command", "reply", "tts", "voice", "total"]
    assert "verified students" not in caplog.text.lower()


# --------------------------------------------------------------------------- one brain, resident

def _recording_client(monkeypatch, answer):
    sent = []

    def handler(request):
        body = json.loads(request.content) if request.content else {}
        sent.append((request.url.path, body))
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": settings.OLLAMA_MODEL, "model": settings.OLLAMA_MODEL,
                                                         "size": 3 * 2 ** 30, "size_vram": 3 * 2 ** 30,
                                                         "context_length": settings.OLLAMA_NUM_CTX}]})
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={"message": {"role": "assistant", "content": answer(body)}})
        return httpx.Response(200, json={"response": "ok"})

    client = OllamaClient()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def reachable():
        return {"reachable": True, "target_model_ready": True}

    client.check_health = reachable
    monkeypatch.setattr(ollama_client, "client", client.client)
    monkeypatch.setattr(ollama_client, "check_health", reachable)
    return client, sent


def test_every_ollama_call_sends_one_num_ctx_and_keeps_the_model_resident(monkeypatch):
    def answer(body):
        if "format" in body:
            return json.dumps(route("verified_today", None, "Verified today?"))
        return "Ta-da! 2 students, hehe! 😊"

    client, sent = _recording_client(monkeypatch, answer)

    async def everything():
        await client.generate_response("typed question", system="agent")          # typed path
        await brief.llm_summary(["Consultation requests received today: 2"])     # 18:05 brief summary
        await ollama_client.answer_agent_query("how are we doing?", {"dashboard": {}})
        await telegram_bot._ai_write_email("remind about passport", {"name": "A"}, "Passport")
        await voice.route("오늘 검증된 학생 몇 명이야?")                            # voice routing
        await voice.spoken_reply("verified today?", "en", "Total Students Verified: 2")
        await voice.spoken_brief("Total Inquiries Received: 5")
        await client.warm_up()                                                     # startup warm-up

    asyncio.run(everything())
    calls = [body for path, body in sent if path in ("/api/generate", "/api/chat")]
    assert len(calls) >= 8
    for body in calls:
        assert body["model"] == settings.OLLAMA_MODEL
        assert body["keep_alive"] == KEEP_ALIVE == -1           # resident: never "0s"
        assert body["options"]["num_ctx"] == settings.OLLAMA_NUM_CTX
        assert body["options"]["temperature"] == 0.3
        assert "think" not in body                              # a non-thinking model
    assert {json.dumps({k: v for k, v in b["options"].items() if k != "num_predict"}) for b in calls} == {
        json.dumps({"temperature": 0.3, "num_ctx": settings.OLLAMA_NUM_CTX})}
    routing = next(b for b in calls if "format" in b)
    assert routing["format"]["required"] == ["command", "date", "english_query", "language"]


def test_warm_up_reports_where_the_model_is(monkeypatch):
    client, sent = _recording_client(monkeypatch, lambda body: "")
    state = asyncio.run(client.warm_up())
    assert state["loaded"] and state["on_gpu"] and state["num_ctx"] == settings.OLLAMA_NUM_CTX
    assert sent[0] == ("/api/generate", {"model": settings.OLLAMA_MODEL, "stream": False, "keep_alive": -1,
                                         "options": {"temperature": 0.3, "num_ctx": settings.OLLAMA_NUM_CTX},
                                         "prompt": ""})


def test_the_brain_chat_never_raises(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client = OllamaClient()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(client.chat([{"role": "user", "content": "hi"}])) is None


def test_warm_brain_reloads_a_model_that_landed_partly_on_the_cpu(monkeypatch):
    states = iter([{"loaded": True, "on_gpu": False, "vram_gb": 1.9, "size_gb": 2.8},
                   {"loaded": True, "on_gpu": True, "vram_gb": 2.8, "size_gb": 2.8, "num_ctx": 3072}])
    events = []

    async def warm_up():
        events.append("load")
        return next(states)

    async def unload():
        events.append("unload")

    async def prepare_fillers():
        events.append("fillers")
        return 0

    monkeypatch.setattr(ollama_client, "warm_up", warm_up)
    monkeypatch.setattr(ollama_client, "unload", unload)
    monkeypatch.setattr(voice, "prepare_fillers", prepare_fillers)
    assert asyncio.run(scheduler.warm_brain(retry_after=0)) is True
    assert events == ["load", "unload", "load", "fillers"]     # the brain first, then the clips


def test_keep_warm_reloads_a_brain_that_ollama_lost_or_that_sits_partly_on_the_cpu(monkeypatch):
    events = []

    async def warm_brain(attempts=3, retry_after=30.0):
        events.append(("load", attempts))
        return True

    async def unload():
        events.append("unload")

    monkeypatch.setattr(scheduler, "warm_brain", warm_brain)
    monkeypatch.setattr(ollama_client, "unload", unload)
    for state in ({"loaded": True, "on_gpu": True},                                  # all on the GPU: nothing
                  {"loaded": False, "on_gpu": False},                                # lost: load it
                  {"loaded": True, "on_gpu": False, "vram_gb": 1.9, "size_gb": 2.8}):  # split: unload, load
        async def residency(state=state):
            return state
        monkeypatch.setattr(ollama_client, "residency", residency)
        asyncio.run(scheduler.keep_brain_warm())
    assert events == [("load", 1), "unload", ("load", 1)]


def test_an_over_long_prompt_is_logged_before_ollama_cuts_it(monkeypatch, caplog):
    """Ollama cuts an over-long prompt silently (keeping ~its last half), so it is measured first."""
    from src.llm.ollama_client import ANSWER_BUDGET_TOKENS, CHARS_PER_TOKEN
    client, sent = _recording_client(monkeypatch, lambda body: "ok")
    caplog.set_level(logging.WARNING, logger="hangeul.llm")
    room = int((client.num_ctx - ANSWER_BUDGET_TOKENS) * CHARS_PER_TOKEN)
    asyncio.run(client.generate_response("question?", system="x" * (room - 100)))
    assert "may cut it" not in caplog.text
    asyncio.run(client.generate_response("question?", system="x" * (room + 100)))
    assert "may cut it" in caplog.text and f"num_ctx {client.num_ctx}" in caplog.text
    caplog.clear()
    asyncio.run(client.chat([{"role": "system", "content": "y" * (room + 100)}, {"role": "user", "content": "hi"}]))
    assert "Ollama chat: the prompt is" in caplog.text
    # After the call: a prompt that Ollama reports as nearly filling the context.
    caplog.clear()
    client._check_used("generate", {"prompt_eval_count": client.num_ctx - 100})
    client._check_used("generate", {"prompt_eval_count": 900})
    assert caplog.text.count("the prompt took") == 1
    # Jennie's own prompts stay well inside it.
    assert client.prompt_fits("route", voice._ROUTER_SYSTEM, "x" * 2000)
    assert client.prompt_fits("reply", voice._REPLY_SYSTEM_KO, "x" * (voice.ANSWER_MAX_CHARS + 1500))


def test_post_init_starts_the_brain_warm_up(monkeypatch):
    started = []

    class App:
        bot = SimpleNamespace()

        def create_task(self, coroutine, update=None, name=None):
            started.append(name)
            coroutine.close()

    async def ok(*args, **kwargs):
        return SimpleNamespace(message_id=1)

    app = App()
    app.bot.set_my_commands = ok
    app.bot.send_message = ok
    app.bot.pin_chat_message = ok
    asyncio.run(telegram_bot.post_init(app))
    assert started == ["brain-warm-up"]


def test_scheduler_keeps_the_brain_warm(monkeypatch):
    added = []
    monkeypatch.setattr(settings, "ENABLE_SCHEDULED_REPORTS", True)
    monkeypatch.setattr(scheduler.scheduler, "add_job", lambda func, trigger, **kw: added.append((func, kw["id"])))
    monkeypatch.setattr(scheduler.scheduler, "start", lambda: None)
    scheduler.setup_scheduler(SimpleNamespace())
    assert (scheduler.keep_brain_warm, "brain_keep_warm") in added
