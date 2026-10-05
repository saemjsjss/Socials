# OCR document checker: plans

Plans, written 5 Oct 2026, for taking the OCR whole-document check and its report out of the bot and into a program of its own. **Nothing here has been built.** Every plan waits on the owner's decisions.

| File | What it is | Status |
|---|---|---|
| [APP_PLAN.md](APP_PLAN.md) | "Hangeul Document Checker": a Windows desktop app. Staff drop a student folder or PDFs on the window; it reads every page offline, tunes itself to the PC's GPU and CPU, and shows only the document-check report. | **Current plan**, awaiting approval |
| [PLAN.md](PLAN.md) | The first design: a background service on the bot's PC that feeds the bot. | Superseded by APP_PLAN.md as a design. Its sections 1-2 (how today's check works and its problems, checked against the code) still hold. |
| [drafts/](drafts/) | The six drafts the two plans were merged from: `draft_reuse`, `draft_accuracy`, `draft_operations` (PLAN.md) and `app_draft_app_ui`, `app_draft_hardware`, `app_draft_engine` (APP_PLAN.md). | Working material |

`path:line` references in these files point at bot commit `8317741` on the office PC, which is `e1a3638` in this repository ([../COMMIT_ID_MAP.md](../COMMIT_ID_MAP.md)). Names, numbers and dates in the examples are placeholders.
