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
of the text, never replaced by a stand-in. The student_*, day and source columns are derived only
from the hashed fields (key, scope, data, content), because Supabase rewrites a record only when
its content_hash changes (hg_sync leaves a same-hash row as it is).

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


def batch(kind: str, scope: str, rows: Sequence[Dict[str, Any]], complete: bool) -> Dict[str, Any]:
    """One (kind, scope) to publish: `rows` are every record the read saw (not only the changed
    ones: publishing sends only those whose hash changed); `complete` only when the read was whole
    (every page, pager total matched, no error): Supabase then deletes the (kind, scope)'s other
    records. A partial or failed read is complete=False, and deletes nothing."""
    return {"kind": kind, "scope": scope, "complete": bool(complete), "rows": list(rows)}


def batches(kind: str, rows: Sequence[Dict[str, Any]], complete: bool,
            scope_range: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
    """Records of one kind in several scopes (each record's own: a day, a passport, a report and
    day): published one scope at a time. With complete=True every scope that has records is
    complete; with `scope_range` (lo, hi), also every scope the bot published before that lies in
    lo..hi (text order: ISO days) and has no record now is emptied (its records are gone)."""
    out = {"kind": kind, "scope": None, "complete": bool(complete), "rows": list(rows)}
    if scope_range:
        out["scope_range"] = [str(scope_range[0]), str(scope_range[1])]
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
    passport = d.get("Passport No") or ""
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


def _student_fields(s: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in s.items() if k not in STUDENT_VOLATILE and not str(k).startswith("_")}


def student(s: Mapping[str, Any], read_at: Any = None) -> Optional[Dict[str, Any]]:
    """kind student, key = the portal uid, scope all: one read_students record (every list column,
    the ~50 details, the file names, the payment chips and stamp, the applications). None for a
    row without a uid (its fallback key is not stable: R11)."""
    uid = str(s.get("uid") or "").strip()
    if _uid(uid) is None:
        return None
    d = s.get("details") or {}
    return make("student", uid, "all", _student_fields(s), student_text(s), "students.php", read_at,
                uid=uid, hng=s.get("student_id"), name=s.get("student_name") or d.get("Full Name"),
                passport=_passport(d.get("Passport No")),
                day=iso_day(s.get("applied_on")) or iso_day(s.get("applied_date")))


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
        d = s.get("details") or {}
        data = dict(_student_fields(s), badge=badge)
        text = _paragraph("Pending payment (students.php?status=pending).", student_text(s),
                          _sentence(f"The portal's Pending Payments badge shows {badge}") if badge is not None else "")
        out.append(make("pending_payment", uid, "all", data, text, "students.php?status=pending", read_at,
                        uid=uid, hng=s.get("student_id"), name=s.get("student_name") or d.get("Full Name"),
                        passport=_passport(d.get("Passport No")),
                        day=iso_day(s.get("applied_on")) or iso_day(s.get("applied_date"))))
    return out


def verification(v: Mapping[str, Any], day: Any, read_at: Any = None) -> Optional[Dict[str, Any]]:
    """kind verification, key uid, scope the stamp's ISO day: one parsers.verification() result
    (verifier, time, amount, method, paid and verified income) for `day`."""
    from src.scraper.parsers import payment_text
    uid = str(v.get("uid") or "").strip()
    iso = iso_day(day)
    if _uid(uid) is None or not iso:
        return None
    data = dict(v, day=iso)
    pay = payment_text(v)
    name = v.get("name") or ""
    text = _paragraph(
        _sentence(f"Payment verification of {name or 'a student'}"
                  f"{_ids(v.get('student_id') or '', f'portal uid {uid}')}"
                  + (f", {v.get('program')}" if v.get("program") else "")),
        _sentence(", ".join(x for x in (v.get("verified_by") and f"Verified by {v.get('verified_by')}",
                                        f"on {v.get('verified_time') or _long_day(iso)} ({_long_day(iso)})") if x)),
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
        files = [f for f in str(row.get("docs") or "").split("|") if f]
        data = dict(row, files=files)
        text = _paragraph(
            _sentence(f"Verified documents on the portal of {row.get('name') or 'a student'}"
                      f"{_ids(row.get('passport') and 'passport ' + row.get('passport'), row.get('program') or '', f'portal uid {uid}')}"),
            _sentence(f"{len(files)} files: " + ", ".join(files)) if files else "")
        out.append(make("student_documents", uid, "all", data, text,
                        "students.php?source=direct&filter_docs=verified", read_at,
                        uid=uid, name=row.get("name"), passport=_passport(row.get("passport"))))
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
        data = dict(row, stale_columns=list(STALE_EXPORT_COLUMNS))
        name, hng = pb.clean_value(row.get("Full Name", "")), pb.clean_value(row.get("Student ID", ""))
        fields = _pairs({k: pb.clean_value(v) for k, v in row.items()},
                        skip=set(STALE_EXPORT_COLUMNS) | {"Full Name", "Student ID"})
        text = _paragraph(_sentence(f"Student export row (students.php?export=csv): {name or 'no name'}"
                                    f"{_ids(hng)}"),
                          _sentence(fields) if fields else "")
        out.append(make("student_export", key, "all", data, text, "students.php?export=csv", read_at,
                        hng=hng, name=name, passport=_passport(row.get("Passport No")),
                        day=iso_day(row.get("Applied On"))))
    return unique_keys(out)


def student_profile(uid: Any, fields: Mapping[str, Any], read_at: Any = None) -> Optional[Dict[str, Any]]:
    """kind student_profile, key = scope = uid: student_edit.php's form as
    HangeulAdminClient._profile_fields reads it (every filled field, by its form name). None when
    it shows no profile (no name or full_name: the page was not the profile)."""
    uid = str(uid or "").strip()
    fields = {str(k): v for k, v in dict(fields or {}).items()}
    name = fields.get("full_name") or fields.get("name") or ""
    if _uid(uid) is None or not name:
        return None
    pairs = _pairs({k.replace("_", " "): v for k, v in fields.items() if k not in ("id", "save")})
    text = _paragraph(_sentence(f"Student profile (student_edit.php) of {name}{_ids(f'portal uid {uid}')}"),
                      _sentence(pairs) if pairs else "")
    return make("student_profile", uid, uid, fields, text, "student_edit.php", read_at,
                uid=uid, name=name, passport=_passport(fields.get("passport_number")))


def student_progress(progress: Mapping[str, Mapping[str, Any]],
                     listed: Optional[Mapping[str, Mapping[str, Any]]] = None,
                     read_at: Any = None) -> List[Dict[str, Any]]:
    """kind student_progress, key uid, scope all: stage_report.read_progress's pages
    ({uid: {"pct", "stage", "status"}}); an entry that could not be read ({"error"}) is left out.
    `listed` ({uid: students.php record}) adds the student's HNG id and name."""
    out = []
    for uid, p in (progress or {}).items():
        uid = str(uid).strip()
        if _uid(uid) is None or not isinstance(p, Mapping) or p.get("error") or "pct" not in p:
            continue
        s = (listed or {}).get(uid) or {}
        hng = s.get("student_id") or ""
        name = s.get("student_name") or (s.get("details") or {}).get("Full Name") or ""
        data = dict(p)
        if hng:
            data["student_id"] = hng
        if name:
            data["student_name"] = name
        text = _sentence(f"Progress of {name or 'a student'}{_ids(hng, f'portal uid {uid}')} on progress.php: "
                         + ", ".join(x for x in (f"{p.get('pct')}% overall",
                                                 p.get("stage") and f"current stage {p.get('stage')}",
                                                 p.get("status") and f"status {p.get('status')}") if x))
        out.append(make("student_progress", uid, "all", data, text, "progress.php", read_at,
                        uid=uid, hng=hng, name=name))
    return out


# --------------------------------------------------------------------------- consult_requests.php

def consultation(row: Mapping[str, Any], day: Any, read_at: Any = None) -> Dict[str, Any]:
    """kind consultation, key = the request's portal id (the row's "id"), else sha1 of name +
    contact + received; scope = the received ISO day. Every field of the row."""
    iso = iso_day(day) or iso_day(row.get("received_date")) or ""
    rid = str(row.get("id") or "").strip()
    key = rid if rid.isdigit() else sha1(row.get("name", ""), row.get("contact", ""), row.get("received", ""))
    by = row.get("handled_by") or ""
    text = _paragraph(
        _sentence(f"Consultation request from {row.get('name') or 'someone'}"
                  + (f" ({row.get('contact')})" if row.get("contact") else "")
                  + (f", received {row.get('received')}" if row.get("received") else "")),
        _sentence(f"City {row.get('city')}") if row.get("city") else "",
        _sentence(f"Program {row.get('program')}") if row.get("program") else "",
        _sentence(f"Consultant {row.get('consultant')}") if row.get("consultant") else "",
        _sentence(", ".join(x for x in (row.get("status") and f"Status: {row.get('status')}",
                                        by and f"last updated by {by}") if x)),
        _sentence(f"Details: {row.get('details')}") if row.get("details") else "",
        _sentence(f"Remarks: {row.get('remarks')}") if row.get("remarks") else "")
    return make("consultation", key, iso, row, text,
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
    count_under_review's rule)."""
    from src.scraper.parsers import _label_key
    out = []
    for row in rows or []:
        if _label_key(str(row.get("status") or "")) != "under review":
            continue
        key = f"{row.get('student', '')}|{row.get('window', '')}"
        text = _sentence(f"Window application of {row.get('student') or 'a student'}"
                         + (f" for {row.get('window')}" if row.get("window") else "")
                         + f": {row.get('status')} (window_applications.php)")
        out.append(make("window_application", key, "all", row, text,
                        "window_applications.php?status=under_review", read_at, name=row.get("student")))
    return unique_keys(out)


def dashboard_facts(facts: Iterable[Any], read_at: Any = None) -> List[Dict[str, Any]]:
    """kind dashboard_fact, key group|label ("#2" for a repeat), scope all: ask.dashboard_facts
    (index.php's tiles and cards, each Fact(group, label, value, text, note))."""
    out = []
    for f in facts or []:
        f = f._asdict() if hasattr(f, "_asdict") else dict(f)
        what = f"{f.get('label')} — {f.get('note')}" if f.get("note") else f.get("label")
        text = _sentence(f"Dashboard (index.php), {f.get('group')}: {what}: {f.get('text')}")
        out.append(make("dashboard_fact", f"{f.get('group', '')}|{f.get('label', '')}", "all", f, text,
                        "index.php", read_at))
    return unique_keys(out)


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
    for all items: publish them with complete=False (nothing deleted)."""
    out = []
    for it in items or []:
        it = it._asdict() if hasattr(it, "_asdict") else dict(it)
        data = jsonable(it)
        cid = str(it.get("id") or "").strip()
        key = cid or "t:" + sha1(it.get("title", ""), "|", data.get("start") or "", "|", it.get("note", ""))
        start, end = data.get("start"), data.get("end")
        when = (f"from {_long_day(start)} to {_long_day(end)}" if start and end and start != end
                else f"on {_long_day(end or start)}" if (start or end) else "")
        text = _paragraph(
            _sentence(f"Calendar (calendar.php): {it.get('title') or 'an item'}"
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
        _sentence(f"Passport audit of {name or 'a student'}{_ids(hng, f'portal uid {uid}')}, scan {scan}: "
                  f"{result.get('status') or 'no status'}"),
        _sentence(str(result.get("verdict"))) if result.get("verdict") else "",
        _sentence("Discrepancies: " + "; ".join(str(x) for x in result.get("discrepancies"))) if result.get("discrepancies") else "",
        _sentence("Check by eye: " + "; ".join(str(x) for x in result.get("uncertain"))) if result.get("uncertain") else "",
        _sentence("Compared: " + "; ".join(compared)) if compared else "")
    return make("passport_audit", f"{uid}|{scan}", "all", data, text, "view_doc.php + student_edit.php", read_at,
                uid=uid, hng=hng, name=name, passport=_passport(passport or (form or {}).get("passport_no")))


def passport_alerts(memory: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """kind passport_alert, key uid|file, scope all: every entry of the passport watcher's memory
    (data/alerted_passport_issues.json v2: status, checked, the alert text, sent, sent_at). The
    memory is the whole truth after every save, so a publish of all of it is complete."""
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

def doc_verdicts(passport: str, entry: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """kind doc_verdict, key passport|document ("#2" for a document checked twice, e.g. two NIDs or
    the three CROSS-CHECK name rows), scope = the passport: results.json documents[passport]'s rows
    (document, file, verdict, the failing rules and flags in its detail)."""
    pas = _passport(passport) or str(passport)
    out = []
    for row in entry.get("rows") or []:
        data = dict(row, student=entry.get("student", ""), program=entry.get("program", ""))
        text = _paragraph(
            _sentence(f"Document check of {entry.get('student') or 'a student'}"
                      f"{_ids(pas, entry.get('program') or '')}: {row.get('doc')}"
                      + (f", file {row.get('file')}" if row.get("file") else "")
                      + f" — {row.get('verdict')}"),
            _sentence(str(row.get("detail"))) if row.get("detail") else "")
        out.append(make("doc_verdict", f"{pas}|{row.get('doc', '')}", pas, data, text, "results.json",
                        entry.get("checked"), name=entry.get("student"), passport=pas,
                        day=iso_day(entry.get("checked"))))
    return unique_keys(out)


def doc_checks(documents: Mapping[str, Any], fields: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """kind doc_check (added: the student-level result, which no document row carries), key = the
    passport, scope all: results.json documents[P] (student, program, verdict, when checked) with
    its rows' verdict counts and the field check's result counts."""
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
        data = {"student": entry.get("student", ""), "program": entry.get("program", ""),
                "verdict": entry.get("verdict", ""), "checked": entry.get("checked", ""),
                "document_rows": counts, "field_rows": fcounts}
        text = _paragraph(
            _sentence(f"Document check result of {entry.get('student') or 'a student'}"
                      f"{_ids(pas, entry.get('program') or '')}: {entry.get('verdict') or 'no verdict'}"
                      + (f", checked {entry.get('checked')}" if entry.get("checked") else "")),
            _sentence("Documents: " + ", ".join(f"{k} {v}" for k, v in counts.items())) if counts else "",
            _sentence("Fields: " + ", ".join(f"{k} {v}" for k, v in fcounts.items())) if fcounts else "")
        out.append(make("doc_check", pas, "all", data, text, "results.json", entry.get("checked"),
                        name=entry.get("student"), passport=pas, day=iso_day(entry.get("checked"))))
    return out


def field_checks(passport: str, entry: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """kind field_check, key passport|field, scope = the passport: results.json fields[passport]'s
    rows (FIELD CHECK: the portal value, MATCH / DIFFERS / UNREADABLE / NO DOCUMENT / BLANK, why)."""
    pas = _passport(passport) or str(passport)
    out = []
    for row in entry.get("rows") or []:
        data = dict(row, student=entry.get("student", ""), program=entry.get("program", ""))
        text = _paragraph(
            _sentence(f"Field check of {entry.get('student') or 'a student'}{_ids(pas, entry.get('program') or '')}: "
                      f"{row.get('field')}"
                      + (f", portal value {row.get('portal')}" if row.get("portal") else "")
                      + f" — {row.get('result')}"),
            _sentence(str(row.get("detail"))) if row.get("detail") else "")
        out.append(make("field_check", f"{pas}|{row.get('field', '')}", pas, data, text, "results.json",
                        entry.get("checked"), name=entry.get("student"), passport=pas,
                        day=iso_day(entry.get("checked"))))
    return unique_keys(out)


def field_corrections(corrections: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """kind field_correction, key = sha1 of the entry's canonical JSON, scope all (append-only on
    the Supabase side, never deleted): results.json corrections[] (a portal field that changed
    after a check, and whether that settled it)."""
    out = []
    for c in corrections or []:
        if not isinstance(c, Mapping):
            continue
        data = jsonable(dict(c))
        text = _paragraph(
            _sentence(f"Portal correction noticed {c.get('noticed')} for {c.get('student') or 'a student'}"
                      f"{_ids(c.get('passport') or '', c.get('program') or '')}: {c.get('field')} was "
                      f"{c.get('was') or 'blank'} ({c.get('was_result')}), now {c.get('now') or 'blank'} "
                      f"({c.get('now_result')})"),
            _sentence(str(c.get("detail"))) if c.get("detail") else "")
        out.append(make("field_correction", sha1(canonical(data)), "all", data, text, "results.json",
                        c.get("noticed"), name=c.get("student"), passport=_passport(c.get("passport")),
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
                   read_at: Any = None) -> List[Dict[str, Any]]:
    """kind doc_page_text, key passport|file|p<page>, scope = the passport: the OCR text cache
    data/verification/text/<PASSPORT>.json, one record per page. A file's per-page entry
    ("PAGES:...") gives its pages; a file read only whole gives p1 when it has one page, else one
    record keyed passport|file|all (its pages cannot be told apart). The version used is the one
    whose size and mtime match the file now in the student's folder (`current`: {file: (size,
    mtime)}), else the newest. Pages that could not be read ("[unreadable: ...]") are left out."""
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
            data = {"file": file, "page": page, "pages": tag == "all", "size": size, "mtime": mtime,
                    "sideways": page in sideways, "words": len(text.split())}
            head = f"Document {file} of {name} ({pas}), {label}:" if name else f"Document {file} ({pas}), {label}:"
            out.append(make("doc_page_text", f"{pas}|{file}|{tag}", pas, data, f"{head}\n{text}",
                            f"verification/text/{pas}.json", read_at, name=name, passport=pas))
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
    lines = [f"{i['program']} {i['intake']} — {i['student_id'] or '(no ID)'} {i['full_name']} — "
             f"{i['missing_count']} missing: {i['missing_fields']}" for i in incomplete]
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
        verdicts[str(e.get("verdict"))] = verdicts.get(str(e.get("verdict")), 0) + 1
        sections.append((f"{e.get('student')} ({pas}, {e.get('program')}): {e.get('verdict')}",
                         [", ".join(f"{k} {v}" for k, v in counts.items()) + f"; checked {e.get('checked')}"]))
    head = f"DOCUMENT CHECK — {len(docs)} students: " + ", ".join(f"{k} {v}" for k, v in sorted(verdicts.items()))
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
        differ = [f"{r.get('field')}: portal {r.get('portal')} — {r.get('detail')}" for r in rows
                  if r.get("result") == "DIFFERS"]
        sections.append((f"{e.get('student')} ({pas}, {e.get('program')}): "
                         + ", ".join(f"{k} {v}" for k, v in counts.items()), differ))
    corrections = store.get("corrections") or []
    if corrections:
        sections.append((f"Corrections ({len(corrections)})",
                         [f"{c.get('noticed')} {c.get('student')} {c.get('field')}: {c.get('was')} -> {c.get('now')} "
                          f"({c.get('was_result')} -> {c.get('now_result')})" for c in corrections]))
    text = "\n".join([f"FIELD CHECK — {len(fields)} students"] + [h for h, _ in sections])
    whole = report("field_check", when, text, {"students": len(fields), "corrections": len(corrections)},
                   "results.json", None, when)
    return whole, report_sections("field_check", when, sections, "results.json", None, when)
