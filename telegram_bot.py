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

# The words a date request may have around its date ("report for 07 Sep 2026", "/verified_date
# yesterday", "how many students were verified"): what is left once they are gone is the date.
_DATE_FILLER_RE = re.compile(
    r"/\w+(?:@\w+)?|[?!.,:;'\"()]|\b(?:reports?|consultations?|consultancy|inquir(?:y|ies)|enquir(?:y|ies)|requests?"
    r"|verified|verifications?|verify|students?|payments?|paid|crosscheck|cross\s*check|audit|check|only|specific"
    r"|specif|dates?|days?|for|of|on|in|at|the|a|an|and|to|by|please|pls|show|give|get|got|tell|me|us|how|many"
    r"|much|were|was|is|are|be|been|did|do|does|done|has|have|had|their|there|total|list|who|what|which|number"
    r"|count|all|any|brief|summary|daily|came|come|received|new)\b", re.I)


def normalize_date_input(text: str, strict: bool = False) -> Optional[tuple]:
    """The date a user's text names, as (portal 'DD Mon YYYY', display 'DD Month YYYY'), e.g. from
    'yesterday', '9 Sep', '08/09/2026', 'report for 07 Sep 2026', '/report 08 Sep 2026'.

    Read by the one strict parser, src.dates.parse_user_date (month names only as whole words; a
    date typed without a year is the latest one not after today). A text with no date in it at
    all (a bare '/report', 'how many students were verified') is today. None when the text has
    something date-like that is not a readable date ('31 Sep 2026', 'Sep', '12th', 'last week'),
    or, with strict, anything besides the command and filler words ('/verified_date foo'): the
    caller then replies with src.bot.replies.date_error_reply. Never a silent stand-in day."""
    from src.dates import has_date_hint, local_today, parse_user_date
    today = local_today()
    day = parse_user_date(text or "", today, prefer_past=True)
    if day is None:
        rest = re.sub(r"\s+", " ", _DATE_FILLER_RE.sub(" ", text or "")).strip()
        if rest and (strict or has_date_hint(rest)):
            return None
        day = today
    return day.strftime("%d %b %Y"), day.strftime("%d %B %Y")

def parse_user_report_intent(text: str) -> tuple[bool, str, str]:
    """Whether a text asks for the day's report (the factual brief, /report), and for which date.
    Only a real report request counts: /report, or "report", "brief", "summary", "overview" or
    "recap" with no subject that has its own answer (src.bot.ask.classify: "consultation report"
    is the consultations, "how many ... today" is never a report, and month names count only as
    whole words next to a day). The dates are "" when the text's date cannot be read (report_command
    then says so)."""
    from src.bot.ask import classify
    t_clean = (text or "").strip()
    if not (t_clean.startswith("/report") or classify(t_clean).kind == "report"):
        return False, "", ""
    p_date, d_date = normalize_date_input(t_clean) or ("", "")
    return True, p_date, d_date

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

    parsed = normalize_date_input(raw_input)
    if parsed is None:
        from src.bot.replies import date_error_reply
        await update.message.reply_text(date_error_reply(raw_input, "/report"), parse_mode="Markdown")
        return
    portal_date, display_date = parsed
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
    """Handle /students: the newest applications on students.php (its first page), each with the
    columns as the portal shows them ("—" where it shows nothing), or why the list could not be read."""
    if not is_authorized(update):
        return

    from src.bot.brief import esc
    from src.bot.replies import portal_error_reply, reply_long
    try:
        apps = await admin_client.get_applications()
    except Exception as e:
        logger.error(f"Error in students_command: {e}")
        await update.message.reply_text(portal_error_reply("The student list", e), parse_mode="Markdown")
        return
    if not apps:
        await update.message.reply_text("ℹ️ The student list on the portal is empty.")
        return
    lines = ["🎓 *Recent Student Applications:*", ""]
    for a in apps[:8]:
        stage = a.get("status") or ""
        status_emoji = "✅" if ("Approved" in stage or "Admitted" in stage) else ("⏳" if "Review" in stage else "📝")
        lines.append(f"• {status_emoji} *{esc(a.get('student_name') or '—')}* ({esc(a.get('target_intake') or '—')})")
        lines.append(f"  └ *Program:* {esc(a.get('program') or '—')}")
        lines.append(f"  └ *Univ:* {esc(a.get('target_university') or '—')} | *Status:* "
                     f"`{(stage or '—').replace('`', '')}`")
        lines.append("")
    await reply_long(update.message, "\n".join(lines).strip())

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
    """Handle /admitted [query]: the students at the dashboard's Admitted stage, picked in code
    from every page of students.php (admin_client.get_admitted_students), optionally narrowed by
    name, HNG id, university, program or intake; or why the list could not be read."""
    if not is_authorized(update):
        return

    query = None
    if context and context.args:
        query = " ".join(context.args).strip()
    elif context and context.user_data.get("override_query"):
        query = context.user_data.pop("override_query", None)

    from src.bot.replies import portal_error_reply, reply_long
    status_msg = await update.message.reply_text("🔍 _Retrieving admitted students live from portal..._", parse_mode="Markdown")
    try:
        result = await admin_client.get_admitted_students(query=query)
        text = format_admitted_report(result)
    except Exception as e:
        logger.error(f"Error in admitted_command: {e}")
        text = portal_error_reply("Admitted students", e)
    await reply_long(update.message, text, edit=status_msg)


ADMITTED_ROSTER_MAX = 12


def format_admitted_report(result: dict) -> str:
    """/admitted's reply from admin_client.get_admitted_students: how many of the students read
    are at the admitted stage, those matching the query, and a roster, every figure counted from
    the rows (the dashboard's Admitted tile is shown only as a cross-check, never instead)."""
    from collections import Counter
    from src.bot.brief import esc

    def code(value) -> str:
        return f"`{str(value).replace('`', '')}`"

    students, query = result.get("students") or [], result.get("query")
    admitted, checked = result.get("admitted", 0), result.get("checked", 0)
    stage, tile = esc(result.get("stage") or ""), result.get("tile")
    where = (f"{admitted} of the {checked} students on the portal "
             f"{'is' if admitted == 1 else 'are'} at the stage “{stage}” (every page of the student list read live)")
    check = ""
    if tile is not None and tile != admitted:
        check = (f"⚠️ The dashboard's Admitted tile says {tile}, but the student list shows {admitted} "
                 "at that stage.")
    elif tile is not None:
        check = f"The dashboard's Admitted tile says {tile} too."
    if not students:
        if query:
            head = (f"ℹ️ *No admitted students match “{esc(query)}”.*" if admitted else
                    f"ℹ️ *No admitted students match “{esc(query)}”:* no student on the portal is admitted right now.")
        else:
            head = "ℹ️ *No admitted students on the portal right now.*"
        return "\n".join(x for x in (head, where[0].upper() + where[1:] + ".", check) if x)

    lines = ["🎓 *Hangeul Portal — Admitted Students*",
             f"• *Admitted:* `{admitted}` — {where}"]
    if query:
        lines.append(f"• *Matching* “{esc(query)}”: `{len(students)}`")
    if check:
        lines.append(check)
    lines.append("")
    groups = (("Universities", "target_university", 4), ("Programs", "program", 3), ("Intakes", "target_intake", 6))
    lines.append("📊 *Breakdown:*")
    for label, key, most in groups:
        counts = Counter(s.get(key) or "—" for s in students)
        lines.append(f"• *{label}:* " + ", ".join(f"{esc(k)} ({n})" for k, n in counts.most_common(most)))
    lines += ["", "📋 *Student Roster:*"]
    for i, s in enumerate(students[:ADMITTED_ROSTER_MAX], 1):
        sid = s.get("student_id") or s.get("id") or ""
        lines.append(f"*{i}. {esc(s.get('student_name') or '—')}*" + (f" ({code(sid)})" if sid else " (no student ID yet)"))
        lines.append(f"   🏛 *Univ:* {esc(s.get('target_university') or '—')} | *Prog:* {esc(s.get('program') or '—')}")
        lines.append(f"   💳 *Pay:* {code(s.get('payment_status') or '—')} | *Intake:* {esc(s.get('target_intake') or '—')}")
    if len(students) > ADMITTED_ROSTER_MAX:
        lines += ["", f"_...and {len(students) - ADMITTED_ROSTER_MAX} more._",
                  "💡 Tip: search by name, ID, university or program: `/admitted <query>`"]
    return "\n".join(lines)

INQUIRIES_LOG_MAX = 10
_DONE_STATUSES = ("Consulted", "File Opened")


def _bold_safe(text) -> str:
    """Portal text for inside a *bold* entity. Legacy Markdown reads an entity literally up to its
    closing '*' (a backslash there would show), so only a '*' of its own needs changing."""
    return str(text).replace("*", "∗")


def _inquiry_who(r: Dict[str, Any]) -> str:
    """Who a logged request is with, from its own row: "(by X)" only for a done request (Consulted
    / File Opened) whose row names who handled it; "(last updated by X)" for another status the row
    names someone for; "(assigned to X)" when the row names nobody but its consultant."""
    from src.bot.brief import esc
    by, consultant = r.get("handled_by") or "", r.get("consultant") or ""
    if by and r.get("status") in _DONE_STATUSES:
        return f" (by {esc(by)})"
    if by:
        return f" (last updated by {esc(by)})"
    if consultant and consultant != "Unassigned":
        return f" (assigned to {esc(consultant)})"
    return ""


def format_inquiries_report(on_day: Dict[str, Any], totals: Optional[Dict[str, int]], display_date: str,
                            totals_error: Optional[Exception] = None) -> str:
    """The /inquiries report (Telegram Markdown). `on_day` is client.read_consultation_day's read:
    the day's figures are the portal's own status-tab counts under its date filter, and the
    breakdown and log come from the day's listed rows. `totals` is read_consultation_totals' all-time
    tab counts, or None with `totals_error` when they could not be read (then "not available")."""
    from collections import Counter
    from src.bot.brief import esc
    from src.scraper.client import portal_error_reason
    counts, rows, complete = on_day["counts"], on_day.get("rows") or [], on_day.get("complete", True)
    c = Counter({k: v for k, v in counts.items() if k != "All"})
    received, done = counts["All"], c["Consulted"] + c["File Opened"]
    rest = received - done - c["New"]                   # No Answer, Wrong Number and any other status
    lines = [
        f"📞 *Consultancy Inquiries Report — {display_date}*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🌐 *Overall Portal Metrics (all time, the portal's own status counts):*",
    ]
    if totals:
        t = Counter(totals)
        lines += [f"• *Total Inquiries on Portal:* `{t['All']}`",
                  f"• *Total All-Time Done:* `{t['Consulted'] + t['File Opened']}` "
                  f"({t['Consulted']} Consulted, {t['File Opened']} Files Opened)",
                  f"• *Still New:* `{t['New']}` | *No Answer:* `{t['No Answer']}` | *Wrong Number:* `{t['Wrong Number']}`"]
        extra = [(k, v) for k, v in totals.items() if k != "All" and k not in _DONE_STATUSES + ("New", "No Answer", "Wrong Number")]
        if extra:
            lines.append("• *Other statuses:* " + ", ".join(f"{esc(k)} {v}" for k, v in extra))
    else:
        why = portal_error_reason(totals_error) if totals_error else "not read"
        lines.append(f"• All-time figures: not available (couldn't read the portal's status counts: {esc(why)})")
    lines[-1] += "\n"
    split = [f"{c[s]} {s}" for s in ("No Answer", "Wrong Number") if c[s]]
    split += [f"{n} {esc(s)}" for s, n in c.items() if n and s not in _DONE_STATUSES + ("New", "No Answer", "Wrong Number")]
    lines += [
        f"📅 *Performance on {display_date}:*",
        f"• *Inquiries Received:* `{received}`",
        f"• *Inquiries Done:* `{done}`",
        f"   ├ ✅ *Consulted:* `{c['Consulted']}`",
        f"   └ 📁 *File Opened:* `{c['File Opened']}`",
        f"• *Pending / New:* `{c['New']}`",
        f"• *No Answer / Other:* `{rest}`" + (f" ({', '.join(split)})" if split and rest else ""),
    ]

    handled = Counter(r.get("handled_by") or "" for r in rows if r.get("status") in _DONE_STATUSES)
    if handled:
        parts = [f"{esc(name)}: {n}" for name, n in handled.most_common() if name]
        if handled[""]:
            parts.append(f"no name on the portal: {handled['']}")
        lines.append("• *Consultations Handled by:* " + ", ".join(parts)
                     + ("" if complete else f" (among the {len(rows)} the portal lists)"))

    if rows:
        lines.append("\n📋 *Inquiries Log:*")
        for idx, r in enumerate(rows[:INQUIRIES_LOG_MAX], 1):
            status = r.get("status") or "?"
            st_emoji = {"Consulted": "✅", "File Opened": "📁", "New": "⏳"}.get(status, "📵")
            prog = r.get("program") or ""
            lines.append(f"*{idx}. {_bold_safe(r.get('name') or '—')}*" + (f" {esc('[' + prog + ']')}" if prog else ""))
            lines.append(f"   └ {st_emoji} Status: `{status.replace('`', '')}`{_inquiry_who(r)} | "
                         f"City: {esc(r.get('city') or 'N/A')}")
        shown = min(len(rows), INQUIRIES_LOG_MAX)
        if received > shown:
            lines.append(f"\n_...and {received - shown} more inquiries received on {display_date}._")
    elif received:
        lines.append(f"\nℹ️ The portal counts {received} requests on {display_date} but lists none of them.")
    else:
        lines.append(f"\nℹ️ *No new consultation requests were recorded on {display_date}.*")
    return "\n".join(lines)


async def build_inquiries_report(target_date_input: str = "today", strict: bool = False) -> str:
    """The inquiries report for the day `target_date_input` names, read live: that day's requests
    from the portal's own date filter (so any day, not only those among the newest 500 requests its
    unfiltered list shows), and the all-time figures from its status tabs. A date that cannot be
    read (with `strict`, anything but a date) gets date_error_reply, a day to come says so, and a
    failed read gets portal_error_reply: never a 0 or "none" standing in for "could not read"."""
    from datetime import datetime
    from src.bot.replies import date_error_reply, portal_error_reply
    from src.dates import local_today
    parsed = normalize_date_input(target_date_input, strict=strict)
    if parsed is None:
        return date_error_reply(target_date_input, "/inquiries_date")
    portal_date, display_date = parsed
    day = datetime.strptime(portal_date, "%d %b %Y").date()
    if day > local_today():
        return f"ℹ️ *Consultancy inquiries on {display_date}:* not available (a date in the future)."
    try:
        on_day = await admin_client.read_consultation_day(day)
    except Exception as e:
        logger.error(f"Inquiries for {portal_date} not read: {type(e).__name__}: {e}")
        return portal_error_reply(f"Consultancy inquiries for {display_date}", e)
    totals, totals_error = None, None
    try:
        totals = await admin_client.read_consultation_totals()
    except Exception as e:
        logger.error(f"All-time consultation counts not read: {type(e).__name__}: {e}")
        totals_error = e
    return format_inquiries_report(on_day, totals, display_date, totals_error)


async def _send_inquiries_report(update: Update, raw_input: str, waiting: str, strict: bool) -> None:
    """Build the report for `raw_input` and reply with it, split under Telegram's limit: the
    "⏳ `waiting`" message becomes its first piece (src.bot.replies.reply_long)."""
    from src.bot.brief import esc
    from src.bot.replies import reply_long
    from src.scraper.client import portal_error_reason
    status_msg = await update.message.reply_text(f"⏳ _{waiting}_", parse_mode="Markdown")
    try:
        report = await build_inquiries_report(raw_input, strict=strict)
    except Exception as e:
        logger.error(f"Error building the inquiries report for {raw_input!r}: {e}")
        report = f"❌ Error building the inquiries report: {esc(portal_error_reason(e))}"
    await reply_long(update.message, report, edit=status_msg)


async def inquiries_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu 1: Total consultancy inquiries and how many were done today."""
    if not is_authorized(update):
        return
    await _send_inquiries_report(update, "today", "Consulting live portal for today's consultancy inquiries...",
                                 strict=True)

async def inquiries_date_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu 2: Total consultancy inquiries and how many were done (ask me specific date). The date
    given (the command's words, the typed answer to the question, or a free-text or voice route's
    words, which route here only when they name a date) must be one: '31 Sep' or 'foo' gets
    date_error_reply, never today's report."""
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

    if normalize_date_input(raw_input, strict=True) is None:
        from src.bot.replies import date_error_reply
        logger.info(f"/inquiries_date: unreadable date {raw_input!r}")
        await update.message.reply_text(date_error_reply(raw_input, "/inquiries_date"), parse_mode="Markdown")
        return
    # Inside the _italic_ waiting line an "_" of the user's own would end it early.
    shown = re.sub(r"\s+", " ", raw_input.replace("_", " ")).strip()[:60]
    await _send_inquiries_report(update, raw_input, f"Consulting live portal for inquiries ({shown})...",
                                 strict=True)

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
        # Legacy Markdown does not nest entities: code spans inside _italics_ showed their backticks.
        await update.message.reply_text(
            "📅 *Total Verified Students*\n\n"
            "Please enter the *specific date* to view verified students:\n"
            "(e.g. `12 Sep 2026`, `yesterday` or `2026-09-12`)",
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
    context.user_data["crosscheck_date_only"] = True
    await crosscheck_command(update, context)

async def crosscheck_date_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu 6: Total crosscheck verified students from live data (ask me specific date each time).
    What it is given must be a date: anything else is "I couldn't read that date", never today
    and never a name search."""
    if not is_authorized(update):
        return

    raw_input = ""
    if hasattr(context, "user_data") and context.user_data.get("override_text"):
        raw_input = context.user_data.pop("override_text")
    elif context and context.args:
        raw_input = " ".join(context.args).strip()

    if not raw_input:
        context.user_data["awaiting_date_for"] = "crosscheck"
        # Legacy Markdown does not nest entities: code spans inside _italics_ showed their backticks.
        await update.message.reply_text(
            "📅 *Live Crosscheck Verified Students*\n\n"
            "Please enter the *specific date* to cross-check verified students:\n"
            "(e.g. `12 Sep 2026`, `yesterday` or `2026-09-12`)",
            parse_mode="Markdown"
        )
        return

    context.user_data["override_text"] = raw_input
    context.user_data["crosscheck_date_only"] = True
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
    """/verified's report (Telegram Markdown) from admin_client.get_verified_students: how many
    students were verified, the total of the amounts the rows show, and each student's name,
    program, payment, verifier and time. Only what the portal rows show: a missing field is "—",
    a total over rows without an amount says so, and nothing is filled in. Only called after
    every page of the student list was read (a failed read is portal_error_reply, never this)."""
    from src.bot.brief import esc
    if not verified_list:
        return f"ℹ️ *No student payments were verified on {display_date}.*"

    total_count = len(verified_list)
    amounts = []
    for v in verified_list:
        amt_match = re.search(r'\d[\d,]*(?:\.\d+)?', v.get("amount") or "")
        if amt_match:
            amounts.append(float(amt_match.group(0).replace(",", "")))
    if not amounts:
        revenue = "not available (no amount on the portal rows)"
    else:
        revenue = f"`৳ {sum(amounts):,.2f} BDT`"
        if len(amounts) < total_count:
            revenue += (f" (the {len(amounts)} with an amount on the portal; "
                        f"{total_count - len(amounts)} without)")

    lines = [
        f"✅ *Student Payment Verifications — {display_date}*",
        f"• *Total Students Verified:* `{total_count}`",
        f"• *Total Verified Revenue:* {revenue}\n",
        "📋 *Verified Student Records:*"
    ]

    for idx, s in enumerate(verified_list, 1):
        # Only what the portal row shows: a missing field is "—", never a made-up value.
        name = esc(s.get("name") or "—")
        prog = esc(s.get("program") or "—")
        payment = (" ".join(x for x in (s.get("amount"), s.get("method")) if x) or "—").replace("`", "")
        counselor = esc(s.get("verified_by") or "—")
        time_str = esc(s.get("verified_time") or "")

        lines.append(f"*{idx}. {name}*")
        lines.append(f"   ├ 🎓 *Program:* {prog}")
        lines.append(f"   ├ 💰 *Payment:* `{payment}`")
        lines.append(f"   └ 👤 *Verified by:* {counselor}" + (f" ({time_str})" if time_str else ""))
        lines.append("")

    return "\n".join(lines).strip()

async def verified_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /verified [date] (and /verified_students, /verified_today, /verified_date and their
    free-text routes): the students whose payment was verified on that day, read live from every
    page of students.php. A date that cannot be read, a day the portal's yearless stamps cannot
    answer for, and a failed portal read each get their own clear reply, never "none verified"."""
    from datetime import datetime
    from src.bot.replies import date_error_reply, portal_error_reply, reply_long
    from src.dates import local_today, yearless_day_problem
    chat_id = update.effective_chat.id
    if not is_authorized(update):
        logger.warning(f"Unauthorized /verified attempt from chat_id: {chat_id}")
        await update.message.reply_text(f"⛔ Unauthorized access. Your Chat ID is: `{chat_id}`", parse_mode="Markdown")
        return

    # Where the date comes from decides how strictly it is read: words routed from a free-text
    # question may have no date in them (then it is today); a date given to a command must be one.
    raw_input, strict = "", True
    if hasattr(context, "user_data") and context.user_data.get("override_text"):
        raw_input, strict = context.user_data.pop("override_text"), False
    elif hasattr(context, "user_data") and context.user_data.get("override_date"):
        raw_input = context.user_data.pop("override_date")
    elif context and context.args:
        raw_input = " ".join(context.args)
    elif update.message and update.message.text:
        raw_input = update.message.text

    parsed = normalize_date_input(raw_input, strict=strict)
    if parsed is None:
        logger.info(f"/verified: unreadable date {raw_input!r} from chat_id {chat_id}")
        await update.message.reply_text(date_error_reply(raw_input, "/verified_date"), parse_mode="Markdown")
        return
    portal_date, display_date = parsed
    day = datetime.strptime(portal_date, "%d %b %Y").date()
    logger.info(f"Checking verified students for portal_date={portal_date}, display_date={display_date} (raw='{raw_input}') from chat_id {chat_id}")

    problem = yearless_day_problem(day, local_today())
    if problem:
        from src.bot.brief import esc
        await update.message.reply_text(
            f"ℹ️ *Verified students on {display_date}:* not available ({esc(problem)}).", parse_mode="Markdown")
        return

    status_msg = await update.message.reply_text(f"⏳ _Gathering verified student records for {display_date}..._", parse_mode="Markdown")
    try:
        verified_list = await admin_client.get_verified_students(target_date=day)
        report_text = format_verified_students_report(verified_list, display_date)
    except Exception as e:
        logger.error(f"Error fetching verified students: {e}")
        report_text = portal_error_reply(f"Verified students for {display_date}", e)
    await reply_long(update.message, report_text, edit=status_msg)
    logger.info(f"Dispatched verified students for {display_date} to chat_id {chat_id}")

PASSPORTS_OCR_MAX = 5      # today's verified students /passports checks by OCR (seconds each)


def format_passports_report(students: list, today_cards: Optional[list], display_date: str, read_at: str,
                            today_problem: str = "") -> str:
    """/passports' report (Telegram Markdown): how many students on the portal have a passport scan
    uploaded and how many do not (by their Passport Status), and today's payment-verified students
    with the verdict of the live OCR check of their scans (_crosscheck_card dicts; those without a
    "verdict" were not checked; None with today_problem when the verification stamps could not be
    read). Only called after every page of students.php was read."""
    from collections import Counter
    from src.bot.brief import esc
    def has_scan(s):
        return any(f.startswith("passport_") for f in s.get("files") or [])

    with_scan = [s for s in students if has_scan(s)]
    without = [s for s in students if not has_scan(s)]
    lines = [
        f"🛂 *Passport Scans — live from the portal ({read_at})*",
        f"• *Students on the portal:* `{len(students)}`",
        f"• *With a passport scan uploaded:* `{len(with_scan)}`",
        f"• *Without a passport scan:* `{len(without)}`",
    ]
    if without:
        by_status = Counter((s.get("details") or {}).get("Passport Status") or "not given" for s in without)
        lines.append("   └ Passport Status: " + ", ".join(f"{esc(k)} `{v}`" for k, v in by_status.most_common()))
    if today_cards is None:
        lines += ["", f"📅 *Payment-verified today ({display_date}):* not available ({esc(today_problem)})"]
        today_cards = []
    else:
        lines += ["", f"📅 *Payment-verified today ({display_date}):* `{len(today_cards)}`"]
    if not today_cards and not today_problem:
        lines.append("ℹ️ No payment was verified today, so no scan was checked. Another day: "
                     "`/crosscheck_date 12 Sep 2026`; one student: `/crosscheck 432`.")
    for idx, c in enumerate(today_cards, 1):
        scan = "✅ scan uploaded" if c["passport_file"] else "⏳ no scan uploaded"
        lines.append(f"*{idx}. {esc(c['name'])}* (ID: `{c['id']}`) — {scan}")
        if c.get("verdict"):
            lines.append(f"   └ 🔍 {esc(c['verdict'])}")
        else:
            lines.append("   └ 🔍 not checked here (see `/crosscheck_today`)")
    ocr = "; each verdict comes from an OCR check of the scan made just now" if any(
        c.get("verdict") for c in today_cards) else ""
    lines += ["", f"_Read live from all {len(students)} students on students.php{ocr}._"]
    return "\n".join(lines)


async def passports_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/passports and /passport_audit: the passport scans on the portal right now, read live from
    every page of students.php, and a live OCR check of the scans of the students whose payment was
    verified today (the first PASSPORTS_OCR_MAX; /crosscheck_today checks them all). Nothing stored
    is shown as current, and a portal that cannot be read is said so, never counted as 0."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.bot.replies import portal_error_reply
    from src.dates import local_today
    chat_id = update.effective_chat.id
    if not is_authorized(update):
        logger.warning(f"Unauthorized /passports attempt from chat_id: {chat_id}")
        await update.message.reply_text(f"⛔ Unauthorized access. Your Chat ID is: `{chat_id}`", parse_mode="Markdown")
        return

    today = local_today()
    display = today.strftime("%d %B %Y")
    status_msg = await update.message.reply_text(
        "⏳ _Reading every student's passport scan live from the portal..._", parse_mode="Markdown")
    try:
        from src.scraper.client import PortalUnavailable
        students = await admin_client.read_students()
        read_at = datetime.now(ZoneInfo(settings.REPORT_TIMEZONE)).strftime("%d %b %Y, %H:%M")
        try:
            _stamp_guard(students)
            cards, problem = [_crosscheck_card(s) for s, _ in _verified_between(students, today, today)], ""
        except PortalUnavailable as e:          # the counts stand; only "verified today" is unknown
            cards, problem = None, f"couldn't read the portal's verification stamps: {e.reason}"
        if cards:
            await _audit_cards(cards[:PASSPORTS_OCR_MAX], status_msg, f"verified today ({display})")
        text = format_passports_report(students, cards, display, read_at, problem)
    except Exception as e:
        logger.error(f"Error in passports_command: {e}")
        text = portal_error_reply("Passport scans", e)
    await _send_blocks(update.message, text, status_msg)
    logger.info(f"Dispatched live passport status to chat_id {chat_id}")

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
    """Handle /calendar [query] (and /events, /deadlines, and calendar questions in plain words).

    Bare, it is today's view (format_calendar_report). With words, they are read by
    src.bot.ask.calendar_query: real dates ("this week" is today to Sunday, "next 7 days", "in
    October", "on 2 Oct"), "deadline" / "due" for what closes within them, "DHL" for the DHL
    items, and any other words (a university) searched for; the answer comes from calendar.php
    read live (ask.answer_calendar), each item with its dates. A date that cannot be read gets a
    clear error, never today's view instead; a calendar that cannot be read says so."""
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

    from src.bot import ask
    from src.bot.replies import date_error_reply, reply_long
    question = ask.calendar_query(raw_input)
    if question.problem:
        await update.message.reply_text(date_error_reply(raw_input, "/calendar", question.problem), parse_mode="Markdown")
        return
    if not question.default:
        status_msg = await update.message.reply_text("⏳ _Consulting live calendar & admission deadlines..._",
                                                     parse_mode="Markdown")
        await reply_long(update.message, await ask.answer_calendar(question), edit=status_msg)
        return

    status_msg = await update.message.reply_text("⏳ _Consulting live calendar & admission deadlines..._", parse_mode="Markdown")
    try:
        cal_data = await admin_client.get_calendar_events()
        report = format_calendar_report(cal_data)          # today's view: the words asked for nothing more
    except Exception as e:
        logger.error(f"Error checking calendar: {e}")
        from src.bot.replies import portal_error_reply
        report = portal_error_reply("The calendar", e)
    await reply_long(update.message, report, edit=status_msg)

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
    """Split a long report into Telegram-safe chunks (<= 4096 chars) on line breaks: the one
    splitter, src.bot.replies.split_text (a short text is one chunk as it is)."""
    from src.bot.replies import split_text, telegram_len
    return split_text(text, limit) if telegram_len(text) > limit else [text]


# --------------------------------------------------------------------------- /crosscheck, /audit
# /crosscheck_today, /crosscheck_date, /crosscheck_range (and _between, _period), /passports.
# Every command reads the whole student list live (admin_client.read_students: every page, session
# renewed when it expired, a failed read raised), picks students by the row's own "Payment verified
# by NAME · 27 Sep, 17:19" stamp (never any other text in the row), and checks each passport scan
# by OCR right then (admin_client.audit_student_passport).

CROSSCHECK_NAME_MAX = 10       # students one name search checks by OCR (several seconds each)

# The command, punctuation and the words around what a /crosscheck asks for ("cross check father
# name of student 527", "crosscheck student Tahira please"): what is left is an ID or a name.
_CROSSCHECK_WORDS_RE = re.compile(
    r"/\w+(?:@\w+)?|[?!.,:;'\"()\[\]]|\b(?:cross\s*-?\s*check(?:ing|ed|s)?|crosscheck|audit|check|verify|verified"
    r"|verification|students?|id|uid|no|number|for|of|the|a|an|info|information|details?|please|pls|show"
    r"|me|give|tell|about|on|only|specific|passports?|documents?|docs?|fathers?|mothers?|parents?"
    r"|address(?:es)?|names?|dob|and|with|against|records?|payments?|his|her|their|live|data|who|is)\b", re.I)


def _crosscheck_query(raw: str, date_only: bool = False) -> Dict[str, Any]:
    """What a /crosscheck text asks for:
      {"kind": "date", "day"}   a day (read by src.dates.parse_user_date; no date at all is today)
      {"kind": "uid", "uid"}    a portal student ID, the N of student_edit.php?id=N ("527", "#527",
                                "student 527", "id: 527")
      {"kind": "hng", "hng"}    an HNG student ID ("HNG-2026-931")
      {"kind": "name", "name"}  a part of a name, at least 3 letters ("Tahira", "Kumar")
      {"kind": "error", "reply"}  a date that cannot be read ("31 Sep", "Sep"), or too little to go on.
    Month names count only as whole words, so "Kumar" or "Junaira" is a name, never a date. With
    date_only (/crosscheck_date, /crosscheck_today) anything but a date is "I couldn't read that date"."""
    from src.bot.replies import date_error_reply
    from src.dates import has_date_hint, local_today, parse_user_date
    text = re.sub(r"\s+", " ", raw or "").strip()
    body = re.sub(r"^/\w+(?:@\w+)?\s*", "", text)
    command = "/crosscheck_date" if date_only else "/crosscheck"
    day = parse_user_date(body, local_today(), prefer_past=True)
    if day is not None:
        return {"kind": "date", "day": day}
    rest = re.sub(r"\s+", " ", _CROSSCHECK_WORDS_RE.sub(" ", body)).strip()
    if not rest:
        return {"kind": "date", "day": local_today()}
    if date_only:
        return {"kind": "error", "reply": date_error_reply(body, command)}
    hng = re.search(r"\bHNG-\d{4}-\d+\b", body, re.I)
    if hng:
        return {"kind": "hng", "hng": hng.group(0).upper()}
    uid = re.fullmatch(r"#?\s*(\d{1,6})", rest)
    if uid:
        return {"kind": "uid", "uid": str(int(uid.group(1)))}
    if has_date_hint(rest):
        return {"kind": "error", "reply": date_error_reply(body, command)}
    if len(re.sub(r"[^A-Za-z]", "", rest)) < 3:
        return {"kind": "error", "reply": (
            "⚠️ I need a date, a student ID or at least 3 letters of a name to cross-check, e.g. "
            "`/crosscheck 27 Sep 2026`, `/crosscheck 432` or `/crosscheck Fahmid`.")}
    return {"kind": "name", "name": rest}


def _stamp_guard(students: list) -> None:
    """Raise PortalUnavailable when the list's verification stamps cannot be read (the checks of
    client.read_verified_students): student rows but no "Payment verified by" line on any of them,
    or a line whose date is not "DD Mon, HH:MM". Then no day's list can be told, not even "none"."""
    from src.dates import parse_stamp
    from src.scraper.client import PortalUnavailable
    lines = [s for s in students if s.get("verified_line")]
    if students and not lines:
        raise PortalUnavailable(f"students.php: {len(students)} student rows but no 'Payment verified by' "
                                "line on any of them (layout not recognised)")
    unreadable = [s for s in lines if parse_stamp(s.get("verified_stamp", "")) is None]
    if unreadable:
        raise PortalUnavailable(f"students.php: {len(unreadable)} verification line(s) with a date the bot "
                                "cannot read (layout not recognised)")


def _verified_between(students: list, first, last) -> list:
    """(student, day) for every student whose own payment-verification stamp is on a day from
    `first` to `last` (parsers.verification: whole day and month tokens, never the transfer-intake
    options' "2027 SEPTEMBER" or the "Applied On" date; not before the student applied). Callers
    first make sure src.dates.yearless_day_problem has nothing against `first`, and `last` is not
    after today (the stamps have no year)."""
    from datetime import timedelta
    from src.scraper.parsers import verification
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    found = []
    for s in students:
        day = next((d for d in days if verification(s, d) is not None), None)
        if day is not None:
            found.append((s, day))
    return found


def _stamp_minutes(student: dict) -> int:
    from src.dates import parse_stamp
    stamp = parse_stamp(student.get("verified_stamp", ""))
    if not stamp or not stamp.time:
        return 0
    hours, minutes = stamp.time.split(":")
    return int(hours) * 60 + int(minutes)


def _crosscheck_card(student: dict) -> Dict[str, Any]:
    """What a cross-check card shows of one students.php record (parse_students_page): only the
    portal's own values, "" where the portal shows none."""
    from src.dates import parse_stamp
    details = student.get("details") or {}
    files = student.get("files") or []
    passport_file = next((f for f in files if f.startswith("passport_")), None)
    stamp = parse_stamp(student.get("verified_stamp", ""))
    name = student.get("student_name") or details.get("Full Name") or ""
    amount = student.get("paid") or student.get("verified_income") or ""
    return {
        "id": student.get("uid") or "", "hng": student.get("student_id") or "",
        "name": name or "—", "name_raw": name,
        "program": student.get("program") or details.get("Program") or "",
        "dob": details.get("DOB") or "", "pass_no": details.get("Passport No") or "",
        "pass_exp": details.get("Passport Expiry") or "", "passport_status": details.get("Passport Status") or "",
        "passport_file": passport_file, "has_pass_doc": bool(passport_file),
        "has_rcpt_doc": any(f.startswith("receipt_") for f in files),
        "payment": " ".join(x for x in (amount, student.get("method")) if x),
        "verifier": student.get("verified_by") or "", "ver_time": stamp.text if stamp else "",
        "fields": {}, "verdict": "", "status": "",
    }


async def _audit_cards(cards: list, status_msg=None, what: str = "") -> None:
    """Check each card's passport scan by OCR, one after another (admin_client.audit_student_passport),
    filling its "fields", "status" and "verdict". A card with no scan on the portal is "Pending
    Passport Scan" without any check. A check that fails says so on its own card; the rest go on."""
    from src.bot.brief import esc
    from src.scraper.client import portal_error_reason
    todo = [c for c in cards if c["passport_file"]]
    if todo and status_msg is not None:
        try:
            await status_msg.edit_text(f"⏳ _Checking {len(todo)} passport scan(s) {esc(what)} by OCR "
                                       "(about 10 seconds each)..._", parse_mode="Markdown")
        except Exception:
            pass
    for c in cards:
        if not c["passport_file"]:
            c.update(fields={}, status="MISSING_DOCUMENT",
                     verdict="⏳ Pending Passport Scan (no scan uploaded on the portal)")
            continue
        form = {"name": c["name_raw"], "dob": c["dob"], "passport_no": c["pass_no"], "passport_expiry": c["pass_exp"]}
        try:
            res = await admin_client.audit_student_passport(c["id"], form, c["passport_file"])
        except Exception as e:
            logger.error(f"Cross-check of student {c['id']} failed: {portal_error_reason(e)}")
            res = {"fields": {}, "status": "ERROR", "verdict": f"❌ Couldn't check this scan: {portal_error_reason(e)}"}
        c.update(fields=res.get("fields") or {}, status=res.get("status", ""), verdict=res.get("verdict", ""))


def _format_crosscheck_results(results: list, header_title: str, checked: Optional[int] = None,
                               note: str = "") -> str:
    """The cross-check report (Telegram Markdown): a header, then one card per student, the blocks
    separated by a blank line (so _send_blocks never cuts a card in half)."""
    from src.bot.brief import esc
    head = [f"📋 *Verified Student Information Cross-Check — {esc(header_title)}*",
            f"• *Total Records Audited:* `{len(results)}`"]
    if checked is not None:
        head.append(f"• _Read live from all {checked} students on students.php; each scan was checked by OCR just now._")
    if note:
        head.append(note)
    blocks = ["\n".join(head)]
    for idx, r in enumerate(results, 1):
        ident = f"`{r['id'] or '—'}`" + (f" · `{r['hng']}`" if r.get("hng") else "")
        rcpt = "receipt ✅ uploaded" if r["has_rcpt_doc"] else "no receipt uploaded"
        if r["has_pass_doc"]:
            scan = "✅ Uploaded"
        else:
            scan = "⏳ None uploaded" + (f" (Passport Status: {esc(r['passport_status'])})" if r.get("passport_status") else "")
        verified = (f"{esc(r['verifier'])} ({r['ver_time']})" if r["verifier"] and r["ver_time"]
                    else esc(r["verifier"]) if r["verifier"] else "— (no payment verification on the portal)")
        lines = [
            f"*{idx}. {esc(r['name'])}* (ID: {ident})",
            f"   ├ 🎓 *Program:* {esc(r['program'] or '—')}",
            f"   ├ 💰 *Payment:* `{(r['payment'] or '—').replace('`', '')}` ({rcpt})",
            f"   ├ 👤 *Verified by:* {verified}",
            f"   ├ 🛂 *Passport Scan:* {scan}",
            f"   ├ 📝 *Portal:* Pass `{r['pass_no'] or '—'}` | Exp `{r['pass_exp'] or '—'}` | DOB `{r['dob'] or '—'}`",
        ]
        f_fields = r.get("fields") or {}
        for key, icon, label in (("father_name", "👨", "Father"), ("mother_name", "👩", "Mother"),
                                 ("address", "🏠", "Address")):
            f = f_fields.get(key) or {}
            doc = (f.get("doc") or "").replace("`", "")
            if key == "address" and len(doc) > 40:
                doc = doc[:40] + "..."
            if doc:
                lines.append(f"   ├ {icon} *{label}:* `{doc}` ({esc(f.get('verdict') or 'Checked')})")
            elif f.get("verdict"):
                lines.append(f"   ├ {icon} *{label}:* {esc(f['verdict'])}")
        lines.append(f"   └ 🔍 *Audit Verdict:* {esc(r.get('verdict') or '—')}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


async def _send_blocks(message, text: str, status_msg=None) -> int:
    """Send a report whose blocks are separated by blank lines in as few messages as fit under
    Telegram's limit, never cutting a block (a student's card) in half; the first message replaces
    status_msg (the "⏳" note). A block too long for one message is split between its lines.
    Markdown Telegram refuses is sent again as plain text (src.bot.replies). -> messages sent."""
    from src.bot.replies import CHUNK_CHARS, reply_long, split_text, telegram_len
    pieces: List[str] = []
    current = ""
    for block in text.split("\n\n"):
        joined = f"{current}\n\n{block}" if current else block
        if telegram_len(joined) <= CHUNK_CHARS:
            current = joined
            continue
        if current:
            pieces.append(current)
        parts = split_text(block) if telegram_len(block) > CHUNK_CHARS else [block]
        pieces.extend(parts[:-1])
        current = parts[-1] if parts else ""
    if current.strip():
        pieces.append(current)
    for i, piece in enumerate(pieces):
        await reply_long(message, piece, edit=status_msg if i == 0 else None)
    return len(pieces)


async def build_crosscheck_report(query: Dict[str, Any], status_msg=None) -> str:
    """The cross-check report for a _crosscheck_query (a "date" query carries "first", "last" and
    "display"): every page of students.php read live, the students picked (by verification stamp,
    portal ID, HNG ID or name), each passport scan checked by OCR. Raises PortalUnavailable when the
    list cannot be read whole, so a failed read is never "no students found"."""
    from src.bot.brief import esc
    students = await admin_client.read_students()
    checked, note = len(students), ""
    kind = query["kind"]
    if kind == "date":
        _stamp_guard(students)
        found = _verified_between(students, query["first"], query["last"])
        if query["first"] != query["last"]:
            found.sort(key=lambda sd: (sd[1], _stamp_minutes(sd[0])))
        picked, title = [s for s, _ in found], query["display"]
        if not picked:
            if query["first"] != query["last"]:
                return (f"ℹ️ *No payment-verified students found between {esc(title)} to cross-check.*\n"
                        f"_(All {checked} students on students.php were read live.)_")
            return (f"ℹ️ *No payment-verified students found for {esc(title)} to cross-check.*\n"
                    f"_(All {checked} students on students.php were read live.)_\n\n"
                    "💡 *Examples:*\n"
                    "• Specific Date: `/crosscheck 10 Sep` or `/crosscheck yesterday`\n"
                    "• Specific Student ID: `/crosscheck 432` or `/crosscheck 431`\n"
                    "• Specific Student Name: `/crosscheck Fahmid` or `/crosscheck Bikash`")
    elif kind in ("uid", "hng"):
        key, value = ("uid", query["uid"]) if kind == "uid" else ("student_id", query["hng"])
        picked = [s for s in students if (s.get(key) or "").upper() == value]
        title = f"Student ID #{value}" if kind == "uid" else f"Student {value}"
        if not picked:
            return (f"ℹ️ *No student found matching ID `{value}`* "
                    f"(all {checked} students on students.php were read live).")
    else:
        wanted = re.sub(r"\s+", " ", query["name"]).strip().lower()
        picked = [s for s in students
                  if wanted in re.sub(r"\s+", " ", s.get("student_name") or (s.get("details") or {}).get("Full Name") or "").lower()]
        title = f"Student '{query['name']}'"
        if not picked:
            shown = query["name"].replace("`", "")
            return (f"ℹ️ *No student found matching Name `{shown}`* "
                    f"(all {checked} students on students.php were read live).")
        if len(picked) > CROSSCHECK_NAME_MAX:
            rest = picked[CROSSCHECK_NAME_MAX:]
            listed = ", ".join(f"{esc(s.get('student_name') or '—')} (`{s.get('uid') or '—'}`)" for s in rest[:40])
            more = f" and {len(rest) - 40} more" if len(rest) > 40 else ""
            note = (f"• ⚠️ {len(picked)} students match; the first {CROSSCHECK_NAME_MAX} are checked below. "
                    f"The others: {listed}{more}. Send `/crosscheck <ID>` for one of them.")
            picked = picked[:CROSSCHECK_NAME_MAX]
    cards = [_crosscheck_card(s) for s in picked]
    await _audit_cards(cards, status_msg, f"for {title}")
    return _format_crosscheck_results(cards, title, checked=checked, note=note)


async def _crosscheck_run(update: Update, query: Dict[str, Any], waiting: str, title: str) -> None:
    """Show `waiting`, build the report, and send it in its place (a failed portal read as
    "Couldn't read the portal: ..." for `title`)."""
    from src.bot.brief import esc
    from src.bot.replies import portal_error_reply
    status_msg = await update.message.reply_text(waiting, parse_mode="Markdown")
    try:
        text = await build_crosscheck_report(query, status_msg)
    except Exception as e:
        logger.error(f"Error in crosscheck ({title}): {e}")
        text = portal_error_reply(f"Cross-check for {esc(title)}", e)
    await _send_blocks(update.message, text, status_msg)


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
    first, last = normalize_date_input(parts[0], strict=True), normalize_date_input(parts[1], strict=True)
    if first is None or last is None:
        return None, None, None             # a date that cannot be read: never today instead
    p1, p2 = first[0], last[0]
    try:
        d1 = datetime.strptime(p1, "%d %b %Y").date()
        d2 = datetime.strptime(p2, "%d %b %Y").date()
    except ValueError:
        return None, None, None
    if d1 > d2:
        d1, d2 = d2, d1
    return d1, d2, f"{d1.strftime('%d %b %Y')} → {d2.strftime('%d %b %Y')}"


async def crosscheck_range_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu 7: Total crosscheck verified students live between a START date and an END date
    (also /crosscheck_between, /crosscheck_period). The students are those whose own verification
    stamp is on a day in the range, read from every page of students.php."""
    from src.bot.brief import esc
    from src.dates import local_today, user_date_problem, yearless_day_problem
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
        why = user_date_problem(raw_input, prefer_past=True)
        why = f" ({esc(why)})" if why and not why.startswith("it names more than one date") else ""
        await update.message.reply_text(
            f"⚠️ I couldn't read two dates there{why}. Please send a *start* and *end* date, e.g. "
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

    # The portal's verification stamps have no year: a start day that has come round again since
    # cannot be told apart from that later day, and days after today have not happened yet.
    today = local_today()
    problem = yearless_day_problem(start_date, today)
    if problem:
        await update.message.reply_text(
            f"ℹ️ *Cross-check for {esc(display)}:* not available ({esc(problem)}).", parse_mode="Markdown")
        return
    if end_date > today:
        end_date = today
        display = f"{start_date.strftime('%d %b %Y')} → {today.strftime('%d %b %Y')} (today)"

    await _crosscheck_run(
        update, {"kind": "date", "first": start_date, "last": end_date, "display": display},
        f"⏳ _Cross-checking every payment-verified student from {esc(display)} live against their "
        "passport documents… this can take a few minutes._", display)


async def crosscheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /crosscheck and /audit [date | student ID | HNG ID | name] (and /crosscheck_today,
    /crosscheck_date): the students verified that day, or the one(s) asked for, read live from every
    page of students.php, each passport scan checked by OCR against their portal entries (name,
    DOB, passport number and expiry by the MRZ; father, mother and address by the printed page).
    A date that cannot be read, a day the portal's yearless stamps cannot answer for, and a failed
    portal read each get their own clear reply, never "none found"."""
    from src.bot.brief import esc
    from src.dates import local_today, yearless_day_problem
    chat_id = update.effective_chat.id
    user_data = context.user_data if getattr(context, "user_data", None) is not None else {}
    date_only = bool(user_data.pop("crosscheck_date_only", False))
    if not is_authorized(update):
        await update.message.reply_text(f"⛔ Unauthorized access. Your Chat ID is: `{chat_id}`", parse_mode="Markdown")
        return

    raw_input = ""
    if user_data.get("override_text"):
        raw_input = user_data.pop("override_text")
    elif context and context.args:
        raw_input = " ".join(context.args)
    elif update.message and update.message.text:
        raw_input = update.message.text

    query = _crosscheck_query(raw_input, date_only=date_only)
    if query["kind"] == "error":
        logger.info(f"/crosscheck: could not read {raw_input!r} from chat_id {chat_id}")
        await update.message.reply_text(query["reply"], parse_mode="Markdown")
        return
    if query["kind"] == "date":
        day = query["day"]
        title = day.strftime("%d %B %Y")
        problem = yearless_day_problem(day, local_today())
        if problem:
            await update.message.reply_text(
                f"ℹ️ *Cross-check for {title}:* not available ({esc(problem)}).", parse_mode="Markdown")
            return
        query.update(first=day, last=day, display=title)
    elif query["kind"] == "name":
        title = f"Student '{query['name']}'"
    else:
        title = f"Student ID #{query.get('uid') or query.get('hng')}"

    await _crosscheck_run(
        update, query, "⏳ _Cross-checking student information, Father, Mother, DOB & Address against documents..._",
        title)

async def handle_natural_language_message(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                          query: Optional[str] = None):
    """A typed question, answered by the command or the live read it asks for, never by a guess.
    A typed message is read from update.message.text; a voice note (src/bot/voice.py), which has no
    text, passes its English query as `query` instead.

    The question is read by src.bot.ask.classify, on whole words ("across" is no "cross",
    "shipping" no "pin", "Janan" and "summary" no month) and with real dates: consultations,
    verified payments and cross-checks go to their commands for the day named (today when none;
    a date that cannot be read gets the command's own "couldn't read" reply; a span of days is
    asked again one day at a time, or cross-checked as a range); pending payments, window
    applications under review, the dashboard's figures, intakes and application dates are read
    live (src.bot.ask.reply); calendar questions go to /calendar with their words, which applies
    the dates ("this week" is today to Sunday); passport questions go to the live cross-check.
    Anything else gets the dashboard facts it names or the local LLM picks, word for word, or an
    honest "I can't answer that from the portal yet" with the commands that can."""
    if not is_authorized(update):
        return

    if query is None:
        query = update.message.text or ""
    query = query.strip()

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
        context.user_data.pop("override_text", None)

    from src.bot import ask
    from src.dates import local_today
    today = local_today()
    route = ask.classify(query, today)
    kind = route.kind
    ud = context.user_data

    def portal_day(day) -> str:
        return day.strftime("%d %b %Y")

    if kind == "hello":
        await update.message.reply_text(ask.HELLO, parse_mode="Markdown")
        return
    if kind == "pin":
        await pin_command(update, context)
        return

    # A span of days asked of an answer given one day at a time: which day (a passport check can
    # be a range: the range cross-check).
    if kind in ask.ONE_DAY_KINDS and route.window is not None:
        w = route.window
        if kind == "passports" and w.first <= today:
            ud["override_text"] = f"{portal_day(w.first)} to {portal_day(min(w.last or today, today))}"
            await crosscheck_range_command(update, context)
            return
        ud["awaiting_date_for"] = {"passports": "crosscheck"}.get(kind, kind)
        await update.message.reply_text(ask.one_day_reply(kind, w), parse_mode="Markdown")
        return

    # 2. Consultancy inquiries (menu items 1 and 2), for the day named; today when none; "a specific
    # date" with none named asks which.
    if kind == "inquiries":
        if route.problem:
            ud["override_text"] = query                 # the command says it cannot read the date
            await inquiries_date_command(update, context)
        elif route.day is None and re.search(r"\b(?:date|specific)\b", query, re.I):
            await inquiries_date_command(update, context)       # it asks which date
        elif route.day is None or route.day == today:
            await inquiries_today_command(update, context)
        else:
            ud["override_text"] = portal_day(route.day)
            await inquiries_date_command(update, context)
        return

    # 3. Cross-checks (menu items 5-7): a range, a day, a student, or ask which date.
    if kind == "crosscheck":
        from src.dates import has_date_hint, parse_user_date
        _r_start, _r_end, _ = _parse_date_range(query)
        if _r_start and _r_start != _r_end:
            ud["override_text"] = query
            await crosscheck_range_command(update, context)
            return
        if route.window is not None and route.window.first <= today:
            w = route.window                                # "cross-check last week": that range
            ud["override_text"] = f"{portal_day(w.first)} to {portal_day(min(w.last or today, today))}"
            await crosscheck_range_command(update, context)
            return
        named = parse_user_date(query, today, prefer_past=True)
        if named is not None and named == today:
            await crosscheck_today_command(update, context)
            return
        if named is not None:
            ud["override_text"] = query
            await crosscheck_date_command(update, context)
            return
        by_student = ask._CROSS_FIELD_RE.search(query) or re.search(r"\b\d{2,5}\b", query)
        if not by_student and has_date_hint(_DATE_FILLER_RE.sub(" ", query)):
            ud["override_text"] = query                 # a date it cannot read: the command says so
            await crosscheck_date_command(update, context)
            return
        if not by_student:
            await crosscheck_date_command(update, context)      # it asks which date
            return
        ud["override_text"] = query
        await crosscheck_command(update, context)
        return

    # Passport problems: the live passport cross-check for the day named (today when none).
    if kind == "passports":
        if route.problem:
            ud["override_text"] = query
            await crosscheck_date_command(update, context)
        elif route.day is None or route.day == today:
            await crosscheck_today_command(update, context)
        else:
            ud["override_text"] = portal_day(route.day)
            await crosscheck_date_command(update, context)
        return

    # 4. Verified students (menu items 3 and 4). The date is read by the one strict parser, and a
    # date-like word it cannot read goes to /verified_date, which says so, instead of today.
    if kind == "verified":
        if route.day is not None and route.day == today:
            await verified_today_command(update, context)
        elif route.day is not None or route.problem:
            ud["override_text"] = query
            await verified_date_command(update, context)
        elif re.search(r"\b(?:date|specific)\b", query, re.I):
            await verified_date_command(update, context)
        else:
            ud["override_text"] = query
            await verified_command(update, context)
        return

    # Admitted students: what is left of the words once the question words are gone ("who is
    # admitted to Hanyang?" -> "hanyang") is the search.
    if kind == "admitted":
        clean_q = re.sub(r"[?!.,;:]", " ", query.lower())
        clean_q = re.sub(r"\b(?:show|list|get|give|tell|me|us|who|whom|which|what|is|are|was|were|has|have|been|all"
                         r"|the|any|students?|admitted|admit|admission|admissions|how|many|number|of|to|in|at|for"
                         r"|from|please|pls|currently|now|so|far|there|our|do|does|we|got)\b", " ", clean_q)
        clean_q = re.sub(r"\s+", " ", clean_q).strip()
        if clean_q:
            ud["override_query"] = clean_q
        await admitted_command(update, context)
        return

    if kind == "missing":
        await missing_command(update, context)
        return
    if kind == "stage":
        await stage_command(update, context)
        return
    if kind == "calendar":
        ud["override_text"] = query                     # /calendar reads the dates in the words
        await calendar_command(update, context)
        return
    if kind == "report":
        ud["override_text"] = query
        await report_command(update, context)
        return
    if kind == "stats":
        await stats_command(update, context)
        return

    # Answers read live here: pending payments, window applications under review, the dashboard's
    # figures, intakes, application dates; and a question with no route (the dashboard facts it
    # names, or "I can't answer that from the portal yet").
    if kind == "applied" and route.problem:
        from src.bot.replies import date_error_reply
        await update.message.reply_text(date_error_reply(query, reason=route.problem), parse_mode="Markdown")
        return
    await ask.reply(update.message, route, query)

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
    """Send plain text, split under Telegram's message limit (src.bot.replies.reply_long)."""
    from src.bot.replies import reply_long
    await reply_long(message, text, parse_mode=None)


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
