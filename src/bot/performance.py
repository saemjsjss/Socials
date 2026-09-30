"""Performance, as the owner means it: the portal's own Consultant Performance page (Leads >
Performance, consult_performance.php), read live for /performance_today and /performance_month
(also /perf_today, /perf_month, /performance [today|month] and their free-text routes). Only this
page's data is shown; nothing is counted from other pages.

One read-only GET of consult_performance.php?period=today or ?period=month (the page's own period
links: its Custom range form is never used), parsed by its labels and header texts
(client.read_consult_performance -> parsers.parse_consult_performance), shown in the bot's style:

  header        the period and the portal's own range text ("Showing Today · 30 Sep – 30 Sep 2026")
  tiles         every tile, label and figure as the page prints them (Consultancies done, Files
                opened, Conversion (file open), Docs ready)
  top performer the "Top performer" card: the name, then its figures with their own labels
  leaderboard   every row in the portal's order with every column (the header's own text as the
                label, in the header's order), then the Score and Points columns' info tooltips
  footer        the source page and the portal's sort note

A reply too long for one message is cut only between records (message_pieces): a consultant's
name line and figure lines always travel together (R6).

Every figure is the portal's own, exactly as printed ("17.9", "18%", "149.5"). Where the page
disagrees with itself (the top card and the leaderboard's crowned row, a tile and its column's
total, a range that does not end today in Dhaka) a ⚠️ line says so; nothing is corrected. A page
that cannot be read, or whose layout is not recognised, is said plainly ("Couldn't read the
portal: ..."), never shown as zeros.

After the reply, the page read is also published to Supabase as kind consultant_performance
(src.cloud.records.consultant_performance, through src.cloud.command_hooks; nothing while
publishing is off), and the hourly full picture reads both periods too.
"""
import calendar
import logging
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from src.bot.brief import esc
from src.scraper.client import PERFORMANCE_PAGE, PERFORMANCE_PERIODS
from src.scraper.parsers import _label_key

logger = logging.getLogger("hangeul.performance")

KINDS = tuple(PERFORMANCE_PERIODS)          # ("today", "month")
RULE = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
# A tile's emoji, by its label's first word (the page's own icons: headset, folder, percent, clipboard).
_TILE_EMOJI = (("consultanc", "🎧"), ("file", "📂"), ("conversion", "🎯"), ("doc", "📋"))
# Tiles that are the total of a leaderboard column (label key prefix -> column key).
_TILE_COLUMN = (("consultanc", "consultancies"), ("file", "files_opened"), ("doc", "docs_ready"))
_TOP_FIGURES = ("score", "conversion", "files_opened", "consultancies")
_RANGE_START_RE = re.compile(r"^\s*(\d{1,2})\s+([A-Za-z]{3,9})\.?")


def title(kind: str) -> str:
    """"Today" or "This Month" (the page's own words for the period)."""
    if kind not in PERFORMANCE_PERIODS:
        raise ValueError(f"no such performance period: {kind!r}")
    return PERFORMANCE_PERIODS[kind]


def source(kind: str) -> str:
    """The page read: "consult_performance.php?period=today"."""
    return f"{PERFORMANCE_PAGE}?period={kind}"


def waiting_text(kind: str) -> str:
    """The "please wait" line (Telegram Markdown: one _italic_ entity, no underscore inside)."""
    return f"⏳ _Reading the portal's Consultant Performance page ({title(kind)}) live..._"


def _bold_safe(text) -> str:
    """Portal text inside a *bold* entity: legacy Markdown reads it literally up to its closing '*'
    (a backslash there would show), so only a '*' of its own is changed."""
    return str(text).replace("*", "∗")


def _code(value) -> str:
    """A figure as a `code` span (a backtick of its own, which would end it, is changed)."""
    return "`" + str(value).replace("`", "ʼ") + "`"


def _int(text) -> Optional[int]:
    t = str(text or "").replace(",", "").strip()
    return int(t) if t.isdigit() else None


def _same_name(a: str, b: str) -> bool:
    return " ".join((a or "").split()).casefold() == " ".join((b or "").split()).casefold()


# --------------------------------------------------------------------------- checks of the page against itself

def _range_dates(text: str) -> Optional[Tuple[date, date]]:
    """The page's range ("30 Sep – 30 Sep 2026", "01 Sep – 30 Sep 2026") as dates, or None."""
    from src.dates import MONTHS, parse_portal_date
    last = parse_portal_date(text)
    m = _RANGE_START_RE.match(text or "")
    month = MONTHS.get(m.group(2).lower()) if m else None
    if last is None or month is None:
        return None
    year = last.year - 1 if month > last.month else last.year
    try:
        return date(year, month, int(m.group(1))), last
    except ValueError:
        return None


def _range_warning(kind: str, range_text: str, today: date) -> Optional[str]:
    """A ⚠️ line when the page's range is not today (Today) or this month from its 1st (This
    Month), as the bot's calendar in Dhaka has them; None when it is, or cannot be read as dates."""
    span = _range_dates(range_text)
    if span is None:
        return None
    first, last = span
    if kind == "today":
        ok = first == last == today
    else:
        month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        ok = first == today.replace(day=1) and last in (today, month_end)
    if ok:
        return None
    return (f"⚠️ The page's range is {esc(range_text)}, but today in Dhaka is {today:%d %b %Y}: "
            "the figures are the portal's, for the range it shows.")


def _top_warnings(page: Dict[str, Any]) -> List[str]:
    """Where the top performer card and the leaderboard disagree (both shown as the portal has them)."""
    top, rows = page.get("top"), page.get("leaderboard") or []
    if top is None:
        return ["⚠️ The page shows no top performer card, though its leaderboard lists "
                f"{len(rows)} consultant{'s' if len(rows) != 1 else ''}."] if rows else []
    if not rows:
        return ["⚠️ The page shows a top performer card but no one on its leaderboard."]
    crowned = [r for r in rows if r.get("top")]
    if not crowned:
        return []
    row = crowned[0]
    if not _same_name(top["name"], row["name"]):
        return [f"⚠️ The top performer card names {esc(top['name'])}, the leaderboard crowns {esc(row['name'])}."]
    differ = [k.replace("_", " ") for k in _TOP_FIGURES if top.get(k) != row.get(k)]
    if differ:
        return [f"⚠️ The top performer card and the leaderboard's top row differ on: {', '.join(differ)}."]
    return []


def _total_warnings(page: Dict[str, Any]) -> List[str]:
    """Where a tile is not its leaderboard column's total (Consultancies done, Files opened, Docs
    ready): both are the portal's own figures, so the difference is said, never resolved."""
    rows = page.get("leaderboard") or []
    labels = dict((key, label) for key, label in page.get("columns") or [] if key)
    lines = []
    for tile, figure in (page.get("tiles") or {}).items():
        key = next((col for word, col in _TILE_COLUMN if _label_key(tile).startswith(word)), None)
        total = _int(figure)
        if key is None or total is None or not rows:
            continue
        values = [_int(r.get(key)) for r in rows]
        if any(v is None for v in values):
            continue
        if sum(values) != total:
            lines.append(f"⚠️ The leaderboard's {esc(labels.get(key, key))} add up to {sum(values)}, "
                         f"the {esc(tile)} tile says {esc(figure)}.")
    return lines


# --------------------------------------------------------------------------- the reply

def _tile_lines(tiles: Dict[str, str]) -> List[str]:
    lines = []
    for label, figure in tiles.items():
        emoji = next((e for word, e in _TILE_EMOJI if _label_key(label).startswith(word)), "•")
        lines.append(f"{emoji} *{_bold_safe(label)}:* {_code(figure)}")
    return lines


def _top_lines(page: Dict[str, Any], kind: str) -> List[str]:
    top = page.get("top")
    if top is None:
        return ["🏆 *Top performer:* none shown on the page for this period."]
    label = top.get("label") or f"Top performer · {title(kind)}"
    lines = [f"🏆 *{_bold_safe(label)}:* {esc(top['name'])}"]
    figures = " · ".join(f"{esc(name)} {_code(value)}" for name, value in top.get("metrics") or [])
    if figures:
        lines.append(f"   {figures}")
    return lines


def _row_lines(row: Dict[str, Any], columns: List[Tuple[Optional[str], str]]) -> List[str]:
    """One consultant: "*1. NAME*" (and the page's Top crown), then every other column in the
    header's order, two a line, each with the header's own text."""
    items = []
    for key, label in columns:
        if key in ("rank", "name"):
            continue
        value = row.get(key) if key else (row.get("extra") or {}).get(label, "")
        items.append(f"{esc(label)} {_code(value) if value != '' else '(blank)'}")
    pairs = [" · ".join(items[i:i + 2]) for i in range(0, len(items), 2)]
    head = f"*{_bold_safe(row.get('rank', ''))}. {_bold_safe(row['name'])}*" + (" 🏆 Top" if row.get("top") else "")
    return [head] + [f"   {'└' if i == len(pairs) - 1 else '├'} {p}" for i, p in enumerate(pairs)]


def _leaderboard_lines(page: Dict[str, Any]) -> List[str]:
    rows = page.get("leaderboard") or []
    count = page.get("count") if page.get("count") is not None else len(rows)
    lines = [f"🏅 *Leaderboard* ({count} consultant{'s' if count != 1 else ''})"]
    if not rows:
        said = page.get("empty_text") or ""
        return lines + ["• Nobody is listed for this period" + (f" (the page says: “{esc(said)}”)." if said else ".")]
    columns = page.get("columns") or []
    for row in rows:
        lines += _row_lines(row, columns)
    labels = dict((key, label) for key, label in columns if key)
    help_lines = [f"ℹ️ *{_bold_safe(labels.get(key, name))}:* {esc(page.get(key + '_help'))}"
                  for key, name in (("score", "Score"), ("points", "Points")) if page.get(key + "_help")]
    return lines + ([""] + help_lines if help_lines else [])


def format_consult_performance(kind: str, page: Dict[str, Any], today: date) -> str:
    """The reply (Telegram Markdown) for the page read for `kind`: header with the period and the
    portal's range, the tiles, the top performer, the whole leaderboard, the tooltips, and a
    footer naming the page and its sort note. Only the page's own words and figures."""
    shown = page.get("period_label") or title(kind)
    header = f"📅 Showing *{_bold_safe(shown)}*"
    if page.get("range_text"):
        header += f" · {esc(page['range_text'])}"
    lines = [f"📈 *Consultant Performance — {title(kind)}*", header]
    if page.get("scope_note"):
        lines.append(f"ℹ️ The page notes: {esc(page['scope_note'])}")
    warning = _range_warning(kind, page.get("range_text") or "", today)
    if warning:
        lines.append(warning)
    lines += [RULE] + _tile_lines(page.get("tiles") or {}) + [""] + _top_lines(page, kind)
    lines += [""] + _leaderboard_lines(page)
    checks = _top_warnings(page) + _total_warnings(page)
    if checks:
        lines += [""] + checks
    note = (page.get("sort_note") or "").strip()
    # The page's path as escaped text, not a `code` span: the plain-text resend (markdown_to_plain)
    # keeps an escaped underscore and would drop one inside a code span.
    footer = (f"🔗 Read live just now, read-only, from the portal's Consultant Performance page "
              f"({esc(source(kind))}).")
    if note:
        footer += f" {esc(note)}" + ("" if note.endswith((".", "!", "?")) else ".")
    return "\n".join(lines + ["", footer])


def message_pieces(text: str, limit: Optional[int] = None) -> List[str]:
    """The reply cut into messages of at most `limit` Telegram characters (replies.CHUNK_CHARS),
    only between records (R6): a consultant's "*N. NAME*" line and its "├ / └" figure lines, and
    the top performer's name with its figures line, always go in one message. A line indented by
    three spaces (or a blank line) continues the line above it, so no message starts with one.
    Joining the pieces with "\\n" gives the text back. A record longer than `limit` on its own
    (never on the live page) is split between its lines (replies.split_text)."""
    from src.bot.replies import CHUNK_CHARS, split_text, telegram_len
    limit = limit or CHUNK_CHARS
    records: List[str] = []
    for line in (text or "").split("\n"):
        if records and (line.startswith("   ") or not line.strip()):
            records[-1] += "\n" + line
        else:
            records.append(line)
    pieces: List[str] = []
    current: Optional[str] = None
    for record in records:
        if telegram_len(record) > limit:
            if current is not None:
                pieces.append(current)
            parts = split_text(record, limit)
            pieces.extend(parts[:-1])
            current = parts[-1] if parts else None
        elif current is not None and telegram_len(current) + 1 + telegram_len(record) > limit:
            pieces.append(current)
            current = record
        else:
            current = record if current is None else f"{current}\n{record}"
    if current is not None and current.strip():
        pieces.append(current)
    return [p for p in pieces if p.strip()]


async def build_performance_report(kind: str, today: Optional[date] = None,
                                   reads: Optional[Dict[str, Any]] = None) -> str:
    """The reply for /performance_today ("today") or /performance_month ("month"), read live from
    the portal's Consultant Performance page. Never raises: a page that cannot be read, or whose
    layout is not recognised, gives the stock "Couldn't read the portal" reply (never zeros).
    `reads` (a dict, when given) keeps the page read, for src.cloud.command_hooks.publish (a page
    that was not read keeps nothing)."""
    from src.bot.replies import portal_error_reply
    from src.cloud import command_hooks as cloud
    from src.dates import local_today
    from src.scraper.client import admin_client, portal_error_reason
    started = time.perf_counter()
    what = f"The portal's Consultant Performance page ({title(kind)})"
    try:
        page = await admin_client.read_consult_performance(kind)
    except Exception as e:                           # the portal down, a layout change, a timeout...
        logger.error(f"Consultant performance {kind}: not read ({portal_error_reason(e)})")
        return portal_error_reply(what, e)
    cloud.seen(reads, performance=(kind, page))      # nothing while publishing is off
    text = format_consult_performance(kind, page, today or local_today())
    logger.info(f"Consultant performance {kind}: read in {time.perf_counter() - started:.1f} s, "
                f"{len(page['leaderboard'])} leaderboard row(s); {len(text)} characters.")
    return text
