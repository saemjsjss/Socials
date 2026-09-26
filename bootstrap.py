"""
Cold start: bring a fresh PC from nothing to a fully checked system.

Run this once on a new machine, or after clearing the progress sheets, to rebuild
everything from the portal in the right order.  Each phase is resumable — stop it and
run it again and it picks up where it left off, because every phase records what it has
already done.

  python bootstrap.py               # run every phase in order
  python bootstrap.py --from 3      # carry on from phase 3
  python bootstrap.py --only 2      # just one phase
  python bootstrap.py --plan        # show what would run, do nothing

Phases
  1  Progress sheets     every program + intake sheet, built from the portal
  2  Passport issue      read the one field the CSV export does not carry
  3  Passport audit      each student's passport scan against their portal record
  4  Documents           download the document-verified students' files
  5  Verification        OCR every document, then compare the sheet's fields against them
  6  Handover            start the bot; the 15-minute cycle keeps it current from here

Portal access is read-only throughout: GETs only, plus the login itself.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import src  # noqa: F401  — sets the CA bundle before any HTTPS call

BOT = Path(__file__).resolve().parent
DOCS = Path(r"E:\VERIFIED STUDENT DOCUMENTS")
PY = sys.executable


def run(label: str, args: list[str], why: str) -> bool:
    print(f"\n{'=' * 74}\n{label}\n{why}\n{'=' * 74}", flush=True)
    t0 = time.time()
    proc = subprocess.run([PY, *args], cwd=BOT)
    ok = proc.returncode == 0
    print(f"\n-> {'done' if ok else 'FAILED (exit %d)' % proc.returncode} in {time.time()-t0:.0f}s",
          flush=True)
    return ok


def phase_1() -> bool:
    return run("PHASE 1 of 6 — progress sheets",
               ["-m", "src.sheets.progress_builder", "--all"],
               "Reads every direct student from the portal and builds one sheet per\n"
               "program and intake in Drive. Main tabs only — university sub-tabs are\n"
               "never touched. Students with no intake on the portal are listed at the\n"
               "end; they cannot be placed until an intake is set.")


def phase_1b() -> bool:
    return run("PHASE 2 of 6 — passport issue dates",
               ["-m", "src.sheets.passport_issue", "--refresh"],
               "The portal shows the passport issue date only on a student's edit page,\n"
               "never in the CSV export, so it is read separately and cached. A fresh\n"
               "machine has no cache, and without this the field check reports every\n"
               "issue date as unreadable. About 290 read-only page fetches; after this\n"
               "the bot refreshes it daily at 08:30 on its own.")


def phase_2() -> bool:
    ok = True
    for program in ("KLP", "EAP", "Bachelor's Degree", "Master's Degree"):
        ok &= run(f"PHASE 3 of 6 — passport audit: {program}",
                  ["audit_program.py", program],
                  "Downloads each student's passport scan only (not the full document\n"
                  "set) and cross-checks name, passport number, date of birth, expiry\n"
                  "and parents against what the portal holds, using the MRZ check\n"
                  "digits. Cheap, and it catches typing mistakes before anything else.")
    return ok


def phase_3() -> bool:
    return run("PHASE 4 of 6 — download verified students' documents",
               ["-m", "src.sheets.verified_docs", "--local", str(DOCS)],
               f"Downloads the full document set for every student the portal marks\n"
               f"document-verified, into {DOCS}\\<PROGRAM>\\<NAME (PASSPORT)>\\.\n"
               "Files over 2 MB are shrunk, with the original kept. Students already\n"
               "downloaded are skipped, so this is safe to re-run.")


def phase_4() -> bool:
    return run("PHASE 5 of 6 — verify every document",
               ["-m", "src.verify.auto_verify", "--recheck", "--budget", "0"],
               "Reads every document (PDF text layer first, OCR for scans), checks it\n"
               "against the programme guidelines, then compares the portal's fields\n"
               "against what the documents actually say. Writes DOCUMENT CHECK.xlsx\n"
               "and FIELD CHECK.xlsx. This is the slow one — allow a few hours the\n"
               "first time, because nothing is cached yet.")


def phase_5() -> bool:
    print(f"\n{'=' * 74}\nPHASE 6 of 6 — hand over to the bot\n{'=' * 74}")
    print("""
From here the bot keeps everything current by itself:

    wscript.exe "E:\\BOT\\start_background.vbs"

Then, every 15 minutes, it rebuilds only the sheets whose students changed,
downloads anyone newly verified, checks those documents, and messages you on
Telegram when something changed. One student at a time, one sheet at a time.

Make it survive restarts:

    .\\install_autostart.bat     starts the bot when you log in
    .\\install_watchdog.bat      restarts it within 5 minutes if it crashes
""")
    return True


PHASES = {1: phase_1, 2: phase_1b, 3: phase_2, 4: phase_3, 5: phase_4, 6: phase_5}


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild the whole system from the portal.")
    ap.add_argument("--from", dest="start", type=int, default=1, help="start at this phase")
    ap.add_argument("--only", type=int, help="run just this phase")
    ap.add_argument("--plan", action="store_true", help="show the phases and stop")
    args = ap.parse_args()

    wanted = [args.only] if args.only else [n for n in sorted(PHASES) if n >= args.start]

    if args.plan:
        print(__doc__)
        print("would run phases:", ", ".join(str(n) for n in wanted))
        return

    print(f"Cold start — phases {', '.join(str(n) for n in wanted)}")
    print("Portal access is read-only. Nothing is ever written to hangeul.com.bd.")
    t0 = time.time()
    for n in wanted:
        if not PHASES[n]():
            print(f"\nStopped at phase {n}. Fix the problem above, then carry on with:"
                  f"\n    python bootstrap.py --from {n}")
            raise SystemExit(1)
    print(f"\n{'=' * 74}\nAll phases finished in {(time.time()-t0)/60:.0f} minutes.\n{'=' * 74}")


if __name__ == "__main__":
    main()
