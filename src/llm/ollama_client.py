import json
import logging
import re
import time
from typing import Optional, Dict, Any, List
import httpx

from src.config import settings
from src.llm.prompts import AGENT_SCHEMA, SYSTEM_AGENT_CHAT

logger = logging.getLogger("hangeul.llm")

# A typed question the bot has no route for: the LLM only picks which live facts answer it.
AGENT_MAX_TOKENS = 60           # a JSON list of a few numbers
AGENT_TIMEOUT = 30.0            # seconds (a warm call takes well under one)
AGENT_MAX_FACTS = 5

_LABEL_STOP = {"a", "an", "the", "of", "to", "for", "in", "on", "and", "or", "by", "at", "with", "is", "are"}


def _label_words(text: str) -> List[str]:
    """The telling words of a label or a question: lower case, a plural 's' dropped, no filler."""
    words = []
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
            w = w[:-1]
        if w not in _LABEL_STOP:
            words.append(w)
    return words

# While Jennie's voice is on, the model stays in VRAM for good ("Jennie's brain"), so no spoken
# question waits for it to load. Otherwise it loads for a question and Ollama unloads it after
# settings.BRAIN_IDLE_UNLOAD idle, leaving the GPU free (brain_pinned()).
KEEP_ALIVE = -1


def brain_pinned() -> bool:
    """Is the brain kept in VRAM for good? Only for Jennie's voice (or BRAIN_ALWAYS_LOADED)."""
    return bool(settings.JENNIE_VOICE_ENABLED or settings.BRAIN_ALWAYS_LOADED)


def keep_alive():
    """The keep_alive every call sends: -1 (never unload) when pinned, else the idle timeout."""
    return KEEP_ALIVE if brain_pinned() else (settings.BRAIN_IDLE_UNLOAD or "5m")
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
        return {"model": self.model, "stream": False, "keep_alive": keep_alive(),
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

    # The daily brief is no longer written by the LLM (it invented passport numbers, visa counts
    # and rates): src/bot/brief.py builds it from the portal in code and asks the LLM only for
    # one checked summary sentence, through chat().

    async def answer_agent_query(self, query: str, facts: List[str]) -> Optional[List[str]]:
        """Which of `facts` (one live portal figure a line, e.g. "Total students (Direct / legacy
        pipeline): 330") answer the typed question `query`. The LLM only picks them, by number,
        and the caller shows the picked facts word for word: it never writes a figure of its own,
        so every number shown is the portal's (src/bot/ask.py answer_unknown).

        -> the picked facts, in the order given ([] when none answers the question); None when
        the brain is down or answered nonsense, or when the facts do not fit its context
        (prompt_fits: Ollama would cut the prompt silently and the pick could be wrong)."""
        facts = [f for f in (facts or []) if f and f.strip()]
        if not facts:
            return []
        numbered = "\n".join(f"{i}. {f}" for i, f in enumerate(facts, 1))
        user = f"Facts:\n{numbered}\n\nQuestion: {query}\n\nJSON:"
        if not self.prompt_fits("agent", SYSTEM_AGENT_CHAT, user):
            return None
        raw = await self.chat([{"role": "system", "content": SYSTEM_AGENT_CHAT}, {"role": "user", "content": user}],
                              format=AGENT_SCHEMA, num_predict=AGENT_MAX_TOKENS, timeout=AGENT_TIMEOUT)
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            found = re.search(r"\{.*\}", raw, re.S)
            try:
                data = json.loads(found.group(0)) if found else None
            except ValueError:
                data = None
        if not isinstance(data, dict) or not isinstance(data.get("facts"), list):
            return None
        if data.get("answered") is False:
            return []
        picked = sorted({int(n) for n in data["facts"]
                         if isinstance(n, (int, float)) and not isinstance(n, bool) and 1 <= int(n) <= len(facts)})
        return [facts[n - 1] for n in picked[:AGENT_MAX_FACTS]]

    def _answer_query_fallback(self, query: str, facts: List[str]) -> List[str]:
        """The facts a question names outright, with no LLM (answer_unknown tries this first, and it
        is all there is while the brain is down): each fact whose whole label, the words before its
        figure, is in the question ("how many open windows?" -> "Open windows (Admissions flow): 3").
        Only the facts' own figures; [] when no label is named whole."""
        asked = set(_label_words(query))
        picked = []
        for fact in facts or []:
            label = re.sub(r"\([^)]*\)", " ", fact.rsplit(":", 1)[0])
            label = label.split(" — ")[0]
            words = _label_words(label)
            if words and set(words) <= asked:
                picked.append(fact)
        return picked[:AGENT_MAX_FACTS]

    def _fallback_response(self, prompt: str) -> str:
        return (
            "🤖 *Hangeul Operational Intelligence*\n"
            "_Note: Local Ollama service is not currently responding. Please verify Ollama is started._\n\n"
            "Request processed successfully."
        )


# Singleton Ollama instance
ollama_client = OllamaClient()
