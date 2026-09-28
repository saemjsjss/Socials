"""Sending long text to Telegram, and the bot's two stock error replies.

Telegram refuses a message over 4096 characters ("Message is too long"), and refuses a whole
message whose legacy Markdown it cannot parse ("Can't parse entities"). Every reply that can grow
with the portal's data goes through here:

  split_text(text)        pieces of at most CHUNK_CHARS (3900), split between lines, never inside
                          one (a single overlong line is cut at a space). Lengths are counted the way
                          Telegram counts them (UTF-16 code units), so emoji never tip a piece over.
  send_pieces(send, ...)  sends the pieces through any `send(text, parse_mode)` coroutine; a piece
                          Telegram cannot parse as Markdown goes again as plain text
                          (markdown_to_plain). Other errors are not hidden.
  reply_long(message, ...)       message.reply_text for every piece; with edit=<a sent "please wait"
                                 message>, that message is edited into the first piece instead.
  send_long(bot, chat_id, ...)   bot.send_message for every piece.

Legacy Markdown entities (*bold*, _italic_, `code`) never span lines in the bot's messages, so a
split between lines never cuts one in half.

  date_error_reply(raw, command)   "I couldn't read that date" with the reason and examples.
  portal_error_reply(what, error)  "Couldn't read the portal: <why>" for a failed live read.
"""
import logging
import re
from typing import Any, Awaitable, Callable, List, Optional

from telegram.error import BadRequest
from telegram.helpers import escape_markdown

logger = logging.getLogger("hangeul.replies")

TELEGRAM_LIMIT = 4096           # characters a message may have
CHUNK_CHARS = 3900              # the most a piece gets, leaving room to spare

Send = Callable[[str, Optional[str]], Awaitable[Any]]


def telegram_len(text: str) -> int:
    """The length of `text` as Telegram counts it: UTF-16 code units (an emoji can count as 2)."""
    return len((text or "").encode("utf-16-le")) // 2


def _cut(line: str, limit: int) -> int:
    """Where to cut an overlong line: the last space that keeps the head within `limit` units."""
    end, units = 0, 0
    for i, ch in enumerate(line):
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > limit:
            break
        end = i + 1
    space = line.rfind(" ", 0, end)
    return space if space > 0 else max(end, 1)


def split_text(text: str, limit: int = CHUNK_CHARS) -> List[str]:
    """Pieces of at most `limit` Telegram characters, split between lines, so no line is ever cut
    (a single line longer than `limit` is split at a space). Joining the pieces with "\\n" gives the
    text back (bar the spaces an overlong line was cut at). A blank text gives []."""
    chunks: List[str] = []
    current = ""
    for line in (text or "").split("\n"):
        while telegram_len(line) > limit:
            cut = _cut(line, limit)
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:cut])
            line = line[cut:].lstrip()
        if current and telegram_len(current) + 1 + telegram_len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current.strip():
        chunks.append(current)
    return chunks


def markdown_to_plain(text: str) -> str:
    """Legacy Telegram Markdown as plain text: the *, _ and ` markers dropped, escaping backslashes
    removed ("Lina\\_Parvin" -> "Lina_Parvin")."""
    text = re.sub(r"(?<!\\)[*_`]", "", text or "")
    return re.sub(r"\\([_*`\[])", r"\1", text)


def is_markdown_error(error: Exception) -> bool:
    """Whether Telegram refused a message for its Markdown ("Can't parse entities ...")."""
    msg = str(error).lower()
    return isinstance(error, BadRequest) and ("parse" in msg or "entit" in msg)


async def _send_one(send: Send, piece: str, parse_mode: Optional[str]) -> Any:
    try:
        return await send(piece, parse_mode)
    except BadRequest as e:
        if not parse_mode or not is_markdown_error(e):
            raise
        logger.warning(f"A reply piece was not accepted as {parse_mode} ({e}); sent as plain text.")
        return await send(markdown_to_plain(piece), None)


async def send_pieces(send: Send, text: str, parse_mode: Optional[str] = "Markdown", *,
                      first: Optional[Send] = None, limit: int = CHUNK_CHARS) -> int:
    """Send `text` through `send(piece, parse_mode)`, piece by piece (split_text); a piece Telegram
    cannot parse as Markdown goes again as plain text. With `first`, the first piece goes through
    `first` instead (editing a "please wait" message); if that edit fails for any reason other than
    its Markdown, the piece is sent through `send` so nothing is lost. -> how many pieces went out."""
    pieces = split_text(text, limit)
    for i, piece in enumerate(pieces):
        if i == 0 and first is not None:
            try:
                await _send_one(first, piece, parse_mode)
                continue
            except BadRequest as e:
                if "not modified" in str(e).lower():
                    continue                     # it already shows exactly this
                logger.warning(f"Could not edit the waiting message ({e}); sending the reply instead.")
        await _send_one(send, piece, parse_mode)
    return len(pieces)


async def reply_long(message, text: str, parse_mode: Optional[str] = "Markdown", *, edit=None) -> int:
    """Reply to `message` with `text`, split under Telegram's limit (send_pieces). With `edit` (the
    "⏳ ..." message the command sent first), that message is edited into the first piece and the
    rest are replies. -> how many pieces went out."""
    first = None
    if edit is not None:
        async def first(piece, mode):
            return await edit.edit_text(piece, parse_mode=mode)
    return await send_pieces(lambda piece, mode: message.reply_text(piece, parse_mode=mode), text,
                             parse_mode, first=first)


async def send_long(bot, chat_id, text: str, parse_mode: Optional[str] = "Markdown") -> int:
    """bot.send_message(chat_id, ...) for every piece of `text` (send_pieces). -> pieces sent."""
    return await send_pieces(lambda piece, mode: bot.send_message(chat_id=chat_id, text=piece, parse_mode=mode),
                             text, parse_mode)


# --------------------------------------------------------------------------- stock replies

def _quoted(raw: str, most: int = 60) -> str:
    raw = re.sub(r"\s+", " ", raw or "").strip()
    return escape_markdown(raw if len(raw) <= most else raw[:most - 1] + "…", version=1)


def date_error_reply(raw: str, command: str = "", reason: Optional[str] = None) -> str:
    """The reply (Telegram Markdown) for a date the bot could not read: what was typed, why (from
    src.dates.user_date_problem when `reason` is not given), and how to ask again with `command`
    ("/verified_date"). Never falls back to another day."""
    from src.dates import user_date_problem
    why = reason or user_date_problem(raw, prefer_past=True) or "it is not a date"
    lines = [f"⚠️ I couldn't read “{_quoted(raw)}” as a date ({escape_markdown(why, version=1)}).",
             "Please send a date like `12 Sep 2026`, `yesterday` or `2026-09-12`"
             + (f", for example `{command} 12 Sep 2026`." if command else ".")]
    return "\n".join(lines)


def portal_error_reply(what: str, error: Exception) -> str:
    """The reply (Telegram Markdown) for a live read that failed: "❌ Couldn't read the portal: <why>.
    <what>: not available right now. ..." `what` is the caller's own (already safe) Markdown, such
    as "Verified students for 12 September 2026". Never a 0, "none" or an empty list."""
    from src.scraper.client import portal_error_reason
    return (f"❌ Couldn't read the portal: {escape_markdown(portal_error_reason(error), version=1)}.\n"
            f"{what}: not available right now. Please try again in a minute.")
