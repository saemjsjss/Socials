"""Which student a passport number belongs to, for the records keyed by passport.

The document check (results.json) and its OCR text caches know a student by passport number only,
but Supabase's student_uid and student_hng_id columns (hg_match(p_student_uid := N)) want the
portal uid and the HNG id. The lists that show them are not read on every run that publishes
those records (the verified-documents list can fail, the backfill can skip the portal), so what
they showed is kept here, in data/cloud/student_index.json:

    {"version": 1, "by_passport": {"<PASSPORT>": {"uid": "425", "hng": "HNG-2026-12"}}}

updated from every list that is read (a newer reading of a passport replaces the older one; a
list that does not show a field leaves it as it was), and the records are built from it. So a
record's ids stay the same run after run, and its hash does not flip each time a list could not
be read. A passport two students share in one list is given to neither (R11: no guessing); a
placeholder passport ("PENDING") is no passport at all.

Local data only (data/ is never committed); nothing here raises: a failure is one log line and
the records are built without the ids.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from src.config import BOT_ROOT

logger = logging.getLogger("hangeul.cloud")

INDEX_PATH = BOT_ROOT / "data" / "cloud" / "student_index.json"
VERSION = 1

Ids = Dict[str, Tuple[str, str]]          # {passport: (portal uid, HNG id)}, "" for each not known


def _key(passport: Any) -> str:
    from src.sheets.passport_issue import passport_key
    return passport_key(str(passport or ""))


def _found(triples: Iterable[Tuple[Any, Any, Any]]) -> Dict[str, Dict[str, str]]:
    """(passport, uid, HNG id) readings of one list -> {passport: {"uid"?, "hng"?}}: a field only
    when the list showed it, "" when it showed two different ones for that passport."""
    uids: Dict[str, set] = {}
    hngs: Dict[str, set] = {}
    for passport, uid, hng in triples:
        key = _key(passport)
        if not key:
            continue
        uid = str(uid or "").strip()
        hng = str(hng or "").strip().upper()
        if uid.isdigit() and 0 < int(uid) < 2 ** 31:
            uids.setdefault(key, set()).add(uid)
        if hng.startswith("HNG-"):
            hngs.setdefault(key, set()).add(hng)
    out: Dict[str, Dict[str, str]] = {}
    for key in set(uids) | set(hngs):
        entry = {}
        if key in uids:
            entry["uid"] = next(iter(uids[key])) if len(uids[key]) == 1 else ""
        if key in hngs:
            entry["hng"] = next(iter(hngs[key])) if len(hngs[key]) == 1 else ""
        out[key] = entry
    return out


def from_students(students: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, str]]:
    """students.php records (parse_students_page): their details' Passport No, uid and HNG id."""
    return _found(((s.get("details") or {}).get("Passport No"), s.get("uid"), s.get("student_id"))
                  for s in students or [] if isinstance(s, Mapping))


def from_documents(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, str]]:
    """The verified-documents list (verified_docs.fetch_verified_students): passport and uid."""
    return _found((r.get("passport"), r.get("uid"), "") for r in rows or [] if isinstance(r, Mapping))


def from_export(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, str]]:
    """The CSV export (students.php?export=csv): Passport No and Student ID (no uid)."""
    return _found((r.get("Passport No"), "", r.get("Student ID")) for r in rows or [] if isinstance(r, Mapping))


def _read() -> Dict[str, Dict[str, str]]:
    try:
        doc = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError:              # a file cut short: rebuilt from the next lists read
        return {}
    if not isinstance(doc, dict) or doc.get("version") != VERSION or not isinstance(doc.get("by_passport"), dict):
        return {}
    return {str(k): {f: str(v) for f, v in e.items() if f in ("uid", "hng")}
            for k, e in doc["by_passport"].items() if isinstance(e, dict)}


def _ids(index: Mapping[str, Mapping[str, str]]) -> Ids:
    return {k: (e.get("uid") or "", e.get("hng") or "") for k, e in index.items()
            if e.get("uid") or e.get("hng")}


def load() -> Ids:
    """{passport: (uid, HNG id)} as kept; {} when there is none or it cannot be read."""
    try:
        return _ids(_read())
    except Exception as e:
        logger.warning("Supabase publish: the student index could not be read (%s); records go without "
                       "their student ids.", type(e).__name__)
        return {}


def remember(*readings: Optional[Mapping[str, Mapping[str, str]]], save: bool = True) -> Ids:
    """Merge lists' readings (from_students / from_documents / from_export) into the index, save it
    when it changed (.part + os.replace; not with save=False: a dry run), and -> {passport: (uid,
    HNG id)}. Never raises."""
    try:
        index = _read()
        before = json.dumps(index, sort_keys=True)
        for found in readings:
            for key, fields in (found or {}).items():
                index.setdefault(key, {}).update(fields)
        if save and json.dumps(index, sort_keys=True) != before:
            INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
            part = INDEX_PATH.with_name(INDEX_PATH.name + ".part")
            part.write_text(json.dumps({"version": VERSION, "by_passport": index}, ensure_ascii=False,
                                       separators=(",", ":")), encoding="utf-8")
            os.replace(part, INDEX_PATH)
        return _ids(index)
    except Exception as e:
        logger.warning("Supabase publish: the student index could not be updated (%s); records go without "
                       "their student ids.", type(e).__name__)
        return {}
