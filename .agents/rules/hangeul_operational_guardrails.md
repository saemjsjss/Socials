---
trigger: always_on
description: Critical operational guardrails, read-only invariants, and metric parsing guidelines for Hangeul Admin Bot.
---

# Hangeul Operational Guardrails

## 1. Absolute Read-Only Constraint
- NEVER perform POST, PUT, DELETE, or automated edit requests to `student_edit.php` or any other portal mutation endpoints on `hangeul.com.bd`.
- Only perform GET requests for scraping, auditing, cross-checking, and report generation.
- If data entry errors or discrepancies are discovered, report them clearly to the user in structured audit tables; never auto-correct them without explicit permission.

## 2. Metric Decoupling Invariant
- **Pending Payments**: Only count records where `students.php?status=pending` is indicated. (Currently 0).
- **Window Applications Under Review**: Only count university window applications under review in `window_applications.php` or dashboard metrics. (Currently 2).
- NEVER sum these two distinct metrics into a single "pending" label. Always report them separately.

## 3. Verified Student & Document Audit Standards
- When querying verified students, always capture:
  1. Student Name and Program.
  2. Amount and Payment Method (bKash, Bank Transfer, Cash).
  3. Counselor Name and Verification Timestamp.
  4. Document Status: Cross-check against uploaded passport scans and MRZ machine-readable lines.
  5. Verdict Classification: `100% Match`, `Typo / Discrepancy`, `Pending Document` (e.g. marked "WILL APPLY"), or `Invalid Document`.

## 4. Calendar & Deadlines
- When querying events or dates, parse both active items for the day (with progress and days left) and the upcoming 45-day timeline from `calendar.php`.

## 5. Live Auditing Invariant (Zero Stored / Stale Data Reliance)
- Whenever performing an audit, crosscheck, verification, or document inspection, ALWAYS query live data directly from the active `hangeul.com.bd` portal via GET requests (`students.php`, `student_edit.php`, `view_doc.php`).
- NEVER answer or generate audit reports based on static in-memory registries, hardcoded dictionaries, or cached historical records.
- Always inspect the live portal fields, download/inspect the live uploaded document file, perform dynamic OCR + MRZ checksum validation in real time, and report the true live findings.
- If discrepancies or changes occur on the live portal (e.g. counselor edits or document re-uploads), the audit must reflect the exact real-time state.

## 6. Scope Boundary Invariant: `students.php` (All Students) Only — Exclude `signed_students.php`
- Audits, cross-checks, and document validations must ONLY be conducted on active students from `students.php` ("All Students").
- NEVER audit, cross-check, or scrape records from `signed_students.php` ("Signed Students"). Signed students are finalized/contracted agreements and are strictly out of scope for document audits and cross-checks.
- All bot commands, scheduled watchers, and agent queries (e.g. `/crosscheck`, `/passports`, `/verified`, `/admitted`) must exclusively source from `students.php` (and its profile endpoint `student_edit.php?id=...`).

## 7. No AI or Actions on the Portal
- NEVER run any AI feature on `hangeul.com.bd` (e.g. `ask_ai.php`, `ai_training.php`, `team_assistant.php`) and never press any button or submit any form there (other than the login itself).
- Portal access is limited to read-only GETs that fetch data: the `students.php?export=csv` export, student list pages, and `download_docs.php` ZIP downloads.
- All analysis — document cross-checks, OCR, MRZ checks, reports — runs ONLY on local copies (e.g. `E:\VERIFIED STUDENT DOCUMENTS`), never on the portal.
