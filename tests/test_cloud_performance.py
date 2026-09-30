"""The Consultant Performance page's copy to Supabase: kind consultant_performance (added to the
spec's kinds: parsed data that fits none of them; src/cloud/records.py).

What is pinned here:
  records     one record per leaderboard row, key "<period>|<first ISO day>|<name>", and one summary
              record per period window, key "<period>|<first ISO day>|summary"; scope
              "<period>|<first ISO day>|<last ISO day>" and day = the range's last day for both;
              a row's data is its figures exactly as printed plus the period, the range and top;
              the summary's data the tiles, the top performer, the sort note and the Score and
              Points help texts; the text forms the spec's; the portal's "—" is no figure (R1)
  complete    p_all_keys only for a whole read of that period's page: the leaderboard's own count
              there and equal to its rows, a readable range, every row keyed by a real name; a range
              that cannot be read publishes nothing at all (no stand-in day: R4)
  commands    /performance_today, /performance_month (and /performance, the free-text routes) hand
              the page read to the publisher after the reply, one handoff (job "command"), the reply
              the same with publishing on or off; a page that was not read publishes nothing; a
              later whole read without a consultant deletes exactly that one from the window
  full picture  two more GETs (period=today, period=month), GET only; a period that cannot be read
              is a failed read and the other is still published

Every page is synthetic, laid out like the live consult_performance.php (tests/test_performance.py's
builder), with invented consultant names; today is 28 Sep 2026 in Dhaka. Supabase is the fake of
tests/test_cloud.py; nothing reaches the network, Telegram or a real Supabase.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_cloud import cloud, no_placeholder  # noqa: E402,F401  (cloud is a fixture)
from test_cloud_commands import handoffs, hooked, process, same_reply_either_way, shape  # noqa: E402
from test_foundation import pin_today, portal, report_of  # noqa: E402,F401  (portal is a fixture)
from test_performance import (  # noqa: E402
    MONTH_KEY, POINTS_TIP, SCORE_TIP, TODAY_KEY, ZERO_TILES, perf_page, person, today_page,
)

from src.bot import performance, telegram_bot  # noqa: E402
from src.cloud import backfill, command_hooks, records  # noqa: E402
from src.config import settings  # noqa: E402
from src.scraper import parsers  # noqa: E402
from src.scraper.client import admin_client  # noqa: E402

READ_AT = "2026-09-28T18:21:04+06:00"
MONTH_SCOPE = "month|2026-09-01|2026-09-30"
TODAY_SCOPE = "today|2026-09-28|2026-09-28"
RANGE = "01 Sep – 30 Sep 2026"

ALPHA, BRAVO, CHARLIE = "COUNSELLOR ALPHA", "COUNSELLOR BRAVO", "COUNSELLOR CHARLIE"
ROWS = (person(1, ALPHA, "17.9", "18%", "26", "146", "148", "1", top=True),
        person(2, BRAVO, "15.8", "16%", "16", "100", "149.5", "5"),
        person(3, CHARLIE, "1", "0%", "2", "0", "0", "—"))                # the portal's "—": no figure
TILES = (("Consultancies done", "246"), ("Files opened", "44"), ("Conversion (file open)", "18%"),
         ("Docs ready", "6"))
TOP = (ALPHA, "17.9", "18%", "26", "146")
TODAY_ROWS = (person(1, BRAVO, "2.3", "100%", "1", "1", "1.5", "0", top=True),
              person(2, ALPHA, "0", "0%", "0", "1", "1", "0"))
TODAY_TILES = (("Consultancies done", "2"), ("Files opened", "1"), ("Conversion (file open)", "50%"),
               ("Docs ready", "0"))
TODAY_TOP = (BRAVO, "2.3", "100%", "1", "1")


@pytest.fixture(autouse=True)
def pinned_today(monkeypatch):
    pin_today(monkeypatch)


def month_html(**kw):
    return perf_page(**{"rows": ROWS, "tiles": TILES, "top": TOP, **kw})


def today_html(**kw):
    return today_page(**{"rows": TODAY_ROWS, "tiles": TODAY_TILES, "top": TODAY_TOP, **kw})


def month_page(**kw):
    return parsers.parse_consult_performance(month_html(**kw))


def month_keys(*names):
    return sorted([f"month|2026-09-01|{n}" for n in names] + ["month|2026-09-01|summary"])


# --------------------------------------------------------------------------- records

def test_every_leaderboard_row_is_one_record_in_its_period_window():
    recs = records.consultant_performance("month", month_page(), READ_AT)
    assert [r["key"] for r in recs] == ["month|2026-09-01|summary", f"month|2026-09-01|{ALPHA}",
                                        f"month|2026-09-01|{BRAVO}", f"month|2026-09-01|{CHARLIE}"]
    for r in recs:
        assert (r["kind"], r["scope"], r["day"]) == ("consultant_performance", MONTH_SCOPE, "2026-09-30")
        assert r["source"] == "consult_performance.php?period=month" and r["read_at"] == READ_AT
        assert (r["student_uid"], r["student_hng_id"], r["student_name"], r["passport_no"]) == (None,) * 4
        assert r["content_hash"] == records.content_hash(r["kind"], r["key"], r["scope"], r["data"], r["content"])
        no_placeholder(r)
    alpha, bravo, charlie = recs[1:]
    assert alpha["data"] == {"period": "month", "period_label": "This Month", "range": RANGE,
                             "first_day": "2026-09-01", "last_day": "2026-09-30", "rank": "1", "name": ALPHA,
                             "top": True, "score": "17.9", "conversion": "18%", "files_opened": "26",
                             "consultancies": "146", "points": "148", "docs_ready": "1"}
    assert alpha["content"] == (f"Consultant performance, This Month ({RANGE}): {ALPHA} — score 17.9, "
                                "conversion 18%, files opened 26, consultancies 146, points 148, docs ready 1.")
    assert bravo["data"]["top"] is False and bravo["data"]["points"] == "149.5"            # as printed
    # The portal's "—" is no figure: "" in data, named, and left out of the text.
    assert charlie["data"]["docs_ready"] == "" and charlie["data"]["blank_on_portal"] == ["docs_ready"]
    assert charlie["content"].endswith("consultancies 0, points 0.") and "docs ready" not in charlie["content"]


def test_the_summary_holds_the_tiles_the_top_performer_the_sort_note_and_the_help_texts():
    summary = records.consultant_performance("month", month_page(), READ_AT)[0]
    data = summary["data"]
    assert data["tiles"] == dict(TILES) and list(data["tiles"]) == [label for label, _ in TILES]
    top = data["top"]
    assert (top["name"], top["score"], top["conversion"], top["files_opened"], top["consultancies"]) == TOP
    assert top["label"] == "Top performer · This Month"
    assert top["metrics"] == [["Score", "17.9"], ["Conversion", "18%"], ["Files opened", "26"], ["Consultancies", "146"]]
    assert (data["sort_note"], data["score_help"], data["points_help"]) == (
        "Sorted by score, highest first", SCORE_TIP, POINTS_TIP)
    assert (data["period"], data["range"], data["first_day"], data["last_day"], data["count"]) == (
        "month", RANGE, "2026-09-01", "2026-09-30", 3)
    assert "empty_text" not in data and "blank_on_portal" not in data
    assert summary["content"] == (
        f"Consultant performance, This Month ({RANGE}): Consultancies done 246; Files opened 44; "
        f"Conversion (file open) 18%; Docs ready 6. Top performer: {ALPHA} — score 17.9, conversion 18%, "
        f"files opened 26, consultancies 146. Leaderboard: 3 consultants. Sorted by score, highest first. "
        f"Score: {SCORE_TIP}. Points: {POINTS_TIP}.")


def test_today_is_a_window_of_its_own():
    page = parsers.parse_consult_performance(today_html())
    recs = records.consultant_performance("today", page, READ_AT)
    assert [r["key"] for r in recs] == ["today|2026-09-28|summary", f"today|2026-09-28|{BRAVO}",
                                        f"today|2026-09-28|{ALPHA}"]
    assert {(r["scope"], r["day"], r["source"]) for r in recs} == {
        (TODAY_SCOPE, "2026-09-28", "consult_performance.php?period=today")}
    assert recs[1]["content"] == (f"Consultant performance, Today (28 Sep – 28 Sep 2026): {BRAVO} — score 2.3, "
                                  "conversion 100%, files opened 1, consultancies 1, points 1.5, docs ready 0.")
    assert records.performance_complete("today", page, recs) == (True, "")


def test_an_empty_leaderboard_is_the_summary_alone_and_a_whole_read():
    page = month_page(rows=(), top=None, tiles=ZERO_TILES)
    (summary,) = records.consultant_performance("month", page, READ_AT)
    assert summary["key"] == "month|2026-09-01|summary" and summary["data"]["top"] is None
    assert summary["data"]["count"] == 0 and summary["data"]["empty_text"].startswith("No consultant activity yet")
    assert "Leaderboard: 0 consultants; the page says: No consultant activity yet" in summary["content"]
    assert "Top performer" not in summary["content"]
    no_placeholder(summary)
    b, failed = records.consultant_performance_batch("month", page, READ_AT)
    assert (b["kind"], b["scope"], b["complete"], failed) == ("consultant_performance", MONTH_SCOPE, True, [])


def test_the_read_is_complete_only_when_the_page_was_read_whole():
    b, failed = records.consultant_performance_batch("month", month_page(), READ_AT)
    assert (b["scope"], b["complete"], failed) == (MONTH_SCOPE, True, [])
    assert sorted(r["key"] for r in b["rows"]) == month_keys(ALPHA, BRAVO, CHARLIE)
    # No count badge: the rows cannot be checked against the page's own total (R2).
    no_count = month_html().replace('<span class="pf-count">3</span>', "")
    b, failed = records.consultant_performance_batch("month", parsers.parse_consult_performance(no_count), READ_AT)
    assert b["complete"] is False and len(b["rows"]) == 4
    assert failed == ["consult_performance.php?period=month: the leaderboard shows no count to check its rows by"]
    # A name hidden behind Cloudflare's protection that cannot be decoded is no identity (R11).
    hidden = '<a class="__cf_email__" href="/cdn-cgi/l/email-protection" data-cfemail="zz">[email&#160;protected]</a>'
    page = month_page(rows=(ROWS[0], dict(ROWS[1], name=hidden), ROWS[2]))
    b, failed = records.consultant_performance_batch("month", page, READ_AT)
    assert b["complete"] is False and sorted(r["key"] for r in b["rows"]) == month_keys(ALPHA, CHARLIE)
    assert failed == ["consult_performance.php?period=month: 1 leaderboard row(s) show no name to key them by"]
    assert "protected" not in json.dumps(b, ensure_ascii=False)
    # Another period's page (the client refuses one; the records say so too).
    b, failed = records.consultant_performance_batch("today", month_page(), READ_AT)
    assert b["complete"] is False and failed == [
        "consult_performance.php?period=today: the page shows another period (layout not recognised)"]


@pytest.mark.parametrize("dates, dates_class", [("", ""), ("01 Jan – 31 Dec 2999", "is-hidden"), ("soon", ""),
                                                ("30 Sep – 01 Sep 2026", "")])
def test_a_range_that_cannot_be_read_as_days_publishes_nothing(dates, dates_class):
    page = month_page(dates=dates, dates_class=dates_class)
    assert records.consultant_performance("month", page, READ_AT) == []
    assert records.consultant_performance_batch("month", page, READ_AT) == (
        None, ["consult_performance.php?period=month: its range could not be read as days (layout not recognised)"])


def test_a_sparse_page_has_no_stand_in_word():
    page = {"period": "month", "period_label": "", "range_text": RANGE, "tiles": {"Docs ready": "—"}, "top": None,
            "leaderboard": [{"name": CHARLIE, "rank": "", "score": "—", "extra": {}, "top": False}],
            "count": None, "empty_text": "", "sort_note": "", "score_help": "", "points_help": ""}
    summary, row = records.consultant_performance("month", page, READ_AT)
    for r in (summary, row):
        no_placeholder(r)
    assert summary["content"] == f"Consultant performance, This Month ({RANGE}). Leaderboard: 1 consultant."
    assert summary["data"]["tiles"] == {"Docs ready": ""} and summary["data"]["blank_on_portal"] == ["tiles.Docs ready"]
    assert row["content"] == f"Consultant performance, This Month ({RANGE}): {CHARLIE}."
    assert row["data"]["score"] == "" and row["data"]["blank_on_portal"] == ["score"] and row["data"]["top"] is False
    assert records.performance_complete("month", page, [summary, row])[0] is False        # no count to check by


def test_a_changed_figure_changes_that_record_only():
    before = {r["key"]: r["content_hash"] for r in records.consultant_performance("month", month_page(), READ_AT)}
    rows = (ROWS[0], dict(ROWS[1], consultancies="101"), ROWS[2])
    after = {r["key"]: r["content_hash"] for r in records.consultant_performance("month", month_page(rows=rows), READ_AT)}
    assert [k for k in before if before[k] != after[k]] == [f"month|2026-09-01|{BRAVO}"]


# --------------------------------------------------------------------------- the commands

def test_performance_month_hands_the_page_over_after_the_reply(cloud, portal, monkeypatch):
    portal.pages[MONTH_KEY] = month_html()
    text = same_reply_either_way(monkeypatch, telegram_bot.performance_month_command, "/performance_month", [])
    assert "Consultant Performance — This Month" in text and ALPHA in text
    assert shape(cloud) == [("consultant_performance", MONTH_SCOPE, True, month_keys(ALPHA, BRAVO, CHARLIE))]
    assert handoffs(cloud)[0]["failed_reads"] == []
    assert portal.asked == [("GET", MONTH_KEY)] * 2                    # one read-only GET a command, no other page
    process(cloud)
    assert cloud.fake.keys("consultant_performance", MONTH_SCOPE) == month_keys(ALPHA, BRAVO, CHARLIE)
    (sync,) = [b for b in cloud.fake.syncs() if b["p_kind"] == "consultant_performance"]
    assert sorted(sync["p_all_keys"]) == month_keys(ALPHA, BRAVO, CHARLIE)
    # A later whole read without one consultant deletes exactly that one from the window.
    cloud.spawned.clear()
    portal.pages[MONTH_KEY] = month_html(rows=ROWS[:1] + ROWS[2:])
    hooked(telegram_bot.performance_month_command, "/performance_month", [])
    process(cloud)
    assert cloud.fake.keys("consultant_performance", MONTH_SCOPE) == month_keys(ALPHA, CHARLIE)
    assert ("delete", "consultant_performance", f"month|2026-09-01|{BRAVO}") in cloud.fake.changes


@pytest.mark.parametrize("handler, text, args", [
    (telegram_bot.performance_today_command, "/performance_today", []),
    (telegram_bot.performance_command, "/performance", []),
    (telegram_bot.handle_natural_language_message, "how is the team doing today", None),
])
def test_today_from_every_route_hands_over_the_today_window(cloud, portal, handler, text, args):
    portal.pages[TODAY_KEY] = today_html()
    chat = hooked(handler, text, args)
    assert "Consultant Performance — Today" in report_of(chat)
    assert shape(cloud) == [("consultant_performance", TODAY_SCOPE, True,
                             sorted([f"today|2026-09-28|{n}" for n in (ALPHA, BRAVO)] + ["today|2026-09-28|summary"]))]
    assert handoffs(cloud)[0]["job"] == "command"


def test_this_month_in_words_hands_over_the_month_window(cloud, portal):
    portal.pages[MONTH_KEY] = month_html()
    hooked(telegram_bot.handle_natural_language_message, "this months performance")
    hooked(telegram_bot.performance_command, "/performance month", ["month"])
    assert [k for k, s, c, _ in shape(cloud)] == ["consultant_performance"] * 2
    assert {s for _, s, _, _ in shape(cloud)} == {MONTH_SCOPE}


@pytest.mark.parametrize("html", [None, "<html>changed</html>", "month page for today"])
def test_a_page_that_was_not_read_publishes_nothing(cloud, portal, html):
    if html == "month page for today":
        portal.pages[TODAY_KEY] = month_html()                          # the page shows another period
    elif html is not None:
        portal.pages[TODAY_KEY] = html                                  # layout not recognised
    chat = hooked(telegram_bot.performance_today_command, "/performance_today", [])
    assert report_of(chat).startswith("❌ Couldn't read the portal")
    assert cloud.spawned == []


def test_another_period_asked_reads_and_publishes_nothing(cloud, portal):
    chat = hooked(telegram_bot.handle_natural_language_message, "consultant performance yesterday")
    assert "/performance\\_today and /performance\\_month" in report_of(chat)
    assert portal.asked == [] and cloud.spawned == []


def test_a_partial_read_publishes_and_deletes_nothing(cloud, portal):
    portal.pages[MONTH_KEY] = month_html()
    hooked(telegram_bot.performance_month_command, "/performance_month", [])
    process(cloud)
    cloud.spawned.clear()
    portal.pages[MONTH_KEY] = month_html(rows=ROWS[:1]).replace('<span class="pf-count">1</span>', "")
    hooked(telegram_bot.performance_month_command, "/performance_month", [])
    assert shape(cloud) == [("consultant_performance", MONTH_SCOPE, False, month_keys(ALPHA))]
    assert handoffs(cloud)[0]["failed_reads"] == [
        "consult_performance.php?period=month: the leaderboard shows no count to check its rows by"]
    process(cloud)
    assert cloud.fake.keys("consultant_performance", MONTH_SCOPE) == month_keys(ALPHA, BRAVO, CHARLIE)
    assert [b["p_all_keys"] for b in cloud.fake.syncs() if b["p_kind"] == "consultant_performance"][-1] is None


def test_nothing_is_kept_while_publishing_is_off_or_in_mock_mode(cloud, portal, monkeypatch):
    portal.pages[MONTH_KEY] = month_html()
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
    reads = {}
    text = asyncio.run(performance.build_performance_report("month", reads=reads))
    assert ALPHA in text and reads == {}
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    monkeypatch.setattr(admin_client, "mock_mode", True)
    hooked(telegram_bot.performance_month_command, "/performance_month", [])
    assert cloud.spawned == [] and not command_hooks.active()


def test_the_command_hook_builds_the_batch_the_records_build(cloud, portal):
    page = month_page()
    reads = {}
    command_hooks.seen(reads, performance=("month", page))
    batches, failed = command_hooks.build(reads)
    assert failed == [] and [(b["kind"], b["scope"], b["complete"]) for b in batches] == [
        ("consultant_performance", MONTH_SCOPE, True)]
    want = records.consultant_performance("month", page, reads["at"]["performance"])
    assert [r["content_hash"] for r in batches[0]["rows"]] == [r["content_hash"] for r in want]


# --------------------------------------------------------------------------- the hourly full picture

def test_the_full_picture_reads_both_periods_with_two_gets(portal):
    portal.pages.update({TODAY_KEY: today_html(), MONTH_KEY: month_html()})
    batches, failed = asyncio.run(backfill.collect_performance(admin_client))
    assert failed == [] and portal.asked == [("GET", TODAY_KEY), ("GET", MONTH_KEY)]
    assert [(b["kind"], b["scope"], b["complete"], len(b["rows"])) for b in batches] == [
        ("consultant_performance", TODAY_SCOPE, True, 3), ("consultant_performance", MONTH_SCOPE, True, 4)]


def test_a_period_the_full_picture_cannot_read_is_a_failed_read_and_the_other_still_goes(portal):
    portal.pages[MONTH_KEY] = month_html()
    batches, failed = asyncio.run(backfill.collect_performance(admin_client))
    assert failed == ["consult_performance.php?period=today: consult_performance.php: the portal answered HTTP 404"]
    assert [(b["scope"], b["complete"]) for b in batches] == [(MONTH_SCOPE, True)]
    portal.pages[TODAY_KEY] = today_html(dates="")                     # no readable range: nothing for today
    batches, failed = asyncio.run(backfill.collect_performance(admin_client))
    assert [b["scope"] for b in batches] == [MONTH_SCOPE] and failed == [
        "consult_performance.php?period=today: its range could not be read as days (layout not recognised)"]
