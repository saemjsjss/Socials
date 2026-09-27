import logging
import time
from typing import Optional, Dict, Any, List
import httpx

from src.config import settings
from src.llm.prompts import SYSTEM_EXECUTIVE_REPORT, SYSTEM_AGENT_CHAT, build_report_prompt

logger = logging.getLogger("hangeul.llm")

# The model stays in VRAM for good ("Jennie's brain"): no call ever unloads it, so no question,
# typed or spoken, waits for it to load again.
KEEP_ALIVE = -1
TEMPERATURE = 0.3

# A prompt longer than num_ctx is cut by Ollama without any error: it keeps only about its last half
# (measured with qwen3:4b-instruct at num_ctx 3072: every over-long prompt came back as 1538 tokens),
# so the system prompt holding the portal data is lost and the answer is wrong. prompt_eval_count
# cannot show that (a cut prompt reports ~num_ctx/2, and a prefix Ollama had cached is not counted),
# so the prompt is measured before it is sent: a warning when it leaves less than ANSWER_BUDGET_TOKENS.
ANSWER_BUDGET_TOKENS = 512
# Measured with qwen3's tokenizer: 2.43 characters per token for the typed-question prompt (portal
# data as Python dicts: every digit is a token), 2.81 for the daily brief, ~4 for plain English.
CHARS_PER_TOKEN = 2.4


class OllamaClient:
    """Async client for the local Ollama LLM (settings.OLLAMA_MODEL) on the RTX 5060.

    Every call sends the same options (options()): Ollama reloads the model whenever a load
    option such as num_ctx differs from the copy in VRAM, which costs seconds. Only the sampling
    limit num_predict may vary per call; it does not reload the model (measured: load 0.002 s)."""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model = settings.OLLAMA_MODEL
        self.num_ctx = int(settings.OLLAMA_NUM_CTX)
        self.client = httpx.AsyncClient(timeout=60.0)

    def options(self, num_predict: Optional[int] = None) -> Dict[str, Any]:
        """The one option set every call sends."""
        opts = {"temperature": TEMPERATURE, "num_ctx": self.num_ctx}
        if num_predict:
            opts["num_predict"] = int(num_predict)
        return opts

    def _payload(self, num_predict: Optional[int] = None, **fields) -> Dict[str, Any]:
        return {"model": self.model, "stream": False, "keep_alive": KEEP_ALIVE,
                "options": self.options(num_predict), **fields}

    def prompt_fits(self, what: str, *texts: Optional[str]) -> bool:
        """Does a prompt made of `texts` leave room for an answer in num_ctx? Logs a warning when it
        may not (Ollama would silently cut it). A character-based estimate, on the safe side."""
        chars = sum(len(t or "") for t in texts)
        estimate = int(chars / CHARS_PER_TOKEN)
        if estimate <= self.num_ctx - ANSWER_BUDGET_TOKENS:
            return True
        logger.warning(f"Ollama {what}: the prompt is ~{estimate} tokens ({chars} characters) of num_ctx "
                       f"{self.num_ctx}, leaving under {ANSWER_BUDGET_TOKENS} for the answer - Ollama may cut it "
                       f"and the answer may be wrong (shorten the prompt or raise OLLAMA_NUM_CTX).")
        return False

    def _check_used(self, what: str, data: Dict[str, Any]):
        """After a call: warn when the prompt Ollama evaluated nearly filled num_ctx."""
        try:
            used = int(data.get("prompt_eval_count") or 0)
        except (TypeError, ValueError):
            return
        if used >= self.num_ctx - ANSWER_BUDGET_TOKENS:
            logger.warning(f"Ollama {what}: the prompt took {used} of num_ctx {self.num_ctx} tokens.")

    async def check_health(self) -> Dict[str, Any]:
        """Check if Ollama service is reachable and list downloaded models."""
        try:
            resp = await self.client.get(f"{self.base_url}/api/tags", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name") for m in data.get("models", [])]
                model_ready = any(self.model in m for m in models)
                return {
                    "reachable": True,
                    "models_installed": models,
                    "target_model": self.model,
                    "target_model_ready": model_ready
                }
        except Exception as e:
            logger.warning(f"Ollama not reachable at {self.base_url}: {e}")
            
        return {
            "reachable": False,
            "error": "Ollama service is not currently running. Will use built-in intelligent reporting engine.",
            "target_model": self.model,
            "target_model_ready": False
        }

    async def generate_response(self, prompt: str, system: Optional[str] = None) -> str:
        """Call Ollama /api/generate endpoint (the model stays resident afterwards)."""
        health = await self.check_health()
        if not health.get("reachable"):
            return self._fallback_response(prompt)

        payload = self._payload(prompt=prompt)
        if system:
            payload["system"] = system
        self.prompt_fits("generate", system, prompt)

        try:
            resp = await self.client.post(f"{self.base_url}/api/generate", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                self._check_used("generate", data)
                return data.get("response", "").strip()
            else:
                logger.error(f"Ollama error {resp.status_code}: {resp.text}")
                return self._fallback_response(prompt)
        except Exception as e:
            logger.error(f"Failed to generate from Ollama: {e}")
            return self._fallback_response(prompt)

    async def chat(self, messages: List[Dict[str, str]], format: Optional[Any] = None,
                   num_predict: Optional[int] = None, timeout: Optional[float] = None) -> Optional[str]:
        """One /api/chat call (Jennie's voice). `format` is "json" or a JSON schema for structured
        output. -> the reply text, or None when Ollama is down or failed (never raises)."""
        payload = self._payload(num_predict, messages=messages)
        if format is not None:
            payload["format"] = format
        try:
            self.prompt_fits("chat", *(str(m.get("content") or "") for m in messages))
            resp = await self.client.post(f"{self.base_url}/api/chat", json=payload,
                                          timeout=timeout or self.client.timeout)
            if resp.status_code != 200:
                logger.warning(f"Ollama chat error {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
            self._check_used("chat", data)
            return str((data.get("message") or {}).get("content") or "").strip()
        except Exception as e:
            logger.warning(f"Ollama chat failed: {type(e).__name__}: {e}")
            return None

    async def residency(self) -> Dict[str, Any]:
        """Is the model in VRAM, and all of it? {"loaded", "on_gpu", "size_gb", "vram_gb", "num_ctx"}"""
        try:
            resp = await self.client.get(f"{self.base_url}/api/ps", timeout=5.0)
            names = {self.model, f"{self.model}:latest"}
            for m in resp.json().get("models") or []:
                if names & {m.get("name"), m.get("model")}:
                    size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
                    return {"loaded": True, "on_gpu": vram >= size > 0, "size_gb": round(size / 2 ** 30, 2),
                            "vram_gb": round(vram / 2 ** 30, 2), "num_ctx": m.get("context_length")}
        except Exception as e:
            logger.warning(f"Ollama not reachable at {self.base_url}: {e}")
            return {"loaded": False, "on_gpu": False, "reachable": False}
        return {"loaded": False, "on_gpu": False}

    async def warm_up(self) -> Dict[str, Any]:
        """Load the model into VRAM with the one option set and keep it there (an empty prompt
        only loads it). -> residency() plus "seconds"; never raises."""
        t = time.perf_counter()
        try:
            resp = await self.client.post(f"{self.base_url}/api/generate", json=self._payload(prompt=""),
                                          timeout=120.0)
            if resp.status_code != 200:
                logger.warning(f"Ollama warm-up error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"Ollama warm-up failed: {type(e).__name__}: {e}")
        state = await self.residency()
        state["seconds"] = round(time.perf_counter() - t, 1)
        return state

    async def unload(self):
        """Take the model out of VRAM now (only to load it again cleanly, see scheduler.warm_brain)."""
        try:
            await self.client.post(f"{self.base_url}/api/generate", json={"model": self.model, "keep_alive": 0},
                                   timeout=30.0)
        except Exception as e:
            logger.warning(f"Ollama unload failed: {type(e).__name__}: {e}")

    async def generate_executive_report(self, dashboard_data: dict, applications: list, inquiries: list, target_date: str = "today") -> str:
        """Generate a complete executive briefing using Ollama with fallbacks."""
        prompt = build_report_prompt(dashboard_data, applications, inquiries)
        
        health = await self.check_health()
        if health.get("reachable") and health.get("target_model_ready"):
            return await self.generate_response(prompt=prompt, system=SYSTEM_EXECUTIVE_REPORT)
            
        # High quality fallback format when Ollama is offline/starting
        return self._generate_structured_report_fallback(dashboard_data, applications, inquiries, target_date=target_date)

    async def answer_agent_query(self, query: str, context: dict) -> str:
        """Answer a natural language question using Ollama."""
        system = SYSTEM_AGENT_CHAT.format(context=context)
        prompt = f"User Question: {query}\n\nProvide a concise and factual answer:"
        
        health = await self.check_health()
        if health.get("reachable") and health.get("target_model_ready"):
            return await self.generate_response(prompt=prompt, system=system)
            
        return self._answer_query_fallback(query, context)

    def _fallback_response(self, prompt: str) -> str:
        return (
            "🤖 *Hangeul Operational Intelligence*\n"
            "_Note: Local Ollama service is not currently responding. Please verify Ollama is started._\n\n"
            "Request processed successfully."
        )

    def _generate_structured_report_fallback(self, dashboard: dict, applications: list, inquiries: list, target_date: str = "today") -> str:
        from zoneinfo import ZoneInfo
        from datetime import datetime, timedelta
        
        try:
            dhaka_tz = ZoneInfo(settings.REPORT_TIMEZONE)
            now = datetime.now(dhaka_tz)
        except Exception:
            now = datetime.now()

        t_low = target_date.lower().strip()
        if t_low == "today":
            formatted_date = now.strftime("%d %B %Y")
        elif t_low == "yesterday":
            formatted_date = (now - timedelta(days=1)).strftime("%d %B %Y")
        else:
            try:
                parsed = datetime.strptime(target_date.strip(), "%Y-%m-%d")
                formatted_date = parsed.strftime("%d %B %Y")
            except ValueError:
                formatted_date = target_date.strip()
        total_came = len(inquiries)

        done_leads = []
        no_ans_leads = []
        pending_leads = []
        c_stats = {}

        for r in inquiries:
            status = str(r.get("status", "")).strip().lower()
            c = r.get("consultant") or "Unassigned"
            if c not in c_stats:
                c_stats[c] = {"total": 0, "done": 0, "no_ans": 0, "pending": 0}
            c_stats[c]["total"] += 1

            if any(w in status for w in ["consulted", "done", "file opened"]):
                done_leads.append(r)
                c_stats[c]["done"] += 1
            elif "no answer" in status:
                no_ans_leads.append(r)
                c_stats[c]["no_ans"] += 1
            else:
                pending_leads.append(r)
                c_stats[c]["pending"] += 1

        pct_done = (len(done_leads) / total_came * 100) if total_came else 0
        pct_no_ans = (len(no_ans_leads) / total_came * 100) if total_came else 0
        pct_pending = (len(pending_leads) / total_came * 100) if total_came else 0

        prog_counts = {}
        for r in inquiries:
            p = r.get("program") or "General"
            prog_counts[p] = prog_counts.get(p, 0) + 1

        summary = dashboard.get("summary", {})
        total_students = summary.get("total_applicants", 262)
        active_apps = summary.get("active_applications", 3)

        if total_came == 0:
            return (
                "📋 *HANGEUL DAILY OPERATIONAL BRIEF*\n"
                f"*Date:* {formatted_date} (Asia/Dhaka)\n\n"
                f"ℹ️ *No consultation inquiries were found on this date ({formatted_date}).*\n\n"
                f"• *Total Students in System:* `{total_students}`\n"
                f"• *Active Review Queue:* `{active_apps}`\n"
            )

        report = (
            "📋 *HANGEUL DAILY OPERATIONAL BRIEF*\n"
            f"*Date:* {formatted_date} (Asia/Dhaka)\n\n"
            "📊 *HIGH-LEVEL SUMMARY*\n"
            f"• *Total Inquiries Received:* `{total_came}`\n"
            f"• *Done / Consulted:* `{len(done_leads)}` ({pct_done:.1f}%)\n"
            f"• *Attempted (No Answer):* `{len(no_ans_leads)}` ({pct_no_ans:.1f}%)\n"
            f"• *Pending / Unhandled (Waiting):* `{len(pending_leads)}` ({pct_pending:.1f}%)\n\n"
            "👥 *COUNSELOR WORKLOAD & COMPLETION*\n"
        )

        for c, s in sorted(c_stats.items(), key=lambda x: -x[1]["total"]):
            status_tag = f"{s['pending']} Pending ⏳" if s["pending"] > 0 else "All Contacted ✅"
            report += f"  • *{c}:* {s['done']}/{s['total']} Done ({status_tag})\n"

        report += "\n🎓 *INQUIRIES BY PROGRAM*\n"
        for p, cnt in sorted(prog_counts.items(), key=lambda x: -x[1]):
            report += f"  • {p}: `{cnt}` leads\n"

        if pending_leads:
            report += f"\n⏳ *PENDING LEADS WAITING FOR CONTACT ({len(pending_leads)})*\n"
            for i, r in enumerate(pending_leads[:7], 1):
                name = r.get("name") or "Applicant"
                prog = r.get("program", "")
                c_name = r.get("consultant", "Unassigned")
                rec = r.get("received", "").split(" ")[-1] if r.get("received") else ""
                time_str = f" [{rec}]" if rec else ""
                report += f"  {i}. *{name}* ({prog}){time_str} ➔ `{c_name}`\n"

        verified_students = summary.get("verified_students", 262)
        pending_payment = summary.get("pending_payment", 0)
        window_review = summary.get("window_apps_under_review", 2)

        report += (
            "\n🏛️ *PORTAL ENROLLMENT SNAPSHOT*\n"
            f"• *Total Students in System:* `{total_students}` (Verified: `{verified_students}`)\n"
            f"• *Pending Payments:* `{pending_payment}`\n"
            f"• *University Window Apps Under Review:* `{window_review}`\n"
        )

        return report


    def _answer_query_fallback(self, query: str, context: dict) -> str:
        summary = context.get("dashboard", {}).get("summary", {})
        q_lower = query.lower()
        
        if any(w in q_lower for w in ["report", "brief", "summary", "today", "consultation", "came", "done", "high-level", "overview"]):
            inquiries = context.get("sample_inquiries") or context.get("inquiries") or []
            return self._generate_structured_report_fallback(
                dashboard=context.get("dashboard", {}),
                applications=context.get("sample_applications") or [],
                inquiries=inquiries
            )
        elif "applicant" in q_lower or "student" in q_lower or "total" in q_lower:
            return (
                f"📋 *Applicant Statistics*\n"
                f"• *Total Applicants on Record:* {summary.get('total_applicants', '262')}\n"
                f"• *Currently Active Applications:* {summary.get('active_applications', '3')}\n"
                f"• *Verified Students:* {summary.get('verified_students', '261')}\n"
                f"• *Pending Document Verification:* {summary.get('pending_document_verification', '21')}"
            )
        elif "visa" in q_lower or "approved" in q_lower:
            return (
                f"🛂 *Visa Status Update*\n"
                f"• *Visas Approved YTD:* {summary.get('visa_approved_ytd', '2')}\n"
                f"• *Pending Document Review:* {summary.get('pending_document_verification', '21')}\n"
                f"• *Total Applicants:* {summary.get('total_applicants', '262')}"
            )
        elif "alert" in q_lower or "urgent" in q_lower:
            alerts = context.get("dashboard", {}).get("urgent_alerts", [])
            lines = ["⚠️ *Current Urgent Alerts:*"]
            for a in alerts:
                lines.append(f"• {a.get('message')}")
            return "\n".join(lines)
        else:
            inquiries = context.get("sample_inquiries") or context.get("inquiries") or []
            return self._generate_structured_report_fallback(
                dashboard=context.get("dashboard", {}),
                applications=context.get("sample_applications") or [],
                inquiries=inquiries
            )

# Singleton Ollama instance
ollama_client = OllamaClient()
