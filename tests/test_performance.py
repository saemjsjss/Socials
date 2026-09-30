"""/performance_today, /performance_month (and /perf_today, /perf_month, /performance [today|month]),
and their free-text routes: the portal's own Consultant Performance page (Leads > Performance,
consult_performance.php), and only that page's data.

What is pinned here: one read-only GET of consult_performance.php?period=today or ?period=month
(the page's own period links; its Custom range form is never used, no other page is read); the
tiles, the top performer card and the whole leaderboard parsed by their labels and header texts,
every figure exactly as the portal prints it ("17.9", "18%", "149.5"); columns found by the
header's words, so a reordered header reads the same and an unknown column is kept with its own
header; the page must say it shows the period asked (it shows This Month for a period it does not
take); a recognised empty state is an empty leaderboard, never an error; a page with no tiles, no
leaderboard header, a missing column, a row or a figure it cannot read, or a count badge that does
not match its rows is "layout not recognised"; a portal that cannot be read says so, never zeros;
where the page disagrees with itself a ⚠️ line says so; the reply is the bot's house style, split
under Telegram's limit and resent as plain text when its Markdown is refused; the menu and the
cheat-sheet name the page; the free-text routes are whole words ("this months performance" is this
month's, "consultations today" is still the inquiries), and another day, month or period is told
what the commands cover and what the page itself offers; the root staging copy of telegram_bot.py
is byte-identical (R24).

Every page is synthetic, laid out like the live consult_performance.php (30 Sep 2026); today is
28 Sep 2026 in Dhaka. Nothing reaches the network or Telegram.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_performance.py -q
"""
import asyncio
import filecmp
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from telegram.error import BadRequest

from test_foundation import (  # noqa: F401  (the portal fixture is used by name)
    TODAY, Message, Sent, fake_update, portal, report_of, run,
)
from src.bot import ask, performance, replies, telegram_bot
from src.config import settings
from src.scraper import client as client_module, parsers
from src.scraper.client import PortalUnavailable, admin_client

BOT_ROOT = Path(__file__).resolve().parent.parent
TODAY_KEY = "consult_performance.php?period=today"
MONTH_KEY = "consult_performance.php?period=month"
SCORE_TIP = "Balanced score = files opened × (0.5 + conversion) × program weight"
POINTS_TIP = "Weighted workload: Bachelor/Master/PhD ×1.5, KLP/EAP ×1"


# --------------------------------------------------------------------------- synthetic consult_performance.php

COLUMNS = ("rank", "name", "score", "conversion", "files_opened", "consultancies", "points", "docs_ready")
TH = {
    "rank": '<th class="c-rank">#</th>',
    "name": "<th>Consultant</th>",
    "score": f'<th title="{SCORE_TIP}">Score<i class="fas fa-circle-info"></i></th>',
    "conversion": "<th>Conversion</th>",
    "files_opened": "<th>Files Opened</th>",
    "consultancies": "<th>Consultancies</th>",
    "points": f'<th title="{POINTS_TIP}">Points<i class="fas fa-circle-info"></i></th>',
    "docs_ready": "<th>Docs Ready</th>",
}


def td(key, r):
    """One leaderboard cell as the live page lays it out."""
    if key == "rank":
        g = f" g{r['rank']}" if r["rank"] in ("1", "2", "3") else ""
        return f'<td class="c-rank"><span class="rank{g}">{r["rank"]}</span></td>'
    if key == "name":
        crown = ('<span class="pf-crown" title="Top performer"><i class="fas fa-trophy"></i> Top</span>'
                 if r.get("top") else "")
        return (f'<td class="c-who"><div class="pf-who"><span class="cav">{r["name"][:1]}</span>'
                f'<div class="pf-who-t"><strong class="pf-name">{r["name"]}</strong>\n {crown} </div></div></td>')
    if key == "score":
        return f'<td class="c-score"><span class="pf-score">{r["score"]}</span></td>'
    if key == "conversion":
        return (f'<td class="c-conv" data-l="Conversion"><div class="pf-conv"><span class="convbar">'
                f'<i style="width:{r["conversion"]}"></i></span><b>{r["conversion"]}</b></div></td>')
    if key == "files_opened":
        return f'<td class="c-mini" data-l="Files opened"><span class="pill green">{r["files_opened"]}</span></td>'
    if key == "consultancies":
        return f'<td class="c-mini" data-l="Consultancies"><span class="pill blue">{r["consultancies"]}</span></td>'
    if key == "points":
        return f'<td class="c-mini pf-dim" data-l="Points">{r["points"]}</td>'
    if key == "docs_ready":
        return f'<td class="c-mini pf-dim" data-l="Docs ready">{r["docs_ready"]}</td>'
    return f'<td class="c-mini">{r.get(key, "")}</td>'


def person(rank, name, score, conversion, files, consultancies, points, docs, top=False):
    return {"rank": str(rank), "name": name, "score": score, "conversion": conversion, "files_opened": files,
            "consultancies": consultancies, "points": points, "docs_ready": docs, "top": top}


# The owner's screenshots of 30 Sep 2026 (This Month).
MONTH_ROWS = (
    person(1, "SUMONA HALDER", "17.9", "18%", "26", "146", "148", "1", top=True),
    person(2, "NOSHIN SAMAD", "15.8", "16%", "16", "100", "149.5", "5"),
    person(3, "MAHIRA JANAN", "15.6", "19%", "22", "117", "120", "0"),
    person(4, "FAHMID KAISAR", "14.6", "11%", "16", "146", "218", "2"),
    person(5, "FIROZA ARA SHAMPA", "14.1", "18%", "20", "111", "115", "0"),
    person(6, "ARSHIA JANAN", "5", "6%", "6", "95", "141.5", "0"),
    person(7, "Owner", "1", "0%", "2", "0", "0", "0"),
)
MONTH_TILES = (("Consultancies done", "715"), ("Files opened", "108"), ("Conversion (file open)", "15%"),
               ("Docs ready", "8"))
MONTH_TOP = ("SUMONA HALDER", "17.9", "18%", "26", "146")

TODAY_ROWS = (
    person(1, "FAHMID KAISAR", "2.3", "100%", "1", "1", "1.5", "0", top=True),
    person(2, "SUMONA HALDER", "0", "0%", "0", "1", "1", "0"),
    person(3, "MAHIRA JANAN", "0", "0%", "0", "1", "1.5", "0"),
)
TODAY_TILES = (("Consultancies done", "3"), ("Files opened", "1"), ("Conversion (file open)", "33%"),
               ("Docs ready", "0"))
TODAY_TOP = ("FAHMID KAISAR", "2.3", "100%", "1", "1")

EMPTY_ROW = ('<tr class="pf-empty-row"><td colspan="8"><div class="pf-empty"><span class="ic">'
             '<i class="fas fa-user-clock"></i></span><b>No consultant activity yet</b>'
             '<span>Nothing was logged in this period.</span></div></td></tr>')


def perf_page(period="month", label="This Month", dates="01 Sep – 30 Sep 2026", tiles=MONTH_TILES,
              top=MONTH_TOP, rows=MONTH_ROWS, columns=COLUMNS, count=None, scope="", dates_class="",
              empty=EMPTY_ROW, extra_th=None):
    """consult_performance.php as the live page lays it out (sidebar, period tabs, the Custom range
    form, the "Showing" line, the scope note, the tiles, the top performer card, the leaderboard
    card with its count and sort note, and the legend). `columns` orders the header and the cells."""
    tabs = "".join(f'<a class="{"on" if p == period else ""}" href="?period={p}">{t}</a>'
                   for p, t in (("today", "Today"), ("week", "This Week"), ("month", "This Month"), ("all", "All Time")))
    head = "".join(extra_th.get(c, TH.get(c, "")) if extra_th else TH.get(c, "") for c in columns)
    body = "".join(('<tr style="background:#f0fdf4" class="is-top">' if r.get("top") else "<tr>")
                   + "".join(td(c, r) for c in columns) + "</tr>" for r in rows) or (empty or "")
    shown = len(rows) if count is None else count
    top_card = ""
    if top is not None:
        name, score, conv, files, cons = top
        top_card = (
            '<section class="pf-top" aria-label="Top performer"><div class="pf-top-who">'
            f'<div class="pf-top-av">{name[:1]}<span class="medal"><i class="fas fa-trophy"></i></span></div>'
            f'<div><div class="pf-top-k"><i class="fas fa-star"></i> Top performer · {label}</div>'
            f'<h2 class="pf-top-name">{name}</h2></div></div><div class="pf-top-m">'
            f"<div><b>{score}</b><span>Score</span></div><div><b>{conv}</b><span>Conversion</span></div>"
            f"<div><b>{files}</b><span>Files opened</span></div><div><b>{cons}</b><span>Consultancies</span></div>"
            "</div></section>")
    return (
        '<html><head><title>Consultant Performance — Hangeul Admin</title></head><body>'
        '<aside class="sidebar"><a href="consult_performance.php" class="sb-item sb-subitem active">'
        '<i class="fas fa-chart-line"></i> Performance</a><table class="decoy"><tr><th>Menu</th></tr>'
        '<tr><td>Leads</td></tr></table></aside>'
        '<div class="main-wrap"><main class="content">'
        f'<div class="pf-bar"><nav class="pf-tabs" aria-label="Period">{tabs}'
        '<label class="" for="pf-from"><i class="fas fa-calendar-days"></i> Custom range</label></nav>'
        '<form method="get" class="pf-range"><input type="hidden" name="period" value="custom">'
        '<div class="pf-f"><label for="pf-from">From</label><input type="date" id="pf-from" name="from" value="2026-09-01"></div>'
        '<div class="pf-f"><label for="pf-to">To</label><input type="date" id="pf-to" name="to" value="2026-09-30"></div>'
        '<button type="submit" class="pf-btn"><i class="fas fa-filter"></i> Apply range</button>'
        f'<p class="pf-showing"><i class="fas fa-calendar-day"></i> Showing <strong>{label}</strong>'
        f'<span class="pf-dates{(" " + dates_class) if dates_class else ""}">{dates}</span></p></form></div>'
        f'<p class="pf-scope">{scope}</p>'
        '<div class="pf-stats">' + "".join(
            f'<div class="pf-stat"><span class="ic inf"><i class="fas fa-headset"></i></span><div>'
            f'<div class="n">{n}</div><div class="l">{lbl}</div></div></div>' for lbl, n in tiles) + "</div>"
        + top_card +
        '<div class="card pf-card"><div class="card-head"><div class="card-title"><i class="fas fa-ranking-star"></i>'
        f' Leaderboard <span class="pf-count">{shown}</span></div><span class="pf-note">'
        '<i class="fas fa-arrow-down-wide-short"></i> Sorted by score, highest first</span></div>'
        f'<div class="tbl-wrap"><table class="tbl pf"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></div>'
        '<section class="pf-legend" aria-label="How the numbers are worked out"><dl class="pf-defs">'
        '<div class="d-files"><dt><i class="fas fa-folder-open"></i> Files opened</dt><dd>Payments you <b>verified</b> in this period.</dd></div>'
        f'<div class="d-score"><dt>Score</dt><dd>{SCORE_TIP}.</dd></div>'
        f'<div class="d-pts"><dt>Points</dt><dd>{POINTS_TIP}.</dd></div></dl></section>'
        "</main></div></body></html>")


def today_page(**kw):
    kw = {"period": "today", "label": "Today", "dates": "28 Sep – 28 Sep 2026", "tiles": TODAY_TILES,
          "top": TODAY_TOP, "rows": TODAY_ROWS, **kw}
    return perf_page(**kw)


def perf_portal(portal):
    portal.pages[TODAY_KEY] = today_page()
    portal.pages[MONTH_KEY] = perf_page()
    return portal


def blocks(text):
    """The leaderboard's blocks: {name: the block's lines}, in the reply's order."""
    part = text.split("🏅 *Leaderboard*")[1].split("\n\n")[0].splitlines()[1:]
    found, name = {}, None
    for line in part:
        if line.startswith("*") and ". " in line:
            name = line.split(". ", 1)[1].split("*")[0]
            found[name] = [line]
        elif name and line.startswith("   "):
            found[name].append(line.strip())
    return found


# --------------------------------------------------------------------------- the parser

def test_the_month_page_is_parsed_exactly_by_its_labels_and_headers():
    got = parsers.parse_consult_performance(perf_page())
    assert (got["period"], got["period_label"], got["range_text"]) == ("month", "This Month", "01 Sep – 30 Sep 2026")
    assert got["tiles"] == {"Consultancies done": "715", "Files opened": "108", "Conversion (file open)": "15%",
                            "Docs ready": "8"}
    assert list(got["tiles"]) == [label for label, _ in MONTH_TILES]            # the page's order
    top = got["top"]
    assert (top["name"], top["score"], top["conversion"], top["files_opened"], top["consultancies"]) == MONTH_TOP
    assert top["label"] == "Top performer · This Month"
    assert top["metrics"] == [("Score", "17.9"), ("Conversion", "18%"), ("Files opened", "26"), ("Consultancies", "146")]
    rows = got["leaderboard"]
    assert [r["name"] for r in rows] == [r["name"] for r in MONTH_ROWS]           # the portal's order
    for got_row, want in zip(rows, MONTH_ROWS):
        assert {k: got_row[k] for k in COLUMNS} == {k: want[k] for k in COLUMNS}
        assert got_row["top"] is want["top"] and got_row["extra"] == {}
    assert rows[1]["points"] == "149.5" and rows[0]["conversion"] == "18%"       # kept as printed
    assert got["count"] == 7 and got["empty_text"] == "" and got["scope_note"] == ""
    assert got["sort_note"] == "Sorted by score, highest first"
    assert (got["score_help"], got["points_help"]) == (SCORE_TIP, POINTS_TIP)
    assert got["columns"] == [("rank", "#"), ("name", "Consultant"), ("score", "Score"), ("conversion", "Conversion"),
                              ("files_opened", "Files Opened"), ("consultancies", "Consultancies"),
                              ("points", "Points"), ("docs_ready", "Docs Ready")]


def test_the_today_page_is_parsed_exactly():
    got = parsers.parse_consult_performance(today_page())
    assert (got["period"], got["period_label"], got["range_text"]) == ("today", "Today", "28 Sep – 28 Sep 2026")
    assert got["tiles"]["Consultancies done"] == "3" and got["tiles"]["Conversion (file open)"] == "33%"
    assert got["top"]["name"] == "FAHMID KAISAR" and got["top"]["score"] == "2.3" and got["top"]["conversion"] == "100%"
    assert [(r["rank"], r["name"], r["score"], r["points"]) for r in got["leaderboard"]] == [
        ("1", "FAHMID KAISAR", "2.3", "1.5"), ("2", "SUMONA HALDER", "0", "1"), ("3", "MAHIRA JANAN", "0", "1.5")]


def test_columns_are_found_by_their_header_text_in_any_order():
    shuffled = ("docs_ready", "name", "points", "rank", "consultancies", "score", "files_opened", "conversion")
    got = parsers.parse_consult_performance(perf_page(columns=shuffled))
    want = parsers.parse_consult_performance(perf_page())
    assert [{k: r[k] for k in COLUMNS} for r in got["leaderboard"]] == [{k: r[k] for k in COLUMNS} for r in want["leaderboard"]]
    assert [key for key, _ in got["columns"]] == list(shuffled)
    # The reply lists each consultant's columns in the header's order, with the header's own text.
    text = performance.format_consult_performance("month", got, TODAY)
    assert blocks(text)["NOSHIN SAMAD"][1:] == ["├ Docs Ready `5` · Points `149.5`",
                                                 "├ Consultancies `100` · Score `15.8`",
                                                 "└ Files Opened `16` · Conversion `16%`"]


def test_header_words_are_matched_by_meaning_and_an_unknown_column_is_kept():
    renamed = {"rank": '<th class="c-rank">Rank</th>', "name": "<th>Counsellor</th>",
               "files_opened": "<th>Files opened</th>", "docs_ready": "<th>Documents ready</th>",
               "branch": "<th>Branch</th>"}
    rows = [dict(r, branch="Dhaka") for r in MONTH_ROWS[:2]]
    html = perf_page(rows=rows, columns=COLUMNS + ("branch",), extra_th=renamed)
    got = parsers.parse_consult_performance(html)
    assert got["leaderboard"][0]["name"] == "SUMONA HALDER" and got["leaderboard"][0]["docs_ready"] == "1"
    assert got["leaderboard"][1]["extra"] == {"Branch": "Dhaka"} and got["columns"][-1] == (None, "Branch")
    text = performance.format_consult_performance("month", got, TODAY)
    assert blocks(text)["SUMONA HALDER"][1:] == ["├ Score `17.9` · Conversion `18%`",
                                                 "├ Files opened `26` · Consultancies `146`",
                                                 "├ Points `148` · Documents ready `1`",
                                                 "└ Branch `Dhaka`"]


def test_the_crown_and_the_avatar_initial_are_not_part_of_the_name():
    got = parsers.parse_consult_performance(perf_page())
    assert got["leaderboard"][0]["name"] == "SUMONA HALDER"                      # not "S SUMONA HALDER Top"


def test_a_cloudflare_protected_name_is_shown_as_the_browser_shows_it():
    protected = ('<a href="/cdn-cgi/l/email-protection" class="__cf_email__" '
                 'data-cfemail="42212d2c31372e36232c366c2d2c2702273a232f322e276c212d2f">[email&#160;protected]</a>')
    rows = [dict(MONTH_ROWS[0], name=protected)] + list(MONTH_ROWS[1:])
    got = parsers.parse_consult_performance(perf_page(rows=rows))
    assert got["leaderboard"][0]["name"] == parsers._cf_email("42212d2c31372e36232c366c2d2c2702273a232f322e276c212d2f")
    assert "[email" not in got["leaderboard"][0]["name"]


def test_a_hidden_range_placeholder_is_no_range():
    # All Time hides a placeholder span ("01 Jan – 31 Dec 2999"): never shown as the period's dates.
    got = parsers.parse_consult_performance(perf_page(period="all", label="All Time", dates="01 Jan – 31 Dec 2999",
                                                      dates_class="is-hidden"))
    assert got["range_text"] == "" and got["period"] == "all"


def test_the_empty_state_is_an_empty_leaderboard_not_an_error():
    zero = (("Consultancies done", "0"), ("Files opened", "0"), ("Conversion (file open)", "0%"), ("Docs ready", "0"))
    got = parsers.parse_consult_performance(today_page(tiles=zero, top=None, rows=()))
    assert got["leaderboard"] == [] and got["top"] is None and got["count"] == 0
    assert got["empty_text"] == "No consultant activity yet Nothing was logged in this period."
    text = performance.format_consult_performance("today", got, TODAY)
    assert "🏆 *Top performer:* none shown on the page for this period." in text
    assert "🏅 *Leaderboard* (0 consultants)\n• Nobody is listed for this period (the page says: " in text
    assert "🎧 *Consultancies done:* `0`" in text                                # a page read whole: a real 0
    assert "⚠️" not in text


def test_a_top_card_with_no_name_is_no_top_performer():
    got = parsers.parse_consult_performance(today_page(top=("—", "0", "0%", "0", "0"), rows=()))
    assert got["top"] is None


@pytest.mark.parametrize("html, why", [
    (perf_page(tiles=()), "its tiles"),
    (perf_page().replace("<th>Consultant</th>", "<th>Member</th>"), "leaderboard table"),
    (perf_page().replace('<table class="tbl pf">', '<div class="tbl pf">').replace("</table>", "</div>"),
     "leaderboard table"),
    (perf_page(columns=tuple(c for c in COLUMNS if c != "points")), "no points column"),
    (perf_page().replace('<td class="c-mini pf-dim" data-l="Docs ready">5</td>', "", 1), "row 2 has 7 cells"),
    (perf_page().replace('<span class="pf-score">15.8</span>', '<span class="pf-score">high</span>', 1),
     "score reads 'high'"),
    (perf_page().replace('<div class="n">715</div>', '<div class="n">lots</div>'), "tile reads 'lots'"),
    (perf_page(count=8), "counts 8 consultants but 7 rows"),
    (perf_page().replace("<span>Score</span>", "<span>Rating</span>"), "top performer card shows no score"),
    (perf_page().replace('<strong class="pf-name">NOSHIN SAMAD</strong>', '<strong class="pf-name"></strong>'),
     "row 2 shows no consultant"),
], ids=["no-tiles", "no-consultant-header", "no-table", "no-points-column", "short-row", "score-not-a-figure",
        "tile-not-a-figure", "count-badge-mismatch", "top-card-without-score", "row-without-name"])
def test_a_layout_the_parser_does_not_know_raises(html, why):
    with pytest.raises(parsers.PerformanceLayoutError) as e:
        parsers.parse_consult_performance(html)
    assert why in str(e.value)


# --------------------------------------------------------------------------- the reader

def test_one_get_of_the_period_link_and_nothing_else(portal):
    perf_portal(portal)
    got = asyncio.run(admin_client.read_consult_performance("month"))
    assert got["tiles"]["Consultancies done"] == "715"
    got = asyncio.run(admin_client.read_consult_performance("today"))
    assert got["top"]["name"] == "FAHMID KAISAR"
    assert portal.asked == [("GET", MONTH_KEY), ("GET", TODAY_KEY)]           # never the form, no other page
    with pytest.raises(ValueError):
        asyncio.run(admin_client.read_consult_performance("custom"))
    assert len(portal.asked) == 2


def test_a_page_that_shows_another_period_is_refused(portal):
    # The page shows This Month for a period it does not take: never labelled "today".
    portal.pages[TODAY_KEY] = perf_page()
    with pytest.raises(PortalUnavailable) as e:
        asyncio.run(admin_client.read_consult_performance("today"))
    assert "shows 'This Month' instead of 'Today'" in e.value.reason
    portal.pages[TODAY_KEY] = today_page(period="month")                        # the open tab disagrees
    with pytest.raises(PortalUnavailable):
        asyncio.run(admin_client.read_consult_performance("today"))


def test_an_unknown_layout_is_portal_unavailable_with_its_reason(portal):
    portal.pages[MONTH_KEY] = perf_page(tiles=())
    with pytest.raises(PortalUnavailable) as e:
        asyncio.run(admin_client.read_consult_performance("month"))
    assert e.value.reason.startswith("consult_performance.php: its tiles") and "layout not recognised" in e.value.reason


# --------------------------------------------------------------------------- the reply

def test_this_month_reply_shows_only_the_pages_data_in_house_style(portal):
    perf_portal(portal)
    chat, _ = run(telegram_bot.performance_month_command, "/performance_month", [])
    assert len(chat) == 1 and chat[0].edits == 1 and chat[0].parse_mode == "Markdown"   # the "⏳" note became it
    text = report_of(chat)
    lines = text.splitlines()
    assert lines[:3] == ["📈 *Consultant Performance — This Month*", "📅 Showing *This Month* · 01 Sep – 30 Sep 2026",
                         performance.RULE]
    assert lines[3:7] == ["🎧 *Consultancies done:* `715`", "📂 *Files opened:* `108`",
                          "🎯 *Conversion (file open):* `15%`", "📋 *Docs ready:* `8`"]
    assert ("🏆 *Top performer · This Month:* SUMONA HALDER\n"
            "   Score `17.9` · Conversion `18%` · Files opened `26` · Consultancies `146`") in text
    people = blocks(text)
    assert list(people) == [r["name"] for r in MONTH_ROWS]
    assert people["SUMONA HALDER"] == ["*1. SUMONA HALDER* 🏆 Top", "├ Score `17.9` · Conversion `18%`",
                                       "├ Files Opened `26` · Consultancies `146`", "└ Points `148` · Docs Ready `1`"]
    assert people["NOSHIN SAMAD"][-1] == "└ Points `149.5` · Docs Ready `5`"
    assert people["Owner"][0] == "*7. Owner*"
    assert "🏅 *Leaderboard* (7 consultants)" in text
    assert f"ℹ️ *Score:* {SCORE_TIP}" in text and f"ℹ️ *Points:* {POINTS_TIP}" in text
    assert lines[-1] == ("🔗 Read live just now, read-only, from the portal's Consultant Performance page "
                         "(consult\\_performance.php?period=month). Sorted by score, highest first.")
    assert "⚠️" not in text                                                     # the page agrees with itself
    # Nothing of the old self-counted report.
    for gone in ("Consultation Requests", "Payments Verified", "By Person", "Received", "৳", "Last updated by"):
        assert gone not in text
    assert portal.asked == [("GET", MONTH_KEY)]


def test_today_reply(portal):
    perf_portal(portal)
    chat, _ = run(telegram_bot.performance_today_command, "/performance_today", [])
    text = report_of(chat)
    assert text.startswith("📈 *Consultant Performance — Today*\n📅 Showing *Today* · 28 Sep – 28 Sep 2026\n")
    assert "🎧 *Consultancies done:* `3`" in text and "🎯 *Conversion (file open):* `33%`" in text
    assert "🏆 *Top performer · Today:* FAHMID KAISAR" in text
    assert list(blocks(text)) == ["FAHMID KAISAR", "SUMONA HALDER", "MAHIRA JANAN"]
    assert "(consult\\_performance.php?period=today)" in text and "⚠️" not in text
    assert portal.asked == [("GET", TODAY_KEY)]


def test_the_waiting_message_names_the_page(portal):
    perf_portal(portal)
    seen = []

    class Watch(Message):
        async def reply_text(self, text, parse_mode=None, **kwargs):
            seen.append(text)
            return await super().reply_text(text, parse_mode=parse_mode, **kwargs)
    update, context, chat = fake_update("/performance_month", [])
    update.message = Watch(chat)
    asyncio.run(telegram_bot.performance_month_command(update, context))
    assert seen[0] == "⏳ _Reading the portal's Consultant Performance page (This Month) live..._"


def test_where_the_page_disagrees_with_itself_it_is_said_never_corrected(portal):
    rows = list(MONTH_ROWS)
    rows[0] = dict(rows[0], score="17.8")                                       # the card says 17.9
    tiles = (("Consultancies done", "720"),) + MONTH_TILES[1:]                   # the rows add up to 715
    portal.pages[MONTH_KEY] = perf_page(rows=rows, tiles=tiles)
    text = report_of(run(telegram_bot.performance_month_command, "/performance_month", [])[0])
    assert "⚠️ The top performer card and the leaderboard's top row differ on: score." in text
    assert "⚠️ The leaderboard's Consultancies add up to 715, the Consultancies done tile says 720." in text
    assert "🎧 *Consultancies done:* `720`" in text and "├ Score `17.8`" in text  # both shown as the portal has them


@pytest.mark.parametrize("kw, said", [
    ({"top": ("NOSHIN SAMAD",) + MONTH_TOP[1:]},
     "⚠️ The top performer card names NOSHIN SAMAD, the leaderboard crowns SUMONA HALDER."),
    ({"top": None}, "⚠️ The page shows no top performer card, though its leaderboard lists 7 consultants."),
    ({"rows": (), "tiles": (("Consultancies done", "0"),)},
     "⚠️ The page shows a top performer card but no one on its leaderboard."),
])
def test_the_top_card_and_the_leaderboard_are_checked_against_each_other(kw, said):
    text = performance.format_consult_performance("month", parsers.parse_consult_performance(perf_page(**kw)), TODAY)
    assert said in text


def test_a_range_that_is_not_today_is_said(portal):
    portal.pages[TODAY_KEY] = today_page(dates="27 Sep – 27 Sep 2026")
    text = report_of(run(telegram_bot.performance_today_command, "/performance_today", [])[0])
    assert ("⚠️ The page's range is 27 Sep – 27 Sep 2026, but today in Dhaka is 28 Sep 2026: the figures are "
            "the portal's, for the range it shows.") in text
    # This month may end today or on the month's last day, as the page shows it.
    for dates in ("01 Sep – 28 Sep 2026", "01 Sep – 30 Sep 2026"):
        page = parsers.parse_consult_performance(perf_page(dates=dates))
        assert "⚠️" not in performance.format_consult_performance("month", page, TODAY)
    page = parsers.parse_consult_performance(perf_page(dates="01 Aug – 31 Aug 2026"))
    assert "⚠️ The page's range is 01 Aug – 31 Aug 2026" in performance.format_consult_performance("month", page, TODAY)


def test_a_scope_note_is_shown():
    page = parsers.parse_consult_performance(perf_page(scope="Showing only your own figures"))
    text = performance.format_consult_performance("month", page, TODAY)
    assert "ℹ️ The page notes: Showing only your own figures" in text.splitlines()[2]


@pytest.mark.parametrize("failure, reason", [
    ("down", "consult_performance.php: could not connect to the portal (ConnectError)"),
    ("timeout", "consult_performance.php: the portal did not answer in time (ReadTimeout)"),
    ("missing", "consult_performance.php: the portal answered HTTP 404"),
    ("login", "couldn't log in to the portal: the portal refused the login (wrong username or password?)"),
    ("layout", "consult_performance.php: its leaderboard table (a header with Consultant and Score) was not found "
               "(layout not recognised)"),
    ("period", "consult_performance.php?period=month shows 'Today' instead of 'This Month' (layout not recognised)"),
])
def test_a_page_that_cannot_be_read_says_so_never_zero(portal, monkeypatch, failure, reason):
    if failure in ("down", "timeout"):
        def fail(request):
            if failure == "down":
                raise httpx.ConnectError("refused", request=request)
            raise httpx.ReadTimeout("", request=request)
        monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(fail)))
    elif failure == "login":
        async def refused(*args, **kwargs):
            return {"success": False, "error": "the portal refused the login (wrong username or password?)"}
        monkeypatch.setattr(admin_client, "is_authenticated", False)
        monkeypatch.setattr(admin_client, "login", refused)
    elif failure == "layout":
        portal.pages[MONTH_KEY] = "<html><body><p>Maintenance</p><div class='pf-stat'><div class='n'>0</div>" \
                                  "<div class='l'>Consultancies done</div></div></body></html>"
    elif failure == "period":
        portal.pages[MONTH_KEY] = today_page()
    chat, _ = run(telegram_bot.performance_month_command, "/performance_month", [])
    text = report_of(chat)
    assert text == (f"❌ Couldn't read the portal: {replies.escape_markdown(reason, version=1)}.\n"
                    "The portal's Consultant Performance page (This Month): not available right now. "
                    "Please try again in a minute.")
    assert "`0`" not in text and "Leaderboard" not in text


def test_mock_mode_is_no_live_page(portal, monkeypatch):
    monkeypatch.setattr(admin_client, "mock_mode", True)
    text = report_of(run(telegram_bot.performance_today_command, "/performance_today", [])[0])
    assert text.startswith("❌ Couldn't read the portal: the bot is in mock mode") and portal.asked == []


# --------------------------------------------------------------------------- Telegram

class PickySent(Sent):
    async def edit_text(self, text, parse_mode=None, **kwargs):
        if parse_mode == "Markdown":
            raise BadRequest("Can't parse entities: can't find end of the entity starting at byte offset 7")
        return await super().edit_text(text, parse_mode=parse_mode, **kwargs)


class PickyMessage(Message):
    """Takes the "⏳" note, but refuses the reply's Markdown (as Telegram does for a bad entity)."""

    async def reply_text(self, text, parse_mode=None, **kwargs):
        if parse_mode == "Markdown" and not text.startswith("⏳"):
            raise BadRequest("Can't parse entities: can't find end of the entity starting at byte offset 7")
        return PickySent(self.chat, text, parse_mode)


def test_a_reply_whose_markdown_is_refused_is_resent_as_plain_text(portal):
    perf_portal(portal)
    update, context, chat = fake_update("/performance_today", [])
    update.message = PickyMessage(chat)
    asyncio.run(telegram_bot.performance_today_command(update, context))
    assert len(chat) == 1 and chat[0].parse_mode is None and chat[0].edits == 1
    assert chat[0].text.startswith("📈 Consultant Performance — Today\n📅 Showing Today · 28 Sep – 28 Sep 2026")
    assert "Consultancies done: 3" in chat[0].text and "*" not in chat[0].text and "`" not in chat[0].text
    assert "consult_performance.php?period=today" in chat[0].text


def test_a_long_leaderboard_is_split_under_telegrams_limit(portal):
    staff = [f"COUNSELLOR NUMBER {i:03d} WITH A LONG NAME" for i in range(1, 121)]
    rows = [person(i, name, "1", "10%", "1", "10", "10", "0", top=i == 1) for i, name in enumerate(staff, 1)]
    tiles = (("Consultancies done", "1200"), ("Files opened", "120"), ("Conversion (file open)", "10%"),
             ("Docs ready", "0"))
    portal.pages[MONTH_KEY] = perf_page(rows=rows, tiles=tiles, top=(staff[0], "1", "10%", "1", "10"))
    chat, _ = run(telegram_bot.performance_month_command, "/performance_month", [])
    assert len(chat) > 1 and all(replies.telegram_len(m.text) <= replies.CHUNK_CHARS for m in chat)
    assert chat[0].edits == 1 and all(m.parse_mode == "Markdown" for m in chat)
    text = report_of(chat)
    assert all(f"*{n}. {name}*" in text for n, name in enumerate(staff, 1))
    for piece in chat.shown():
        ok, error, rendered, _ = parse_legacy_markdown(piece)
        assert ok, error
    assert "⚠️" not in text                                                     # 120 × 10 = 1200, 120 × 1 = 120


def test_every_reply_is_valid_legacy_markdown(portal):
    perf_portal(portal)
    for command in (telegram_bot.performance_today_command, telegram_bot.performance_month_command):
        for piece in run(command, "/x", [])[0].shown():
            ok, error, rendered, _ = parse_legacy_markdown(piece)
            assert ok, error
            assert replies.telegram_len(rendered) <= replies.TELEGRAM_LIMIT
    # Portal words with Markdown characters in them stay text.
    odd = [dict(MONTH_ROWS[0], name="LINA_PARVIN *STAR*")] + list(MONTH_ROWS[1:])
    page = parsers.parse_consult_performance(perf_page(rows=odd, top=("LINA_PARVIN *STAR*",) + MONTH_TOP[1:],
                                                       scope="only_yours [beta]"))
    text = performance.format_consult_performance("month", page, TODAY)
    ok, error, rendered, _ = parse_legacy_markdown(text)
    assert ok, error
    assert "LINA_PARVIN ∗STAR∗" in rendered and "only_yours [beta]" in rendered
    for fixed in (telegram_bot.get_commands_cheatsheet_text(), performance.waiting_text("month"),
                  performance.waiting_text("today"),
                  ask.performance_other_reply(ask.performance_route("performance yesterday", TODAY)),
                  ask.performance_other_reply(ask.performance_route("all time performance", TODAY)), ask.CANT_ANSWER):
        assert parse_legacy_markdown(fixed)[0], fixed


def test_an_unknown_sender_is_refused_with_their_chat_id(portal):
    perf_portal(portal)
    for command in (telegram_bot.performance_today_command, telegram_bot.performance_month_command,
                    telegram_bot.performance_command):
        update, context, chat = fake_update("/performance_today", [])
        update.effective_chat = SimpleNamespace(id=999)
        asyncio.run(command(update, context))
        assert chat.shown() == ["⛔ Unauthorized access. Your Chat ID is: `999`"]
    assert portal.asked == []


# --------------------------------------------------------------------------- menu, aliases, cheat-sheet

def test_the_menu_the_handlers_and_the_cheat_sheet_name_the_page(monkeypatch):
    menus = []

    class App:
        bot = SimpleNamespace()

        def create_task(self, coroutine, update=None, name=None):
            coroutine.close()

    async def set_my_commands(commands, **kwargs):
        menus.append(commands)

    async def ok(*args, **kwargs):
        return SimpleNamespace(message_id=1)
    app = App()
    app.bot.set_my_commands, app.bot.send_message, app.bot.pin_chat_message = set_my_commands, ok, ok
    asyncio.run(telegram_bot.post_init(app))
    menu = {c.command: c.description for c in menus[0]}
    assert len(menu) == 13 and list(menu)[-2:] == ["performance_today", "performance_month"]
    assert menu["performance_today"] == ("Today: the portal's Consultant Performance page: tiles, top performer, "
                                         "leaderboard")
    assert menu["performance_month"] == ("This month: the portal's Consultant Performance page: tiles, top "
                                         "performer, leaderboard")
    assert all(3 <= len(d) <= 256 for d in menu.values())

    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:TEST-TOKEN-NOT-REAL")
    monkeypatch.setattr(settings, "ENABLE_SCHEDULED_REPORTS", False)    # no scheduler in tests
    built = telegram_bot.build_telegram_application()
    by_name = {name: h.callback for group in built.handlers.values() for h in group
               for name in getattr(h, "commands", ())}
    assert by_name["performance_today"] is by_name["perf_today"] is telegram_bot.performance_today_command
    assert by_name["performance_month"] is by_name["perf_month"] is telegram_bot.performance_month_command
    assert by_name["performance"] is telegram_bot.performance_command

    sheet = telegram_bot.get_commands_cheatsheet_text()
    assert ("1️⃣1️⃣ `/performance_today`\n└ *Today: the portal's Consultant Performance page — tiles, top performer, "
            "leaderboard*") in sheet
    assert ("1️⃣2️⃣ `/performance_month`\n└ *This month: the portal's Consultant Performance page — tiles, top "
            "performer, leaderboard*") in sheet
    assert "consultations & payments verified" not in sheet and "per person" not in sheet
    assert ("• The portal's Consultant Performance page (tiles, top performer, leaderboard): /performance\\_today · "
            "/performance\\_month") in ask.CANT_ANSWER


def test_the_welcome_names_the_page(portal, monkeypatch):
    async def no_brain():
        return {"reachable": False}
    monkeypatch.setattr(telegram_bot.ollama_client, "check_health", no_brain)
    text = report_of(run(telegram_bot.start_command, "/start", [])[0])
    assert "`/performance_today` — Today on the portal's Consultant Performance page: tiles, top performer, leaderboard" in text
    assert "`/performance_month` — This month on the portal's Consultant Performance page: tiles, top performer, leaderboard" in text


@pytest.mark.parametrize("args, expect", [
    ([], "📈 *Consultant Performance — Today*"),
    (["today"], "📈 *Consultant Performance — Today*"),
    (["month"], "📈 *Consultant Performance — This Month*"),
    (["this", "month"], "📈 *Consultant Performance — This Month*"),
    (["last", "week"], "📈 /performance\\_today and /performance\\_month show the portal's Consultant Performance page"),
    (["all", "time"], ", and you asked about all time."),
    (["31", "Sep"], "I couldn't read the date there: 31 sep: September has 30 days"),
])
def test_the_performance_alias_reads_its_words(portal, args, expect):
    perf_portal(portal)
    text = report_of(run(telegram_bot.performance_command, "/performance " + " ".join(args), args)[0])
    assert expect in text
    if "Consultant Performance —" not in expect:
        assert portal.asked == []                                       # nothing read for a period it cannot give


# --------------------------------------------------------------------------- free text

@pytest.mark.parametrize("text, topic", [
    ("performance today", "today"), ("today's performance", "today"), ("todays performance", "today"),
    ("How did the team do today?", "today"), ("team performance", "today"), ("how is the team doing", "today"),
    ("staff activity today", "today"), ("consultant performance", "today"), ("leaderboard", "today"),
    ("who is the top performer today", "today"),
    ("this month's performance", "month"), ("monthly performance", "month"), ("performance this month", "month"),
    ("how did the team do this month", "month"), ("performance for September", "month"),
    ("team's performance month to date", "month"), ("performance so far this month", "month"),
    ("who is the top performer this month", "month"), ("this month's leaderboard", "month"),
    # Written without the apostrophe, as the owner writes ("todays", "inquires").
    ("this months performance", "month"), ("current months performance", "month"),
    ("performance this months", "month"), ("this months team performance", "month"),
    ("this months performance for all", "month"),
    ("performance for the month of September", "month"), ("performance for September 2026", "month"),
    ("performance from 1 Sep to 30 Sep", "month"), ("may I see this month's performance", "month"),
    ("how are the consultants doing today", "today"), ("consultant performance today", "today"),
    ("team stats", "today"), ("staff report", "today"), ("team summary today", "today"),
])
def test_performance_questions_route_to_the_page(text, topic):
    route = ask.classify(text, TODAY)
    assert (route.kind, route.topic) == ("performance", topic), text


@pytest.mark.parametrize("text, first, last, words", [
    ("performance for the month of august", date(2026, 8, 1), date(2026, 8, 31), ""),
    ("performance of the month of september 2025", date(2025, 9, 1), date(2025, 9, 30), ""),
    ("month performance 2025", None, None, "2025"),
    ("performance this month 2025", None, None, "2025"),
    ("performance this month last year", None, None, "last year"),
    ("performance for the month of may", date(2026, 5, 1), date(2026, 5, 31), ""),
    ("this month's performance for October", date(2025, 10, 1), date(2025, 10, 31), ""),
    ("performance from 1 Sep to 15 Oct", date(2026, 9, 1), date(2026, 10, 15), ""),
])
def test_another_month_or_year_named_with_this_month_is_never_this_months_page(text, first, last, words):
    route = ask.classify(text, TODAY)
    assert route.kind == "performance" and route.topic == "", text
    if first:
        assert (route.window.first, route.window.last) == (first, last), text
    else:
        assert route.window is None and route.words == words, text


@pytest.mark.parametrize("text, words", [
    ("all time performance", "all time"), ("overall performance", "overall"), ("weekly performance", "weekly"),
    ("yearly performance", "yearly"), ("performance custom range", "custom range"),
    ("all-time leaderboard", "all-time"), ("best performer ever", "ever"),
])
def test_the_pages_other_periods_are_never_todays(text, words):
    route = ask.classify(text, TODAY)
    assert (route.kind, route.topic, route.words) == ("performance", "", words), text


def test_on_the_first_of_a_month_this_month_is_the_month_and_another_month_is_not():
    first = date(2026, 10, 1)
    assert ask.classify("this months performance", first).topic == "month"
    assert ask.classify("performance this month", first).topic == "month"
    assert ask.classify("performance today", first).topic == "today"
    route = ask.classify("performance for the month of august", first)
    assert route.topic == "" and (route.window.first, route.window.last) == (date(2026, 8, 1), date(2026, 8, 31))
    assert ask.classify("performance for September", first).topic == ""        # last month by then
    assert ask.classify("performance this month 2025", first).topic == ""


def test_a_past_facing_range_stays_in_the_order_it_was_written():
    window, problem = ask.date_window("from 1 Sep to 30 Sep", TODAY, forward=False)
    assert problem is None and (window.first, window.last) == (date(2026, 9, 1), date(2026, 9, 30))
    window, _ = ask.date_window("from 25 Sep to 5 Oct", TODAY, forward=False)
    assert (window.first, window.last) == (date(2026, 9, 25), date(2026, 10, 5))
    window, _ = ask.date_window("from 20 Dec to 5 Jan", TODAY, forward=False)   # both gone: unchanged
    assert (window.first, window.last) == (date(2025, 12, 20), date(2026, 1, 5))
    reply = ask.performance_other_reply(ask.classify("performance from 1 Sep to 15 Oct", TODAY))
    assert "you asked about 01 Sep to 15 Oct 2026" in reply


@pytest.mark.parametrize("text, what", [
    ("performance yesterday", "day"), ("last month's performance", "window"), ("performance last week", "window"),
    ("how did the team do on 12 Sep", "day"), ("performance over the past 3 months", "words"),
    ("performance on 31 Sep", "problem"), ("performance over the last 2 weeks", "window"),
])
def test_performance_questions_about_other_days_get_no_stand_in_period(text, what):
    route = ask.classify(text, TODAY)
    assert route.kind == "performance" and route.topic == "", text
    assert getattr(route, what), text


def test_this_week_is_the_pages_this_week_never_today_even_on_a_monday():
    # 28 Sep 2026 is a Monday: "this week" so far is that one day, still not Today's page.
    route = ask.classify("performance this week", TODAY)
    assert (route.kind, route.topic, route.window, route.words) == ("performance", "", None, "this week")
    route = ask.classify("this week's leaderboard", date(2026, 9, 30))
    assert route.topic == "" and (route.window.first, route.window.last) == (date(2026, 9, 28), date(2026, 9, 30))
    assert ask.classify("weekly performance", TODAY).words == "weekly"
    reply = ask.performance_other_reply(ask.classify("performance this week", TODAY))
    assert ", and you asked about this week." in reply and "This Week, All Time and a custom range" in reply


@pytest.mark.parametrize("text, kind", [
    ("consultations today", "inquiries"), ("how many consultations were done today", "inquiries"),
    ("consultancies done today", "inquiries"), ("consultations this month", "inquiries"),
    ("consultations handled by Arshia Janan", "inquiries"), ("Total verified students today", "verified"),
    ("summary for today", "report"), ("show pending payments", "pending"), ("any deadlines this week", "calendar"),
    ("applications under review", "window_review"), ("students across all programs", "dashboard"),
    ("the team's deadlines this month", "calendar"), ("performing arts", "unknown"), ("pin the menu", "pin"),
    ("how is the team doing with pending payments", "pending"),
    ("how did the team do on pending payments this week", "pending"),
    ("academic performance of the March 2027 intake", "intake"),
    ("how is the team doing with the deadlines this week", "calendar"),
    ("how did the team do on window applications under review", "window_review"),
    ("team performance on passport cross-checks today", "crosscheck"),
    ("how is the team doing with missing documents", "missing"),
    ("how did the counsellors do yesterday", "inquiries"),
    ("how did the team do on verifications yesterday", "verified"),
    ("top universities", "dashboard"),
])
def test_other_questions_keep_their_own_routes(text, kind):
    assert ask.classify(text, TODAY).kind == kind, text


def test_the_counsellors_yesterday_is_that_days_consultations():
    route = ask.classify("how did the counsellors do yesterday", TODAY)
    assert (route.kind, route.day) == ("inquiries", date(2026, 9, 27))
    assert ask.classify("how did the counsellors do today", TODAY).topic == "today"
    assert ask.classify("how did the counsellors do this month", TODAY).topic == "month"
    assert ask.classify("how did the counsellors do last week", TODAY).kind == "performance"


@pytest.fixture
def recorded(monkeypatch):
    ran = []

    def recorder(name):
        async def command(update, context):
            ran.append(name)
            await update.message.reply_text(f"{name} answered")
        return command
    for name in ("performance_today_command", "performance_month_command", "inquiries_today_command",
                 "verified_today_command", "report_command"):
        monkeypatch.setattr(telegram_bot, name, recorder(name))
    return ran


@pytest.mark.parametrize("said, command", [
    ("performance today", "performance_today_command"), ("today's performance", "performance_today_command"),
    ("how did the team do today", "performance_today_command"),
    ("this month's performance", "performance_month_command"), ("monthly performance", "performance_month_command"),
    ("performance this month", "performance_month_command"),
    ("this months performance", "performance_month_command"),
    ("current months performance", "performance_month_command"),
    ("who is the top performer this month", "performance_month_command"),
    ("consultations today", "inquiries_today_command"), ("verified students today", "verified_today_command"),
])
def test_free_text_reaches_the_right_command(portal, recorded, said, command):
    run(telegram_bot.handle_natural_language_message, said, None)
    assert recorded == [command]


def test_free_text_performance_reads_the_page_live(portal):
    perf_portal(portal)
    text = report_of(run(telegram_bot.handle_natural_language_message, "this months performance", None)[0])
    assert text.startswith("📈 *Consultant Performance — This Month*") and portal.asked == [("GET", MONTH_KEY)]


def test_free_text_about_another_day_is_told_what_can_be_read(portal, recorded):
    chat, _ = run(telegram_bot.handle_natural_language_message, "how did the team do yesterday", None)
    assert recorded == [] and portal.asked == []
    assert chat.shown() == [
        "📈 /performance\\_today and /performance\\_month show the portal's Consultant Performance page for "
        "*today* and for *this month*, and you asked about Sun 27 Sep 2026.\n"
        "The page itself (Leads › Performance, consult\\_performance.php) also offers This Week, All Time and a "
        "custom range: open it on the portal for those."]


@pytest.mark.parametrize("said, asked", [
    ("performance for the month of august", "you asked about August 2026 (Sat 01 Aug – Mon 31 Aug 2026)"),
    ("month performance 2025", "you asked about 2025."),
    ("this months performance last year", "you asked about last year."),
    ("all time performance", "you asked about all time."),
    ("weekly performance", "you asked about weekly."),
])
def test_free_text_about_another_period_is_never_answered_with_this_months_page(portal, recorded, said, asked):
    chat, _ = run(telegram_bot.handle_natural_language_message, said, None)
    assert recorded == [] and portal.asked == []
    assert len(chat.shown()) == 1 and asked in chat.shown()[0], chat.shown()
    assert "This Week, All Time and a custom range" in chat.shown()[0]


# --------------------------------------------------------------------------- what was removed stays removed

def test_the_self_counted_report_and_its_readers_are_gone():
    for name in ("tally", "Person", "Tally", "Reads", "read_performance", "window"):
        assert not hasattr(performance, name), name
    for name in ("read_consultation_range", "read_verified_window", "ensure_session"):
        assert not hasattr(client_module.HangeulAdminClient, name), name
    assert not hasattr(parsers, "verified_between") and not hasattr(client_module, "CONSULT_RANGE_MAX_READS")


# --------------------------------------------------------------------------- the staging copy (R24)

def test_the_root_staging_copies_are_byte_identical():
    for root, src in (("telegram_bot.py", "src/bot/telegram_bot.py"), ("config.py", "src/config.py"),
                      ("progress_builder.py", "src/sheets/progress_builder.py")):
        assert filecmp.cmp(BOT_ROOT / root, BOT_ROOT / src, shallow=False), root


# --------------------------------------------------------------------------- Telegram's legacy Markdown

def parse_legacy_markdown(text: str):
    """Telegram's parse_mode="Markdown" (v1), as tdlib parses it (a copy of the command audit's
    tg_markdown.py re-implementation): -> (ok, error or None, rendered text, entities)."""
    out, ents = [], []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and text[i + 1] in "_*`[":
            out.append(text[i + 1])
            i += 2
            continue
        if c not in "_*`[":
            out.append(c)
            i += 1
            continue
        begin = i
        end_ch = "]" if c == "[" else c
        is_pre = False
        i += 1
        if c == "`" and text[i:i + 2] == "``":
            is_pre = True
            i += 2
            j = i
            while j < n and text[j] not in " \n`":
                j += 1
            if j < n and text[j] == "\n":
                i = j + 1
            end_ch = "`"
        start_len = len("".join(out))
        while i < n and (text[i] != end_ch or (is_pre and text[i + 1:i + 3] != "``")):
            out.append(text[i])
            i += 1
        if i >= n:
            return False, f"Can't find end of the entity starting at offset {begin}", None, ents
        cur_len = len("".join(out))
        if cur_len != start_len:
            kind = {"_": "italic", "*": "bold", "`": "pre" if is_pre else "code", "[": "text_link"}[c]
            if c == "[" and i + 1 < n and text[i + 1] == "(":
                i += 2
                url_begin = i
                while i < n and text[i] != ")":
                    i += 1
                if i >= n:
                    return False, f"Can't find end of a URL at offset {url_begin}", None, ents
            ents.append((kind, start_len, cur_len - start_len))
        if is_pre:
            i += 2
        i += 1
    return True, None, "".join(out), ents
