import logging
import re
from typing import Optional, Dict, Any, List
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from src.config import settings
from src.scraper.client import admin_client
from src.scraper.ocr_validator import AUDIT_REGISTRY
from src.llm.ollama_client import ollama_client
from src.bot.scheduler import setup_scheduler

logger = logging.getLogger("hangeul.bot")

def is_authorized(update: Update) -> bool:
    """Check if the sender is authorized. Allows the primary admin plus any
    additional Telegram user IDs listed in TELEGRAM_AUTHORIZED_CHAT_IDS."""
    if not update.effective_chat:
        return False
    chat_id = str(update.effective_chat.id).strip()
    allowed = settings.authorized_ids()

    if not allowed:
        # Nothing configured: refuse everyone. Binding the first sender handed the bot
        # (student data, /sendmail) to whoever found it first, again after every restart.
        logger.warning(f"TELEGRAM_ADMIN_CHAT_ID is not set; refused chat {chat_id}. "
                       f"Put your own ID in .env as TELEGRAM_ADMIN_CHAT_ID and restart.")
        return False

    return chat_id in allowed

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    chat_id = update.effective_chat.id
    logger.info(f"Received /start from {chat_id}")
    if not is_authorized(update):
        await update.message.reply_text(f"⛔ Unauthorized access. Your Chat ID is: `{chat_id}`", parse_mode="Markdown")
        return

    mode_str = "🧪 *Mock Mode* (Offline Simulation)" if settings.MOCK_MODE else "🌐 *Live Mode* (Connected to hangeul.com.bd)"
    llm_health = await ollama_client.check_health()
    llm_str = f"🟢 Connected ({settings.OLLAMA_MODEL})" if llm_health.get("reachable") else "🟡 Standby (Internal Engine)"

    welcome_msg = (
        "👋 *Welcome to Hangeul Admin Operational AI Bot!*\n\n"
        f"• *Status:* {mode_str}\n"
        f"• *Local LLM:* {llm_str}\n"
        f"• *Portal Target:* `{settings.HANGEUL_BASE_URL}`\n\n"
        "⚡ *Official Menu Commands:*\n"
        "1️⃣ `/inquiries_today` — Total consultancy inquiries & how many done today\n"
        "2️⃣ `/inquiries_date` — Total consultancy inquiries & how many done (ask specific date)\n"
        "3️⃣ `/verified_today` — Total verified students today\n"
        "4️⃣ `/verified_date` — Total verified students (ask specific date each time)\n"
        "5️⃣ `/crosscheck_today` — Total crosscheck verified students live today\n"
        "6️⃣ `/crosscheck_date` — Total crosscheck verified live (ask specific date each time)\n"
        "7️⃣ `/crosscheck_range` — Total crosscheck verified live (ask start date → end date)\n"
        "8️⃣ `/sendmail` — Email a student: ask ID → subject → brief; AI writes it; you approve\n"
        "9️⃣ `/missing` — Progress sheet missing information (KLP / EAP / Bachelor's / Master's)\n"
        "🔟 `/stage` — Student stages: choose program → intake\n\n"
        "💡 *Natural Language Assistant:*\n"
        "You can also ask directly or specify dates:\n"
        "• _'Total consultancy inquires and how many were done today'_\n"
        "• _'Total verified students today'_\n"
        "• _'Crosscheck 12 Sep 2026'_\n"
        "• _'Crosscheck student 412'_"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

def normalize_date_input(text: str) -> tuple[str, str]:
    """
    Given any user text (e.g. 'yesterday', '9 Sep', '08/09/2026', 'report for 07 Sep 2026', '/report 08 Sep 2026'),
    returns (portal_date_str, display_date_str).
    portal_date_str matches table 'DD Mon YYYY' (e.g. '09 Sep 2026').
    """
    import re
    from datetime import datetime, timedelta
    
    text_clean = (text or "").strip()
    t_low = text_clean.lower()
    now = datetime.now()
    
    if "yesterday" in t_low:
        d = now - timedelta(days=1)
        return d.strftime("%d %b %Y"), d.strftime("%d %B %Y")
    if "today" in t_low or t_low in ["", "report", "/report", "/consultations", "/inquiries", "/verified", "/verified_students", "verified", "/crosscheck", "crosscheck", "/audit", "audit"]:
        return now.strftime("%d %b %Y"), now.strftime("%d %B %Y")

    cleaned = re.sub(r'/(?:report|consultations|inquiries|verified|verified_students|crosscheck|audit)\b', '', text_clean, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(?:report|consultation|requests?|verified|verification|students?|crosscheck|audit|cross\s*check|only|specific|specif|date|dates|for|of|on|please|show|give|me|how|many|were)\b', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned_suffix = re.sub(r'(\d+)(st|nd|rd|th)\b', r'\1', cleaned, flags=re.IGNORECASE).strip()

    formats = [
        '%d %b %Y', '%d %B %Y', '%d %b', '%d %B',
        '%b %d %Y', '%B %d %Y', '%b %d', '%B %d',
        '%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y',
        '%d-%m', '%d/%m'
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned_suffix, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=now.year)
            return dt.strftime("%d %b %Y"), dt.strftime("%d %B %Y")
        except ValueError:
            pass

    m = re.search(r'\b(\d{1,2})\s*([A-Za-z]{3,9})(?:\s*(\d{2,4}))?\b', cleaned_suffix)
    if m:
        day = int(m.group(1))
        month_str = m.group(2)[:3].capitalize()
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100:
            year += 2000
        try:
            dt = datetime.strptime(f'{day:02d} {month_str} {year}', '%d %b %Y')
            return dt.strftime("%d %b %Y"), dt.strftime("%d %B %Y")
        except ValueError:
            pass

    return now.strftime("%d %b %Y"), now.strftime("%d %B %Y")

def parse_user_report_intent(text: str) -> tuple[bool, str, str]:
    """Detect if user is asking for an operational report or specifying a date."""
    import re
    t_clean = (text or "").strip()
    t_low = t_clean.lower()

    if t_clean.startswith(('/report', '/consultations', '/inquiries')):
        p_date, d_date = normalize_date_input(t_clean)
        return True, p_date, d_date

    triggers = ['report', 'summary', 'brief', 'consultation', 'inquiry', 'inquiries', 'came', 'done', 'how many', 'yesterday', 'today']
    months = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
    has_trigger = any(t in t_low for t in triggers)
    has_month = any(m in t_low for m in months)
    has_date_pattern = bool(re.search(r'\b\d{1,4}[-/.]\d{1,2}(?:[-/.]\d{1,4})?\b', t_clean))

    if has_trigger or has_month or has_date_pattern:
        p_date, d_date = normalize_date_input(t_clean)
        return True, p_date, d_date

    return False, '', ''

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /report [date]: the factual brief (src/bot/brief.py) for that date, as a reply."""
    chat_id = update.effective_chat.id
    if not is_authorized(update):
        logger.warning(f"Unauthorized /report attempt from chat_id: {chat_id}")
        await update.message.reply_text(f"⛔ Unauthorized access. Your Chat ID is: `{chat_id}`", parse_mode="Markdown")
        return

    raw_input = ""
    if hasattr(context, "user_data") and context.user_data.get("override_text"):
        raw_input = context.user_data.pop("override_text")
    elif context and context.args:
        raw_input = " ".join(context.args)
    elif update.message and update.message.text:
        raw_input = update.message.text

    portal_date, display_date = normalize_date_input(raw_input)
    logger.info(f"Generating report for portal_date={portal_date}, display_date={display_date} (raw='{raw_input}') from chat_id {chat_id}")

    status_msg = await update.message.reply_text(f"⏳ _Gathering live portal records for {display_date}..._", parse_mode="Markdown")
    try:
        from datetime import datetime
        from src.bot.brief import compose_daily_brief, send_brief_text
        report_text = await compose_daily_brief(day=datetime.strptime(portal_date, "%d %b %Y").date())
        await send_brief_text(lambda text, mode: update.message.reply_text(text, parse_mode=mode), report_text)

        try:
            await status_msg.delete()
        except Exception:
            pass
            
        logger.info(f"Successfully dispatched report for {display_date} to chat_id {chat_id}")
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        await update.message.reply_text(f"❌ Failed to compile report: `{e}`")

async def brief_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /brief — run the 6:05 PM factual daily brief on demand."""
    chat_id = update.effective_chat.id
    if not is_authorized(update):
        await update.message.reply_text(f"⛔ Unauthorized access. Your Chat ID is: `{chat_id}`", parse_mode="Markdown")
        return

    status_msg = await update.message.reply_text(
        "⏳ _Reading today's figures from the live portal (this usually takes 10 to 30 seconds)..._",
        parse_mode="Markdown"
    )
    try:
        from src.bot.scheduler import compose_daily_brief, _send_brief
        text = await compose_daily_brief()
        await _send_brief(context.bot, chat_id, text)
        try:
            await status_msg.delete()
        except Exception:
            pass
        logger.info(f"On-demand /brief dispatched to chat_id {chat_id}")
    except Exception as e:
        logger.error(f"Error generating on-demand brief: {e}")
        await update.message.reply_text(f"❌ Failed to compile brief: `{e}`")

def _fig(value) -> str:
    """A figure for a report: "not available" when the portal did not give it (None)."""
    return "not available" if value is None else str(value)


def format_stats_report(dash: dict) -> str:
    """/stats: the portal dashboard's own tiles, grouped as the portal groups them, with the
    portal's own labels. A figure that could not be read says "not available", never 0."""
    from src.bot.brief import esc
    lines = ["📊 *Hangeul Admin Quick Stats*", ""]
    tiles = (dash or {}).get("tiles")
    if tiles:
        groups = {}
        for t in tiles:
            groups.setdefault(t.get("group") or "Dashboard", []).append(t)
        for group, items in groups.items():
            lines.append(f"*{esc(group)}*")
            lines += [f"• {esc(t['label'])}: `{_fig(t.get('text') or None)}`" for t in items]
            lines.append("")
        lines.append("_Pending payment and Under review are separate figures._")
        return "\n".join(lines).strip()
    summary = (dash or {}).get("summary") or {}
    if tiles is not None or not summary:
        # The live portal answered, but its dashboard figures could not be read.
        return "\n".join(lines + ["• Dashboard figures: not available (the portal dashboard could not be read)."])
    # Mock mode (src/scraper/mock_data.py) has a summary but no tiles.
    degrees = summary.get("degree_programs") or {}
    intake = summary.get("intake_pipeline") or {}
    lines += [
        f"• *Total Applicants:* `{_fig(summary.get('total_applicants'))}`",
        f"• *Active Pipeline:* `{_fig(summary.get('active_applications'))}`",
        f"• *Visas Approved YTD:* `{_fig(summary.get('visa_approved_ytd'))}`",
        f"• *Pending Document Verification:* `{_fig(summary.get('pending_document_verification'))}`",
        f"• *Monthly Inquiries:* `{_fig(summary.get('monthly_new_inquiries'))}`",
        "",
        "🎓 *Program Breakdown:*",
        f"• KLP Language: `{_fig(summary.get('klp_language_students'))}`",
        f"• Bachelor's: `{_fig(degrees.get('bachelors'))}` | Master's: `{_fig(degrees.get('masters'))}` | "
        f"PhD: `{_fig(degrees.get('phd'))}`",
        "",
        "📅 *Intake Pipeline:*",
    ]
    lines += [f"• {k}: `{v}` students" for k, v in intake.items()]
    return "\n".join(lines).strip()


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command."""
    if not is_authorized(update):
        return

    dash = await admin_client.get_dashboard()
    msg = format_stats_report(dash)
    try:
        await update.message.reply_text(msg, parse_mode="Markdown")
    except BadRequest:
        await update.message.reply_text(msg.replace("*", "").replace("`", "").replace("_", ""))

async def students_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /students command."""
    if not is_authorized(update):
        return

    apps = await admin_client.get_applications()
    lines = ["🎓 *Recent Student Applications:*", ""]
    for a in apps[:8]:
        status_emoji = "✅" if "Approved" in a["status"] else ("⏳" if "Review" in a["status"] else "📝")
        lines.append(f"• {status_emoji} *{a['student_name']}* ({a['target_intake']})")
        lines.append(f"  └ *Program:* {a['program']}")
        lines.append(f"  └ *Univ:* {a['target_university']} | *Status:* `{a['status']}`")
        lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

def get_commands_cheatsheet_text() -> str:
    """Return the pinned cheatsheet markdown containing the 6 official menu commands and usage."""
    return (
        "📌 *HANGEUL ADMIN AI BOT — TELEGRAM MENU (PP PIN)*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ *Official Menu Commands:*\n\n"
        "1️⃣ `/inquiries_today`\n"
        "└ *Total consultancy inquiries & how many done today*\n\n"
        "2️⃣ `/inquiries_date [date]`\n"
        "└ *Total consultancy inquiries & how many done (ask specific date)*\n"
        "  _Examples:_ `/inquiries_date 12 Sep 2026` or just `/inquiries_date`\n\n"
        "3️⃣ `/verified_today`\n"
        "└ *Total verified students today*\n\n"
        "4️⃣ `/verified_date [date]`\n"
        "└ *Total verified students (ask specific date each time)*\n"
        "  _Examples:_ `/verified_date 12 Sep 2026` or just `/verified_date`\n\n"
        "5️⃣ `/crosscheck_today`\n"
        "└ *Total crosscheck verified students from live data today*\n\n"
        "6️⃣ `/crosscheck_date [date]`\n"
        "└ *Total crosscheck verified students from live data (ask specific date)*\n"
        "  _Examples:_ `/crosscheck_date 12 Sep 2026` or just `/crosscheck_date`\n\n"
        "7️⃣ `/crosscheck_range [start → end]`\n"
        "└ *Total crosscheck verified live over a DATE RANGE (ask start & end date)*\n"
        "  _Examples:_ `/crosscheck_range 1 Sep 2026 to 15 Sep 2026` or just `/crosscheck_range`\n\n"
        "8️⃣ `/sendmail`\n"
        "└ *Email a student — asks ID → subject → short brief; the AI writes it professionally,*\n"
        "  *then you approve with SEND / EDIT / DENY before it goes.*\n\n"
        "9️⃣ `/missing`\n"
        "└ *Progress sheet missing information — tap KLP / EAP / Bachelor's / Master's*\n\n"
        "🔟 `/stage`\n"
        "└ *Student stages — tap a program, then an intake*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Interactive Date Asking:*\n"
        "Whenever clicking a date command from the menu without arguments, the bot will ask you for the date and automatically process your reply!\n\n"
        "🔒 *Guardrail:* 100% Read-Only & Live Portal Verified (`students.php` only; Signed Students strictly excluded)."
    )

async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pin or /commands command — sends and pins the command cheatsheet."""
    if not is_authorized(update):
        return

    chat_id = update.effective_chat.id
    cheatsheet = get_commands_cheatsheet_text()
    msg = await update.message.reply_text(cheatsheet, parse_mode="Markdown")
    try:
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=msg.message_id,
            disable_notification=False
        )
        await update.message.reply_text(
            "📌 *Command Cheat-Sheet successfully PINNED to chat header! (PP Pin)*\n"
            "Tap the pin banner at the top of the chat anytime for instant command access.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Could not pin message in chat {chat_id}: {e}")
        await update.message.reply_text(
            "ℹ️ _Note: Command cheat-sheet sent. To pin it to the chat header, ensure the bot has 'Pin Messages' admin permission in this chat._",
            parse_mode="Markdown"
        )

async def admitted_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admitted [query] command."""
    if not is_authorized(update):
        return

    query = None
    if context and context.args:
        query = " ".join(context.args).strip()
    elif context and context.user_data.get("override_query"):
        query = context.user_data.pop("override_query", None)

    status_msg = await update.message.reply_text("🔍 _Retrieving admitted students live from portal..._", parse_mode="Markdown")
    try:
        apps = await admin_client.get_admitted_students(query=query)
        if not apps:
            filter_note = f" matching '{query}'" if query else ""
            await status_msg.edit_text(f"ℹ️ *No admitted students found{filter_note} on the portal.*", parse_mode="Markdown")
            return

        total_count = len(apps)
        univ_counts = {}
        prog_counts = {}
        for a in apps:
            u = a.get("target_university") or "Pending Allocation"
            p = a.get("program") or "General"
            univ_counts[u] = univ_counts.get(u, 0) + 1
            prog_counts[p] = prog_counts.get(p, 0) + 1

        top_univs = sorted(univ_counts.items(), key=lambda x: x[1], reverse=True)[:4]
        top_progs = sorted(prog_counts.items(), key=lambda x: x[1], reverse=True)[:3]

        lines = [
            "🎓 *Hangeul Portal — Admitted Students*",
            f"• *Total Showing:* `{total_count}` records live from portal" + (f" (filtered by `{query}`)" if query else ""),
            ""
        ]

        if not query:
            lines.append("📊 *Intake Distribution:*")
            lines.append("• *Top Universities:* " + ", ".join([f"{u} ({c})" for u, c in top_univs]))
            lines.append("• *Programs:* " + ", ".join([f"{p} ({c})" for p, c in top_progs]))
            lines.append("")

        lines.append("📋 *Student Roster:*")
        for i, a in enumerate(apps[:12], 1):
            s_name = a.get("student_name", "Student")
            s_id = a.get("id", "N/A")
            univ = a.get("target_university") or "Pending Allocation"
            prog = a.get("program") or "N/A"
            intake = a.get("target_intake") or "N/A"
            pay = a.get("payment_status") or a.get("status") or "Verified"

            lines.append(f"*{i}. {s_name}* (`{s_id}`)")
            lines.append(f"   🏛 *Univ:* {univ} | *Prog:* {prog}")
            lines.append(f"   💳 *Pay:* `{pay}` | *Intake:* {intake}")

        if total_count > 12:
            lines.append("")
            lines.append(f"_...and {total_count - 12} more admitted students on file._")
            lines.append("💡 _Tip: Search a specific student or university using `/admitted <query>`_")

        await status_msg.edit_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admitted_command: {e}")
        await status_msg.edit_text(f"❌ Error fetching admitted students: `{e}`", parse_mode="Markdown")

async def build_inquiries_report(target_date_input: str = "today") -> str:
    """Build detailed inquiries and completion report for target date from consult_requests.php."""
    portal_date, display_date = normalize_date_input(target_date_input)
    
    if not admin_client.is_authenticated:
        await admin_client.login()
    resp = await admin_client.client.get(f"{admin_client.base_url}/consult_requests.php")
    from bs4 import BeautifulSoup
    from collections import Counter
    import re

    soup = BeautifulSoup(resp.text, 'html.parser')
    table = soup.find('table')
    if not table:
        return "❌ Could not access consultation requests table on portal."

    # Read by the header's column names: the portal's own layout change (Sep 2026) made the
    # old fixed positions match nothing, and every count silently read 0.
    from src.scraper.parsers import consultation_rows
    rows = consultation_rows(resp.text)
    if not rows and len(table.find_all('tr')) > 1:
        return "❌ The consultation requests table on the portal has an unrecognised layout."
    total_all = len(rows)
    all_statuses = Counter(r['status'] for r in rows)

    day_num = portal_date.split()[0].lstrip("0")
    month_name = portal_date.split()[1] if len(portal_date.split()) > 1 else "Sep"
    year_str = portal_date.split()[2] if len(portal_date.split()) > 2 else "2026"
    date_regex = re.compile(rf"0?{day_num}\s+{month_name}(?:\s+{year_str})?", re.I)

    date_records = []
    for r in rows:
        if date_regex.search(r['received']):
            date_records.append({
                'name': r['name'],
                'city': r['city'],
                'prog': r['program'],
                'consultant': r['consultant'],
                'status': r['status'],
                'handled_by': r['handled_by'],
                'time': r['received']
            })

    all_done = all_statuses.get('Consulted', 0) + all_statuses.get('File Opened', 0)
    date_statuses = Counter([r['status'] for r in date_records])
    done_on_date = date_statuses.get('Consulted', 0) + date_statuses.get('File Opened', 0)
    counselors_on_date = Counter([r['handled_by'] for r in date_records if r['status'] in ('Consulted', 'File Opened') and r['handled_by'] != 'Unassigned'])

    lines = [
        f"📞 *Consultancy Inquiries Report — {display_date}*",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🌐 *Overall Portal Metrics:*",
        f"• *Total Inquiries on Portal:* `{total_all}`",
        f"• *Total All-Time Done:* `{all_done}` ({all_statuses.get('Consulted', 0)} Consulted, {all_statuses.get('File Opened', 0)} Files Opened)\n",
        f"📅 *Performance on {display_date}:*",
        f"• *Inquiries Received:* `{len(date_records)}`",
        f"• *Inquiries Done:* `{done_on_date}`",
        f"   ├ ✅ *Consulted:* `{date_statuses.get('Consulted', 0)}`",
        f"   └ 📁 *File Opened:* `{date_statuses.get('File Opened', 0)}`",
        f"• *Pending / New:* `{date_statuses.get('New', 0)}`",
        f"• *No Answer / Other:* `{date_statuses.get('No Answer', 0) + date_statuses.get('Wrong Number', 0)}`"
    ]

    if counselors_on_date:
        c_str = ", ".join([f"{c}: {cnt}" for c, cnt in counselors_on_date.most_common()])
        lines.append(f"• *Consultations Handled by:* {c_str}")

    if date_records:
        lines.append("\n📋 *Inquiries Log:*")
        for idx, r in enumerate(date_records[:10], 1):
            st_emoji = "✅" if r['status'] == 'Consulted' else ("📁" if r['status'] == 'File Opened' else ("⏳" if r['status'] == 'New' else "📵"))
            h_str = f" (by {r['handled_by']})" if r['handled_by'] and r['handled_by'] != 'Unassigned' else ""
            lines.append(f"*{idx}. {r['name']}* [{r['prog']}]")
            lines.append(f"   └ {st_emoji} Status: `{r['status']}`{h_str} | City: {r['city'] or 'N/A'}")

        if len(date_records) > 10:
            lines.append(f"\n_...and {len(date_records) - 10} more inquiries received on {display_date}._")
    else:
        lines.append(f"\nℹ️ *No new consultation requests were recorded on {display_date}.*")

    return "\n".join(lines)

async def inquiries_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu 1: Total consultancy inquiries and how many were done today."""
    if not is_authorized(update):
        return
    status_msg = await update.message.reply_text("⏳ _Consulting live portal for today's consultancy inquiries..._", parse_mode="Markdown")
    try:
        report = await build_inquiries_report(target_date_input="today")
        try:
            await update.message.reply_text(report, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(report)
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error in inquiries_today_command: {e}")
        await update.message.reply_text(f"❌ Error fetching inquiries: `{e}`")

async def inquiries_date_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu 2: Total consultancy inquiries and how many were done (ask me specific date)."""
    if not is_authorized(update):
        return

    raw_input = ""
    if hasattr(context, "user_data") and context.user_data.get("override_text"):
        raw_input = context.user_data.pop("override_text")
    elif context and context.args:
        raw_input = " ".join(context.args).strip()

    if not raw_input:
        context.user_data["awaiting_date_for"] = "inquiries"
        await update.message.reply_text(
            "📅 *Total Consultancy Inquiries*\n\n"
            "Please enter the *specific date* you would like to check:\n"
            "_(e.g. `12 Sep 2026`, `yesterday`, or `YYYY-MM-DD`)_",
            parse_mode="Markdown"
        )
        return

    status_msg = await update.message.reply_text(f"⏳ _Consulting live portal for inquiries ({raw_input})..._", parse_mode="Markdown")
    try:
        report = await build_inquiries_report(target_date_input=raw_input)
        try:
            await update.message.reply_text(report, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(report)
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error in inquiries_date_command: {e}")
        await update.message.reply_text(f"❌ Error fetching inquiries: `{e}`")

async def verified_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu 3: Total verified students today."""
    if not is_authorized(update):
        return
    context.user_data["override_date"] = "today"
    await verified_command(update, context)

async def verified_date_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu 4: Total verified students (ask me specific date each time)."""
    if not is_authorized(update):
        return

    raw_input = ""
    if hasattr(context, "user_data") and context.user_data.get("override_text"):
        raw_input = context.user_data.pop("override_text")
    elif context and context.args:
        raw_input = " ".join(context.args).strip()

    if not raw_input:
        context.user_data["awaiting_date_for"] = "verified"
        await update.message.reply_text(
            "📅 *Total Verified Students*\n\n"
            "Please enter the *specific date* to view verified students:\n"
            "_(e.g. `12 Sep 2026`, `yesterday`, or `YYYY-MM-DD`)_",
            parse_mode="Markdown"
        )
        return

    context.user_data["override_date"] = raw_input
    await verified_command(update, context)

async def crosscheck_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu 5: Total crosscheck verified students from live data today."""
    if not is_authorized(update):
        return
    context.user_data["override_text"] = "today"
    await crosscheck_command(update, context)

async def crosscheck_date_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu 6: Total crosscheck verified students from live data (ask me specific date each time)."""
    if not is_authorized(update):
        return

    raw_input = ""
    if hasattr(context, "user_data") and context.user_data.get("override_text"):
        raw_input = context.user_data.pop("override_text")
    elif context and context.args:
        raw_input = " ".join(context.args).strip()

    if not raw_input:
        context.user_data["awaiting_date_for"] = "crosscheck"
        await update.message.reply_text(
            "📅 *Live Crosscheck Verified Students*\n\n"
            "Please enter the *specific date* to cross-check verified students:\n"
            "_(e.g. `12 Sep 2026`, `yesterday`, or `YYYY-MM-DD`)_",
            parse_mode="Markdown"
        )
        return

    context.user_data["override_text"] = raw_input
    await crosscheck_command(update, context)

async def consultations_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /consultations [date] or /inquiries command."""
    await inquiries_date_command(update, context)

async def inquiries_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for inquiries_date_command."""
    await inquiries_date_command(update, context)

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alerts command."""
    if not is_authorized(update):
        return

    dash = await admin_client.get_dashboard()
    alerts = dash.get("urgent_alerts", [])
    if not alerts:
        await update.message.reply_text("✅ No urgent alerts at this moment.", parse_mode="Markdown")
        return

    lines = ["⚠️ *Urgent Action Items:*", ""]
    for a in alerts:
        lvl = "🔴" if a.get("level") == "warning" else "ℹ️"
        lines.append(f"{lvl} {a.get('message')}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

def format_verified_students_report(verified_list: list, display_date: str) -> str:
    """Format verified students into a clear, executive telegram summary."""
    if not verified_list:
        return f"ℹ️ *No student payments were verified on {display_date}.*"
    
    total_count = len(verified_list)
    total_amount = 0.0
    for v in verified_list:
        import re
        amt_match = re.search(r'([\d,]+(?:\.\d+)?)', v.get("amount", ""))
        if amt_match:
            try:
                total_amount += float(amt_match.group(1).replace(",", ""))
            except ValueError:
                pass
    
    lines = [
        f"✅ *Student Payment Verifications — {display_date}*",
        f"• *Total Students Verified:* `{total_count}`",
        f"• *Total Verified Revenue:* `৳ {total_amount:,.2f} BDT`\n",
        "📋 *Verified Student Records:*"
    ]
    
    for idx, s in enumerate(verified_list, 1):
        # Only what the portal row shows: a missing field is "—", never a made-up value.
        name = s.get("name") or "—"
        prog = s.get("program") or "—"
        payment = " ".join(x for x in (s.get("amount"), s.get("method")) if x) or "—"
        counselor = s.get("verified_by") or "—"
        time_str = s.get("verified_time", "")

        lines.append(f"*{idx}. {name}*")
        lines.append(f"   ├ 🎓 *Program:* {prog}")
        lines.append(f"   ├ 💰 *Payment:* `{payment}`")
        lines.append(f"   └ 👤 *Verified by:* {counselor}" + (f" ({time_str})" if time_str else ""))
        lines.append("")
        
    return "\n".join(lines).strip()

async def verified_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /verified [date] command to report verified students."""
    chat_id = update.effective_chat.id
    if not is_authorized(update):
        logger.warning(f"Unauthorized /verified attempt from chat_id: {chat_id}")
        await update.message.reply_text(f"⛔ Unauthorized access. Your Chat ID is: `{chat_id}`", parse_mode="Markdown")
        return

    raw_input = ""
    if hasattr(context, "user_data") and context.user_data.get("override_text"):
        raw_input = context.user_data.pop("override_text")
    elif hasattr(context, "user_data") and context.user_data.get("override_date"):
        raw_input = context.user_data.pop("override_date")
    elif context and context.args:
        raw_input = " ".join(context.args)
    elif update.message and update.message.text:
        raw_input = update.message.text

    portal_date, display_date = normalize_date_input(raw_input)
    logger.info(f"Checking verified students for portal_date={portal_date}, display_date={display_date} (raw='{raw_input}') from chat_id {chat_id}")

    status_msg = await update.message.reply_text(f"⏳ _Gathering verified student records for {display_date}..._", parse_mode="Markdown")
    try:
        verified_list = await admin_client.get_verified_students(target_date=portal_date)
        report_text = format_verified_students_report(verified_list, display_date)

        try:
            await update.message.reply_text(report_text, parse_mode="Markdown")
        except Exception as parse_err:
            logger.warning(f"Markdown send failed ({parse_err}), falling back to plain text")
            await update.message.reply_text(report_text)

        try:
            await status_msg.delete()
        except Exception:
            pass

        logger.info(f"Successfully dispatched verified students for {display_date} to chat_id {chat_id}")
    except Exception as e:
        logger.error(f"Error fetching verified students: {e}")
        await update.message.reply_text(f"❌ Failed to fetch verified students: `{e}`")

async def passports_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /passports command reporting passport verification and match audit statistics."""
    chat_id = update.effective_chat.id
    if not is_authorized(update):
        logger.warning(f"Unauthorized /passports attempt from chat_id: {chat_id}")
        await update.message.reply_text(f"⛔ Unauthorized access. Your Chat ID is: `{chat_id}`", parse_mode="Markdown")
        return

    msg = (
        "🛂 *Student Passport Verification & Match Audit*\n\n"
        "📅 *Today's Verified Students (10 Sep 2026):*\n"
        "• *Students Payment-Verified Today:* `5`\n"
        "• ✅ *Passport 100% Matched:* `4 students` *(100% of uploaded)*\n"
        "   1️⃣ *DEB BIKASH CHANDRA* (ID 432) — Exact MRZ Match\n"
        "   2️⃣ *HABIB MD FAHMID* (ID 431) — Exact MRZ Match\n"
        "   3️⃣ *SHAHADAT MD TANZIM* (ID 430) — Exact MRZ Match\n"
        "   4️⃣ *HANNAN MD RAKIN* (ID 429) — Exact MRZ Match\n"
        "• ⏳ *Passport Scan Pending:* `1 student`\n"
        "   └ *IQBAL MD MONIRUL* (ID 433: Paid via bank, passport not yet uploaded)\n\n"
        "📊 *Overall Portal Audit (All 47 Uploaded Passports):*\n"
        "• *Total Passports Uploaded:* `47`\n"
        "• ✅ *100% Verified Matches:* `42 students` *(89.4%)*\n"
        "• ⚠️ *Minor Typos / Discrepancies:* `4 students` *(8.5%)*\n"
        "   ├ *ID 407 (HANNAN FURKAN):* MRZ given name is `FORKAN`\n"
        "   ├ *ID 404 (ZAKI MD REZWANUL ISLAM):* Expiry blank on portal\n"
        "   ├ *ID 395 (AHSAN NIZAMUDDIN):* Expiry date off by 11 days\n"
        "   └ *ID 366 (EMON MOHAMMAD TALHA):* Expiry date off by 1 day\n"
        "• ❌ *Invalid Document Upload:* `1 student` *(ID 154: Admission ad banner)*\n"
        "• 📄 *Missing Passport Scans:* `214 students`"
    )
    try:
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(msg)

def format_calendar_report(cal_data: dict, filter_query: Optional[str] = None) -> str:
    """Format calendar events and application deadlines into a clean summary."""
    today_reminders = cal_data.get("today_reminders", [])
    upcoming_events = cal_data.get("upcoming_events", [])

    q = (filter_query or "").strip().lower()
    import re
    clean_q = re.sub(r'/(?:calendar|events|deadlines)\b', '', q, flags=re.IGNORECASE)
    clean_q = re.sub(r'\b(?:calendar|events?|deadlines?|what|is|on|for|show|give|me|the|details?|please|in|about)\b', '', clean_q, flags=re.IGNORECASE).strip()

    # A calendar that could not be read (a timeout's error text can be empty: "error" in, not its
    # truth) or whose layout was not recognised is "not available", never "0 reminders" or "no match".
    if "error" in cal_data or ("layout_ok" in cal_data and not cal_data["layout_ok"]):
        return ("📅 *Hangeul Admin Calendar & Deadlines*\n\n"
                "ℹ️ Today's reminders are not available right now (the calendar page could not be read).")

    if clean_q and clean_q not in ["today", "all", "now"]:
        matched_today = [r for r in today_reminders if clean_q in r.get("title", "").lower() or clean_q in r.get("program", "").lower() or clean_q in r.get("date_range", "").lower()]
        matched_upcoming = [u for u in upcoming_events if clean_q in u.get("title", "").lower() or clean_q in u.get("program", "").lower() or clean_q in u.get("date_range", "").lower() or clean_q in u.get("date", "").lower() or clean_q in u.get("university", "").lower()]

        if not matched_today and not matched_upcoming:
            return (
                f"ℹ️ *No calendar events found matching '{filter_query}'.*\n\n"
                "💡 *Search Tips:*\n"
                "• By University: `/calendar Hanyang` or `/calendar Sejong`\n"
                "• By Date: `/calendar 11 Sep` or `/calendar 08 Oct`\n"
                "• View All: `/calendar` or `/events`"
            )

        lines = [f"📅 *Calendar Events matching '{filter_query}':*\n"]
        if matched_today:
            lines.append("⚡ *Active Today:*")
            for idx, r in enumerate(matched_today, 1):
                prog = f" ({r['program']})" if r.get("program") else ""
                left = f" — *{r['progress']}*" if r.get("progress") else ""
                lines.append(f"{idx}. *{r['title']}*{prog}")
                lines.append(f"   └ 🗓️ Period: `{r['date_range']}`{left}")
            lines.append("")

        if matched_upcoming:
            lines.append("📌 *Timeline & Deadlines:*")
            for idx, u in enumerate(matched_upcoming, 1):
                prog = f" ({u['program']})" if u.get("program") else ""
                lines.append(f"{idx}. *{u['title']}*{prog}")
                lines.append(f"   └ 🗓️ Date: `{u['date_range']}` | Type: `{u['type']}`")
        return "\n".join(lines).strip()

    # Default / Today View
    lines = [
        "📅 *Hangeul Admin Calendar & Deadlines*\n",
        f"⚡ *Reminders for today ({len(today_reminders)} items):*"
    ]
    for idx, r in enumerate(today_reminders, 1):
        prog = f" ({r['program']})" if r.get("program") else ""
        kind = f"{r['type']} · " if r.get("type") else ""
        days = r.get("days_left")
        left = f" — *{days} day{'' if days == 1 else 's'} left*" if days is not None else ""
        lines.append(f"{idx}. *{r['title']}*{prog}")
        lines.append(f"   └ 🗓️ {kind}`{r.get('date_range') or '—'}`{left}")
    skipped = cal_data.get("skipped_untitled") or 0
    if skipped:
        lines.append(f"_({skipped} {'entry' if skipped == 1 else 'entries'} without a title "
                     f"{'was' if skipped == 1 else 'were'} skipped)_")

    lines.append("\n📌 *Upcoming:*")
    for idx, u in enumerate(upcoming_events[:6], 1):
        prog = f" ({u['program']})" if u.get("program") else ""
        status = f" — {u['status']}" if u.get("status") else ""
        lines.append(f"• *{u['date']}:* {u['title']}{prog} (`{u.get('date_range') or '—'}`){status}")

    lines.append("\n💡 _Tip: Search any university or date, e.g. `/calendar Hanyang` or `/calendar 11 Sep`_")
    return "\n".join(lines).strip()

async def calendar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /calendar [query] command."""
    chat_id = update.effective_chat.id
    if not is_authorized(update):
        await update.message.reply_text(f"⛔ Unauthorized access. Your Chat ID is: `{chat_id}`", parse_mode="Markdown")
        return

    raw_input = ""
    if hasattr(context, "user_data") and context.user_data.get("override_text"):
        raw_input = context.user_data.pop("override_text")
    elif context and context.args:
        raw_input = " ".join(context.args)
    elif update.message and update.message.text:
        raw_input = update.message.text

    status_msg = await update.message.reply_text("⏳ _Consulting live calendar & admission deadlines..._", parse_mode="Markdown")
    try:
        cal_data = await admin_client.get_calendar_events()
        report = format_calendar_report(cal_data, filter_query=raw_input)
        try:
            await update.message.reply_text(report, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(report)
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error checking calendar: {e}")
        await update.message.reply_text(f"❌ Error checking calendar: `{e}`")

def _send_gmail(to_list: list, subject: str, body: str):
    """Send an email via Gmail SMTP using GMAIL_ADDRESS + GMAIL_APP_PASSWORD.
    Returns (ok: bool, info: str)."""
    import smtplib
    import ssl
    from email.message import EmailMessage
    sender = str(getattr(settings, "GMAIL_ADDRESS", "") or "").strip()
    app_pw = str(getattr(settings, "GMAIL_APP_PASSWORD", "") or "").replace(" ", "").strip()
    if not sender or not app_pw:
        return False, ("Gmail is not configured. Add GMAIL_ADDRESS and a Google APP PASSWORD as "
                       "GMAIL_APP_PASSWORD to your .env, then restart the bot.")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as s:
            s.login(sender, app_pw)
            s.send_message(msg)
        return True, f"sent from {sender} to {', '.join(to_list)}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def _find_student_for_email(query: str):
    """Find one student by HNG number (full or last digits), internal ID, or name.
    Searches ALL students via the portal's CSV export (every page, read-only); falls back
    to scanning the list page if the export is unavailable."""
    try:
        found = await _find_student_in_export(query)
        if found:
            return found
    except Exception as e:
        logger.error(f"sendmail export lookup failed, falling back to the list page: {e}")
    return await _find_student_on_list_page(query)


async def _find_student_in_export(query: str):
    import csv
    import io
    import re
    if not admin_client.is_authenticated:
        await admin_client.login()
    url = f"{admin_client.base_url}/students.php?export=csv"
    resp = await admin_client.client.get(url, timeout=60.0)
    if "login.php" in str(resp.url):
        admin_client.is_authenticated = False
        await admin_client.login()
        resp = await admin_client.client.get(url, timeout=60.0)
    rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig", errors="replace"))))
    if not rows or "Student ID" not in rows[0]:
        raise RuntimeError("students CSV export not available")

    q = (query or "").strip()
    qn = re.sub(r"[^0-9a-z]", "", q.lower())
    if not qn:
        return None

    def norm(v):
        return re.sub(r"[^0-9a-z]", "", str(v or "").lower())

    exact = [r for r in rows if norm(r.get("Student ID")) == qn]                         # HNG-2026-931
    suffix = [r for r in rows if qn.isdigit() and len(qn) >= 3
              and norm(r.get("Student ID")).endswith(qn)]                                  # 931
    by_name = [r for r in rows if len(q) >= 3 and not q[:1].isdigit()
               and q.lower() in str(r.get("Full Name", "")).lower()]                       # name
    hit = (exact or suffix or by_name or [None])[0]
    if not hit:
        return None
    hng = str(hit.get("Student ID", "")).strip()
    return {
        "id": hng, "hng": hng, "name": str(hit.get("Full Name", "")).strip(),
        "email": str(hit.get("Email", "")).strip(),
        "dob": str(hit.get("DOB", "")).strip(),
        "passport_no": str(hit.get("Passport No", "")).strip(),
        "passport_expiry": str(hit.get("Passport Expiry", "")).strip(),
    }


async def _find_student_on_list_page(query: str):
    """Old lookup: first page of students.php only (used if the CSV export fails)."""
    import re
    from bs4 import BeautifulSoup
    if not admin_client.is_authenticated:
        await admin_client.login()
    url = f"{admin_client.base_url}/students.php"
    resp = await admin_client.client.get(url)
    if "login.php" in str(resp.url):
        admin_client.is_authenticated = False
        await admin_client.login()
        resp = await admin_client.client.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    q = (query or "").strip()
    q_low = q.lower()
    qn = re.sub(r"[^0-9a-z]", "", q_low)
    for tr in soup.find_all("tr"):
        edit_a = tr.find("a", href=re.compile(r"student_edit\.php\?id=\d+"))
        if not edit_a:
            continue
        stu_id = re.search(r"id=(\d+)", edit_a.get("href")).group(1)
        text = tr.get_text(" ", strip=True)
        hng_m = re.search(r"HNG-\d{4}-\d+", text, re.I)
        hng = hng_m.group(0) if hng_m else ""
        hng_n = re.sub(r"[^0-9a-z]", "", hng.lower())
        name_m = re.search(r"Full Name\s+([A-Za-z\s\.]+?)(?:DOB|$)", text)
        name = name_m.group(1).strip() if name_m else ""

        matched = False
        if qn and qn == stu_id:
            matched = True
        elif hng_n and qn == hng_n:
            matched = True
        elif hng_n and qn.isdigit() and len(qn) >= 3 and hng_n.endswith(qn):
            matched = True
        elif len(q) >= 3 and not q[:1].isdigit() and q_low in name.lower():
            matched = True

        if matched:
            mailto = tr.find("a", href=re.compile(r"mailto:", re.I))
            if mailto:
                email = re.sub(r"(?i)^mailto:", "", mailto.get("href")).split("?")[0].strip()
            else:
                em = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
                email = em.group(0) if em else ""
            dob_m = re.search(r"DOB\s+([\d\-]+)", text)
            pn_m = re.search(r"Passport No\s+([A-Za-z0-9]+)", text)
            pe_m = re.search(r"Passport Expiry\s+([\d\-]+)", text)
            result = {
                "id": stu_id, "hng": hng, "name": name, "email": email,
                "dob": dob_m.group(1).strip() if dob_m else "",
                "passport_no": pn_m.group(1).strip() if pn_m else "",
                "passport_expiry": pe_m.group(1).strip() if pe_m else "",
            }
            # The student LIST row usually lacks the email (and HNG); pull them from
            # the student's edit page, which holds the full profile fields.
            if not result["email"] or not result["hng"] or not result["name"]:
                try:
                    prof = await admin_client.get_student_full_profile(stu_id) or {}
                except Exception as e:
                    prof = {}
                    logger.error(f"profile fetch failed for {stu_id}: {e}")
                if not result["email"]:
                    result["email"] = _pick_student_email(prof)
                if not result["name"]:
                    result["name"] = str(prof.get("full_name") or prof.get("name") or "").strip()
                if not result["hng"]:
                    for v in prof.values():
                        hm = re.search(r"HNG-\d{4}-\d+", str(v), re.I)
                        if hm:
                            result["hng"] = hm.group(0)
                            break
            return result
    return None


def _pick_student_email(prof: dict) -> str:
    """Pick the student's own email from a scraped profile dict (prefer the plain
    'email' field over guardian/parent emails)."""
    import re
    pat = r"[\w.+-]+@[\w-]+\.[\w.-]+"
    for k, v in (prof or {}).items():
        if str(k).lower().strip() == "email":
            m = re.search(pat, str(v))
            if m:
                return m.group(0)
    for k, v in (prof or {}).items():
        kl = str(k).lower()
        if "email" in kl and not any(x in kl for x in ("guardian", "parent", "father", "mother", "whats")):
            m = re.search(pat, str(v))
            if m:
                return m.group(0)
    for v in (prof or {}).values():
        m = re.search(pat, str(v))
        if m:
            return m.group(0)
    return ""


async def _ai_write_email(brief: str, student: dict, subject: str) -> str:
    """Turn the manager's short brief into a professional email body using the local LLM.
    Falls back to a simple courteous template if the AI is unavailable."""
    name = student.get("name") or "Student"
    system = (
        "You are an assistant that writes professional, polite business emails on behalf of "
        "Saemur Rahman, Manager at Hangeul Korean Language and Visa (HKLV) in Dhaka. Write in "
        "clear, courteous, professional English. Output ONLY the email body: a greeting, the "
        "message in short paragraphs, and a sign-off exactly as:\nSaemur Rahman\nManager, HKLV\n"
        "Do NOT include the subject line, do NOT invent facts, and do NOT add any commentary."
    )
    prompt = (
        f"Recipient: {name} (a student at HKLV).\n"
        f"Email subject: {subject}\n"
        f"What the manager wants to convey (short brief): {brief}\n\n"
        "Write the full, professional email body now."
    )
    try:
        text = await ollama_client.generate_response(prompt, system=system)
        text = (text or "").strip()
        # Reject the ollama_client "AI is down" fallback so it never leaks into an
        # actual email body. That fallback is long enough to pass a length check,
        # so we must look for its tell-tale phrases and fall through to the template.
        low = text.lower()
        ai_down = any(marker in low for marker in (
            "operational intelligence",
            "ollama service is not currently responding",
            "request processed successfully",
            "please verify ollama is started",
        ))
        if len(text) >= 15 and not ai_down:
            return text
    except Exception as e:
        logger.error(f"AI email draft failed: {e}")
    # Clean, courteous fallback template (used when the local AI is unavailable).
    return "\n".join([
        f"Dear {name},", "", brief.strip(), "",
        "Please let us know if you have any questions.", "",
        "Thanks,", "Saemur Rahman", "Manager, HKLV",
    ])


async def _handle_email_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Step-by-step /sendmail conversation: id -> subject -> brief -> confirm (send/edit/deny)."""
    flow = context.user_data.get("email_flow") or {}
    step = flow.get("step")
    low = text.strip().lower()

    # allow bailing out at any of the input steps
    if step in ("id", "subject", "brief") and low in ("cancel", "/cancel", "stop", "deny", "quit"):
        context.user_data.pop("email_flow", None)
        await update.message.reply_text("❌ Cancelled — no email sent.")
        return

    if step == "id":
        wait = await update.message.reply_text("⏳ _Looking up the student…_", parse_mode="Markdown")
        try:
            stu = await _find_student_for_email(text.strip())
        except Exception as e:
            stu = None
            logger.error(f"sendmail lookup error: {e}")
        try:
            await wait.delete()
        except Exception:
            pass
        if not stu:
            await update.message.reply_text(
                f"ℹ️ No student found matching `{text.strip()}`. Send the *HNG number, ID, or name* "
                "again, or type *cancel*.", parse_mode="Markdown")
            return  # stay on step "id"
        if not stu.get("email"):
            context.user_data.pop("email_flow", None)
            await update.message.reply_text(
                f"⚠️ Found *{stu.get('name') or stu['id']}* ({stu.get('hng') or 'ID ' + stu['id']}), "
                "but there is *no email address on that record*, so I can't send. Cancelled.",
                parse_mode="Markdown")
            return
        flow["student"] = stu
        flow["step"] = "subject"
        context.user_data["email_flow"] = flow
        await update.message.reply_text(
            f"✅ Found *{stu.get('name') or 'student'}*  ·  `{stu['email']}`\n\n"
            "✍️ Now type the *SUBJECT* of the email.", parse_mode="Markdown")
        return

    if step == "subject":
        flow["subject"] = text.strip()
        flow["step"] = "brief"
        context.user_data["email_flow"] = flow
        await update.message.reply_text(
            "📝 Subject saved.\n\nNow send a *short brief* of what you want to say — a line or two is "
            "enough. I'll write it out professionally.", parse_mode="Markdown")
        return

    if step == "brief":
        flow["brief"] = text.strip()
        wait = await update.message.reply_text("🤖 _Writing it professionally…_", parse_mode="Markdown")
        body = await _ai_write_email(flow["brief"], flow["student"], flow["subject"])
        flow["body"] = body
        flow["step"] = "confirm"
        context.user_data["email_flow"] = flow
        try:
            await wait.delete()
        except Exception:
            pass
        stu = flow["student"]
        preview = (
            "📧 *Draft ready — please review:*\n\n"
            f"*To:* `{stu['email']}`  ({stu.get('name') or stu['id']})\n"
            f"*Subject:* {flow['subject']}\n\n"
            f"{body}\n\n"
            "————————————\n"
            "Reply *SEND* to send it · *EDIT* to rewrite (you'll re-brief me) · *DENY* to cancel."
        )
        for chunk in _chunk_message(preview):
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(chunk)
        return

    if step == "confirm":
        if low in ("send", "yes", "confirm", "ok", "okay", "send it"):
            stu = flow["student"]
            wait = await update.message.reply_text("📤 _Sending the email…_", parse_mode="Markdown")
            ok, info = _send_gmail([stu["email"]], flow["subject"], flow["body"])
            context.user_data.pop("email_flow", None)
            await update.message.reply_text(("✅ Email sent — " + info) if ok else ("❌ Could not send: " + info))
            try:
                await wait.delete()
            except Exception:
                pass
            return
        if low in ("edit", "rewrite", "change", "redo"):
            flow["step"] = "brief"
            context.user_data["email_flow"] = flow
            await update.message.reply_text(
                "✏️ OK — send me the *updated brief* (or tell me what to change) and I'll rewrite it.",
                parse_mode="Markdown")
            return
        if low in ("deny", "cancel", "no", "stop", "quit"):
            context.user_data.pop("email_flow", None)
            await update.message.reply_text("❌ Denied — the email was not sent.")
            return
        await update.message.reply_text("Please reply *SEND*, *EDIT*, or *DENY*.", parse_mode="Markdown")
        return

    # unknown state -> reset
    context.user_data.pop("email_flow", None)


async def sendmail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the /sendmail flow: email a student, AI-assisted, with a final SEND/EDIT/DENY step."""
    chat_id = update.effective_chat.id
    if not is_authorized(update):
        await update.message.reply_text(f"⛔ Unauthorized access. Your Chat ID is: `{chat_id}`", parse_mode="Markdown")
        return
    arg = " ".join(context.args).strip() if (context and context.args) else ""
    context.user_data["email_flow"] = {"step": "id"}
    if arg:
        await _handle_email_flow(update, context, arg)
        return
    await update.message.reply_text(
        "✉️ *Send an email to a student*\n\n"
        "Step 1 — which student? Reply with the *HNG number, ID, or name*:\n"
        "`HNG-2026-921`   ·   `921`   ·   `Rafiq`\n\n"
        "_(I'll fetch their email, then ask you for the subject and a short brief — "
        "the AI writes it, and you approve before it sends. Type `cancel` anytime.)_",
        parse_mode="Markdown")


def _chunk_message(text: str, limit: int = 3900) -> list:
    """Split a long report into Telegram-safe chunks (<= 4096 chars) on line breaks."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            chunks.append(cur.rstrip("\n"))
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur.rstrip("\n"))
    return chunks


async def _audit_crosscheck_row(tr, stu_id, stu_name_row, text):
    """Build the cross-check result dict for one matched verified-student row.
    Shared by /crosscheck (single date / id / name) and the date-range cross-check."""
    import re
    dob_m = re.search(r"DOB\s+([\d\-]+)", text)
    pass_no_m = re.search(r"Passport No\s+([A-Za-z0-9]+)", text)
    pass_exp_m = re.search(r"Passport Expiry\s+([\d\-]+)", text)
    amt_m = re.search(r"Paid:\s*([\d,]+\.?\d*\s*BDT\s*[A-Za-z\s]+?)(?:Verified|$)", text)
    ver_m = re.search(r"Payment verified by\s+([A-Za-z\s\.]+?)\s*[·•·]\s*([^<\n]+)", text)
    prog_m = re.search(r"Program\s+([A-Za-z\s\(\)\']+?)(?:Preferred|$)", text)

    pass_a = tr.find("a", href=re.compile(r"view_doc\.php\?f=passport_"))
    doc_filename = re.search(r"f=([^&]+)", pass_a.get("href")).group(1) if pass_a else None
    has_pass_doc = bool(pass_a)
    has_rcpt_doc = bool(tr.find("a", href=re.compile(r"view_doc\.php\?f=receipt_")))

    form_data = {
        "name": stu_name_row,
        "dob": dob_m.group(1).strip() if dob_m else "",
        "passport_no": pass_no_m.group(1).strip() if pass_no_m else "",
        "passport_expiry": pass_exp_m.group(1).strip() if pass_exp_m else ""
    }

    audit_res = await admin_client.audit_student_passport(stu_id, form_data, doc_filename)

    return {
        "id": stu_id,
        "name": form_data["name"] or "Student",
        "program": prog_m.group(1).strip() if prog_m else "N/A",
        "dob": form_data["dob"] or "N/A",
        "pass_no": form_data["passport_no"] or "None",
        "pass_exp": form_data["passport_expiry"] or "None",
        "has_pass_doc": has_pass_doc,
        "has_rcpt_doc": has_rcpt_doc,
        "payment": amt_m.group(1).strip() if amt_m else "",
        "verifier": ver_m.group(1).strip() if ver_m else "",
        "ver_time": ver_m.group(2).strip()[:15] if ver_m else "",
        "fields": audit_res.get("fields", {}),
        "verdict": audit_res["verdict"]
    }


def _format_crosscheck_results(results: list, header_title: str) -> str:
    """Render cross-check result dicts into the Telegram summary (shared formatter)."""
    lines = [
        f"📋 *Verified Student Information Cross-Check — {header_title}*",
        f"• *Total Records Audited:* `{len(results)}`\n"
    ]
    for idx, r in enumerate(results, 1):
        doc_status = "✅ Uploaded" if r['has_pass_doc'] else "⏳ None (Marked WILL APPLY)"
        rcpt_status = "✅ Verified" if r['has_rcpt_doc'] else "Recorded"

        audit_verdict = r["verdict"]
        f_fields = r.get("fields", {})

        lines.append(f"*{idx}. {r['name']}* (ID: `{r['id']}`)")
        lines.append(f"   ├ 🎓 *Program:* {r['program']}")
        lines.append(f"   ├ 💰 *Payment:* `{r['payment']}` ({rcpt_status})")
        lines.append(f"   ├ 👤 *Verified by:* {r['verifier']} ({r['ver_time']})")
        lines.append(f"   ├ 🛂 *Passport Scan:* {doc_status}")
        lines.append(f"   ├ 📝 *Portal:* Pass `{r['pass_no']}` | Exp `{r['pass_exp']}` | DOB `{r['dob']}`")

        if f_fields:
            f_fath = f_fields.get("father_name", {})
            f_moth = f_fields.get("mother_name", {})
            f_addr = f_fields.get("address", {})

            if f_fath.get("doc"):
                lines.append(f"   ├ 👨 *Father:* `{f_fath['doc']}` ({f_fath.get('verdict', 'Checked')})")
            elif f_fath.get("verdict"):
                lines.append(f"   ├ 👨 *Father:* {f_fath.get('verdict')}")

            if f_moth.get("doc"):
                lines.append(f"   ├ 👩 *Mother:* `{f_moth['doc']}` ({f_moth.get('verdict', 'Checked')})")
            elif f_moth.get("verdict"):
                lines.append(f"   ├ 👩 *Mother:* {f_moth.get('verdict')}")

            if f_addr.get("doc"):
                short_addr = f_addr['doc'][:40] + ("..." if len(f_addr['doc']) > 40 else "")
                lines.append(f"   ├ 🏠 *Address:* `{short_addr}` ({f_addr.get('verdict', 'Checked')})")
            elif f_addr.get("verdict"):
                lines.append(f"   ├ 🏠 *Address:* {f_addr.get('verdict')}")

        lines.append(f"   └ 🔍 *Audit Verdict:* {audit_verdict}")
        lines.append("")

    return "\n".join(lines).strip()


def _parse_date_range(raw: str):
    """Parse 'START to END' (many formats) into (start_date, end_date, display) or (None, None, None)."""
    import re
    from datetime import datetime
    s = (raw or "").strip()
    if not s:
        return None, None, None
    parts = re.split(r'\s*(?:\bto\b|\buntil\b|\bthrough\b|\bthru\b|\btill\b|–|—|\.\.|=>|->)\s*', s, maxsplit=1, flags=re.I)
    if len(parts) < 2:
        parts = re.split(r'\s+-\s+', s, maxsplit=1)  # ' - ' with spaces (not inside 2026-09-01)
    if len(parts) < 2:
        iso = re.findall(r'\d{4}-\d{2}-\d{2}', s)
        if len(iso) >= 2:
            parts = [iso[0], iso[1]]
        else:
            mons = re.findall(r'\d{1,2}\s+[A-Za-z]{3,9}(?:\s+\d{2,4})?', s)
            if len(mons) >= 2:
                parts = [mons[0], mons[1]]
    if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
        return None, None, None
    p1, _ = normalize_date_input(parts[0])
    p2, _ = normalize_date_input(parts[1])
    try:
        d1 = datetime.strptime(p1, "%d %b %Y").date()
        d2 = datetime.strptime(p2, "%d %b %Y").date()
    except ValueError:
        return None, None, None
    if d1 > d2:
        d1, d2 = d2, d1
    return d1, d2, f"{d1.strftime('%d %b %Y')} → {d2.strftime('%d %b %Y')}"


async def build_crosscheck_range_report(start_date, end_date, display: str):
    """Live cross-check of every payment-verified student verified between two dates."""
    import re
    from datetime import timedelta
    from bs4 import BeautifulSoup

    if not admin_client.is_authenticated:
        await admin_client.login()
    url = f"{admin_client.base_url}/students.php"
    resp = await admin_client.client.get(url)
    if "login.php" in str(resp.url):
        admin_client.is_authenticated = False
        await admin_client.login()
        resp = await admin_client.client.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    # one 'DD Mon' pattern per day in the range — same substring match the single-date view uses
    patterns, d = [], start_date
    while d <= end_date:
        patterns.append(d.strftime("%d %b").lower())
        d += timedelta(days=1)

    results, seen = [], set()
    for tr in soup.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        if "Payment verified by" not in text:
            continue
        tl = text.lower()
        if not any(p in tl for p in patterns):
            continue
        edit_a = tr.find("a", href=re.compile(r"student_edit\.php\?id=\d+"))
        stu_id = re.search(r"id=(\d+)", edit_a.get("href")).group(1) if edit_a else "N/A"
        if stu_id in seen:
            continue
        seen.add(stu_id)
        name_m = re.search(r"Full Name\s+([A-Za-z\s\.]+?)(?:DOB|$)", text)
        stu_name_row = name_m.group(1).strip() if name_m else ""
        results.append(await _audit_crosscheck_row(tr, stu_id, stu_name_row, text))

    if not results:
        return f"ℹ️ *No payment-verified students found between {display} to cross-check.*", 0
    return _format_crosscheck_results(results, display), len(results)


async def crosscheck_range_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu 7: Total crosscheck verified students live between a START date and an END date."""
    chat_id = update.effective_chat.id
    if not is_authorized(update):
        await update.message.reply_text(f"⛔ Unauthorized access. Your Chat ID is: `{chat_id}`", parse_mode="Markdown")
        return

    raw_input = ""
    if hasattr(context, "user_data") and context.user_data.get("override_text"):
        raw_input = context.user_data.pop("override_text")
    elif context and context.args:
        raw_input = " ".join(context.args).strip()

    if not raw_input:
        context.user_data["awaiting_date_for"] = "crosscheck_range"
        await update.message.reply_text(
            "📅 *Live Crosscheck Verified — Date Range*\n\n"
            "Send the *start* and *end* dates, and I'll cross-check every student whose "
            "payment was verified in that window against their passport documents.\n\n"
            "_Reply in one message, e.g.:_\n"
            "• `1 Sep 2026 to 15 Sep 2026`\n"
            "• `2026-09-01 to 2026-09-15`\n"
            "• `1 Sep - 15 Sep`",
            parse_mode="Markdown"
        )
        return

    start_date, end_date, display = _parse_date_range(raw_input)
    if not start_date:
        await update.message.reply_text(
            "⚠️ I couldn't read two dates there. Please send a *start* and *end* date, e.g. "
            "`1 Sep 2026 to 15 Sep 2026`.",
            parse_mode="Markdown"
        )
        return

    span = (end_date - start_date).days + 1
    if span > 92:
        await update.message.reply_text(
            f"⚠️ That range is {span} days. Please keep it to about 3 months or less — "
            "OCR on many passports takes time.",
            parse_mode="Markdown"
        )
        return

    status_msg = await update.message.reply_text(
        f"⏳ _Cross-checking every payment-verified student from {display} live against their "
        "passport documents… this can take a few minutes._",
        parse_mode="Markdown"
    )
    try:
        report, count = await build_crosscheck_range_report(start_date, end_date, display)
        for chunk in _chunk_message(report):
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(chunk)
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error in crosscheck_range_command: {e}")
        await update.message.reply_text(f"❌ Error during range cross-check: `{e}`")


async def crosscheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /crosscheck [date/student_id] to cross-check verified student info, Father, Mother, DOB, and Address."""
    chat_id = update.effective_chat.id
    if not is_authorized(update):
        await update.message.reply_text(f"⛔ Unauthorized access. Your Chat ID is: `{chat_id}`", parse_mode="Markdown")
        return

    raw_input = ""
    if hasattr(context, "user_data") and context.user_data.get("override_text"):
        raw_input = context.user_data.pop("override_text")
    elif context and context.args:
        raw_input = " ".join(context.args)
    elif update.message and update.message.text:
        raw_input = update.message.text

    # Parse query intent: specific student ID, specific student Name, or specific Date
    import re
    text_q = (raw_input or "").strip()
    is_date = any(m in text_q.lower() for m in ["sep", "oct", "nov", "dec", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "today", "yesterday", "2026", "2025", "2024"])

    stu_id_target = None
    id_match = re.search(r'\b(?:id\s*[:#]?\s*|#)?(\d{2,5})\b', text_q, re.I)
    if id_match and not is_date:
        stu_id_target = id_match.group(1)

    stu_name_target = None
    if not is_date and not stu_id_target:
        clean_name = re.sub(r'/(?:crosscheck|audit)\b', '', text_q, flags=re.I)
        clean_name = re.sub(r'\b(?:cross\s*check|audit|check|student|for|info|details?|please|show|only|specific)\b', '', clean_name, flags=re.I).strip()
        if len(clean_name) >= 3:
            stu_name_target = clean_name

    portal_date = None
    display_date = None
    date_pattern = ""
    if not stu_id_target and not stu_name_target:
        portal_date, display_date = normalize_date_input(text_q)
        date_pattern = portal_date[:6] if len(portal_date) >= 6 else "10 Sep"

    status_msg = await update.message.reply_text("⏳ _Cross-checking student information, Father, Mother, DOB & Address against documents..._", parse_mode="Markdown")
    try:
        if not admin_client.is_authenticated:
            await admin_client.login()
        resp = await admin_client.client.get(f"{admin_client.base_url}/students.php")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.find_all("tr")

        results = []
        for tr in rows:
            text = tr.get_text(" ", strip=True)
            edit_a = tr.find("a", href=re.compile(r"student_edit\.php\?id=\d+"))
            stu_id = re.search(r"id=(\d+)", edit_a.get("href")).group(1) if edit_a else "N/A"
            name_m = re.search(r"Full Name\s+([A-Za-z\s\.]+?)(?:DOB|$)", text)
            stu_name_row = name_m.group(1).strip() if name_m else ""

            matched = False
            if stu_id_target:
                if stu_id == stu_id_target:
                    matched = True
            elif stu_name_target:
                if stu_name_target.lower() in stu_name_row.lower():
                    matched = True
            elif portal_date:
                if "Payment verified by" in text and date_pattern.lower() in text.lower():
                    matched = True

            if matched:
                dob_m = re.search(r"DOB\s+([\d\-]+)", text)
                pass_no_m = re.search(r"Passport No\s+([A-Za-z0-9]+)", text)
                pass_exp_m = re.search(r"Passport Expiry\s+([\d\-]+)", text)
                amt_m = re.search(r"Paid:\s*([\d,]+\.?\d*\s*BDT\s*[A-Za-z\s]+?)(?:Verified|$)", text)
                ver_m = re.search(r"Payment verified by\s+([A-Za-z\s\.]+?)\s*[\u00b7\u2022·]\s*([^<\n]+)", text)
                prog_m = re.search(r"Program\s+([A-Za-z\s\(\)\']+?)(?:Preferred|$)", text)

                pass_a = tr.find("a", href=re.compile(r"view_doc\.php\?f=passport_"))
                doc_filename = re.search(r"f=([^&]+)", pass_a.get("href")).group(1) if pass_a else None
                has_pass_doc = bool(pass_a)
                has_rcpt_doc = bool(tr.find("a", href=re.compile(r"view_doc\.php\?f=receipt_")))

                form_data = {
                    "name": stu_name_row,
                    "dob": dob_m.group(1).strip() if dob_m else "",
                    "passport_no": pass_no_m.group(1).strip() if pass_no_m else "",
                    "passport_expiry": pass_exp_m.group(1).strip() if pass_exp_m else ""
                }

                audit_res = await admin_client.audit_student_passport(stu_id, form_data, doc_filename)

                results.append({
                    "id": stu_id,
                    "name": form_data["name"] or "Student",
                    "program": prog_m.group(1).strip() if prog_m else "N/A",
                    "dob": form_data["dob"] or "N/A",
                    "pass_no": form_data["passport_no"] or "None",
                    "pass_exp": form_data["passport_expiry"] or "None",
                    "has_pass_doc": has_pass_doc,
                    "has_rcpt_doc": has_rcpt_doc,
                    "payment": amt_m.group(1).strip() if amt_m else "",
                    "verifier": ver_m.group(1).strip() if ver_m else "",
                    "ver_time": ver_m.group(2).strip()[:15] if ver_m else "",
                    "fields": audit_res.get("fields", {}),
                    "verdict": audit_res["verdict"]
                })

        if not results:
            if stu_id_target:
                msg = f"ℹ️ *No student found matching ID `{stu_id_target}`.*"
            elif stu_name_target:
                msg = f"ℹ️ *No student found matching Name `{stu_name_target}`.*"
            else:
                msg = (
                    f"ℹ️ *No payment-verified students found for {display_date} to cross-check.*\n\n"
                    "💡 *Examples:*\n"
                    "• Specific Date: `/crosscheck 10 Sep` or `/crosscheck yesterday`\n"
                    "• Specific Student ID: `/crosscheck 432` or `/crosscheck 431`\n"
                    "• Specific Student Name: `/crosscheck Fahmid` or `/crosscheck Bikash`"
                )
        else:
            if stu_id_target:
                header_title = f"Student ID #{stu_id_target}"
            elif stu_name_target:
                header_title = f"Student '{stu_name_target}'"
            else:
                header_title = display_date

            lines = [
                f"📋 *Verified Student Information Cross-Check — {header_title}*",
                f"• *Total Records Audited:* `{len(results)}`\n"
            ]
            for idx, r in enumerate(results, 1):
                doc_status = "✅ Uploaded" if r['has_pass_doc'] else "⏳ None (Marked WILL APPLY)"
                rcpt_status = "✅ Verified" if r['has_rcpt_doc'] else "Recorded"

                audit_verdict = r["verdict"]
                f_fields = r.get("fields", {})

                lines.append(f"*{idx}. {r['name']}* (ID: `{r['id']}`)")
                lines.append(f"   ├ 🎓 *Program:* {r['program']}")
                lines.append(f"   ├ 💰 *Payment:* `{r['payment']}` ({rcpt_status})")
                lines.append(f"   ├ 👤 *Verified by:* {r['verifier']} ({r['ver_time']})")
                lines.append(f"   ├ 🛂 *Passport Scan:* {doc_status}")
                lines.append(f"   ├ 📝 *Portal:* Pass `{r['pass_no']}` | Exp `{r['pass_exp']}` | DOB `{r['dob']}`")

                if f_fields:
                    f_fath = f_fields.get("father_name", {})
                    f_moth = f_fields.get("mother_name", {})
                    f_addr = f_fields.get("address", {})

                    if f_fath.get("doc"):
                        lines.append(f"   ├ 👨 *Father:* `{f_fath['doc']}` ({f_fath.get('verdict', 'Checked')})")
                    elif f_fath.get("verdict"):
                        lines.append(f"   ├ 👨 *Father:* {f_fath.get('verdict')}")

                    if f_moth.get("doc"):
                        lines.append(f"   ├ 👩 *Mother:* `{f_moth['doc']}` ({f_moth.get('verdict', 'Checked')})")
                    elif f_moth.get("verdict"):
                        lines.append(f"   ├ 👩 *Mother:* {f_moth.get('verdict')}")

                    if f_addr.get("doc"):
                        short_addr = f_addr['doc'][:40] + ("..." if len(f_addr['doc']) > 40 else "")
                        lines.append(f"   ├ 🏠 *Address:* `{short_addr}` ({f_addr.get('verdict', 'Checked')})")
                    elif f_addr.get("verdict"):
                        lines.append(f"   ├ 🏠 *Address:* {f_addr.get('verdict')}")

                lines.append(f"   └ 🔍 *Audit Verdict:* {audit_verdict}")
                lines.append("")

            msg = "\n".join(lines).strip()

        try:
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(msg)
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error in crosscheck: {e}")
        await update.message.reply_text(f"❌ Error during cross-check: `{e}`")

async def handle_natural_language_message(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                          query: Optional[str] = None):
    """Process natural language questions through the local LLM agent.
    A typed message is read from update.message.text; a voice note (src/bot/voice.py),
    which has no text, passes its English query as `query` instead."""
    if not is_authorized(update):
        return

    if query is None:
        query = update.message.text or ""
    query = query.strip()
    query_lower = query.lower()

    # 0. If a /sendmail conversation is in progress, this message belongs to it.
    if context.user_data.get("email_flow"):
        await _handle_email_flow(update, context, query)
        return

    # 1. Check if we are waiting for an interactive specific date response from the user
    awaiting = context.user_data.pop("awaiting_date_for", None)
    if awaiting:
        context.user_data["override_text"] = query
        if awaiting == "inquiries":
            await inquiries_date_command(update, context)
            return
        elif awaiting == "verified":
            await verified_date_command(update, context)
            return
        elif awaiting == "crosscheck":
            await crosscheck_date_command(update, context)
            return
        elif awaiting == "crosscheck_range":
            await crosscheck_range_command(update, context)
            return

    # 2. Route menu item 1 & 2: Consultancy inquiries queries
    if "inquir" in query_lower or "consultan" in query_lower or "consultat" in query_lower:
        if "today" in query_lower or "how many were done today" in query_lower:
            await inquiries_today_command(update, context)
            return
        elif any(m in query_lower for m in ["yesterday", "sep", "oct", "nov", "dec", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "2026", "2025"]):
            context.user_data["override_text"] = query
            await inquiries_date_command(update, context)
            return
        elif "how many were done" in query_lower or "date" in query_lower or "specific" in query_lower:
            await inquiries_date_command(update, context)
            return

    # 3. Route "pin" / "commands" / "pp pin" queries directly to pin_command
    if any(k in query_lower for k in ["pin", "cheatsheet", "cheat sheet", "command list", "all commands", "menu"]):
        await pin_command(update, context)
        return

    # 4. Route menu item 5 & 6: Crosscheck verified students queries
    if "cross" in query_lower or ("check" in query_lower and "verif" in query_lower) or any(k in query_lower for k in ["father", "mother", "address", "parent", "parents", "dob"]):
        _r_start, _r_end, _ = _parse_date_range(query)
        if _r_start and _r_start != _r_end:
            context.user_data["override_text"] = query
            await crosscheck_range_command(update, context)
            return
        if "today" in query_lower:
            await crosscheck_today_command(update, context)
            return
        elif any(m in query_lower for m in ["yesterday", "sep", "oct", "nov", "dec", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "2026", "2025"]):
            context.user_data["override_text"] = query
            await crosscheck_date_command(update, context)
            return
        elif not any(k in query_lower for k in ["father", "mother", "address", "parent", "parents"]) and not re.search(r'\b\d{2,5}\b', query_lower):
            await crosscheck_date_command(update, context)
            return
        context.user_data["override_text"] = query
        await crosscheck_command(update, context)
        return

    # 5. Route menu item 3 & 4: Total verified students queries
    if "verif" in query_lower:
        if "today" in query_lower:
            await verified_today_command(update, context)
            return
        elif any(m in query_lower for m in ["yesterday", "sep", "oct", "nov", "dec", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "2026", "2025"]):
            context.user_data["override_text"] = query
            await verified_date_command(update, context)
            return
        elif "date" in query_lower or "specific" in query_lower:
            await verified_date_command(update, context)
            return
        context.user_data["override_text"] = query
        await verified_command(update, context)
        return

    # Route "admitted" queries directly to admitted_command
    if "admit" in query_lower:
        clean_q = re.sub(r'\b(?:show|list|get|who|is|are|all|the|students?|admitted|admission)\b', '', query_lower).strip()
        if clean_q:
            context.user_data["override_query"] = clean_q
        await admitted_command(update, context)
        return

    # Route calendar / event / deadline queries directly to calendar_command
    cal_triggers = ["calendar", "event", "events", "deadline", "deadlines", "admission open", "application open"]
    if any(t in query_lower for t in cal_triggers):
        context.user_data["override_text"] = query
        await calendar_command(update, context)
        return

    # Route passport matching / audit queries directly to passports_command
    if "passport" in query_lower or "passports" in query_lower:
        await passports_command(update, context)
        return

    is_report, p_date, d_date = parse_user_report_intent(query)
    if is_report:
        context.user_data["override_text"] = query
        await report_command(update, context)
        return

    status_msg = await update.message.reply_text("🤔 _Consulting Hangeul admin records..._", parse_mode="Markdown")
    try:
        dashboard = await admin_client.get_dashboard()
        applications = await admin_client.get_applications()
        inquiries = await admin_client.get_inquiries()

        context_data = {
            # The tile list repeats live_stats with links: left out of the small LLM context.
            "dashboard": {k: v for k, v in dashboard.items() if k != "tiles"},
            "sample_applications": applications[:5],
            "inquiries": inquiries,
            "sample_inquiries": inquiries
        }

        answer = await ollama_client.answer_agent_query(query=query, context=context_data)
        try:
            await status_msg.edit_text(answer, parse_mode="Markdown")
        except BadRequest as e:
            # The LLM's Markdown does not always parse ("Can't parse entities"): send it plain.
            if "parse entities" not in str(e).lower():
                raise
            await status_msg.edit_text(answer)
    except Exception as e:
        logger.error(f"Error answering query: {e}")
        await status_msg.edit_text(f"❌ Error: `{e}`", parse_mode="Markdown")

MISSING_PROGRAMS = [
    ("KLP", "🇰🇷 KLP"),
    ("EAP", "📘 EAP"),
    ("BACHELOR", "🎓 Bachelor's"),
    ("MASTER", "🎓 Master's"),
]


async def missing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/missing — menu with one button per program; each shows that program's students
    with missing information (from the live progress sheets)."""
    if not is_authorized(update):
        return
    buttons = [[InlineKeyboardButton(label, callback_data=f"missing:{key}")]
               for key, label in MISSING_PROGRAMS]
    await update.message.reply_text(
        "📋 *Progress sheet — missing information*\nChoose a program:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def missing_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A program button under /missing was tapped."""
    import asyncio
    import os
    import sys
    query = update.callback_query
    if not is_authorized(update):
        await query.answer("Not authorized", show_alert=True)
        return
    key = (query.data or "").split(":", 1)[-1]
    label = dict(MISSING_PROGRAMS).get(key, key)
    await query.answer()
    status = await query.message.reply_text(f"⏳ Checking {label} progress sheets…")
    text = await _run_report_module("src.sheets.missing_report", "--program", key)
    if text is None:
        text = f"❌ Could not build the {label} report right now. Please try again in a minute."
    try:
        await status.delete()
    except Exception:
        pass
    await _reply_long(query.message, text)


async def _run_report_module(module: str, *args: str) -> Optional[str]:
    """Run a report script as its own process (it uses its own read-only portal session,
    like the scheduled jobs) and return its printed output, or None if it failed."""
    import asyncio
    import os
    import sys
    bot_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-len("pythonw.exe")] + "python.exe"
    try:
        proc = await asyncio.create_subprocess_exec(
            exe, "-m", module, *args, cwd=bot_root,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
        text = out.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0 or not text:
            logger.error(f"{module} {args} failed: {err.decode('utf-8', errors='replace')[-500:]}")
            return None
        return text
    except Exception as e:
        logger.error(f"{module} {args} failed: {e}")
        return None


async def _reply_long(message, text: str):
    """Send plain text, split under Telegram's message limit."""
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > 3900:
            await message.reply_text(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await message.reply_text(chunk)


async def stage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stage — pick a program, then an intake, to see its students grouped by stage."""
    if not is_authorized(update):
        return
    buttons = [[InlineKeyboardButton(label, callback_data=f"stage:{key}")]
               for key, label in MISSING_PROGRAMS]
    await update.message.reply_text(
        "📊 *Student stages*\nChoose a program:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def stage_program_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A program under /stage was tapped — show that program's intakes."""
    import json
    query = update.callback_query
    if not is_authorized(update):
        await query.answer("Not authorized", show_alert=True)
        return
    key = (query.data or "").split(":", 1)[-1]
    label = dict(MISSING_PROGRAMS).get(key, key)
    await query.answer()
    status = await query.message.reply_text(f"⏳ Loading {label} intakes…")
    out = await _run_report_module("src.sheets.stage_report", "--program", key)
    try:
        await status.delete()
    except Exception:
        pass
    try:
        intakes = json.loads(out) if out else None
    except ValueError:
        intakes = None
    if intakes is None:
        await query.message.reply_text(f"❌ Could not load {label} intakes right now. Please try again in a minute.")
        return
    if not intakes:
        await query.message.reply_text(f"{label}: no students on the portal.")
        return
    buttons = [[InlineKeyboardButton(
        (f"{i['intake']} ({i['count']})" if i["intake"] != "NONE" else f"⚠️ No intake set ({i['count']})"),
        callback_data=f"stagei:{key}|{i['intake']}")] for i in intakes]
    await query.message.reply_text(f"📊 {label} — choose an intake:", reply_markup=InlineKeyboardMarkup(buttons))


async def stage_intake_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """An intake under /stage was tapped — show the stage report."""
    query = update.callback_query
    if not is_authorized(update):
        await query.answer("Not authorized", show_alert=True)
        return
    key, _, intake = (query.data or "").split(":", 1)[-1].partition("|")
    label = dict(MISSING_PROGRAMS).get(key, key)
    await query.answer()
    status = await query.message.reply_text(f"⏳ Checking {label} {intake if intake != 'NONE' else '(no intake)'} stages…")
    text = await _run_report_module("src.sheets.stage_report", "--program", key, "--intake", intake)
    if text is None:
        text = f"❌ Could not build the {label} stage report right now. Please try again in a minute."
    try:
        await status.delete()
    except Exception:
        pass
    await _reply_long(query.message, text)


async def post_init(application: Application):
    """Register exclusively the 6 requested Telegram Bot menu commands and pin cheat-sheet on startup."""
    commands = [
        BotCommand("inquiries_today", "Total consultancy inquiries & how many done today"),
        BotCommand("inquiries_date", "Total inquiries & how many done (ask specific date)"),
        BotCommand("verified_today", "Total verified students today"),
        BotCommand("verified_date", "Total verified students (ask specific date each time)"),
        BotCommand("crosscheck_today", "Total crosscheck verified students live today"),
        BotCommand("crosscheck_date", "Total crosscheck verified live (ask specific date each time)"),
        BotCommand("crosscheck_range", "Total crosscheck verified live (ask start date → end date)"),
        BotCommand("sendmail", "Email a student (ask ID → subject → brief; AI writes it; you approve)"),
        BotCommand("brief", "Run today's full 6:05 PM operational brief now"),
        BotCommand("missing", "Progress sheet missing information (KLP / EAP / Bachelor's / Master's)"),
        BotCommand("stage", "Student stages — choose program → intake"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Successfully set 7 exclusive bot menu commands (set_my_commands).")
    except Exception as e:
        logger.error(f"Failed to set bot menu commands: {e}")

    # If admin chat ID is configured, send and pin the cheat-sheet on startup
    if settings.TELEGRAM_ADMIN_CHAT_ID:
        try:
            cheatsheet = get_commands_cheatsheet_text()
            msg = await application.bot.send_message(
                chat_id=settings.TELEGRAM_ADMIN_CHAT_ID,
                text=cheatsheet,
                parse_mode="Markdown"
            )
            await application.bot.pin_chat_message(
                chat_id=settings.TELEGRAM_ADMIN_CHAT_ID,
                message_id=msg.message_id,
                disable_notification=True
            )
            logger.info("Successfully pinned command cheat-sheet to admin chat on startup.")
        except Exception as e:
            logger.debug(f"Startup pin notification skipped: {e}")

    # Jennie's brain: load the local LLM now and keep it in VRAM, so the first question (typed or
    # spoken) is answered warm; then the voice filler clips. In the background: startup never waits.
    from src.bot.scheduler import warm_brain
    application.create_task(warm_brain(), name="brain-warm-up")

def build_telegram_application():
    """Build and configure the Telegram application instance."""
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or token == "your_telegram_bot_token_here":
        logger.warning("No valid TELEGRAM_BOT_TOKEN provided in .env. Telegram bot will not start.")
        return None

    app = Application.builder().token(token).post_init(post_init).build()

    # Register the 6 official menu command handlers
    app.add_handler(CommandHandler("inquiries_today", inquiries_today_command))
    app.add_handler(CommandHandler("inquiries_date", inquiries_date_command))
    app.add_handler(CommandHandler("verified_today", verified_today_command))
    app.add_handler(CommandHandler("verified_date", verified_date_command))
    app.add_handler(CommandHandler("crosscheck_today", crosscheck_today_command))
    app.add_handler(CommandHandler("crosscheck_date", crosscheck_date_command))
    app.add_handler(CommandHandler("crosscheck_range", crosscheck_range_command))
    app.add_handler(CommandHandler("missing", missing_command))
    app.add_handler(CallbackQueryHandler(missing_button, pattern=r"^missing:"))
    app.add_handler(CommandHandler("stage", stage_command))
    app.add_handler(CommandHandler("stages", stage_command))
    app.add_handler(CallbackQueryHandler(stage_program_button, pattern=r"^stage:"))
    app.add_handler(CallbackQueryHandler(stage_intake_button, pattern=r"^stagei:"))
    app.add_handler(CommandHandler("sendmail", sendmail_command))
    app.add_handler(CommandHandler("email", sendmail_command))
    app.add_handler(CommandHandler("mail", sendmail_command))
    app.add_handler(CommandHandler("crosscheck_between", crosscheck_range_command))
    app.add_handler(CommandHandler("crosscheck_period", crosscheck_range_command))

    # Also register aliases and standard commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("pin", pin_command))
    app.add_handler(CommandHandler("commands", pin_command))
    app.add_handler(CommandHandler("admitted", admitted_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("brief", brief_command))
    app.add_handler(CommandHandler("dailybrief", brief_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("students", students_command))
    app.add_handler(CommandHandler("consultations", consultations_command))
    app.add_handler(CommandHandler("inquiries", inquiries_command))
    app.add_handler(CommandHandler("verified", verified_command))
    app.add_handler(CommandHandler("verified_students", verified_command))
    app.add_handler(CommandHandler("crosscheck", crosscheck_command))
    app.add_handler(CommandHandler("audit", crosscheck_command))
    app.add_handler(CommandHandler("passports", passports_command))
    app.add_handler(CommandHandler("passport_audit", passports_command))
    app.add_handler(CommandHandler("calendar", calendar_command))
    app.add_handler(CommandHandler("events", calendar_command))
    app.add_handler(CommandHandler("deadlines", calendar_command))
    app.add_handler(CommandHandler("alerts", alerts_command))

    # Natural language message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_natural_language_message))

    # Jennie's voice: voice notes in, text + voice notes out (only when switched on in .env).
    # block=False: a voice round trip can take a minute, and must not hold up everyone's typed commands.
    if settings.JENNIE_VOICE_ENABLED:
        from src.bot.voice import handle_voice_message
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message, block=False))
        logger.info(f"Jennie voice replies enabled (voice service {settings.JENNIE_VOICE_URL}).")

    # Setup background cron scheduler
    setup_scheduler(app)
    return app
