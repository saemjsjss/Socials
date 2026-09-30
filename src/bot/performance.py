"""Team performance, read live: /performance_today (today) and /performance_month (the 1st of this
month to today, both included, in settings.REPORT_TIMEZONE).

One report, from two read-only reads of the portal's own records:
  consultations   consult_requests.php through its own date filter for the window
                  (client.read_consultation_range): its status tabs count every request received in
                  the window; its rows say who did what ("Last updated by", the Consultant column)
  verifications   every page of students.php, read ONCE for the whole window
                  (client.read_verified_window): each row's own "Payment verified by NAME · 27 Sep,
                  17:19" stamp. The stamps have no year, so a window a year or more back is "not
                  available" (src.dates.yearless_day_problem, as for one day).

The team figures are the portal's own counts (the tabs; the verifications counted in code). The
lines per person are counted in code from the rows, the way the daily brief counts them:
  consultations done  Consulted + File Opened, by the row's "Last updated by" (the brief's "Done by")
  follow-ups          No Answer and Wrong Number, by the row's "Last updated by"
  requests assigned   the window's requests whose Consultant column names that person
  payments verified   by the stamp's name, with the total of the verified income (else the amount paid)
Names are matched without regard to case ("MAHIRA JANAN" on a stamp is "Mahira Janan" on a
request). A request no name is on is said as such ("no name on the portal", "assigned to no
consultant" for the portal's "—"), never credited to anybody; a page with no Consultant column makes
requests assigned "not available".

A part that cannot be read says which ("Consultations: couldn't read the portal: ..."), and the part
that was read is still shown: a figure that was not read is never a 0, and the report's last line
names only the parts that were read. The two reads run side by side on one session (it is opened
first), each within PART_TIMEOUT.
"""
import asyncio
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from src.bot.brief import _amount, esc

logger = logging.getLogger("hangeul.performance")

PART_TIMEOUT = 120.0            # seconds each read may take (7 student pages ~10 s, a month of requests ~4 s)
KINDS = ("today", "month")
DONE = ("Consulted", "File Opened")
FOLLOW_UPS = ("No Answer", "Wrong Number")
KNOWN = DONE + FOLLOW_UPS + ("New",)
RULE = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def window(kind: str, today: date) -> Tuple[date, date]:
    """(first, last) of a performance window: today alone, or this month's 1st to today."""
    if kind not in KINDS:
        raise ValueError(f"no such performance window: {kind!r}")
    return (today, today) if kind == "today" else (today.replace(day=1), today)


def window_title(kind: str, first: date, last: date) -> str:
    """'Today, 29 September 2026' or 'This Month, 01–29 September 2026'."""
    if kind == "today":
        return f"Today, {last:%d %B %Y}"
    if first == last:
        return f"This Month, {last:%d %B %Y}"
    return f"This Month, {first:%d}–{last:%d %B %Y}"


def waiting_text(kind: str, first: date, last: date) -> str:
    """The "please wait" line (Telegram Markdown: one _italic_ entity, no underscore inside)."""
    what = "today's team performance" if kind == "today" else \
        f"this month's team performance ({first:%d %b} to {last:%d %b})"
    return (f"⏳ _Reading {what} live from the portal: the consultation requests and every page of the "
            "student list (about 10 to 20 seconds)..._")


def _bold_safe(text) -> str:
    """Portal text inside a *bold* entity: legacy Markdown reads it literally up to its closing '*'
    (a backslash there would show), so only a '*' of its own is changed."""
    return str(text).replace("*", "∗")


def _key(name: str) -> str:
    return " ".join((name or "").split()).casefold()


@dataclass
class Person:
    """One staff member's figures in the window."""
    name: str
    consulted: int = 0
    file_opened: int = 0
    no_answer: int = 0
    wrong_number: int = 0
    other: Counter = field(default_factory=Counter)     # other statuses they set ("Rescheduled": 1)
    assigned: int = 0
    verified: int = 0
    amount: float = 0.0                                 # the total of their verifications' amounts
    with_amount: int = 0                                # how many of those show an amount

    @property
    def done(self) -> int:
        return self.consulted + self.file_opened

    @property
    def activity(self) -> int:
        """What they did in the window: consultations done, follow-ups, other status updates and
        payments verified (requests assigned to them are shown, not counted as activity)."""
        return self.done + self.no_answer + self.wrong_number + sum(self.other.values()) + self.verified


class Tally(NamedTuple):
    people: List[Person]            # sorted by activity, then requests assigned, then name
    unnamed: Counter                # figures no name is on: "done", "follow_up", "other", "verified"
    unassigned: int                 # the window's requests whose Consultant column names nobody ("—")
    consultant_column: bool         # False when the requests were read without a Consultant column


def tally(rows: Optional[List[Dict[str, Any]]], verified: Optional[List[Dict[str, Any]]],
          consultant_column: bool = True) -> Tally:
    """Per person, from the window's request rows (None: not read) and its verifications (None: not
    read). `consultant_column`: whether the rows were read from a page with a Consultant column
    (without one, nothing is counted as assigned, to anybody or to nobody). A name that differs only
    in case or spacing is one person; the name shown is the one the portal writes in mixed case
    when it has one ("Mahira Janan" rather than "MAHIRA JANAN")."""
    people: Dict[str, Person] = {}
    unnamed: Counter = Counter()

    def person(name: str) -> Person:
        name = " ".join(name.split())
        p = people.get(_key(name))
        if p is None:
            p = people[_key(name)] = Person(name)
        elif p.name.isupper() and not name.isupper():
            p.name = name
        return p

    unassigned = 0
    for r in rows or []:
        status, by = r.get("status") or "", (r.get("handled_by") or "").strip()
        consultant = (r.get("consultant") or "").strip()
        if consultant_column:                       # else the page shows no Consultant column
            if consultant and consultant != "Unassigned":
                person(consultant).assigned += 1
            else:
                unassigned += 1                     # the portal's "—"
        if status == "New":
            continue                                # nobody has an outcome for a request still new
        bucket = ("done" if status in DONE else "follow_up" if status in FOLLOW_UPS else "other")
        if not by:
            unnamed[bucket] += 1
            continue
        p = person(by)
        if status == "Consulted":
            p.consulted += 1
        elif status == "File Opened":
            p.file_opened += 1
        elif status == "No Answer":
            p.no_answer += 1
        elif status == "Wrong Number":
            p.wrong_number += 1
        else:
            p.other[status or "blank"] += 1
    for v in verified or []:
        by = (v.get("verified_by") or "").strip()
        if not by:
            unnamed["verified"] += 1
            continue
        p = person(by)
        p.verified += 1
        amount = _amount(v.get("amount"))
        if amount is not None:
            p.amount += amount
            p.with_amount += 1
    ranked = sorted(people.values(), key=lambda p: (-p.activity, -p.assigned, p.name.casefold()))
    return Tally(ranked, unnamed, unassigned, consultant_column)


class Reads(NamedTuple):
    consultations: Optional[Dict[str, Any]]     # client.read_consultation_range's result, or None
    consult_error: Optional[Exception]          # why it was not read
    verified: Optional[Dict[str, Any]]          # client.read_verified_window's result, or None
    verified_error: Optional[Exception]         # why it was not read
    verified_problem: Optional[str]             # why the window cannot be answered (the yearless rule)
    seconds: float = 0.0


async def read_performance(first: date, last: date, today: date) -> Reads:
    """Both reads for the window: one session opened first, then the consultation range and every
    page of students.php side by side, each within PART_TIMEOUT. A read that fails keeps its
    exception; the other part is still returned. Never raises."""
    from src.dates import yearless_day_problem
    from src.scraper.client import admin_client
    started = time.perf_counter()
    problem = yearless_day_problem(first, today) or yearless_day_problem(last, today)

    async def part(job):
        try:
            return await asyncio.wait_for(job(), timeout=PART_TIMEOUT), None
        except Exception as e:                       # the portal down, a layout change, a timeout...
            return None, e

    try:
        await admin_client.ensure_session()
    except Exception as e:
        return Reads(None, e, None, None if problem else e, problem, time.perf_counter() - started)
    jobs = [part(lambda: admin_client.read_consultation_range(first, last))]
    if not problem:
        jobs.append(part(lambda: admin_client.read_verified_window(first, last)))
    results = await asyncio.gather(*jobs)
    consult, consult_error = results[0]
    verified, verified_error = results[1] if len(results) > 1 else (None, None)
    return Reads(consult, consult_error, verified, verified_error, problem, time.perf_counter() - started)


def _money(value: float) -> str:
    return f"৳ {value:,.2f} BDT"


def _failed(what: str, error: Exception) -> str:
    from src.scraper.client import portal_error_reason
    return f"• ❌ {what}: couldn't read the portal: {esc(portal_error_reason(error))}."


def _consultation_lines(reads: Reads) -> List[str]:
    lines = ["📞 *Consultation Requests* (received in the window, with their status now)"]
    if reads.consultations is None:
        return lines + [_failed("Consultations", reads.consult_error or RuntimeError("not read"))]
    counts = reads.consultations["counts"]
    c = Counter({k: v for k, v in counts.items() if k != "All"})
    lines += [f"• *Received:* `{counts['All']}`",
              f"• *Done:* `{c['Consulted'] + c['File Opened']}` ({c['Consulted']} Consulted, "
              f"{c['File Opened']} File Opened)",
              f"• *Still New:* `{c['New']}` | *No Answer:* `{c['No Answer']}` | *Wrong Number:* `{c['Wrong Number']}`"]
    other = [(s, n) for s, n in counts.items() if s != "All" and s not in KNOWN and n]
    if other:
        lines.append("• *Other statuses:* " + ", ".join(f"{esc(s)} `{n}`" for s, n in other))
    return lines


def _verified_lines(reads: Reads) -> List[str]:
    lines = ["✅ *Payments Verified*"]
    if reads.verified_problem:
        return lines + [f"• ℹ️ Payments verified: not available ({esc(reads.verified_problem)})."]
    if reads.verified is None:
        return lines + [_failed("Payments verified", reads.verified_error or RuntimeError("not read"))]
    verified = reads.verified["verified"]
    lines.append(f"• *Students Verified:* `{len(verified)}`")
    if not verified:
        return lines
    amounts = [a for a in (_amount(v.get("amount")) for v in verified) if a is not None]
    if not amounts:
        return lines + ["• *Total:* not available (no amount on the portal rows)"]
    income = sum(1 for v in verified if v.get("verified_income"))
    # What the total adds up, as the daily brief says it.
    source = ("verified income" if income and income >= len(amounts) else
              "verified income, or the amount paid where no income is shown" if income else "amounts paid")
    if len(amounts) < len(verified):
        source += f"; the {len(amounts)} with an amount on the portal, {len(verified) - len(amounts)} without"
    return lines + [f"• *Total:* `{_money(sum(amounts))}` ({source})"]


def _person_lines(n: int, p: Person, consult_read: bool, verified_read: bool,
                  assigned_read: bool = True) -> List[str]:
    items = []
    if consult_read:
        done = f"✅ Consultations done: `{p.done}`"
        if p.file_opened:
            done += f" ({p.consulted} Consulted, {p.file_opened} File Opened)"
        items.append(done)
        items.append(f"📵 Follow-ups: No Answer `{p.no_answer}` · Wrong Number `{p.wrong_number}`")
        if p.other:
            items.append("✏️ Other status updates: " + ", ".join(f"{esc(s)} `{k}`" for s, k in p.other.most_common()))
        if assigned_read:
            items.append(f"📋 Requests assigned: `{p.assigned}`")
    if verified_read:
        paid = f"💳 Payments verified: `{p.verified}`"
        if p.verified and p.with_amount == p.verified:
            paid += f" ({_money(p.amount)})"
        elif p.with_amount:
            paid += f" ({_money(p.amount)} for the {p.with_amount} with an amount)"
        elif p.verified:
            paid += " (no amount on the portal rows)"
        items.append(paid)
    lines = [f"*{n}. {_bold_safe(p.name)}*"]
    lines += [f"   {'└' if i == len(items) - 1 else '├'} {item}" for i, item in enumerate(items)]
    return lines


def _people_lines(reads: Reads) -> List[str]:
    consult_read = reads.consultations is not None
    verified_read = reads.verified is not None
    lines = ["👥 *By Person* (most active first)"]
    if not consult_read and not verified_read:
        return lines + ["• not available (neither part could be read)"]
    t = tally(reads.consultations["rows"] if consult_read else None,
              reads.verified["verified"] if verified_read else None,
              consultant_column=_consultant_column(reads))
    if not consult_read:
        lines.append("_Consultation figures per person: not available (the consultation requests could not be read)._")
    if not verified_read:
        lines.append("_Payments per person: not available (" + ("the window cannot be answered"
                     if reads.verified_problem else "the student list could not be read") + ")._")
    if consult_read and not reads.consultations.get("complete", True):
        lines.append(f"⚠️ _The portal lists {len(reads.consultations['rows'])} of the "
                     f"{reads.consultations['counts']['All']} requests (one day holds more than its list shows): "
                     "the consultation figures per person count those._")
    if not t.people:
        # Only about what was read: a request list that was not read says nothing about requests.
        what = " or ".join(w for w, read in (("a request", consult_read), ("a payment verification", verified_read))
                           if read)
        lines.append(f"• Nobody's name is on {what} in this window.")
    for n, p in enumerate(t.people, 1):
        lines += _person_lines(n, p, consult_read, verified_read, t.consultant_column)
    extra = []
    if consult_read:
        if t.unnamed["done"]:
            extra.append(f"• Done with no name on the portal: `{t.unnamed['done']}`")
        if t.unnamed["follow_up"]:
            extra.append(f"• No Answer / Wrong Number with no name on the portal: `{t.unnamed['follow_up']}`")
        if t.unnamed["other"]:
            extra.append(f"• Other status updates with no name on the portal: `{t.unnamed['other']}`")
        if not t.consultant_column:
            extra.append("• Requests assigned: not available (the consultation page shows no Consultant column)")
        elif t.unassigned:
            extra.append(f"• Requests assigned to no consultant: `{t.unassigned}`")
    if verified_read and t.unnamed["verified"]:
        extra.append(f"• Payments verified with no name on the portal: `{t.unnamed['verified']}`")
    if extra:
        lines += [""] + extra
    return lines


def _consultant_column(reads: Reads) -> bool:
    """Whether the consultation requests were read from pages with a Consultant column."""
    return reads.consultations is not None and reads.consultations.get("consultant_column", True)


def _source_line(reads: Reads) -> Optional[str]:
    """The report's last line: what was read, and how the people are sorted. Only the parts that
    were read are named (a part that could not be read is claimed as nothing); None when neither
    part was read."""
    parts, sorted_by = [], []
    if reads.consultations is not None:
        how = "done and follow-ups by each request's own \"Last updated by\""
        if _consultant_column(reads):
            how += ", assigned by its Consultant"
        parts.append(f"the consultation page's own date filter for the window (statuses as they are now; {how})")
        sorted_by.append("consultations done + follow-ups + other status updates")
    if reads.verified is not None:
        parts.append(f"all {reads.verified['students']} students of the student list by their own "
                     "\"Payment verified by\" stamp")
        sorted_by.append("payments verified")
    if not parts:
        return None
    return f"_Read live just now, read-only: {', and '.join(parts)}. Sorted by {' + '.join(sorted_by)}._"


def format_performance_report(kind: str, first: date, last: date, reads: Reads) -> str:
    """The report (Telegram Markdown): the window in the header, the team's figures, then one block
    per person, and a last line naming what was read. Only what was read: a part that was not is
    said so, never shown as 0, and never named as read."""
    lines = [f"📈 *Team Performance — {window_title(kind, first, last)}*", RULE]
    lines += _consultation_lines(reads) + [""] + _verified_lines(reads) + [""] + _people_lines(reads)
    source = _source_line(reads)
    if source:
        lines += ["", source]
    return "\n".join(lines)


async def build_performance_report(kind: str, today: Optional[date] = None) -> str:
    """The performance report for `kind` ("today" or "month"), read live."""
    from src.dates import local_today
    today = today or local_today()
    first, last = window(kind, today)
    reads = await read_performance(first, last, today)
    text = format_performance_report(kind, first, last, reads)
    logger.info(f"Performance {kind} ({first}..{last}): portal read in {reads.seconds:.1f} s; consultations "
                f"{'read' if reads.consultations is not None else 'not read'}"
                f"{' in ' + str(reads.consultations['reads']) + ' page(s)' if reads.consultations else ''}, "
                f"verifications {'read' if reads.verified is not None else 'not read'}; {len(text)} characters.")
    return text
