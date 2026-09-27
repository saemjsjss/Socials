"""Tests for Jennie's voice (src/bot/voice.py) and its hooks in the bot and the scheduler.

Nothing here touches the network: the voice service is an httpx.MockTransport that follows the
API contract, the local LLM ("the brain") and the portal are stubs (the real clients are swapped
for ones that fail loudly), and the Telegram objects are small fakes. The bot is never started.
tests/test_voice_fast.py imports the fakes and fixtures below.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_voice.py -q
"""
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

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
COLLEAGUE_ID = 222222222
STRANGER_ID = 999999999
OGG = b"OggS" + b"\x00" * 64
NOW = datetime(2026, 9, 28, 10, 30, tzinfo=ZoneInfo("Asia/Dhaka"))     # a Monday


def filler_audio(name):
    return b"OggS-filler-" + name.encode()


# --------------------------------------------------------------------------- fakes

class FakeChat:
    """Everything the bot shows in one chat, in order."""

    def __init__(self, chat_id):
        self.id = chat_id
        self.log = []
        self.events = []        # ("text", text) and ("voice", bytes or file id), in the order sent

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
        self.chat.events.append(("text", text))
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
        self.file_ids = False       # True: send_voice answers like Telegram, with the file's id

    async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
        self.messages.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
        return FakeMessage(self.chat or FakeChat(chat_id), text=text)

    async def send_voice(self, chat_id, voice, duration=None, filename=None, **kwargs):
        self.voices.append({"chat_id": chat_id, "voice": voice, "duration": duration, "filename": filename})
        if self.chat is not None:
            self.chat.events.append(("voice", voice))
        if self.file_ids:
            file_id = voice if isinstance(voice, str) else f"file-{len(self.voices)}"
            return SimpleNamespace(voice=SimpleNamespace(file_id=file_id))
        return None

    async def send_chat_action(self, chat_id, action, **kwargs):
        self.actions.append(action)

    def replies(self):
        """The spoken answers (not the filler clips)."""
        return [v for v in self.voices if v["voice"] == OGG]

    def fillers(self):
        return [v for v in self.voices if v["voice"] != OGG]


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
        self.tts_seconds = 3.4      # X-Duration of every rendered clip
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
            return httpx.Response(200, content=OGG, headers={"Content-Type": "audio/ogg",
                                                             "X-Duration": str(self.tts_seconds), "X-Seconds": "1.1"})
        return httpx.Response(404, json={"error": "not found"})


ROUTE_TODAY = {"command": "verified_today", "date": None,
               "english_query": "How many students were verified today?", "language": "en"}


class FakeLLM:
    """Stands in for ollama_client.chat, the brain behind every voice call: the routing call
    (a JSON schema in `format`), the spoken reply and the spoken brief."""

    def __init__(self):
        self.calls = []
        self.down = False
        self.routes = {}                # utterance -> the JSON answer (dict, or a raw string)
        self.route_default = ROUTE_TODAY
        self.reply_ko = "짜잔! 오늘 검증된 학생은 2명이에용!"
        self.reply_en = "Good news! 2 students were verified today."
        self.chat_ko = "헤헤, 고마워용~ 💖"
        self.chat_en = "Aww, thank you, hehe! 😊"
        self.brief = "Good evening! We had 5 inquiries today and 3 are done."

    @staticmethod
    def utterance(messages):
        return messages[-1]["content"].rsplit("NEW utterance: ", 1)[-1]

    async def chat(self, messages, format=None, num_predict=None, timeout=None):
        system, user = messages[0]["content"], messages[-1]["content"]
        kind = "route" if format is not None else ("brief" if "evening update" in system else "reply")
        self.calls.append({"kind": kind, "system": system, "user": user, "format": format,
                           "num_predict": num_predict})
        if self.down:
            return None
        if kind == "route":
            answer = self.routes.get(self.utterance(messages), self.route_default)
            return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        if kind == "brief":
            return self.brief
        small_talk = "(none, this is small talk)" in user
        if "KOREAN" in system:
            return self.chat_ko if small_talk else self.reply_ko
        return self.chat_en if small_talk else self.reply_en

    def kinds(self):
        return [c["kind"] for c in self.calls]


def _refuse(request):
    raise AssertionError(f"tests must not reach the network: {request.method} {request.url.host}")


# --------------------------------------------------------------------------- fixtures

@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """Known settings, no way out to the portal, Ollama or Telegram, a fixed 'now' in Dhaka,
    ready filler clips in a temporary folder, and no memory of earlier tests' chats."""
    monkeypatch.setattr(settings, "TELEGRAM_ADMIN_CHAT_ID", str(ADMIN_ID))
    monkeypatch.setattr(settings, "TELEGRAM_AUTHORIZED_CHAT_IDS", str(COLLEAGUE_ID))
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
    monkeypatch.setattr(voice, "_now", lambda: NOW)

    folder = tmp_path / "jennie_fillers"
    folder.mkdir()
    manifest = {}
    for language, name, line in voice._filler_wanted():
        (folder / name).write_bytes(filler_audio(name))
        manifest[name] = {"line": line, "duration": 1.8}
    (folder / "fillers.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(voice, "FILLER_DIR", folder)
    monkeypatch.setattr(voice, "_filler_clips", {})
    monkeypatch.setattr(voice, "_filler_job", None)
    monkeypatch.setattr(voice, "_history", {})
    return folder


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(ollama_client, "chat", fake.chat)
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
    assert chat.log == [] and context.bot.voices == []      # not even a filler clip

    # The same refusal a typed question from that chat gets: silence.
    text_update, text_context, text_chat = voice_update(chat_id=STRANGER_ID, text="verified students today")
    asyncio.run(telegram_bot.handle_natural_language_message(text_update, text_context))
    assert text_chat.log == []


def test_korean_voice_is_routed_answered_and_spoken(service, llm, verified_today, caplog):
    caplog.set_level(logging.INFO, logger="hangeul.voice")
    service.text, service.language = "오늘 검증된 학생 몇 명이야?", "ko"
    llm.route_default = {**ROUTE_TODAY, "language": "ko"}
    update, context, chat = voice_update(voice=FakeVoice(data=b"korean-opus"))
    asyncio.run(voice.handle_voice_message(update, context))

    # One line of timings per note, with the facts about the note, never what was said.
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Voice note from")]
    assert len(lines) == 1
    for stage in ("filler +", "download ", "stt ", "route ", "command ", "reply ", "tts ", "voice sent ", "total "):
        assert stage in lines[0]
    assert "verified_today" in lines[0]
    assert "검증" not in caplog.text and "were verified" not in caplog.text

    # All three: what was heard, the full text answer (as typed), and Jennie's voice.
    shown = chat.visible()
    assert shown[0] == "🎧 heard: 오늘 검증된 학생 몇 명이야?"
    assert len(verified_today) == 1                              # /verified_today ran directly
    assert any("Student Payment Verifications" in t and "DEB BIKASH CHANDRA" in t for t in shown)
    assert not any(t.startswith("⏳") for t in shown)
    assert voice.UNAVAILABLE_NOTE not in shown

    # Two brain calls: one routing call, one short reply that saw the captured answer.
    assert llm.kinds() == ["route", "reply"]
    routing, reply = llm.calls
    assert "NEW utterance: 오늘 검증된 학생 몇 명이야?" in routing["user"]
    assert routing["format"]["properties"]["command"]["enum"] == list(voice.ROUTE_COMMANDS)
    assert "KOREAN" in reply["system"] and "Student Payment Verifications" in reply["user"]

    assert service.uploads and b"korean-opus" in service.uploads[0]
    assert service.tts_payloads == [{"text": "짜잔! 오늘 검증된 학생은 두명이에용!",
                                     "language": "ko", "style": "aegyo"}]
    assert context.bot.replies() == [{"chat_id": ADMIN_ID, "voice": OGG, "duration": 3, "filename": "jennie.ogg"}]
    # The Korean filler went out first of all, before "heard".
    assert chat.events[0][0] == "voice" and chat.events[0][1].startswith(b"OggS-filler-ko_")


def test_english_voice_is_routed_answered_and_spoken(service, llm, verified_today):
    update, context, chat = voice_update(voice=FakeVoice())
    asyncio.run(voice.handle_voice_message(update, context))

    assert chat.visible()[0] == "🎧 heard: How many verified students today?"
    assert llm.kinds() == ["route", "reply"]                    # no separate rewrite any more
    assert "KOREAN" not in llm.calls[1]["system"]
    assert b'name="audio"; filename="voice.ogg"' in service.uploads[0]
    assert service.tts_payloads == [{"text": "Good news! two students were verified today.",
                                     "language": "en", "style": "aegyo"}]
    assert context.bot.replies()[0]["chat_id"] == ADMIN_ID


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
    assert context.bot.replies() == []


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
    assert service.requests == ["/stt"] and llm.calls == [] and context.bot.replies() == []


def test_voice_service_error_replies_are_classified():
    """The contract's JSON errors: 503 means busy, anything else means unavailable."""
    busy = voice._service_error(httpx.Response(503, json={"error": "busy"}), "speech-to-text")
    broken = voice._service_error(httpx.Response(500, json={"error": "RuntimeError"}), "speech-to-text")
    plain = voice._service_error(httpx.Response(502, content=b"Bad Gateway"), "speech")
    assert isinstance(busy, voice.VoiceServiceBusy) and str(busy) == "speech-to-text HTTP 503: busy"
    assert type(broken) is voice.VoiceServiceError and str(broken) == "speech-to-text HTTP 500: RuntimeError"
    assert type(plain) is voice.VoiceServiceError and str(plain) == "speech HTTP 502: Bad Gateway"


def test_brain_down_still_answers_through_the_typed_routing(service, llm, verified_today):
    llm.down = True
    update, context, chat = voice_update(voice=FakeVoice())
    asyncio.run(voice.handle_voice_message(update, context))

    # The typed-question routing took the words as heard, and the report is in the chat.
    assert len(verified_today) == 1
    assert any("Student Payment Verifications" in t for t in chat.visible())
    # Jennie still speaks: a short honest line instead of the brain's summary.
    spoken = service.tts_payloads[0]["text"]
    assert spoken == voice._FALLBACK[("en", True)]
    assert len(context.bot.replies()) == 1


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
    assert context.bot.voices == []                             # no filler either


def test_sendmail_typed_during_the_routing_does_not_get_the_voice_query(service, llm, monkeypatch):
    """Voice notes run with block=False: /sendmail can be typed while a note is being routed."""
    email_steps = []

    async def handle_email_flow(update, context, text):
        email_steps.append(text)

    monkeypatch.setattr(telegram_bot, "_handle_email_flow", handle_email_flow)
    service.text, service.language = "오늘 검증된 학생 몇 명이야?", "ko"
    update, context, chat = voice_update(voice=FakeVoice())
    brain = llm.chat

    async def route_while_sendmail_is_typed(messages, **kwargs):
        context.user_data["email_flow"] = {"step": "subject", "student_id": "412"}
        return await brain(messages, **kwargs)

    monkeypatch.setattr(ollama_client, "chat", route_while_sendmail_is_typed)
    asyncio.run(voice.handle_voice_message(update, context))

    assert email_steps == []                                     # the query never became the subject
    assert context.user_data["email_flow"] == {"step": "subject", "student_id": "412"}
    assert chat.visible()[-1] == voice.EMAIL_FLOW_NOTE
    assert llm.kinds() == ["route"] and service.tts_payloads == []


def test_too_long_recording_is_not_downloaded(service, llm):
    # A note is never longer than the time /stt gets: the CPU fallback runs faster than real time.
    assert voice.MAX_VOICE_SECONDS <= voice.STT_TIMEOUT
    update, context, chat = voice_update(voice=FakeVoice(duration=voice.MAX_VOICE_SECONDS + 1))
    asyncio.run(voice.handle_voice_message(update, context))
    assert service.requests == [] and "too long" in chat.visible()[0]
    assert f"under {voice.MAX_VOICE_SECONDS} seconds" in chat.visible()[0]
    assert context.bot.voices == []


def test_voice_flows_take_turns_at_the_voice_service(service, llm, verified_today):
    """Two voice notes and the spoken brief at once: one voice-service request at a time."""
    service.delay = 0.02
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
    assert len(first_context.bot.replies()) == 1 and len(second_context.bot.replies()) == 1
    assert len(first_context.bot.fillers()) == 1 and len(second_context.bot.fillers()) == 1
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
    assert service.requests == [] and context.bot.replies() == [] and brief_bot.voices == []
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
    asyncio.run(scheduler.send_daily_briefing(app))
    assert len(bot.messages) == 1 and "DAILY OPERATIONAL BRIEF" in bot.messages[0]["text"]
    assert llm.kinds() == ["brief"] and "Total Inquiries Received: 5" in llm.calls[0]["user"]
    assert service.tts_payloads == [{"text": "Good evening! We had five inquiries today and three are done.",
                                     "language": "en", "style": "aegyo"}]
    assert len(service.tts_payloads[0]["text"]) <= voice.BRIEF_MAX_CHARS
    assert bot.voices == [{"chat_id": str(ADMIN_ID), "voice": OGG, "duration": 3, "filename": "jennie-brief.ogg"}]


def test_spoken_brief_is_short(service, llm, monkeypatch):
    """One or two short sentences: a long answer is cut at a sentence end within BRIEF_MAX_CHARS."""
    app, bot = _brief_setup(monkeypatch)
    llm.brief = "Good evening! We had 5 inquiries today. " + "And 3 are done, yay! " * 20
    asyncio.run(scheduler.send_daily_briefing(app))
    spoken = service.tts_payloads[0]["text"]
    assert len(spoken) <= voice.BRIEF_MAX_CHARS and spoken.endswith("!")


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
