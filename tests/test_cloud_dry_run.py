"""Regression tests for the findings of the Supabase dry run (29 Sep), one block per finding.

What is pinned here:
  fillers      the words the portal types for "no value" ("N/A", "None", "--", "PENDING", "TBD"...)
               are "" in every portal kind's data and left out of its text, whole cells only; each
               is named in data["blank_on_portal"] (only when there is one); a status field's
               "Pending" is data; the list and the CSV export blank the same words (every marker
               progress_builder.clean_value blanks), and a Bangla text is a value in both
  embed error  gte-small unavailable: one log line for the whole run, the rest of it silent, never
               a raise, no call made for it and the hash state not advanced
  CUDA         the publisher process, started the way the handoff starts it, really sees no GPU
               (CUDA_VISIBLE_DEVICES=-1 survives on Windows; "" did not)
  body size    every hg_sync body stays at or under MAX_BODY bytes, besides the 200-row cap;
               p_all_keys only on the last call of a complete read, and counted in its size; a
               record larger than the cap goes alone, with one log line of its size and nothing of
               its content
Nothing reaches the network: Supabase is test_cloud's FakeSupabase (httpx.MockTransport).
"""
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path

import httpx
import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_cloud import cloud, cloud_warnings, listed, no_placeholder, state, student_rows  # noqa: E402,F401
from test_foundation import KLP, row  # noqa: E402

from src.cloud import embed, handoff, publish, records  # noqa: E402
from src.sheets import progress_builder as pb  # noqa: E402

T0 = "2026-09-29T10:00:00+06:00"
BANGLA = "আমার নাম"          # a synthetic Bangla answer ("my name")
FILLED = ("N/A", "None", "--", "PENDING", "Pending", "TBD", "nil", "null", "Not Available", "not applicable")


def with_dets(html, **fields):
    """A students.php row (test_foundation.row) with more details fields, given as label=value
    (an underscore in the label is a space, "__" a slash)."""
    items = "".join(f'<div class="det-item"><label>{k.replace("__", "/").replace("_", " ")}</label>'
                    f"<span>{v}</span></div>" for k, v in fields.items())
    return html.replace('<div class="det">', '<div class="det">' + items, 1)


# --------------------------------------------------------------------------- 1. the portal's filler words

def test_filler_words_are_whole_cells_and_a_status_keeps_its_pending():
    for word in ("N/A", " n/a ", "NA", "n.a.", "None", "NONE", "null", "nil", "-", "--", "—", "–", "...",
                 "PENDING", "Pending", "TBD", "tbd", "Not Available", "not applicable", "Not Provided"):
        assert records.is_filler(word, "IELTS/TOEFL"), word
    for value in ("NO", "NOT YET", "No", "0", "Yes", "IELTS N/A", "Pending verification", BANGLA, "", "  ", None, 0,
                  False, ["N/A"]):
        assert not records.is_filler(value, "IELTS/TOEFL"), value
    for status in ("status", "stage", "payment_status", "docs_status", "Payment Status", "Passport Status",
                   "Study Status", "VIN Status", "Visa Result", "Current Stage", "Current Status", "Next Step",
                   "Payment", "Bank Certificate", "Bank Solvency", "VIN App", "VIN Required", "visa_status"):
        assert records.is_status_field(status), status
        assert not records.is_filler("Pending", status) and not records.is_filler("PENDING", status), status
        assert records.is_filler("N/A", status), status             # only its "Pending" is a state
    for field in ("Passport Expiry", "HSC GPA", "IELTS/TOEFL", "Passport Issue Date", "Payment Amount",
                  "Final University", "Stepfather"):
        assert not records.is_status_field(field) and records.is_filler("Pending", field), field


def test_every_marker_the_sheets_blank_is_a_filler_and_a_bangla_text_is_not():
    for marker in pb._BLANKS:
        if marker:
            assert records.is_filler(marker), marker
    assert not records.is_filler(BANGLA)
    (r,) = records.student_exports([{"Student ID": "HNG-2026-905", "Full Name": "TEST A", "Questions / Notes": BANGLA,
                                     "Address": BANGLA}], T0)
    assert r["data"]["Questions / Notes"] == BANGLA and r["data"]["Address"] == BANGLA
    assert "blank_on_portal" not in r["data"] and f"Questions / Notes: {BANGLA}" in r["content"]


def test_a_students_filler_details_are_no_value_in_data_or_text_and_are_named():
    html = with_dets(row(425, 1, "TEST STUDENT ONE", hng="HNG-2026-425", pay="Pending"),
                     IELTS__TOEFL="N/A", CGPA="n/a", HSC_GPA="PENDING", Passport_Expiry="Pending", Field="NA",
                     SSC_GPA="--", Sponsor="None", University="TBD", Father_Occupation="Not Available",
                     Visa_Rejection_History="NO", Korean_Level="NOT YET", Passport_Status="Pending",
                     District=BANGLA, Passport_No="PENDING")
    (s,) = listed(html)
    r = records.student(s, T0)
    d = r["data"]["details"]
    blanked = ["CGPA", "Father Occupation", "Field", "HSC GPA", "IELTS/TOEFL", "Passport Expiry", "Passport No",
               "SSC GPA", "Sponsor", "University"]
    assert all(d[k] == "" for k in blanked)
    assert r["data"]["blank_on_portal"] == [f"details.{k}" for k in blanked]
    assert (d["Visa Rejection History"], d["Korean Level"], d["Passport Status"], d["District"]) == \
        ("NO", "NOT YET", "Pending", BANGLA)
    assert d["Payment Status"] == "pending" and r["data"]["payment_status"] == "Pending"   # statuses: data
    text = r["content"]
    for word in FILLED + ("IELTS", "CGPA", "HSC GPA", "Sponsor", "University", "expires", "blank on portal"):
        assert word not in text.replace("Payment status: Pending", "").replace("status Pending", ""), word
    assert "Payment status: Pending." in text and "Visa Rejection History: NO" in text
    assert f"district {BANGLA}" in text and "status Pending" in text
    no_placeholder(r)
    (p,) = records.pending_payments([s], 1, T0)                  # the same student, the same blanks
    assert p["data"]["blank_on_portal"] == r["data"]["blank_on_portal"] and p["data"]["payment_status"] == "Pending"
    assert "N/A" not in p["content"] and "PENDING" not in p["content"]


def test_a_record_without_a_filler_has_no_blank_on_portal_key():
    (s,) = listed(row(425, 1, "TEST STUDENT ONE", hng="HNG-2026-425"))
    r = records.student(s, T0)
    assert "blank_on_portal" not in r["data"]
    assert r["data"]["details"]["Full Name"] == "TEST STUDENT ONE"
    assert records.student(dict(s), T0)["content_hash"] == r["content_hash"]


def test_the_export_blanks_the_same_words_as_the_list_and_keeps_its_statuses():
    cells = {"Student ID": "HNG-2026-905", "Full Name": "TEST A", "Mobile": "N/A", "Passport No": "PENDING",
             "IELTS/TOEFL": "PENDING", "HSC GPA": "PENDING", "Passport Expiry": "Pending", "Passport Issue Date": "PENDING",
             "CGPA": "N/A", "Questions / Notes": "NO", "Visa Rejection History": "NO", "VIN Status": "Pending",
             "Visa Result": "Pending", "Payment Status": "Pending", "Current Status": "Pending verification",
             "Next Step": "Pending", "Bank Certificate": "Pending", "VIN App": "Not Started", "Progress %": "--"}
    (r,) = records.student_exports([cells], T0)
    d = r["data"]
    blanked = ["CGPA", "HSC GPA", "IELTS/TOEFL", "Mobile", "Passport Expiry", "Passport Issue Date", "Passport No",
               "Progress %"]
    assert all(d[k] == "" for k in blanked) and d["blank_on_portal"] == blanked
    for k in ("VIN Status", "Visa Result", "Payment Status", "Next Step", "Bank Certificate"):
        assert d[k] == "Pending", k
    assert (d["Current Status"], d["Questions / Notes"], d["VIN App"]) == ("Pending verification", "NO", "Not Started")
    assert d["stale_columns"] == records.STALE_EXPORT_COLUMNS
    text = r["content"]
    for word in ("N/A", "PENDING", "IELTS", "CGPA", "HSC GPA", "Mobile", "Passport", "Progress", "blank on portal"):
        assert word not in text, word
    assert "VIN Status: Pending" in text and "Visa Result: Pending" in text and "Visa Rejection History: NO" in text
    no_placeholder(r)
    # the student list and the export of one student leave the same fields blank
    (s,) = listed(with_dets(row(425, 1, "TEST A", hng="HNG-2026-905"), IELTS__TOEFL="PENDING", HSC_GPA="PENDING",
                            CGPA="N/A"))
    listed_blank = {b.split(".", 1)[1] for b in records.student(s, T0)["data"]["blank_on_portal"]}
    assert {"IELTS/TOEFL", "HSC GPA", "CGPA"} <= listed_blank and {"IELTS/TOEFL", "HSC GPA", "CGPA"} <= set(blanked)


def test_every_other_portal_kind_blanks_its_filler_cells():
    at = T0
    prof = records.student_profile("425", {"full_name": "TEST A", "ielts": "N/A", "passport_number": "PENDING",
                                           "payment_status": "Pending", "address": "—", "hsc_gpa": "12"}, at)
    assert (prof["data"]["ielts"], prof["data"]["address"], prof["data"]["payment_status"]) == ("", "", "Pending")
    assert prof["data"]["blank_on_portal"] == ["address", "ielts", "passport_number"]
    assert "ielts" not in prof["content"] and "payment status: Pending" in prof["content"]
    (prog,) = records.student_progress({"425": {"pct": 10, "stage": "Pending", "status": "N/A"}},
                                       {"425": {"student_id": "N/A", "student_name": "TEST A"}}, at)
    assert (prog["data"]["stage"], prog["data"]["status"], prog["data"]["blank_on_portal"]) == ("Pending", "", ["status"])
    assert "student_id" not in prog["data"] and prog["student_hng_id"] is None
    assert prog["content"] == "Progress of TEST A (portal uid 425) on progress.php: 10% overall, current stage Pending."
    (docs,) = records.student_documents([{"uid": "425", "name": "TEST A", "passport": "N/A", "program": "none",
                                          "docs": "a.pdf"}], at)
    assert (docs["data"]["passport"], docs["data"]["program"], docs["data"]["files"]) == ("", "", ["a.pdf"])
    assert docs["data"]["blank_on_portal"] == ["passport", "program"] and docs["passport_no"] is None
    ver = records.verification({"uid": "425", "name": "TEST A", "method": "N/A", "amount": "1,000.00 BDT",
                                "paid": "1,000.00 BDT"}, "2026-09-27", at)
    assert ver["data"]["method"] == "" and ver["data"]["blank_on_portal"] == ["method"] and "N/A" not in ver["content"]
    con = records.consultation({"id": "9001", "name": "TEST LEAD", "city": "N/A", "remarks": "none", "status": "New",
                                "details": "HSC 4.50 / 2024 IELTS N/A"}, "2026-09-28", at)
    assert (con["key"], con["data"]["city"], con["data"]["remarks"]) == ("9001", "", "")
    assert con["data"]["details"] == "HSC 4.50 / 2024 IELTS N/A"      # a longer text is the text's own
    assert con["data"]["blank_on_portal"] == ["city", "remarks"] and "City" not in con["content"]
    (win,) = records.window_applications([{"student": "TEST A", "window": "W1", "status": "Under Review",
                                           "note": "TBD"}], at)
    assert win["data"]["note"] == "" and win["data"]["blank_on_portal"] == ["note"] and win["key"] == "TEST A|W1"
    (cal,) = records.calendar_items([{"id": "9", "title": "TEST DEADLINE", "kind": "", "where": "N/A", "start": None,
                                      "end": None, "done": False, "note": "none"}], at)
    assert (cal["data"]["where"], cal["data"]["note"], cal["data"]["blank_on_portal"]) == ("", "", ["note", "where"])
    assert cal["content"] == "Calendar (calendar.php): TEST DEADLINE."
    for r in (prof, prog, docs, ver, win, cal):                  # (the consultation's details say N/A)
        no_placeholder(r)


# --------------------------------------------------------------------------- 2. gte-small unavailable: one line a run

class Unloadable(embed.StubEmbedder):
    """An embedder whose model cannot be loaded (what GteSmall raises when the cache is gone)."""

    def __init__(self):
        super().__init__()
        self.asked = 0

    def chunks(self, content):
        self.asked += 1
        raise embed.EmbedError("gte-small could not be loaded (OSError)")


def test_a_model_that_cannot_load_costs_one_line_for_the_whole_run(cloud, caplog):
    broken = Unloadable()
    embed.set_embedder(broken)
    exports = records.student_exports([{"Student ID": f"HNG-2026-{i}", "Full Name": f"TEST {i}"} for i in range(3)], T0)
    batches = [records.batch("student", "all", student_rows("TEST A", "TEST B"), True),
               records.batch("student_export", "all", exports, True),
               records.batch("student_progress", "all", records.student_progress({"500": {"pct": 1}}), False)]
    results = publish.publish_batches("backfill", batches)
    assert [r.ok for r in results] == [False, False, False]
    assert [x.getMessage() for x in cloud_warnings(caplog)] == \
        ["Supabase publish failed (student): gte-small could not be loaded (OSError)"]
    assert broken.asked == 1                             # the rest of the run did not try again
    assert cloud.fake.syncs() == [] and state() is None  # nothing sent, the hash state not advanced
    (run,) = cloud.fake.runs.values()
    assert run["status"] == "failed" and len(run["counts"]["failed"]) == 3
    embed.set_embedder(cloud.stub)                       # a new run tries again, and sends
    assert publish.publish("student", "all", student_rows("TEST A", "TEST B"), True).ok


def test_a_model_that_fails_mid_read_keeps_what_was_accepted_and_is_silent_after(cloud, caplog, monkeypatch):
    class FailsSecond(embed.StubEmbedder):
        def embed(self, texts):
            if self.calls:
                raise embed.EmbedError("gte-small could not embed (RuntimeError)")
            return super().embed(texts)
    monkeypatch.setattr(publish, "MAX_ROWS", 2)
    embed.set_embedder(FailsSecond())
    with publish.run("backfill") as r:
        first = publish.publish("student", "all", student_rows("TEST A", "TEST B", "TEST C", "TEST D"), True)
        again = publish.publish("student_progress", "all", records.student_progress({"500": {"pct": 1}}), False)
    assert not first.ok and not again.ok and again.error.startswith("skipped (gte-small could not embed")
    assert r.down and [x.getMessage() for x in cloud_warnings(caplog)] == \
        ["Supabase publish failed (student): gte-small could not embed (RuntimeError)"]
    assert len(cloud.fake.syncs()) == 1 and cloud.fake.syncs()[0]["p_all_keys"] is None
    assert sorted(k for k in state()["records"]) == ["student|500", "student|501"]   # the accepted call only
    assert "student|all" not in state()["scopes"]        # the read was not sent whole: no digest


# --------------------------------------------------------------------------- 3. the GPU is really hidden

PROBE = r"""
import json, os, sys

def os_value():
    # the process's real environment (what the CUDA runtime reads), not Python's copy of it
    if os.name != "nt":
        return os.environ.get("CUDA_VISIBLE_DEVICES")
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    buf = ctypes.create_unicode_buffer(64)
    ctypes.set_last_error(0)
    n = k.GetEnvironmentVariableW("CUDA_VISIBLE_DEVICES", buf, 64)
    return None if n == 0 and ctypes.get_last_error() == 203 else buf.value

inherited = os_value()
from src.cloud import embed
embed.prepare_process()
import torch
print(json.dumps({"inherited": inherited, "after": os_value(), "cpu_only": embed.cpu_only_process(),
                  "available": torch.cuda.is_available(), "count": torch.cuda.device_count()}))
"""


@pytest.mark.skipif(importlib.util.find_spec("torch") is None, reason="torch is not installed here")
def test_the_publisher_process_started_as_the_handoff_starts_it_sees_no_gpu(tmp_path):
    log = tmp_path / "probe.log"
    with open(log, "a", encoding="utf-8") as out:
        proc = handoff.start(["-c", PROBE], out)          # handoff.spawn's python, folder, env and flags
    assert proc.wait(timeout=600) == 0, log.read_text(encoding="utf-8")[-1500:]
    got = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert got["inherited"] == "-1" and got["after"] == "-1" and got["cpu_only"] is True
    assert got["available"] is False or got["count"] == 0


def test_every_entry_point_hides_the_gpu_with_minus_one():
    assert handoff.child_env()["CUDA_VISIBLE_DEVICES"] == embed.NO_GPU == "-1"
    for module in ("publish", "backfill", "full_picture"):
        source = (BOT_ROOT / "src" / "cloud" / f"{module}.py").read_text(encoding="utf-8")
        assert 'os.environ["CUDA_VISIBLE_DEVICES"] = "-1"' in source, module
        assert 'os.environ["CUDA_VISIBLE_DEVICES"] = ""' not in source, module


def test_an_empty_cuda_value_is_not_a_cpu_only_process(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    assert not embed.cpu_only_process()
    with pytest.raises(embed.EmbedError):
        embed.GteSmall()._load()
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "-1")
    assert embed.cpu_only_process()


# --------------------------------------------------------------------------- 4. the body size

@pytest.fixture
def bodies(cloud, monkeypatch):
    """The raw bytes of every hg_sync body sent (the fake Supabase answers them all)."""
    seen = []

    def handler(request):
        if request.url.path.endswith("/rpc/hg_sync"):
            seen.append(len(request.content))
        return cloud.fake(request)
    monkeypatch.setattr(publish, "TRANSPORT", httpx.MockTransport(handler))
    return seen


def bulky(n, words=600, first=600):
    """Students with a long details field each (about 25 KB a row with its chunks)."""
    return [records.student({"uid": str(first + i), "student_name": f"TEST BULK {i}", "program": KLP,
                             "status": "Payment Verified",
                             "details": {"Full Name": f"TEST BULK {i}",
                                         "Questions / Notes for Counselor": " ".join(f"n{i}w{j}" for j in range(words))}},
                            T0) for i in range(n)]


def test_calls_are_split_to_stay_under_the_body_cap_with_the_key_list_on_the_last(cloud, bodies):
    rows = bulky(90)
    res = publish.publish("student", "all", rows, True)
    syncs = cloud.fake.syncs()
    assert res.ok and res.upserted == 90 and len(syncs) >= 3 and res.calls == len(syncs)
    assert max(bodies) <= publish.MAX_BODY == 1_000_000
    assert all(len(b["p_rows"]) <= publish.MAX_ROWS for b in syncs)
    assert [b["p_all_keys"] is None for b in syncs] == [True] * (len(syncs) - 1) + [False]
    assert syncs[-1]["p_all_keys"] == sorted(r["key"] for r in rows)
    assert sorted(r["key"] for b in syncs for r in b["p_rows"]) == sorted(r["key"] for r in rows)   # each once
    assert len(state()["records"]) == 90 and "student|all" in state()["scopes"]
    publish.publish("student", "all", rows[1:], True)            # a complete read without one: exactly it goes
    assert cloud.fake.keys("student") == sorted(r["key"] for r in rows[1:])


def test_a_partial_read_split_by_size_sends_no_key_list(cloud, bodies):
    publish.publish("student", "all", bulky(90), False)
    assert len(bodies) >= 3 and max(bodies) <= publish.MAX_BODY
    assert {b["p_all_keys"] is None for b in cloud.fake.syncs()} == {True}


def test_the_key_list_is_counted_in_the_last_calls_size(cloud, bodies, monkeypatch):
    monkeypatch.setattr(publish, "MAX_BODY", 120_000)
    rows = student_rows(*[f"TEST {i}" for i in range(40)])
    extra = [f"{9000 + i}" for i in range(12_000)]               # a long key list (~85 KB of JSON)
    res = publish.publish("student", "all", rows, True, all_keys=extra)
    syncs = cloud.fake.syncs()
    assert res.ok and max(bodies) <= 120_000 and len(syncs) >= 2
    assert syncs[-1]["p_all_keys"] is not None and len(syncs[-1]["p_all_keys"]) == 12_040
    assert all(b["p_all_keys"] is None for b in syncs[:-1])
    assert sum(len(b["p_rows"]) for b in syncs) == 40
    monkeypatch.setattr(publish, "MAX_BODY", 50_000)             # the key list alone is over the cap
    res = publish.publish("student", "all", student_rows(*[f"TEST {i}" for i in range(41)]), True, all_keys=extra)
    last = cloud.fake.syncs()[-1]
    assert res.ok and last["p_rows"] == [] and len(last["p_all_keys"]) == 12_041


def test_a_record_larger_than_the_cap_goes_alone_with_one_line_of_its_size(cloud, bodies, monkeypatch, caplog):
    monkeypatch.setattr(publish, "MAX_BODY", 100_000)
    big = bulky(1, words=9000, first=700)[0]                     # ~0.4 MB with its 26 chunks
    rows = bulky(6) + [big] + bulky(6, first=800)
    res = publish.publish("student", "all", rows, True)
    syncs = cloud.fake.syncs()
    assert res.ok and res.upserted == 13
    alone = [b for b in syncs if any(r["key"] == "700" for r in b["p_rows"])]
    assert len(alone) == 1 and len(alone[0]["p_rows"]) == 1 and alone[0]["p_all_keys"] is None
    assert sorted(bodies)[-1] > 100_000 and sorted(bodies)[-2] <= 100_000       # only that one is over
    lines = [x.getMessage() for x in cloud_warnings(caplog)]
    assert len(lines) == 1 and lines[0].startswith("Supabase publish (student): one record makes a body of ")
    assert "over the 100000-byte cap; it is sent in a call of its own." in lines[0]
    assert "TEST BULK" not in caplog.text and "n0w1" not in caplog.text          # its size only
    assert syncs[-1]["p_all_keys"] is not None and "student|700" in state()["records"]


def test_the_split_keeps_every_row_once_in_order_and_every_body_under_the_cap(monkeypatch, caplog):
    import random
    rnd = random.Random(20260929)
    monkeypatch.setattr(publish, "MAX_BODY", 5_000)
    head = {"p_run": "00000000-0000-0000-0000-000000000000", "p_kind": "student", "p_scope": "all"}
    for _ in range(300):
        rows = [{"key": str(i), "pad": "x" * rnd.choice([10, 200, 900, 2500, 4800, 7000])}
                for i in range(rnd.randint(0, 25))]
        keys = [str(i) for i in range(rnd.choice([0, 10, 300, 1200]))] if rnd.random() < 0.6 else None
        calls = publish._by_size("student", head, rows, keys)
        assert [r["key"] for c in calls for r in c] == [r["key"] for r in rows]          # each once, in order
        for n, c in enumerate(calls):
            ks = keys if keys is not None and n == len(calls) - 1 else None
            size = len(publish._body(dict(head, p_rows=c, p_all_keys=ks)))
            alone = len(c) == 1 and len(publish._body(dict(head, p_rows=c, p_all_keys=None))) > 5_000
            keys_alone = not c and ks is not None
            assert size <= 5_000 or alone or keys_alone
        assert calls and all(calls[:-1])                  # only the last call may be empty (the key list's)


def test_a_dry_run_writes_the_same_split_bodies(cloud, monkeypatch):
    publish.publish("student", "all", bulky(90), True, dry_run=True)
    files = sorted((cloud.tmp / "cloud" / "dry_run").rglob("*hg_sync*"))
    assert len(files) >= 3 and max(f.stat().st_size for f in files) <= publish.MAX_BODY
    bodies = [json.loads(f.read_bytes()) for f in files]
    assert [b["p_all_keys"] is None for b in bodies] == [True] * (len(bodies) - 1) + [False]
    assert cloud.fake.calls == [] and state() is None
