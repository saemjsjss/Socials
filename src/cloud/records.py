"""One pure function per kind: what a reader or report already returns -> Supabase records.

A record is a JSON-safe dict:

  {"kind", "key", "scope",                       what it is, and the unit a complete read covers
   "student_uid", "student_hng_id", "student_name", "passport_no", "day",   None when not known
   "data",        every field the reader parsed, with the reader's own keys (an object)
   "content",     the text form for search, built here, from fields that exist only (R1)
   "content_hash" sha256 hex of the canonical JSON of {kind, key, scope, data, content}
   "source",      where it came from ("students.php", "results.json", "brief"...)
   "read_at"}     when the bot read it, ISO with the +06:00 offset

Nothing is re-parsed here and nothing is filled in: a value the reader did not give is left out
of the text, never replaced by a stand-in, and the words a reader writes where the portal shows
nothing ("Unassigned", "Event", "Dashboard") are no value in data or text (R1). Nor are the words
the portal itself (or a student filling in its form) types in a field that has no value ("N/A",
"None", "--", "—", "PENDING", "TBD"..., and Cloudflare's "[email protected]" for an address the
parser could not decode: is_filler), in every kind read from the portal's own
fields: such a cell is "" in data, left out of the text, and its name is kept in
data["blank_on_portal"] (sorted; "details.<label>" for a students.php details field; only when
there is one), so Jeannie can say "not given on the portal" without a value being lost or made
up. A status field's "Pending" (a payment, a stage, a visa step: is_status_field) is data, never a
filler. The student_*, day and source columns are derived only from
the hashed fields (key, scope, data, content), because Supabase rewrites a record only when its
content_hash changes (hg_sync leaves a same-hash row as it is): the passport-keyed kinds put the
student's uid and HNG id in data when they are known. The one exception is field_correction, an
append-only record keyed by its own data, whose student columns are set when it is first sent.

Records are grouped for publishing with batch() (one kind and one scope) or batches() (one kind,
each record in its own scope: per day, per passport, per report).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

CLOUD_KINDS = (
    "student", "student_export", "student_profile", "student_progress", "student_documents",
    "verification", "consultation", "consultation_day", "consultation_totals", "pending_payment",
    "window_application", "dashboard_fact", "calendar_item", "passport_audit", "passport_alert",
    "passport_issue", "doc_verdict", "doc_check", "field_check", "field_correction", "doc_page_text",
    "report", "report_section", "brief_fact", "notification",
)

# students.php fields that change without the student changing: the list's row number (every new
# registration shifts it), the whole details row as one text (every select option's words in it)
# and "id" (the same as student_id). Left out, or every student would be sent again each time.
STUDENT_VOLATILE = ("sl", "details_text", "id")
# The CSV export's columns that are not trusted (04 §3.3): kept in data, marked, left out of the text.
STALE_EXPORT_COLUMNS = ["Current Stage", "Current Status", "Progress %"]
# The export has no pager and states no total: it counts as a whole read only when it has at least
# this share of the students the list (students.php, every page, pager checked) counts (R2).
EXPORT_SHARE = 0.9
# Passport audits that checked nothing (scheduler.UNCHECKED_STATUSES) and the cross-check's own
# "ERROR": publishing them would overwrite a real audit of the same scan.
UNCHECKED_AUDITS = ("MISSING_DOCUMENT", "PORTAL_UNREADABLE", "OCR_UNAVAILABLE", "ERROR")


# --------------------------------------------------------------------------- values

def _zone():
    from zoneinfo import ZoneInfo
    from src.config import settings
    return ZoneInfo(settings.REPORT_TIMEZONE)


def now() -> datetime:
    return datetime.now(_zone())


def as_read_at(value: Any = None) -> str:
    """A read time as ISO with the business time zone's offset ("2026-09-29T18:21:04+06:00"):
    None is now; a naive time (the stores write local Dhaka time without a zone) is Dhaka time; a
    date is its midnight; a text is read as ISO ("2026-09-27T15:19:01", "2026-09-29 18:21").
    A text that is no time at all is now."""
    if value is None or value == "":
        return now().isoformat(timespec="seconds")
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return now().isoformat(timespec="seconds")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=_zone())
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=_zone()).isoformat(timespec="seconds")
    return now().isoformat(timespec="seconds")


def iso_day(value: Any) -> Optional[str]:
    """A day as "YYYY-MM-DD": a date, a datetime, an ISO text ("2026-09-27T15:19:01"), or a portal
    text ("27 Sep 2026", "Applied On 27 Sep 2026, 17:16"). None when it names no full day."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    from src.dates import parse_portal_date
    day = parse_portal_date(text)
    return day.isoformat() if day else None


def _long_day(iso: Optional[str]) -> str:
    """"2026-09-28" -> "28 Sep 2026" (the portal's own way of writing a day)."""
    try:
        return f"{date.fromisoformat(iso):%d %b %Y}" if iso else ""
    except ValueError:
        return iso or ""


def clean_text(text: str) -> str:
    """A text Postgres accepts: no NUL characters, no unpaired surrogates (OCR text can hold both)."""
    if "\x00" in text:
        text = text.replace("\x00", "")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = text.encode("utf-8", "replace").decode("utf-8")
    return text


def jsonable(value: Any) -> Any:
    """`value` as plain JSON: dates as ISO text, named tuples and Counters as objects, tuples and
    sets as lists, every text cleaned (clean_text), a non-finite number as None."""
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "_asdict"):
        return jsonable(value._asdict())
    if isinstance(value, Mapping):
        return {clean_text(str(k)): jsonable(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return [jsonable(v) for v in sorted(value, key=str)]
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return clean_text(str(value))


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def content_hash(kind: str, key: str, scope: str, data: Dict[str, Any], content: str) -> str:
    """sha256 hex of the canonical JSON (sorted keys, UTF-8) of {kind, key, scope, data, content}."""
    obj = {"kind": kind, "key": key, "scope": scope, "data": data, "content": content}
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def sha1(*parts: Any) -> str:
    return hashlib.sha1("".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _uid(value: Any) -> Optional[int]:
    """A portal user id as the integer Supabase stores (None unless it is one: digits, int32)."""
    text = str(value if value is not None else "").strip()
    if text.isdigit() and 0 < int(text) < 2 ** 31:
        return int(text)
    return None


def _passport(value: Any) -> str:
    """A "Passport No" as an identity ("" for blank, "—" or a placeholder such as PENDING): R11."""
    from src.sheets.passport_issue import passport_key
    return passport_key(str(value or ""))


def _passport_value(value: Any) -> str:
    """A passport number field as data: the value as the portal prints it, or "" when it is no
    passport number at all (blank, "—", a placeholder such as PENDING: R1, R11)."""
    text = "" if value is None else str(value).strip()
    return text if _passport(text) else ""


# --------------------------------------------------------------------------- the portal's "no value" words

# What the portal (or a student filling in its form) types in a field that has no value, compared
# whole-cell, case-insensitively, on the cell's letters and digits alone after trimming ("N/A",
# "n.a." and "NA" are one word, "Not Available" is "notavailable"); a cell of marks only ("—",
# "--", "–", "-", "...") is no value either. Every marker progress_builder.clean_value blanks is
# here (na, n/a, n.a., none, null, not provided, not applicable, the dashes); unlike clean_value,
# a text in another script (Bangla) is a value: clean_value compares ASCII letters only, so it
# reads such a text as a mark. "NO", "NOT YET", "0" are answers, not fillers. Cloudflare's
# "[email protected]" ("emailprotected") is the stand-in of an address the page hid and the parser
# could not decode (parsers.decode_cf_emails): no address, so a cell of it alone is no value either.
FILLER_WORDS = frozenset({"na", "none", "null", "nil", "pending", "tbd", "notavailable", "notapplicable",
                          "notprovided", "emailprotected"})
# Fields whose "Pending" is a real state, not a stand-in for a value: every field whose name says
# status, stage, result or step (students.php's status = the stage, payment_status = the Payment
# column, docs_status; its details' Payment Status, Passport Status, Study Status; the export's
# Payment Status, Passport Status, Study Status, VIN Status, Visa Result, Current Stage, Current
# Status, Next Step; progress.php's stage and status; a consultation's or window application's
# status; student_edit.php's *_status fields), and these (a payment, a document or a VIN step).
STATUS_FIELDS = frozenset({"payment", "bank certificate", "bank solvency", "vin app", "vin required"})
_STATUS_NAME_RE = re.compile(r"\b(?:status|stage|result|step)\b")
BLANK_ON_PORTAL = "blank_on_portal"


def _filler_key(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def is_status_field(name: Any) -> bool:
    """Whether a field holds a state ("Payment Status", "payment_status", "Visa Result"...): its
    "Pending" is data (STATUS_FIELDS)."""
    n = re.sub(r"[\s_]+", " ", str(name or "")).strip().lower()
    return bool(_STATUS_NAME_RE.search(n)) or n in STATUS_FIELDS


def is_filler(value: Any, field: Any = "") -> bool:
    """Whether a cell holds one of the words the portal types for "no value" (FILLER_WORDS, or
    marks only) instead of data (R1). The cell `field`'s own name decides "Pending": in a status
    field it is data."""
    if not isinstance(value, str) or not value.strip():
        return False
    key = _filler_key(value)
    if not key:
        return True
    return key in FILLER_WORDS and not (key == "pending" and is_status_field(field))


def _blank_cells(fields: Mapping[str, Any], prefix: str = "") -> Tuple[Dict[str, Any], List[str]]:
    """`fields` with every filler cell (is_filler) as "" -> (the fields, the blanked cells' names,
    each led by `prefix`). Other values, lists and objects are kept as they are."""
    out: Dict[str, Any] = {}
    blanked: List[str] = []
    for k, v in fields.items():
        if is_filler(v, k):
            out[k] = ""
            blanked.append(f"{prefix}{k}")
        else:
            out[k] = v
    return out, blanked


def _passport_cell(fields: Dict[str, Any], name: str, blanked: List[str], prefix: str = "") -> None:
    """A passport number field as data (_passport_value); a value that is no passport number is
    blanked and named in `blanked` like a filler."""
    if name in fields:
        value = fields[name]
        fields[name] = _passport_value(value)
        if not fields[name] and str(value or "").strip():
            blanked.append(f"{prefix}{name}")


def _mark_blank(data: Dict[str, Any], blanked: Iterable[str]) -> Dict[str, Any]:
    """`data` with data["blank_on_portal"] = the sorted names in `blanked`, when there are any."""
    names = sorted({str(b) for b in blanked})
    if names:
        data[BLANK_ON_PORTAL] = names
    return data


def _given(value: Any) -> Any:
    """A value as it is, a filler as ""."""
    return "" if is_filler(value) else value


# Words the readers write where the portal shows nothing (they are not the portal's data: R1).
FILLED_CONSULTANT = "Unassigned"      # parsers._consultation_table_rows, for a blank or "—" consultant
FILLED_CALENDAR_KIND = "Event"        # ask.calendar_items, for an item whose kind the page does not show
FILLED_TILE_GROUP = "Dashboard"       # ask.dashboard_facts, for a tile outside every tile group


def _ids_of(ids: Any) -> Tuple[str, str]:
    """(portal uid, HNG id) of a student, from (uid, hng) or {"uid", "hng"}; "" for each not known."""
    if isinstance(ids, Mapping):
        uid, hng = ids.get("uid"), ids.get("hng")
    elif isinstance(ids, (tuple, list)) and len(ids) == 2:
        uid, hng = ids
    else:
        uid = hng = None
    uid = str(uid or "").strip()
    return (uid if _uid(uid) is not None else ""), str(hng or "").strip()


def make(kind: str, key: Any, scope: Any, data: Mapping[str, Any], content: str, source: str,
         read_at: Any = None, *, uid: Any = None, hng: Any = None, name: Any = None,
         passport: Any = None, day: Any = None) -> Dict[str, Any]:
    """One record, cleaned and hashed (see the module docstring)."""
    key, scope = clean_text(str(key)), clean_text(str(scope))
    data = jsonable(dict(data))
    content = clean_text(content or "").strip()

    def opt(v):
        v = clean_text(str(v)).strip() if v not in (None, "") else ""
        return v or None

    return {"kind": kind, "key": key, "scope": scope,
            "student_uid": _uid(uid), "student_hng_id": opt(hng), "student_name": opt(name),
            "passport_no": opt(passport), "day": iso_day(day),
            "data": data, "content": content, "content_hash": content_hash(kind, key, scope, data, content),
            "source": source, "read_at": as_read_at(read_at)}


def unique_keys(records: Iterable[Optional[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """The records (None dropped) with a key that repeats given "#2", "#3"... in order, so two
    records never overwrite each other (the sheet sync's own rule for its row keys)."""
    out, seen = [], {}
    for r in records:
        if r is None:
            continue
        base = r["key"]
        n = seen.get(base, 0) + 1
        seen[base] = n
        if n > 1:
            key = f"{base}#{n}"
            while key in seen:
                n += 1
                key = f"{base}#{n}"
            seen[key] = 1
            r = dict(r, key=key)
            r["content_hash"] = content_hash(r["kind"], key, r["scope"], r["data"], r["content"])
        out.append(r)
    return out


def batch(kind: str, scope: str, rows: Sequence[Dict[str, Any]], complete: bool,
          all_keys: Optional[Iterable[str]] = None, read_at: Any = None) -> Dict[str, Any]:
    """One (kind, scope) to publish: `rows` are every record the read saw (not only the changed
    ones: publishing sends only those whose hash changed); `complete` only when the read was whole
    (every page, pager total matched, no error): Supabase then deletes the (kind, scope)'s other
    records. A partial or failed read is complete=False, and deletes nothing.

    `all_keys`, with complete=True, is the whole key list when `rows` hold only some of the
    records (the passport watcher audits only new scans, but its complete list read names every
    scan there is: all_keys = every "uid|file" listed now). The records to keep are then those
    keys and the rows' own.

    `read_at`: when the read that makes the batch whole was made, when that is not its rows' own
    read_at (the watcher's audits come after its list read; a store's records carry the time each
    was checked). Publishing orders reads of one scope by it: by default the rows' earliest."""
    out = {"kind": kind, "scope": scope, "complete": bool(complete), "rows": list(rows)}
    if all_keys is not None:
        out["all_keys"] = sorted({str(k) for k in all_keys if k not in (None, "")})
    if read_at not in (None, ""):
        out["read_at"] = as_read_at(read_at)
    return out


def batches(kind: str, rows: Sequence[Dict[str, Any]], complete: bool,
            scope_range: Optional[Tuple[str, str]] = None, read_at: Any = None) -> Dict[str, Any]:
    """Records of one kind in several scopes (each record's own: a day, a passport, a report and
    day): published one scope at a time. With complete=True every scope that has records is
    complete; with `scope_range` (lo, hi), also every scope the bot published before that lies in
    lo..hi (text order: ISO days) and has no record now is emptied (its records are gone).
    `read_at` (see batch): the one read time of every scope, the emptied ones included."""
    out = {"kind": kind, "scope": None, "complete": bool(complete), "rows": list(rows)}
    if scope_range:
        out["scope_range"] = [str(scope_range[0]), str(scope_range[1])]
    if read_at not in (None, ""):
        out["read_at"] = as_read_at(read_at)
    return out


# --------------------------------------------------------------------------- text helpers

def _sentence(*parts: str, end: str = ".") -> str:
    text = " ".join(p for p in parts if p).strip()
    return (text if text.endswith((".", "!", "?", ":")) else text + end) if text else ""


def _paragraph(*sentences: str) -> str:
    return " ".join(s for s in sentences if s)


def _pairs(fields: Mapping[str, Any], skip: Iterable[str] = ()) -> str:
    """"Label: value; Label: value" for every field with a value (lists joined), `skip` left out."""
    skip = set(skip)
    out = []
    for k, v in fields.items():
        if k in skip or v in (None, "", [], {}):
            continue
        if isinstance(v, (list, tuple)):
            v = ", ".join(str(x) for x in v if x not in (None, ""))
        elif isinstance(v, dict):
            continue
        v = str(v).strip()
        if v:
            out.append(f"{k}: {v}")
    return "; ".join(out)


def _ids(*ids: str) -> str:
    shown = [i for i in ids if i]
    return f" ({', '.join(shown)})" if shown else ""


# --------------------------------------------------------------------------- students.php

_STUDENT_TEXT_LABELS = {"Full Name", "Program", "Intake", "Applied On", "Payment Status", "Passport No",
                        "Passport Expiry", "Passport Status", "DOB", "Gender", "Mobile", "Email",
                        "Guardian WhatsApp", "Father", "Mother", "Address", "District", "Consultant"}


def student_text(s: Mapping[str, Any]) -> str:
    """The text form of one students.php record (parse_students_page)."""
    from src.scraper.parsers import payment_text
    d = s.get("details") or {}
    name = s.get("student_name") or d.get("Full Name") or ""
    uid = str(s.get("uid") or "")
    ids = _ids(s.get("student_id") or "", f"portal uid {uid}" if uid else "")
    program, intake = s.get("program") or "", s.get("target_intake") or ""
    stage, applied = s.get("status") or "", s.get("applied_date") or ""
    pay = payment_text({"paid": s.get("paid"), "verified_income": s.get("verified_income"),
                        "method": s.get("method"), "amount": s.get("verified_income") or s.get("paid")})
    by, stamp = s.get("verified_by") or "", s.get("verified_stamp") or ""
    verified = (f"verified by {by} on {stamp}" if by and stamp else f"verified by {by}" if by
                else f"verified on {stamp}" if stamp else "")
    passport = _passport_value(d.get("Passport No"))
    address = ", ".join(x for x in (d.get("Address"), d.get("District") and f"district {d.get('District')}") if x)
    others = _pairs({k: v for k, v in d.items() if k not in _STUDENT_TEXT_LABELS})
    return _paragraph(
        _sentence(f"Student {name}{ids}" if name else f"Student{ids}"),
        _sentence(", ".join(x for x in (program and f"Program {program}", intake and f"intake {intake}") if x)),
        _sentence(", ".join(x for x in (stage and f"Stage: {stage}", applied and f"applied {applied}") if x)),
        _sentence(f"Applied on {s.get('applied_on')}") if s.get("applied_on") and not applied else "",
        _sentence(f"University: {s.get('target_university')}") if s.get("target_university") else "",
        _sentence("Applications: " + "; ".join(s.get("applications"))) if s.get("applications") else "",
        _sentence(f"Documents: {s.get('docs_status')}") if s.get("docs_status") else "",
        _sentence(f"Payment status: {s.get('payment_status')}") if s.get("payment_status") else "",
        _sentence(", ".join(x for x in (pay and f"Payment {pay}", verified) if x)),
        _sentence(", ".join(x for x in (passport and f"Passport {passport}",
                                        d.get("Passport Expiry") and f"expires {d.get('Passport Expiry')}",
                                        d.get("Passport Status") and f"status {d.get('Passport Status')}") if x)),
        _sentence(f"Date of birth {d.get('DOB')}") if d.get("DOB") else "",
        _sentence(f"Gender {d.get('Gender')}") if d.get("Gender") else "",
        _sentence(f"Mobile {d.get('Mobile')}") if d.get("Mobile") else "",
        _sentence(f"Email {d.get('Email')}") if d.get("Email") else "",
        _sentence(f"Guardian WhatsApp {d.get('Guardian WhatsApp')}") if d.get("Guardian WhatsApp") else "",
        _sentence(f"Father {d.get('Father')}") if d.get("Father") else "",
        _sentence(f"Mother {d.get('Mother')}") if d.get("Mother") else "",
        _sentence(f"Address {address}") if address else "",
        _sentence(f"Consultant {d.get('Consultant')}") if d.get("Consultant") else "",
        _sentence(f"Other details: {others}") if others else "",
    )


def _student_fields(s: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """A students.php record's fields as data -> (the fields, the cells blanked): the volatile ones
    left out, every list cell and details field that holds a filler word blanked (is_filler), and
    a placeholder passport number ("PENDING") blanked, as no identity is no value either (R1,
    R11)."""
    out, blanked = _blank_cells({k: v for k, v in s.items()
                                 if k not in STUDENT_VOLATILE and not str(k).startswith("_")})
    d = out.get("details")
    if isinstance(d, Mapping):
        d, more = _blank_cells(d, "details.")
        _passport_cell(d, "Passport No", more, "details.")
        out["details"], blanked = d, blanked + more
    return out, blanked


def student(s: Mapping[str, Any], read_at: Any = None) -> Optional[Dict[str, Any]]:
    """kind student, key = the portal uid, scope all: one read_students record (every list column,
    the ~50 details, the file names, the payment chips and stamp, the applications), the portal's
    fillers blanked and named in blank_on_portal. None for a row without a uid (its fallback key is
    not stable: R11)."""
    uid = str(s.get("uid") or "").strip()
    if _uid(uid) is None:
        return None
    fields, blanked = _student_fields(s)
    d = fields.get("details") or {}
    return make("student", uid, "all", _mark_blank(dict(fields), blanked), student_text(fields), "students.php",
                read_at, uid=uid, hng=fields.get("student_id"), name=fields.get("student_name") or d.get("Full Name"),
                passport=_passport(d.get("Passport No")),
                day=iso_day(fields.get("applied_on")) or iso_day(fields.get("applied_date")))


def students(rows: Iterable[Mapping[str, Any]], read_at: Any = None) -> List[Dict[str, Any]]:
    """student() for every row, each uid once (the first), rows without a uid left out."""
    out, seen = [], set()
    for s in rows:
        r = student(s, read_at)
        if r is not None and r["key"] not in seen:
            seen.add(r["key"])
            out.append(r)
    return out


def pending_payments(rows: Iterable[Mapping[str, Any]], badge: Optional[int],
                     read_at: Any = None) -> List[Dict[str, Any]]:
    """kind pending_payment, key uid, scope all: the students of every page of
    students.php?status=pending whose own Payment column says Pending (the page also lists
    others), each with the portal's own Pending Payments badge in data ("badge", None when the page
    showed none)."""
    out, seen = [], set()
    for s in rows:
        uid = str(s.get("uid") or "").strip()
        if _uid(uid) is None or uid in seen:
            continue
        if re.sub(r"[^a-z]", "", str(s.get("payment_status") or "").lower()) != "pending":
            continue
        seen.add(uid)
        fields, blanked = _student_fields(s)
        d = fields.get("details") or {}
        data = _mark_blank(dict(fields, badge=badge), blanked)
        text = _paragraph("Pending payment (students.php?status=pending).", student_text(fields),
                          _sentence(f"The portal's Pending Payments badge shows {badge}") if badge is not None else "")
        out.append(make("pending_payment", uid, "all", data, text, "students.php?status=pending", read_at,
                        uid=uid, hng=fields.get("student_id"), name=fields.get("student_name") or d.get("Full Name"),
                        passport=_passport(d.get("Passport No")),
                        day=iso_day(fields.get("applied_on")) or iso_day(fields.get("applied_date"))))
    return out


def pending_complete(pending: Sequence[Any], badge: Optional[int], empty_page: bool = False) -> bool:
    """Whether a whole read of students.php?status=pending (every page, each page's layout known)
    may delete the pending payments it no longer shows: only when its rows can be checked against
    the page itself (R5, R8). With the portal's Pending Payments badge, the rows whose own Payment
    says Pending must be exactly that many; without one, some row must say Pending, or the list
    must show its own empty state ("No students found"). The Payment column is not one the list
    must have, so rows none of which say Pending mean it was not read (a renamed header), and an
    empty filtered list is not by itself "nobody"."""
    if badge is not None:
        return len(pending) == badge
    return bool(pending) or bool(empty_page)


def verification(v: Mapping[str, Any], day: Any, read_at: Any = None) -> Optional[Dict[str, Any]]:
    """kind verification, key uid, scope the stamp's ISO day: one parsers.verification() result
    (verifier, time, amount, method, paid and verified income) for `day`."""
    from src.scraper.parsers import payment_text
    uid = str(v.get("uid") or "").strip()
    iso = iso_day(day)
    if _uid(uid) is None or not iso:
        return None
    v, blanked = _blank_cells(dict(v))
    data = _mark_blank(dict(v, day=iso), blanked)
    pay = payment_text(v)
    name = v.get("name") or ""
    when = v.get("verified_time") or ""
    text = _paragraph(
        _sentence("Payment verification" + (f" of {name}" if name else "")
                  + f"{_ids(v.get('student_id') or '', f'portal uid {uid}')}"
                  + (f", {v.get('program')}" if v.get("program") else "")),
        _sentence((f"Verified by {v.get('verified_by')}, on " if v.get("verified_by") else "Verified on ")
                  + (f"{when} ({_long_day(iso)})" if when else _long_day(iso))),
        _sentence(f"Amount {pay}") if pay else "")
    return make("verification", uid, iso, data, text, "students.php", read_at,
                uid=uid, hng=v.get("student_id"), name=name, day=iso)


def verification_window(today: date) -> Tuple[str, str]:
    """The days (lo, hi as ISO) a yearless verification stamp can be dated on: the last year up to
    today (src.dates.yearless_day_problem)."""
    from src.dates import yearless_day_problem
    lo = today - timedelta(days=367)
    while yearless_day_problem(lo, today):
        lo += timedelta(days=1)
    return lo.isoformat(), today.isoformat()


def verification_day(s: Mapping[str, Any], today: date) -> Optional[date]:
    """The day a students.php record's payment was verified, from its own stamp: the one day in
    the last year (or the stamp's own year) that parsers.verification accepts; None when its
    stamp is missing, unreadable or too old to date."""
    from src.dates import parse_stamp, yearless_day_problem
    from src.scraper.parsers import verification as verify
    stamp = parse_stamp(s.get("verified_stamp") or "")
    if stamp is None:
        return None
    years = [stamp.year] if stamp.year else [today.year, today.year - 1]
    for y in years:
        try:
            d = date(y, stamp.month, stamp.day)
        except ValueError:
            continue
        if d > today or (not stamp.year and yearless_day_problem(d, today)):
            continue
        if verify(dict(s), d) is not None:
            return d
    return None


def verifications(rows: Iterable[Mapping[str, Any]], today: date, read_at: Any = None) -> List[Dict[str, Any]]:
    """verification() of every students.php record whose stamp can be dated (verification_day):
    records in many day scopes (publish them with batches(..., scope_range=verification_window))."""
    from src.scraper.parsers import verification as verify
    out = []
    for s in rows:
        d = verification_day(s, today)
        if d is not None:
            r = verification(verify(dict(s), d), d, read_at)
            if r is not None:
                out.append(r)
    return unique_keys(out)


def student_documents(rows: Iterable[Mapping[str, Any]], read_at: Any = None) -> List[Dict[str, Any]]:
    """kind student_documents, key uid, scope all: the verified-documents list
    (verified_docs.fetch_verified_students: uid, name, passport, program and the "|"-joined file
    names, the fingerprint). File names only, never the files."""
    out, seen = [], set()
    for row in rows:
        uid = str(row.get("uid") or "").strip()
        if _uid(uid) is None or uid in seen:
            continue
        seen.add(uid)
        # The list's cells as data, the portal's "—" and other fillers as "" and a placeholder
        # passport as none (R1), each named in blank_on_portal.
        data, blanked = _blank_cells(dict(row))
        _passport_cell(data, "passport", blanked)
        files = [f for f in str(data.get("docs") or "").split("|") if f]
        data = _mark_blank(dict(data, files=files), blanked)
        name, passport, program = data.get("name") or "", data.get("passport") or "", data.get("program") or ""
        text = _paragraph(
            _sentence("Verified documents on the portal" + (f" of {name}" if name else "")
                      + _ids(passport and f"passport {passport}", program, f"portal uid {uid}")),
            _sentence(f"{len(files)} files: " + ", ".join(files)) if files else "")
        out.append(make("student_documents", uid, "all", data, text,
                        "students.php?source=direct&filter_docs=verified", read_at,
                        uid=uid, name=name, passport=_passport(passport)))
    return out


def student_exports(rows: Iterable[Mapping[str, str]], read_at: Any = None) -> List[Dict[str, Any]]:
    """kind student_export, key = the sheet sync's row key (Student ID: / Passport No: / NAME:,
    "#2" for a repeat), scope all: every row of students.php?export=csv with all its columns, and
    "stale_columns" (Current Stage, Current Status and Progress % are not trusted: 04 §3.3)."""
    from src.sheets import progress_builder as pb
    from src.sheets.auto_sync import _row_key
    out = []
    for row in rows:
        row = {str(k): ("" if v is None else v) for k, v in dict(row).items() if k is not None}
        key = _row_key(dict(row, Mobile=pb.normalize_phone(row.get("Mobile", ""))))
        # Every column, each cell trimmed: the export's "N/A", "—", "none", a "PENDING" date... are
        # no value, the same words as in the student list (is_filler: every marker
        # progress_builder.clean_value blanks, and a Bangla text kept), and a placeholder passport
        # is none (R1); each is named in blank_on_portal.
        cells, blanked = _blank_cells({k: str(v).strip() for k, v in row.items()})
        _passport_cell(cells, "Passport No", blanked)
        data = _mark_blank(dict(cells, stale_columns=list(STALE_EXPORT_COLUMNS)), blanked)
        name, hng = cells.get("Full Name", ""), cells.get("Student ID", "")
        fields = _pairs(cells, skip=set(STALE_EXPORT_COLUMNS) | {"Full Name", "Student ID"})
        text = _paragraph(_sentence("Student export row (students.php?export=csv)"
                                    + (f": {name}" if name else "") + _ids(hng)),
                          _sentence(fields) if fields else "")
        out.append(make("student_export", key, "all", data, text, "students.php?export=csv", read_at,
                        hng=hng, name=name, passport=_passport(row.get("Passport No")),
                        day=iso_day(cells.get("Applied On"))))
    return unique_keys(out)


def export_complete(rows: Sequence[Mapping[str, Any]], listed: Optional[int]) -> Tuple[bool, str]:
    """Whether a students.php?export=csv read is whole -> (complete, why not). It must have its
    header (Student ID and Full Name) and at least EXPORT_SHARE of `listed`, the students a whole
    read of the list counts; with no such count known it cannot be proven whole (a stream cut
    short after its header still parses)."""
    if not rows or not {"Student ID", "Full Name"} <= set(rows[0]):
        return False, "students.php?export=csv: no Student ID and Full Name header"
    if not listed:
        return False, "students.php?export=csv: no whole student list to check its row count by"
    if len(rows) < EXPORT_SHARE * listed:
        return False, (f"students.php?export=csv: {len(rows)} rows, fewer than {EXPORT_SHARE:.0%} of the "
                       f"{listed} students the list shows")
    return True, ""


def student_profile(uid: Any, fields: Mapping[str, Any], read_at: Any = None) -> Optional[Dict[str, Any]]:
    """kind student_profile, key = scope = uid: student_edit.php's form as
    HangeulAdminClient._profile_fields reads it (every filled field, by its form name), the
    portal's fillers blanked and named in blank_on_portal. None when it shows no profile (no name
    or full_name: the page was not the profile)."""
    uid = str(uid or "").strip()
    fields, blanked = _blank_cells({str(k): v for k, v in dict(fields or {}).items()})
    _passport_cell(fields, "passport_number", blanked)
    name = fields.get("full_name") or fields.get("name") or ""
    if _uid(uid) is None or not name:
        return None
    pairs = _pairs({k.replace("_", " "): v for k, v in fields.items() if k not in ("id", "save")})
    text = _paragraph(_sentence(f"Student profile (student_edit.php) of {name}{_ids(f'portal uid {uid}')}"),
                      _sentence(pairs) if pairs else "")
    return make("student_profile", uid, uid, _mark_blank(fields, blanked), text, "student_edit.php", read_at,
                uid=uid, name=name, passport=_passport(fields.get("passport_number")))


def student_progress(progress: Mapping[str, Mapping[str, Any]],
                     listed: Optional[Mapping[str, Mapping[str, Any]]] = None,
                     read_at: Any = None) -> List[Dict[str, Any]]:
    """kind student_progress, key uid, scope all: stage_report.read_progress's pages
    ({uid: {"pct", "stage", "status"}}); an entry that could not be read ({"error"}) is left out.
    `listed` ({uid: students.php record}) adds the student's HNG id and name. A filler is blanked
    and named in blank_on_portal (the stage's and status's "Pending" is a status, kept)."""
    out = []
    for uid, p in (progress or {}).items():
        uid = str(uid).strip()
        if _uid(uid) is None or not isinstance(p, Mapping) or p.get("error") or "pct" not in p:
            continue
        s = (listed or {}).get(uid) or {}
        hng = _given(s.get("student_id")) or ""
        name = _given(s.get("student_name")) or _given((s.get("details") or {}).get("Full Name")) or ""
        p, blanked = _blank_cells(dict(p))
        data = _mark_blank(dict(p), blanked)
        if hng:
            data["student_id"] = hng
        if name:
            data["student_name"] = name
        text = _sentence("Progress" + (f" of {name}" if name else "") + f"{_ids(hng, f'portal uid {uid}')} on "
                         "progress.php: "
                         + ", ".join(x for x in (p.get("pct") not in (None, "") and f"{p.get('pct')}% overall",
                                                 p.get("stage") and f"current stage {p.get('stage')}",
                                                 p.get("status") and f"status {p.get('status')}") if x))
        out.append(make("student_progress", uid, "all", data, text, "progress.php", read_at,
                        uid=uid, hng=hng, name=name))
    return out


# --------------------------------------------------------------------------- consult_requests.php

def consultation(row: Mapping[str, Any], day: Any, read_at: Any = None) -> Dict[str, Any]:
    """kind consultation, key = the request's portal id (the row's "id": the hidden id of its own
    forms, parsers._consultation_table_rows), else sha1 of name + contact + received (the key then
    changes when the name or contact is edited: a delete and a new record, not an edit); scope =
    the received ISO day. Every field of the row, except the reader's "Unassigned" for a request
    with no consultant, which is no value (R1), and a cell that holds only a filler word (blanked
    and named in blank_on_portal; the words inside a longer text, such as the form's details, are
    the text's own)."""
    iso = iso_day(day) or iso_day(row.get("received_date")) or ""
    rid = str(row.get("id") or "").strip()
    key = rid if rid.isdigit() else sha1(row.get("name", ""), row.get("contact", ""), row.get("received", ""))
    row, blanked = _blank_cells(dict(row))
    if str(row.get("consultant") or "").strip() == FILLED_CONSULTANT:
        row["consultant"] = ""
    by = row.get("handled_by") or ""
    text = _paragraph(
        _sentence("Consultation request" + (f" from {row.get('name')}" if row.get("name") else "")
                  + (f" ({row.get('contact')})" if row.get("contact") else "")
                  + (f", received {row.get('received')}" if row.get("received") else "")),
        _sentence(f"City {row.get('city')}") if row.get("city") else "",
        _sentence(f"Program {row.get('program')}") if row.get("program") else "",
        _sentence(f"Consultant {row.get('consultant')}") if row.get("consultant") else "",
        _sentence(", ".join(x for x in (row.get("status") and f"Status: {row.get('status')}",
                                        by and f"last updated by {by}") if x)),
        _sentence(f"Details: {row.get('details')}") if row.get("details") else "",
        _sentence(f"Remarks: {row.get('remarks')}") if row.get("remarks") else "")
    return make("consultation", key, iso, _mark_blank(row, blanked), text,
                f"consult_requests.php?status=all&from={iso}&to={iso}", read_at, name=row.get("name"), day=iso)


def consultations(on_day: Mapping[str, Any], read_at: Any = None) -> Tuple[List[Dict[str, Any]], bool]:
    """read_consultation_day(day) -> (its rows as consultation records, whether it listed every
    request of the day: only then is the day's scope complete)."""
    day = on_day.get("day")
    rows = [consultation(r, day, read_at) for r in on_day.get("rows") or []]
    return unique_keys(rows), bool(on_day.get("complete"))


def consultation_day(on_day: Mapping[str, Any], read_at: Any = None) -> Optional[Dict[str, Any]]:
    """kind consultation_day, key = the ISO day, scope all: the day's status-tab counts from
    read_consultation_day (the portal's own date filter; "All" is how many were received)."""
    iso = iso_day(on_day.get("day"))
    counts = dict(on_day.get("counts") or {})
    if not iso or not counts:
        return None
    data = {"day": iso, "counts": counts, "listed": len(on_day.get("rows") or []),
            "complete": bool(on_day.get("complete"))}
    text = _sentence(f"Consultation requests received on {_long_day(iso)} (the portal's date filter): "
                     + "; ".join(f"{k} {v}" for k, v in counts.items()))
    return make("consultation_day", iso, "all", data, text,
                f"consult_requests.php?status=all&from={iso}&to={iso}", read_at, day=iso)


def consultation_totals(totals: Mapping[str, Any], read_at: Any = None) -> Optional[Dict[str, Any]]:
    """kind consultation_totals, key all, scope all: read_consultation_totals() (the status tabs,
    which count every request, all time)."""
    totals = dict(totals or {})
    if not totals:
        return None
    text = _sentence("All-time consultation requests (the status tabs of consult_requests.php): "
                     + "; ".join(f"{k} {v}" for k, v in totals.items()))
    return make("consultation_totals", "all", "all", {"counts": totals}, text,
                "consult_requests.php?status=file_opened", read_at)


# --------------------------------------------------------------------------- other portal pages

def window_applications(rows: Iterable[Mapping[str, Any]], read_at: Any = None) -> List[Dict[str, Any]]:
    """kind window_application, key student|window, scope all: the rows of
    window_applications.php?status=under_review whose own status is under review (parsers
    count_under_review's rule). A filler cell is blanked and named in blank_on_portal."""
    from src.scraper.parsers import _label_key
    out = []
    for row in rows or []:
        if _label_key(str(row.get("status") or "")) != "under review":
            continue
        key = f"{row.get('student', '')}|{row.get('window', '')}"
        row, blanked = _blank_cells(dict(row))
        text = _sentence("Window application" + (f" of {row.get('student')}" if row.get("student") else "")
                         + (f" for {row.get('window')}" if row.get("window") else "")
                         + f": {row.get('status')} (window_applications.php)")
        out.append(make("window_application", key, "all", _mark_blank(row, blanked), text,
                        "window_applications.php?status=under_review", read_at, name=row.get("student")))
    return unique_keys(out)


def window_complete(rows: Sequence[Any], records_: Sequence[Any], paged: bool) -> bool:
    """Whether a read of window_applications.php?status=under_review may delete the applications
    it no longer shows (R5, R8): the page has no pager (it states no total to prove more pages
    by), and it is either its own empty table or has a row whose own status is under review. Rows
    none of which say so mean the status wording was not recognised, not that nobody is waiting."""
    return not paged and (not rows or bool(records_))


def dashboard_facts(facts: Iterable[Any], read_at: Any = None) -> List[Dict[str, Any]]:
    """kind dashboard_fact, key group|label ("#2" for a repeat), scope all: ask.dashboard_facts
    (index.php's tiles and cards, each Fact(group, label, value, text, note))."""
    out = []
    for f in facts or []:
        f = f._asdict() if hasattr(f, "_asdict") else dict(f)
        if f.get("group") == FILLED_TILE_GROUP:
            f["group"] = ""           # ask.dashboard_facts' word for a tile outside every group (R1)
        label, value = f.get("label") or "", f.get("text")
        what = " — ".join(x for x in (label, f.get("note") or "") if x)
        text = _sentence(f"Dashboard (index.php)" + (f", {f.get('group')}" if f.get("group") else "")
                         + (f": {what}" if what else "")
                         + (f": {value}" if value not in (None, "") else ""))
        out.append(make("dashboard_fact", f"{f.get('group') or ''}|{label}", "all", f, text,
                        "index.php", read_at))
    return unique_keys(out)


def tile_facts(tiles: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """client.get_dashboard()'s tiles (group, label, value, text) as the facts ask.dashboard_facts
    makes of the same tiles (note ""), so a tile is one record, with one hash, whichever read it
    came from (the brief, /stats, the hourly full picture). Tiles only, no cards: publish them
    with complete=False. A tile outside every group has no group ("", never a stand-in)."""
    return [{"group": t.get("group") or "", "label": t["label"], "value": t.get("value"),
             "text": t.get("text") or "", "note": ""}
            for t in tiles or [] if isinstance(t, Mapping) and t.get("label")]


# The dashboard's groups a whole read shows: its two tile sections and the five cards ask reads.
DASHBOARD_GROUPS = ("Admissions flow", "Direct / legacy pipeline", "At a glance", "Needs attention",
                    "Application pipeline", "Applications by program", "Top universities")


def dashboard_complete(facts: Iterable[Any]) -> bool:
    """Whether a dashboard read shows every group (its tiles and cards): only then may facts that
    are gone be deleted (a card missing from the page cannot be told from a card with no items)."""
    groups = {(f._asdict() if hasattr(f, "_asdict") else dict(f)).get("group") for f in facts or []}
    return all(g in groups for g in DASHBOARD_GROUPS)


def calendar_items(items: Iterable[Any], read_at: Any = None) -> List[Dict[str, Any]]:
    """kind calendar_item, key = the portal's event id (else sha1 of title, start and note), scope
    all: ask.calendar_items (the month's event list, today's reminders and the 45-day timeline,
    merged). calendar.php shows only this month and the next 45 days, so a read is never complete
    for all items: publish them with complete=False (nothing deleted). A filler cell (a title,
    place or note that says only "N/A"...) is blanked and named in blank_on_portal."""
    out = []
    for it in items or []:
        it = it._asdict() if hasattr(it, "_asdict") else dict(it)
        if it.get("kind") == FILLED_CALENDAR_KIND:
            it["kind"] = ""           # ask.calendar_items' word for a kind the page does not show (R1)
        cid = str(it.get("id") or "").strip()
        key = cid or "t:" + sha1(it.get("title", ""), "|", jsonable(it.get("start")) or "", "|", it.get("note", ""))
        it, blanked = _blank_cells(it)
        data = _mark_blank(jsonable(it), blanked)
        start, end = data.get("start"), data.get("end")
        when = (f"from {_long_day(start)} to {_long_day(end)}" if start and end and start != end
                else f"on {_long_day(end or start)}" if (start or end) else "")
        text = _paragraph(
            _sentence("Calendar (calendar.php)" + (f": {it.get('title')}" if it.get("title") else "")
                      + (f" — {it.get('kind')}" if it.get("kind") else "")
                      + (f" at {it.get('where')}" if it.get("where") else "")
                      + (f", {when}" if when else "")
                      + (", done" if it.get("done") else "")),
            _sentence(f"Note: {it.get('note')}") if it.get("note") else "")
        out.append(make("calendar_item", key, "all", data, text, "calendar.php", read_at, day=end or start))
    return unique_keys(out)


# --------------------------------------------------------------------------- passports

def passport_audit(uid: Any, scan: str, result: Mapping[str, Any], read_at: Any = None,
                   student: Optional[Mapping[str, Any]] = None,
                   form: Optional[Mapping[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """kind passport_audit, key uid|file, scope all: one audit_student_passport result (status,
    is_valid, the fields compared, MRZ and visual readings, discrepancies, uncertain, verdict), with
    the portal values it was compared with (`form`) and the student's HNG id and name. None for an
    audit that checked nothing (UNCHECKED_AUDITS): it would overwrite a real one."""
    uid = str(uid or "").strip()
    if _uid(uid) is None or not scan or not isinstance(result, Mapping):
        return None
    if str(result.get("status") or "") in UNCHECKED_AUDITS:
        return None
    s = student or {}
    hng = s.get("student_id") or ""
    name = (form or {}).get("name") or s.get("student_name") or (s.get("details") or {}).get("Full Name") or ""
    fields = result.get("fields") or {}
    data = {"uid": uid, "file": scan, "result": dict(result)}
    if form:
        data["form"] = dict(form)
    if hng:
        data["student_id"] = hng
    if name:
        data["student_name"] = name
    compared = []
    for field, f in fields.items():
        if isinstance(f, Mapping):
            bits = ", ".join(x for x in (f.get("portal") and f"portal {f.get('portal')}",
                                         f.get("doc") and f"scan {f.get('doc')}", f.get("status")) if x)
            if bits:
                compared.append(f"{field.replace('_', ' ')}: {bits}")
    passport = (fields.get("passport_no") or {}).get("portal") if isinstance(fields.get("passport_no"), Mapping) else ""
    text = _paragraph(
        _sentence("Passport audit" + (f" of {name}" if name else "") + f"{_ids(hng, f'portal uid {uid}')}, scan {scan}"
                  + (f": {result.get('status')}" if result.get("status") else "")),
        _sentence(str(result.get("verdict"))) if result.get("verdict") else "",
        _sentence("Discrepancies: " + "; ".join(str(x) for x in result.get("discrepancies"))) if result.get("discrepancies") else "",
        _sentence("Check by eye: " + "; ".join(str(x) for x in result.get("uncertain"))) if result.get("uncertain") else "",
        _sentence("Compared: " + "; ".join(compared)) if compared else "")
    return make("passport_audit", f"{uid}|{scan}", "all", data, text, "view_doc.php + student_edit.php", read_at,
                uid=uid, hng=hng, name=name, passport=_passport(passport or (form or {}).get("passport_no")))


def passport_alerts(memory: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """kind passport_alert, key uid|file, scope all: every entry of the passport watcher's memory
    (data/alerted_passport_issues.json v2: status, checked, the alert text, sent, sent_at). A
    publish of it is complete over the scans the student list shows (bot_jobs.watched_scans as
    all_keys): a memory that was lost restarts empty, and the alerts about scans it has not audited
    again are kept until it has."""
    out = []
    for key, e in ((memory or {}).get("scans") or {}).items():
        if not isinstance(e, Mapping) or "|" not in str(key):
            continue
        uid, scan = str(key).split("|", 1)
        data = dict(e, file=scan)
        alert = e.get("alert")
        said = (f"Alert sent {e.get('sent_at')}: {alert}" if alert and e.get("sent") and e.get("sent_at")
                else f"Alert sent: {alert}" if alert and e.get("sent")
                else f"Alert not sent yet: {alert}" if alert else "No alert was raised.")
        text = _paragraph(
            _sentence(f"Passport watcher memory for portal uid {uid}{_ids(e.get('student_id') or '')}, scan {scan}: "
                      + ", ".join(x for x in (e.get("status") and f"status {e.get('status')}",
                                              e.get("checked") and f"checked {e.get('checked')}") if x)),
            said)
        out.append(make("passport_alert", key, "all", data, text, "alerted_passport_issues.json",
                        e.get("sent_at") or e.get("checked"), uid=uid, hng=e.get("student_id"),
                        day=iso_day(e.get("checked"))))
    return out


def passport_issues(by_passport: Mapping[str, Any], read_at: Any = None) -> List[Dict[str, Any]]:
    """kind passport_issue, key = the passport number, scope all: data/passport_issue.json
    ({"by_passport": {passport: "YYYY-MM-DD"}}, the 08:30 refresh of student_edit.php)."""
    out = []
    for pas, issued in (by_passport or {}).items():
        key = _passport(pas)
        if not key or not issued:
            continue
        text = _sentence(f"Passport {key}: issue date {issued} (student_edit.php, read by the daily refresh)")
        out.append(make("passport_issue", key, "all", {"passport_no": key, "issue_date": issued}, text,
                        "passport_issue.json", read_at, passport=key))
    return out


# --------------------------------------------------------------------------- the document check

def _joined(*parts: Any, sep: str = " ") -> str:
    """The parts that have a value, joined (a missing one is left out, never written as a word)."""
    return sep.join(str(p).strip() for p in parts if p is not None and p is not False and str(p).strip())


def _with_ids(data: Dict[str, Any], ids: Any) -> Tuple[Dict[str, Any], str, str]:
    """A passport-keyed record's data with the student's portal uid and HNG id when they are known
    (so the record's hash, and with it Supabase's student_uid column, follows them) -> (data, uid,
    hng)."""
    uid, hng = _ids_of(ids)
    if uid:
        data["uid"] = uid
    if hng:
        data["student_id"] = hng
    return data, uid, hng


def _uid_text(uid: str) -> str:
    return f"portal uid {uid}" if uid else ""


def doc_verdicts(passport: str, entry: Mapping[str, Any], ids: Any = None) -> List[Dict[str, Any]]:
    """kind doc_verdict, key passport|document ("#2" for a document checked twice, e.g. two NIDs or
    the three CROSS-CHECK name rows), scope = the passport: results.json documents[passport]'s rows
    (document, file, verdict, the failing rules and flags in its detail). `ids`: the student's
    (portal uid, HNG id) when known (src.cloud.student_index), for student_uid."""
    pas = _passport(passport) or str(passport)
    out = []
    for row in entry.get("rows") or []:
        data, uid, hng = _with_ids(dict(row, student=entry.get("student", ""), program=entry.get("program", "")), ids)
        what = _joined(row.get("doc"), row.get("file") and f"file {row.get('file')}", sep=", ")
        text = _paragraph(
            _sentence("Document check" + (f" of {entry.get('student')}" if entry.get("student") else "")
                      + _ids(pas, entry.get("program") or "", hng, _uid_text(uid))
                      + (f": {what}" if what else "")
                      + (f" — {row.get('verdict')}" if row.get("verdict") else "")),
            _sentence(str(row.get("detail"))) if row.get("detail") else "")
        out.append(make("doc_verdict", f"{pas}|{row.get('doc', '')}", pas, data, text, "results.json",
                        entry.get("checked"), uid=uid, hng=hng, name=entry.get("student"), passport=pas,
                        day=iso_day(entry.get("checked"))))
    return unique_keys(out)


def doc_checks(documents: Mapping[str, Any], fields: Optional[Mapping[str, Any]] = None,
               ids: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """kind doc_check (added: the student-level result, which no document row carries), key = the
    passport, scope all: results.json documents[P] (student, program, verdict, when checked) with
    its rows' verdict counts and the field check's result counts. `ids`: {passport: (uid, HNG id)}
    of the students known (src.cloud.student_index). Publish it with read_at = when the store was
    read (each record's own read_at is the time it was checked)."""
    out = []
    for passport, entry in (documents or {}).items():
        if not isinstance(entry, Mapping):
            continue
        pas = _passport(passport) or str(passport)
        counts: Dict[str, int] = {}
        for row in entry.get("rows") or []:
            v = str(row.get("verdict") or "")
            counts[v] = counts.get(v, 0) + 1
        fcounts: Dict[str, int] = {}
        for row in ((fields or {}).get(passport) or {}).get("rows") or []:
            v = str(row.get("result") or "")
            fcounts[v] = fcounts.get(v, 0) + 1
        data, uid, hng = _with_ids({"student": entry.get("student", ""), "program": entry.get("program", ""),
                                    "verdict": entry.get("verdict", ""), "checked": entry.get("checked", ""),
                                    "document_rows": counts, "field_rows": fcounts}, (ids or {}).get(pas))
        text = _paragraph(
            _sentence("Document check result" + (f" of {entry.get('student')}" if entry.get("student") else "")
                      + _ids(pas, entry.get("program") or "", hng, _uid_text(uid))
                      + (f": {entry.get('verdict')}" if entry.get("verdict") else "")
                      + (f", checked {entry.get('checked')}" if entry.get("checked") else "")),
            _sentence("Documents: " + ", ".join(f"{k} {v}" for k, v in counts.items() if k)) if any(counts) else "",
            _sentence("Fields: " + ", ".join(f"{k} {v}" for k, v in fcounts.items() if k)) if any(fcounts) else "")
        out.append(make("doc_check", pas, "all", data, text, "results.json", entry.get("checked"),
                        uid=uid, hng=hng, name=entry.get("student"), passport=pas,
                        day=iso_day(entry.get("checked"))))
    return out


def field_checks(passport: str, entry: Mapping[str, Any], ids: Any = None) -> List[Dict[str, Any]]:
    """kind field_check, key passport|field, scope = the passport: results.json fields[passport]'s
    rows (FIELD CHECK: the portal value, MATCH / DIFFERS / UNREADABLE / NO DOCUMENT / BLANK, why).
    `ids`: the student's (portal uid, HNG id) when known."""
    pas = _passport(passport) or str(passport)
    out = []
    for row in entry.get("rows") or []:
        data, uid, hng = _with_ids(dict(row, student=entry.get("student", ""), program=entry.get("program", "")), ids)
        what = _joined(row.get("field"), row.get("portal") and f"portal value {row.get('portal')}", sep=", ")
        text = _paragraph(
            _sentence("Field check" + (f" of {entry.get('student')}" if entry.get("student") else "")
                      + _ids(pas, entry.get("program") or "", hng, _uid_text(uid))
                      + (f": {what}" if what else "")
                      + (f" — {row.get('result')}" if row.get("result") else "")),
            _sentence(str(row.get("detail"))) if row.get("detail") else "")
        out.append(make("field_check", f"{pas}|{row.get('field', '')}", pas, data, text, "results.json",
                        entry.get("checked"), uid=uid, hng=hng, name=entry.get("student"), passport=pas,
                        day=iso_day(entry.get("checked"))))
    return unique_keys(out)


def _arrow(before: Any, after: Any) -> str:
    """"a -> b", "-> b" or "a ->" from the two values that exist ("" when neither does)."""
    before, after = _joined(before), _joined(after)
    return f"{before} -> {after}" if before and after else f"-> {after}" if after else f"{before} ->" if before else ""


def _was_now(label: str, value: Any, result: Any) -> str:
    """"was 2000-01-02 (DIFFERS)" / "now (BLANK)": the value and its check result that exist."""
    shown = _joined(value, result and f"({result})")
    return f"{label} {shown}" if shown else ""


def field_corrections(corrections: Iterable[Mapping[str, Any]],
                      ids: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """kind field_correction, key = sha1 of the entry's canonical JSON, scope all (append-only on
    the Supabase side, never deleted): results.json corrections[] (a portal field that changed
    after a check, and whether that settled it). `ids` ({passport: (uid, HNG id)}) fills the
    student_uid column only: the key is the entry itself, so nothing is added to its data."""
    out = []
    for c in corrections or []:
        if not isinstance(c, Mapping):
            continue
        data = jsonable(dict(c))
        pas = _passport(c.get("passport"))
        uid, hng = _ids_of((ids or {}).get(pas)) if pas else ("", "")
        change = _joined(_was_now("was", c.get("was"), c.get("was_result")),
                         _was_now("now", c.get("now"), c.get("now_result")), sep=", ")
        text = _paragraph(
            _sentence("Portal correction" + (f" noticed {c.get('noticed')}" if c.get("noticed") else "")
                      + (f" for {c.get('student')}" if c.get("student") else "")
                      + _ids(c.get("passport") or "", c.get("program") or "")
                      + (f": {_joined(c.get('field'), change)}" if _joined(c.get("field"), change) else "")),
            _sentence(str(c.get("detail"))) if c.get("detail") else "")
        out.append(make("field_correction", sha1(canonical(data)), "all", data, text, "results.json",
                        c.get("noticed"), uid=uid, hng=hng, name=c.get("student"), passport=pas,
                        day=iso_day(c.get("noticed"))))
    return unique_keys(out)


_UNREADABLE_RE = re.compile(r"^\s*\[unreadable\b", re.I)


def _cache_entry(key: str) -> Optional[Tuple[bool, str, int, int, int]]:
    """An OCR text-cache key -> (per-page, file, size, mtime, max pages), None when not one."""
    pages = key.startswith("PAGES:")
    parts = (key[6:] if pages else key).rsplit(":", 3)
    if len(parts) != 4:
        return None
    try:
        return pages, parts[0], int(parts[1]), int(parts[2]), int(parts[3])
    except ValueError:
        return None


def doc_page_texts(passport: str, cache: Mapping[str, Any], name: str = "",
                   current: Optional[Mapping[str, Tuple[int, int]]] = None,
                   read_at: Any = None, ids: Any = None) -> List[Dict[str, Any]]:
    """kind doc_page_text, key passport|file|p<page>, scope = the passport: the OCR text cache
    data/verification/text/<PASSPORT>.json, one record per page. A file's per-page entry
    ("PAGES:...") gives its pages; a file read only whole gives p1 when it has one page, else one
    record keyed passport|file|all (its pages cannot be told apart). The version used is the one
    whose size and mtime match the file now in the student's folder (`current`: {file: (size,
    mtime)}), else the newest. Pages that could not be read ("[unreadable: ...]") are left out.
    `ids`: the student's (portal uid, HNG id) when known."""
    pas = _passport(passport) or str(passport)
    versions: Dict[str, Dict[Tuple[int, int], Dict[str, Any]]] = {}
    for key, value in (cache or {}).items():
        parsed = _cache_entry(str(key))
        if parsed is None or not isinstance(value, Mapping):
            continue
        per_page, file, size, mtime, max_pages = parsed
        slot = versions.setdefault(file, {}).setdefault((size, mtime), {})
        kind = "pages" if per_page else "text"
        if max_pages >= slot.get(f"{kind}_max", -1):
            slot[kind], slot[f"{kind}_max"] = value, max_pages
    out = []
    for file, by_version in versions.items():
        want = (current or {}).get(file)
        version = tuple(want) if want and tuple(want) in by_version else max(by_version, key=lambda v: v[1])
        slot = by_version[version]
        size, mtime = version
        if "pages" in slot:
            texts = [(f"p{i}", f"page {i}", str(t)) for i, t in enumerate(slot["pages"].get("pages") or [], 1)]
            sideways = set(slot["pages"].get("sideways") or [])
        elif "text" in slot:
            n = len(slot["text"].get("sizes") or [])
            texts = [("p1" if n <= 1 else "all", "page 1" if n <= 1 else f"all {n} pages",
                      str(slot["text"].get("text") or ""))]
            sideways = set()
        else:
            continue
        for tag, label, text in texts:
            if not text.strip() or _UNREADABLE_RE.match(text):
                continue
            page = int(tag[1:]) if tag.startswith("p") else None
            data, uid, hng = _with_ids({"file": file, "page": page, "pages": tag == "all", "size": size,
                                        "mtime": mtime, "sideways": page in sideways,
                                        "words": len(text.split())}, ids)
            head = f"Document {file} of {name} ({pas}), {label}:" if name else f"Document {file} ({pas}), {label}:"
            out.append(make("doc_page_text", f"{pas}|{file}|{tag}", pas, data, f"{head}\n{text}",
                            f"verification/text/{pas}.json", read_at, uid=uid, hng=hng, name=name, passport=pas))
    return unique_keys(out)


# --------------------------------------------------------------------------- reports

def split_sections(text: str) -> List[Tuple[str, List[str]]]:
    """A report's text as its sections: blocks between blank lines, each (its first line, the
    rest). A report is published whole (report) and per section (report_sections)."""
    out = []
    for block in re.split(r"\n[ \t]*\n+", text or ""):
        lines = [ln.rstrip() for ln in block.strip("\n").splitlines() if ln.strip()]
        if lines:
            out.append((lines[0].strip(), [ln.strip() for ln in lines[1:]]))
    return out


def report(name: str, when: Any, text: str, facts: Optional[Mapping[str, Any]] = None,
           source: str = "", read_at: Any = None, day: Any = None) -> Dict[str, Any]:
    """kind report, key <report>|<ISO day or run time>, scope = the report's name: a generated
    report whole, its text as sent in content and its structured facts in data. Several days'
    reports share one scope, so publish one with complete=False (a day's report never deletes
    another's)."""
    when = str(when)
    data = {"report": name, "when": when}
    if facts:
        data["facts"] = dict(facts)
    return make("report", f"{name}|{when}", name, data, text, source or name, read_at,
                day=day if day is not None else iso_day(when))


def report_sections(name: str, when: Any, sections: Sequence[Any], source: str = "",
                    read_at: Any = None, day: Any = None) -> List[Dict[str, Any]]:
    """kind report_section, key <report>|<when>|<n> (n from 1), scope <report>|<when>: the same
    report one section (or one student line) a record; `sections` are (heading, lines) pairs or
    texts. A report's sections are published together with complete=True."""
    when = str(when)
    out = []
    for n, sec in enumerate(sections or [], 1):
        heading, lines = (sec, []) if isinstance(sec, str) else (sec[0], list(sec[1] or []))
        text = "\n".join([str(heading)] + [str(x) for x in lines])
        data = {"report": name, "when": when, "n": n, "heading": heading, "lines": lines}
        out.append(make("report_section", f"{name}|{when}|{n}", f"{name}|{when}", data, text,
                        source or name, read_at, day=day if day is not None else iso_day(when)))
    return out


def brief_facts(day: Any, facts: Sequence[str], read_at: Any = None) -> List[Dict[str, Any]]:
    """kind brief_fact, key <ISO day>|<n> (n from 1), scope the ISO day: each fact line of
    Brief(text, facts)."""
    iso = iso_day(day) or ""
    return [make("brief_fact", f"{iso}|{n}", iso, {"day": iso, "n": n, "fact": fact},
                 f"Daily brief for {_long_day(iso)}, fact {n}: {fact}", "brief", read_at, day=iso)
            for n, fact in enumerate(facts or [], 1) if str(fact).strip()]


def notification(text: str, sent_at: Any = None, source: str = "", title: str = "") -> Dict[str, Any]:
    """kind notification, key sha1 of the text and the time it was sent, scope the ISO day: one
    Telegram notification a job sent (a sync summary, a document-check notice, alerts), as sent."""
    at = as_read_at(sent_at)
    iso = at[:10]
    full = f"{title}\n\n{text}" if title and not str(text).startswith(title) else str(text)
    data = {"text": full, "sent_at": at, "source": source}
    return make("notification", sha1(full, "|", at), iso, data, full, source or "telegram", at, day=iso)


def missing_report(day: Any, rows: Sequence[Sequence[Any]], text: str = "", read_at: Any = None,
                   source: str = "missing_report") -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """The missing-information report of `day` (missing_report.build_report's rows: program,
    intake, Student ID, Full Name, Mobile, missing count, the missing fields) -> (its report record,
    one report_section per incomplete student). `text` is the report as sent, when there is one;
    else a text is built from the rows."""
    iso = iso_day(day) or str(day)
    cols = ("program", "intake", "student_id", "full_name", "mobile", "missing_count", "missing_fields")
    items = [dict(zip(cols, [("" if v is None else v) for v in r])) for r in rows or []]
    incomplete = [i for i in items if str(i["missing_count"]).isdigit() and int(i["missing_count"]) > 0]
    lines = [_joined(_joined(i["program"], i["intake"]), _joined(i["student_id"], i["full_name"]),
                     f"{i['missing_count']} missing" + (f": {i['missing_fields']}" if i["missing_fields"] else ""),
                     sep=" — ")
             for i in incomplete]
    body = text or "\n".join([f"Missing-information report — {_long_day(iso)}",
                              f"{len(incomplete)} students have missing information."] + lines)
    whole = report("missing_report", iso, body, {"rows": items}, source, read_at, iso)
    sections = report_sections("missing_report", iso, [(ln, []) for ln in lines], source, read_at, iso)
    return whole, sections


def _newest_check_day(section: Mapping[str, Any]) -> str:
    days = [iso_day((e or {}).get("checked")) for e in (section or {}).values() if isinstance(e, Mapping)]
    return max((d for d in days if d), default="")


def document_check_report(store: Mapping[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """DOCUMENT CHECK.xlsx's content from the store it is built from (results.json, as
    auto_verify.write_document_report does): -> (report "document_check|<day of the newest
    check>", one section per student: verdict and its Missing/Fail/Flag/Pass counts). (None, [])
    when the store holds no student."""
    docs = {p: e for p, e in (store.get("documents") or {}).items() if isinstance(e, Mapping)}
    when = _newest_check_day(docs)
    if not docs or not when:
        return None, []
    sections = []
    verdicts: Dict[str, int] = {}
    for pas, e in sorted(docs.items(), key=lambda kv: (str(kv[1].get("program")), str(kv[1].get("student")))):
        counts = {k: sum(1 for r in e.get("rows") or [] if r.get("verdict") == k) for k in ("MISSING", "FAIL", "FLAG", "PASS")}
        if e.get("verdict"):
            verdicts[str(e["verdict"])] = verdicts.get(str(e["verdict"]), 0) + 1
        who = _joined(e.get("student"), f"({_joined(pas, e.get('program'), sep=', ')})")
        sections.append((who + (f": {e.get('verdict')}" if e.get("verdict") else ""),
                         [", ".join(f"{k} {v}" for k, v in counts.items())
                          + (f"; checked {e.get('checked')}" if e.get("checked") else "")]))
    head = f"DOCUMENT CHECK — {len(docs)} students" + (
        ": " + ", ".join(f"{k} {v}" for k, v in sorted(verdicts.items())) if verdicts else "")
    text = "\n".join([head] + [h for h, _ in sections])
    whole = report("document_check", when, text, {"students": len(docs), "verdicts": verdicts},
                   "results.json", None, when)
    return whole, report_sections("document_check", when, sections, "results.json", None, when)


def field_check_report(store: Mapping[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """FIELD CHECK.xlsx's content from results.json (auto_verify.write_field_report): -> (report
    "field_check|<day of the newest check>", one section per student with its result counts and
    the fields that differ, and a Corrections section when there are any). (None, []) when empty."""
    fields = {p: e for p, e in (store.get("fields") or {}).items() if isinstance(e, Mapping)}
    when = _newest_check_day(fields)
    if not fields or not when:
        return None, []
    sections = []
    for pas, e in sorted(fields.items(), key=lambda kv: (str(kv[1].get("program")), str(kv[1].get("student")))):
        rows = e.get("rows") or []
        counts = {k: sum(1 for r in rows if r.get("result") == k)
                  for k in ("MATCH", "DIFFERS", "UNREADABLE", "NO DOCUMENT", "BLANK")}
        differ = [_joined(r.get("field") and f"{r.get('field')}:", r.get("portal") and f"portal {r.get('portal')}",
                          r.get("detail") and f"— {r.get('detail')}")
                  for r in rows if r.get("result") == "DIFFERS"]
        who = _joined(e.get("student"), f"({_joined(pas, e.get('program'), sep=', ')})")
        sections.append((f"{who}: " + ", ".join(f"{k} {v}" for k, v in counts.items()), [d for d in differ if d]))
    corrections = [c for c in store.get("corrections") or [] if isinstance(c, Mapping)]
    if corrections:
        sections.append((f"Corrections ({len(corrections)})",
                         [_joined(c.get("noticed"), c.get("student"),
                                  _joined(c.get("field") and f"{c.get('field')}:", _arrow(c.get("was"), c.get("now"))),
                                  _arrow(c.get("was_result"), c.get("now_result"))
                                  and f"({_arrow(c.get('was_result'), c.get('now_result'))})")
                          for c in corrections]))
    text = "\n".join([f"FIELD CHECK — {len(fields)} students"] + [h for h, _ in sections])
    whole = report("field_check", when, text, {"students": len(fields), "corrections": len(corrections)},
                   "results.json", None, when)
    return whole, report_sections("field_check", when, sections, "results.json", None, when)
