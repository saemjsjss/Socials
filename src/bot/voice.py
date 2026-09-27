"""Jennie's voice: Telegram voice notes in, text + voice notes out.

A voice note from an authorised user goes to the local voice service (JENNIE_VOICE_URL,
127.0.0.1:8765) for speech-to-text, and the bot replies "🎧 heard: ..." at once. A request
in any language other than English is rewritten into a short English query by the local
LLM; the query then runs through exactly the same routing as a typed question
(telegram_bot.handle_natural_language_message), so the full text answer appears as usual.
What that routing leaves in the chat is captured, the local LLM turns it into a short spoken
reply in the language spoken (cute 애교 Jennie in Korean and in English), and the voice service
renders it with CosyVoice2 as an OGG/Opus voice note.

Everything stays on this PC. If the voice service is down or slow, the text answers still
arrive and one short note says the voice reply is unavailable; nothing here ever raises out
of the handler. The bot sends the voice service one request at a time (_voice_turn), so a
timeout only ever counts the bot's own request, and the local LLM has handed its VRAM back
before speech is rendered.

Voice service contract (127.0.0.1 only):
  POST /stt  multipart "audio"                      -> {"text", "language", "duration_s", "seconds"}
  POST /tts  {"text", "language": "en"|"ko", "style": "aegyo"|"neutral"}
             -> OGG/Opus body, headers X-Duration / X-Seconds (text over 600 chars -> 413)
"""
import asyncio
import logging
import re
import warnings
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.config import settings
from src.llm.ollama_client import ollama_client

logger = logging.getLogger("hangeul.voice")

STT_TIMEOUT = 60.0              # seconds allowed for /stt
TTS_TIMEOUT = 120.0             # seconds allowed for /tts (the service queues one request at a time)
TTS_MAX_CHARS = 600             # the voice service refuses longer text (413)
REPLY_MAX_CHARS = 400           # spoken answer to a voice note
BRIEF_MAX_CHARS = 500           # spoken daily brief
ANSWER_MAX_CHARS = 3000         # how much of the written answer the summary prompt sees
# Longer recordings are not transcribed. Kept within STT_TIMEOUT: when the GPU is busy the voice
# service transcribes on the CPU, which runs just under real time, so a longer note would time out.
MAX_VOICE_SECONDS = 60
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024   # Telegram's own limit for bot downloads
VOICE_TURN_WAIT = 240.0         # seconds a voice flow waits for its turn at the voice service

# Ollama keep_alive for the voice flow's own LLM calls; the GPU is shared with speech and OCR.
# The rewrite keeps the model warm for the routed command and the summary right after it.
# The summary is the last LLM call before speech is rendered, so it hands the VRAM straight
# back ("0s" unloads the model as soon as it has answered) instead of holding it through TTS.
REWRITE_KEEP_ALIVE = "30s"
SUMMARY_KEEP_ALIVE = "0s"

UNAVAILABLE_NOTE = "🔇 Voice reply unavailable right now — the answer is in the text above."
EMAIL_FLOW_NOTE = ("✉️ An email is waiting for your answer — please type it (SEND / EDIT / DENY or the detail "
                   "I asked for). I don't handle emails from voice notes.")

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

# ollama_client answers with this canned text when the local LLM is down (_fallback_response).
_LLM_DOWN_MARKERS = (
    "ollama service is not currently responding",
    "please verify ollama is started",
    "request processed successfully",
)


class VoiceServiceError(Exception):
    """The local voice service could not be reached, or refused the request."""


class VoiceServiceBusy(VoiceServiceError):
    """The voice service is there but busy: it timed out, answered 503, or our turn never came."""


# --------------------------------------------------------------------------- one request at a time

_turn = None    # (event loop, asyncio.Lock), created lazily on the bot's loop


@asynccontextmanager
async def _voice_turn():
    """The bot's own turn at the voice service. Voice flows (voice notes, which run concurrently
    with block=False, and the spoken brief) take turns, so the bot never has two requests in
    flight: each request's timeout counts only its own work, and one flow's spoken summary never
    loads the local LLM while another flow's speech is rendering on the GPU."""
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


# --------------------------------------------------------------------------- local LLM

async def _ask_llm(prompt: str, system: str, keep_alive: str) -> Optional[str]:
    """One local-LLM call; None when Ollama is down or answers with its canned fallback."""
    try:
        text = await ollama_client.generate_response(prompt, system=system, keep_alive=keep_alive)
    except Exception as e:
        logger.warning(f"Local LLM call failed: {e}")
        return None
    text = (text or "").strip()
    if not text or any(marker in text.lower() for marker in _LLM_DOWN_MARKERS):
        return None
    return text


def _today() -> str:
    try:
        now = datetime.now(ZoneInfo(settings.REPORT_TIMEZONE))
    except Exception:
        now = datetime.now()
    return now.strftime("%A %d %b %Y")


_REWRITE_SYSTEM = (
    "You turn a staff member's spoken request (usually Korean) into ONE short English query for "
    "the Telegram bot of Hangeul Korean Language & Visa, a study-in-Korea agency. Use the bot's own "
    "wording whenever it fits:\n"
    "- consultancy inquiries today / consultancy inquiries on 12 Sep 2026\n"
    "- verified students today / verified students on 12 Sep 2026\n"
    "- crosscheck today / crosscheck 12 Sep 2026 / crosscheck 1 Sep 2026 to 15 Sep 2026 / "
    "crosscheck student 412\n"
    "- admitted students / admitted students Hanyang\n"
    "- calendar deadlines / calendar Hanyang\n"
    "- passport audit\n"
    "- report for today / report for 12 Sep 2026\n"
    "Otherwise write the question itself in plain English.\n"
    "Keep every name, ID and number exactly as given. Keep 'today' and 'yesterday' as words; write "
    "other dates like 12 Sep 2026 (today is {today}).\n"
    "Output only the query: one line, no quotes, no explanation."
)


async def rewrite_to_english(transcript: str, language: str) -> Optional[str]:
    """A non-English request -> a short English query in the bot's own wording (None = failed)."""
    answer = await _ask_llm(
        f"Spoken request (language: {language}): {transcript}\nEnglish query:",
        _REWRITE_SYSTEM.format(today=_today()),
        keep_alive=REWRITE_KEEP_ALIVE,
    )
    if not answer:
        return None
    line = next((ln.strip() for ln in answer.splitlines() if ln.strip()), "")
    line = re.sub(r"^(?:english\s+)?query\s*[:：]\s*", "", line, flags=re.I)
    line = line.strip().strip("\"'“”‘’`").strip()
    return line[:200] or None


_SUMMARY_RULES_EN = (
    "Rules:\n"
    "- English only, 1 to 3 short sentences, at most {limit} characters in total.\n"
    "- Use only facts from the written text; never invent numbers, names or dates. Give totals rather "
    "than long lists of names.\n"
    "- If the written text asks the user for something (such as a date), ask for it briefly.\n"
    "- Write numbers as words where natural (twelve students, not 12 students).\n"
    "- Plain spoken sentences only: no Markdown, asterisks, emojis, bullet points, tables or URLs.\n"
    "Output only the words Jennie says."
)

# The owner wants the same cute 애교 Jennie in English as in Korean: playful and sweet, but the facts
# stay exact.
_CUTE_EN = (
    "Speak in a cute, bubbly, playful style, the English version of Korean 애교: cheerful openers "
    "like 'Ta-da!' or 'Yay!', sweet little touches like 'hehe' or 'okie', and a happy, caring tone. "
    "Stay polite, and keep every fact exact.\n"
)

_SUMMARY_SYSTEM_EN = (
    "You are Jennie, the cute and cheerful voice of the office bot of Hangeul Korean Language & Visa "
    "in Dhaka. Turn the bot's written answer into the words Jennie says aloud in a short voice note.\n"
    + _CUTE_EN + _SUMMARY_RULES_EN
)

_BRIEF_SYSTEM_EN = (
    "You are Jennie, the cute and cheerful voice of the office bot of Hangeul Korean Language & Visa "
    "in Dhaka. Turn today's written operational brief into Jennie's short spoken evening update: a "
    "brief greeting, then the two or three most important numbers or actions.\n"
    + _CUTE_EN + _SUMMARY_RULES_EN
)

_SUMMARY_SYSTEM_KO = (
    "You are Jennie (제니), the cute and cheerful voice of the office bot of Hangeul Korean Language & "
    "Visa. Turn the bot's written answer (usually English) into the words Jennie says aloud in a "
    "short KOREAN voice note.\n"
    "Rules:\n"
    "- Korean (Hangul) only, in a cute 애교 style: friendly endings like ~요, ~용, ~어용, ~구요, and "
    "you may start with '짜잔!'. Warm and polite, never rude.\n"
    "- 1 to 3 short sentences, at most {limit} characters in total.\n"
    "- Use only facts from the written answer; never invent numbers, names or dates. Give totals "
    "rather than long lists of names.\n"
    "- If the written answer asks the user for something (such as a date), ask for it briefly.\n"
    "- Write every number in Hangul words, never digits: 3명 -> 세 명, 12개 -> 열두 개, "
    "412번 -> 사백십이 번, 2026년 -> 이천이십육 년.\n"
    "- No Markdown, asterisks, emojis, bullet points, tables, URLs or English sentences.\n"
    "Example: 짜잔! 오늘 서류 검증된 학생은 세 명이에용. 모두 여권 정보가 딱 맞았어요!\n"
    "Output only the words Jennie says."
)

_KO_FALLBACK = "짜잔! 답변은 채팅에 글로 보내드렸어요. 확인해 주세용!"
_HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")


async def spoken_summary(answer: str, language: str, question: str = "",
                         limit: int = REPLY_MAX_CHARS, brief: bool = False) -> str:
    """The words Jennie says about a written answer: 1-3 short sentences in `language`
    ("ko" = cute Korean, anything else = English), ready for the speech engine."""
    written = _plain(answer)[:ANSWER_MAX_CHARS]
    if language == "ko":
        system = _SUMMARY_SYSTEM_KO.format(limit=limit)
    else:
        language = "en"
        system = (_BRIEF_SYSTEM_EN if brief else _SUMMARY_SYSTEM_EN).format(limit=limit)
    if brief:
        prompt = f"Today's written operational brief:\n{written}\n\nJennie says:"
    else:
        prompt = f"The user asked (spoken): {question}\n\nThe bot's written answer:\n{written}\n\nJennie says:"

    spoken = await _ask_llm(prompt, system, keep_alive=SUMMARY_KEEP_ALIVE)
    if spoken:
        spoken = _speech_text(spoken, language, limit)
        if language == "ko" and not _HANGUL_RE.search(spoken):
            spoken = ""     # the model answered in English: not what a Korean speaker gets
    if spoken:
        return spoken

    # The local LLM is down: read the written answer itself (English), or say where it is (Korean).
    if language == "ko":
        return _KO_FALLBACK
    opener = "Good evening! Here is today's brief. " if brief else ""
    return _speech_text(opener + written, "en", limit) or "Your answer is in the chat."


# --------------------------------------------------------------------------- text for speech

_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFFℹ←-⇿⌀-⏿①-⓿─-➿"
    "⬀-⯿︎️‍⃣]"
)
_MARKUP_RE = re.compile(r"[*_`#|~<>\[\]{}]")


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
    """A voice note (or audio file) sent to the bot: listen, answer in text, then speak."""
    try:
        await _answer_voice(update, context)
    except Exception as e:
        # Never let a voice problem escape the handler.
        logger.error(f"Voice message failed: {type(e).__name__}: {e}")


async def _answer_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.bot.telegram_bot import is_authorized, handle_natural_language_message

    message = update.message
    if message is None:
        return
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not is_authorized(update):
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

    await _chat_action(context, chat_id, ChatAction.TYPING)
    try:
        tg_file = await media.get_file()
        audio = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        logger.warning(f"Could not download voice note: {e}")
        await _note(message, "🎧 Sorry, I couldn't download that voice note. Please try again.")
        return

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

    heard = stt["text"]
    if not heard:
        await _note(message, "🎧 I couldn't make out any words in that voice note. Please try again.")
        return
    heard_msg = await message.reply_text(f"🎧 heard: {heard}"[:3900])

    language = spoken_language(stt["language"], heard)
    reply_language = "ko" if language == "ko" else "en"

    # /sendmail waits for typed answers only: a misheard "send" must never email a student.
    if context.user_data.get("email_flow"):
        await _note(message, EMAIL_FLOW_NOTE)
        return

    query = heard
    if language != "en":
        query = await rewrite_to_english(heard, language) or heard
        if query != heard:
            try:
                await heard_msg.edit_text(f"🎧 heard: {heard}\n🔎 as: {query}"[:3900])
            except Exception:
                pass
    # Metadata only: what staff say about students stays out of the log.
    logger.info(f"Voice note from {chat_id}: {stt['duration_s']:.1f}s, {language}, transcribed in "
                f"{stt['seconds']:.1f}s, query of {len(query)} chars{' (rewritten)' if query != heard else ''}")

    # Checked again with no await before the routing's own check: a /sendmail typed while this
    # note was being rewritten (voice notes run with block=False) must not get the query as its answer.
    if context.user_data.get("email_flow"):
        await _note(message, EMAIL_FLOW_NOTE)
        return

    # The same routing as a typed question; what it sends is captured for the spoken reply.
    # It runs outside _voice_turn: a slow report must not hold up everyone else's voice notes.
    capture = _Capture()
    try:
        await handle_natural_language_message(_CapturingUpdate(update, capture), context, query=query)
    except Exception as e:
        logger.error(f"Voice query failed: {type(e).__name__}: {e}")
        await _note(message, f"❌ Error: {e}")
        return
    answer = capture.text()
    if not answer:
        return

    await _chat_action(context, chat_id, ChatAction.RECORD_VOICE)
    try:
        # One turn for the summary and the speech: the summary's LLM call (keep_alive "0s") has
        # handed the VRAM back before speech renders, and no other voice flow loads it meanwhile.
        async with _voice_turn():
            speech = await spoken_summary(answer, reply_language, question=heard)
            audio_out, seconds = await synthesize(speech, reply_language, "aegyo")
        await context.bot.send_voice(chat_id=chat_id, voice=audio_out, duration=_voice_duration(seconds),
                                     filename="jennie.ogg", write_timeout=60)
    except Exception as e:
        logger.warning(f"Voice reply unavailable: {type(e).__name__}: {e}")
        await _note(message, UNAVAILABLE_NOTE)


async def send_spoken_brief(bot, chat_id, brief_text: str) -> bool:
    """Speak a short English summary of the daily brief to chat_id, after the text brief.
    Never raises: False means the voice note was skipped (the reason is logged)."""
    try:
        async with _voice_turn():
            speech = await spoken_summary(brief_text, "en", limit=BRIEF_MAX_CHARS, brief=True)
            audio, seconds = await synthesize(speech, "en", "aegyo")
        await bot.send_voice(chat_id=chat_id, voice=audio, duration=_voice_duration(seconds),
                             filename="jennie-brief.ogg", write_timeout=60)
        logger.info("Spoken daily brief sent.")
        return True
    except Exception as e:
        logger.warning(f"Spoken daily brief skipped: {type(e).__name__}: {e}")
        return False
