# 03b: File map of the scraper, dates, config, LLM and REST API

**What's in this file:** a file-by-file map of `src\config.py` (and the root `config.py` copy, including the five Supabase settings), `src\dates.py`, `src\scraper\` (`client.py` with `read_consult_performance`; `parsers.py` with the Cloudflare e-mail decoder `decode_cf_emails` applied at every soup and the Consultant Performance parser `parse_consult_performance`; `ocr_validator.py`; `mock_data.py`), `src\llm\` (`ollama_client.py`, `prompts.py`), `src\api\` (the FastAPI app, its routes and schemas), `src\__init__.py` (the CA hook and the log redactor, section 11) and `src\net_fix.py` (the Telegram DNS workaround, section 13). For every file you get its purpose, exact signatures, constants, regexes and CSS selectors, what it reads and writes, who calls it, how it fails, and its history.
**Source:** `C:\Hangeul\BOT` at `main` = `8317741` (48 commits). Line numbers are `path:line` at that commit. Pack written 29 September 2026 from `c17d887`; refreshed 30 September 2026 (Asia/Dhaka) at `8317741`.
**Siblings:** the Telegram commands and scheduled jobs that call these modules are in [Commands](05_TELEGRAM_COMMANDS_AND_JOBS.md). The other file maps are [03a (`src\bot\`, including `performance.py`)](03a_FILES_src_bot.md), [03c (`src\sheets\`, `src\verify\`, root scripts)](03c_FILES_sheets_verify_root_scripts.md) and [03d (`src\cloud\`, the Supabase publish layer)](03d_FILES_src_cloud.md); Supabase end to end is in [13](13_SUPABASE_PUBLISHING.md), the portal page by page in [04](04_PORTAL_INTEGRATION.md), the LLM rules in [06](06_LLM_AND_JENNIE_VOICE.md), the dated story in [08](08_HISTORY_STAGE_BY_STAGE.md), the tests in [10](10_TESTS_AND_VERIFICATION.md), the system view in [01_ARCHITECTURE.md](01_ARCHITECTURE.md) and the pack index in [00_INDEX.md](00_INDEX.md). Secret values are never written here; they appear as "value in secrets/bot.env (KEY_NAME)".

**What changed in this group between `c17d887` and `8317741`** (details in each section):
- `config.py` (both copies, 36ae72e): five new settings, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `CLOUD_PUBLISH_ENABLED`, `CLOUD_EMBED_MODEL`, `CLOUD_EMBED_REVISION` (§1.3).
- `client.py`: `read_consult_performance(period)` and the constants `PERFORMANCE_PAGE` / `PERFORMANCE_PERIODS` (ce23535); `get_admitted_students` also returns `listed` and `dashboard` (2b6798f); both `student_edit.php` soups are decoded (9ead47d). The public `ensure_session()`, `read_consultation_range()` and `read_verified_window()` of the first, self-computed performance report (bbd8f98, a721066) were **removed** in ce23535 (§3.10).
- `parsers.py`: `decode_cf_emails` / `_cf_address` replace `_decode_cf_emails` / `_cf_email`, and every `BeautifulSoup(...)` in `src\` is wrapped in it, pinned by a source test (9ead47d, e5e532e; §4.1.1); `parse_consult_performance` and `PerformanceLayoutError` (ce23535, 314afdb; §4.12); a consultation row's own portal `id` (3caa393).
- `src\__init__.py` (36ae72e): `redact()` also hides Supabase keys, on more loggers (§11).
- `src\dates.py`, `src\llm\`, `src\api\`, `ocr_validator.py`, `mock_data.py`, `net_fix.py`: **unchanged**; only their callers and the operating state moved (§2.5, §8).

---

## 0. The files in scope

All 19 tracked files matching `config.py`, `src/config.py`, `src/dates.py`, `src/scraper/*`, `src/llm/*` and `src/api/**` (checked against `git ls-files`):

| File | Lines | Role | Added | Last changed |
|---|---|---|---|---|
| `config.py` (root) | 147 | Staging copy of `src\config.py`, byte-identical. Only `apply_bot_update.bat` uses it. | 366dec0 | 36ae72e |
| `src\config.py` | 147 | All settings (pydantic-settings, reads `.env`), `BOT_ROOT`, and the folder helpers | 366dec0 | 36ae72e |
| `src\dates.py` | 259 | Strict parsing of user dates, and portal date stamps | e0d47ab | e0d47ab |
| `src\scraper\__init__.py` | 1 | Docstring only | 366dec0 | 366dec0 |
| `src\scraper\client.py` | 778 | `HangeulAdminClient`: the portal session and every portal read; the singleton `admin_client` | 366dec0 | e5e532e (merge; last own changes ce23535 on main, 9ead47d on the cloud branch) |
| `src\scraper\parsers.py` | 1351 | Pure HTML parsers, one or more per portal page, plus the Cloudflare e-mail decoder | 366dec0 | e5e532e (merge; last own changes 314afdb on main, 9ead47d on the cloud branch) |
| `src\scraper\ocr_validator.py` | 897 | Passport-scan OCR (EasyOCR on the CPU), MRZ check digits, portal-vs-scan verdicts | 366dec0 | 40da0e6 |
| `src\scraper\mock_data.py` | 209 | Made-up demo data used when `MOCK_MODE=true` | 366dec0 | 366dec0 |
| `src\llm\__init__.py` | 1 | Docstring only | 366dec0 | 366dec0 |
| `src\llm\ollama_client.py` | 274 | `OllamaClient`: the local LLM over HTTP; the singleton `ollama_client` | 366dec0 | c17d887 |
| `src\llm\prompts.py` | 20 | The fact-picking system prompt and its JSON schema | 366dec0 | 7f42ad0 |
| `src\api\__init__.py` | 1 | Docstring only | 366dec0 | 366dec0 |
| `src\api\main.py` | 69 | The FastAPI `app`: CORS, routers, `/` and `/healthz` | 366dec0 | 366dec0 |
| `src\api\routes\__init__.py` | 1 | Docstring only | 366dec0 | 366dec0 |
| `src\api\routes\auth.py` | 27 | `/api/auth/csrf`, `/api/auth/login`, `/api/auth/status` | 366dec0 | 366dec0 |
| `src\api\routes\dashboard.py` | 16 | `/api/dashboard/stats`, `/api/dashboard/alerts` | 366dec0 | 366dec0 |
| `src\api\routes\applications.py` | 26 | `/api/applications`, `/api/applications/inquiries`, `/api/applications/consultations` | 366dec0 | 366dec0 |
| `src\api\routes\crawler.py` | 12 | `/api/crawler/parse-page` | 366dec0 | 366dec0 |
| `src\api\schemas.py` | 76 | Pydantic request and response models (3 are used, 7 are unused) | 366dec0 | 366dec0 |

`src\__init__.py` is not in this group, but every module here is imported through it. Its side effects are summarised in section 11.

One more tracked file is mapped here because no other file map covers it: `src\net_fix.py` (105 lines, added 366dec0, unchanged since), the in-process Telegram DNS workaround that `run.py` calls at start-up. It is in [section 13](#13-srcnet_fixpy-the-telegram-dns-workaround).

**Dependency direction:** `config` ← `dates` ← `parsers` ← `client` → `ocr_validator`, `mock_data`. `config` ← `prompts` ← `ollama_client`. `api` → `client`. Nothing in this group imports `src\bot\`, `src\sheets\`, `src\verify\` or `src\cloud\` (the word `src.cloud` appears only in comments of `parsers.py:70` and `config.py:82`). The other direction is new and heavy: `src\cloud\` builds its records from these parsers' output and reads the portal through `HangeulAdminClient` ([03d](03d_FILES_src_cloud.md)). The parsers are pure functions (HTML in, dicts out) and never do I/O; `client.py` now imports `_label_key`, `decode_cf_emails`, `parse_consult_performance` and `PerformanceLayoutError` from them (`client.py:12-37`).

**Pinned libraries** (`requirements.txt`): httpx 0.28.1, beautifulsoup4 4.15.0 (the built-in `html.parser` is used, not lxml), pydantic 2.13.5, pydantic-settings 2.15.0, fastapi 0.141.1, uvicorn 0.54.0, easyocr 1.7.2, opencv-python-headless 5.0.0.93, pypdf 6.19.0, tzdata 2026.4 (needed for `ZoneInfo("Asia/Dhaka")` on Windows), torch 2.11.0+cu128 and torchvision 0.26.0+cu128. Install torch first, from the cu128 index, or easyocr pulls in a CPU-only torch. New in 36ae72e, for `src\cloud\embed.py` only (nothing in this group imports them): sentence-transformers 6.1.0 and transformers 5.17.0 (pinned because transformers 5 loads gte-small as float16 unless `embed.py` asks for float32); they pull huggingface_hub, tokenizers, safetensors and scikit-learn. The model cache is `%USERPROFILE%\.cache\huggingface` (`hub\models--thenlper--gte-small`).

---

## 1. `src\config.py` and the root `config.py`

### 1.1 Purpose
It is the single place where settings are defined. One `Settings(BaseSettings)` instance, `settings`, is created at import time (`src/config.py:147`). It reads `C:\Hangeul\BOT\.env`, with UTF-8 encoding and `extra="ignore"` (`:141-145`). pydantic-settings resolves each value in this order: constructor arguments, then OS environment variables, then `.env`, then the code default. So a Windows environment variable of the same name overrides `.env`, and a `.env` key that is not a field (such as `SUPABASE_ACCESS_TOKEN`) is ignored.

**Pitfall (checked with the venv's pydantic-settings 2.15.0):** an **empty** value for a `bool` field, e.g. a line `CLOUD_PUBLISH_ENABLED=`, is not "unset": it raises `ValidationError ... Input should be a valid boolean, unable to interpret input [type=bool_parsing, input_value='']` at `import src.config`, so the bot does not start at all. Write `true` / `false`, or leave the line out.

### 1.2 Module-level names
| Name | Line | Value / contract |
|---|---|---|
| `BOT_ROOT` | `:6` | `Path(__file__).resolve().parent.parent`, i.e. `C:\Hangeul\BOT` (the folder that holds `run.py` and `.env`). It is used by `client.py` (passports folder), `scheduler.py`, `voice.py`, `auto_sync.py`, `missing_report.py`, `passport_issue.py`, `progress_builder.py` (both copies) and, new, `src\cloud\backfill.py`, `handoff.py`, `publish.py` and `student_index.py` (`data\cloud_state.json`, `data\cloud\`). |
| `ENV_PATH` | `:7` | `BOT_ROOT / ".env"` |
| `_folder(value: str, default: Path) -> Path` | `:10` | An empty value gives `default`. An absolute path is used as it is. A relative path is taken from `BOT_ROOT`. |

### 1.3 Every setting
"Value on this PC" comes from `C:\Hangeul\BOT\.env`, reading only non-secret keys. "not set" means the code default applies.

| Key | Type | Code default | Value on this PC | Meaning | Read by |
|---|---|---|---|---|---|
| `MOCK_MODE` | bool | **`True`** | `false` | True replaces every portal read with `mock_data.py` (made-up demo data). A missing line in `.env` therefore means fake data. In mock mode `src\cloud\` publishes nothing (`full_picture.py` checks `settings.MOCK_MODE`; the command hooks and bot jobs check `admin_client.mock_mode`), and `read_consult_performance` refuses (§3.8). | client.py, api/main.py, run.py, telegram_bot.py, audit_program.py, src\cloud\full_picture.py |
| `HANGEUL_BASE_URL` | str | `https://hangeul.com.bd/admin` | same | Portal root; every path is appended after `/` | client.py, api/main.py, telegram_bot.py |
| `HANGEUL_USERNAME` | str | `"admin"` (placeholder) | value in secrets/bot.env (HANGEUL_USERNAME) | Portal login | client.py only |
| `HANGEUL_PASSWORD` | str | `"password"` (placeholder) | value in secrets/bot.env (HANGEUL_PASSWORD) | Portal login | client.py only |
| `OLLAMA_BASE_URL` | str | `http://127.0.0.1:11434` | same | Ollama server. Use 127.0.0.1, not `localhost`: on this PC, localhost tries IPv6 first and loses about 2 s per new connection (comment at `:28-30`). | ollama_client.py |
| `OLLAMA_MODEL` | str | `qwen3:4b-instruct` | `qwen3:4b-instruct` | One model for everything: typed questions, the brief summary line, e-mails, voice | ollama_client, run.py, scheduler, telegram_bot, voice |
| `OLLAMA_NUM_CTX` | int | `3072` | not set (3072) | The context window of **every** call. Ollama reloads the model when `num_ctx` differs from the loaded copy, so all calls use one value. Measured: 2048 gives 2.68 GiB and 3072 gives 2.82 GiB. The brief's prompt (about 1,300-1,600 tokens) needs 3072. | ollama_client.py |
| `TELEGRAM_BOT_TOKEN` | str | `""` | value in secrets/bot.env (TELEGRAM_BOT_TOKEN) | Bot token; empty means no Telegram, API only | run.py, telegram_bot, auto_sync, missing_report |
| `TELEGRAM_ADMIN_CHAT_ID` | str | `""` | value in secrets/bot.env (TELEGRAM_ADMIN_CHAT_ID) (the owner's Telegram user id; an identifier, not a secret, as [secrets/README §3](secrets/README.md) says, but kept out of the shareable documents) | The primary admin. Receives the daily brief and the passport alerts. Empty means the bot refuses everyone (c5c1a7c). | telegram_bot, scheduler |
| `TELEGRAM_AUTHORIZED_CHAT_IDS` | str | `""` | not set | Extra allowed user IDs, separated by commas, semicolons or spaces | telegram_bot (via `authorized_ids()`) |
| `TELEGRAM_BRIEF_CHAT_IDS` | str | `""` | not set | Who gets the 15-minute sync summaries and the 09:05 missing-info report. Empty means every authorised user. | auto_sync, missing_report (via `brief_recipient_ids()`) |
| `DAILY_REPORT_TIME` | str | `"18:05"` | `18:05` | Time of the daily brief, as HH:MM in `REPORT_TIMEZONE` | scheduler |
| `REPORT_TIMEZONE` | str | `"Asia/Dhaka"` | `Asia/Dhaka` | The zone of every "today" (`dates.local_today`) and of the schedules | dates, brief, scheduler, telegram_bot, voice, src\cloud\records.py (`:68`, the zone of every `read_at`) |
| `ENABLE_SCHEDULED_REPORTS` | bool | `True` | `true` | Master switch for the scheduled jobs | scheduler |
| `GMAIL_ADDRESS` | str | `""` | value in secrets/bot.env (GMAIL_ADDRESS) | Sender for `/sendmail` | telegram_bot |
| `GMAIL_APP_PASSWORD` | str | `""` | value in secrets/bot.env (GMAIL_APP_PASSWORD) | A 16-character Google app password, not the account password | telegram_bot |
| `JENNIE_VOICE_ENABLED` | bool | `False` | `false` (the owner turned the voice off on 28 Sep 17:08; still off at 8317741: the `JennieVoiceWatchdog` scheduled task is Disabled and `JennieVoice.lnk` sits in `C:\Hangeul\JARVIS\disabled`, so the voice service does not start) | Registers the voice-note handler and pins the LLM in VRAM | telegram_bot, scheduler, ollama_client |
| `JENNIE_VOICE_URL` | str | `http://127.0.0.1:8765` | not set | The local voice service (FastAPI, faster-whisper + CosyVoice2). It must be this PC. | telegram_bot, voice |
| `JENNIE_SPOKEN_BRIEF` | bool | `True` | `false` | Also sends a spoken brief; needs voice on | scheduler |
| `BRAIN_ALWAYS_LOADED` | bool | `False` | not set | Pins the LLM in VRAM even with voice off | ollama_client (`brain_pinned`) |
| `BRAIN_IDLE_UNLOAD` | str | `"5m"` | not set | The Ollama `keep_alive` when the model is not pinned | ollama_client (`keep_alive`) |
| `API_HOST` | str | `"0.0.0.0"` | `0.0.0.0` | Bind address of uvicorn. The owner chose to keep 0.0.0.0 (migration decision 9). | run.py |
| `API_PORT` | int | `8000` | `8000` | REST API port | run.py |
| `SUPABASE_URL` | str | `""` (`:86`) | `https://dcbcbpwpmdtaanboetiz.supabase.co` (project ref `dcbcbpwpmdtaanboetiz`, the Jeannie project; not a secret) | The Supabase project root. `publish._client()` uses it as `base_url` (trailing `/` stripped); a run refuses anything that does not start with `https://` ("SUPABASE_URL is not an https:// address", `publish.py:405`). | src\cloud\publish.py (`enabled()`, `_client()`, `_start`), backfill.py, handoff.py, command_hooks.py (via `enabled()`) |
| `SUPABASE_SECRET_KEY` | str | `""` (`:87`) | value in secrets/bot.env (SUPABASE_SECRET_KEY) | The project's **secret** API key (`sb_secret_...`), never the publishable key. Sent as both `apikey: <key>` and `Authorization: Bearer <key>` on every call (`publish.py:342-347`); never printed or logged (`src\__init__.redact` hides `sb_secret_...`, §11). | src\cloud\publish.py only |
| `CLOUD_PUBLISH_ENABLED` | bool | `False` (`:88`) | `true` since 30 Sep 22:27 (`.env` line 43; before that the line was absent and the real backfill ran with it set in that one process's environment only) | Master switch of the Supabase layer. Publishing runs only when **all three** of `SUPABASE_URL`, `SUPABASE_SECRET_KEY` and this are set (`publish.enabled()`, `publish.py:103-107`); otherwise every hook does nothing (no file, no process, no request). A Supabase failure is one log line and never delays Drive, Sheets or Telegram. Never write it empty (see the pitfall in §1.1). `tests\conftest.py` forces all three off for every test. | src\cloud\publish.py (and everything that asks `enabled()`) |
| `CLOUD_EMBED_MODEL` | str | `"thenlper/gte-small"` (`:91`) | not set (default) | The embedding model (384 dimensions, mean pooling, L2-normalised, float32, on the CPU). Every vector in Supabase must come from exactly this model, the one Jeannie embeds her questions with. | src\cloud\embed.py (`model_id()` `:57`, `GteSmall` `:202`) |
| `CLOUD_EMBED_REVISION` | str | `"17e1f347d17fe144873b1201da91788898c639cd"` (`:92`) | not set (default) | The pinned Hugging Face revision of that model. Each chunk carries `embed_model = "thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd"`. Change both only when Jeannie changes her model too (`.env.example:112-113`). | src\cloud\embed.py (`:57`, `:203`) |
| `DOCS_ROOT` | str | `""` | not set, so `C:\Hangeul\VERIFIED STUDENT DOCUMENTS` | Downloaded documents: `<PROGRAM>\<NAME (PASSPORT)>\` | `docs_root()` |
| `DOCS_ORIGINALS_ROOT` | str | `""` | not set, so `C:\Hangeul\VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB` | Untouched originals of files shrunk below 2 MB | `docs_originals_root()` |
| `KONYANG_ROOT` | str | `""` | not set, so `C:\Hangeul\KONYANG DOCUMENTS` (absent, skipped) | Older Konyang downloads | `konyang_root()` |
| `VERIFICATION_DIR` | str | `""` | not set, so `C:\Hangeul\BOT\data\verification` | OCR text cache, `results.json`, check reports | `verification_dir()` |

These are **not** Settings fields. `SUPABASE_ACCESS_TOKEN` (the Supabase CLI's personal access token, `sbp_...`, value in secrets/bot.env (SUPABASE_ACCESS_TOKEN)) is a line in `.env` (line 42) that pydantic ignores (`extra="ignore"`): no bot code reads it. It exists only so the Supabase CLI (v2.118.0, `C:\Hangeul\JARVIS\tools\supabase\bin\supabase.exe`) could run `supabase link --project-ref dcbcbpwpmdtaanboetiz` and `supabase db push` from the Jeannie repo `C:\Hangeul\JARVIS\Jeenie-saem-bot` (its 4 files in `supabase\migrations\`); the agent handed it to that process's environment without printing it. It can be deleted from `.env` and revoked when no more migrations are due ([13](13_SUPABASE_PUBLISHING.md)). `CUDA_VISIBLE_DEVICES` is set to `"-1"` by `src\cloud\embed.prepare_process()` in the embedding processes only, never in `.env` ([03d](03d_FILES_src_cloud.md)). `TELEGRAM_DNS_FIX` and `TELEGRAM_API_IP` are read from the Windows environment (`os.environ`) by `src\net_fix.py` ([section 13](#13-srcnet_fixpy-the-telegram-dns-workaround)); putting them in `.env` has no effect. `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` are Windows user variables read by the Ollama server. Both are set on this PC. What they save, measured two ways: on the **live** instance (`/api/ps`, the figure used in [02](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md), [06](06_LLM_AND_JENNIE_VOICE.md) and [09](09_BLUEPRINT_RULES_AND_LESSONS.md)) the model at `num_ctx` 3072 went from **2.82 GiB to 2.62 GiB** (about 0.2 GiB); the config comment (`src\config.py:38-40`) quotes an earlier test on a side Ollama instance on `127.0.0.1:11435`, **3.18 GB → 2.81 GB** (about 0.35 GiB). Both agree on the "after" figure (2.81 GB = 2.62 GiB); only the "before" differs.

### 1.4 Methods
| Method | Line | Contract |
|---|---|---|
| `Settings.docs_root() -> Path` | `:101` | `_folder(DOCS_ROOT, BOT_ROOT.parent / "VERIFIED STUDENT DOCUMENTS")` |
| `Settings.docs_originals_root() -> Path` | `:104` | `_folder(DOCS_ORIGINALS_ROOT, BOT_ROOT.parent / "VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB")` |
| `Settings.konyang_root() -> Path` | `:108` | `_folder(KONYANG_ROOT, BOT_ROOT.parent / "KONYANG DOCUMENTS")` |
| `Settings.verification_dir() -> Path` | `:111` | `_folder(VERIFICATION_DIR, BOT_ROOT / "data" / "verification")` |
| `Settings.authorized_ids() -> set` | `:114` | `{TELEGRAM_ADMIN_CHAT_ID}` plus the IDs in `TELEGRAM_AUTHORIZED_CHAT_IDS`, split after `;` and spaces are turned into `,`. Values are strings. |
| `Settings.brief_recipient_ids() -> set` | `:128` | An empty `TELEGRAM_BRIEF_CHAT_IDS` returns `authorized_ids()`; otherwise only the listed IDs |

The Supabase block (`:82-92`) sits between `API_PORT` and the folder settings, with this comment: it publishes only when all three switches are set, a failure is one log line and never touches Drive, Sheets or Telegram, the secret key is never printed or logged, and the CLI's access token is not read here. There is no helper method for it; `src\cloud\publish.enabled()` is the one test of "publishing is on".

### 1.5 The root `config.py`
`diff config.py src/config.py` shows no difference at 8317741. The two files have changed together in every commit (366dec0, 4154aa5, d7a5817, d9bbecc, c17d887, 36ae72e; 4154aa5 says "The root staging copies stay byte-identical to src/"). Nothing imports it: `git grep "from config \|import config"` finds nothing. Its only consumer is `apply_bot_update.bat`, which copies `config.py` (from the bot folder, or failing that the newest `%USERPROFILE%\Downloads\config*.py`) over `src\config.py`, and a root or downloaded `telegram_bot.py` over `src\bot\telegram_bot.py`, then clears `__pycache__` and restarts. **Rule for a rebuild:** keep the two copies identical, or the next "apply update" overwrites `src\config.py` with the stale one. If the root copy were ever imported directly, `BOT_ROOT` would resolve to `C:\Hangeul` and `.env` would be looked for at `C:\Hangeul\.env`.

### 1.6 History
- 366dec0 (baseline): 78 lines, `OLLAMA_BASE_URL=http://localhost:11434`, `OLLAMA_MODEL=qwen2.5:7b`, no path settings.
- 4154aa5: added `BOT_ROOT`, `_folder` and the four folder settings, because `E:\` paths had been written into the code and the new PC has only `C:`.
- d7a5817: `JENNIE_VOICE_ENABLED`, `JENNIE_VOICE_URL`, `JENNIE_SPOKEN_BRIEF`.
- d9bbecc: 127.0.0.1, `qwen3:4b-instruct`, `OLLAMA_NUM_CTX=3072`, with the measured-VRAM comment.
- c17d887: `BRAIN_ALWAYS_LOADED` and `BRAIN_IDLE_UNLOAD` (the model is loaded on demand while voice is off).
- 36ae72e (29 Sep 11:28, merged to main 30 Sep): `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `CLOUD_PUBLISH_ENABLED`, `CLOUD_EMBED_MODEL`, `CLOUD_EMBED_REVISION` (147 lines), with `.env.example:106-118` documenting them. The owner's spec is `C:\Users\User\Downloads\hangeul-bot-prompt.md` (decisions D1-D13: full student data in Supabase, the `hg_*` tables owned by the Jeannie repo); see [13](13_SUPABASE_PUBLISHING.md).

---

## 2. `src\dates.py`: strict dates

### 2.1 Purpose
There is one strict reader for dates typed by users, and one matcher for the portal's yearless stamps. Everything is pure and offline. "Today" means `local_today()` in `settings.REPORT_TIMEZONE`. **Design rule:** text that names no date, two dates, or an impossible date gives `None` plus a reason. It never gives today or any other stand-in day. Before e0d47ab, `parsers.normalize_target_date` fell back to returning the raw text, and relative words used the PC's `datetime.now()`. The audit also found that `8 Sep` matched inside `18 Sep` and `28 Sep`.

### 2.2 Constants and regexes
| Name | Line | Content |
|---|---|---|
| `MONTHS` | `:27` | `{"jan":1,"january":1,...,"sep":9,"sept":9,"september":9,...,"dec":12,"december":12}` |
| `MONTH_NAMES` | `:33` | `("January", ..., "December")` (used by `voice.py`) |
| `_MONTH` | `:36` | Alternation of the `MONTHS` keys, longest first, so `september` is never read as `sep` + `tember` |
| `_ORD` | `:37` | `(?:st\|nd\|rd\|th)?` |
| `_YEAR_AFTER_MONTH` | `:38` | Optional `,? YEAR` that is not followed by a digit or `:`, and not followed by another month (so a second date's day is not taken as a year) |
| `_USER_DATE_RE` | `:40-56` | Named alternatives: `iy/im/id` = ISO `2026-09-08` or `2026/09/08`. `nd/nm/ny` = day-first `08/09/2026`, `8-9-2026`, `8.9.26`. `sd/sm` = `08/09` (slash only, this year; `5.5` and `1-2` are not dates). `dd/dm/dy` = `8 Sep`, `8th of September 2026`, `8Sep`. `mm/md/my` = `Sep 8`, `September 8th, 2026`. `dby` = day before yesterday; `yday` = yesterday('s); `tmrw` = tomorrow('s); `tday` = today('s) or tonight. Guards: `(?<![\w/.:-])` before numbers and `(?![\w/.:-])` after them. Month names match only as whole words (`\b`). |
| `_HINT_MONTH` | `:60` | Month alternation without `may`, so "may I see" is not a date |
| `_DATE_HINT_RE` | `:61` | A digit, a month, a weekday name, or `weeks?\|months?\|years?\|ago\|last\|previous\|next\|tomorrow\|fortnight` |
| `_STAMP_RE` | `:191` | `(?<![\w/.:-])(?P<d>\d{1,2})\s+(?P<m>MONTH)\b\.?(?:,?\s+(?P<y>\d{4})(?![\d:]))?(?:,?\s+(?P<t>\d{1,2}:\d{2}))?` (case-insensitive) |

**Verbatim source, `src\dates.py:27-65`** (the core of rules R3 and R4 in [09](09_BLUEPRINT_RULES_AND_LESSONS.md); copy it exactly, the escapes matter):

```python
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December")
# Longest first, so "september" is never read as "sep" + "tember".
_MONTH = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + ")"
_ORD = r"(?:st|nd|rd|th)?"
_YEAR_AFTER_MONTH = rf"(?:,?\s*(?P<{{name}}>\d+)(?![\d:])(?!\s*(?:of\s+)?{_MONTH}\b))?"

_USER_DATE_RE = re.compile(
    # 2026-09-08, 2026/09/08
    r"(?<![\w/.-])(?P<iy>\d{4})[-/.](?P<im>\d{1,2})[-/.](?P<id>\d{1,2})(?![\w/.:-])"
    # 08/09/2026, 8-9-2026, 8.9.26 (day first)
    r"|(?<![\w/.:-])(?P<nd>\d{1,2})[-/.](?P<nm>\d{1,2})[-/.](?P<ny>\d{4}|\d{2})(?![\w/.:-])"
    # 08/09 (day first, no year; a slash only, so "5.5" and "1-2" are no dates)
    r"|(?<![\w/.:-])(?P<sd>\d{1,2})/(?P<sm>\d{1,2})(?![\w/.:-])"
    # 8 Sep, 8th of September 2026, 8Sep
    rf"|(?<![\w/.:-])(?P<dd>\d{{1,3}}){_ORD}\s*(?:of\s+)?(?P<dm>{_MONTH})\b\.?"
    + _YEAR_AFTER_MONTH.format(name="dy") +
    # Sep 8, Sep 8th 2026, September 8, 2026
    rf"|\b(?P<mm>{_MONTH})\b\.?\s*(?P<md>\d{{1,3}}){_ORD}(?![\d:])(?![a-z])"
    + _YEAR_AFTER_MONTH.format(name="my") +
    # the relative days
    r"|(?P<dby>\bday\s+before\s+yesterday\b)|(?P<yday>\byesterday'?s?\b)|(?P<tmrw>\btomorrow'?s?\b)"
    r"|(?P<tday>\b(?:today'?s?|tonight)\b)",
    re.I)

# Words that show the text meant a date the parser could not read ("in Sep", "last week", "12th").
# "may" is left out: "may I see..." is no date.
_HINT_MONTH = "(?:" + "|".join(m for m in sorted(MONTHS, key=len, reverse=True) if m != "may") + ")"
_DATE_HINT_RE = re.compile(
    rf"\d|\b{_HINT_MONTH}\b|\b(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?\b"
    r"|\b(?:weeks?|months?|years?|ago|last|previous|next|tomorrow|fortnight)\b",
    re.I)
```

Notes on reading it: `_YEAR_AFTER_MONTH` is a template, formatted twice with `name="dy"` and `name="my"` (the `{{name}}` survives the f-string as `{name}`); the ISO branch's look-behind is `(?<![\w/.-])` (no `:`), every other numeric branch uses `(?<![\w/.:-])`; the day groups allow 3 digits (`\d{1,3}`) so that "123 Sep" is matched and then rejected as an impossible day instead of being read as "23 Sep".

### 2.3 Types
- `_Found(NamedTuple)` (`:67`): `text` (the words as typed), `day: Optional[date]`, `problem: Optional[str]`.
- `Stamp(NamedTuple)` (`:196`): `day: int`, `month: int`, `year: Optional[int]` (`None` means the portal left it out), `time: str` (`"17:19"` or `""`), `text: str` (as the bot shows it, without a year: `"27 Sep, 17:19"`).

### 2.4 Functions
| Signature | Line | Contract |
|---|---|---|
| `local_today() -> date` | `:73` | `datetime.now(ZoneInfo(settings.REPORT_TIMEZONE)).date()`. It imports settings lazily. |
| `_days_in(month, year=None) -> int` | `:79` | February has 29 days when the year is `None` or a leap year |
| `_year(text) -> (year, why)` | `:85` | 2 digits become 20xx; 4 digits must be 1900-2100; otherwise `(None, "“202” is not a year")` |
| `_make(day, month, year, today, prefer_past, words) -> _Found` | `:96` | Validates the day and month. With no year it uses today's year, or last year when `prefer_past` is set and the day is still to come. It re-checks 29 Feb in the chosen year. |
| `_scan(text, today, prefer_past) -> List[_Found]` | `:122` | Every match of `_USER_DATE_RE`, each turned into a `_Found` |
| `parse_user_date(text, today=None, *, prefer_past=False) -> Optional[date]` | `:149` | The one date named, or `None` when there is none, when any match is impossible, or when two different dates are named |
| `user_date_problem(text, today=None, *, prefer_past=False) -> Optional[str]` | `:164` | The reason, for a reply: `"31 Sep: September has 30 days"`, `"it names more than one date (8 Sep, 9 Sep)"`, `"it names a month but no day of it"`, `"there is no month in it"`, `"there is no date in it"`; `None` when the text is readable |
| `has_date_hint(text) -> bool` | `:183` | Whether the text looks date-like, so an unreadable date gets an error instead of today |
| `parse_stamp(text) -> Optional[Stamp]` | `:204` | The first `DD Mon[ YYYY][, HH:MM]`, read on whole tokens; `None` for an impossible day |
| `parse_portal_date(text) -> Optional[date]` | `:218` | The first full `DD Mon YYYY` (e.g. `Applied On 27 Sep 2026, 17:16`). A stamp without a year is skipped. |
| `stamp_on_day(stamp, day, applied=None) -> bool` | `:230` | Day and month must equal `day`'s. A stamp with a year must have `day.year`. A yearless stamp counts only if `applied` is `None` or on or before `day`. |
| `yearless_day_problem(day, today) -> Optional[str]` | `:245` | `"a date in the future"` when `day > today`. Otherwise, if the same day and month has come round again (`day + 1 year <= today`), it returns "the portal writes verification times without a year, so 20 Sep 2025 cannot be told apart from 20 Sep 2026". `None` when the stamp can be trusted. 29 Feb rolls to 1 Mar. |

Results checked offline with `today = 29 Sep 2026`: `"27 Dec"` gives 2026-12-27, or 2025-12-27 with `prefer_past`. `"8.9.26"` gives 2026-09-08. `"5.5"` gives `None` ("there is no month in it"). `"may I see"` gives `None`. `"29 Feb 2026"` gives `None` ("February 2026 has 28 days").

### 2.5 Callers
At 8317741 (`git grep "from src.dates import"`):
- This group: `parsers.py` (`normalize_target_date` `:581`, `target_day` `:805`, `verification` `:826`), `client.py:11` (`parse_portal_date`, `parse_stamp`).
- `src\bot\`: `ask.py:37` (`has_date_hint`, `local_today`, `parse_user_date`, `user_date_problem`, imported **by name**) and `:1015`; `telegram_bot.py` (14 local imports, e.g. `:98`, `:865`, `:1528`, `:1859`); `brief.py:54` (`yearless_day_problem`); `replies.py:151` (`user_date_problem`); `voice.py:585` (`MONTH_NAMES`, `parse_user_date`, `user_date_problem`); new, `performance.py:95` (`_range_dates`: `MONTHS` and `parse_portal_date` read the page's own range, "01 Sep – 30 Sep 2026", for the ⚠️ line when it is not today / this month from the 1st) and `:290` (`local_today`, the Dhaka day that check compares with).
- New, `src\cloud\`: `records.py:112` (`parse_portal_date`), `:567` and `:578` (`parse_stamp`, `yearless_day_problem`: which stamp days a verification batch may claim as complete), `backfill.py:99` (`parse_stamp`), `bot_jobs.py:165` and `:187`, `command_hooks.py:106`, `:258`, `:282` ([03d](03d_FILES_src_cloud.md)).
- `test_verified.py:11`.

Tests: `tests\test_foundation.py` and the suites that use its `portal` fixture. **Pinning "today" in a test:** because `ask.py` binds `local_today` by name at import, patching `src.dates.local_today` alone leaves `ask.local_today` on the real clock; 6 tests therefore passed only on 28 Sep. The fix is test-only: `tests/test_foundation.py:136-140` `pin_today(monkeypatch, today=TODAY)` patches both `dates.local_today` and `ask.local_today`; the `portal` fixture calls it, and `test_freetext.py`, `test_cloud_commands.py` and `test_cloud_performance.py` call it directly (bbd8f98 on main; e5e532e dropped the cloud branch's own copies). The live bot was never wrong. A rebuild should read today through one module attribute (`dates.local_today()`) instead of importing the function by name.

**History:** new in e0d47ab ("Foundation: strict dates..."), unchanged since (still byte-identical at 8317741).

---

## 3. `src\scraper\client.py`: the portal client

### 3.1 Purpose and rules
`HangeulAdminClient` holds the only HTTP session to `hangeul.com.bd/admin`. **Strictly read-only:** it makes GETs, plus exactly one POST, the login (`login.php`). `.agents\rules\hangeul_operational_guardrails.md` §1 forbids any POST, PUT or DELETE and any edit request. The singleton `admin_client = HangeulAdminClient()` (`:778`) is shared by the bot, the in-process scheduler jobs and the REST API, which run in one process and one event loop (see §10.4). Since 8317741 two more kinds of process open **their own** session with the same class: the Supabase backfill (`python -m src.cloud.backfill`, `backfill.py:503-504`: `HangeulAdminClient()`) and the hourly full picture (`python -m src.cloud.full_picture`, `full_picture.py:77`: `class PortalSession(HangeulAdminClient)`, which overrides `portal_get` to latch `down = "the portal did not answer"` after the first unreachable answer, so the pages after it fail at once instead of each timing out). `cloud\sheet_hooks.py:431` calls the static `HangeulAdminClient._profile_fields(html)` on `student_edit.php` pages the sheet jobs already fetched, and feeds the result to `records.student_profile`. The same rules (GET only, the login POST) hold in every one of them. Logger: `hangeul.client`.

**Core design rule (since e0d47ab and f8fefa4):** a read that fails must never look like a figure. Nothing may be reported as a 0, "none" or an empty list. New code raises `PortalUnavailable`, and callers reply "Couldn't read the portal: <reason>". The older methods kept for compatibility return `[]` or `{}` instead (§3.9).

### 3.2 Module constants
| Name | Line | Value | Why |
|---|---|---|---|
| `STUDENTS_PER_PAGE` | `:44` | 50 | students.php page size. A full first page with no pager is an error. |
| `MAX_STUDENT_PAGES` | `:45` | 40 | A cap, so a misread "Page 1 of N" can never loop for long |
| `CONNECT_TIMEOUT` | `:48` | 10.0 s | A host that does not accept the connection is given up on quickly, while a slow page (consult_requests.php is about 2 MB) still gets its full read timeout |
| `CONSULT_LIST_LIMIT` | `:52` | 500 | consult_requests.php lists at most the newest 500 requests |
| `CONSULT_TOTALS_VIEW` | `:53` | `{"status": "file_opened"}` | The lightest tab whose status tabs still count every request |
| `PERFORMANCE_PAGE` | `:57` | `"consult_performance.php"` | The portal's Consultant Performance page (menu Leads > Performance). Also imported by `bot\performance.py:39` (the reply's footer names `consult_performance.php?period=<kind>`); `cloud\records.py:807-809` writes the same path as a literal for a record's source, and imports `PERFORMANCE_PERIODS` (`:834`). |
| `PERFORMANCE_PERIODS` | `:58` | `{"today": "Today", "month": "This Month"}` | The only two periods the bot reads: each key is the page's own `?period=` link value, each value the period the page must then say it shows. The page's other tabs (`week` "This Week", `all` "All Time") and its "Custom range" GET form (`period=custom&from=&to=`) are never used. `bot\performance.KINDS` is `tuple(PERFORMANCE_PERIODS)`. |

(`CONSULT_RANGE_MAX_READS = 16`, added in bbd8f98 for the self-computed performance report, was removed with it in ce23535.)

### 3.3 Errors and helpers
| Name | Line | Contract |
|---|---|---|
| `_error_text(e) -> str` | `:61` | `str(e) or type(e).__name__`, never empty (`str(httpx.ReadTimeout(''))` is `''`) |
| `class PortalUnavailable(RuntimeError)` | `:66` | `__init__(self, reason: str, *, unreachable: bool = False)`. It has `.reason` (a short plain-English reason) and `.unreachable` (True when the portal did not answer at all: a timeout or refused connection). It is raised for a failed login, a page that still ends on `login.php` after a fresh login, HTTP ≥ 400, a timeout or transport error, and an unrecognised layout. |
| `portal_error_reason(e) -> str` | `:80` | For a `PortalUnavailable`: `e.reason`. For `asyncio.TimeoutError` or `httpx.TimeoutException`: `"the portal did not answer in time"`. For `httpx.TransportError`: `"could not connect to the portal (<Type>)"`. Anything else: `"<Type>: <text>"`. Used by `bot\replies.portal_error_reply`, `ask.py`, `performance.py`, `scheduler.py`, `telegram_bot.py`, `missing_report.py`, `stage_report.py`, `audit_program.py`, `download_passports.py`, `inspect_passports.py`, `test_verified.py`, and in `src\cloud\` by `backfill.py`, `bot_jobs.py` and `sheet_hooks.py` (a failed read is named in the run's `failed` list, never published as rows). |
| `_ended_on_login(resp) -> bool` | `:93` | `resp.url.path.rstrip("/").endswith("login.php")`: after following redirects, the session expired |

### 3.4 Construction (`__init__`, `:100`)
- `base_url = settings.HANGEUL_BASE_URL.rstrip("/")`; `username` and `password` come from settings; `mock_mode = settings.MOCK_MODE`.
- Headers: a Chrome 122 on Windows 10 `User-Agent`, `Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8`, `Accept-Language: en-US,en;q=0.9`.
- `httpx.AsyncClient(headers=..., follow_redirects=True, timeout=15.0, verify=False)` (`:113-118`). TLS verification is off (the comment calls it "flexible SSL handling"). **There is no recorded reason** in the repo docs, the commits or the sessions: the setting is inherited from the baseline `366dec0`. The audit and verification scripts copied it. The cookie jar holds the portal session. **Rebuild rule:** use `verify=True`. If a network intercepts TLS (antivirus HTTPS scanning or the ISP, as on 26 Sep 2026), export the Windows root store to `data\windows-ca.pem` with `tools\export_windows_ca.ps1`; the hook in `src\__init__.py` then sets `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `HTTPX_SSL_CERT_FILE` and `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` to it (`os.environ.setdefault`, only when the file exists; on this PC it does not exist, so the hook is inactive) ([section 11](#11-src__init__py-context-for-everything-above), [02 §4](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)).
- `is_authenticated = False`. There is also a lazily created `_profile_cache: dict`.
- `async close()` (`:121`) closes the httpx client. FastAPI's lifespan calls it (§10.1). `sheets\auto_sync._fresh_portal_client()` replaces the singleton with a new `HangeulAdminClient()` between steps, because each step runs its own event loop and closes the client.

### 3.5 Session and login flow
```
portal_get(path, params, timeout)
  └─ _ensure_session(): if not is_authenticated → login(); a login that did not succeed →
       PortalUnavailable("couldn't log in to the portal: <why>", unreachable=<from login>)
  └─ _get_once(path, params, httpx.Timeout(timeout, connect=min(timeout, 10))):
       GET {base_url}/{path} with params URL-encoded by httpx
       httpx.TimeoutException → PortalUnavailable("<path>: the portal did not answer in time (<Type>)", unreachable=True)
       httpx.TransportError  → PortalUnavailable("<path>: could not connect to the portal (<Type>)", unreachable=True)
  └─ ended on login.php? → is_authenticated=False, _ensure_session() again, GET once more;
       still login.php → PortalUnavailable("<path>: the portal kept sending its login page after a fresh login")
  └─ status >= 400 → PortalUnavailable("<path>: the portal answered HTTP <code>")
  └─ return the httpx.Response
```
| Method | Line | Contract |
|---|---|---|
| `async get_login_page() -> Dict` | `:124` | GET `login.php` (timeout 30 s), then `extract_csrf_token`. Returns `{"status_code", "current_url", "csrf_token", "cookies": dict(client.cookies), "mock": False}`. In mock mode: `{"csrf_token": "mock-csrf-token-12345", "session_active": False, "mock": True}`. On failure it returns `{"error": portal_error_reason(e), "unreachable": isinstance(e, httpx.TransportError), "mock": False}` and never raises. |
| `async login(username=None, password=None) -> Dict` | `:150` | Takes the login page's CSRF token, then POSTs `login.php` with the form `{"_csrf": token, "username": u, "password": p}`. That is the bot's only POST. A response that still ends on `login.php` is a refused login: `{"success": False, "error": "the portal refused the login (wrong username or password?)"}`. Success is `{"success": True, "status_code", "redirected_url", "message": "Authentication successful"}` and sets `is_authenticated = True`. No token gives `{"success": False, "error": "Could not extract CSRF token from login page"}`. Unreachable gives `{"success": False, "error": "the login page could not be opened (...)", "unreachable": bool}`. Mock mode gives `{"success": True, "message": "Successfully authenticated in Mock Mode as '<u>'", "role": "admin", "mock": True}`. It never raises. |
| `async _ensure_session() -> None` | `:294` | See the diagram. It checks `login()`'s result; the legacy methods do not. **Private, and the only session opener.** bbd8f98 added a public `ensure_session()` wrapper so the old self-computed performance report's two reads (run side by side with `asyncio.gather`) shared one login instead of racing two; ce23535 removed it together with those reads. A rebuild that runs reads in parallel on one client should open the session first in the same way, or two concurrent first GETs each log in. |
| `async _get_once(path, params, limits) -> httpx.Response` | `:303` | One GET, with timeouts mapped to `PortalUnavailable` |
| `async portal_get(path, params=None, timeout=60.0) -> httpx.Response` | `:314` | **The one way to read a portal page.** It never returns a login or error page as data. Used directly by `audit_student_passport` (binary scan download) and `download_passports.py`; overridden by `cloud\full_picture.PortalSession` (§3.1). |
| `async fetch_html(path, timeout=60.0, params=None) -> str` | `:339` | `(await portal_get(...)).text`. Used by every reader below (`read_consult_performance` with `params={"period": period}`), `ask.py` (`index.php`, `calendar.php`), `passport_issue.py` (`student_edit.php`, `{"id": uid}`), `stage_report.py` (`progress.php`, `{"uid": uid}`) and the `src\cloud\backfill.collect_*` readers. |

`path` may carry its own query (`"students.php?status=pending"`). `params` values are URL-encoded, so `"Admission & Tuition"` stays one value. Parsing of the large pages (students.php about 1 MB a page, consult_requests.php about 2 MB) runs in `asyncio.to_thread`, so the event loop keeps answering Telegram.

### 3.6 The all-pages students reader
**`async read_student_pages(params=None, *, all_pages=True) -> List[str]`** (`:454`) returns the HTML of every page of `students.php` for `params` (e.g. `{"q": "Kim"}`, `{"status": "pending"}`, `{"prog": ...}`). Empty values and `pg` are dropped from `params`, and the rest is kept on every page.
1. Page 1 is fetched with `params` (no `pg`); page N with `{**params, "pg": N}`.
2. A page without `"<table"` raises `PortalUnavailable("students.php has no student table (its layout is not recognised)")`.
3. It reads `student_pager(html)` (`Page X of N · T students`) and `student_uids(html)`.
4. On page 1, if there is no pager and 50 or more rows, it raises ("... but no 'Page 1 of N', so its later pages cannot be found"). If there is a pager, it takes `pages` and `total` from it.
5. If the pager says another page than the one asked for, it raises ("the list changed while it was read").
6. `pages = max(pages, pager.pages)`, so the page count follows a list that grows during the read (a new registration shifts rows down).
7. More than `MAX_STUDENT_PAGES` pages raises.
8. With `all_pages=False` it stops after page 1 (the 50 newest applications).
9. At the end, if fewer unique uids than the pager's `total` were seen, it raises ("the student list says T students but its N pages hold U (it changed while it was read, or rows were not recognised)").

**`async read_students(params=None, *, all_pages=True) -> List[Dict]`** (`:501`) runs `parse_students_page` on each page in a worker thread. It turns `StudentListLayoutError` into `PortalUnavailable("students.php: <why>")` and de-duplicates by `uid`, falling back to the key `("row", student_id, student_name, applied_date)`, keeping list order (a row can shift onto the next page mid-read). The record shape is in §4.4.4. Callers: `ask.py`, `scheduler.py` (passport watcher), `telegram_bot.py` (crosscheck, passports, stage...), `passport_issue.py`, `stage_report.py`, `audit_program.py` (`{"prog": program}`), `download_passports.py`, `inspect_passports.py`, `verified_docs.py` (through `read_student_pages`), and `src\cloud\backfill.collect_students` / `collect_pending` (`backfill.py:93`, `:221`, the latter through `read_student_pages({"status": "pending"})`), which the full picture reuses.

### 3.7 Every reader
| Method (line) | Portal GET(s) | Returns | On failure | Main callers |
|---|---|---|---|---|
| `get_dashboard()` (`:202`) | `index.php` (30 s) | `parse_hangeul_live_dashboard` dict (§4.3); mock gives `MOCK_DASHBOARD_STATS` | `{"error": reason}`; never raises | brief.py, telegram_bot `/stats`, API, `get_admitted_students` |
| `get_applications(status=None, intake=None)` (`:214`) | students.php: page 1 without a filter, every page with one | Student records, filtered by case-insensitive substring on `"status"` (the stage) and on `"target_intake"` | Raises `PortalUnavailable` | telegram_bot `/students`, API |
| `get_admitted_students(query=None)` (`:236`) | `index.php` (via `get_dashboard`), then every students.php page | `{"students": admitted matching query, "admitted": n, "checked": n read, "stage": stage used, "tile": dashboard Admitted figure or None, "query", "listed": every student read (the whole list), "dashboard": the `get_dashboard()` dict (None in mock mode)}`. The last two are new in 2b6798f, so `/admitted` can hand the whole list and the dashboard it read to `cloud.command_hooks.seen(reads, students=..., dashboard=...)` (`telegram_bot.py:367`) without reading them again. | Raises `PortalUnavailable` | telegram_bot `/admitted` |
| `get_consultation_requests(target_date="today")` (`:269`) | **legacy**: `consult_requests.php` unfiltered (newest 500 only) | `parse_consultation_requests(html, target_date)` rows | `[]` on any exception | API only |
| `get_inquiries()` (`:287`) | as above, for `"today"` | rows; mock gives `MOCK_INQUIRIES` | `[]` | API only |
| `read_consultations()` (`:344`) | `consult_requests.php` | `consultation_table` rows, `[]` when empty, `None` for an unknown layout | Raises `PortalUnavailable` | tests only (production code no longer calls it) |
| `read_consultation_view(params=None)` (`:351`) | `consult_requests.php?<params>` | `consultation_view` dict `{rows, tabs, status, from, to, listed}` | Raises in mock mode, when there are no tabs ("status tabs (All, New, ...) and their counts were not found"), or when rows are unreadable | the next two; `cloud\backfill.py:157` (a date-range view for the backfill) |
| `read_consultation_totals()` (`:368`) | `consult_requests.php?status=file_opened` | All-time tab counts, e.g. `{"All": N, "New": n, "No Answer": n, "Wrong Number": n, "Consulted": n, "File Opened": n}` | Raises when the open tab is not `file_opened`, or a date filter is echoed (the counts would not be all-time) | brief.py, telegram_bot `/inquiries*`, `cloud\backfill.collect_totals` |
| `read_consultation_day(day)` (`:382`) | `consult_requests.php?status=all&from=YYYY-MM-DD&to=YYYY-MM-DD` | `{"day": date, "counts": tab counts for the day ("All" = received), "rows": the day's rows newest first, "complete": len(rows) == counts["All"]}` | `ValueError` for a non-date. `PortalUnavailable` when the search form does not echo the filter; when a row is from another day or has an unreadable date; when the caption count ≠ rows; when rows > All; when rows < All with no caption and fewer than 500 rows; or, when complete, when the per-status `Counter` of rows ≠ the tabs | brief.py, telegram_bot `/inquiries_today`, `/inquiries_date`..., `cloud\backfill.collect_consultations` (`backfill.py:189`; the full picture reads yesterday and today) |
| `read_consult_performance(period)` (`:425`) | `consult_performance.php?period=today` or `?period=month` (60 s; the page's own period links) | `parse_consult_performance` dict (§4.12): `{period, period_label, range_text, scope_note, tiles, top, columns, leaderboard, count, empty_text, sort_note, score_help, points_help}`, every figure a string as printed | `ValueError` for any other period; `PortalUnavailable` in mock mode, for a failed read, for `PerformanceLayoutError`, or when the page shows another period (details in §3.8) | `bot\performance.build_performance_report` (`performance.py:295`: `/performance_today`, `/performance_month`, `/perf_today`, `/perf_month`, `/performance [today\|month]` and the free-text routes), `cloud\backfill.collect_performance` (`backfill.py:294-313`; the backfill and the hourly full picture, `full_picture.py:110`) |
| `read_verified_students(target_date="today", all_pages=True)` (`:522`) | every students.php page | `parsers.verification` dicts for students whose "Payment verified by NAME · 27 Sep, 17:19" stamp is on the day | `ValueError` for a non-date. `PortalUnavailable` when rows exist but none has a "Payment verified by" line (the wording changed), or any stamp is unreadable | brief.py |
| `get_verified_students(target_date="today")` (`:547`) | same, `all_pages=True` | same | raises (never `[]` for a failed read) | telegram_bot `/verified*`, test_verified.py |
| `read_pending_payments()` (`:553`) | `students.php?status=pending` (page 1) | `{"count", "listed", "badge"}` or `None` (unreadable; see §4.8); mock gives `None` | fetch raises `PortalUnavailable` | brief.py (`ask.py` reads every pending page itself via `read_student_pages({"status": "pending"})`) |
| `read_window_apps_under_review()` (`:561`) | `window_applications.php?status=under_review` | int, counted from each row's own status; `None` when there is no table with a Status column; mock gives `None` | raises | brief.py, ask.py |
| `get_calendar_events()` (`:570`) | **legacy session**: `calendar.php` | `parse_calendar_events` dict (§4.10); mock gives `{"today_reminders": [], "upcoming_events": []}` | `{"today_reminders": [], "upcoming_events": [], "error": text, "layout_ok": False}` | brief.py, telegram_bot `/calendar` (`ask.py` fetches `calendar.php` through `fetch_html`) |
| `get_student_full_profile(student_id, force_live=True)` (`:592`) | **legacy**: `student_edit.php?id=<id>` | `{field name: value}` of every input, textarea and select (textarea and select give their full text), cached in `_profile_cache`. The soup is `decode_cf_emails(BeautifulSoup(resp.text, "html.parser"))` (`:614`): an address hidden in a textarea's text is read back; an input's `value` attribute is taken as served (Cloudflare does not rewrite attributes). | `{}` on error; an empty id gives `{}` | telegram_bot `_find_student_on_list_page` (`telegram_bot.py:1229`, the `/sendmail` fallback lookup when the CSV export fails: it takes `details["Email"]` from the list when it is a real address, which since 9ead47d it is, and reads this profile only for a missing e-mail, name or HNG id; the docstring still says the list hides the address) |
| `audit_student_passport(student_id, form_data, doc_filename=None, force_live=True)` (`:630`) | `student_edit.php?id=<sid>` (30 s), then `view_doc.php?f=<file>` (60 s) | the `ocr_validator` result dict (§5.10) | `unchecked_result(...)` (`PORTAL_UNREADABLE`); never raises for a portal failure | scheduler passport watcher, telegram_bot crosscheck and `/passports`, audit_program.py |
| `crawl_page(path)` (`:741`) | **legacy**: GET of any `path` | `{"status_code", "url", "tables": parse_tables(html), "dashboard_summary": parse_dashboard_metrics(html)}` (the latter is always `None`, see §4.2) | `{"error": str(e)}` | API only |

### 3.8 Method details that matter
**`get_admitted_students`.** The portal ignores `?status=admitted` and sends the whole list, so admitted students are picked in code. The stage comes from the dashboard's own Admitted tile: the tile whose label reduces (letters only) to `admitted` and whose href contains `students.php`. The stage is read from its href query `stage=` (`students.php?stage=Admitted+%2F+Completed`). If the tile is not there, `ADMITTED_STAGE = "Admitted / Completed"` is used. `is_admitted(s, stage)` compares case- and spacing-insensitively. `query` narrows the result in code with `student_matches` (name, HNG id, university, program, intake, application lines). The query never goes into a URL.

**`read_consult_performance(period)`** (`:425-452`), in order (ce23535; why: on 30 Sep at 13:11 the owner corrected the first, self-computed performance report: "performance" means the portal's own Consultant Performance page, and he wants only that page's data for today and this month, so the bot shows that page and computes nothing):
1. `want = PERFORMANCE_PERIODS.get(period)`; `None` raises `ValueError(f"no such performance period: {period!r} (only today, month)")`.
2. Mock mode raises `PortalUnavailable("the bot is in mock mode, so there is no live portal to read")` (there is no mock page).
3. `html = await self.fetch_html(PERFORMANCE_PAGE, params={"period": period})`: one GET of `consult_performance.php?period=today|month` (default 60 s read, 10 s connect).
4. `page = await asyncio.to_thread(parse_consult_performance, html)`; a `PerformanceLayoutError` becomes `PortalUnavailable(f"consult_performance.php: {e} (layout not recognised)")`.
5. **The period guard.** The page silently shows This Month for a `?period=` it does not take, so a wrong page would look right. It must say it shows the period asked for: `_label_key(page["period_label"]) == _label_key(want)` (the "Showing <strong>This Month</strong>" line, else the open tab's text) **and** `page["period"]` (the open tab's `?period=`) is `None` or `period`. Otherwise `PortalUnavailable(f"{PERFORMANCE_PAGE}?period={period} shows {repr(shown) if shown else 'no period'} instead of {want!r} (layout not recognised)")`, e.g. "consult_performance.php?period=today shows 'This Month' instead of 'Today' (layout not recognised)".
6. Returns the parsed dict unchanged; nothing is summed, ranked or corrected here (checks of the page against itself are warning lines in `bot\performance.format_consult_performance`, [03a](03a_FILES_src_bot.md)).

Measured live and read-only on 30 Sep (fake Telegram, every host but the portal blocked): `/performance_today` 1.2 s (login GET + POST, then the one GET), `/performance_month` 0.3 s (one GET on the open session). An independent check matched 34 of 34 and 9 of 9 figures against the page.

**`audit_student_passport`** (`:630-713`), in order:
1. `fetch_html(f"student_edit.php?id={sid}", timeout=30.0)`. A `PortalUnavailable` returns `unchecked_result(sid, "the student's profile (student_edit.php?id=<sid>) could not be read: <reason>")`.
2. `_profile_fields(html)`. With no `name` or `full_name` field, it returns `unchecked_result(sid, "student_edit.php?id=<sid> shows no student profile")`.
3. It caches the profile in `_profile_cache[sid]` and merges it into `form_data`: over it when `force_live`, otherwise only into empty keys.
4. With no `doc_filename`, it takes the profile page's own link `view_doc\.php\?f=(passport_[^"'\s&<>]+)`.
5. The filename must `fullmatch r"[A-Za-z0-9._-]+"` and contain no `..`; otherwise `unchecked_result(... "is not one the bot can save")`.
6. The local path is `C:\Hangeul\BOT\passports\<sid>_<doc_filename>`. The file name carries the upload time (`passport_<uid>_<unixtime>.<ext>`), so a saved copy is this very upload. `saved()` is true when the file exists, is at least 1000 bytes, and its first non-space byte is not `<` (so a login page saved long ago never counts).
7. If not saved: `portal_get(f"view_doc.php?f={doc_filename}", timeout=60)`. A failure returns `unchecked_result(... "the passport scan could not be downloaded: ...")`. Content starting with `<` or containing `<html` in its first 1000 bytes returns `unchecked_result(... "the portal sent a web page instead of the passport scan")`. Content of ≤ 1000 bytes returns `unchecked_result(... "only N bytes")`.
8. It checks `saved()` again (another audit may have saved the file meanwhile), writes `passports\.<sid>_<file>.part`, then `os.replace`s it into place. The check, write and rename never yield the event loop, so a scan is written once and a reader sees either no file or the whole file (7241465).
9. `await asyncio.to_thread(validate_passport_data, sid, form_data, local_path, live_audit=force_live)`. The OCR runs off the event loop, which fixes "the bot goes deaf for 3.5 minutes every half hour" (7241465).

A student with no scan on the portal gets `local_path=None` → `MISSING_DOCUMENT`. An older scan saved on this PC is never checked in its place.

**`_profile_fields(html)`** (static, `:716`) builds its soup with `decode_cf_emails(BeautifulSoup(html or "", "html.parser"))` (`:721`), then reads every `input`, `textarea` and `select` by `name` (or `id`). Input `value` attributes are kept exactly as served (Cloudflare leaves attributes alone; a served stand-in value is blanked later by `cloud\records.student_profile` as a filler). It is also called statically by `cloud\sheet_hooks.py:431` on `student_edit.php` pages the sheet jobs already fetched. It skips `_csrf` and the types `password`, `submit` and `button`. A select gives its `option[selected]` value or text, never the text of all its options (the legacy `get_student_full_profile` still takes all of it). A textarea gives its text; an input gives its `value`. Empty values are left out, and the first occurrence wins. The keys the validator reads from this dict are `name`/`full_name`, `dob`, `passport_no`/`passport_number`, `passport_expiry`, `father_name`, `mother_name`, `address`, `district` (the student_edit.php field names).

**Files written:** `C:\Hangeul\BOT\passports\<uid>_passport_<uid>_<unixtime>.<ext>` (the folder holds about 367 files; never open them). For a PDF scan, `ocr_validator` also writes `<base>_extracted.jpg` next to it.

### 3.9 Two generations of session code
| | New path (e0d47ab+) | Legacy methods (baseline) |
|---|---|---|
| Methods | `portal_get`, `fetch_html`, `read_*` (including `read_consult_performance`), `get_dashboard`, `get_applications`, `get_admitted_students`, `get_verified_students`, `audit_student_passport` | `get_consultation_requests`, `get_inquiries`, `get_calendar_events`, `get_student_full_profile`, `crawl_page` |
| Login check | `_ensure_session` checks `login()` and raises | `login()` result ignored |
| Expired session | `_ended_on_login` (URL path), one re-login, then raises | `"login.php" in str(resp.url)`, one re-login, no check afterwards |
| Timeouts | per call, connect 10 s | client default 15 s |
| Failure | `PortalUnavailable` | `[]`, `{}` or a dict with `"error"` |
| Mock check | yes | `get_consultation_requests` and `get_student_full_profile` have **none**: in mock mode they call the mock `login()` and then GET the real portal unauthenticated, which parses the login page and gives `[]` or `{}` |

A rebuild should use only the new path.

### 3.10 History
- 366dec0 baseline: 407 lines. `get_verified_students` read **page 1 only** (the audit showed 274 of 322 verifications invisible; on 12 Sep "0" where the truth was 10, on 23 Jul "0" instead of 62). The parser invented a `"20,000.00 BDT"` amount. Every failure returned `[]` ("No student payments were verified").
- 4154aa5: the passports folder moved from `os.getcwd()` to `BOT_ROOT`.
- 7241465: OCR via `asyncio.to_thread`; `.part` then rename.
- f8fefa4: `fetch_html`, `read_consultations`, `read_verified_students(all_pages)`, `read_pending_payments`, `read_window_apps_under_review`, the constants.
- e0d47ab: `PortalUnavailable`, `portal_error_reason`, `_ended_on_login`, `_ensure_session`, `_get_once`, `portal_get`, `read_student_pages`, `read_students`. `get_admitted_students` now returns a dict (it used to return a list).
- 46cdf03: `read_consultation_view`, `read_consultation_totals`, `read_consultation_day`. Before this, days older than about 3 weeks read 0 and the all-time figures were about half (500 / 367 against the portal's 999 / 797).
- 40da0e6: `audit_student_passport` goes through `portal_get`, gives `PORTAL_UNREADABLE`, never saves a web page as a scan, never uses a stale local scan; `_profile_fields` added.
- 2b6798f (29 Sep, cloud branch): `get_admitted_students` also returns `listed` and `dashboard`, for the Supabase command hooks.
- 9ead47d (29 Sep, cloud branch): both `student_edit.php` soups (`get_student_full_profile`, `_profile_fields`) are wrapped in `decode_cf_emails` (§4.1.1).
- bbd8f98 (29 Sep 21:41, main) and a721066 (30 Sep 10:29, main): the **first** `/performance_today` / `/performance_month`, a team report the bot computed itself, added readers that are now **gone**:
  - `ensure_session()`: public wrapper of `_ensure_session`, so the two reads below, run with `asyncio.gather` (each within 120 s), shared one login;
  - `read_consultation_range(first, last)`: `consult_requests.php?status=all&from=&to=` for a window; when the list stopped at its 500-row limit, the days after the oldest one reached were kept and the rest re-read as its own window (September already had 636 requests), up to `CONSULT_RANGE_MAX_READS = 16` reads, with `_ListChanged(PortalUnavailable)` forcing one more full read when the parts did not add up to the window's own tab count; a721066 added `consultant_column` (and `consultation_view` briefly returned `columns`);
  - `read_verified_window(first, last)`: every students.php page read **once** for the window, each student counted on its own stamp's day (`parsers.verified_between`), with the stamp checks factored into `_stamp_guard(students)` and shared with `read_verified_students`;
  - `_span(first, last)`, the header text of a window.
  Live on 29 Sep they took 9-10 s and 8-9 GETs a report. The owner then said this was not what he meant (§3.8), and **ce23535 (30 Sep 13:34) removed all of them**, together with `parsers.verified_between`; `read_verified_students` got its stamp checks back inline. A rebuild does not need them: a date-range consultation reader is a valid technique (§4.7 explains the 500-row cap), but no current command uses one. (`telegram_bot._verified_between`, `telegram_bot.py:1571`, is an older, separate helper for spans of verification days, present at c17d887 already, and still exists.)
- ce23535: `PERFORMANCE_PAGE`, `PERFORMANCE_PERIODS`, `read_consult_performance(period)`.
- e5e532e (30 Sep 21:04): the merge of main into the cloud branch; `client.py` keeps both sides' imports (`decode_cf_emails`, and main's `_label_key` and performance names). 8317741 is this file's state.

---

## 4. `src\scraper\parsers.py`: HTML parsers

It is pure BeautifulSoup (`html.parser`) plus regexes, with no I/O. Imports at 8317741: `copy`, `logging`, `re`, `typing`, `urllib.parse.parse_qs/urlsplit`, `bs4.BeautifulSoup, NavigableString, Tag` (`:1-7`). Logger: `hangeul.parsers` (unused). **Design rules:** find columns by the header's **names**, never by position (the portal re-laid out consult_requests.php and students.php on its own). Use the page's own CSS classes. A field the page does not show is `""` or `None`, never a stand-in value. An unrecognised layout raises `StudentListLayoutError` / `PerformanceLayoutError` or returns `None`, never `0`. **Every soup is built as `decode_cf_emails(BeautifulSoup(html, "html.parser"))`**, on one line, so no parser ever sees Cloudflare's "[email protected]" stand-in where the page has an address (§4.1.1).

### 4.1 Shared helpers
| Function | Line | Contract |
|---|---|---|
| `_label_key(text) -> str` | `:100` | Lower case, non-alphanumerics become spaces, and a plural `s` is dropped from the **last** word (if it is longer than 3 letters and does not end in ss, us or is). `"Pending payments"` → `"pending payment"`; `"Total students"` → `"total student"`; `"Consultancies"` → `"consultancie"`; `"#"` → `""`. Also imported by `client.py` (the performance period guard). |
| `_int_or_none(text) -> Optional[int]` | `:109` | `"1,234"` → 1234; anything but `\d[\d,]*` gives `None` |
| `_blank(text) -> str` | `:342` | Collapses whitespace; the portal's `—`, `-` and `–` (nothing) become `""` |
| `_no_dash(value) -> str` | `:713` | `""` for `—`, `-`, `–`, `--` |
| `_header_index(tr) -> Dict[str, int]` | `:885` | `{_label_key(cell text): index}` for a header row |

#### 4.1.1 Cloudflare's e-mail protection (`decode_cf_emails`)
**Why.** hangeul.com.bd is served through Cloudflare, whose "e-mail address obfuscation" rewrites every address in the HTML it sends. A browser's `email-decode.min.js` puts the addresses back, so nobody noticed; a parser reading the HTML sees the text `[email protected]` (with a non-breaking space, `&#160;`) instead. Dry run 2 of the Supabase backfill (29 Sep, about 15:37) found it: the stand-in was stored as `details.Email` in all 333 student records and the 1 pending-payment record, and in 1,005 of the consultation contacts, and the bot's own replies showed it too. The earlier per-cell `_cf_email` / `_decode_cf_emails` (46cdf03) had decoded only a consultation's `.cr-name`. 9ead47d (29 Sep 16:19) replaced them with one decoder called at every soup; after it, a guarded live check decoded 50 of 50 `details.Email` on students.php page 1 (100 `data-cfemail` elements) and 12 of 12 consultation contacts for one day, and the postcheck of the real backfill found 0 stand-ins in 13,540 records.

**The three forms Cloudflare writes** (all handled):
1. `<a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="HEX">[email&#160;protected]</a>` (an address in text),
2. `<span class="__cf_email__" data-cfemail="HEX">[email&#160;protected]</span>` (the same as a span),
3. `<a href="/cdn-cgi/l/email-protection#HEX">…</a>` (a `mailto:` link; its text is either its own words or a form-2 span).

| Name | Line | Contract |
|---|---|---|
| `_CF_CLASS` | `:19` | `"__cf_email__"` |
| `_CF_LINK` | `:20` | `"/cdn-cgi/l/email-protection#"` |
| `_HEX_RE` | `:21` | `[0-9A-Fa-f]+` |
| `_cf_address(hexstr) -> str` | `:24` | The decode: strip; `""` unless the hex is at least 4 characters, of even length and all hex. `raw = bytes.fromhex(h)`; the **first byte is the key**, and `bytes(b ^ raw[0] for b in raw[1:])` decoded as **UTF-8** is the text (`UnicodeDecodeError` gives `""`). The result must contain `@`, be `isprintable()` and hold no whitespace, else `""` (a mailto query such as `?subject=` is URL-encoded, so it has none). Checked offline: a key of `0x42` over a synthetic `student@example.com` round-trips; `"zz"`, `""` and an odd-length hex give `""`. |
| `_is_cf_email(tag) -> bool` | `:42` | Class `__cf_email__` **and** a `data-cfemail` attribute, or an `a` whose `href` contains `/cdn-cgi/l/email-protection#` |
| `_put_text(el, text)` | `:47` | Replaces `el` by a `NavigableString` and **joins** it with a plain-text sibling on either side, so `get_text(strip=True)` reads `"Email: x@y.com"` as a browser shows it, not `"Email:x@y.com"` |
| `decode_cf_emails(node) -> node` | `:64-97` | In place, and returns `node` (so it wraps the constructor). A non-`Tag` is returned as it is. It finds every `_is_cf_email` element (plus `node` itself when a single tag is passed). A form-3 link gets `href="mailto:<address>"` and keeps its text. A `__cf_email__` element whose hex decodes becomes the address as plain text (`_put_text`); when it is the caller's own tag, or has no parent, it is kept with its text replaced, `data-cfemail` deleted and the class removed. A malformed or empty hex leaves the element exactly as served, still `[email protected]`. It never touches form fields' `value` attributes (Cloudflare does not rewrite them) and fetches nothing. Calling it twice equals calling it once. |
| `_EMAIL_HIDDEN_RE` | `:327` | `\[email\s*protected\]` (case-insensitive): the stand-in text, stripped from `.stu-name` |
| `_EMAIL_HIDDEN_GAP_RE` | `:328` | `\s*\[email\s*protected\]\s*` (case-insensitive; `\s` also matches the `&#160;`) |
| `_EMAIL_RE` | `:329` | `[\w.+-]+@[\w-]+(?:\.[\w-]+)+`: an address line, which the Student-cell fallback no longer takes for the name |
| `_without_hidden_email(text) -> str` | `:707` | A longer text without a stand-in that could not be decoded: `"01700000000 [email protected]"` → `"01700000000"`. Used for a consultation's `contact` and `details`. (The old code stripped only `"[email protected]"` with an ASCII space, which never matched Cloudflare's `&#160;`.) |

**What an undecodable stand-in becomes.** A whole cell of `[email protected]` stays in the parser's output, but `src\cloud\records.is_filler` treats it as "no value": `FILLER_WORDS` holds `"emailprotected"` (`records.py:206-207`; compared on letters and digits only, any case, either space), so the record blanks the field and names it in `data.blank_on_portal` (e.g. `["details.Email"]`). No record ever holds a fake address ([03d](03d_FILES_src_cloud.md)).

**Every soup is wrapped, and a test enforces it.** At 8317741 the 17 constructions in `src\` are:
- `parsers.py` (13): `extract_csrf_token` `:116`, `parse_tables` `:138`, `parse_dashboard_metrics` `:185`, `parse_hangeul_live_dashboard` `:276`, `parse_students_page` `:438`, `parse_progress_page` `:566`, `consultation_rows` `:618`, `consultation_table` `:626`, `consultation_view` `:688`, `parse_pending_payments` `:896`, `parse_window_applications` `:924`, `parse_consult_performance` `:1120`, `parse_calendar_events` `:1326`;
- `client.py` (2): `get_student_full_profile` `:614`, `_profile_fields` `:721`;
- `bot\ask.py` (1): `dashboard_facts` `:690` (the index.php cards);
- `sheets\verified_docs.py` (1): `:47` (the verified-documents list, which feeds the `student_documents` kind).

`tests\test_cloud_cf_email.py:287-298`, `test_every_page_parse_in_src_decodes_right_after_building_its_soup`, reads every `src\**\*.py` line that contains `BeautifulSoup(` and not `import`, asserts the line contains `decode_cf_emails(BeautifulSoup(`, and pins the counts: `parsers.py` 13, `client.py` 2, `ask.py` 1, `verified_docs.py` 1. So a new parser **must** wrap its soup on the same line and bump the count; a soup built without it, or one more or fewer, fails the suite with `path:line`. The count was 12 on the cloud branch; the merge e5e532e made it 13 when `parse_consult_performance` (from main) was wrapped and main's `_decode_cf_emails` calls in `_perf_name` / `_perf_top` were dropped. Not covered: files outside `src\`. The root script `get_consultations.py` still builds a bare soup and strips the stand-in by text, and reads the pre-28-Sep fixed-column layout, so it is broken regardless; no bot code uses it. The file's other tests (18 test functions in all) cover the round trip (keys 00, 01, 42, 5A, A7, FF, upper-case hex, a UTF-8 address), the three forms, malformed hex, no network, idempotence, untouched `value` attributes, each page end to end, `records.is_filler` on the stand-in, and (the last three) the one-log-line rule for a missing embedding model; all addresses there are synthetic (`example.com` / `example.org`).

### 4.2 Generic parsers (used by the API's crawler and by login)
- `extract_csrf_token(html) -> Optional[str]` (`:114`): in order, `input[name=_csrf]`, then `input[name=csrf_token|token|_token|csrf]`, then `meta[name=csrf-token][content]`.
- `parse_tables(html) -> List[Dict]` (`:136`): every `<table>` becomes `{"table_id": id or "table_<n>", "columns": headers (from `thead th`, else the first row; blanks become `col_<i>`), "row_count", "rows": [{header: cell text}]}`. It skips the header-echo row and empty rows.
- `parse_dashboard_metrics(html) -> Dict` (`:183`): **bug since the baseline, still there at 8317741: it has no `return` statement, so it always returns `None`.** It builds `metrics` from elements whose class contains card, stat, metric, counter or widget, and `alerts` from alert, notice, error or warning elements, then drops them. So `crawl_page()["dashboard_summary"]` is always `None`. `test_system.py:57` expects `metrics["metrics"]`, so that smoke test would fail at this step. (9ead47d wrapped its soup like the others; nothing else changed.)

### 4.3 `index.php` dashboard
**DOM:** `div.dash-sec > .ds-t` (group heading, e.g. "Direct / legacy pipeline", "Admissions flow"), then `.stats-row` containing `a.stat-card[href]` (or a `.stat-card` inside an `<a>`), each with `.stat-num` (the figure) and `.stat-lbl` (the label). Older layout fallback: `.stat-num` and `.stat-lbl` side by side in a `.stats-row`.

`_DASHBOARD_TILES` (`:217`) maps each summary key to (the tile label as printed, a part of its link). Nothing is relabelled.
| summary key | label | href must contain |
|---|---|---|
| `open_windows` | Open windows | `admission_windows` |
| `draft_windows` | Draft windows | `admission_windows` |
| `submitted_window_apps` | Submitted apps | `window_applications` |
| `window_apps_under_review` | Under review | `window_applications` |
| `window_docs_to_review` | Docs to review | `review_queue` |
| `window_apps_accepted` | Accepted (accepted window applications, **not visas**; the dashboard has no visa figure) | `window_applications` |
| `total_students` | Total students | `students.php` |
| `pending_payment` | Pending payment | `students.php` |
| `verified_students` | Verified | `students.php` |
| `students_docs_to_review` | Docs to review | `students.php` |
| `admitted` | Admitted | `students.php` |

- `_dashboard_tiles(soup) -> List[{"group", "label", "value": int|None, "text", "href"}]` (`:232`).
- `_tile_value(tiles, label, href_part) -> Optional[int]` (`:257`): if exactly one tile has the label and the label is not shared by two keys, it returns that tile's value. Otherwise it returns the one tile whose href contains `href_part`, or `None`.
- `parse_hangeul_live_dashboard(html) -> Dict` (`:269`; soup decoded at `:276`) returns `{"status": "success", "portal": "Hangeul Korean Language & Visa - Live Portal", "last_synced": <now ISO>, "summary": {11 keys above + aliases "total_applicants" (= total_students) and "pending_document_verification" (= students_docs_to_review)}, "live_stats": {label (a duplicated label gets " (<group or href>)"): figure text}, "tiles": [...], "recent_activity": up to 5 texts of a[href*=window_application_view]}`. Callers: `client.get_dashboard`, `ask.py:687-689` (`dashboard_facts`, `:683`: typed questions build their "facts" from it, and it decodes its own soup of the page's cards at `:690`), and through `get_dashboard` / `dashboard_facts` the Supabase `dashboard_fact` kind.
- History: the baseline returned placeholder numbers when a label was missing (`262` total, `31` this week, `2` under review, `21` docs), read labels case-sensitively, and hard-coded program and university regexes. f8fefa4 replaced this with label keys and `None`.

### 4.4 `students.php`

#### 4.4.1 Constants and regexes
| Name | Line | Value |
|---|---|---|
| `ADMITTED_STAGE` | `:317` | `"Admitted / Completed"` (the Admitted tile links to `students.php?stage=Admitted+%2F+Completed`) |
| `_STUDENT_COLUMNS` | `:321` | `sl`←`sl`, `student`←`student`, `university`←`universit`, `program`←`program`, `docs`←`doc`, `payment`←`payment`, `stage`←`stage` (prefix match on `_label_key` of the header cells) |
| `_REQUIRED_STUDENT_COLUMNS` | `:324` | `("sl", "student", "program", "stage")` |
| `_PAGER_RE` | `:325` | `Page\s+(\d+)\s+of\s+(\d+)(?:\s*·\s*([\d,]+)\s+students?)?` (case-insensitive) |
| `_UID_RE` | `:326` | `student_edit\.php\?id=(\d+)` |
| `_EMAIL_HIDDEN_RE`, `_EMAIL_HIDDEN_GAP_RE`, `_EMAIL_RE` | `:327-329` | Cloudflare's stand-in, the stand-in with its surrounding space, and an address (§4.1.1) |
| `_HNG_RE` | `:330` | `HNG-\d{4}-\d+` (the agency's student id, e.g. `HNG-2026-NNN`) |
| `_STAMP_TEXT` | `:331` | `\d{1,2}\s+[A-Za-z]{3,9}\.?(?:\s+\d{4})?(?:,\s*\d{1,2}:\d{2})?` |
| `_VERIFIED_BY_RE` | `:332` | `Payment verified by\s+([^·\n]{1,80}?)\s*·\s*(<STAMP>)` |
| `_PAID_RE` | `:333` | `Paid:\s*([\d,]+\.?\d*\s*BDT)\s*([A-Za-z][A-Za-z\s\-]*?)?\s*(?:Verified\|$)` |
| `_INCOME_RE` | `:334` | `Verified income:\s*([\d,]+\.?\d*\s*BDT)` |
| `class StudentListLayoutError(ValueError)` | `:337` | The page was read, but its layout is unknown |

#### 4.4.2 The page's DOM (as the tests model the live page)
```
table.tbl.stu-tbl
  thead tr: th(''), th SL, th Student, th University, th "Program · Intake", th Docs, th Payment, th "Stage · Applied", th('')
  tr.stu-row            td.c-chk | td.c-sl <n> | td.c-stu: strong.stu-name <name>, .stu-mail (a.__cf_email__[data-cfemail]),
                        .stu-tags .stu-sid <HNG id> | td.c-uni (.stu-uni + .upr lines) | td.c-prog <program><div.stu-sub> <intake>
                        | td.c-docs | td.c-pay | td.c-stage <stage><div.stu-sub> <applied day> | td.c-exp
  tr.xp-row td[colspan=9]: .det > .det-item(label, span) ...   (Full Name, DOB, Email (a Cloudflare-protected
                        address), Program, Intake, Payment Status, Applied On, Passport No, Passport Expiry,
                        Passport Status ...)
                        .pay > span.pf.paid "Paid: 8,000.00 BDT", span.pf.method "bKash", span.pf.verified
                        "Verified income: ...", div.pf-by "Payment verified by <strong>NAME</strong> · 27 Sep, 17:19"
                        a[href=view_doc.php?f=passport_<uid>_<unixtime>.jpeg] / receipt_... ; a[href=student_edit.php?id=<uid>]
                        a[href=progress.php?uid=<uid>] ; button onclick=showDel(<uid>, ...) ; a POST form with stage and
                        transfer-intake <select>s (read-only for the bot; their words must never be taken as data)
  tr.empty-row          "No students found ..."
div.stu-pager "Page 1 of 7 · 330 students"
```

#### 4.4.3 Functions
| Function | Line | Contract |
|---|---|---|
| `student_pager(html) -> {"page", "pages", "total"}` | `:348` | Each is `None` when there is no pager (a one-page list has none) |
| `student_uids(html) -> List[str]` | `:358` | The uids on the page, in order, each once (a regex, cheap for every page) |
| `_student_details(tr) -> Dict` | `:364` | One `.xp-row` gives `{"uid" (from student_edit.php?id=, else showDel(N, else progress.php?uid=N), "details": {label: value} (first of each label, "—" → ""), "files": [view_doc.php?f= names], "details_text", "verified_line": bool, "verified_by", "verified_stamp", "paid", "method", "verified_income", "applied_on"}`. It reads the stamp from `.pf-by`'s own text, so any other text in the row cannot pass for a stamp. `verified_by` comes from `.pf-by strong`/`b`, else the regex. `paid`, `method` and `income` come from `.pf.paid`, `.pf.method` and `.pf.verified`, with the regexes as fallback. `applied_on` comes from `details["Applied On"]`, else the regex `Applied On\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4}(?:,\s*\d{1,2}:\d{2})?)`. |
| `parse_students_page(html) -> {"students", "empty", "page", "pages", "total"}` | `:413` | See the algorithm below. Its soup is decoded first (`:438`), so the Student cell's `.stu-mail` and the details' `Email` hold the real address. |
| `_main_and_sub(cell) -> (main, sub)` | `:486` | The cell's own text and its `.stu-sub` line (`"KLP"` / `"MARCH 2027"`; `"Payment Verified"` / `"28 Sep 2026"`). Without a `.stu-sub`, its first two text lines. |
| `_student_row(cells, col, sl) -> Dict` | `:499` | The list row's columns, with `"_open": True` until its details row is read. Without a `.stu-name`, the name is the first cell line that is neither an HNG id nor an address (`_EMAIL_RE.fullmatch`, 9ead47d), because the decoded `.stu-mail` line would otherwise be taken for the name. |
| `parse_hangeul_live_students(html) -> List` | `:536` | `parse_students_page(html)["students"]` (kept for older callers; tests only) |
| `is_admitted(student, stage=ADMITTED_STAGE) -> bool` | `:543` | `_label_key(student["status"]) == _label_key(stage)` |
| `student_matches(student, query) -> bool` | `:549` | Case- and space-insensitive substring over student_name, student_id, target_university, program, target_intake and every `applications` line. An empty query is True. |

**`parse_students_page` algorithm:** take the first `<table>` (none: raise "students.php has no student table"). Take the rows whose parent is that table. The header is the first row with a `th` (none: raise). Map `_STUDENT_COLUMNS` to indexes, each index used once; a missing required column raises "the student table's header has no X column (it reads [...])". Then, for each row:
- `len(cells) == len(header)` and the SL cell is a number: a student row.
- Class `xp-row`, or one cell while the current student is still open: that student's details row.
- Class `empty-row`, or one cell matching `\bno\s+students?\b`: counted as empty.
- Any other non-empty row: counted as unread.

Students with no details row get `_student_details(None)`, i.e. empty fields. Any unread rows raise ("N row(s) the parser cannot read"). It returns `empty = bool(empty rows) and not students`.

#### 4.4.4 A student record (`read_students` / `parse_students_page`)
| Key | Meaning / example |
|---|---|
| `uid` | Portal user id (`student_edit.php?id=N`); `""` when there is no link |
| `sl` | The SL number shown |
| `student_id`, `id` | HNG id (`HNG-2026-NNN`); `""` before one is given (`id` is the older name) |
| `student_name` | `.stu-name` text, with `[email protected]` removed, or the first line that is neither an HNG id nor an e-mail address |
| `target_university` | The University cell's own `.stu-uni` line (e164679), else the cell text |
| `applications` | `.upr` lines, e.g. `"Applied: <University> · Bachelor's Degree"`; `[]` when there are none |
| `program`, `target_intake` | Program cell main text and its sub line |
| `docs_status`, `payment_status` | The cells as shown |
| `status` | **The stage** (e.g. `"Payment Verified"`, `"Admitted / Completed"`) |
| `applied_date` | The sub line under the stage (`"28 Sep 2026"`) |
| `details`, `files`, `details_text`, `verified_line`, `verified_by`, `verified_stamp` (`"27 Sep, 17:19"`, no year), `paid`, `method`, `verified_income`, `applied_on` (`"27 Sep 2026, 17:16"`) | From the details row (see `_student_details`) |

Known `details` labels read elsewhere: `Full Name`, `DOB`, `Email` (the `/sendmail` list-page fallback, and the Supabase `student` record), `Passport No`, `Passport Expiry`, `Passport Status`, `Program`, `Intake`, `Payment Status`, `Applied On`.

History: the baseline read fixed positions `tds[1..9]` (shifted by one cell), gave every student the intake `"March 2027"`, and invented ids `HNG-SL-<n>` and the university `"Pending Allocation"`. e0d47ab rewrote it by header name; e164679 added `.stu-uni` and `.upr`; 9ead47d decodes the page's Cloudflare addresses (before it, every `details["Email"]` was `"[email protected]"`) and keeps an address line out of the name fallback.

### 4.5 `progress.php?uid=N`
`parse_progress_page(html) -> {"pct": int, "stage": str, "status": str}` (`:561`). It reads `.pg-ring` (the text must contain `(\d{1,3})\s*%`), `.pg-now .pg-stage` and `.pg-now .pg-status` (e.g. `"Verified"`, `"Pending verification"`). It raises `StudentListLayoutError("progress.php shows no progress ring with a % and a current stage")`. Caller: `sheets\stage_report.py` (in a worker thread). Added in e164679.

### 4.6 Payment verifications (students.php stamps)
| Function | Line | Contract |
|---|---|---|
| `normalize_target_date(target_date) -> Optional[str]` | `:576` | A user date formatted as the portal writes it, `"09 Sep 2026"`, via `parse_user_date(prefer_past=True)`. `None` only for empty input; raises `ValueError("not a date: '31 Sep' (31 Sep: September has 30 days)")`. |
| `target_day(target_date) -> date` | `:801` | A `date` is returned as it is; text (default `"today"`) is parsed with `prefer_past=True`; unreadable text raises `ValueError` |
| `verification(student, day) -> Optional[Dict]` | `:814` | If the row's own stamp is on `day` (`stamp_on_day` with `applied` = `parse_portal_date(applied_on)` or `applied_date`), returns `{"student_id", "uid", "name" (student_name, else details["Full Name"]), "program", "amount" (verified_income, else paid, else ""), "paid", "verified_income", "method", "verified_by", "verified_time" (stamp.text)}`, else `None`. The caller must first reject a day a year or more back (`yearless_day_problem`). |
| `_money(text)` | `:847` | Whitespace removed, upper-cased (for comparing amounts) |
| `payment_text(v) -> str` | `:851` | `"8,000.00 BDT bKash"`. When paid ≠ verified income: `"Paid 8,160.00 BDT bKash (verified income 8,000.00 BDT)"`. `""` when there is no payment. Callers: brief.py, telegram_bot `/verified`. |
| `verified_on_day(students, day) -> List` | `:862` | `verification` over a list, keeping list order |
| `scan_verified_students(html, target_date="today") -> {"verified", "students", "markers"}` | `:868` | One page. `markers` counts rows with any stamp, so "nobody that day" can be told apart from "layout unknown". |
| `parse_verified_students(html, target_date="today") -> List` | `:791` | `scan_verified_students(...)["verified"]` (tests only) |

Why stamps and not other text: the audit found that the transfer-intake option "2027 SEPTEMBER" matched 27 Sep, that "Applied On 15 Sep" matched 15 Sep, and that `8 Sep` matched 18 Sep (40da0e6 / e0d47ab). A window version, `verified_between(students, first, last)`, existed from bbd8f98 to ce23535 for the removed `read_verified_window` (§3.10); it is gone.

### 4.7 `consult_requests.php` (consultation requests / inquiries)
**DOM:** `nav.cr-tabs > a` (class `st-<value>`, plus class `on` or `aria-current` on the open tab), each with the label text and a `.n` count. `form.cr-search` (GET) with inputs `status`, `from` and `to`, which echo the applied filter. The caption `<b>N</b> requests · newest first`. The table header is Student, Consultant, City & program, Received, Status, Remarks, Update status. Cells use `.cr-name` (with `.cr-contact`), `.cr-cons`, `.city`, `.prog` and `.crd-body`, `.d` (day) and `.t` (time), `.stbadge` (status), `.cr-by` ("Last updated by"), and a remarks `textarea`. The empty row is `.cr-empty` or `tr.cr-empty-row` ("No consultation requests yet."). E-mail addresses (a name that is an address, and the contact line) are protected by Cloudflare: names as `span.__cf_email__[data-cfemail]`, contacts as link-form `a[href^="/cdn-cgi/l/email-protection#"]` (in the 29 Sep live check all 12 contacts of one day were link-form) (§4.1.1). Each row carries never-submitted forms with a hidden `input[name=id]`, the request's own portal id. The "Remarks" and "Update status" forms are only read, never submitted.

| Function | Line | Contract |
|---|---|---|
| `_consult_columns(header) -> Dict[str, int]` | `:592` | By substring: name←student or name, contact←contact or phone, city, program, consultant, details←detail, received←received or date, status, remarks←remark. Headers containing "update" are skipped. |
| `consultation_rows(html) -> List[Dict]` | `:608` | Rows of the first table of the decoded soup (`:618`); `[]` when there is none |
| `consultation_table(html) -> Optional[List]` | `:622` | `None` when there is no table or the rows are unreadable; `[]` for a truly empty table (decoded soup at `:626`) |
| `_consultation_data_rows(table)` | `:635` | The rows below the header, minus the portal's empty row |
| `CONSULT_STATUSES` | `:642` | `("New", "No Answer", "Wrong Number", "Consulted", "File Opened")` (spelt as on the portal; not referenced elsewhere) |
| `_consultation_tabs(soup) -> (counts, current)` | `:645` | `{label: count}` including `"All"`, and the open tab's `st-` value. `(None, None)` when there is no nav, a count is not a number, or there is no "All". |
| `consultation_view(html) -> Dict` | `:671` | `{"rows": list or None, "tabs": dict or None, "status": open tab value or None, "from", "to": the search form's echo ("" = none; None when there is no form), "listed": the caption count or None}` (decoded soup at `:688`; unchanged shape at 8317741: the `columns` key a721066 added was removed again in ce23535) |
| `_without_hidden_email(text)` | `:707` | Drops an undecodable stand-in from a longer text (§4.1.1) |
| `_consultation_table_rows(table) -> List[Dict]` | `:718` | Needs the name and status columns. Each row becomes `{"id", "name", "contact", "city" and "program" ("—" → ""), "consultant" (`.cr-cons`, else "Unassigned"), "details" ("View" removed), "received" ("<day> <time>"), "received_date" (the day), "status" (`.stbadge` text), "handled_by" (`.cr-by` text, "" when nobody has touched it; never the assigned consultant), "remarks" (the textarea text)}`. `id` (3caa393) is the value of every `form input[type="hidden"][name="id"]` in the row when they all agree on one all-digit value, else `""`; the Supabase `consultation` kind uses it as the record key, so a changed row is updated in place, never deleted and re-created (the postcheck of the real backfill matched its 1,034 consultation keys to the portal's request ids one by one). `contact` and `details` go through `_without_hidden_email` (9ead47d). Rows with no name are skipped. |
| `parse_consultation_requests(html, target_date=None) -> List` | `:784` | Legacy: rows whose `received` contains `normalize_target_date(target_date)`. Only the API uses it. |

History: cd0277a (28 Sep): the portal moved from 8 or more fixed columns to 7 named ones, so every count silently read 0. The rewrite reads columns by header name. 46cdf03 added `consultation_view`, the tabs, a per-cell Cloudflare decode of `.cr-name` (`_cf_email`, `_decode_cf_emails`), `_no_dash`, and `handled_by` from `.cr-by`. 3caa393 added the row's `id`. 9ead47d replaced the per-cell decode with `decode_cf_emails` on the whole soup, which also fixed the contact lines (1,005 of them had held the stand-in).

### 4.8 `students.php?status=pending`
`parse_pending_payments(html) -> Optional[{"count", "listed", "badge"}]` (`:890`). `badge` comes from the first `a[href~=status=pending]` whose text matches `pending\s+payments?\D{0,5}(\d+)`. `listed` counts rows whose SL cell (found by header name) is a number. When both exist the badge wins (the list is paged at 50). It returns `None` when there is no badge and no SL column, or no badge and a pager showing more than one page (`Page \d+ of (\d+)` > 1): a paged list with no badge is not counted at all.

### 4.9 `window_applications.php?status=under_review`
- `parse_window_applications(html) -> Optional[List[{"student", "window", "status"}]]` (`:920`): the first table that has a Status header. The status is `.status-pill` text, else the cell text. It returns `None` when no such table exists, and `[]` when the table is empty.
- `count_under_review(rows) -> int` (`:948`): rows whose `_label_key(status) == "under review"` (so `under_review` and `Under Review` both count). This figure is kept apart from pending payments and never added to them.

### 4.10 `calendar.php`
**DOM:** section headings `.sec-h` (e.g. "Reminders for today · N items", "Upcoming") inside `.cal-card`. Reminders are `.rm-item`, with a title in `.rm-title` / `.rm-t` / the first `a`, a sub line (a `div` holding a `span` and a `·`), an optional progress line and optional notes. The same reminders repeat in a pop-up as `.rm-row`, which is **not** read, so nothing counts twice. Upcoming rows are `.ev-row`, with `.li-date` (its child divs), `.ev-main`, `.ev-title`, `.ev-sub` and `.st` (status). An entry id comes from an `a[href*="edit=N"]`, else `input[name=id]` (the Mark-done form).

| Regex | Line | Pattern |
|---|---|---|
| `_CAL_RANGE_RE` | `:1211` | `\d{1,2}\s+[A-Za-z]{3}(?:\s+\d{4})?(?:\s*[–—-]\s*\d{1,2}\s+[A-Za-z]{3}(?:\s+\d{4})?)?` |
| `_CAL_TIME_RE` | `:1212` | `\d{1,2}:\d{2}` |
| `_CAL_TIME_END_RE` | `:1213` | `(\d{1,2}:\d{2})\s*[–—-]\s*(\d{1,2}\s+[A-Za-z]{3}(?:\s+\d{4})?)`, i.e. "14:00 – 23 Oct 2026" |
| `_CAL_PROGRESS_RE` | `:1214` | `\d+\s*%\|\bdays?\s+left\b` |
| `_CAL_EMPTY_RE` | `:1215` | no reminders, items, events or tasks; nothing due or for today; all done or clear |
| `_CAL_PROGRAM_RE` | `:1217` | `\b(?:program(?:me)?s?\|klp\|eap\|bachelor'?s?\|master'?s?\|degree\|language\|phd\|diploma)\b` (also imported by `ask.py:1353`) |

| Function | Line | Contract |
|---|---|---|
| `_cal_text(tag)` | `:1220` | Whitespace-collapsed text, or `""` |
| `_cal_card(soup, heading)` | `:1224` | The `.cal-card` whose `.sec-h` starts with `heading` (by `_label_key`) |
| `_cal_sub(line) -> {"type", "date_range", "time", "where", "today"}` | `:1232` | Splits `"Application period · 21 Sep–05 Oct · 10:00 · <UNIVERSITY> · today"` on `·`. `"08 Oct · 14:00 – 23 Oct 2026"` becomes the range `"08 Oct – 23 Oct 2026"` plus the time 14:00. |
| `_cal_id(tag) -> str` | `:1259` | The portal's own event id (e164679: two events with one title stay two) |
| `_cal_reminder(item) -> Dict` | `:1272` | `{"id", "title", type, date_range, time, where, today, "progress", "days_left": int or None, "program" (the note if it looks like a program), "note"}` |
| `_cal_upcoming(row) -> Dict` | `:1297` | `{"id", "date", "type", "title", "university" (= where), "date_range", "program", "note", "status"}` |
| `parse_calendar_events(html) -> Dict` | `:1313` (soup decoded at `:1326`) | `{"today_reminders": titled reminders, "upcoming_events": titled rows, "layout_ok": entries were found or the card says there are none ("· 0 items" / an empty phrase), "upcoming_ok", "skipped_untitled", "heading_count": the stated N items}`. A reminders card whose entries are not recognised gives `layout_ok=False`, which callers show as "not available", never 0. |

History: the baseline parser returned 11 reminders with every field empty after the portal's layout change (hence the brief's "eleven deadlines"). f8fefa4 rewrote it for `rm-item` / `ev-row`; e164679 added `_cal_id`, `_CAL_TIME_END_RE` and ranges.

### 4.11 Selector cheat sheet
| Page | Selectors / regexes |
|---|---|
| `login.php` | `input[name=_csrf]` (the POST fields are `_csrf`, `username`, `password`) |
| `index.php` | `.dash-sec .ds-t`, `.stats-row`, `.stat-card[href]`, `.stat-num`, `.stat-lbl`, `a[href*=window_application_view]` |
| `students.php` | `table` first, header `th` names, `tr.stu-row`, `tr.xp-row`, `tr.empty-row`, `.stu-name`, `.stu-sub`, `.stu-uni`, `.upr`, `.det-item label/span`, `.pf.paid`, `.pf.method`, `.pf.verified`, `.pf-by strong`, `student_edit\.php\?id=(\d+)`, `showDel\((\d+)`, `progress\.php\?uid=(\d+)`, `view_doc\.php\?f=...`, pager `Page X of N · T students`. Query params used: `pg`, `q`, `status=pending`, `prog`, `stage`. |
| `student_edit.php?id=N` | every `input`, `textarea` and `select[option selected]` by name |
| `progress.php?uid=N` | `.pg-ring`, `.pg-now .pg-stage`, `.pg-now .pg-status` |
| `consult_requests.php` | `nav.cr-tabs a .n`, `a.st-*`, `.on`, `form.cr-search input`, caption `<b>N</b> requests · newest first`, `.cr-name`, `.cr-contact`, `.cr-cons`, `.city`, `.prog`, `.crd-body`, `.d`, `.t`, `.stbadge`, `.cr-by`, `textarea`, `.cr-empty`, `form input[type="hidden"][name="id"]` (the request's id), `.__cf_email__[data-cfemail]`, `a[href*="/cdn-cgi/l/email-protection#"]`. Params: `status` (all, new, file_opened...), `from`, `to` (YYYY-MM-DD). |
| `window_applications.php?status=under_review` | a table with a Status header, `.status-pill` |
| `calendar.php` | `.cal-card .sec-h`, `.rm-item`, `.rm-title`/`.rm-t`, `.ev-row`, `.li-date`, `.ev-main`, `.ev-title`, `.ev-sub`, `.st`, `a[href*=edit=N]`, `input[name=id]` |
| `consult_performance.php?period=today\|month` | `.pf-tabs a.on[href*=period=]`, `.pf-showing strong`, `.pf-dates` (`.is-hidden` = no range), `.pf-scope`, `.pf-stat .l` / `.n`, `section.pf-top` (`.pf-top-k`, `.pf-top-name`, `.pf-top-m > div > b + span`), the first `table` whose header names Consultant and Score (`table.tbl.pf` live), `.pf-name`/`strong`, `.cav`, `.pf-crown`, `.medal`, `tr.is-top`, `tr.pf-empty-row` / `.pf-empty`, `.pf-count`, `.pf-note`, `th[title]`, `dl dt` + `dd` (§4.12) |
| every page | Cloudflare: `.__cf_email__[data-cfemail]` (a or span) and `a[href*="/cdn-cgi/l/email-protection#"]`, decoded by `decode_cf_emails` before any other selector (§4.1.1) |
| `view_doc.php?f=<file>` | the binary scan (never HTML) |

### 4.12 `consult_performance.php` (the Consultant Performance page)
Added in ce23535 (30 Sep 13:34), hardened in 314afdb (14:04), soup-wrapped in e5e532e. Read by `client.read_consult_performance` (§3.8), shown by `bot\performance.py` ([03a](03a_FILES_src_bot.md), [05](05_TELEGRAM_COMMANDS_AND_JOBS.md)), published as the `consultant_performance` kind ([03d](03d_FILES_src_cloud.md)). The portal page in context: [04](04_PORTAL_INTEGRATION.md).

**DOM** (as `tests\test_performance.py:57-182`, `perf_page()` at `:132`, models the live page from the owner's 30 Sep screenshots; names here are placeholders):
```
aside.sidebar ... a[href=consult_performance.php] "Performance"; table.decoy (Menu / Leads)   <- a table the parser must skip
div.pf-bar
  nav.pf-tabs[aria-label=Period]  a[href="?period=today"] Today | a[href="?period=week"] This Week |
                                  a.on[href="?period=month"] This Month | a[href="?period=all"] All Time | label "Custom range"
  form.pf-range (GET: hidden period=custom, input[type=date] from, to, button "Apply range")  <- never used
    p.pf-showing  "Showing <strong>This Month</strong>" span.pf-dates "01 Sep – 30 Sep 2026"   (span.pf-dates.is-hidden
                                                                                              for All Time: a placeholder)
p.pf-scope  ""  (a scope note; empty for the owner/admin)
div.pf-stats  div.pf-stat > div > div.n "<figure>" + div.l "Consultancies done" | "Files opened" |
                                                        "Conversion (file open)" ("15%") | "Docs ready"
section.pf-top[aria-label="Top performer"]  .pf-top-k "Top performer · This Month"  h2.pf-top-name "<CONSULTANT>"
  div.pf-top-m  div(b "<score>", span "Score") div(b "<n>%", span "Conversion") div(b, span "Files opened")
                div(b, span "Consultancies")
div.card.pf-card  .card-title "Leaderboard" span.pf-count "<rows>"   span.pf-note "Sorted by score, highest first"
  table.tbl.pf  thead tr: th.c-rank "#" | th "Consultant" | th[title=<score formula>] "Score" | th "Conversion" |
                          th "Files Opened" | th "Consultancies" | th[title=<points formula>] "Points" | th "Docs Ready"
    tbody tr(.is-top for the leader): td.c-rank span.rank | td.c-who (span.cav initial, strong.pf-name "<CONSULTANT>",
          span.pf-crown "Top") | td span.pf-score "17.9" | td .pf-conv b "18%" | td span.pill "26" | td span.pill "146" |
          td "149.5" | td "1"
    tr.pf-empty-row td[colspan=8] div.pf-empty "No consultant activity yet ..."          (the page's empty state)
section.pf-legend[aria-label="How the numbers are worked out"]  dl.pf-defs  dt "Score" dd "..."  dt "Points" dd "..."
```
The tooltips as the tests model them: Score "Balanced score = files opened × (0.5 + conversion) × program weight"; Points "Weighted workload: Bachelor/Master/PhD ×1.5, KLP/EAP ×1". The bot shows them as the page gives them and never uses them to compute anything.

**Constants** (`parsers.py:955-990`):
| Name | Line | Value |
|---|---|---|
| `class PerformanceLayoutError(ValueError)` | `:955` | The page is not laid out the way the parser knows: nothing may be reported |
| `_PERF_COLUMNS` | `:963-972` | Ordered (key, test on `(_label_key(header), raw header)`), each key taking the **first unused** header it accepts: `rank` (key in `rank`, `no`, `pos`, `position`, `sl`, or an empty key with `#` in the raw text), `name` (starts with `consultant`, `counsellor`, `counselor`, `staff`, `name`), `score` (`score`), `conversion` (`conversion`), `files_opened` (`file`), `consultancies` (`consultanc`), `points` (`point`), `docs_ready` (`doc`, `document`) |
| `_PERF_NUMBER` | `:973` | `-?\d[\d,]*(?:\.\d+)?` |
| `_PERF_SHAPES` | `:976-984` | `rank` `\d+`; `score` and `points` `_PERF_NUMBER`; `conversion` `_PERF_NUMBER\s*%?`; `files_opened`, `consultancies`, `docs_ready` `\d[\d,]*` (full match) |
| `_PERF_TILE_SHAPE` | `:985` | `_PERF_NUMBER\s*%?` |
| `_PERF_DASHES` | `:986` | `("—", "–", "-", "--")`: the portal's "no figure", kept as it is |
| `_PERF_TOP_METRICS` | `:988-989` | `(("score", "score"), ("conversion", "conversion"), ("files_opened", "file"), ("consultancies", "consultanc"))`: the top card's figures by their labels |

**Functions:**
| Function | Line | Contract |
|---|---|---|
| `_perf_text(tag) -> str` | `:992` | Whitespace-collapsed `get_text(" ", strip=True)`, `""` for `None` |
| `_perf_value(text, shape, what) -> str` | `:996` | The figure **exactly as printed** once it full-matches `shape` (or is a dash); else `PerformanceLayoutError(f"{what} reads {text[:30]!r}, which is not a figure")` |
| `_perf_columns(header_cells) -> {key: index}` | `:1007` | `_PERF_COLUMNS` over the header cells, in order |
| `_perf_table(soup)` | `:1020` | The first `table` whose header row (`thead tr`, else its first `tr`; direct `th`/`td` children, else any) has both `name` and `score` → `(table, header, cells, cols)`, else `None`. So the sidebar's decoy table is skipped. |
| `_perf_name(cell) -> str` | `:1034` | `.pf-name`, else `strong`; else the cell's text without `.cav` (the initial), `.pf-crown` and `.medal` (on a `copy.copy` of the cell) |
| `_perf_top(soup) -> Optional[Dict]` | `:1047` | The card is `section.pf-top`, else an element whose `aria-label` starts with "top performer". Name: `.pf-top-name`, else the first `h2`/`h3`/`strong`. No card, or a card with no name or a dash (a period nobody worked in), gives `None`. `metrics` = each direct `div` of `.pf-top-m` (else of the card) that has a `b` (figure) and a `span` (label), in order. Each of score, conversion, files opened and consultancies must be found by label (`_label_key(label).startswith(word)`), else `PerformanceLayoutError("the top performer card shows no <key> (it reads [...])")`, and pass `_perf_value`. Returns `{"label": .pf-top-k text, "name", "metrics": [(label, figure)], "score", "conversion", "files_opened", "consultancies"}`. |
| `_perf_help(soup, cells, cols, key, word) -> str` | `:1075` | A column's explanation: its header cell's `title` (whitespace-collapsed), else the legend's `dl dt` whose label key starts with `word` → its next `dd`, else `""` |
| `parse_consult_performance(html) -> Dict` | `:1088` | The page, by labels, header texts and classes, never by position; soup `decode_cf_emails(BeautifulSoup(html, "html.parser"))` (`:1120`). Algorithm and shape below. |

**`parse_consult_performance` algorithm** (every "raise" is `PerformanceLayoutError`, which the client turns into "Couldn't read the portal: consult_performance.php: <why> (layout not recognised)", never 0):
1. **Tiles:** every `.pf-stat` with a `.l` (label) and `.n` (figure) → `tiles[label] = figure` (first of each label, page order; figures via `_PERF_TILE_SHAPE`). No tile at all → raise "its tiles (Consultancies done, Files opened, ...) were not found".
2. **Leaderboard table:** `_perf_table`; none → raise "its leaderboard table (a header with Consultant and Score) was not found". Every key of `_PERF_COLUMNS` must be found → else raise "the leaderboard's header has no <keys> column (it reads [...])". `columns` = `[(key or None, header text)]` in header order; a header the bot does not know is kept with key `None`.
3. **Rows:** the `tbody` rows (else the table's), minus the header and any `thead` row; rows with no cells or no text are skipped.
   - The page's own empty state: class `pf-empty-row`, or exactly one cell holding a `.pf-empty` box → `empty_text` = that text, no row.
   - Any **other** one-cell row (e.g. "Could not load the leaderboard (SQL error)") → raise "leaderboard row N is one cell that is not the page's empty state (it reads '...')". Before 314afdb any one-cell row with a `colspan` passed as "nobody is listed"; that would have shown a portal error as an empty leaderboard.
   - A cell count different from the header's → raise "leaderboard row N has X cells, its header Y".
   - Each cell by its column: `name` via `_perf_name`; a known key via `_perf_value(…, _PERF_SHAPES[key], …)`; an unknown column into `extra[header text]`. No name → raise. `top` = the row has class `is-top` or a `.pf-crown`.
   - Rows **and** an empty state together → raise.
4. **Count badge:** `.pf-count` must read as an integer (else raise) and equal the rows read (else raise "the leaderboard counts N consultants but M rows could be read"). A page without a badge passes (`count = None`).
5. **Period and the rest:** `period` = the `period` query of `.pf-tabs a.on`'s `href` (`parse_qs(urlsplit(href).query)`), or `None`; `period_label` = `.pf-showing strong`, else the open tab's text, else `None`; `range_text` = `.pf-dates` text, `""` when it is absent or has class `is-hidden`; `scope_note` = `.pf-scope`; `sort_note` = `.pf-note`; `score_help` / `points_help` via `_perf_help`; `top` via `_perf_top`.

**Returned dict:**
```
{"period": "month" | "today" | ... | None,
 "period_label": "This Month",            "range_text": "01 Sep – 30 Sep 2026",   "scope_note": "",
 "tiles": {"Consultancies done": "<n>", "Files opened": "<n>", "Conversion (file open)": "<n>%", "Docs ready": "<n>"},
 "top": {"label": "Top performer · This Month", "name": "<CONSULTANT>", "metrics": [("Score", "<x>"), ...],
         "score": "<x>", "conversion": "<n>%", "files_opened": "<n>", "consultancies": "<n>"} | None,
 "columns": [("rank", "#"), ("name", "Consultant"), ("score", "Score"), ("conversion", "Conversion"),
             ("files_opened", "Files Opened"), ("consultancies", "Consultancies"), ("points", "Points"),
             ("docs_ready", "Docs Ready")],
 "leaderboard": [{"rank": "1", "name": "<CONSULTANT>", "score": "<x>", "conversion": "<n>%", "files_opened": "<n>",
                  "consultancies": "<n>", "points": "<x>", "docs_ready": "<n>", "extra": {}, "top": True}, ...],
 "count": <int> | None,  "empty_text": "",  "sort_note": "Sorted by score, highest first",
 "score_help": "<the Score tooltip>",  "points_help": "<the Points tooltip>"}
```
Every figure is a **string as printed** ("17.9", "18%", "149.5", "1,304"), never a parsed number, so the reply and Supabase show exactly what the page shows. Verified offline at 8317741 on a synthetic two-row page: the shape above, and the two raises for a count badge of 3 with 2 rows and for a header "Rate" in place of "Conversion".

**Tests:** `tests\test_performance.py` (52 test functions: the live layout, the period guard, the layout guards, the three accepted empty-state forms, the portal error row, whole-record message splitting for 56 and 120 consultants, the free-text spellings) and `tests\test_cloud_performance.py` (20: the `consultant_performance` records). The whole suite has 1152 tests at 8317741, 2 of which skip by design in the live checkout (`test_cloud.py:893`, `test_cloud_bot_jobs.py:620`: "this checkout has a .env (or Supabase settings in the environment): the child could publish") ([10](10_TESTS_AND_VERIFICATION.md)).

---

## 5. `src\scraper\ocr_validator.py`: passport-scan OCR and verdicts

### 5.1 Purpose
It checks a student's portal entries (name, DOB, passport number, expiry, father, mother, address) against the uploaded passport scan, read live by local OCR. The module docstring (`:1-31`) is the spec. Logger: `hangeul.ocr`. Callers: `client.audit_student_passport` (in a worker thread), and through it the 30-minute passport watcher in `scheduler.py`, the `/crosscheck*`, `/audit` and `/passports` commands, and `audit_program.py`. **This is not the document verifier:** `src\verify\doc_verifier.py` is a separate EasyOCR pipeline that runs on the GPU.

### 5.2 Constants
| Name | Line | Value |
|---|---|---|
| `MRZ_LINE_LEN` | `:44` | 44 (ICAO 9303 TD3: two lines of 44 characters) |
| `MRZ_MIN_CONF` | `:45` | 0.3; below this OCR confidence a line-1 read is low-confidence |
| `OCR_WIDTH`, `OCR_MAX_SIDE` | `:46-47` | 1600 px wide at most, 2400 px on the long side at most (`cv2.INTER_AREA`) |
| `ROTATIONS` | `:49` | `((0, None), (270, ROTATE_90_COUNTERCLOCKWISE), (90, ROTATE_90_CLOCKWISE), (180, ROTATE_180))`: upright first, then 270, because PDF pages are mostly stored a quarter-turn sideways |
| `MRZ_UNREADABLE_NOTE` | `:51` | "couldn't read the MRZ (the photo may be rotated or blurred, or it may not be a passport); please check the scan by eye" |
| `FIELD_ORDER` | `:54` | `("name", "dob", "passport_no", "expiry", "father_name", "mother_name", "address")` |
| `FIELD_LABELS` | `:55` | Name, DOB, Passport No, Expiry, Father, Mother, Address |

### 5.3 The OCR engine
- `get_ocr_reader()` (`:70`) lazily builds `easyocr.Reader(['en'], gpu=False, verbose=False)`: **English only, on the CPU.** It uses double-checked locking under `_ocr_lock`. On failure it logs and returns `None`, and the audit becomes `OCR_UNAVAILABLE`. The docstring says "GPU support or CPU fallback", but the code is CPU-only, as it has been since the baseline. The CPU keeps the 8 GB RTX 5060 for Ollama and for the GPU EasyOCR in `doc_verifier.py` (`gpu=torch.cuda.is_available()`). `verbose=False` matters: with the default progress bar, the first model download crashed a cp1252 Windows console (d659983 fixed the same issue in `doc_verifier`; this module already had it). The models are cached in `C:\Users\User\.EasyOCR\model` (`craft_mlt_25k.pth`, `english_g2.pth`).
- `_ocr_lock = threading.RLock()` (`:67`). `validate_passport_data` holds it for the whole audit, and `_ocr_items` takes it again around `reader.readtext`. So audits run one at a time even from worker threads. The shared reader is never used by two threads, and a PDF's `<name>_extracted.jpg` is never written while another audit reads it (7241465).

### 5.4 Loading and preparing the page
- `load_passport_image(image_path) -> Optional[np.ndarray]` (`:128`). For a `.pdf` it reuses `<base>_extracted.jpg` if that is over 1000 bytes. Otherwise it writes each embedded image of each page (`pypdf.PdfReader(...).pages[i].images`) to that file until `cv2.imread` accepts one. If that fails it falls back to `cv2.imread(path)`. It returns `None` for a missing or unreadable file.
- `_prepare(img)` (`:157`) resizes to fit the limits above.
- `_ocr_items(reader, img) -> [{"text", "conf", "box": (x0, y0, x1, y1)}]` (`:169`) uses `reader.readtext(img, detail=1)`. A reader that returns bare strings gives items with no confidence and no box.
- `_clean_mrz(text)` (`:190`): upper case, whitespace removed, `«` → `<<`, `‹` → `<`, and only `A-Z0-9<` kept.
- `_rows(items) -> List[List[item]]` (`:196`) groups items into lines top to bottom (same line when the vertical centres are within 0.5 × the taller height), each sorted left to right. If any item lacks a box, each item is its own line.

### 5.5 MRZ parsing and check digits
- `compute_icao_check_digit(data) -> str` (`:109`): weights 7, 3, 1 repeating. A digit counts as its value, `A`–`Z` as 10–35, and `<` or anything else as 0. The result is the sum mod 10, and `"0"` for empty input (the ICAO sample `L898902C3` gives `6`).
- `parse_mrz_date(yymmdd, is_expiry=False) -> "YYYY-MM-DD" or ""` (`:87`). DOB: 20yy if `yy <= current yy`, else 19yy. Expiry: 20yy if `yy <= current yy + 40`. An impossible calendar date gives `""`.
- Translation tables (`:214-219`):
  - `_L1_RE = P[<KC(]?([A-Z]{3})([A-Z0-9<]*)`: "P", an optional type character (or an OCR misread K, C or `(`), the 3-letter state, then the name.
  - `_NAME_DIGITS`: 8→B, 0→O, 1→I, 5→S, 2→Z, in name fields.
  - `_TO_DIGIT`: O, D, Q, U→0; I, L→1; Z→2; S→5; B→8; G→6; T→7, in number fields.
  - `_TO_LETTER`: 0→O, 1→I, 5→S, 8→B, 2→Z, 6→G, 4→A, for nationality.
  - `_SWAPS` (one-character repairs): 4↔1, O↔0, B↔8, S↔5, Z↔2, I→1, D→0, G↔6.
- `parse_mrz_line1(text) -> Optional[Dict]` (`:222`) returns `{"line1", "line1_ok", "state", "surname", "given_name", "full_name", "name_tokens"}`. It returns `None` if the match starts after index 2 or the text has fewer than two `<`. `line1_ok` requires exactly 44 characters, `fullmatch P[<A-Z][A-Z]{3}[A-Z<]{39}`, a `<<` after position 5, and a name of the form `[A-Z]+(<[A-Z]+)*(<<[A-Z]+(<[A-Z]+)*)?<*`.
- `_repair_doc_number(raw, chk) -> (number, ok)` (`:248`): the number as read. If the check fails, it tries a leading 4, 8 or 0 as `A` (Bangladeshi numbers start with a letter), then each single `_SWAPS` swap.
- `_line2_at(seg)` (`:265`) reads TD3 line 2 at its fixed positions:

| Slice | Field | Check |
|---|---|---|
| `[0:9]` | passport number | `[9]` (via `_repair_doc_number`) |
| `[10:13]` | nationality (`_TO_LETTER`) | none |
| `[13:19]` | DOB (`_TO_DIGIT`) | `[19]` |
| `[20]` | sex M/F → `"MALE"`/`"FEMALE"`/`""` | none |
| `[21:27]` | expiry | `[27]` |
| `[28:42]` | personal number | `[42]` (an all-`<` field accepts `<` or `0`) |
| `[43]` | composite over doc+chk+dob+chk+exp+chk+pers+chk | itself |

It returns `{"line2", "passport_no", "passport_no_ok", "check_digit", "nationality", "dob", "dob_raw", "dob_ok", "sex", "expiry", "expiry_raw", "expiry_ok", "line2_ok" (44 characters and all five checks), "checks": count of (doc, dob, exp, composite) ok}`.
- `_L2_ANCHOR_RE = (?=[A-Z<]{3}[0-9ODQUILZSBGT]{7}[MF<])` (`:297`): the nationality, DOB and check digit, then the sex. It finds line 2 even when the passport number was read one character short or long.
- `parse_mrz_line2(text) -> Optional[Dict]` (`:300`). With at least 28 characters, it builds candidates at start offsets 0–3, plus one at each anchor minus 10. If that start is negative, the text is padded with `<` and the passport number is marked not ok. It returns the first candidate with the most checks, or `None` if the best has no check that agrees.
- `_find_mrz(items) -> (mrz or None, ids of the items used)` (`:324`). Line 1 is the first piece on a row that matches `P[<KC(]?[A-Z]{3}` with at least 20 joined characters; `line1_conf` = the minimum confidence of its pieces. Line 2 is searched in the 2 rows after line 1, or else as the row with the most checks (at least 2). The merged dict has every key above plus `"valid" = line1_ok and line2_ok`.

### 5.6 Reading a scan
`read_passport_scan(image_path) -> Dict` (`:375`) returns `{"mrz": dict or None, "printed": the other text pieces in reading order, "words": set of [A-Z]+ words printed, "rotation": the angle the MRZ was found at, "tried": [angles read], "error": None | "image" | "ocr"}`. It OCRs the whole page at 0, 270, 90 and 180 degrees, stopping at the first turn where an MRZ is found. `mrz["rotation"]` is set. With no MRZ at any turn, `printed` is the upright reading. Wrappers: `extract_mrz_from_image(path)` (`:415`) gives the `"mrz"` value or `None`; `extract_visual_fields_from_image(path)` (`:538`) runs `parse_visual_text_lines` on the printed text, with empty defaults on error.

History: the baseline cropped the bottom 30% of an upright page and needed a literal `P<`. So rotated PDFs and phone photos were reported as "not a valid passport". The baseline also shipped `AUDIT_REGISTRY`, a hard-coded "pre-audited" ledger dated 10 Sep 2026 that `/passports` printed as if it were current. Both were removed in 40da0e6, and every result now comes from the live scan.

### 5.7 The printed page (data page and emergency page)
`parse_visual_text_lines(lines) -> {"father", "mother", "address", "visual_passport_no", "has_emergency_page", "emergency_name", "emergency_rel"}` (`:422`). Its regexes tolerate OCR noise:
- The emergency section starts at a line matching `emergency\s+contac` (and not `personal data`). Within the next 8 lines it reads `relationship` and the name (`\bnam[ea]s?\b`), taking the value after `:` or `.`, or the next line.
- Father: `father['’s$\s]*nam`, `fathcn\W*nan` or `fath[a-z]*...nam`. It takes up to 2 lines, stopping at mother, guardian or address words.
- Mother: `m[o0]ther...nam`, `kotner` or `koth`, or a line that is exactly `mo`. It skips `ther$` / `name$` fragments and stops at guardian, address or father words.
- Address: `perman[a-z]*\s+add?r`, up to 3 lines.
- The printed passport number is the first `\b([A-Z][0-9]{8})\b`.
- If the emergency relation is FATHER or MOTHER and the parent read is empty or shorter, the emergency name replaces it.

### 5.8 Comparing names and addresses
- `_HONORIFICS = {MD, MST, MR, MRS, MISS, MOHAMMAD, MOHAMMED, MOSTAFA, LATE}` are set aside when comparing. `_FILLER_LIKE = <KCSLEX` are letters the MRZ filler `<` is often read as.
- `_levenshtein(a, b)`: edit distance.
- `_split_merged(token, known)`: a token that is known names run together with the `<` read as a letter (e.g. `<GIVEN>K<SURNAME>` gives the two names), or one name with trailing filler letters, is split. Extra letters in front of a single name are not split (that may be a real spelling).
- `_name_diff(portal, doc) -> {"kind": "match" | "near" | "far", "overlap": bool, "differing": [...]}`. `match` means the same names, or one side has extra names. `near` means every differing name is one edit away.
- `compare_names(portal_name, doc_name, *, source="scan", trusted=False, printed=None) -> (status, message)` (`:626`):

| Status | When |
|---|---|
| `NOT_IN_SCAN` | nothing read on the document |
| `MISSING_PORTAL` | the portal field is blank |
| `NOT_READ` | the document name has no letters; or an MRZ name that is untrusted and "far" |
| `MATCH` | `_name_diff` is `match` (honorifics and extra names allowed) |
| `MISMATCH` | printed-page source: `far` with no overlap. MRZ source: `trusted` (or confirmed by the printed words) and `far` with no overlap. |
| `TYPO` | MRZ source: `trusted` or confirmed, and not a no-overlap far difference |
| `OCR_UNCERTAIN` | printed source: `near`, or `far` with some overlap. MRZ source: the page's printed words contain every portal name (the MRZ reading is the odd one out), or `near` and untrusted. |

- `compare_address(portal_addr, portal_dist, doc_addr) -> (status, message)` (`:673`) compares tokens of 3 or more characters `[A-Z0-9]`. It gives `MATCH` when the district token is on the document or at least 2 tokens overlap, `PARTIAL_MATCH` for 1, `MISMATCH` for 0, plus `NOT_IN_SCAN` and `MISSING_PORTAL`.

### 5.9 The audit
- `validate_passport_data(student_id, form_data, image_path=None, live_audit=True) -> Dict` (`:739`) takes `_ocr_lock`, then calls `_validate_passport_data`. `live_audit` is kept for old callers; there is no registry to fall back on.
- `_validate_passport_data` (`:767`), in order:
  1. No file: `MISSING_DOCUMENT`, verdict "⏳ Pending Passport Scan (No document on file)", discrepancy "No passport document scan uploaded on file".
  2. `scan.error == "ocr"`: `OCR_UNAVAILABLE`, "❌ Couldn't run the OCR engine on this computer, so the scan was not checked".
  3. `scan.error == "image"`: `SCAN_UNREADABLE`, with that note as its discrepancy.
  4. No MRZ at any turn: `MRZ_UNREADABLE`, `mrz_data = {"tried_rotations": [0, 270, 90, 180]}`, discrepancy `MRZ_UNREADABLE_NOTE`. It is **never** "not a passport".
  5. Otherwise, a per-field comparison:

| Field (form_data key) | Source on the scan | MATCH | Discrepancy (confirmed) | Uncertain (check by eye) |
|---|---|---|---|---|
| Passport No (`passport_no` or `passport_number`) | MRZ line 2 (or the printed number) | MRZ number or printed number equals the portal; **or** the portal number fits the MRZ check digit and the read differs by ≤ 1 edit (≤ 2 if the MRZ number's own check failed): "✅ Match (MRZ check digit)" | `pass_ok` and different: `MISMATCH` "Passport No mismatch: Portal has '…', Doc has '…'" | check digit failed: `NOT_READ` |
| DOB (`dob`, YYYY-MM-DD) | MRZ | the same (check ok, or the read equals the portal even with a failed check) | check ok and different: `MISMATCH` | check failed and different: `NOT_READ` |
| Expiry (`passport_expiry`) | MRZ | as DOB | blank on the portal: `INCOMPLETE` "⚠️ Incomplete: Expiry date left blank on portal (MRZ says …)"; check ok and different: `DATE_MISMATCH` | `NOT_READ` |
| Name (`name` or `full_name`) | MRZ line 1, `trusted = valid MRZ and (line1_conf is None or ≥ 0.3)` | `compare_names(source="mrz", printed=words)` | `TYPO` or `MISMATCH` → "Name spelling issue: Portal has '…', MRZ has '…'" | `OCR_UNCERTAIN`, `NOT_READ` (with no line 1: "Couldn't read MRZ line 1 (the name), check by eye") |
| Father / Mother (`father_name`, `mother_name`) | printed page | `compare_names(source="scan")` | `MISMATCH` → "Father's Name discrepancy: …" | `OCR_UNCERTAIN`, `NOT_READ` |
| Address (`address` + `district`) | printed page | `compare_address` | `MISMATCH` | `PARTIAL_MATCH` |

  6. The overall `status`: any discrepancy gives `TYPO` if any discrepancy text contains "Typo" or "spelling" (so **any** name discrepancy, even a MISMATCH, makes the whole result `TYPO`), else `DISCREPANCY`. No discrepancy but some uncertain items gives `CHECK_BY_EYE`. Otherwise `MATCH`. `is_valid = not discrepancies`.
- `_date_field(portal, read, ok, label)` (`:753`): the date rule above.
- `unchecked_result(student_id, reason)` (`:707`) gives `PORTAL_UNREADABLE`, verdict "❌ Couldn't read the portal: <reason>. The passport was not checked.", with no discrepancy.
- `build_verdict(fields, discrepancies, uncertain) -> str` (`:715`) joins with " · ": "⚠️ Discrepancy Found: a; b", "🔎 Check by eye: …", then "✅ 100% Match across All Fields (Name, DOB, Passport No, Expiry, Father, Mother, Address)" only when all 7 match (else "✅ Match: <labels>"), "ℹ️ Not on the scan: …", "ℹ️ Blank on the portal: …". With nothing to say it is "ℹ️ Nothing could be compared".
- `_result(...)` (`:700`) builds the **result dict**: `{"student_id", "status", "is_valid", "fields": {name, passport_no, dob, expiry, father_name, mother_name: {"portal", "doc", "status", "verdict"}, address: {+ "district"}}, "mrz_data": the MRZ dict (+ rotation, line1_conf, valid), "visual_data": the parse_visual_text_lines dict, "discrepancies": [str], "uncertain": [str], "verdict": str}`.

### 5.10 Every result status
| Status | Checked? | discrepancies | Watcher behaviour (`scheduler.py`) |
|---|---|---|---|
| `MATCH` | yes | [] | recorded, no alert |
| `CHECK_BY_EYE` | yes | [] (only `uncertain`) | recorded, no alert |
| `TYPO` | yes | ≥ 1 (name spelling) | alert |
| `DISCREPANCY` | yes | ≥ 1 | alert |
| `MRZ_UNREADABLE` | the OCR ran | [note] | alert ("check the scan by eye") |
| `SCAN_UNREADABLE` | no | [note] | alert |
| `MISSING_DOCUMENT` | no | [no scan] | in `UNCHECKED_STATUSES`: not recorded, retried next run |
| `OCR_UNAVAILABLE` | no | [] | in `UNCHECKED_STATUSES`: retried |
| `PORTAL_UNREADABLE` | no | [] | in `UNCHECKED_STATUSES`: retried |

`UNCHECKED_STATUSES = ("MISSING_DOCUMENT", "PORTAL_UNREADABLE", "OCR_UNAVAILABLE")` is defined at `scheduler.py:39`. (`ocr_validator.py` itself is unchanged at 8317741. After each run the watcher now also hands its reads to Supabase: the student list, this run's audit results as `passport_audit` records and its memory as `passport_alert` records, built in a worker thread and published by a separate process; see `cloud\bot_jobs.py` in [03d](03d_FILES_src_cloud.md).) The watcher alerts when `not is_valid and discrepancies`. `telegram_bot.py` adds its own `"ERROR"` status for an exception during a cross-check.

**Discrepancies vs uncertain:** `discrepancies` holds confirmed differences a person must fix: a check-digit-valid MRZ field that differs, a blank expiry, a name the valid MRZ or the printed page spells differently, a parent's name with no overlap, a missing or unreadable scan. `uncertain` holds "check by eye" items: a failed check digit, a one-letter difference on a weak read, an MRZ name the printed page contradicts, a parent's name that partly matches, a partial address. Uncertain items are never shown as portal errors.

**Known deferred issue** (found 28 Sep evening; the owner said "not now"): a garbled line 2 whose passport-number check digit passes by chance is reported as a confirmed "Passport No mismatch", even when the nationality is nonsense and the DOB and expiry checks fail. The planned fix, in `_validate_passport_data`: trust `passport_no_ok` only when line 2 is otherwise sane (the nationality equals line 1's state, or at least 2 check digits agree), flag a one-character printed-page difference, and name the scan file, its upload date and a view_doc link in the watcher alert.

Tests: `tests\test_crosscheck.py` (synthetic pages and a stub OCR engine), `tests\test_watcher_nonblocking.py` (the loop keeps ticking during an audit; a new upload is saved once).

---

## 6. `src\scraper\mock_data.py`
Made-up demo data (fictional names, `example.com` addresses, placeholder `+8801…` phones), used only when `MOCK_MODE=true`:
- `MOCK_DASHBOARD_STATS`: `{"status", "portal", "last_synced", "summary": {total_applicants, active_applications, visa_approved_ytd, pending_document_verification, klp_language_students, degree_programs{bachelors, masters, phd}, monthly_new_inquiries, intake_pipeline{...}}, "consultations_today", "performance", "verified_admissions_today", "pending_payments", "recent_activities": [{timestamp, action, student, program}], "urgent_alerts": [{level, message}]}`. Its shape predates the live parser and has no `tiles`.
- `MOCK_APPLICATIONS`: 6 dicts `{"id": "HNG-2026-941..946", "student_name", "email", "phone", "program", "target_university", "target_intake", "topik_level", "visa_type", "status", "documents_verified", "financial_solvency", "created_at"}`.
- `MOCK_INQUIRIES`: 3 dicts `{"id": "INQ-50x", "lead_name", "phone", "email", "interested_program", "status", "consultant_assigned", "inquiry_date", ...}`.

Used by `client.py` only. Danger: `MOCK_MODE` defaults to `True` in code, so a `.env` without `MOCK_MODE=false` runs on this invented data (MIGRATION.md warns about this).

## 7. `src\scraper\__init__.py`, `src\llm\__init__.py`, `src\api\__init__.py`, `src\api\routes\__init__.py`
One-line docstrings each ("Scraper and HTTP session management module.", "Local LLM client and prompt templates module.", "FastAPI Application module.", "API routes package."). No code.

---

## 8. `src\llm\ollama_client.py`: the local LLM

### 8.1 Purpose and design
It is an async client for Ollama at `settings.OLLAMA_BASE_URL`, model `qwen3:4b-instruct` (`ollama list` also still shows `qwen2.5:7b`, the pre-28 Sep model). Logger: `hangeul.llm`. **The LLM never writes a figure.** Typed questions only *pick* numbered facts, which are then shown word for word. The daily brief is built in code (`src\bot\brief.py`), and the LLM adds only one summary sentence that is checked against the facts. The old LLM-written brief invented passport numbers, visa counts and rates, and was removed in f8fefa4. The same rule governs the new performance commands: they show the portal's own Consultant Performance page and no LLM touches them (§4.12).

**Operating state at 8317741 (30 Sep 2026).** Both files are byte-identical to c17d887; what changed is how they run:
- **Voice off, brain on demand.** `JENNIE_VOICE_ENABLED=false`, `JENNIE_SPOKEN_BRIEF=false`, `BRAIN_ALWAYS_LOADED` unset, so `brain_pinned()` is `False` and every call sends `keep_alive="5m"`: the model loads for a question (about 3 s) and Ollama unloads it after 5 idle minutes, leaving the RTX 5060 at about 1.0-1.2 GB used. At start-up `telegram_bot.post_init` releases any copy an earlier run pinned (`telegram_bot.py:2355-2365`, `ollama_client.unload()` as the task "brain-release"). The voice service stays down: its watchdog task `JennieVoiceWatchdog` is Disabled and `JennieVoice.lnk` was moved to `C:\Hangeul\JARVIS\disabled`.
- **Start-up race after a reboot.** On 30 Sep 20:35 the PC rebooted and the bot came up before Ollama, so the start-up health check (`run.py:48-57` `check_ollama_status()`, called at `:76`) found it unreachable and printed its "Ollama Standby: Ollama not detected at http://localhost:11434 ..." line (the URL in that text is hard-coded and stale; the client uses `OLLAMA_BASE_URL`, 127.0.0.1). Nothing is cached from that check: once Ollama is up the next question reaches it, and until then `ask.py` answers from `_answer_query_fallback`. (The HangeulBotWatchdog also started a second bot copy, which stopped itself.) A fix was offered (wait up to 60 s for Ollama at start-up; a watchdog grace period after boot); the owner has not answered, so nothing changed ([11](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)).
- **The second model on this PC is not an LLM.** `src\cloud\embed.py` runs `thenlper/gte-small` (settings `CLOUD_EMBED_MODEL` / `CLOUD_EMBED_REVISION`, §1.3) through sentence-transformers, **on the CPU only**, in separate publisher, backfill and full-picture processes that set `CUDA_VISIBLE_DEVICES=-1` before torch is imported (`""` does not survive on Windows, so an empty value let torch see the GPU until 752cd53). It never goes through Ollama and never takes VRAM from it or from the document OCR ([03d](03d_FILES_src_cloud.md)).

### 8.2 Constants and module functions
| Name | Line | Value / contract |
|---|---|---|
| `AGENT_MAX_TOKENS` | `:14` | 60 (`num_predict` for the fact pick) |
| `AGENT_TIMEOUT` | `:15` | 30.0 s |
| `AGENT_MAX_FACTS` | `:16` | 5 (the prompt says at most 4; the code caps at 5) |
| `_LABEL_STOP` | `:18` | Stop words: a, an, the, of, to, for, in, on, and, or, by, at, with, is, are |
| `_label_words(text)` | `:21` | Lower-case words with a plural `s` dropped and stop words removed |
| `KEEP_ALIVE` | `:34` | -1 (never unload) |
| `brain_pinned() -> bool` | `:37` | `JENNIE_VOICE_ENABLED or BRAIN_ALWAYS_LOADED` (currently False) |
| `keep_alive()` | `:42` | `-1` if pinned, else `BRAIN_IDLE_UNLOAD or "5m"` (currently `"5m"`) |
| `TEMPERATURE` | `:45` | 0.3 |
| `ANSWER_BUDGET_TOKENS` | `:52` | 512, the room left for the answer |
| `CHARS_PER_TOKEN` | `:55` | 2.4. Measured with qwen3's tokenizer: 2.43 characters per token for the portal-data prompt, 2.81 for the brief, about 4 for plain English. |

Why `prompt_fits` exists: Ollama silently truncates a prompt longer than `num_ctx`, keeping about its last half (measured: every over-long prompt came back as 1538 tokens at 3072). The system prompt holding the data is then lost, and `prompt_eval_count` cannot reveal it, so the prompt is measured before it is sent.

### 8.3 `class OllamaClient` (singleton `ollama_client`, `:274`)
`__init__` (`:65`): `base_url`, `model`, `num_ctx = int(settings.OLLAMA_NUM_CTX)`, `client = httpx.AsyncClient(timeout=60.0)`.

| Method | Line | Ollama HTTP | Contract |
|---|---|---|---|
| `options(num_predict=None) -> Dict` | `:71` | none | `{"temperature": 0.3, "num_ctx": 3072[, "num_predict": n]}`. Every call sends the same set, because a changed load option reloads the model. `num_predict` does not reload it. |
| `_payload(num_predict=None, **fields)` | `:78` | none | `{"model", "stream": False, "keep_alive": keep_alive(), "options": ..., **fields}` |
| `prompt_fits(what, *texts) -> bool` | `:82` | none | `sum(len)/2.4 <= num_ctx - 512`; else it logs a warning and returns False |
| `_check_used(what, data)` | `:94` | none | Warns when `prompt_eval_count >= num_ctx - 512` |
| `async check_health() -> Dict` | `:103` | `GET /api/tags` (5 s) | `{"reachable": True, "models_installed", "target_model", "target_model_ready": any(model in name)}` or `{"reachable": False, "error": "...", "target_model", "target_model_ready": False}` |
| `async generate_response(prompt, system=None) -> str` | `:127` | `check_health()`, then `POST /api/generate` `{..., "prompt", "system"?}` | The response text; on any failure `_fallback_response()`, a canned Markdown note ("Local Ollama service is not currently responding..."). Caller: `telegram_bot._ai_write_email` (`/sendmail`, `telegram_bot.py:1330`), which detects that note and uses a template instead. |
| `async chat(messages, format=None, num_predict=None, timeout=None) -> Optional[str]` | `:151` | `POST /api/chat` `{..., "messages", "format"?}` | The reply text, or `None` on any failure (never raises). `format` is `"json"` or a JSON schema. Callers: `brief.py:550` (summary line), `voice.py:541` and `:991` (Jennie's routing and reply; not reached while the voice is off). |
| `async residency() -> Dict` | `:172` | `GET /api/ps` (5 s) | `{"loaded", "on_gpu": size_vram >= size > 0, "size_gb", "vram_gb", "num_ctx": context_length}`; unreachable gives `{"loaded": False, "on_gpu": False, "reachable": False}` |
| `async warm_up() -> Dict` | `:187` | `POST /api/generate` `{"prompt": ""}` (120 s) | Loads the model; returns `residency()` plus `"seconds"`; never raises. Caller: `scheduler.warm_brain` (only when pinned). |
| `async unload()` | `:202` | `POST /api/generate` `{"model", "keep_alive": 0}` (30 s) | Frees VRAM now. Callers: `scheduler.warm_brain` and `keep_brain_warm` (reload when the model sits partly on the CPU); `telegram_bot.post_init` releases a copy pinned by an earlier run when not pinned. |
| `async answer_agent_query(query, facts) -> Optional[List[str]]` | `:214` | `chat(format=AGENT_SCHEMA, num_predict=60, timeout=30)` | See below |
| `_answer_query_fallback(query, facts) -> List[str]` | `:250` | none | The facts whose whole label is named in the question. The label is the text before the last `:`, without `( ... )` and before `" — "`. Up to 5. `ask.py` tries this **first**, and it is all there is while Ollama is down. |
| `_fallback_response(prompt) -> str` | `:265` | none | The canned "Ollama not responding" text |

**`answer_agent_query` flow:**
1. Drop empty facts; no facts gives `[]`.
2. Number them `"1. <fact>"`. The user message is `"Facts:\n<numbered>\n\nQuestion: <query>\n\nJSON:"`.
3. If `prompt_fits("agent", SYSTEM_AGENT_CHAT, user)` fails, return `None`.
4. Call `chat` with the system and user messages. An empty reply gives `None`.
5. Parse with `json.loads`, else the first `{...}` block. Anything other than a dict with a list under `facts` gives `None`.
6. `answered is False` gives `[]`.
7. Keep the unique integer indices within `1..len`, excluding booleans, sorted, and return the first 5 matching facts.

Caller: `ask.py:1055` (`answer_unknown`, `:1038`; it tries `_answer_query_fallback` first at `:1052`). The facts are the dashboard tiles and cards (`ask.dashboard_facts`, whose soup is Cloudflare-decoded), e.g. `"Open windows (Admissions flow): 3"`. No raw inquiry dicts, contacts or remarks ever go into a prompt (7f42ad0). Free text about performance never reaches the LLM: `ask.classify` routes it (including the owner's spelling "performence") to the performance commands before `answer_unknown` ([03a](03a_FILES_src_bot.md)).

### 8.4 History
- Baseline: `generate_executive_report` plus a 100-line `_generate_structured_report_fallback`, and an `answer_agent_query(query, context: dict) -> str` that let the LLM write free answers from portal dicts; `num_ctx` 4096; `qwen2.5:7b`.
- d7a5817: an optional `keep_alive` on `generate_response`, so the voice summary could release VRAM before TTS.
- d9bbecc: one option set, `KEEP_ALIVE=-1`, `chat()`, `residency()`, `warm_up()`, `unload()`, `prompt_fits`.
- f8fefa4: the executive report was removed (the brief is built in code).
- 7f42ad0: `answer_agent_query` became fact-picking, and the fallback became label matching.
- c17d887: `brain_pinned()` and `keep_alive()`, i.e. the model loaded on demand while voice is off. The GPU idles at about 1.0-1.2 GB.
- c17d887..8317741: no change to `src\llm\` (the 20 commits touched only its callers' line numbers and the operating state above).

## 9. `src\llm\prompts.py`
- `SYSTEM_AGENT_CHAT` (`:7-11`), verbatim, a 5-line triple-quoted string (the line breaks are part of it; the same text is in [06 §2.1](06_LLM_AND_JENNIE_VOICE.md)):

```text
You help the office of Hangeul Korean Language & Visa (a study-in-Korea agency in Dhaka) find figures on its admin portal.
You get numbered facts, each one figure read live from the portal dashboard, and a question.
Pick the facts that answer the question directly, at most 4. Never answer the question yourself, never calculate, add or compare figures, and never pick a fact that is only loosely related.
If no fact answers the question, pick none.
Answer with JSON only: {"facts": [the numbers of the facts you picked], "answered": true if they answer the question, else false}.
```
- `AGENT_SCHEMA` (`:13`): `{"type": "object", "properties": {"facts": {"type": "array", "items": {"type": "integer"}}, "answered": {"type": "boolean"}}, "required": ["facts", "answered"]}`. It is passed as Ollama's `format`, which constrains the output.
- History: the baseline had `SYSTEM_EXECUTIVE_REPORT` (a 4-section template with fake examples) and an agent prompt with a `{context}` slot, plus `build_report_prompt` and `build_chat_prompt`. f8fefa4 and 7f42ad0 removed them all.

---

## 10. `src\api\`: the REST API

### 10.1 `src\api\main.py`
- `logging.basicConfig(level=INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")` runs at import. Logger: `hangeul.api`.
- `lifespan(app)` (`:16`, `asynccontextmanager`): logs "Starting Hangeul Admin API (Mock Mode: …)", yields, then `await admin_client.close()` at shutdown.
- `app = FastAPI(title="Hangeul Korean Language & Visa — Admin API", version="1.0.0", docs_url="/docs", redoc_url="/redoc", lifespan=lifespan)`.
- `CORSMiddleware(allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])`.
- The routers `auth`, `dashboard`, `applications` and `crawler` are mounted with `prefix="/api"`.
- `GET /` (`:47`) returns `{"portal": "Hangeul Korean Language & Visa - Admin API", "docs_url": "/docs", "mock_mode", "target_url": HANGEUL_BASE_URL, "endpoints": [the 9 /api paths]}`.
- `GET /healthz` (`:67`) returns `{"status": "ok", "mock_mode"}`.

### 10.2 Every endpoint
| Method + path | Handler | Client call | Portal traffic (live) | Response | On failure |
|---|---|---|---|---|---|
| `GET /` | `main.root` | none | none | the dict above | none |
| `GET /healthz` | `main.health_check` | none | none | `{"status": "ok", "mock_mode"}` | none |
| `GET /docs`, `/redoc`, `/openapi.json` | FastAPI | none | none | Swagger / ReDoc / schema | none |
| `GET /api/auth/csrf` | `auth.get_csrf` (`auth.py:7`) | `get_login_page()` | GET `login.php` | `{"status_code", "current_url", "csrf_token", "cookies", "mock"}` | `{"error", "unreachable", "mock"}` with HTTP 200 |
| `POST /api/auth/login` | `auth.login` (`:12`), body `LoginRequest {username?, password?}` | `login(username, password)` (the .env credentials when omitted) | GET + **POST** `login.php` | `LoginResponse {success, message, role?, mock?, error?}` | HTTP 401 `detail=<error>` |
| `GET /api/auth/status` | `auth.auth_status` (`:20`) | attributes | none | `{"authenticated", "mock_mode", "base_url"}` | none |
| `GET /api/dashboard/stats` | `dashboard.get_dashboard_stats` (`dashboard.py:6`) | `get_dashboard()` | GET `index.php` | the §4.3 dict (mock: `MOCK_DASHBOARD_STATS`) | `{"error": reason}` with HTTP 200 |
| `GET /api/dashboard/alerts` | `dashboard.get_dashboard_alerts` (`:11`) | `get_dashboard()` | GET `index.php` | `{"alerts": dash.urgent_alerts or dash.alerts or []}`. The live parser has neither key, so it is **always `[]` live**; mock mode gives the 2 mock alerts. | `[]` |
| `GET /api/applications?status=&intake=` | `applications.get_applications` (`applications.py:7`) | `get_applications(status, intake)` | students.php: page 1, or every page with a filter | list of student records (§4.4.4), substring-filtered | `PortalUnavailable` is not caught, giving **HTTP 500** |
| `GET /api/applications/inquiries` | `applications.get_inquiries` (`:15`) | `get_inquiries()` → `get_consultation_requests("today")` | GET `consult_requests.php` (unfiltered, about 2 MB) | today's consultation rows (§4.7 shape; mock: `MOCK_INQUIRIES`) | `[]` (looks like zero) |
| `GET /api/applications/consultations?date=today` | `applications.get_consultations` (`:20`) | `get_consultation_requests(target_date=date)` | same | rows whose `received` contains `DD Mon YYYY`. Only the newest 500 requests are visible, so older days read `[]`. | `[]`, also for an unreadable date |
| `POST /api/crawler/parse-page` body `{"path": "payments.php"}` | `crawler.crawl_admin_page` (`crawler.py:7`) | `crawl_page(path)` | GET `<base>/<path>`: **any path** | `{"status_code", "url", "tables", "dashboard_summary": None}`; mock: `{"mock", "requested_path", "status": "success", "tables": [1 sample]}` | `{"error": str(e)}` with HTTP 200 |

Router tags: "Authentication", "Dashboard", "Applications & Leads", "Generic Table & Page Crawler".

### 10.3 `src\api\schemas.py`
| Model | Fields | Used by |
|---|---|---|
| `LoginRequest` | `username: Optional[str]`, `password: Optional[str]` | `/api/auth/login` body |
| `LoginResponse` | `success: bool`, `message: str`, `role: Optional[str]`, `mock: Optional[bool]=False`, `error: Optional[str]` | `/api/auth/login` `response_model` (extra keys such as `status_code` are dropped) |
| `CrawlRequest` | `path: str` (required) | `/api/crawler/parse-page` body |
| `DashboardSummary`, `ActivityItem`, `AlertItem`, `DashboardResponse`, `ApplicationItem`, `InquiryItem`, `CrawlResponse` | mock-era shapes (`total_applicants`, `visa_approved_ytd`, `topik_level`, `visa_type`, ...) | **unused** (`git grep` finds them only in `schemas.py`) |

### 10.4 How the API runs, and its caveats
- It runs **inside the bot process.** `run.py` builds `uvicorn.Config("src.api.main:app", host=settings.API_HOST, port=settings.API_PORT, log_level="info")` and awaits `server.serve()` in the same event loop as the Telegram polling. So the API shares the bot's `admin_client` session. Without a Telegram token it runs the API alone. `hangeul_stderr.log` shows `Uvicorn running on http://0.0.0.0:8000`, and port 8000 is listening on 0.0.0.0. No API request line appears in any log, so nothing uses it today.
- The API is untouched since the baseline (still at 8317741; it has no performance endpoint and publishes nothing to Supabase), and it is the known leftover of the 28 Sep all-commands fix: "The REST API (src/api) still reads the 500-row consult page, and a portal failure gives HTTP 500."
- **Security caveats** (for a rebuild: add authentication or bind to 127.0.0.1). There is no authentication, and it binds 0.0.0.0 (kept on purpose, migration decision 9) with CORS `*`:
  - `/api/auth/csrf` returns the shared client's cookie jar, which includes the live portal session cookie once the bot has logged in.
  - `/api/auth/login` can log the shared session in as someone else.
  - `/api/crawler/parse-page` GETs any path the caller names. That breaks the read-only guarantee if the portal has a state-changing GET link (a logout link, for example, would end the bot's session).

---

## 11. `src\__init__.py` (context for everything above)
79 lines at 8317741 (last changed 36ae72e). It is imported before any `src.*` module, and has two side effects:
1. If `C:\Hangeul\BOT\data\windows-ca.pem` exists (`:18-22`), it sets `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `HTTPX_SSL_CERT_FILE` and `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` to it with `setdefault`. The file is rebuilt with `tools\export_windows_ca.ps1`; on 26 Sep an HTTPS-inspecting middlebox broke the Google token refresh. **The file is absent on this PC now**, so this hook is inactive. The portal client uses `verify=False` either way; the Supabase client (`src\cloud\publish._client`) verifies TLS (httpx default).
2. **Secret redaction in log records.** `_SECRET_PATTERNS` (`:41-49`) is applied in order by `redact(text) -> str` (`:52-56`, public; tested in `tests\test_cloud.py:1122` with a fake token):

| Pattern | Replaced by | What it hides |
|---|---|---|
| `bot\d{6,}(?::\|%3[Aa])[A-Za-z0-9_-]{30,}` (`_TOKEN_RE`, `:36`) | `bot<token>` | the Telegram bot token in a Bot API URL (the `:` is `%3A` in file-download URLs) (0fce479, e205327) |
| `(?i)(bearer\s+)(?!<)[A-Za-z0-9._~+/=-]{8,}` | `\1<redacted>` | an `Authorization: Bearer ...` value |
| `(?i)(apikey['"]?\s*[:=,]\s*b?['"]?)(?!<)[A-Za-z0-9._~+/=-]{8,}` | `\1<redacted>` | an `apikey` header in any printed form (dict, bytes, `k=v`) |
| `sb_secret_[A-Za-z0-9_-]{6,}` | `sb_secret_<redacted>` | the Supabase secret key |
| `sb_publishable_[A-Za-z0-9_-]{6,}` | `sb_publishable_<redacted>` | the publishable key |
| `sbp_[A-Za-z0-9_-]{16,}` | `sbp_<redacted>` | the CLI's personal access token |
| `eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}` | `<jwt>` | the older JWT-shaped Supabase keys |

   The `(?!<)` guards keep an already-redacted `<redacted>` from being matched again. `_RedactBotToken(logging.Filter)` (`:59-71`; the name is kept from when it covered only the bot token) calls `record.getMessage()` (a record whose formatting fails is passed through untouched), and when `redact` changed anything it replaces `record.msg` with the clean text and empties `record.args`; it always returns `True` (nothing is dropped). One instance is added (`:76-79`) to `httpx`, `httpcore`, `httpcore.connection`, `httpcore.http11`, `httpcore.http2`, `httpcore.proxy`, `httpcore.socks` and `hangeul.cloud`, because a logger's filter does not see records of its child loggers (httpcore logs per module at DEBUG). Before 36ae72e only `httpx` had it, and only for the bot token.

---

## 12. Rebuild rules distilled from these files
1. **One client, one session path.** Every portal page goes through `portal_get` / `fetch_html`: it logs in when needed, checks the login worked, re-logs in once on a redirect to the login page, uses a 10 s connect timeout and a per-page read timeout, and raises a typed error (`PortalUnavailable(reason, unreachable)`) for everything else. The only non-GET request is the login POST.
2. **A failed read is never a figure.** Raise, and reply "Couldn't read the portal: <reason>". Reserve `0`, "none" and `[]` for pages that were read whole and say so.
3. **Read every page.** Follow the pager, keep the query on every page, de-duplicate by the portal's own id, cap the page count, and verify the total. Page 1 alone hid most verifications.
4. **Parse by meaning.** Match header names and the page's CSS classes, never column positions. Raise a layout error for rows you cannot read.
5. **Use the portal's own counters when they exist** (status tabs, badges, dashboard tiles, date-filter views) rather than counting a list that is capped (500 rows).
6. **Parse dates strictly.** Whole-word months, `None` plus a reason for impossible dates, no stand-in "today". Yearless stamps are trusted only within the last year (`yearless_day_problem`), and never before the student's application date.
7. **OCR claims need proof.** Trust MRZ fields by their own check digits. Keep two lists (confirmed discrepancies vs check by eye), try rotations before saying "unreadable", and run OCR in a worker thread behind one lock.
8. **The LLM picks facts; it never writes them.** Use a JSON-schema output, a fixed `num_ctx` (a change reloads the model), a measured prompt size, the model unloaded when idle unless voice needs it, and a no-LLM fallback.
9. **Settings in one pydantic class**, secrets only in `.env`, and `MOCK_MODE` default `True` handled explicitly. Keep any staging copy byte-identical to the live file.
10. **Verify TLS.** `verify=False` on the portal client is an unexplained baseline leftover (§3.4); a rebuild keeps verification on and solves an intercepting network with the exported Windows CA bundle (§11).
11. **Undo the CDN before parsing.** A site behind Cloudflare hides every e-mail address as `[email protected]` with a `data-cfemail` hex (key = first byte, XOR, UTF-8). Decode the whole soup right after building it, on every page, leave a malformed hex as served, never touch attribute values, and treat an undecodable stand-in as "no value" downstream. Pin it with a source test that fails on any unwrapped `BeautifulSoup(` (§4.1.1); a browser never shows the problem, so only a test or a data check finds it.
12. **When the owner names a portal page, show that page.** The first performance report was computed by the bot from other pages; the owner wanted the portal's own Consultant Performance page. Read the page the owner means, keep every figure as printed, check the page against the request (the period guard) and against itself (the count badge, the empty state), and compute nothing (§3.8, §4.12).
13. **Log in once before reading side by side.** `_ensure_session` inside `portal_get` is the only session opener (§3.5), and it has no lock, so reads started together on a client with no session would each log in. Do one read first, then run the rest concurrently, as `sheets\stage_report.py:100-101` does ("the login, once, before the rest go side by side"); the removed `ensure_session()` (§3.10) served the same purpose.
14. **Settings: never an empty bool.** `KEY=` for a `bool` field stops the whole bot at import (§1.1). Keep a feature's master switch off by default, and require every one of its settings (URL, key, switch) before it does anything (`publish.enabled()`).

---

## 13. `src\net_fix.py`: the Telegram DNS workaround

**File:** 105 lines, added in the baseline `366dec0`, unchanged since (`git log -- src/net_fix.py` shows only 366dec0). Logger: `hangeul.netfix`. Called once, from `run.py:71` (`tg_ip = apply_telegram_dns_fix()`, imported at `run.py:31`), before Ollama is checked and before uvicorn and the Telegram polling start; a non-`None` result is printed on the console as `⚠ Telegram DNS override: api.telegram.org -> <ip>`. Nothing else imports it (no test covers it).

**Why it exists** (module docstring `:1-13`): on the old PC's network the DNS answer for `api.telegram.org` pointed at an unreachable Telegram address, while other Telegram front-end addresses answered with a valid certificate. Editing the Windows `hosts` file needs admin rights, so the process probes known addresses and overrides name resolution **for itself only**.

### 13.1 Constants

| Name | Line | Value |
|---|---|---|
| `TELEGRAM_HOST` | `:20` | `"api.telegram.org"` |
| `TELEGRAM_PORT` | `:21` | `443` |
| `PROBE_TIMEOUT` | `:22` | `3.0` s per TCP probe |
| `CANDIDATE_IPS` | `:25-36` | 10 entries (comment: "DC2 / DC4 / DC5 ranges"): `149.154.167.99`, `149.154.167.220`, `149.154.166.110`, `149.154.167.50`, `149.154.167.51`, `149.154.167.91`, `149.154.167.220` (a **duplicate** of the 2nd entry, harmless: it is probed twice at most), `149.154.175.50`, `91.108.4.200`, `91.108.56.100` |
| `_original_getaddrinfo` | `:38` | `socket.getaddrinfo`, saved before any patch |
| `_chosen_ip` | `:39` | `None` until an override is chosen |

### 13.2 Functions

| Signature | Line | What it does |
|---|---|---|
| `_tcp_ok(ip: str) -> bool` | `:42` | `socket.create_connection((ip, 443), timeout=3.0)`; `True` if it connects, `False` on any `OSError`. A TCP connect only: no TLS handshake, no HTTP request. |
| `_dns_ips() -> list` | `:50` | The IPv4 addresses the normal resolver gives for `api.telegram.org:443` (`AF_INET`, `SOCK_STREAM`), de-duplicated in order; `[]` on `OSError`. |
| `_patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0)` | `:64` | Replacement for `socket.getaddrinfo`. Decodes a `bytes` host (httpx/anyio may pass bytes). If `_chosen_ip` is set and the host is `api.telegram.org` (case-insensitive), resolves `_chosen_ip` instead, forcing `AF_INET`; every other host goes to the original resolver unchanged. TLS still uses the host name for SNI and certificate checks, so the certificate must be valid for `api.telegram.org`. |
| `apply_telegram_dns_fix() -> str \| None` | `:72` | 1. `TELEGRAM_DNS_FIX` in `("0","false","no","off")` (default `"true"`) → log "disabled" and return `None`. 2. `TELEGRAM_API_IP` set → use it without probing, patch `socket.getaddrinfo`, return it. 3. If any normal DNS address passes `_tcp_ok` → log "reachable via normal DNS", return `None` (no patch). 4. Otherwise probe each `CANDIDATE_IPS` entry not in the DNS answer; the first that connects is chosen, `socket.getaddrinfo` is patched process-wide, a WARNING "Telegram DNS override active" is logged, and the IP is returned. 5. None connects → ERROR "No reachable Telegram address found. Bot startup will likely time out." and `None`. |

**Costs and failure modes.** When DNS works (the normal case on this PC), the cost is one resolver call and one TCP connect. When DNS is dead, the start-up can wait up to 10 × 3 s = 30 s. The patch is global for the process, so it also covers `python-telegram-bot`'s httpx client; the subprocess jobs (`auto_sync`, `missing_report`) that call the Bot API with their own `httpx.Client` never call `apply_telegram_dns_fix()` and get no override.

**The docstring's advice is wrong.** `:11-12` says "Set TELEGRAM_API_IP in .env". Nothing loads `.env` into `os.environ` (there is no `load_dotenv` anywhere; pydantic-settings reads `.env` only into the `Settings` object, and neither key is a Settings field). Only **Windows environment variables** (user or process) reach this module, as [secrets/README](secrets/README.md) and [02 §4](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md) say. **Rebuild rule:** either make both keys Settings fields, or document them as OS environment variables; keep the override process-local and never edit `hosts`.
