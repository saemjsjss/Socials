"""Dates, read strictly: the dates users type, and the date stamps the portal prints.

User dates (parse_user_date, user_date_problem)
    "today", "yesterday", "day before yesterday", "tomorrow"; "8 Sep", "8th Sep", "8 September 2026",
    "the 8th of September", "Sep 8", "Sep 8, 2026", "September 8th 2026"; day-first numbers
    "08/09/2026", "8-9-2026", "8.9.26", "08/09" (this year); ISO "2026-09-08", "2026/09/08".
    Month names and their abbreviations count only as whole words next to a day number, so "may I"
    or "separately" is no month, and "8 Sep" is never found inside "18 Sep". A text that names no
    date, two different dates, or an impossible one ("31 Sep", "29 Feb 2026", "13/13/2026") gives
    None: never a stand-in day such as today.

Portal stamps (parse_stamp, stamp_on_day, parse_portal_date)
    The portal writes a payment verification as "Payment verified by NAME · 27 Sep, 17:19": a day
    and a month with no year. A stamp is read on whole tokens only, and a yearless stamp is taken to
    be within the last year, which is only safe for a day that has not come round again since:
    callers first ask yearless_day_problem(day, today) and say "not available" when it gives a reason
    (the rule the daily brief follows, src/bot/brief.py). A stamp that does carry a year must match it,
    and a student cannot have been verified before the day they applied.

Everything here is pure and offline; "today" is the day in settings.REPORT_TIMEZONE (local_today).
"""
import re
from datetime import date, datetime, timedelta
from typing import List, NamedTuple, Optional, Tuple
from zoneinfo import ZoneInfo

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December")
# Longest first, so "september" is never read as "sep" + "tember".
_MONTH = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + ")"
_ORD = r"(?:st|nd|rd|th)?"
_YEAR_AFTER_MONTH = rf"(?:,?\s*(?P<{{name}}>\d+)(?![\d:])(?!\s*(?:of\s+)?{_MONTH}\b))?"

_USER_DATE_RE = re.compile(
    # 2026-09-08, 2026/09/08
    r"(?<![\w/.-])(?P<iy>\d{4})[-/.](?P<im>\d{1,2})[-/.](?P<id>\d{1,2})(?![\w/.:-])"
    # 08/09/2026, 8-9-2026, 8.9.26 (day first)
    r"|(?<![\w/.:-])(?P<nd>\d{1,2})[-/.](?P<nm>\d{1,2})[-/.](?P<ny>\d{4}|\d{2})(?![\w/.:-])"
    # 08/09 (day first, no year; a slash only, so "5.5" and "1-2" are no dates)
    r"|(?<![\w/.:-])(?P<sd>\d{1,2})/(?P<sm>\d{1,2})(?![\w/.:-])"
    # 8 Sep, 8th of September 2026, 8Sep
    rf"|(?<![\w/.:-])(?P<dd>\d{{1,3}}){_ORD}\s*(?:of\s+)?(?P<dm>{_MONTH})\b\.?"
    + _YEAR_AFTER_MONTH.format(name="dy") +
    # Sep 8, Sep 8th 2026, September 8, 2026
    rf"|\b(?P<mm>{_MONTH})\b\.?\s*(?P<md>\d{{1,3}}){_ORD}(?![\d:])(?![a-z])"
    + _YEAR_AFTER_MONTH.format(name="my") +
    # the relative days
    r"|(?P<dby>\bday\s+before\s+yesterday\b)|(?P<yday>\byesterday'?s?\b)|(?P<tmrw>\btomorrow'?s?\b)"
    r"|(?P<tday>\b(?:today'?s?|tonight)\b)",
    re.I)

# Words that show the text meant a date the parser could not read ("in Sep", "last week", "12th").
# "may" is left out: "may I see..." is no date.
_HINT_MONTH = "(?:" + "|".join(m for m in sorted(MONTHS, key=len, reverse=True) if m != "may") + ")"
_DATE_HINT_RE = re.compile(
    rf"\d|\b{_HINT_MONTH}\b|\b(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?\b"
    r"|\b(?:weeks?|months?|years?|ago|last|previous|next|tomorrow|fortnight)\b",
    re.I)


class _Found(NamedTuple):
    text: str               # the words as typed ("31 Sep")
    day: Optional[date]     # None when they name no real day
    problem: Optional[str]  # why not ("September has 30 days")


def local_today() -> date:
    """Today in the bot's report time zone (settings.REPORT_TIMEZONE, Asia/Dhaka)."""
    from src.config import settings
    return datetime.now(ZoneInfo(settings.REPORT_TIMEZONE)).date()


def _days_in(month: int, year: Optional[int] = None) -> int:
    if month == 2:
        return 29 if year is None or (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def _year(text: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    """A typed year -> (year, None), or (None, why) for "202" or "12345"; (None, None) when absent."""
    if not text:
        return None, None
    if len(text) == 2:
        return 2000 + int(text), None
    if len(text) == 4 and 1900 <= int(text) <= 2100:
        return int(text), None
    return None, f"“{text}” is not a year"


def _make(day: int, month: int, year: Optional[int], today: date, prefer_past: bool,
          words: str) -> _Found:
    """One typed day, month and (maybe) year -> the date, or why there is none."""
    if not 1 <= month <= 12:
        return _Found(words, None, f"there is no month {month}")

    def no_such_day(y: Optional[int]) -> Optional[str]:
        if 1 <= day <= _days_in(month, y):
            return None
        if day < 1:
            return f"there is no day {day}"
        return f"{MONTH_NAMES[month - 1]}{f' {y}' if y else ''} has {_days_in(month, y)} days"

    why = no_such_day(year)
    if why:
        return _Found(words, None, why)
    if year is None:
        year = today.year
        if prefer_past and (month, day) > (today.month, today.day):
            year -= 1                        # still to come this year: the one just gone
        why = no_such_day(year)              # 29 Feb in a year that has none
        if why:
            return _Found(words, None, why)
    return _Found(words, date(year, month, day), None)


def _scan(text: str, today: date, prefer_past: bool) -> List[_Found]:
    found = []
    for m in _USER_DATE_RE.finditer(text or ""):
        g = m.groupdict()
        words = m.group(0).strip()
        if g["iy"]:
            year, why = _year(g["iy"])
            found.append(_Found(words, None, why) if why else
                         _make(int(g["id"]), int(g["im"]), year, today, prefer_past, words))
        elif g["nd"]:
            year, why = _year(g["ny"])
            found.append(_Found(words, None, why) if why else
                         _make(int(g["nd"]), int(g["nm"]), year, today, prefer_past, words))
        elif g["sd"]:
            found.append(_make(int(g["sd"]), int(g["sm"]), None, today, prefer_past, words))
        elif g["dd"] or g["md"]:
            day_text, month_word, year_text = ((g["dd"], g["dm"], g["dy"]) if g["dd"] else (g["md"], g["mm"], g["my"]))
            year, why = _year(year_text)
            found.append(_Found(words, None, why) if why else
                         _make(int(day_text), MONTHS[month_word.lower().rstrip(".")], year, today,
                               prefer_past, words))
        else:
            back = 2 if g["dby"] else 1 if g["yday"] else -1 if g["tmrw"] else 0
            found.append(_Found(words, today - timedelta(days=back), None))
    return found


def parse_user_date(text: str, today: Optional[date] = None, *, prefer_past: bool = False) -> Optional[date]:
    """The one calendar date `text` names (see the module docstring for the forms read), or None.

    None when the text names no date, two different dates, or an impossible one: never today or any
    other stand-in. A date typed without a year is in today's year; with prefer_past, a day still to
    come this year is last year's instead (on 5 Jan, "27 Dec" is the 27 Dec just gone). `today`
    defaults to local_today()."""
    today = today or local_today()
    found = _scan(text, today, prefer_past)
    if not found or any(f.day is None for f in found):
        return None
    days = {f.day for f in found}
    return days.pop() if len(days) == 1 else None


def user_date_problem(text: str, today: Optional[date] = None, *, prefer_past: bool = False) -> Optional[str]:
    """Why parse_user_date(text) gives None, in plain words for a reply ("31 Sep: September has 30
    days"), or None when it reads a date."""
    today = today or local_today()
    found = _scan(text, today, prefer_past)
    bad = [f for f in found if f.day is None]
    if bad:
        return f"{bad[0].text}: {bad[0].problem}"
    if len({f.day for f in found}) > 1:
        return "it names more than one date (" + ", ".join(f.text for f in found) + ")"
    if not found:
        if re.search(rf"\b{_HINT_MONTH}\b", text or "", re.I):
            return "it names a month but no day of it"
        if re.search(r"\d", text or ""):
            return "there is no month in it"
        return "there is no date in it"
    return None


def has_date_hint(text: str) -> bool:
    """Whether the text has anything date-like (a digit, a month or weekday name, "last week"...),
    so a text parse_user_date cannot read was meant as a date and deserves an error, not today."""
    return bool(_DATE_HINT_RE.search(text or ""))


# --------------------------------------------------------------------------- portal stamps

_STAMP_RE = re.compile(
    rf"(?<![\w/.:-])(?P<d>\d{{1,2}})\s+(?P<m>{_MONTH})\b\.?(?:,?\s+(?P<y>\d{{4}})(?![\d:]))?(?:,?\s+(?P<t>\d{{1,2}}:\d{{2}}))?",
    re.I)


class Stamp(NamedTuple):
    day: int
    month: int
    year: Optional[int]     # None: the portal left it out ("27 Sep, 17:19")
    time: str               # "17:19", or ""
    text: str               # the stamp without its year, as the bot shows it: "27 Sep, 17:19"


def parse_stamp(text: str) -> Optional[Stamp]:
    """The first "DD Mon[ YYYY][, HH:MM]" in a portal text, read on whole tokens ("8 Sep" is not
    found in "18 Sep"), or None when there is none or it names an impossible day ("31 Sep")."""
    m = _STAMP_RE.search(text or "")
    if not m:
        return None
    day, month = int(m.group("d")), MONTHS[m.group("m").lower().rstrip(".")]
    year = int(m.group("y")) if m.group("y") else None
    if not 1 <= day <= _days_in(month, year):
        return None
    shown = f"{m.group('d')} {m.group('m')}" + (f", {m.group('t')}" if m.group("t") else "")
    return Stamp(day, month, year, m.group("t") or "", shown)


def parse_portal_date(text: str) -> Optional[date]:
    """The first full "DD Mon YYYY" date in a portal text ("Applied On 27 Sep 2026, 17:16",
    "28 Sep 2026"), or None when there is none (a stamp without a year is no full date)."""
    for m in _STAMP_RE.finditer(text or ""):
        if m.group("y"):
            try:
                return date(int(m.group("y")), MONTHS[m.group("m").lower().rstrip(".")], int(m.group("d")))
            except ValueError:
                return None
    return None


def stamp_on_day(stamp, day: date, applied: Optional[date] = None) -> bool:
    """Whether a portal stamp (a Stamp, or text such as "27 Sep, 17:19") is on `day`.

    Day and month must be the day's own; a stamp with a year must have the day's year; a stamp
    without one is read as within the last year, so the caller must first have checked
    yearless_day_problem(day, today) is None. A student who applied after `day` cannot have been
    verified on it (the stamp is then another year's)."""
    s = stamp if isinstance(stamp, Stamp) else parse_stamp(stamp)
    if s is None or (s.day, s.month) != (day.day, day.month):
        return False
    if s.year is not None:
        return s.year == day.year
    return applied is None or applied <= day


def yearless_day_problem(day: date, today: date) -> Optional[str]:
    """Why a yearless portal stamp cannot tell whether something happened on `day`, or None when
    it can. The portal writes verification times without a year ("27 Sep, 17:19"), so a day whose
    day and month have come round again since cannot be told apart from that later one; a day
    still to come cannot have happened yet."""
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
