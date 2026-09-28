"""The last cases the independent re-verification found partly wrong, and the brain on demand."""
import asyncio
from datetime import date
from types import SimpleNamespace

from src.bot import ask
from src.bot import telegram_bot as tb
from src.bot.brief import section_verified
from src.config import settings
from src.llm import ollama_client as oc
from src.sheets import auto_sync


def test_a_mistyped_date_answer_keeps_the_question_open():
    for typo in ("tomorow", "yesteday", "foo"):
        ctx = SimpleNamespace(user_data={tb.DATE_PROMPT_KEY: "verified"})
        tb._ask_date_again(ctx, "verified", typo)
        assert ctx.user_data.get("awaiting_date_for") == "verified", typo
    # A whole new question is not read as the date.
    ctx = SimpleNamespace(user_data={tb.DATE_PROMPT_KEY: "verified"})
    tb._ask_date_again(ctx, "verified", "what is the total number of students")
    assert "awaiting_date_for" not in ctx.user_data


def test_an_unreadable_scan_is_not_counted_as_checked_by_ocr():
    cards = [{"status": "SCAN_UNREADABLE"}, {"status": "MATCH"}]
    assert tb._ocr_checked(cards) == 1


def test_a_sibling_with_the_same_mobile_is_not_an_edit():
    old = {"Full Name": "RAHMAN MST SHIULY", "Mobile": "01711223344", "DOB": "01/02/2001"}
    new = {"Full Name": "RAHMAN MD ALAM", "Mobile": "01711223344", "DOB": "05/06/2003"}
    assert auto_sync._likely_same(old, new) == 0.0
    # A common surname alone is no longer "a telling word" either.
    new_no_dob = {"Full Name": "RAHMAN MD ALAM", "Mobile": "01711223344"}
    assert auto_sync._likely_same({"Full Name": "RAHMAN MST SHIULY", "Mobile": "01711223344"}, new_no_dob) == 0.0
    # The real case the rule is for still matches: a name completed in the same sync as the ID.
    assert auto_sync._likely_same({"Full Name": "HASAN MD", "Mobile": "01711223344"},
                                  {"Full Name": "HASAN MD RAIYAN", "Mobile": "01711223344"}) > 1.0


def test_a_dated_calendar_answer_says_what_it_left_out_as_done():
    today = date(2026, 9, 28)
    items = [
        ask.CalItem("SEJONG DHL", "DHL to send", "SEJONG", date(2026, 9, 20), date(2026, 9, 22), False, ""),
        ask.CalItem("HANYANG BACHELOR", "DHL to send", "HANYANG", date(2026, 9, 20), date(2026, 9, 22), True, ""),
    ]
    q = ask.CalendarQuery(ask.Window(date(2026, 9, 21), date(2026, 9, 21), "Mon 21 Sep 2026"),
                          False, False, [], None, False)
    text = ask.calendar_answer(items, q, today)
    assert "`1`" in text and "SEJONG DHL" in text
    assert "marked done on the portal: HANYANG BACHELOR (due 22 Sep)" in text


def test_the_briefs_verified_total_says_what_it_adds_up():
    verified = [{"name": "A", "amount": "8,000.00 BDT", "verified_income": "8,000.00 BDT"},
                {"name": "B", "amount": "1.00 BDT", "verified_income": "1.00 BDT"}]
    lines, _ = section_verified(verified, "19 Sep 2026", False)
    assert "Total: 8,001.00 BDT (verified income)" in lines[1]
    paid = [{"name": "A", "amount": "8,000.00 BDT"}]
    lines, _ = section_verified(paid, "19 Sep 2026", False)
    assert "Total: 8,000.00 BDT (amounts paid)" in lines[1]


def test_the_brain_is_pinned_only_for_the_voice(monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_ALWAYS_LOADED", False)
    monkeypatch.setattr(settings, "JENNIE_VOICE_ENABLED", False)
    assert not oc.brain_pinned() and oc.keep_alive() == "5m"
    assert oc.ollama_client._payload()["keep_alive"] == "5m"
    monkeypatch.setattr(settings, "JENNIE_VOICE_ENABLED", True)
    assert oc.brain_pinned() and oc.keep_alive() == -1
    monkeypatch.setattr(settings, "JENNIE_VOICE_ENABLED", False)
    monkeypatch.setattr(settings, "BRAIN_ALWAYS_LOADED", True)
    assert oc.keep_alive() == -1


def test_keep_brain_warm_does_nothing_when_the_brain_is_not_pinned(monkeypatch):
    from src.bot import scheduler
    monkeypatch.setattr(settings, "BRAIN_ALWAYS_LOADED", False)
    monkeypatch.setattr(settings, "JENNIE_VOICE_ENABLED", False)
    called = []

    async def residency():
        called.append("residency")
        return {}
    monkeypatch.setattr(scheduler.ollama_client, "residency", residency)
    asyncio.run(scheduler.keep_brain_warm())
    assert called == []


def test_the_verifiers_sibling_pairs_and_real_corrections():
    mob = {"Mobile": "01711223344"}
    assert auto_sync._likely_same({"Full Name": "ISLAM MD MASHIUL", **mob}, {"Full Name": "ISLAM MD MASUD", **mob}) == 0.0
    assert auto_sync._likely_same({"Full Name": "MD MASHIUL ISLAM", **mob}, {"Full Name": "MD MASHIOL ISLAM", **mob}) > 1.0
    assert auto_sync._likely_same({"Full Name": "BADHON SUFIUR RAHMAN", **mob},
                                  {"Full Name": "BADHON SOUFIUR RAHMAN", **mob}) > 1.0
