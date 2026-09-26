# Hangeul BOT — system handoff

**Written 25 September 2026.** For whoever picks this up next, human or agent.
Read the "Known problems" section before trusting any document verdict.

---

## 1. What this is and why it exists

Hangeul Korean Language & Visa (Dhaka) processes students applying to study in South
Korea. The CEO built the student portal at `hangeul.com.bd/admin`. This system sits
*beside* that portal and does four things the portal does not:

1. Keeps a Google Sheets progress sheet per programme+intake in sync with the portal
2. Downloads every document-verified student's files to this PC
3. Checks those documents against the programme guidelines with local OCR
4. Reports through Telegram

It was built in Claude Code over several sessions, starting from an existing
Telegram-bot codebase that already did portal scraping and daily briefings.

### The one rule that governs everything

**The portal is read-only.** One `POST` exists in the entire codebase — `login.php`
(`src/scraper/client.py:101`). Everything else is `GET`. No form submissions, no button
presses, no AI features run on the portal. All analysis happens on local copies.

This is the user's standing instruction, recorded in
`.agents/rules/hangeul_operational_guardrails.md` (rule 7). Findings are **reported**;
corrections are made by staff on the portal by hand.

Also standing: never audit `signed_students.php`, only `students.php`.
`RAFIQ MD MOTIN UR` (passport `A00990004`) is the head of branch, not an applicant —
excluded from all checks.

---

## 2. Architecture

```
hangeul.com.bd/admin ──GET──┐
                            │
                    src/scraper/client.py      (login, CSRF, session)
                            │
        ┌───────────────────┼────────────────────┐
        │                   │                    │
 progress_builder     verified_docs        passport_issue
 (Google Sheets)      (document ZIPs)      (edit-page only field)
        │                   │                    │
        └────────► auto_sync.py ◄────────────────┘
                     │        │
                     │        └──► auto_verify.py ──► doc_verifier ──► EasyOCR/GPU
                     │                    │                └─► page_checks (cv2, pyzbar)
                     │                    └─► field_check  ──► portal values vs documents
                     ▼                    ▼
              Telegram summary      DOCUMENT CHECK.xlsx / FIELD CHECK.xlsx
```

One `pythonw run.py` process holds the Telegram bot and APScheduler. Every heavy job
runs as its **own subprocess**, so a failure inside one cannot take the bot down.

### Files that matter

| File | Lines | Role |
|---|---|---|
| `src/verify/doc_verifier.py` | 1138 | Reads each file; per-document rules; cross-document checks |
| `src/verify/page_checks.py` | 416 | Image-level: colour, QR/barcode, seals, e-Apostille page structure |
| `src/verify/auto_verify.py` | 589 | Orchestration, OCR caching, locking, both Excel reports |
| `src/verify/field_check.py` | 302 | Portal values compared against documents |
| `src/verify/rules.py` | 134 | The guidelines as data — thresholds, file patterns, required docs |
| `src/sheets/auto_sync.py` | 318 | The 15-minute cycle |
| `src/sheets/progress_builder.py` | 591 | Builds the Google Sheets, the Book1 flat layout |
| `src/sheets/verified_docs.py` | 408 | Document download + >2 MB shrinking |
| `src/bot/scheduler.py` | 252 | The five scheduled jobs |
| `src/bot/telegram_bot.py` | 1980 | ~25 commands, menus for /missing and /stage |

### Where data lives

| Path | What |
|---|---|
| `E:\VERIFIED STUDENT DOCUMENTS\<PROGRAM>\<NAME (PASSPORT)>\` | Downloaded documents (145 students) |
| `E:\VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB\` | Originals of anything shrunk |
| `data/verification/results.json` | Every check result; both reports are rebuilt from it |
| `data/verification/text/<PASSPORT>.json` | Cached OCR text, 154 files — this is why re-checks are fast |
| `data/sheet_state.json` | Last-seen state per programme+intake, drives "what changed" |
| `data/passport_issue.json` | Passport issue dates (not in the CSV export) |
| `token.json` / `credentials.json` | Google OAuth as rahmansaem@gmail.com. **No service account exists.** |

---

## 3. The workflow, step by step

### Every 15 minutes — `src/sheets/auto_sync.py`

**Step 1 — pull.** `students.php?export=csv` returns all 62 columns for every student.
Page-by-page scraping was abandoned early because it silently capped at 50 students.

**Step 2 — sheets.** For each programme+intake, build the row set and hash it
(`_row_key`, `_digest`). Compare with `data/sheet_state.json`. Only a sheet whose data
actually changed is rebuilt, and only its **main tab** — university sub-tabs the manager
adds by hand are never touched. `pb.sheet_drift` restores main-tab cells that were
hand-edited (this caught 127 cells blanked by a different Google account).

**Step 3 — documents.** `students.php?source=direct&filter_docs=verified` lists verified
students; `download_docs.php?uid=N&zip=1` returns their ZIP. Files over 2 MB are shrunk
(PDF re-rendered down an A4 ladder 1754→950 px, quality 70→45) with the original kept.
A `.download_complete` marker means "don't fetch again".

**Step 4 — Telegram.** Sends only when something changed. A failing step is retried 3×
with 20 s gaps, and only reports after **3 consecutive failed runs** — so a passing
Google 503 never pings anyone.

**Step 5 — verification.** Runs *after* the summary is sent, so slow OCR never delays
sheet notifications. Budget of 6 students per pass; the rest wait for the next tick.

### Other jobs (`src/bot/scheduler.py`)

| When | Job |
|---|---|
| every 30 min | Passport watcher — newly uploaded passports vs portal fields |
| 08:30 daily | Refresh passport issue dates (edit page only; ~290 fetches) |
| 09:05 daily | Missing-information report — Telegram + Excel |
| 18:05 daily | Executive briefing |

All times Asia/Dhaka. Autostart is installed (`Startup\HangeulBot.lnk` →
`start_background.vbs`), so the bot returns after a reboot **once you log in**. It does
**not** survive a crash — `install_watchdog.bat` adds a 5-minute watchdog but has not
been run.

---

## 4. How a document actually gets checked

### 4.1 Reading it

`doc_verifier.read_document()` / `read_pages()`:

1. **PDF with a text layer** → read it directly. Exact, instant.
2. **Scan or image** → render at 200 dpi with PyMuPDF, then EasyOCR on the GPU.
3. **Poor result** (< 300 characters) → retry rotated 90° each way and 180°, keep the
   best. Board certificates are printed landscape and scanned sideways; untouched they
   yield 196 characters and nothing useful, rotated they yield 729 and every field.
4. Everything is cached by `filename:size:mtime` in `data/verification/text/`. A cold
   student takes ~50 s; a cached re-check takes ~6 s.

**Stack:** EasyOCR 1.7.2 · PyTorch 2.11.0+cu128 · RTX 5060 (8 GB) · PyMuPDF 1.28.2 ·
OpenCV 5.0 headless · pyzbar 0.1.9 · Pillow 12.3.0 · openpyxl 3.1.5. All local — **no
API, no tokens, no cost**. GPU time only.

### 4.2 Classifying it

`rules.FILE_PATTERNS` maps filename keywords to a document key
(`passport`, `photo`, `birth_cert`, `father_nid`, `family_cert`, `academic`, `bank`,
`trade_license`, `income_tax`, `affidavit`, …). The portal names files consistently, so
matching on the name is reliable.

`rules.REQUIRED[programme]` says which must exist. Anything required and absent is
recorded as **MISSING**.

### 4.3 Checking it

Each key maps to a checker in the `CHECKS` table. Every checker receives the document's
text, the portal record, the page sizes, the file path, **and the documents already read
for that student** — which is how the birth certificate is compared against the passport
and the trade licence against the bank account holder.

Three layers run per document:

1. **Text rules** — dates, amounts, names, notarisation wording, fiscal years
2. **Image rules** (`page_checks`) — coloured-pixel share, QR/barcode decode, visible
   seal detection (violet/red connected components in HSV)
3. **Cross-document** — name, date of birth and passport number must agree across at
   least two readable documents

### 4.4 How it decides something is wrong

Verdicts: **FAIL** (rule broken) · **FLAG** (needs a human) · **NOTE** (advisory, never
blocks) · **MISSING**. A document's verdict is the worst of its findings, ignoring NOTEs.
A student is **PASS** only when nothing fails, flags or is missing.

Worked examples of real detection:

- **Passport number.** OCR read `A00990007` as `AG0770008`. The MRZ carries an ICAO check
  digit computed from the number, so `A00990008` (check digit 8 ✓) can be proven against
  `A00990009` (would be 9 ✗). This is how BABU MD JAKIR's portal typo was confirmed.
- **Birth certificate.** pyzbar decodes the QR to
  `https://bdris.gov.bd/certificate/verify?key=…` — a link that checks the certificate
  against the government register. OpenCV's own detector could not find these QRs at all,
  at any resolution.
- **Passport validity.** Bangladeshi passports run exactly 5 or 10 years, so issue and
  expiry prove each other arithmetically even when OCR mangles one.
- **Academic.** Each e-Apostille page is found by its QR host (`apostille.mygov.bd`), and
  the certificate/transcript beside it must be one qualification.

### 4.5 The field check

`field_check.py` compares ~22 portal fields per student against what the documents say:
MATCH / DIFFERS / UNREADABLE / NO DOCUMENT / BLANK. It tolerates OCR confusions
(A↔4, O↔0, S↔5), reads MRZ dates, and accepts a trade licence as proof of "business".

**This is the part that works.** Latest run: **3,394 comparisons, 1 difference.**

---

## 5. Known problems

### 5.1 Four document rules produce false failures — do not trust the verdict column

| Rule | Failures | Why it is wrong |
|---|---|---|
| ID number differs between pages | 91 | A Bangladeshi has **both** a 10-digit Smart NID and a 13/17-digit legacy number. 31 of 91 are that, not a mismatch. The other 60 are probably OCR misreads |
| Solvency vs statement date | 46 | Picks the statement's *period start* instead of its issue date |
| Opening balance below minimum | 64 | The unlabelled fallback takes the amount column, not the running balance (e.g. 1,185 BDT) |
| Apostille qualification mismatch | 50 | A transcript naming two exams reads as "mixed" |

Current output: PASS 1 · REVIEW 8 · FAIL 123 · INCOMPLETE 22 of 154. **The 123 is mostly
these four rules.** They should be downgraded to FLAG until each is proven against real
documents.

### 5.2 Smaller open items

- **TIN taxpayer name** unreadable on 17 students, so the TIN-vs-trade-licence rule
  cannot run
- **Corrections sheet** cannot tell a staff edit from a cache refresh — 85 of 246 entries
  are the passport-issue refresh, not people
- **AZAD TAMIM** is never checked: his portal record carries the HOB's passport number
  `A00990004`, and the system keys students by passport
- **Passport seal-placement check** disabled — it flagged all 12 test passports because it
  could not separate the passport image from the page
- **`annotate()`** in `page_checks.py` is dead code
- **`attendance.py`** reads the office attendance sheet but is not wired into the 09:05
  report; office start time and grace period were never confirmed
- **Watchdog not installed** — the bot survives a reboot but not a crash

### 5.3 Structural weaknesses

- **Hardcoded paths.** `E:\BOT`, `E:\VERIFIED STUDENT DOCUMENTS` are written into the
  source. The checker is not portable without editing.
- **The checker needs the portal.** `portal_students()` fetches live; there is no offline
  mode reading a saved CSV.
- **8 GB VRAM is tight.** EasyOCR (~1.5 GB) plus qwen2.5:7b (~4.7 GB) nearly fills it;
  running a second OCR process during a verification pass throws CUDA OOM.
- **System drive had 9 GB free** at last check. `.ollama` (4.4 GB) and Python/torch
  (5.4 GB) sit on C:. Moving Ollama models to E: via `OLLAMA_MODELS` is the easy win.
- **One physical disk** holds Windows, the bot and every student document.

---

## 6. Lessons that cost real time — do not repeat these

1. **Never patch source through a shell heredoc.** Escaping mangled `\b` into literal
   backspace bytes (`\x08`) in two files. In `doc_verifier` it meant NID numbers were
   never read; in `page_checks` it meant `H.S.C.`, `B.Sc`, `MBA` and `Master` were never
   recognised, which produced ~70 false apostille flags. Write a patch script to a file
   and run it, or use an editor tool.
2. **A swallowed exception looks exactly like a clean result.** `name 'holder' is not
   defined` skipped every bank check for a whole run and the report looked fine. Code
   faults (`NameError`, `AttributeError`, `TypeError`, `ImportError`) now stop the run.
3. **Never report a difference from cached data.** A day-old passport-issue cache accused
   staff of an error they had already fixed. The cache now refreshes daily, is part of
   the change-detection fingerprint, and a difference is suppressed if the cache is over
   26 hours old.
4. **Check the process, not the job id.** `$!` in bash gives the shell's job id, not the
   Python PID — twice I reported a run as finished while it was still going.
5. **Every false positive in this system was found by the manager looking at a document,
   not by the code.** Photo background sampled over shoulders; "ADV." not matched as
   advocate; a family certificate flagged for a QR it never had; a trade licence not
   credited as proof of business. Treat the first report on any new rule as a list of
   questions.

---

## 7. Running it

```bash
# one sync cycle by hand
python -m src.sheets.auto_sync --no-notify

# check what is waiting
python -m src.verify.auto_verify --pending

# re-test everyone against the current rules (~90 min, 154 students)
python -m src.verify.auto_verify --recheck --budget 0

# one student
python -m src.verify.auto_verify --recheck --passport A00990003

# only rewrite the reports from stored results
python -m src.verify.auto_verify --rebuild

# refresh passport issue dates
python -m src.sheets.passport_issue --refresh
```

Python 3.11 at `C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe`,
run from `E:\BOT`.

**Close `DOCUMENT CHECK.xlsx` and `FIELD CHECK.xlsx` before a run** — Excel locks them
and the write fails at the very end.

---

## 8. If you only do three things

1. **Downgrade the four rules in 5.1 from FAIL to FLAG**, then fix them one at a time,
   each proven against real documents before it goes back to FAIL.
2. **Free the C: drive and install the watchdog.** Both are minutes of work and both
   prevent silent, confusing failures.
3. **Fix AZAD TAMIM's duplicate passport on the portal** so he stops being skipped —
   a staff edit, not a code change.
