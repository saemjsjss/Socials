"""Jennie voice service: offline ears (speech-to-text) and voice (text-to-speech) for the
Hangeul Telegram bot (@the_Jennie_bot).

  GET  /health -> {"ok": true, "stt": <model>, "tts": "cosyvoice2", "device": "cuda|cpu", "tts_on_gpu": bool,
                   "busy_s": <seconds the current request has held the lock>}   (503 + "ok": false when hung)
  POST /stt    multipart field "audio" (Telegram .ogg/Opus, .wav, .mp3, .m4a)
               -> {"text", "language", "duration_s", "seconds"}
  POST /tts    JSON {"text", "language": "en"|"ko", "style": "aegyo"|"neutral"}
               -> OGG/Opus voice note (audio/ogg) with X-Duration / X-Seconds headers

Speech-to-text is faster-whisper; text-to-speech is CosyVoice2-0.5B, zero-shot for Korean and
cross-lingual for English from ONE Korean-female reference, so Jennie has one voice in both languages.
Everything runs on this PC and nothing is downloaded at run time. It listens on 127.0.0.1 only and
refuses browsers (see _LocalClientsOnly). One lock serialises requests. The GPU is shared with the bot's
OCR and Ollama, so the models only visit it per request (see the VRAM policy in README.md).
"""
import asyncio
import contextlib
import ctypes
import gc
import io
import logging
import logging.handlers
import os
import re
import socket
import sys
import threading
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))

# pythonw.exe has no console: sys.stdout / sys.stderr are None and the first library print would crash.
if sys.stdout is None:
    sys.stdout = open(os.path.join(HERE, "jennie_voice_stdout.log"), "a", encoding="utf-8", buffering=1)
if sys.stderr is None:
    sys.stderr = open(os.path.join(HERE, "jennie_voice_stderr.log"), "a", encoding="utf-8", buffering=1)


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# ================================================================ configuration
HOST = "127.0.0.1"          # never 0.0.0.0: the bot on this PC is the only client
PORT = 8765

# --- text-to-speech: CosyVoice2-0.5B, code and weights reused by path from the trial folder
COSYVOICE_TRIAL = r"C:\Hangeul\JARVIS\voice-trials\cosyvoice"
COSYVOICE_REPO = os.path.join(COSYVOICE_TRIAL, "repo")
COSYVOICE_MODEL = os.path.join(COSYVOICE_REPO, "pretrained_models", "CosyVoice2-0.5B")
REF_WAV = os.path.join(COSYVOICE_TRIAL, "ref", "ref_v2xl_ko_female.wav")     # "ref_v2xl_ko_female"
REF_TEXT = "안녕하세요! 저는 제니예요. 오늘도 만나서 정말 반가워요. 궁금한 게 있으면 언제든지 물어봐 주세요."
REF_WAV_EN = REF_WAV        # English = cross-lingual from the same reference: one persona in both languages
TTS_SEED = 1234             # the seed the approved samples were rendered with
TTS_MAX_CHARS = 600         # longer text -> 413
TTS_GPU_NEED_GB = 3.8       # free VRAM needed to bring the TTS model to the GPU (measured: weights 2.6 + work 0.9)
TTS_GPU_WORK_GB = 1.2       # free VRAM needed for a render when the model is already on the GPU
TTS_IDLE_S = _env_float("JENNIE_TTS_IDLE_S", 300)   # back to the CPU after this many idle seconds
TTS_MAX_S = _env_float("JENNIE_TTS_MAX_S", 100)     # a /tts answers within this many seconds of arriving, or 503
# CPU render time ~ TTS_CPU_BASE_S + TTS_CPU_RTF x seconds of speech (the 11 s voice prompt runs through the
# models every time). Measured with the bot running: 1.8 s of speech 19.6 s, 4.6 s 29 s, 16.4 s 96 s;
# a 3.8 s line whose render rambled to 10.5 s took 64 s. (GPU: ~0.7 x the speech.)
TTS_CPU_BASE_S = 10.0
TTS_CPU_RTF = 5.5
TTS_CPU_THREADS = 6
TTS_CHUNK_GAP_S = 0.12      # pause between the sentences CosyVoice renders one by one
TTS_BODY_MAX = 64 * 1024    # bytes of JSON a /tts may send (600 characters need ~2 KB)

# --- output voice note: OGG/Opus written by soundfile, 48 kHz mono like Telegram's own voice notes
OGG_SAMPLE_RATE = 48000
TARGET_RMS_DBFS = -19.0     # loudness of the voiced part
PEAK_CEILING_DBFS = -1.0
TRIM_PAD_S = (0.08, 0.15)   # silence kept before / after the speech
SOUND_DB = -30.0            # frames this far below the loud speech (95th percentile) are silence
SPEECH_PEAK_DB = -18.0      # a stretch of sound that never gets louder than this is breath/noise, not words
MAX_PAUSE_S = 0.9           # a longer silence inside a reply is shortened to KEEP_PAUSE_S
KEEP_PAUSE_S = 0.5
SECONDS_PER_CHAR = {"ko": 0.19, "en": 0.075}   # measured speaking pace of Jennie's voice
RUNAWAY_FACTOR = 2.5        # longer than this x the expected length: the model rambled - render again
TOO_SHORT_FACTOR = 0.35     # shorter than this x the expected length (texts over 20 chars): the render failed

# --- speech-to-text: faster-whisper (choice and numbers in README.md / bench_stt.json)
WHISPER_TRIAL_HUB = r"C:\Hangeul\JARVIS\voice-trials\whisper\hf_home\hub"
STT_MODEL_DIRS = {
    "large-v3-turbo": os.path.join(HERE, "models", "hf", "hub", "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"),
    "large-v3": os.path.join(WHISPER_TRIAL_HUB, "models--Systran--faster-whisper-large-v3"),
    "medium": os.path.join(WHISPER_TRIAL_HUB, "models--Systran--faster-whisper-medium"),
    "small": os.path.join(HERE, "models", "hf", "hub", "models--Systran--faster-whisper-small"),
}
STT_MODEL = "large-v3-turbo"        # GPU, float16: Korean as good as large-v3 here, 2.4x faster, ~2.2 GB VRAM
STT_CPU_MODEL = "medium"            # CPU fallback, int8 ("small" is 3x faster on the CPU but hears Korean worse)
STT_GPU_MIN_FREE_GB = 3.0           # use the GPU only when this much VRAM is free at request time
STT_GPU_KEEP_S = _env_float("JENNIE_STT_GPU_KEEP_S", 0)  # 0 = weights leave the GPU right after each request
STT_GPU_UNLOAD_TO_RAM = False       # True: park the GPU weights in RAM (faster reload, +1.6 GB RAM)
STT_CPU_THREADS = 6
STT_BEAM = 5
STT_LANGS = ("en", "ko")            # Jennie speaks these two
STT_OTHER_LANG_MIN_PROB = 0.85      # a confident other language is returned as is (bot can say so)
STT_UNSURE_PROB = 0.6               # below this, en vs ko is re-checked by transcribing both ways
STT_MAX_BYTES = 25 * 1024 * 1024
STT_MAX_AUDIO_S = 600

USE_GPU = os.environ.get("JENNIE_GPU", "1") != "0"   # JENNIE_GPU=0: never touch the GPU (CPU only)
LOCK_WAIT_S = _env_float("JENNIE_LOCK_WAIT_S", 120)   # a request waiting longer for the lock gets 503
HUNG_AFTER_S = _env_float("JENNIE_HUNG_S", 600)       # /health answers 503 once one request holds the lock longer
IDLE_CHECK_S = 10
LOCAL_HOSTS = {f"{HOST}:{PORT}", f"localhost:{PORT}", HOST, "localhost"}   # accepted Host headers
LOG_FILE = os.path.join(HERE, "jennie_voice.log")
LOG_TEXT_CHARS = 40         # never log more of a student's words than this

# offline only: never reach the hub / modelscope at run time; no progress bars in the logs
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HOME", os.path.join(HERE, "models", "hf"))
os.environ.setdefault("MODELSCOPE_CACHE", os.path.join(HERE, "models", "modelscope"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TQDM_DISABLE", "1")
if not USE_GPU:
    os.environ["CUDA_VISIBLE_DEVICES"] = ""   # CosyVoice would otherwise still open a CUDA context

# ================================================================ logging


class _RedactFilter(logging.Filter):
    """CosyVoice logs the text of every chunk it speaks ('synthesis text ...', and a 'too short than prompt
    text' warning for short chunks). A long reply is several chunks, so even 40 characters of each would leak
    most of it: keep only the length. The request's own log line already has its first 40 characters."""

    SHORT = " too short than prompt text "

    def filter(self, record):
        if isinstance(record.msg, str) and record.msg.startswith("synthesis text"):
            said = record.getMessage()[len("synthesis text "):]
            short = said.find(self.SHORT)
            if short >= 0:
                record.msg = "synthesis text chunk (%d chars) is short next to the prompt text" % short
            else:
                record.msg = "synthesis text chunk (%d chars)" % len(said)
            record.args = None
        return True


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handlers = [logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3,
                                                     encoding="utf-8")]
    if sys.stdout is not None and getattr(sys.stdout, "isatty", lambda: False)():
        handlers.append(logging.StreamHandler(sys.stdout))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(_RedactFilter())
        root.addHandler(h)
    logging.captureWarnings(True)
    for noisy in ("numba", "matplotlib", "urllib3", "modelscope", "httpx", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_setup_logging()
log = logging.getLogger("jennie.voice")


def _snip(text):
    text = " ".join(str(text).split())
    return repr(text[:LOG_TEXT_CHARS] + ("..." if len(text) > LOG_TEXT_CHARS else ""))


class _MemCounters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32)] + [
        (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                             "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                             "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                                             "PrivateUsage")]


def _ram():
    """'RAM x.x GB (private y.y GB)' of this process, for the log (Windows only)."""
    try:
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MemCounters), ctypes.c_uint32]
        c = _MemCounters()
        c.cb = ctypes.sizeof(c)
        k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return f"RAM {c.WorkingSetSize / 2 ** 30:.1f} GB (private {c.PrivateUsage / 2 ** 30:.1f} GB)"
    except Exception:
        return "RAM ?"


def _claim_port():
    """Bind 127.0.0.1:8765 before anything heavy loads, so a second copy exits at once instead of loading
    ~5.5 GB of models and only then failing to bind. The socket stays bound but not listening (callers get
    'connection refused') until uvicorn serves on it. None when another process holds the port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)   # nobody else may share the port
    try:
        s.bind((HOST, PORT))
    except OSError:
        s.close()
        return None
    return s


_listener = None
if __name__ == "__main__":
    _listener = _claim_port()
    if _listener is None:
        log.error("%s:%d is already in use - is another Jennie voice service running? Exiting.", HOST, PORT)
        sys.exit(1)

# ================================================================ heavy imports
sys.path.insert(0, os.path.join(HERE, "stubs"))                          # pyworld stub
sys.path.insert(0, COSYVOICE_REPO)
sys.path.insert(0, os.path.join(COSYVOICE_REPO, "third_party", "Matcha-TTS"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402  (before CTranslate2: puts torch\lib - cuBLAS / cuDNN - on the DLL path)
from faster_whisper import WhisperModel  # noqa: E402
from faster_whisper.audio import decode_audio  # noqa: E402
from fastapi import FastAPI, File, Request, UploadFile  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _gb(n_bytes):
    return n_bytes / 1024 ** 3


def _snapshot(repo_dir):
    """The Hugging Face cache folder of a model -> its snapshot folder holding model.bin."""
    snaps = os.path.join(repo_dir, "snapshots")
    for name in sorted(os.listdir(snaps)):
        if os.path.exists(os.path.join(snaps, name, "model.bin")):
            return os.path.join(snaps, name)
    raise FileNotFoundError(f"no model.bin under {snaps}")


@contextlib.contextmanager
def _cuda_hidden():
    """CosyVoice picks its device while it is built. Build it on the CPU: it only visits the GPU per request."""
    real = torch.cuda.is_available
    torch.cuda.is_available = lambda: False
    try:
        yield
    finally:
        torch.cuda.is_available = real


# ================================================================ text preparation for the voice
_SINO_DIGITS = "영일이삼사오육칠팔구"
_NATIVE = ["", "하나", "둘", "셋", "넷", "다섯", "여섯", "일곱", "여덟", "아홉"]
_NATIVE_BEFORE_COUNTER = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
_NATIVE_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
# counters read with native Korean numbers (한 명, 두 개, 세 시) up to 99; the others are Sino-Korean
_NATIVE_COUNTERS = ("명", "개", "살", "시간", "시", "마리", "권", "잔", "장", "번째", "번", "가지", "곳", "달",
                    "사람", "군데", "통", "병")
_SINO_COUNTERS = ("개월", "분", "초", "일", "월", "년", "원", "주", "층", "학년", "퍼센트", "%")
_KO_COUNTER_RX = "|".join(sorted(_NATIVE_COUNTERS + _SINO_COUNTERS, key=len, reverse=True))


def _sino_small(n):
    out = ""
    for value, unit in ((1000, "천"), (100, "백"), (10, "십"), (1, "")):
        d = n // value % 10
        if d:
            out += ("" if d == 1 and unit else _SINO_DIGITS[d]) + unit
    return out


def ko_sino(n):
    """2026 -> 이천이십육 (Sino-Korean: years, dates, money, minutes, phone digits)."""
    if n == 0:
        return "영"
    if n >= 10 ** 16:
        return " ".join(_SINO_DIGITS[int(d)] for d in str(n))
    out = ""
    for value, unit in ((10 ** 12, "조"), (10 ** 8, "억"), (10 ** 4, "만"), (1, "")):
        chunk = n // value % 10000
        if chunk:
            out += ("" if chunk == 1 and unit == "만" else _sino_small(chunk)) + unit
    return out


def ko_native(n, before_counter=True):
    """7 -> 일곱, 20 명 -> 스무 명 (native Korean, 1..99)."""
    tens, ones = divmod(n, 10)
    t = "스무" if (before_counter and tens == 2 and ones == 0) else _NATIVE_TENS[tens]
    return t + (_NATIVE_BEFORE_COUNTER if before_counter else _NATIVE)[ones]


def _ko_number(m):
    whole, frac, counter = m.group(1).replace(",", ""), m.group(2), m.group(3) or ""
    n = int(whole)
    if frac:
        spoken = ko_sino(n) + " 점 " + "".join(_SINO_DIGITS[int(d)] for d in frac[1:])
    elif counter == "번째" and n == 1:
        spoken = "첫"
    elif counter in _NATIVE_COUNTERS and 1 <= n <= 99:
        spoken = ko_native(n)
    elif counter == "월" and 1 <= n <= 12:
        return _ko_month(n)
    elif not counter and len(whole) > 1 and whole.startswith("0"):
        spoken = "".join("공" if d == "0" else _SINO_DIGITS[int(d)] for d in whole)   # codes: 017 -> 공일칠
    else:
        spoken = ko_sino(n)
    if counter in ("%", "퍼센트"):
        counter = "퍼센트"
    return spoken + (" " + counter if counter else "")


def _ko_time(m):
    said, h, mnt = m.group(1), int(m.group(2)), int(m.group(3))
    if h > 24 or mnt > 59:
        return m.group(0)
    half = said or ("오전" if h % 24 < 12 else "오후")     # "오후 6:30": the text already says which half
    h12 = h % 12 or 12
    return f"{half} {ko_native(h12)} 시" + (f" {ko_sino(mnt)} 분" if mnt else "")


def _ko_month(n):
    """9 -> 구월, 6 -> 유월, 11 -> 십일월: a month name is one word. Spaced, CosyVoice's reading was misheard
    ('십일 월' came back as '10일 월', '시 월' as '시 월'); written as one word both were heard right."""
    return {6: "유월", 10: "시월"}.get(n) or ko_sino(n) + "월"


def _ko_date(m):
    """2026-09-27 -> 이천이십육년 구월 이십칠일 (attached: with spaces, seed 1234 turned '마감일은 이천이십육 년
    구 월 이십칠 일까지예요!' into 17 s of mumbling; attached, it was spoken and heard back right)."""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return m.group(0)
    return f"{ko_sino(y)}년 {_ko_month(mo)} {ko_sino(d)}일"


def _digits_ko(s):
    return " ".join("".join("공" if d == "0" else _SINO_DIGITS[int(d)] for d in g) for g in re.findall(r"\d+", s))


def _ko_range(a, b, rest):
    """'3', '5', '명이에요' -> '3명에서 5' (the counter after 5 stays in rest): 세 명에서 다섯 명.
    Two years keep the counter once: 2025-2026학년도 -> 2025에서 2026학년도."""
    counter = re.match(r"\s*(" + _KO_COUNTER_RX + ")", rest)
    if counter and not (len(a) == 4 and len(b) == 4):
        return f"{a}{counter.group(1)}에서 {b}"
    return f"{a}에서 {b}"


def _ko_dashed(m):
    """Digits joined by '-': a phone number (read digit by digit), a range (3-5일), or a code."""
    s = m.group(0)
    groups = re.findall(r"\d+", s)
    if s.startswith("+") or (s.startswith("0") and sum(map(len, groups)) >= 7):
        return _digits_ko(s)                                 # 010-1234-5678, +880 1711-123456
    if len(groups) == 2 and max(map(len, groups)) <= 4:
        return _ko_range(groups[0], groups[1], m.string[m.end():])
    return _digits_ko(s)                                     # 1711-123456, 12-34-56


# Digit-only boundaries: Python counts Hangul as \w, so \b never matches in '18:05에' or '2026-09-27까지'.
_KO_DATE_RX = re.compile(r"(?<!\d)(\d{4})[-./](\d{1,2})[-./](\d{1,2})(?!\d)")
_KO_TILDE_RX = re.compile(r"(?<![\d+-])(\d{1,4})\s*~\s*(\d{1,4})(?![\d-])")
_KO_TIME_RX = re.compile(r"(?:(오전|오후)\s*)?(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])")
_KO_DASHED_RX = re.compile(r"(?<![\d+-])(?:\+\d{1,4}[ -]?)?\d+(?:-\d+)+(?![\d-])|(?<![\d+])\+\d{7,15}(?!\d)")


def spell_numbers_ko(text):
    text = _KO_DATE_RX.sub(_ko_date, text)
    text = _KO_TILDE_RX.sub(lambda m: _ko_range(m.group(1), m.group(2), m.string[m.end():]), text)
    text = _KO_TIME_RX.sub(_ko_time, text)
    text = _KO_DASHED_RX.sub(_ko_dashed, text)
    return re.sub(r"(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:\s*(" + _KO_COUNTER_RX + r"))?", _ko_number, text)


_inflect = None


def _en_words(n):
    global _inflect
    if _inflect is None:
        import inflect
        _inflect = inflect.engine()
    return _inflect.number_to_words(n)


def _en_time(m):
    h, mnt, said = int(m.group(1)), int(m.group(2)), m.group(3)
    if h > 24 or mnt > 59:
        return m.group(0)
    half = (said[0].upper() + "M") if said else ("AM" if h % 24 < 12 else "PM")   # 6:30pm keeps its PM
    h12 = h % 12 or 12
    if mnt == 0:
        return f"{h12} {half}"
    return f"{h12} {'oh ' if mnt < 10 else ''}{mnt} {half}"


_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"]


def _en_date(m):
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return m.group(0)
    _en_words(0)
    if 2000 <= y <= 2009:
        year = _inflect.number_to_words(y, andword="")                     # two thousand five
    elif 1100 <= y <= 2099:
        year = _inflect.number_to_words(y, group=2, zero="oh").replace(",", "")   # twenty twenty-six
    else:
        year = str(y)
    return f"{_MONTHS[mo - 1]} {_inflect.ordinal(_en_words(d))}, {year}"


def spell_numbers_en(text):
    """CosyVoice spells plain digits itself (inflect); fix the forms it would read wrongly."""
    # digit-only boundaries: \b never matches between the 0 and the p of "6:30pm"
    text = re.sub(r"(?<!\d)(\d{4})[-./](\d{1,2})[-./](\d{1,2})(?!\d)", _en_date, text)
    text = re.sub(r"(\d)\s*~\s*(\d)", r"\1 to \2", text)
    # "p.m." keeps its final dot when it ends the sentence ("5:30 p.m." -> "5 30 PM.")
    text = re.sub(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])(?:\s*([AaPp])\.?[Mm](?:\.(?=\s*[a-z,;]))?(?![A-Za-z]))?",
                  _en_time, text)
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
    text = re.sub(r"(?<![\d.])(\d+)(st|nd|rd|th)\b", lambda m: _inflect_ordinal(int(m.group(1))), text)
    text = re.sub(r"(\d)\.(\d+)", lambda m: f"{m.group(1)} point {' '.join(m.group(2))}", text)
    return text.replace("%", " percent")


def _inflect_ordinal(n):
    _en_words(0)
    return _inflect.ordinal(_en_words(n))


def prepare_text(text, language):
    """Bot text -> what CosyVoice should read: no markdown, emoji, links or control tags; numbers spelled out
    (CosyVoice has no text normaliser here); one line per sentence."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"<\|[^|>]*\|>|\[[a-z_ ]+\]", " ", text)                     # CosyVoice control tokens
    text = re.sub(r"https?://\S+|www\.\S+", "링크" if language == "ko" else "the link", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("So", "Sk", "Cs", "Co", "Cn")
                   or ch in "%")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^[\s>#*\-•·▪◦]+", "", line)
        line = re.sub(r"[*_`#|]+", " ", line).strip()
        if line:
            lines.append(line if line[-1] in ".!?…" else (line[:-1] if line[-1] in ",:;" else line) + ".")
    text = " ".join(lines)
    text = spell_numbers_ko(text) if language == "ko" else spell_numbers_en(text)
    text = re.sub(r"[(){}\[\]<>]", ", ", text)
    text = re.sub(r"(?<=\D)/(?=\D)", ", ", text)                              # IELTS/TOPIK
    text = re.sub(r"~+(?=\s|$)", "!", text)                                   # 제니예요~ -> 제니예요!
    text = text.replace("~", "").replace("&", " 그리고 " if language == "ko" else " and ")
    text = re.sub(r"\s+([,.!?:;])", r"\1", text)
    text = re.sub(r",+(\s*,+)*", ",", text)
    text = re.sub(r"[,:;]+(?=\s*[.!?])", "", text)                            # "TOPIK,." -> "TOPIK."
    return re.sub(r"\s+", " ", text).strip(" ,")


# ================================================================ audio post-processing
def _frame_rms(wav, sr, hop_s=0.01):
    hop = max(1, int(sr * hop_s))
    n = len(wav) // hop
    if n == 0:
        return np.zeros(0, dtype=np.float32), hop
    return np.sqrt(np.mean(wav[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12), hop


def polish(wav, sr):
    """Trim silence and breath/noise before and after the words, shorten over-long pauses inside, bring the
    speech to TARGET_RMS_DBFS and keep peaks under the ceiling."""
    wav = np.asarray(wav, dtype=np.float32)
    rms, hop = _frame_rms(wav, sr)
    if len(rms) == 0 or rms.max() < 1e-4:
        return wav
    ref = float(np.percentile(rms, 95))
    rel = 20 * np.log10(rms / ref + 1e-12)
    segments = []                                   # [first, last] frame of each stretch of sound
    for i in np.where(rel >= SOUND_DB)[0]:
        if segments and i - segments[-1][1] <= int(0.3 / 0.01):
            segments[-1][1] = i
        else:
            segments.append([i, i])
    words = [k for k, (a, b) in enumerate(segments) if rel[a:b + 1].max() >= SPEECH_PEAK_DB] or [0, len(segments) - 1]
    keep = segments[words[0]:words[-1] + 1]
    pieces, pos = [], max(0, keep[0][0] * hop - int(TRIM_PAD_S[0] * sr))
    for (_, a_end), (b_start, _) in zip(keep, keep[1:]):
        gap_start, gap_end = (a_end + 1) * hop, b_start * hop
        if gap_end - gap_start > MAX_PAUSE_S * sr:
            half = int(KEEP_PAUSE_S * sr / 2)
            pieces.append(wav[pos:gap_start + half])
            pos = gap_end - half
    pieces.append(wav[pos:min(len(wav), (keep[-1][1] + 1) * hop + int(TRIM_PAD_S[1] * sr))])
    wav = np.concatenate(pieces).astype(np.float32)
    fade = min(int(0.01 * sr), len(wav) // 2)
    if fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        wav[:fade] *= ramp
        wav[-fade:] *= ramp[::-1]
    rms, _ = _frame_rms(wav, sr)
    loud = rms[rms >= ref * 10 ** (SOUND_DB / 20)]
    level = float(np.sqrt(np.mean(loud ** 2))) if len(loud) else float(np.sqrt(np.mean(wav ** 2)))
    gain = 10 ** (TARGET_RMS_DBFS / 20) / max(level, 1e-6)
    peak = float(np.max(np.abs(wav))) * gain
    ceiling = 10 ** (PEAK_CEILING_DBFS / 20)
    if peak > ceiling:
        gain *= ceiling / peak
    return (wav * gain).astype(np.float32)


def encode_ogg_opus(wav, sr):
    """float32 mono -> OGG/Opus bytes (soundfile / libsndfile), re-read to prove it decodes."""
    if sr != OGG_SAMPLE_RATE:
        import soxr
        wav = soxr.resample(wav, sr, OGG_SAMPLE_RATE, quality="HQ").astype(np.float32)
    buf = io.BytesIO()
    with sf.SoundFile(buf, mode="w", samplerate=OGG_SAMPLE_RATE, channels=1, format="OGG", subtype="OPUS") as f:
        block = OGG_SAMPLE_RATE * 5          # libsndfile's Ogg writer is happier with modest blocks
        for i in range(0, len(wav), block):
            f.write(wav[i:i + block])
    data = buf.getvalue()
    check, check_sr = sf.read(io.BytesIO(data), dtype="float32")
    duration = len(check) / check_sr
    if duration < 0.05 or abs(duration - len(wav) / OGG_SAMPLE_RATE) > 0.25:
        raise RuntimeError(f"OGG/Opus check failed: decoded {duration:.2f} s of {len(wav) / OGG_SAMPLE_RATE:.2f} s")
    return data, duration


# ================================================================ speech-to-text: words Whisper invents
# Whisper turns sounds that are not speech (a hum, a tone, music) into stock phrases from its training
# subtitles. Measured on an 8 s humming tone: medium int8 (CPU) heard "Thanks for watching!" with no_speech
# 0.91 and logprob -0.98; large-v3-turbo (GPU) heard "You", logprob -0.99, with no_speech 0.00 (turbo
# reports ~0 for every segment, so the phrase list is what catches it there). On real speech (6 clips and
# their 1.2 s openings) medium's no_speech stayed at or under 0.47.
NO_SPEECH_PROB = 0.6
NO_SPEECH_MAX_LOGPROB = -0.5
_HALLUCINATION_RX = re.compile(
    r"(한글)?자막(제공)?(by|제공).*|시청(해)?주셔서감사합니다.*|구독(과|이랑)?좋아요.*|좋아요와구독.*"
    r"|(thanks|thankyou)(verymuch|somuch)?forwatching.*|subtitles?by.*|.*amaraorg.*|pleasesubscribe.*")
_WEAK_HALLUCINATIONS = {"you", "thankyou", "thanks", "bye", "byebye"}   # dropped only when unsure (logprob)


def _hallucinated(segment):
    said = "".join(ch for ch in segment.text.lower() if unicodedata.category(ch)[0] in "LN")
    if not said:
        return True
    if segment.no_speech_prob > NO_SPEECH_PROB and segment.avg_logprob < NO_SPEECH_MAX_LOGPROB:
        return True
    if _HALLUCINATION_RX.fullmatch(said):
        return True
    return said in _WEAK_HALLUCINATIONS and segment.avg_logprob < -0.6


# ================================================================ engine
class Job:
    """One HTTP request: the time it must be answered by (None = no limit) and whether its client hung up.
    'gone' is set from the event loop (see _watch_client) and read by the worker thread doing the work."""

    def __init__(self, what, budget_s=None):
        self.what = what
        self.budget_s = budget_s
        self.deadline = time.monotonic() + budget_s if budget_s else None
        self.gone = threading.Event()

    def left_s(self):
        return None if self.deadline is None else self.deadline - time.monotonic()

    def stop_reason(self):
        if self.gone.is_set():
            return "the client went away"
        if self.deadline is not None and time.monotonic() > self.deadline:
            return f"the {self.budget_s:.0f} s time limit passed"
        return None


class _Stop(Exception):
    """A render stopped on purpose: past its time limit, or its client went away."""


class _RenderControl:
    """Shared by one render and the hooks inside CosyVoice (see Engine._install_hooks). CosyVoice runs its
    language model in a thread of its own that swallows exceptions; the hook records them here instead."""

    def __init__(self, job):
        self.job = job
        self.error = None           # exception raised in CosyVoice's LLM thread (e.g. CUDA out of memory)
        self.stopped = None         # why the render was stopped, once it was

    def should_stop(self):
        if self.stopped is None and self.job is not None:
            self.stopped = self.job.stop_reason()
        return self.stopped is not None or self.error is not None

    def raise_if_done(self):
        """Before more work: stop now if the request is done for (checks the clock and the client)."""
        if self.should_stop():
            self.raise_if_failed()

    def raise_if_failed(self):
        """After a sentence: raise if it was cut short (by an error or a stop), without a new clock check, so a
        sentence that did finish in time is kept."""
        if self.error is not None:
            raise self.error
        if self.stopped is not None:
            raise _Stop(self.stopped)


def _is_oom(e):
    return isinstance(e, torch.OutOfMemoryError) or (isinstance(e, RuntimeError) and "out of memory" in str(e))


class Engine:
    def __init__(self):
        self.lock = threading.Lock()
        self.busy_since = None      # time.monotonic() when the request holding the lock took it
        self.busy_what = None
        self._ctl = None            # _RenderControl of the render in progress
        self.gpu = False
        self.tts = None
        self.sample_rate = 24000
        self.tts_device = "cpu"
        self._tts_cpu = None        # id(parameter or buffer) -> its CPU tensor, kept for the life of the process
        self._spk_cpu = None
        self.tts_last_used = 0.0
        self.stt_gpu = None
        self.stt_gpu_last_used = 0.0
        self.stt_cpu = None
        self.stt_path = None
        self.warm_audio = None

    # ---------------------------------------------------------------- VRAM helpers
    def free_gb(self):
        if not self.gpu:
            return 0.0
        try:
            return _gb(torch.cuda.mem_get_info()[0])
        except Exception:
            return 0.0

    def _stt_gpu_loaded(self):
        return self.stt_gpu is not None and self.stt_gpu.model.model_is_loaded

    def _stt_gpu_unload(self):
        if self._stt_gpu_loaded():
            self.stt_gpu.model.unload_model(to_cpu=STT_GPU_UNLOAD_TO_RAM)

    def _make_room(self, need_gb, keep):
        """Free our own idle GPU residents (never the one about to run) until need_gb is free."""
        free = self.free_gb()
        if free >= need_gb:
            return free
        if keep != "stt" and self._stt_gpu_loaded():
            self._stt_gpu_unload()
            free = self.free_gb()
            log.info("unloaded the idle STT model from the GPU to make room: %.2f GB free", free)
        if free < need_gb and keep != "tts" and self.tts_device == "cuda":
            self._tts_to("cpu")
            free = self.free_gb()
            log.info("moved the idle TTS model to the CPU to make room: %.2f GB free", free)
        return free

    def _tts_tensors(self):
        """Every parameter and buffer of the TTS model, once each (tied weights are one tensor)."""
        m, seen = self.tts.model, set()
        for module in (m.llm, m.flow, m.hift):
            for t in list(module.parameters()) + list(module.buffers()):
                if id(t) not in seen:
                    seen.add(id(t))
                    yield t

    def _tts_to(self, device):
        """Point the TTS weights at the GPU or back at their CPU copy.

        The CPU copy is never freed: the parameters only borrow a GPU copy of it (.data swap), so going back
        to the CPU allocates nothing and RAM stays flat however often the model visits the GPU."""
        if device == self.tts_device:
            return
        t = time.perf_counter()
        m, fe = self.tts.model, self.tts.frontend
        if self._tts_cpu is None:
            self._tts_cpu = {id(p): p.data for p in self._tts_tensors()}
            self._spk_cpu = {name: dict(spk) for name, spk in fe.spk2info.items()}

        def point(dev):
            gpu_of = {}                         # storage -> its one GPU copy (keeps shared storage shared)
            for p in self._tts_tensors():
                cpu = self._tts_cpu[id(p)]
                if dev.type == "cpu":
                    p.data = cpu
                else:
                    key = (cpu.untyped_storage().data_ptr(), cpu.storage_offset(), tuple(cpu.shape))
                    if key not in gpu_of:
                        gpu_of[key] = cpu.to(dev)
                    p.data = gpu_of[key]
            m.device = fe.device = dev
            m.llm_context = torch.cuda.stream(torch.cuda.Stream(dev)) if dev.type == "cuda" else contextlib.nullcontext()
            for name, spk in self._spk_cpu.items():
                fe.spk2info[name] = {k: (v.to(dev) if torch.is_tensor(v) else v) for k, v in spk.items()}

        try:
            point(torch.device(device))
            self.tts_device = device
        except Exception:
            point(torch.device("cpu"))         # never leave the model half on the GPU
            self.tts_device = "cpu"
            if self.gpu:
                torch.cuda.empty_cache()
            raise
        if device == "cpu" and self.gpu:
            torch.cuda.empty_cache()
        log.info("TTS model -> %s in %.1f s (%.2f GB VRAM free, %s)", device, time.perf_counter() - t, self.free_gb(),
                 _ram())

    def _install_hooks(self):
        """Two small wrappers inside CosyVoice so a render can be stopped and its errors are not lost:
        * the language model's token generator (run by CosyVoice in its own thread, which would print an
          exception to stderr and carry on with the tokens made so far) stops at the next token once the
          request's time is up or its client is gone, and records an exception instead of losing it;
        * the flow decoder's estimator (called ~10 times per sentence on the request's own thread) raises
          that exception, or _Stop, before doing more work."""
        engine = self
        llm, decoder = self.tts.model.llm, self.tts.model.flow.decoder
        llm_inference, forward_estimator = llm.inference, decoder.forward_estimator

        def guarded_inference(*args, **kwargs):
            ctl = engine._ctl
            tokens = llm_inference(*args, **kwargs)
            try:
                for token in tokens:
                    yield token
                    if ctl is not None and ctl.should_stop():
                        return
            except Exception as e:
                if ctl is None:
                    raise
                ctl.error = e
            finally:
                tokens.close()          # frees the model's key/value cache now

        def guarded_estimator(*args, **kwargs):
            ctl = engine._ctl
            if ctl is not None:
                ctl.raise_if_done()
            return forward_estimator(*args, **kwargs)

        llm.inference = guarded_inference
        decoder.forward_estimator = guarded_estimator

    def _forget_render(self):
        """A render that stopped half-way skips CosyVoice's own clean-up of its per-sentence state."""
        m = self.tts.model
        with m.lock:
            for d in (m.tts_speech_token_dict, m.llm_end_dict, m.hift_cache_dict):
                d.clear()

    # ---------------------------------------------------------------- startup
    def load(self):
        t_all = time.perf_counter()
        torch.set_num_threads(TTS_CPU_THREADS)
        self.gpu = USE_GPU and torch.cuda.is_available()
        if self.gpu:
            t = time.perf_counter()
            torch.zeros(1, device="cuda")
            torch.cuda.synchronize()
            log.info("CUDA ready in %.1f s: %s, %.2f GB VRAM free", time.perf_counter() - t,
                     torch.cuda.get_device_name(0), self.free_gb())
        else:
            log.warning("GPU not used (%s): everything runs on the CPU",
                        "JENNIE_GPU=0" if not USE_GPU else "no CUDA device")

        # --- TTS, built on the CPU; the reference voice is analysed once and cached as speaker "jennie"
        t = time.perf_counter()
        from cosyvoice.cli.cosyvoice import AutoModel
        with _cuda_hidden():
            self.tts = AutoModel(model_dir=COSYVOICE_MODEL)
        self._install_hooks()
        self.sample_rate = self.tts.sample_rate
        self.tts.add_zero_shot_spk(REF_TEXT, REF_WAV, "jennie")
        if REF_WAV_EN != REF_WAV:
            self.tts.add_zero_shot_spk("", REF_WAV_EN, "jennie_en")
        # prompt features are cached: the ONNX speech tokenizer and speaker encoder are not needed again
        self.tts.frontend.speech_tokenizer_session = None
        self.tts.frontend.campplus_session = None
        gc.collect()
        log.info("CosyVoice2 loaded on the CPU in %.1f s (%d Hz), %s", time.perf_counter() - t, self.sample_rate,
                 _ram())

        # --- STT
        self.warm_audio = decode_audio(REF_WAV, sampling_rate=16000)
        self.stt_path = _snapshot(STT_MODEL_DIRS[STT_MODEL])
        t = time.perf_counter()
        self.stt_cpu = WhisperModel(_snapshot(STT_MODEL_DIRS[STT_CPU_MODEL]), device="cpu", compute_type="int8",
                                    cpu_threads=STT_CPU_THREADS, local_files_only=True)
        self._whisper(self.stt_cpu, self.warm_audio[: 16000 * 3], "ko")
        log.info("STT CPU model %s int8 ready in %.1f s", STT_CPU_MODEL, time.perf_counter() - t)

        # --- one GPU warm-up of each model, then both leave the GPU
        if self.gpu:
            if self.free_gb() >= STT_GPU_MIN_FREE_GB:
                try:
                    t = time.perf_counter()
                    self._stt_gpu_ready()
                    self._whisper(self.stt_gpu, self.warm_audio, None)
                    log.info("STT GPU warm-up (%s float16) %.1f s", STT_MODEL, time.perf_counter() - t)
                except Exception:
                    log.exception("STT GPU warm-up failed: STT stays on the CPU until a request finds room")
                finally:
                    self._stt_gpu_unload()
            else:
                log.warning("STT GPU warm-up skipped: %.2f GB VRAM free", self.free_gb())
            if self.free_gb() >= TTS_GPU_NEED_GB:
                try:
                    t = time.perf_counter()
                    self._tts_to("cuda")
                    self._render("안녕하세요! 제니예요. 오늘도 잘 부탁해요.", "ko")
                    log.info("TTS GPU warm-up %.1f s", time.perf_counter() - t)
                except Exception:
                    log.exception("TTS GPU warm-up failed")
                finally:
                    self._tts_to("cpu")
            else:
                log.warning("TTS GPU warm-up skipped: %.2f GB VRAM free", self.free_gb())
            torch.cuda.empty_cache()
        gc.collect()
        log.info("ready in %.1f s; idle VRAM free %.2f GB, %s", time.perf_counter() - t_all, self.free_gb(), _ram())

    # ---------------------------------------------------------------- the one-at-a-time lock
    @contextlib.contextmanager
    def turn(self, what, job=None):
        """Wait (at most LOCK_WAIT_S) for the one lock. A request whose client hung up, or whose time ran
        out while it waited, is dropped instead of being worked on for nobody."""
        t = time.monotonic()
        while not self.lock.acquire(timeout=0.5):
            if job is not None and job.gone.is_set():
                log.info("%s: the client went away after waiting %.0f s - dropped", what, time.monotonic() - t)
                raise ApiError(503, "the client went away")
            if time.monotonic() - t >= LOCK_WAIT_S:
                log.warning("%s: still busy after %d s - 503", what, LOCK_WAIT_S)
                raise ApiError(503, f"busy: waited {LOCK_WAIT_S:.0f} s for the previous request")
        self.busy_since, self.busy_what = time.monotonic(), what
        try:
            reason = job.stop_reason() if job is not None else None
            if reason:
                log.info("%s: %s while waiting %.0f s for the lock - dropped", what, reason, time.monotonic() - t)
                raise ApiError(503, f"busy: {reason} while waiting for the previous request")
            yield time.monotonic() - t
        finally:
            self.busy_since = None
            self.lock.release()

    def busy_s(self):
        """How long the request holding the lock has had it (0 when idle)."""
        since = self.busy_since
        return 0.0 if since is None else time.monotonic() - since

    # ---------------------------------------------------------------- speech-to-text
    def _stt_gpu_ready(self):
        if self.stt_gpu is None:
            self.stt_gpu = WhisperModel(self.stt_path, device="cuda", compute_type="float16", local_files_only=True)
        elif not self.stt_gpu.model.model_is_loaded:
            self.stt_gpu.model.load_model()

    def _whisper(self, model, audio, language, job=None):
        segments, info = model.transcribe(audio, language=language, beam_size=STT_BEAM, vad_filter=True,
                                          vad_parameters={"min_silence_duration_ms": 500},
                                          condition_on_previous_text=False)
        kept, weighted, seconds = [], 0.0, 0.0
        for s in segments:                  # decoded lazily, one 30 s window at a time
            if job is not None and job.gone.is_set():
                raise ApiError(503, "the client went away")
            if _hallucinated(s):
                log.info("stt: dropped a %.1f s segment that looks like no speech (no_speech %.2f, logprob %.2f, "
                         "%d chars)", s.end - s.start, s.no_speech_prob, s.avg_logprob, len(s.text.strip()))
                continue
            kept.append(s.text)
            length = max(s.end - s.start, 0.1)
            weighted, seconds = weighted + s.avg_logprob * length, seconds + length
        # How confidently the words were decoded: the duration-weighted mean log-probability.
        score = weighted / seconds if seconds else float("-inf")
        return "".join(kept).strip(), info, score

    def _transcribe(self, model, audio, job=None):
        text, info, score = self._whisper(model, audio, None, job)
        language, prob = info.language, info.language_probability
        if language not in STT_LANGS and prob < STT_OTHER_LANG_MIN_PROB:
            probs = dict(info.all_language_probs or [])
            forced = max(STT_LANGS, key=lambda code: probs.get(code, 0.0))
            log.info("heard %s (%.2f): transcribing again as %s", language, prob, forced)
            text, _, _ = self._whisper(model, audio, forced, job)
            language = forced
        elif language in STT_LANGS and prob < STT_UNSURE_PROB:
            # A short note that opens with a name ("제니야 ...") is easily taken for English:
            # Korean at 0.96 was once heard as English at 0.14 ("Genia Onul's Soryo").  Decode it
            # as the other language too and keep whichever reads more confidently.
            other = next(code for code in STT_LANGS if code != language)
            alt_text, _, alt_score = self._whisper(model, audio, other, job)
            log.info("unsure %s (%.2f, score %.2f); as %s score %.2f", language, prob, score, other, alt_score)
            if alt_text and alt_score > score:
                text, language = alt_text, other
        return text, language, prob

    def stt(self, data, job=None):
        try:
            audio = decode_audio(io.BytesIO(data), sampling_rate=16000)
        except Exception as e:
            raise ApiError(400, f"could not decode the audio: {type(e).__name__}")
        duration = len(audio) / 16000
        if duration > STT_MAX_AUDIO_S:
            raise ApiError(413, f"audio is {duration:.0f} s long; the limit is {STT_MAX_AUDIO_S} s")
        with self.turn("stt", job) as waited:
            t = time.perf_counter()
            if self.tts_device == "cuda":
                # A voice note starts a new voice turn: the bot's LLM (Ollama, 4.7 GB) answers it before the
                # next /tts, so the idle TTS model makes room now (back on the GPU in <1 s when needed).
                log.info("voice note arrived - the idle TTS model leaves the GPU for the bot's LLM")
                self._tts_to("cpu")
            device, model = "cpu", self.stt_cpu
            if self.gpu:
                free = self.free_gb() if self._stt_gpu_loaded() else self._make_room(STT_GPU_MIN_FREE_GB, "stt")
                if self._stt_gpu_loaded() or free >= STT_GPU_MIN_FREE_GB:
                    try:
                        self._stt_gpu_ready()
                        device, model = "cuda", self.stt_gpu
                    except Exception as e:
                        log.warning("STT could not load on the GPU (%s) - using the CPU", e)
                        self._stt_gpu_unload()
                else:
                    log.info("STT on the CPU: only %.2f GB VRAM free (need %.1f)", free, STT_GPU_MIN_FREE_GB)
            try:
                try:
                    text, language, prob = self._transcribe(model, audio, job)
                except ApiError:
                    raise
                except Exception as e:
                    if device != "cuda":
                        raise
                    log.warning("STT failed on the GPU (%s) - retrying on the CPU", e)
                    self._stt_gpu_unload()
                    device, model = "cpu", self.stt_cpu
                    text, language, prob = self._transcribe(model, audio, job)
            finally:
                if device == "cuda":
                    self.stt_gpu_last_used = time.monotonic()
                    if STT_GPU_KEEP_S <= 0:
                        self._stt_gpu_unload()
            seconds = time.perf_counter() - t
        log.info("stt %s: %.1f s audio, %s (%.2f), %.2f s (waited %.1f s), %s, text %s",
                 device, duration, language, prob, seconds, waited, _ram(), _snip(text))
        return {"text": text, "language": language, "duration_s": round(duration, 2), "seconds": round(seconds, 2)}

    # ---------------------------------------------------------------- text-to-speech
    def _render(self, text, language, seed=TTS_SEED, job=None):
        """Speak `text` once -> (wav, number of sentences). Raises _Stop when the job's time is up or its client
        left, and re-raises an exception from CosyVoice's LLM thread (a CUDA out-of-memory there would
        otherwise come back as a voice note cut short)."""
        from cosyvoice.utils.common import set_all_random_seed
        set_all_random_seed(seed)
        ctl = self._ctl = _RenderControl(job)
        parts, out = [], None
        try:
            with torch.inference_mode():
                if language == "ko":
                    out = self.tts.inference_zero_shot(text, REF_TEXT, REF_WAV, zero_shot_spk_id="jennie",
                                                       stream=False)
                else:
                    spk = "jennie" if REF_WAV_EN == REF_WAV else "jennie_en"
                    out = self.tts.inference_cross_lingual(text, REF_WAV_EN, zero_shot_spk_id=spk, stream=False)
                for o in out:
                    ctl.raise_if_failed()       # a sentence cut short by a stop or an error is never used
                    parts.append(o["tts_speech"].squeeze(0).float().cpu().numpy())
            ctl.raise_if_failed()
        except Exception as e:
            if out is not None:
                out.close()
            self._forget_render()
            if ctl.error is not None and e is not ctl.error and not isinstance(e, _Stop):
                raise ctl.error from e      # the follow-on error (e.g. no tokens) hides the real cause
            raise
        finally:
            self._ctl = None
        if not parts:
            raise RuntimeError("CosyVoice returned no audio")
        gap = np.zeros(int(TTS_CHUNK_GAP_S * self.sample_rate), dtype=np.float32)
        wav = parts[0]
        for p in parts[1:]:
            wav = np.concatenate([wav, gap, p])
        return wav, len(parts)

    def _cpu_render_fits(self, expected_s, job):
        """503 at once when a CPU render could not finish in the request's time: the bot then sends its text
        answer alone right away instead of waiting for a voice note that would come too late."""
        estimate = TTS_CPU_BASE_S + expected_s * TTS_CPU_RTF
        left = job.left_s() if job is not None else None
        if left is not None and estimate > left:
            where = "no room on the GPU" if self.gpu else "no GPU"
            log.warning("tts: %s, and a CPU render of ~%.1f s of speech would take ~%.0f s with %.0f s left - 503",
                        where, expected_s, estimate, max(left, 0.0))
            raise ApiError(503, f"{where}: a CPU render would take ~{estimate:.0f} s, over the "
                                f"{TTS_MAX_S:.0f} s limit")

    def _render_on(self, device, spoken, language, job):
        """Render on `device`. A CUDA out-of-memory (on any CosyVoice thread) sends the model to the CPU and
        renders there, time permitting. -> (wav, sentences, device used, torch reserved peak GB or None)"""
        try:
            self._tts_to(device)
            if device == "cuda":
                torch.cuda.reset_peak_memory_stats()
            wav, chunks = self._render(spoken, language, job=job)
            return wav, chunks, device, (_gb(torch.cuda.max_memory_reserved()) if device == "cuda" else None)
        except Exception as e:
            if device != "cuda" or not _is_oom(e):
                raise
            kind = type(e).__name__
        # outside the except block, so the traceback (and the GPU tensors its frames hold) can be freed
        gc.collect()
        log.warning("TTS ran out of VRAM on the GPU (%s) - rendering on the CPU instead", kind)
        self._tts_to("cpu")
        self._cpu_render_fits(len(spoken) * SECONDS_PER_CHAR[language], job)
        wav, chunks = self._render(spoken, language, job=job)
        return wav, chunks, "cpu", None

    @staticmethod
    def _length_problem(raw_s, got_s, spoken, expected_s):
        """raw_s: the render as CosyVoice made it; got_s: after polish() trimmed silence and noise. A runaway
        is judged on the raw length: polish() can trim 17 s of mumbling to 7 s that no longer looks long."""
        if max(raw_s, got_s) > RUNAWAY_FACTOR * expected_s + 2.0:
            return "long"       # the language model failed to stop and kept making sound
        if len(spoken) > 20 and got_s < TOO_SHORT_FACTOR * expected_s:
            return "short"      # it stopped early: part of the reply is missing
        return None

    def tts_request(self, text, language, style, job=None):
        spoken = prepare_text(text, language)
        if not spoken.strip(" .,!?"):
            raise ApiError(400, "nothing speakable in the text")
        expected_s = len(spoken) * SECONDS_PER_CHAR[language]
        with self.turn("tts", job) as waited:
            t = time.perf_counter()
            device = "cpu"
            if self.gpu:
                need = TTS_GPU_WORK_GB if self.tts_device == "cuda" else TTS_GPU_NEED_GB
                free = self._make_room(need, "tts")
                if free >= need:
                    device = "cuda"
                else:
                    log.info("TTS on the CPU: only %.2f GB VRAM free (need %.1f)", free, need)
                    self._tts_to("cpu")
            if device == "cpu":
                self._cpu_render_fits(expected_s, job)
            retried = False
            try:
                wav, chunks, device, peak_reserved = self._render_on(device, spoken, language, job)
                first_s = time.perf_counter() - t
                raw_s = len(wav) / self.sample_rate
                wav = polish(wav, self.sample_rate)
                got_s = len(wav) / self.sample_rate
                problem = self._length_problem(raw_s, got_s, spoken, expected_s)
                if problem:
                    left = job.left_s() if job is not None else None
                    why = (f"tts ran {problem} ({raw_s:.1f} s raw, {got_s:.1f} s trimmed, for {len(spoken)} chars; "
                           f"expected ~{expected_s:.1f} s)")
                    if device != "cuda":
                        log.warning("%s - not rendering again on the CPU", why)
                    elif left is not None and left < 1.2 * first_s + 1.0:
                        log.warning("%s - no time left to render again (%.0f s left)", why, left)
                    else:
                        log.warning("%s - rendering again with another seed", why)
                        retried = True
                        try:
                            again, again_chunks = self._render(spoken, language, seed=TTS_SEED + 1, job=job)
                            again_raw_s = len(again) / self.sample_rate
                            again = polish(again, self.sample_rate)
                            # too long: keep the render that rambled less; too short: the one that says more
                            if (again_raw_s < raw_s) if problem == "long" else (len(again) > len(wav)):
                                wav, chunks, raw_s = again, again_chunks, again_raw_s
                                got_s = len(wav) / self.sample_rate
                        except Exception as e:
                            if isinstance(e, _Stop) and job is not None and job.gone.is_set():
                                raise
                            log.warning("the second render failed (%s: %s) - keeping the first", type(e).__name__, e)
                    if self._length_problem(raw_s, got_s, spoken, expected_s) == "short":
                        raise ApiError(503, "speech came out cut short - render failed")
            except _Stop as e:
                log.warning("tts %s %s/%s: stopped after %.1f s (waited %.1f s): %s; %d chars, text %s", device,
                            language, style, time.perf_counter() - t, waited, e, len(spoken), _snip(text))
                raise ApiError(503, f"speech stopped: {e}")
            finally:
                self.tts_last_used = time.monotonic()
            render_s = time.perf_counter() - t
            ogg, duration = encode_ogg_opus(wav, self.sample_rate)
            seconds = time.perf_counter() - t
        log.info("tts %s %s/%s: %d chars in %d part(s) -> %.1f s audio, %d KB, render %.1f s, total %.1f s "
                 "(waited %.1f s)%s%s, %s, text %s", device, language, style, len(spoken), chunks, duration,
                 len(ogg) // 1024, render_s, seconds, waited, ", rendered twice" if retried else "",
                 f", torch reserved peak {peak_reserved:.2f} GB" if peak_reserved is not None else "", _ram(),
                 _snip(text))
        return ogg, duration, seconds

    # ---------------------------------------------------------------- idle offload
    def idle_loop(self):
        while True:
            time.sleep(IDLE_CHECK_S)
            try:
                now = time.monotonic()
                tts_idle = self.tts_device == "cuda" and now - self.tts_last_used >= TTS_IDLE_S
                stt_idle = self._stt_gpu_loaded() and now - self.stt_gpu_last_used >= max(STT_GPU_KEEP_S, 1)
                if not (tts_idle or stt_idle) or not self.lock.acquire(blocking=False):
                    continue
                try:
                    if tts_idle and self.tts_device == "cuda":
                        log.info("TTS idle for %.0f s - leaving the GPU", now - self.tts_last_used)
                        self._tts_to("cpu")
                    if stt_idle:
                        self._stt_gpu_unload()
                        log.info("STT idle - weights left the GPU (%.2f GB VRAM free)", self.free_gb())
                    torch.cuda.empty_cache()
                finally:
                    self.lock.release()
            except Exception:
                log.exception("idle offload failed")


engine = Engine()

# ================================================================ HTTP API
_BODY_LIMITS = {"/tts": TTS_BODY_MAX, "/stt": STT_MAX_BYTES + 1024 * 1024}   # + room for the multipart framing


class _LocalClientsOnly:
    """Only the bot on this PC may use the service. Listening on 127.0.0.1 is not enough on its own: any web
    page open in a browser here could POST to it (text/plain and multipart need no CORS preflight) or reach
    it through DNS rebinding. So, before any body is read, refuse:
      * a Host header other than 127.0.0.1:8765 / localhost:8765 (DNS rebinding),
      * any request carrying an Origin header (browsers send one on every POST; httpx and PowerShell do not),
      * a POST without Content-Length, or with more than its route's limit (the body is never read),
      * a /tts whose Content-Type is not application/json."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        refusal = self._refusal(scope) if scope["type"] == "http" else None
        if refusal is None:
            await self.app(scope, receive, send)
            return
        status, message = refusal
        log.warning("refused %s %s (HTTP %d): %s", scope.get("method"), scope.get("path"), status, message)
        await JSONResponse({"error": message}, status_code=status, headers={"Connection": "close"})(
            scope, receive, send)

    @staticmethod
    def _refusal(scope):
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or ()}
        host = headers.get("host", "").strip().lower()
        if host not in LOCAL_HOSTS:
            return 403, f"Host must be {HOST}:{PORT} or localhost:{PORT}"
        if "origin" in headers:
            return 403, "requests from web pages are not accepted"
        if scope.get("method") == "POST":
            length = headers.get("content-length", "").strip()
            if not length.isdigit():
                return 411, "Content-Length is required"
            limit = _BODY_LIMITS.get(scope.get("path"), TTS_BODY_MAX)
            if int(length) > limit:
                return 413, f"request body over {limit // 1024} KB"
            content_type = headers.get("content-type", "").split(";")[0].strip().lower()
            if scope.get("path") == "/tts" and content_type != "application/json":
                return 415, "Content-Type must be application/json"
        return None


app = FastAPI(title="Jennie voice", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(_LocalClientsOnly)


def _error(status, message):
    return JSONResponse({"error": message}, status_code=status)


@app.exception_handler(ApiError)
async def _api_error(request, exc):
    return _error(exc.status, exc.message)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request, exc):
    return _error(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def _validation_error(request, exc):
    problems = "; ".join(f"{'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors())
    return _error(422, f"invalid request: {problems}")


async def _watch_client(request, job):
    """Marks the job when its client hangs up (e.g. the bot's timeout), so the work stops and frees the lock."""
    try:
        while not await request.is_disconnected():
            await asyncio.sleep(0.5)
        job.gone.set()
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


async def _job(request, job, fn, *args):
    """Run a blocking job in the thread pool while watching the client; anything unexpected becomes a JSON 500."""
    watcher = asyncio.create_task(_watch_client(request, job))
    try:
        return await run_in_threadpool(fn, *args, job)
    except ApiError:
        raise
    except Exception as e:
        log.exception("%s failed", job.what)
        raise ApiError(500, f"{job.what} failed: {type(e).__name__}: {str(e)[:200]}")
    finally:
        watcher.cancel()


_hung_logged = [0.0]      # time.monotonic() of the last "hung" log line (at most one a minute)


@app.get("/health")
async def health():
    busy = engine.busy_s()
    body = {"ok": True, "stt": STT_MODEL if engine.gpu else STT_CPU_MODEL, "tts": "cosyvoice2",
            "device": "cuda" if engine.gpu else "cpu", "tts_on_gpu": engine.tts_device == "cuda",
            "busy_s": round(busy, 1)}
    if busy > HUNG_AFTER_S:
        # nothing legitimate holds the lock this long (a /tts gives up after JENNIE_TTS_MAX_S): a CUDA or
        # driver stall. Not ok, so the watchdog restarts the service.
        if time.monotonic() - _hung_logged[0] >= 60:
            _hung_logged[0] = time.monotonic()
            log.error("/health: one %s request has held the lock for %.0f s - reporting not ok",
                      engine.busy_what, busy)
        body.update(ok=False, error=f"hung: one {engine.busy_what} request has held the lock for {busy:.0f} s")
        return JSONResponse(body, status_code=503)
    return body


@app.post("/stt")
async def stt(request: Request, audio: UploadFile = File(...)):
    data = await audio.read(STT_MAX_BYTES + 1)
    if not data:
        raise ApiError(400, "the audio file is empty")
    if len(data) > STT_MAX_BYTES:
        raise ApiError(413, f"audio file larger than {STT_MAX_BYTES // (1024 * 1024)} MB")
    return await _job(request, Job("stt"), engine.stt, data)


@app.post("/tts")
async def tts(request: Request):
    job = Job("tts", TTS_MAX_S)      # the clock starts when the request arrives, lock wait included
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, 'body must be JSON: {"text": ..., "language": "en"|"ko", "style": "aegyo"|"neutral"}')
    if not isinstance(body, dict):
        raise ApiError(400, "body must be a JSON object")
    text, language, style = body.get("text"), body.get("language"), body.get("style", "neutral")
    if not isinstance(text, str) or not text.strip():
        raise ApiError(400, '"text" must be a non-empty string')
    if len(text) > TTS_MAX_CHARS:
        raise ApiError(413, f"text is {len(text)} characters; the limit is {TTS_MAX_CHARS}")
    if language not in ("en", "ko"):
        raise ApiError(400, '"language" must be "en" or "ko"')
    if style not in ("aegyo", "neutral"):
        raise ApiError(400, '"style" must be "aegyo" or "neutral"')
    ogg, duration, seconds = await _job(request, job, engine.tts_request, text, language, style)
    return Response(ogg, media_type="audio/ogg",
                    headers={"X-Duration": f"{duration:.2f}", "X-Seconds": f"{seconds:.2f}"})


def main():
    # _listener: 127.0.0.1:8765, bound at import time before the heavy imports (see _claim_port)
    log.info("starting (pid %d) on %s:%d", os.getpid(), HOST, PORT)
    try:
        engine.load()
    except Exception:
        log.exception("startup failed")
        return 1
    threading.Thread(target=engine.idle_loop, name="idle-offload", daemon=True).start()
    import uvicorn
    config = uvicorn.Config(app, host=HOST, port=PORT, log_config=None, access_log=False, workers=1)
    uvicorn.Server(config).run(sockets=[_listener])
    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
