# Plan: Document Checker - a desktop app

Plan for approval, 5 Oct 2026, revised the same day for the owner's desk-check facts (Appendix C lists every change). Nothing has been built, run or installed.
- It merges three drafts in this folder: `app_draft_app_ui.md`, `app_draft_hardware.md` and `app_draft_engine.md`.
- What `PLAN.md` sections 1-2 found about today's check still holds and is reused. Its design, a background service feeding the bot, is not used.
- `path:line` is relative to `C:/Hangeul/JARVIS/socials/repo` at commit `8317741`, the code the live bot runs. `easyocr/...` is EasyOCR 1.7.2 in the bot's venv, read only.
- *(measured)* marks the owner's figures from this PC and a read-only look at the bot's venv. *(est.)* marks an estimate that a later measurement replaces.
- Names, numbers, dates and files are placeholders.

## Summary

- **What you get:** "Hangeul Document Checker", a Windows program for the desk. A student walks in with a ready file. Staff drop the student's folder, or the PDFs, on the window. While the student waits, the app reads every page in place, read-only and offline, and fills in **only the document-check report**: the urgent results first (required documents, passport and identity, apostille order, colour scans), then the rest, with the page and the problem marked, plus Excel and PDF. There is no portal login, password, Telegram or cloud. History, re-checks and batches of many students stay, as secondary features.
- **Same rules as today:** the rule code is copied word for word, and must reproduce the bot's results with **0 differing rows** before anyone relies on it. Each finding gets a rule id, a page and the text it saw.
- **The office's three cards, one installer:** the app uses the card the PC has: a GTX 1650 (4 GB, the lowest), the RTX 5060 (8 GB, the bot's PC) or an RTX 5080 (16 GB). One build covers all three *(measured: the bot's torch is compiled for every card from the GTX 16 series to the RTX 50 series)*. The app checks the NVIDIA driver, and each PC passes a parity check before it shows a verdict. A PC with no NVIDIA card, or one older than the GTX 16 series, is not supported, and the app says so.
- **Under 5 minutes on the weakest PC:** a typical whole file (about 11 files and 41 pages, 32 of them needing OCR) takes about 1-1.5 minutes on the RTX 5060, under 1 minute on the RTX 5080, and about **3-4.5 minutes on the GTX 1650** *(est.; that card is not measured yet)*. That is close to the bar, so it is met with steps that cannot change a verdict: a reader kept loaded, text pages skipping OCR, rendering and picture checks on processor helpers beside the card, urgent results first, and re-reading only a replaced file. Phase 0 measures the real GTX 1650 PC before anything else. Speed-ups that change the text come only if it still misses, and only on your word.
- **How long:** a desk check on this PC after about **29 working days**; everything, with the GTX 1650 and RTX 5080 PCs installed and proven, in about **63**, plus a one-week pilot at the desk.
- **Decided on 5 Oct (section 10):** the PCs, one installer, and the wait at the desk. **You decide:** window technology, portal import, the bot's own check, the main desk PC, keeping a reader loaded, full FP32 on every card, exports, and seven smaller points.

## 1. What the app does (and does not do)

**It does:**
- **A desk check, one student at a time,** while the student waits. Staff drop (or pick) one of two inputs. The drop area says "Files stay on this PC. Nothing is uploaded." Staff do not want student data in any cloud.
  - **A student folder in exactly the bot's layout,** for example `C:\Hangeul\VERIFIED STUDENT DOCUMENTS\EAP (ENGLISH FOR ACADEMIC PURPOSE)\<NAME (PASSPORT)>`. The folder name gives the student. The parent folder's name gives the program (the four names in `progress_builder.py:108-131`). Each file's type comes from its name, with today's patterns and longest-match rule (`rules.py:56-74`; `doc_verifier.py:1036-1045`). You confirmed every folder follows this format, so the app never reads page content to classify or split files.
  - **Loose PDFs, one document per PDF.** The type comes from the file name in the same way. A name that matches no pattern gets a one-click "pick the type". Staff type or pick the student, and pick the program.
- **Reads in place, read-only.** It never shrinks, renames or moves a file, as today's download does (`verified_docs.py:292-327`). A file that disappears mid-check (a USB stick pulled out) ends the check as "not finished".
- **Reads every page,** up to 40 per file, with a flag above that. When a folder sits in the bot's tree and a file over 2 MB was shrunk, it reads the **original** from the `... - ORIGINALS OVER 2MB` tree (`config.py:104-106`; `verified_docs.py:316-320`). A walk-in folder is read as it is.
- **Runs today's rules** and shows one report, filled in live while the pages are read.
- **Keeps a local history,** re-checks only files that changed, and can still check many students as a batch.

**It does not:**
- log in to the portal, download, or hold any password, token or key;
- open any network connection;
- send Telegram messages, publish to Supabase, use a language model, or browse portal data;
- use cloud OCR;
- check a student on the processor alone. Only a single page may be read there, after repeated memory errors (section 3);
- change a rule's severity, or judge forgery;
- write into student folders or the bot's folders. It only reads the bot's lock file.

**Works without the portal and without passwords.** Today every check needs a live portal record fetched after a login (`doc_verifier.py:1120-1126`), and loading the rules reads the bot's `.env` (`doc_verifier.py:34`; `config.py:141-147`). The app checks the documents only by default, and replaces the record:

| Value | Source in the app |
|---|---|
| Name and passport number | The folder name `<NAME (PASSPORT)>`, which holds the portal's own values (`verified_docs.py:91-93`). For loose PDFs, typed by staff or picked from History. |
| Date of birth, expiry, sex | The passport's machine-readable lines (MRZ), used only when the check digit agrees **without "repair"**. The repair loop is PLAN problem 15 (`ocr_validator.py:248-262`). |
| Parents | The passport's printed page |
| Sponsor | Inferred from the bank file |
| Anything still missing | Staff may type it. The rules then re-run in seconds, with no page read again. |
| Program | The parent folder's name, or staff pick it (always for loose PDFs). Never the silent KLP default (`doc_verifier.py:1131`). |

Anything that cannot be checked is listed under **"Checks not run"**, instead of being skipped silently as today (`doc_verifier.py:452, 590, 965`).

**The optional portal-data import** is the portal's CSV export, saved by staff from their own browser; the app never logs in. It keeps only the columns the rules read. It adds:
- today's **24-field comparison** (`field_check.py:39-56`);
- the GPA and named-sponsor checks;
- a "portal says / passport says" identity column;
- results equal to the bot's on the same files.

## 2. The screens

All screens share a left rail (Home, History, Settings) and a card badge, for example "GTX 1650 - ready", "loading the reader" or "RTX 5060 - waiting for the bot's check". Verdict colours are today's Excel colours (`auto_verify.py:342-343`), always shown beside the word. **The desk check is the main flow: Home, then the live student report.**

**Home**
```
+-----------+--------------------------------------------------------------------+
| > Home    |  Files stay on this PC. Nothing is uploaded.   [GTX 1650 - ready]  |
|   History |  +--------------------------------------------------------------+  |
|   Settings|  |                                                              |  |
|           |  |            Drop the student's folder or PDFs here            |  |
|           |  |         [ Choose folder... ]     [ Choose PDFs... ]          |  |
|           |  |                                                              |  |
|           |  +--------------------------------------------------------------+  |
|           |  Recent checks                                                     |
|           |  14:12  <NAME (PASSPORT)>  EAP        FAIL, 2 to fix        [Open] |
|           |  13:40  <NAME (PASSPORT)>  BACHELOR   PASS                  [Open] |
|           |  10:03  <NAME (PASSPORT)>  KLP        re-check: FAIL->REVIEW [Open]|
+-----------+--------------------------------------------------------------------+
```
Use: drop the student's folder or PDFs. Reading starts at once, and the live report opens.
- A student folder gives the student and the program by itself. Anything still to confirm is asked on the live report, while the pages are read.
- Several student folders, a program folder or the whole root, dropped at once, become a batch under History.

**Loose PDFs** (a panel at the top of the live report, only when PDFs were dropped)
```
Loose PDFs - who and what                                  Reading has already started
Student  [ <NAME> ] [ <PASSPORT> ]   or  [ Pick from History v ]
Program  [ EAP v ]           [x] This is the student's complete set
| File                     | Pages | Type (from the file name)                  |
| passport_<UID>.pdf       |   2   | 01 Passport                                |
| bank_statement_<UID>.pdf |   9   | 08 Bank Solvency & Statement               |
| scan0012.pdf             |   3   | [ Pick the type v ]  (name not recognised) |
```
Use: answer while the pages are read; the rules wait for the answers, the reading does not.
- Without "complete set", the report says "these files only" and has no MISSING rows.
- Another student's passport number in a file raises a warning.

**Live student report** (the main screen)
```
<NAME (PASSPORT)> - EAP (from the folder) [change]        Checking - nothing saved yet
[########################..............]  19 of 32 OCR pages   GTX 1650 - about 2 min left
URGENT
 Required documents   9 of 9 present (from the file names)                         ok
 01 Passport          read; expiry and number checked                              ok
 Identity             name, number: folder | birth date, expiry, sex: MRZ          ok
 07 Academic          FAIL [AC-ORD] page 1 is not an e-Apostille (QR on page 3) [View]
 Colour scans         FAIL [SC-COL] 05 Father NID looks black-and-white         [View]
THE REST, in today's order
 04 Birth Certificate  PASS                  05 Mother NID     PASS
 06 Family Cert.       reading page 2 of 2   07 Academic       waits for 06
 08 Bank               waiting (9 pages)     09 Financial      waiting
 Cross-checks          after the last file
VERDICT  shown when every page is read                                     [ Cancel ]
```
Use: watch the urgent results arrive and talk the student through them while the rest is read.
- **Urgent first** *(est.: within about a minute on the GTX 1650)*: required documents present or missing come from the file names at once; the passport is read first; the apostille on page 1 and the colour scans come from processor helpers, which need no OCR. Then the other documents follow in today's order.
- **Every line shown is final.** It comes from today's rule function on complete reads, so it never changes later (section 4). The verdict appears only when every page is read and the cross-checks have run.
- **The time-left bar** names the card and counts down from this PC's measured seconds per page ("GTX 1650 - about 4 min"). It shows the estimate as soon as the folder is dropped. If the card is busy, it says why and since when.
- **Nothing is stored until the end.** Cancel or a failure shows "Not finished - nothing saved". A report is never half full.

**Student report** (the same screen when finished; full content in section 5)
```
<NAME (PASSPORT)> - EAP (from the folder) - checked <DATE> 14:12 on RTX 5060 in 1 min 14 s
VERDICT: FAIL - 2 to fix - 2 to look at - 11 files, 41 pages read (3 from originals)
Since <DATE>: 1 fixed - 2 still open - 0 new
             [ Edit details & re-run rules ]  [ Re-check ]  [ Export PDF ]
v MUST FIX (2)          rule id, document, page, message, what was seen  [View page >]
v TO LOOK AT (2)
> IDENTITY  > PORTAL FIELDS  > FILES NOT CHECKED (2)  > CHECKS NOT RUN (2)
> PAGES READ AND TIME  > ALL CHECKS PASSED
```
Use: work through "must fix", open each finding's page, and fill a missing value to re-run the rules. When the student comes back with a replaced file, a re-check reads only that file.

**Page viewer**
```
07 Academic Certificate & Transcript - academic_<UID>.pdf - read from: ORIGINAL
+-------+----------------------------------------+-------------------------------+
| [1] ! |  +----------------------------------+  | FAIL [AC-ORD]   1 of 4 [<][>] |
| [2]   |  |##################################|  | Page 1 is not an e-Apostille; |
| [3] A |  |# HIGHER SECONDARY CERTIFICATE   #|  | the first one is on page 3.   |
| [4]   |  |#  (whole page outlined: the     #|  | Fix: apostille first, then    |
| [5]   |  |#   e-Apostille was expected)    #|  | its certificate + transcript. |
| [6] A |  +----------------------------------+  | Text read on page 1 (OCR,     |
|       |   [ - ] [ + ] [ fit ] [ open file ]    | turned 90 deg, conf 0.91) ... |
+-------+----------------------------------------+-------------------------------+
```
Use: see why.
- It draws a box on the words or QR code a rule used.
- For "not found" findings it outlines the whole page and shows the text that was read.
- It still works from stored crops if the file has moved.

**Batch** (under History; secondary)
```
History > Batch: BACHELOR'S DEGREE - 15 students - <DATE> 14:12 - rules v1 - RTX 5080
| FAIL 8 | REVIEW 5 | INCOMPLETE 1 | PASS 0 | Not finished 0 |  14 of 15 done, about 1 min left
What to fix first                                                       Students
[AC-ORD]  07 Academic: apostille not on page 1 -> re-assemble, apostille first  6
[BC-DOB]  04 Birth certificate: date of birth not found on the passport         2
[SC-COL]  black-and-white scan -> ask for a colour scan                         2
| Student           | Verdict | Fix | Look at | Not checked | First problem    |
| <NAME (PASSPORT)> | FAIL    |  2  |    2    |      2      | 07 Academic: ..  |
| <NAME (PASSPORT)> | REVIEW  |  0  |    3    |      0      | 08 Bank: ..      |
| <NAME (PASSPORT)> | reading 08 Bank, page 6 of 9                             |
[ Pause ] [ Cancel ]   [ Export Excel ] [ Export PDF ] [ Re-check selected ]
```
Use: check or re-check many students, then open one.
- Unchanged students are skipped. A `*.part` file marks a student "downloading - later".
- **A desk check always goes first:** a batch pauses after its current file and resumes afterwards.
- Pause frees the card after 2 minutes. Cancel keeps finished students and discards the one in progress whole. Windows is kept awake while a batch runs.
- The student verdict is today's (`doc_verifier.py:1089-1096`). The "apostille not followed by its pages" FLAG is folded under AC-ORD.

**Settings (This PC)**, shown here on a GTX 1650 desk PC
```
Settings  [ This PC ] [ Folders ] [ Portal file ] [ History & privacy ] [ Rules ] [ Self-test ]
 Card        NVIDIA GeForce GTX 1650, 4 GB (Turing: full FP32)          [ Re-test this PC ]
 Driver      <VERSION> - OK (R570 or later needed)
 Processor   <CPU>, <N> cores / <N> threads                   Memory <N> GB
 Parity      sample pack passed <DATE>: sample rows equal, <N> of <N> OCR pages identical
 Readers     1, cap 2.6 GB, starts at 3.2 GB free     Helpers 3     Fresh every 5 students
 Keep ready  (o) keep the reader loaded, release after 30 min idle   ( ) load for each check
 Wait while  <GAME>.exe, or free card memory below 3.2 GB
 Speed       last measured <N> s per OCR page - typical whole file about <N> min
```
Use: see what the app chose for this PC and override it within safe limits.
- The Rules tab shows AC-ORD as "pinned: FAIL".
- Settings that change the text read are not on this screen.

## 3. How it fits each office PC

The office has exactly three kinds of PC, all with NVIDIA cards (5 Oct). One build covers them: the bot's torch 2.11.0+cu128 is compiled for sm_75, sm_80, sm_86, sm_90, sm_100 and sm_120 *(measured)*, which is every card from the GTX 16 series (Turing) to the RTX 50 series (Blackwell). An RTX 20, 30 or 40 card, or a card above the RTX 5080, works too and is set up like the nearest tier by its memory.

**Detection** takes under 2 seconds, needs no administrator rights, and never loads CUDA in the window process. Through the driver's NVML library and Windows it reads:
- the card, its memory (total and free), whether it drives the monitor, and the programs on it;
- **the driver version.** CUDA 12.8 needs the **R570 driver branch or later**; the exact minimum number is fixed in phase 0 from NVIDIA's CUDA 12.8 notes and the three office PCs. An older driver stops the app before any reading: "Update the NVIDIA driver to <MIN VERSION> or later, then restart." You or staff update it; the app never changes system settings.
- the card's generation, against the build's list written at build time; the first reader confirms it with a small test calculation;
- cores, threads, RAM and free disk;
- the neighbours on the card: a game list, the bot's lock (read only), its language model (Ollama) and voice service, and any full-screen program.

**Not supported:** a PC with no NVIDIA card, or a card older than the GTX 16 series (GTX 10 series and older). The app says so at start ("This PC has no supported NVIDIA card. Use a checking PC with a GTX 1650 or newer.") and shows no verdict. There is no processor-only mode. Your message also said "GTX 1650 or lower end version": decision 14 asks you to confirm that no office card is below a GTX 1650.

A hardware id (a hash of the card, driver, processor, memory and app version, with no PC or user name) selects the PC's saved profile.

**First-run calibration on bundled sample pages.** The pack holds about 25 fake pages:
- "SAMPLE" names, a specimen MRZ and a fake apostille QR;
- a violet stamp, Bangla text, a computer-made PDF and a giant page;
- pages printed once and scanned on the office scanner, plus one phone photo of a page turned sideways;
- sample student folders whose reference results are made on this PC: PASS, the AC-ORD FAIL, INCOMPLETE, and one of typical size (about 11 files, 41 pages) for the 5-minute test.

The calibration runs in this order:
1. **Self-test:** the QR is decoded by zbar, the models load with downloads off, and outside connections are refused.
2. **Parity check,** with the readers this PC will use: the sample students give the reference rows, and at least 95 % of OCR pages give identical text. 5 sample pages are also read by the processor reader that may read one page after memory errors (below). **No verdict is shown on a PC before this passes.**
3. **Speed test, in the background:** helpers, readers, seconds per OCR page, model load time, and graphics memory per page size.
4. **Profile saved.** It holds no student data.

It takes about 5-10 minutes *(est.)*, once per PC. It runs again after a card, driver or app change, or when staff ask.

**The core rule: the tuner only changes settings that cannot change a verdict.**
- **It may change:** readers, helper processes, threads, the graphics-memory cap, keeping a reader loaded, students per fresh reader, caches, priority, and the largest page it renders.
- **Locked at today's values:** batch size 1, image size 2560, the 150/200/250 dpi renders, the rotation retry, the card's own arithmetic (see "Numbers" below), and full precision for the processor reader. Any change needs decision 10.
- **Why the lock matters:**
  - In EasyOCR 1.7.2, a batch above 1 on a card takes a different code path (`easyocr/easyocr.py:377-410`).
  - On a processor, EasyOCR uses 8-bit models by default (`easyocr/detection.py:77-81`; `easyocr/recognition.py:168-177`), so the processor reader always turns that off.

**The three office PCs**

| | **GTX 1650, 4 GB** (the lowest) | **RTX 5060, 8 GB: this PC** | **RTX 5080, 16 GB** |
|---|---|---|---|
| Hardware | Turing: no tensor cores, no TF32. Processor and RAM unknown until phase 0. | Blackwell. Also runs the desktop, the bot's check, its language model and sometimes a game. Ryzen 5 8600G 6c/12t, 16 GB *(measured)*. | Blackwell. Processor and RAM unknown until phase 0. |
| Graphics-memory cap | **about 2.6 GB** = 4.0 − 0.6 desktop − 0.4 overhead − 0.3 margin; a reader starts at 3.2 GB free | **3.0 GB** = 7.96 − 1.4 desktop − 2.8 kept for the language model − 0.4 − 0.3; starts at 3.6 GB free | **3.5 GB per reader**; 3 readers use about 11.7 GB with overhead, leaving about 4 GB |
| Readers | 1 | 1 | **2-3 in parallel,** each on a different file of the same student (the speed test picks 2 or 3) |
| Processor helpers: render pages and run the picture checks while the card reads | cores − 2, at most 4 *(est. 2-4)* | 4 | cores − 2, less 1 per extra reader, at most 6 |
| Reader kept loaded (decision 5) | yes, so the load time is never in the wait; released after 30 min idle or when a game starts | loaded for each check (the card is shared); released 5 min after it, and at once when the bot's check starts | yes, 2 readers; a third starts at the drop |
| Fresh reader | every 5 students *(measured: 93 s each, up to 570 s in one long process)*, or on memory growth or slowdown; swapped in while idle, so no student waits for it | the same | the same |
| Typical whole file: 11 files, 41 pages, 32 OCR | **about 3-4.5 min** *(est.)* | **about 1-1.5 min** *(est. from 1.8 s per OCR page, measured)*; 93 s per student today at 6 pages per file *(measured)* | **under 1 min** *(est.)* |
| Card memory runs out | the ladder below; most likely here, with giant originals | the ladder below | the ladder below |

**Meeting 5 minutes on the GTX 1650.** Its time per OCR page is estimated at **4.5-7 s**, 2.5-4 times the RTX 5060's 1.8 s *(est.: about 3 TFLOPS of FP32 against about 19, no tensor cores, no TF32)*. Where a typical whole file's time goes *(est.)*:
- OCR of about 32 pages: 2.4-3.8 min on the card;
- sideways pages read again: up to about 0.5 min;
- rendering and picture checks: alongside on the helpers, so close to 0;
- loading the model: 0 with the reader kept loaded (otherwise about 10-30 s *(est.)*);
- the rules: about 1 s.

The total, about 3-4.5 minutes, is close to the bar. These steps reach it without changing a verdict:
1. **Text pages skip OCR,** as today: a page with a text layer is read in milliseconds (`doc_verifier.py:107-108, 141-142`). Originals bring back the text layer that shrunk bank PDFs lost (`verified_docs.py:249-274`).
2. **A reader kept loaded,** so the model load is never in the student's wait.
3. **Processor helpers beside the card.** Today rendering and the picture checks run one after another with the OCR (`doc_verifier.py:1074-1080`). In the app, helpers render the pages with the same calls and dpi, so the pixels are the same, and run the colour, QR and seal checks while the card reads. Only OCR is left on the card's path.
4. **Urgent results first.** The total is the same, but the urgent results are on screen in about a minute, and staff talk to the student while the rest is read.
5. **Re-check only what changed.** Page text and picture results are cached by the file's content, so when the student returns with one replaced file, only that file is read.
6. **Only if it still misses:** speed-ups that change the text (GPU batch mode, a smaller image size, half precision), each only after the 40-student set shows 0 changed verdicts (decision 10). Or the RTX 5080 becomes the main desk PC (decision 4).

Phase 0 measures the real GTX 1650 PC and says whether the bar is reachable. A file much bigger than typical can still take longer; the bar shows that as soon as it is dropped.

**On the bot's PC (RTX 5060): a desk check beside the bot.**
- The card holds the desktop (1.4 GB), the bot's language model when loaded (2.6-2.8 GB, unloaded after 5 minutes idle, `config.py:75-76`), sometimes a game, and the bot's own check. That check runs inside the 15-minute portal sync, uncapped (3.9 GB peak *(measured)*), up to 6 students a pass (`auto_verify.py:59`) at about 93 s each: up to about 10 minutes.
- The desk check's 3.0 GB cap fits beside the desktop and the language model, but not beside the bot's check. Both together would overfill the card, and the bot stores an out-of-memory error in its check as a final FLAG (`doc_verifier.py:1066-1071`; `auto_verify.py:292-298`).
- **So the app gives way.** While the bot's lock is fresh and its process alive (the logic of `auto_verify.py:62-97`, never the delete at `:96`), no reader starts, and a running reader stops within one page. Files already fully read are kept; the file in progress is read again later. The helpers carry on with rendering and picture checks. The live report says "Waiting: the bot's own check is using the card (since 14:02, usually under 10 min)".
- The app cannot make the bot wait. The bot checks only its own lock (`auto_verify.py:465`), and the app never stops another process.
- Later, with decision 3 (b), the bot's check runs through the app's engine, in one queue on the card in which a desk check goes first.
- This is why the main desk PC should be a GTX 1650 or RTX 5080 PC, with the bot's PC kept for the bot (decision 4).

**Numbers: TF32.** RTX 30-series and newer cards, the 50-series included, use TF32, a shortened number format, inside cuDNN convolutions by default. The GTX 1650 cannot, and computes in full FP32. So OCR text can differ, in rare cases, between the GTX 1650 and the 50-series cards. Three things catch it:
- each PC's parity check on the sample pack;
- Gate B repeated on the GTX 1650 PC with 20 students (section 8);
- the card and its arithmetic, printed on every report and kept in the cache key.

Forcing full FP32 on every card costs a little speed on the 50-series (measured in phase 0). That is decision 6.

**Live adaptation.** The window process watches every 2 seconds. The reader asks before each page whether it may go on.

| Signal | What the app does |
|---|---|
| Little graphics memory left (NVML free memory) | Finish the file, then wait, and name the program holding the card (decision 9). |
| A game or heavy graphics program: the game list, Windows' per-program GPU counters (already used on this PC, `voice.py:58`), or a full-screen program | End the reader within one page, so all its memory is freed, then wait. *(measured: with a game open, OCR fell from 1.8 s to about 17 s per page.)* |
| The bot's language model loads (bot's PC) | Nothing, because the reserve was sized for it. If it does not fit, wait for it to unload after 5 minutes idle. |
| The bot's own check starts (bot's PC) | End the reader within one page; the helpers continue (above). |
| The bot's quiet windows: 08:25-08:40, 09:00-09:10, 18:00-18:10 (`backfill.py:57`) (bot's PC) | Start no batch reader. A desk check still starts. |
| Someone working at the PC during a batch, the processor busy, or low RAM | Half the helpers; pause them on low RAM. A desk check keeps all its helpers: staff are waiting for it. |
| The reader slows down or its memory grows | Swap in a fresh reader after this student. |

**When the card runs out of memory,** the app never shrinks the image, lowers the dpi or keeps a shorter text:
1. First error: discard the file's partial read and read it again.
2. Second error: start a fresh reader and read it again.
3. Third error: read **that one page** on the processor (full precision, the same models), if this PC's parity check passed for the processor reader. The report marks the page "read on the processor" *(est. 20-40 s for the page)*. Otherwise: "Check not finished: page N too large for this card", with no verdict.

The speed test measures memory against page size, so a page known to be too big goes straight to step 3. Optional, and set by you, never by the app: the NVIDIA driver option "Prefer No Sysmem Fallback". An over-full card then gives a handled error instead of a silent slowdown. It is recommended on the GTX 1650 PCs.

## 4. The checking engine

The engine is a library, `doccheck_engine`, with no network code and no secrets. The app calls it once per student and receives each result the moment it is final. It returns a report, or "not finished" with nothing stored.

**Reused word for word, and what changes:**

| Today's code | In the app |
|---|---|
| `rules.py`: thresholds, file patterns, required documents, titles | The whole file, word for word |
| Every rule function: `check_*`, `cross_checks`, `classify`, `student_verdict` and helpers in `doc_verifier.py`; the colour, QR, Bangla, seal and apostille checks in `page_checks.py`; `field_check.check_field` | Word for word. A test compares each function with the bot's file. `classify` still gives each file's type from its name (`doc_verifier.py:1036-1045`). |
| Reading (`doc_verifier.py:49-150`; `page_checks.py:20-37`) | One new reader behind the same signatures: every page, originals, word boxes, complete reads only. Helpers render the pages with the same calls. |
| The settings import (`doc_verifier.py:34`), and the date fixed when the module loads (`:42`) | The app's own settings, with no `.env`. The date is set before each student. |
| `verify_student` (`doc_verifier.py:1048-1086`) | The same loop and rows, in today's order. Files come from the app's inventory, and every finding gets a rule id. A resource failure never becomes "could not read the file". |
| Folder finding, the portal fetch, and the program (`:1100-1131`) | The folder intake: the student from the folder name, the program from the parent folder's name (`progress_builder.py:108-131`) or picked; the portal-file import. Never the KLP default. |
| MRZ parsing (`ocr_validator.py:87-125, 190-372`) | Pure functions fed with the app's own OCR words. **Not reused:** its processor-only reader (`:79`), and `load_passport_image`, which writes `<name>_extracted.jpg` beside the scan (`:133-145`). |
| Excel writers (`auto_verify.py:318-445`) | Reused for today's workbook layout |

**Today's problems** (PLAN, re-checked against the code) **and the fix:**

| Today | Evidence | In the app |
|---|---|---|
| The automatic pass reads 6 pages per file | `auto_verify.py:191` | Every page, up to 40 |
| Colour, QR and seal checks see 4 pages | `page_checks.py:20, 275` | Every page |
| The shrunk copy is read. It has lost its text layer, so a computer-made bank PDF is held to the colour rule. | `verified_docs.py:249-274`; `page_checks.py:40-65` | The original for content; the submitted copy for format and photo rules |
| A failed first read is stored as a final FLAG | `doc_verifier.py:1066-1071`; `auto_verify.py:292-298` | Nothing is stored; the file is retried. |
| Rotation retries swallow every error and keep the shorter text | `doc_verifier.py:79-82` | Abort plus taint (below) |
| Unknown files are not reported; replaced uploads are still checked | `doc_verifier.py:1053-1072`; `verified_docs.py:387-388` | Every file is listed once, as checked or not checked, with a reason. |
| Findings have no rule id, page or evidence | `doc_verifier.py:1083-1084` | Rule id, page, the text seen, and a box |
| The check slows down in one long process | 93 → 570 s *(measured)* | A fresh reader every 5 students, swapped in while idle, with capped memory |
| A missing zbar silently falls back to OpenCV | `page_checks.py:100-103` | The self-test blocks checking. |

**Urgent first, without changing a row.** The rule functions share what they have seen:
- the birth-certificate and NID rules read the passport's text (`doc_verifier.py:393, 451`);
- the bank rule records the account holder, which the financial rule then uses (`:757, 820`).

So the engine may **read** files in any order, and several at once on the RTX 5080, but it **runs the rules** in today's order (`rules.py:78-89`, then the cross-checks). Each rule runs as soon as its file and every file before it are read. The passport comes first in that order. The other urgent results need no OCR text: missing documents come from the file names, and the apostille-on-page-1 and colour results come from today's picture functions (`page_checks.py:152, 404-407`), run by the helpers on the same file. A test compares the rows with a run in today's order.

**Whole documents and originals.**
- **Two reading profiles:**
  - `compat` reproduces today's reading exactly, and exists only to prove parity.
  - `full` is the app's reading: every page, one 200 dpi OCR pass per page, the original when its page count matches the copy, and the rotation retry on image files too.
- **Giant originals** fall back to the copy, with a note. `page_codes` renders its own pages (`page_checks.py:340-350`), so this is decided before the rules run.

**Nothing half-read is ever stored. There are two layers:**
- **Abort.** A resource error (graphics or system memory, or the reader being stopped) raises an abort that no rule's `except Exception` can catch. Nothing in `src/verify` catches more than `Exception`.
- **Taint.** The same error is also recorded as a taint, so errors caught inside picture checks (`page_checks.py:274-277`) still void the run.
- **Cache.** Page text is cached by the file's content hash, in one transaction, only after every page of the file has been read.

**Rule ids and evidence.**
- **About 70 rule ids** come from a table keyed by document, level and message pattern, so no rule body changes. An unmapped message stops the run as a code fault, like today's stop (`auto_verify.py:492-500`).
- **Today's message text is kept exactly.**
- **Evidence is one of:**
  - a located value (a date, amount, number or name, found with the rule's own parser);
  - page facts (where the apostilles are);
  - measurements (coloured pixels, seal size, photo background);
  - an absence (the pages searched and the words looked for).

**Documents-only checks and portal-data checks:**

| Checks | Without a portal file | With a portal file |
|---|---|---|
| Rules that read no portal value: birth certificate, notarisation, colour, QR, Bangla, apostille order, family-certificate age, NID numbers, bank minimum, fiscal year, income tax, most photo rules | As today | As today |
| Passport expiry; date-of-birth cross-check | The MRZ values (check digit); otherwise the latest date on the scan, as today | Portal values |
| Names on the NIDs, family certificate and academic papers; name and affidavit cross-checks | Folder name, or the MRZ for loose files; parents from the printed page or typed. An affidavit FAIL resting on a name not from the portal shows as FLAG. | Portal values |
| Bank and financial holder | Sponsor inferred from the bank file, or typed | The portal's sponsor |
| Passport number on the scan and across documents | Runs when the number came from the folder or was typed. Not run when it came from that same passport. | Runs |
| GPAs, named sponsor, 24-field comparison | Not run (GPAs and sponsor run if typed) | Run |
| New identity checks: no readable MRZ, or the folder number differs from the MRZ | FLAG only | Shown beside the portal values |

**Your rule decisions are kept:**
- "Page 1 is not an e-Apostille" (AC-ORD, `page_checks.py:404-407`) **stays FAIL** and is pinned (your earlier decision 18). *(measured: 47 of the 61 FAILs.)*
- The solvency-date rule (`doc_verifier.py:737-742`) and the "one qualification" rule (`page_checks.py:432-439`) **stay FLAG** (your earlier decision 7).
- The apostille-subject rule stays dormant: its data file has no writer (`page_checks.py:295-311`).
- No screen can change a severity.

## 5. The report

**A student report shows, in order:**
1. **Header:** the student, the program and its source, the mode, the card and its arithmetic (TF32 or full FP32), the date used by the date rules, and the rules, engine and reading versions.
2. **Verdict line,** plus "these files only" or "PASS (limited: no portal file)" where they apply, and what was fixed, is still open, or is new since the last check (matched by rule id and document, never by message text).
3. **Must fix:** each FAIL and MISSING, with its rule id, document, file ("read from the original"), pages, today's message, what was seen, the fix, and any folded findings.
4. **To look at:** each FLAG, with "on trial" tags. NOTEs follow as "Worth a glance".
5. **Identity:** each value with its source.
6. **Portal fields,** with a portal file only.
7. **Files not checked, and why.**
8. **Checks not run, and why.**
9. **Pages read, and time.**
10. **Passed checks,** collapsed.

**Exports** are written only where staff choose:
- **Excel** in today's `DOCUMENT CHECK.xlsx` layout, plus "To fix" and "Findings" sheets;
- **PDF.**

By default an export holds the report only. Pictures and full page text are opt-in.

```
DOCUMENT CHECK - <NAME (PASSPORT)> - BACHELOR (from the folder) - documents only
Checked <DATE> 14:12 on RTX 5060 (TF32) in 1 min 14 s - rules as of <DATE> - rules v1, engine 1.0, full
VERDICT: FAIL - 2 to fix, 2 to look at - 11 files, 41 pages read (3 from originals)
Since <DATE>: 1 fixed ([SC-COL] 05 Mother NID), 2 still open, 0 new

MUST FIX
 1 [AC-ORD] 07 Academic Certificate & Transcript, <FILE 1> (read from the original), pages 1, 3
   page 1 is not an e-Apostille - the first apostille is on page 3. The file must start with ...
   Seen: page 3, QR "<first 52 characters of the apostille link>"
   Fix: re-assemble - e-Apostille first, then the certificate and transcript it covers.
   Same cause: [AC-FOL] the e-Apostille on page 6 is not followed by the certificate ...
 2 [FC-AGE] 06 Family Relationship Certificate, <FILE 2>, page 1
   issued <DATE> (4 months ago) - older than the 3-month validity
   Seen: page 1, "Date: <DATE>" (OCR confidence 0.88)
   Fix: get a family certificate issued within the last 3 months.
TO LOOK AT
 3 [BK-DATE, on trial] 08 Bank, <FILE 3>, pages 1, 3: the solvency certificate is dated
   <DATE 1> but the statement was generated on <DATE 2> - they must carry the SAME date
 4 [ID-FOLD] the folder name says <PASSPORT A>; the passport MRZ says <PASSPORT B> (check digits ok)
 Worth a glance: [AC-SIDE] page 4 is scanned sideways - turned upright to be read
IDENTITY        name, passport no: folder name | date of birth, expiry, sex: MRZ (check digits ok)
                father, mother: passport printed page (OCR only) | sponsor: inferred from bank file
PORTAL FIELDS   not compared - no portal file
NOT CHECKED     <FILE 4> - name not recognised                                  [Set type]
                <FILE 5> - older upload, replaced on the portal
CHECKS NOT RUN  AC-GPA (needs the GPAs) | FN-SPON (needs the portal's sponsor)
PAGES READ      41 pages: 9 text layer, 32 OCR (2 turned upright, 1 still under 300 characters)
TIME            74 s: OCR 70 s on the card; picture checks 18 s on 4 helpers, alongside;
                rules 1 s; waited 0 s; 2 files from cache
```

## 6. Technology and packaging

| Part | Choice | Why |
|---|---|---|
| Window | **PySide6 (Qt 6 Widgets)**, Python 3.12 | One language with the engine. Native drag and drop gives real folder paths, which the program folder, the originals tree and the download marker need. A zoomable page viewer, and no open port. |
| Reading | EasyOCR 1.7.2 on torch 2.11.0, the `cu128` build, compiled for sm_75 to sm_120 *(measured)*: every card from the GTX 16 series to the RTX 50 series | The rules are tuned to its text, and it is proven on this card. The same build reads the rare single page on the processor. |
| Pages, images, QR | PyMuPDF 1.28.2, OpenCV 5.0.0.93, Pillow 12.3.0, pyzbar 0.1.9 with its Visual C++ runtime DLLs shipped beside it | Today's pinned versions (`requirements.txt:13-23`). Without that runtime, QR reading fails silently (`MIGRATION.md:57`). |
| History | SQLite, one transaction per finished student | A crash-safe single file |
| Exports | openpyxl through today's writers; Qt's own PDF writer | No browser engine is needed. |
| Hardware | NVML (`nvidia-ml-py`), psutil, Windows calls | Sees the whole card and the driver version, with no administrator rights |
| Reader process | The same program started with `--worker`, one per reader (2-3 on the RTX 5080), kept loaded between checks, fresh every 5 students, reporting one line per page | A crash cannot take the window down, and graphics memory is freed when it exits. |
| Packaging | PyInstaller (one folder) and Inno Setup | One offline pipeline, one installer |

The rejected options are in section 11. The licences (PySide6 LGPL, PyMuPDF AGPL) are fine for in-house use.

**One installer for every office PC.** It is:
- the same on the GTX 1650, RTX 5060 and RTX 5080 PCs;
- per-user, so no administrator rights are needed;
- offline, copied by USB stick or the office share;
- about 2.5-3 GB to copy and about 5 GB installed *(est.; the CUDA torch alone is 4.2 GB, measured)*.

- **Driver minimum:** NVIDIA R570 or later, for CUDA 12.8 (the exact number fixed in phase 0). The installer and the app check it and name the version to install. They never install or change a driver.
- On a PC with no supported NVIDIA card, the installer stops with "not supported" and says why.
- The OCR models (98 MB *(measured)*) and the sample pack are bundled; nothing is ever downloaded.
- The code lives in `C:\Hangeul\DOCCHECK\app\`, in its own repository outside the GitHub staging tree.

**Data and history** are kept per Windows user in `%LOCALAPPDATA%\Hangeul Document Checker\`:

| What | Holds |
|---|---|
| `history.db` | batches; students (each identity value with its source); files (path, content hash, original, type, checked or not and why); page text and word boxes (by content hash and card); picture-check results (by content hash); check runs (never overwritten); findings; field results |
| Other folders | 14 daily backups, small evidence crops, one hardware profile per PC (no student data), and logs (ids, counts and times only) |

A damaged `history.db` is refused and a backup offered. Today an unreadable `results.json` silently becomes empty (`auto_verify.py:136-144`).

**Privacy:**
- **No network:**
  - no HTTP library is shipped;
  - a socket fence allows only this PC;
  - EasyOCR downloads are off;
  - the self-test proves all three.
- **No secrets:** the app never opens `.env`, `token.json` or `credentials.json`.
- **No writes to sources:** a guard refuses any write under a folder that staff added.
- **Copies on the PC:** page text, crops and the database, kept for the time you choose (decision 12), with "Forget this student".
- **Exports** carry a personal-data warning. There is no send or upload button.

## 7. Build phases

Days are working days for one developer with an AI assistant. Test runs use read-only folders, and run on this PC only while the bot's lock is free and no game is running.

| Phase | What you get | Acceptance test | Days |
|---|---|---|---|
| **0. Groundwork and the three office PCs** | A read-only replay copy (decision 11); the first rule-id table; a packaged test app with the driver check; a first sample pack, with a typical-size sample student; benchmarks on the GTX 1650, RTX 5060 and RTX 5080 PCs: seconds per OCR page, model load time, graphics memory per page, TF32 against full FP32 on the 50-series; a one-page note: **can the GTX 1650 meet 5 minutes, and with which steps?** | On each of the three PCs, with the network cable out, the installed test app opens in under 3 s, reports the card and driver correctly, reads a sample page on the card and attempts no connection. Every stored finding maps to one rule id. The counts read back as FAIL 61 / REVIEW 65 / INCOMPLETE 15 / PASS 3. Section 3's *(est.)* times are replaced by measurements. | 5 |
| **1. Desk check on this PC** | The Home drop area; a student folder or loose PDFs (type from the name, or picked); the program from the parent folder, or picked; the live student report, urgent first, with the time-left bar; the student report and Excel; rules proven equal; today's reading by default; a reader kept loaded and swapped while idle; processor helpers for rendering and picture checks; this PC's fixed settings (3.0 GB cap; gives way to the bot, games and low memory); nothing half-read stored; optional portal CSV | **Gate A: 0 differing rows.** Rows are identical urgent-first and in today's order, and with 0 and 4 helpers. A real student folder dropped on the window shows the urgent results within 1 minute, then the report. Types are right for 30 generated file names, and an unmatched name asks for its type. A faked out-of-memory error on page 3 stores nothing, and the retry equals a clean run. The bot's lock appearing stops the reader within one page, and the check then finishes with the same rows. The window never freezes for more than 100 ms. The document team lead finds every FAIL of 5 students from the report alone. | 23.5 |
| **2. Identity, evidence, history, batches** | MRZ identity; the full portal import and the field section; the page viewer; history; re-checks of changed files only (page text and picture results cached by content); backups; the batch view under History | MRZ-against-portal disagreements are judged, with 0 OCR errors among check-digit-valid values. Boxes sit right from 50 to 400 % zoom. A student back with one replaced file: only that file is read. A desk check dropped during a batch starts after the batch's current file. | 14.5 |
| **3. Whole documents proven** | Gates B-D (Gate B also with TF32 off, for decision 6); your list of changed verdicts; the hand-checked set; full reading as the default on your word; the full Excel and PDF | Section 8's bar, items 1-4, is met, and you approve. | 4 + 2 nights + about 7 h of staff labelling |
| **4. Fits each card by itself** | Detection and the driver check; the full sample pack, calibration and the per-PC parity check (card and processor reader); profiles; the three tiers' settings; 2-3 parallel readers for the RTX 5080; the memory ladder with the one-page processor read; live adaptation | On this PC, each tier is simulated (a 2.6 GB cap with 1 reader; this PC; 3 readers) and gets section 3's settings. Rows are identical with 1, 2 and 3 readers. A forced memory error on one page walks the ladder to a marked processor read, or to "not finished". A dummy 5 GB load pauses the check, which resumes within 30 s after. A listed "game" ends the reader within one page. A simulated old driver stops with the update message. 20 students stay within ±20 % speed. | 9.5 |
| **5. One installer; the GTX 1650 and RTX 5080 PCs** | The installer; the app installed and calibrated on a GTX 1650 PC and the RTX 5080 PC; Gate B repeated on the GTX 1650 | A clean PC with no internet installs without administrator rights and passes its parity check. **The GTX 1650 PC returns the typical sample student in under 5 minutes** in 5 of 5 runs, with the reader kept loaded. Gate B on the GTX 1650: every differing row traced, and no changed verdict, or each one listed for you. The RTX 5080 gives identical rows with 1 and 3 readers. | 4.5 + about 2 h of runs |
| **6. Pilot at the desk** | A week of real walk-in checks on the main desk PC (decision 4); fixes | 0 half-read results, no unhandled crash, at least 95 % of checks under 5 minutes on that PC (the median and the slowest reported), and no student waits for a reader to load. You sign off. | 2 + 1 week |

**Total:** about **63 days**, plus the pilot week, two nights, about 2 hours of runs on the GTX 1650 PC, and about 7 hours of staff labelling. The desk check works on this PC after about **29 days** (phases 0-1).

- **Phase 0** removes the two biggest risks first: freezing PySide6, CUDA torch and EasyOCR into one installable program, and the GTX 1650's speed. It also proves that one build and the driver check work on all three PCs.
- **Phase 1** is what you asked for, on this PC: drop the student's folder and watch the report fill in. Gate A proves the copied rules match the bot before anyone relies on them. The settings are fixed by hand from the measurements already made.
- **Phase 2** adds identity without the portal, the page viewer, quick re-checks when a student returns with a replaced file, and batches.
- **Phase 3** shows you every verdict that reading whole documents and originals changes, with its cause, before it becomes the default.
- **Phase 4** makes the app set itself up on each of the three cards and give way by itself.
- **Phase 5** installs it on the other two kinds of PC and proves the 5-minute bar on the GTX 1650.
- **Phase 6** puts it at the desk.

## 8. How we prove it is right

| Test | How | Pass bar |
|---|---|---|
| **Gate A: logic parity** (phase 1, then on every engine change) | Replay today's `results.json` with today's reading, using the bot's cached text, on the same unchanged files. The date is pinned to each stored check, and the portal row comes from a same-day CSV. Students qualify when today's two fingerprints prove their files and record unchanged (`auto_verify.py:114-133`). The others are compared on the rules that read no portal value. | **0 differing rows** (document, file, verdict, detail) and the same verdict counts |
| **Gate B: reading parity** | Fresh reads with today's settings: 20 students on this PC, with TF32 on (as today) and off (decision 6); in phase 5 the same 20 on the GTX 1650 PC | Word-box reads join to exactly today's text. Every differing row is traced to a cause. |
| **Gate C: whole documents against today** | Full reading of everyone in one night | **Every** changed verdict has a cause: more pages, the original, one 200 dpi pass, rotated image files, no photo OCR, or an unknown or older file. Watch FAIL → PASS on the bank minimum, which takes the highest amount (`doc_verifier.py:687-691`), and on the birth date, which passes on any shared date (`:401-403`). |
| **Gate D: documents only against the portal** | The same cached text, with and without the CSV row | Differences appear only where section 4 says, and every FAIL difference is listed. |
| **Hand-checked set** | `PLAN.md` §6's 40 students: every PASS, samples of each common FAIL and both trial rules, INCOMPLETE, MASTER and EAP, shrunk and sideways files. Split 20/20. Labelled blind (violated / fine / cannot tell); a second person labels 10. | About 7 hours of labelling |
| **Parity per office PC** (each PC before its first verdict; again after a card, driver or app change) | The sample pack on that PC, with the readers it will use; the processor reader on 5 sample pages; on the GTX 1650, also Gate B | The sample students give the reference rows; at least 95 % of OCR pages give identical text; every difference is listed. On the GTX 1650, every differing row is traced, with no changed verdict unless you accept it. |
| **Desk speed** (estimated in phase 0, proven in phase 5, watched in the pilot) | The typical sample student (about 11 files, 41 pages, 32 OCR) dropped on the GTX 1650 PC, with the reader kept loaded, 5 runs; then every walk-in check in the pilot | **Under 5 minutes** from drop to report on the GTX 1650 in all 5 runs, with the urgent results in about 1 minute; in the pilot, at least 95 % of checks under 5 minutes |

**The bar before staff rely on it.** All of these must hold:
1. **Gate A:** 0 differing rows.
2. **Gates B and D** are met, and every difference is explained.
3. **You approve Gate C's list.** On the test half there is no new false FAIL, and no lost true FAIL unless you accept its cause. Every FAIL rule that fired at least 10 times has at most 5 % false FAILs.
4. **The document team lead** finds every FAIL of 5 students from the report alone.
5. **Every office PC** passes its parity check before it shows a verdict.
6. **The GTX 1650 PC** returns a typical whole file's report in under 5 minutes.
7. **The pilot week** at the desk is clean.

## 9. Risks

| Risk | Likelihood | What we do |
|---|---|---|
| Packaging CUDA torch fails, or the result is huge | high | The phase 0 spike first; a one-folder build; one installer of about 5 GB |
| **The GTX 1650 misses 5 minutes** for a typical whole file | medium: about 3-4.5 min *(est.)*, unmeasured | Phase 0 measures it first. Section 3's verdict-neutral steps. The estimate is shown at the drop. If it still misses: decision 10, or the RTX 5080 as the main desk PC (decision 4). |
| **4 GB runs out on the GTX 1650** (giant originals, or a browser or another program on the card) | medium | A 2.6 GB cap; a reader starts only at 3.2 GB free and names what holds the card; the memory ladder; never a smaller image or a shorter text; "Prefer No Sysmem Fallback" recommended there |
| **An old NVIDIA driver** on an office PC | medium | The driver check before any reading, naming the minimum. You update it; the app never does. |
| **TF32: the GTX 1650 reads slightly different text from the 50-series cards** | text: rare but certain; verdicts: unknown | The parity check per PC; Gate B repeated on the GTX 1650; the card and arithmetic on every report and in the cache key; decision 6 |
| **A desk check and the bot compete on the bot's PC** (the bot's check, its language model, games) | high on that PC | The app gives way to the bot's check and shows why; the 3.0 GB cap keeps room for the language model; the main desk PC elsewhere (decision 4); later one queue (decision 3) |
| Whole documents change verdicts, including FAIL → PASS on "highest amount" and "any shared date" rules | high | Gate C lists every move. Full reading becomes the default only on your word. |
| Windows hides per-program graphics memory, so a game is missed | high | The game list, Windows' GPU counters, the full-screen check |
| Weaker checks without portal data read as a clean PASS | medium | "Checks not run" is always shown, and the verdict reads "PASS (limited)". |
| The wrong student or type for loose PDFs | medium | The type from the name or picked; the student typed or picked; a warning on another student's number; the name on every header |
| A USB stick is pulled out mid-check | low | The check ends "not finished", with nothing stored; drop the folder again. |
| zbar's runtime is missing on a new PC | medium | The DLLs are shipped; the self-test decodes a QR before any check. |
| More copies of student data on office PCs | certain | A per-user folder, retention, Forget, no network, content-free logs |
| The app's verdicts differ from the bot's Telegram line | high | Every report states its rules version and reading; one announcement at the pilot |
| An unsigned installer is blocked by SmartScreen | medium | "Run anyway" on the first PCs; signing decided before phase 5 |

## 10. Decisions for the owner

**Decided on 5 Oct 2026**

| Question | Your answer | What the plan does |
|---|---|---|
| **Which PCs must it run on?** (was 4) | All office PCs. There are exactly three kinds: GTX 1650 4 GB (the lowest), RTX 5060 8 GB (the bot's PC) and RTX 5080 16 GB. Every PC has an NVIDIA card, none older than the GTX 16 series. | One GPU build for all; no processor-only mode; phases 0, 4 and 5 cover all three. Your message also said "or lower end version": decision 14. |
| **How many installers?** (was 5) | Follows from the answer above: every PC has a supported NVIDIA card. | **One installer**, about 5 GB installed. The "Standard" installer is dropped. |
| **How long may the student wait?** | A student walks in with a ready file, and staff check it at the desk, one student at a time, while the student waits. Target: the report in under 5 minutes on the weakest PC. Batches are secondary. | The desk check is the main flow; urgent results first; the 5-minute bar on the GTX 1650 (sections 3 and 8). |

**Still open**

| # | Question | Options | Recommended | Why |
|---|---|---|---|---|
| 1 | **Window technology** | (a) PySide6 desktop window<br/>(b) Tauri or Electron around Python<br/>(c) a local browser page (Gradio, Streamlit, FastAPI) | **(a)** | One language with the engine. Real folder paths on drop. No open port, one installer. |
| 2 | **Documents only, or portal-data import?** | (a) documents only<br/>(b) documents only by default, plus an optional portal CSV that staff save themselves<br/>(c) a portal file is required | **(b)** | It works on any PC with no portal or password. A file adds the 24-field comparison and more checks. |
| 3 | **Does the bot keep its own automatic check, or use the app's engine later?** | (a) the bot keeps its own check<br/>(b) the bot keeps it, unchanged, through the pilot (the app gives way to it); afterwards the bot calls the app's engine behind one setting, with a rollback, in one queue where a desk check goes first<br/>(c) turn the bot's check off now | **(b)** | One set of rules, and no two checkers on one card. Telegram and Supabase keep working. No bot change before the gates and the pilot. |
| 4 | **Which PC is the main desk PC?** | (a) the RTX 5080 PC<br/>(b) a GTX 1650 PC at the desk<br/>(c) the bot's RTX 5060 PC | **(a), or (b) if phase 0 shows the GTX 1650 meets 5 minutes.** Keep (c) for the bot. | On the bot's PC a desk check waits whenever the bot's own check runs (up to about 10 min), and shares the card with the language model and games. |
| 5 | **Keep a reader loaded, or load it for each check?** | (a) keep it loaded while the app is open (about 2-3 GB of card memory), released after 30 min idle<br/>(b) load it for each check (adds the load time, about 10-30 s *(est.)*, measured in phase 0) | **(a) on the GTX 1650 and RTX 5080 PCs; (b) on the bot's PC** | The student is waiting. On the bot's PC that memory belongs to the bot and its language model. |
| 6 | **Force full FP32 on every card?** | (a) no: the cards' defaults (TF32 on the 50-series, FP32 on the GTX 1650); each PC's parity check catches differences<br/>(b) yes: TF32 off everywhere, so all cards do the same arithmetic (closer, not guaranteed identical), at a small speed cost on the 50-series | **(b), if phase 0 shows the cost is small** | The same file should read the same at every desk. Gate B is run with TF32 off in phase 3 either way. |
| 7 | **Export formats** | (a) Excel only<br/>(b) Excel (today's layout plus "To fix" and "Findings") and PDF<br/>(c) (b) plus JSON | **(b)**, report only by default | Staff know the Excel, and a PDF prints and files well. Pictures and full text leave the app only when ticked. |
| 8 | Default reading | (a) whole documents and originals, after you approve Gate C<br/>(b) today's (6 pages of shrunk copies)<br/>(c) whole documents at once | **(a)** | It is what "check the documents" means, and you see every change first. |
| 9 | The card is busy during a check (a game, another program, or the bot's check) | (a) wait, showing what holds the card and since when<br/>(b) read the whole student on the processor<br/>(c) ask each time | **(a)** | On the desk PCs only a game or another program can hold the card, and staff can close it; the bot's check ends within about 10 min. (b) would take 10-25 min *(est.)*. Please name the game's program file. |
| 10 | Speed-ups that change the text (GPU batch mode, a smaller image size, half precision), **only if the GTX 1650 misses 5 minutes** after section 3's steps | (a) never: use the RTX 5080 as the desk PC instead<br/>(b) each one only after the 40-student set shows 0 changed verdicts, on all cards alike<br/>(c) now | **(b)** | Batch mode takes a different EasyOCR code path. On all cards alike, a file still reads the same at every desk. |
| 11 | May the developer copy the bot's `results.json`, text cache and passport-issue cache, read-only, into a sandbox on this PC; may staff save one portal CSV that day; and may Gate B's 20 student folders be copied to the GTX 1650 PC for one day? | yes / no | **yes**, deleted after phase 3 (the GTX 1650 copy the same day) | Gates A and B need them. The copies never leave the office PCs. |
| 12 | How long is data kept on each PC? | 6 months / 1 year / until deleted | **Results 1 year, page text 30 days**, 14 daily backups, "Forget this student" | It covers an application cycle, and text copies do not pile up. |
| 13 | Who labels the 40-student set (about 7 hours)? | the document team lead / you / both | **The document team lead, a second person for 10 students, and you settling disagreements** | Without labels, no one knows whether a FAIL is true. |
| 14 | Is any office card **below a GTX 1650**? (Your message said "GTX 1650 or lower end version"; the 5 Oct notes say the GTX 1650 is the lowest.) | (a) no: anything older than the GTX 16 series is not supported, and the app says so<br/>(b) yes, a GTX 16-series or newer card (for example a GTX 1630): the same installer, its own measurement, probably over 5 minutes<br/>(c) yes, older than the GTX 16 series: a second build on an older CUDA, its own parity gate, about 3-4 more days | **(a)**; please confirm | The build covers the GTX 16 series and newer *(measured)*. (b) needs no new work; (c) brings back two installers. |

## 11. Alternatives considered

- **The background service feeding the bot** (`PLAN.md`). It has no screens, and it is not what you asked for.
- **Fix the check inside the bot.** OCR stays in the 15-minute sync, and there is no app.
- **A local browser page.** Browsers hide folder paths, so the program folder, the originals and the marker cannot be found. Folders would be uploaded into copies, and a port would open.
- **Tauri or Electron.** Two stacks and two installer pipelines, and their drawing uses the same graphics card.
- **Tkinter.** No proper page viewer or large tables.
- **A new OCR engine now** (PaddleOCR, docTR, Tesseract). The rules are tuned to EasyOCR's text.
- **A processor-only mode and a "Standard" installer.** Dropped on 5 Oct: every office PC has a supported NVIDIA card. The processor reads only a single page after repeated memory errors.
- **Reading page content to classify or split files.** Not needed: every folder follows the bot's naming. A loose PDF with an unknown name gets a one-click type.
- **Parallel readers on the GTX 1650 or the RTX 5060.** 4 GB holds one reader; on the RTX 5060 the rest of the card belongs to the bot.
- **ONNX, DirectML or OpenVINO for AMD and Intel graphics.** Not needed: every office PC has an NVIDIA card.
- **Cloud OCR or a vision language model.** Staff declined the cloud, and a model that "corrects" a digit is the failure a checker must not have.
- **Reuse the bot's text cache.** It can hold text cut short by memory errors. It is used only inside Gate A.

## Appendix A: where the drafts disagreed, and the decision

- **Processes.** The window runs the job controller and the monitor; reader processes (one, or 2-3 on the RTX 5080), fresh every 5 students, with the helpers beside them. *Why:* the UI draft's worker plus the hardware draft's helpers, with no extra supervisor to keep alive.
- **Reading.** The engine draft's same-signature wrappers, with the hardware draft's reader proxy as the lowest layer. *Why:* a proxy alone cannot read whole documents, originals or word boxes.
- **Half-read protection.** Both the abort (hardware) and the taint (engine). *Why:* it also catches errors swallowed inside picture checks.
- **Cache key.** The content hash in SQLite (UI and engine), not today's name, size and time. *Why:* identical files are reused, and changed ones are always re-read.
- **Date.** Set per student, so the hardware draft's midnight recycle is dropped. *Why:* the same effect, more simply.
- **Identity.** The folder name first for name and number; the MRZ for date of birth, expiry and sex (the engine draft put the MRZ first). *Why:* the folder holds the portal's own values, so the rules behave as today.
- **Skipped checks.** A "Checks not run" list, not a new SKIPPED level (UI draft). *Why:* today's levels and verdicts stay untouched.
- **Evidence boxes.** Stored as fractions of the page (UI), not 200 dpi pixels (engine). *Why:* they draw right at any zoom.
- **Installers.** Two (hardware), not one (UI), in the first version of this plan. *Superseded on 5 Oct:* one, because every office PC has a supported NVIDIA card.
- **Install location.** Per user, not Program Files (UI). *Why:* staff PCs may lack administrator rights.
- **Sample pages.** One pack for the self-test, the parity check, calibration and the 5-minute test. *Why:* one thing to build.
- **Rules version.** One name, "rules v1". *Why:* the drafts used three.
- **Size.** The engine at 22 days (engine draft), not 10 (UI draft), with the overlaps removed. *Why:* about 60 days in all, not about 70; about 63 after the 5 Oct revision.

## Appendix B: corrections after checking the code

- **The UI draft's "bot's portal snapshot".** No code writes one (PLAN's D2 was never built). Dropped; the import is a staff-saved export.
- **The hardware draft's picture checks.** Patching `PC._pages` does not cover `page_codes`, which renders its own pages (`page_checks.py:340-350`). Giant originals are therefore routed to the copy beforehand.
- **The hardware draft's reading.** Keeping `read_document`/`read_pages` unchanged cannot read whole documents (6 pages, `auto_verify.py:191`), originals or word boxes.
- **The engine draft's MRZ rule.** `_line2_at` returns a repaired passport number without saying it was repaired (`ocr_validator.py:276, 286`). The engine therefore re-tests the check digit on the raw characters itself.
- **The 3.0 GB cap (PLAN 4.4, UI draft).** It protects the app, not the bot. The bot's uncapped check (3.9 GB peak) starts without looking at the app, so the app yields when the bot's lock appears.
- **Urgent-first order (5 Oct revision).** The rule functions share state across documents (`doc_verifier.py:393, 451, 720, 757, 820`). Reading files in a new order is safe; calling the rules in a new order is not. The engine therefore keeps today's rule order (section 4).
- **Still true.** Everything else in `PLAN.md` sections 1-2 holds: 6 pages (`auto_verify.py:191`), 4 pages (`page_checks.py:20`), a failed first read stored as final (`doc_verifier.py:1066-1071`), retries swallowing errors (`:79-82`), the KLP default (`:1131`).

## Appendix C: changes in this revision (5 Oct 2026, the owner's desk-check facts)

- **Summary:** rewritten for the walk-in desk check, the three office cards, one installer, the 5-minute target and how it is met, and the new timeline (29 days to a desk check on this PC, 63 in all).
- **Section 1:** the two inputs as you described them (a folder in the bot's layout, or one document per PDF); the program from the parent folder or picked; types from file names, picked when unmatched; no content-based classification; documents-only by default with the optional portal CSV.
- **Section 2:** Home is now one drop area plus recent checks; the new live student report (urgent first, time-left bar with the card name) is the main screen; "Add documents", "Add student folders" and "Progress" are replaced by the loose-PDF panel and the batch view under History; the processor lines are gone from Settings.
- **Section 3:** the three example PCs are replaced by the three real tiers, each with its memory cap, readers, helpers, kept-loaded reader, recycling, time for a typical whole file and memory ladder.
- **Section 3:** added the driver check (R570 or later), the "not supported" message, the TF32 note, the 5-minute steps for the GTX 1650, and how a desk check shares the bot's card.
- **Section 3:** removed the processor-only PC, the processor parity gate and the AMD and Intel spike; the processor now reads only a single page, after memory errors, gated by each PC's parity check.
- **Section 4:** added "urgent first, without changing a row": files may be read in any order, but the rules run in today's order; the program comes from the parent folder.
- **Section 5:** the header shows the card and its arithmetic; "name not recognised" no longer guesses a type from content; the time line shows the helpers working alongside the card.
- **Section 6:** one installer for every office PC, with the driver minimum; the "Standard" installer is dropped; the reading build is named with the cards it covers.
- **Section 7:** phase 0 now benchmarks all three PCs and answers the 5-minute question; phase 1 is the desk check with the live report on this PC; tuning comes in phase 4, the GTX 1650 and RTX 5080 PCs in phase 5, and the pilot at the desk last; the processor gate work is removed; days recomputed (63, from 60).
- **Section 8:** added the 5-minute bar on the GTX 1650, the parity check per office PC, and Gate B with TF32 off and on the GTX 1650; the processor-gate bar is removed.
- **Section 9:** added the GTX 1650 missing 5 minutes, 4 GB running out, an old driver, TF32 differences, the desk check and the bot competing, and a pulled USB stick; removed "processor-only PCs are too slow".
- **Section 10:** the PCs, installers and wait are marked decided; added the main desk PC (4), keeping a reader loaded (5), full FP32 (6) and a card below the GTX 1650 (14); the text-changing speed-ups (10) apply only if the GTX 1650 misses 5 minutes; the busy-card decision (9) no longer offers the processor as the default; the rest are renumbered.
- **Section 11:** added the processor-only mode, the "Standard" installer, content-based classification and parallel readers on the smaller cards as rejected options.
- **Appendices A and B:** the two-installer line is marked superseded, the size line updated, and the rule-order finding added.
