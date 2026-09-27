# Moving the system to a new PC

Updated 27 September 2026, after the move to the Ryzen 5 8600G / RTX 5060 PC. Every
step below was run on that machine; the timings are real.

The new machine rebuilds everything from the portal rather than inheriting the old one's
files. Portal access stays read-only throughout: GETs and the login, nothing else.

---

## 1. Where things live now

Nothing is tied to a drive letter any more. Every location is set in `.env`, and the
defaults sit beside the bot folder:

| Path | What |
|---|---|
| `C:\Hangeul\BOT` | The system itself, with `.env`, `credentials.json`, `token.json` and `data\` |
| `C:\Hangeul\BOT\.venv` | The bot's own Python 3.12 environment. Every launcher uses it |
| `C:\Hangeul\VERIFIED STUDENT DOCUMENTS` | Downloaded documents, `<PROGRAM>\<NAME (PASSPORT)>\` |
| `C:\Hangeul\VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB` | Originals of anything shrunk |
| `C:\Hangeul\BOT\data\verification` | OCR text cache, `results.json`, both check reports |

To put any of them elsewhere, set `DOCS_ROOT`, `DOCS_ORIGINALS_ROOT`, `KONYANG_ROOT` or
`VERIFICATION_DIR` in `.env` (see `.env.example`). If the bot folder is `X:\BOT`, the defaults
become `X:\VERIFIED STUDENT DOCUMENTS` and so on, so the old `E:\BOT` layout still works
unchanged.

**Konyang.** There is no local `KONYANG DOCUMENTS` folder on this PC; the verifier skips it.
A copy of 41 students is in Google Drive, in the bot's Drive folder under
`KONYANG DOCUMENTS`. Seven of the eleven students listed in the previous version of this file
are in neither place and are gone.

---

## 2. What to bring from the old machine

| Bring | Why |
|---|---|
| `.env` | Portal login, Telegram token, Gmail app password. Hidden by default: copy it on purpose |
| `data\verification\results.json` | **The only copy of the Corrections history.** Archive it outside `data\` even on a clean start |
| `credentials.json` | Optional: it can be downloaded again (section 6) |

Do **not** bring `.venv` (rebuild it), `token.json` (sign in again), `passports\` or the rest
of `data\` (all rebuilt). The student documents are downloaded again in phase 4.

If the old machine is lost, the code is on GitHub. The secrets come from their sources: the
portal login from whoever administers the portal; the Telegram token from @BotFather
(`/mybots` → the bot → API Token); the Gmail app password from Google Account → Security →
App passwords.

---

## 3. Python 3.12 and the packages

Install **Python 3.12** from python.org (3.11 is no longer required). Also install the
**Microsoft Visual C++ Redistributable (x64)**; without it `pyzbar` cannot decode QR codes.

In PowerShell, inside the bot folder:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install torch==2.11.0+cu128 torchvision==0.26.0+cu128 --index-url https://download.pytorch.org/whl/cu128
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

**Torch must go in first, from the CUDA index.** If `easyocr` is installed first it pulls in
PyPI's CPU-only torch, and the CUDA command then silently does nothing. The last command
must print `True`. `cu128` suits RTX 50-series (Blackwell) cards.

From here on, **use `.venv\Scripts\python.exe` for every command**, never bare `python`.
The launchers only ever use the venv, and a package installed into another Python is invisible
to them.

---

## 4. Ollama (optional)

```powershell
winget install Ollama.Ollama      # or the installer from ollama.com
ollama pull qwen2.5:7b
```

Only the 18:05 brief, `/sendmail` drafting and free-text answers use it; without it the brief
falls back to a template. The default model location is fine when the system drive has room.

---

## 5. Check HTTPS

```powershell
.venv\Scripts\python.exe -c "import urllib.request; urllib.request.urlopen('https://oauth2.googleapis.com/token', timeout=20)"
```

An `HTTP Error 404` means HTTPS works; skip the rest of this section. A
`CERTIFICATE_VERIFY_FAILED` means antivirus or the ISP intercepts HTTPS: run
`tools\export_windows_ca.ps1` and see the previous version of this file in git history.

---

## 6. Google sign-in

The OAuth app (Google Cloud project `hangeul-bo`) has been **In production** since
27 September 2026, so sign-ins no longer expire after 7 days. If it ever shows "Testing"
again, publish it before signing in: a sign-in made while in Testing still expires.

1. Google Cloud → Google Auth Platform → **Clients** → the **Desktop** client. Download its
   JSON (if the secret is hidden, **+ Add secret** and download straight away). Save it as
   `credentials.json` in the bot folder.
2. Delete any old `token.json`, then:

```powershell
.venv\Scripts\python.exe -m src.sheets.progress_builder --auth
```

Sign in as **rahmansaem@gmail.com**. The warning *"Google hasn't verified this app"* is
expected: **Advanced → Go to Hangeul Bot (unsafe)**, then allow both Drive and Sheets.

---

## 7. `.env`

Copy `.env.example` to `.env` and fill it in. Check three things:

- `MOCK_MODE=false`. If the line is missing the bot runs on **made-up demo data**, and
  `/stats` still answers.
- `TELEGRAM_ADMIN_CHAT_ID` is set. If it is empty the bot refuses everyone.
- The admin has pressed **Start** in the bot's Telegram chat (now **@the_Jennie_bot**).
  Telegram does not let a bot message anyone who has not, so the brief and alerts would fail
  silently.

---

## 8. Cold start: one phase at a time

**Do not run `bootstrap.py` unattended.** It only notices crashes, not phases that quietly
did nothing, so read each phase's summary before starting the next. Close games first:
OCR shares the GPU, and with a game open it ran ten times slower.

**Do not clear the progress sheets in Drive.** Phase 1 rewrites each main tab in place.
If a main tab is *deleted*, the code overwrites the first remaining tab instead, usually a
manager's university tab.

Run from the bot folder, in this order. Phase 2 comes before phase 1 so the Passport Issue
column is filled:

| Step | Command | Took |
|---|---|---|
| 2: passport issue dates | `.venv\Scripts\python.exe bootstrap.py --only 2` | 2 min |
| 1: progress sheets | `.venv\Scripts\python.exe bootstrap.py --only 1` | 35 s |
| 3: passport audit, 326 students | `.venv\Scripts\python.exe bootstrap.py --only 3` | 33 min |
| 4: documents, 146 students, 1.2 GB | `.venv\Scripts\python.exe -m src.sheets.verified_docs --local "C:\Hangeul\VERIFIED STUDENT DOCUMENTS" --include-drive-done` | 15 min |
| 5: document check | the batch loop below | 2 h 26 min |
| quiet first sync | `.venv\Scripts\python.exe -m src.sheets.auto_sync --no-notify` | 1 min |

What to look for:

- **Phase 2** prints how many issue dates it cached. 274 of 302 is normal; the rest are blank
  on the portal. `0 cached` means the portal login failed.
- **Phase 1** should say `updating existing sheet` for every sheet and `FAILED` for none.
- **Phase 3** writes `program_audit_*.csv`. Each program should report dozens of students,
  never `Found 0 students`. A student who "differs" is a question for a person, not a
  confirmed error.
- **Phase 4** ends with `N saved ... 0 failed`. Keep `--include-drive-done`, or students once
  uploaded to Drive are silently skipped.

**Phase 5 must run in batches.** One long `auto_verify` process keeps growing its GPU memory
until Windows spills it into system RAM, and each student slows from about 70 s to about
570 s. A fresh process per five students stays fast:

```powershell
do {
    $out = .venv\Scripts\python.exe -m src.verify.auto_verify --budget 5 2>&1
    $out | Select-String "Documents checked|more waiting|could not"
} while ($LASTEXITCODE -eq 0 -and ($out -match "more waiting"))
```

The quiet first sync records the starting state without messaging anyone. Without it, the
bot's first 15-minute run announces every sheet as new.

---

## 9. Start the bot and make it survive restarts

```powershell
wscript.exe start_background.vbs     # starts the bot in the background
.\install_autostart.bat              # starts it when you sign in to Windows
.\install_watchdog.bat               # restarts it within 5 minutes if it crashes
```

Both run only once someone is signed in. For recovery from a power cut, set the BIOS to
**power on when AC power returns**, and let Windows sign in automatically.

`check_status.bat` shows the bot's processes and the end of its log; `stop.bat` stops the bot
and its running jobs, and nothing else. Then send the bot **`/stats`**: it must answer with
live numbers, not demo data.

---

## 10. Retire the old PC

**Never run two bots at once.** Two copies fight over the Telegram token and both write the
same Google Sheets. On the old PC, in this order, so the watchdog cannot restart it:

```powershell
schtasks /Delete /TN "HangeulBotWatchdog" /F
Remove-Item "$([Environment]::GetFolderPath('Startup'))\HangeulBot.lnk"
.\stop.bat
```

Then check that no `python -m src.*` job is still running, because a sync in progress keeps
writing after the bot has stopped. Archive `data\verification\results.json` before wiping
anything.

---

## 11. From then on it runs itself

| When (Asia/Dhaka) | Job |
|---|---|
| every 15 min | Portal sync: sheets, newly verified students' documents, their check |
| every 30 min | Passport watcher: newly uploaded passports against portal fields |
| 08:30 | Passport issue dates refresh |
| 09:05 | Missing-information report |
| 18:05 | Executive brief |

The 15-minute sync checks at most six students per run, each run a fresh process, so it
never hits the GPU-memory slowdown from section 8.

---

## 12. Things that went wrong in this move, now fixed or known

| What | Status |
|---|---|
| E: paths in 11 files, not 5; launchers tied to Python 3.11 | Fixed: configurable paths, self-locating launchers |
| `rich` and `pypdf` missing from the install list; CPU-only torch trap | Fixed: `requirements.txt`, torch first |
| EasyOCR's first model download crashed on a Windows console | Fixed: the reader is built with `verbose=False` |
| Phase 3 audited 78 of 326 students ("KLP"/"EAP" matched nobody; only page 1 read) | Fixed |
| Two known-false rules gave FAIL | Now FLAG: solvency vs statement date; apostille "one qualification" |
| Empty admin chat ID handed the bot to the first stranger | Fixed: it now refuses everyone |
| One long OCR run slows to a crawl | Known: run in batches (section 8) |
| Passport watcher sends 3 alerts per run and marks the rest sent | Known, left as is: phase 3's CSVs are the full list |
| REST API listens on the whole network with no password | Known, left as is by choice (`API_HOST`) |
| A game on the same GPU slows OCR tenfold and risks out-of-memory | Known: keep games closed during long checks |

Read `HANDOFF.md` before changing any verification rule.
