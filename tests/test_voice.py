"""Tests for Jennie's voice (src/bot/voice.py) and its hooks in the bot and the scheduler.

Nothing here touches the network: the voice service is an httpx.MockTransport that follows the
API contract, the local LLM and the portal are stubs (the real clients are swapped for ones that
fail loudly), and the Telegram objects are small fakes. The bot is never started.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_voice.py -q
"""
import asyncio
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

from src.config import settings  # noqa: E402
from src.bot import scheduler, telegram_bot, voice  # noqa: E402
from src.llm.ollama_client import OllamaClient, ollama_client  # noqa: E402
from src.scraper.client import admin_client  # noqa: E402

ADMIN_ID = 111111111
STRANGER_ID = 999999999
OGG = b"OggS" + b"\x00" * 64


# --------------------------------------------------------------------------- fakes

class FakeChat:
    """Everything the bot shows in one chat, in order."""

    def __init__(self, chat_id):
        self.id = chat_id
        self.log = []

    def visible(self):
        return [m.text for m in self.log if not m.deleted]


class FakeMessage:
    _next_id = 1

    def __init__(self, chat, text=None, voice=None, audio=None):
        self.chat = chat
        self.text = text
        self.voice = voice
        self.audio = audio
        self.deleted = False
        self.message_id = FakeMessage._next_id
        FakeMessage._next_id += 1

    async def reply_text(self, text, parse_mode=None, **kwargs):
        sent = FakeMessage(self.chat, text=text)
        self.chat.log.append(sent)
        return sent

    async def edit_text(self, text, parse_mode=None, **kwargs):
        self.text = text
        return self

    async def delete(self, **kwargs):
        self.deleted = True
        return True


class FakeFile:
    def __init__(self, data):
        self.data = data

    async def download_as_bytearray(self):
        return bytearray(self.data)


class FakeVoice:
    def __init__(self, data=b"recorded-opus", duration=4, file_size=2048, mime_type="audio/ogg"):
        self.data = data
        self.duration = duration
        self.file_size = file_size
        self.mime_type = mime_type

    async def get_file(self):
        return FakeFile(self.data)


class FakeBot:
    def __init__(self, chat=None):
        self.chat = chat
        self.messages = []
        self.voices = []
        self.actions = []

    async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
        self.messages.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
        return FakeMessage(self.chat or FakeChat(chat_id), text=text)

    async def send_voice(self, chat_id, voice, duration=None, filename=None, **kwargs):
        self.voices.append({"chat_id": chat_id, "voice": voice, "duration": duration, "filename": filename})

    async def send_chat_action(self, chat_id, action, **kwargs):
        self.actions.append(action)


def voice_update(chat_id=ADMIN_ID, voice=None, text=None):
    chat = FakeChat(chat_id)
    message = FakeMessage(chat, text=text, voice=voice if text is None else None)
    update = SimpleNamespace(message=message, effective_message=message, callback_query=None,
                             effective_chat=SimpleNamespace(id=chat_id),
                             effective_user=SimpleNamespace(id=chat_id))
    context = SimpleNamespace(bot=FakeBot(chat), user_data={}, args=None)
    return update, context, chat


class FakeVoiceService:
    """The voice-service API contract, served through httpx.MockTransport."""

    def __init__(self, text="How many verified students today?", language="en"):
        self.text = text
        self.language = language
        self.stt_failure = None     # None | "refused" | "timeout" | "503" | "500" | "not-json"
        self.tts_failure = None     # None | "refused" | "timeout" | "503" | "not-ogg"
        self.delay = 0.0            # seconds each request takes
        self.in_flight = 0
        self.max_in_flight = 0
        self.requests = []
        self.tts_payloads = []
        self.uploads = []

    async def __call__(self, request):
        self.requests.append(request.url.path)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return self._respond(request)
        finally:
            self.in_flight -= 1

    def _respond(self, request):
        if request.url.path == "/stt":
            if self.stt_failure == "refused":
                raise httpx.ConnectError("connection refused", request=request)
            if self.stt_failure == "timeout":
                raise httpx.ReadTimeout("timed out", request=request)
            if self.stt_failure == "503":
                return httpx.Response(503, json={"error": "busy: waited 120 s for the previous request"})
            if self.stt_failure == "500":
                return httpx.Response(500, json={"error": "RuntimeError"})
            if self.stt_failure == "not-json":
                return httpx.Response(200, content=b"<html>proxy page</html>", headers={"Content-Type": "text/html"})
            body = request.read()
            self.uploads.append(body)
            return httpx.Response(200, json={"text": self.text, "language": self.language,
                                             "duration_s": 3.9, "seconds": 0.8})
        if request.url.path == "/tts":
            payload = json.loads(request.content)
            self.tts_payloads.append(payload)
            if self.tts_failure == "refused":
                raise httpx.ConnectError("connection refused", request=request)
            if self.tts_failure == "timeout":
                raise httpx.ReadTimeout("timed out", request=request)
            if self.tts_failure == "503":
                return httpx.Response(503, json={"error": "busy for more than 120 s"})
            if self.tts_failure == "not-ogg":
                return httpx.Response(200, content=b"RIFF\x24\x00\x00\x00WAVEfmt ", headers={"Content-Type": "audio/wav"})
            if len(payload["text"]) > 600:
                return httpx.Response(413, json={"error": "text too long"})
            return httpx.Response(200, content=OGG,
                                  headers={"Content-Type": "audio/ogg", "X-Duration": "3.4", "X-Seconds": "1.1"})
        return httpx.Response(404, json={"error": "not found"})


class FakeLLM:
    """Stands in for ollama_client.generate_response."""

    def __init__(self):
        self.calls = []
        self.down = False
        self.rewrite = "verified students today"
        self.summary_ko = "짜잔! 오늘 검증된 학생은 2명이에용. 모두 확인 완료예요!"
        self.summary_en = "Good news! 2 students were verified today."

    async def generate_response(self, prompt, system=None, keep_alive=None):
        self.calls.append({"prompt": prompt, "system": system or "", "keep_alive": keep_alive})
        if self.down:
            return OllamaClient._fallback_response(None, prompt)     # the real "Ollama is down" text
        if "English query:" in prompt:
            return self.rewrite
        if "KOREAN" in (system or ""):
            return self.summary_ko
        return self.summary_en

    def kinds(self):
        return ["rewrite" if "English query:" in c["prompt"] else "summary" for c in self.calls]


def _refuse(request):
    raise AssertionError(f"tests must not reach the network: {request.method} {request.url.host}")


# --------------------------------------------------------------------------- fixtures

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Known settings, and no way out to the portal, Ollama or Telegram."""
    monkeypatch.setattr(settings, "TELEGRAM_ADMIN_CHAT_ID", str(ADMIN_ID))
    monkeypatch.setattr(settings, "TELEGRAM_AUTHORIZED_CHAT_IDS", "")
    monkeypatch.setattr(settings, "JENNIE_VOICE_ENABLED", True)
    monkeypatch.setattr(settings, "JENNIE_VOICE_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(settings, "JENNIE_SPOKEN_BRIEF", True)
    refusing = httpx.AsyncClient(transport=httpx.MockTransport(_refuse))
    monkeypatch.setattr(admin_client, "client", refusing)
    monkeypatch.setattr(admin_client, "is_authenticated", True)
    monkeypatch.setattr(ollama_client, "client", refusing)

    async def no_login(*args, **kwargs):
        raise AssertionError("tests must not log in to the portal")

    async def ollama_unreachable():
        return {"reachable": False}

    monkeypatch.setattr(admin_client, "login", no_login)
    monkeypatch.setattr(ollama_client, "check_health", ollama_unreachable)


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(ollama_client, "generate_response", fake.generate_response)
    return fake


@pytest.fixture
def service(monkeypatch):
    svc = FakeVoiceService()

    def client(timeout):
        return httpx.AsyncClient(base_url="http://127.0.0.1:8765", timeout=timeout,
                                 transport=httpx.MockTransport(svc))

    monkeypatch.setattr(voice, "_http", client)
    return svc


@pytest.fixture
def verified_today(monkeypatch):
    """The portal's verified-students list, as the /verified_today command reads it."""
    asked = []

    async def get_verified_students(target_date="today"):
        asked.append(target_date)
        return [
            {"name": "DEB BIKASH CHANDRA", "program": "KLP", "amount": "Paid: 25,000 BDT",
             "verified_by": "Lina", "verified_time": "10:15"},
            {"name": "HABIB MD FAHMID", "program": "Bachelor's", "amount": "Paid: 30,000 BDT",
             "verified_by": "Lina", "verified_time": "11:40"},
        ]

    monkeypatch.setattr(admin_client, "get_verified_students", get_verified_students)
    return asked


# --------------------------------------------------------------------------- the voice handler

def test_unauthorized_sender_is_refused(service, llm):
    update, context, chat = voice_update(chat_id=STRANGER_ID, voice=FakeVoice())
    asyncio.run(voice.handle_voice_message(update, context))
    assert service.requests == []          # nothing downloaded or transcribed
    assert llm.calls == []
    assert chat.log == [] and context.bot.voices == []

    # The same refusal a typed question from that chat gets: silence.
    text_update, text_context, text_chat = voice_update(chat_id=STRANGER_ID, text="verified students today")
    asyncio.run(telegram_bot.handle_natural_language_message(text_update, text_context))
    assert text_chat.log == []


def test_korean_voice_is_rewritten_routed_and_spoken(service, llm, verified_today, caplog):
    caplog.set_level(logging.INFO, logger="hangeul.voice")
    service.text, service.language = "오늘 검증된 학생 몇 명이야?", "ko"
    update, context, chat = voice_update(voice=FakeVoice(data=b"korean-opus"))
    asyncio.run(voice.handle_voice_message(update, context))

    # The log gets the facts about the note, never what was said.
    assert "Voice note from" in caplog.text and "(rewritten)" in caplog.text
    assert "검증" not in caplog.text and "verified students" not in caplog.text

    shown = chat.visible()
    assert shown[0] == "🎧 heard: 오늘 검증된 학생 몇 명이야?\n🔎 as: verified students today"
    # The existing routing ran /verified_today with the rewritten query: its report is in the chat
    # exactly as for a typed question, and its "⏳ Gathering…" note was deleted as usual.
    assert len(verified_today) == 1
    assert any("Student Payment Verifications" in t and "DEB BIKASH CHANDRA" in t for t in shown)
    assert not any(t.startswith("⏳") for t in shown)
    assert voice.UNAVAILABLE_NOTE not in shown

    assert llm.kinds() == ["rewrite", "summary"]
    rewrite, summary = llm.calls
    assert "오늘 검증된 학생 몇 명이야?" in rewrite["prompt"] and rewrite["keep_alive"] == "30s"
    assert "KOREAN" in summary["system"] and summary["keep_alive"] == "0s"
    assert "Student Payment Verifications" in summary["prompt"]    # the captured answer fed the summary

    assert service.uploads and b"korean-opus" in service.uploads[0]
    assert service.tts_payloads == [{"text": "짜잔! 오늘 검증된 학생은 두명이에용. 모두 확인 완료예요!",
                                     "language": "ko", "style": "aegyo"}]
    assert context.bot.voices == [{"chat_id": ADMIN_ID, "voice": OGG, "duration": 3, "filename": "jennie.ogg"}]


def test_english_voice_goes_straight_to_routing_and_tts(service, llm, verified_today):
    update, context, chat = voice_update(voice=FakeVoice())
    asyncio.run(voice.handle_voice_message(update, context))

    assert chat.visible()[0] == "🎧 heard: How many verified students today?"
    assert llm.kinds() == ["summary"]                               # no rewrite for English
    assert b'name="audio"; filename="voice.ogg"' in service.uploads[0]
    assert service.tts_payloads == [{"text": "Good news! two students were verified today.",
                                     "language": "en", "style": "aegyo"}]
    assert context.bot.voices[0]["voice"] == OGG
    assert context.bot.voices[0]["chat_id"] == ADMIN_ID


def test_capture_collects_the_commands_final_text(monkeypatch):
    update, context, chat = voice_update(voice=FakeVoice())
    capture = voice._Capture()
    proxy = voice._CapturingUpdate(update, capture)

    async def routed_command():
        status = await proxy.message.reply_text("⏳ _Gathering…_", parse_mode="Markdown")
        await proxy.message.reply_text("✅ *Report* — `3` students", parse_mode="Markdown")
        await status.delete()
        thinking = await proxy.message.reply_text("🤔 _Consulting…_")
        await thinking.edit_text("The answer is 42.")

    asyncio.run(routed_command())
    assert capture.text() == "✅ *Report* — `3` students\n\nThe answer is 42."
    assert chat.visible() == ["✅ *Report* — `3` students", "The answer is 42."]   # all really sent
    assert proxy.effective_chat.id == ADMIN_ID                  # everything else is the real update

    # And through the real natural-language routing (the LLM-agent branch edits its status note).
    async def get_dashboard():
        return {"summary": {}}

    async def empty_list(*args, **kwargs):
        return []

    async def answer_agent_query(query, context):
        return f"Answer to: {query}"

    monkeypatch.setattr(admin_client, "get_dashboard", get_dashboard)
    monkeypatch.setattr(admin_client, "get_applications", empty_list)
    monkeypatch.setattr(admin_client, "get_inquiries", empty_list)
    monkeypatch.setattr(ollama_client, "answer_agent_query", answer_agent_query)
    capture = voice._Capture()
    asyncio.run(telegram_bot.handle_natural_language_message(
        voice._CapturingUpdate(update, capture), context, query="what is the office phone policy"))
    assert capture.text() == "Answer to: what is the office phone policy"


def test_crosscheck_route_no_longer_hits_missing_re_import(monkeypatch):
    """handle_natural_language_message uses re.search on this branch; it needs the module import."""
    called = []

    async def crosscheck_date_command(update, context):
        called.append(True)

    monkeypatch.setattr(telegram_bot, "crosscheck_date_command", crosscheck_date_command)
    update, context, chat = voice_update(voice=FakeVoice())
    asyncio.run(telegram_bot.handle_natural_language_message(update, context, query="crosscheck please"))
    assert called == [True]


@pytest.mark.parametrize("failure", ["503", "refused", "timeout", "not-ogg"])
def test_voice_service_down_still_sends_text_answers(service, llm, verified_today, failure):
    service.tts_failure = failure
    update, context, chat = voice_update(voice=FakeVoice())
    asyncio.run(voice.handle_voice_message(update, context))   # must not raise

    shown = chat.visible()
    assert shown[0].startswith("🎧 heard:")
    assert any("Student Payment Verifications" in t for t in shown)
    assert shown.count(voice.UNAVAILABLE_NOTE) == 1 and shown[-1] == voice.UNAVAILABLE_NOTE
    assert context.bot.voices == []


@pytest.mark.parametrize("failure, note", [
    ("refused", "voice service is unavailable"),
    ("500", "voice service is unavailable"),
    ("not-json", "voice service is unavailable"),
    ("503", "voice service is busy"),
    ("timeout", "voice service is busy"),
])
def test_speech_to_text_failure_gives_one_short_note(service, llm, failure, note):
    service.stt_failure = failure
    update, context, chat = voice_update(voice=FakeVoice())
    asyncio.run(voice.handle_voice_message(update, context))   # must not raise
    assert len(chat.visible()) == 1 and note in chat.visible()[0]
    assert "type your question" in chat.visible()[0]
    assert service.requests == ["/stt"] and llm.calls == [] and context.bot.voices == []


def test_voice_service_error_replies_are_classified():
    """The contract's JSON errors: 503 means busy, anything else means unavailable."""
    busy = voice._service_error(httpx.Response(503, json={"error": "busy"}), "speech-to-text")
    broken = voice._service_error(httpx.Response(500, json={"error": "RuntimeError"}), "speech-to-text")
    plain = voice._service_error(httpx.Response(502, content=b"Bad Gateway"), "speech")
    assert isinstance(busy, voice.VoiceServiceBusy) and str(busy) == "speech-to-text HTTP 503: busy"
    assert type(broken) is voice.VoiceServiceError and str(broken) == "speech-to-text HTTP 500: RuntimeError"
    assert type(plain) is voice.VoiceServiceError and str(plain) == "speech HTTP 502: Bad Gateway"


def test_llm_down_still_speaks_the_text_answer(service, llm, verified_today):
    llm.down = True
    update, context, chat = voice_update(voice=FakeVoice())
    asyncio.run(voice.handle_voice_message(update, context))
    spoken = service.tts_payloads[0]["text"]
    assert spoken.startswith("Student Payment Verifications")
    assert len(spoken) <= voice.REPLY_MAX_CHARS and not any(ch.isdigit() for ch in spoken)
    assert "*" not in spoken and "✅" not in spoken
    assert len(context.bot.voices) == 1


def test_voice_never_drives_the_email_flow(service, llm, monkeypatch):
    def no_email(*args, **kwargs):
        raise AssertionError("a voice note must never send an email")

    monkeypatch.setattr(telegram_bot, "_send_gmail", no_email)
    service.text = "send"
    update, context, chat = voice_update(voice=FakeVoice())
    context.user_data["email_flow"] = {"step": "confirm"}
    asyncio.run(voice.handle_voice_message(update, context))
    assert chat.visible()[0] == "🎧 heard: send"
    assert "please type it" in chat.visible()[1]
    assert context.user_data["email_flow"] == {"step": "confirm"}
    assert service.tts_payloads == [] and llm.calls == []


def test_sendmail_typed_during_the_rewrite_does_not_get_the_voice_query(service, llm, monkeypatch):
    """Voice notes run with block=False: /sendmail can be typed while a Korean note is rewritten."""
    email_steps = []

    async def handle_email_flow(update, context, text):
        email_steps.append(text)

    monkeypatch.setattr(telegram_bot, "_handle_email_flow", handle_email_flow)
    service.text, service.language = "오늘 검증된 학생 몇 명이야?", "ko"
    update, context, chat = voice_update(voice=FakeVoice())
    rewrite = llm.generate_response

    async def rewrite_while_sendmail_is_typed(prompt, system=None, keep_alive=None):
        context.user_data["email_flow"] = {"step": "subject", "student_id": "412"}
        return await rewrite(prompt, system=system, keep_alive=keep_alive)

    monkeypatch.setattr(ollama_client, "generate_response", rewrite_while_sendmail_is_typed)
    asyncio.run(voice.handle_voice_message(update, context))

    assert email_steps == []                                     # the query never became the subject
    assert context.user_data["email_flow"] == {"step": "subject", "student_id": "412"}
    assert chat.visible()[-1] == voice.EMAIL_FLOW_NOTE
    assert llm.kinds() == ["rewrite"] and service.tts_payloads == []


def test_too_long_recording_is_not_downloaded(service, llm):
    # A note is never longer than the time /stt gets: the CPU fallback runs faster than real time.
    assert voice.MAX_VOICE_SECONDS <= voice.STT_TIMEOUT
    update, context, chat = voice_update(voice=FakeVoice(duration=voice.MAX_VOICE_SECONDS + 1))
    asyncio.run(voice.handle_voice_message(update, context))
    assert service.requests == [] and "too long" in chat.visible()[0]
    assert f"under {voice.MAX_VOICE_SECONDS} seconds" in chat.visible()[0]


def test_voice_flows_take_turns_at_the_voice_service(service, llm, verified_today, monkeypatch):
    """Two voice notes and the spoken brief at once: one voice-service request at a time, and no
    spoken summary loads the LLM while speech is being rendered."""
    service.delay = 0.02
    summaries_during_requests = []
    summarize = llm.generate_response

    async def summary(prompt, system=None, keep_alive=None):
        summaries_during_requests.append(service.in_flight)
        await asyncio.sleep(0.01)
        return await summarize(prompt, system=system, keep_alive=keep_alive)

    monkeypatch.setattr(ollama_client, "generate_response", summary)
    first_update, first_context, first_chat = voice_update(voice=FakeVoice())
    second_update, second_context, second_chat = voice_update(voice=FakeVoice())
    brief_bot = FakeBot()

    async def all_at_once():
        return await asyncio.gather(
            voice.handle_voice_message(first_update, first_context),
            voice.handle_voice_message(second_update, second_context),
            voice.send_spoken_brief(brief_bot, ADMIN_ID, "📋 *BRIEF*\n• *Done:* `3`"),
        )

    asyncio.run(all_at_once())
    assert service.requests.count("/stt") == 2 and service.requests.count("/tts") == 3
    assert service.max_in_flight == 1
    assert summaries_during_requests == [0, 0, 0]
    assert len(first_context.bot.voices) == 1 and len(second_context.bot.voices) == 1
    assert len(brief_bot.voices) == 1
    for chat in (first_chat, second_chat):
        assert voice.UNAVAILABLE_NOTE not in chat.visible()


def test_a_voice_flow_that_never_gets_its_turn_gives_up(service, llm, verified_today, monkeypatch):
    monkeypatch.setattr(voice, "VOICE_TURN_WAIT", 0.05)
    update, context, chat = voice_update(voice=FakeVoice())
    brief_bot = FakeBot()

    async def while_the_service_is_held():
        async with voice._voice_turn():          # someone else's long turn
            await asyncio.gather(voice.handle_voice_message(update, context),
                                 voice.send_spoken_brief(brief_bot, ADMIN_ID, "brief"))

    asyncio.run(while_the_service_is_held())
    assert service.requests == [] and context.bot.voices == [] and brief_bot.voices == []
    assert len(chat.visible()) == 1 and "voice service is busy" in chat.visible()[0]


def test_voice_url_must_stay_on_this_pc(monkeypatch):
    monkeypatch.setattr(settings, "JENNIE_VOICE_URL", "http://192.168.1.20:8765")
    with pytest.raises(voice.VoiceServiceError):
        voice._service_url()
    with pytest.raises(voice.VoiceServiceError):
        asyncio.run(voice.transcribe(b"x"))
    for url in ("http://127.0.0.1:8765", "http://localhost:8765/", "http://[::1]:8765"):
        monkeypatch.setattr(settings, "JENNIE_VOICE_URL", url)
        assert voice._service_url() == url.rstrip("/")


# --------------------------------------------------------------------------- the daily brief

def _brief_setup(monkeypatch):
    async def get_dashboard():
        return {"summary": {}}

    async def empty_list(*args, **kwargs):
        return []

    async def report(**kwargs):
        return "📋 *HANGEUL DAILY OPERATIONAL BRIEF*\n• *Total Inquiries Received:* `5`\n• *Done:* `3` (60.0%)"

    monkeypatch.setattr(admin_client, "get_dashboard", get_dashboard)
    monkeypatch.setattr(admin_client, "get_applications", empty_list)
    monkeypatch.setattr(admin_client, "get_inquiries", empty_list)
    monkeypatch.setattr(ollama_client, "generate_executive_report", report)
    bot = FakeBot()
    return SimpleNamespace(bot=bot), bot


def test_spoken_brief_follows_the_text_brief(service, llm, monkeypatch):
    app, bot = _brief_setup(monkeypatch)
    llm.summary_en = "Good evening! We had 5 inquiries today and 3 are done."
    asyncio.run(scheduler.send_daily_briefing(app))
    assert len(bot.messages) == 1 and "DAILY OPERATIONAL BRIEF" in bot.messages[0]["text"]
    assert service.tts_payloads == [{"text": "Good evening! We had five inquiries today and three are done.",
                                     "language": "en", "style": "aegyo"}]
    assert len(service.tts_payloads[0]["text"]) <= voice.BRIEF_MAX_CHARS
    assert bot.voices == [{"chat_id": str(ADMIN_ID), "voice": OGG, "duration": 3, "filename": "jennie-brief.ogg"}]


def test_brief_voice_failure_is_isolated(service, llm, monkeypatch):
    app, bot = _brief_setup(monkeypatch)
    service.tts_failure = "refused"
    asyncio.run(scheduler.send_daily_briefing(app))              # must not raise
    assert len(bot.messages) == 1 and bot.voices == []

    # Even a bug inside the voice code cannot reach the text brief.
    async def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(voice, "send_spoken_brief", broken)
    app, bot = _brief_setup(monkeypatch)
    asyncio.run(scheduler.send_daily_briefing(app))
    assert len(bot.messages) == 1 and bot.voices == []


def test_brief_is_not_spoken_while_voice_is_off(service, llm, monkeypatch):
    app, bot = _brief_setup(monkeypatch)
    monkeypatch.setattr(settings, "JENNIE_VOICE_ENABLED", False)
    asyncio.run(scheduler.send_daily_briefing(app))
    assert len(bot.messages) == 1 and service.requests == [] and bot.voices == []

    monkeypatch.setattr(settings, "JENNIE_VOICE_ENABLED", True)
    monkeypatch.setattr(settings, "JENNIE_SPOKEN_BRIEF", False)
    app, bot = _brief_setup(monkeypatch)
    asyncio.run(scheduler.send_daily_briefing(app))
    assert len(bot.messages) == 1 and service.requests == []


# --------------------------------------------------------------------------- registration & helpers

@pytest.mark.parametrize("enabled", [False, True])
def test_voice_handler_registered_only_when_enabled(monkeypatch, enabled):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:TEST-TOKEN-NOT-REAL")
    monkeypatch.setattr(settings, "ENABLE_SCHEDULED_REPORTS", False)    # no scheduler in tests
    monkeypatch.setattr(settings, "JENNIE_VOICE_ENABLED", enabled)
    app = telegram_bot.build_telegram_application()
    handlers = [h for group in app.handlers.values() for h in group]
    voice_handlers = [h for h in handlers if getattr(h, "callback", None) is voice.handle_voice_message]
    assert len(voice_handlers) == (1 if enabled else 0)
    if enabled:
        assert voice_handlers[0].block is False


def test_ollama_keep_alive_is_optional(monkeypatch):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"response": "ok"})

    client = OllamaClient()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def reachable():
        return {"reachable": True}

    client.check_health = reachable
    assert asyncio.run(client.generate_response("hi")) == "ok"
    assert asyncio.run(client.generate_response("hi", keep_alive="30s")) == "ok"
    assert "keep_alive" not in sent[0]              # default behaviour unchanged
    assert sent[1]["keep_alive"] == "30s"


def test_text_is_made_speakable():
    en = voice._speech_text("✅ *12 inquiries* on 12 Sep 2026 at 6:05 PM, ৳ 1,250.50 BDT (41.7%)", "en", 400)
    assert en == ("twelve inquiries on the twelfth of September two thousand twenty-six at six oh five PM, "
                  "one thousand two hundred fifty point five zero taka (forty-one point seven percent)")
    ko = voice._speech_text("짜잔! 3명, 412번, 2026년 6월 12일, 20개, 3개월, 18:05", "ko", 400)
    assert ko == "짜잔! 세명, 사백십이번, 이천이십육년 유월 십이일, 스무개, 삼개월, 열여덟 시 오 분"
    long_text = "First sentence here. " * 40
    assert len(voice._speech_text(long_text, "en", 400)) <= 400
    assert voice._speech_text(long_text, "en", 400).endswith(".")
    assert voice.spoken_language("ja", "오늘 검증된 학생 몇 명이야?") == "ko"
    assert voice.spoken_language("en", "verified students today") == "en"
