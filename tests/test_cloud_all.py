"""Where the Supabase hook branches meet (cloud/all: core + jobs + inproc + commands).

What is pinned here, beyond each branch's own tests:
  one record a tile  the brief (get_dashboard's tiles), /stats (the same tiles) and a full index.php
                     read (ask.dashboard_facts) make the same dashboard_fact record, hash included,
                     through one conversion (records.tile_facts), so they never overwrite each other
  audits meet        a cross-check's audit of an older scan the portal still lists (commands:
                     partial) survives the watcher's complete passport_audit publish (inproc)
  job names          every hook's hg_runs job name is one of src.cloud.JOBS
  the scheduler      the real bot, built inside an event loop without polling, registers the hourly
                     full picture exactly once (IntervalTrigger 60 min, first 7.5 min after the
                     start, max_instances=1, coalesce=True) next to the six jobs it had, and the job
                     starts no process while publishing is off

Nothing reaches the network: FakeSupabase (httpx.MockTransport), the fake portal and fake Telegram.
"""
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_foundation import page, portal  # noqa: E402,F401  (portal is a fixture)
from test_jobs import Bot, scan_row, watcher  # noqa: E402,F401  (watcher is a fixture)
from test_cloud import cloud  # noqa: E402,F401  (cloud is a fixture: FakeSupabase)

from src.bot import scheduler  # noqa: E402
from src.cloud import JOBS, bot_jobs, command_hooks, full_picture, publish, records, sheet_hooks  # noqa: E402
from src.config import settings  # noqa: E402

DHAKA = ZoneInfo("Asia/Dhaka")


def test_a_tile_is_one_record_from_the_brief_stats_and_the_whole_page():
    from test_brief import INDEX
    from src.bot.ask import dashboard_facts
    from src.scraper.parsers import parse_hangeul_live_dashboard
    at = "2026-09-29T18:05:00+06:00"
    dash = parse_hangeul_live_dashboard(INDEX)
    reads = {"day": datetime(2026, 9, 29).date(), "today": datetime(2026, 9, 29).date(), "dashboard": dash}
    (brief_batch,) = [b for b in bot_jobs.brief_reads(reads, at) if b["kind"] == "dashboard_fact"]
    stats_batches, failed = command_hooks.build({"dashboard": dash, "at": {"dashboard": at}})
    (stats_batch,) = [b for b in stats_batches if b["kind"] == "dashboard_fact"]
    whole = {r["key"]: r["content_hash"] for r in records.dashboard_facts(dashboard_facts(INDEX), at)}

    def pairs(batch):
        return [(r["key"], r["content_hash"]) for r in batch["rows"]]
    assert failed == [] and pairs(brief_batch) == pairs(stats_batch) and pairs(brief_batch)
    assert brief_batch["complete"] is False and stats_batch["complete"] is False          # tiles only
    assert all(whole[k] == h for k, h in pairs(brief_batch))                               # same as the page's
    assert command_hooks.tile_facts(dash["tiles"]) == records.tile_facts(dash["tiles"])


def test_a_cross_checks_audit_of_an_older_listed_scan_survives_the_watcher(cloud, watcher):
    older, newer = "passport_502_1690000000.jpg", "passport_502_1790000000.jpg"
    card = {"id": "502", "passport_file": older,
            "audit": {"result": {"status": "MATCH", "is_valid": True, "discrepancies": []},
                      "form": {"name": "TEST NADIA"}, "at": "2026-09-29T11:00:00+06:00", "profile": None}}
    batches = command_hooks.audit_batches([card], [])
    assert [(b["kind"], b["scope"], b["complete"]) for b in batches] == [("passport_audit", "all", False)]
    publish.publish_batches("command", batches)
    assert cloud.fake.keys("passport_audit") == [f"502|{older}"]

    listed = '<a href="view_doc.php?f=' + older + '">Old passport</a><a href="student_edit.php'
    watcher.portal.pages["students.php"] = page(scan_row(501, 1, "TEST KARIM"),
                                                scan_row(502, 2, "TEST NADIA").replace('<a href="student_edit.php',
                                                                                       listed, 1))
    asyncio.run(scheduler.check_new_passport_uploads(SimpleNamespace(bot=Bot())))
    (path,) = cloud.spawned
    publish.process_file(path)
    assert cloud.fake.keys("passport_audit") == ["501|passport_501_1790000000.jpg", f"502|{older}", f"502|{newer}"]


def test_every_hook_names_its_run_with_one_of_the_known_jobs():
    names = {sheet_hooks.JOB_SYNC, sheet_hooks.JOB_MISSING, sheet_hooks.JOB_STAGE, sheet_hooks.JOB_ISSUE,
             command_hooks.JOB, full_picture.JOB, publish.DEFAULT_JOB}
    source = Path(scheduler.__file__).read_text(encoding="utf-8")
    names |= set(re.findall(r'bot_jobs\.hand_over\("([a-z_]+)"', source))
    assert {"passport_watcher", "daily_brief"} <= names
    assert names <= set(JOBS), names - set(JOBS)


# --------------------------------------------------------------------------- the scheduler

class Jobs:
    def __init__(self, sched):
        self.all = sched.get_jobs()

    def by_id(self, job_id):
        return [j for j in self.all if j.id == job_id]


def build_the_bot(monkeypatch):
    """The real Telegram application, built inside an event loop (no initialize, no polling, no
    request), with a fresh scheduler instead of the module's: -> (its jobs, the startup time)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from src.bot import telegram_bot
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456789:" + "A" * 35)
    monkeypatch.setattr(settings, "ENABLE_SCHEDULED_REPORTS", True)
    monkeypatch.setattr(settings, "JENNIE_VOICE_ENABLED", False)
    fresh = AsyncIOScheduler()
    monkeypatch.setattr(scheduler, "scheduler", fresh)

    async def build():
        started = datetime.now(DHAKA)
        app = telegram_bot.build_telegram_application()
        try:
            assert app is not None and fresh.running
            return Jobs(fresh), started, app
        finally:
            fresh.shutdown(wait=False)
    return asyncio.run(build())


@pytest.mark.parametrize("publishing", [False, True])
def test_the_bot_registers_the_hourly_full_picture_exactly_once(monkeypatch, publishing):
    if publishing:
        monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.test")
        monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "sb_secret_" + "x" * 30)
        monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    jobs, started, app = build_the_bot(monkeypatch)
    assert sorted(j.id for j in jobs.all) == ["brain_keep_warm", "cloud_full_picture", "daily_executive_briefing",
                                              "missing_info_report", "passport_issue_refresh",
                                              "passport_upload_watcher", "portal_sync"]
    (job,) = jobs.by_id("cloud_full_picture")
    assert [j for j in jobs.all if j.func is scheduler.run_full_picture] == [job]
    assert job.func is scheduler.run_full_picture and job.args == ()
    assert job.max_instances == 1 and job.coalesce is True
    assert job.trigger.interval == timedelta(minutes=60)
    first = job.trigger.get_next_fire_time(None, datetime.now(DHAKA))
    assert timedelta(minutes=7) <= first - started <= timedelta(minutes=8)                 # 7.5 min after start
    later = job.trigger.get_next_fire_time(first, first)
    assert later - first == timedelta(minutes=60)
    # The other jobs are as they were.
    assert jobs.by_id("portal_sync")[0].trigger.interval == timedelta(minutes=15)
    assert jobs.by_id("passport_upload_watcher")[0].trigger.interval == timedelta(minutes=30)
    assert jobs.by_id("daily_executive_briefing")[0].misfire_grace_time == 600


def test_the_hourly_job_starts_no_process_while_publishing_is_off(monkeypatch):
    started = []

    async def run_module(module, label):
        started.append(module)
    monkeypatch.setattr(scheduler, "_run_module", run_module)
    asyncio.run(scheduler.run_full_picture())
    assert started == []
