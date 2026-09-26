# Workstation build — Hangeul document verification

**For:** Saemur Rahman, Hangeul Korean Language & Visa, Dhaka
**Purpose:** replace the i3-14100 / RTX 5060 machine currently running the bot, the
progress-sheet sync and the OCR document verification.
**Date:** 26 September 2026. Prices are Dhaka ballpark — confirm at Star Tech or Ryans.

---

## What the current machine actually struggles with

Measured on the existing PC, not guessed:

| Observation | Meaning |
|---|---|
| OCR runs ~50 s per student cold, ~6 s cached | Most of the cold time is **CPU** page rasterising, not GPU inference |
| Full re-check of 154 students ≈ 90 minutes | 4 cores is the ceiling |
| `CUDA out of memory — 7.93 GiB total` when a second OCR process starts | 8 GB VRAM is full with EasyOCR (~1.5 GB) + qwen2.5:7b (~4.7 GB) |
| System drive: 9 GB free of 119 GB | `.ollama` 4.4 GB + Python/torch 5.4 GB both live on C: |
| One physical disk — Colorful CN600 512 GB | Windows, the bot and every student document on a single budget SSD |
| RAM running at 2133 MT/s | XMP never enabled — rated speed unused |

**Conclusion:** the CPU and the disk are the real limits. The GPU is barely working.

---

## The build

| Part | Spec | Why this one |
|---|---|---|
| **CPU** | Intel Core i7-14700 (20 cores: 8P + 12E), tray | ~5× the current multicore. OCR backlog 90 min → ~25 min |
| **CPU cooler** | DeepCool AK620 Digital or Thermalright Peerless Assassin 120 SE | Tray CPU ships bare; the 14700 turbos to 219 W |
| **Motherboard** | MSI MAG B760 Tomahawk WiFi DDR5 (or Gigabyte B760 AORUS Elite AX) | Real power delivery. The current PRO B760M-E would throttle a 14700. The 14700 is non-K, so Z790 buys nothing |
| **RAM** | 32 GB (2×16) DDR5-6000 CL30 | Feeds the cores during page rasterising — the actual bottleneck |
| **GPU** | Colorful iGame RTX 5080 Neptune OC 16 GB | The 16 GB is what matters: it fits a document-understanding vision model beside the language model |
| **System drive** | 1 TB Gen4 NVMe — Samsung 990 Pro or WD SN850X | 200 GB+ free, ends the 9 GB problem |
| **Data drive** | Carry over the existing Colorful CN600 512 GB | Two physical disks — a drive failure no longer costs the whole document archive |
| **PSU** | 850 W 80+ Gold, ATX 3.1, native 12V-2x6 — Corsair RM850x or MSI MAG A850GL | The 5080 alone draws ~360 W with hard transient spikes |
| **Case** | Lian Li Lancool 216, Montech King 95, or Corsair 4000D Airflow | Must fit the Neptune's radiator **and** the CPU cooler |

---

## Three things that catch people out

**1. The existing 32 GB DDR4 will not transfer.** Corsair DDR4 does not fit a DDR5
board. Either budget for new DDR5, or choose a DDR4 board and reuse the sticks — that
saves roughly 15,000 BDT at the cost of building a 2026 machine on last generation's
memory. DDR5 is the better choice here because the workload is memory-bandwidth hungry
during page rendering.

**2. Confirm the Neptune's radiator size before choosing the case.** The iGame Neptune
is liquid-cooled with its own AIO — 240 mm on some SKUs, 360 mm on others. Ask the shop.
Getting this wrong is the most common way this exact build fails at assembly, because
the case then cannot hold both the GPU radiator and the CPU tower cooler.

**3. Do not reuse the current PSU.** A system built around an i3 almost certainly has a
450–550 W unit. A 5080 needs 850 W and an ATX 3.1 rail that tolerates transient spikes.

---

## Actual Star Tech prices — checked 26 September 2026

Every line below was in stock on startech.com.bd at the time of checking.

| Item | Product at Star Tech | BDT |
|---|---|---|
| CPU | Intel Core i7-14700 (20 cores) | **39,500** |
| CPU cooler | DeepCool AK620 Dual-Tower | **7,000** |
| Motherboard | MSI PRO Z790-P WIFI DDR5 ATX | **31,900** |
| RAM | G.Skill Trident Z5 Neo RGB 32 GB DDR5-6000 CL36 | **65,000** |
| GPU | Colorful iGame RTX 5080 Neptune OC 16 GB-V | **259,000** |
| System drive | Team MP44 1 TB Gen4 NVMe (7200/6200 MB/s) | **27,000** |
| PSU | DeepCool PN850D 850 W Gold ATX12V 3.1 | **12,500** |
| Case | DeepCool CH510 Mid-Tower ATX | **8,200** |
| **Total** | | **450,100** |

### Corrections to the earlier estimate

- **RAM was badly underestimated.** 32 GB DDR5-6000 costs **65,000**, not the
  14,000–20,000 quoted above. DDR5 prices have risen sharply. This single line is most of
  the difference between the 308–389k estimate and the real 450k.
- **The CPU is cheaper than expected** — 39,500, down from 45,000.
- **The Neptune is 259,000**, discounted from 310,000.
- **The B760 Tomahawk is out of stock** in both DDR5 and DDR4, as are the TUF B760-PLUS,
  ROG STRIX B760-A and Gigabyte B760 AORUS ELITE AX. The MSI PRO Z790-P WIFI at 31,900 is
  in stock and is the better board for a 14700 anyway — stronger power delivery.

### Alternatives worth knowing

- **Cheaper 5080s, all air-cooled:** Manli Nebula 210,000 · MSI VENTUS 3X OC 245,000 ·
  PNY OC 245,000. An air-cooled card removes the radiator-fitting problem below and saves
  up to 49,000.
- **Cheaper board:** MSI B760 GAMING PLUS WIFI at 22,500 (in stock) saves 9,400, with
  weaker power delivery under sustained all-core load.
- **Modular PSU:** OCPC ENERGIA GD850M 850 W Gold fully modular, 12,000 — slightly cheaper
  than the DeepCool and easier to cable around a large GPU.

---

## AMD alternative (if the ASUS ROG STRIX X870-F is the board you want)

**The ROG STRIX X870-F GAMING is an AMD board** — X870 chipset, **AM5 socket**, for Ryzen
7000/8000/9000. It physically cannot take the Intel i7-14700 (LGA1700). Choosing it means
changing the CPU too. Ryans: **69,200৳** (from 74,870), 3-year replacement, 1-day delivery.

Everything else carries over unchanged: the AK620 cooler ships with AM5 mounting, and the
DDR5 RAM, GPU, SSD, PSU and case are all platform-agnostic.

| Build | CPU | Board | Total |
|---|---|---|---|
| **Intel (as planned)** | i7-14700 — 20 cores, 39,500 | MSI PRO Z790-P WIFI, 31,900 | **450,100** |
| AMD, ROG STRIX + 9900X | Ryzen 9 9900X — 12C/24T, 42,900 | ROG STRIX X870-F, 69,200 | **490,800** |
| AMD, ROG STRIX + 9950X | Ryzen 9 9950X — 16C/32T, 53,500 | ROG STRIX X870-F, 69,200 | **501,400** |
| **AMD, value board + 9950X** | Ryzen 9 9950X, 53,500 | ASRock X870 Pro RS WiFi, 35,000 | **467,200** |
| **CHOSEN — 9950X3D + ROG STRIX** | Ryzen 9 9950X3D — 16C/32T, 145 MB cache, 77,500 | ROG STRIX X870-F, 69,200 | **525,400** |
| Same CPU, value board | Ryzen 9 9950X3D, 77,500 | ASRock X870 Pro RS WiFi, 35,000 | **491,200** |

### On the 9950X3D

Ryans: **77,500৳** (from 83,550), OEM/tray, **no cooler included** — the AK620 covers
that. 16 cores / 32 threads, AM5, officially supports the X870 chipset. Memory is rated
DDR5-5600; the DDR5-6000 kit will run at full speed through EXPO.

The 3D V-Cache (145 MB total) is a **gaming** feature: it helps workloads whose working
set fits in cache. OCR streams large page bitmaps through the CPU and does not benefit,
so the 9950X3D and the plain 9950X land within a few percent of each other here — a
**24,000৳ premium for no measurable gain on this workload**. It is the right chip if the
machine will also be used for gaming; it is not the value choice for verification alone.

### On the board itself

The ROG STRIX costs **34,200৳ more** than an ASRock X870 Pro RS WiFi with the same X870
chipset, same AM5 socket, same DDR5 support and the same Wi-Fi 7. The premium buys RGB,
better audio, and VRM headroom for overclocking — none of which this workload uses.
Cheaper X870 boards in stock at Star Tech:

- ASRock X870 Pro RS WiFi — **35,000**
- ASRock X870 Steel Legend WiFi — **39,999**
- ASUS PRIME X870-P-CSM — **41,500**
- ASRock X870 RIPTIDE WiFi — **42,900**

### Which CPU is actually better for OCR

The Ryzen 9 9950X (16 cores / 32 threads, Zen 5) is **faster than the i7-14700** for
sustained multithreaded work — which is exactly what page rasterising during OCR is. The
9900X (12C/24T) is roughly level with the 14700. So the AMD path does buy real
performance; it is not only a board swap.

**If you want this platform, the sensible build is Ryzen 9 9950X + ASRock X870 Pro RS at
467,200৳** — faster than the Intel plan for 17,100৳ more. Paying 69,200 for the ROG STRIX
adds 34,200 for features a verification workstation will not use.

### One thing to confirm at the counter

**Ask the shop whether the CH510 fits the Neptune's radiator alongside the AK620.** The
Neptune is liquid-cooled with its own AIO, and I could not confirm from the product page
whether it is 240 mm or 360 mm, nor the CH510's radiator mounts. If the answer is no,
either pick a larger case or take one of the air-cooled 5080s above.

---

## What the upgrade actually unlocks

Not speed — capability:

- **Document-understanding models.** A local vision-language model (Qwen2.5-VL) reads a
  passport *as a document* rather than as disconnected characters. This is the fix for
  the whole class of OCR misreads currently corrected by hand — `A00990007` read as
  `AG0770008`, dates read as year 7028, NID numbers split across spaces. Needs 12–16 GB
  VRAM; impossible on 8 GB.
- **A larger local LLM.** qwen2.5:14b instead of 7b for briefings and emails, loaded
  *alongside* the document model rather than swapping them in and out.
- **Whisper** — transcribe and summarise consultation calls.
- **Search across every document** — a local embedding model answers "which students have
  a garments trade licence" from the files themselves.
- **Parallel checking** — 20 cores means several students checked at once instead of one
  at a time.

---

## Migration plan

1. **Keep the old PC.** Give it the Telegram bot and the 15-minute portal sync — light
   work it handles fine. Put OCR, the models and the verification passes on the new
   machine. A rebuild or crash on either box then stops only half the system.
2. Copy `E:\BOT` and `E:\VERIFIED STUDENT DOCUMENTS` to the new machine's data drive.
3. Install Python 3.11, then `pip install easyocr pymupdf opencv-python-headless pyzbar
   pillow openpyxl httpx beautifulsoup4`, and torch from the CUDA index matching the card.
4. Edit the hardcoded paths in `src/verify/doc_verifier.py` and `src/verify/auto_verify.py`
   if the drive letters change.
5. Set `OLLAMA_MODELS` to the data drive so models never fill the system drive again.
6. Enable **XMP / A-XMP** in BIOS on the first boot — memory runs at JEDEC default
   otherwise, which is what is happening on the current machine today.

---

## Free wins on the current machine, whether or not you buy

- Enable **A-XMP** in BIOS: RAM goes from 2133 MT/s to its rated 3200+. Two minutes.
- Set `OLLAMA_MODELS=E:\ollama` and clear `AppData\Local\Temp`: about 6 GB back on C:.
- Run `install_watchdog.bat` so the bot restarts itself after a crash.
