"""What the merge of the fix branches (fix/all) put right where one branch's change met another's,
and the leftovers found after it: /alerts reads the dashboard's live "Needs attention" card (it
used to say "No urgent alerts" whatever the portal showed), /stats is split and resent as plain
text like every other reply, the /sendmail lookup reads every page of students.php when the CSV
export fails and says so when the portal cannot be read, the /inquiries_date prompt has no code
spans inside italics, and the root passport scripts list every page.

Every portal page is synthetic (laid out like the live pages, Sep 2026). Nothing reaches the
network, Telegram, SMTP or Ollama.

Run from the BOT folder:
    .venv\\Scripts\\python.exe -m pytest tests\\test_integration.py -q
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

from src.bot import telegram_bot  # noqa: E402
from test_foundation import ADMIN_ID, Chat, Message, page, portal, report_of, row, run  # noqa: E402,F401
from test_freetext import dashboard_page  # noqa: E402


def two_pages_of_students():
    first = page(*[row(600 + i, i + 1, f"PAGE ONE STUDENT {chr(65 + i)}", hng=f"HNG-2026-{600 + i}")
                   for i in range(3)], pg=1, pages=2, total=4)
    second = page(row(700, 4, "SECOND PAGE SADIA", hng="HNG-2026-700"), pg=2, pages=2, total=4)
    return {"students.php": first, "students.php?pg=2": second}


# --------------------------------------------------------------------------- /alerts

def test_alerts_are_the_dashboards_live_needs_attention_card(portal):
    portal.pages["index.php"] = dashboard_page(pending=2)
    chat, _ = run(telegram_bot.alerts_command, "/alerts", [])
    text = report_of(chat)
    assert "Needs attention" in text and "No urgent alerts" not in text
    assert "Payment verification" in text and "Rejected documents" in text and "`13`" in text
    assert [m for m, _ in portal.asked] == ["GET"]


def test_alerts_say_when_the_dashboard_cannot_be_read(portal):
    chat, _ = run(telegram_bot.alerts_command, "/alerts", [])                  # index.php answers 404
    text = report_of(chat)
    assert "Couldn't read the portal" in text and "No urgent alerts" not in text


# --------------------------------------------------------------------------- /stats

def stats_update(chat, refuse_markdown=False):
    update = SimpleNamespace(message=Message(chat, "/stats", refuse_markdown=refuse_markdown),
                             effective_chat=SimpleNamespace(id=ADMIN_ID), effective_user=SimpleNamespace(id=ADMIN_ID),
                             callback_query=None)
    return update, SimpleNamespace(args=[], user_data={}, bot=SimpleNamespace())


def test_stats_markdown_trouble_is_resent_as_plain_text(portal):
    portal.pages["index.php"] = dashboard_page()
    chat = Chat()
    asyncio.run(telegram_bot.stats_command(*stats_update(chat, refuse_markdown=True)))
    assert len(chat) == 1 and chat[0].parse_mode is None
    assert "Hangeul Admin Quick Stats" in chat[0].text and "*" not in chat[0].text


def test_a_long_stats_reply_is_split_under_telegrams_limit(portal):
    # A dashboard with many more tiles than today's: the reply is split between lines, never
    # refused as "Message is too long".
    extra = "".join(f'<a class="stat-card kpi" href="students.php"><span class="kpi-txt"><span class="stat-num">{i}'
                    f'</span><span class="stat-lbl">An extra dashboard figure with a long label {i}</span></span></a>'
                    for i in range(150))
    portal.pages["index.php"] = dashboard_page().replace(
        "</div></div>", '</div><div class="dash-sec"><div class="ds-txt"><h2 class="ds-t">More figures</h2></div></div>'
        f'<div class="stats-row">{extra}</div></div>', 1)
    chat = Chat()
    asyncio.run(telegram_bot.stats_command(*stats_update(chat)))
    text = "\n".join(m.text for m in chat)
    assert len(chat) > 1 and all(m.parse_mode == "Markdown" for m in chat)
    assert "An extra dashboard figure with a long label 149" in text and "Total students" in text


# --------------------------------------------------------------------------- /sendmail's lookup

def edit_page(uid, name, email):
    return (f'<html><body><form><input name="full_name" value="{name}"><input name="email" value="{email}">'
            f'<input name="guardian_email" value="guardian@example.test"></form></body></html>')


def test_the_sendmail_lookup_reads_every_page_when_the_export_fails(portal):
    portal.pages.update(two_pages_of_students())                  # no CSV export: it answers 404
    portal.pages["student_edit.php?id=700"] = edit_page(700, "SECOND PAGE SADIA", "sadia.second@example.test")
    chat, context = run(telegram_bot.handle_natural_language_message, "Sadia", None, {"email_flow": {"step": "id"}})
    text = report_of(chat)
    assert "Found *SECOND PAGE SADIA*" in text and "sadia.second@example.test" in text
    assert "protected" not in text                                 # Cloudflare's placeholder is no email
    assert context.user_data["email_flow"]["step"] == "subject"
    assert ("GET", "students.php?pg=2") in portal.asked
    assert {m for m, _ in portal.asked} == {"GET"}

    found = asyncio.run(telegram_bot._find_student_on_list_page("HNG-2026-700"))
    assert found["id"] == "700" and found["hng"] == "HNG-2026-700" and found["dob"] == "2000-01-01"
    assert asyncio.run(telegram_bot._find_student_on_list_page("Nobody Here")) is None


def test_a_sendmail_lookup_that_cannot_read_the_portal_says_so(portal):
    chat, context = run(telegram_bot.handle_natural_language_message, "Sadia", None, {"email_flow": {"step": "id"}})
    text = report_of(chat)
    assert "Couldn't read the portal" in text and "No student found" not in text
    assert context.user_data["email_flow"]["step"] == "id"          # it waits for the id again


# --------------------------------------------------------------------------- prompts and scripts

def test_the_inquiries_date_prompt_has_no_code_inside_italics(portal):
    chat, _ = run(telegram_bot.inquiries_date_command, "/inquiries_date", [])
    assert "(e.g. `12 Sep 2026`, `yesterday` or `2026-09-12`)" in chat[0].text
    assert "_(" not in chat[0].text


def test_the_program_audit_script_sorts_the_new_ocr_results_honestly(portal):
    import audit_program
    from src.scraper.ocr_validator import unchecked_result
    # The portal could not serve the profile or scan: nothing was checked, never "scan unreadable".
    assert audit_program.classify(unchecked_result("7", "timed out"))["scan"] == "unchecked"
    assert audit_program.classify({"status": "OCR_UNAVAILABLE", "fields": {}})["scan"] == "unchecked"
    assert audit_program.classify({"status": "MRZ_UNREADABLE", "fields": {}})["scan"] == "unreadable"
    # A possible OCR misread is "check by eye", never a match and never an error.
    c = audit_program.classify({"status": "UNCERTAIN", "fields": {
        "name": {"status": "OCR_UNCERTAIN", "portal": "BELAL HOSSEN", "doc": "BELAL HOSSEM"},
        "dob": {"status": "MATCH", "portal": "2000-01-01", "doc": "2000-01-01"},
        "passport_no": {"status": "NOT_READ", "portal": "A01234567", "doc": ""}}})
    assert c["scan"] == "ok" and c["check"] == ["Name", "Passport No"] and c["wrong"] == []
    # The program's list is read on every page, with its filter kept.
    first = page(row(600, 1, "P ONE"), pg=1, pages=2, total=2)
    second = page(row(601, 2, "P TWO"), pg=2, pages=2, total=2)
    portal.pages.update({"students.php?prog=Bachelor%27s+Degree": first,
                         "students.php?prog=Bachelor%27s+Degree&pg=2": second})
    students = asyncio.run(audit_program.fetch_program_student_ids("Bachelor's Degree"))
    assert [(s["id"], s["name"], s["doc_filename"]) for s in students] == [
        ("600", "P ONE", "passport_600_1700000000.jpeg"), ("601", "P TWO", "passport_601_1700000000.jpeg")]


def test_the_passport_scripts_list_every_page(portal):
    import inspect_passports
    from src.scraper.client import admin_client
    portal.pages.update(two_pages_of_students())
    students = inspect_passports.passport_students(asyncio.run(admin_client.read_students()))
    assert [s["id"] for s in students] == ["600", "601", "602", "700"]
    assert students[-1]["doc_url"] == "view_doc.php?f=passport_700_1700000000.jpeg"
    assert students[-1]["name"] == "SECOND PAGE SADIA"
