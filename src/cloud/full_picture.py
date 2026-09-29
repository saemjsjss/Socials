"""The hourly "full picture" for Supabase, a process of its own (spec step 4):

    python -m src.cloud.full_picture [--dry-run]

The bot's scheduler starts it once an hour (scheduler.run_full_picture: IntervalTrigger(60 min),
max_instances=1, coalesce=True) the way it starts the portal sync (the venv's python.exe, UTF-8,
no window, its output appended to hangeul_sync.log), so Jeannie is complete even on a day nobody
asks the bot anything. With a portal session of its own, GET only (portal_get; the login POST is
the only other request), it reads

  every page of students.php                    student (complete) and verification (per stamp day)
  every page of students.php?status=pending     pending_payment (complete)
  consult_requests.php, yesterday and today     consultation (per day) and consultation_day
  consult_requests.php?status=file_opened       consultation_totals
  window_applications.php?status=under_review   window_application
  index.php                                     dashboard_fact (its tiles and cards)
  calendar.php                                  calendar_item (never complete)

with the backfill's own readers (src.cloud.backfill.collect_*), then publishes them in one run
(publish.publish_batches, job "full_picture"): only what changed is embedded and sent, and only a
whole read deletes anything. A read that fails publishes nothing and is named in the run's failed
reads; once the portal does not answer, the pages after it are not tried. CUDA is hidden before
anything can import torch, so gte-small runs on the CPU (R12), and only when something changed.

It does nothing while publishing is off or the bot is in mock mode; nothing in (or less than
LEAD_MINUTES before) the quiet windows of the scheduled jobs (18:00-18:10, 08:25-08:40,
09:00-09:10) or while a portal sync runs (data/auto_sync.lock), checked by the scheduler before it
starts this, again here, again once it holds the publish lock, and before every page it reads (a
run that began just before a quiet window stops reading there); and nothing while another
publisher (the backfill) holds the publish lock. It stops itself after DEADLINE seconds, well
before the next hour. It sends nothing to Telegram and never logs student data.
"""
from __future__ import annotations

import os
import sys

if __name__ == "__main__":          # a CPU-only embedding process: before torch can be imported
    os.environ["CUDA_VISIBLE_DEVICES"] = ""

import argparse
import asyncio
import logging
import threading
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.cloud import backfill, publish, records
from src.config import settings
from src.scraper.client import HangeulAdminClient, PortalUnavailable

logger = logging.getLogger("hangeul.cloud")

JOB = "full_picture"
DEADLINE = 45 * 60          # seconds: the process stops itself long before the next hour
LOCK_WAIT = 120.0           # seconds to wait for another publisher before skipping this hour
LEAD_MINUTES = 5            # a run takes a minute or two: it does not start this close to a quiet window
PORTAL_DOWN = "the portal did not answer"

Batches = List[Dict[str, Any]]


def skip_reason(at=None, data_dir=None) -> Optional[str]:
    """Why the full picture must not start now, or None when it may: a quiet window of the
    scheduled jobs now or within LEAD_MINUTES, or a portal sync running (backfill.quiet_reason)."""
    at = at or records.now()
    reason = backfill.quiet_reason(at, data_dir)
    if reason:
        return reason
    soon = backfill.quiet_reason(at + timedelta(minutes=LEAD_MINUTES), data_dir)
    return f"{soon}, less than {LEAD_MINUTES} minutes from now" if soon else None


class PortalSession(HangeulAdminClient):
    """The full picture's own portal session. Once the portal did not answer (a timeout, a refused
    connection, a login that could not reach it) the pages after it are not tried: each is then a
    PortalUnavailable at once ("<page>: not read: the portal did not answer")."""

    down = ""

    async def portal_get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: float = 60.0):
        if self.down:
            raise PortalUnavailable(f"{path}: not read: {self.down}", unreachable=True)
        try:
            return await super().portal_get(path, params=params, timeout=timeout)
        except PortalUnavailable as e:
            if e.unreachable:
                self.down = PORTAL_DOWN
            raise


async def collect(client, today: date, may_read: Optional[Callable[[], Optional[str]]] = None
                  ) -> Tuple[Batches, List[str]]:
    """Every page of the full picture (see the module docstring), one after another, with the
    backfill's readers -> (their batches, the reads that failed). `may_read` (skip_reason) is
    asked before each page: once it gives a reason (a quiet window is near, a portal sync began),
    the pages after are not read (one failed read says why); what was read is each a whole read of
    its own page, and goes as it is."""
    batches, failed = [], []
    steps = [lambda: backfill.collect_students(client, today),
             lambda: backfill.collect_pending(client),
             lambda: backfill.collect_consultations(client, [today - timedelta(days=1), today]),
             lambda: backfill.collect_totals(client),
             lambda: backfill.collect_window_applications(client),
             lambda: backfill.collect_dashboard(client),
             lambda: backfill.collect_calendar(client, today)]
    for n, step in enumerate(steps):
        stop = may_read() if may_read is not None else None
        if stop:
            failed.append(f"the full picture's last {len(steps) - n} page read(s): not read ({stop})")
            break
        got, why, *_ = await step()
        batches += got
        failed += why
    return batches, failed


async def _read(today: date, client=None, may_read=None) -> Tuple[Batches, List[str]]:
    own = client is None
    client = client or PortalSession()
    try:
        return await collect(client, today, may_read)
    finally:
        if own:
            await client.close()


def run(today: Optional[date] = None, *, client=None, dry_run: bool = False) -> int:
    """One full picture: the checks, the reads, the publish. -> the exit status (0 when skipped)."""
    if not dry_run and not publish.enabled():
        logger.info("Full picture skipped: publishing is off.")
        return 0
    if settings.MOCK_MODE:
        logger.warning("Full picture skipped: the bot is in mock mode (MOCK_MODE), so nothing is live.")
        return 0
    reason = skip_reason()
    if reason:
        logger.info("Full picture skipped: %s.", reason)
        return 0
    with publish.publisher_lock(LOCK_WAIT) as got:
        if not got:
            logger.info("Full picture skipped: another publisher (the backfill?) holds the publish lock.")
            return 0
        # The lock can take LOCK_WAIT seconds: look again, and before every page (a run that
        # started just before a quiet window must not read the portal into it).
        reason = skip_reason()
        if reason:
            logger.info("Full picture skipped: %s.", reason)
            return 0
        started = time.perf_counter()
        today = today or records.now().date()
        batches, failed = asyncio.run(_read(today, client, lambda: skip_reason()))
        read_seconds = time.perf_counter() - started
        results = publish.publish_batches(JOB, batches, failed, dry_run=dry_run)
    logger.info("Full picture: %d batch(es) read in %.1f s, %d read(s) failed; %d publish(es), %d failed.",
                len(batches), read_seconds, len(failed), len(results), sum(1 for r in results if not r.ok))
    return 0


def _deadline(seconds: float) -> threading.Timer:
    """Stop this process after `seconds` (a hung read or model must not live on into the next
    hour): one log line; the publish lock is released by the OS."""
    def expire():
        logger.warning("Supabase publish failed (%s): the full picture ran over %d s and was stopped",
                       JOB, int(seconds))
        os._exit(3)
    timer = threading.Timer(max(1.0, seconds), expire)
    timer.daemon = True
    timer.start()
    return timer


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Read the portal's full picture (GET only) and publish it to Supabase.")
    ap.add_argument("--dry-run", action="store_true", help="write the payloads to data/cloud/dry_run/, send nothing")
    args = ap.parse_args(argv)
    from src.cloud import embed
    if not embed.custom_embedder():
        try:
            embed.prepare_process()            # CPU only, offline; a no-op when already done
        except embed.EmbedError as e:
            logger.warning("Supabase publish failed (%s): %s", JOB, e)
            return 2
    timer = _deadline(DEADLINE)
    try:
        return run(dry_run=args.dry_run)
    except Exception as e:
        logger.warning("Supabase publish failed (%s): internal error (%s)", JOB, type(e).__name__)
        return 1
    finally:
        timer.cancel()


if __name__ == "__main__":
    from src.cloud import embed as _embed
    _embed.prepare_process()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from src.cloud import full_picture as _full_picture      # the module itself, not this __main__ copy
    sys.exit(_full_picture.main())
