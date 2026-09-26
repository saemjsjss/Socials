# Moving the system to the new PC

Updated 26 September 2026 — clean-start version.

The new machine rebuilds everything from the portal rather than inheriting this one's
files. **About 440 MB to copy**, then one command that runs the whole cold start.

Portal access stays read-only throughout: GETs and the login, nothing else.

---

## 1. What to copy — and what not to

### Copy this

| From | Size | Why |
|---|---|---|
| `E:\BOT` | ~100 MB | The system itself |
| `E:\KONYANG DOCUMENTS` | 340 MB | **Cannot be re-downloaded — see below** |

Inside `E:\BOT`, skip `passports\` (113 MB) and `passports_001\` (27 MB). They are
scratch copies the passport watcher rebuilds by itself.

**Hidden files that must come across.** A folder copy that skips dotfiles leaves you with
no portal login, no Telegram token and no Google access:

- `.env` — portal login, Telegram token, Gmail password
- `token.json`, `credentials.json` — the Google login
- `.agents\rules\` — the operational guardrails

### Do not copy

`E:\VERIFIED STUDENT DOCUMENTS` (1.23 GB) — the new PC downloads it fresh from the portal
in phase 3. That is the point of the clean start.

### Why Konyang is different

`E:\KONYANG DOCUMENTS` holds 48 students. **Eleven of them are no longer
document-verified on the portal** — checked live, all eleven are absent from the current
list of 145:

> ANJUM MST SUBORNA ANJUM · FARUK MUNTASIR RAHMAN · HAIDER MD SHAFIQUL ·
> HARUN MD ALTAFUR · IDRIS MD ISHTIAQ · KHALIL MD SHAHJALAL · MD TOWFIQ ARMAN ·
> MRIDHA TAUFIQUL · SOHEL MD SAIFAN BHUIYAN · TAREK MOSHIUR HALIM · TUMPA RUMANA ANJUM

Phase 3 downloads only what the portal marks verified today, so it will not bring them
back. Copy the folder or those documents are gone.

### Leave `data\` behind

`E:\BOT\data\` holds caches: extracted OCR text, verification results, sheet state and
passport issue dates. **Do not copy it.** The new machine rebuilds all of it, which is the
point of a fresh start — it also means nothing stale follows the system across.

Two consequences to expect:

- Phase 5 does full OCR on every document: **2–3 hours**, not minutes.
- `data\windows-ca.pem` goes too. That file is this machine's certificate list and should
  not be reused anyway; if the new PC needs one, generate its own in step 5.

`token.json`, `credentials.json` and `.env` sit in `E:\BOT` itself, not in `data\`, so
they come across with the folder.

---

## 2. Install Python 3.11

Use **Python 3.11** — not 3.12 or 3.13. EasyOCR and PyTorch are pinned to what works
here. Tick **"Add python.exe to PATH"**.

Also install the **Microsoft Visual C++ Redistributable (x64)**. Without it `pyzbar`
fails to load, and the symptom is "no QR code found" rather than an error — which would
quietly disable the apostille check.

---

## 3. Install the packages

In PowerShell, inside the copied `BOT` folder:

```powershell
python -m pip install --upgrade pip
python -m pip install easyocr pymupdf opencv-python-headless pyzbar pillow openpyxl `
    httpx beautifulsoup4 python-telegram-bot apscheduler pandas `
    google-api-python-client google-auth-oauthlib google-auth-httplib2 `
    fastapi uvicorn pydantic-settings python-dotenv
```

Then PyTorch for the new PC's graphics card. This machine uses CUDA 12.8:

```powershell
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

For a 40-series or older card use `cu121`. Then check:

```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

**`cuda.is_available()` must print `True`** — otherwise OCR runs on the CPU and phase 4
takes ten times longer.

### Versions working here

```
easyocr 1.7.2       torch 2.11.0+cu128     pymupdf 1.28.2
opencv-python-headless 5.0.0.93            pyzbar 0.1.9
pillow 12.3.0       openpyxl 3.1.5         httpx 0.28.1
python-telegram-bot 22.8                   apscheduler 3.11.3
google-api-python-client 2.200.0           google-auth-oauthlib 1.4.1
beautifulsoup4 4.15.0                      pandas 3.0.5
```

---

## 4. Install Ollama

Point it at a data drive **before** pulling the model, or it fills the system drive the
way this machine's filled up:

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "E:\ollama", "User")
ollama pull qwen2.5:7b
```

---

## 5. Check the SSL certificates

On this PC, antivirus or the ISP intercepts HTTPS, so Python cannot verify any
certificate and every network call fails silently. Test the new PC first:

```powershell
python -c "import httpx; print(httpx.get('https://oauth2.googleapis.com/token', timeout=20).status_code)"
```

- **Prints a number** (404 is fine) → nothing to do, skip this step.
- **`CERTIFICATE_VERIFY_FAILED`** → the new PC has the same interception. Generate its own
  certificate list, then append it to certifi's bundle:

```powershell
powershell -ExecutionPolicy Bypass -File tools\export_windows_ca.ps1
```

```powershell
python -c "import certifi,shutil,pathlib; b=pathlib.Path(certifi.where()); shutil.copy2(b, b.with_suffix('.pem.original')); b.write_text(b.read_text(encoding='utf-8') + open(r'data\windows-ca.pem', encoding='utf-8').read(), encoding='utf-8'); print('done')"
```

`src\__init__.py` picks up that file automatically. **Never run
`pip install --upgrade certifi` afterwards** — it replaces the bundle and everything
breaks again, pip included.

---

## 6. If the drive letters differ

Five files carry absolute paths. Keeping `E:` avoids this entirely — create an E:
partition, or map a folder with `subst`.

| File | Paths |
|---|---|
| `src\verify\doc_verifier.py` | `E:\VERIFIED STUDENT DOCUMENTS`, `E:\KONYANG DOCUMENTS`, `E:\BOT\data\verification` |
| `src\verify\auto_verify.py` | `E:\BOT\data\verification` |
| `src\verify\page_checks.py` | `E:\BOT\data\verification\apostille.json` |
| `src\sheets\verified_docs.py` | `E:\VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB` |
| `src\sheets\auto_sync.py` | `E:\VERIFIED STUDENT DOCUMENTS` |

---

## 7. Sign in to Google

```powershell
python -m src.sheets.progress_builder --auth
```

A browser opens — sign in as **rahmansaem@gmail.com** and approve Drive and Sheets. The
copied `token.json` may survive the move, but re-authorising takes a minute and removes
the doubt.

**While you are in Google Cloud Console, check the OAuth app is Published, not in
"Testing".** In testing mode the login expires every 7 days. That is what caused the
nine-hour outage on 26 September.

---

## 8. Clear the old sheets, then cold start

If you are starting the progress sheets fresh, delete their contents in Drive first
(main tabs only — leave your university sub-tabs alone).

Then one command does everything:

```powershell
python bootstrap.py
```

| Phase | What it does | Roughly |
|---|---|---|
| 1 | Builds every program + intake sheet from the portal | minutes |
| 2 | Reads passport issue dates — the one field the CSV export omits | ~20 min |
| 3 | Passport audit — each passport scan against the portal record | ~1 hour |
| 4 | Downloads the **document-verified** students' files only | 1–2 hours |
| 5 | OCR every document, then compare the sheet's fields against them | 2–3 hours |
| 6 | Hands over to the bot | — |

It is resumable. If something stops it:

```powershell
python bootstrap.py --from 5      # carry on
python bootstrap.py --only 2      # one phase
python bootstrap.py --plan        # show what would run
```

Start it in the evening. Phases 4 and 5 together are four hours or more on a cold
machine, because nothing is cached.

---

## 9. Make it survive restarts

```powershell
.\install_autostart.bat     # starts the bot when you log in
.\install_watchdog.bat      # restarts it within 5 minutes if it crashes
```

Confirm the bot answers `/stats` on Telegram before moving on.

---

## 10. Retire this PC — carefully

**Never run both at once.** Two bots on one Telegram token fight over messages, and two
syncs write to the same Google Sheets.

Once the new PC has completed a sync and answers on Telegram:

```powershell
# on the OLD pc
.\stop.bat
schtasks /Delete /TN "HangeulBotWatchdog" /F
Remove-Item "$([Environment]::GetFolderPath('Startup'))\HangeulBot.lnk"
```

Keep this machine's files for a week before deleting anything.

---

## 11. From then on it runs itself

Every 15 minutes the bot compares the live portal against what it last saw and acts only
on differences:

- a student added → appears on their sheet
- a field edited → that sheet rebuilt, the field named in Telegram
- a student newly document-verified → documents downloaded and checked
- a verified student's documents replaced → downloaded again and re-checked
- someone types on a main tab → restored from the portal
- nothing changed → silent

Plus passport issue dates at 08:30, the missing-information report at 09:05, the
executive brief at 18:05, and the passport watcher every 30 minutes.

**Still needs a person:** three students have no intake set on the portal and cannot be
placed until they do; the apostille QR lookups need Playwright before that check runs on
more than a handful of students.

Read `HANDOFF.md` before changing any verification rule.
