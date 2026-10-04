# What was changed before this code was published

This note is for the owner and for anyone, person or AI assistant, who reads this repository. It says what was replaced or removed before the bot's code was uploaded, where, and what that changes. It contains no real personal value: it names categories, places and counts only.

Two terms are used throughout:

| Term | Meaning |
|---|---|
| working copy | The bot's own git repository on the office PC, the one the live bot runs from. Its last commit is dated 30 September 2026 (old id `8317741` (here `e1a3638`)). |
| this repository | The published copy: the same 48 commits, rewritten, plus the documentation added for publishing. |

`path:line` references are relative to the repository root.

## Contents

1. [Why](#1-why)
2. [What was removed](#2-what-was-removed)
3. [What was replaced](#3-what-was-replaced)
4. [What was deliberately kept](#4-what-was-deliberately-kept)
5. [Files that differ from the working copy](#5-files-that-differ-from-the-working-copy)
6. [Where the published code behaves differently from the live bot](#6-where-the-published-code-behaves-differently-from-the-live-bot)
7. [History](#7-history)
8. [Test results before and after](#8-test-results-before-and-after)
9. [What is not in the repository at all](#9-what-is-not-in-the-repository-at-all)
10. [How it was checked](#10-how-it-was-checked)

## 1. Why

The bot works with the real records of an education agency's students. Its working copy on the office PC holds real students' and staff members' details: names, student ids, passport numbers, phone numbers and e-mail addresses in test data, in comments and docstrings that use real cases as examples, and in demo data. Older commits also held a hard-coded list of students with their passport numbers, parents' names and home addresses, and every commit held a photo of a passport. The published copy must not hold any of this, so every commit was rewritten with made-up values before it was uploaded. The working copy itself was not changed: the bot on the office PC still runs the original code.

## 2. What was removed

**`test_passport.jpg`, from every commit.** It was a photograph of a real person's open passport (a 382,243-byte JPEG), tracked at the repository root from the first commit on. It was deleted from all 48 commits. No commit of this repository contains it, and after its removal no commit contains any binary file.

**What still mentions it.** No script, launcher, module or test in any of the 48 commits opens the file or names it, so nothing fails without it. The tests named `test_passports_...` are about the `/passports` command, not this file. The file name appears only in documents:

| File | What it says |
|---|---|
| `docs/reference/02_ENVIRONMENT_SETUP_AND_OPERATIONS.md:80` | Lists it in the file tree of the bot folder. |
| `docs/reference/03c_FILES_sheets_verify_root_scripts.md:625-626` | Section 4.6: a tracked image that nothing references. |
| `README.md`, `docs/PROJECT_STRUCTURE.md` | Say that it was left out of this repository. |

**What to use instead.** Any passport image of your own. To try the passport reader by hand, pass its path to `read_passport_scan(image_path)` (`src/scraper/ocr_validator.py:375`) or `extract_mrz_from_image(image_path)` (`src/scraper/ocr_validator.py:415`). Both accept an image file or a PDF; for a PDF the reader writes `<name>_extracted.jpg` beside it (`load_passport_image`, `src/scraper/ocr_validator.py:128`). Do not commit that image.

## 3. What was replaced

Every real value was replaced by a made-up one by a list of rules. One rule replaces one written form of one real value (for example the upper-case form of a name, or an id without its leading zeros). The rules were applied to every version of every file in all 48 commits, to the commit messages, to the extras and to the reference documents. There are 210 rules.

### 3.1 By category

| Category | Where it appeared | Distinct real values | Rules |
|---|---|---|---|
| Students' names used in test fixtures and code comments (real, or unsure and treated as real) | Tests; comments and docstrings of the name matcher and the OCR code; a trial script in `extras/`; one commit message | 27 names or name parts | 39 |
| Students named in the bot's documents and examples | `HANDOFF.md`; a CLI example and a docstring in `src/verify/doc_verifier.py`; the demo data in `src/scraper/mock_data.py`; the sample table in `test_system.py`; one test fixture | 4 names, and 1 e-mail address made from one of them | 7 |
| Students in an old hard-coded audit list and a fixed `/passports` reply | Older commits only: `src/scraper/ocr_validator.py`, both copies of `telegram_bot.py`, the old root `test_crosscheck.py`. At HEAD their given names were still used as examples in `/crosscheck` help texts and in tests | 12 names | 34 |
| Parents' names | The same old list (older commits only) | 10 | 10 |
| Home addresses | The same old list (older commits only) | 5 | 5 |
| Students in an old list in `MIGRATION.md` | Older commits only; the list was dropped when the document was rewritten | 11 | 11 |
| Passport numbers | The old list; `HANDOFF.md`; `PC_BUILD.md`; `src/verify/auto_verify.py`; CLI examples; OCR comments and docstrings; the demo data | 21 written values: 18 numbers, plus an OCR misread, a 9-digit scanned form and a mistyped portal copy of some of them. Two of the 18, in the demo data, matched no record but were replaced anyway | 21 |
| Phone numbers | The `normalize_phone` docstring (both copies of `progress_builder.py`) | 2 | 2 |
| A national-ID-style number | A docstring in `src/verify/doc_verifier.py` | 1 | 1 |
| E-mail addresses | A partner's Google account in a comment (both copies of `progress_builder.py`); a staff member's address hidden in Cloudflare's e-mail-protection code in `tests/test_performance.py` | 2 | 2 |
| HNG student ids that belong to real students | Examples in comments, docstrings, CLI examples and the `/sendmail` prompt; fixture and demo ids that are in the range of ids in use; the phone app's tests and planning notes; one reference document | 39 | 50 |
| Payment details (amount and method) beside a portal student number | A planning note of the phone app in `extras/` | 1 | 1 |
| Consultants' names | Tests; docstrings; 3 commit messages; older versions of the performance page reader; 4 reference documents | 6 consultants, plus 1 hyphenated verifier name that contains their shared surname | 20 |
| The head of branch's name | `HANDOFF.md`; a comment in `src/verify/auto_verify.py`; the `/sendmail` prompt | 1 | 2 |
| A payment verifier's name (unsure, treated as real) | Tests; a docstring in `src/bot/replies.py` | 1 | 5 |
| **Total** | | | **210** |

### 3.2 Principles

- **Unsure means real.** A value that might belong to a real person was treated as real.
- **One made-up value per real value, everywhere.** The same real value got the same made-up value in every file, every commit, every commit message, the extras and the reference documents. Two different real values never share a made-up value. A value written in several forms (upper case, title case, the given name alone, an id with or without leading zeros, an id's short number, a name run together the way OCR reads a passport) got the matching form of the same made-up value.
- **Made-up values are not real.** No made-up name, passport number, phone number, id or e-mail address is a real one, and no made-up name is within two letters of a real name, in any word order. Common surnames (and words such as `MD` and `MST`) were kept where they stood beside a replaced given name.
- **The shape the code relies on was kept.** Names keep their number of words. Lists of names keep their alphabetical order. Siblings still share a surname. A spelling pair (portal against passport) is still one letter apart. No month abbreviation was gained or lost inside a name, so the date-reading tests see the same thing. A name inside a machine-readable passport line keeps its length, so the line keeps its length.
- **Passport numbers keep their check digit.** Every made-up passport number has the same letter-and-digit pattern as the real one and the same ICAO 9303 check digit, so a check digit printed after it in a passport's machine-readable line stays valid. Where a document proves a typo by the check digit, the made-up pair proves it the same way.
- **Formats were kept.** Phone numbers keep their written format (with `+`, with a leading `0`, or without). The e-mail address hidden in Cloudflare's encoding was encoded again with the same key.
- **Dates were kept.** All dates and times are unchanged, everywhere.
- **Line numbers did not change.** Every replacement happens inside one line. None of the 132 rewritten file versions gained or lost a line. A `path:line` reference in the reference documents, in the bot's older documents or in this repository's documents points at the same line here as in the working copy. Within a line, text after a replacement can move left or right when the made-up value is shorter or longer.
- **Three edits go beyond swapping a value:**
  - `tests/test_crosscheck.py:76`: one fixture call `verified(...)` is written out as the equivalent `row(...)` call, so that the fixture's student id is a made-up one while its portal number stays. The page it builds is the same except for the id.
  - `extras/jeannie-app/tests/hangeul-migration.test.ts`: an id that the test builds from a fixture number now adds a fixed offset, so the built id equals the made-up id the test expects.
  - Two planning notes of the phone app (`extras/jeannie-app/.scratch/hangeul-cloud-context/issues/05-answers-and-orchestrator.md`, `08-live-verification.md`): a few words were added inside one line to say that the id there is a made-up stand-in.

### 3.3 Recognising made-up values

| Kind | Made-up values look like |
|---|---|
| HNG student ids | `HNG-2026-9xx` (every id from 900 up is made up) |
| Passport numbers | `A0099xxxx`, `B0099xxxx`, `AG077xxxx`, and the 9-digit form `40099xxxx` |
| Phone numbers | `017000000xx`, also written without the leading `0`, or with `880` or `+880` in front |
| E-mail addresses | `...@example.com` |

Names have no such pattern. After the rewrite, the checks of section 10 found no real student's or staff member's value left, apart from what section 4 lists as kept. Treat every name, id, passport number, phone number and e-mail address in this repository as made up, except the owner's own name and e-mail address. The list that maps real values to made-up ones exists only on the office PC and is not published; do not try to reconstruct it.

## 4. What was deliberately kept

| Kept | Where | Why |
|---|---|---|
| The owner's own name and e-mail address | Author and committer of all 48 commits; the Google account named in the docstring of both `progress_builder.py` copies and in `MIGRATION.md`; `PC_BUILD.md`; a prompt in both `telegram_bot.py` copies; the phone app's own profile fixtures | They are the owner's own, published by the owner. |
| Business identifiers | The agency's name; its portal address (`src/config.py:24`); its office details in the phone app's profile fixture (`extras/jeannie-app/tests/memory-chunk.test.ts`); the Google Drive id of the agency's "ALL STUDENTS" folder (`src/sheets/progress_builder.py:56` and the root copy); program and university names | They identify the business, not a person. |
| Dates and times | Everywhere, including the old hard-coded list in older commits | Kept by rule. The names, numbers and addresses beside them were replaced. |
| Figures | Amounts and payment methods in the code's standard examples, counts, prices | Not personal. One payment in a planning note was replaced anyway (section 3.1). |
| Portal student numbers (the `N` of `student_edit.php?id=N`) | Tests, docstrings, help texts | Internal row numbers of the portal; kept by rule. |
| Example Telegram chat ids | The comment at `src/config.py:49` | Kept by rule. |
| HNG ids that belong to no student | Gaps in the numbering, numbers above the range in use, the made-up 9xx block, a 2025 year example in `src/bot/ask.py` | Nobody has them. |
| Common surnames, and generic names made up for the demo data and fixtures | The name matcher's word lists, `src/scraper/mock_data.py`, test fixtures | Ordinary name words. Every distinctive word of a real name was replaced. |
| A placeholder passport number in a machine-readable-line docstring | `src/scraper/ocr_validator.py` | A standard placeholder, not anyone's number. |

## 5. Files that differ from the working copy

### 5.1 At HEAD

`diff -rq` between the working copy at old id `8317741` (here `e1a3638`) and this repository's rewrite of that commit lists 35 entries: 34 files that differ, and the removed image. "Lines" is the number of lines that differ.

| File | Lines | What kind of value changed |
|---|---|---|
| `HANDOFF.md` | 8 | Passport numbers; the head of branch's name; students' names |
| `PC_BUILD.md` | 2 | Passport numbers (an OCR misread example) |
| `progress_builder.py` | 3 | A student id (CLI example); a partner's e-mail address (comment); phone numbers (docstring) |
| `src/bot/ask.py` | 1 | The consultants' surname (docstring example) |
| `src/bot/replies.py` | 1 | A payment verifier's name (docstring example) |
| `src/bot/telegram_bot.py` | 10 | Student ids, students' names, the head of branch's surname, the consultants' surname (comments, docstrings, three reply texts) |
| `src/scraper/mock_data.py` | 11 | Student ids, passport numbers, a student's name and e-mail address (demo data) |
| `src/scraper/ocr_validator.py` | 4 | A passport number (comment); students' names (docstring and comment examples of names run together by OCR) |
| `src/scraper/parsers.py` | 1 | A student id (docstring) |
| `src/sheets/auto_sync.py` | 4 | Students' names (comments and docstring: sibling and spelling examples) |
| `src/sheets/missing_report.py` | 1 | A student id (CLI example) |
| `src/sheets/progress_builder.py` | 3 | Same as the root `progress_builder.py` (byte-identical copy) |
| `src/verify/auto_verify.py` | 2 | The head of branch's name (comment) and passport number (`SKIP_PASSPORTS`) |
| `src/verify/doc_verifier.py` | 4 | A student's name and a passport number (CLI examples); a national-ID-style number (docstring); a student's name (docstring) |
| `src/verify/field_check.py` | 3 | Passport numbers (CLI example, docstring) |
| `telegram_bot.py` | 10 | Same as `src/bot/telegram_bot.py` (byte-identical copy) |
| `test_passport.jpg` | - | Removed (section 2) |
| `test_system.py` | 1 | A student's name (sample HTML table) |
| `tests/test_brief.py` | 18 | Consultants' names; a payment verifier's name |
| `tests/test_cloud.py` | 13 | Consultants' names; student ids |
| `tests/test_cloud_dry_run.py` | 3 | Student ids |
| `tests/test_cloud_fixes.py` | 2 | Student ids |
| `tests/test_cloud_jobs.py` | 4 | Student ids |
| `tests/test_crosscheck.py` | 19 | Students' names; consultants' names; student ids; one fixture call written out (section 3.2) |
| `tests/test_final_fixes.py` | 9 | Students' names |
| `tests/test_foundation.py` | 18 | Students' names; consultants' names; a payment verifier's name; a student id |
| `tests/test_freetext.py` | 9 | Students' names; consultants' names; a payment verifier's name |
| `tests/test_inquiries.py` | 12 | Consultants' names |
| `tests/test_integration.py` | 1 | Students' names |
| `tests/test_jobs.py` | 61 | Students' names; student ids |
| `tests/test_performance.py` | 33 | Consultants' names; a payment verifier's name; an e-mail address in Cloudflare's encoding |
| `tests/test_repair.py` | 19 | Students' names; consultants' names; student ids |
| `tests/test_voice.py` | 5 | Students' names; a payment verifier's name |
| `tests/test_voice_fast.py` | 1 | A payment verifier's name |
| `tests/test_watcher_nonblocking.py` | 1 | A student's name (fixture) |

Every other file of the bot is byte-identical to the working copy. On top of the 48 commits, the documentation commit added `docs/`, `extras/` and a new `README.md`; the bot's own README was moved, unchanged, to `docs/BOT_README.md`. A patch to the bot's files made in this repository applies to the working copy, except where it touches one of the lines above.

### 5.2 Only in older commits

| File | Commits whose version changed | What kind of value changed |
|---|---|---|
| `src/scraper/ocr_validator.py` | 21 commits, from the first commit until old id `40da0e6` (here `515984b`) removed the list | The old hard-coded audit list: students' names, passport numbers, parents' names, home addresses |
| `src/bot/telegram_bot.py`, `telegram_bot.py` | The same 21 commits | The fixed `/passports` reply: students' names and passport numbers |
| `test_crosscheck.py` (root) | The same 21 commits; old id `40da0e6` (here `515984b`) deleted the file | Students' names and passport numbers from the old list |
| `MIGRATION.md` | 8 commits, from the first commit until old id `b0245df` (here `3721de1`) rewrote the document | A list of 11 students' names. The current `MIGRATION.md` is unchanged. |
| `src/bot/performance.py` | 2 commits | Consultants' names |
| Older versions of the files in 5.1 | Various | The same kinds as at HEAD |

In total 132 file versions were rewritten: 32 that are part of HEAD and 100 that exist only in older commits.

### 5.3 Extras

`extras/` is not part of the bot's git history; it was copied in and rewritten with the same rules. 9 of its files differ from their originals on the office PC:

| File | Lines | What kind of value changed |
|---|---|---|
| `extras/jeannie-app/tests/hangeul-answer.test.ts` | 2 | Student ids |
| `extras/jeannie-app/tests/hangeul-fixtures.ts` | 7 | Student ids |
| `extras/jeannie-app/tests/hangeul-migration.test.ts` | 2 | Student ids; an id template (section 3.2) |
| `extras/jeannie-app/tests/hangeul-router.test.ts` | 2 | Student ids |
| `extras/jeannie-app/tests/hg-local.test.ts` | 3 | Student ids |
| `extras/jeannie-app/.scratch/hangeul-cloud-context/hangeul-bot-prompt.md` | 1 | The amount and method of one payment beside a portal student number |
| `extras/jeannie-app/.scratch/hangeul-cloud-context/issues/05-answers-and-orchestrator.md` | 1 | A student id, with a few words added (section 3.2) |
| `extras/jeannie-app/.scratch/hangeul-cloud-context/issues/08-live-verification.md` | 1 | A student id, with a few words added (section 3.2) |
| `extras/trials/brain-trial/trial.py` | 2 | Two students' names in a sample prompt |

### 5.4 Reference documents

`docs/reference/` holds copies of the reference pack kept on the office PC, rewritten with the same rules. 5 of its 17 files differ from the originals:

| File | What kind of value changed |
|---|---|
| `docs/reference/03a_FILES_src_bot.md` | The consultants' surname, used as an example word |
| `docs/reference/03b_FILES_src_scraper_llm_api_config.md` | The pattern of the demo data's student ids |
| `docs/reference/05_TELEGRAM_COMMANDS_AND_JOBS.md` | The consultants' surname, used as an example word |
| `docs/reference/09_BLUEPRINT_RULES_AND_LESSONS.md` | The consultants' surname, used as an example word |
| `docs/reference/10_TESTS_AND_VERIFICATION.md` | The consultants' surname, used as an example word |

## 6. Where the published code behaves differently from the live bot

These are the places outside `tests/` where a value that the code uses (not only a comment) held a real value:

| Place | What it held | Effect in the published code |
|---|---|---|
| `src/verify/auto_verify.py:56`, `SKIP_PASSPORTS` | The head of branch's passport number. The head of branch is staff, not an applicant, so the document check skips that record. | Now a made-up number. Run against the live portal, the document check would no longer skip the head of branch's record, nor the student record that `HANDOFF.md:226-227` says carries the same number; it would check them like any applicant's. Put your own staff passport numbers here. |
| `src/bot/telegram_bot.py:1486` and `telegram_bot.py:1486`, the `/sendmail` prompt | Three examples of how to name a student: a real student's HNG id, its short number, and the head of branch's surname | Shows made-up examples. Typed in, they find no student. |
| `src/bot/telegram_bot.py:1551` and `:1773` (same lines in `telegram_bot.py`), `/crosscheck` reply texts | Real students' given names as examples | Shows made-up names. |
| `src/scraper/mock_data.py:48`, `:54`, `:68` (`MOCK_DASHBOARD_STATS`) and `:82-84`, `:97`, `:112`, `:127`, `:142`, `:157` (`MOCK_APPLICATIONS`) | Demo data with HNG ids of real students, two passport-like numbers, a student's name and e-mail address | In mock mode (`MOCK_MODE`, default `true` at `src/config.py:21`) the demo answers show the made-up values. |
| `test_system.py:41`, `sample_html` | A student's name in a sample table | The script parses and prints the made-up name. Its checks count rows only, so its result is unchanged. |

Everything else that changed outside `tests/` is a comment, a docstring or a document, and changes no behaviour:

- `src/bot/ask.py:6`, `src/bot/replies.py:81`, `src/bot/telegram_bot.py:1211`, `:1213`, `:1509`, `:1522-1525`, `:1980` (same lines in `telegram_bot.py`)
- `src/scraper/ocr_validator.py:511`, `:568-569`, `:605`, `src/scraper/parsers.py:419`
- `src/sheets/auto_sync.py:167`, `:176-177`, `:181`, `src/sheets/missing_report.py:21`, `src/sheets/progress_builder.py:27`, `:54`, `:176` (same lines in `progress_builder.py`)
- `src/verify/doc_verifier.py:19-20`, `:418`, `:776`, `src/verify/field_check.py:15`, `:67-68`
- `HANDOFF.md:33`, `:183-185`, `:226-227`, `:286`, `:309`, `PC_BUILD.md:168-169`

A CLI example copied from one of these docstrings or documents now names a student or a passport number that does not exist, so it finds nothing.

## 7. History

- **All 48 commits are kept**, in the same order, with the same 8 merges, the same authors and committers, the same e-mail addresses, the same dates and the same subjects.
- **Every commit id changed.** Rewriting a file changes the id of every commit from that point on, and `test_passport.jpg` was removed from the first commit. [COMMIT_ID_MAP.md](COMMIT_ID_MAP.md), beside this file, maps each old id to its new id.
- **Old ids are still quoted in places.** The reference documents under [reference/](reference/) quote the OLD ids from the office PC. Some commit messages name an earlier commit by its old id. Look those ids up in COMMIT_ID_MAP.md. Commits after the 48 (the documentation commit and any later ones) were made for this repository and have no old id.
- **Four commit messages changed**, in their body only: old ids `bbd8f98` (here `bde5af4`), `7f42ad0` (here `9797406`) and `46cdf03` (here `7be92d0`) (consultants' names) and `40da0e6` (a student's name from a test fixture).
- **History-only material was rewritten in every commit that holds it** (section 5.2). None of it is at HEAD.

## 8. Test results before and after

Command, from the repository root: `python -m pytest tests -m "not slow" -q`

| Code | Result |
|---|---|
| Working copy, untouched (old id `8317741` (here `e1a3638`)) | 1151 passed, 1 deselected (the one test marked `slow`, which loads a real embedding model) |
| This repository, the rewrite of the same commit | 1151 passed, 0 failed, 1 deselected |

The run on the rewritten code left no tracked file changed.

While the rules were being made, the tests of 29 older commits, chosen to cover the rewritten versions of the Python files, were also run on both copies with every network connection outside the PC refused. Each commit gave the same result on the original and on the rewritten copy. Some older commits hold tests that depend on the date they are run; those fail on both copies alike.

The phone app's tests (`extras/jeannie-app/tests`) were not run, because nothing could be installed for this check. The changed lines were read instead: each test still expects the same made-up id its fixture holds.

## 9. What is not in the repository at all

The full list, with where each item lives on the office PC, is in [PROJECT_STRUCTURE.md section 7](PROJECT_STRUCTURE.md#7-what-is-on-the-office-pc-but-not-in-this-repository-and-why).

- **Secrets:** `.env`, `credentials.json`, `token.json`, the office PC's secrets folder, and the phone app's settings files.
- **The data folder:** `data/` (sheet state, verification results, OCR text caches, publishing state, locks).
- **Student documents:** `passports/`, the downloaded verified-document folders, CSV and Excel reports, and the passport photo of section 2.
- **Logs:** the bot's, the sync's, the watchdog's and the voice service's logs (only 13 trial and benchmark logs under `extras/`, checked and holding made-up sample sentences only, are included).
- **Audio:** the voice's reference clip, the filler clips, the trial samples and test voice notes.
- **Models:** the Ollama model, the EasyOCR models, the embedding model, and the Whisper and CosyVoice weights.
- **Environments and build output:** `.venv`, `node_modules/`, `.next/`.
- **The phone app's media and tool folders:** avatar clips, posters, icons, and its `.claude` folder.
- **The replacement rules and the scripts that applied and checked them:** they hold the real values, so they stay on the office PC.

## 10. How it was checked

Each round started from a fresh clone of the working copy, rewrote all 48 commits, copied and rewrote the extras and the reference documents, and ran the tests. Then three checks were made independently of each other:

1. **Database needles.** A list of every real value was built fresh from the bot's own local data on the office PC: student records, sheet state, verification results, saved portal pages, staff and verifier names, phone numbers, passport numbers, student ids and e-mail addresses. Every version of every file in all 48 commits, every commit message, the extras and the reference documents were searched for each value: exactly, ignoring case, in any word order, one letter off, run together the way OCR reads a passport, and, for passport numbers, within two characters. Every made-up value was also checked against the list, so that none is real or close to a real name.
2. **Careful reading without needles.** A separate reviewer read every changed line and the text around it, without the list, looking for anything that still reads like a person's details (names, numbers, addresses, e-mail addresses, including encoded ones) and for any replacement that changed the meaning of the text or code.
3. **Tests and behaviour.** The unit tests were run on the rewritten code. Every changed line in every commit was compared word by word with the original. The check digits of the passport numbers were computed again. Applying the rules a second time changed nothing; no rule rewrote another rule's made-up value; no file gained or lost a line; properties the code relies on (word counts, alphabetical order, shared surnames, spelling pairs, line lengths in passport lines) were compared before and after.

Whatever a check found was fixed in the rules, and the next round started again from a fresh clone. There were 3 rounds. In the last round all three checks came back clean.
