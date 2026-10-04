# 06 — The local LLM and Jennie's voice

What's in this file: how the bot talks to its local LLM through Ollama (the one option set, `num_ctx`,
`keep_alive`, the prompt-size guard, the brain loaded on demand), every prompt verbatim, the three places the
LLM is used today and the claim checker that keeps it honest, why the LLM-written executive report was
removed, and the complete design of "Jennie", the voice assistant (voice service, how to build it from zero
with a `service.py` function map, bot side, persona, measured latencies), which is **switched off**: how it
was switched off, its exact state on 30 Sep 2026, and how to switch it back on.

Sibling files: install, `.env`, GPU budget and day-2 operations are in
[02_ENVIRONMENT_SETUP_AND_OPERATIONS.md](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md); the commands the LLM and
Jennie route to are in [05_TELEGRAM_COMMANDS_AND_JOBS.md](05_TELEGRAM_COMMANDS_AND_JOBS.md); the line-level
file references for `src\bot\voice.py`, `brief.py`, `ask.py` and `src\llm\` are in [03a](03a_FILES_src_bot.md) and
[03b](03b_FILES_src_scraper_llm_api_config.md); the dated build story in [08](08_HISTORY_STAGE_BY_STAGE.md) and
what is still open in [11](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md); the voice-note flow inside the whole system in
[01_ARCHITECTURE.md](01_ARCHITECTURE.md) §2.6, the LLM rule (R7) with its incidents in
[09_BLUEPRINT_RULES_AND_LESSONS.md](09_BLUEPRINT_RULES_AND_LESSONS.md), the Supabase publish layer (which uses a
separate embedding model, not this LLM) in [13](13_SUPABASE_PUBLISHING.md), and the pack index in [00_INDEX.md](00_INDEX.md).

**Pack written:** 29 Sep 2026 at `c17d887`. **Refreshed:** 30 Sep 2026 (Asia/Dhaka) at `8317741`. Code facts
are from `C:\Hangeul\BOT` at that head and from `C:\Hangeul\JARVIS\jennie_voice\service.py`. Between the two
heads `src\llm\` and `src\bot\voice.py` did not change (so their line numbers below still hold); `brief.py`
moved by +3 lines in the part cited here (a `reads` field on `Brief` at `:79-81`, for the Supabase copy) and
`telegram_bot.py` by ~100 (the performance commands and the publish hooks); their line numbers below are the
new ones.

**The one rule behind everything in this file: the LLM never states a fact of its own.** Code reads the
portal and counts; the LLM may only (a) pick which already-computed facts answer a question, (b) route a
spoken request to a command, or (c) word a short sentence that a checker then verifies claim by claim against
the facts, dropping it when anything does not match. That rule came from a real failure (section 4).

---

## 1. The model and the Ollama client

### 1.1 The model

| Item | Value |
|---|---|
| Server | Ollama 0.34.4, `http://127.0.0.1:11434` (`OLLAMA_BASE_URL`; 127.0.0.1, because `localhost` tried IPv6 `::1` first and lost ~2 s per new connection) |
| Model | **`qwen3:4b-instruct`** (`OLLAMA_MODEL`), Ollama ID `0edcdef34593`, 2.5 GB on disk, Apache-2.0, the *non-thinking* Qwen3-4B-Instruct-2507 edition |
| Resident size | 2.62 GiB at `num_ctx` 3072 with `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` (2.82 GiB without them) |
| Speed (brain trial, 27 Sep 2026) | load 2.77 s; routing call 0.30-0.43 s warm; generation 119.8 tokens/s; prompt 18,053 tokens/s |
| Also pulled, unused | `qwen2.5:7b` (4.7 GB): the original brain until 28 Sep 2026 |

**How it was chosen** (`C:\Hangeul\JARVIS\brain-trial\trial.py`, results `results_*.json`): 12 English/Korean
utterances including follow-ups ("그럼 어제는?"), scored on the routing command, the resolved date and valid
JSON, plus a cute reply, with a VRAM budget of ≤ 3.5 GB so the voice could run beside it.

| Model | VRAM (ctx 4096) | Command | Date | JSON | Route / reply | Verdict |
|---|---|---|---|---|---|---|
| `qwen2.5:7b` | 4.42 GiB | 12/12 | 12/12 | 12/12 | 0.46 / 0.38 s | too big beside the voice (leaves ~2.2 GB) |
| `qwen3:4b` (Ollama tag = Thinking-2507) | 2.96 GiB | 12/12 | 12/12 | 12/12 | 0.44 / **1.97 s** | leaks its reasoning even with `think: false` |
| `qwen3:1.7b` | 1.59 GiB | 10/12 | **5/12** | 12/12 | 0.31 / 0.27 s | rejected: dates |
| **`qwen3:4b-instruct`** | 2.96 GiB | **12/12** | **12/12** | **12/12** | **0.34 / 0.29 s** | **chosen** (route + reply 0.63 s) |
| `qwen2.5:3b`, `gemma3:4b` | — | — | — | — | — | not installed (licence check: Qwen Research License / Gemma Terms) |

It adds emojis to replies ("짜잔! 오늘 서류 검증된 학생은 두 명이에요용~ 💖"); the bot strips them. The same
small model was then used **everywhere** (typed questions, brief summary, e-mail drafts, voice), by the owner's
choice (decision J14), so one copy fits in VRAM.

### 1.2 `src\llm\ollama_client.py` (274 lines)

Singleton `ollama_client = OllamaClient()`; `httpx.AsyncClient(timeout=60.0)`. Constants:

| Name | Value | Why |
|---|---|---|
| `TEMPERATURE` | `0.3` | one value for every call |
| `KEEP_ALIVE` | `-1` | "never unload" while the brain is pinned |
| `ANSWER_BUDGET_TOKENS` | `512` | room a prompt must leave for the answer |
| `CHARS_PER_TOKEN` | `2.4` | measured with qwen3's tokenizer: **2.43** characters/token for the typed-question prompt (portal data as Python dicts: every digit is a token), **2.81** for the daily brief, **~4** for plain English; 2.4 is the safe side |
| `AGENT_MAX_TOKENS` | `60` | the fact-picking answer is a short JSON list |
| `AGENT_TIMEOUT` | `30.0` s | a warm call takes well under 1 s |
| `AGENT_MAX_FACTS` | `5` | at most 5 facts shown |

**The one option set.** Every request is built by `_payload(num_predict=None, **fields)`:

```python
{"model": settings.OLLAMA_MODEL, "stream": False, "keep_alive": keep_alive(),
 "options": {"temperature": 0.3, "num_ctx": settings.OLLAMA_NUM_CTX, ["num_predict": n]}, **fields}
```

Ollama reloads the model whenever a *load* option (such as `num_ctx`) differs from the copy in VRAM, which
costs seconds; so every call sends the same `num_ctx`. Only `num_predict` varies per call; it is a sampling
limit and does not reload (measured: load 0.002 s).

**`num_ctx` = 3072** (`OLLAMA_NUM_CTX`, default in `src\config.py`). Measured with `/api/ps` on 28 Sep 2026:
2048 → 2.68 GiB, 3072 → 2.82 GiB (before flash attention). 3072 fits the brief's summary prompt
(~1,300-1,600 tokens plus its answer; 2048 would cut it) and left ~3.2-3.4 GiB beside the desktop and the idle
voice service; 4096 did not leave enough for a Korean speech render (peaks ~3.6 GiB).

**`keep_alive`**:

```python
def brain_pinned() -> bool:
    return bool(settings.JENNIE_VOICE_ENABLED or settings.BRAIN_ALWAYS_LOADED)

def keep_alive():
    return KEEP_ALIVE if brain_pinned() else (settings.BRAIN_IDLE_UNLOAD or "5m")
```

Pinned (voice on): `-1`, the brain stays in VRAM so no spoken question waits ~3 s for a load; `post_init` runs
`scheduler.warm_brain()` and `brain_keep_warm` re-checks every 10 minutes (a model that loaded partly on the CPU
while the GPU was busy is unloaded and loaded again: Ollama never moves a loaded model and never unloads a
`-1` one). Not pinned (voice off, today): `"5m"`, and `post_init` calls `unload()` to release a copy an earlier
run pinned. History: the first voice version sent `keep_alive: 0` to free VRAM before each speech render, and the
7B then reloaded (7-9 s) on every call — the main reason voice replies took 20-70 s.

**The brain on demand, as this PC runs it (checked 30 Sep 2026).** `JENNIE_VOICE_ENABLED=false` and
`BRAIN_ALWAYS_LOADED` unset, so `brain_pinned()` (`src\llm\ollama_client.py:37`) is False:

| Moment | What happens | Where |
|---|---|---|
| Bot start | `post_init` starts `ollama_client.unload()` in the background (`{"model": "qwen3:4b-instruct", "keep_alive": 0}` → `POST /api/generate`), never `warm_brain()`; no `Brain … resident on the GPU` line is logged | `src\bot\telegram_bot.py:2360-2365` |
| Every 10 min | `brain_keep_warm` still runs (the job is always registered) but `keep_brain_warm()` returns at once | `src\bot\scheduler.py:317-325` |
| A typed question no route answers, the brief's summary, a `/sendmail` draft | the call sends `keep_alive: "5m"`; the first call after a quiet spell waits ~3 s for the load (2.62 GiB onto the GPU), later ones are warm | `ollama_client.keep_alive()`, `:42-44` |
| 5 min after the last call | Ollama unloads it; `ollama ps` is empty again | Ollama |

Measured: the GPU idles at ~1.0-1.2 GB (950 MiB at 23:4x on 30 Sep) and peaks at ~3.8-3.9 GB while the brain
is loaded or a sync's EasyOCR runs ([02 §8.1](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)). If Ollama is not up yet
when the bot starts (after a reboot `Ollama.lnk` and the bot start together), the start-up health check logs
`Ollama not reachable at http://127.0.0.1:11434:` and the bot carries on; the next call loads the brain as
usual (30 Sep 20:36: Ollama answered the `unload()` 6 s later; [02 §9.6](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)).
None of this touches the Supabase layer: its embedding model (gte-small) is a different model, run on the CPU
in separate processes, never through Ollama.

**`prompt_fits(what, *texts) -> bool`**: Ollama silently truncates a prompt longer than `num_ctx` — it keeps
only about its last half (measured at 3072: every over-long prompt came back as 1,538 tokens), so the system
prompt holding the portal data is lost and the answer is wrong, and `prompt_eval_count` cannot reveal it (a cut
prompt reports ~num_ctx/2, and a cached prefix is not counted). So the prompt is measured *before* sending:
`estimate = int(sum(len(t) for t in texts) / 2.4)`; if `estimate > num_ctx - 512` it logs
`Ollama <what>: the prompt is ~N tokens (C characters) of num_ctx 3072, leaving under 512 for the answer - Ollama
may cut it ...` and returns `False`. `generate_response` and `chat` only warn; `answer_agent_query` refuses to call
(returns `None`). After a call, `_check_used(what, data)` warns when `prompt_eval_count >= num_ctx - 512`.

**Methods**

| Method | Endpoint | Returns / never raises |
|---|---|---|
| `check_health()` | `GET /api/tags` (5 s) | `{"reachable", "models_installed", "target_model", "target_model_ready"}` |
| `generate_response(prompt, system=None)` | `POST /api/generate` | text; on any failure `_fallback_response()` ("🤖 *Hangeul Operational Intelligence* … Local Ollama service is not currently responding …") — callers must detect that text (the e-mail path does) |
| `chat(messages, format=None, num_predict=None, timeout=None)` | `POST /api/chat` | reply text, or `None` when Ollama is down or errs; `format` is `"json"` or a JSON schema (structured output) |
| `residency()` | `GET /api/ps` | `{"loaded", "on_gpu" (size_vram >= size), "size_gb", "vram_gb" (÷2^30), "num_ctx"}` |
| `warm_up()` | `POST /api/generate` with `prompt: ""` (120 s) | loads the model with the one option set; `residency()` + `"seconds"` |
| `unload()` | `POST /api/generate` `{"model": ..., "keep_alive": 0}` | frees VRAM now |
| `answer_agent_query(query, facts)` | `/api/chat` with `AGENT_SCHEMA` | the picked facts in order, `[]` when none answers, `None` when down / nonsense / prompt too big |
| `_answer_query_fallback(query, facts)` | none | facts whose whole label (words before the last `:`, parentheses and `" — …"` removed, plural `s` dropped, stop words `a an the of to for in on and or by at with is are` removed) is contained in the question's words |

---

## 2. Every prompt, verbatim

### 2.1 Picking facts for a typed question (`src\llm\prompts.py`)

```python
SYSTEM_AGENT_CHAT = """You help the office of Hangeul Korean Language & Visa (a study-in-Korea agency in Dhaka) find figures on its admin portal.
You get numbered facts, each one figure read live from the portal dashboard, and a question.
Pick the facts that answer the question directly, at most 4. Never answer the question yourself, never calculate, add or compare figures, and never pick a fact that is only loosely related.
If no fact answers the question, pick none.
Answer with JSON only: {"facts": [the numbers of the facts you picked], "answered": true if they answer the question, else false}."""

AGENT_SCHEMA = {"type": "object",
                "properties": {"facts": {"type": "array", "items": {"type": "integer"}},
                               "answered": {"type": "boolean"}},
                "required": ["facts", "answered"]}
```

User message: `"Facts:\n1. <fact>\n2. <fact>…\n\nQuestion: <query>\n\nJSON:"`, `num_predict=60`, `timeout=30`.
Parsing: `json.loads`, else the first `{...}` in the text; must be a dict with a list `facts`; `answered: false`
→ `[]`; indices kept only if they are real ints (not bools) in `1..len(facts)`, de-duplicated, sorted, max 5.

### 2.2 The brief's one summary (`src\bot\brief.py`, `_SUMMARY_SYSTEM`)

```
You write a one- or two-sentence plain-English summary of an office's figures for its owner. Use ONLY the facts
given, with their numbers exactly as written, and put each number next to the words of its own fact, one figure
per clause (for example '<number> consultation requests were received today'). Never add a number, total,
percentage, rate, date or time; never add figures together, compare them or guess a trend; never use a name,
status or word for a count that the facts do not use. Pending payments and window applications under review are
separate: never combine them. Do not mention visas, passports, intakes or conversion. No Markdown, no emojis, at
most 280 characters. Output only the summary.
```

User message: `"Facts:\n- <fact>\n- <fact>…\n\nSummary:"`; `SUMMARY_MAX_TOKENS = 120`, `SUMMARY_TIMEOUT = 30.0`.
The facts are the brief's own one-figure-a-line list, e.g. `Consultation requests received today: 3`,
`Consultations done today: 1`, `Marked Consulted today: 1`, `Requests still new today: 2`,
`Students whose payment was verified today: 2`, `Total amount verified today: 28,000.00 BDT`,
`Pending payments: 0`, `Window applications under review (a separate figure): 2`,
`Calendar reminders for today: 4` (figures illustrative). The complete set of templates, section by section and
with every condition (the `(only the rows with an amount)` total, the per-type calendar facts, what is never a
fact: the other dashboard tiles and all local data), is in [03a §4.3](03a_FILES_src_bot.md).

### 2.3 `/sendmail` e-mail drafting (`src\bot\telegram_bot.py:1312-1351`, `_ai_write_email`)

```
system: You are an assistant that writes professional, polite business emails on behalf of <manager name>,
Manager at Hangeul Korean Language and Visa (HKLV) in Dhaka. Write in clear, courteous, professional English.
Output ONLY the email body: a greeting, the message in short paragraphs, and a sign-off exactly as:
<manager name>
Manager, HKLV
Do NOT include the subject line, do NOT invent facts, and do NOT add any commentary.

prompt: Recipient: <student name> (a student at HKLV).
Email subject: <subject>
What the manager wants to convey (short brief): <brief>

Write the full, professional email body now.
```

Via `generate_response`. The draft is rejected (template used instead) if it is shorter than 15 characters or
contains any of `operational intelligence`, `ollama service is not currently responding`,
`request processed successfully`, `please verify ollama is started` (the client's "AI is down" text). Template:
`Dear <name>,` / the brief / `Please let us know if you have any questions.` / `Thanks,` / `<manager name>` /
`Manager, HKLV`. Nothing is sent until the manager answers SEND (EDIT / DENY also offered).

**Hard-coded identity.** The manager's real name and the title `Manager, HKLV` are literal strings in the code: the system prompt at `telegram_bot.py:1317-1320` (name twice: "on behalf of …" at `:1318` and the sign-off at `:1320`) and the fallback template at `:1350`. The pack writes them as `<manager name>`. A new bot should make them settings (for example `EMAIL_SIGNOFF_NAME`, `EMAIL_SIGNOFF_TITLE` and `AGENCY_NAME` in `.env`) and build both strings from them; see [12 Adaptation map](12_ADAPTATION_MAP.md).

### 2.4 Jennie's prompts (`src\bot\voice.py`)

Router (one call per voice note; `<TODAY>` = e.g. `Monday 2026-09-28`, `<DAYS>` = the seven days before it as
`Sunday 2026-09-27, Saturday 2026-09-26, …`):

```
You are the command router for Jennie, the voice assistant of the Telegram bot of Hangeul Korean Language & Visa,
a study-in-Korea agency in Dhaka. Office staff talk to Jennie in Korean or English. The text comes from speech
recognition, which sometimes mishears a word, so go by the overall meaning. Choose exactly ONE command for the
NEW utterance.

Commands:
- verified_today: students whose payment/documents were verified today (검증된 학생)
- verified_date: verified students on one specific date other than today
- inquiries_today: consultancy inquiries / consultations handled today (상담, 문의)
- inquiries_date: consultancy inquiries on one specific date other than today
- calendar: upcoming schedule, deadlines, DHL shipments and application windows (일정, 마감)
- passports: passport audit, students whose passport data is wrong or missing (여권)
- stats: overall statistics and totals: pending payments, applications under review, students per program or
  intake, documents to review (전체 통계, 결제 대기)
- missing_report: students with missing documents or missing data
- crosscheck: cross-check payments against records for a date or a student
- chat: greetings, thanks, praise, small talk, or anything that is not a data request

Today is <TODAY>. The seven days before it were: <DAYS>. Resolve relative dates such as 어제 / yesterday against
today. A short follow-up such as 'and yesterday?' keeps the topic of the previous request and changes only the date.
Answer with JSON only: {"command": one of the commands, "date": "YYYY-MM-DD" or null, "english_query": the request
as one short English sentence, "language": "ko" if the new utterance is Korean, otherwise "en"}. The date is null
unless the command is verified_date, inquiries_date, crosscheck or passports with a spoken date.
```

`_ROUTER_SCHEMA`: object with `command` (enum of the 10 commands), `date` (`string` or `null`),
`english_query` (string), `language` (enum `ko`, `en`), all required. User message:
`"Conversation so far:\n<last 3 turns>\n\nNEW utterance: <heard>"`, where each turn is `User: <words>` and
`Jennie (<command> <date>): <what she said>`. `num_predict=160`, `timeout=30`.

Reply, English (`_REPLY_SYSTEM_EN`, `<LIMIT>` = 90):

```
You are Jennie, the cute and cheerful voice of the office bot of Hangeul Korean Language & Visa in Dhaka. Say, in
a short English voice note, the answer to what the user just asked, using the facts the bot just read from the
portal. If there is no written answer, just reply naturally.
Speak in a cute, bubbly, playful style, the English version of Korean 애교: cheerful openers like 'Ta-da!' or
'Yay!', sweet little touches like 'hehe' or 'okie', and a happy, caring tone. Stay polite, and keep every fact exact.
Rules:
- English only, ONE short sentence, at most <LIMIT> characters.
- Use only the facts given; never invent numbers, names or dates. Say the one or two figures that answer the
  question, each with the words of its own fact; never read out lists or names.
- Write numbers as digits (they are read out correctly).
- If there are no facts and the written answer asks the user for something (a date, or to choose a program), ask
  for it briefly; if it says the portal could not be read, say so; say no number then.
- Say the day exactly as it is given under 'The day' (or no day at all), never another day; when there is no day,
  never say one.
- When the figure is 0, say in words that there were none.
- No Markdown, asterisks, emojis, bullet points or URLs.
Output only the words Jennie says.
```

Reply, Korean (`_REPLY_SYSTEM_KO`, `<LIMIT>` = 22) — same structure, with: "Korean (Hangul) only, in a cute 애교
style: friendly endings like ~요, ~용, ~어용, ~구요, and you may start with '짜잔!'. Warm and polite, never rude.",
"When the figure is 0, say 없어요 instead of a number.", "No … URLs or English sentences.", and the example
`어느 날짜를 볼까용?`. In practice the Korean prompt is used only for small talk and for answers without facts;
a Korean sentence *about facts* is built in code (section 5.3).

Spoken brief (`_BRIEF_SYSTEM_EN`, `<LIMIT>` = 140): "Turn today's facts from the written operational brief into
Jennie's short spoken evening update. Say each number with the words of its own fact." + the cute-English block +
"English only, one or two short sentences, at most <LIMIT> characters in total: a cute greeting and the one or two
most important numbers." + the fact rules + no Markdown/emojis.

Reply prompt bodies: `"Recent conversation:\n<turns>\n\nThe user just said (spoken): <heard>\n\nThe day: <today |
yesterday | on 12 September | (none: these are live figures, say no day)>\n\nFacts the bot just read from the
portal (one figure a line):\n- <fact>…\n\nJennie says:"`; small talk uses `The bot's written answer:\n(none, this
is small talk)`. `num_predict=120`.

Fixed lines used instead of the brain: `_FALLBACK[("ko", True)] = "짜잔! 답변은 채팅에 글로 보내드렸어요. 확인해 주세용!"`,
`("ko", False) = "네~ 제니 여기 있어용!"`, `("en", True) = "Ta-da! Your answer is in the chat, hehe."`,
`("en", False) = "Hehe, Jennie is here!"`, `_BRIEF_FALLBACK = "Good evening! Today's brief is in the chat, hehe."`,
portal down: `"Sorry, I couldn't read the portal just now, so I can't say. Please try again in a minute."` /
`"지금은 포털을 못 읽었어요. 잠시 후 다시 물어봐 주세용!"`.

---

## 3. Where the LLM is used today

| Use | Code | LLM's job | If the brain is down |
|---|---|---|---|
| **The 18:05 brief's optional summary** (also `/brief`, `/report`) | `brief.llm_summary(facts, is_today)` → `check_summary` → `claims_problem` | write 1-2 sentences from the brief's fact list; shown as `🤖 _Summary by the local AI, its numbers checked against the facts:_ …` only if every claim checks out | the summary line is left out; the brief is complete without it |
| **Free-text questions no route fits** | `ask.answer_unknown(query)` → `_answer_query_fallback` first, then `answer_agent_query` | pick fact numbers from the live dashboard facts (`label: value` lines); the bot shows the picked facts **word for word** with `_Read live just now; the local AI picked which figures answer it; each figure is the portal's own._` | label matching only; else `cant_answer()`: "I can't answer that from the portal yet" + the commands that can |
| **`/sendmail` drafting** | `telegram_bot._ai_write_email` | write the e-mail body from the manager's short brief | courteous template |
| Jennie (voice; **off since 28 Sep 2026 17:08**, still off on 30 Sep) | `voice.route`, `voice.spoken_reply`, `voice.spoken_brief` | route to a command (JSON); word one short sentence (checked) | text answers still arrive; fixed fallback lines |

Everything else — every command, every figure in the brief, cross-checks, OCR verdicts, sync summaries, and
the performance commands (`/performance_today`, `/performance_month`, which show only the portal's own
Consultant Performance page, word for word: [05](05_TELEGRAM_COMMANDS_AND_JOBS.md)) — is code. What the bot
publishes to Supabase is code too: its text form is built by `src\cloud\records.py` and embedded by gte-small
on the CPU; no LLM writes or reads any of it ([13](13_SUPABASE_PUBLISHING.md)).
Most typed questions never reach the LLM: `ask.classify(text)` routes them on whole words and real dates to live
reads (verified, consultations, pending payments, window applications, dashboard cards, intakes, applied dates,
calendar, and since `314afdb` performance, including the owner's spelling "performence": `ask.performance_route`,
`src\bot\ask.py:395`); see [05](05_TELEGRAM_COMMANDS_AND_JOBS.md). No raw inquiry records, contacts or remarks go into any prompt.

### 3.1 The claim checker: `brief.claims_problem(text, facts, extra_words=()) -> Optional[str]`

Returns why a text may not be shown, or `None` when every claim is one of the facts. It is applied to the brief
summary, to Jennie's English answer sentences (with her extra words) and to her spoken brief. Steps, in order:

1. Empty → `"empty"`.
2. Any non-ASCII character except `‘’“”–—…` and NBSP (`_FOREIGN_RE = [^\x00-\x7F‘’“”–—…\u00a0]`) →
   `"not plain English"` (Bangla or Korean number words would slip past the number check).
3. Off-topic: `\b(?:visas?|passports?|conversion|intakes?|rates?|percent(?:age)?|per\s+cent|prepared\s+by|ytd)\b|%`
   → `"it talks about what the brief does not report"`.
4. Vague or comparing count words: `dozen(s), half, twice, thrice, double(d/s), triple, quarter, both, couple,
   pair(s), single, several, few, fewer, many, multiple, handful, numerous, various, lot(s), plenty, most,
   majority, minority, all, every, each, some, any, another, more, less, least, average, ratio, than, compared,
   increase(d), decrease(d), higher, lower, trend, growth, record`, the ordinals `first … thousandth`, and
   `\d+(st|nd|rd|th)` → `"a vague or comparing count word"`.
5. After turning the phrases `no answer(s)` → `noanswer` and `not available` → `notavailable`: a negation
   (`not, never, without, cannot, neither, nor, n't`) → `"a negation"` (the check cannot follow "3 were not done").
6. Numbers: every number in the text, in digits or words (`voice._numbers_in`: `28,000.50` → 28000 and 50;
   `twenty-eight thousand` → 28000; Korean `세 명` → 3, `이십 건` → 20; plus a lone `one`) must occur in the facts →
   else `"numbers not in the facts [...]"`. Decimals other than `.00` must too.
7. Vocabulary: every word (lower case, plurals folded: `ies→y`, trailing `s` dropped unless `ss/us/is`; synonyms
   `inquiry/enquiry/lead→request`, `came/arrived→received`, `taka/tk→bdt`, `counselor/consultant→counsellor`,
   `verification/verify→verified`) must be a word of some fact, a plain connecting word (`_STOP_TEXT`: articles,
   prepositions, `is/are/was/were…`, `today tonight day evening morning afternoon still also yet just now currently`,
   `remain(s/ed/ing) waiting awaiting listed recorded logged shown reported overall altogether together due summary`,
   `no none nothing nobody nil zero`, …), or one of `extra_words` → else `"words the facts do not use [...]"`.
   So an invented name, status ("cleared", "approved") or subject never gets through.
8. Clause by clause (split at `,` `.` not inside numbers, `; ! ? ( ) [ ] \n`, and the words
   `and but while whereas plus with also then`): the clause's numbers (a `no/none/nothing/nobody/nil` adds 0) must
   be the figure of **the fact that clause is about** — the fact sharing its most telling keywords, each keyword
   weighted `1/df` (a word few facts use counts more, exact `Fraction` arithmetic), ties broken by the fewest fact
   keywords the clause does not use. A number belonging to no fact → `"a number that belongs to no fact (...)"`;
   the wrong figure (e.g. "5 done" when 5 were *received*) → `"[5] is not the figure of what it describes (...)"`.

`check_summary(summary, facts, is_today=True)`: plain text via `voice._plain`, whitespace collapsed, quotes and a
leading `Summary:` / `In short:` removed, cut to the first two sentences; dropped if empty or longer than
`SUMMARY_MAX_CHARS = 350`; for a brief about a past day, dropped if it says `today / tonight / yesterday /
tomorrow / this morning|afternoon|evening`; then `claims_problem`. Every drop is logged as
`Brief summary dropped: <reason>.` and the brief goes out without it. `llm_summary` does not call the LLM at all
when no fact contains a digit (the portal could not be read).

**The word lists, verbatim** (`src\bot\brief.py:364-411`; copy them exactly, the check is only as good as these lists):

```python
# What the brief never reports, so a summary that brings it up is making it up.
_OFF_TOPIC_RE = re.compile(r"\b(?:visas?|passports?|conversion|intakes?|rates?|percent(?:age)?|per\s+cent|"
                           r"prepared\s+by|ytd)\b|%", re.I)
# Words for a count or a comparison that the number check cannot compare with a fact.
_ORDINALS = ("first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
             "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth thirtieth fortieth "
             "fiftieth hundredth thousandth").split()
_VAGUE_NUMBER_RE = re.compile(
    r"\b(?:dozens?|half|halves|twice|thrice|double[ds]?|triple[ds]?|quadrupled?|quarter|both|couple|pairs?|"
    r"single|several|few|fewer|many|multiple|handful|numerous|various|lots?|plenty|most|majority|minority|"
    r"all|every|each|some|any|another|more|less|least|average|ratio|than|compared|increased?|decreased?|"
    r"higher|lower|trend|growth|record|" + "|".join(_ORDINALS) + r")\b|\b\d+(?:st|nd|rd|th)\b", re.I)
# A negation turns a figure around ("3 were not done"); the check cannot follow that.
_NEGATION_RE = re.compile(r"\b(?:not|never|without|cannot|neither|nor)\b|n[’']t\b", re.I)
# "No", "none", "nobody"... claim a 0: it must be the 0 of the fact the clause talks about.
_NOTHING_RE = re.compile(r"\b(?:no|none|nothing|nobody|nil)\b", re.I)
# Phrases that are one fact word, not a "no" or a "not" ("No answer: 2", "not available").
_PHRASES = ((re.compile(r"\bno[\s-]+answers?\b", re.I), " noanswer "),
            (re.compile(r"\bnot\s+available\b", re.I), " notavailable "))
# Only plain English: another script's number words ("পাঁচ") would get past the number check.
_FOREIGN_RE = re.compile(r"[^\x00-\x7F‘’“”–—… ]")
# A clause ends at punctuation (not inside "28,000.00") or a joining word.
_CLAUSE_RE = re.compile(r"(?<!\d)[,.]|[,.](?!\d)|[;!?()\[\]\n]|\b(?:and|but|while|whereas|plus|with|also|then)\b", re.I)
# Plain connecting words any sentence may use besides the facts' own words. They never tell which
# fact a clause is about, and none of them is a count, a status or a comparison.
_STOP_TEXT = ("""
a an the and or but of in on at by for to from with as so far this that these those there here it its
they their them we our us is are was were be been being has have had do does did get got come comes
coming into out today tonight day evening morning afternoon still also yet just now currently
which who whose while whereas plus worth totalling totaling amounting stand stands standing sit sits
remain remains remained remaining waiting awaiting listed recorded logged shown reported overall
altogether together due summary no none nothing nobody nil zero s ve re ll d m
""")
# Other words for a fact's own word.
_SYNONYMS = {"inquiry": "request", "enquiry": "request", "lead": "request", "came": "received",
             "arrived": "received", "taka": "bdt", "tk": "bdt", "counselor": "counsellor",
             "consultant": "counsellor", "verification": "verified", "verify": "verified"}
```

`_STOP_WORDS = {_stem(w) for w in _STOP_TEXT.split()}` (`:436`), where `_stem` (`:428`) folds `…ies`→`…y` (words longer than 4), drops a trailing `s` (words longer than 3, not ending `ss`/`us`/`is`), then maps through `_SYNONYMS`. Note that `voice.py` has a **different** `_NOTHING_RE` of its own (for the bot's written answers); the one above is the brief's.

**Must port the number reader.** `claims_problem` depends on `voice._numbers_in` (`voice.py:900-929`) and on `voice._WORD_VALUES` / `voice._WORD_SCALES` (`voice.py:1380-1381`). It reads digits (the comma thousands group removed; the decimal part added as its own number only when it is not zero), English number words (`zero`…`nineteen`, `twenty`…`ninety`, summed; `hundred` multiplies; `thousand`, `million`, `billion` close a group; `and` skipped inside a number; a lone `one` ignored, which `brief._numbers` then adds back), and Korean numbers only when Hangul is present. A rebuild without voice must still carry this code; put it in a neutral module. Details: [03a §4.5](03a_FILES_src_bot.md).

---

## 4. Why the LLM executive report was removed

Until 28 Sep 2026 the 18:05 brief was written by the LLM: `ollama_client.generate_executive_report(dashboard,
applications, inquiries)` sent `build_report_prompt(...)` (the dashboard dict, 6 applications, 5 inquiries, as
Python reprs) with the system prompt `SYSTEM_EXECUTIVE_REPORT`, which prescribed a four-section template:

```
📋 HANGEUL DAILY OPERATIONAL BRIEF — 6:05 PM (Asia/Dhaka)
1️⃣ TODAY'S CONSULTATION REQUESTS & STAFF METRICS   (Total Inquiries Received Today, Breakdown by Counselor, Special Cases)
2️⃣ PERFORMANCE SNAPSHOT                             (Active Intake Pipeline, Visas Approved YTD, Weekly Lead-to-Application Conversion Rate)
3️⃣ PAYMENT-VERIFIED STUDENTS & PASSPORT CROSS-CHECK  (… Form Data: Name | Passport: [Number] | DOB | Scanned Image: [Matched ✅ / Discrepancy ⚠️])
4️⃣ REMAINING PENDING PAYMENTS                       (Total Pending Invoices … outstanding)
```

The template asked for figures **no reader provides** (visa counts, conversion rates, passport numbers and dates of
birth, a scan-match verdict), so the model filled the slots. The brief sent on request at ~11:50 on 28 Sep 2026
contained fake passport numbers (`1234567890…`), fake dates of birth, "Scanned Image: Matched", a visas-YTD figure,
a conversion percentage and filler; its prompt was ~2,728 of the 3,072-token context, close to silent truncation.
Two portal readers were also broken underneath it (the dashboard summary fell back to placeholder numbers such as
262 applicants and 31 registrations; the calendar parser returned 11 empty reminders after a layout change), so
even the "real" numbers were wrong. The owner chose a **factual brief**:

* commit `f8fefa4` (28 Sep 13:51): `src\bot\brief.py` builds the brief in code from live read-only GETs (five
  sections: consultations of the day via `consult_requests.php?status=all&from=DAY&to=DAY` + the all-time status-tab
  counts; payment-verified students from every `students.php` page; pending payments and window applications as two
  separate figures + dashboard tiles; today's calendar reminders; the last local document check, marked "not live").
  A figure that cannot be read is "not available", never 0. `generate_executive_report`,
  `SYSTEM_EXECUTIVE_REPORT`, `build_report_prompt` and the placeholder fallback report were deleted; the LLM keeps
  only the checked one-line summary.
* commit `7f42ad0` (28 Sep 15:31): the free-text agent, which used to answer from a context dict with "accurate
  numbers, names, and actionable advice", now only picks fact numbers (section 2.1).

Lesson for any new bot: **never give an LLM a report template with slots that the data does not fill**; compute
the facts in code, and let the LLM only choose or word them under a checker.

---

## 5. Jennie — the voice assistant (built, currently OFF)

### 5.0 State now: OFF (checked read-only on 30 Sep 2026)

| Piece | State | How it was switched off (28 Sep 2026 17:08, at the owner's request: "its maxing my gpu") |
|---|---|---|
| `.env` flags | `JENNIE_VOICE_ENABLED=false`, `JENNIE_SPOKEN_BRIEF=false` (lines 36-37) | both set from `true` to `false` |
| Voice-note handler | not registered (`telegram_bot.py:2430`: only `if settings.JENNIE_VOICE_ENABLED`), so a voice note gets no answer at all; no filler clips are rendered; the 18:05 brief is text only | follows from the flag at the next bot start |
| Brain | on demand (`keep_alive "5m"`, unloaded at start; §1.2) | follows from the flag (`brain_pinned()` False) |
| Watchdog task `JennieVoiceWatchdog` | **Disabled** (`Get-ScheduledTask` → State Disabled) | `Disable-ScheduledTask -TaskName JennieVoiceWatchdog`, **before** stopping the service (otherwise it restarts it within 5 min) |
| Autostart | `JennieVoice.lnk` is **not** in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\` (which holds `HangeulBot.lnk`, `Ollama.lnk`, `Send to OneNote.lnk`); it is parked in `C:\Hangeul\JARVIS\disabled\JennieVoice.lnk` | moved there with `Move-Item` |
| Service `service.py` on 127.0.0.1:8765 | not running (`/health` does not answer) | `cmd /c "C:\Hangeul\JARVIS\jennie_voice\stop_jennie_voice.bat" nopause`; last ran until ~17:06 on 28 Sep |
| Code | `src\bot\voice.py` unchanged since `c17d887`; nothing of the voice publishes to Supabase | — |

Effect: GPU use fell from 8-9.8 GB peaks to 3.8 GB, then to ~1.0 GB idle once the brain went on demand
(`c17d887`). Everything the voice needs is still on disk (the service, its venv, the CosyVoice and Whisper
weights under `voice-trials\`): switching it back on is §5.7, and takes ~1 minute plus the bot restart. Note
for a re-enable: the voice router's 10 commands (`ROUTE_COMMANDS`, `voice.py:380-381`) were not extended for
the performance commands; a spoken question the router sends to `stats` does reach the typed routes through
`ask.classify` (`voice.py:760-763`), performance included, but that path was never tested by voice.

### 5.1 What it is and the decisions behind it

Jennie answers **Telegram voice notes**: the office speaks a question on the phone, the bot replies with the
transcript, the normal text answer and a short voice note in a cute voice. Named after the bot (@the_Jennie_bot);
a future wake word would be "Hey Jennie". Everything runs on this PC; nothing leaves it.

| # | Decision (27-28 Sep 2026) |
|---|---|
| J1 | Phone first (Telegram voice notes in, text + voice out); a hands-free "Hey Jennie" at the PC later, on the same brain — **not built** |
| J2 | **English + Korean** (Bangla offered, not chosen) |
| — | A celebrity voice was asked for and **declined: no cloning of a real person's voice** without consent (that includes the film "Jarvis" actor and BLACKPINK's Jennie). Only synthetic stock-voice output may be used as a reference, never a real person's recording |
| J3 | The voice is chosen **by ear** from rendered samples (`C:\Hangeul\JARVIS\voice-samples`) |
| J4 | v1 abilities: answer questions, run reports by voice, a spoken 18:05 brief. E-mail by voice was left for later; today a voice note can never drive `/sendmail` (the code refuses it) |
| J5 | Reply = voice note + text, in the language spoken (auto-detected), showing what was heard |
| J6 | Named Jennie; female voices |
| J7 | Stock voices (Kokoro, MeloTTS, Piper) were "too AI": a more realistic **offline** model with **애교** (aegyo, cute) style; online TTS (Naver, Azure, ElevenLabs) declined for privacy (answers contain student names) |
| J8 | **CosyVoice2-0.5B zero-shot with the "krfemale" timbre** (sample `real__cosyvoice__v2-zeroshot-krfemale__kr-aegyo.wav`, Whisper CER 0.034); English from the same timbre via cross-lingual, one persona |
| J9 | 애교 **in English too** ("Ta-da!", "hehe", "okie") |
| J10 | "Too slow" → **option 1: faster, chattier Telegram voice notes** (~10-15 s target, short natural replies, memory of the last few exchanges, offline). A live "Hey Jennie" at the PC, a phone live-web page and cloud realtime were offered; option 1 alone was picked. Plan: one resident small brain chosen by trial instead of three calls to `qwen2.5:7b`, the 8 GB VRAM budget kept, per-chat history |
| J11 | The chat keeps **all three messages** ("heard", the full text answer, the voice note), just faster |
| J12 | "Instant" asked for; a voice note has a ~4-7 s floor, so **A: an instant pre-rendered filler clip (~1 s, cute, KO/EN) plus a fast one-sentence real reply** was chosen. B (live streaming talk) and C (cloud) declined |
| J13 | Brain trial (`C:\Hangeul\JARVIS\brain-trial`, 12 EN/KR routing utterances, VRAM ≤ 3.5 GB) → **`qwen3:4b-instruct`** (2.96 GB, 12/12 routing, route+reply 0.63 s). `qwen3:4b` (the thinking edition leaks reasoning) and `qwen3:1.7b` (dates 5/12) rejected and removed |
| J14 | **Build approved: the small brain `qwen3:4b-instruct` everywhere** (voice, typed questions, brief), not voice-only |
| J15 | **The passport-watcher non-blocking fix is included** in the same build (OCR off the event loop: `asyncio.to_thread` + an `RLock`), because the 30-minute watcher's CPU OCR blocked Telegram ~3.5 min per run ("bot not replying", 27 Sep 23:49). Deployed with the fast voice path on 28 Sep 01:51 (`7241465`, `d9bbecc`); see [08 §6.8-6.9](08_HISTORY_STAGE_BY_STAGE.md) |
| off | 28 Sep 2026 17:08: switched off at the owner's request ("its maxing my gpu"); still off on 30 Sep 2026 (§5.0); fully built and ready to re-enable (section 5.7) |

**Voice trials** (`C:\Hangeul\JARVIS\voice-trials\<engine>` venvs, samples in `voice-samples\`):

| Engine | Licence | Result |
|---|---|---|
| Kokoro (bf_emma, af_heart, af_bella, bf_isabella…) | Apache-2.0 | English only; "too AI" |
| MeloTTS (EN accents + KR) | MIT | the only good stock Korean (female, correct g2pkk rules; needed a transformers pin + eunjeon + torch 2.5.1 CPU); 4 aegyo levels by speed 1.0-1.15 / pitch +0-+5 st; "too AI" |
| Piper | ko_KR-kss CC BY-NC-SA (rejected, non-commercial); en_GB cori public domain | "too AI" |
| Chatterbox Multilingual | MIT | ko+en with an exaggeration control; GPU peak 4.3 GB, ~0.5× real time, a Perth watermark in every output |
| CosyVoice 300M-SFT, stock speaker 韩语女 | Apache-2.0 | unintelligible Korean (CER 0.53): used only as a *timbre* source |
| **CosyVoice2-0.5B** zero-shot / cross-lingual | Apache-2.0 | **chosen**; peak 2.9 GB, 0.6-0.9× RT; instruct mode ("happy", "sajiao") made words less clear (CER 0.051-0.085) |
| Fun-CosyVoice3-0.5B | Apache-2.0 | peak 3.5 GB; not better |

**How Jennie's reference voice was made — synthetic, no real person** (`voice-trials\cosyvoice\synth.py`, job
`v2b`): the stock 300M-SFT speaker 韩语女 rendered the line `REF_TEXT` → `ref\ref_sft_ko_female.wav` (right timbre,
bad words); CosyVoice2 cross-lingual then re-spoke `REF_TEXT` from that timbre with seeds 1234, 7 and 42, Whisper
small scored each by CER, and the best (seed 7) was copied to `ref\ref_v2xl_ko_female.wav`. `REF_TEXT` =
`안녕하세요! 저는 제니예요. 오늘도 만나서 정말 반가워요. 궁금한 게 있으면 언제든지 물어봐 주세요.`

### 5.2 The voice service — `C:\Hangeul\JARVIS\jennie_voice\service.py`

A separate FastAPI process in its own venv, **`127.0.0.1:8765` only**, one request at a time.

**API**

```
GET  /health -> 200 {"ok": true, "stt": "large-v3-turbo", "tts": "cosyvoice2", "device": "cuda", "tts_on_gpu": false, "busy_s": 0.0}
               503 {"ok": false, "error": "hung: one <stt|tts> request has held the lock for N s", ...} when busy_s > JENNIE_HUNG_S (600)
POST /stt    multipart/form-data, field "audio" (Telegram .ogg/Opus, .wav, .mp3, .m4a; ≤ 25 MB, ≤ 600 s)
             -> 200 {"text": "...", "language": "ko", "duration_s": 17.2, "seconds": 2.9}
POST /tts    application/json {"text": "...", "language": "en"|"ko", "style": "aegyo"|"neutral"}  (text ≤ 600 chars)
             -> 200 audio/ogg (Opus, mono, 48 kHz), headers X-Duration (s of audio) and X-Seconds (render time)
```

Errors are JSON `{"error": "..."}`: 400 bad input / undecodable audio / nothing speakable, 413 text > 600 chars or
audio > 25 MB / 600 s, 422 missing field, 500 unexpected, 503 lock wait > 120 s (`JENNIE_LOCK_WAIT_S`), a `/tts`
that cannot finish within `JENNIE_TTS_MAX_S` = 100 s from arrival (answered at once when a CPU render would not fit),
speech that came out cut short, or a client that hung up. `docs_url`, `redoc_url`, `openapi_url` are disabled.

**Local-clients-only guard** (`_LocalClientsOnly` ASGI middleware, before any body is read): 403 if the `Host`
header is not `127.0.0.1:8765` / `localhost:8765` (DNS rebinding); 403 for any request with an `Origin` header (a
web page in a browser on this PC — browsers send it on every POST; httpx and PowerShell do not); 411 for a POST
without `Content-Length`; 413 over 64 KB (`/tts`) or 26 MB (`/stt`); 415 for a `/tts` that is not
`application/json`. Listening on 127.0.0.1 alone is not enough: any open web page could otherwise POST to it.

**Models and residency**

| Part | Model | Where | GPU rule |
|---|---|---|---|
| STT (GPU) | faster-whisper **large-v3-turbo**, float16, beam 5, Silero VAD, language auto-detect | `jennie_voice\models\hf\hub\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo` (1.6 GB) | loaded per request only if ≥ `STT_GPU_MIN_FREE_GB = 3.0` free; unloaded right after (`JENNIE_STT_GPU_KEEP_S = 0`); ~2.2 GB while used |
| STT (CPU fallback) | faster-whisper **medium**, int8, 6 threads | `voice-trials\whisper\hf_home\hub\models--Systran--faster-whisper-medium` | always in RAM |
| TTS | **CosyVoice2-0.5B**: Korean = `inference_zero_shot(text, REF_TEXT, REF_WAV, zero_shot_spk_id="jennie")`; English = `inference_cross_lingual(text, REF_WAV_EN, zero_shot_spk_id=...)` with `REF_WAV_EN = REF_WAV`; `TTS_SEED = 1234` | `voice-trials\cosyvoice\repo\pretrained_models\CosyVoice2-0.5B` (3.8 GB), code from `voice-trials\cosyvoice\repo` | CPU copy always in RAM; borrows a GPU copy for a request when **`TTS_GPU_NEED_GB = 3.8`** is free (`TTS_GPU_WORK_GB = 1.2` if already there); back to the CPU after `JENNIE_TTS_IDLE_S = 300` idle s, or at once when a new voice note reaches `/stt` (the bot's LLM answers next and needs the room); move to GPU 0.7-0.9 s, back 0.1 s, `torch.cuda.empty_cache()` |

Before giving up on the GPU the service evicts only **its own** idle model (e.g. the resident TTS model to make room
for Whisper), never another process's. A CUDA out-of-memory during a render falls back to the CPU (time
permitting), including one raised in the thread CosyVoice runs its language model in (the service hooks the token
generator so that thread cannot swallow the error). Caveat measured on this PC: `torch.cuda.mem_get_info` did not see
the resident brain, so the 3.8 GB gate did not always stop a move onto a full card (then Windows pages VRAM to
shared RAM and renders slow down).

**STT details**: a segment is dropped as non-speech when `no_speech > 0.6` with `logprob < -0.5`, when it is a stock
subtitle phrase ("Thanks for watching", "한글자막 by …", "시청해주셔서 감사합니다", …) or a lone "you" / "thank you" /
"bye" with `logprob < -0.6` (an 8 s hum came back as `""`). Language: Jennie speaks `en` and `ko`
(`STT_LANGS`); a third language under 0.85 probability is transcribed again as the likelier of en/ko; if en/ko is
detected under `STT_UNSURE_PROB = 0.6` the note is decoded both ways and the more confident text wins (a Korean note
starting "제니야…" was once heard as English at 0.14).

**TTS details**: `prepare_text` spells numbers out (CosyVoice has no text normaliser): Korean `3명`→`세 명`,
`2026-09-27까지`→`이천이십육 년 구 월 이십칠 일까지`, `18:05에`→`오후 여섯 시 오 분에`, `3~5일`→`삼 일에서 오 일`,
`12.5%`→`십이 점 오 퍼센트`, phone numbers digit by digit; English `18:05`→`6 oh 5 PM`, dates, ordinals, `%`;
emoji, Markdown, bullets and links removed; a closing `~` becomes `!`. Audio `polish`: trim silence and trailing
breath (`SOUND_DB = -30`, `SPEECH_PEAK_DB = -18`, pads 0.08/0.15 s), pauses > 0.9 s shortened to 0.5 s, loudness
-19 dBFS RMS with peaks ≤ -1 dBFS, resampled to 48 kHz, written as OGG/Opus by soundfile and decoded again to prove
it plays. Length check: expected speech = chars × `SECONDS_PER_CHAR = {"ko": 0.19, "en": 0.075}`; longer than
2.5× + 2 s ("ran long": the model failed to stop) or, for > 20 chars, shorter than 0.35× (part missing) → rendered
once more with seed 1235 on the GPU if the time left allows; still short → 503, never a partial note. CPU render
estimate `10 s + 5.5 × seconds of speech`, so on the CPU only ~85 Korean or ~215 English characters fit the 100 s
limit. `style` "aegyo" and "neutral" render identically: the cuteness is in the words the bot writes.

**Startup (35-60 s)**: `_claim_port()` binds 127.0.0.1:8765 with `SO_EXCLUSIVEADDRUSE` *before* the heavy imports
(a second copy logs "already in use" and exits within seconds); sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`,
`HF_HOME=models\hf`, `MODELSCOPE_CACHE`, `TQDM_DISABLE`; imports torch before CTranslate2 (puts torch's
cuBLAS/cuDNN DLLs on the path); builds CosyVoice2 on the CPU, caches the reference as speakers "jennie" /
"jennie_en" (`add_zero_shot_spk`) and frees the ONNX speech tokenizer and speaker encoder; loads Whisper medium on
the CPU; warms the GPU once (turbo transcribes the reference, CosyVoice renders one line, both leave the GPU) so the
~27-29 s first CUDA call is not paid by the first student; starts the idle-offload thread (`IDLE_CHECK_S = 10`);
`uvicorn.Server(Config(app, host, port, workers=1, access_log=False)).run(sockets=[_listener])`.

**Logs**: `jennie_voice.log` (rotating 3 × 2 MB): at most `LOG_TEXT_CHARS = 40` characters of anything said;
CosyVoice's own per-sentence "synthesis text" lines are reduced to their length (`_RedactFilter`). Example request
line: `tts cuda en/aegyo: 40 chars in 1 part(s) -> 2.9 s audio, 22 KB, render 6.9 s, total 6.9 s (waited 0.0 s),
torch reserved peak 3.33 GB, RAM 2.7 GB (private …)`.

**Environment** (`jennie_voice\.venv`, Python 3.12, 6.7 GB):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install "setuptools<81" wheel
.venv\Scripts\python.exe -m pip install torch==2.7.1+cu128 torchaudio==2.7.1+cu128 --index-url https://download.pytorch.org/whl/cu128
.venv\Scripts\python.exe -m pip install -r requirements.txt -c constraints.txt
```

`constraints.txt`: `torch==2.7.1+cu128`, `torchaudio==2.7.1+cu128`, `numpy<2`, `setuptools<81`,
`transformers==4.51.3`, `huggingface_hub<1.0`, `tokenizers<0.22`, `faster-whisper==1.2.1`, `ctranslate2==4.8.2`.
`requirements.txt`: the CosyVoice inference set (`conformer==0.3.2`, `diffusers==0.29.0`, `HyperPyYAML==1.2.3`,
`inflect==7.3.1`, `librosa==0.10.2`, `lightning==2.2.4`, `hydra-core==1.3.2`, `omegaconf==2.3.0`, `rich==13.7.1`,
`onnx`, `onnxruntime`, `openai-whisper==20250625`, `transformers==4.51.3`, `x-transformers==2.11.24`,
`modelscope==1.20.0`, `gdown==5.1.0`, `matplotlib`, `wget`, `rootutils`, …), `faster-whisper==1.2.1`, `fastapi`,
`uvicorn`, `python-multipart`. `stubs\pyworld.py` replaces pyworld (no cp312 Windows wheel; only used in training).
**Do not delete** `voice-trials\cosyvoice\repo`, `voice-trials\cosyvoice\ref` or `voice-trials\whisper\hf_home`:
the service loads code, weights, the reference and Whisper medium from there by path.

**Scripts**

| Script | What |
|---|---|
| `start_jennie_voice.vbs` | self-locating; checks `.venv\Scripts\pythonw.exe` (MsgBox if missing); `WshShell.Run """<pythonw>"" service.py", 0, False` |
| `stop_jennie_voice.bat [nopause]` | stops only `service.py` under this folder's venv + its Python312 child |
| `watchdog_jennie_voice.ps1` | `/health` via `Invoke-RestMethod -TimeoutSec 15`; if it fails twice 20 s apart: a process younger than 5 min is left alone (still loading); otherwise kill and restart via the .vbs; not running → start; log `jennie_watchdog.log` |
| `install_jennie_voice.bat` | creates `Startup\JennieVoice.lnk` (wscript.exe `"...\start_jennie_voice.vbs"`, WindowStyle 7) and `schtasks /Create /TN "JennieVoiceWatchdog" /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"...\watchdog_jennie_voice.ps1\"" /SC MINUTE /MO 5 /RL LIMITED /F` |
| `bench_stt.py` → `bench_stt.json`, `bench_stt_cpu2.json` | STT model comparison (below) |
| `smoke_test.py` → `smoke_test.json` | against a running service: 24/24 pass (health, STT KO/EN/OGG/silence, TTS KO/EN/short, dates heard back, client give-up, refusals, `/health` latency during renders, VRAM sampling) |
| `offline_test.py` | no model/port: text preparation, log redaction, guard, non-speech filter, render stop: 58/58 pass |

Task state now: `JennieVoiceWatchdog` **Disabled** (`<Enabled>false</Enabled>`; otherwise the same XML shape as
HangeulBotWatchdog, action `-File "C:\Hangeul\JARVIS\jennie_voice\watchdog_jennie_voice.ps1"`, created
2026-09-27T20:01:56); `JennieVoice.lnk` parked in `C:\Hangeul\JARVIS\disabled\` (target
`C:\Windows\system32\wscript.exe`, args `"C:\Hangeul\JARVIS\jennie_voice\start_jennie_voice.vbs"`, working dir
`C:\Hangeul\JARVIS\jennie_voice`). The service last ran on 28 Sep 2026 until ~17:06.

**STT choice** (`bench_stt.py`: 21 synthetic clips, 13 Korean in 7 voices incl. 3 pitch-shifted "very cute", 8
English; CER vs the rendered text):

| Model | Device | Korean CER | English CER | Wrong language | ~12 s clip | Load |
|---|---|---|---|---|---|---|
| **large-v3-turbo** | GPU fp16 | 0.034 | 0.007 | 0/21 | **0.59 s** | 2.6 s (reload 1.9 s) |
| large-v3 | GPU fp16 | 0.030 | 0.007 | 0/21 | 1.39 s | 4.9 s (reload 9.3 s), ~4 GB VRAM |
| large-v3-turbo | CPU int8 | 0.037 | 0.007 | 0/21 | 10.3 s | 3.7 s |
| **medium** | CPU int8 | 0.042 | 0.013 | 0/21 | **7.6-8.1 s** | 3.0-3.5 s |
| small | CPU int8 | 0.066 | 0.010 | 0/21 | 2.75 s | 1.1 s |

Caveat: all clips were synthetic; real noisy phone notes with Bangladeshi-accented English were never tested.

**Build the voice service from zero** (everything is on disk here; this is how to reproduce it on another PC). The service reaches the network **only while you build it**: at run time it sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` (`service.py:116-117`), so every model must already be on disk.

1. **CosyVoice code.** `git clone --recursive https://github.com/FunAudioLLM/CosyVoice C:\Hangeul\JARVIS\voice-trials\cosyvoice\repo`, then `git -C ...\repo checkout 074ca6d` (the commit on this PC: 26 May 2026, "Add FunAudioLLM ecosystem section with links to ASR projects") and `git -C ...\repo submodule update --init` so that `third_party\Matcha-TTS` is at `dd9105b` (v0.0.5-2). `service.py:219-221` puts `stubs\`, the repo and `repo\third_party\Matcha-TTS` at the front of `sys.path`; nothing is pip-installed from the repo.
2. **CosyVoice weights** (`voice-trials\cosyvoice\dl_models.sh`, a POSIX `sh` script run from Git Bash; `curl -sSL --retry 3` from `https://huggingface.co/<repo>/resolve/main/<file>` into `repo\pretrained_models\<repo name>\<file>`, skipping files already present):
   - `FunAudioLLM/CosyVoice2-0.5B` (the voice; 3.8 GB): `CosyVoice-BlankEN/config.json`, `CosyVoice-BlankEN/generation_config.json`, `CosyVoice-BlankEN/merges.txt`, `CosyVoice-BlankEN/model.safetensors`, `CosyVoice-BlankEN/tokenizer_config.json`, `CosyVoice-BlankEN/vocab.json`, `campplus.onnx`, `config.json`, `configuration.json`, `cosyvoice2.yaml`, `flow.pt`, `hift.pt`, `llm.pt`, `speech_tokenizer_v2.onnx`, `README.md`.
   - `FunAudioLLM/CosyVoice-300M-SFT` (only for the reference *timbre*, step 6): `campplus.onnx`, `config.json`, `configuration.json`, `cosyvoice.yaml`, `flow.pt`, `hift.pt`, `llm.pt`, `speech_tokenizer_v1.onnx`, `spk2info.pt`, `README.md`.
   - (`dl_v3.sh` fetched `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` for the trial only; not used by the service.)
3. **Whisper models, before going offline.** GPU model `mobiuslabsgmbh/faster-whisper-large-v3-turbo` into the service's own `HF_HOME` = `jennie_voice\models\hf` (so it lands in `models\hf\hub\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo`, 1.6 GB); CPU fallback `Systran/faster-whisper-medium` into `voice-trials\whisper\hf_home` (the trial's `download_models.py` does `huggingface_hub.snapshot_download(repo)` with `HF_HOME` set to that folder). `Systran/faster-whisper-small` is also in `models\hf\hub` (optional, `STT_CPU_MODEL = "small"`). The service reads them by path (`STT_MODEL_DIRS`, `service.py:89-94`; `_snapshot()` picks the snapshot folder) with `local_files_only=True`.
4. **The venv** (`jennie_voice\.venv`, Python 3.12): torch first, then the rest under the constraints (commands above): `pip install "setuptools<81" wheel`; `pip install torch==2.7.1+cu128 torchaudio==2.7.1+cu128 --index-url https://download.pytorch.org/whl/cu128`; `pip install -r requirements.txt -c constraints.txt`.
5. **`stubs\pyworld.py`**: a 9-line module whose `harvest`, `dio` and `stonemask` raise `RuntimeError("pyworld stub: not available in this inference-only install")` (pyworld has no cp312 Windows wheel; CosyVoice uses it only for training-time F0).
6. **The reference voice** (`voice-trials\cosyvoice\synth.py`, run in the trial venv `voice-trials\cosyvoice\venv`): `python synth.py sft` renders the stock 300M-SFT Korean female speaker saying `REF_KO_TEXT` → `ref\ref_sft_ko_female.wav`; `python synth.py v2b` re-speaks it with CosyVoice2 cross-lingual from that timbre with seeds 1234, 7 and 42, scores each with openai-whisper `small` (CPU, `download_root=whisper_models`) by CER, and copies the best to `ref\ref_v2xl_ko_female.wav` (= `REF_WAV`, `service.py:56`). The text is `REF_TEXT` (`service.py:57`), quoted in §5.1.
7. Start with `start_jennie_voice.vbs`, check `GET /health`, then run `smoke_test.py` (24 checks) and `offline_test.py` (58 checks).

**`service.py` function map** (1,309 lines):

| Line | Name | What it does, and why it is not obvious |
|---|---|---|
| `:49-114` | constants | `HOST="127.0.0.1"`, `PORT=8765`; paths (`COSYVOICE_REPO`, `COSYVOICE_MODEL`, `REF_WAV`, `REF_TEXT`); the TTS, STT and GPU thresholds quoted above; `LOCAL_HOSTS`; `LOG_TEXT_CHARS=40` |
| `:116-121` | environment | `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `HF_HOME=models\hf`, `MODELSCOPE_CACHE=models\modelscope`, `TQDM_DISABLE` (all `setdefault`); `JENNIE_GPU=0` hides CUDA entirely |
| `:129` | `_RedactFilter` | cuts CosyVoice's own "synthesis text" log lines to their length |
| `:196` | `_claim_port()` | binds 127.0.0.1:8765 with `SO_EXCLUSIVEADDRUSE` **before** the heavy imports, so a second copy exits in seconds instead of loading 3.8 GB first; the socket is handed to uvicorn in `main()` |
| `:219-221` | `sys.path` | stubs, CosyVoice repo, Matcha-TTS; then `import torch` before `faster_whisper` (torch's cuBLAS/cuDNN DLLs on the path for CTranslate2) |
| `:267-445` | number spelling | Korean native/Sino numbers with counters (`_NATIVE_COUNTERS`, `_SINO_COUNTERS`), dates, times (`오전/오후`), ranges `3~5`, phone numbers digit by digit (`_KO_DASHED_RX`); English times, dates and ordinals (CosyVoice has no text normaliser) |
| `:450` | `prepare_text(text, language)` | strip emoji, Markdown, bullets and links; spell numbers; a closing `~` becomes `!` |
| `:485` | `polish(wav, sr)` | trim silence and trailing breath, shorten long pauses, set loudness, resample to 48 kHz |
| `:527` | `encode_ogg_opus(wav, sr)` | writes OGG/Opus with soundfile and **decodes it again** to prove it plays. CosyVoice renders at **24000 Hz** (`self.sample_rate`, `:636`/`:793`); the service always writes **48 kHz** |
| `:551-569` | `_hallucinated(segment)` | the non-speech filter: `NO_SPEECH_PROB=0.6` with `NO_SPEECH_MAX_LOGPROB=-0.5`, `_HALLUCINATION_RX` (subtitle phrases), `_WEAK_HALLUCINATIONS` |
| `:571-622` | `Job`, `_Stop`, `_RenderControl` | a request's time budget (`left_s`, `stop_reason`: timed out or client gone) and the per-render control the hooks consult (`should_stop`, `raise_if_done`, `raise_if_failed`) |
| `:624` | `_is_oom(e)` | recognises CUDA out-of-memory errors |
| `:628` | `class Engine` | the models, the one lock and the GPU policy |
| `:663` | `Engine._make_room(need_gb, keep)` | evicts only this service's own idle model from the GPU, never another process's |
| `:687` | `Engine._tts_to(device)` | moves CosyVoice between CPU and GPU by swapping `p.data` to a GPU copy of the permanent CPU tensors (shared storage kept shared), switches `llm_context` to a CUDA stream, and moves the cached speaker features in `frontend.spk2info`; on failure points everything back to the CPU so the model is never half on the GPU; `empty_cache()` after leaving the GPU |
| `:730` | `Engine._install_hooks()` | wraps `model.llm.inference` (CosyVoice runs it in its own thread, which would print and swallow an out-of-memory error) so it stops at the next token when time is up and records the exception; wraps `flow.decoder.forward_estimator` so the request thread raises it (or `_Stop`) before more work |
| `:765` | `Engine._forget_render()` | clears CosyVoice's per-sentence dicts after a render stopped half-way |
| `:773` | `Engine.load()` | CUDA init; `AutoModel(model_dir=COSYVOICE_MODEL)` on the CPU (`_cuda_hidden()`); `add_zero_shot_spk(REF_TEXT, REF_WAV, "jennie")`; frees the ONNX speech tokenizer and campplus sessions; Whisper medium int8 on the CPU; one GPU warm-up of each model, then both leave the GPU |
| `:845` | `Engine.turn(what, job)` | the one-at-a-time lock (waits `LOCK_WAIT_S`, then 503); `busy_s()` feeds `/health` |
| `:879-966` | `_whisper`, `_transcribe`, `stt(data, job)` (`:918`) | decode, VAD, language detection with the en/ko re-check below `STT_UNSURE_PROB`, the GPU model only when `STT_GPU_MIN_FREE_GB` is free |
| `:968-1039` | `_render`, `_cpu_render_fits`, `_render_on`, `_length_problem` | sentence-by-sentence rendering with `TTS_CHUNK_GAP_S` gaps; the CPU-time estimate; the ran-long / too-short checks |
| `:1048` | `Engine.tts_request(text, language, style, job)` | GPU if there is room, CPU if it fits the budget, one retry with seed 1235, never a partial note |
| `:1116` | `Engine.idle_loop()` | every `IDLE_CHECK_S`: TTS back to the CPU after `TTS_IDLE_S` |
| `:1145` | `_LocalClientsOnly` | the ASGI guard described above (Host, Origin, Content-Length, body size, content type) |
| `:1188-1238` | `app`, error handlers, `_watch_client`, `_job` | FastAPI with docs off; JSON errors; a request whose client hung up stops its render |
| `:1241-1287` | `/health`, `/stt`, `/tts` | the API above |
| `:1292` | `main()` | `engine.load()`, the idle thread, `uvicorn.Server(Config(app, host, port, log_config=None, access_log=False, workers=1)).run(sockets=[_listener])` |

### 5.3 The bot side — `C:\Hangeul\BOT\src\bot\voice.py` (1,877 lines)

Registered only when `JENNIE_VOICE_ENABLED=true`:
`app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message, block=False))` —
`block=False` so a slow voice round trip never holds up typed commands.

Constants: `STT_TIMEOUT = 60.0`, `TTS_TIMEOUT = 120.0` (above the service's 100 s limit, so the bot always gets an
answer, not a timeout), `TTS_MAX_CHARS = 600`, `REPLY_MAX_CHARS = {"ko": 32, "en": 120}` (hard limit),
`REPLY_TARGET_CHARS = {"ko": 22, "en": 90}` (asked for), `BRIEF_MAX_CHARS = 160`, `ANSWER_MAX_CHARS = 2000`,
`MAX_VOICE_SECONDS = 60`, `MAX_DOWNLOAD_BYTES = 20 MB`, `VOICE_TURN_WAIT = 240.0`, `LLM_TIMEOUT = 30.0`,
`ROUTE_MAX_TOKENS = 160`, `REPLY_MAX_TOKENS = 120`, `HISTORY_TURNS = 6`, `PROMPT_TURNS = 3`. Why one short
sentence: every character is ~0.19 s (Korean) / ~0.075 s (English) of speech the GPU must render first, and a
Korean render peaks at 3.55-3.67 GiB — right at the edge of the card beside the resident brain.

**One voice note, step by step** (`handle_voice_message` → `_answer_voice`; nothing ever raises out of the handler):

1. `bot.is_authorized(update)` — unauthorised senders get no reply at all (logged).
2. Longer than 60 s or bigger than 20 MB → `🎧 That recording is too long for me — please keep voice notes under 60 seconds.`
3. **Filler at once** (background task, before the download): a random ready clip in the chat's last language
   (`last_language(chat)`, Korean until someone has spoken), unless a `/sendmail` flow is waiting (then only a
   "typing" action).
4. Download (`media.get_file()` → bytes).
5. `/stt` inside `_voice_turn()` (a per-event-loop `asyncio.Lock`: the bot never has two requests in flight at the
   service, so each timeout counts only its own work; waiting > 240 s → busy). Busy → `🎧 Sorry, the voice service
   is busy right now. Please try again in a minute with a short voice note, or type your question.`; unreachable →
   `🎧 Sorry, I can't listen to voice notes right now (the voice service is unavailable). Please type your question.`;
   no words → `🎧 I couldn't make out any words in that voice note. Please try again.`
6. Language: `spoken_language(code, text)` = `ko` when Whisper says `ko` or ≥ 30 % of the letters are Hangul; the
   reply language is `ko` or else `en`.
7. `🎧 heard: <transcript>` is sent (background, capped at 3,900 chars) while the brain routes.
8. If a `/sendmail` flow is waiting (checked before and again right before dispatch, since notes run concurrently):
   `✉️ An email is waiting for your answer — please type it (SEND / EDIT / DENY or the detail I asked for). I don't
   handle emails from voice notes.` — a misheard "send" must never e-mail a student.
9. **One routing call** `route(heard, turns)` → `{"command", "date", "english_query", "date_problem"}` or `None`.
   Dates are then corrected in code: relative words (`오늘/어제/그저께/그제`, today/yesterday/day before yesterday,
   weekday names incl. `지난 금요일` → the last one before today) are computed by `_spoken_day`, because the brain
   miscounts weekdays; a calendar date the words name must match the brain's date, else the words' own single date is
   used; a date that does not exist ("31 September", "the 45th", `9월 31일`) gives the command's own "I couldn't read
   that date" reply, never another day.
10. **Dispatch** (`_dispatch`): the command's handler runs **exactly as when typed**, on a `_CapturingUpdate` whose
    `message.reply_text` / `edit_text` / `delete` are recorded (PTB objects are frozen, so they are wrapped, not
    patched). The date goes in through `context.user_data["override_text"]` (e.g. `"26 Sep 2026"`,
    `"1 Sep 2026 to 15 Sep 2026"`, `"student 412"`). Mapping: `verified_*`/`inquiries_*` → today or date commands;
    `crosscheck` → range (two dates + a range word), date, today or `student <id>`; `passports` → the live
    cross-check for that day; `calendar` → `/calendar` with the English words; `stats` → a specific figure through
    the typed route (`ask.classify`), else `/stats`; `missing_report` → `/missing`; `chat` → no command. An answer
    to a pending "which date?" question is recognised. Anything unplaced (or the brain down) goes through
    `telegram_bot.handle_natural_language_message(update, context, query=english_query or heard)`.
11. **The spoken sentence** `spoken_reply(heard, language, answer, turns, day)`:
    * small talk → one brain call; any number must come from the question (`_facts_ok`); shown as `💬 <sentence>`;
    * an answer with facts: `answer_facts(answer)` extracts up to 8 one-figure lines (`label: value`, `(N items)`
      headings, and "No … were verified/recorded" lines as `…: 0`). **English**: one brain call, checked by
      `_fact_problem` = the day named must be the answer's own day, it must state a figure (or "none"), and
      `brief.claims_problem` against the facts with Jennie's extra words (`ta da yay hehe okie … boss team …`);
      one retry with the allowed numbers listed; else the plain line `Okie! <label> <day>: <value>, hehe!`
      (`Aww, <label>: none, hehe!` for 0). **Korean**: never the brain's words (they cannot be checked): built in
      code from the headline fact via `_KO_TOPICS`, e.g. `짜잔! 어제 상담 요청은 21건이에용!`, `오늘 검증된 학생은 없어용!`
      (copula 이에용/예용 by final consonant; the `짜잔!` dropped if over 32 chars);
    * an answer without facts (a question back): brain words with no number allowed; "couldn't read the portal" →
      the fixed portal-down line.
12. `_remember(chat_id, heard, language, command, day, speech)` — per-chat `deque(maxlen=6)` in memory only
    (cleared on restart; voice turns only; the router sees the last 3).
13. `/tts` in `_voice_turn()` with `style="aegyo"` → `bot.send_voice(voice=<ogg>, duration=…, filename="jennie.ogg")`;
    failure → `🔇 Voice reply unavailable right now — the answer is in the text above.`
14. One metadata-only INFO line: `Voice note from <chat>: 5.2s audio, ko, verified_today | filler +0.14s, download
    0.00s, stt 3.57s, route 0.51s, command 1.87s, reply 0.38s, tts 26.92s, voice sent 0.00s, total 33.25s`.

The user sees three messages: `🎧 heard: …`, the normal text answer, and Jennie's voice note (plus the filler clip
first).

**Filler clips** (`data\jennie_fillers\`, git-ignored, re-rendered when missing or when a line changes):

| File | Line | Duration |
|---|---|---|
| `ko_1.ogg` | 잠시만용~ 찾아볼게요! | 2.75 s |
| `ko_2.ogg` | 음~ 찾아볼게용! | 2.55 s |
| `ko_3.ogg` | 금방 알려드릴게용~ | 2.53 s |
| `en_1.ogg` | Ooh, one sec~ let me check! | 2.19 s |
| `en_2.ogg` | Hehe, checking now! | 1.30 s |
| `en_3.ogg` | Okie, give me a moment~ | 1.32 s |

`fillers.json` = `{"<file>": {"line", "duration"}}`. Rendered through `/tts` (style aegyo) by `prepare_fillers()`
(after `warm_brain`, and in the background after each note), written atomically (`.tmp` + `os.replace`); a clip
longer than `FILLER_MAX_SECONDS = 3.5` is never sent (CosyVoice's fixed seed sometimes drags a short Korean line out;
these lines were picked because they render in 1.4-2.8 s). After the first send, Telegram's `file_id` is reused, so
later sends upload nothing.

**The spoken brief**: after the text brief (never instead of it), if `JENNIE_VOICE_ENABLED and
JENNIE_SPOKEN_BRIEF`, `send_spoken_brief(bot, chat_id, "\n".join(composed.facts))` — Jennie gets the brief's fact
list (not its text, whose dates, clock times and tile figures would let a number be said about the wrong thing),
`spoken_brief()` asks the brain for ≤ 140 characters of cute English, checks it with `claims_problem` plus
`_BRIEF_CHEER_WORDS` (`… fighting cheer cheers busy bye see tomorrow rest well thank thanks …`), falls back to
`Good evening! Today's brief is in the chat, hehe.`, renders it (`filename="jennie-brief.ogg"`). Any failure only
skips the voice note.

**Text for speech in the bot** (`_speech_text`): `_plain` (links → their text; URLs, emojis, backticks and the
Markdown characters `* _ # | < > [ ] { }` removed; `→` → "to"; the `~` is kept, the service turns it into "!"), `BDT`/`৳` → "taka"/"타카", numbers spelled (`_spell_numbers_en`: dates as "the twenty-sixth of
September", clock "six oh five", ordinals, amounts, `%`; `_spell_numbers_ko`: native numbers before counters
`명 개 시간 시 살 마리 권 잔 가지 곳 군데 번째 달`, Sino otherwise, `6월`→유월, `10월`→시월; phone numbers / IDs digit by
digit), then `_fit` to the limit at a sentence end.

### 5.4 Language and style

* **Two languages**: the reply follows the language spoken, per note. Korean = cute 애교: endings ~요, ~용, ~어용,
  ~구요, openers 짜잔!, 없어용 for zero; English = the English version of 애교: "Ta-da!", "Yay!", "hehe", "okie", warm
  and caring — the owner asked for 애교 "in english as well" (J9). One voice (one Korean-female synthetic timbre)
  for both, so Jennie is one persona.
* The cuteness is in the **words**, not in a TTS style: CosyVoice's instruct mode ("say it cutely") made speech less
  intelligible, so `style` is passed but renders the same.
* Facts stay exact in any style: every spoken number is checked (English) or built from the fact (Korean).
* **No cloning of real people or celebrities**: the reference voice is synthetic (section 5.1); a real voice would
  only ever be used with that person's consent (e.g. the owner's own).

### 5.5 Measured latencies

| Version / test | Result |
|---|---|
| v1 (`d7a5817`, qwen2.5:7b, rewrite + keyword routing + summary = 3 LLM calls, `keep_alive: 0` before speech), first live note 27 Sep 20:15 | **~70 s** (STT 5 s, 36 s queued behind another note's LLM call, two 7B reloads, TTS 5-9 s) — "too late, I want something more conversational" |
| v1, live test 27 Sep 23:52 | 20-28 s (7B cold reloads 7-9 s; a 294-char English summary took 12 s of TTS) |
| **Fast Jennie** (`d9bbecc`), latency harness with a fake Telegram, 28 Sep 01:45, brain resident (2.82 GiB, warm in 3.7 s) | filler **0.14-0.15 s**; "heard" **2.2-3.6 s**; full text 2.9-6.0 s; voice note **5.9-9.5 s** typical, mean 11.6 s, max 33.3 s |
| — per stage, 8 notes | STT mean 2.57 s (max 3.57); route 0.47 (max 0.54); command 0.66 (max 1.87, portal login + read); reply 0.31 (max 0.38); TTS mean 7.62 s (max 26.92); TTS = 65.5 % of the time, STT 22.1 % |
| — examples | EN "what deadlines are coming up?" 6.97 s total (TTS 3.5 s); EN thanks (chat) 5.90 s; KO "오늘 서류 검증된 학생 몇 명이야?" 33.25 s (the 22-char render "ran long" and was rendered twice, 26.9 s, peak 3.87 GB); KO follow-up "그럼 어제는" 15.88 s (rendered twice, 10.6 s) |
| Live note, 28 Sep 08:55 (GPU full: desktop ~2 GB) | 25.8 s: STT 5.1 s, TTS move to GPU 8.7 s with 0.23 GB free, render 12.7 s |
| Voice service smoke test (GPU / CPU-only) | `/stt` 17 s Korean note 2.4-4.7 s / 8.9 s; 9-12 s English 2.1-3.5 s / 7.9 s; 3 s silence 1.6 s; `/tts` Korean 87 chars → 16.5 s audio in 10.8-14.1 s / ~96 s; English 166 chars → 11.3 s in 6.6-9.1 s; 20 Korean chars → 3.8 s in 3.0-3.6 s / 64 s. GPU speech ≈ 0.65-0.8× real time |
| Floor | a Telegram voice note cannot be "instant": ~4-7 s minimum (download, STT, render, upload); hence the filler clip |

VRAM with the voice on: 4.6-4.8 GB idle, 7.1-7.8 GB peaks during Korean replies; RAM: the service ~5.5 GB working
set (private 7.8-10.4 GB), free RAM 1.7-2.7 GB on the 16 GB PC. This is why it was switched off (details and the
GPU lessons: [02 §8](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)).

### 5.6 Known limits (open when it was switched off)

* Korean renders sometimes "run long" and are rendered twice (16-33 s). Short lines make it rarer, not impossible.
* VRAM at the edge beside the resident brain; moving the monitor to the iGPU (~1.2-1.4 GB) was the recommended fix.
* History is in memory only and holds voice turns only (typed questions are not in it).
* The filler language follows the chat's previous turn, not the note being answered.
* Real noisy / accented speech never tested; no wake word; no voice e-mail.
* Ideas discussed, not built: a PC "Hey Jennie" wake word on the same brain; a private "Jennie Call" web app over
  Tailscale (a public Vercel demo with open access was advised against).

### 5.7 How to turn Jennie back on

First check the state is as §5.0 says (all read-only):

```powershell
Select-String '^JENNIE_' C:\Hangeul\BOT\.env                                   # both false
Get-ScheduledTask -TaskName JennieVoiceWatchdog | Select-Object TaskName, State  # Disabled
Test-Path "C:\Hangeul\JARVIS\disabled\JennieVoice.lnk"                          # True
try { Invoke-RestMethod http://127.0.0.1:8765/health -TimeoutSec 3 } catch { "voice service: not answering" }
nvidia-smi --query-gpu=memory.used,memory.total --format=csv                    # ~1.0-1.2 GB used
```

Budget the GPU before you do it: with the voice on the card idles at ~4.6-4.8 GB and peaks at 7.1-7.8 GB
(8-9.8 GB with extra apps, which spills), and a sync's EasyOCR (~2.4 GB, peaks ~3.9) now shares it too;
moving the monitor cable to the motherboard frees ~1.2 GB first ([02 §8](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)).
Then, at a quiet moment (not 18:00-18:10, 08:25-08:40, 09:00-09:10):

1. `C:\Hangeul\BOT\.env`: `JENNIE_VOICE_ENABLED=true` and (for the spoken 18:05 brief) `JENNIE_SPOKEN_BRIEF=true`.
2. Move the shortcut back:
   `Move-Item "C:\Hangeul\JARVIS\disabled\JennieVoice.lnk" "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\"`
3. `Enable-ScheduledTask -TaskName JennieVoiceWatchdog`
4. Start the service **first** and wait until `http://127.0.0.1:8765/health` returns `"ok": true` (35-60 s):
   `wscript.exe "C:\Hangeul\JARVIS\jennie_voice\start_jennie_voice.vbs"`
5. Restart the bot so it registers the voice handler, pins the brain (`keep_alive -1`, `warm_brain`, the 10-minute
   keep-warm) and renders any missing fillers: `cmd /c "C:\Hangeul\BOT\stop.bat" nopause`, then
   `Start-Process wscript.exe -ArgumentList '"C:\Hangeul\BOT\start_background.vbs"' -WorkingDirectory C:\Hangeul\BOT`.
6. Check `hangeul_bot.log` for `Jennie voice replies enabled (voice service http://127.0.0.1:8765).` and
   `Brain qwen3:4b-instruct resident on the GPU: 2.62 GB …`, then send a short voice note. `ollama ps` should keep
   listing the model with no near expiry (keep_alive -1).

To switch it off again (exactly what was done on 28 Sep 2026 17:08), in this order:

```powershell
# 1. .env: JENNIE_VOICE_ENABLED=false and JENNIE_SPOKEN_BRIEF=false (edit the file; keep a .env.bak-YYYYMMDD first)
Disable-ScheduledTask -TaskName JennieVoiceWatchdog                 # 2. BEFORE stopping, or it restarts the service
Move-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\JennieVoice.lnk" "C:\Hangeul\JARVIS\disabled\"   # 3.
cmd /c "C:\Hangeul\JARVIS\jennie_voice\stop_jennie_voice.bat" nopause   # 4. stops only service.py under its own venv
cmd /c "C:\Hangeul\BOT\stop.bat" nopause                              # 5. restart the bot (full-path restart: 02 §9.2)
Start-Process wscript.exe -ArgumentList '"C:\Hangeul\BOT\start_background.vbs"' -WorkingDirectory C:\Hangeul\BOT
```

At its start the bot then releases the brain (`unload()`), and the GPU returns to ~1.0 GB idle.

---

## 6. Blueprint notes for a new bot

* One small local model, one option set, one `num_ctx`; measure the prompt before sending (chars ÷ 2.4) because
  Ollama truncates silently; `127.0.0.1`, not `localhost`.
* Pin the model only when latency matters (voice); otherwise `keep_alive` a few minutes and free the GPU.
  Make the switch one flag (`brain_pinned()`), and release a pinned copy at start-up when the flag is off.
* Make the voice switchable in one place per piece (an `.env` flag for the bot side; the service's Startup
  shortcut and watchdog task parked, not deleted), so "off" frees the GPU completely and "on" is minutes.
* A second model for another job (here gte-small for the Supabase embeddings) goes to the CPU in its own
  processes with the GPU hidden (`CUDA_VISIBLE_DEVICES=-1` on Windows), so it never competes with the LLM.
* The LLM chooses (JSON indices or a command enum via Ollama's `format` schema) or words a sentence that a
  deterministic checker verifies number by number and word by word; drop what fails, never "fix" it.
* Keep speech a separate local service with a tiny HTTP contract (`/health`, `/stt`, `/tts`), one lock, time limits
  below the client's timeouts, 127.0.0.1 only plus Host/Origin checks, and metadata-only logs.
* Make the "instant" part pre-rendered (filler clips) and keep the real reply to one short sentence.
* Only synthetic or consenting voices as references.
