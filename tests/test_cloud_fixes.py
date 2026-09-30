"""Regression tests for the review of the Supabase publish layer (src/cloud), one block per finding.

What is pinned here:
  hash state      keys a complete read no longer shows are forgotten only once the call that
                  deleted them was accepted (a failed call deletes them next time); a scope's key
                  digest never makes an unacknowledged call look sent; locally unchanged records
                  count as "unchanged" in hg_runs; a failed hg_sync call (timeout, refused key)
                  leaves the state as it was, closes the run's row as failed and costs one line
  read order      a complete read older than the last one sent deletes nothing and rolls nothing
                  back, and never deletes what a newer read showed
  embed model     a process with another model than the chunks Supabase holds publishes nothing
  completeness    pending payments and window applications are complete only when their rows
                  agree with the page; the sync's CSV export only with most of the listed students;
                  a watcher memory that was lost deletes no alert; the full picture stops reading
                  once a quiet window is near
  records         no stand-in word or reader's filler in any kind's text or data, from sparse
                  input; the passport-keyed kinds carry the student's uid; a consultation is keyed
                  by its row's own hidden id
  logs            an internal error or an embedding failure never logs its text
Nothing reaches the network: Supabase is test_cloud's FakeSupabase, the portal the foundation's fake.
"""
import asyncio
import json
import logging
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_cloud import (STORE, _disk_fixture, cloud, cloud_warnings, no_placeholder,  # noqa: E402,F401
                        state, student_rows)
from test_cloud_bot_jobs import full_picture_pages, run_watcher  # noqa: E402
from test_cloud_jobs import handed, sync, telegram  # noqa: E402,F401  (sync is a fixture)
from test_foundation import KLP, TODAY, page, portal, row  # noqa: E402,F401  (portal is a fixture)
from test_jobs import Bot, bad, scan_row, watcher  # noqa: E402,F401  (watcher is a fixture)

from src.bot import scheduler  # noqa: E402
from src.cloud import (backfill, bot_jobs, command_hooks, embed, full_picture, publish, records,  # noqa: E402
                       sheet_hooks, student_index)
from src.scraper import parsers  # noqa: E402
from src.scraper.client import admin_client  # noqa: E402
from src.sheets import auto_sync  # noqa: E402

T0, T1, T2, T3 = ("2026-09-29T10:00:00+06:00", "2026-09-29T10:10:00+06:00", "2026-09-29T10:20:00+06:00",
                  "2026-09-29T10:30:00+06:00")


def students_at(at, *uids, names=None):
    """Student records of one students.php read made at `at`: one per uid, named "TEST <uid>"
    unless `names` ({uid: name}) says otherwise."""
    out = []
    for uid in uids:
        name = (names or {}).get(uid, f"TEST {uid}")
        out.append(records.student({"uid": str(uid), "student_name": name, "program": KLP,
                                    "status": "Payment Verified", "details": {"Full Name": name}}, at))
    return out


def timeout_once(fake, commit=False):
    """The next hg_sync call times out; with commit, Supabase applied it first (it only never answered)."""
    def fail(req):
        if not req.url.path.endswith("hg_sync"):
            return None
        fake.fail = None
        if commit:
            fake._sync(json.loads(req.content))
        return httpx.ReadTimeout("timed out", request=req)
    return fail


# --------------------------------------------------------------------------- keys gone, forgotten only once deleted

def test_a_delete_whose_call_failed_is_sent_again_by_the_next_complete_read(cloud):
    publish.publish("student", "all", students_at(T0, 500, 501, 502), True)
    cloud.fake.fail = timeout_once(cloud.fake)
    res = publish.publish("student", "all", students_at(T1, 500, 502), True)      # 501 left; the call times out
    assert not res.ok and cloud.fake.keys("student") == ["500", "501", "502"]
    assert "student|501" in state()["records"]                  # not forgotten: Supabase still holds it
    res = publish.publish("student", "all", students_at(T2, 500, 502), True)
    assert res.ok and res.deleted == 1 and cloud.fake.keys("student") == ["500", "502"]
    assert "student|501" not in state()["records"]


def test_a_student_a_partial_read_added_is_deleted_even_after_a_failed_call(cloud):
    publish.publish("student", "all", students_at(T0, 500, 501), True)            # complete {500, 501}
    publish.publish("student", "all", students_at(T1, 502), False)                # /students page 1: 502
    cloud.fake.fail = timeout_once(cloud.fake)
    publish.publish("student", "all", students_at(T2, 500, 501), True)            # 502 is gone; the call fails
    for _ in range(3):
        publish.publish("student", "all", students_at(T3, 500, 501), True)
    assert cloud.fake.keys("student") == ["500", "501"]


def test_an_emptied_day_whose_delete_failed_stays_known_until_it_is_deleted(cloud):
    def v(uid, day):
        return records.verification({"uid": str(uid), "name": f"TEST {uid}", "amount": "1 BDT"}, day, T0)
    window = ("2026-01-01", "2026-09-29")
    publish.publish_scopes("verification", [v(425, "2026-09-27"), v(426, "2026-09-28")], True, window)
    cloud.fake.fail = timeout_once(cloud.fake)
    publish.publish_scopes("verification", [v(426, "2026-09-28")], True, window)   # 425's day is empty now
    assert "2026-09-27" in publish.known_scopes("verification")
    publish.publish_scopes("verification", [v(426, "2026-09-28")], True, window)
    assert cloud.fake.keys("verification") == ["426"] and "2026-09-27" not in publish.known_scopes("verification")


def test_a_call_supabase_took_but_did_not_answer_never_makes_a_later_read_look_sent(cloud):
    def pending(*uids):
        return [records.make("pending_payment", str(u), "all", {"uid": str(u)}, f"Pending payment of uid {u}.",
                             "students.php?status=pending", T0, uid=u) for u in uids]
    publish.publish("pending_payment", "all", pending(500), True)
    cloud.fake.fail = timeout_once(cloud.fake, commit=True)
    publish.publish("pending_payment", "all", pending(500, 501), True)            # applied, never answered
    assert cloud.fake.keys("pending_payment") == ["500", "501"] and "pending_payment|501" not in state()["records"]
    res = publish.publish("pending_payment", "all", pending(500), True)          # 501 paid: gone from the list
    assert res.skipped != "no changes" and res.deleted == 1
    assert cloud.fake.keys("pending_payment") == ["500"]


def test_a_second_identical_run_counts_its_records_unchanged(cloud):
    publish.publish_batches("full_picture", [records.batch("student", "all", student_rows("A", "B", "C"), True)])
    results = publish.publish_batches("full_picture", [records.batch("student", "all", student_rows("A", "B", "C"), True)])
    assert results[0].skipped == "no changes" and results[0].unchanged == 3
    first, second = cloud.fake.runs.values()
    assert first["counts"]["upserted"] == 3 and first["counts"]["unchanged"] == 0
    assert second["counts"]["unchanged"] == 3 and second["counts"]["by_kind"] == {"student": [0, 0, 3]}
    assert second["status"] == "ok" and second["counts"]["older"] == 0


# --------------------------------------------------------------------------- an hg_sync call that alone fails

@pytest.mark.parametrize("failure, reason", [
    (lambda req: httpx.ReadTimeout("timed out", request=req), "Supabase did not answer in time (ReadTimeout)"),
    (lambda req: httpx.Response(401, json={"code": "42501", "message": "permission denied for A1234567"}),
     "HTTP 401 42501 (the key was refused)"),
    (lambda req: httpx.Response(503, json={"code": "XX000", "message": "row TEST A"}),
     "HTTP 503 XX000 (Supabase server error)"),
])
def test_an_hg_sync_call_that_fails_leaves_the_state_and_closes_the_run_as_failed(cloud, caplog, failure, reason):
    cloud.fake.fail = lambda req: failure(req) if req.url.path.endswith("hg_sync") else None
    results = publish.publish_batches("portal_sync", [
        records.batch("student", "all", student_rows("TEST A", "TEST B"), True),
        records.batch("dashboard_fact", "all", records.dashboard_facts(
            [{"group": "At a glance", "label": "Applied this week", "value": 24, "text": "24", "note": ""}]), True)])
    assert [r.ok for r in results] == [False, False]
    assert [line.getMessage() for line in cloud_warnings(caplog)] == [f"Supabase publish failed (student): {reason}"]
    assert "A1234567" not in caplog.text and "TEST A" not in caplog.text
    assert state() is None                                      # nothing advanced for the failed rows
    assert [m for m, p, _ in cloud.fake.calls] == ["POST", "POST", "PATCH"]     # the run's row is closed
    run = next(iter(cloud.fake.runs.values()))
    assert run["status"] == "failed" and run["finished_at"] and run["counts"]["upserted"] == 0
    cloud.fake.fail = None
    res = publish.publish("student", "all", student_rows("TEST A", "TEST B"), True)
    assert res.changed == 2 and res.upserted == 2               # the same rows go again next run


# --------------------------------------------------------------------------- reads published out of order

def test_an_older_complete_read_published_later_deletes_nothing_and_rolls_nothing_back(cloud):
    edited = {501: "TEST CHANGED"}
    publish.publish("student", "all", students_at(T0, 500, 501), True)                  # an earlier full picture
    publish.publish("student", "all", students_at(T2, 500, 501, 502, names=edited), True)   # 501 edited, 502 new
    res = publish.publish("student", "all", students_at(T1, 500, 501), True)            # the watcher's list, handed late
    assert res.older_read and res.older == 1 and res.changed == 0
    assert cloud.fake.keys("student") == ["500", "501", "502"]
    assert cloud.fake.records[("student", "501")]["student_name"] == "TEST CHANGED"
    assert not [c for c in cloud.fake.changes if c[0] == "delete"]
    # A newer complete read without 502 deletes it as ever.
    publish.publish("student", "all", students_at(T3, 500, 501, names=edited), True)
    assert cloud.fake.keys("student") == ["500", "501"]


def test_a_complete_read_never_deletes_what_a_newer_read_showed(cloud):
    publish.publish("student", "all", students_at(T0, 500, 501), True)
    publish.publish("student", "all", students_at(T2, 502), False)                # /students page 1, newer
    res = publish.publish("student", "all", students_at(T1, 500, 501), True)      # read before 502 registered
    assert res.ok and cloud.fake.keys("student") == ["500", "501", "502"]
    assert "502" in cloud.fake.syncs()[-1]["p_all_keys"]
    publish.publish("student", "all", students_at(T3, 500, 501), True)
    assert cloud.fake.keys("student") == ["500", "501"]


def test_the_watchers_batches_are_dated_by_its_list_read():
    listed = [{"uid": "425", "student_name": "TEST A", "files": ["passport_425_1790000000.jpg"]}]
    out, _ = bot_jobs.watcher_batches(listed, T1, [], {"version": 2, "scans": {}})
    assert {b["kind"]: b.get("read_at") for b in out} == {"student": T1, "passport_audit": T1, "passport_alert": T1}


# --------------------------------------------------------------------------- one embed model on every chunk

def test_a_process_with_another_embed_model_publishes_nothing(cloud, caplog):
    publish.publish("student", "all", student_rows("TEST A"), True)
    assert state()["embed_model"] == cloud.stub.model_id
    sent = len(cloud.fake.syncs())
    embed.set_embedder(embed.StubEmbedder("other/model@rev2"))
    results = publish.publish_batches("full_picture", [
        records.batch("student", "all", student_rows("TEST A CHANGED"), True),
        records.batch("consultation_totals", "all", [records.consultation_totals({"All": 3})], True)])
    assert not any(r.ok for r in results) and len(cloud.fake.syncs()) == sent
    (line,) = [x.getMessage() for x in cloud_warnings(caplog)]
    assert line.startswith("Supabase publish failed (student): Supabase holds chunks embedded with "
                           "stub/gte-small@test, but this process embeds with other/model@rev2")
    assert list(cloud.fake.runs.values())[-1]["status"] == "failed"
    assert state()["embed_model"] == "stub/gte-small@test"


def test_the_backfill_that_ignores_the_state_still_checks_the_model(cloud, capsys):
    data, ver, docs = _disk_fixture(cloud.tmp)
    publish.save_state(dict(publish._empty_state(), embed_model="thenlper/gte-small@an-old-revision"))
    assert backfill.main(["--skip-portal", "--ignore-state", "--data-dir", str(data), "--verification-dir", str(ver),
                          "--docs-root", str(docs)]) == 0
    assert cloud.fake.syncs() == []                              # nothing sent with another model
    assert state()["embed_model"] == "thenlper/gte-small@an-old-revision"
    assert publish.STATE_PATH.with_name("cloud_state.json.bak").exists()
    assert "FAILED: Supabase holds chunks embedded with" in capsys.readouterr().out


# --------------------------------------------------------------------------- pending payments and window applications

def _pending_page(*rows, badge=None):
    html = page(*rows)
    if badge is not None:
        html = html.replace("<body>", f'<body><nav><a href="students.php?status=pending">Pending Payments '
                                      f'<span class="b">{badge}</span></a></nav>')
    return html


def test_pending_payments_are_complete_only_when_the_rows_agree_with_the_page(cloud, portal):
    two = (row(501, 1, "TEST A", pay="Pending"), row(502, 2, "TEST B", pay="Pending"))
    cases = [(_pending_page(*two, badge=2), True, 2),
             (_pending_page(*two, badge=3), False, 2),                                      # the badge disagrees
             (_pending_page(*two, badge=2).replace("<th>Payment</th>", "<th>Fee</th>"), False, 0),  # renamed header
             (_pending_page(*two).replace("<th>Payment</th>", "<th>Fee</th>"), False, 0),
             (_pending_page(*two), True, 2),                   # no badge, but the rows say Pending
             (_pending_page(), True, 0)]                       # the list's own "No students found"
    for html, complete, n in cases:
        portal.pages["students.php?status=pending"] = html
        b, f = asyncio.run(backfill.collect_pending(admin_client))
        assert (b[0]["complete"], len(b[0]["rows"]), bool(f)) == (complete, n, not complete), html[-300:]
    # Published: a whole read, then one whose Payment header was renamed, deletes nobody.
    for html in cases[0][0], cases[2][0]:
        portal.pages["students.php?status=pending"] = html
        b, f = asyncio.run(backfill.collect_pending(admin_client))
        publish.publish_batches("full_picture", b, f)
    assert cloud.fake.keys("pending_payment") == ["501", "502"]
    assert list(cloud.fake.runs.values())[-1]["status"] == "partial"


def test_a_command_whose_pending_rows_do_not_match_the_badge_deletes_nothing():
    renamed = parsers.parse_students_page(_pending_page(row(501, 1, "TEST A", pay="Pending"), badge=1)
                                          .replace("<th>Payment</th>", "<th>Fee</th>"))["students"]
    batches, failed = command_hooks.build({"pending": (renamed, 1), "at": {}, "today": TODAY})
    assert batches == [] and failed == ["students.php?status=pending: 0 row(s) say Pending but the portal's badge says 1"]
    good = parsers.parse_students_page(_pending_page(row(501, 1, "TEST A", pay="Pending"), badge=1))["students"]
    batches, failed = command_hooks.build({"pending": (good, 1), "at": {}, "today": TODAY})
    assert [(b["kind"], b["complete"], len(b["rows"])) for b in batches] == [("pending_payment", True, 1)] and not failed


def test_window_applications_none_of_which_reads_under_review_are_not_complete(portal):
    from test_freetext import window_page
    for html, complete, n, failed in ((window_page("Under Review", "submitted"), True, 1, []),
                                      (window_page("In Review", "Queued"), False, 0,
                                       ["window_applications.php: no row's status reads under review "
                                        "(layout not recognised)"]),
                                      (window_page(), True, 0, [])):                 # its own empty table
        portal.pages["window_applications.php?status=under_review"] = html
        b, f = asyncio.run(backfill.collect_window_applications(admin_client))
        assert (b[0]["complete"], len(b[0]["rows"]), f) == (complete, n, failed)


# --------------------------------------------------------------------------- the sync's CSV export

def export_rows(n):
    return [{"Source": "Direct", "Student ID": f"HNG-2026-{i}", "Full Name": f"TEST {i}", "Mobile": f"0171100{i:04d}",
             "Passport No": ""} for i in range(n)]


def test_a_short_export_in_the_sync_is_never_complete(cloud, monkeypatch):
    listed = {"n": 10}
    monkeypatch.setattr(sheet_hooks, "listed_students", lambda: listed["n"])

    def export_batch(rows):
        out, failed = sheet_hooks.sync_batches({"run_at": 1790000000.0, "export": rows, "documents": []})
        (b,) = [x for x in out if x["kind"] == "student_export"]
        return b, [f for f in failed if "export" in f]
    b, f = export_batch(export_rows(10))
    assert b["complete"] and f == []
    publish.publish_batches("portal_sync", [b])
    b, f = export_batch(export_rows(2))                         # a stream cut short after its header
    assert not b["complete"] and f == ["students.php?export=csv: 2 rows, fewer than 90% of the 10 students the list shows"]
    publish.publish_batches("portal_sync", [b])
    assert len(cloud.fake.keys("student_export")) == 10        # nothing deleted
    listed["n"] = 0
    b, f = export_batch(export_rows(10))
    assert not b["complete"] and f == ["students.php?export=csv: no whole student list to check its row count by"]


def test_the_listed_students_are_the_hash_states_whole_list(cloud):
    assert sheet_hooks.listed_students() == 0
    publish.publish("student", "all", student_rows("A", "B", "C"), True)
    assert sheet_hooks.listed_students() == 3


# --------------------------------------------------------------------------- the watcher's memory

def test_a_lost_watcher_memory_deletes_no_alert(cloud, watcher, monkeypatch):
    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "TEST KARIM"), scan_row(502, 2, "TEST NADIA"))
    watcher.results.update({"501": bad(501), "502": bad(502)})
    run_watcher(Bot())
    publish.process_file(cloud.spawned.pop())
    both = ["501|passport_501_1790000000.jpg", "502|passport_502_1790000000.jpg"]
    assert cloud.fake.keys("passport_alert") == both
    Path(scheduler.ALERTED_CACHE_FILE).write_text("{ cut short", encoding="utf-8")     # the memory is lost
    monkeypatch.setattr(scheduler, "WATCHER_BUDGET_SECONDS", -1)                      # and no scan is re-audited
    run_watcher(Bot())
    path, = cloud.spawned
    doc = json.loads(path.read_text(encoding="utf-8"))
    (alerts,) = [b for b in doc["batches"] if b["kind"] == "passport_alert"]
    assert alerts["rows"] == [] and alerts["complete"] and alerts["all_keys"] == both
    publish.process_file(path)
    assert cloud.fake.keys("passport_alert") == both            # Supabase's copy is the only one left: kept
    assert cloud.fake.records[("passport_alert", both[1])]["data"]["sent"] is True
    # A student gone from the list: that alert goes, as the watcher itself forgets it.
    cloud.spawned.clear()
    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "TEST KARIM"))
    run_watcher(Bot())
    publish.process_file(cloud.spawned.pop())
    assert cloud.fake.keys("passport_alert") == both[:1]


def test_the_watched_scans_are_the_watchers_own_newest_scan_per_student():
    students = [{"uid": "501", "files": ["passport_501_1690000000.jpg", "passport_501_1790000000.pdf", "receipt_501_1.jpg"]},
                {"uid": "502", "files": ["receipt_502_1.jpg"]}, {"uid": "", "files": ["passport_x_1.jpg"]},
                {"uid": "503", "files": ["passport_503_1790000001.jpg"]}]
    assert bot_jobs.watched_scans(students) == ["501|passport_501_1790000000.pdf", "503|passport_503_1790000001.jpg"]
    for s in students:
        if s["uid"] and scheduler.passport_scan(s):
            assert f"{s['uid']}|{scheduler.passport_scan(s)}" in bot_jobs.watched_scans(students)


def test_the_backfill_publishes_the_memory_whole_only_with_the_student_list(tmp_path):
    (tmp_path / "alerted_passport_issues.json").write_text(json.dumps({"version": 2, "scans": {
        "425|passport_425_1.jpg": {"uid": "425", "status": "MATCH", "checked": "2026-09-28 18:56", "alert": None,
                                   "sent": False}}}), encoding="utf-8")
    (b,), _ = backfill.collect_watcher(tmp_path)
    assert b["complete"] is False and "all_keys" not in b
    listed = [{"uid": "425", "files": ["passport_425_1.jpg"]}, {"uid": "426", "files": ["passport_426_2.jpg"]}]
    (b,), _ = backfill.collect_watcher(tmp_path, listed, T1)
    assert b["complete"] and b["all_keys"] == ["425|passport_425_1.jpg", "426|passport_426_2.jpg"] and b["read_at"] == T1


# --------------------------------------------------------------------------- the full picture and the quiet windows

def test_the_full_picture_stops_reading_once_a_quiet_window_is_near(portal):
    portal.pages.update(full_picture_pages())
    answers = iter([None, "18:00-18:10 is a quiet window (a scheduled job runs then), less than 5 minutes from now"])
    batches, failed = asyncio.run(full_picture.collect(admin_client, TODAY, lambda: next(answers, "x")))
    assert [b["kind"] for b in batches] == ["student", "verification"]
    assert failed == ["the full picture's last 7 page read(s): not read (18:00-18:10 is a quiet window (a scheduled "
                      "job runs then), less than 5 minutes from now)"]
    assert {key.split("?")[0] for _, key in portal.asked} == {"students.php"}


def test_the_full_picture_looks_again_once_it_holds_the_lock(cloud, portal, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    portal.pages.update(full_picture_pages())
    monkeypatch.setattr(full_picture.settings, "MOCK_MODE", False)
    reasons = iter([None, "a portal sync is running (data/auto_sync.lock)"])
    monkeypatch.setattr(full_picture, "skip_reason", lambda *a, **k: next(reasons, None))
    assert full_picture.run(TODAY, client=admin_client) == 0
    assert "Full picture skipped: a portal sync is running" in caplog.text
    assert portal.asked == [] and cloud.fake.calls == []


# --------------------------------------------------------------------------- no stand-in words, from sparse input

def test_every_kind_from_sparse_input_has_no_stand_in_word():
    at = T0
    made = [
        records.verification({"uid": "425"}, "2026-09-27", at),
        *records.student_documents([{"uid": "425", "name": "", "passport": "—", "program": "", "docs": ""}], at),
        *records.student_exports([{"Student ID": "", "Full Name": "", "Mobile": "N/A", "Passport No": "PENDING",
                                   "Email": "—", "Address": "none"}], at),
        records.student_profile("425", {"full_name": "TEST A", "passport_number": "PENDING", "address": "—"}, at),
        *records.student_progress({"425": {"pct": 11}}, None, at),
        records.consultation({"name": "", "consultant": "Unassigned", "status": "New"}, "2026-09-28", at),
        *records.window_applications([{"student": "", "window": "W1", "status": "Under Review"}], at),
        *records.dashboard_facts([{"group": "Dashboard", "label": "Open windows", "value": 3, "text": "3", "note": ""}], at),
        *records.calendar_items([{"title": "", "kind": "Event", "where": "", "start": None, "end": None, "done": False,
                                  "note": "", "id": "9"}], at),
        records.passport_audit("425", "passport_425_1.jpg", {"fields": {}}, at),
        *records.doc_verdicts("A1234567", {"rows": [{"doc": "01 Passport"}]}),
        *records.doc_checks({"A1234567": {"rows": [{"doc": "01 Passport"}]}}),
        *records.field_checks("A1234567", {"rows": [{"field": "DOB"}]}),
        *records.field_corrections([{"field": "DOB", "was": "", "now": "2000-01-01", "was_result": "BLANK",
                                     "now_result": "MATCH"}]),
        *records.missing_report("2026-09-29", [("KLP", "MARCH 2027", "", "TEST A", "", 2, "Email, DOB")])[1],
    ]
    assert all(r is not None for r in made)
    for r in made:
        no_placeholder(r)
    by_kind = {r["kind"]: r for r in made}
    assert by_kind["verification"]["content"] == "Payment verification (portal uid 425). Verified on 27 Sep 2026."
    assert by_kind["student_documents"]["data"]["passport"] == "" and by_kind["student_documents"]["passport_no"] is None
    exp = by_kind["student_export"]
    assert (exp["data"]["Passport No"], exp["data"]["Mobile"], exp["data"]["Email"], exp["data"]["Address"]) == ("",) * 4
    assert exp["content"] == "Student export row (students.php?export=csv)."
    assert by_kind["student_profile"]["data"]["passport_number"] == "" and by_kind["student_profile"]["passport_no"] is None
    assert by_kind["consultation"]["data"]["consultant"] == ""
    assert by_kind["dashboard_fact"]["key"] == "|Open windows" and by_kind["dashboard_fact"]["data"]["group"] == ""
    assert by_kind["dashboard_fact"]["content"] == "Dashboard (index.php): Open windows: 3."
    assert by_kind["calendar_item"]["data"]["kind"] == "" and by_kind["calendar_item"]["content"] == "Calendar (calendar.php)."
    assert by_kind["doc_verdict"]["content"] == "Document check (A1234567): 01 Passport."
    assert by_kind["field_check"]["content"] == "Field check (A1234567): DOB."
    assert by_kind["field_correction"]["content"] == "Portal correction: DOB was (BLANK), now 2000-01-01 (MATCH)."
    assert by_kind["report_section"]["content"] == "KLP MARCH 2027 — TEST A — 2 missing: Email, DOB"


def test_a_tile_without_a_group_is_one_record_whichever_read_it_came_from():
    from src.bot import ask
    html = ('<div class="stats-row"><a class="stat-card" href="students.php"><span class="stat-num">5</span>'
            '<span class="stat-lbl">Total students</span></a></div>')
    via_ask = records.dashboard_facts(ask.dashboard_facts(html), T0)
    via_tiles = records.dashboard_facts(records.tile_facts(
        parsers.parse_hangeul_live_dashboard(html).get("tiles") or []), T0)
    assert [r["key"] for r in via_ask] == [r["key"] for r in via_tiles]
    assert [r["content_hash"] for r in via_ask] == [r["content_hash"] for r in via_tiles]
    assert all(no_placeholder(r) for r in via_ask)


def test_a_placeholder_passport_is_no_value_in_a_students_data_or_text():
    s = {"uid": "425", "student_name": "TEST A", "details": {"Full Name": "TEST A", "Passport No": "PENDING"}}
    r = records.student(s, T0)
    assert r["data"]["details"]["Passport No"] == "" and "Passport" not in r["content"] and no_placeholder(r)
    s["details"]["Passport No"] = "A1234567"
    assert "Passport A1234567." in records.student(s, T0)["content"]


# --------------------------------------------------------------------------- the passport-keyed kinds' student

def test_the_student_index_keeps_what_the_lists_showed(cloud):
    ids = student_index.remember(student_index.from_documents([
        {"uid": "425", "passport": "a1234567"}, {"uid": "426", "passport": "B7654321"},
        {"uid": "427", "passport": "B7654321"}, {"uid": "428", "passport": "PENDING"}]))
    assert ids == {"A1234567": ("425", "")}                     # a shared passport is no one's; PENDING is none
    ids = student_index.remember(student_index.from_export([{"Passport No": "A1234567", "Student ID": "hng-2026-12"}]))
    assert ids == {"A1234567": ("425", "HNG-2026-12")}
    assert student_index.load() == ids                          # kept for a run whose lists were not read
    listed = student_index.from_students([{"uid": "430", "student_id": "HNG-2026-932",
                                           "details": {"Passport No": "C1111111"}}])
    assert student_index.remember(listed, save=False)["C1111111"] == ("430", "HNG-2026-932")
    assert "C1111111" not in student_index.load()               # save=False (a dry run) wrote nothing


def test_the_document_check_records_carry_the_students_uid(cloud, monkeypatch, tmp_path):
    from src.verify import auto_verify as av
    monkeypatch.setattr(av, "TEXT_DIR", tmp_path / "text")
    result = {"checked": [{"passport": "A1234567"}], "store": STORE}
    out, _ = sheet_hooks.verify_batches(result, True, folders={}, ids={"A1234567": ("425", "HNG-2026-425")})
    rows = {b["kind"]: b["rows"] for b in out if b["rows"]}
    for kind in ("doc_verdict", "field_check", "doc_check"):
        assert {(r["student_uid"], r["student_hng_id"]) for r in rows[kind]} == {(425, "HNG-2026-425")}, kind
        assert all(r["data"]["uid"] == "425" and r["data"]["student_id"] == "HNG-2026-425" for r in rows[kind])
    (corr,) = rows["field_correction"]
    assert corr["student_uid"] == 425 and "uid" not in corr["data"]       # its key is its own data
    (check,) = [b for b in out if b["kind"] == "doc_check"]
    assert check["read_at"]                                              # dated by the store read
    publish.publish_batches("portal_sync", out)
    assert cloud.fake.records[("doc_verdict", "A1234567|01 Passport")]["student_uid"] == 425
    alone, _ = sheet_hooks.verify_batches(result, True, folders={}, ids={})
    assert {r["student_uid"] for b in alone for r in b["rows"] if b["kind"] == "doc_verdict"} == {None}


def test_the_sync_keeps_a_passports_student_when_its_list_could_not_be_read(sync, cloud):
    with telegram():
        auto_sync.run_once()
    _, kinds = handed(cloud)
    (verdicts,) = kinds["doc_verdict"]
    assert {(r["student_uid"], r["student_hng_id"]) for r in verdicts["rows"]} == {(425, "HNG-2026-012")}
    (check,) = kinds["doc_check"]
    before = check["rows"][0]["content_hash"]
    cloud.spawned.clear()
    sync.documents = RuntimeError("the portal did not answer")          # the verified list is not read this time
    auto_sync.STATE_PATH.unlink()
    with telegram():
        auto_sync.run_once()
    _, kinds = handed(cloud)
    assert kinds["doc_check"][0]["rows"][0]["content_hash"] == before   # the same record: no flip-flop
    assert kinds["doc_check"][0]["rows"][0]["student_uid"] == 425


# --------------------------------------------------------------------------- the consultation's own id

def test_a_consultation_is_keyed_by_the_hidden_id_of_its_forms():
    from test_consultations import _page, _row
    with_id = _row("TEST LEAD", "New", "28 Sep 2026").replace(
        '<form><textarea', '<form><input type="hidden" name="id" value="9001"><textarea').replace(
        '<form class="cr-inline">', '<form class="cr-inline"><input type="hidden" name="id" value="9001">')
    mixed = _row("TEST LEAD TWO", "New", "28 Sep 2026").replace(
        '<form><textarea', '<form><input type="hidden" name="id" value="9002"><textarea').replace(
        '<form class="cr-inline">', '<form class="cr-inline"><input type="hidden" name="id" value="9003">')
    rows = parsers.consultation_rows(_page(with_id, mixed, _row("TEST LEAD THREE", "New", "28 Sep 2026")))
    assert [r["id"] for r in rows] == ["9001", "", ""]          # two ids that disagree are no id
    recs, _ = records.consultations({"day": date(2026, 9, 28), "rows": rows, "complete": True}, T0)
    assert recs[0]["key"] == "9001" and len(recs[1]["key"]) == 40 and len(recs[2]["key"]) == 40


# --------------------------------------------------------------------------- what never reaches a log line

def test_an_internal_error_logs_its_type_only(cloud, caplog, monkeypatch):
    def broken(kind, scope, rows):
        raise ValueError("row of TEST SECRET NAME, passport A7654321")
    monkeypatch.setattr(publish, "_normalise", broken)
    res = publish.publish("student", "all", student_rows("TEST A"), True)
    assert not res.ok and res.error == "internal error (ValueError)"
    assert "TEST SECRET NAME" not in caplog.text and "A7654321" not in caplog.text
    assert "Supabase publish failed (student): internal error (ValueError)" in [x.getMessage() for x in cloud_warnings(caplog)]


def test_an_embedding_failure_logs_no_text(cloud, caplog, monkeypatch):
    class Model:
        @staticmethod
        def tokenizer(text, **kw):
            return {"input_ids": text.split()}

        @staticmethod
        def encode(texts, **kw):
            raise RuntimeError(f"could not embed {texts[0]}")
    gte = embed.GteSmall()
    gte._model = Model()
    embed.set_embedder(gte)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "-1")
    res = publish.publish("student", "all", students_at(T0, 500, names={500: "TEST SECRET NAME"}), True)
    assert not res.ok and res.error == "gte-small could not embed (RuntimeError)"
    assert "TEST SECRET NAME" not in caplog.text
    assert [x.getMessage() for x in cloud_warnings(caplog)] == \
        ["Supabase publish failed (student): gte-small could not embed (RuntimeError)"]
    assert state() is None and cloud.fake.syncs() == []
