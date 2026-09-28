import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram.helpers import escape_markdown

from zoneinfo import ZoneInfo
from src.config import BOT_ROOT, settings
from src.scraper.client import admin_client, portal_error_reason
from src.llm.ollama_client import ollama_client
from src.bot.brief import compose_brief, compose_daily_brief, _send_brief  # noqa: F401 (/brief imports them from here)
from src.bot.replies import CHUNK_CHARS, send_pieces, telegram_len
import re
import json
import os

logger = logging.getLogger("hangeul.scheduler")

scheduler = AsyncIOScheduler()

# The passport watcher's memory: every scan it has audited, keyed "uid|file name". The portal names
# each upload passport_<uid>_<unix upload time>.<ext>, so a re-uploaded passport is a new key and is
# checked again, while an unchanged scan is checked once and never again (valid or not). An alert
# is marked sent only after Telegram accepted the message that carried it; until then it is sent
# again on every run. (The file used to be a bare list of uids; that list is not trusted.)
ALERTED_CACHE_FILE = os.path.join(BOT_ROOT, "data", "alerted_passport_issues.json")
WATCHER_CACHE_VERSION = 2
# The OCR takes seconds a scan and the portal has 300+ of them: a run stops starting new audits
# after this long, and the scans left (the oldest uploads) wait for the next run, 30 minutes on.
WATCHER_BUDGET_SECONDS = 20 * 60
_UPLOAD_TIME_RE = re.compile(r"passport_\d+_(\d{9,11})\b")
# Audit results that checked nothing (a scan the portal lists but did not send, a profile or scan
# it could not serve, an OCR engine that did not run): tried again next run, never remembered.
UNCHECKED_STATUSES = ("MISSING_DOCUMENT", "PORTAL_UNREADABLE", "OCR_UNAVAILABLE")
_ALERT_FOOTER ="_(Strict Read-Only Alert: Please update in admin portal manually if required)_"


def load_watcher_cache() -> Dict[str, Any]:
    """The watcher's memory {"version": 2, "scans": {"uid|file": entry}}. An old uid-only list, or a
    file that cannot be read, gives an empty memory: every current scan is checked once more."""
    empty = {"version": WATCHER_CACHE_VERSION, "scans": {}}
    if not os.path.exists(ALERTED_CACHE_FILE):
        return empty
    try:
        with open(ALERTED_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"Passport watcher memory unreadable ({e}); every current scan is checked again.")
        return empty
    if not isinstance(data, dict) or data.get("version") != WATCHER_CACHE_VERSION \
            or not isinstance(data.get("scans"), dict):
        logger.info("Passport watcher memory is the old uid-only list (it marked alerts as sent that "
                    "never went out); every current scan is checked again.")
        return empty
    return data


def save_watcher_cache(cache: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(ALERTED_CACHE_FILE), exist_ok=True)
    part = ALERTED_CACHE_FILE + ".part"
    try:
        with open(part, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=0)
        os.replace(part, ALERTED_CACHE_FILE)
    except Exception as e:
        logger.error(f"Failed to save the passport watcher memory: {e}")


def passport_scan(student: Dict[str, Any]) -> Optional[str]:
    """The student's passport upload on students.php (its view_doc.php file name, which carries the
    upload time), the newest when there are several; None when there is none."""
    scans = [f for f in student.get("files") or [] if f.startswith("passport_")]
    return max(scans, key=_upload_time) if scans else None


def _upload_time(file_name: str) -> int:
    m = _UPLOAD_TIME_RE.search(file_name or "")
    return int(m.group(1)) if m else 0


def _plain_name(text: str) -> str:
    """A name for inside *bold*: the Markdown markers dropped (names are letters anyway)."""
    return re.sub(r"[*_`\[\]]", "", re.sub(r"\s+", " ", text or "")).strip() or "(no name on the portal)"


def _alert_block(student: Dict[str, Any], form: Dict[str, Any], result: Dict[str, Any]) -> str:
    """One student's alert (Telegram Markdown), in the watcher's usual words: the portal's HNG id
    next to its uid, the validator's own status and findings, and the edit link."""
    uid = student["uid"]
    ids = f"`{student['student_id']}`, `ID {uid}`" if student.get("student_id") else f"`ID {uid}`"
    edit_url = f"{admin_client.base_url}/student_edit.php?id={uid}"
    issues = "; ".join(str(d) for d in result.get("discrepancies") or [])
    return (f"• *Student:* *{_plain_name(form.get('name') or student.get('student_name', ''))}* ({ids})\n"
            f"• *Status:* `{str(result.get('status', '')).replace('`', '')}`\n"
            f"• *Issue:* {escape_markdown(issues, version=1)}\n"
            f"• 🔗 *Direct Review Link:* [Edit Student #{uid}]({edit_url})")


def _alert_messages(blocks: List[Tuple[str, str]], limit: int = CHUNK_CHARS) -> List[Tuple[List[str], str]]:
    """The pending alerts [(key, block)] packed into as few messages as fit under Telegram's limit,
    each whole block in one message -> [(the keys it carries, text)]."""
    reserve = 80 + telegram_len(_ALERT_FOOTER)           # header and footer
    groups: List[List[Tuple[str, str]]] = []
    size = 0
    for key, block in blocks:
        need = telegram_len(block) + 2
        if groups and size + need + reserve <= limit:
            groups[-1].append((key, block))
            size += need
        else:
            groups.append([(key, block)])
            size = need
    total = len(blocks)
    out = []
    for i, group in enumerate(groups, 1):
        if total == 1:
            head = "🚨 *Automated Document Audit Alert*"
        else:
            head = f"🚨 *Automated Document Audit: {total} alerts*" + (f" (part {i} of {len(groups)})"
                                                                         if len(groups) > 1 else "")
        text = head + "\n\n" + "\n\n".join(b for _, b in group) + "\n\n" + _ALERT_FOOTER
        out.append(([k for k, _ in group], text))
    return out


async def _send_alerts(bot, chat_id, cache: Dict[str, Any], keys: List[str]) -> Tuple[int, int]:
    """Send the pending alerts of `keys`, grouped (_alert_messages). Each alert is marked sent, and
    the memory saved, right after Telegram accepted its message; a message Telegram refuses stops
    the sending, and it and the rest stay pending for the next run. -> (alerts sent, messages sent)."""
    scans = cache["scans"]
    sent = messages = 0
    for group, text in _alert_messages([(k, scans[k]["alert"]) for k in keys]):
        try:
            await send_pieces(lambda piece, mode: bot.send_message(chat_id=chat_id, text=piece, parse_mode=mode),
                              text, "Markdown")
        except Exception as e:
            logger.error(f"Passport audit alerts not sent ({type(e).__name__}: {e}); "
                         f"{len(keys) - sent} stay pending for the next run.")
            break
        stamp = time.strftime("%Y-%m-%d %H:%M")
        for k in group:
            scans[k]["sent"] = True
            scans[k]["sent_at"] = stamp
        save_watcher_cache(cache)
        sent += len(group)
        messages += 1
    return sent, messages


async def check_new_passport_uploads(bot_application):
    """Audit every passport scan on the portal once (every page of students.php), newest upload
    first, and alert the admin chat on the ones with issues. A scan is known by its uid and file
    name, so a re-upload is audited again; a run stops starting new audits after
    WATCHER_BUDGET_SECONDS and the rest wait for the next run. Alerts are grouped into as few
    messages as fit and are marked sent only once Telegram accepted them."""
    chat_id = settings.TELEGRAM_ADMIN_CHAT_ID
    if not chat_id:
        return

    logger.info("Running automated passport upload audit check...")
    try:
        students = await admin_client.read_students()
    except Exception as e:
        logger.error(f"Passport audit check skipped: couldn't read the portal: {portal_error_reason(e)}")
        return

    try:
        cache = load_watcher_cache()
        scans = cache["scans"]
        current: Dict[str, Tuple[Dict[str, Any], str]] = {}
        for s in students:
            scan = passport_scan(s)
            if s.get("uid") and scan:
                current[f"{s['uid']}|{scan}"] = (s, scan)
        # Scans the portal no longer lists (replaced by a new upload, or the student removed) are
        # forgotten, alerts not yet sent about them included: they are about a file that is gone.
        for key in [k for k in scans if k not in current]:
            del scans[key]
        todo = sorted((k for k in current if k not in scans), key=lambda k: -_upload_time(current[k][1]))

        started = time.monotonic()
        audited = found = failed = 0
        for key in todo:
            if time.monotonic() - started > WATCHER_BUDGET_SECONDS:
                break
            s, scan = current[key]
            details = s.get("details") or {}
            form = {"name": details.get("Full Name") or s.get("student_name", ""),
                    "dob": details.get("DOB", ""),
                    "passport_no": details.get("Passport No", ""),
                    "passport_expiry": details.get("Passport Expiry", "")}
            try:
                result = await admin_client.audit_student_passport(s["uid"], form, scan)
            except Exception as e:
                failed += 1
                logger.error(f"Passport audit of uid {s['uid']} failed ({type(e).__name__}: {e}); "
                             "it is tried again next run.")
                continue
            if result.get("status") in UNCHECKED_STATUSES:
                # The portal lists this scan, so it was not downloaded; or the profile or the scan
                # could not be read (ocr_validator.unchecked_result); or the OCR engine did not
                # run: nothing was checked, so it is neither alerted nor remembered as audited.
                failed += 1
                logger.warning(f"Passport scan {scan} of uid {s['uid']} could not be checked "
                               f"({result.get('verdict') or result.get('status')}); it is tried again next run.")
                continue
            entry = {"uid": s["uid"], "student_id": s.get("student_id", ""), "status": result.get("status", ""),
                     "checked": time.strftime("%Y-%m-%d %H:%M"), "alert": None, "sent": False}
            if not result.get("is_valid") and result.get("discrepancies"):
                entry["alert"] = _alert_block(s, form, result)
                found += 1
            scans[key] = entry
            audited += 1
            save_watcher_cache(cache)          # after every audit: a restart loses none of them

        pending = sorted((k for k in current if scans.get(k, {}).get("alert") and not scans[k].get("sent")),
                         key=lambda k: -_upload_time(current[k][1]))
        sent, messages = await _send_alerts(bot_application.bot, chat_id, cache, pending) if pending else (0, 0)
        save_watcher_cache(cache)
        waiting = len(todo) - audited - failed
        logger.info(f"Passport audit check: {len(current)} scans on the portal, {audited} audited this run "
                    f"({found} with issues), {failed} could not be checked, {waiting} waiting for the next run; "
                    f"{sent} alert(s) sent in {messages} message(s), {len(pending) - sent} not sent yet.")
    except Exception as e:
        logger.error(f"Error in check_new_passport_uploads: {e}")

async def send_daily_briefing(bot_application):
    """Compose the factual daily brief (src/bot/brief.py: live portal figures counted in code)
    and push it to the admin chat, then Jennie's spoken version of it."""
    chat_id = settings.TELEGRAM_ADMIN_CHAT_ID
    if not chat_id:
        logger.warning("No TELEGRAM_ADMIN_CHAT_ID configured. Skipping scheduled report.")
        return

    logger.info(f"Generating scheduled briefing ({settings.REPORT_TIMEZONE}) for chat {chat_id}...")
    try:
        composed = await compose_brief()
        await _send_brief(bot_application.bot, chat_id, composed.text)
        logger.info("Scheduled briefing dispatched successfully.")
    except Exception as e:
        logger.error(f"Failed to dispatch scheduled briefing: {e}")
        return

    # Jennie reads a short summary of it aloud. Only after the text brief went out, and
    # nothing here may ever touch the text brief: every failure just skips the voice note.
    # She is given the brief's facts (one checked figure a line), not the whole text, whose
    # dates, clock times and tile figures would let a number be said about the wrong thing.
    if settings.JENNIE_VOICE_ENABLED and settings.JENNIE_SPOKEN_BRIEF:
        try:
            from src.bot.voice import send_spoken_brief
            await send_spoken_brief(bot_application.bot, chat_id, "\n".join(composed.facts))
        except Exception as e:
            logger.error(f"Spoken daily brief skipped (the text brief was sent): {e}")

async def warm_brain(attempts: int = 3, retry_after: float = 30.0) -> bool:
    """Load Jennie's brain (the local LLM, settings.OLLAMA_MODEL) into VRAM and keep it there, so
    the first question, typed or spoken, is answered warm; then render any missing voice filler
    clips. A model that landed partly on the CPU (the GPU was busy at that moment, e.g. the voice
    service warming up) is loaded again once there is room. Never raises.
    -> True when the whole model is on the GPU."""
    import asyncio
    on_gpu = False
    try:
        for attempt in range(1, attempts + 1):
            state = await ollama_client.warm_up()
            if state.get("loaded") and state.get("on_gpu"):
                on_gpu = True
                logger.info(f"Brain {settings.OLLAMA_MODEL} resident on the GPU: {state.get('vram_gb')} GB, "
                            f"num_ctx {state.get('num_ctx')}, ready in {state.get('seconds')} s.")
                break
            if state.get("loaded"):
                logger.warning(f"Brain {settings.OLLAMA_MODEL} is only partly on the GPU "
                               f"({state.get('vram_gb')} of {state.get('size_gb')} GB) - it answers slowly.")
                if attempt < attempts:
                    await ollama_client.unload()
            else:
                logger.warning(f"Brain {settings.OLLAMA_MODEL} did not load (is Ollama running?).")
            if attempt < attempts:
                await asyncio.sleep(retry_after)
    except Exception as e:
        logger.error(f"Brain warm-up failed: {e}")

    if settings.JENNIE_VOICE_ENABLED:
        try:
            from src.bot.voice import prepare_fillers
            await prepare_fillers()
        except Exception as e:
            logger.error(f"Voice filler clips not prepared: {e}")
    return on_gpu


async def keep_brain_warm():
    """Load the brain again if Ollama lost it (a restart or an update), or if it sits partly on the
    CPU: Ollama never moves a loaded model, and with keep_alive -1 never unloads it, so a model that
    loaded while the GPU was full (the voice service keeps its speech model there for a few minutes
    after each reply) would answer slowly until the bot restarts. It is unloaded and loaded again;
    if the GPU is still full, the next check (10 minutes later) tries again. Otherwise nothing to do.
    Nothing at all when the brain is not pinned (voice off): it then loads only for a question."""
    from src.llm.ollama_client import brain_pinned
    if not brain_pinned():
        return
    try:
        state = await ollama_client.residency()
        if state.get("loaded") and state.get("on_gpu"):
            return
        if state.get("loaded"):
            logger.warning(f"Brain {settings.OLLAMA_MODEL} is only partly on the GPU ({state.get('vram_gb')} of "
                           f"{state.get('size_gb')} GB) - loading it again.")
            await ollama_client.unload()
        await warm_brain(attempts=1)
    except Exception as e:
        logger.error(f"Brain keep-warm check failed: {e}")


SYNC_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             "hangeul_sync.log")


async def run_portal_sync():
    """Portal -> progress sheets + verified-documents sync (src/sheets/auto_sync.py).
    It sends its own Telegram summary when something changed."""
    await _run_module("src.sheets.auto_sync", "Portal sync")


async def run_issue_date_refresh():
    """Re-read every student's passport issue date (src/sheets/passport_issue.py).
    The portal keeps it only on the edit page, so it cannot ride along with the CSV export
    and would otherwise stay as it was the day it was first read."""
    await _run_module("src.sheets.passport_issue --refresh", "Passport issue dates")


async def run_missing_report():
    """Daily missing-information report from the progress sheets (src/sheets/missing_report.py).
    It sends its own Telegram summary + Excel file."""
    await _run_module("src.sheets.missing_report", "Missing-information report")


async def _run_module(module: str, label: str):
    """Run a job as its own process so a problem in it can never take the bot down."""
    import sys
    import asyncio
    bot_root = os.path.dirname(SYNC_LOG_FILE)
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):  # background mode: use the console-less twin
        exe = exe[:-len("pythonw.exe")] + "python.exe"
    try:
        with open(SYNC_LOG_FILE, "a", encoding="utf-8") as log:
            parts = module.split()
            proc = await asyncio.create_subprocess_exec(
                exe, "-m", *parts, cwd=bot_root,
                stdout=log, stderr=log,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                creationflags=0x08000000 if os.name == "nt" else 0,  # CREATE_NO_WINDOW
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=3600)
            except asyncio.TimeoutError:
                proc.kill()
                logger.error(f"{label} took over an hour and was stopped.")
        logger.info(f"{label} finished (exit {proc.returncode}).")
    except Exception as e:
        logger.error(f"{label} could not run: {e}")


def setup_scheduler(bot_application):
    """Configure and start APScheduler background cron jobs."""
    if not settings.ENABLE_SCHEDULED_REPORTS:
        logger.info("Scheduled reports are disabled in settings.")
        return scheduler

    # 1. Daily Executive Briefing (e.g. 18:05)
    try:
        parts = settings.DAILY_REPORT_TIME.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        hour, minute = 18, 5

    tz = ZoneInfo(settings.REPORT_TIMEZONE)
    # A stalled moment at 18:05 must not drop the brief: APScheduler's default grace is 1 second.
    scheduler.add_job(
        send_daily_briefing,
        CronTrigger(hour=hour, minute=minute, timezone=tz),
        args=[bot_application],
        id="daily_executive_briefing",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )

    # 2. Automated Passport Upload Watcher (Every 30 minutes; one run at a time, since a run with
    #    many unaudited scans, e.g. with an empty memory, audits for up to WATCHER_BUDGET_SECONDS)
    scheduler.add_job(
        check_new_passport_uploads,
        IntervalTrigger(minutes=30),
        args=[bot_application],
        id="passport_upload_watcher",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    
    # 3. Portal -> progress sheets + verified documents sync (every 15 minutes)
    scheduler.add_job(
        run_portal_sync,
        IntervalTrigger(minutes=15),
        id="portal_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # 4. Daily missing-information report at 09:05
    scheduler.add_job(
        run_missing_report,
        CronTrigger(hour=9, minute=5, timezone=tz),
        id="missing_info_report",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # 5. Passport issue dates, once a day before the morning report
    scheduler.add_job(
        run_issue_date_refresh,
        CronTrigger(hour=8, minute=30, timezone=tz),
        id="passport_issue_refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # 6. Jennie's brain stays in VRAM (loaded at startup by post_init); reload it if Ollama lost it
    scheduler.add_job(
        keep_brain_warm,
        IntervalTrigger(minutes=10),
        id="brain_keep_warm",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    logger.info(f"Scheduler active: daily briefing set for {hour:02d}:{minute:02d} ({settings.REPORT_TIMEZONE}), passport watcher running every 30m, portal sync every 15m, missing-info report 09:05.")
    return scheduler

