r"""Real end-to-end latency of fast Jennie (the code in C:\Hangeul\BOT, not deployed yet), measured
without touching the bot that runs in production.

The harness imports src.bot.voice and src.bot.telegram_bot from C:\Hangeul\BOT into THIS process,
with OLLAMA_MODEL=qwen3:4b-instruct and JENNIE_VOICE_ENABLED=true set in its own environment
(pydantic settings read environment variables before .env; .env is never written), and drives
voice.handle_voice_message with fake PTB Update / Context / Bot objects:

  * the fake bot records every send_message / send_voice / edit / delete with its time and sends
    NOTHING to Telegram; the fake get_file returns the bytes of a local OGG;
  * the REAL voice service (127.0.0.1:8765), the REAL Ollama (127.0.0.1:11434) and the REAL portal
    reads (the bot's own commands: GETs plus the existing login) are used. A guard on httpx refuses
    every other host, and every portal request other than a GET or the login POST;
  * the chat is a made-up chat id, allowed through TELEGRAM_AUTHORIZED_CHAT_IDS in this process only.

The test voice notes are the questions rendered by the voice service's /tts (cached in latency_notes).
The brain is warmed first; then the four notes run in order, twice, in one chat (so the follow-up
"그럼 어제는?" has its history). Per run: time to the filler clip, to "heard", to the full text answer
and to Jennie's voice note (Telegram's own network time is not included, since nothing is sent; see
--tg-rtt), the voice module's per-stage timing line, every Ollama / voice-service / portal request,
the voice service's own log lines (STT / TTS device, render time, VRAM) and nvidia-smi.

At the end the brain is unloaded again (the production bot does not use it yet), unless --keep-loaded.
Results: latency_results.json and latency_harness.log beside this file. Student names stay out of
both: only the first lines of each written answer are kept.

Run with the bot's venv:
    C:\Hangeul\BOT\.venv\Scripts\python.exe C:\Hangeul\JARVIS\brain-trial\latency_harness.py
"""
import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
BOT_ROOT = Path(r"C:\Hangeul\BOT")
NOTES_DIR = HERE / "latency_notes"
RESULTS_FILE = HERE / "latency_results.json"
LOG_FILE = HERE / "latency_harness.log"
SERVICE_LOG = Path(r"C:\Hangeul\JARVIS\jennie_voice\jennie_voice.log")
PROD_LOG = BOT_ROOT / "hangeul_bot.log"
BRAIN = "qwen3:4b-instruct"
FAKE_CHAT_ID = 900000001        # not a real Telegram chat: nothing is ever sent anywhere
VOICE_URL = "http://127.0.0.1:8765"
OLLAMA_URL = "http://127.0.0.1:11434"

NOTES = (
    ("ko_today", "ko", "제니야, 오늘 서류 검증된 학생 몇 명이야?"),
    ("ko_followup", "ko", "그럼 어제는?"),
    ("en_deadlines", "en", "Jennie, what deadlines are coming up?"),
    ("en_thanks", "en", "Thanks Jennie, you're the best!"),
)
RUN_TIMEOUT_S = 300.0

# Before anything from the bot is imported: pydantic settings read these first (this process only).
os.environ["OLLAMA_MODEL"] = BRAIN
os.environ["JENNIE_VOICE_ENABLED"] = "true"
os.environ["TELEGRAM_AUTHORIZED_CHAT_IDS"] = str(FAKE_CHAT_ID)
sys.path.insert(0, str(BOT_ROOT))

import httpx  # noqa: E402  (the bot's venv)


# --------------------------------------------------------------------------- what happened, and when

class Recorder:
    """Times are seconds since the voice note arrived (begin())."""

    def __init__(self):
        self.t0 = time.perf_counter()
        self.events = []
        self.requests = []

    def begin(self):
        self.t0 = time.perf_counter()
        self.events, self.requests = [], []

    def now(self) -> float:
        return round(time.perf_counter() - self.t0, 3)

    def event(self, kind, **fields):
        self.events.append({"t": self.now(), "kind": kind, **fields})


REC = Recorder()


def _ollama_label(payload: dict) -> str:
    if payload.get("format") is not None:
        return "route"
    messages = payload.get("messages")
    if messages:
        system = next((str(m.get("content") or "") for m in messages if m.get("role") == "system"), "")
        if "KOREAN voice note" in system:
            return "reply-ko"
        if "English voice note" in system:
            return "reply-en"
        if "evening update" in system:
            return "brief"
        return "chat"
    if "prompt" not in payload:
        return "unload"
    return "load" if payload.get("prompt") == "" else "generate"


def _record_request(kind, request, response, started, seconds, error=None):
    entry = {"kind": kind, "method": request.method, "path": request.url.path, "t": started,
             "seconds": round(seconds, 3)}
    if error:
        entry["error"] = error
    if response is not None:
        entry["status"] = response.status_code
    try:
        if kind == "ollama" and request.url.path in ("/api/chat", "/api/generate"):
            payload = json.loads(request.content or b"{}")
            entry["label"] = _ollama_label(payload)
            entry["num_ctx"] = (payload.get("options") or {}).get("num_ctx")
            entry["keep_alive"] = payload.get("keep_alive")
            if response is not None and response.status_code == 200:
                data = response.json()
                for key in ("load_duration", "prompt_eval_duration", "eval_duration", "total_duration"):
                    if data.get(key) is not None:
                        entry[key.replace("duration", "s")] = round(data[key] / 1e9, 3)
                entry["prompt_tokens"] = data.get("prompt_eval_count")
                entry["output_tokens"] = data.get("eval_count")
        elif kind == "voice" and request.url.path == "/tts":
            payload = json.loads(request.content or b"{}")
            entry["text"] = payload.get("text")
            entry["language"] = payload.get("language")
            if response is not None and response.status_code == 200:
                entry["audio_s"] = float(response.headers.get("X-Duration") or 0)
                entry["service_s"] = float(response.headers.get("X-Seconds") or 0)
        elif kind == "voice" and request.url.path == "/stt" and response is not None \
                and response.status_code == 200:
            data = response.json()
            entry["service_s"] = data.get("seconds")
            entry["language"] = data.get("language")
            entry["audio_s"] = data.get("duration_s")
    except Exception as e:     # the record is best effort; the request itself went through
        entry["record_error"] = f"{type(e).__name__}: {e}"
    REC.requests.append(entry)


# --------------------------------------------------------------------------- guard: read-only, local only

_PORTAL_DOMAIN = None       # set once the bot's settings are imported
_LOCAL = {("127.0.0.1", 11434): "ollama", ("127.0.0.1", 8765): "voice"}
_original_send = httpx.AsyncClient.send


class Refused(RuntimeError):
    """The harness refused a request (not local, or not a read on the portal)."""


async def _guarded_send(self, request, *args, **kwargs):
    url = request.url
    kind = _LOCAL.get((url.host, url.port))
    if kind is None:
        host = (url.host or "").lower()
        if not (_PORTAL_DOMAIN and (host == _PORTAL_DOMAIN or host.endswith("." + _PORTAL_DOMAIN))):
            raise Refused(f"harness: request to {url.host} refused (only 127.0.0.1 and the portal)")
        if request.method != "GET" and not (request.method == "POST" and url.path.endswith("/login.php")):
            raise Refused(f"harness: {request.method} {url.path} on the portal refused (read-only)")
        kind = "portal"
    started = REC.now()
    t = time.perf_counter()
    try:
        response = await _original_send(self, request, *args, **kwargs)
    except Exception as e:
        _record_request(kind, request, None, started, time.perf_counter() - t, error=type(e).__name__)
        raise
    _record_request(kind, request, response, started, time.perf_counter() - t)
    return response


httpx.AsyncClient.send = _guarded_send

from src.config import settings  # noqa: E402
from src.bot import telegram_bot, voice  # noqa: E402,F401  (telegram_bot: the commands the notes run)
from src.llm.ollama_client import ollama_client  # noqa: E402
from src.scraper.client import admin_client  # noqa: E402

_PORTAL_DOMAIN = (httpx.URL(settings.HANGEUL_BASE_URL).host or "").lower().removeprefix("www.") or None


# --------------------------------------------------------------------------- fake Telegram

class FakeMessage:
    _next_id = 1

    def __init__(self, chat_id, text=None, voice=None, tg_rtt=0.0):
        self.chat_id = chat_id
        self.chat = SimpleNamespace(id=chat_id, type="private")
        self.text = text
        self.caption = None
        self.voice = voice
        self.audio = None
        self.deleted = False
        self.tg_rtt = tg_rtt
        self.message_id = FakeMessage._next_id
        FakeMessage._next_id += 1

    async def reply_text(self, text, parse_mode=None, **kwargs):
        if self.tg_rtt:
            await asyncio.sleep(self.tg_rtt)
        sent = FakeMessage(self.chat_id, text=text, tg_rtt=self.tg_rtt)
        REC.event("text", id=sent.message_id, text=str(text))
        return sent

    async def edit_text(self, text, parse_mode=None, **kwargs):
        if self.tg_rtt:
            await asyncio.sleep(self.tg_rtt)
        self.text = text
        REC.event("edit", id=self.message_id, text=str(text))
        return self

    async def delete(self, *args, **kwargs):
        if self.tg_rtt:
            await asyncio.sleep(self.tg_rtt)
        self.deleted = True
        REC.event("delete", id=self.message_id)
        return True


class FakeFile:
    def __init__(self, data: bytes):
        self.data = data

    async def download_as_bytearray(self):
        return bytearray(self.data)


class FakeVoice:
    def __init__(self, data: bytes, duration: float):
        self.data = data
        self.duration = max(1, int(round(duration)))
        self.file_size = len(data)
        self.mime_type = "audio/ogg"
        self.file_id = f"fake-note-{id(self)}"

    async def get_file(self):
        return FakeFile(self.data)


class FakeBot:
    """Records; sends nothing. send_voice answers like Telegram (with a file id), so the filler
    clip is re-sent by file id the second time, as in production."""

    def __init__(self, filler_audio: set, tg_rtt=0.0):
        self.filler_audio = filler_audio
        self.tg_rtt = tg_rtt
        self.sent = 0

    async def send_voice(self, chat_id, voice, duration=None, filename=None, **kwargs):
        if self.tg_rtt:
            await asyncio.sleep(self.tg_rtt)
        self.sent += 1
        filler = isinstance(voice, str) or bytes(voice) in self.filler_audio
        REC.event("voice", filler=filler, duration=duration, by_file_id=isinstance(voice, str),
                  bytes=None if isinstance(voice, str) else len(voice))
        return SimpleNamespace(voice=SimpleNamespace(file_id=f"fake-file-{self.sent}"))

    async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
        if self.tg_rtt:
            await asyncio.sleep(self.tg_rtt)
        sent = FakeMessage(chat_id, text=text, tg_rtt=self.tg_rtt)
        REC.event("text", id=sent.message_id, text=str(text), via="bot.send_message")
        return sent

    async def send_chat_action(self, chat_id, action, **kwargs):
        REC.event("chat_action", action=str(action))


def fake_update(voice_note: FakeVoice, tg_rtt: float):
    message = FakeMessage(FAKE_CHAT_ID, voice=voice_note, tg_rtt=tg_rtt)
    return SimpleNamespace(message=message, effective_message=message, callback_query=None,
                           effective_chat=SimpleNamespace(id=FAKE_CHAT_ID, type="private"),
                           effective_user=SimpleNamespace(id=FAKE_CHAT_ID, first_name="Harness"),
                           update_id=message.message_id)


# --------------------------------------------------------------------------- logs, GPU, Ollama

class Lines(logging.Handler):
    """The bot's own log lines ("hangeul.*") of the current run."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.records = []

    def emit(self, record):
        try:
            self.records.append((record.levelname, record.name, record.getMessage()))
        except Exception:
            pass


LINES = Lines()


def setup_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(fh)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter("  [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(console)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("hangeul").addHandler(LINES)


def smi() -> dict:
    """nvidia-smi: MiB used / free on the card."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.free,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True,
                             timeout=10).stdout.strip().splitlines()[0]
        used, free, total = (int(x) for x in out.split(","))
        return {"used_mib": used, "free_mib": free, "total_mib": total}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


async def vram_peak(state: dict, every_s=0.5):
    """Samples nvidia-smi until cancelled; keeps the highest 'used'."""
    try:
        while True:
            now = await asyncio.to_thread(smi)
            if "used_mib" in now and now["used_mib"] > state.get("peak_used_mib", 0):
                state["peak_used_mib"] = now["used_mib"]
            await asyncio.sleep(every_s)
    except asyncio.CancelledError:
        pass


async def ollama_ps() -> list:
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/ps")
        return [{"name": m.get("name"), "size_gib": round((m.get("size") or 0) / 2 ** 30, 2),
                 "vram_gib": round((m.get("size_vram") or 0) / 2 ** 30, 2),
                 "num_ctx": m.get("context_length"), "expires_at": m.get("expires_at")}
                for m in resp.json().get("models") or []]
    except Exception as e:
        return [{"error": f"{type(e).__name__}: {e}"}]


def file_mark(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def read_since(path: Path, mark: int) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(mark)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


_SVC_PATTERNS = (
    ("stt", re.compile(r"stt (?P<device>cuda|cpu): (?P<audio_s>[\d.]+) s audio, (?P<language>\w+) \((?P<prob>[\d.]+)\), "
                       r"(?P<seconds>[\d.]+) s \(waited (?P<waited>[\d.]+) s\)")),
    ("tts", re.compile(r"tts (?P<device>cuda|cpu) (?P<language>\w+)/(?P<style>\w+): (?P<chars>\d+) chars in (?P<parts>\d+) "
                       r"part\(s\) -> (?P<audio_s>[\d.]+) s audio, \d+ KB, render (?P<render_s>[\d.]+) s, total "
                       r"(?P<seconds>[\d.]+) s \(waited (?P<waited>[\d.]+) s\)(?P<twice>, rendered twice)?"
                       r"(?:, torch reserved peak (?P<peak_gb>[\d.]+) GB)?")),
    ("tts_on_cpu", re.compile(r"TTS on the CPU: only (?P<free_gb>[\d.]+) GB VRAM free \(need (?P<need_gb>[\d.]+)\)")),
    ("stt_on_cpu", re.compile(r"STT on the CPU: only (?P<free_gb>[\d.]+) GB VRAM free \(need (?P<need_gb>[\d.]+)\)")),
    ("tts_move", re.compile(r"TTS model -> (?P<device>cuda|cpu) in (?P<seconds>[\d.]+) s \((?P<free_gb>[\d.]+) GB VRAM free")),
    ("tts_oom", re.compile(r"TTS ran out of VRAM")),
    ("tts_rerender", re.compile(r"tts ran (?P<problem>long|short)")),
    ("evict_for_llm", re.compile(r"the idle TTS model leaves the GPU")),
    ("made_room", re.compile(r"(?:unloaded the idle STT|moved the idle TTS) model .*?: (?P<free_gb>[\d.]+) GB free")),
)


def service_events(text: str) -> list:
    """The voice service's log lines, as fields only (never the words)."""
    found = []
    for line in text.splitlines():
        stamp = line[11:23] if len(line) > 23 else ""
        for kind, pattern in _SVC_PATTERNS:
            m = pattern.search(line)
            if m:
                fields = {k: v for k, v in m.groupdict().items() if v is not None}
                found.append({"at": stamp, "kind": kind, **fields})
                break
    return found


# --------------------------------------------------------------------------- the test notes

async def make_notes() -> dict:
    """Each question rendered once by the voice service's /tts (neutral style), cached by its text."""
    NOTES_DIR.mkdir(exist_ok=True)
    manifest_path = NOTES_DIR / "notes.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    notes = {}
    async with httpx.AsyncClient(base_url=VOICE_URL, timeout=httpx.Timeout(180.0, connect=5.0),
                                 trust_env=False) as client:
        for name, language, text in NOTES:
            path = NOTES_DIR / f"{name}.ogg"
            entry = manifest.get(name) or {}
            if entry.get("text") != text or not path.is_file():
                t = time.perf_counter()
                resp = await client.post("/tts", json={"text": text, "language": language, "style": "neutral"})
                if resp.status_code != 200 or not resp.content.startswith(b"OggS"):
                    raise RuntimeError(f"/tts for {name} answered HTTP {resp.status_code}: {resp.text[:200]}")
                path.write_bytes(resp.content)
                entry = {"text": text, "language": language,
                         "duration_s": float(resp.headers.get("X-Duration") or 0),
                         "render_s": round(time.perf_counter() - t, 2)}
                manifest[name] = entry
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"  rendered {name}.ogg: {entry['duration_s']:.1f} s of speech in {entry['render_s']:.1f} s")
            notes[name] = {**entry, "data": path.read_bytes(), "bytes": path.stat().st_size}
    return notes


async def preflight_stt(note: dict) -> dict:
    """One /stt outside the runs: moves an idle TTS model off the GPU (as a voice note does) before the
    brain loads, so the brain lands on the GPU as it does in production after a note."""
    t = time.perf_counter()
    stt = await voice.transcribe(note["data"])
    return {"seconds": round(time.perf_counter() - t, 2), "language": stt["language"], "text": stt["text"]}


# --------------------------------------------------------------------------- one voice note

def _first_lines(text: str, n=2, width=110) -> list:
    lines = []
    for line in str(text or "").splitlines():
        line = re.sub(r"[*_`]", "", line).strip()
        if line:
            lines.append(line[:width])
        if len(lines) >= n:
            break
    return lines


_SUMMARY_RE = re.compile(r"Voice note from [^:]+: (?P<audio>[\d.]+)s audio, (?P<language>[^,]+), (?P<ran>.+?) \| "
                         r"(?P<stages>.+)$")


def _stages(summary: str) -> dict:
    stages = {}
    for part in summary.split(", "):
        m = re.match(r"^(?P<name>.+?) \+?(?P<s>[\d.]+)s$", part.strip())
        if m:
            stages[m.group("name")] = float(m.group("s"))
    return stages


def analyse(events: list) -> dict:
    heard = next((e for e in events if e["kind"] == "text" and e["text"].startswith("🎧 heard:")), None)
    fillers = [e for e in events if e["kind"] == "voice" and e["filler"]]
    replies = [e for e in events if e["kind"] == "voice" and not e["filler"]]
    messages = {}
    for e in events:
        if e["kind"] == "text":
            messages[e["id"]] = {"t": e["t"], "text": e["text"], "deleted": False}
        elif e["kind"] == "edit" and e["id"] in messages:
            messages[e["id"]].update(t=e["t"], text=e["text"])
        elif e["kind"] == "delete" and e["id"] in messages:
            messages[e["id"]]["deleted"] = True
    answer = [m for m in messages.values() if not m["deleted"] and not m["text"].startswith("🎧 heard:")
              and not m["text"].startswith("🔇")]
    return {
        "t_filler_s": fillers[0]["t"] if fillers else None,
        "filler_by_file_id": fillers[0]["by_file_id"] if fillers else None,
        "t_heard_s": heard["t"] if heard else None,
        "heard": heard["text"].replace("🎧 heard:", "").strip() if heard else None,
        "t_text_s": max(m["t"] for m in answer) if answer else None,
        "t_first_text_s": min(m["t"] for m in answer) if answer else None,
        "text_messages": len(answer),
        "text_chars": sum(len(m["text"]) for m in answer),
        "text_head": [line for m in answer for line in _first_lines(m["text"])],
        "t_voice_s": replies[0]["t"] if replies else None,
        "voice_duration_s": replies[0]["duration"] if replies else None,
        "unavailable_note": any(m["text"].startswith("🔇") for m in messages.values()),
    }


async def one_run(n: int, pass_no: int, name: str, notes: dict, bot: FakeBot, user_data: dict,
                  tg_rtt: float) -> dict:
    note = notes[name]
    svc_mark = file_mark(SERVICE_LOG)
    LINES.records.clear()
    vram = {"before": smi()}
    ps_before = await ollama_ps()
    filler_language = voice.last_language(FAKE_CHAT_ID)
    update = fake_update(FakeVoice(note["data"], note["duration_s"]), tg_rtt)
    context = SimpleNamespace(bot=bot, user_data=user_data, chat_data={}, bot_data={}, args=None)

    sampler = asyncio.create_task(vram_peak(vram))
    REC.begin()
    t = time.perf_counter()
    try:
        await asyncio.wait_for(voice.handle_voice_message(update, context), RUN_TIMEOUT_S)
    except asyncio.TimeoutError:
        REC.event("harness_timeout")
    handler_s = time.perf_counter() - t
    pending = [task for task in list(voice._tasks) if not task.done()]
    if pending:
        await asyncio.wait(pending, timeout=30)
    sampler.cancel()
    await asyncio.gather(sampler, return_exceptions=True)
    vram["after"] = smi()
    await asyncio.sleep(0.3)    # the service writes its log line right after answering
    svc = service_events(read_since(SERVICE_LOG, svc_mark))

    summary = next((msg for level, logger_name, msg in LINES.records if "Voice note from" in msg), "")
    m = _SUMMARY_RE.search(summary)
    result = {
        "run": n, "pass": pass_no, "note": name, "utterance": note["text"], "note_audio_s": note["duration_s"],
        "filler_language": filler_language,
        **analyse(REC.events),
        "handler_s": round(handler_s, 3),
        "language": m.group("language") if m else None,
        "ran": m.group("ran") if m else None,
        "stages_line": m.group("stages") if m else summary,
        "stages": _stages(m.group("stages")) if m else {},
        "spoken": next((r.get("text") for r in REC.requests if r["kind"] == "voice" and r["path"] == "/tts"), None),
        "llm_calls": [r for r in REC.requests if r["kind"] == "ollama" and r["path"] in ("/api/chat", "/api/generate")],
        "llm_health_checks": sum(1 for r in REC.requests if r["kind"] == "ollama" and r["path"] == "/api/tags"),
        "portal_requests": [{k: r.get(k) for k in ("method", "path", "status", "t", "seconds", "error")}
                            for r in REC.requests if r["kind"] == "portal"],
        "voice_requests": [{k: v for k, v in r.items() if k not in ("kind",)}
                           for r in REC.requests if r["kind"] == "voice"],
        "service_log": svc,
        "tts_device": next((e["device"] for e in svc if e["kind"] == "tts"), None),
        "stt_device": next((e["device"] for e in svc if e["kind"] == "stt"), None),
        "vram": vram,
        "ollama_before": ps_before,
        "ollama_after": await ollama_ps(),
        "bot_warnings": [f"{level} {logger_name}: {msg}"[:300] for level, logger_name, msg in LINES.records
                         if level in ("WARNING", "ERROR", "CRITICAL")],
        "timeline": [{k: (v[:60] if isinstance(v, str) else v) for k, v in e.items()
                      if not (k == "text" and not str(v).startswith(("🎧", "🔇", "⏳", "🤔", "💬")))}
                     for e in REC.events],
    }
    return result


def _fmt(value, width=6):
    return f"{value:>{width}.2f}" if isinstance(value, (int, float)) else f"{'-':>{width}}"


def print_run(r: dict):
    print(f"\n#{r['run']} pass {r['pass']} {r['note']}: {r['utterance']}")
    print(f"   heard    : {r['heard']}")
    print(f"   ran      : {r['ran']}   ({r['language']}; filler in {r['filler_language']})")
    print(f"   spoken   : {r['spoken']}")
    print(f"   text     : {' | '.join(r['text_head'][:3])}")
    print(f"   times    : filler {_fmt(r['t_filler_s'])} s  heard {_fmt(r['t_heard_s'])} s  "
          f"text {_fmt(r['t_text_s'])} s  voice {_fmt(r['t_voice_s'])} s  (voice note {r['voice_duration_s']} s)")
    print(f"   stages   : {r['stages_line']}")
    for c in r["llm_calls"]:
        print(f"   llm      : {c.get('label', '?'):9} {c['seconds']:.2f} s (load {c.get('load_s', 0):.2f}, prompt "
              f"{c.get('prompt_tokens')} tok {c.get('prompt_eval_s', 0):.2f} s, out {c.get('output_tokens')} tok "
              f"{c.get('eval_s', 0):.2f} s, num_ctx {c.get('num_ctx')})")
    for p in r["portal_requests"]:
        print(f"   portal   : {p['method']} {p['path']} {p.get('status')} {p['seconds']:.2f} s at +{p['t']:.2f}")
    for e in r["service_log"]:
        print(f"   service  : {json.dumps(e, ensure_ascii=False)}")
    print(f"   vram     : before {r['vram']['before'].get('used_mib')} MiB, peak {r['vram'].get('peak_used_mib')} MiB, "
          f"after {r['vram']['after'].get('used_mib')} MiB; brain {r['ollama_after']}")
    for w in r["bot_warnings"]:
        print(f"   warning  : {w}")


def overview(runs: list) -> dict:
    stage_names = []
    for r in runs:
        for name in r["stages"]:
            if name not in stage_names and name != "total":
                stage_names.append(name)
    per_stage = {}
    for name in stage_names:
        values = [r["stages"][name] for r in runs if name in r["stages"]]
        per_stage[name] = {"mean_s": round(sum(values) / len(values), 2), "max_s": round(max(values), 2),
                           "n": len(values)}
    to_voice = [r["t_voice_s"] for r in runs if r["t_voice_s"] is not None]
    total_stage = sum(v["mean_s"] for k, v in per_stage.items() if k not in ("filler",))
    shares = {k: round(100 * v["mean_s"] / total_stage, 1) for k, v in per_stage.items()
              if k != "filler" and total_stage}
    return {
        "per_stage": per_stage,
        "stage_share_pct": dict(sorted(shares.items(), key=lambda kv: -kv[1])),
        "t_voice_mean_s": round(sum(to_voice) / len(to_voice), 2) if to_voice else None,
        "t_voice_max_s": max(to_voice) if to_voice else None,
        "tts_devices": [r["tts_device"] for r in runs],
        "stt_devices": [r["stt_device"] for r in runs],
    }


# --------------------------------------------------------------------------- main

async def main(args) -> int:
    setup_logging()
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    prod_mark = file_mark(PROD_LOG)
    print(f"fast-Jennie latency harness, {started}; brain {settings.OLLAMA_MODEL}, num_ctx {settings.OLLAMA_NUM_CTX}, "
          f"voice {settings.JENNIE_VOICE_URL}, portal {_PORTAL_DOMAIN}")
    if settings.OLLAMA_MODEL != BRAIN:
        print(f"OLLAMA_MODEL is {settings.OLLAMA_MODEL}, not {BRAIN}: stopping.")
        return 2
    if not telegram_bot.is_authorized(fake_update(FakeVoice(b"OggS", 1), 0.0)):
        print("the fake chat is not authorised: stopping.")
        return 2

    results = {"started": started, "brain": settings.OLLAMA_MODEL, "num_ctx": settings.OLLAMA_NUM_CTX,
               "tg_rtt_s": args.tg_rtt, "setup": {}, "runs": []}
    async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
        results["setup"]["voice_health_before"] = (await client.get(f"{VOICE_URL}/health")).json()
    results["setup"]["ollama_before"] = await ollama_ps()
    results["setup"]["vram_idle"] = smi()
    print(f"voice service: {results['setup']['voice_health_before']}")
    print(f"ollama loaded: {results['setup']['ollama_before']}; GPU {results['setup']['vram_idle']}")

    try:
        print("test notes:")
        notes = await make_notes()
        results["setup"]["notes"] = {k: {kk: vv for kk, vv in v.items() if kk != "data"} for k, v in notes.items()}
        pre = await preflight_stt(notes[NOTES[0][0]])
        results["setup"]["preflight_stt"] = pre
        print(f"  preflight /stt of {NOTES[0][0]}: {pre['seconds']} s, {pre['language']}: {pre['text']}")

        print("warming the brain:")
        warm = await ollama_client.warm_up()
        if warm.get("loaded") and not warm.get("on_gpu"):
            print(f"  only partly on the GPU ({warm}); loading again")
            await ollama_client.unload()
            await asyncio.sleep(5)
            warm = await ollama_client.warm_up()
        t = time.perf_counter()
        hello = await ollama_client.chat([{"role": "user", "content": "Say hello in one word."}], num_predict=8)
        warm["first_chat_s"] = round(time.perf_counter() - t, 2)
        warm["first_chat_ok"] = bool(hello)
        warm["vram"] = smi()
        results["setup"]["warm_up"] = warm
        print(f"  {warm}")
        if not warm.get("on_gpu"):
            print("  WARNING: the brain is not all on the GPU; the numbers below are not representative")

        filler_audio = set()
        for path in voice.FILLER_DIR.glob("*.ogg"):
            filler_audio.add(path.read_bytes())
        results["setup"]["filler_clips"] = len(filler_audio)
        results["setup"]["fillers_missing"] = [n for _, n, _ in voice.missing_fillers()]
        bot = FakeBot(filler_audio, args.tg_rtt)
        user_data = {}      # one chat: context.user_data lives across the notes, as in PTB

        n = 0
        for pass_no in range(1, args.passes + 1):
            for name, _, _ in NOTES:
                n += 1
                if n > 1:
                    await asyncio.sleep(args.gap)
                r = await one_run(n, pass_no, name, notes, bot, user_data, args.tg_rtt)
                results["runs"].append(r)
                print_run(r)
                RESULTS_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

        results["overview"] = overview(results["runs"])
        print("\noverview:")
        print(json.dumps(results["overview"], ensure_ascii=False, indent=1))
    finally:
        prod = read_since(PROD_LOG, prod_mark)
        results["production_log_during_run"] = {
            "lines": len(prod.splitlines()),
            "voice_notes": sum(1 for line in prod.splitlines() if "Voice note from" in line),
            "llm_lines": sum(1 for line in prod.splitlines() if "hangeul.llm" in line or "Ollama" in line),
        }
        results["setup"]["voice_health_after"] = None
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                results["setup"]["voice_health_after"] = (await client.get(f"{VOICE_URL}/health")).json()
        except Exception as e:
            results["setup"]["voice_health_after"] = f"{type(e).__name__}: {e}"
        if not args.keep_loaded:
            await ollama_client.unload()
            await asyncio.sleep(2)
        results["setup"]["ollama_after"] = await ollama_ps()
        results["setup"]["vram_end"] = smi()
        results["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        RESULTS_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nproduction log during the run: {results['production_log_during_run']}")
        print(f"brain {'kept loaded' if args.keep_loaded else 'unloaded'}: ollama {results['setup']['ollama_after']}, "
              f"GPU {results['setup']['vram_end']}")
        print(f"results: {RESULTS_FILE}")
        for client in (ollama_client.client, admin_client.client):
            try:
                await client.aclose()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--passes", type=int, default=2, help="how many times the four notes run (default 2)")
    parser.add_argument("--gap", type=float, default=3.0, help="seconds between notes (default 3)")
    parser.add_argument("--tg-rtt", type=float, default=0.0,
                        help="seconds each fake Telegram send takes (default 0: Telegram's time not included)")
    parser.add_argument("--keep-loaded", action="store_true", help="leave the brain in VRAM at the end")
    sys.exit(asyncio.run(main(parser.parse_args())))
