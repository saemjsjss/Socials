# 03d: File map of `src\cloud\` (the Supabase publish layer) and every hook call site

**What's in this file:** a function-by-function map of the 11 files of `src\cloud\`, the package that copies everything the bot reads to Supabase: `__init__.py`, `publish.py`, `records.py`, `embed.py`, `handoff.py`, `backfill.py`, `full_picture.py`, `bot_jobs.py`, `command_hooks.py`, `sheet_hooks.py` and `student_index.py`. For each it gives the constants, classes and functions with their exact signatures and `path:line`, what each reads and writes, and how it fails. Then it lists **every call site in the rest of the code** that feeds the layer: the scheduler, the command handlers, the free-text answers, the performance page, the sheet jobs, the scraper's Cloudflare decoding and client additions, the log redaction and the settings, and (§12.8) every helper outside `src\cloud\` whose contract shapes a key, scope or day, with a link to where it is defined. It ends with the tests that pin the layer, the run-time files, and the history of each file.
**Pack written:** 30 September 2026 (Asia/Dhaka), from `C:\Hangeul\BOT` at `main` = `8317741`. This file is new in the pack's refresh from `c17d887` to `8317741`. Line numbers are `path:line` at `8317741`.
**Siblings:** the behaviour, the server contract, every kind and the operations are in [13_SUPABASE_PUBLISHING.md](13_SUPABASE_PUBLISHING.md); read it first. The other file maps are [03a (`src\bot\`)](03a_FILES_src_bot.md), [03b (config, scraper, LLM, API)](03b_FILES_src_scraper_llm_api_config.md) and [03c (`src\sheets\`, `src\verify\`, root files)](03c_FILES_sheets_verify_root_scripts.md). The system view is [01_ARCHITECTURE.md](01_ARCHITECTURE.md), the tests are [10](10_TESTS_AND_VERIFICATION.md), and the index is [00_INDEX.md](00_INDEX.md). Secret values are never written here; a secret is "value in secrets/bot.env (KEY)". Student data appears only as `<placeholders>`.

---

## 0. The files in scope

| File | Lines | Role | Added | Last changed | Commits |
|---|---|---|---|---|---|
| `src\cloud\__init__.py` | 24 | Package docstring and `JOBS`, the `hg_runs.job` names | 36ae72e | 36ae72e | 1 |
| `src\cloud\publish.py` | 938 | The engine: `hg_sync` calls, the hash state, `hg_runs`, the lock, the dry run; the publisher process `python -m src.cloud.publish --from <file>` | 36ae72e | 752cd53 | 4 |
| `src\cloud\records.py` | 1491 | One pure function per kind: reader output to records; the filler rule; `batch` / `batches` | 36ae72e | 8317741 | 8 |
| `src\cloud\embed.py` | 298 | gte-small on the CPU, chunking, the stub embedder | 36ae72e | 9ead47d | 3 |
| `src\cloud\handoff.py` | 144 | The handoff file and the publisher child process | 36ae72e | 752cd53 | 3 |
| `src\cloud\backfill.py` | 684 | `python -m src.cloud.backfill`: the one-time copy; the `collect_*` readers the full picture reuses | 36ae72e | 8317741 | 7 |
| `src\cloud\full_picture.py` | 204 | `python -m src.cloud.full_picture`: the hourly read-and-publish | 5048a07 | e4d1cea | 4 |
| `src\cloud\bot_jobs.py` | 309 | The bot process's scheduled jobs: the 18:05 brief and the passport watcher | 5048a07 | 3caa393 | 3 |
| `src\cloud\command_hooks.py` | 357 | What the command handlers and free-text answers publish, after the reply | 2b6798f | e4d1cea | 4 |
| `src\cloud\sheet_hooks.py` | 470 | What the four subprocess sheet jobs publish, last of all | 41055de | 3caa393 | 2 |
| `src\cloud\student_index.py` | 132 | `data\cloud\student_index.json`: passport to (uid, HNG id) | 3caa393 | 3caa393 | 1 |

**Who imports whom.**
- `records` is imported by everything; it imports `src.config`, `src.dates`, `src.scraper.parsers`, `src.sheets.passport_issue.passport_key`, `src.sheets.progress_builder`, `src.sheets.auto_sync._row_key`, `src.scraper.client.PERFORMANCE_PERIODS` and `src.bot.performance._range_dates`, **all lazily inside functions**. Module-level imports are only `hashlib`, `json`, `math`, `re` and `datetime`, so importing `records` costs nothing and makes no import cycle.
- `publish` imports `src.config` and `httpx` at module level; `records`, `embed` and `handoff` lazily.
- `handoff` imports `publish` (for `CHILD_TIMEOUT`, `CLOUD_DIR`, `enabled`) and `embed.NO_GPU` lazily.
- `backfill` imports `records` at module level and the portal and sheet modules lazily.
- `full_picture` imports `backfill`, `publish`, `records` and `src.scraper.client`.
- `bot_jobs` imports `handoff` and `records`.
- `command_hooks` and `sheet_hooks` import only `logging`/`asyncio` at module level, and the rest inside functions.
- `student_index` imports `src.config`.

**Rules every file keeps:**
- Nothing raises into a job.
- Nothing logs student data: reasons are exception types, HTTP statuses and Postgres codes.
- Nothing happens while publishing is off (`publish.enabled()`).
- Nothing embeds except a process that hid CUDA first (`embed.cpu_only_process()`).

The logger for all 11 files is `logging.getLogger("hangeul.cloud")`, which the redaction filter covers (§12.7).

---

## 1. `src\cloud\__init__.py`

- The docstring (`:1-20`) is the package summary. It says the schema belongs to the Jeannie repo (`supabase/migrations/20260929030000_hangeul_context.sql`) and that the package only writes rows through `hg_sync` and `hg_runs`.
- `JOBS = ("portal_sync", "passport_watcher", "daily_brief", "missing_report", "issue_refresh", "stage_report", "command", "backfill", "full_picture")` (`:23-24`): the `hg_runs.job` values. The server does not check them; `tests\test_cloud_all.py` pins every hook's job name to this tuple.

---

## 2. `src\cloud\publish.py`: the engine and the publisher process

### 2.1 Top of the file

- `:60-61` `if __name__ == "__main__": os.environ["CUDA_VISIBLE_DEVICES"] = "-1"`. The publisher process hides the GPU before anything can import torch; `""` would be dropped from a Windows environment (13 §8.1).
- Paths (`:83-87`): `DATA_DIR = BOT_ROOT / "data"`, `STATE_PATH = DATA_DIR / "cloud_state.json"`, `CLOUD_DIR = DATA_DIR / "cloud"`, `DRY_RUN_DIR = CLOUD_DIR / "dry_run"`, `LOCK_PATH = CLOUD_DIR / "publish.lock"`.
- Limits (`:89-96`):

| Constant | Value | Meaning |
|---|---|---|
| `MAX_ROWS` | `200` | rows a call (`hg_sync` refuses more) |
| `MAX_CHUNKS` | `250` | chunks embedded at a time |
| `MAX_BODY` | `1_000_000` | bytes of one `hg_sync` body |
| `TIMEOUT` | `30.0` | seconds per HTTP call |
| `LOCK_WAIT` | `20 * 60` | seconds a publisher waits for another |
| `CHILD_TIMEOUT` | `3600` | seconds before the publisher process stops itself |
| `STATE_VERSION` | `1` | |
| `DEFAULT_JOB` | `"command"` | |

- `TRANSPORT: Optional[httpx.BaseTransport] = None` (`:99`): tests put an `httpx.MockTransport` here. `_DRY_RUN = False` (`:100`).

### 2.2 Switches

| Function | Line | Contract |
|---|---|---|
| `enabled() -> bool` | `:103` | True only when `settings.SUPABASE_URL` and `settings.SUPABASE_SECRET_KEY` are non-blank and `settings.CLOUD_PUBLISH_ENABLED` is true; the key's value is never logged |
| `set_dry_run(on: bool) -> None` | `:110` | every later publish in this process is a dry run (the backfill's `--dry-run`) |
| `_dry(dry_run: Optional[bool]) -> bool` | `:116` | the call's own flag, else the process flag |

### 2.3 `Result` (dataclass, `:120-137`)

What one `publish(kind, scope, ...)` did: `kind`, `scope`, `rows` (records given), `changed` (hash differed: embedded and sent), `upserted`, `unchanged` (in the state already, or Supabase said so), `deleted`, `calls`, `left_out` (refused before sending), `older` (a newer read already sent), `older_read` (a complete read older than the last: nothing deleted), `ok` (default True), `skipped` (why nothing was sent), `error` (the short reason logged, never data), `delegated` (handed to the publisher process).

### 2.4 The hash state (`:140-205`)

| Function | Line | Contract |
|---|---|---|
| `_empty_state() -> Dict` | `:142` | `{"version": 1, "embed_model": "", "records": {}, "scopes": {}, "reads": {}}` |
| `load_state() -> Dict` | `:146` | `data\cloud_state.json`, or an empty state when it is missing, unreadable (one WARNING: "Supabase hash state unreadable (<type>); every record is sent again."), the wrong version, or badly shaped; a missing `reads` is added |
| `save_state(state) -> None` | `:164` | compact JSON to `cloud_state.json.part`, then `os.replace` |
| `_split_state_key(key) -> (kind, rest)` | `:171` | splits `"<kind>\|<key>"` on the **first** "\|" only (a record key may hold "\|") |
| `known_scopes(kind) -> set` | `:176` | the scopes of `kind` the state holds records in |
| `known_keys(kind, scope=None) -> set` | `:182` | the keys of `kind` (in `scope`) the state holds |
| `_keys_digest(keys) -> str` | `:192` | sha256 hex of the sorted, de-duplicated keys joined by `\n` |
| `_when(value) -> Optional[datetime]` | `:196` | an ISO read time (a trailing `Z` accepted) as an aware datetime; None for none, a bad text, or a naive time |

State shape: `records["<kind>|<key>"] = {"h": content_hash, "s": scope, "t": read_at}`, `scopes["<kind>|<scope>"] = digest of the keys of its last complete publish`, `reads["<kind>|<scope>"] = read time of its last complete publish`. The reasons for each part are in 13 §7.2.

### 2.5 One publisher at a time (`:208-271`)

| Function | Line | Contract |
|---|---|---|
| `_os_lock(path: Path, wait: float) -> Optional[int]` | `:215` | `os.open(path, O_RDWR\|O_CREAT)`, then `msvcrt.locking(fd, LK_NBLCK, 1)` on Windows (after `lseek(fd, 0, 0)`) or `fcntl.flock(LOCK_EX\|LOCK_NB)` elsewhere, retried every 0.25 s until `wait`; returns the fd, or None (fd closed) |
| `_os_unlock(fd) -> None` | `:237` | unlocks and closes |
| `publisher_lock(wait: float = LOCK_WAIT)` | `:251` | context manager yielding whether the lock was got; re-entrant in one process (`_mutex` RLock, `_lock_depth`, `_lock_fd`); the OS frees it if the process dies |

### 2.6 Runs: `hg_runs` (`:274-481`)

- `_now_iso() -> str` (`:276`) is `records.as_read_at(None)`.
- **`Run`** (dataclass, `:281-324`):
  - fields: `job`, `dry`, `id` (uuid4 text), `started_at`, `failed_reads: List[str]`, `client: Optional[httpx.Client]`, `posted` (its row exists; else `p_run` is null), `down` (why Supabase is given up on for the rest of the run), `down_logged`, `publishes`, `failed: List[str]`, `upserted`, `deleted`, `unchanged`, `older`, `sent`, `by_kind: Dict[str, List[int]]`, `embedded`, `chunks`, `embed_seconds`, `requests` (dry run: files written), `dry_dir`, `started` (a perf counter);
  - `fail(kind, reason) -> None` (`:307`): appends `"<kind>: <reason>"`. It logs **one** WARNING "Supabase publish failed (<kind>): <reason>". Once `down` is set and that line was written, the rest go to DEBUG ("Supabase publish skipped ...");
  - `write(label, body: bytes) -> Path` (`:316`): the dry-run writer. The first call makes `data\cloud\dry_run\<YYYYMMDD-HHMMSS>-<job>-<id[:8]>\`, and each body goes to `<NNNN>-<label>.json`.
- `_current: Optional[Run]`, `current_run() -> Optional[Run]` (`:330`), and `current_job() -> str` (`:334`, the current run's job or `"command"`).
- `_body(obj) -> bytes` (`:338`): `json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")`. These are the exact bytes sent, and the bytes `_by_size` counts.
- `_client() -> httpx.Client` (`:342`): `base_url` = `SUPABASE_URL` stripped of the trailing "/", `timeout=30.0`, `transport=TRANSPORT`, `follow_redirects=False`, headers `apikey`, `Authorization: Bearer`, `Content-Type: application/json`, `Accept: application/json`; the key is the value in secrets/bot.env (SUPABASE_SECRET_KEY).
- `_PG_CODE_RE = re.compile(r"^[A-Z0-9]{5,10}$")` (`:350`).
- `_reason(resp) -> (str, bool)` (`:353`): the short reason from the status and the Postgres code only, and whether to give up. 401/403: "the key was refused"; 404: "hg_sync or hg_runs not found: is the Jeannie migration applied?"; 5xx: "Supabase server error". All three give up. 409 "conflict" and any other "refused" go on. The full table is in 13 §7.6.
- `_request(r, method, path, body, prefer="") -> (accepted, json or None, reason)` (`:375`): creates the client on first use. `httpx.TimeoutException` sets `r.down = "Supabase did not answer in time (<type>)"`; any other `httpx.HTTPError` sets `r.down = "could not connect to Supabase (<type>)"`. A 2xx is accepted (its JSON, or None).
- `_start(r)` (`:399`): `POST /rest/v1/hg_runs` with `Prefer: return=minimal` and body `{"id", "job", "started_at", "counts": {}}`. A dry run writes `POST-hg_runs`. A non-`https://` URL gives up the run.
- `_status(r) -> str` (`:415`): `failed` when there are failures and (`down`, or failures ≥ max(1, publishes)); `partial` when there is any failure or failed read; else `ok`.
- `_finish(r)` (`:423`): the body is `{"finished_at", "status", "counts", "note"}`.
  - `counts = {upserted, deleted, unchanged, older, sent, failed_reads, failed, by_kind, embedded, chunks}`; `note = "<n> read(s) failed; <m> publish(es) failed"` or null.
  - A dry run writes `PATCH-hg_runs` and one INFO line "Supabase dry run (<job>): <n> request(s) written to <dir> in <t> s (...)".
  - Otherwise it sends **one PATCH** `/rest/v1/hg_runs?id=eq.<id>` whenever the row was posted, even after a give-up. The PATCH also sends `Prefer: return=minimal` (`:442`); the `hg_sync` POST (`:780`) sends no `Prefer` header, because its JSON answer is read. When anything was published or failed, it writes the INFO summary "Supabase publish (<job>): <status>, <u> upserted, <d> deleted, <n> unchanged, <s> row(s) sent, <f> failed, <r> read(s) failed; <e> record(s) embedded in <t> s; <T> s in all, peak memory <g> GB."
- **`run(job="command", failed_reads=(), *, dry_run=None)`** (`:452-480`): a context manager yielding the `Run`, or None while publishing is off (and not a dry run). A nested run joins the outer one and adds its failed reads. It always calls `_finish` and closes the client. An exception in `_start` is "internal error (<type>)" on `hg_runs`.
- `_memory_note() -> str` (`:483`): ", peak memory X GB", from `GetProcessMemoryInfo` (`PeakWorkingSetSize`) on Windows or `ru_maxrss` elsewhere; `""` when it cannot be read.

### 2.7 Publishing (`:513-866`)

- `_ROW_FIELDS = ("student_uid", "student_hng_id", "student_name", "passport_no", "day")` (`:515`).
- `_normalise(kind, scope, rows) -> (rows, left_out)` (`:518`): the rows Supabase would accept, each key once.
  - Left out: not a dict, no key, another kind or scope, no `data` object, no source, a repeated key.
  - The key and texts are cleaned (`records.clean_text`); `data` goes through `records.jsonable`; `""` becomes None in the five columns; `student_uid` must be an int or digits below 2³¹.
  - `content_hash` is **recomputed** with `records.content_hash`, and `read_at` goes through `records.as_read_at`.
- `_groups(rows: List[(row, chunk texts)]) -> List[group]` (`:552`): at most `MAX_ROWS` rows and `MAX_CHUNKS` chunks a group.
- `_embedded(r, group) -> List[payload row]` (`:566`): embeds all the group's chunk texts at once and adds `chunks: [{"ord", "content", "embedding": [float(f"{x:.8g}") ...], "embed_model"}]`. It counts `embedded`, `chunks` and `embed_seconds`, and raises `EmbedError` if the number of vectors differs.
- `_by_size(kind, head, rows, keys) -> List[call rows]` (`:589-631`): splits one embedded group into calls of at most `MAX_BODY` bytes. The size is the exact serialisation: the empty body plus each row plus the commas. It leaves room for `p_all_keys` on the last call; a row, or a key list alone, over the cap goes into a call of its own with one WARNING naming the size. The algorithm is in 13 §7.5.
- `_can_embed_here() -> bool` (`:634`): `embed.custom_embedder() or embed.cpu_only_process()`.
- **`publish(kind: str, scope: str, rows: Sequence[Dict], complete: bool, *, all_keys: Optional[Iterable[str]] = None, read_at: Any = None, dry_run: Optional[bool] = None, job: Optional[str] = None) -> Result`** (`:639-675`): never raises.
  - Off: `skipped="publishing is off"`. No kind or scope: one line.
  - When this process may not embed, it hands the batch over (`handoff.submit(job or current_job(), [records.batch(kind, scope, rows, complete, all_keys, read_at)])`, with `delegated=True`).
  - Otherwise `with run(job)` and `_publish`. Any exception is "internal error (<type>)".
- **`_publish(r, res, kind, scope, rows, complete, all_keys=None, read_at=None) -> Result`** (`:678-804`): the algorithm of 13 §7.3, in this order.
  1. `_normalise` (left out means not complete);
  2. `listed` = the keys ∪ `all_keys`; the read time;
  3. the lock; `load_state()`;
  4. an older complete read becomes partial (`older_read`);
  5. the changed rows (and `older`);
  6. the gone and kept keys; `keys` and their digest; the unchanged tally;
  7. "no changes" returns early;
  8. `r.down` means skip;
  9. the `embed_model` guard;
  10. `emb.chunks()` for each changed row;
  11. per group: `_embedded`, `_by_size`, and per call: the dry-run file, or (before the first real call) the scope digest dropped and saved, then `POST /rest/v1/rpc/hg_sync`;
  12. on acceptance, `recs[...] = {"h", "s", "t"}` for each row; on the last complete call, the gone keys are dropped, and `scopes` and `reads` are set (a partial read restores the old digest); `state["embed_model"]` is set; `save_state`.
- `_model_unavailable(r, res, kind, e) -> Result` (`:807`): an `EmbedError` fails this publish, sets `r.down`, logs one line, and advances no state.
- **`publish_scopes(kind: str, rows: Sequence[Dict], complete: bool, scope_range: Optional[Sequence[str]] = None, *, read_at=None, dry_run=None, job=None) -> List[Result]`** (`:817-833`): one publish per record scope. With `complete` and `(lo, hi)`, every known scope of the kind in lo..hi with no record now is published empty and complete.
- **`publish_batches(job: str, batches: Sequence[Dict], failed_reads: Sequence[str] = (), *, dry_run=None) -> List[Result]`** (`:836-866`): the whole handoff file in one run under the lock (on failure: one line "another publisher held the lock for over 20 minutes"). A batch with `"scope": None` goes through `publish_scopes`; otherwise `publish(..., all_keys=b.get("all_keys"), read_at=b.get("read_at"))`. Never raises.

### 2.8 The publisher process (`:869-938`)

- `process_file(path: Path, *, dry_run: bool = False) -> int` (`:871`): reads the handoff JSON (not an object, or unreadable: one line, return 1), returns 0 while publishing is off, runs `publish_batches(doc["job"], doc["batches"], doc["failed_reads"])`, and **always deletes the file** in `finally`.
- `_deadline(seconds, path) -> threading.Timer` (`:895`): a daemon timer. On expiry it logs "Supabase publish failed (<job>): the publisher ran over <n> s and was stopped", deletes the file and calls `os._exit(3)`.
- `main(argv=None) -> int` (`:911`): argparse `--from` (required, dest `path`), `--timeout` (float, default 3600), `--dry-run`. It calls `embed.prepare_process()` unless a stub embedder is set (an `EmbedError` gives one line, the file deleted, exit 2), arms the deadline, and runs `process_file`.
- `:932-938` `__main__`: `prepare_process()`, `logging.basicConfig(level=INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")`, `httpx` at WARNING, then `sys.exit(src.cloud.publish.main())`. It uses the imported module, not the `__main__` copy, so the module-level state is shared with the rest of the package.

---

## 3. `src\cloud\records.py`: records, the filler rule, batches

### 3.1 Constants (`:41-60`, `:195-216`, `:279-282`, `:798-804`, `:1015-1017`)

| Name | Line | Value |
|---|---|---|
| `CLOUD_KINDS` | `:41` | the 26 kinds (the spec's 24 plus `doc_check` and `consultant_performance`) |
| `STUDENT_VOLATILE` | `:52` | `("sl", "details_text", "id")` |
| `STALE_EXPORT_COLUMNS` | `:54` | `["Current Stage", "Current Status", "Progress %"]` |
| `EXPORT_SHARE` | `:57` | `0.9` |
| `UNCHECKED_AUDITS` | `:60` | `("MISSING_DOCUMENT", "PORTAL_UNREADABLE", "OCR_UNAVAILABLE", "ERROR")` |
| `FILLER_WORDS` | `:206` | `{"na", "none", "null", "nil", "pending", "tbd", "notavailable", "notapplicable", "notprovided", "emailprotected"}` |
| `STATUS_FIELDS` | `:214` | `{"payment", "bank certificate", "bank solvency", "vin app", "vin required"}` |
| `_STATUS_NAME_RE` | `:215` | `r"\b(?:status\|stage\|result\|step)\b"` |
| `BLANK_ON_PORTAL` | `:216` | `"blank_on_portal"` |
| `FILLED_CONSULTANT`, `FILLED_CALENDAR_KIND`, `FILLED_TILE_GROUP` | `:280-282` | `"Unassigned"`, `"Event"`, `"Dashboard"` (the readers' own stand-ins) |
| `PERFORMANCE_KIND`, `PERFORMANCE_SUMMARY` | `:798-799` | `"consultant_performance"`, `"summary"` |
| `PERFORMANCE_FIGURES` | `:802` | `(("score","score"), ("conversion","conversion"), ("files_opened","files opened"), ("consultancies","consultancies"), ("points","points"), ("docs_ready","docs ready"))`; `_TOP_FIGURES` = the first four |
| `DASHBOARD_GROUPS` | `:1016` | the 7 groups a whole `index.php` read shows |
| `_STUDENT_TEXT_LABELS` | `:411-413` | the 18 details labels the student text names on its own, so "Other details" leaves them out: `{"Full Name", "Program", "Intake", "Applied On", "Payment Status", "Passport No", "Passport Expiry", "Passport Status", "DOB", "Gender", "Mobile", "Email", "Guardian WhatsApp", "Father", "Mother", "Address", "District", "Consultant"}` (a set: it shapes the student text and so its hash) |
| `_UNREADABLE_RE` | `:1282` | `r"^\s*\[unreadable\b"` (re.I) |

### 3.2 Values (`:63-192`)

| Function | Line | Contract |
|---|---|---|
| `_zone()` | `:65` | `ZoneInfo(settings.REPORT_TIMEZONE)` (Asia/Dhaka) |
| `now() -> datetime` | `:71` | now in that zone |
| `as_read_at(value=None) -> str` | `:75` | ISO with the offset, seconds; the rules are in 13 §4.3 |
| `iso_day(value) -> Optional[str]` | `:96` | `"YYYY-MM-DD"` from a date, a datetime, an ISO text or a portal text (`src.dates.parse_portal_date`) |
| `_long_day(iso) -> str` | `:117` | `"2026-09-28"` becomes `"28 Sep 2026"` |
| `clean_text(text) -> str` | `:125` | no NUL, no unpaired surrogates |
| `jsonable(value) -> Any` | `:136` | plain JSON (dates as ISO, named tuples and mappings as objects, sets as sorted lists, non-finite floats as None, texts cleaned) |
| `canonical(value) -> str` | `:160` | `json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)` |
| `content_hash(kind, key, scope, data, content) -> str` | `:164` | sha256 hex of `canonical({kind, key, scope, data, content})` |
| `sha1(*parts) -> str` | `:170` | sha1 hex of the parts joined |
| `_uid(value) -> Optional[int]` | `:174` | digits only, 0 < n < 2³¹ |
| `_passport(value) -> str` | `:182` | `sheets.passport_issue.passport_key(str(value or ""))` (`passport_issue.py:47-51`): whitespace removed, upper-cased; `""` unless it has at least 6 characters and a digit (blank, "—", PENDING → `""`) (R11; [03c §1.6](03c_FILES_sheets_verify_root_scripts.md)). This value is the scope of `doc_verdict`, `field_check` and `doc_page_text`, the key of `doc_check` and `passport_issue`, and the student-index key |
| `_passport_value(value) -> str` | `:188` | the value as printed, or `""` when it is no passport number |

### 3.3 The filler rule (`:219-276`)

| Function | Line | Contract |
|---|---|---|
| `_filler_key(text) -> str` | `:219` | the case-folded letters and digits |
| `is_status_field(name) -> bool` | `:223` | `_`/spaces collapsed, lower-case; matches `_STATUS_NAME_RE` or is in `STATUS_FIELDS` |
| `is_filler(value, field="") -> bool` | `:230` | a whole-cell string whose key is empty (marks only) or in `FILLER_WORDS`, except `pending` in a status field |
| `_blank_cells(fields, prefix="") -> (fields, blanked names)` | `:242` | every filler cell becomes `""`, and its name, led by `prefix`, is listed |
| `_passport_cell(fields, name, blanked, prefix="")` | `:256` | a passport field that is no passport number becomes `""` and is listed |
| `_mark_blank(data, blanked) -> data` | `:266` | `data["blank_on_portal"]` = the sorted names, only when there are any |
| `_given(value)` | `:274` | the value, or `""` for a filler |
| `_ids_of(ids) -> (uid, hng)` | `:285` | from `(uid, hng)` or `{"uid", "hng"}`; `""` for each not known |

### 3.4 Building and grouping (`:297-407`)

- **`make(kind, key, scope, data, content, source, read_at=None, *, uid=None, hng=None, name=None, passport=None, day=None) -> Dict`** (`:297`): one record, cleaned and hashed (the shape is in 13 §4.1).
- `unique_keys(records) -> List[Dict]` (`:316`): drops None, gives repeated keys `#2`, `#3`..., and recomputes their hash.
- **`batch(kind, scope, rows, complete, all_keys=None, read_at=None) -> Dict`** (`:338`): `{"kind", "scope", "complete", "rows"[, "all_keys" (sorted, unique, no blanks)][, "read_at"]}`. `all_keys` is for a complete read whose rows hold only some of the records (the watcher's audits).
- **`batches(kind, rows, complete, scope_range=None, read_at=None) -> Dict`** (`:361`): `{"kind", "scope": None, "complete", "rows"[, "scope_range": [lo, hi]][, "read_at"]}`, each row in its own scope.
- Text helpers: `_sentence(*parts, end=".")` (`:378`, adds the end unless the text already ends with `.!?:`), `_paragraph(*sentences)` (`:383`), `_pairs(fields, skip=())` (`:387`, `"Label: value; ..."` for fields with a value; lists joined; dicts skipped), `_ids(*ids)` (`:404`, `" (a, b)"` of the ids that exist).

### 3.5 The kind builders (each kind in full: 13 §5)

| Function | Line | Signature | Kind |
|---|---|---|---|
| `student_text` | `:416` | `(s: Mapping) -> str` | the text of one students.php record |
| `_student_fields` | `:459` | `(s) -> (fields, blanked)` | data without volatile fields, fillers and placeholder passport blanked |
| `student` | `:474` | `(s, read_at=None) -> Optional[Dict]` | `student` |
| `students` | `:490` | `(rows, read_at=None) -> List[Dict]` | each uid once |
| `pending_payments` | `:501` | `(rows, badge: Optional[int], read_at=None) -> List[Dict]` | `pending_payment` |
| `pending_complete` | `:527` | `(pending, badge, empty_page=False) -> bool` | the complete rule |
| `verification` | `:540` | `(v, day, read_at=None) -> Optional[Dict]` | `verification` |
| `verification_window` | `:564` | `(today: date) -> (lo, hi)` | the datable days |
| `verification_day` | `:574` | `(s, today: date) -> Optional[date]` | the stamp's day |
| `verifications` | `:596` | `(rows, today, read_at=None) -> List[Dict]` | every datable stamp |
| `student_documents` | `:610` | `(rows, read_at=None) -> List[Dict]` | `student_documents` |
| `student_exports` | `:637` | `(rows, read_at=None) -> List[Dict]` | `student_export` |
| `export_complete` | `:665` | `(rows, listed: Optional[int]) -> (bool, why)` | the complete rule |
| `student_profile` | `:680` | `(uid, fields, read_at=None) -> Optional[Dict]` | `student_profile` |
| `student_progress` | `:698` | `(progress: Mapping[uid, page], listed=None, read_at=None) -> List[Dict]` | `student_progress` |
| `consultation` | `:731` | `(row, day, read_at=None) -> Dict` | `consultation` |
| `consultations` | `:761` | `(on_day, read_at=None) -> (records, complete)` | from `read_consultation_day` |
| `consultation_day` | `:769` | `(on_day, read_at=None) -> Optional[Dict]` | `consultation_day` |
| `consultation_totals` | `:784` | `(totals, read_at=None) -> Optional[Dict]` | `consultation_totals` |
| `performance_source` | `:807` | `(period) -> str` | `"consult_performance.php?period=<period>"` |
| `performance_window` | `:812` | `(page) -> Optional[(first, last)]` | the page's range as ISO days |
| `performance_scope` | `:823` | `(period, window) -> str` | `"<period>\|<first day>"` |
| `_performance_title` | `:832` | `(period, page) -> str` | "Today" / "This Month" |
| `_figures_text` | `:838` | `(values, figures, extra=None) -> str` | "score 17.9, conversion 18%, ..." |
| `consultant_performance` | `:847` | `(period, page, read_at=None) -> List[Dict]` | summary + one per row |
| `performance_complete` | `:923` | `(period, page, recs) -> (bool, why)` | the complete rule |
| `consultant_performance_batch` | `:946` | `(period, page, read_at=None) -> (Optional[batch], failed)` | `(None, [why])` when the range cannot be read |
| `window_applications` | `:960` | `(rows, read_at=None) -> List[Dict]` | `window_application` |
| `window_complete` | `:979` | `(rows, records_, paged: bool) -> bool` | the complete rule |
| `dashboard_facts` | `:987` | `(facts, read_at=None) -> List[Dict]` | `dashboard_fact` |
| `tile_facts` | `:1005` | `(tiles) -> List[Dict]` | `get_dashboard()` tiles as facts (note `""`) |
| `dashboard_complete` | `:1020` | `(facts) -> bool` | all 7 groups present |
| `calendar_items` | `:1027` | `(items, read_at=None) -> List[Dict]` | `calendar_item` |
| `passport_audit` | `:1058` | `(uid, scan, result, read_at=None, student=None, form=None) -> Optional[Dict]` | `passport_audit` |
| `passport_alerts` | `:1100` | `(memory) -> List[Dict]` | `passport_alert` |
| `passport_issues` | `:1127` | `(by_passport, read_at=None) -> List[Dict]` | `passport_issue` |
| `_joined`, `_with_ids`, `_uid_text` | `:1143-1161` | | parts that exist; ids into data; "portal uid N" |
| `doc_verdicts` | `:1164` | `(passport, entry, ids=None) -> List[Dict]` | `doc_verdict` |
| `doc_checks` | `:1186` | `(documents, fields=None, ids=None) -> List[Dict]` | `doc_check` |
| `field_checks` | `:1222` | `(passport, entry, ids=None) -> List[Dict]` | `field_check` |
| `_arrow`, `_was_now` | `:1243-1252` | | "a -> b", "was X (DIFFERS)" |
| `field_corrections` | `:1255` | `(corrections, ids=None) -> List[Dict]` | `field_correction` |
| `_cache_entry` | `:1285` | `(key) -> Optional[(per_page, file, size, mtime, max_pages)]` | parses an OCR cache key |
| `doc_page_texts` | `:1297` | `(passport, cache, name="", current=None, read_at=None, ids=None) -> List[Dict]` | `doc_page_text` |
| `split_sections` | `:1349` | `(text) -> List[(heading, lines)]` | blocks between blank lines |
| `report` | `:1360` | `(name, when, text, facts=None, source="", read_at=None, day=None) -> Dict` | `report` |
| `report_sections` | `:1374` | `(name, when, sections, source="", read_at=None, day=None) -> List[Dict]` | `report_section` |
| `brief_facts` | `:1390` | `(day, facts, read_at=None) -> List[Dict]` | `brief_fact` |
| `notification` | `:1399` | `(text, sent_at=None, source="", title="") -> Dict` | `notification` |
| `missing_report` | `:1409` | `(day, rows, text="", read_at=None, source="missing_report") -> (report, sections)` | the missing-information report |
| `_newest_check_day` | `:1430` | `(section) -> str` | the newest `checked` day |
| `document_check_report` | `:1435` | `(store) -> (Optional[report], sections)` | DOCUMENT CHECK from `results.json` |
| `field_check_report` | `:1462` | `(store) -> (Optional[report], sections)` | FIELD CHECK from `results.json` |

---

## 4. `src\cloud\embed.py`: gte-small on the CPU

| Name | Line | Value or contract |
|---|---|---|
| `DIMENSIONS`, `MAX_WORDS`, `MAX_TOKENS`, `HEADING_WORDS`, `ENCODE_BATCH` | `:34-38` | 384, 350, 510, 40, 32 |
| `NO_GPU` | `:43` | `"-1"` |
| `QUIET_LOGGERS` | `:47` | `("sentence_transformers", "transformers", "huggingface_hub")` |
| `class EmbedError(RuntimeError)` | `:50` | "could not be loaded or used here"; the message never contains text |
| `model_id() -> str` | `:54` | `"<CLOUD_EMBED_MODEL>@<CLOUD_EMBED_REVISION>"` |
| `prepare_process() -> None` | `:60` | raises `EmbedError` if torch is imported and CUDA is not hidden; sets `CUDA_VISIBLE_DEVICES=-1`, `HF_HUB_OFFLINE=1`, `HF_HUB_DISABLE_PROGRESS_BARS=1`, `TQDM_DISABLE=1`, and by default `TRANSFORMERS_VERBOSITY=error` and `TOKENIZERS_PARALLELISM=false`; calls `quiet_libraries()` |
| `quiet_libraries() -> None` | `:76` | raises each of `QUIET_LOGGERS` below WARNING to WARNING (a stricter level is left) |
| `cpu_only_process() -> bool` | `:87` | `os.environ.get("CUDA_VISIBLE_DEVICES") == "-1"` |
| `_PARAGRAPH_RE`, `_SENTENCE_RE` | `:94`, `:96` | `r"\n[ \t]*\n+"`, `r"(?<=[.!?])[ \t]+\|\n+"` |
| `_words(text)`, `_cut(text, max_words)`, `_units(text, max_words)` | `:99-136` | word count; word-boundary pieces; paragraphs, else sentences or lines, else word pieces, each with the separator before it |
| `split_text(text, max_words=MAX_WORDS) -> List[str]` | `:139` | packs whole units while they fit; `[]` for no words |
| `chunk_texts(content, max_words=MAX_WORDS, count_tokens=None, max_tokens=MAX_TOKENS) -> List[str]` | `:160` | the whole text when it fits; else a short first line (40 words or fewer) repeated as the heading on every chunk (budget `max(20, 350 - heading)`); a chunk over `max_tokens` is halved until it fits or is 20 words or fewer |
| `class GteSmall` | `:197-244` | `name`, `revision`, `model_id`, a lazy `_model` under a lock. `_load()` refuses unless `cpu_only_process()` and loads `SentenceTransformer(name, revision=..., device="cpu", model_kwargs={"dtype": torch.float32})` (any failure: `EmbedError("gte-small could not be loaded (<type>)")`). `count_tokens(text)` uses the model tokenizer with special tokens and no truncation. `chunks(content)` is `chunk_texts(content, 350, count_tokens)`. `embed(texts) -> List[List[float]]` calls `encode(batch_size=32, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)`, float32, each vector checked; failure is `EmbedError("gte-small could not embed (<type>)")` |
| `class StubEmbedder` | `:247-266` | tests: `model_id="stub/gte-small@test"`, `chunks` without a tokenizer, `embed` gives a deterministic unit vector from sha256, `calls` records the texts |
| `_checked(vec) -> vec` | `:269` | 384 finite numbers, else `EmbedError` |
| `get_embedder()` | `:279` | the process's one embedder (`GteSmall()` unless set) |
| `set_embedder(embedder)` | `:289` | returns the old one; None goes back to gte-small |
| `custom_embedder() -> bool` | `:296` | a stand-in was set |

---

## 5. `src\cloud\handoff.py`: the handoff file and the publisher child

| Name | Line | Value or contract |
|---|---|---|
| `PENDING_DIR` | `:46` | `data\cloud\pending` |
| `LOG_PATH` | `:47` | `C:\Hangeul\BOT\hangeul_sync.log` |
| `STALE_HOURS` | `:48` | 6 |
| `CREATE_NO_WINDOW` | `:49` | `0x08000000` |
| `FORMAT_VERSION` | `:50` | 1 |
| `_children: List[Popen]` | `:52` | references kept so the children are not reaped mid-run |
| `_slug(job) -> str` | `:55` | `[A-Za-z0-9_-]` only, 40 characters at most, `"command"` for none |
| `_prune() -> None` | `:59` | deletes `pending\*.json*` older than 6 hours (left by killed publishers) |
| `write(job, batches, failed_reads=()) -> Path` | `:70` | prunes, then writes `{"version": 1, "job", "created_at", "failed_reads", "batches"}` (`jsonable`, `allow_nan=False`) to `<%Y%m%d-%H%M%S-%f>-<slug>.json` through `.part` + `os.replace` |
| `_python() -> str` | `:86` | `sys.executable`, with `pythonw.exe` swapped for its console twin `python.exe` |
| `child_env() -> Dict[str, str]` | `:93` | `{**os.environ, "PYTHONIOENCODING": "utf-8", "CUDA_VISIBLE_DEVICES": "-1", "HF_HUB_OFFLINE": "1"}` |
| `start(args, log) -> Popen` | `:101` | `Popen([_python(), *args], cwd=BOT_ROOT, stdin=DEVNULL, stdout=log, stderr=log, env=child_env(), close_fds=True, creationflags=CREATE_NO_WINDOW on Windows)`; the tests start their child through the same function |
| `spawn(path, timeout=CHILD_TIMEOUT) -> Popen` | `:109` | opens `hangeul_sync.log` for append and starts `-m src.cloud.publish --from <path> --timeout <int>`; not waited for |
| `submit(job, batches, failed_reads=()) -> Optional[Path]` | `:118` | never raises. None when publishing is off or there is no batch (a falsy batch is dropped). Writes and spawns (on a spawn failure the file is deleted). Any failure is one line "Supabase publish failed (<job>): the handoff could not be written or started (<type>)" |
| `async submit_async(job, batches, failed_reads=())` | `:141` | `asyncio.to_thread(submit, ...)`: a full student list is about 1 MB |

`enabled` is re-exported from `publish` (`:41`) and is part of the API: every hook calls `handoff.enabled()`.

---

## 6. `src\cloud\backfill.py`: the one-time copy and the shared readers

- `:34-35` `__main__` hides CUDA (`"-1"`). Constants: `Batches = List[Dict]`, `CONSULT_FLOOR = date(2015, 1, 1)`, `QUIET_WINDOWS = ((18, 0, 18, 10), (8, 25, 8, 40), (9, 0, 9, 10))`, `SYNC_LOCK_STALE = 2 * 3600` (`:54-58`), `_PAGED_RE` (`:242`), `ALL_SCOPES = ("", chr(0xFFFF))` (`:326`; `chr()` so no invisible character is written in the source, `a0572ba`).
- `_why(e) -> str` (`:61`) is `client.portal_error_reason(e)`.
- **`quiet_reason(at=None, data_dir=None) -> Optional[str]`** (`:66-83`): gives `"HH:MM-HH:MM is a quiet window (a scheduled job runs then)"`, or `"a portal sync is running (data/auto_sync.lock)"` when the lock is younger than 2 hours and its PID is alive (`auto_sync._pid_alive`; the lock is only read); else None.

The portal collectors all return `(batches, failed reads)`:

| Function | Line | Signature | Reads | Batches |
|---|---|---|---|---|
| `collect_students` | `:88` | `async (client, today) -> (batches, failed, students or None)` | `client.read_students()` | `student` (complete), `verification` via `batches(..., stamps_ok, verification_window(today))` |
| `collect_export` | `:107` | `async (client, total=None)` | `portal_get("students.php", {"export": "csv"}, timeout=60)`; `utf-8-sig`; requires `text/csv` or "Full Name" | `student_export`, complete per `export_complete(rows, total)` |
| `collect_documents` | `:125` | `async (client)` | `verified_docs.fetch_verified_students` | `student_documents` (complete) |
| `collect_progress` | `:135` | `async (students)` | `to_thread(stage_report.read_progress, uids)` | `student_progress`, complete when no error and every uid read |
| `_range_count` | `:154` | `async (client, first, last) -> int` | `read_consultation_view({"status": "all", "from", "to"})`; must echo the dates (else `PortalUnavailable`) | the All tab count |
| `oldest_consultation_day` | `:163` | `async (client, today, floor=CONSULT_FLOOR) -> Optional[date]` | bisection on `_range_count(floor, mid)`, about 13 reads | |
| `collect_consultations` | `:178` | `async (client, days, *, whole_range=False)` | `read_consultation_day(day)` for each day; stops at the first unreachable answer | `consultation` per day; `consultation_day` complete only with `whole_range` and no failure |
| `collect_totals` | `:206` | `async (client)` | `read_consultation_totals()` | `consultation_totals` (complete) |
| `collect_pending` | `:215` | `async (client)` | `read_student_pages({"status": "pending"})`, `parse_pending_payments` (the badge), `parse_students_page` of each page (a layout error is a failed read) | `pending_payment` per `pending_complete(pending, badge, empty)` |
| `collect_window_applications` | `:245` | `async (client)` | `fetch_html("window_applications.php?status=under_review")`, `parse_window_applications` | `window_application` per `window_complete` |
| `collect_dashboard` | `:265` | `async (client)` | `fetch_html("index.php", timeout=30)`, `ask.dashboard_facts` | `dashboard_fact` per `dashboard_complete` |
| `collect_calendar` | `:280` | `async (client, today)` | `fetch_html("calendar.php")`, `ask.calendar_items` | `calendar_item` (never complete) |
| `collect_performance` | `:294` | `async (client, periods=("today", "month"))` | `read_consult_performance(period)` each; stops at the first unreachable answer | `consultant_performance` per window |

The disk collectors:

| Function | Line | Signature | Reads | Batches |
|---|---|---|---|---|
| `_read_json`, `_mtime` | `:318-323` | | JSON; file mtime as `read_at` | |
| `collect_results` | `:329` | `(verification_dir, ids=None) -> (batches, failed, store)` | `results.json` | `doc_verdict` and `field_check` (`batches(..., True, ALL_SCOPES)`), `doc_check` (complete, `read_at` = the file's mtime), `field_correction` (partial), the DOCUMENT CHECK and FIELD CHECK `report` (partial) + `report_section` (complete) |
| `_current_files` | `:362` | `(docs_root, passport) -> {file: (size, mtime)}` | `<docs_root>\*\*(<passport>)\` | |
| `collect_page_texts` | `:377` | `(verification_dir, store, docs_root, ids=None)` | every `text\*.json` | `doc_page_text`, one complete batch per passport |
| `collect_watcher` | `:399` | `(data_dir, students=None, listed_at=None)` | `alerted_passport_issues.json` (must be version 2) | `passport_alert`, complete over `bot_jobs.watched_scans(students)` when the list is known |
| `collect_issue_dates` | `:423` | `(data_dir)` | `passport_issue.json` (`by_passport`) | `passport_issue` (complete) |
| `collect_missing_report` | `:437` | `(data_dir)` | the newest `missing_reports\missing_information_YYYY-MM-DD.xlsx` (openpyxl, `read_only`, `data_only`, rows from 2) | `report` (partial) + `report_section` (complete) |

The run:
- `_say(results, kind, complete, dry, say)` (`:463`): the counts-only progress line.
- `publish_all(batches, say=print, only=None) -> List[Result]` (`:482`): publishes each batch now, in the current run.
- `async _portal(args, today, say, failed, only) -> (students, listed_at)` (`:500-578`): own `HangeulAdminClient`, closed in `finally`. Consultations are published one day at a time, with one summary line.
- `_disk(args, say, failed, only, students=None, listed_at=None)` (`:581-611`): the student index is `remember(from_students(students), save=not dry)` or `load()`.
- **`main(argv=None) -> int`** (`:614-674`): the options `--dry-run`, `--only`, `--skip-portal`, `--skip-disk`, `--days`, `--ignore-state`, `--data-dir`, `--verification-dir`, `--docs-root`, `--force` (13 §12). The refusals give exit 2 (no CPU process, publishing off, a quiet window) and exit 1 (the lock). `--ignore-state` moves the state to `.bak` and keeps the `embed_model`. The run is `publish.run("backfill")` under `publisher_lock()`, with `asyncio.run(_portal(...))` and then `_disk(...)`.
- `:677-684` `__main__`: `prepare_process()`, stdout reconfigured to UTF-8, logging at WARNING, `sys.exit(src.cloud.backfill.main())`.
- **Stale docstring (the code wins):** the module docstring's list of portal pages (`:6-16`) leaves out `consult_performance.php`, and `:22-27` says `collect_performance` covers the Consultant Performance page "which only the hourly job reads". Since `8317741` the backfill reads it too: `_portal` runs `collect_performance(client)` as its step "consult_performance.php (today and this month)" (`:568-569`), 2 GETs.

---

## 7. `src\cloud\full_picture.py`: the hourly read and publish

| Name | Line | Contract |
|---|---|---|
| `__main__` CUDA line | `:40-41` | `CUDA_VISIBLE_DEVICES=-1` before torch |
| `JOB`, `DEADLINE`, `LOCK_WAIT`, `LEAD_MINUTES`, `PORTAL_DOWN` | `:57-61` | `"full_picture"`, 2700 s, 120.0 s, 5, `"the portal did not answer"` |
| `skip_reason(at=None, data_dir=None) -> Optional[str]` | `:66` | `backfill.quiet_reason(now)`, or the same 5 minutes ahead ("<reason>, less than 5 minutes from now") |
| `class PortalSession(HangeulAdminClient)` | `:77-92` | `down = ""`; `async portal_get(path, params=None, timeout=60.0)` raises `PortalUnavailable("<path>: not read: <down>", unreachable=True)` once `down` is set, and sets it on the first unreachable `PortalUnavailable` |
| `async collect(client, today, may_read=None) -> (batches, failed)` | `:95` | the 8 steps (students, pending, consultations of yesterday and today, totals, window applications, dashboard, calendar, performance today and month), asking `may_read()` before each; a reason stops the rest with one failed read |
| `async _read(today, client=None, may_read=None)` | `:122` | its own `PortalSession`, closed afterwards |
| `run(today=None, *, client=None, dry_run=False) -> int` | `:132` | 0 (INFO "Full picture skipped: publishing is off.") when off; a WARNING in mock mode; skipped by `skip_reason`; `publisher_lock(120)`, else skipped; `skip_reason` checked again under the lock; `asyncio.run(_read(today, client, skip_reason))`, then `publish.publish_batches("full_picture", batches, failed, dry_run)`; one INFO summary line |
| `_deadline(seconds) -> Timer` | `:164` | one line, then `os._exit(3)` |
| `main(argv=None) -> int` | `:177` | `--dry-run`; `prepare_process()` (on failure: one line, exit 2); deadline; `run()`; an unexpected exception is "internal error (<type>)", exit 1 |
| `:198-204` `__main__` | | `prepare_process()`, INFO logging, httpx at WARNING, `sys.exit(src.cloud.full_picture.main())` |

---

## 8. `src\cloud\bot_jobs.py`: the brief and the watcher (bot process)

| Name | Line | Contract |
|---|---|---|
| `HANDOFF_WAIT` | `:45` | 30.0 s |
| `BRIEF_READS` | `:48-54` | the brief's reads (`brief._PortalReads` names) and their pages: consultations, verified students, consultation totals, pending payments, window applications, dashboard, calendar |
| `now()` | `:57` | `records.now()` |
| `_mock() -> bool` | `:62` | `admin_client.mock_mode` |
| `async hand_over(job, build, *args) -> Optional[Path]` | `:67-89` | None when off, or in mock mode (one INFO). Otherwise `build(*args)` and `handoff.submit(job, batches, failed)` run in `asyncio.to_thread`, under `wait_for(timeout=30)`. A timeout is one line ("the handoff took over 30 s (the job itself was done)"); an exception is one line ("its records could not be built (<type>)"). Never raises |
| `_reason(e) -> str` | `:92` | the portal reader's words for a portal, timeout or httpx error; else "not read (<type>)" |
| `brief_failures(reads) -> List[str]` | `:104` | the brief's failed or skipped reads as `"<page>: <why>"` (from `reads["why"]`, `reads["errors"]`, a `None` pending or window read, a dashboard error, a calendar error or unrecognised layout on today's brief) |
| `_brief_figures(facts, reads, failed) -> Dict` | `:130` | the brief report's facts: `lines`, `pending_payments`, `window_apps_under_review`, `calendar_today`, `document_check`, `not_read` |
| `brief_reads(reads, read_at) -> Batches` | `:148-182` | each read only when it succeeded: the day's `consultation` (complete per the reader) and `consultation_day` (partial); `verification` for the day (complete when all rows were made and the day passes `yearless_day_problem`); `consultation_totals` (complete); the dashboard's tiles as `dashboard_fact` (partial, through `records.tile_facts`). Nothing in mock mode |
| `brief_batches(composed) -> (Batches, failed)` | `:185-199` | `report "brief\|<day>"` (partial), its `report_section` (complete), `brief_fact` (complete), plus `brief_reads`. The day is `reads["day"]`, else `dates.local_today()`; `read_at` is `reads["at"]` |
| `profile_now(uid) -> Optional[Dict]` | `:204` | the profile the client holds for `uid` now (`command_hooks.profile_of`); None while off |
| `keep_profile(profiles, uid, before) -> None` | `:217` | after an audit, keeps `(uid, profile, now)` when the client's profile is another object than `before` (a failed profile read leaves the old one) |
| `note_sent(accepted, text) -> None` | `:230` | keeps `(text, now)` of an alert message Telegram accepted |
| `listed_scans(students) -> List[str]` | `:240` | every `"uid\|passport_*"` scan the list shows |
| `_UPLOAD_TIME_RE`, `_upload_time(name) -> int` | `:249-254` | `r"passport_\d+_(\d{9,11})\b"`: the upload time in the file name (`scheduler.passport_scan`'s rule; a test pins the two together) |
| `watched_scans(students) -> List[str]` | `:257` | each listed student's newest passport scan, `"uid\|file"` |
| `watcher_batches(students, read_at, audits, memory, unchecked=0, sent=(), profiles=()) -> (Batches, failed)` | `:270-309` | `student` (complete, dated by the list read); `passport_audit` (complete, `all_keys=listed_scans`); `passport_alert` (complete, `all_keys=watched_scans`); one `student_profile` batch per uid (the last read wins, never a `_csrf` read); one `notification` per accepted alert message; a failed read "student_edit.php / view_doc.php: <n> passport scan(s) could not be checked (tried again next run)" |

---

## 9. `src\cloud\command_hooks.py`: commands and free-text answers

The pattern (docstring `:1-18`):

```python
reads = {}
students = await admin_client.read_students()
command_hooks.seen(reads, students=students)   # the read's result and when it was read
...                                             # the reply is built and sent exactly as before
command_hooks.publish(reads)                    # after the reply: returns at once
```

| Name | Line | Contract |
|---|---|---|
| `JOB` | `:68` | `"command"` |
| `STAMP_PROBLEM` | `:69` | `"students.php: a verification stamp could not be read (layout not recognised)"` |
| `_tasks: Set[Task]` | `:71` | strong references to the background tasks |
| `active() -> bool` | `:74` | `handoff.enabled()` and `admin_client.mock_mode is False` |
| `now() -> datetime` | `:87` | `records.now()` |
| `seen(reads, **values) -> None` | `:93` | when active, keeps the non-None values in `reads`, their read times in `reads["at"][name]`, and `reads["today"] = local_today()`; never raises (one line) |
| `profile_of(uid) -> Optional[Dict]` | `:112` | `admin_client._profile_cache.get(uid)`: the last `student_edit.php` profile the client read |
| `audited(card, result, form, before) -> None` | `:124` | after one cross-check audit, `card["audit"] = {"result", "form", "at", "profile"}` (the profile only when it is a new read) |
| `publish(reads, job="command") -> Optional[Future]` | `:139` | when there is something and it is active, `_background(_build_and_submit, dict(reads), job)`; never raises |
| `_background(fn, *args)` | `:151` | a task `asyncio.to_thread(fn, *args)` in the running loop (kept in `_tasks`), else a daemon thread `cloud-handoff` |
| `async drain(timeout=None)` | `:163` | waits for this loop's handoffs (tests, a clean shutdown) |
| `_build_and_submit(reads, job)` | `:171` | `build(reads)`, then `handoff.submit(job, batches, failed)`; a build failure is one line |
| `build(reads) -> (batches, failed)` | `:183-247` | turns each kept read into batches (below); drops batches with no rows that delete nothing |
| `_failed(page, why) -> str` | `:250` | `"<page>: <why>"` |
| `stamps_readable(students) -> bool` | `:255` | `telegram_bot._stamp_guard`'s rule |
| `student_list(students, today, read_at=None)` | `:263` | `student` complete, plus `verification` per day (complete within the window when the stamps are readable), plus `STAMP_PROBLEM` otherwise |
| `verification_day(day, verified, today, read_at=None) -> batch` | `:277` | the day's `verification` batch, each uid once, complete when the day passes `yearless_day_problem` |
| `consultation_batches(on_day, read_at=None)` | `:293` | `consultation` for the day (complete per the reader) and `consultation_day` (partial) |
| `inquiries_report(on_day, text, totals, read_at=None)` | `:308` | `report "inquiries_report\|<day>"` (partial) and its sections (complete) |
| `tile_facts(tiles)` | `:327` | `records.tile_facts` |
| `audit_batches(cards, students)` | `:335` | `passport_audit` (partial, one per scan) and one `student_profile` batch per profile read (complete, never a `_csrf` read) |

What `seen()` keys become in `build()` (docstring `:20-53`):

| `seen()` key | Value | Batches |
|---|---|---|
| `students` | `read_students()` (every page, no filter) | `student_list`: `student` complete + `verification` per day |
| `page` | `read_students(all_pages=False)` (`/students`) | `student`, partial |
| `verified` | `(day, read_verified_students(day))` | `verification_day` |
| `consultations` | `read_consultation_day(day)` | `consultation_batches` (+ `inquiries_report` when that key is kept too) |
| `totals` | `read_consultation_totals()` | `consultation_totals`, complete |
| `totals_error` | the reason the totals were not read | a failed read |
| `inquiries_report` | the `/inquiries` text as sent | `report` + `report_section` |
| `facts` | `ask.dashboard_facts` of `index.php` | `dashboard_fact`, complete per `dashboard_complete` |
| `dashboard` | `client.get_dashboard()` | its tiles as `dashboard_fact`, partial; its `error` is a failed read |
| `pending` | `(students of every pending page, badge)` | `pending_payment` per `pending_complete(pending, badge)`, with a failed read when not complete |
| `calendar` | `ask.calendar_items` | `calendar_item`, never complete |
| `cards` | the audited cross-check cards | `audit_batches` |
| `performance` | `(period, read_consult_performance(period))` | `consultant_performance_batch` |

The module docstring at `:45-49` still describes the performance scope as `"<period>|<first day>|<last day>"`. That is stale since `8317741`, which made the scope `"<period>|<first day>"` in `records.performance_scope`. (The two other stale texts at `8317741` that touch this layer: `backfill.py:6-16` / `:22-27`, §6, and the comment `scheduler.py:490`, [03a §9](03a_FILES_src_bot.md); all three are listed in [13 §18](13_SUPABASE_PUBLISHING.md) item 3.)

---

## 10. `src\cloud\sheet_hooks.py`: the subprocess sheet jobs

| Name | Line | Contract |
|---|---|---|
| `JOB_SYNC`, `JOB_MISSING`, `JOB_STAGE`, `JOB_ISSUE` | `:41-44` | `portal_sync`, `missing_report`, `stage_report`, `issue_refresh` |
| `CATCH_UP_PASSPORTS` | `:48` | 6 |
| `on() -> bool` | `:56` | `handoff.enabled()`, False on any doubt: the jobs keep what they read only then |
| `hand_over(job, build) -> Optional[Path]` | `:65` | when on: `build()`, then `handoff.submit(job, [b for b in batches if b and b.get("rows")], failed)`. Batches without rows are left out: a complete batch is never sent empty from a job. Never raises, **never prints** (a button report's stdout is its reply); one line on failure |
| `_URL_RE`, `reason(what, e) -> str` | `:80-99` | `"<what>: <portal words or 'could not be read (<type>)'>"`, URLs replaced by `<url>`, 200 characters at most |
| `_at(ts) -> str`, `_today() -> str` | `:102-112` | an epoch time as `read_at` (Dhaka); today's ISO day |
| `line_sections(lines)` | `:115` | each margin line opens a section, the indented lines are its lines |
| `_report(name, when, text, facts, source, read_at, sections) -> Batches` | `:130` | `report` (partial) + `report_section` (complete) |
| `_notification(text, sent_at, source, title="")` | `:141` | one `notification` batch (partial) |
| `store_readable(path) -> bool` | `:149` | `results.json` readable as an object, or missing (a fresh start) |
| `sync_batches(cloud) -> Built` | `:160-213` | from what `auto_sync.run_once` kept (keys below): `student_export` (per `export_complete(rows, listed_students())`, else a failed read); `student_documents` (complete; `None` or `[]` is a failed read); `report "sync_summary\|<run_at>"` when the summary had lines; `verify_batches` of the check; one `notification` per notice Telegram accepted |
| `listed_students() -> int` | `:216` | `len(publish.known_keys("student", "all"))` |
| `student_ids(documents, export)` | `:226` | `student_index.remember(from_export(export), from_documents(documents))` |
| `_folder_files(folder)` | `:234` | `{file: (size, mtime)}` of a student's folder |
| `_page_texts(passport, name, folders, failed, ids=None)` | `:246` | the `doc_page_text` records of one OCR cache, dated by the cache file's mtime |
| `verify_batches(result, store_ok=True, folders=None, ids=None) -> Built` | `:266-333` | the checked passports plus up to 6 never accepted (`known_scopes("doc_verdict") \| known_scopes("field_check")`): `doc_verdict`, `field_check` and `doc_page_text` per passport, complete, **first**; then, from the whole store, `doc_check` (complete, `read_at` = now), `field_correction`, and the DOCUMENT CHECK / FIELD CHECK reports. With `store_ok` False the store-wide kinds are not sent, and there is a failed read |
| `_MISSING_COLUMNS` | `:338` | `(program, intake, student_id, full_name, mobile, missing_count, missing_fields)` |
| `missing_daily(lines, rows, sent_at) -> Built` | `:341` | `report "missing_report\|<today>"` + one section per incomplete student, and a `notification` when Telegram accepted it |
| `missing_failed(notice, sent_at, error) -> Built` | `:355` | the failure notice as a `notification`, and a failed read "progress sheets or the portal: ..." |
| `missing_program(program_key, text, data, index) -> Built` | `:361` | `report "missing_program:<KEY>\|<today>"` with every student's missing fields (`missing_report.build_report` on the program's sheets) |
| `stage_batches(program_key, intake, text, reads) -> Built` | `:381` | `student_progress` of the pages read (partial), and `report "stage_report:<KEY>:<INTAKE>\|<today>"` with counts and students |
| `issue_batches(by_passport, pages, complete) -> Built` | `:418` | `passport_issue` (complete when the refresh had no `--limit`), and `student_profile` of every edit page read (`HangeulAdminClient._profile_fields(html)`, `batches` with each uid its own complete scope) |
| `after_sync(cloud)` | `:441` | `hand_over("portal_sync", sync_batches)` |
| `after_missing_daily(lines, rows, sent_at)` | `:446` | `hand_over("missing_report", missing_daily)` |
| `after_missing_failed(notice, sent_at, error)` | `:451` | `hand_over("missing_report", missing_failed)` |
| `after_missing_program(program_key, text, data, index)` | `:456` | `hand_over("missing_report", missing_program)` |
| `after_stage(program_key, intake, text, reads)` | `:462` | `hand_over("stage_report", stage_batches)` |
| `after_issue_refresh(by_passport, pages, complete)` | `:467` | `hand_over("issue_refresh", issue_batches)` |

The keys of `auto_sync`'s `cloud` dict (docstring `:161-169`): `run_at` (epoch start), `export` (progress_builder's CSV rows, or None), `sheets_error`, `documents` (`verified_docs.run_local`'s `"students"`, or None), `documents_at`, `docs_error`, `title`, `lines` (the summary as built), `sent` (`[(title, lines, epoch)]` of each notice Telegram accepted), `verify` (`auto_verify.run`'s result, or None), `verify_error` and `store_ok`.

---

## 11. `src\cloud\student_index.py`: passport to (uid, HNG id)

| Name | Line | Contract |
|---|---|---|
| `INDEX_PATH`, `VERSION` | `:31-32` | `data\cloud\student_index.json`, 1 |
| `Ids` | `:34` | `Dict[str, Tuple[str, str]]` |
| `_key(passport) -> str` | `:37` | `passport_key` |
| `_found(triples) -> Dict[str, Dict[str, str]]` | `:42` | `(passport, uid, hng)` readings of one list: a field only when shown, `""` when the list shows two different values for that passport; a uid must be digits below 2³¹, an HNG id must start `HNG-` |
| `from_students(students)` | `:68` | details Passport No, uid, `student_id` |
| `from_documents(rows)` | `:74` | passport, uid |
| `from_export(rows)` | `:79` | Passport No, Student ID |
| `_read()` | `:84` | the file, `{}` when missing, cut short, or the wrong version |
| `_ids(index) -> Ids` | `:97` | entries with a uid or an HNG id |
| `load() -> Ids` | `:102` | as kept; `{}` and one line on failure |
| `remember(*readings, save=True) -> Ids` | `:112` | merges (a newer reading replaces the older, a field not shown is left), saves when changed (`.part` + `os.replace`; not with `save=False`, a dry run), never raises |

---

## 12. Every hook call site outside `src\cloud\`

### 12.1 The scheduler, in the bot process (`src\bot\scheduler.py`)

| Line | Function | What it does for Supabase |
|---|---|---|
| `:17` | module | `from src.cloud import bot_jobs` |
| `:131-155` | `_send_alerts(bot, chat_id, cache, keys, accepted=None)` | after each alert message Telegram accepted: `bot_jobs.note_sent(accepted, text)` (`:154`) |
| `:158-245` | `check_new_passport_uploads(bot_application)` | `listed_at = bot_jobs.now()` right after `read_students()` (`:174`). Before each audit, `profile_before = bot_jobs.profile_now(uid)` (`:204`); after it, `bot_jobs.keep_profile(profiles, uid, profile_before)` (`:212`). Each remembered audit is kept as `(s, scan, form, result, bot_jobs.now())` (`:229`). **Last**, after the memory is saved and the alerts sent: `await bot_jobs.hand_over("passport_watcher", bot_jobs.watcher_batches, students, listed_at, checked, cache, failed, accepted, profiles)` (`:243`) |
| `:248-278` | `send_daily_briefing(bot_application)` | after the text brief and the spoken brief: `await bot_jobs.hand_over("daily_brief", bot_jobs.brief_batches, composed)` (`:278`) |
| `:363-366` | constants | `FULL_PICTURE_MINUTES = 60`, `FULL_PICTURE_FIRST_MINUTES = 7.5` |
| `:369-389` | `run_full_picture()` | nothing while `bot_jobs.handoff.enabled()` is False; `full_picture.skip_reason()` (one INFO line when skipped); else `await _run_module("src.cloud.full_picture", "Full picture publish")` |
| `:500-508` | `setup_scheduler` | `add_job(run_full_picture, IntervalTrigger(minutes=60, start_date=now + 7.5 min), id="cloud_full_picture", replace_existing=True, max_instances=1, coalesce=True)` |
| `:512-513` | `setup_scheduler` | the start line ends ", Supabase full picture every 60m." when publishing is on |

### 12.2 The command handlers (`src\bot\telegram_bot.py`; the root `telegram_bot.py` is byte-identical, R24)

Each handler makes `reads: Dict[str, Any] = {}`, calls `cloud.seen(reads, ...)` right after each successful read, and calls `cloud.publish(reads)` **after its reply is sent** (not awaited). `cloud` is `src.cloud.command_hooks`.

| Lines | Function (commands) | `seen()` keys | Published |
|---|---|---|---|
| `:233-245` | `stats_command` (`/stats`) | `dashboard=get_dashboard()` | `dashboard_fact` tiles (partial) |
| `:247-277` | `students_command` (`/students`) | `page=get_applications()` (page 1 only) | `student` (partial) |
| `:346-372` | `admitted_command` (`/admitted [query]`) | `students=result["listed"]`, `dashboard=result["dashboard"]` | `student` (complete), `verification` per day, tiles |
| `:534-569` | `build_inquiries_report(target_date_input, strict, reads)` | `consultations=on_day`, then `totals` / `totals_error`, then `inquiries_report=<text>` | `consultation` (day), `consultation_day`, `consultation_totals`, `report inquiries_report` |
| `:572-587` | `_send_inquiries_report` (`/inquiries_today`, `/inquiries_date`, `/inquiries`, `/consultations`) | through `build_inquiries_report` | publishes after the reply |
| `:718-739` | `_send_performance_report(update, kind)` (`/performance_today` `:742`, `/performance_month` `:752`, `/perf_today`, `/perf_month`, `/performance [today\|month]` `:762`, and the free-text performance routes) | `performance=(kind, page)` (in `performance.build_performance_report`) | `consultant_performance` |
| `:788-796` | `alerts_command` (`/alerts`) | through `ask.reply(Route("dashboard", topic="attention"))` | `dashboard_fact` |
| `:858-912` | `verified_command` (`/verified_today`, `/verified_date`, `/verified`, `/verified_students`) | `verified=(day, get_verified_students(day))`, after the day passed the date checks | `verification` for the day |
| `:969-1008` | `passports_command` (`/passports`, `/passport_audit`) | `students=read_students()`; after `_audit_cards`, `cards=cards[:PASSPORTS_OCR_MAX]` | `student`, `verification`, `passport_audit` (partial), `student_profile` |
| `:1095-1135` | `calendar_command` (`/calendar <words>`, `/events <words>`, `/deadlines <words>`; a bare command is today's default view and publishes nothing) | through `ask.answer_calendar(question, reads=reads)` | `calendar_item` |
| `:1621-1648` | `_audit_cards(cards, status_msg, what)` | before each audit `profile_before = cloud.profile_of(id)` (`:1641`); after it `cloud.audited(c, res, form, profile_before)` (`:1648`) | (the cards carry the audit to `cards`) |
| `:1745-1800` | `build_crosscheck_report(query, status_msg, reads)` | `students=read_students()` (`:1755`), `cards=cards` (`:1799`) | `student`, `verification`, `passport_audit` (partial), `student_profile` |
| `:1803-1817` | `_crosscheck_run` (`/crosscheck_*`, `/crosscheck`, `/audit`) | through `build_crosscheck_report` | publishes after the reply |
| `:1973-2170` | `handle_natural_language_message` | routes to the handlers above, or to `ask.reply(update.message, route, query)` (`:2170`) | as those |

### 12.3 The free-text answers (`src\bot\ask.py`)

| Lines | Function | `seen()` keys |
|---|---|---|
| `:870-879` | `answer_dashboard(route, query, *, reads=None)` | `facts=<index.php facts>` (`:878`) |
| `:882-907` | `answer_pending(*, reads=None)` | `pending=(students of every pending page, badge)` (`:907`), after every page was read with its layout known |
| `:937-951` | `answer_window_review(*, reads=None)` | `facts` (the dashboard read for the Under review tile, `:951`); the window rows themselves are not kept |
| `:975-987` | `answer_intake(route, query, *, reads=None)` | `students=read_students()` (`:987`) |
| `:1009-1026` | `answer_applied(route, *, reads=None)` | `students` (`:1026`) |
| `:1038-1050` | `answer_unknown(query, *, reads=None)` | `facts` (`:1050`) |
| `:1065-1092` | `reply(message, route, query)` | makes `reads`, calls the answer, replies, then `cloud.publish(reads)` (`:1092`) |
| `:1395-1410` | `answer_calendar(q, *, reads=None)` | `calendar=items` (`:1410`), only when the layout was recognised |
| `:683-690` | `dashboard_facts(html)` | `decode_cf_emails(BeautifulSoup(html, "html.parser"))` (`:690`) |

### 12.4 `src\bot\performance.py` and `src\bot\brief.py`

- `performance.build_performance_report(kind, today=None, reads=None) -> str` (`performance.py:281-303`): after `admin_client.read_consult_performance(kind)` succeeded, `cloud.seen(reads, performance=(kind, page))` (`:299`). A page that was not read keeps nothing. The module docstring (`:28`) names the path.
- `brief.Brief(text, facts, reads=None)` (`brief.py:76-81`) is a NamedTuple whose third field carries what the brief's portal reads returned, for `bot_jobs.brief_batches`; the text and facts never depend on it. `compose_brief` fills it (`brief.py:656-662`): `{"day", "today", "at", "is_today", "mock", "consultations", "verified", "verified_why", "consultation totals", "pending payments", "window applications", "dashboard", "calendar", "documents", "why", "errors", "down"}`.

### 12.5 The sheet jobs (subprocesses)

| File:lines | Function | What it does for Supabase |
|---|---|---|
| `src\sheets\auto_sync.py:275-285` | `sync_docs(cloud=None)` | `cloud["documents"], cloud["documents_at"] = result["students"], started` |
| `auto_sync.py:315-326` | `verify_docs(cloud=None)` | before the check, `cloud["store_ok"] = sheet_hooks.store_readable(av.STORE_PATH)`; after it, `cloud["verify"] = result` |
| `auto_sync.py:412-480` | `run_once(send=True, verify=True)` | `cloud = {"run_at": time.time(), "title": SYNC_TITLE, "sent": []}` only when `sheet_hooks.on()` (a failure to load is one line). It keeps `sheets_error`, `docs_error`, `lines`, each accepted notice in `sent`, and `verify_error`. **Last of all:** `cloud["export"] = pb._ALL_STUDENTS_CACHE; sheet_hooks.after_sync(cloud)` (`:475-477`) |
| `src\sheets\missing_report.py:280-288` | `_supabase(call)` | `call(sheet_hooks)`; never raises or prints (one line) |
| `missing_report.py:314` | `main` (`--program KEY`, the `/missing` button) | `_supabase(lambda h: h.after_missing_program(key, text, data, index))` after the list was printed |
| `missing_report.py:347` | `main` (the daily run, report not built) | `_supabase(lambda h: h.after_missing_failed(notice, sent_at, e))` after the notice was sent |
| `missing_report.py:354` | `main` (the daily run) | `_supabase(lambda h: h.after_missing_daily(lines, rows, sent_at))` after the text and the Excel file went to Telegram |
| `src\sheets\stage_report.py:178-205` | `stage_report(program_key, intake, listed=None, progress=None, reads=None)` | new `reads` parameter: filled with `matched`, `pages`, `by_stage` |
| `stage_report.py:240-261` | `main` (`--intake`, the `/stage` button) | `reads = {}`; `text = stage_report(key, intake, reads=reads)`; `print(text)`; then `sheet_hooks.after_stage(key, <normalised intake>, text, reads)` (`:257-258`); a failure is one line; nothing after a failed read |
| `src\sheets\passport_issue.py:85` | `_fetch_async` | `pages[str(uid)] = (html, time.time())` for each edit page read, when a `pages` dict was given |
| `passport_issue.py:113-118` | `_supabase_on()` | `sheet_hooks.on()`, False on any error |
| `passport_issue.py:129-141` | `main` (`--refresh`, 08:30) | `pages = {} if args.refresh and _supabase_on() else None`, so the edit pages are kept only while publishing is on; after the cache file is written, `sheet_hooks.after_issue_refresh(data, pages, not args.limit)` (`:138-139`) |
| `src\sheets\verified_docs.py:44-47` | `_parse_rows(html)` | `decode_cf_emails(BeautifulSoup(html, "html.parser"))` |
| `verified_docs.py:330-350` | `run_local(root, limit=0, skip_drive_done=True)` | the result gains `"students": listed`, every verified student the list showed (the whole list, whatever `limit` is) |

### 12.6 The scraper (`src\scraper\client.py`, `src\scraper\parsers.py`)

- `parsers.py:12-97`: `_CF_CLASS = "__cf_email__"`, `_CF_LINK = "/cdn-cgi/l/email-protection#"`, `_HEX_RE`, `_cf_address(hexstr) -> str` (`:24`), `_is_cf_email(tag) -> bool` (`:42`), `_put_text(el, text)` (`:47`), **`decode_cf_emails(node) -> node`** (`:64`). The rules are in 13 §6.3.
- `decode_cf_emails` is called at `parsers.py:116` (`extract_csrf_token`), `:138` (`parse_tables`), `:185` (`parse_dashboard_metrics`), `:276` (`parse_hangeul_live_dashboard`), `:438` (`parse_students_page`), `:566` (`parse_progress_page`), `:618` (`consultation_rows`), `:626` (`consultation_table`), `:688` (`consultation_view`), `:896` (`parse_pending_payments`), `:924` (`parse_window_applications`), `:1120` (`parse_consult_performance`) and `:1326` (`parse_calendar_events`).
- `parsers.py:328` `_EMAIL_HIDDEN_GAP_RE = re.compile(r"\s*\[email\s*protected\]\s*", re.I)` and `:707-710` `_without_hidden_email(text)`: the stand-in removed from a longer text.
- `client.py:57-58` `PERFORMANCE_PAGE = "consult_performance.php"`, `PERFORMANCE_PERIODS = {"today": "Today", "month": "This Month"}` (read by `records._performance_title`).
- `client.py:425-452` `async read_consult_performance(period) -> Dict`: one GET through `fetch_html`, parsed in a thread. It raises `ValueError` for another period, and `PortalUnavailable` in mock mode, for a layout error, or for a page that shows another period.
- `client.py:236-267` `get_admitted_students(query=None)`: now also returns `"listed"` (every student read) and `"dashboard"` (`get_dashboard()`'s read, None in mock mode), which `/admitted` publishes.
- `client.py:614`, `:721`: `decode_cf_emails` on the `student_edit.php` soups (the profile read and `_profile_fields`). Input `value` attributes are kept as they are; `records.student_profile` blanks a stand-in value as a filler.
- `client.py:598`, `:624`, `:662`: `_profile_cache[...]`, which `command_hooks.profile_of` reads.

### 12.7 Package level

- `src\__init__.py:38-79`:
  - `_SECRET_PATTERNS` (`:41`) holds the bot token, `Bearer`, `apikey`, `sb_secret_`, `sb_publishable_`, `sbp_` and JWT patterns;
  - `redact(text) -> str` (`:52`);
  - `_RedactBotToken.filter` (`:59`) now covers every pattern and never fails on a record whose message cannot be built;
  - the filter is attached (`:77-79`) to `httpx`, `httpcore`, `httpcore.connection`, `httpcore.http11`, `httpcore.http2`, `httpcore.proxy`, `httpcore.socks` and `hangeul.cloud`.
- `src\config.py:82-92` (and the byte-identical root `config.py`): `SUPABASE_URL: str = ""`, `SUPABASE_SECRET_KEY: str = ""`, `CLOUD_PUBLISH_ENABLED: bool = False`, `CLOUD_EMBED_MODEL: str = "thenlper/gte-small"`, `CLOUD_EMBED_REVISION: str = "17e1f347d17fe144873b1201da91788898c639cd"`.
- `.env.example:106-118`: the five keys by name, with `CLOUD_PUBLISH_ENABLED=false`. It says the CLI's personal access token is not read by the bot.
- `requirements.txt:38-44`: `sentence-transformers==6.1.0`, `transformers==5.17.0`.
- `tests\conftest.py:20-29`: publishing is **off in every test by default** (an autouse fixture `_no_real_supabase` blanks the URL and key and sets the flag False), so no test can reach a real Supabase.

### 12.8 What the layer takes from the rest of the bot

`records.py`, `backfill.py`, `full_picture.py` and the hooks never re-parse a page: they call these helpers, whose output shapes a key, a scope, a day or a record's data. A rebuild must copy each contract exactly, or the keys and scopes (and so the deletes by `p_all_keys`) come out different. Lines are at `8317741`.

| Helper (where) | Contract: inputs → output, and the rule that shapes a key or scope | Used by | Documented in |
|---|---|---|---|
| `src.dates.yearless_day_problem(day, today) -> Optional[str]` (`dates.py:245-259`) | `"a date in the future"` when `day > today`; a reason when the same day and month has come round again (`day` + 1 year ≤ `today`; 29 Feb → 1 Mar), because the portal's verification stamps have no year; else `None` | `records.verification_window` / `verification_day` (the `verification` scopes), `command_hooks.verification_day`, `bot_jobs.brief_reads` | [03b §2.4](03b_FILES_src_scraper_llm_api_config.md) |
| `src.dates.parse_portal_date(text) -> Optional[date]` (`dates.py:218-227`) | the first full `DD Mon YYYY` in a portal text (`"Applied On 27 Sep 2026, 17:16"`); a yearless stamp is skipped; an impossible date → `None` | `records.iso_day` (every portal-text `day`), `performance._range_dates` | [03b §2.4](03b_FILES_src_scraper_llm_api_config.md) |
| `src.sheets.passport_issue.passport_key(value) -> str` (`passport_issue.py:47-51`) | `re.sub(r"\s+", "", value or "").upper()`, kept only when it has at least 6 characters and a digit, else `""` (blank, "—", PENDING) | `records._passport` (the `passport_no` column; the scope of `doc_verdict`, `field_check`, `doc_page_text`; the key of `doc_check`, `passport_issue`), `student_index`, `sheet_hooks` | [03c §1.6](03c_FILES_sheets_verify_root_scripts.md) |
| `src.sheets.auto_sync._row_key(rec) -> str` (`auto_sync.py:109-116`) | `Student ID:<clean_value(ID).upper()>`, else `Passport No:<_passport_no>` (clean_value, no whitespace, upper-cased, ≥ 6 characters with a digit), else `NAME:<_norm_key(Full Name)><_norm_key(Mobile)>` (`_norm_key` = lower-case, `[^a-z0-9]` removed); `records.student_exports` calls it with Mobile passed through `progress_builder.normalize_phone` first, and `unique_keys` adds `#2`, `#3` | the `student_export` key | [03c §1.2](03c_FILES_sheets_verify_root_scripts.md), 13 §5.5 |
| `src.scraper.parsers.verification(student, day) -> Optional[dict]` (`parsers.py:814`) | the row's "Payment verified by NAME · 27 Sep, 17:19" stamp when it is on `day` (a date), as `{student_id, uid, name, program, amount, paid, verified_income, method, verified_by, verified_time}`; `amount` = verified income, else paid; the caller must reject a day `yearless_day_problem` refuses | `records.verification` (data), `records.verification_day` | [03b §4.6](03b_FILES_src_scraper_llm_api_config.md) |
| `src.scraper.parsers.payment_text(v) -> str` (`parsers.py:851-859`) | `"<amount> <method>"`; when paid and verified income differ, `"Paid <paid> <method> (verified income <income>)"`; `""` with no payment | the `student` and `verification` texts (and so their hashes) | [03b §4.6](03b_FILES_src_scraper_llm_api_config.md) |
| `src.scraper.parsers.count_under_review(rows) -> int` (`parsers.py:948-950`) | rows whose `_label_key(status) == "under review"` (`under_review`, `Under Review`...) | `records.window_applications` applies the same rule (which rows are records), and `window_complete` | [03b §4.9](03b_FILES_src_scraper_llm_api_config.md) |
| `HangeulAdminClient.read_consultation_day(day) -> dict` (`client.py:382`) | one GET `consult_requests.php?status=all&from=DAY&to=DAY` → `{"day": date, "counts": the status tabs ("All" = received), "rows": the day's requests, newest first, "complete": every one of them listed}`; raises `PortalUnavailable` when the filter was not applied, a row is from another day or undated, or the counts disagree | `backfill.collect_consultations`, `command_hooks` (`consultations`), the brief; `records.consultations` (scope = the day; complete = `"complete"`) | [03b §3.7](03b_FILES_src_scraper_llm_api_config.md), [03a §4.3](03a_FILES_src_bot.md) row 1 |
| `src.scraper.parsers._consultation_table_rows(table)` (`parsers.py:718`) | needs the name and status columns (found by header words); each row becomes a dict with the portal's hidden request id where the row carries one, and `"Unassigned"` for a blank or "—" consultant (`records.FILLED_CONSULTANT` blanks it again) | the `consultation` key (the portal id; else sha1 of name + contact + received) | [03b §4.7](03b_FILES_src_scraper_llm_api_config.md) |
| `src.bot.performance._range_dates(text) -> Optional[(date, date)]` (`performance.py:93`) and the page dict of `parsers.parse_consult_performance` | `"01 Sep – 30 Sep 2026"` → (1 Sep 2026, 30 Sep 2026): the last day by `parse_portal_date`, the first day's month by `_RANGE_START_RE`, a year earlier when that month is after the last day's; the page dict holds `period`, `period_label`, `range_text`, `scope_note`, `tiles`, `top`, `columns`, `leaderboard` (each row `rank`, `name`, `top`, the six figures, `extra`), `count`, `empty_text`, `sort_note`, `score_help`, `points_help` | `records.performance_scope` (`"<period>\|<first ISO day>"`), the record `day` (the last day), every `consultant_performance` key | [03a §6a.2-§6a.3](03a_FILES_src_bot.md), [03b §4.12](03b_FILES_src_scraper_llm_api_config.md) |
| `HangeulAdminClient._profile_fields(html) -> {name: value}` (static, `client.py:716-736`) and `_profile_cache` (`:597-662`) | `student_edit.php`'s form: an input's `value`, a textarea's text, a select's chosen option; empty fields, `_csrf`, password / submit / button inputs left out; the first of a repeated name kept. `_profile_cache[uid]` holds the last profile read | `records.student_profile` (data), `sheet_hooks` (issue refresh), `command_hooks.profile_of` / `bot_jobs.profile_now` | [03b §3.8](03b_FILES_src_scraper_llm_api_config.md) |
| `src.sheets.stage_report.read_progress(uids)` (`stage_report.py:68`) | each `progress.php?uid=N` with a session of its own, 4 at a time → `{uid: {"pct", "stage", "status"}}` or `{uid: {"error": why}}`; once the portal stops answering, the rest get the same reason | `backfill.collect_progress` (`student_progress`, complete only with no error and every uid read), `sheet_hooks.after_stage` | [03c §1.5](03c_FILES_sheets_verify_root_scripts.md) |
| `src.sheets.verified_docs.fetch_verified_students(client)` (`verified_docs.py:71-80`) and `run_local(...)["students"]` (`:330-350`) | every page of `students.php?source=direct&filter_docs=verified`, de-duplicated by uid → rows `{uid, name, passport, program, docs}`; raises `PortalUnavailable` rather than return a partial list. `run_local` returns that whole list as `"students"`, whatever `limit` is | `student_documents` (complete), `student_index.from_documents` | [03c §1.3](03c_FILES_sheets_verify_root_scripts.md) |
| `src.bot.ask.dashboard_facts(html) -> List[Fact]` (`ask.py:683`) and `Fact(group, label, value, text, note="")` (`ask.py:657-663`) | the index.php tiles (group `"Dashboard"` for a tile outside every group) and the 5 cards, each figure with the portal's own label | the `dashboard_fact` key `<group>\|<label>` (`records.FILLED_TILE_GROUP` blanks `"Dashboard"`) | [03a §6.6](03a_FILES_src_bot.md) |
| `src.bot.ask.calendar_items(html, today) -> (List[CalItem], bool)` (`ask.py:1243`) and `CalItem` (`ask.py:1097`) | the month's `var EV` list, today's reminders and the 45-day timeline merged, matched by the portal's event id; kind `"Event"` when the page shows none; `bool` = layout recognised | the `calendar_item` key (event id, else `t:`sha1; `records.FILLED_CALENDAR_KIND` blanks `"Event"`) | [03a §6.8](03a_FILES_src_bot.md) |
| `src.bot.telegram_bot._stamp_guard(students)` (`telegram_bot.py:1555-1568`) | raises `PortalUnavailable` when there are student rows but no "Payment verified by" line, or a line whose stamp `parse_stamp` cannot read | `command_hooks.stamps_readable` (`command_hooks.py:255`) and `records.batches(..., stamps_ok, ...)` copy its rule: the `verification` batches are complete only when it passes | [03a §8.7](03a_FILES_src_bot.md) |
| `src.bot.scheduler.passport_scan(student)` (`scheduler.py:74-78`) and `UNCHECKED_STATUSES` (`:39`) | the newest `passport_*` file of the student's `files`, ordered by the upload time in `passport_<uid>_<unixtime>` (`_UPLOAD_TIME_RE`, `:36`); `("MISSING_DOCUMENT", "PORTAL_UNREADABLE", "OCR_UNAVAILABLE")` = audits that checked nothing | `bot_jobs.watched_scans` (the `passport_alert` all-keys), `records.UNCHECKED_AUDITS` (the same three plus `"ERROR"`) | [03a §5.3](03a_FILES_src_bot.md) |
| `data\verification\results.json` and `data\verification\text\<PASSPORT>.json` (`auto_verify.STORE_PATH`, `TEXT_DIR`, `auto_verify.py:48-49`) | the store: `documents[P]` (`fingerprint`, `checked`, `student`, `program`, `verdict`, `rows` of `{doc, file, verdict, detail}`), `fields[P]` (`rows` of `{field, portal, result, detail}`), `corrections[]`; the OCR cache: whole-file text by `"{file}:{size}:{mtime}:{max_pages}"` and per-page text by `"PAGES:{file}:{size}:{mtime}:{max_pages}"` | `doc_verdict`, `doc_check`, `field_check`, `field_correction`, the two check reports; `doc_page_text` (only the version whose size and mtime match the file now on disk) | [07 §10.7](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md), [03c §2.5](03c_FILES_sheets_verify_root_scripts.md) |
| `src.bot.brief.compose_brief(...)` → `Brief.reads` (`brief.py:656-662`) | the dict of what the brief's portal reads returned: `day`, `today`, `at`, `is_today`, `mock`, `consultations`, `verified`, `verified_why`, `consultation totals`, `pending payments`, `window applications`, `dashboard`, `calendar`, `documents`, `why`, `errors`, `down` | `bot_jobs.brief_batches` | §12.4, [03a §4.4](03a_FILES_src_bot.md) |

---

## 13. The tests that pin `src\cloud\`

All run with no network: a fake Supabase on `httpx.MockTransport` answers `hg_sync` and `hg_runs` as the migration's SQL does (upsert by `(kind, key)`, `unchanged` for the same hash, deletes by `p_all_keys` in `(kind, scope)`, append-only `field_correction`) and fails the test on any other host, path or method. The fake portal and fake Telegram come from [10 §2](10_TESTS_AND_VERIFICATION.md), and the embedder is `StubEmbedder`. The whole suite is 1,152 tests at `8317741`; 2 skip in the live checkout by design, because of the real `.env`.

| File | Test functions | What it pins |
|---|---|---|
| `tests\test_cloud.py` | 59 | every kind from synthetic reader output with no placeholder anywhere; `content_hash`; only changed rows sent; a partial read deletes nothing; a complete read without a student deletes exactly that student; 200 rows a call and `p_all_keys` on the last call only; long records chunked with the heading; a 500, a timeout and a refused key cost one line and leave the state; `hg_runs` POST and PATCH; the dry run; the handoff (one atomic file, a child started without waiting, UTF-8, no window, CUDA hidden, output to the sync log); secret redaction; one slow test with the real cached gte-small |
| `tests\test_cloud_all.py` | 5 | where the hook branches meet: one record per tile whichever read made it; a cross-check audit survives the watcher's complete publish; every hook's job name is in `JOBS`; the real scheduler registers the hourly full picture exactly once (60 min, first after 7.5 min, `max_instances=1`, `coalesce=True`) and it starts nothing while off |
| `tests\test_cloud_bot_jobs.py` | 29 | the watcher's handoff (student complete, audits complete over the listed scans, alerts complete over the watched scans, nothing from a list not read whole); the brief's handoff (the brief, sections, facts, each read only when it succeeded); the full picture's pages, quiet windows, lock and portal-down path (8 failed reads when the portal is down) |
| `tests\test_cloud_cf_email.py` | 18 | `decode_cf_emails` (the a, span and link forms, a round trip over several keys, malformed HEX left alone, no network, idempotent, input values kept); every soup in `src\` is wrapped (13 in parsers, 2 in client, 1 in ask, 1 in verified_docs); end to end through students.php and consult_requests.php; one log line with an empty model cache |
| `tests\test_cloud_commands.py` | 29 | each command and free-text answer hands over the right kind, scope and complete flag, one handoff per command, after the reply; the reply is identical with publishing on or off; nothing in mock mode |
| `tests\test_cloud_dry_run.py` | 17 | the dry run's findings: whole-cell fillers and `blank_on_portal`, status "Pending" kept, a Bangla text kept; one line for an unavailable model; a real child started as the handoff starts it sees no GPU (`-1`); an empty CUDA value is not a CPU-only process; the body-size split |
| `tests\test_cloud_fixes.py` | 30 | the review's findings: gone keys forgotten only after an accepted delete; the digest never makes an unanswered call look sent; locally unchanged counted; read ordering; the model guard; `pending_complete`, `window_complete`, `export_complete`; the watcher memory never deletes alerts; the quiet windows before every page; reader fillers blanked; the student index |
| `tests\test_cloud_jobs.py` | 26 | the sheet jobs: the sync (export, documents, summary, notices, the document check's kinds and the order passport-first); the missing report (daily, failed, per program); `/stage`; the issue refresh; nothing built or printed while off |
| `tests\test_cloud_performance.py` | 20 | `consultant_performance`: keys, the stable scope `"<period>\|<first day>"`, day, data and text of rows and the summary; complete only for a whole read; a later read deletes exactly the consultant who is gone; the commands publish after the reply; the full picture's 2 GETs and a failed period |

Counts are test functions (`def test_`); parametrised cases add more collected tests.

---

## 14. Files the layer reads and writes at run time (all gitignored under `data\`)

| Path | Written by | Contents |
|---|---|---|
| `data\cloud_state.json` | `publish.save_state` | the hash state (13 §7.2); 2.2 MB on 30 Sep |
| `data\cloud_state.json.part` | `save_state` | the atomic-write temp file |
| `data\cloud_state.json.bak` | `backfill --ignore-state` | the moved state |
| `data\cloud\publish.lock` | `publisher_lock` | the OS lock file (1 byte locked; empty) |
| `data\cloud\pending\<time>-<job>.json` | `handoff.write` | one handoff each; deleted by its publisher, pruned after 6 hours |
| `data\cloud\dry_run\<stamp>-<job>-<run8>\NNNN-<label>.json` | `Run.write` | dry-run request bodies (full student data: delete after review) |
| `data\cloud\student_index.json` | `student_index.remember` | passport to uid / HNG id; 14.7 KB |
| `data\cloud\backfill_20260930.log` | the shell redirect of the real backfill | the 30 Sep backfill's progress (counts only) |
| `C:\Hangeul\BOT\hangeul_sync.log` | publisher, full picture and sheet-job children | the INFO/WARNING lines of `hangeul.cloud` (13 §18 on lines lost to concurrent appends) |
| `C:\Hangeul\BOT\hangeul_bot.log` | the bot process | handoff failures of the watcher, the brief and the commands |

Read only: `data\verification\results.json`, `data\verification\text\*.json`, `data\alerted_passport_issues.json`, `data\passport_issue.json`, `data\missing_reports\missing_information_*.xlsx`, `data\auto_sync.lock`, and the student folders under `DOCS_ROOT` (listed and stat-ed only).

---

## 15. History of the files (`c17d887..8317741`)

| Commit | Date (Dhaka) | What it did to `src\cloud\` |
|---|---|---|
| `36ae72e` | 29 Sep 11:28 | the package: `__init__`, `publish`, `records`, `embed`, `handoff`, `backfill` |
| `a0572ba` | 29 Sep 11:30 | two invisible characters written as `chr()` calls (`ALL_SCOPES`) |
| `cfd10f1` | 29 Sep 11:33 | `all_keys`: a complete key list for batches that carry only some records |
| `2b6798f` | 29 Sep 11:58 | `command_hooks.py` and the handler hooks |
| `5048a07` | 29 Sep 12:02 | `bot_jobs.py`, `full_picture.py`, the scheduler hooks |
| `41055de` | 29 Sep 12:03 | `sheet_hooks.py` and the four sheet jobs' hooks |
| `44c9378`, `112325b`, `969f917` | 29 Sep 12:05 | the three branch merges into `cloud/all` |
| `cb16394` | 29 Sep 12:15 | integration: one tile record (`tile_facts`), the watcher's profiles and alerts |
| `3caa393` | 29 Sep 14:25 | the review fixes: gone keys after the accepted delete, read ordering, the digest drop, the model guard, the complete rules, `watched_scans`, `student_index.py`, the reader fillers |
| `752cd53` | 29 Sep 15:26 | the dry run's findings: `is_filler` and `blank_on_portal`, one line a run, `-1`, the 1 MB cap (`_by_size`), `handoff.child_env` / `start` |
| `9ead47d` | 29 Sep 16:19 | `decode_cf_emails` in the scraper; `"emailprotected"` a filler; `quiet_libraries` |
| `e5e532e` | 30 Sep 21:04 | main (the Consultant Performance page) merged into `cloud/release`; `parse_consult_performance` decodes the whole soup |
| `e4d1cea` | 30 Sep 21:16 | kind `consultant_performance`, `collect_performance`, the `/performance_*` hook |
| `8317741` | 30 Sep 21:45 | the performance scope `"<period>\|<first day>"`; the backfill reads the page |

The performance commits in between (`bbd8f98`, `a721066`, `ce23535`, `314afdb`) touched `src\bot\` only; they are in [03a](03a_FILES_src_bot.md) and [08](08_HISTORY_STAGE_BY_STAGE.md).
