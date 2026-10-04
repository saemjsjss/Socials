"""Jennie brain trial: routing (A), spoken reply (B) and resources (C) for small Ollama models.

Usage: python trial.py [model ...]   (default: every candidate; models that are not installed
are recorded as unavailable and skipped). Nothing is pulled here; each model is unloaded
(keep_alive 0) when its run ends. Results: results_<model>.json and a printed summary.
"""
import json
import re
import sys
import time
import urllib.request

# 127.0.0.1, not localhost: on this PC "localhost" tries ::1 first and every new connection
# loses ~2.03 s before falling back to IPv4 (see localhost_check.py).
OLLAMA = "http://127.0.0.1:11434"
OUT_DIR = "C:/Hangeul/JARVIS/brain-trial"
CANDIDATES = ["qwen2.5:7b", "qwen2.5:3b", "qwen3:4b", "gemma3:4b", "qwen3:1.7b"]
SEED = 42
TEMP = 0.3
NUM_CTX = 4096
BUDGET_GB = 3.5
TODAY = "2026-09-27"

COMMANDS = ["verified_today", "verified_date", "inquiries_today", "inquiries_date", "calendar",
            "passports", "stats", "missing_report", "crosscheck", "chat"]


# --------------------------------------------------------------------------- HTTP

def call(path, payload=None, timeout=600):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(OLLAMA + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def installed():
    return {m["name"] for m in call("/api/tags")["models"]}


def ps(model):
    for m in call("/api/ps")["models"]:
        if m["name"] == model or m["model"] == model:
            return m
    return None


def unload(model):
    try:
        call("/api/generate", {"model": model, "keep_alive": 0})
    except Exception as e:  # noqa: BLE001
        print("unload failed:", e)


def chat(model, messages, fmt=None, num_predict=256):
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": "10m",
        "options": {"temperature": TEMP, "seed": SEED, "num_ctx": NUM_CTX, "num_predict": num_predict},
    }
    if model.startswith("qwen3"):
        payload["think"] = False
    if fmt is not None:
        payload["format"] = fmt
    t0 = time.perf_counter()
    r = call("/api/chat", payload)
    wall = time.perf_counter() - t0
    ev_n, ev_d = r.get("eval_count", 0), r.get("eval_duration", 0)
    pe_n, pe_d = r.get("prompt_eval_count", 0), r.get("prompt_eval_duration", 0)
    return {
        "text": r["message"]["content"],
        "thinking": r["message"].get("thinking"),
        "wall_s": round(wall, 3),
        "ollama_s": round(r.get("total_duration", 0) / 1e9, 3),
        "load_s": round(r.get("load_duration", 0) / 1e9, 3),
        "prompt_tokens": pe_n,
        "prompt_tok_s": round(pe_n / (pe_d / 1e9), 1) if pe_d else None,
        "gen_tokens": ev_n,
        "gen_tok_s": round(ev_n / (ev_d / 1e9), 1) if ev_d else None,
    }


# --------------------------------------------------------------------------- A) routing

ROUTER_SYSTEM = (
    "You are the command router for Jennie, the voice assistant of the Telegram bot of Hangeul "
    "Korean Language & Visa, a study-in-Korea agency in Dhaka. Office staff talk to Jennie in "
    "Korean or English. The text comes from speech recognition, which sometimes mishears a word, "
    "so go by the overall meaning. Choose exactly ONE command for the NEW utterance.\n\n"
    "Commands:\n"
    "- verified_today: students whose payment/documents were verified today (검증된 학생)\n"
    "- verified_date: verified students on one specific date other than today\n"
    "- inquiries_today: consultancy inquiries / consultations handled today (상담, 문의)\n"
    "- inquiries_date: consultancy inquiries on one specific date other than today\n"
    "- calendar: upcoming schedule, deadlines and intakes (일정, 마감)\n"
    "- passports: passport audit, students whose passport data is wrong or missing (여권)\n"
    "- stats: overall statistics and totals (전체 통계)\n"
    "- missing_report: students with missing documents or missing data\n"
    "- crosscheck: cross-check payments against records for a date or a student\n"
    "- chat: greetings, thanks, praise, small talk, or anything that is not a data request\n\n"
    f"Today is Sunday {TODAY}. Resolve relative dates such as 어제 / yesterday against today. "
    "A short follow-up such as 'and yesterday?' keeps the topic of the previous request and "
    "changes only the date.\n"
    "Answer with JSON only: {\"command\": one of the commands, \"date\": \"YYYY-MM-DD\" or null, "
    "\"english_query\": the request as one short English sentence, \"language\": \"ko\" if the new "
    "utterance is Korean, otherwise \"en\"}. The date is null unless the command is verified_date, "
    "inquiries_date or crosscheck with a spoken date."
)

ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "enum": COMMANDS},
        "date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "english_query": {"type": "string"},
        "language": {"type": "string", "enum": ["ko", "en"]},
    },
    "required": ["command", "date", "english_query", "language"],
}

KO1 = "제니야 오늘 서류 검증된 학생 몇 명이야?"
EN7 = "Jennie, how many students were verified today?"
KO1_REPLY = "짜잔! 오늘 서류 검증된 학생은 두 명이에용. 총 이만 팔천 타카예요!"
EN7_REPLY = "Ta-da! Two students were verified today, for twenty-eight thousand taka in total, hehe!"

# (id, lang, utterance, history [(role, text)], expected command, expected date)
ROUTING_CASES = [
    (1, "ko", KO1, [], "verified_today", None),
    (2, "ko", "제니야 오늘 수료 검증된 학생 몇 명이야?", [], "verified_today", None),
    (3, "ko", "그럼 어제는?", [("User", KO1), ("Jennie", KO1_REPLY)], "verified_date", "2026-09-26"),
    (4, "ko", "이번 주 일정이나 마감 있어?", [], "calendar", None),
    (5, "ko", "여권 정보 틀린 학생 있어?", [], "passports", None),
    (6, "ko", "오늘 상담 몇 건 했어?", [], "inquiries_today", None),
    (7, "en", EN7, [], "verified_today", None),
    (8, "en", "and yesterday?", [("User", EN7), ("Jennie", EN7_REPLY)], "verified_date", "2026-09-26"),
    (9, "en", "What deadlines are coming up?", [], "calendar", None),
    (10, "en", "Thanks Jennie, you're the best!", [], "chat", None),
    (11, "ko", "고마워 제니야, 수고했어!", [], "chat", None),
    (12, "en", "Give me the overall stats", [], "stats", None),
]


def router_user_msg(utterance, history):
    hist = "\n".join(f"{who}: {text}" for who, text in history) or "(none)"
    return f"Conversation so far:\n{hist}\n\nNEW utterance: {utterance}"


def run_routing(model):
    rows = []
    for cid, lang, utt, hist, exp_cmd, exp_date in ROUTING_CASES:
        r = chat(model, [{"role": "system", "content": ROUTER_SYSTEM},
                         {"role": "user", "content": router_user_msg(utt, hist)}],
                 fmt=ROUTER_SCHEMA, num_predict=160)
        raw = r["text"].strip()
        parsed, valid = None, False
        try:
            parsed = json.loads(raw)
            valid = (isinstance(parsed, dict) and parsed.get("command") in COMMANDS
                     and parsed.get("language") in ("ko", "en")
                     and isinstance(parsed.get("english_query"), str)
                     and (parsed.get("date") is None
                          or bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(parsed.get("date"))))))
        except Exception:  # noqa: BLE001
            parsed = None
        cmd = parsed.get("command") if valid else None
        date = parsed.get("date") if valid else "<invalid>"
        rows.append({
            "id": cid, "utterance": utt, "expected": [exp_cmd, exp_date], "raw": raw,
            "json_valid": valid, "command_ok": valid and cmd == exp_cmd,
            "date_ok": valid and date == exp_date,
            "lang_ok": valid and parsed.get("language") == lang,
            **{k: r[k] for k in ("wall_s", "ollama_s", "prompt_tokens", "gen_tokens", "gen_tok_s", "prompt_tok_s")},
        })
        print(f"  A{cid:>2} {'OK ' if rows[-1]['command_ok'] and rows[-1]['date_ok'] else 'BAD'} "
              f"{r['wall_s']:.2f}s {raw}")
    return rows


# --------------------------------------------------------------------------- B) spoken reply

WRITTEN = ("✅ Student Payment Verifications — 27 September 2026\n"
           "• Total Students Verified: 2\n"
           "• Total Verified Revenue: ৳ 28,000.00 BDT\n"
           "1. BADHON SUFIUR RAHMAN — KLP — 20,000 BDT Cash\n"
           "2. KHANOM TAHIRA — BACHELOR'S DEGREE — 8,000 BDT bKash")

REPLY_SYSTEM_KO = (
    "You are Jennie (제니), the cute and cheerful voice of the office bot of Hangeul Korean Language & "
    "Visa. Say, in a short KOREAN voice note, the answer to what the user just asked, using the bot's "
    "written answer (usually English). If there is no written answer, just reply naturally.\n"
    "Rules:\n"
    "- Korean (Hangul) only, in a cute 애교 style: friendly endings like ~요, ~용, ~어용, ~구요, and "
    "you may start with '짜잔!'. Warm and polite, never rude.\n"
    "- 1 or 2 short sentences, at most 200 characters in total.\n"
    "- Use only facts from the written answer; never invent numbers, names or dates. Give totals "
    "rather than lists of names.\n"
    "- Write every number in Hangul words, never digits: 3명 -> 세 명, 12개 -> 열두 개, "
    "412번 -> 사백십이 번, 2026년 -> 이천이십육 년.\n"
    "- No Markdown, asterisks, emojis, bullet points, URLs or English sentences.\n"
    "Output only the words Jennie says."
)

REPLY_SYSTEM_EN = (
    "You are Jennie, the cute and cheerful voice of the office bot of Hangeul Korean Language & Visa "
    "in Dhaka. Say, in a short English voice note, the answer to what the user just asked, using the "
    "bot's written answer. If there is no written answer, just reply naturally.\n"
    "Speak in a cute, bubbly, playful style, the English version of Korean 애교: cheerful openers "
    "like 'Ta-da!' or 'Yay!', sweet little touches like 'hehe' or 'okie', and a happy, caring tone. "
    "Stay polite, and keep every fact exact.\n"
    "Rules:\n"
    "- English only, 1 or 2 short sentences, at most 200 characters in total.\n"
    "- Use only facts from the written answer; never invent numbers, names or dates. Give totals "
    "rather than lists of names.\n"
    "- No Markdown, asterisks, emojis, bullet points or URLs.\n"
    "Output only the words Jennie says."
)

# (id, lang, utterance, last 2 turns, written answer or None, expects the verified facts)
REPLY_CASES = [
    (1, "ko", KO1, [("User", "제니야 안녕!"), ("Jennie", "안녕하세용! 제니 여기 있어요, 뭐 도와드릴까용?")],
     WRITTEN, True),
    (7, "en", EN7, [("User", "Hi Jennie!"), ("Jennie", "Hi hi! Jennie is here, hehe. What can I do for you?")],
     WRITTEN, True),
    (10, "en", "Thanks Jennie, you're the best!", [("User", EN7), ("Jennie", EN7_REPLY)], None, False),
]

HANGUL = re.compile(r"[가-힣]")
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200d]")
MARKDOWN = re.compile(r"[*#`_|]|^\s*[-•]\s|\[[^\]]*\]\(|^\s*\d+\.\s", re.M)
URL = re.compile(r"https?://|www\.", re.I)


def reply_checks(text, lang, facts):
    c = {"len": len(text), "len_ok": 0 < len(text) <= 200,
         "sentences": len([s for s in re.split(r"(?<=[.!?])\s+|(?<=[.!?])$", text.strip()) if s.strip()]),
         "no_markdown": not MARKDOWN.search(text), "no_emoji": not EMOJI.search(text),
         "no_url": not URL.search(text)}
    c["sentences_ok"] = c["sentences"] <= 2
    if lang == "ko":
        latin_runs = re.findall(r"[A-Za-z]+(?:[ ,'-]+[A-Za-z]+){2,}", text)
        c["hangul"] = bool(HANGUL.search(text))
        c["no_latin_sentence"] = not latin_runs
        c["latin_words"] = re.findall(r"[A-Za-z]{2,}", text)
        c["no_ascii_digits"] = not re.search(r"[0-9]", text)
        c["lang_ok"] = c["hangul"] and c["no_latin_sentence"]
        if facts:
            c["fact_two"] = bool(re.search(r"두\s*명|두\s*분", text))
            c["fact_28000"] = bool(re.search(r"이만\s*팔천", text))
    else:
        c["lang_ok"] = not HANGUL.search(text) and bool(re.search(r"[A-Za-z]", text))
        if facts:
            c["fact_two"] = bool(re.search(r"\btwo\b|\b2\b", text, re.I))
            c["fact_28000"] = bool(re.search(r"28,?000|twenty[- ]eight thousand", text, re.I))
    keys = ["len_ok", "sentences_ok", "no_markdown", "no_emoji", "no_url", "lang_ok"]
    if lang == "ko":
        keys.append("no_ascii_digits")
    if facts:
        keys += ["fact_two", "fact_28000"]
    c["passed"] = [k for k in keys if c[k]]
    c["failed"] = [k for k in keys if not c[k]]
    return c


def run_replies(model):
    rows = []
    for cid, lang, utt, hist, written, facts in REPLY_CASES:
        system = REPLY_SYSTEM_KO if lang == "ko" else REPLY_SYSTEM_EN
        hist_txt = "\n".join(f"{who}: {text}" for who, text in hist)
        prompt = (f"Recent conversation:\n{hist_txt}\n\nThe user just said (spoken): {utt}\n\n"
                  f"The bot's written answer:\n{written if written else '(none, this is small talk)'}"
                  "\n\nJennie says:")
        r = chat(model, [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                 num_predict=200)
        text = r["text"].strip()
        rows.append({"id": cid, "utterance": utt, "reply": text, "checks": reply_checks(text, lang, facts),
                     **{k: r[k] for k in ("wall_s", "ollama_s", "prompt_tokens", "gen_tokens", "gen_tok_s", "prompt_tok_s")}})
        print(f"  B{cid:>2} {r['wall_s']:.2f}s fail={rows[-1]['checks']['failed']} :: {text}")
    return rows


# --------------------------------------------------------------------------- C) resources + driver

def run_model(model):
    res = {"model": model}
    if ps(model):
        unload(model)
        time.sleep(2)
    # Cold load: empty prompt loads the weights with the trial's num_ctx.
    t0 = time.perf_counter()
    r = call("/api/generate", {"model": model, "prompt": "", "keep_alive": "10m",
                               "options": {"num_ctx": NUM_CTX}})
    res["load_wall_s"] = round(time.perf_counter() - t0, 2)
    res["load_ollama_s"] = round(r.get("load_duration", 0) / 1e9, 2)
    p = ps(model) or {}
    res["size_gb"] = round(p.get("size", 0) / 2**30, 2)
    res["size_vram_gb"] = round(p.get("size_vram", 0) / 2**30, 2)
    res["context_length"] = p.get("context_length")
    res["fully_on_gpu"] = p.get("size", 0) == p.get("size_vram", -1)
    res["fits_budget"] = res["fully_on_gpu"] and res["size_vram_gb"] <= BUDGET_GB
    print(f"{model}: load {res['load_wall_s']}s, VRAM {res['size_vram_gb']} GiB of {res['size_gb']} GiB")
    # One warm-up call so the timed calls are warm.
    chat(model, [{"role": "user", "content": "hi"}], num_predict=8)
    try:
        res["routing"] = run_routing(model)
        res["replies"] = run_replies(model)
    finally:
        unload(model)
    rt = res["routing"]
    n = len(rt)
    res["routing_command_acc"] = f"{sum(x['command_ok'] for x in rt)}/{n}"
    res["routing_date_acc"] = f"{sum(x['date_ok'] for x in rt)}/{n}"
    res["json_valid"] = f"{sum(x['json_valid'] for x in rt)}/{n}"
    res["route_latency_s"] = round(sum(x["wall_s"] for x in rt) / n, 2)
    rp = res["replies"]
    res["reply_latency_s"] = round(sum(x["wall_s"] for x in rp) / len(rp), 2)
    toks = [x["gen_tok_s"] for x in rt + rp if x["gen_tok_s"]]
    res["gen_tok_s"] = round(sum(toks) / len(toks), 1) if toks else None
    ptoks = [x["prompt_tok_s"] for x in rt + rp if x["prompt_tok_s"]]
    res["prompt_tok_s"] = round(sum(ptoks) / len(ptoks), 1) if ptoks else None
    res["route_plus_reply_s"] = round(res["route_latency_s"] + res["reply_latency_s"], 2)
    return res


def main():
    models = sys.argv[1:] or CANDIDATES
    have = installed()
    summary = []
    for m in models:
        if m not in have:
            print(f"{m}: not installed, skipped")
            summary.append({"model": m, "available": False})
            continue
        res = run_model(m)
        res["available"] = True
        with open(f"{OUT_DIR}/results_{m.replace(':', '_')}.json", "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        summary.append({k: v for k, v in res.items() if k not in ("routing", "replies")})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("still loaded:", [m["name"] for m in call("/api/ps")["models"]])


if __name__ == "__main__":
    main()
