import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from zoneinfo import ZoneInfo
from src.config import BOT_ROOT, settings
from src.scraper.client import admin_client
from src.llm.ollama_client import ollama_client
from src.bot.brief import compose_brief, compose_daily_brief, _send_brief  # noqa: F401 (/brief imports them from here)
from bs4 import BeautifulSoup
import re
import json
import os

logger = logging.getLogger("hangeul.scheduler")

scheduler = AsyncIOScheduler()

# Cache file to avoid duplicate Telegram alerts
ALERTED_CACHE_FILE = os.path.join(BOT_ROOT, "data", "alerted_passport_issues.json")

def get_alerted_cache() -> set:
    if os.path.exists(ALERTED_CACHE_FILE):
        try:
            with open(ALERTED_CACHE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_alerted_cache(alerted: set):
    os.makedirs(os.path.dirname(ALERTED_CACHE_FILE), exist_ok=True)
    try:
        with open(ALERTED_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(alerted), f)
    except Exception as e:
        logger.error(f"Failed to save alerted cache: {e}")

async def check_new_passport_uploads(bot_application):
    """Periodically check recent passport uploads and proactively alert on discrepancies."""
    chat_id = settings.TELEGRAM_ADMIN_CHAT_ID
    if not chat_id:
        return

    logger.info("Running automated passport upload audit check...")
    try:
        if not admin_client.is_authenticated:
            await admin_client.login()
        resp = await admin_client.client.get(f"{admin_client.base_url}/students.php")
        soup = BeautifulSoup(resp.text, "html.parser")
        
        alerted = get_alerted_cache()
        new_alerts = []

        for tr in soup.find_all("tr"):
            text = tr.get_text(" ", strip=True)
            pass_a = tr.find("a", href=re.compile(r"view_doc\.php\?f=passport_"))
            edit_a = tr.find("a", href=re.compile(r"student_edit\.php\?id=\d+"))
            
            if pass_a and edit_a:
                stu_id = re.search(r"id=(\d+)", edit_a.get("href")).group(1)
                doc_fn = re.search(r"f=([^&]+)", pass_a.get("href")).group(1)
                
                if stu_id in alerted:
                    continue
                    
                name_m = re.search(r"Full Name\s+([A-Za-z\s\.]+?)(?:DOB|$)", text)
                dob_m = re.search(r"DOB\s+([\d\-]+)", text)
                pass_no_m = re.search(r"Passport No\s+([A-Za-z0-9]+)", text)
                pass_exp_m = re.search(r"Passport Expiry\s+([\d\-]+)", text)

                form_data = {
                    "name": name_m.group(1).strip() if name_m else "",
                    "dob": dob_m.group(1).strip() if dob_m else "",
                    "passport_no": pass_no_m.group(1).strip() if pass_no_m else "",
                    "passport_expiry": pass_exp_m.group(1).strip() if pass_exp_m else ""
                }

                result = await admin_client.audit_student_passport(stu_id, form_data, doc_fn)
                if not result["is_valid"] and result["discrepancies"]:
                    alerted.add(stu_id)
                    edit_url = f"{admin_client.base_url}/student_edit.php?id={stu_id}"
                    msg = (
                        "🚨 *Automated Document Audit Alert*\n\n"
                        f"• *Student:* *{form_data['name']}* (`ID {stu_id}`)\n"
                        f"• *Status:* `{result['status']}`\n"
                        f"• *Issue:* {'; '.join(result['discrepancies'])}\n"
                        f"• 🔗 *Direct Review Link:* [Edit Student #{stu_id}]({edit_url})\n\n"
                        "_(Strict Read-Only Alert: Please update in admin portal manually if required)_"
                    )
                    new_alerts.append(msg)

        if new_alerts:
            save_alerted_cache(alerted)
            for alert_msg in new_alerts[:3]:  # rate limit max 3 per cycle
                await bot_application.bot.send_message(
                    chat_id=chat_id,
                    text=alert_msg,
                    parse_mode="Markdown"
                )
            logger.info(f"Dispatched {len(new_alerts)} new passport audit alerts.")
        else:
            logger.info("Passport audit check completed: no new discrepancies found.")
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
    if the GPU is still full, the next check (10 minutes later) tries again. Otherwise nothing to do."""
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

    # 2. Automated Passport Upload Watcher (Every 30 minutes)
    scheduler.add_job(
        check_new_passport_uploads,
        IntervalTrigger(minutes=30),
        args=[bot_application],
        id="passport_upload_watcher",
        replace_existing=True
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

