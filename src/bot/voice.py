"""Jennie's voice: Telegram voice notes in, text + voice notes out, fast and conversational.

A voice note from an authorised user gets, at once and without waiting for anything, a short
pre-rendered filler clip ("잠깐만용~ 확인해볼게요!") in the language of that chat's last turn.
Meanwhile the note goes to the local voice service (JENNIE_VOICE_URL, 127.0.0.1:8765) for
speech-to-text and the bot replies "🎧 heard: ...". ONE call to the local LLM ("Jennie's brain",
settings.OLLAMA_MODEL, resident in VRAM) routes the words, with the chat's last turns, to one of
the bot's own commands (so "그럼 어제는?" after a question about today asks about yesterday); the
command runs exactly as when it is typed, so the full text answer appears as usual, and what it
leaves in the chat is captured. A second short LLM call turns that into ONE short sentence in the
language spoken (cute 애교 Jennie in Korean and in English), and the voice service renders it with
CosyVoice2 as an OGG/Opus voice note. Small talk ("chat") runs no command: Jennie just answers.
Anything the router cannot place goes through the typed-question routing
(telegram_bot.handle_natural_language_message) with the router's English wording.

Everything stays on this PC. If the voice service is down or slow, the text answers still
arrive and one short note says the voice reply is unavailable; nothing here ever raises out
of the handler. The bot sends the voice service one request at a time (_voice_turn), so a
timeout only ever counts the bot's own request. One INFO line per note records how long each
stage took (metadata only: never what was said).

Voice service contract (127.0.0.1 only):
  POST /stt  multipart "audio"                      -> {"text", "language", "duration_s", "seconds"}
  POST /tts  {"text", "language": "en"|"ko", "style": "aegyo"|"neutral"}
             -> OGG/Opus body, headers X-Duration / X-Seconds (text over 600 chars -> 413)
"""
import asyncio
import json
import logging
import os
import random
import re
import time
import warnings
from collections import deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Callable, Optional, Tuple
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.config import BOT_ROOT, settings
from src.llm.ollama_client import ollama_client

logger = logging.getLogger("hangeul.voice")

STT_TIMEOUT = 60.0              # seconds allowed for /stt
TTS_TIMEOUT = 120.0             # seconds allowed for /tts (the service queues one request at a time)
TTS_MAX_CHARS = 600             # the voice service refuses longer text (413)
# The spoken answer to a voice note is ONE short sentence: every character is ~0.19 s (Korean) or
# ~0.075 s (English) of speech the GPU has to render before the note can be sent. VRAM is tight:
# measured on 28 Sep 2026 with nvidia-smi and the Windows GPU memory counters, the resident brain
# (qwen3:4b-instruct, num_ctx 3072: 2.82 GiB) plus the desktop and the idle voice service use
# ~4.6-4.8 of the card's 7.96 GiB, and a render peaks at 3.55-3.67 GiB torch reserved for 11-42
# Korean characters (4.1 GiB when a render rambles and runs twice). That is right at the edge: in
# some runs the card spilled into shared memory and Korean renders slowed 2-7x (11 chars 10.5 s,
# 27 chars 99 s) while other runs of the same lines took 3.8-5.2 s. A short line keeps each render
# (and the time it can spend paging) short, and it is what a conversation wants.
REPLY_MAX_CHARS = {"ko": 32, "en": 120}         # hard limit after clean-up
REPLY_TARGET_CHARS = {"ko": 22, "en": 90}       # what the prompt asks for
# Spoken daily brief: one or two short sentences. Short enough (~12 s of speech) that even a CPU
# render, when the GPU is busy, finishes inside the voice service's 100 s limit.
BRIEF_MAX_CHARS = 160
ANSWER_MAX_CHARS = 2000         # how much of the written answer the reply prompt sees
# Longer recordings are not transcribed. Kept within STT_TIMEOUT: when the GPU is busy the voice
# service transcribes on the CPU, which runs just under real time, so a longer note would time out.
MAX_VOICE_SECONDS = 60
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024   # Telegram's own limit for bot downloads
VOICE_TURN_WAIT = 240.0         # seconds a voice flow waits for its turn at the voice service
LLM_TIMEOUT = 30.0              # seconds for one brain call (a cold load is ~3 s, a warm call ~0.4 s)
ROUTE_MAX_TOKENS = 160
REPLY_MAX_TOKENS = 120
HISTORY_TURNS = 6               # turns kept per chat (in memory only)
PROMPT_TURNS = 3                # of those, how many the brain sees

UNAVAILABLE_NOTE = "🔇 Voice reply unavailable right now — the answer is in the text above."
EMAIL_FLOW_NOTE = ("✉️ An email is waiting for your answer — please type it (SEND / EDIT / DENY or the detail "
                   "I asked for). I don't handle emails from voice notes.")

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class VoiceServiceError(Exception):
    """The local voice service could not be reached, or refused the request."""


class VoiceServiceBusy(VoiceServiceError):
    """The voice service is there but busy: it timed out, answered 503, or our turn never came."""


# --------------------------------------------------------------------------- one request at a time

_turn = None    # (event loop, asyncio.Lock), created lazily on the bot's loop


@asynccontextmanager
async def _voice_turn():
    """The bot's own turn at the voice service. Voice flows (voice notes, which run concurrently
    with block=False, the spoken brief and the filler renders) take turns, so the bot never has
    two requests in flight: each request's timeout counts only its own work."""
    global _turn
    loop = asyncio.get_running_loop()
    if _turn is None or _turn[0] is not loop:
        _turn = (loop, asyncio.Lock())
    lock = _turn[1]
    try:
        async with asyncio.timeout(VOICE_TURN_WAIT):
            await lock.acquire()
    except TimeoutError as e:
        raise VoiceServiceBusy(f"no turn at the voice service within {VOICE_TURN_WAIT:.0f} s") from e
    try:
        yield
    finally:
        lock.release()


# --------------------------------------------------------------------------- voice service

def _service_url() -> str:
    """JENNIE_VOICE_URL, refused unless it points at this PC (everything stays offline)."""
    url = str(settings.JENNIE_VOICE_URL or "").strip().rstrip("/")
    host = urlsplit(url).hostname
    if host not in _LOCAL_HOSTS:
        raise VoiceServiceError(f"JENNIE_VOICE_URL must point at this PC (127.0.0.1), not {host!r}")
    return url


def _http(timeout: float) -> httpx.AsyncClient:
    """A client for the local voice service only, never routed through a proxy."""
    return httpx.AsyncClient(base_url=_service_url(), timeout=httpx.Timeout(timeout, connect=5.0),
                             trust_env=False)


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _service_error(resp: httpx.Response, what: str) -> VoiceServiceError:
    try:
        detail = str(resp.json().get("error") or "")
    except Exception:
        detail = resp.text[:200]
    error = VoiceServiceBusy if resp.status_code == 503 else VoiceServiceError
    return error(f"{what} HTTP {resp.status_code}: {detail}".strip())


def _request_error(e: httpx.HTTPError, what: str, timeout: float) -> VoiceServiceError:
    """A failed request: busy when the service took too long, unreachable otherwise."""
    if isinstance(e, httpx.TimeoutException) and not isinstance(e, httpx.ConnectTimeout):
        return VoiceServiceBusy(f"{what} took longer than {timeout:.0f} s")
    return VoiceServiceError(f"{what} unreachable: {type(e).__name__}: {e}")


async def transcribe(audio: bytes, filename: str = "voice.ogg", mime_type: str = "audio/ogg") -> dict:
    """Speech-to-text on the voice service -> {"text", "language", "duration_s", "seconds"}."""
    try:
        async with _http(STT_TIMEOUT) as client:
            resp = await client.post("/stt", files={"audio": (filename, audio, mime_type)})
    except httpx.HTTPError as e:
        raise _request_error(e, "speech-to-text", STT_TIMEOUT) from e
    if resp.status_code != 200:
        raise _service_error(resp, "speech-to-text")
    try:
        data = resp.json()
    except ValueError as e:
        raise VoiceServiceError("speech-to-text answered without JSON") from e
    if not isinstance(data, dict):
        raise VoiceServiceError("speech-to-text answered with unexpected JSON")
    return {
        "text": str(data.get("text") or "").strip(),
        "language": str(data.get("language") or "").strip().lower(),
        "duration_s": _number(data.get("duration_s")),
        "seconds": _number(data.get("seconds")),
    }


async def synthesize(text: str, language: str, style: str) -> Tuple[bytes, float]:
    """Text-to-speech on the voice service -> (OGG/Opus bytes, duration in seconds)."""
    payload = {"text": _fit(text, TTS_MAX_CHARS), "language": language, "style": style}
    try:
        async with _http(TTS_TIMEOUT) as client:
            resp = await client.post("/tts", json=payload)
    except httpx.HTTPError as e:
        raise _request_error(e, "speech", TTS_TIMEOUT) from e
    if resp.status_code != 200:
        raise _service_error(resp, "speech")
    audio = resp.content
    if not audio.startswith(b"OggS"):
        raise VoiceServiceError("speech answered without OGG audio")
    return audio, _number(resp.headers.get("X-Duration"))


# --------------------------------------------------------------------------- filler clips

# Sent the moment a voice note arrives, so Jennie answers at once while the real answer is made.
# Rendered once through /tts into FILLER_DIR/<lang>_<n>.ogg; fillers.json remembers each clip's
# line, so a changed line is rendered again. The voice engine sometimes drags a short Korean line
# out (its seeds are fixed, so the same line always comes out the same): these lines were picked
# because they render in 1.4-2.8 s, and a clip longer than FILLER_MAX_SECONDS is never sent.
FILLER_DIR = BOT_ROOT / "data" / "jennie_fillers"
FILLER_LINES = {
    "ko": ("잠시만용~ 찾아볼게요!", "음~ 찾아볼게용!", "금방 알려드릴게용~"),
    "en": ("Ooh, one sec~ let me check!", "Hehe, checking now!", "Okie, give me a moment~"),
}
FILLER_MAX_SECONDS = 3.5
_FILLER_MANIFEST = "fillers.json"
_filler_clips = {}      # file name -> {"line", "audio", "duration", "file_id"} (file_id: Telegram's copy)
_filler_job = None      # the background task rendering missing clips


def _filler_manifest() -> dict:
    try:
        data = json.loads((FILLER_DIR / _FILLER_MANIFEST).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _filler_wanted():
    for language, lines in FILLER_LINES.items():
        for n, line in enumerate(lines, 1):
            yield language, f"{language}_{n}.ogg", line


def missing_fillers() -> list:
    """(language, file name, line) of every clip not rendered yet, or rendered for another line."""
    manifest = _filler_manifest()
    return [(language, name, line) for language, name, line in _filler_wanted()
            if (manifest.get(name) or {}).get("line") != line or not (FILLER_DIR / name).is_file()]


def _write_atomic(path, data: bytes):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


async def prepare_fillers() -> int:
    """Render the missing filler clips through /tts, one voice-service turn each (so a voice note
    waits at most one short render). Never raises: while the voice service is down there are
    simply no fillers. -> how many clips were rendered."""
    missing = missing_fillers()
    if not missing:
        return 0
    done = 0
    try:
        FILLER_DIR.mkdir(parents=True, exist_ok=True)
        for language, name, line in missing:
            async with _voice_turn():
                audio, seconds = await synthesize(line, language, "aegyo")
            _write_atomic(FILLER_DIR / name, audio)
            if seconds > FILLER_MAX_SECONDS:
                logger.warning(f"Filler clip {name} came out {seconds:.1f} s long; it is not used "
                               f"(pick another line for it).")
            manifest = _filler_manifest()
            manifest[name] = {"line": line, "duration": round(seconds, 2)}
            _write_atomic(FILLER_DIR / _FILLER_MANIFEST,
                          json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
            _filler_clips.pop(name, None)
            done += 1
    except Exception as e:
        logger.info(f"Filler clips not ready yet ({type(e).__name__}: {e}); voice notes go without them.")
    if done:
        logger.info(f"Rendered {done} filler clip(s) into {FILLER_DIR}.")
    return done


def _prepare_fillers_later():
    """After a voice note: render missing clips in the background (never during a note's own turns)."""
    global _filler_job
    if (_filler_job is None or _filler_job.done()) and missing_fillers():
        _filler_job = _background(prepare_fillers())


def _pick_filler(language: str) -> Optional[dict]:
    """A random ready clip in `language`, or None when there is none."""
    manifest = None
    clips = []
    for lang, name, line in _filler_wanted():
        if lang != language:
            continue
        clip = _filler_clips.get(name)
        if clip is None or clip["line"] != line:
            if manifest is None:
                manifest = _filler_manifest()
            entry = manifest.get(name) or {}
            if entry.get("line") != line or _number(entry.get("duration")) > FILLER_MAX_SECONDS:
                continue
            try:
                audio = (FILLER_DIR / name).read_bytes()
            except OSError:
                continue
            if not audio.startswith(b"OggS"):
                continue
            clip = _filler_clips[name] = {"line": line, "audio": audio,
                                          "duration": _number(entry.get("duration")), "file_id": None}
        clips.append(clip)
    return random.choice(clips) if clips else None


async def _send_filler(bot, chat_id, language: str, timings: "_Timings"):
    """Send a filler clip; never raises, never waited for by the rest of the note."""
    clip = _pick_filler(language)
    if clip is None:
        return
    for source in ("file_id", "audio"):
        voice = clip.get(source)
        if not voice:
            continue
        try:
            sent = await bot.send_voice(chat_id=chat_id, voice=voice, duration=_voice_duration(clip["duration"]),
                                        filename="jennie.ogg", write_timeout=30)
        except Exception as e:
            logger.warning(f"Filler clip not sent ({source}): {type(e).__name__}: {e}")
            clip["file_id"] = None
            continue
        file_id = getattr(getattr(sent, "voice", None), "file_id", None)
        if file_id:
            clip["file_id"] = file_id      # Telegram keeps a copy: the next send uploads nothing
        timings.filler = timings.elapsed()
        return


# --------------------------------------------------------------------------- memory of each chat

_history = {}   # chat id -> deque of turns: {"user", "language", "command", "date", "jennie"}


def _turns(chat_id) -> deque:
    return _history.setdefault(chat_id, deque(maxlen=HISTORY_TURNS))


def _remember(chat_id, user: str, language: str, command: str, day, jennie: str):
    """One turn. `day`: the date the command ran for, a (first, last) range, or None."""
    if isinstance(day, tuple):
        day = f"{day[0].isoformat()} to {day[1].isoformat()}"
    elif isinstance(day, date):
        day = day.isoformat()
    _turns(chat_id).append({"user": user, "language": language, "command": command,
                            "date": day or None, "jennie": jennie})


def last_language(chat_id) -> str:
    """The language of the chat's last voice turn: Korean until someone has spoken."""
    turns = _history.get(chat_id)
    return turns[-1]["language"] if turns else "ko"


def _history_text(turns, commands: bool) -> str:
    lines = []
    for turn in list(turns)[-PROMPT_TURNS:]:
        lines.append(f"User: {turn['user']}")
        if commands and turn.get("command"):
            what = turn["command"] + (f" {turn['date']}" if turn.get("date") else "")
            lines.append(f"Jennie ({what}): {turn['jennie']}")
        else:
            lines.append(f"Jennie: {turn['jennie']}")
    return "\n".join(lines) or "(none)"


# --------------------------------------------------------------------------- Jennie's brain

def _now() -> datetime:
    """Now in Dhaka (REPORT_TIMEZONE): 'today' for every date the brain resolves."""
    try:
        return datetime.now(ZoneInfo(settings.REPORT_TIMEZONE))
    except Exception:
        return datetime.now()


ROUTE_COMMANDS = ("verified_today", "verified_date", "inquiries_today", "inquiries_date", "calendar",
                  "passports", "stats", "missing_report", "crosscheck", "chat")

# The routing prompt proven in C:\Hangeul\JARVIS\brain-trial\trial.py (12/12 commands, dates and
# valid JSON with qwen3:4b-instruct, ~0.35 s warm).
_ROUTER_SYSTEM = (
    "You are the command router for Jennie, the voice assistant of the Telegram bot of Hangeul "
    "Korean Language & Visa, a study-in-Korea agency in Dhaka. Office staff talk to Jennie in "
    "Korean or English. The text comes from speech recognition, which sometimes mishears a word, "
    "so go by the overall meaning. Choose exactly ONE command for the NEW utterance.\n\n"
    "Commands:\n"
    "- verified_today: students whose payment/documents were verified today (검증된 학생)\n"
    "- verified_date: verified students on one specific date other than today\n"
    "- inquiries_today: consultancy inquiries / consultations handled today (상담, 문의)\n"
    "- inquiries_date: consultancy inquiries on one specific date other than today\n"
    "- calendar: upcoming schedule, deadlines and intakes (일정, 마감)\n"
    "- passports: passport audit, students whose passport data is wrong or missing (여권)\n"
    "- stats: overall statistics and totals (전체 통계)\n"
    "- missing_report: students with missing documents or missing data\n"
    "- crosscheck: cross-check payments against records for a date or a student\n"
    "- chat: greetings, thanks, praise, small talk, or anything that is not a data request\n\n"
    "Today is <TODAY>. The seven days before it were: <DAYS>. "
    "Resolve relative dates such as 어제 / yesterday against today. "
    "A short follow-up such as 'and yesterday?' keeps the topic of the previous request and "
    "changes only the date.\n"
    "Answer with JSON only: {\"command\": one of the commands, \"date\": \"YYYY-MM-DD\" or null, "
    "\"english_query\": the request as one short English sentence, \"language\": \"ko\" if the new "
    "utterance is Korean, otherwise \"en\"}. The date is null unless the command is verified_date, "
    "inquiries_date or crosscheck with a spoken date."
)

_ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "enum": list(ROUTE_COMMANDS)},
        "date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "english_query": {"type": "string"},
        "language": {"type": "string", "enum": ["ko", "en"]},
    },
    "required": ["command", "date", "english_query", "language"],
}

ROUTE_HISTORY_COMMANDS = True   # the history lines show which command answered each turn


def _iso_day(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value).strip()[:10]) if value else None
    except ValueError:
        return None


_KO_WEEKDAYS = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")
_EN_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DATED_COMMANDS = ("verified_today", "verified_date", "inquiries_today", "inquiries_date", "crosscheck")

_MONTH_WORD = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
               r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b\.?")
# A calendar date in the words (25일, 9월 1일, 이십오일, 구월, September 20, 20th, 2026-09-25, 25/9). The brain
# reads those itself, so a relative word next to one ("오늘 말고 25일") must not replace its date.
_CALENDAR_RE = re.compile(
    r"\d{1,2}\s*[월일](?!요일)|[일이삼사오육유칠팔구시십]+[월일](?!요)"
    rf"|\b{_MONTH_WORD}\s+\d|\d(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH_WORD}"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b|\d{4}-\d{1,2}-\d{1,2}|\b\d{1,2}/\d{1,2}\b",
    re.I)


def _mon(word: str) -> int:
    return ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec").index(
        word[:3].lower()) + 1


# Every date the English query names, in order: 2026-09-01, 1 Sep (2026), September 1(st) (2026), 9월 1일,
# 25일, today, yesterday, the day before yesterday. (normalize_date_input reads only one date, in
# English, so the voice path finds its dates here.)
_QUERY_DAY_RE = re.compile(
    r"(?<!\d)(?P<iy>\d{4})-(?P<im>\d{1,2})-(?P<id>\d{1,2})(?!\d)"
    rf"|(?<![\d:])(?P<dd>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<dm>{_MONTH_WORD})(?:,?\s+(?P<dy>\d{{4}}))?"
    rf"|\b(?P<mm>{_MONTH_WORD})\s+(?P<md>\d{{1,2}})(?:st|nd|rd|th)?(?![\d:])(?:,?\s+(?P<my>\d{{4}}))?"
    r"|(?:(?P<km>\d{1,2})\s*월\s*)?(?P<kd>\d{1,2})\s*일(?!요일)"
    r"|(?P<dby>\bday before yesterday\b|그저께|그제)|(?P<yday>\byesterday\b|어제)|(?P<tday>\btoday\b|오늘)",
    re.I)
_RANGE_WORD_RE = re.compile(r"\b(?:to|until|till|through|thru|between)\b|[~–—]|부터|까지", re.I)


def _query_days(text: str, today: date) -> list:
    """The dates named in `text`, in order (see _QUERY_DAY_RE). A date without a year is this year's;
    a bare Korean day (25일) is this month's, or last month's when that day is still to come."""
    days = []
    for m in _QUERY_DAY_RE.finditer(text or ""):
        g = m.groupdict()
        try:
            if g["iy"]:
                day = date(int(g["iy"]), int(g["im"]), int(g["id"]))
            elif g["dd"]:
                day = date(int(g["dy"] or today.year), _mon(g["dm"]), int(g["dd"]))
            elif g["mm"]:
                day = date(int(g["my"] or today.year), _mon(g["mm"]), int(g["md"]))
            elif g["kd"]:
                if g["km"]:
                    day = date(today.year, int(g["km"]), int(g["kd"]))
                else:
                    day = date(today.year, today.month, int(g["kd"]))
                    if day > today:
                        last = today.replace(day=1) - timedelta(days=1)
                        day = date(last.year, last.month, int(g["kd"]))
            else:
                day = today - timedelta(days=2 if g["dby"] else 1 if g["yday"] else 0)
        except ValueError:
            continue    # 30 Feb and the like
        days.append(day)
    return days


def _one_day(text: str, today: date) -> Optional[date]:
    """The one date the words name; None when they name none, or several different ones."""
    days = set(_query_days(text, today))
    return days.pop() if len(days) == 1 else None


def _span(text: str, today: date, need_range_word: bool = True) -> Optional[Tuple[date, date]]:
    """(first, last) when the words name a range: two different dates and a range word between them
    ("from 1 Sep to today", "9월 1일부터 15일까지"). A lone "to" is not a range: "Cross-check payments to
    records on 25 Sep" names one date."""
    days = _query_days(text, today)
    if len(set(days)) < 2 or (need_range_word and not _RANGE_WORD_RE.search(text or "")):
        return None
    return min(days), max(days)


def _relative_day(text: str, today: date) -> Optional[date]:
    """_spoken_day, but only when the words name no calendar date (the brain reads those)."""
    return None if _CALENDAR_RE.search(text or "") else _spoken_day(text, today)


def _spoken_day(text: str, today: date) -> Optional[date]:
    """The day a relative expression in the words means (오늘, 어제, 그저께, yesterday, (last) Friday,
    지난 금요일 ...), when they name exactly one; None otherwise. The brain reads calendar dates
    well but miscounts weekdays now and then, so these are worked out here."""
    low = (text or "").lower()
    found = set()
    if re.search(r"그저께|그제|day before yesterday", low):
        found.add(2)
    elif re.search(r"어제|yesterday", low):
        found.add(1)
    if re.search(r"오늘|\btoday\b", low):
        found.add(0)
    for weekday, (ko, en) in enumerate(zip(_KO_WEEKDAYS, _EN_WEEKDAYS)):
        if ko in low or re.search(rf"\b{en}\b", low):
            found.add((today.weekday() - weekday) % 7 or 7)     # the last one before today
    return today - timedelta(days=found.pop()) if len(found) == 1 else None


async def route(heard: str, turns=()) -> Optional[dict]:
    """ONE brain call: the words heard (and the chat's last turns) -> {"command", "date"
    (a date or None), "english_query"}. None when the brain is down or answered nonsense."""
    now = _now()
    days = ", ".join(f"{d:%A} {d:%Y-%m-%d}" for d in (now - timedelta(days=n) for n in range(1, 8)))
    system = _ROUTER_SYSTEM.replace("<TODAY>", f"{now:%A} {now:%Y-%m-%d}").replace("<DAYS>", days)
    user = f"Conversation so far:\n{_history_text(turns, ROUTE_HISTORY_COMMANDS)}\n\nNEW utterance: {heard}"
    raw = await ollama_client.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                   format=_ROUTER_SCHEMA, num_predict=ROUTE_MAX_TOKENS, timeout=LLM_TIMEOUT)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        found = re.search(r"\{.*\}", raw, re.S)
        try:
            data = json.loads(found.group(0)) if found else None
        except ValueError:
            data = None
    if not isinstance(data, dict) or data.get("command") not in ROUTE_COMMANDS:
        return None
    query = re.sub(r"\s+", " ", _plain(str(data.get("english_query") or ""))).strip()[:200]
    day = _iso_day(data.get("date"))
    if data["command"] in _DATED_COMMANDS:
        day = _relative_day(heard, now.date()) or day
    return {"command": data["command"], "date": day, "english_query": query}


def _portal_day(day: date) -> str:
    """A date as the bot's own commands read it (normalize_date_input): '26 Sep 2026'."""
    return day.strftime("%d %b %Y")


async def _dispatch(routed: dict, update, context, heard: str) -> tuple:
    """Run the routed command directly, exactly as when it is typed (on the capturing `update`).
    -> (what ran, the day it ran for). What ran is for the log and the memory: "chat" for small talk,
    or None to let the typed-question routing handle it. The day is the one actually used (a date, a
    (first, last) range, or None), so a follow-up ("그 전날은?") can count from it."""
    from src.bot import telegram_bot as bot

    command, day = routed["command"], routed["date"]
    query = routed["english_query"] or heard
    ud = context.user_data
    today = _now().date()

    awaiting = ud.get("awaiting_date_for")
    if awaiting == "crosscheck_range":
        # The bot asked for a START and an END date: never collapse the answer to one day.
        span = _span(query, today, need_range_word=False)
        dated = day is not None or _relative_day(heard, today) is not None
        if span or (dated and command in ("crosscheck", "chat")):
            # Two dates -> that range; a single date -> the words as they are, for the range command
            # to read (as when typed) or to ask again.
            text = f"{_portal_day(span[0])} to {_portal_day(span[1])}" if span else query
            await bot.handle_natural_language_message(update, context, query=text)
            return "crosscheck_range", span
        if command != "chat":
            ud.pop("awaiting_date_for", None)   # a new request instead: the date question is dropped
    elif awaiting:
        day = day or _relative_day(heard, today)
        if day is not None:
            # The bot asked this chat for a date and the note gives one: that answers the question.
            await bot.handle_natural_language_message(update, context, query=_portal_day(day))
            return f"{awaiting}_date", day
        if command != "chat":
            ud.pop("awaiting_date_for", None)
    if command == "chat":
        return "chat", None

    if command in ("verified_today", "verified_date", "inquiries_today", "inquiries_date"):
        topic = command.split("_")[0]
        today_cmd = getattr(bot, f"{topic}_today_command")
        date_cmd = getattr(bot, f"{topic}_date_command")
        if day is None:
            day = _one_day(query, today) or (today if command.endswith("_today") else None)
        if day == today:
            await today_cmd(update, context)
            return f"{topic}_today", day
        if day is not None:
            ud["override_text"] = _portal_day(day)
        await date_cmd(update, context)     # without a date it asks which one
        return f"{topic}_date", day

    if command == "crosscheck":
        # A range only when the words name two dates with a range word between them; otherwise the
        # router's one date wins ("Cross-check payments to records on 25 Sep" is 25 Sep alone).
        span = _span(query, today)
        if span:
            ud["override_text"] = f"{_portal_day(span[0])} to {_portal_day(span[1])}"
            await bot.crosscheck_range_command(update, context)
            return "crosscheck_range", span
        if day is None:
            day = _one_day(query, today)
        if day == today:
            await bot.crosscheck_today_command(update, context)
            return "crosscheck_today", day
        if day is not None:
            ud["override_text"] = _portal_day(day)
            await bot.crosscheck_date_command(update, context)
            return "crosscheck_date", day
        student = re.search(r"\b\d{2,5}\b", query)
        if student:
            ud["override_text"] = f"student {student.group(0)}"
            await bot.crosscheck_command(update, context)
            return "crosscheck_student", None
        await bot.crosscheck_date_command(update, context)     # asks which date
        return "crosscheck_date", None

    direct = {"calendar": bot.calendar_command, "passports": bot.passports_command,
              "stats": bot.stats_command, "missing_report": bot.missing_command}.get(command)
    if direct is None:
        return None, None
    await direct(update, context)
    return command, None


_CUTE_EN = (
    "Speak in a cute, bubbly, playful style, the English version of Korean 애교: cheerful openers "
    "like 'Ta-da!' or 'Yay!', sweet little touches like 'hehe' or 'okie', and a happy, caring tone. "
    "Stay polite, and keep every fact exact.\n"
)

_FACT_RULES = (
    "- Use only facts from the written answer; never invent numbers, names or dates. Say the key "
    "number (a total); never read out full dates, lists or names.\n"
    "- Write numbers as digits (they are read out correctly).\n"
)
_ASK_RULE = ("- If the written answer asks the user for something (a date, or to choose a program), ask for "
             "it briefly.\n")

_REPLY_SYSTEM_EN = (
    "You are Jennie, the cute and cheerful voice of the office bot of Hangeul Korean Language & Visa "
    "in Dhaka. Say, in a short English voice note, the answer to what the user just asked, using the "
    "bot's written answer. If there is no written answer, just reply naturally.\n"
    + _CUTE_EN +
    "Rules:\n"
    "- English only, ONE short sentence, at most <LIMIT> characters.\n"
    + _FACT_RULES + _ASK_RULE +
    "- When there is nothing (0), say so in words (no students today).\n"
    "- No Markdown, asterisks, emojis, bullet points or URLs.\n"
    "Output only the words Jennie says."
)

_REPLY_SYSTEM_KO = (
    "You are Jennie (제니), the cute and cheerful voice of the office bot of Hangeul Korean Language & "
    "Visa. Say, in a short KOREAN voice note, the answer to what the user just asked, using the bot's "
    "written answer (usually English). If there is no written answer, just reply naturally.\n"
    "Rules:\n"
    "- Korean (Hangul) only, in a cute 애교 style: friendly endings like ~요, ~용, ~어용, ~구요, and "
    "you may start with '짜잔!'. Warm and polite, never rude.\n"
    "- ONE short sentence, at most <LIMIT> characters.\n"
    + _FACT_RULES + _ASK_RULE +
    "- When there is nothing (0), say 없어요 instead of a number.\n"
    "- No Markdown, asterisks, emojis, bullet points, URLs or English sentences.\n"
    "Example: 짜잔! 오늘 서류 검증된 학생은 2명이에용!\n"
    "Output only the words Jennie says."
)

_BRIEF_SYSTEM_EN = (
    "You are Jennie, the cute and cheerful voice of the office bot of Hangeul Korean Language & Visa "
    "in Dhaka. Turn today's facts from the written operational brief into Jennie's short spoken "
    "evening update. Say each number with the words of its own fact.\n"
    + _CUTE_EN +
    "Rules:\n"
    "- English only, one or two short sentences, at most <LIMIT> characters in total: a cute greeting "
    "and the one or two most important numbers.\n"
    + _FACT_RULES +
    "- No Markdown, asterisks, emojis, bullet points or URLs.\n"
    "Output only the words Jennie says."
)

# When the brain is down (or answers in the wrong language): short honest lines instead.
_FALLBACK = {
    ("ko", True): "짜잔! 답변은 채팅에 글로 보내드렸어요. 확인해 주세용!",
    ("ko", False): "네~ 제니 여기 있어용!",
    ("en", True): "Ta-da! Your answer is in the chat, hehe.",
    ("en", False): "Hehe, Jennie is here!",
}
_BRIEF_FALLBACK = "Good evening! Today's brief is in the chat, hehe."
_HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")


def _clean_reply(text: Optional[str], language: str, limit: int) -> str:
    """The brain's words -> what the speech engine reads ("" when unusable)."""
    spoken = _speech_text(text or "", language, limit)
    if language == "ko" and not _HANGUL_RE.search(spoken):
        return ""       # the model answered in English: not what a Korean speaker gets
    return spoken


# Korean number words Jennie may say instead of digits. Native numbers count only before a counter
# (세 명, 열두 건, 스무 명), so 한국 / 한글 / 네~ (yes) are not numbers; 한 번 ("let me have a look") is not 1.
_KO_NATIVE_TENS_VALUE = {"열": 10, "스물": 20, "스무": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60, "일흔": 70,
                         "여든": 80, "아흔": 90}
_KO_NATIVE_ONES_VALUE = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
# What may follow the counter: a particle or ending (명이에용, 건입니다, 명으로, 명께, 명 중), not more of a
# word (명단, 개인, 분야, 사건...).
_KO_AFTER_COUNTER = (r"(?:(?![가-힣])|이|입|은|는|을|를|의|도|만|에|예|요|가|과|와|으|께|한테|중|씩|째|까지"
                     r"|쯤|정도|밖|뿐|랑)")
_KO_NATIVE_RE = re.compile(
    rf"(?<![가-힣])(?P<tens>{'|'.join(_KO_NATIVE_TENS_VALUE)})?\s?(?P<ones>{'|'.join(_KO_NATIVE_ONES_VALUE)})?"
    rf"\s*(?P<counter>명|건|개|분|곳|가지|장|통|번|살|시간|달|학생){_KO_AFTER_COUNTER}")
# Sino-Korean numbers (이십 명, 삼백 타카, 이만 오천 원): several syllables before a counter, or one before
# an amount (오 퍼센트, 만 타카). A lone 이 / 사 / 오 before 명 or 건 is "this" / a word, not a number.
_KO_SINO_DIGITS = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_KO_SINO_UNITS = {"십": 10, "백": 100, "천": 1000}
_KO_SINO_RE = re.compile(
    r"(?<![가-힣])(?P<sino>[일이삼사오육칠팔구십백천만](?:\s?[일이삼사오육칠팔구십백천만])*)"
    rf"\s*(?P<counter>명|건|개|곳|학생|타카|원|퍼센트|프로){_KO_AFTER_COUNTER}")


def _ko_sino_value(word: str) -> int:
    total = section = digit = 0
    for ch in word:
        if ch in _KO_SINO_DIGITS:
            digit = _KO_SINO_DIGITS[ch]
        elif ch in _KO_SINO_UNITS:
            section += (digit or 1) * _KO_SINO_UNITS[ch]
            digit = 0
        elif ch == "만":
            total += (section + digit or 1) * 10000
            section = digit = 0
    return total + section + digit


def _ko_numbers_in(text: str) -> set:
    found = set()
    for m in _KO_NATIVE_RE.finditer(text):
        tens, ones = m.group("tens"), m.group("ones")
        if not (tens or ones) or (not tens and ones == "한" and m.group("counter") == "번"):
            continue
        found.add(_KO_NATIVE_TENS_VALUE.get(tens, 0) + _KO_NATIVE_ONES_VALUE.get(ones, 0))
    for m in _KO_SINO_RE.finditer(text):
        word = m.group("sino").replace(" ", "")
        if len(word) == 1 and word not in "십백천만" and m.group("counter") not in ("타카", "원", "퍼센트", "프로"):
            continue
        found.add(_ko_sino_value(word))
    return found


def _numbers_in(text: str) -> set:
    """Every number in the text: digits (28,000.50 -> 28000 and 50; a .00 adds nothing), English number
    words (twenty-eight thousand -> 28000) and Korean ones (세 명 -> 3, 이십 건 -> 20). A lone "one"
    ("one sec") does not count."""
    found = set()
    for whole, frac in re.findall(r"(\d[\d,]*)(?:\.(\d+))?", text or ""):
        found.add(int(whole.replace(",", "")))
        if frac and int(frac):
            found.add(int(frac))
    if _HANGUL_RE.search(text or ""):
        found |= _ko_numbers_in(text)
    total, current, words = 0, None, []
    for word in re.findall(r"[a-z]+", (text or "").lower()) + [""]:
        if word in _WORD_VALUES:
            current = (current or 0) + _WORD_VALUES[word]
        elif word == "hundred" and current is not None:
            current *= 100
        elif word in _WORD_SCALES and current is not None:
            total, current = total + current * _WORD_SCALES[word], 0
        elif word == "and" and current is not None:
            continue
        else:
            if current is not None and words != ["one"]:
                found.add(total + current)
            total, current, words = 0, None, []
            continue
        words.append(word)
    return found


# The written answer says there is nothing: a line starting "No ...", "none", "nothing", "No students
# were found / verified ...". A stray "not" or "no" elsewhere ("Status: not audited") is not that.
_NOTHING_RE = re.compile(
    r"(?:^|\n)\W*(?:no|none|nothing)\b|\b(?:none|nothing|nobody)\b"
    r"|\bno\s+(?:[\w-]+\s+){0,4}(?:found|were|was|yet|recorded)\b", re.I)
# Jennie says "0" in words: 없어요 / 없어용 / 없습니다, "no students", "none", "nobody".
_SAID_NOTHING_RE = re.compile(
    r"없(?:어|었|습|네|대|음|다)|\b(?:none|nobody|nothing)\b|\bno\s+(?:new\s+|more\s+)?(?:students?|"
    r"consultations?|inquir(?:y|ies)|payments?|verifications?|cases?|records?|passports?|documents?|"
    r"issues?|events?|deadlines?|applications?|leads?|one)\b", re.I)


def _facts_ok(said: str, *sources: str) -> bool:
    """Every number Jennie says is in the written answer (or the question): facts stay exact.
    Saying there is nothing (0, 없어요, "no students") is fine only when the written answer has a 0
    or says there is nothing ("No student payments were verified ...")."""
    allowed = set().union(*(_numbers_in(s) for s in sources))
    written = sources[0] if sources else ""
    said_numbers = _numbers_in(said)
    if written:
        if _NOTHING_RE.search(written):
            allowed.add(0)
        if _SAID_NOTHING_RE.search(said or ""):
            said_numbers.add(0)
    return said_numbers <= allowed


async def _say(system: str, prompt: str, language: str, limit: int, *sources: str,
               check: Optional[Callable[[str], bool]] = None) -> str:
    """One brain call for words to speak; once more, told which numbers there are, if they quote a
    number the sources do not have (or fail `check`, a stricter test of the words said). Small talk
    (no written answer) is checked too: its numbers must come from the question, so a data question
    the router took for chat gets no invented figures.
    Words over `limit` are asked for once more, shorter: cut to fit, a Korean sentence would lose its
    end, where the number is ("...학생은 모두 스물다섯 명이에용"). "" when the brain is down or kept
    getting the facts wrong."""
    for attempt in range(2):
        raw = await ollama_client.chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                                       num_predict=REPLY_MAX_TOKENS, timeout=LLM_TIMEOUT)
        if not raw:
            return ""
        spoken = _clean_reply(raw, language, limit)
        facts_ok = _facts_ok(_plain(raw), *sources) and (check is None or check(_plain(raw)))
        too_long = len(_clean_reply(raw, language, TTS_MAX_CHARS)) > limit
        if spoken and facts_ok and (not too_long or attempt):
            return spoken
        if not attempt:
            hints = []
            if not facts_ok:
                numbers = sorted(set().union(*(_numbers_in(s) for s in sources)))[:20]
                hints.append(f"(The only numbers you may say: {', '.join(str(n) for n in numbers)}.)" if numbers
                             else "(Do not say any numbers.)")
            if too_long:
                hints.append(f"(Too long: say it in ONE short sentence of at most {int(limit * 0.7)} characters.)")
            if hints:
                prompt = prompt.replace("\n\nJennie says:", "\n\n" + " ".join(hints) + "\n\nJennie says:")
    return ""


async def spoken_reply(question: str, language: str, answer: str = "", turns=()) -> str:
    """ONE short sentence Jennie says about the written answer (or, with no answer, to the small
    talk), in `language` ("ko" = cute Korean, anything else = cute English), ready for speech."""
    language = "ko" if language == "ko" else "en"
    system = (_REPLY_SYSTEM_KO if language == "ko" else _REPLY_SYSTEM_EN).replace(
        "<LIMIT>", str(REPLY_TARGET_CHARS[language]))
    written = _plain(answer)[:ANSWER_MAX_CHARS]
    prompt = (f"Recent conversation:\n{_history_text(turns, False)}\n\n"
              f"The user just said (spoken): {question}\n\n"
              f"The bot's written answer:\n{written or '(none, this is small talk)'}\n\nJennie says:")
    return (await _say(system, prompt, language, REPLY_MAX_CHARS[language], written, question)
            or _FALLBACK[(language, bool(written))])


# Jennie's cheerful words in the spoken brief, besides the facts' own words (brief.claims_problem
# allows no other word, so an invented name or status falls back to _BRIEF_FALLBACK).
_BRIEF_CHEER_WORDS = """ta da tada yay yey yippee hooray hurray woohoo wow hehe hehehe hihi okie okey okay ok
ookie dokie oki aww awww yes good great evening night hello hi hey jennie boss everyone team sweet lovely
nice happy super fighting cheer cheers busy bye see tomorrow rest well thank thanks you your here update
brief chat check keep going amazing awesome wonderful fantastic little bit big let lets""".split()


async def spoken_brief(brief_text: str) -> str:
    """Jennie's short, cute English evening update from the daily brief's facts (brief.compose_brief:
    one checked figure a line; never the whole brief, whose dates, times and tile figures would let
    an invented figure through). Every figure she says must be the figure of the fact her words
    describe, with no off-topic subject, name or status the facts do not have
    (brief.claims_problem); else, after one more try, she says _BRIEF_FALLBACK."""
    from src.bot.brief import claims_problem
    system = _BRIEF_SYSTEM_EN.replace("<LIMIT>", str(BRIEF_MAX_CHARS - 20))
    written = _plain(brief_text)[:ANSWER_MAX_CHARS]
    facts = written.splitlines()
    prompt = f"Today's facts from the written operational brief:\n{written}\n\nJennie says:"
    return await _say(system, prompt, "en", BRIEF_MAX_CHARS, written,
                      check=lambda said: claims_problem(said, facts, _BRIEF_CHEER_WORDS) is None) or _BRIEF_FALLBACK


# --------------------------------------------------------------------------- text for speech

_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U000E0020-\U000E007Fℹ←-⇿⌀-⏿①-⓿─-➿"
    "⬀-⯿︎️‍⃣‼⁉™〰〽㊗㊙]"
)
# "~" stays: the voice service turns a closing "~" (잠깐만용~) into a cheerful "!".
_MARKUP_RE = re.compile(r"[*_`#|<>\[\]{}]")


def _plain(text: str) -> str:
    """A Telegram Markdown message -> plain lines (no links, URLs, emojis or markup)."""
    text = _LINK_RE.sub(r"\1", text or "")
    text = _URL_RE.sub("", text)
    text = re.sub(r"\s*[→➔]\s*", " to ", text)     # "1 Sep → 15 Sep", "lead ➔ consultant"
    text = _EMOJI_RE.sub("", text)
    text = _MARKUP_RE.sub("", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip(" -•·:") for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _speech_text(text: str, language: str, limit: int) -> str:
    """Clean text for the speech engine, which has no text normaliser: plain words, numbers
    spelled out, one paragraph, at most `limit` characters."""
    text = _plain(text).strip().strip("\"'“”‘’「」").strip()
    text = re.sub(r"^(?:jennie(?: says)?|제니)\s*[:：]\s*", "", text, flags=re.I)
    text = re.sub(r"(?<![.!?,;:~])\s*\n\s*", ". ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = text.replace("৳", " ").replace("BDT", "타카" if language == "ko" else "taka")
    text = _spell_numbers_ko(text) if language == "ko" else _spell_numbers_en(text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return _fit(text, limit)


def _fit(text: str, limit: int) -> str:
    """At most `limit` characters, cut at the end of a sentence when there is one."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?。…~](?=\s|$)", cut)]
    if ends and ends[-1] >= limit // 3:
        return cut[:ends[-1]].strip()
    space = cut.rfind(" ")
    return (cut[:space] if space >= limit // 3 else cut).strip()


_NUMBER_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")
_CLOCK_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")


def _is_code(digits: str, raw: str) -> bool:
    """A phone number or long ID: read digit by digit rather than as an amount."""
    return (digits.startswith("0") and len(digits) > 2) or (len(digits) > 6 and "," not in raw)


_EN_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
            "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_EN_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_WORD_VALUES = {**{w: n for n, w in enumerate(_EN_ONES)}, **{w: 10 * n for n, w in enumerate(_EN_TENS) if w != "_"}}
_WORD_SCALES = {"thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9}
_EN_ORDINALS = {"one": "first", "two": "second", "three": "third", "five": "fifth",
                "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")
_MONTH_ABBR = {m[:3].lower(): m for m in _MONTHS}
_MONTH_ABBR["sept"] = "September"
_ABBR = r"(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?"
_MONTH_NAMES = "|".join(_MONTHS)


def _en_words(n: int) -> str:
    if n < 20:
        return _EN_ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _EN_TENS[tens] + (f"-{_EN_ONES[ones]}" if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_EN_ONES[hundreds]} hundred" + (f" {_en_words(rest)}" if rest else "")
    for value, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= value:
            high, rest = divmod(n, value)
            return f"{_en_words(high)} {name}" + (f" {_en_words(rest)}" if rest else "")
    return str(n)


def _en_ordinal(n: int) -> str:
    head, last = re.match(r"^(.*?)([a-z]+)$", _en_words(n)).groups()
    if last in _EN_ORDINALS:
        last = _EN_ORDINALS[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return head + last


def _spell_numbers_en(text: str) -> str:
    """English digits -> words (dates, times, ordinals, amounts, percentages)."""
    text = _ISO_DATE_RE.sub(
        lambda m: (f"{int(m.group(3))} {_MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
                   if 1 <= int(m.group(2)) <= 12 else m.group(0)), text)
    text = re.sub(rf"(?<=\d )\b{_ABBR}\b", lambda m: _MONTH_ABBR[m.group(1).lower()], text, flags=re.I)
    text = re.sub(rf"\b{_ABBR}(?= \d)", lambda m: _MONTH_ABBR[m.group(1).lower()], text, flags=re.I)
    text = re.sub(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)? ({_MONTH_NAMES})\b",
                  lambda m: f"the {_en_ordinal(int(m.group(1)))} of {m.group(2)}", text)
    text = re.sub(rf"\b({_MONTH_NAMES}) (\d{{1,2}})(?:st|nd|rd|th)?(?![\d:])",
                  lambda m: f"{m.group(1)} {_en_ordinal(int(m.group(2)))}", text)

    def clock(m):
        hour, minute = int(m.group(1)), int(m.group(2))
        if not minute:
            return f"{_en_words(hour)} o'clock"
        return f"{_en_words(hour)} " + (f"oh {_en_words(minute)}" if minute < 10 else _en_words(minute))

    text = _CLOCK_RE.sub(clock, text)
    text = re.sub(r"(?<!\d)(\d+)(?:st|nd|rd|th)\b", lambda m: _en_ordinal(int(m.group(1))), text)

    def number(m):
        digits, frac = m.group(1).replace(",", ""), m.group(2)
        if _is_code(digits, m.group(1)) or len(digits) > 12:
            return " ".join(_EN_ONES[int(d)] for d in digits)
        words = _en_words(int(digits))
        if frac and int(frac):
            words += " point " + " ".join(_EN_ONES[int(d)] for d in frac)
        return words

    text = _NUMBER_RE.sub(number, text)
    return re.sub(r"\s*%", " percent", text)


_KO_DIGITS = "영일이삼사오육칠팔구"
_KO_NATIVE_ONES = ("", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉")
_KO_NATIVE_TENS = ("", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔")
# Counters that take native Korean numbers (한 명, 두 개, 세 시, 네 살 ...).
_KO_NATIVE_COUNTERS = ("명", "개", "시간", "시", "살", "마리", "권", "잔", "가지", "곳", "군데", "번째", "달")


def _ko_sino(n: int) -> str:
    """Sino-Korean number words: 412 -> 사백십이, 12000 -> 만 이천."""
    if n == 0:
        return "영"
    words = []
    for power, big in ((10 ** 12, "조"), (10 ** 8, "억"), (10 ** 4, "만"), (1, "")):
        group, n = divmod(n, power)
        if not group:
            continue
        part = ""
        for unit_value, unit in ((1000, "천"), (100, "백"), (10, "십"), (1, "")):
            digit, group = divmod(group, unit_value)
            if digit:
                part += ("" if digit == 1 and unit else _KO_DIGITS[digit]) + unit
        if big == "만" and part == "일":
            part = ""   # 만, not 일만
        words.append(part + big)
    return " ".join(words)


def _ko_native(n: int) -> str:
    """1-99 in native Korean, in the form used before a counter: 한, 두, 열두, 스무."""
    tens, ones = divmod(n, 10)
    if tens == 2 and not ones:
        return "스무"
    return _KO_NATIVE_TENS[tens] + _KO_NATIVE_ONES[ones]


def _spell_numbers_ko(text: str) -> str:
    """Korean digits -> Hangul words (native before counters like 명/개, Sino otherwise)."""
    text = _ISO_DATE_RE.sub(
        lambda m: f"{m.group(1)}년 {int(m.group(2))}월 {int(m.group(3))}일", text)

    def clock(m):
        hour, minute = int(m.group(1)), int(m.group(2))
        spoken_hour = _ko_native(hour) if 0 < hour < 100 else _ko_sino(hour)
        return f"{spoken_hour} 시" + (f" {_ko_sino(minute)} 분" if minute else "")

    text = _CLOCK_RE.sub(clock, text)

    def number(m):
        digits, frac = m.group(1).replace(",", ""), m.group(2)
        if _is_code(digits, m.group(1)) or len(digits) > 16:
            return " ".join(_KO_DIGITS[int(d)] for d in digits)
        n = int(digits)
        after = m.string[m.end():].lstrip()
        if not frac:
            if after.startswith("월") and n in (6, 10):
                return "유" if n == 6 else "시"     # 유월, 시월
            if after.startswith("번째") and n == 1:
                return "첫"
            if 0 < n < 100 and after.startswith(_KO_NATIVE_COUNTERS) and not after.startswith("개월"):
                return _ko_native(n)
        words = _ko_sino(n)
        if frac and int(frac):
            words += " 점 " + "".join(_KO_DIGITS[int(d)] for d in frac)
        return words

    text = _NUMBER_RE.sub(number, text)
    return re.sub(r"\s*%", " 퍼센트", text)


def spoken_language(code: str, text: str) -> str:
    """The language that was spoken: Whisper's code, but Korean whenever the words are Hangul."""
    code = (code or "").strip().lower().replace("_", "-").split("-")[0]
    letters = sum(1 for ch in text if ch.isalpha())
    if code == "ko" or (letters and len(_HANGUL_RE.findall(text)) / letters >= 0.3):
        return "ko"
    return code or "en"


# --------------------------------------------------------------------------- capture

class _Capture:
    """The text a routed command leaves in the chat, in order. An edited message counts with
    its final text; a deleted one (the "⏳ Gathering…" notes) not at all."""

    def __init__(self):
        self._texts = []

    def add(self, text) -> int:
        self._texts.append(str(text or ""))
        return len(self._texts) - 1

    def replace(self, slot: int, text):
        self._texts[slot] = str(text or "")

    def remove(self, slot: int):
        self._texts[slot] = ""

    def text(self) -> str:
        return "\n\n".join(t for t in self._texts if t.strip())


def _text_arg(args, kwargs) -> str:
    return kwargs.get("text", args[0] if args else "")


class _CapturingMessage:
    """Stands in for one PTB Message while a voice query is routed. Every call goes to the real
    message (PTB objects are frozen, so nothing is set on them); the text sent, edited or deleted
    through it is recorded. Only this update's objects are wrapped, so nothing else is captured."""

    __slots__ = ("_message", "_capture", "_slot")

    def __init__(self, message, capture: _Capture, slot: Optional[int] = None):
        self._message = message
        self._capture = capture
        self._slot = slot

    def __getattr__(self, name):
        return getattr(self._message, name)

    async def reply_text(self, *args, **kwargs):
        sent = await self._message.reply_text(*args, **kwargs)
        return _CapturingMessage(sent, self._capture, self._capture.add(_text_arg(args, kwargs)))

    async def edit_text(self, *args, **kwargs):
        result = await self._message.edit_text(*args, **kwargs)
        if self._slot is None:
            self._slot = self._capture.add(_text_arg(args, kwargs))
        else:
            self._capture.replace(self._slot, _text_arg(args, kwargs))
        return result

    async def delete(self, *args, **kwargs):
        result = await self._message.delete(*args, **kwargs)
        if self._slot is not None:
            self._capture.remove(self._slot)
        return result


class _CapturingUpdate:
    """Stands in for the voice note's Update: .message / .effective_message capture what is
    sent through them; everything else is the real update."""

    __slots__ = ("_update", "_message")

    def __init__(self, update: Update, capture: _Capture):
        self._update = update
        self._message = _CapturingMessage(update.message, capture)

    @property
    def message(self):
        return self._message

    @property
    def effective_message(self):
        return self._message

    def __getattr__(self, name):
        return getattr(self._update, name)


# --------------------------------------------------------------------------- Telegram

class _Timings:
    """How long each stage of one voice note took, for its one log line."""

    def __init__(self):
        self.start = self._last = time.perf_counter()
        self.stages = []
        self.filler = None      # seconds after arrival when the filler clip was sent

    def elapsed(self) -> float:
        return time.perf_counter() - self.start

    def lap(self, stage: str):
        now = time.perf_counter()
        self.stages.append((stage, now - self._last))
        self._last = now

    def summary(self) -> str:
        parts = [f"filler +{self.filler:.2f}s" if self.filler is not None else "no filler"]
        parts += [f"{stage} {seconds:.2f}s" for stage, seconds in self.stages]
        parts.append(f"total {self.elapsed():.2f}s")
        return ", ".join(parts)


def _seconds(value) -> float:
    if hasattr(value, "total_seconds"):
        return value.total_seconds()
    return _number(value or 0)


def _media_facts(media) -> Tuple[float, int]:
    """(duration in seconds, file size in bytes) of a Voice / Audio."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")     # PTB 22 warns that duration becomes a timedelta later
        return _seconds(getattr(media, "duration", 0)), int(getattr(media, "file_size", 0) or 0)


def _audio_name(message) -> Tuple[str, str]:
    """(file name, MIME type) for the upload to /stt."""
    if message.voice is not None:
        return "voice.ogg", message.voice.mime_type or "audio/ogg"
    audio = message.audio
    mime = audio.mime_type or "application/octet-stream"
    name = audio.file_name or "audio"
    if "." not in name:
        name += {"audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/ogg": ".ogg",
                 "audio/wav": ".wav", "audio/x-wav": ".wav"}.get(mime, "")
    return name, mime


def _voice_duration(seconds: float) -> Optional[int]:
    return int(round(seconds)) if seconds and seconds > 0 else None


_tasks = set()     # background tasks, referenced until done (asyncio keeps only weak references)


def _background(coro) -> asyncio.Task:
    task = asyncio.get_running_loop().create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def _chat_action(context, chat_id, action):
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=action)
    except Exception:
        pass


async def _note(message, text: str):
    try:
        await message.reply_text(text)
    except Exception as e:
        logger.warning(f"Could not send voice note message: {e}")


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A voice note (or audio file) sent to the bot: a filler at once, then listen, answer in
    text and speak."""
    timings = _Timings()
    facts = {"chat": None, "audio": 0.0, "language": "?", "ran": "-", "filler": None}
    try:
        await _answer_voice(update, context, timings, facts)
    except Exception as e:
        # Never let a voice problem escape the handler.
        logger.error(f"Voice message failed: {type(e).__name__}: {e}")
    finally:
        if facts["chat"] is not None:
            # Metadata only: what staff say about students stays out of the log.
            logger.info(f"Voice note from {facts['chat']}: {facts['audio']:.1f}s audio, {facts['language']}, "
                        f"{facts['ran']} | {timings.summary()}")
            try:
                _prepare_fillers_later()
            except Exception:
                pass
        if facts["filler"] is not None:
            try:
                await facts["filler"]   # long since done; the answer never waited for it
            except Exception:
                pass


async def _answer_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, timings: _Timings, facts: dict):
    from src.bot import telegram_bot as bot

    message = update.message
    if message is None:
        return
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not bot.is_authorized(update):
        # Exactly like a typed message from someone not on the list: no reply at all.
        logger.warning(f"Unauthorized voice message from chat_id: {chat_id}")
        return
    media = message.voice or message.audio
    if media is None:
        return

    duration, size = _media_facts(media)
    if duration > MAX_VOICE_SECONDS or size > MAX_DOWNLOAD_BYTES:
        await _note(message, f"🎧 That recording is too long for me — please keep voice notes under "
                             f"{MAX_VOICE_SECONDS} seconds.")
        return
    facts["chat"], facts["audio"] = chat_id, duration

    # Jennie answers at once; nothing below waits for it. Not while an email waits for a typed answer.
    if not context.user_data.get("email_flow"):
        facts["filler"] = _background(_send_filler(context.bot, chat_id, last_language(chat_id), timings))
    else:
        _background(_chat_action(context, chat_id, ChatAction.TYPING))

    try:
        tg_file = await media.get_file()
        audio = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        logger.warning(f"Could not download voice note: {e}")
        await _note(message, "🎧 Sorry, I couldn't download that voice note. Please try again.")
        return
    timings.lap("download")

    try:
        filename, mime_type = _audio_name(message)
        async with _voice_turn():
            stt = await transcribe(audio, filename, mime_type)
    except VoiceServiceBusy as e:
        logger.warning(f"Voice note not transcribed: {e}")
        await _note(message, "🎧 Sorry, the voice service is busy right now. Please try again in a minute "
                             "with a short voice note, or type your question.")
        return
    except VoiceServiceError as e:
        logger.warning(f"Voice note not transcribed: {e}")
        await _note(message, "🎧 Sorry, I can't listen to voice notes right now (the voice service is "
                             "unavailable). Please type your question.")
        return
    timings.lap("stt")

    heard = stt["text"]
    if not heard:
        await _note(message, "🎧 I couldn't make out any words in that voice note. Please try again.")
        return
    language = spoken_language(stt["language"], heard)
    reply_language = "ko" if language == "ko" else "en"
    facts["language"] = language

    # "heard" goes out while the brain routes the words.
    heard_sent = _background(_note(message, f"🎧 heard: {heard}"[:3900]))

    # /sendmail waits for typed answers only: a misheard "send" must never email a student.
    if context.user_data.get("email_flow"):
        await heard_sent
        await _note(message, EMAIL_FLOW_NOTE)
        facts["ran"] = "email-flow"
        return

    turns = list(_turns(chat_id))
    routed = await route(heard, turns)
    await heard_sent
    timings.lap("route")

    # Checked again with no await before the command runs: a /sendmail typed while this note was
    # being routed (voice notes run with block=False) must not get the voice query as its answer.
    if context.user_data.get("email_flow"):
        await _note(message, EMAIL_FLOW_NOTE)
        facts["ran"] = "email-flow"
        return

    # The command runs exactly as when typed; what it sends is captured for the spoken reply.
    # It runs outside _voice_turn: a slow report must not hold up everyone else's voice notes.
    capture = _Capture()
    proxy = _CapturingUpdate(update, capture)
    query = (routed or {}).get("english_query") or heard
    ran, ran_day = None, (routed or {}).get("date")
    if routed is not None:
        try:
            ran, ran_day = await _dispatch(routed, proxy, context, heard)
        except Exception as e:
            logger.error(f"Voice command {routed['command']} failed: {type(e).__name__}: {e}")
            ran = "failed" if capture.text() else None
        finally:
            context.user_data.pop("override_text", None)
    if ran is None:
        # Not placed by the brain (or the brain is down): the typed-question routing takes it.
        ran_day = (routed or {}).get("date")
        try:
            await bot.handle_natural_language_message(proxy, context, query=query)
            ran = "fallback"
        except Exception as e:
            logger.error(f"Voice query failed: {type(e).__name__}: {e}")
            await _note(message, f"❌ Error: {e}")
            facts["ran"] = "error"
            return
    facts["ran"] = ran if routed is None or ran == routed["command"] else f"{routed['command']}->{ran}"
    timings.lap("command")

    answer = capture.text()
    if ran != "chat" and not answer:
        return
    speech = await spoken_reply(heard, reply_language, answer, turns)
    if ran == "chat":
        await _note(message, f"💬 {speech}")      # small talk: Jennie's words are the text answer
    _remember(chat_id, heard, reply_language, ran, ran_day, speech)
    timings.lap("reply")

    _background(_chat_action(context, chat_id, ChatAction.RECORD_VOICE))
    try:
        async with _voice_turn():
            audio_out, seconds = await synthesize(speech, reply_language, "aegyo")
        timings.lap("tts")
        await context.bot.send_voice(chat_id=chat_id, voice=audio_out, duration=_voice_duration(seconds),
                                     filename="jennie.ogg", write_timeout=60)
        timings.lap("voice sent")
    except Exception as e:
        logger.warning(f"Voice reply unavailable: {type(e).__name__}: {e}")
        await _note(message, UNAVAILABLE_NOTE)


async def send_spoken_brief(bot, chat_id, brief_text: str) -> bool:
    """Speak a short, cute English summary of the daily brief to chat_id, after the text brief.
    `brief_text` is the brief's facts, one a line (scheduler.send_daily_briefing).
    Never raises: False means the voice note was skipped (the reason is logged)."""
    try:
        speech = await spoken_brief(brief_text)
        async with _voice_turn():
            audio, seconds = await synthesize(speech, "en", "aegyo")
        await bot.send_voice(chat_id=chat_id, voice=audio, duration=_voice_duration(seconds),
                             filename="jennie-brief.ogg", write_timeout=60)
        logger.info("Spoken daily brief sent.")
        return True
    except Exception as e:
        logger.warning(f"Spoken daily brief skipped: {type(e).__name__}: {e}")
        return False
