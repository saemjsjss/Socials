"""Questions typed (or spoken) to the bot in plain words: which answer they ask for, and the
answers read live from the portal that no menu command gives.

classify(text) -> Route
    Which answer a question asks for, read on whole words ("across" is no "cross", "shipping" no
    "pin", "Janan" no January, "summary" no March) and with real dates: one day through
    src.dates.parse_user_date, a span of days ("this week", "the next 7 days", "in October")
    through date_window. telegram_bot.handle_natural_language_message runs the route, and Jennie's
    voice notes (src/bot/voice.py) reach the same routes.

The answers built here, each from read-only GETs made when asked, every figure with its source:
    pending payments              students.php?status=pending, every page: who, and the portal's count
    window applications in review window_applications.php?status=under_review, and the dashboard tile
    the dashboard's figures       index.php: its tiles and its cards (At a glance, Needs attention,
                                  Application pipeline, Applications by program, Top universities)
    students per intake           students.php, every page, counted by intake (and program)
    students who applied on days  students.php, every page, counted by their Applied date
    calendar questions            calendar.php: today's reminders, the 45-day timeline and the
                                  month's event list, filtered by real dates (answer_calendar)
A question none of these fits gets the dashboard facts whose whole label it names, or, failing
that, the ones the local LLM picks (ollama_client.answer_agent_query): shown word for word, so no
figure is ever the LLM's own. Anything else gets cant_answer(): "I can't answer that from the
portal yet" and the commands that can. A portal that cannot be read is said plainly
(portal_error_reply), never a 0 or an empty list. Pending payments and window applications under
review are always two separate figures, never added together (guardrail 2).
"""
import asyncio
import json
import logging
import re
from collections import Counter
from datetime import date, timedelta
from typing import Dict, List, NamedTuple, Optional, Tuple

from bs4 import BeautifulSoup

from src.dates import has_date_hint, local_today, parse_user_date, user_date_problem

logger = logging.getLogger("hangeul.ask")

MAX_NAMES_LISTED = 30           # pending-payment students listed by name in one reply
MAX_CALENDAR_LISTED = 25        # calendar items listed in one reply


# --------------------------------------------------------------------------- words

def _re(words: str) -> "re.Pattern":
    """Whole words only: r"\\b(?:words)\\b", case-insensitive."""
    return re.compile(r"\b(?:" + words + r")\b", re.I)


_HELLO_RE = re.compile(
    r"^\W*(?:hi+|hello|hey|hiya|salam|assalamu?\s*alaikum|good\s+(?:morning|afternoon|evening|night)|thanks?|"
    r"thank\s+you|thx|ok(?:ay)?|cool|great|nice|bye)(?:\s+(?:jennie|bot|there|so\s+much|a\s+lot))?\W*$", re.I)
_PIN_RE = _re(r"pp\s*pin|pin(?:ned)?|pin\s+it|cheat\s*-?\s*sheet|command\s+list|list\s+of\s+commands|all\s+commands"
              r"|commands|menu")
_REPORT_RE = _re(r"reports?|brief(?:ing)?|summary|summari[sz]e|overview|recap|round-?up")
_CONSULT_RE = _re(r"consult(?:ation|ations|ancy|ancies)?|inquir(?:y|ies)|enquir(?:y|ies)|leads?|counsell?ors?"
                  r"|consultants?")
_CROSS_RE = _re(r"cross[\s-]*check(?:ed|ing|s)?|crosscheck(?:ed|ing|s)?|audit(?:ed|ing|s)?")
_CROSS_FIELD_RE = _re(r"father'?s?|mother'?s?|address(?:es)?|parents?'?|dob|date\s+of\s+birth")
_CHECK_RE = _re(r"check(?:ed|ing|s)?")
_PASSPORT_RE = _re(r"passports?|mrz")
_VERIFY_RE = _re(r"verif(?:y|ied|ies|ication|ications)")
_PAY_RE = _re(r"pay(?:s|ing|ment|ments|ed)?|paid")
_PENDING_WORD_RE = _re(r"pending|waiting|awaiting|outstanding|due|unconfirmed|approval")
_UNPAID_RE = _re(r"unpaid|not\s+(?:yet\s+)?paid|payment\s+approvals?")
_DOCS_RE = _re(r"docs?|documents?|papers?|files?|uploads?")
_DOC_STATE_RE = _re(r"review(?:s|ed|ing)?|verif\w*|waiting|pending|approv\w*|reject\w*|check(?:ed|ing)?|unverified"
                    r"|queue|to\s+verify")
_UNDER_REVIEW_RE = _re(r"under\s+review|in\s+review|being\s+reviewed|reviewing")
_APPLICATION_RE = _re(r"app(?:lication)?s?")
_WINDOW_APP_RE = _re(r"window\s+app(?:lication)?s?|admission\s+window\s+app(?:lication)?s?")
_MISSING_RE = _re(r"missing|incomplete")
_STAGE_RE = _re(r"stages?")
_PIPELINE_RE = _re(r"pipeline|funnel")
_ADMIT_RE = _re(r"admit(?:ted|s)?")
_CALENDAR_RE = _re(r"calendar|events?|deadlines?|due|dhl|shipping|shipments?|ship|courier|reminders?|schedule[sd]?"
                   r"|closing|closes|opening|application\s+(?:windows?|periods?)|open\s+for\s+applications?"
                   r"|accepting\s+applications?|(?:admissions?|applications?)\s+(?:is\s+|are\s+)?open")
_OPEN_WINDOWS_RE = _re(r"(?:open|active|draft)\s+(?:admission\s+)?windows?")
_VISA_RE = _re(r"visas?")
_INTAKE_WORD_RE = _re(r"intakes?|batch(?:es)?")
_MONTH_WORDS = (r"january|february|march|april|may|june|july|august|september|october|november|december"
                r"|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec")
_INTAKE_RE = re.compile(rf"\b(?P<month>{_MONTH_WORDS})\.?\s*(?:,\s*)?(?P<year>20\d\d)\b(?!\s*[-/.]\d)", re.I)
_PROGRAM_RE = _re(r"programs?|programmes?|courses?|klp|eap|bachelor'?s?|masters?|master'?s|degrees?|phd"
                  r"|language\s+program")
_UNIVERSITY_RE = _re(r"universit(?:y|ies)|unis?|colleges?")
_STUDENTS_RE = _re(r"students?|applicants?|people|enrol(?:l)?ments?|admissions?")
_APPLIED_RE = _re(r"registered|registrations?|registering|sign(?:ed)?[\s-]*ups?|signups?|joined|enrolled"
                  r"|new\s+(?:students?|applicants?|applications?)|applied|applications?\s+(?:received|came)")
_ATTENTION_RE = _re(r"urgent|alerts?|attention|to[\s-]*dos?|action\s+items?|needs?\s+attention")
_STATS_RE = _re(r"stats|statistics|dashboard|figures|kpis?|metrics|numbers")
_REJECT_RE = _re(r"reject\w*")
_APPROVE_RE = _re(r"approv\w*")
_MOST_RE = _re(r"most|top|biggest|largest|popular|highest|leading|best")
# Performance (/performance_today, /performance_month: the portal's Consultant Performance page):
# "performance today", "today's performance", "how did the team do today", "monthly performance",
# "team activity", "who is the top performer this month". The words that name performance itself,
# as the owner writes them too ("performence this month", "perfomance today", "performances"),
# whole words only, so "outperform" and "performing arts" are none of them.
_PERFORMANCE_WORDS = (r"perform[ae]nces?|perfom[ae]nces?|performaces?|perfromances?|preformances?"
                      r"|productivity|leader[\s-]?boards?|performers?")
_PERFORMANCE_RE = _re(_PERFORMANCE_WORDS +
                      r"|how\s+(?:did|does|do|has|have|is|are|was|were)\s+(?:the\s+|our\s+|my\s+)?(?:whole\s+)?"
                      r"(?:team|staff|everyone|everybody|counsell?ors?|consultants?)\s+"
                      r"(?:do|done|doing|did|perform(?:ed|ing)?|go|going|gone)"
                      r"|(?:team|staff)(?:'s)?\s+(?:activity|stats|statistics|report|summary|scores?|results?)")
# A question that says "performance" (or "perform", "leaderboard", "top performer") in so many
# words is about the Consultant Performance page even for another day ("consultant performance
# yesterday"): never that day's consultations, whose report is not the page.
_PERFORMANCE_WORD_RE = _re(_PERFORMANCE_WORDS + r"|perform(?:s|ed|ing)?")
_OTHER_MONTH_RE = _re(r"(?:last|previous|past|next|coming|following)\s+(?:\w+\s+)?months?(?:'s)?|months")
_THIS_MONTH_RE = _re(r"monthly|month(?:'s)?|mtd")
# Periods the Consultant Performance page has besides Today and This Month, named without a date
# ("all time performance", "overall leaderboard", "yearly", "ytd", "this year's", "custom range").
_OTHER_PERIOD_RE = _re(r"all[\s-]*time|overall|lifetime|ever|in\s+total|altogether"
                       r"|ytd|(?:(?:this|the|current)\s+)?year[\s-]+to[\s-]+date"
                       r"|(?:last|previous|past|next|coming|following)\s+years?(?:'s)?|(?:a\s+)?years?\s+(?:ago|back)"
                       r"|yearly|annual(?:ly)?|(?:(?:this|the|current|a)\s+)?year(?:'s)?|quarter(?:ly)?"
                       r"|custom(?:\s+range)?|range")
# A week ("this week's performance", "weekly leaderboard", "last 2 weeks", "wtd"): the page's This Week.
_WEEK_RE = _re(r"(?:(?:this|current|last|previous|past|next)\s+)?(?:weekly|weeks?(?:'s)?|fortnight(?:ly)?)|wtd")
# The period words as the reply names them back ("ever", "overall" -> "all time"); any other
# words ("yearly", "last week", "custom range") are said as they were written.
_PERIOD_NAMES = ((re.compile(r"all time|overall|lifetime|ever|in total|altogether"), "all time"),
                 (re.compile(r"(?:(?:this|the|current) )?(?:ytd|year to date)"), "the year to date"),
                 (re.compile(r"(?:this|the|current) year|year"), "this year"),
                 (re.compile(r"yearly|annual(?:ly)?"), "yearly figures"),
                 (re.compile(r"quarter(?:ly)?"), "a quarter"),
                 (re.compile(r"weekly"), "weekly figures"),
                 (re.compile(r"fortnight(?:ly)?"), "a fortnight"),
                 (re.compile(r"wtd"), "the week to date"),
                 (re.compile(r"custom(?: range)?|range"), "a custom range"))
# "this months performance": the owner writes without apostrophes ("todays", "inquires"), so "this
# months" and "current months" are this month's, never "another month".
_THIS_MONTHS_RE = re.compile(r"\b(this|current)\s+months\b")
# The words that say "this month" ("the month of"): taken out to see which month, if another one,
# the words name ("performance for the month of august" asks about August).
_THE_MONTH_RE = re.compile(r"\b(?:this|the|current)\s+month(?:'s)?(?:\s+of)?\b")
# A year on its own ("month performance 2025"), not inside an id or a date ("HNG-2025-001", "2025-09-01").
_YEAR_WORD_RE = re.compile(r"(?<![\w/.:-])(?:19|20)\d\d(?![\w/:-]|\.\d)")
# Another year in words ("this month last year", "a year ago").
_OTHER_YEAR_RE = re.compile(r"\b(?:(?:last|previous|past|next|coming|following)\s+years?|years?\s+ago"
                            r"|a\s+year\s+(?:ago|back))\b")
# Subjects the Consultant Performance page does not show (it shows consultancies, files opened,
# conversion and docs ready, per consultant): a question that names one of them is that subject's,
# even when it also says "how is the team doing" or "performance" ("how is the team doing with
# pending payments", "academic performance of the March 2027 intake").
_CROSS_WORD_RE = _re(r"cross[\s-]*check(?:ed|ing|s)?|crosscheck(?:ed|ing|s)?")
_CALENDAR_TOPIC_RE = _re(r"calendar|events?|deadlines?|dhl|shipping|shipments?|courier|reminders?")

# The words any question may have around what it asks about.
_FILLER = set("""
a an the and or of in on at to for from by with about into is are was were be been being am do does did done
have has had we our us you your me my i it its this that these those there here what whats which who whom
whose how many much number numbers count counts total totals overall altogether all so far currently current
now right please pls plz show give get got tell list let lets know see find any some every each per across
whole entire student students applicant applicants people person record records system portal hangeul office
are there in-all till until up yet still just can could would will shall should may might jennie bot hey hi
""".split())

_PROGRAM_KEYS = (("klp", re.compile(r"\bklp\b|\bkorean\s+language\b|\blanguage\s+program", re.I), "KLP"),
                 ("eap", re.compile(r"\beap\b|\benglish\s+for\s+academic", re.I), "EAP"),
                 ("bachelor", re.compile(r"\bbachelor'?s?\b|\bundergrad", re.I), "BACHELOR"),
                 ("master", re.compile(r"\bmasters?\b|\bmaster'?s\b|\bpostgrad", re.I), "MASTER"),
                 ("phd", re.compile(r"\bphd\b|\bdoctor(?:ate|al)\b", re.I), "PHD"))
_PROGRAM_NAMES = {"klp": "KLP", "eap": "EAP", "bachelor": "Bachelor's", "master": "Master's", "phd": "PhD"}

_STAGES = ("Application Received", "Payment Verified", "Documents Under Review", "Documents Verified",
           "University Applied", "Admission & Tuition", "VIN Application", "Embassy Submission", "Visa Result",
           "Admitted / Completed")
# Stage names that can only mean the stage (the others, "payment verified", "admitted", need the
# word "stage" beside them).
_STAGE_ONLY = ("University Applied", "Admission & Tuition", "VIN Application", "Embassy Submission", "Visa Result",
               "Application Received", "Documents Under Review")


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", (text or "").lower())


def _leftover(text: str, *drop: "re.Pattern") -> List[str]:
    """The words of `text` that are neither filler nor matched by any of `drop`."""
    for pattern in drop:
        text = pattern.sub(" ", text)
    return [w for w in _words(text) if w not in _FILLER and w.rstrip("s") not in _FILLER]


# Numbers that are part of a date ("12 Sep", "2026-09-12"), not a student id.
_DAY_NUMBERS_RE = re.compile(rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTH_WORDS})\b\.?(?:\s+\d{{4}})?"
                             rf"|\b(?:{_MONTH_WORDS})\b\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?"
                             r"|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}(?:[-/.]\d{2,4})?", re.I)


def _stage_named(low: str) -> List[str]:
    """The pipeline stages the words name ("visa result", "the payment verified stage"; "applied to
    a university" is University Applied)."""
    found = []
    for stage in _STAGES:
        words = r"\s*(?:&|and)?\s*".join(re.escape(w) for w in re.findall(r"[a-z]+", stage.lower()))
        if re.search(rf"\b{words}\b", low):
            if stage in _STAGE_ONLY or _STAGE_RE.search(low):
                found.append(stage)
    if "University Applied" not in found and re.search(r"\bapplied\s+(?:to|for|at)\s+(?:a\s+|the\s+)?universit", low):
        found.append("University Applied")
    return found


def _program_filter(low: str) -> Optional[Tuple[str, str]]:
    """(key, what a program name contains) for a program the words name, or None."""
    for key, pattern, needle in _PROGRAM_KEYS:
        if pattern.search(low):
            return key, needle
    return None


# --------------------------------------------------------------------------- date windows

class Window(NamedTuple):
    first: date
    last: Optional[date]    # None: open-ended ("coming up": from `first` on, as far as the page lists)
    label: str              # "this week", "the next 7 days", "October 2026", "today"...

    def span(self) -> str:
        """'Mon 28 Sep – Sun 04 Oct 2026', 'Mon 28 Sep 2026', 'from Mon 28 Sep 2026 on'."""
        if self.last is None:
            return f"from {self.first:%a %d %b %Y} on"
        if self.first == self.last:
            return f"{self.first:%a %d %b %Y}"
        head = f"{self.first:%a %d %b}" + (f" {self.first:%Y}" if self.first.year != self.last.year else "")
        return f"{head} – {self.last:%a %d %b %Y}"

    def title(self) -> str:
        """'this week (Mon 28 Sep – Sun 04 Oct 2026)' or 'Mon 12 Oct 2026'."""
        span = self.span()
        return span if self.label == span else f"{self.label} ({span})"


_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
                 "fifteen": 15, "twenty": 20, "thirty": 30, "few": 3, "couple": 2}
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTH_NUMBER = {m: i for i, names in enumerate(
    (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
     ("dec", "december")), 1) for m in names}
_RANGE_RE = re.compile(r"^(?:.*?\b(?:from|between)\s+)?(?P<a>.+?)\s*(?:\b(?:to|until|till|through|thru|and)\b|–|—|\s-\s)"
                       r"\s*(?P<b>.+)$", re.I)
_SPAN_RE = re.compile(r"\b(?P<dir>next|coming|upcoming|following|past|last|previous)\s+(?P<n>\d{1,3}|"
                      + "|".join(_NUMBER_WORDS) + r")\s+(?P<unit>days?|weeks?)\b", re.I)
_WEEKDAY_RE = re.compile(r"\b(?:(?P<which>this|next|last|coming)\s+)?(?P<day>" + "|".join(_WEEKDAYS) + r")\b", re.I)
_MONTH_ALONE_RE = re.compile(rf"\b(?:(?P<which>this|next|last)\s+)?(?P<month>{_MONTH_WORDS})\b\.?(?:\s+(?P<year>\d{{4}}))?",
                             re.I)


def _month_end(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _day_label(d: date, today: date) -> str:
    return {0: "today", -1: "yesterday", 1: "tomorrow"}.get((d - today).days, f"{d:%a %d %b %Y}")


def date_window(text: str, today: Optional[date] = None, *, forward: bool = True, months: bool = True
                ) -> Tuple[Optional[Window], Optional[str]]:
    """The days `text` asks about: (Window, None); (None, None) when it names none; (None, why)
    when it names something date-like that cannot be read ("31 Sep", "the 45th").

    Read: one date (src.dates.parse_user_date: "today", "8 Oct", "2026-10-08"...), a range
    ("from 1 Oct to 10 Oct", "between today and 5 Oct"), "this / next / last week", "this weekend",
    "this / next / last month", "the next / past N days (weeks)", a weekday ("on Friday": the next
    one), a month ("in October", "October 2026"; not with months=False, where a month without a
    day is a date that cannot be read), and "coming up" / "upcoming" / "soon" (from today on).
    `forward` (questions about what is still to come, such as deadlines) makes "this week" and
    "this month" run from today to their end, and a month alone the coming one; otherwise they run
    from their start to today, and a month alone is the latest one not after today."""
    today = today or local_today()
    low = re.sub(r"\s+", " ", (text or "").lower().replace("’", "'")).strip()
    prefer_past = not forward

    # A range: two dates with a range word between them.
    m = _RANGE_RE.match(low)
    if m and re.search(r"\b(?:from|between)\b|\b(?:to|until|till|through|thru)\b|–|—|\s-\s", low):
        a = parse_user_date(m.group("a"), today, prefer_past=prefer_past)
        b = parse_user_date(m.group("b"), today, prefer_past=prefer_past)
        if a and b and prefer_past and b < a:
            # A range read past-facing stays in one year: on 29 Sep, "1 Sep to 30 Sep" is 1-30 Sep
            # 2026, not 30 Sep 2025 - 1 Sep 2026 (the end alone read as the one just gone).
            ahead = parse_user_date(m.group("b"), today)
            if ahead and ahead >= a:
                b = ahead
        if a and b:
            first, last = min(a, b), max(a, b)
            return Window(first, last, f"{first:%d %b} to {last:%d %b %Y}"), None

    day = parse_user_date(low, today, prefer_past=prefer_past)
    if day:
        return Window(day, day, _day_label(day, today)), None
    problem = user_date_problem(low, today, prefer_past=prefer_past)
    if problem and (":" in problem or problem.startswith("it names more than one")):
        return None, problem                    # "31 Sep: September has 30 days"

    monday = today - timedelta(days=today.weekday())
    if re.search(r"\b(?:this\s+)?weekend\b", low):
        sat = monday + timedelta(days=5)
        return Window(max(sat, today) if forward else sat, sat + timedelta(days=1), "this weekend"), None
    if re.search(r"\bnext\s+week\b", low):
        return Window(monday + timedelta(days=7), monday + timedelta(days=13), "next week"), None
    if re.search(r"\b(?:last|previous|past)\s+week\b", low):
        return Window(monday - timedelta(days=7), monday - timedelta(days=1), "last week"), None
    if re.search(r"\b(?:this|the|current)\s+week\b|\bweek\b(?!s)", low) and not _SPAN_RE.search(low):
        sunday = monday + timedelta(days=6)
        return (Window(today, sunday, "this week") if forward else Window(monday, today, "this week")), None
    first_of_month = today.replace(day=1)
    if re.search(r"\bnext\s+month\b", low):
        start = _month_end(today) + timedelta(days=1)
        return Window(start, _month_end(start), f"next month, {start:%B %Y}"), None
    if re.search(r"\b(?:last|previous|past)\s+month\b", low):
        end = first_of_month - timedelta(days=1)
        return Window(end.replace(day=1), end, f"last month, {end:%B %Y}"), None
    if re.search(r"\b(?:this|the|current)\s+month\b", low):
        return (Window(today, _month_end(today), "this month") if forward
                else Window(first_of_month, today, "this month")), None
    m = _SPAN_RE.search(low)
    if m:
        n = int(m.group("n")) if m.group("n").isdigit() else _NUMBER_WORDS[m.group("n").lower()]
        days = n * (7 if m.group("unit").startswith("week") else 1)
        if not 1 <= days <= 400:
            return None, f"“{m.group(0)}” is too long a span"
        unit = m.group("unit").rstrip("s") + ("" if n == 1 else "s")
        if m.group("dir") in ("past", "last", "previous"):
            return Window(today - timedelta(days=days - 1), today, f"the past {n} {unit}"), None
        return Window(today, today + timedelta(days=days - 1), f"the next {n} {unit}"), None
    if re.search(r"\b(?:coming\s+up|upcoming|soon|ahead|from\s+now\s+on|in\s+the\s+future|future|next)\b", low):
        return Window(today, None, "coming up"), None
    m = _WEEKDAY_RE.search(low)
    if m:
        target = _WEEKDAYS.index(m.group("day").lower())
        ahead = (target - today.weekday()) % 7
        if m.group("which") == "last" or (not forward and m.group("which") != "next"):
            back = (today.weekday() - target) % 7 or 7
            day = today - timedelta(days=back)
        else:
            if m.group("which") == "next" and ahead == 0:
                ahead = 7
            day = today + timedelta(days=ahead)
        return Window(day, day, _day_label(day, today)), None
    m = _MONTH_ALONE_RE.search(low) if months else None
    if m and (m.group("month").lower() != "may" or m.group("year") or re.search(r"\b(?:in|during|for)\s+may\b", low)):
        month = _MONTH_NUMBER[m.group("month").lower()]
        if m.group("year"):
            year = int(m.group("year"))
        else:
            year = today.year
            if m.group("which") == "next" or (forward and month < today.month):
                year += 1 if month <= today.month else 0
            elif m.group("which") == "last" or (not forward and month > today.month):
                year -= 1
        start = date(year, month, 1)
        return Window(start, _month_end(start), f"{start:%B %Y}"), None
    if has_date_hint(low):
        return None, problem or "it is not a date"
    return None, None


# --------------------------------------------------------------------------- routes

class Route(NamedTuple):
    kind: str                           # what answers the question (see classify)
    day: Optional[date] = None          # the one day it names
    window: Optional[Window] = None     # or the span of days it names
    topic: str = ""                     # which of the dashboard's figures ("program", "documents"...)
    words: str = ""                     # what is left to search for (admitted, a program, an intake)
    problem: Optional[str] = None       # why a date-like part of it cannot be read


# Kinds answered one day at a time.
ONE_DAY_KINDS = ("inquiries", "verified", "passports")


def _when(low: str, today: date) -> Tuple[Optional[date], Optional[Window], Optional[str]]:
    """(the one day, or a span of days, or why a date-like part cannot be read) for a question about
    the past (a day without a year is the latest one not after today). A month without a day
    ("verified in Sep") is a date that cannot be read here, as the /verified commands have it."""
    window, problem = date_window(low, today, forward=False, months=False)
    if window is not None and window.first == window.last:
        return window.first, None, None
    if window is not None and window.last is None:
        return None, None, None                 # "upcoming" means nothing for a day gone by
    return None, window, problem


def performance_route(text: str, today: Optional[date] = None) -> Route:
    """Which view of the portal's Consultant Performance page the words ask for: topic "today" (no
    day named, or today) or "month" (this month: "this month", "monthly", "month's", the month's
    own name). Anything else, another day or span or month, or another period of the page ("all
    time", "overall", "weekly", "yearly", "ytd", "this year", "custom range"), has no topic, with
    the `day`, `window` or `words` it named (a period by a readable name: "overall" is "all time"),
    or the `problem` of a date that cannot be read: it is answered with
    performance_other_reply, never with a stand-in period. "This month" is given only when the
    words name no other month and no other year ("performance for the month of august" and
    "month performance 2025" ask about another month)."""
    today = today or local_today()
    low = re.sub(r"\s+", " ", (text or "").lower().replace("’", "'")).strip()
    low = _THIS_MONTHS_RE.sub(r"\1 month's", low)
    if _OTHER_MONTH_RE.search(low):
        window, _ = date_window(low, today, forward=False)
        return Route("performance", window=window, words="" if window else "another month")
    week = _WEEK_RE.search(low)
    if week:
        # The page's This Week (or another week) is not Today, even on a Monday, when "this week"
        # is one day so far.
        window, _ = date_window(low, today, forward=False)
        span = window if window is not None and window.first != window.last else None
        return Route("performance", window=span, words="" if span else _period_name(week.group(0)))
    window, problem = date_window(low, today, forward=False)
    if (window is not None and window.first == today.replace(day=1) and window.last is not None
            and window.last >= today and (window.first != window.last or _THIS_MONTH_RE.search(low))):
        # This month so far ("this month", "September", "1 Sep to 30 Sep"; on the 1st, "this month"
        # is that one day): unless the words also name another month or year.
        return _this_month_route(low, today, window)
    if window is not None and window.first == window.last:
        return Route("performance", day=window.first, topic="today" if window.first == today else "")
    if window is not None:
        return Route("performance", window=window)
    # "month's performance", "month to date": the word "month" is the only date-like part.
    named_date = problem and (":" in problem or problem.startswith("it names"))
    if _THIS_MONTH_RE.search(low) and not named_date:
        return _this_month_route(low, today)
    other = _OTHER_PERIOD_RE.search(low)
    if other and not named_date:
        # The page's other periods ("all time performance", "ytd", "this year's performance"): not
        # today's, and no date to be read in them ("year" alone is no date that cannot be read).
        return Route("performance", words=_period_name(other.group(0)))
    year = _YEAR_WORD_RE.search(low)
    if year and not named_date:
        return Route("performance", words=year.group(0))            # "performance 2025": a year
    if problem:
        return Route("performance", problem=problem)
    return Route("performance", topic="today")


def _period_name(said: str) -> str:
    """The period the words named, as the reply says it back: "ever", "overall", "lifetime" ->
    "all time"; "ytd" -> "the year to date"; "this year's" -> "this year"; "wtd" -> "the week to
    date"; "custom" -> "a custom range"; anything else as written ("yearly", "last week")."""
    key = re.sub(r"[\s-]+", " ", said.lower().replace("'s", "")).strip()
    return next((name for pattern, name in _PERIOD_NAMES if pattern.fullmatch(key)), key)


def _other_period_named(low: str, today: date) -> str:
    """The words of `low` that name a month or a year other than today's ("august", "september
    2025", "2025", "last year"), joined by ", ", or "" when it names none. "May" is a month only as
    "May 2026", "in / during / for May" or "the month of May" (else it is a word, or a name)."""
    named, taken = [], []
    for m in _MONTH_ALONE_RE.finditer(low):
        word = m.group("month").lower()
        if word == "may" and not (m.group("year") or re.search(r"\b(?:in|during|for|month\s+of)\s+$",
                                                                 low[:m.start()])):
            continue
        taken.append(m.span())
        if _MONTH_NUMBER[word] != today.month or (m.group("year") and int(m.group("year")) != today.year):
            named.append(m.group(0).strip())
    for m in _YEAR_WORD_RE.finditer(low):
        if int(m.group(0)) != today.year and not any(a <= m.start() < b for a, b in taken):
            named.append(m.group(0))
    named += [m.group(0) for m in _OTHER_YEAR_RE.finditer(low)]
    return ", ".join(dict.fromkeys(named))


def _this_month_route(low: str, today: date, window: Optional[Window] = None) -> Route:
    """Topic "month" for words that ask about this month, unless they also name another month or
    year: then the day or span those words name without "this / the month", else the words
    themselves, with no topic, so the report is never given for a month that was not asked about
    ("performance for the month of august" is August; "performance this month 2025" is "2025")."""
    other = _other_period_named(low, today)
    if not other:
        return Route("performance", window=window, topic="month")
    asked, _ = date_window(_THE_MONTH_RE.sub(" ", low), today, forward=False)
    if asked is not None and asked.first == asked.last:
        return Route("performance", day=asked.first)
    if asked is not None and (asked.first != today.replace(day=1) or asked.last is None
                              or asked.last > _month_end(today)):
        return Route("performance", window=asked)
    return Route("performance", words=other)


def _names_another_topic(low: str) -> bool:
    """Whether the words name a subject the Consultant Performance page does not show (it shows
    consultancies, files opened, conversion and docs ready per consultant): pending payments, window
    applications, intakes, programs, universities, stages, documents, missing information,
    admitted students, visas, the calendar, passports, cross-checks or registrations. Such a
    question keeps that subject's own route even with "performance" or "how is the team doing" in
    it. "March 2027" alone is no intake here ("performance for September 2026" is a month)."""
    return bool(
        _UNPAID_RE.search(low) or (_PAY_RE.search(low) and _PENDING_WORD_RE.search(low))
        or _UNDER_REVIEW_RE.search(low) or _WINDOW_APP_RE.search(low) or _OPEN_WINDOWS_RE.search(low)
        or _INTAKE_WORD_RE.search(low) or _PROGRAM_RE.search(low) or _UNIVERSITY_RE.search(low)
        or _stage_named(low) or _STAGE_RE.search(low) or _PIPELINE_RE.search(low)
        or (_DOCS_RE.search(low) and (_DOC_STATE_RE.search(low) or _UNDER_REVIEW_RE.search(low)))
        or _MISSING_RE.search(low) or _ADMIT_RE.search(low) or _VISA_RE.search(low)
        or _CALENDAR_TOPIC_RE.search(low) or _PASSPORT_RE.search(low) or _CROSS_WORD_RE.search(low)
        or _CROSS_FIELD_RE.search(low) or _APPLIED_RE.search(low))


def performance_other_reply(route: Route) -> str:
    """For a performance question about another day, span, month or period (Telegram Markdown):
    what the two commands cover, and that the portal page itself offers the other periods. The
    bot never uses the page's Custom range form, so it reads nothing for them."""
    from src.bot.brief import esc
    if route.problem:
        asked = f" (I couldn't read the date there: {esc(route.problem)})"
    elif route.window is not None:
        asked = f", and you asked about {esc(route.window.title())}"
    elif route.day is not None:
        asked = f", and you asked about {route.day:%a %d %b %Y}"
    elif route.words:
        asked = f", and you asked about {esc(route.words)}"
    else:
        asked = ""
    return ("📈 /performance\\_today and /performance\\_month show the portal's Consultant Performance page "
            f"for *today* and for *this month*{asked}.\n"
            "The page itself (Leads › Performance, consult\\_performance.php) also offers This Week, "
            "All Time and a custom range: open it on the portal for those.")


def classify(text: str, today: Optional[date] = None) -> Route:
    """Which answer a typed (or spoken, in English) question asks for, on whole words and real
    dates. The kinds, in the order they are tried:

      hello          a greeting or thanks
      pin            the command cheat-sheet ("pin", "menu", "commands")
      performance    the portal's Consultant Performance page, today or this month (performance_route:
                     topic "today" or "month"; another day, span or period has no topic), unless the
                     words name a subject the page does not show (_names_another_topic: pending payments,
                     an intake...), or name another single day and consultations or verifications
                     without saying performance ("how did the counsellors do yesterday": that day's own
                     answer; "consultant performance yesterday" stays here)
      crosscheck     a cross-check: a day, a student, a range (window: "cross-check last week")
      passports      passport problems: the live passport cross-check for the day named
      pending        pending payments
      dashboard      a stage the words name (topic "pipeline"), then documents to review ("documents")
      inquiries      consultations on the day named
      verified       payments verified on the day named ("in total": the dashboard's Verified figure)
      missing        /missing;  dashboard "pipeline";  admitted /admitted;  stage /stage
      dashboard      "visa" (no visa figure: said so), then window_review, then the Accepted /
                     Submitted apps / Open and Draft windows tiles
      calendar       /calendar with the words (deadlines, DHL, events, their dates)
      intake         students per intake (words: the intake named, "MARCH 2027")
      applied        students who applied on a day or span ("this week" / "this month": the
                     dashboard's own At a glance figures)
      dashboard      "program", "university", "attention" (Needs attention), "total_students"
      report, stats  the brief for a day (/report); /stats
      unknown        none of these
    A dated kind carries the day it names (None: today), or the span (window), or why its date
    cannot be read (problem). Nothing here reads the portal."""
    today = today or local_today()
    low = re.sub(r"\s+", " ", (text or "").lower().replace("’", "'")).strip()
    if not low:
        return Route("unknown")
    if _HELLO_RE.match(low):
        return Route("hello")
    if low.startswith(("/report", "/brief")):
        return Route("report")
    if _PIN_RE.search(low):
        return Route("pin")
    if _PERFORMANCE_RE.search(low) and not _names_another_topic(low):
        route = performance_route(low, today)
        # "How did the counsellors do yesterday": another day's consultations (or payments
        # verified) have their own one-day answers, which name who handled each. Not when the
        # words say performance ("consultant performance yesterday", "consultant leaderboard on
        # Monday"): that is the page's, for a day its two commands do not cover.
        if (route.topic or route.day is None or _PERFORMANCE_WORD_RE.search(low)
                or not (_CONSULT_RE.search(low) or _VERIFY_RE.search(low))):
            return route

    if _CROSS_RE.search(low) or _CROSS_FIELD_RE.search(low) or (_CHECK_RE.search(low) and _VERIFY_RE.search(low)):
        window = None
        if not re.search(r"\b\d{2,5}\b", _DAY_NUMBERS_RE.sub(" ", low)):
            window = _when(low, today)[1]                   # "cross-check this week": the range
        return Route("crosscheck", window=window)
    if _PASSPORT_RE.search(low):
        day, window, problem = _when(low, today)
        return Route("passports", day, window, problem=problem)
    if _UNPAID_RE.search(low) or (_PAY_RE.search(low) and _PENDING_WORD_RE.search(low)):
        return Route("pending")
    stages = _stage_named(low)
    if stages:
        return Route("dashboard", topic="pipeline", words="|".join(stages))
    if _DOCS_RE.search(low) and (_DOC_STATE_RE.search(low) or _UNDER_REVIEW_RE.search(low)) and not _MISSING_RE.search(low):
        return Route("dashboard", topic="documents")
    if _CONSULT_RE.search(low):
        day, window, problem = _when(low, today)
        return Route("inquiries", day, window, problem=problem)
    if _VERIFY_RE.search(low):
        if re.search(r"\b(?:in\s+total|overall|altogether|all[\s-]+time|so\s+far|ever|in\s+all|on\s+record)\b", low) \
                and not has_date_hint(low) and not re.search(r"\b(?:today|yesterday|tonight)\b", low):
            return Route("dashboard", topic="verified_total")
        day, window, problem = _when(low, today)
        return Route("verified", day, window, problem=problem)
    if _MISSING_RE.search(low):
        return Route("missing")
    if _PIPELINE_RE.search(low):
        return Route("dashboard", topic="pipeline")
    if _ADMIT_RE.search(low):
        return Route("admitted")
    if _STAGE_RE.search(low):
        return Route("stage")
    if _VISA_RE.search(low):
        return Route("dashboard", topic="visa")
    if _UNDER_REVIEW_RE.search(low) or _WINDOW_APP_RE.search(low):
        return Route("window_review")
    for topic, pattern in (("accepted", r"\baccepted\b"), ("submitted", r"\bsubmitted\b")):
        if re.search(pattern, low) and _APPLICATION_RE.search(low):
            return Route("dashboard", topic=topic)
    if _OPEN_WINDOWS_RE.search(low):
        return Route("dashboard", topic="windows")
    if _CALENDAR_RE.search(low):
        return Route("calendar")

    # "March 2027" is an intake; "07 Sep 2026" is a date.
    intake = next((m for m in _INTAKE_RE.finditer(low)
                   if not re.search(r"\d(?:st|nd|rd|th)?\s*(?:of\s+)?$", low[:m.start()])), None)
    if intake or _INTAKE_WORD_RE.search(low):
        words = ""
        if intake:
            month = _MONTH_NUMBER[intake.group("month").lower()]
            words = f"{date(2000, month, 1):%B} {intake.group('year')}".upper()
        return Route("intake", words=words)
    if _APPLIED_RE.search(low):
        if re.search(r"\b(?:this|the|current)\s+(?:week|month)\b", low):
            return Route("dashboard", topic="applied")
        day, window, problem = _when(low, today)
        if day or window or problem:
            return Route("applied", day, window, problem=problem)
        return Route("dashboard", topic="applied")
    if (_PROGRAM_RE.search(low) and _STUDENTS_RE.search(low)) or re.search(r"\b(?:per|by|each|every|across)\s+programs?\b", low):
        return Route("dashboard", topic="program")
    if _UNIVERSITY_RE.search(low) and (_MOST_RE.search(low) or _STUDENTS_RE.search(low)
                                       or re.search(r"\b(?:per|by|each|every)\s+universit", low)):
        return Route("dashboard", topic="university")
    if _ATTENTION_RE.search(low):
        return Route("dashboard", topic="attention")
    if _STUDENTS_RE.search(low) and not _leftover(low, _STUDENTS_RE, _re(r"registered|records?|enrolled")):
        return Route("dashboard", topic="total_students")
    if _REPORT_RE.search(low):
        return Route("report")
    if _STATS_RE.search(low):
        return Route("stats")
    return Route("unknown")


# --------------------------------------------------------------------------- the dashboard's figures

class Fact(NamedTuple):
    """One figure the portal dashboard (index.php) shows."""
    group: str              # its tile group or card: "Direct / legacy pipeline", "At a glance"...
    label: str              # the portal's own label: "Total students", "Applied this week"
    value: Optional[int]    # None when it is not a plain number
    text: str               # the figure as printed
    note: str = ""          # the portal's own line under the label, if any

    def line(self) -> str:
        """'Total students (Direct / legacy pipeline): 330': one fact a line, for the LLM and Jennie."""
        what = f"{self.label} — {self.note}" if self.note else self.label
        return f"{what} ({self.group}): {self.text}"


_CARDS = ("At a glance", "Needs attention", "Application pipeline", "Applications by program", "Top universities")


def _text(tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip() if tag is not None else ""


def _number(text: str) -> Optional[int]:
    t = (text or "").strip()
    return int(t.replace(",", "")) if re.fullmatch(r"\d[\d,]*", t) else None


def dashboard_facts(html: str) -> List[Fact]:
    """Every figure on index.php: its tiles (parsers.parse_hangeul_live_dashboard) and the cards
    At a glance, Needs attention, Application pipeline, Applications by program and Top
    universities, each figure with the portal's own label. [] for a page with none of them."""
    from src.scraper.parsers import parse_hangeul_live_dashboard
    facts = [Fact(t.get("group") or "Dashboard", t["label"], t.get("value"), t.get("text") or "")
             for t in parse_hangeul_live_dashboard(html).get("tiles") or []]
    soup = BeautifulSoup(html, "html.parser")
    for card in soup.select(".card"):
        title = _text(card.select_one(".card-title"))
        card_name = next((c for c in _CARDS if title.lower().startswith(c.lower())), None)
        if card_name is None:
            continue
        for item in card.select(".gl"):
            label, value = _text(item.select_one(".gl-l")), _text(item.select_one(".gl-v"))
            if label and value:
                facts.append(Fact(card_name, label, _number(value), value))
        for item in card.select(".pipe-row"):
            top = item.select_one(".pipe-top") or item
            label, value = _text(top.select_one("strong")), _text(item.select_one(".pipe-c"))
            if label and value:
                facts.append(Fact(card_name, label, _number(value), value))
        for item in card.select(".wf-item"):
            if "pipe-row" in (item.get("class") or []):
                continue
            info = item.select_one(".wf-info")
            label = _text(info.select_one("strong")) if info is not None else ""
            note = _text(info.select_one("span")) if info is not None else ""
            value = _text(item.select_one(".wf-count"))
            if label and value:
                facts.append(Fact(card_name, label, _number(value), value, note))
    return facts


def _find(facts: List[Fact], group: str, label: str) -> List[Fact]:
    """The facts of one card or tile group whose label is `label` (case and spacing ignored)."""
    key = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    return [f for f in facts if key(f.group).startswith(key(group)) and (not label or key(f.label) == key(label))]


def _group(facts: List[Fact], group: str) -> List[Fact]:
    return _find(facts, group, "")


def _fact_line(f: Fact, esc) -> str:
    what = f"{esc(f.label)} — {esc(f.note)}" if f.note else esc(f.label)
    return f"• {what} ({esc(f.group)}): `{f.text}`"


# --------------------------------------------------------------------------- the answers

SOURCE_DASHBOARD = "_Read live from the portal dashboard (index.php) just now._"

CANT_ANSWER = (
    "Here is what I can read live for you:\n"
    "• Payments verified on a day: /verified\\_today · /verified\\_date\n"
    "• Consultations on a day: /inquiries\\_today · /inquiries\\_date\n"
    "• Pending payments, applications under review, totals, programs, intakes and the dashboard's "
    "figures: just ask, e.g. “show pending payments”\n"
    "• Deadlines and DHL: /calendar, or “any deadlines this week”\n"
    "• Admitted students: /admitted · Stages: /stage · Missing information: /missing\n"
    "• Passport and document cross-checks: /crosscheck\\_today · /crosscheck\\_date\n"
    "• The portal's Consultant Performance page (tiles, top performer, leaderboard): /performance\\_today · /performance\\_month\n"
    "• The day's brief: /brief"
)

HELLO = ("👋 Hi! I read the Hangeul portal live for you. Ask me things like “how many students were "
         "verified today”, “show pending payments” or “any deadlines this week”.\n\n" + CANT_ANSWER)


def cant_answer(why: Optional[str] = None) -> str:
    """The honest reply (Telegram Markdown) for a question the portal's live data cannot answer."""
    from src.bot.brief import esc
    head = "🤷 I can't answer that from the portal yet" + (f" ({esc(why)})" if why else "") + "."
    return f"{head}\n{CANT_ANSWER}"


def one_day_reply(kind: str, window: Window) -> str:
    """For a span of days asked of an answer given one day at a time (consultations, verified
    payments, passports): which day, and how to ask."""
    what, command = {"inquiries": ("Consultations are", "/inquiries\\_date"),
                     "verified": ("Verified payments are", "/verified\\_date"),
                     "passports": ("Passport cross-checks are", "/crosscheck\\_date")}[kind]
    return (f"📅 {what} counted one day at a time, and you asked about {window.title()}.\n"
            f"Please send the day you want (e.g. `{window.first:%d %b %Y}`), or use {command} <date>.")


async def _dashboard() -> List[Fact]:
    from src.scraper.client import PortalUnavailable, admin_client
    html = await admin_client.fetch_html("index.php", timeout=30.0)
    facts = await asyncio.to_thread(dashboard_facts, html)
    if not facts:
        raise PortalUnavailable("index.php: none of the dashboard's figures could be read (layout not recognised)")
    return facts


def _dashboard_answer(route: Route, facts: List[Fact], query: str) -> str:
    """The reply for a dashboard topic, from the live facts: each figure with its label and where
    on the dashboard it is. A figure the page does not show is "not available"."""
    from src.bot.brief import esc
    low = (query or "").lower()
    topic = route.topic
    lines: List[str] = []

    def add(title: str, found: List[Fact], missing: str):
        lines.append(title)
        if found:
            lines.extend(_fact_line(f, esc) for f in found)
        else:
            lines.append(f"• {missing}: not available (the dashboard does not show it right now)")

    if topic == "total_students":
        add("🎓 *Students on the portal*", _find(facts, "Direct / legacy", "Total students"), "Total students")
        programs = _group(facts, "Applications by program")
        if programs:
            lines.append("• By program: " + " · ".join(f"{esc(f.label)} `{f.text}`" for f in programs)
                         + " (Applications by program)")
    elif topic == "verified_total":
        add("✅ *Students with a verified payment, in all*", _find(facts, "Direct / legacy", "Verified"),
            "Verified")
        lines.append("_For the payments verified on one day, ask e.g. “verified today” or /verified\\_date._")
    elif topic == "program":
        programs = _group(facts, "Applications by program")
        wanted = _program_filter(low)
        if wanted and re.search(r"\b(?:per|by|each|every|across|all)\b", low) is None:
            programs = [f for f in programs if wanted[1] in f.label.upper()]
        add("🎓 *Students by program*", programs, "Applications by program")
        total = _find(facts, "Direct / legacy", "Total students")
        if total:
            lines.append(_fact_line(total[0], esc))
    elif topic == "university":
        unis = _group(facts, "Top universities")
        add("🏛 *Students by university* (the dashboard's Top universities list)", unis, "Top universities")
        ranked = [f for f in unis if f.value is not None]
        if ranked and _MOST_RE.search(low):
            top = max(ranked, key=lambda f: f.value)
            lines.insert(1, f"• *Most students:* {esc(top.label)} (`{top.text}`)")
    elif topic == "applied":
        glance = [f for f in _group(facts, "At a glance") if f.label.lower().startswith("applied")]
        if "week" in low and "month" not in low:
            glance = [f for f in glance if "week" in f.label.lower()] or glance
        elif "month" in low and "week" not in low:
            glance = [f for f in glance if "month" in f.label.lower()] or glance
        add("📝 *Students who applied* (the dashboard's own figures)", glance, "Applied this week / this month")
    elif topic == "documents":
        if _REJECT_RE.search(low):
            add("📄 *Rejected documents*", _find(facts, "Needs attention", "Rejected documents"), "Rejected documents")
        elif _APPROVE_RE.search(low):
            add("📄 *Documents approved*", _find(facts, "At a glance", "Docs approved") + _find(facts, "At a glance", "Total docs"),
                "Docs approved")
        else:
            found = [f for f in facts if f.group not in _CARDS and f.label.lower() == "docs to review"]
            found += _find(facts, "Application pipeline", "Documents Under Review")
            add("📄 *Documents waiting for review*", found, "Docs to review")
    elif topic == "pipeline":
        stages = [s for s in route.words.split("|") if s]
        found = _group(facts, "Application pipeline")
        if stages:
            keys = {re.sub(r"[^a-z]+", "", s.lower()) for s in stages}
            found = [f for f in found if re.sub(r"[^a-z]+", "", f.label.lower()) in keys]
        add("📊 *Students by stage* (the dashboard's Application pipeline)", found, "Application pipeline")
    elif topic == "attention":
        add("⚠️ *Needs attention*", _group(facts, "Needs attention"), "Needs attention")
    elif topic == "visa":
        lines.append("🛂 *Visas*")
        lines.append("I can't answer that from the portal yet: it has no count of approved visas.")
        lines.append("What it does show, live:")
        found = [f for f in _group(facts, "Application pipeline")
                 if f.label.lower() in ("vin application", "embassy submission", "visa result", "admitted / completed")]
        lines.extend(_fact_line(f, esc) + " students at that stage now" for f in found)
        accepted = [f for f in facts if f.group not in _CARDS and f.label.lower() == "accepted"]
        lines.extend(_fact_line(f, esc) + " accepted admission-window applications, not visas" for f in accepted)
        if not found and not accepted:
            lines.append("• nothing about visas on the dashboard right now")
    elif topic in ("accepted", "submitted", "windows"):
        labels = {"accepted": ("accepted",), "submitted": ("submitted apps",),
                  "windows": ("open windows", "draft windows")}[topic]
        if topic == "windows" and ("draft" in low) != bool(re.search(r"\b(?:open|active)\b", low)):
            labels = ("draft windows",) if "draft" in low else ("open windows",)
        found = [f for f in facts if f.group not in _CARDS and f.label.lower() in labels]
        add("🪟 *Admission windows*", found, " / ".join(label.capitalize() for label in labels))
    else:
        return cant_answer()
    lines.append(SOURCE_DASHBOARD)
    return "\n".join(lines)


async def answer_dashboard(route: Route, query: str) -> str:
    from src.bot.replies import portal_error_reply
    try:
        facts = await _dashboard()
    except Exception as e:
        logger.warning(f"Dashboard answer ({route.topic}) not read: {type(e).__name__}: {e}")
        return portal_error_reply("The dashboard's figures", e)
    return _dashboard_answer(route, facts, query)


async def answer_pending() -> str:
    """Who is waiting for payment approval: every page of students.php?status=pending, checked in
    code (a row counts only when its own Payment column says Pending), with the portal's own count."""
    from src.bot.brief import esc
    from src.bot.replies import portal_error_reply
    from src.scraper.client import PortalUnavailable, admin_client
    from src.scraper.parsers import StudentListLayoutError, parse_pending_payments, parse_students_page
    try:
        pages = await admin_client.read_student_pages({"status": "pending"})
        badge = (await asyncio.to_thread(parse_pending_payments, pages[0]) or {}).get("badge") if pages else None
        students, seen = [], set()
        for html in pages:
            try:
                parsed = await asyncio.to_thread(parse_students_page, html)
            except StudentListLayoutError as e:
                raise PortalUnavailable(f"students.php?status=pending: {e}") from e
            for s in parsed["students"]:
                if s.get("uid") not in seen:
                    seen.add(s.get("uid"))
                    students.append(s)
    except Exception as e:
        logger.warning(f"Pending payments not read: {type(e).__name__}: {e}")
        return portal_error_reply("Pending payments", e)
    pending = [s for s in students if re.sub(r"[^a-z]", "", (s.get("payment_status") or "").lower()) == "pending"]
    lines = ["💳 *Pending payments*",
             f"• Pending payments: `{len(pending)}` (students.php?status=pending, every page read)"]
    for i, s in enumerate(pending[:MAX_NAMES_LISTED], 1):
        sid = s.get("student_id") or ""
        bits = [x for x in (s.get("program"), s.get("target_intake")) if x]
        line = f"{i}. *{esc(s.get('student_name') or '—')}*" + (f" (`{sid}`)" if sid else "")
        if bits:
            line += " — " + esc(", ".join(bits))
        if s.get("applied_date"):
            line += f" — applied {esc(s['applied_date'])}"
        if s.get("status"):
            line += f" — stage {esc(s['status'])}"
        lines.append(line)
    if len(pending) > MAX_NAMES_LISTED:
        lines.append(f"_...and {len(pending) - MAX_NAMES_LISTED} more._")
    if not pending:
        lines.append("ℹ️ No student is waiting for payment approval right now.")
    other = len(students) - len(pending)
    if other:
        lines.append(f"⚠️ The page also listed {other} student(s) whose payment is not Pending; they are not counted.")
    if badge is not None and badge != len(pending):
        lines.append(f"⚠️ The portal's own Pending Payments count says {badge}, but its list shows {len(pending)}.")
    elif badge is not None:
        lines.append(f"The portal's own Pending Payments count says {badge} too.")
    lines.append("_Window applications under review are a separate figure, never added to this one._")
    return "\n".join(lines)


async def answer_window_review() -> str:
    """Window applications under review: window_applications.php?status=under_review, counted by
    each row's own status, and the dashboard's Under review tile beside it."""
    from src.bot.replies import portal_error_reply
    from src.scraper.client import admin_client
    try:
        review = await admin_client.read_window_apps_under_review()
    except Exception as e:
        logger.warning(f"Window applications not read: {type(e).__name__}: {e}")
        return portal_error_reply("Window applications under review", e)
    tile = None
    try:
        found = [f for f in await _dashboard() if f.group not in _CARDS and f.label.lower() == "under review"]
        tile = found[0].value if len(found) == 1 else None
    except Exception as e:
        logger.info(f"Dashboard tile for window applications not read: {type(e).__name__}: {e}")
    lines = ["🪟 *Window applications under review*"]
    if review is None:
        lines.append("• Under review: not available (the window applications page's table was not recognised)")
        if tile is not None:
            lines.append(f"The dashboard's Under review tile says {tile}.")
    else:
        lines.append(f"• Window applications under review: `{review}` (window\\_applications.php, each row's own status)")
        if tile is not None and tile != review:
            lines.append(f"⚠️ The dashboard's Under review tile says {tile}.")
        elif tile is not None:
            lines.append(f"The dashboard's Under review tile says {tile} too.")
    lines.append("_Pending payments are a separate figure, never added to this one._")
    return "\n".join(lines)


def _intake_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).upper()


async def answer_intake(route: Route, query: str) -> str:
    """Students per intake, counted from every page of students.php (the dashboard has no intake
    figure), for one intake when the words name one, and one program when they name one."""
    from src.bot.brief import esc
    from src.bot.replies import portal_error_reply
    from src.scraper.client import admin_client
    try:
        students = await admin_client.read_students()
    except Exception as e:
        logger.warning(f"Intakes not read: {type(e).__name__}: {e}")
        return portal_error_reply("Students per intake", e)
    program = _program_filter((query or "").lower())
    pool = [s for s in students if not program or program[1] in (s.get("program") or "").upper()]
    what = f" in {_PROGRAM_NAMES[program[0]]}" if program else ""
    source = f"_Counted from every page of the student list ({len(students)} students), read live just now._"
    if route.words:
        wanted = _intake_key(route.words)
        in_it = [s for s in pool if _intake_key(s.get("target_intake")) == wanted]
        lines = [f"🗓 *{esc(wanted)} intake*",
                 f"• Students{esc(what)} in the {esc(wanted)} intake: `{len(in_it)}`"]
        if in_it and not program:
            by = Counter(_intake_key(s.get("program")) or "—" for s in in_it)
            lines.append("• By program: " + " · ".join(f"{esc(k)} `{n}`" for k, n in by.most_common()))
        return "\n".join(lines + [source])
    by = Counter(_intake_key(s.get("target_intake")) or "no intake set" for s in pool)
    lines = [f"🗓 *Students by intake{esc(what)}*"]
    lines += [f"• {esc(k)}: `{n}`" for k, n in by.most_common()]
    if not by:
        lines.append("• No students on the list" + (esc(what) if what else "") + ".")
    return "\n".join(lines + [source])


async def answer_applied(route: Route) -> str:
    """How many students applied on a day or in a span of days, counted from the Applied date of
    every student on students.php."""
    from src.bot.brief import esc
    from src.bot.replies import portal_error_reply
    from src.dates import parse_portal_date
    from src.scraper.client import admin_client
    first = route.day or (route.window.first if route.window else local_today())
    last = route.day or (route.window.last if route.window and route.window.last else local_today())
    label = (Window(first, last, _day_label(first, local_today())).title() if route.day
             else route.window.title() if route.window else "today")
    try:
        students = await admin_client.read_students()
    except Exception as e:
        logger.warning(f"Applied dates not read: {type(e).__name__}: {e}")
        return portal_error_reply(f"Students who applied {esc(label)}", e)
    days = [parse_portal_date(s.get("applied_date") or s.get("applied_on") or "") for s in students]
    unread = sum(1 for d in days if d is None)
    count = sum(1 for d in days if d is not None and first <= d <= last)
    lines = [f"📝 *Students who applied — {esc(label)}*",
             f"• Students who applied: `{count}`"]
    if unread:
        lines.append(f"⚠️ {unread} student(s) on the list have an Applied date the bot cannot read; they are not counted.")
    lines.append(f"_Counted from the Applied date of every student on the list ({len(students)} students), read live just now._")
    return "\n".join(lines)


async def answer_unknown(query: str) -> str:
    """A question no route fits: the dashboard facts whose whole label it names; else the ones the
    local LLM picks (ollama_client.answer_agent_query), shown word for word; else cant_answer."""
    from src.bot.brief import esc
    from src.llm.ollama_client import ollama_client
    from src.scraper.client import portal_error_reason
    try:
        facts = await _dashboard()
    except Exception as e:
        logger.warning(f"Dashboard not read for a question: {type(e).__name__}: {e}")
        return cant_answer(f"the portal dashboard could not be read: {portal_error_reason(e)}")
    lines = [f.line() for f in facts if f.value is not None]
    picked = ollama_client._answer_query_fallback(query, lines)
    how = "the figures whose label your question names"
    if not picked:
        chosen = await ollama_client.answer_agent_query(query, lines)
        picked, how = (chosen or []), "the local AI picked which figures answer it; each figure is the portal's own"
    by_line = {f.line(): f for f in facts}
    picked = [by_line[p] for p in picked if p in by_line]
    if not picked:
        return cant_answer()
    return "\n".join(["📊 *From the portal dashboard*"] + [_fact_line(f, esc) for f in picked]
                     + [f"_Read live just now; {how}._"])


async def reply(message, route: Route, query: str) -> None:
    """Answer a question whose answer is built here (the kinds pending, window_review, dashboard,
    intake, applied and unknown): a "please wait" note, the live reads, then the answer in its
    place (split under Telegram's limit)."""
    from src.bot.replies import reply_long
    status = await message.reply_text("🤔 _Reading the live portal..._", parse_mode="Markdown")
    try:
        if route.kind == "pending":
            text = await answer_pending()
        elif route.kind == "window_review":
            text = await answer_window_review()
        elif route.kind == "dashboard":
            text = await answer_dashboard(route, query)
        elif route.kind == "intake":
            text = await answer_intake(route, query)
        elif route.kind == "applied":
            text = await answer_applied(route)
        else:
            text = await answer_unknown(query)
    except Exception as e:                   # never a silent failure
        logger.error(f"Question ({route.kind}) failed: {type(e).__name__}: {e}")
        from src.bot.replies import portal_error_reply
        text = portal_error_reply("The answer", e)
    await reply_long(message, text, edit=status)


# --------------------------------------------------------------------------- the calendar

class CalItem(NamedTuple):
    title: str
    kind: str                   # "DHL to send", "Application period"...
    where: str                  # the university, as the portal shows it
    start: Optional[date]
    end: Optional[date]         # the last day: when it closes, or when the DHL must go
    done: bool
    note: str                   # the event's own note: its program ("MASTER'S PROGRAM") or free text
    id: str = ""                # the portal's own event id ("" when the page shows none)


class CalendarQuery(NamedTuple):
    window: Optional[Window]    # the days asked about
    deadlines: bool             # only what closes (is due) within them
    dhl: bool                   # only DHL items
    words: List[str]            # search words (a university, a program)
    problem: Optional[str]      # a date-like part that cannot be read
    default: bool               # nothing asked beyond the calendar itself: today's view


_EV_KINDS = {"dhl": "DHL to send", "period": "Application period"}
_CAL_FILLER_RE = _re(
    r"calendar|events?|deadlines?|due|dhl|shipping|shipments?|ship|courier|parcels?|status|reminders?|schedule[sd]?"
    r"|closing|closes?|close|opening|opens?|open|application|applications|periods?|windows?|dates?|sending|send|sent"
    r"|coming|upcoming|up|soon|ahead|next|this|week|weekend|month|today|tomorrow|days?|weeks?|months?|when|what's"
    r"|last|left|still|pending|any|show|list|all|the|a|an|for|of|in|on|at|is|are|there|what|which|me|please|pls"
    r"|do|we|have|our|to|by|from|between|and|until|till|through|how|many|much|it|its|there's|remaining|universit\w*"
    r"|accepting|timeline|agenda|happening|coming|items?")


def calendar_query(text: str, today: Optional[date] = None) -> CalendarQuery:
    """What a /calendar question asks: the days (date_window, forward: "this week" is today to
    Sunday), only deadlines ("deadline", "due", "closing"), only DHL, and the words left to search
    for. A bare /calendar, "deadlines" or "events" is today's view."""
    today = today or local_today()
    low = re.sub(r"/(?:calendar|events|deadlines)(?:@\w+)?", " ", (text or "").lower().replace("’", "'"))
    low = re.sub(r"\s+", " ", low).strip()
    window, problem = date_window(low, today, forward=True)
    deadlines = bool(re.search(r"\b(?:deadlines?|due|closing|closes?|close|last\s+day|expir\w*|submit\w*\s+by)\b", low))
    dhl = bool(re.search(r"\b(?:dhl|shipping|shipments?|ship|courier|parcels?)\b", low))
    rest = _CAL_FILLER_RE.sub(" ", low)
    rest = re.sub(rf"\b(?:{_MONTH_WORDS}|monday|tuesday|wednesday|thursday|friday|saturday|sunday|yesterday)\b", " ", rest)
    words = [w for w in _words(rest) if not w.isdigit() and w not in _FILLER and len(w) > 1]
    bare = not re.search(r"\b(?:coming\s+up|upcoming|soon|ahead|next)\b", low)
    default = window is None and problem is None and not dhl and not words and bare
    if window is None and problem is None and not default and not words and not dhl:
        window = Window(today, None, "coming up")
    return CalendarQuery(window, deadlines, dhl, words, problem, default)


def _cal_day(day: int, month_word: str, year: Optional[int], near: date) -> Optional[date]:
    """'26 Sep' -> the date of that day nearest to `near` (or in `year` when the page gives it)."""
    month = _MONTH_NUMBER.get(month_word.lower()[:3]) or _MONTH_NUMBER.get(month_word.lower())
    if not month:
        return None
    years = [year] if year else [near.year - 1, near.year, near.year + 1]
    best = None
    for y in years:
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if best is None or abs((d - near).days) < abs((best - near).days):
            best = d
    return best


_CAL_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?(?:\s+(\d{4}))?")


def _cal_range(text: str, near: date) -> Tuple[Optional[date], Optional[date]]:
    """'26 Sep–05 Oct', '07 Oct – 14 Oct 2026', '21 Sep' -> (start, end or None)."""
    found = _CAL_DATE_RE.findall(text or "")
    if not found:
        return None, None
    year_end = int(found[-1][2]) if found[-1][2] else None
    start = _cal_day(int(found[0][0]), found[0][1], int(found[0][2]) if found[0][2] else None, near)
    if len(found) < 2 or start is None:
        return start, None
    end = _cal_day(int(found[1][0]), found[1][1], year_end, near)
    if end is not None and start > end:
        if found[0][2]:
            end = _cal_day(int(found[1][0]), found[1][1], start.year + 1, near)
        else:
            try:
                start = start.replace(year=start.year - 1)
            except ValueError:
                pass
    return start, end


def _status_days(status: str, today: date) -> Tuple[Optional[date], Optional[date]]:
    """The timeline's status -> (start, end) it tells: "Closes in 4 days", "In 7 days", "Today",
    "Opens in 9 days"."""
    s = (status or "").lower()
    m = re.search(r"opens?\s+in\s+(\d+)\s+days?", s)
    if m:
        return today + timedelta(days=int(m.group(1))), None
    if re.search(r"opens?\s+today", s):
        return today, None
    if re.search(r"opens?\s+tomorrow", s):
        return today + timedelta(days=1), None
    m = re.search(r"(?:closes?\s+|due\s+)?in\s+(\d+)\s+days?", s)
    if m:
        return None, today + timedelta(days=int(m.group(1)))
    if re.search(r"\btomorrow\b", s):
        return None, today + timedelta(days=1)
    if re.search(r"\btoday\b", s):
        return None, today
    return None, None


def _ev_items(html: str) -> Optional[List[CalItem]]:
    """The month's event list the calendar page carries as data (var EV = [...]): each with its
    own id, full start and end dates and its notes (the program: two events with one title, such
    as a university's Master's and Bachelor's application periods, are two items). None when the
    page has none."""
    m = re.search(r"\bvar\s+EV\s*=\s*", html or "")
    if not m:
        return None
    try:
        events, _ = json.JSONDecoder().raw_decode(html[m.end():])
    except ValueError:
        return None
    if not isinstance(events, list):
        return None
    items = []
    for e in events:
        if not isinstance(e, dict) or not e.get("title"):
            continue
        try:
            start = date.fromisoformat(str(e.get("start"))[:10]) if e.get("start") else None
            end = date.fromisoformat(str(e.get("end"))[:10]) if e.get("end") else start
        except ValueError:
            continue
        kind = str(e.get("type") or "")
        items.append(CalItem(str(e["title"]).strip(), _EV_KINDS.get(kind.lower(), kind.title() or "Event"),
                             str(e.get("uni") or "").strip(), start, end, bool(e.get("done")),
                             re.sub(r"\s+", " ", str(e.get("notes") or "")).strip(), str(e.get("id") or "").strip()))
    return items


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def calendar_items(html: str, today: Optional[date] = None) -> Tuple[List[CalItem], bool]:
    """Every calendar item calendar.php shows, once: the month's event list (full dates, notes),
    today's reminders ("26 Sep–05 Oct") and the 45-day timeline (its date, range and status,
    "Closes in 4 days"). An entry is matched by the portal's own event id (its edit link) when it
    has one, else by title, start and note; two different ids are never one item, so a
    university's Master's and Bachelor's periods with one title and the same dates stay two.
    -> (items, whether the page's layout was recognised)."""
    from src.scraper.parsers import parse_calendar_events
    today = today or local_today()
    cal = parse_calendar_events(html)
    ev = _ev_items(html)
    items: List[CalItem] = []
    ids = set()
    for item in ev or []:
        if item.id and item.id in ids:
            continue                                # the same event twice in the list
        ids.add(item.id)
        items.append(item)

    def same(v: CalItem, cid: str, title: str, start: Optional[date], note: str) -> bool:
        if cid and v.id:
            return cid == v.id
        return (_key(v.title) == _key(title) and (start is None or v.start is None or v.start == start)
                and (not note or not v.note or _key(v.note) == _key(note)))

    def add(cid, title, kind, where, start, end, note):
        """An item from the page's lists: the one already known (the same id; without one, the same
        title, and the same start and note when both have one) gets what it lacks; another is added."""
        for n, v in enumerate(items):
            if same(v, cid, title, start, note):
                items[n] = v._replace(start=v.start or start, end=v.end or end, note=v.note or note,
                                      where=v.where or where, id=v.id or cid)
                return
        items.append(CalItem(title, kind or "Event", where, start, end, False, note, cid))

    for r in cal.get("today_reminders") or []:
        start, end = _cal_range(r.get("date_range") or "", today)
        add(r.get("id") or "", r["title"], r.get("type"), r.get("where") or "", start, end, r.get("program") or "")
    for u in cal.get("upcoming_events") or []:
        near = today
        start, end = _cal_range(u.get("date_range") or u.get("date") or "", near)
        s_start, s_end = _status_days(u.get("status") or "", today)
        start = start or s_start
        if end is None or (start is not None and end == start and s_end is not None):
            end = s_end or end
        done = bool(re.search(r"\b(?:done|completed)\b", u.get("status") or "", re.I))
        if done:
            continue
        add(u.get("id") or "", u["title"], u.get("type"), u.get("university") or "", start, end, u.get("program") or "")
    ok = ev is not None or bool(cal.get("layout_ok")) or bool(cal.get("upcoming_ok"))
    unique, seen = [], set()
    for item in items:
        sig = item.id or (_key(item.title), item.kind, item.start, item.end, _key(item.note))
        if sig not in seen:
            seen.add(sig)
            unique.append(item)
    return unique, ok


def _when_due(item: CalItem, today: date) -> str:
    verb = "closes" if "period" in item.kind.lower() else "due"
    if item.end is None:
        return f"opens {item.start:%a %d %b}" if item.start and item.start > today else "end date not shown"
    left = (item.end - today).days
    if left == 0:
        return f"{verb} *today* ({item.end:%a %d %b})"
    if left == 1:
        return f"{verb} tomorrow ({item.end:%a %d %b})"
    if left < 0:
        return (f"closed {item.end:%a %d %b}" if verb == "closes"
                else f"was due {item.end:%a %d %b}" + ("" if item.done else " (not marked done)"))
    return f"{verb} {item.end:%a %d %b} ({left} days left)"


def calendar_answer(items: List[CalItem], q: CalendarQuery, today: date) -> str:
    """The reply (Telegram Markdown) for a calendar question, from the page's items."""
    from src.bot.brief import esc
    pool = [i for i in items if not i.done]
    if q.dhl:
        pool = [i for i in pool if "dhl" in (i.kind + " " + i.title).lower()]
    if q.words:
        pool = [i for i in pool if all(w in f"{i.title} {i.where} {i.kind} {i.note}".lower() for w in q.words)]
    w = q.window
    if w is not None:
        last = w.last or date.max
        if q.deadlines:
            pool = [i for i in pool if i.end is not None and w.first <= i.end <= last]
        else:
            pool = [i for i in pool if (i.start or i.end) is not None and (i.start or i.end) <= last
                    and (i.end or i.start) >= w.first]
    elif q.deadlines:
        pool = [i for i in pool if i.end is not None]       # a deadline is an item's last day
    pool.sort(key=lambda i: (i.end or i.start or date.max, i.title, i.note))

    what = "DHL shipments" if q.dhl else "Deadlines" if q.deadlines else "Calendar items"
    head = what
    if q.words:
        head += " matching “" + esc(" ".join(q.words)) + "”"
    if w is not None:
        head += f" — {esc(w.title())}"
    # The count's own words say where the items stand (Jennie speaks from this line): none of the
    # items counted is marked done on the portal.
    if q.dhl:
        counted = "DHL shipments still to send"
    elif q.deadlines and pool and all(i.end >= today for i in pool):
        counted = "Deadlines still open"
    elif q.deadlines and pool and all(i.end < today for i in pool):
        counted = "Deadlines already passed"
    else:
        counted = what
    from src.scraper.parsers import _CAL_PROGRAM_RE
    lines = [f"📅 *{head}*", f"• {counted}: `{len(pool)}`"]
    for n, i in enumerate(pool[:MAX_CALENDAR_LISTED], 1):
        bits = [esc(i.kind)] + ([esc(i.where)] if i.where and i.where.lower() not in i.title.lower() else [])
        span = ""
        if i.start and i.end and i.start != i.end:
            span = f" · {i.start:%d %b}–{i.end:%d %b}"
        program = f" ({esc(i.note)})" if i.note and _CAL_PROGRAM_RE.search(i.note) and len(i.note) <= 40 else ""
        lines.append(f"{n}. *{esc(i.title)}*{program} — {' · '.join(bits)}{span} — {_when_due(i, today)}")
    if len(pool) > MAX_CALENDAR_LISTED:
        lines.append(f"_...and {len(pool) - MAX_CALENDAR_LISTED} more._")
    if not pool:
        lines.append(f"ℹ️ None on the calendar{' for ' + esc(w.title()) if w else ''}.")
    if w is not None:
        last = w.last or date.max
        done_in = sorted((i for i in items if i.done and (i.start or i.end) is not None
                          and (i.start or i.end) <= last and (i.end or i.start) >= w.first
                          and (not q.dhl or "dhl" in (i.kind + " " + i.title).lower())
                          and (not q.words or all(x in f"{i.title} {i.where} {i.kind} {i.note}".lower()
                                                  for x in q.words))),
                         key=lambda i: (i.end or date.min))
        if done_in:
            lines.append("_Not counted, marked done on the portal: " + ", ".join(
                esc(i.title) + (f" (due {i.end:%d %b})" if i.end else "") for i in done_in[:5])
                + (f" and {len(done_in) - 5} more" if len(done_in) > 5 else "") + "._")
    if q.dhl and w is None:
        done = sorted((i for i in items if i.done and "dhl" in (i.kind + " " + i.title).lower()),
                      key=lambda i: (i.end or date.min), reverse=True)
        if done:
            lines.append("_Marked done: " + ", ".join(
                esc(i.title) + (f" (due {i.end:%d %b})" if i.end else "") for i in done[:5]) + "._")
    if q.deadlines and w is not None and w.last is not None:
        later = sorted((i for i in items if not i.done and i.end and i.end > w.last
                        and (not q.dhl or "dhl" in (i.kind + " " + i.title).lower())
                        and (not q.words or all(x in f"{i.title} {i.where} {i.kind} {i.note}".lower() for x in q.words))),
                       key=lambda i: (i.end, i.title))
        if later:
            lines.append(f"_The next one after that: {esc(later[0].title)}, {_when_due(later[0], today).replace('*', '')}._")
    lines.append("_Read live from calendar.php: today's reminders, the 45-day timeline and the month's event list._")
    return "\n".join(lines)


async def answer_calendar(q: CalendarQuery) -> str:
    """calendar.php read live, its items filtered by the question (calendar_query)."""
    from src.bot.replies import portal_error_reply
    from src.scraper.client import PortalUnavailable, admin_client
    today = local_today()
    try:
        html = await admin_client.fetch_html("calendar.php")
        items, ok = await asyncio.to_thread(calendar_items, html, today)
        if not ok:
            raise PortalUnavailable("calendar.php: its layout was not recognised")
    except Exception as e:
        logger.warning(f"Calendar not read: {type(e).__name__}: {e}")
        return portal_error_reply("The calendar", e)
    return calendar_answer(items, q, today)
