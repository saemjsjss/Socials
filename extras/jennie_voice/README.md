# Jennie voice service

Jennie's ears and voice for the Hangeul Telegram bot (@the_Jennie_bot), running on this PC only.
The bot sends a voice note to `/stt`, gets back what was said and in which language, answers it,
and sends the answer to `/tts` to get a voice note in Jennie's voice (English or cute Korean).
Nothing leaves the PC and nothing is downloaded while it runs. It listens on `127.0.0.1:8765` only.

| Part | What | Where the weights are |
|---|---|---|
| Speech-to-text (GPU) | faster-whisper **large-v3-turbo**, float16 | `models\hf\hub\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo` (downloaded once, 1.6 GB) |
| Speech-to-text (CPU fallback) | faster-whisper **medium**, int8 | `C:\Hangeul\JARVIS\voice-trials\whisper\hf_home\...faster-whisper-medium` (trial folder, by path) |
| Text-to-speech | **CosyVoice2-0.5B**: zero-shot for Korean, cross-lingual for English, one reference voice | `C:\Hangeul\JARVIS\voice-trials\cosyvoice\repo\pretrained_models\CosyVoice2-0.5B` (trial folder, by path) |
| Jennie's voice | reference `ref_v2xl_ko_female.wav` + its transcript, seed 1234 (the approved sample) | `C:\Hangeul\JARVIS\voice-trials\cosyvoice\ref\` |

**Do not delete `C:\Hangeul\JARVIS\voice-trials\cosyvoice\repo` or `...\voice-trials\whisper\hf_home`**: the
service loads the CosyVoice code, its weights and the medium Whisper model from there. All paths are
constants at the top of `service.py`.

## API

```
GET  /health -> 200 {"ok": true, "stt": "large-v3-turbo", "tts": "cosyvoice2", "device": "cuda", "tts_on_gpu": false,
                     "busy_s": 0.0}
POST /stt    multipart/form-data, field "audio" (Telegram voice .ogg/Opus, or .wav/.mp3/.m4a)
             -> 200 {"text": "...", "language": "ko", "duration_s": 17.2, "seconds": 2.9}
POST /tts    {"text": "...", "language": "en"|"ko", "style": "aegyo"|"neutral"}
             -> 200 audio/ogg (Opus, mono, 48 kHz), headers X-Duration (s) and X-Seconds (render time)
```

* Errors are JSON `{"error": "..."}`: 400 bad input or undecodable audio, 413 text over 600 characters
  (or audio over 25 MB / 600 s), 422 missing `audio` field, 500 anything unexpected, and 503 when:
  * the request waited more than 120 s for the one-at-a-time lock;
  * a `/tts` would miss its time limit: the GPU has no room and a CPU render of that text would take
    longer than the 100 s the request has (answered at once), or the render ran past the limit;
  * the rendered speech came out cut short (a failed render);
  * the client hung up (nobody reads that answer; the work stops and frees the lock).
* Requests that are not from the bot are refused before their body is read: 403 for a `Host` other than
  `127.0.0.1:8765` / `localhost:8765` (DNS rebinding) or any request with an `Origin` header (a web page
  in a browser on this PC), 411 for a POST without `Content-Length`, 413 for a body over 64 KB (`/tts`) or
  26 MB (`/stt`), 415 for a `/tts` that is not `Content-Type: application/json`. httpx (`json=`, `files=`)
  and PowerShell's `Invoke-RestMethod` pass all of these.
* `/health` never waits for the lock: it answers in ~20 ms even during a long render (measured).
  `busy_s` is how long the request in progress has held the lock. When one request has held it for over
  10 minutes (`JENNIE_HUNG_S`; nothing legitimate takes that long, so it is a stalled GPU/driver call),
  `/health` answers **503** with `"ok": false`, and the watchdog restarts the service.
* `"stt"` in `/health` is the GPU model; with no usable GPU it names the CPU model.
* `language` from `/stt` is the Whisper code. Jennie speaks `en` and `ko`: when Whisper is unsure and
  guesses a third language (under 0.85 probability) the note is transcribed again as the likelier of
  en/ko. A confident other language (say Bangla) is returned as is, so the bot can answer in English.
  Silence, and sounds that are not speech (a hum, a tone, music), come back as `{"text": ""}`.

### What the bot can send to /tts

Plain reply text. The service prepares it for the voice (CosyVoice has no text normaliser here):
numbers are spelled out, also with a particle attached as Korean normally writes them (Korean: `3명` ->
`세 명`, `7개` -> `일곱 개`, `2026-09-27까지` -> `이천이십육 년 구 월 이십칠 일까지`, `18:05에` -> `오후 여섯
시 오 분에`, `오후 6:30` -> `오후 여섯 시 삼십 분`, `3-5일` / `3~5일` -> `삼 일에서 오 일`, `3-5명` -> `세 명에서
다섯 명`, `2025-2026학년도` -> `이천이십오에서 이천이십육 학년도`, `12.5%` -> `십이 점 오 퍼센트`, phone numbers
(`010-1234-5678`, `+880 1711-123456`) digit by digit; English: `18:05` -> `6 oh 5 PM`, `6:30pm` -> `6 30 PM`,
dates, ordinals, `%`), emoji, markdown, bullets and links are removed, and each line becomes a sentence.
`offline_test.py` checks these. So the 18:05 brief text can go in nearly as it is sent to Telegram, as
long as it is under 600 characters.

`style`: `aegyo` and `neutral` render the same way. CosyVoice2's instruct mode ("say it cutely") was
tried in the trials and made the words less clear (Whisper large-v3 CER 0.051-0.085 vs 0.034 for plain
zero-shot), so the cute style lives in the text the bot writes (짜잔!, ~요, 헤헤, 있으세용?), exactly
like the approved sample.

## How it works

* **Startup (35-60 s measured)**: first takes the port (bound, not yet listening), so a second copy
  exits within seconds instead of loading the models too. Then builds CosyVoice2 on the CPU, analyses
  the reference voice once and caches it as speaker "jennie" (then frees the ONNX speech tokenizer),
  loads Whisper medium int8 on the CPU, then warms up the GPU once: Whisper turbo transcribes the
  reference, CosyVoice renders one line, and both leave the GPU again. The slow first CUDA call (the
  ~27 s seen in the trials; 29 s in one of my starts) is paid here, not by the first student.
* **One lock** serialises all `/stt` and `/tts` work; a request waiting more than 120 s gets 503. A
  request whose client hangs up while it waits is dropped, and one that is running stops (see below).
* **Speech-to-text**: if the Whisper turbo weights can go on the GPU (at least 3 GB free at that
  moment), they are loaded (~1.5-2 s from disk), used, and unloaded right after the request, so they
  never sit on the GPU while Ollama needs it. Otherwise the medium int8 model on the CPU is used.
  Beam 5, Silero VAD filter, language auto-detect. Segments that are not speech are dropped: Whisper
  turns a hum or a tone into stock subtitle phrases (measured on an 8 s tone: medium heard "Thanks for
  watching!" with no_speech 0.91, turbo heard "You" with logprob -0.99), so a segment is dropped when
  no_speech > 0.6 with logprob < -0.5, when it is one of those phrases ("Thanks for watching",
  "한글자막 by ...", "시청해주셔서 감사합니다", ...), or when it is a lone "you"/"thank you"/"bye" with
  logprob < -0.6. Turbo reports no_speech ~0 for everything, so the phrase list is what works there.
* **Text-to-speech**: Korean = CosyVoice2 zero-shot with the reference and its transcript; English =
  cross-lingual with the same reference. Seed 1234 every time. The audio is trimmed (silence and the
  faint breath/noise the model sometimes adds after the words), pauses longer than 0.9 s are shortened
  to 0.5 s, the speech is levelled to -19 dBFS RMS with peaks under -1 dBFS, resampled to 48 kHz and
  written as OGG/Opus by soundfile, then decoded again to prove the file plays. If a reply still comes
  out far longer than its text (the model occasionally fails to stop), or far shorter (under 0.35 x
  the expected length: part of it is missing), it is rendered once more with another seed - on the GPU
  only, and only when the time left allows. Speech still cut short is a 503, never a partial voice note.
* **Time limit (`JENNIE_TTS_MAX_S`, 100 s from arrival, lock wait included)**: below the bot's 120 s
  `/tts` timeout, so the bot always gets an answer rather than a timeout. A CPU render costs about
  10 s + 5.5 x the length of the speech (the 11 s voice prompt goes through the models every time;
  measured with the bot running: 1.8 s of speech took 19.6 s, 4.6 s 29 s, 16.4 s 96 s), so before a CPU
  render the service estimates it (speech length = 0.19 s/char Korean, 0.075 s/char English) and answers
  503 at once if it would not fit: on the CPU only replies up to ~85 Korean or ~215 English characters
  are spoken; the bot then sends its text answer alone. A render that still runs past the limit, or
  whose client hangs up (checked every 0.5 s), stops at the next token of CosyVoice's language model /
  step of its flow decoder and frees the lock within about a second.
* **VRAM policy**: idle, the service holds only its CUDA context (~0.25-0.3 GB). The TTS model moves to
  the GPU for a request when 3.8 GB is free (1.2 GB if it is already there), and goes back to the CPU
  after 5 idle minutes (`JENNIE_TTS_IDLE_S`), or as soon as a voice note arrives at `/stt` (the bot's LLM
  answers that note before the next `/tts`, so it gets the room), with `torch.cuda.empty_cache()`. The
  CPU copy of the weights is kept all the time and the model only borrows a GPU copy, so the move back
  is instant (0.1 s) and RAM stays flat. If there is not enough free VRAM, the request runs on the CPU
  (time permitting, see above) and the log says so; before giving up on the GPU the service first evicts
  its own idle model (e.g. the resident TTS model to make room for Whisper), never anyone else's. A CUDA
  out-of-memory during a render falls back to the CPU (time permitting), also when it happens in the
  thread CosyVoice runs its language model in: that thread would swallow the error and carry on with
  the tokens made so far, so the service hooks the token generator, records the error and raises it on
  the request's own thread.
* **Logs**: `jennie_voice.log` beside `service.py` (rotating, 3 x 2 MB). Never more than the first 40
  characters of anything a student said or Jennie says; CosyVoice's own per-sentence "synthesis text"
  lines keep only the length (a long reply is several sentences, so 40 characters of each would leak
  most of it). Each request line has timing, device, VRAM/RAM figures.

### Working with Ollama on the one 8 GB GPU (for the bot side)

Ollama keeps `qwen2.5:7b` (4.7 GB) on the GPU for 5 minutes after each answer. While it is there,
free VRAM is ~2 GB, so **both Whisper and CosyVoice fall back to the CPU**: speech-to-text then takes
~7-9 s per note, and a spoken reply takes about 6-17 x its length (a 4 s Korean reply took 64 s on
the CPU; on the GPU 3 s), so only short replies fit the 100 s limit and longer ones get a quick 503.
For voice replies the bot should free Ollama before calling `/tts`, e.g. ask for the voice-turn answer
with `"keep_alive": 0` (Ollama unloads right after answering), or send
`{"model": "qwen2.5:7b", "keep_alive": 0}` to `/api/generate` (the bot does the former).

The other way round, the TTS model (2.6 GB) stays on the GPU for up to 5 minutes after a spoken reply,
leaving ~4.2 GB free: less than qwen2.5:7b needs, so Ollama would load partly on the CPU. The service
therefore moves the TTS model off the GPU as soon as a new voice note arrives at `/stt` (the bot's LLM
calls come right after it). A typed question answered within 5 minutes of a spoken reply (or of the
18:05 spoken brief) still finds the TTS model there; set `JENNIE_TTS_IDLE_S` lower (e.g. 60) if that
matters more than the ~0.8 s the next `/tts` saves by finding the model on the GPU.

Client timeouts: the service answers a `/tts` (voice note or 503) within `JENNIE_TTS_MAX_S` = 100 s of
receiving it, plus well under a second of encoding, so the bot's 120 s `/tts` timeout is enough; keep it
above that limit. `/stt` has no time limit of its own (a 60 s note takes ~3 s on the GPU, ~8-15 s on the
CPU). When the bot gives up on a request anyway, the service notices the closed connection within 0.5 s
and stops working on it, so the next voice note does not wait behind it.

## Measured on this PC (RTX 5060 8 GB, Ryzen 5 8600G, bot running)

### Speech-to-text choice (`bench_stt.py`, `bench_stt.json`, `bench_stt_cpu2.json`)

21 clips: 13 Korean in 7 different voices (including 3 pitch-shifted "very cute" ones) and 8 English
in 7 voices, each scored by character error rate against the text it was rendered from. Same
settings as the service (beam 5, VAD, auto language). Numerals written as digits are not counted as
errors; most remaining Korean "errors" are spelling choices (있구요 -> 있고요, 있으세용 -> 있으세요).

| Model | Device | Korean CER | English CER | Wrong language | Time for a ~12 s clip | Load |
|---|---|---|---|---|---|---|
| **large-v3-turbo** | GPU fp16 | 0.034 | 0.007 | 0 / 21 | **0.59 s** | 2.6 s (reload 1.9 s) |
| large-v3 | GPU fp16 | 0.030 | 0.007 | 0 / 21 | 1.39 s | 4.9 s (reload 9.3 s) |
| large-v3-turbo | CPU int8 | 0.037 | 0.007 | 0 / 21 | 10.3 s | 3.7 s |
| **medium** | CPU int8 | 0.042 | 0.013 | 0 / 21 | **7.6-8.1 s** | 3.0-3.5 s |
| small | CPU int8 | 0.066 | 0.010 | 0 / 21 | 2.75 s | 1.1 s |

* **GPU: large-v3-turbo.** It keeps Korean accuracy (0.034 vs 0.030; identical on the pitch-shifted
  clips), is 2.4x faster, reloads in 1.9 s instead of 9.3 s, and needs ~2.2 GB of VRAM (nvidia-smi:
  +2.0 GB loaded, +0.13 GB while transcribing) instead of ~4 GB for large-v3.
* **CPU fallback: medium int8.** Turbo is barely faster than real time on this CPU (0.86x), medium is
  0.64-0.68x on 12 s clips. Whisper always encodes a full 30 s window, so on the CPU a note costs about
  7-9 s whatever its length: faster than real time only for notes longer than ~10 s, and slower when
  the bot is busy. `small` would be 3x faster (2.75 s) but hears Korean clearly worse (0.066, up to 0.19
  on the cute voices). To trade accuracy for speed set `STT_CPU_MODEL = "small"` (already downloaded).
* Caveat: every clip is synthetic (TTS voices). No real student voice notes with background noise or
  Bangladeshi accents were available; accuracy on those will be lower for every model.

### Service timings (`smoke_test.py` -> `smoke_test.json`, `cpu_test.json`)

Four GPU runs of the smoke test (the spread is the bot's own load on the PC) and one CPU-only run:

| Request | GPU | CPU (`JENNIE_GPU=0`) |
|---|---|---|
| `/stt` 17 s Korean voice note (includes loading turbo onto the GPU) | 2.4-4.7 s | 8.9 s |
| `/stt` 9-12 s English note | 2.1-3.5 s | 7.9 s |
| `/stt` 4-5 s note (.mp3 / .m4a / .ogg) | 1.9 s | 6.9-7.1 s |
| `/stt` 3 s of silence | 1.6 s, `""` | |
| `/tts` Korean aegyo, 87 chars -> 16.5 s voice note | 10.8-14.1 s | ~96 s (99 chars -> 16.4 s) |
| `/tts` English, 166 chars -> 11.3 s voice note | 6.6-9.1 s | 29 s (79 chars -> 4.6 s) |
| `/tts` short Korean, 20 chars -> 3.8 s voice note | 3.0-3.6 s | 64 s |

GPU speech is rendered at about 0.65-0.8x real time. Moving the TTS model to the GPU takes 0.7-0.9 s,
back to the CPU 0.1 s. Every rendered note was sent back through `/stt`: Korean heard with CER
0.10-0.12 (the digits Whisper writes, 있고요, and one word, 최신 heard as 출신 in the same render with or
without post-processing), the short Korean line and English 0.0.

### Limits and failures (measured on the test instances, `smoke_test.py` and by hand)

| Situation | What happened |
|---|---|
| bot gives up on a 215-char `/tts` after 3 s (client timeout) | render stopped 0.1 s later ("the client went away"), lock free 3.3 s after sending |
| CPU only, 114-char Korean reply, 30-35 s limit | 503 in 0.02 s: "no GPU: a CPU render would take ~129 s, over the 35 s limit" |
| CPU only, 20-char line started under a 35 s limit | stopped at 35.9 s, 503 "the 35 s time limit passed"; the next `/stt` ran at once (9 s on the CPU) |
| one request holding the lock past `JENNIE_HUNG_S` (set to 15 s for the test) | `/health` 503 `"ok": false` from 15.0 s on, 200 again once the request ended |
| `마감일은 이천이십육 년 구 월 이십칠 일까지예요!` (seed 1234) | rendered 17.6 s of mumbling, trimmed to 6.9 s, heard as nothing; now caught on the raw length, rendered again with seed 1235 (5.1 s, heard right), 21.6 s in all. The date spelling now used (`이천이십육년 구월 이십칠일`) renders right the first time |
| `브리핑은 18:05에 보내드려요~` / `마감일은 2026-09-27까지예요!` | heard back as "브리핑은 오후 6시 5분에 보내드려요." / "마감일은 2026년 9월 27일까지예요." |
| 8 s humming tone to `/stt` (bot's own httpx) | `{"text": ""}` (turbo heard "You", logprob -1.19, dropped) |
| second copy started while the first loads | exits at once with "already in use", loads nothing |
| requests the bot makes (httpx 0.28, `json=` / `files=`), the watchdog's `Invoke-RestMethod` | accepted by the local-clients-only guard |

### VRAM (device-wide, nvidia-smi; the desktop alone uses ~0.9-1.0 GB)

| State | Used | Service share |
|---|---|---|
| service idle | 1.26-1.29 GB | ~0.25-0.3 GB (CUDA context only) |
| during `/stt` (peak) | 3.3-3.4 GB | ~2.2 GB |
| during `/tts` (peak) | 4.6-4.75 GB | ~3.5 GB (weights 2.6 + work 0.9; torch reserved peak 3.5 GB) |
| TTS model resident, between requests (up to 5 min) | 3.7-3.8 GB | ~2.6 GB |
| after the idle offload | 1.29 GB | back to the context |

### RAM

About 5.5 GB working set when idle (CosyVoice2 weights 2.4 GB stay in RAM, Whisper medium int8, CUDA
and library DLLs); 4.5 GB in CPU-only mode. Private bytes are ~7.8-8.1 GB idle and ~10.4 GB while the
TTS model is on the GPU (Windows commits system memory for VRAM allocations), back to ~7.9 GB after the
offload. Flat across requests and GPU round trips (checked over two full cycles). With the bot running,
free RAM on this 16 GB PC was 1.7-2.7 GB while the service ran.

## Start and stop

* **Start by hand (hidden)**: double-click `start_jennie_voice.vbs`. It runs
  `.venv\Scripts\pythonw.exe service.py` from this folder, and shows a message box if the venv is
  missing. Ready when `http://127.0.0.1:8765/health` answers (about a minute).
* **Start in a console (to watch it)**: `.venv\Scripts\python.exe service.py` (Ctrl+C stops it).
* **Autostart + watchdog**: run `install_jennie_voice.bat` once. It creates the Startup shortcut
  `JennieVoice.lnk` and the task `JennieVoiceWatchdog` (every 5 minutes, only while signed in,
  `/RL LIMITED`) that runs `watchdog_jennie_voice.ps1`: if `/health` fails twice in a row (20 s apart;
  a hung service answers 503) it restarts the service, or starts it if it is not running; a process
  younger than 5 minutes is left alone while it loads. The processes are looked up after the two
  checks, so a copy started during the 20 s wait is seen and left alone. Log: `jennie_watchdog.log`.
  Remove with `schtasks /Delete /TN "JennieVoiceWatchdog" /F` and delete `JennieVoice.lnk` from
  `shell:startup`.
* **Stop**: `stop_jennie_voice.bat` (stops only `service.py` under this folder's venv). The watchdog
  starts it again within 5 minutes unless it is disabled first:
  `schtasks /Change /TN "JennieVoiceWatchdog" /DISABLE`.
* Only one instance can run: the port is taken (with `SO_EXCLUSIVEADDRUSE`) before anything heavy
  loads, so a second copy logs "already in use" and exits within seconds (measured: before loading
  any model), even while the first is still loading.

### Settings (environment variables, for testing or tuning)

| Variable | Default | Meaning |
|---|---|---|
| `JENNIE_TTS_IDLE_S` | 300 | idle seconds before the TTS model leaves the GPU |
| `JENNIE_TTS_MAX_S` | 100 | a `/tts` answers within this many seconds of arriving, or 503 (keep it under the bot's 120 s timeout) |
| `JENNIE_HUNG_S` | 600 | `/health` answers 503 once one request has held the lock this long |
| `JENNIE_STT_GPU_KEEP_S` | 0 | idle seconds the Whisper weights stay on the GPU (0 = unload after each note) |
| `JENNIE_GPU` | 1 | `0` = never touch the GPU (no CUDA context at all) |
| `JENNIE_LOCK_WAIT_S` | 120 | lock wait before 503 (the contract says 120; lower only for tests) |

Everything else (paths, thresholds, loudness, reference voice) is a constant at the top of `service.py`.
`REF_WAV_EN` chooses the English reference: it is `ref_v2xl_ko_female` (one reference for both
languages, as specified). The approved English sample was actually rendered from `ref_sft_ko_female`;
CosyVoice's own speaker encoder rates English from `ref_v2xl` at 0.977 cosine similarity to that sample,
and English from `ref_sft` at 1.000 (it reproduces it exactly). Set
`REF_WAV_EN = os.path.join(COSYVOICE_TRIAL, "ref", "ref_sft_ko_female.wav")` to get the approved English
sample's voice exactly.

## Tests

* `smoke_test.py`: against a running service: health, `/stt` on Korean and English WAV and a
  Telegram-style OGG/Opus copy, silence, `/tts` Korean aegyo + English + a short line (saved as
  `test_out_ko.ogg` / `test_out_en.ogg`, decoded again and sent back through `/stt`), Korean times and
  dates with particles heard back, a client that gives up after 3 s (render stopped, lock free), the
  error answers including the local-clients-only refusals, `/health` latency during renders, and VRAM
  sampling. Writes `smoke_test.json`. Last run: 24/24 pass.
* `offline_test.py`: no model, no service, no port: text preparation (numbers with particles, dates,
  months, ranges, phone numbers, English times), log redaction of CosyVoice's per-sentence lines, the
  request guard, the non-speech filter, and the render stop / LLM-thread error capture on a fake model.
  Last run: 58/58 pass.
* `bench_stt.py`: the speech-to-text comparison above.

## Rebuilding the environment

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install "setuptools<81" wheel
.venv\Scripts\python.exe -m pip install torch==2.7.1+cu128 torchaudio==2.7.1+cu128 --index-url https://download.pytorch.org/whl/cu128
.venv\Scripts\python.exe -m pip install -r requirements.txt -c constraints.txt
```

torch 2.7.1+cu128 is needed for the RTX 5060 (sm_120). CTranslate2 (Whisper) uses the cuBLAS/cuDNN DLLs
that ship inside torch, which is why `service.py` imports torch first. `stubs\pyworld.py` replaces
pyworld (no Windows wheel for Python 3.12; CosyVoice only uses it for training). `numpy<2` and
`setuptools<81` as in the trial recipe.

## Files

| File | Purpose |
|---|---|
| `service.py` | the service |
| `start_jennie_voice.vbs` | start hidden (used by the Startup shortcut and the watchdog) |
| `watchdog_jennie_voice.ps1` | restart when `/health` fails twice |
| `install_jennie_voice.bat` | create the Startup shortcut and the watchdog task (not run yet) |
| `stop_jennie_voice.bat` | stop the service |
| `requirements.txt`, `constraints.txt` | the venv recipe |
| `stubs\pyworld.py` | pyworld stand-in |
| `smoke_test.py`, `offline_test.py`, `bench_stt.py` | tests; `*.json` their last results |
| `test_out_ko.ogg`, `test_out_en.ogg` | voice notes from the last smoke test; `test_in_ko.ogg` its OGG input |
| `models\hf\` | Whisper large-v3-turbo (used) and small (optional CPU fallback) |
