"""The Supabase publish layer (src/cloud): records, hash state, hg_sync calls, runs, handoff, backfill.

What is pinned here:
  records     every kind is built from what its reader already returns: the key, scope, day, data and
              the text form, with no placeholder anywhere; content_hash is the spec's sha256
  publish     only changed rows are sent (a second identical run sends nothing; a changed field sends
              that row alone); at most 200 rows a call and p_all_keys only on the last call of a
              complete read; a partial read sends p_all_keys null and deletes nothing; a complete read
              without a student deletes exactly that student (and the hash state forgets it);
              Supabase 500, a timeout and a refused key: the job finishes, one log line, the hash
              state not advanced; hg_runs gets its row (POST, then PATCH); the dry run writes the
              exact payloads and changes nothing
  handoff     one atomic file and a publisher process started without waiting (UTF-8, no window,
              CUDA hidden, output to the sync log, never the caller's pipe); the process deletes it
  secrets     sb_secret_ / sb_publishable_ keys, JWTs and Bearer tokens never reach a log line
  embeddings  a stub in every test; one slow test with the real cached gte-small (384 numbers, unit
              length, CUDA never initialised)

The fake Supabase (httpx.MockTransport) answers hg_sync and hg_runs as the Jeannie migration's SQL
does and fails the test on any other host, path or method. Every portal page is synthetic.
Nothing reaches the network, Supabase, Telegram or the portal.
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

from test_foundation import KLP, TODAY, page, portal, row, verified  # noqa: E402,F401
from test_consultations import _row as consult_row  # noqa: E402
from test_inquiries import TOTALS, TOTALS_KEY, day_key, day_page, totals_page  # noqa: E402

from src.cloud import backfill, embed, handoff, publish, records, student_index  # noqa: E402
from src.config import settings  # noqa: E402
from src.scraper import parsers  # noqa: E402
from src.scraper.client import admin_client  # noqa: E402

REAL_SPAWN = handoff.spawn          # the launcher itself (the fixture replaces it with a recorder)
URL = "https://example.supabase.co"
KEY = "sb_secret_" + "Fak3KeyForTests0nly" * 2
DHAKA = ZoneInfo("Asia/Dhaka")
READ_AT = "2026-09-28T18:21:04+06:00"
PLACEHOLDERS = ("None", "N/A", "n/a", "null", "undefined", "Unknown", "PENDING", ": —", "(—", "Admin", "20,000.00 BDT",
                # the stand-ins a text form once wrote for a value that is not there (R1)
                "a student", "someone", "no name", "(no ID)", "an item", "no status", "no verdict", "blank",
                "Unassigned", "— Event", "passport —", "()")


# --------------------------------------------------------------------------- the fake Supabase

class FakeSupabase:
    """hg_runs and hg_sync as the migration 20260929030000_hangeul_context.sql does them, in memory.
    Every request is recorded; any other host, path or method fails the test."""

    def __init__(self):
        self.records = {}        # (kind, key) -> the stored row (scope, content_hash, ...)
        self.chunks = {}         # (kind, key) -> its chunks
        self.runs = {}           # id -> the hg_runs row
        self.calls = []          # (method, path, body)
        self.changes = []        # (op, kind, key): the change log the trigger writes
        self.fail = None         # request -> an httpx.Response, an exception to raise, or None

    # the transport
    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.scheme != "https" or request.url.host != "example.supabase.co":
            raise AssertionError(f"a request to another host: {request.url.host}")
        assert request.headers.get("apikey") == KEY, "the secret key goes in apikey"
        assert request.headers.get("authorization") == f"Bearer {KEY}", "and as the Bearer token"
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        if self.fail is not None:
            out = self.fail(request)
            if isinstance(out, Exception):
                raise out
            if out is not None:
                return out
        if request.url.path == "/rest/v1/hg_runs" and request.method == "POST":
            return self._run_insert(body)
        if request.url.path == "/rest/v1/hg_runs" and request.method == "PATCH":
            return self._run_update(request, body)
        if request.url.path == "/rest/v1/rpc/hg_sync" and request.method == "POST":
            assert request.headers.get("content-type") == "application/json"
            return self._sync(body)
        raise AssertionError(f"Supabase: unexpected {request.method} {request.url.path}")

    @staticmethod
    def _error(status, code, message="error"):
        return httpx.Response(status, json={"code": code, "message": message, "details": None, "hint": None})

    def _run_insert(self, body):
        assert set(body) <= {"id", "job", "started_at", "finished_at", "status", "counts", "note"}
        uuid.UUID(body["id"])
        if body["id"] in self.runs:
            return self._error(409, "23505")
        if not isinstance(body.get("job"), str) or body.get("counts", {}) is None:
            return self._error(400, "23502")
        if body.get("status") not in (None, "ok", "partial", "failed"):
            return self._error(400, "23514")
        self.runs[body["id"]] = dict(body, status=body.get("status"))
        return httpx.Response(201)

    def _run_update(self, request, body):
        m = re.fullmatch(r"id=eq\.([0-9a-f-]{36})", request.url.query.decode())
        assert m, "hg_runs is always patched by its id"
        if body.get("status") not in (None, "ok", "partial", "failed"):
            return self._error(400, "23514")
        if "counts" in body and body["counts"] is None:
            return self._error(400, "23502")
        if m.group(1) in self.runs:
            self.runs[m.group(1)].update(body)
        return httpx.Response(204)

    def _sync(self, body):
        need = {"p_run", "p_kind", "p_scope", "p_rows"}
        if not need <= set(body) or set(body) - need - {"p_all_keys"}:
            return self._error(404, "PGRST202")
        run, kind, scope, rows, all_keys = (body["p_run"], body["p_kind"], body["p_scope"], body["p_rows"],
                                            body.get("p_all_keys"))
        if not kind or not scope or not isinstance(rows, list) or len(rows) > 200:
            return self._error(400, "22023")
        model = None
        for r in rows:
            if not isinstance(r, dict) or not r.get("key"):
                return self._error(400, "22023")
            if not isinstance(r.get("data"), dict):
                return self._error(400, "22023")
            if not isinstance(r.get("content"), str) or not all(r.get(k) for k in ("content_hash", "source", "read_at")):
                return self._error(400, "22023")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", r["read_at"]):
                return self._error(400, "22007")
            if r.get("student_uid") is not None and not (isinstance(r["student_uid"], int) and 0 < r["student_uid"] < 2 ** 31):
                return self._error(400, "22P02")
            if r.get("day") is not None:
                date.fromisoformat(r["day"])
            chunks = r.get("chunks", [])
            if not isinstance(chunks, list):
                return self._error(400, "22023")
            ords = set()
            for c in chunks:
                emb = c.get("embedding")
                if not isinstance(emb, list) or len(emb) != 384 or not all(
                        isinstance(x, (int, float)) and not isinstance(x, bool) for x in emb):
                    return self._error(400, "22023")
                if not c.get("embed_model") or (model is not None and c["embed_model"] != model):
                    return self._error(400, "22023")
                model = c["embed_model"]
                if not isinstance(c.get("ord"), int) or c["ord"] < 0 or c["ord"] in ords or not isinstance(c.get("content"), str):
                    return self._error(400, "23514")
                ords.add(c["ord"])
            for text in [r["content"]] + [c["content"] for c in chunks] + [json.dumps(r["data"])]:
                if "\x00" in text:
                    return self._error(400, "22P05")
        if all_keys is not None:
            assert isinstance(all_keys, list) and None not in all_keys, "no null element in p_all_keys"
        changed = [r for r in rows if (self.records.get((kind, r["key"])) or {}).get("content_hash") != r["content_hash"]]
        if changed and run is not None and run not in self.runs:
            return self._error(409, "23503")          # the whole call rolls back
        up = un = 0
        for r in rows:
            k = (kind, r["key"])
            if (self.records.get(k) or {}).get("content_hash") == r["content_hash"]:
                un += 1
                continue
            self.records[k] = dict({f: v for f, v in r.items() if f != "chunks"}, scope=scope, run_id=run)
            self.chunks[k] = r.get("chunks", [])
            self.changes.append(("upsert", kind, r["key"]))
            up += 1
        deleted = 0
        if all_keys is not None and kind != "field_correction":
            for k in [k for k, v in self.records.items() if k[0] == kind and v["scope"] == scope and k[1] not in all_keys]:
                del self.records[k]
                self.chunks.pop(k, None)
                self.changes.append(("delete", k[0], k[1]))
                deleted += 1
        return httpx.Response(200, json={"upserted": up, "deleted": deleted, "unchanged": un})

    # views for the tests
    def syncs(self):
        return [b for m, p, b in self.calls if p == "/rest/v1/rpc/hg_sync"]

    def keys(self, kind, scope=None):
        return sorted(k[1] for k, v in self.records.items() if k[0] == kind and (scope is None or v["scope"] == scope))


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    """Publishing switched on against the fake Supabase, the hash state, lock, dry-run and handoff
    folders in tmp_path, the stub embedder, and a launcher that records instead of starting."""
    fake = FakeSupabase()
    monkeypatch.setattr(settings, "SUPABASE_URL", URL)
    monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", KEY)
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    monkeypatch.setattr(publish, "TRANSPORT", httpx.MockTransport(fake))
    monkeypatch.setattr(publish, "STATE_PATH", tmp_path / "cloud_state.json")
    monkeypatch.setattr(publish, "LOCK_PATH", tmp_path / "cloud" / "publish.lock")
    monkeypatch.setattr(publish, "DRY_RUN_DIR", tmp_path / "cloud" / "dry_run")
    monkeypatch.setattr(publish, "_DRY_RUN", False)
    monkeypatch.setattr(handoff, "PENDING_DIR", tmp_path / "cloud" / "pending")
    monkeypatch.setattr(handoff, "LOG_PATH", tmp_path / "hangeul_sync.log")
    monkeypatch.setattr(student_index, "INDEX_PATH", tmp_path / "cloud" / "student_index.json")
    spawned = []
    monkeypatch.setattr(handoff, "spawn", lambda path, timeout=0: spawned.append(Path(path)))
    stub = embed.StubEmbedder()
    old = embed.set_embedder(stub)
    try:
        yield SimpleNamespace(fake=fake, stub=stub, spawned=spawned, tmp=tmp_path)
    finally:
        embed.set_embedder(old)


def state():
    return json.loads(publish.STATE_PATH.read_text(encoding="utf-8")) if publish.STATE_PATH.exists() else None


def cloud_warnings(caplog):
    return [r for r in caplog.records if r.name == "hangeul.cloud" and r.levelno >= logging.WARNING]


def no_placeholder(record):
    """R1: the text form holds no stand-in value and no "None", and data holds none of the
    readers' filled-in words or the portal's "no value" markers."""
    for word in PLACEHOLDERS:
        assert word not in record["content"], (word, record["kind"], record["content"])
    for bad in ("  ", ". .", ", ,", ": :", ": .", " — ."):
        assert bad not in record["content"], (bad, record["kind"], record["content"])

    def values(v):
        if isinstance(v, dict):
            for x in v.values():
                yield from values(x)
        elif isinstance(v, list):
            for x in v:
                yield from values(x)
        else:
            yield v
    for v in values(record["data"]):
        assert v not in ("—", "N/A", "n/a", "PENDING", "Unassigned", "Event", "Dashboard"), (v, record["kind"])
    return True


# --------------------------------------------------------------------------- synthetic reader output

def listed(*rows):
    return parsers.parse_students_page(page(*rows))["students"]


def three_students():
    return listed(verified(425, 1, "TEST STUDENT ONE", "27 Sep, 17:19", amount="20,000.00 BDT", method="bKash",
                           applied="12 Sep 2026"),
                  row(426, 2, "TEST STUDENT TWO", pay="Pending", stage="Application Received", applied="28 Sep 2026"),
                  row(427, 3, "TEST STUDENT THREE", applied="20 Sep 2026"))


def student_rows(*names):
    """Student records of a complete students.php read, one per name, uids from 500."""
    return [records.student({"uid": str(500 + i), "student_name": n, "program": KLP, "status": "Payment Verified",
                             "details": {"Full Name": n}}, READ_AT) for i, n in enumerate(names)]


# --------------------------------------------------------------------------- records, per kind

def test_the_content_hash_is_sha256_of_the_canonical_json():
    r = records.make("student", "425", "all", {"b": 1, "a": "é"}, "text", "students.php", READ_AT)
    canonical = json.dumps({"kind": "student", "key": "425", "scope": "all", "data": {"a": "é", "b": 1},
                            "content": "text"}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert r["content_hash"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert r["read_at"] == READ_AT


def test_a_student_record_from_every_list_field_without_the_volatile_ones():
    s = three_students()[0]
    r = records.student(s, READ_AT)
    assert (r["kind"], r["key"], r["scope"], r["student_uid"], r["student_hng_id"]) == \
        ("student", "425", "all", 425, "HNG-2026-425")
    assert r["student_name"] == "TEST STUDENT ONE" and r["day"] == "2026-09-12" and r["source"] == "students.php"
    assert "sl" not in r["data"] and "details_text" not in r["data"] and "id" not in r["data"]
    assert r["data"]["details"]["DOB"] == "2000-01-01" and r["data"]["files"] == ["passport_425_1700000000.jpeg"]
    assert r["data"]["verified_by"] == "MAHIRA JANAN" and r["data"]["verified_stamp"] == "27 Sep, 17:19"
    text = r["content"]
    assert text.startswith("Student TEST STUDENT ONE (HNG-2026-425, portal uid 425).")
    assert f"Program {KLP}, intake MARCH 2027." in text and "Stage: Payment Verified, applied 12 Sep 2026." in text
    assert "Payment 20,000.00 BDT bKash, verified by MAHIRA JANAN on 27 Sep, 17:19." in text
    assert "Date of birth 2000-01-01." in text
    assert "University" not in text and "Passport" not in text     # the portal shows none: nothing said
    for word in ("None", "N/A", "null", "—"):
        assert word not in text


def test_a_student_without_a_uid_is_no_record_and_the_list_is_one_per_uid():
    s = three_students()
    assert records.student(dict(s[0], uid=""), READ_AT) is None
    assert [r["key"] for r in records.students(s + s[:1], READ_AT)] == ["425", "426", "427"]


def test_a_placeholder_passport_is_no_identity():
    s = dict(three_students()[1])
    s["details"] = dict(s["details"], **{"Passport No": "PENDING"})
    assert records.student(s, READ_AT)["passport_no"] is None
    s["details"]["Passport No"] = "a 1234567"
    assert records.student(s, READ_AT)["passport_no"] == "A1234567"


def test_pending_payments_are_the_rows_whose_own_payment_is_pending_with_the_badge():
    rows = records.pending_payments(three_students(), 3, READ_AT)
    assert [r["key"] for r in rows] == ["426"]
    r = rows[0]
    assert r["kind"] == "pending_payment" and r["data"]["badge"] == 3 and r["source"] == "students.php?status=pending"
    assert r["content"].startswith("Pending payment (students.php?status=pending). Student TEST STUDENT TWO")
    assert "The portal's Pending Payments badge shows 3." in r["content"] and no_placeholder(r)
    assert "badge shows" not in records.pending_payments(three_students(), None, READ_AT)[0]["content"]


def test_a_verification_is_dated_by_its_own_stamp_within_the_last_year():
    today = date(2026, 9, 28)
    out = records.verifications(three_students(), today, READ_AT)
    assert [(r["key"], r["scope"], r["day"]) for r in out] == [("425", "2026-09-27", "2026-09-27")]
    r = out[0]
    assert r["data"]["verified_by"] == "MAHIRA JANAN" and r["data"]["amount"] == "20,000.00 BDT"
    assert r["content"] == ("Payment verification of TEST STUDENT ONE (HNG-2026-425, portal uid 425), "
                            f"{KLP}. Verified by MAHIRA JANAN, on 27 Sep, 17:19 (27 Sep 2026). "
                            "Amount 20,000.00 BDT bKash.")
    # A yearless stamp is dated within the last year: "29 Sep" is 29 Sep 2025 on 28 Sep 2026...
    last_year = listed(verified(430, 1, "TEST STUDENT OLD", "29 Sep, 10:00", applied="01 Jan 2025"))
    assert [r["scope"] for r in records.verifications(last_year, today, READ_AT)] == ["2025-09-29"]
    # ...and one that fits no day of it (before the student applied this year) is not dated at all.
    undatable = listed(verified(431, 1, "TEST STUDENT LATE", "20 Sep, 10:00", applied="25 Sep 2026"))
    assert records.verifications(undatable, today, READ_AT) == []
    assert records.verification_window(today) == ("2025-09-29", "2026-09-28")


def test_the_export_rows_keep_every_column_keyed_like_the_sheet_sync():
    base = {"Source": "Direct", "Student ID": "", "Full Name": "TEST STUDENT FOUR", "Mobile": "01711000001",
            "Passport No": "", "Current Stage": "Payment Verified", "Current Status": "x", "Progress %": "11",
            "Applied On": "2026-09-12 17:16:00", "Email": "four@example.test"}
    rows = [dict(base, **{"Student ID": "HNG-2026-908"}),
            dict(base, **{"Passport No": "B1234567", "Full Name": "TEST FIVE"}),
            dict(base, **{"Passport No": "PENDING", "Full Name": "TEST SIX"}),
            dict(base, **{"Passport No": "PENDING", "Full Name": "TEST SIX"})]
    out = records.student_exports(rows, READ_AT)
    assert [r["key"] for r in out] == ["Student ID:HNG-2026-908", "Passport No:B1234567",
                                       "NAME:testsix8801711000001", "NAME:testsix8801711000001#2"]
    r = out[0]
    assert r["data"]["stale_columns"] == ["Current Stage", "Current Status", "Progress %"]
    assert r["data"]["Current Stage"] == "Payment Verified"            # kept, marked
    assert "Payment Verified" not in r["content"] and "Progress" not in r["content"]
    assert "Email: four@example.test" in r["content"] and r["day"] == "2026-09-12" and r["student_uid"] is None
    assert out[1]["passport_no"] == "B1234567" and out[2]["passport_no"] is None


def test_a_profile_is_its_own_scope_and_a_page_without_a_name_is_none():
    r = records.student_profile("425", {"full_name": "TEST STUDENT ONE", "father_name": "TEST FATHER",
                                        "passport_number": "c7654321", "id": "425"}, READ_AT)
    assert (r["key"], r["scope"], r["passport_no"], r["student_name"]) == ("425", "425", "C7654321", "TEST STUDENT ONE")
    assert "father name: TEST FATHER" in r["content"] and "id: 425" not in r["content"]
    assert records.student_profile("425", {"email": "x@example.test"}) is None


def test_progress_pages_that_were_not_read_are_left_out():
    listed_by_uid = {s["uid"]: s for s in three_students()}
    out = records.student_progress({"425": {"pct": 22, "stage": "Payment Verified", "status": "Verified"},
                                    "426": {"error": "progress.php: the portal did not answer in time"}},
                                   listed_by_uid, READ_AT)
    assert [r["key"] for r in out] == ["425"]
    assert out[0]["data"] == {"pct": 22, "stage": "Payment Verified", "status": "Verified",
                              "student_id": "HNG-2026-425", "student_name": "TEST STUDENT ONE"}
    assert out[0]["content"] == ("Progress of TEST STUDENT ONE (HNG-2026-425, portal uid 425) on progress.php: "
                                 "22% overall, current stage Payment Verified, status Verified.")


def test_the_verified_documents_list_is_file_names_only():
    out = records.student_documents([{"uid": "425", "name": "TEST STUDENT ONE", "passport": "A1234567",
                                      "program": KLP, "docs": "birth_cert_425_1.pdf|passport_425_1.jpg"}], READ_AT)
    assert out[0]["data"]["files"] == ["birth_cert_425_1.pdf", "passport_425_1.jpg"]
    assert "2 files: birth_cert_425_1.pdf, passport_425_1.jpg" in out[0]["content"] and no_placeholder(out[0])


def test_a_consultation_is_keyed_by_its_portal_id_else_by_what_it_is():
    on_day = {"day": date(2026, 9, 28), "counts": {"All": 2, "New": 1, "Consulted": 1}, "complete": True,
              "rows": [{"id": "9001", "name": "TEST LEAD", "contact": "01700000000", "city": "Dhaka", "program": "",
                        "consultant": "Unassigned", "details": "", "received": "28 Sep 2026 10:15",
                        "received_date": "28 Sep 2026", "status": "New", "handled_by": "", "remarks": ""},
                       {"name": "TEST LEAD TWO", "contact": "01700000001", "city": "", "program": "KLP",
                        "consultant": "Staff One", "details": "DOB 2000-01-01", "received": "28 Sep 2026 11:00",
                        "received_date": "28 Sep 2026", "status": "Consulted", "handled_by": "Staff One",
                        "remarks": "called twice"}]}
    rows, complete = records.consultations(on_day, READ_AT)
    assert complete is True
    assert rows[0]["key"] == "9001" and rows[1]["key"] == hashlib.sha1(
        "TEST LEAD TWO0170000000128 Sep 2026 11:00".encode()).hexdigest()
    assert {r["scope"] for r in rows} == {"2026-09-28"} and rows[0]["day"] == "2026-09-28"
    # The reader's "Unassigned" (the portal shows "—") is no consultant: no value in data or text (R1).
    assert rows[0]["content"] == ("Consultation request from TEST LEAD (01700000000), received 28 Sep 2026 10:15. "
                                  "City Dhaka. Status: New.")
    assert rows[0]["data"]["consultant"] == "" and rows[1]["data"]["consultant"] == "Staff One"
    assert "Consultant Staff One." in rows[1]["content"]
    assert "Status: Consulted, last updated by Staff One. Details: DOB 2000-01-01. Remarks: called twice." \
        in rows[1]["content"]
    day = records.consultation_day(on_day, READ_AT)
    assert (day["key"], day["scope"], day["data"]["counts"]["All"]) == ("2026-09-28", "all", 2)
    tot = records.consultation_totals(TOTALS, READ_AT)
    assert (tot["key"], tot["data"]["counts"]["All"]) == ("all", 999) and "All 999; New 8" in tot["content"]


def test_window_applications_are_the_rows_under_review_only():
    out = records.window_applications([{"student": "TEST A", "window": "Hanyang Fall", "status": "Under Review"},
                                       {"student": "TEST B", "window": "Hanyang Fall", "status": "submitted"},
                                       {"student": "TEST A", "window": "Hanyang Fall", "status": "under_review"}])
    assert [r["key"] for r in out] == ["TEST A|Hanyang Fall", "TEST A|Hanyang Fall#2"]


def test_dashboard_facts_are_keyed_by_group_and_label_and_complete_only_with_every_card():
    from src.bot import ask
    from test_freetext import dashboard_page
    facts = ask.dashboard_facts(dashboard_page())
    out = records.dashboard_facts(facts, READ_AT)
    keys = [r["key"] for r in out]
    assert "Direct / legacy pipeline|Total students" in keys and "At a glance|Applied this week" in keys
    assert len(keys) == len(set(keys))
    total = next(r for r in out if r["key"] == "Direct / legacy pipeline|Total students")
    assert total["data"]["value"] == 330 and total["content"] == \
        "Dashboard (index.php), Direct / legacy pipeline: Total students: 330."
    assert records.dashboard_complete(facts)
    from test_brief import INDEX                                   # tiles only: the cards are missing
    assert not records.dashboard_complete(ask.dashboard_facts(INDEX))


def test_calendar_items_by_event_id_never_complete():
    from src.bot import ask
    from test_freetext import calendar_html
    items, ok = ask.calendar_items(calendar_html(), date(2026, 9, 28))
    out = records.calendar_items(items, READ_AT)
    by_key = {r["key"]: r for r in out}
    assert ok and "1" in by_key and by_key["1"]["data"]["start"] == "2026-09-26"
    assert by_key["1"]["day"] == "2026-09-28" and "SEJONG DHL — DHL to send at Sejong University" in by_key["1"]["content"]
    assert all(no_placeholder(r) for r in out)


def test_a_passport_audit_is_kept_only_when_it_checked_something():
    result = {"student_id": "425", "status": "DISCREPANCY", "is_valid": False,
              "fields": {"name": {"portal": "TEST STUDENT ONE", "doc": "TEST STUDENT 0NE", "status": "TYPO",
                                  "verdict": "x"},
                         "passport_no": {"portal": "A1234567", "doc": "A1234567", "status": "MATCH", "verdict": "y"}},
              "mrz_data": {"valid": True}, "visual_data": {}, "discrepancies": ["Name differs"], "uncertain": [],
              "verdict": "Discrepancy Found: Name differs"}
    s = three_students()[0]
    r = records.passport_audit("425", "passport_425_1700000000.jpeg", result, READ_AT, student=s,
                               form={"name": "TEST STUDENT ONE"})
    assert r["key"] == "425|passport_425_1700000000.jpeg" and r["passport_no"] == "A1234567"
    assert r["data"]["result"]["discrepancies"] == ["Name differs"] and r["data"]["student_id"] == "HNG-2026-425"
    assert "Discrepancies: Name differs." in r["content"] and "passport no: portal A1234567, scan A1234567, MATCH" \
        in r["content"]
    for status in ("PORTAL_UNREADABLE", "MISSING_DOCUMENT", "OCR_UNAVAILABLE", "ERROR"):
        assert records.passport_audit("425", "p.jpg", dict(result, status=status)) is None


def test_the_watcher_memory_and_the_issue_dates():
    memory = {"version": 2, "scans": {
        "425|passport_425_1700000000.jpeg": {"uid": "425", "student_id": "HNG-2026-425", "status": "MATCH",
                                             "checked": "2026-09-28 18:56", "alert": None, "sent": False},
        "426|passport_426_1700000001.jpeg": {"uid": "426", "student_id": "", "status": "DISCREPANCY",
                                             "checked": "2026-09-28 18:56", "alert": "• *Student:* x",
                                             "sent": True, "sent_at": "2026-09-28 18:57"}}}
    out = records.passport_alerts(memory)
    assert [r["key"] for r in out] == list(memory["scans"])
    assert out[0]["content"].endswith("No alert was raised.") and out[0]["read_at"] == "2026-09-28T18:56:00+06:00"
    assert "Alert sent 2026-09-28 18:57: • *Student:* x" in out[1]["content"] and out[1]["day"] == "2026-09-28"
    issues = records.passport_issues({"a1234567": "2021-03-04", "PENDING": "2020-01-01", "B7654321": ""})
    assert [(r["key"], r["data"]["issue_date"]) for r in issues] == [("A1234567", "2021-03-04")]


STORE = {
    "documents": {"A1234567": {"fingerprint": "f", "checked": "2026-09-27T15:19:01", "student": "TEST STUDENT ONE",
                               "program": "KLP", "verdict": "REVIEW",
                               "rows": [{"doc": "01 Passport", "file": "passport.pdf", "verdict": "PASS",
                                         "detail": "PASS: valid until 2031"},
                                        {"doc": "03 Student NID", "file": "nid1.pdf", "verdict": "FLAG", "detail": "x"},
                                        {"doc": "03 Student NID", "file": "nid2.pdf", "verdict": "PASS", "detail": "y"}]}},
    "fields": {"A1234567": {"fingerprint": "g", "checked": "2026-09-27T15:19:01", "student": "TEST STUDENT ONE",
                            "program": "KLP", "rows": [{"field": "DOB", "portal": "2000-01-01", "result": "MATCH",
                                                        "detail": "found on 01 Passport"}]}},
    "corrections": [{"noticed": "2026-09-20T10:00:00", "student": "TEST STUDENT ONE", "passport": "A1234567",
                     "program": "KLP", "field": "DOB", "was": "2000-01-02", "now": "2000-01-01",
                     "was_result": "DIFFERS", "now_result": "MATCH", "detail": "found on 01 Passport"}],
}


def test_the_document_check_store_becomes_verdicts_checks_and_corrections():
    v = records.doc_verdicts("A1234567", STORE["documents"]["A1234567"])
    assert [r["key"] for r in v] == ["A1234567|01 Passport", "A1234567|03 Student NID", "A1234567|03 Student NID#2"]
    assert {r["scope"] for r in v} == {"A1234567"} and v[0]["day"] == "2026-09-27"
    assert v[0]["read_at"] == "2026-09-27T15:19:01+06:00" and v[1]["data"]["file"] == "nid1.pdf"
    f = records.field_checks("A1234567", STORE["fields"]["A1234567"])
    assert f[0]["key"] == "A1234567|DOB" and "portal value 2000-01-01 — MATCH" in f[0]["content"]
    c = records.field_corrections(STORE["corrections"])
    assert c[0]["key"] == records.field_corrections(STORE["corrections"])[0]["key"] and c[0]["scope"] == "all"
    assert "DOB was 2000-01-02 (DIFFERS), now 2000-01-01 (MATCH)" in c[0]["content"]
    d = records.doc_checks(STORE["documents"], STORE["fields"])
    assert d[0]["key"] == "A1234567" and d[0]["data"]["document_rows"] == {"PASS": 2, "FLAG": 1}
    whole, sections = records.document_check_report(STORE)
    assert whole["key"] == "document_check|2026-09-27" and whole["scope"] == "document_check"
    assert [s["scope"] for s in sections] == ["document_check|2026-09-27"]
    assert "MISSING 0, FAIL 0, FLAG 1, PASS 2" in sections[0]["content"]
    fw, fs = records.field_check_report(STORE)
    assert fw["key"] == "field_check|2026-09-27" and fs[-1]["data"]["heading"] == "Corrections (1)"


def test_ocr_pages_one_record_a_page_with_the_version_on_disk():
    cache = {"scan.pdf:100:1700000000:6": {"text": "page one\npage two", "sizes": [[1, 1], [1, 1]]},
             "PAGES:scan.pdf:100:1700000000:20": {"pages": ["page one words", "", "[unreadable: x]", "page four"],
                                                  "sideways": [4]},
             "photo.jpg:50:1700000000:6": {"text": "a photo text", "sizes": [[1, 1]]},
             "old.pdf:10:1600000000:6": {"text": "old version", "sizes": [[1, 1], [1, 1]]},
             "old.pdf:11:1700000009:6": {"text": "new version", "sizes": [[1, 1], [1, 1]]},
             "bad key": {"text": "x"}}
    out = records.doc_page_texts("A1234567", cache, "TEST STUDENT ONE", read_at=READ_AT)
    by_key = {r["key"]: r for r in out}
    assert sorted(by_key) == ["A1234567|old.pdf|all", "A1234567|photo.jpg|p1", "A1234567|scan.pdf|p1",
                              "A1234567|scan.pdf|p4"]
    assert by_key["A1234567|scan.pdf|p4"]["content"] == "Document scan.pdf of TEST STUDENT ONE (A1234567), page 4:\npage four"
    assert by_key["A1234567|scan.pdf|p4"]["data"]["sideways"] is True
    assert by_key["A1234567|old.pdf|all"]["content"].endswith("all 2 pages:\nnew version")
    chosen = records.doc_page_texts("A1234567", cache, "", {"old.pdf": (10, 1600000000)})
    assert next(r for r in chosen if "old.pdf" in r["key"])["content"] == \
        "Document old.pdf (A1234567), all 2 pages:\nold version"


def test_text_postgres_cannot_store_is_cleaned():
    r = records.make("doc_page_text", "k", "s", {"t": "a\x00b\ud800c"}, "x\x00y\udfffz", "src", READ_AT)
    assert r["data"]["t"] == "ab?c" and r["content"] == "xy?z"
    json.dumps(r, ensure_ascii=False).encode("utf-8")


def test_reports_their_sections_brief_facts_and_notifications():
    text = "📋 *HANGEUL DAILY BRIEF*\n_Facts only_\n\n1) CONSULTATIONS\n• Received today: 5\n\n2) VERIFIED\n• none"
    sections = records.split_sections(text)
    assert sections[1] == ("1) CONSULTATIONS", ["• Received today: 5"])
    whole = records.report("brief", "2026-09-28", text, {"facts": ["Received today: 5"]}, "brief", READ_AT)
    assert (whole["key"], whole["scope"], whole["day"], whole["content"]) == \
        ("brief|2026-09-28", "brief", "2026-09-28", text)
    secs = records.report_sections("brief", "2026-09-28", sections, "brief", READ_AT)
    assert [s["key"] for s in secs] == ["brief|2026-09-28|1", "brief|2026-09-28|2", "brief|2026-09-28|3"]
    assert {s["scope"] for s in secs} == {"brief|2026-09-28"} and secs[1]["content"] == "1) CONSULTATIONS\n• Received today: 5"
    facts = records.brief_facts(date(2026, 9, 28), ["Consultation requests received today: 5", ""])
    assert [(f["key"], f["scope"]) for f in facts] == [("2026-09-28|1", "2026-09-28")]
    note = records.notification("📄 KLP: sheet updated", datetime(2026, 9, 28, 18, 21, tzinfo=DHAKA), "auto_sync",
                                title="🔄 Portal sync — changes found")
    assert note["scope"] == "2026-09-28" and note["content"] == "🔄 Portal sync — changes found\n\n📄 KLP: sheet updated"
    assert note["key"] == records.sha1(note["content"], "|", "2026-09-28T18:21:00+06:00")
    whole, secs = records.missing_report("2026-09-29", [("KLP", "MARCH 2027", "HNG-2026-905", "TEST A", "8801", 2,
                                                         "Email, DOB"),
                                                        ("KLP", "MARCH 2027", "HNG-2026-906", "TEST B", "8801", 0, "")])
    assert whole["key"] == "missing_report|2026-09-29" and len(secs) == 1
    assert secs[0]["content"] == "KLP MARCH 2027 — HNG-2026-905 TEST A — 2 missing: Email, DOB"


# --------------------------------------------------------------------------- publishing

def test_only_changed_rows_are_sent(cloud):
    rows = student_rows("TEST A", "TEST B", "TEST C")
    res = publish.publish("student", "all", rows, True)
    assert (res.ok, res.changed, res.upserted, res.calls) == (True, 3, 3, 1)
    assert cloud.fake.keys("student") == ["500", "501", "502"]
    assert all(len(c) == 1 and len(c[0]["embedding"]) == 384 for c in cloud.fake.chunks.values())
    sent = sum(len(b["p_rows"]) for b in cloud.fake.syncs())
    again = publish.publish("student", "all", student_rows("TEST A", "TEST B", "TEST C"), True)
    assert again.changed == 0 and again.skipped == "no changes"
    assert sum(len(b["p_rows"]) for b in cloud.fake.syncs()) == sent        # a second identical run sends 0 rows
    changed = student_rows("TEST A", "TEST B CHANGED", "TEST C")
    res = publish.publish("student", "all", changed, True)
    last = cloud.fake.syncs()[-1]
    assert res.changed == 1 and [r["key"] for r in last["p_rows"]] == ["501"]
    assert cloud.fake.records[("student", "501")]["student_name"] == "TEST B CHANGED"


def test_a_complete_read_without_a_student_deletes_exactly_that_student(cloud):
    publish.publish("student", "all", student_rows("TEST A", "TEST B", "TEST C"), True)
    gone = [r for r in student_rows("TEST A", "TEST B", "TEST C") if r["key"] != "501"]
    res = publish.publish("student", "all", gone, True)
    assert res.deleted == 1 and cloud.fake.keys("student") == ["500", "502"]
    assert cloud.fake.syncs()[-1] == {"p_run": cloud.fake.syncs()[-1]["p_run"], "p_kind": "student",
                                      "p_scope": "all", "p_rows": [], "p_all_keys": ["500", "502"]}
    assert "student|501" not in state()["records"]                  # forgotten: it would never be sent again
    back = publish.publish("student", "all", student_rows("TEST A", "TEST B", "TEST C"), True)
    assert back.changed == 1 and cloud.fake.keys("student") == ["500", "501", "502"]


def test_a_complete_key_list_can_cover_records_not_sent_this_time(cloud):
    """The watcher audits only new scans, but its complete read of the list names every scan: the
    audits of scans still listed are kept, the one whose scan was replaced is deleted."""
    def audit(uid, scan):
        return records.passport_audit(uid, scan, {"status": "MATCH", "is_valid": True, "fields": {},
                                                  "discrepancies": [], "uncertain": [], "verdict": "ok"}, READ_AT)
    first = records.batch("passport_audit", "all", [audit("500", "passport_500_1.jpg"), audit("501", "passport_501_1.jpg")],
                          True, all_keys=["500|passport_500_1.jpg", "501|passport_501_1.jpg", "502|passport_502_1.jpg"])
    publish.publish_batches("passport_watcher", [first])
    assert cloud.fake.keys("passport_audit") == ["500|passport_500_1.jpg", "501|passport_501_1.jpg"]
    second = records.batch("passport_audit", "all", [audit("501", "passport_501_2.jpg")], True,
                           all_keys=["500|passport_500_1.jpg", "501|passport_501_2.jpg", "502|passport_502_1.jpg"])
    publish.publish_batches("passport_watcher", [second])
    assert cloud.fake.keys("passport_audit") == ["500|passport_500_1.jpg", "501|passport_501_2.jpg"]
    assert cloud.fake.syncs()[-1]["p_all_keys"] == second["all_keys"]
    assert set(state()["records"]) == {"passport_audit|500|passport_500_1.jpg", "passport_audit|501|passport_501_2.jpg"}


def test_a_partial_read_sends_no_key_list_and_deletes_nothing(cloud):
    publish.publish("student", "all", student_rows("TEST A", "TEST B", "TEST C"), True)
    res = publish.publish("student", "all", student_rows("TEST A", "TEST B X"), False)   # e.g. /students: page 1
    assert res.ok and cloud.fake.syncs()[-1]["p_all_keys"] is None and res.deleted == 0
    assert cloud.fake.keys("student") == ["500", "501", "502"]


def test_a_list_that_cannot_be_read_whole_publishes_nothing(cloud, portal):
    portal.pages["students.php"] = page(row(1, 1, "TEST A"), pg=1, pages=3, total=120)
    portal.pages["students.php?pg=2"] = page(row(2, 2, "TEST B"), pg=2, pages=3, total=120)
    # page 3 is missing: the portal answers 404, a PortalUnavailable
    batches, failed, students = asyncio.run(backfill.collect_students(admin_client, TODAY))
    assert batches == [] and students is None and failed[0].startswith("students.php: students.php: the portal answered HTTP 404")
    portal.pages["students.php?pg=3"] = page(row(3, 3, "TEST C"), pg=3, pages=3, total=120)   # pager total mismatch
    batches, failed, _ = asyncio.run(backfill.collect_students(admin_client, TODAY))
    assert batches == [] and "says 120 students" in failed[0]
    backfill.publish_all(batches, say=lambda _: None)
    assert cloud.fake.syncs() == []


def test_the_full_list_is_complete_and_its_verifications_per_day(cloud, portal):
    portal.pages["students.php"] = page(
        verified(425, 1, "TEST STUDENT ONE", "27 Sep, 17:19", applied="12 Sep 2026"),
        verified(426, 2, "TEST STUDENT TWO", "28 Sep, 09:00", applied="12 Sep 2026"),
        row(427, 3, "TEST STUDENT THREE"))
    batches, failed, students = asyncio.run(backfill.collect_students(admin_client, TODAY))
    assert failed == [] and len(students) == 3
    assert [(b["kind"], b["scope"], b["complete"]) for b in batches] == [("student", "all", True),
                                                                        ("verification", None, True)]
    assert batches[1]["scope_range"] == ["2025-09-29", "2026-09-28"]
    backfill.publish_all(batches, say=lambda _: None)
    assert cloud.fake.keys("verification", "2026-09-27") == ["425"] and cloud.fake.keys("verification", "2026-09-28") == ["426"]
    # Next read: 425's verification is gone from the list; its day, known from the state, is emptied.
    portal.pages["students.php"] = page(verified(426, 2, "TEST STUDENT TWO", "28 Sep, 09:00", applied="12 Sep 2026"),
                                        row(427, 3, "TEST STUDENT THREE"))
    batches, _, _ = asyncio.run(backfill.collect_students(admin_client, TODAY))
    backfill.publish_all(batches, say=lambda _: None)
    assert cloud.fake.keys("verification") == ["426"] and cloud.fake.keys("student") == ["426", "427"]


def test_at_most_200_rows_a_call_and_the_key_list_on_the_last_call_only(cloud):
    rows = student_rows(*[f"TEST {i}" for i in range(450)])
    res = publish.publish("student", "all", rows, True)
    syncs = cloud.fake.syncs()
    assert [len(b["p_rows"]) for b in syncs] == [200, 200, 50] and res.upserted == 450
    assert [b["p_all_keys"] is None for b in syncs] == [True, True, False]
    assert len(syncs[-1]["p_all_keys"]) == 450 and syncs[-1]["p_all_keys"] == sorted(syncs[-1]["p_all_keys"])


def test_a_long_record_gets_several_chunks_each_led_by_its_heading(cloud):
    text = " ".join(f"word{i}." for i in range(800))
    r = records.doc_page_texts("A1234567", {"PAGES:scan.pdf:1:2:20": {"pages": [text]}}, "TEST A")[0]
    publish.publish("doc_page_text", "A1234567", [r], True)
    chunks = cloud.fake.chunks[("doc_page_text", "A1234567|scan.pdf|p1")]
    assert [c["ord"] for c in chunks] == [0, 1, 2]
    assert all(c["content"].startswith("Document scan.pdf of TEST A (A1234567), page 1:\n") for c in chunks)
    assert all(len(c["content"].split()) <= 350 for c in chunks)
    assert {c["embed_model"] for c in chunks} == {cloud.stub.model_id}


@pytest.mark.parametrize("failure, reason", [
    (lambda req: httpx.Response(500, json={"code": "XX000", "message": "row 425: A1234567 ..."}),
     "HTTP 500 XX000 (Supabase server error)"),
    (lambda req: httpx.ReadTimeout("timed out", request=req), "Supabase did not answer in time (ReadTimeout)"),
    (lambda req: httpx.Response(401, json={"code": "42501", "message": "permission denied"}),
     "HTTP 401 42501 (the key was refused)"),
])
def test_a_failure_is_one_log_line_the_job_goes_on_and_the_state_stays(cloud, caplog, failure, reason):
    """Every request fails here (the hg_runs POST first): the publish returns, never raises. That
    the jobs' own Drive, Sheets and Telegram work still happens is pinned with the real jobs:
    test_cloud_jobs (the sync, the daily report), test_cloud_bot_jobs (the watcher, the brief) and
    test_cloud_commands (a command's reply); an hg_sync call that alone fails: test_cloud_fixes."""
    caplog.set_level(logging.INFO)
    cloud.fake.fail = failure
    results = publish.publish_batches("portal_sync", [
        records.batch("student", "all", student_rows("TEST A", "TEST B"), True),
        records.batch("student_documents", "all", records.student_documents(
            [{"uid": "500", "name": "TEST A", "passport": "", "program": KLP, "docs": "a.pdf"}]), True)])
    assert not any(r.ok for r in results)
    lines = cloud_warnings(caplog)
    assert [line.getMessage() for line in lines] == [f"Supabase publish failed (hg_runs): {reason}"]
    assert "A1234567" not in caplog.text and "row 425" not in caplog.text          # never the server's words
    assert state() is None                                     # not advanced for the failed rows
    cloud.fake.fail = None
    res = publish.publish("student", "all", student_rows("TEST A", "TEST B"), True)
    assert res.changed == 2 and res.upserted == 2               # sent again next run


def test_supabase_failing_mid_run_is_one_line_and_the_rest_of_the_run_is_skipped(cloud, caplog):
    cloud.fake.fail = lambda req: httpx.Response(500) if req.url.path.endswith("hg_sync") else None
    results = publish.publish_batches("full_picture", [
        records.batch("student", "all", student_rows("TEST A"), True),
        records.batch("pending_payment", "all", [], True),
        records.batch("dashboard_fact", "all", records.dashboard_facts(
            [{"group": "At a glance", "label": "Applied this week", "value": 24, "text": "24", "note": ""}]), True)])
    assert [r.ok for r in results] == [False, False, False]
    assert [line.getMessage() for line in cloud_warnings(caplog)] == \
        ["Supabase publish failed (student): HTTP 500 (Supabase server error)"]
    # The run's row is still closed, as failed: a run that failed never looks like one still going.
    assert len(cloud.fake.syncs()) == 1 and [m for m, _, _ in cloud.fake.calls] == ["POST", "POST", "PATCH"]
    run = next(iter(cloud.fake.runs.values()))
    assert run["status"] == "failed" and run["finished_at"] and run["note"] == "3 publish(es) failed"
    assert state() is None


def test_a_refused_call_after_the_run_started_is_one_line_and_other_kinds_still_go(cloud, caplog):
    cloud.fake.fail = lambda req: (httpx.Response(400, json={"code": "22023", "message": "row A1234567|x: ..."})
                                   if req.url.path.endswith("hg_sync") and b'"p_kind":"doc_verdict"' in req.content
                                   else None)
    results = publish.publish_batches("portal_sync", [
        records.batches("doc_verdict", records.doc_verdicts("A1234567", STORE["documents"]["A1234567"]), True),
        records.batch("student", "all", student_rows("TEST A"), True)])
    assert [r.ok for r in results] == [False, True]
    assert [line.getMessage() for line in cloud_warnings(caplog)] == \
        ["Supabase publish failed (doc_verdict): HTTP 400 22023 (refused)"]
    run = next(iter(cloud.fake.runs.values()))
    assert run["status"] == "partial" and run["counts"]["upserted"] == 1
    assert set(state()["records"]) == {"student|500"}


def test_every_run_has_its_hg_runs_row(cloud):
    publish.publish_batches("passport_watcher", [records.batch("student", "all", student_rows("TEST A"), True)],
                            failed_reads=["calendar.php: the portal did not answer in time"])
    (method, path, body), *rest = cloud.fake.calls
    assert (method, path, body["job"], set(body)) == ("POST", "/rest/v1/hg_runs", "passport_watcher",
                                                     {"id", "job", "started_at", "counts"})
    run_id = body["id"]
    assert cloud.fake.syncs()[0]["p_run"] == run_id
    assert cloud.fake.calls[-1][0] == "PATCH"
    run = cloud.fake.runs[run_id]
    assert run["status"] == "partial" and run["note"] == "1 read(s) failed" and run["finished_at"]
    assert run["counts"]["upserted"] == 1 and run["counts"]["failed_reads"] == ["calendar.php: the portal did not answer in time"]
    assert cloud.fake.records[("student", "500")]["run_id"] == run_id


def test_a_run_whose_row_could_not_be_written_publishes_with_no_run(cloud, caplog):
    cloud.fake.fail = lambda req: httpx.Response(409, json={"code": "23505"}) if req.url.path.endswith("hg_runs") else None
    res = publish.publish("student", "all", student_rows("TEST A"), True)
    assert res.ok and cloud.fake.syncs()[0]["p_run"] is None
    assert [line.getMessage() for line in cloud_warnings(caplog)] == \
        ["Supabase publish failed (hg_runs): HTTP 409 23505 (conflict)"]


def test_records_that_cannot_be_sent_are_left_out_and_nothing_is_deleted(cloud):
    publish.publish("student", "all", student_rows("TEST A", "TEST B"), True)
    bad = student_rows("TEST A CHANGED") + [{"key": "", "data": {}, "source": "x"},
                                            dict(student_rows("TEST C")[0], scope="other"), "not a record"]
    res = publish.publish("student", "all", bad, True)
    assert (res.left_out, res.calls, res.upserted) == (3, 1, 1)
    assert cloud.fake.syncs()[-1]["p_all_keys"] is None           # the read was said complete: not trusted
    assert cloud.fake.keys("student") == ["500", "501"]


def test_a_dry_run_writes_the_exact_payloads_and_changes_nothing(cloud):
    publish.publish("student", "all", student_rows("TEST A", "TEST B"), True, dry_run=True)
    assert cloud.fake.calls == [] and state() is None
    files = sorted((cloud.tmp / "cloud" / "dry_run").rglob("*.json"))
    assert [f.name.split("-", 1)[1] for f in files] == ["POST-hg_runs.json", "rpc-hg_sync-student.json",
                                                         "PATCH-hg_runs.json"]
    body = json.loads(files[1].read_text(encoding="utf-8"))
    assert set(body) == {"p_run", "p_kind", "p_scope", "p_rows", "p_all_keys"}
    assert body["p_all_keys"] == ["500", "501"] and body["p_run"] == json.loads(files[0].read_bytes())["id"]
    row0 = body["p_rows"][0]
    assert set(row0) == {"key", "student_uid", "student_hng_id", "student_name", "passport_no", "day", "data",
                         "content", "content_hash", "source", "read_at", "chunks"}
    assert cloud.fake._sync(dict(body, p_run=None)).status_code == 200    # the server would take it as it is
    publish.publish("student", "all", student_rows("TEST A", "TEST B"), True, dry_run=True)
    assert len(list((cloud.tmp / "cloud" / "dry_run").rglob("*hg_sync*"))) == 2   # the same again: nothing kept


def test_nothing_happens_while_publishing_is_off(cloud, monkeypatch):
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    assert publish.publish("student", "all", student_rows("TEST A"), True).skipped == "publishing is off"
    assert handoff.submit("command", [records.batch("student", "all", student_rows("TEST A"), True)]) is None
    assert cloud.fake.calls == [] and cloud.spawned == [] and not handoff.PENDING_DIR.exists()
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "")
    assert not publish.enabled()


def test_no_test_publishes_for_real_whatever_the_env_says():
    assert not publish.enabled()                                 # tests/conftest.py switches it off
    assert handoff.submit("command", [records.batch("student", "all", student_rows("TEST A"), True)]) is None


def test_the_append_only_corrections_are_never_given_a_key_list(cloud):
    publish.publish("field_correction", "all", records.field_corrections(STORE["corrections"]), False)
    assert cloud.fake.syncs()[0]["p_all_keys"] is None


def test_one_publisher_at_a_time(cloud):
    with publish.publisher_lock() as got:
        assert got
        with publish.publisher_lock() as again:                  # the same process: re-entrant
            assert again
        assert publish._os_lock(publish.LOCK_PATH, 0.3) is None   # another handle waits, then gives up
    fd = publish._os_lock(publish.LOCK_PATH, 0.3)
    assert fd is not None
    publish._os_unlock(fd)


def test_a_process_that_may_not_load_the_model_hands_the_batch_over(cloud, monkeypatch):
    embed.set_embedder(None)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    res = publish.publish("student", "all", student_rows("TEST A"), True, job="command")
    assert res.delegated and cloud.fake.calls == [] and len(cloud.spawned) == 1
    doc = json.loads(cloud.spawned[0].read_text(encoding="utf-8"))
    assert doc["job"] == "command" and doc["batches"][0]["kind"] == "student"


# --------------------------------------------------------------------------- the handoff

def test_submit_writes_one_file_and_starts_the_publisher_without_waiting(cloud, monkeypatch):
    started = []

    class FakePopen:
        def __init__(self, args, **kw):
            started.append((args, kw))

        def poll(self):
            return None

    monkeypatch.setattr(handoff, "spawn", REAL_SPAWN)
    monkeypatch.setattr(handoff.subprocess, "Popen", FakePopen)
    path = handoff.submit("passport_watcher", [records.batch("student", "all", student_rows("TEST A"), True), None],
                          failed_reads=["calendar.php: x"])
    assert path.parent == handoff.PENDING_DIR and re.fullmatch(r"\d{8}-\d{6}-\d{6}-passport_watcher\.json", path.name)
    assert not list(handoff.PENDING_DIR.glob("*.part"))
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert (doc["version"], doc["job"], doc["failed_reads"], len(doc["batches"])) == (1, "passport_watcher",
                                                                                    ["calendar.php: x"], 1)
    assert doc["created_at"].endswith("+06:00")
    (args, kw), = started
    assert args[0].lower().endswith("python.exe") or args[0].endswith("python") or "python" in args[0].lower()
    assert not args[0].lower().endswith("pythonw.exe")
    assert args[1:5] == ["-m", "src.cloud.publish", "--from", str(path)] and args[5] == "--timeout"
    assert kw["cwd"] == str(BOT_ROOT) and kw["stdin"] == subprocess.DEVNULL
    assert kw["stdout"] is kw["stderr"] and kw["stdout"] not in (subprocess.PIPE, None)
    assert kw["env"]["CUDA_VISIBLE_DEVICES"] == "" and kw["env"]["PYTHONIOENCODING"] == "utf-8"
    if os.name == "nt":
        assert kw["creationflags"] == handoff.CREATE_NO_WINDOW


def test_submit_never_raises(cloud, monkeypatch, caplog):
    def broken(path, timeout=0):
        raise OSError("no python")
    monkeypatch.setattr(handoff, "spawn", broken)
    assert handoff.submit("command", [records.batch("student", "all", student_rows("TEST A"), True)]) is None
    assert [line.getMessage() for line in cloud_warnings(caplog)] == \
        ["Supabase publish failed (command): the handoff could not be written or started (OSError)"]
    assert not list(handoff.PENDING_DIR.glob("*.json"))
    assert asyncio.run(handoff.submit_async("command", [])) is None


def test_the_publisher_publishes_a_handoff_file_and_deletes_it(cloud):
    path = handoff.write("stage_report", [records.batch("student_progress", "all", records.student_progress(
        {"500": {"pct": 22, "stage": "Payment Verified", "status": "Verified"}}), False)])
    assert publish.main(["--from", str(path), "--timeout", "60"]) == 0
    assert not path.exists() and cloud.fake.keys("student_progress") == ["500"]
    path = handoff.write("stage_report", [records.batch("student", "all", student_rows("TEST A"), True)])
    cloud.fake.fail = lambda req: httpx.Response(503)
    assert publish.process_file(path) == 0 and not path.exists()        # failed: deleted all the same
    bad = handoff.PENDING_DIR / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert publish.process_file(bad) == 1 and not bad.exists()


def test_the_real_publisher_process_starts_and_tidies_up(tmp_path):
    """A real child (no .env in this checkout: publishing is off there), started as the jobs start
    it: it reads its file, deletes it and exits 0, without the caller waiting on a pipe."""
    if (BOT_ROOT / ".env").exists() or any(k in os.environ for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY",
                                                                     "CLOUD_PUBLISH_ENABLED")):
        pytest.skip("this checkout has a .env (or Supabase settings in the environment): the child could publish")
    path = tmp_path / "20260928-182104-000000-command.json"
    path.write_text(json.dumps({"version": 1, "job": "command", "batches": []}), encoding="utf-8")
    env_log = tmp_path / "sync.log"
    old = handoff.LOG_PATH
    handoff.LOG_PATH = env_log
    try:
        proc = REAL_SPAWN(path, timeout=120)
        assert proc.wait(timeout=120) == 0
    finally:
        handoff.LOG_PATH = old
    assert not path.exists()


def test_nothing_in_the_publish_layer_imports_torch_until_it_embeds():
    code = ("import sys; import src.cloud.publish, src.cloud.handoff, src.cloud.records, src.cloud.backfill, "
            "src.cloud.embed as e; e.split_text('a b c'); print('torch' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=str(BOT_ROOT), capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip() == "False"


# --------------------------------------------------------------------------- the backfill's readers

def test_the_consultation_days_their_counts_and_the_totals(cloud, portal):
    rows = (consult_row("TEST LEAD A", "New", "28 Sep 2026"), consult_row("TEST LEAD B", "Consulted", "28 Sep 2026", by="Staff"))
    portal.pages[day_key("2026-09-28")] = day_page("2026-09-28", *rows)
    portal.pages[day_key("2026-09-27")] = day_page("2026-09-27")
    portal.pages[TOTALS_KEY] = totals_page()
    days = [date(2026, 9, 26), date(2026, 9, 27), date(2026, 9, 28)]           # 26 Sep is not served: 404
    batches, failed = asyncio.run(backfill.collect_consultations(admin_client, days, whole_range=True))
    assert failed == ["consult_requests.php 2026-09-26: consult_requests.php: the portal answered HTTP 404"]
    assert [(b["kind"], b["scope"], b["complete"], len(b["rows"])) for b in batches] == [
        ("consultation", "2026-09-27", True, 0), ("consultation", "2026-09-28", True, 2),
        ("consultation_day", "all", False, 2)]                    # a day not read: no day is deleted
    t, f = asyncio.run(backfill.collect_totals(admin_client))
    assert f == [] and t[0]["rows"][0]["data"]["counts"] == TOTALS
    backfill.publish_all(batches + t, say=lambda _: None)
    assert len(cloud.fake.keys("consultation", "2026-09-28")) == 2 and cloud.fake.keys("consultation_totals") == ["all"]


def test_the_oldest_request_is_found_from_the_portals_own_counts(monkeypatch):
    requests = [date(2026, 3, 14), date(2026, 3, 15), date(2026, 9, 1)]

    async def count(client, first, last):
        return sum(1 for d in requests if first <= d <= last)
    monkeypatch.setattr(backfill, "_range_count", count)
    assert asyncio.run(backfill.oldest_consultation_day(None, date(2026, 9, 28))) == date(2026, 3, 14)
    requests.clear()
    assert asyncio.run(backfill.oldest_consultation_day(None, date(2026, 9, 28))) is None


def test_pending_window_dashboard_and_calendar_readers(cloud, portal):
    from test_freetext import calendar_html, dashboard_page, pending_pages, window_page
    portal.pages.update(pending_pages())
    portal.pages["window_applications.php?status=under_review"] = window_page("Under Review", "submitted")
    portal.pages["index.php"] = dashboard_page()
    portal.pages["calendar.php"] = calendar_html()
    b, f = asyncio.run(backfill.collect_pending(admin_client))
    assert f == [] and [r["key"] for r in b[0]["rows"]] == ["579", "577", "501"] and b[0]["rows"][0]["data"]["badge"] == 3
    b, f = asyncio.run(backfill.collect_window_applications(admin_client))
    assert f == [] and [r["key"] for r in b[0]["rows"]] == ["Student 0|Window 0"] and b[0]["complete"]
    b, f = asyncio.run(backfill.collect_dashboard(admin_client))
    assert f == [] and b[0]["complete"] and len(b[0]["rows"]) > 20
    b, f = asyncio.run(backfill.collect_calendar(admin_client, TODAY))
    assert f == [] and not b[0]["complete"] and len(b[0]["rows"]) >= 6
    portal.pages["calendar.php"] = "<html>changed</html>"
    b, f = asyncio.run(backfill.collect_calendar(admin_client, TODAY))
    assert b == [] and f == ["calendar.php: layout not recognised"]


def test_progress_is_complete_only_when_every_page_was_read(monkeypatch):
    from src.sheets import stage_report
    pages = {"425": {"pct": 22, "stage": "Payment Verified", "status": "Verified"},
             "426": {"error": "progress.php: the portal did not answer in time"}}
    monkeypatch.setattr(stage_report, "read_progress", lambda uids: {u: pages[u] for u in uids if u in pages})
    b, f = asyncio.run(backfill.collect_progress(three_students()[:2]))
    assert not b[0]["complete"] and [r["key"] for r in b[0]["rows"]] == ["425"] and "1 of 2 pages not read" in f[0]
    del pages["426"]
    b, f = asyncio.run(backfill.collect_progress(three_students()[:1]))
    assert b[0]["complete"] and f == []


def test_the_export_is_complete_when_it_came_whole(portal):
    csv_text = chr(0xFEFF) + "Source,Student ID,Full Name,Mobile,Passport No\nDirect,HNG-2026-905,TEST A,01711000001,A1234567\n"
    portal.pages["students.php?export=csv"] = csv_text
    b, f = asyncio.run(backfill.collect_export(admin_client, total=1))
    assert f == [] and b[0]["complete"] and b[0]["rows"][0]["key"] == "Student ID:HNG-2026-905"
    b, f = asyncio.run(backfill.collect_export(admin_client, total=10))
    assert not b[0]["complete"] and f
    portal.pages["students.php?export=csv"] = "<html>login</html>"
    b, f = asyncio.run(backfill.collect_export(admin_client))
    assert b == [] and f == ["students.php?export=csv: the portal did not send the export"]


def _disk_fixture(tmp):
    data, ver, docs = tmp / "data", tmp / "data" / "verification", tmp / "docs"
    (ver / "text").mkdir(parents=True)
    (ver / "results.json").write_text(json.dumps(STORE), encoding="utf-8")
    (ver / "text" / "A1234567.json").write_text(json.dumps(
        {"PAGES:passport.pdf:10:20:20": {"pages": ["TEST STUDENT ONE page one", "page two"], "sideways": []}}),
        encoding="utf-8")
    (data / "alerted_passport_issues.json").write_text(json.dumps({"version": 2, "scans": {
        "425|passport_425_1.jpg": {"uid": "425", "student_id": "", "status": "MATCH", "checked": "2026-09-28 18:56",
                                   "alert": None, "sent": False}}}), encoding="utf-8")
    (data / "passport_issue.json").write_text(json.dumps({"by_passport": {"A1234567": "2021-03-04"}}), encoding="utf-8")
    from openpyxl import Workbook
    (data / "missing_reports").mkdir()
    wb = Workbook()
    ws = wb.active
    ws.append(["Program", "Intake", "Student ID", "Full Name", "Mobile", "Missing count", "Missing fields"])
    ws.append([KLP, "MARCH 2027", "HNG-2026-905", "TEST A", "8801711000001", 2, "Email, DOB"])
    wb.save(data / "missing_reports" / "missing_information_2026-09-28.xlsx")
    (docs / "KOREAN LANGUAGE PROGRAM (KLP)" / "TEST STUDENT ONE (A1234567)").mkdir(parents=True)
    return data, ver, docs


def test_the_backfill_from_disk_in_a_dry_run(cloud, capsys):
    data, ver, docs = _disk_fixture(cloud.tmp)
    code = backfill.main(["--dry-run", "--skip-portal", "--data-dir", str(data), "--verification-dir", str(ver),
                          "--docs-root", str(docs)])
    out = capsys.readouterr().out
    assert code == 0 and cloud.fake.calls == [] and state() is None
    for kind in ("doc_verdict", "field_check", "doc_check", "field_correction", "report", "report_section",
                 "doc_page_text", "passport_alert", "passport_issue"):
        assert f"  {kind}: " in out, kind
    assert "doc_verdict: 3 record(s), 3 to send" in out and "doc_page_text: 2 record(s), 2 to send" in out
    assert "TEST" not in out and "A1234567" not in out                  # counts only, never student data
    written = [json.loads(f.read_bytes()) for f in (cloud.tmp / "cloud" / "dry_run").rglob("*hg_sync*")]
    kinds = {w["p_kind"] for w in written}
    assert {"doc_verdict", "doc_page_text", "passport_issue", "report", "report_section"} <= kinds
    assert all(cloud.fake._sync(dict(w, p_run=None)).status_code == 200 for w in written)


def test_the_backfill_for_real_from_disk_then_again_sends_nothing(cloud, capsys):
    data, ver, docs = _disk_fixture(cloud.tmp)
    args = ["--skip-portal", "--data-dir", str(data), "--verification-dir", str(ver), "--docs-root", str(docs)]
    assert backfill.main(args) == 0
    first = len(cloud.fake.syncs())
    assert cloud.fake.keys("doc_page_text") == ["A1234567|passport.pdf|p1", "A1234567|passport.pdf|p2"]
    assert cloud.fake.keys("passport_alert") == ["425|passport_425_1.jpg"]
    assert next(iter(cloud.fake.runs.values()))["job"] == "backfill"
    assert backfill.main(args) == 0
    assert len(cloud.fake.syncs()) == first                              # nothing changed: nothing sent
    assert "0 sent" in capsys.readouterr().out


def test_the_backfill_refuses_when_publishing_is_off_or_in_a_quiet_window(cloud, monkeypatch, capsys):
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    assert backfill.main([]) == 2 and "Publishing is off" in capsys.readouterr().out
    assert backfill.quiet_reason(datetime(2026, 9, 28, 18, 5, tzinfo=DHAKA)).startswith("18:00-18:10")
    assert backfill.quiet_reason(datetime(2026, 9, 28, 8, 30, tzinfo=DHAKA)).startswith("08:25-08:40")
    assert backfill.quiet_reason(datetime(2026, 9, 28, 9, 9, tzinfo=DHAKA)).startswith("09:00-09:10")
    assert backfill.quiet_reason(datetime(2026, 9, 28, 12, 0, tzinfo=DHAKA), data_dir=cloud.tmp) is None
    (cloud.tmp / "auto_sync.lock").write_text(str(os.getpid()), encoding="utf-8")
    assert backfill.quiet_reason(datetime(2026, 9, 28, 12, 0, tzinfo=DHAKA), data_dir=cloud.tmp) == \
        "a portal sync is running (data/auto_sync.lock)"


# --------------------------------------------------------------------------- embeddings

def test_long_text_is_split_on_paragraphs_then_sentences():
    para = " ".join(f"w{i}" for i in range(200))
    assert embed.split_text(f"{para}\n\n{para}", 350) == [para, para]
    assert embed.split_text("One two. Three four.\nFive six.", 3) == ["One two.", "Three four.", "Five six."]
    assert embed.split_text("a b c d e", 2) == ["a b", "c d", "e"]
    assert embed.split_text("  \n\n ") == []
    chunks = embed.chunk_texts("Heading line:\n" + " ".join(f"x{i}." for i in range(700)), 350)
    assert len(chunks) == 3 and all(c.startswith("Heading line:\n") and len(c.split()) <= 350 for c in chunks)
    assert embed.chunk_texts("short text") == ["short text"]


def test_the_stub_embedder_gives_384_unit_numbers():
    vec = embed.StubEmbedder().embed(["hello"])[0]
    assert len(vec) == 384 and abs(sum(x * x for x in vec) - 1) < 1e-9


def test_gte_small_refuses_to_load_where_cuda_is_not_hidden(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    with pytest.raises(embed.EmbedError):
        embed.GteSmall()._load()
    assert embed.model_id() == "thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd"


def _model_cached() -> bool:
    hub = os.environ.get("HF_HUB_CACHE") or os.path.join(
        os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface"), "hub")
    return os.path.isdir(os.path.join(hub, "models--thenlper--gte-small", "snapshots", settings.CLOUD_EMBED_REVISION))


@pytest.mark.slow
@pytest.mark.skipif(not _model_cached(), reason="thenlper/gte-small at the pinned revision is not in the cache")
def test_the_real_gte_small_gives_384_unit_float32_numbers_on_the_cpu():
    code = r"""
import json, sys, time
from src.cloud import embed
embed.prepare_process()
emb = embed.get_embedder()
t = time.perf_counter()
vecs = emb.embed(["Student TEST STUDENT ONE (HNG-2026-905). Program KLP, intake MARCH 2027.", "a DHL is due"])
import torch
print(json.dumps({"dims": [len(v) for v in vecs], "norms": [sum(x * x for x in v) ** 0.5 for v in vecs],
                  "dtype": str(next(emb._model.parameters()).dtype), "cuda": torch.cuda.is_initialized(),
                  "tokens": emb.count_tokens("hello world"), "model": emb.model_id}))
"""
    out = subprocess.run([sys.executable, "-c", code], cwd=str(BOT_ROOT), capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stderr[-1500:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["dims"] == [384, 384] and all(abs(n - 1) < 1e-4 for n in got["norms"])
    assert got["dtype"] == "torch.float32" and got["cuda"] is False and got["tokens"] == 4
    assert got["model"] == "thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd"


# --------------------------------------------------------------------------- secrets and staging copies

def test_supabase_keys_and_tokens_never_reach_a_log_line(caplog):
    caplog.set_level(logging.DEBUG)
    secret = "sb_secret_" + "AbCdEf0123456789" * 2
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2lnbmF0dXJlLXNpZ25hdHVyZQ"
    logging.getLogger("httpx").info("HTTP Request: POST %s/rest/v1/rpc/hg_sync apikey: %s", URL, secret)
    logging.getLogger("httpcore.http11").debug("send_request_headers.started headers=[(b'apikey', b'%s'), "
                                               "(b'Authorization', b'Bearer %s')]", secret, jwt)
    logging.getLogger("httpx").info("key sb_publishable_%s and Bearer %s", "XyZ0123456789abc", "opaque-token-123456")
    logging.getLogger("hangeul.cloud").warning("sbp_%s", "0123456789abcdef0123456789abcdef01234567")
    text = "\n".join(r.getMessage() for r in caplog.records)
    for leaked in (secret, jwt, "XyZ0123456789abc", "opaque-token-123456", "0123456789abcdef0123456789abcdef"):
        assert leaked not in text
    assert "apikey: <redacted>" in text and "Bearer <redacted>" in text and "sb_publishable_<redacted>" in text
    import src
    assert src.redact("https://api.telegram.org/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/send") == \
        "https://api.telegram.org/bot<token>/send"


def test_the_root_staging_copies_are_byte_identical():
    for root, src_copy in (("telegram_bot.py", "src/bot/telegram_bot.py"), ("config.py", "src/config.py"),
                           ("progress_builder.py", "src/sheets/progress_builder.py")):
        assert (BOT_ROOT / root).read_bytes() == (BOT_ROOT / src_copy).read_bytes(), root
