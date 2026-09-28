"""The daily brief, written in code from facts.

Every number, name and status below comes from a read-only GET of the live portal (and, in one
section labelled "not live", the bot's own local document-check results), counted here in code.
Nothing is estimated: a figure that cannot be read is "not available", and a section with nothing
in it says so ("None today"). A day the portal cannot answer for is "not available" too, never a
0: consult_requests.php lists only the latest CONSULT_PAGE_LIMIT requests, and students.php writes
verification times without a year. There are no passport-match claims, visa counts, conversion
rates or intakes: no reader provides them.

The local LLM may add ONE short summary at the end, written from a small list of the same facts,
one figure a line (llm_summary). It is dropped unless every claim in it checks out against those
facts (claims_problem): each number, in digits or words, must be the figure of the fact its own
clause talks about ("5 done" when 5 were received is dropped), "no" / "none" / "zero" count as 0,
and every word must come from the facts or a short list of plain connecting words, so an invented
name, status ("cleared", "approved"), vague count ("several", "both"), ordinal, decimal or foreign
number word never gets through. It is left out when the brain is down. Jennie's spoken brief is
built from the same facts and checked the same way (voice.spoken_brief). Pending payments and
window applications under review are two separate figures everywhere (guardrail 2): never added
together, and never one line.

The portal reads run one after another within PORTAL_BUDGET; after the first read the portal does
not answer, the rest are skipped, so a hung portal delays the brief by about a minute, not ten.

The text is Telegram Markdown (legacy): portal text (names, titles) is escaped, section headings
are bold. send_brief_text sends it in pieces of at most CHUNK_CHARS, split between lines, and
sends a piece again as plain text when Telegram cannot parse it.

Sections, and the pages behind them:
  1) consultations              consult_requests.php (read by column name)
  2) payment-verified students  students.php, every page
  3) portal figures             students.php?status=pending, window_applications.php, index.php
  4) today's calendar reminders calendar.php
  5) the last document check    data/verification/results.json (local, not live)
"""
import asyncio
import json
import logging
import re
import time
from collections import Counter
from datetime import date, datetime
from fractions import Fraction
from typing import Any, Awaitable, Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx
from telegram.error import BadRequest
from telegram.helpers import escape_markdown

from src.config import settings
from src.llm.ollama_client import ollama_client
from src.scraper.client import admin_client

logger = logging.getLogger("hangeul.brief")

NA = "not available"
DONE = ("Consulted", "File Opened")
KNOWN_STATUSES = ("Consulted", "File Opened", "New", "No Answer", "Wrong Number")
VERDICT_ORDER = ("FAIL", "REVIEW", "INCOMPLETE", "PASS")
CHUNK_CHARS = 3900              # Telegram allows 4096 characters a message
MAX_REMINDERS_LISTED = 8
SUMMARY_MAX_TOKENS = 120
SUMMARY_TIMEOUT = 30.0          # seconds for the one summary call (a warm call takes ~1 s)
SUMMARY_MAX_CHARS = 350
CONSULT_PAGE_LIMIT = 500        # consult_requests.php lists the latest 500 requests, no more
READ_TIMEOUT = 75.0             # seconds one portal read may take (the consultation page is ~2 MB)
PORTAL_BUDGET = 150.0           # seconds all the brief's portal reads together may take
PORTAL_DOWN = "the portal did not answer"

Section = Tuple[List[str], List[str]]     # (Markdown lines, plain one-figure facts for the summary)


class Brief(NamedTuple):
    text: str                   # the brief, Telegram Markdown
    facts: List[str]            # its figures, one plain line each: what the summary and Jennie may say


def _now() -> datetime:
    return datetime.now(ZoneInfo(settings.REPORT_TIMEZONE))


def esc(value: Any) -> str:
    """Portal text (a name, a title) made safe inside Telegram Markdown."""
    return escape_markdown(str(value), version=1)


def brief_plain(text: str) -> str:
    """The Markdown brief as plain text: no bold or italic markers, no escaping backslashes."""
    text = re.sub(r"(?<!\\)[*_]", "", text or "")
    return re.sub(r"\\([_*`\[])", r"\1", text)


def _fig(value: Any) -> str:
    return NA if value is None else str(value)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _amount(text: Optional[str]) -> Optional[float]:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    return float(m.group(0).replace(",", "")) if m else None


def _day(text: Optional[str]) -> Optional[date]:
    """'28 Sep 2026' -> a date, or None."""
    try:
        return datetime.strptime((text or "").strip(), "%d %b %Y").date()
    except ValueError:
        return None


def _na(why: Optional[str], default: str) -> str:
    return f"{NA} ({why or default})"


# --------------------------------------------------------------------------- 1) consultations

def consultation_coverage(rows: List[Dict[str, Any]], day: date) -> Optional[str]:
    """Why the consultation page cannot give `day`'s requests, or None when it can. The page lists
    only the latest CONSULT_PAGE_LIMIT requests: a day before its oldest row is unknown (not 0), and
    when the list is full its oldest day is only partly there. A row whose date cannot be read
    makes every day's count unsure."""
    if not rows:
        return None
    dates = [_day(r.get("received_date")) for r in rows]
    unread = sum(1 for d in dates if d is None)
    if unread:
        return (f"{_plural(unread, 'request')} on the page {'has a date' if unread == 1 else 'have dates'} "
                "the brief cannot read")
    oldest = min(dates)
    if day < oldest:
        return f"the consultation page only lists requests back to {oldest:%d %b %Y}"
    if day == oldest and len(rows) >= CONSULT_PAGE_LIMIT:
        return (f"the page's list of the latest {len(rows)} requests starts partway through "
                f"{oldest:%d %b %Y}")
    return None


def section_consultations(rows: Optional[List[Dict[str, Any]]], portal_day: str, is_today: bool,
                          why: Optional[str] = None) -> Section:
    when = "today" if is_today else f"on {portal_day}"
    said = "today" if is_today else "on the day"
    lines = [f"*1) CONSULTATIONS {when.upper()}*"]
    if rows is None:
        return (lines + [f"• {_na(why, 'the consultation page could not be read')}"],
                [f"Consultation requests received {said}: {NA}"])
    day = _day(portal_day)
    gap = consultation_coverage(rows, day) if day else "the date could not be read"
    if gap:
        lines.append(f"• {NA} ({esc(gap)})")
        facts = [f"Consultation requests received {said}: {NA}"]
    else:
        day_rows = [r for r in rows if r.get("received_date") == portal_day]
        st = Counter(r.get("status", "") for r in day_rows)
        done = sum(st[s] for s in DONE)
        facts = [f"Consultation requests received {said}: {len(day_rows)}"]
        if not day_rows:
            lines.append(f"• None received {when}")
        else:
            lines.append(f"• Received: {len(day_rows)}  |  Done: {done} "
                         f"({st['Consulted']} consulted, {st['File Opened']} file opened)")
            lines.append(f"• New / pending: {st['New']}  |  No answer: {st['No Answer']}  |  "
                         f"Wrong number: {st['Wrong Number']}")
            other = [(s, n) for s, n in st.most_common() if s not in KNOWN_STATUSES]
            if other:
                lines.append("• Other status: " + ", ".join(f"{esc(s or 'blank')} {n}" for s, n in other))
            by = Counter(r.get("handled_by") or "Unassigned" for r in day_rows if r.get("status") in DONE)
            if by:
                lines.append("• Done by: " + ", ".join(f"{esc(name)} {n}" for name, n in by.most_common()))
            # One figure a fact, each with words of its own, so a summary's number can be checked
            # against the very fact its words describe (claims_problem).
            facts += [f"Consultations done {said}: {done}",
                      f"Marked Consulted {said}: {st['Consulted']}",
                      f"Marked File Opened {said}: {st['File Opened']}",
                      f"Requests still new {said}: {st['New']}",
                      f"No answer {said}: {st['No Answer']}",
                      f"Wrong number {said}: {st['Wrong Number']}"]
            facts += [f"Handled {said} by counsellor {name}: {n}" for name, n in by.most_common()]
    every = Counter(r.get("status", "") for r in rows)
    # Not all-time: the page lists only its newest requests, so say which days they cover.
    days = sorted(d for d in (_day(r.get("received_date") or "") for r in rows) if d)
    span = f", {days[0]:%d %b}–{days[-1]:%d %b %Y}" if days else ""
    lines.append(f"• The latest {len(rows)} requests on the page{span}: "
                 f"{sum(every[s] for s in DONE)} done, {every['New']} new, {every['No Answer']} no answer, "
                 f"{every['Wrong Number']} wrong number")
    return lines, facts


# --------------------------------------------------------------------------- 2) verified payments

def verified_day_problem(day: date, today: date) -> Optional[str]:
    """Why students.php cannot tell who was verified on `day`, or None when it can. The portal
    writes verification times without a year ("27 Sep, 17:19"), so a day whose day and month have
    come round again since cannot be told apart from that later one."""
    if day > today:
        return "a date in the future"
    try:
        again = day.replace(year=day.year + 1)
    except ValueError:                       # 29 Feb
        again = date(day.year + 1, 3, 1)
    if again <= today:
        return (f"the portal writes verification times without a year, so {day:%d %b %Y} cannot be "
                f"told apart from {again:%d %b %Y}")
    return None


def _clock(verified_time: str) -> str:
    """'27 Sep, 17:19' -> '17:19' (the day is the brief's own); anything else as it is."""
    m = re.search(r"\b\d{1,2}:\d{2}\b", verified_time or "")
    return m.group(0) if m else (verified_time or "").strip()


def section_verified(verified: Optional[List[Dict[str, Any]]], portal_day: str, is_today: bool,
                     why: Optional[str] = None) -> Section:
    when = "today" if is_today else f"on {portal_day}"
    said = "today" if is_today else "on the day"
    lines = [f"*2) PAYMENT-VERIFIED STUDENTS {when.upper()}*"]
    if verified is None:
        return (lines + [f"• {_na(esc(why) if why else None, 'the student list could not be read')}"],
                [f"Students whose payment was verified {said}: {NA}"])
    facts = [f"Students whose payment was verified {said}: {len(verified)}"]
    if not verified:
        return lines + [f"• None {when}"], facts
    amounts = [a for a in (_amount(v.get("amount")) for v in verified) if a is not None]
    head = f"• {_plural(len(verified), 'student')}"
    if amounts:
        total = f"{sum(amounts):,.2f} BDT"
        head += f"  |  Total: {total}"
        if len(amounts) < len(verified):
            head += f" (the {len(amounts)} with an amount on the portal; {len(verified) - len(amounts)} without)"
            facts.append(f"Total amount verified {said} (only the rows with an amount): {total}")
        else:
            facts.append(f"Total amount verified {said}: {total}")
    else:
        head += f"  |  Total: {NA} (no amount on the rows)"
        facts.append(f"Total amount verified {said}: {NA}")
    lines.append(head)
    for i, v in enumerate(verified, 1):
        parts = [esc(v[k]) for k in ("name", "program") if v.get(k)]
        paid = " ".join(x for x in (v.get("amount"), v.get("method")) if x)
        if paid:
            parts.append(esc(paid))
        clock = _clock(v.get("verified_time", ""))
        if v.get("verified_by") or clock:
            parts.append((f"verified by {esc(v['verified_by'])}" if v.get("verified_by") else "verified")
                         + (f" at {esc(clock)}" if clock else ""))
        lines.append(f"  {i}. " + (" — ".join(parts) or "(no details on the portal row)"))
    return lines, facts


# --------------------------------------------------------------------------- 3) portal figures

def _separate_line(label: str, value: Optional[int], tile: Optional[int], source: str,
                   why: Optional[str] = None) -> str:
    if value is not None:
        text = f"{value} ({source})"
        if tile is not None and tile != value:
            text += f"; the dashboard tile says {tile}"
    elif tile is not None:
        text = f"{tile} (dashboard tile; {source} could not be read)"
    else:
        text = f"{NA} ({why})" if why else NA
    return f"• {label}: {text}"


def section_portal(pending: Optional[Dict[str, Any]], review: Optional[int],
                   dashboard: Optional[Dict[str, Any]], why: Optional[str] = None) -> Section:
    lines = ["*3) PORTAL FIGURES (live now)*"]
    summary = (dashboard or {}).get("summary") or {}
    tiles = (dashboard or {}).get("tiles") or []
    pending_count = pending.get("count") if pending else None
    pending_tile, review_tile = summary.get("pending_payment"), summary.get("window_apps_under_review")
    lines.append(_separate_line("Pending payments", pending_count, pending_tile, "students.php?status=pending", why))
    lines.append(_separate_line("Window applications under review", review, review_tile,
                                "window\\_applications.php", why))
    lines.append("  _(two separate figures, never added together)_")
    groups: Dict[str, List[str]] = {}
    for t in tiles:
        key = re.sub(r"[^a-z]+", " ", t["label"].lower()).strip()
        if key.startswith("pending payment") or key == "under review":
            continue                                   # already on their own lines above
        groups.setdefault(t.get("group") or "", []).append(f"{esc(t['label'])} {esc(t['text'])}")
    if not groups:
        lines.append(f"• Dashboard tiles: {NA}" + (f" ({why})" if why else ""))
    for group, items in groups.items():
        lines.append(f"• Dashboard{', ' + esc(group) if group else ''}: " + " · ".join(items))
    pending_fact = pending_count if pending_count is not None else pending_tile
    review_fact = review if review is not None else review_tile
    return lines, [f"Pending payments: {_fig(pending_fact)}",
                   f"Window applications under review (a separate figure): {_fig(review_fact)}"]


# --------------------------------------------------------------------------- 4) calendar

def section_calendar(cal: Optional[Dict[str, Any]], is_today: bool, why: Optional[str] = None) -> Section:
    lines = ["*4) TODAY'S CALENDAR REMINDERS*"]
    if not is_today:
        return lines + ["• shown for today only (the calendar page lists today's reminders)"], []
    if cal is None or "error" in cal:
        return (lines + [f"• {_na(why, 'the calendar page could not be read')}"],
                [f"Calendar reminders for today: {NA}"])
    if not cal.get("layout_ok"):
        return (lines + [f"• {NA} (the calendar page's layout was not recognised)"],
                [f"Calendar reminders for today: {NA}"])
    reminders = cal.get("today_reminders") or []
    skipped, stated = cal.get("skipped_untitled") or 0, cal.get("heading_count")
    if not reminders:
        if skipped or stated:
            return (lines + [f"• {NA} (the page lists {stated or skipped} but none could be read)"],
                    [f"Calendar reminders for today: {NA}"])
        return lines + ["• None today"], ["Calendar reminders for today: 0"]
    kinds = Counter(r.get("type") or "Other" for r in reminders)
    lines.append(f"• {_plural(len(reminders), 'reminder')}: " + ", ".join(f"{esc(k)} {n}" for k, n in kinds.most_common()))
    if skipped:
        lines.append(f"  ({skipped} {'entry' if skipped == 1 else 'entries'} without a title skipped)")
    for r in reminders[:MAX_REMINDERS_LISTED]:
        bits = [esc(r["title"])]
        bits += [esc(r[k]) for k in ("type", "date_range") if r.get(k)]
        if r.get("days_left") is not None:
            bits.append(f"{_plural(r['days_left'], 'day')} left")
        lines.append("  - " + " — ".join(bits))
    if len(reminders) > MAX_REMINDERS_LISTED:
        lines.append(f"  … and {len(reminders) - MAX_REMINDERS_LISTED} more")
    return lines, ([f"Calendar reminders for today: {len(reminders)}"]
                   + [f"Calendar reminders for today of type {k}: {n}" for k, n in kinds.most_common()])


# --------------------------------------------------------------------------- 5) document check

def read_document_check() -> Optional[Dict[str, Any]]:
    """Verdict counts from the bot's own document-check store (src/verify/auto_verify.py), or None."""
    try:
        store = json.loads((settings.verification_dir() / "results.json").read_text(encoding="utf-8"))
        docs = [d for d in (store.get("documents") or {}).values() if isinstance(d, dict)]
    except Exception as e:
        logger.info(f"Document-check results not read: {type(e).__name__}: {e}")
        return None
    verdicts = Counter(d.get("verdict") or "no verdict" for d in docs)
    return {"students": len(docs), "verdicts": verdicts,
            "last_checked": max((str(d.get("checked") or "") for d in docs), default="")}


def section_documents(doc: Optional[Dict[str, Any]]) -> Section:
    lines = ["*5) DOCUMENT CHECK (from the last automated check, not live)*"]
    if doc is None:
        return lines + [f"• {NA} (no local check results)"], []
    if not doc["students"]:
        return lines + ["• No student checked yet"], []
    v = doc["verdicts"]
    order = [k for k in VERDICT_ORDER if v.get(k)] + sorted(k for k in v if k not in VERDICT_ORDER)
    lines.append(f"• {_plural(doc['students'], 'student')}: " + ", ".join(f"{esc(k)} {v[k]}" for k in order))
    try:
        when = datetime.fromisoformat(doc["last_checked"]).strftime("%d %b %Y, %H:%M")
        lines.append(f"• Last check: {when}")
    except ValueError:
        pass
    return lines, []


# --------------------------------------------------------------------------- checking claims

_SUMMARY_SYSTEM = (
    "You write a one- or two-sentence plain-English summary of an office's figures for its owner. "
    "Use ONLY the facts given, with their numbers exactly as written, and put each number next to "
    "the words of its own fact, one figure per clause (for example '<number> consultation requests "
    "were received today'). Never add a number, total, percentage, rate, date or time; never add "
    "figures together, compare them or guess a trend; never use a name, status or word for a "
    "count that the facts do not use. "
    "Pending payments and window applications under review are separate: never combine them. "
    "Do not mention visas, passports, intakes or conversion. No Markdown, no emojis, at most 280 "
    "characters. Output only the summary."
)
# What the brief never reports, so a summary that brings it up is making it up.
_OFF_TOPIC_RE = re.compile(r"\b(?:visas?|passports?|conversion|intakes?|rates?|percent(?:age)?|per\s+cent|"
                           r"prepared\s+by|ytd)\b|%", re.I)
# Words for a count or a comparison that the number check cannot compare with a fact.
_ORDINALS = ("first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
             "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth thirtieth fortieth "
             "fiftieth hundredth thousandth").split()
_VAGUE_NUMBER_RE = re.compile(
    r"\b(?:dozens?|half|halves|twice|thrice|double[ds]?|triple[ds]?|quadrupled?|quarter|both|couple|pairs?|"
    r"single|several|few|fewer|many|multiple|handful|numerous|various|lots?|plenty|most|majority|minority|"
    r"all|every|each|some|any|another|more|less|least|average|ratio|than|compared|increased?|decreased?|"
    r"higher|lower|trend|growth|record|" + "|".join(_ORDINALS) + r")\b|\b\d+(?:st|nd|rd|th)\b", re.I)
# A negation turns a figure around ("3 were not done"); the check cannot follow that.
_NEGATION_RE = re.compile(r"\b(?:not|never|without|cannot|neither|nor)\b|n[’']t\b", re.I)
# "No", "none", "nobody"... claim a 0: it must be the 0 of the fact the clause talks about.
_NOTHING_RE = re.compile(r"\b(?:no|none|nothing|nobody|nil)\b", re.I)
# Phrases that are one fact word, not a "no" or a "not" ("No answer: 2", "not available").
_PHRASES = ((re.compile(r"\bno[\s-]+answers?\b", re.I), " noanswer "),
            (re.compile(r"\bnot\s+available\b", re.I), " notavailable "))
# Only plain English: another script's number words ("পাঁচ") would get past the number check.
_FOREIGN_RE = re.compile(r"[^\x00-\x7F‘’“”–—…\u00a0]")
# A clause ends at punctuation (not inside "28,000.00") or a joining word.
_CLAUSE_RE = re.compile(r"(?<!\d)[,.]|[,.](?!\d)|[;!?()\[\]\n]|\b(?:and|but|while|whereas|plus|with|also|then)\b", re.I)
# Plain connecting words any sentence may use besides the facts' own words. They never tell which
# fact a clause is about, and none of them is a count, a status or a comparison.
_STOP_TEXT = ("""
a an the and or but of in on at by for to from with as so far this that these those there here it its
they their them we our us is are was were be been being has have had do does did get got come comes
coming into out today tonight day evening morning afternoon still also yet just now currently
which who whose while whereas plus worth totalling totaling amounting stand stands standing sit sits
remain remains remained remaining waiting awaiting listed recorded logged shown reported overall
altogether together due summary no none nothing nobody nil zero s ve re ll d m
""")
# Other words for a fact's own word.
_SYNONYMS = {"inquiry": "request", "enquiry": "request", "lead": "request", "came": "received",
             "arrived": "received", "taka": "bdt", "tk": "bdt", "counselor": "counsellor",
             "consultant": "counsellor", "verification": "verified", "verify": "verified"}


def _numbers(text: str) -> set:
    """Every number in the text, digits or words (voice._numbers_in), and a lone "one" too."""
    from src.bot.voice import _numbers_in
    found = _numbers_in(text or "")
    if re.search(r"\bone\b", text or "", re.I):
        found.add(1)
    return found


def _number_word(word: str) -> bool:
    from src.bot.voice import _WORD_SCALES, _WORD_VALUES
    return word in _WORD_VALUES or word in _WORD_SCALES or word == "hundred"


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        word = word[:-3] + "y"
    elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    return _SYNONYMS.get(word, word)


_STOP_WORDS = {_stem(w) for w in _STOP_TEXT.split()}


def _words(text: str) -> List[str]:
    """The text's words, lower case, plurals and synonyms folded ("inquiries" -> "request")."""
    text = (text or "").lower()
    for pattern, token in _PHRASES:
        text = pattern.sub(token, text)
    return [_stem(w) for w in re.findall(r"[a-z]+", text)]


def _keywords(text: str) -> set:
    """The words that tell what a fact or a clause is about."""
    return {w for w in _words(text) if w not in _STOP_WORDS and not _number_word(w)}


def _decimals(text: str) -> set:
    return {float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.\d+", text or "")}


def claims_problem(text: str, facts: Iterable[str], extra_words: Iterable[str] = ()) -> Optional[str]:
    """Why `text` (the LLM's summary, or Jennie's spoken line) may not be shown, or None when every
    claim in it is one of the facts (one figure a line, as compose_brief builds them).

    Each clause's numbers (a "no" / "none" / "zero" is 0) must be the figure of the fact that
    clause's words point to: the fact sharing its most telling words (a word few facts use counts
    more), and among equals the one with the fewest words the clause does not use. Every word must
    be a fact's word, a plain connecting word (_STOP_WORDS) or one of `extra_words` (Jennie's
    "yay", "hehe"). Off-topic subjects, vague or comparing count words, negations, decimals and
    numbers the facts do not have are refused outright."""
    facts = [f.strip() for f in facts if f and f.strip()]
    plain = re.sub(r"\s+", " ", text or "").strip()
    if not plain:
        return "empty"
    if _FOREIGN_RE.search(plain):
        return "not plain English"
    if _OFF_TOPIC_RE.search(plain):
        return "it talks about what the brief does not report"
    if _VAGUE_NUMBER_RE.search(plain):
        return "a vague or comparing count word"
    phrased = plain
    for pattern, token in _PHRASES:
        phrased = pattern.sub(token, phrased)
    if _NEGATION_RE.search(phrased):
        return "a negation"
    facts_text = "\n".join(facts)
    extra = _numbers(plain) - _numbers(facts_text)
    if extra:
        return f"numbers not in the facts {sorted(extra)}"
    odd = {d for d in _decimals(plain) if d != int(d)} - _decimals(facts_text)
    if odd:
        return f"decimals not in the facts {sorted(odd)}"
    known = {w for f in facts for w in _words(f)} | _STOP_WORDS | {_stem(w.lower()) for w in extra_words}
    unknown = sorted({w for w in _words(plain) if w not in known and not _number_word(w)})
    if unknown:
        return f"words the facts do not use {unknown}"

    parsed = [(_keywords(f), _numbers(f)) for f in facts]
    df = Counter(k for kws, _ in parsed for k in kws)
    for clause in _CLAUSE_RE.split(phrased):
        said = _numbers(clause)
        if _NOTHING_RE.search(clause):
            said.add(0)
        if not said:
            continue
        about = _keywords(clause) & set(df)
        scored = [(sum(Fraction(1, df[k]) for k in about & kws), -len(kws - about), nums)
                  for kws, nums in parsed if about & kws]
        if not scored:
            return f"a number that belongs to no fact ({clause.strip()!r})"
        best = max((s, e) for s, e, _ in scored)
        allowed = set().union(*(nums for s, e, nums in scored if (s, e) == best))
        wrong = said - allowed
        if wrong:
            return f"{sorted(wrong)} is not the figure of what it describes ({clause.strip()!r})"
    return None


def check_summary(summary: Optional[str], facts: str) -> Optional[str]:
    """The LLM's summary, cleaned (plain text, at most two sentences), or None when it may not be
    shown: empty, too long, or any claim that is not one of the facts (claims_problem). `facts` is
    the list the LLM was given, one "- fact" a line."""
    from src.bot.voice import _plain
    text = re.sub(r"\s+", " ", _plain(summary or "")).strip().strip("\"'“”").strip()
    text = re.sub(r"^(?:summary|in short)\s*[:：-]\s*", "", text, flags=re.I)
    text = " ".join(re.split(r"(?<=[.!?])\s+", text)[:2]).strip()
    if not text or len(text) > SUMMARY_MAX_CHARS:
        return None
    problem = claims_problem(text, (line.strip().lstrip("-").strip() for line in (facts or "").splitlines()))
    if problem:
        logger.info(f"Brief summary dropped: {problem}.")
        return None
    return text


async def llm_summary(facts: List[str]) -> Optional[str]:
    """One short summary from the local LLM (the one option set every call uses), checked by
    check_summary. None when the brain is down, slow, or got a fact wrong, and when no fact has a
    figure (the portal could not be read): there is nothing to sum up."""
    if not facts or not any(re.search(r"\d", f) for f in facts):
        return None
    facts_text = "\n".join(f"- {f}" for f in facts)
    try:
        raw = await ollama_client.chat(
            [{"role": "system", "content": _SUMMARY_SYSTEM},
             {"role": "user", "content": f"Facts:\n{facts_text}\n\nSummary:"}],
            num_predict=SUMMARY_MAX_TOKENS, timeout=SUMMARY_TIMEOUT)
    except Exception as e:
        logger.warning(f"Brief summary skipped: {type(e).__name__}: {e}")
        return None
    return check_summary(raw, facts_text)


# --------------------------------------------------------------------------- compose & send

class _PortalReads:
    """The brief's portal reads, one after another (one portal session, no parallel logins), each
    within READ_TIMEOUT and all within PORTAL_BUDGET. Once the portal does not answer (a timeout, a
    refused or dropped connection), the remaining reads are skipped: the brief then goes out on
    time with those sections "not available". A read that fails any other way is "not available"
    on its own. `why` keeps each skipped or unanswered read's reason for its section."""

    def __init__(self):
        self.started = time.perf_counter()
        self.down: Optional[str] = None
        self.why: Dict[str, str] = {}

    async def read(self, what: str, job: Callable[[], Awaitable[Any]]) -> Any:
        if self.down:
            self.why[what] = f"not read: {self.down}"
            return None
        left = PORTAL_BUDGET - (time.perf_counter() - self.started)
        if left < 1:
            self.down = "the portal reads ran out of time"
            self.why[what] = f"not read: {self.down}"
            return None
        try:
            return await asyncio.wait_for(job(), timeout=min(READ_TIMEOUT, left))
        except (asyncio.TimeoutError, httpx.TransportError) as e:
            self.down = self.why[what] = PORTAL_DOWN
            logger.warning(f"Brief: {what} not read, {PORTAL_DOWN} ({type(e).__name__}); "
                           "the remaining portal reads are skipped.")
            return None
        except Exception as e:
            logger.warning(f"Brief: {what} not read: {type(e).__name__}: {e}")
            return None


async def compose_brief(day: Optional[date] = None, with_summary: bool = True) -> Brief:
    """The brief for `day` (default: today in settings.REPORT_TIMEZONE) from live read-only portal
    reads, and its facts (what the summary was written from, and what Jennie may say)."""
    started = time.perf_counter()
    now = _now()
    today = now.date()
    day = day or today
    is_today = day == today
    portal_day = day.strftime("%d %b %Y")
    reads = _PortalReads()

    if day > today:
        consultations = verified = None
        consult_why = verified_why = "a date in the future"
    else:
        consultations = await reads.read("consultations", admin_client.read_consultations)
        consult_why = reads.why.get("consultations")
        verified_why = verified_day_problem(day, today)
        verified = None
        if not verified_why:
            verified = await reads.read("verified students",
                                        lambda: admin_client.read_verified_students(portal_day, all_pages=True))
            verified_why = reads.why.get("verified students")
    pending = await reads.read("pending payments", admin_client.read_pending_payments)
    review = await reads.read("window applications", admin_client.read_window_apps_under_review)
    dashboard = await reads.read("dashboard", admin_client.get_dashboard)
    calendar = await reads.read("calendar", admin_client.get_calendar_events) if is_today else None
    documents = await asyncio.to_thread(read_document_check)
    read_seconds = time.perf_counter() - started

    if is_today:
        lines = [f"📋 *HANGEUL DAILY BRIEF* — {now:%d %B %Y}, {now:%H:%M} ({esc(settings.REPORT_TIMEZONE)})"]
    else:
        lines = [f"📋 *HANGEUL BRIEF FOR {day:%d %B %Y}* — read {now:%d %b %Y}, {now:%H:%M} "
                 f"({esc(settings.REPORT_TIMEZONE)})"]
    lines += ["_Facts only, read live from the portal (read-only) unless marked otherwise. Nothing is estimated._", ""]
    facts: List[str] = []
    for section_lines, section_facts in (
            section_consultations(consultations, portal_day, is_today, consult_why),
            section_verified(verified, portal_day, is_today, verified_why),
            section_portal(pending, review, dashboard, reads.down),
            section_calendar(calendar, is_today, reads.why.get("calendar")),
            section_documents(documents)):
        lines += section_lines + [""]
        facts += section_facts

    summary = await llm_summary(facts) if with_summary else None
    if summary:
        lines.append(f"🤖 _Summary by the local AI, its numbers checked against the facts:_ {esc(summary)}")
    text = "\n".join(lines).strip()
    logger.info(f"Daily brief composed: portal read in {read_seconds:.1f} s"
                f"{' (' + reads.down + ')' if reads.down else ''}, total "
                f"{time.perf_counter() - started:.1f} s, {len(text)} characters, "
                f"summary {'added' if summary else 'none'}.")
    return Brief(text, facts)


async def compose_daily_brief(day: Optional[date] = None, with_summary: bool = True) -> str:
    """The brief's text alone (compose_brief): /brief, /report and the dry run."""
    return (await compose_brief(day, with_summary)).text


def split_brief(text: str, limit: int = CHUNK_CHARS) -> List[str]:
    """Pieces of at most `limit` characters, split between lines, so no line is ever cut (a single
    line longer than `limit`, which the brief never has, is split at a space)."""
    chunks: List[str] = []
    current = ""
    for line in (text or "").split("\n"):
        while len(line) > limit:
            cut = line.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:cut])
            line = line[cut:].lstrip()
        if current and len(current) + 1 + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current.strip():
        chunks.append(current)
    return chunks


async def send_brief_text(send: Callable[[str, Optional[str]], Awaitable[Any]], text: str) -> int:
    """Send the brief through `send(text, parse_mode)`, piece by piece; a piece Telegram cannot
    parse as Markdown goes again as plain text. -> how many messages were sent."""
    sent = 0
    for chunk in split_brief(text):
        try:
            await send(chunk, "Markdown")
        except BadRequest as e:
            if "parse" not in str(e).lower() and "entit" not in str(e).lower():
                raise
            logger.warning(f"Brief piece not accepted as Markdown ({e}); sent as plain text.")
            await send(brief_plain(chunk), None)
        sent += 1
    return sent


async def _send_brief(bot, chat_id, text: str) -> int:
    """Send the brief to chat_id with bot.send_message (the 18:05 job and /brief)."""
    return await send_brief_text(
        lambda chunk, mode: bot.send_message(chat_id=chat_id, text=chunk, parse_mode=mode), text)
