"""Offline checks of service.py that need no model and no running service (loads no weights, opens no port).

  .venv\\Scripts\\python.exe offline_test.py

Text preparation for the voice (Korean numbers with particles attached, times, dates, ranges, phone
numbers; English times and dates), log redaction of CosyVoice's per-sentence lines, the local-clients-only
request guard, the filter for words Whisper invents on non-speech, and the render stop / error capture
hooked into CosyVoice. Exit code 0 when everything passes.
"""
import asyncio
import logging
import sys
import threading
import time
from types import SimpleNamespace

import service

for _h in list(logging.getLogger().handlers):      # keep this test's lines out of the service's jennie_voice.log
    logging.getLogger().removeHandler(_h)
logging.getLogger().addHandler(logging.NullHandler())

failures = 0


def check(name, cond, detail=""):
    global failures
    failures += 0 if cond else 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""), flush=True)


# ---------------------------------------------------------------- text preparation
PREP = [
    # Korean: a particle right after the number is the normal way to write it (\b never matched there)
    ("ko", "브리핑은 18:05에 보내드려요~", "브리핑은 오후 여섯 시 오 분에 보내드려요."),
    ("ko", "18:05부터 시작해요.", "오후 여섯 시 오 분부터 시작해요."),
    ("ko", "18:05 브리핑", "오후 여섯 시 오 분 브리핑."),
    ("ko", "오후 6:30에 만나요.", "오후 여섯 시 삼십 분에 만나요."),
    ("ko", "마감일은 2026-09-27까지예요!", "마감일은 이천이십육년 구월 이십칠일까지예요!"),
    ("ko", "2026.09.27까지 내주세요.", "이천이십육년 구월 이십칠일까지 내주세요."),
    ("ko", "마감은 2026-09-27이에요.", "마감은 이천이십육년 구월 이십칠일이에요."),
    # month names are one word (spaced '십일 월' was heard back as '10일 월')
    ("ko", "원서 접수는 10월 15일까지, 상담은 11월에 해요.", "원서 접수는 시월 십오 일까지, 상담은 십일월에 해요."),
    ("ko", "등록금은 2026-06-30까지예요.", "등록금은 이천이십육년 유월 삼십일까지예요."),
    ("ko", "3-5월에 열려요.", "삼월에서 오월에 열려요."),
    # ranges and school years are not phone numbers
    ("ko", "서류는 3-5일 걸려요.", "서류는 삼 일에서 오 일 걸려요."),
    ("ko", "학생 3-5명이 와요.", "학생 세 명에서 다섯 명이 와요."),
    ("ko", "3~5일 정도요.", "삼 일에서 오 일 정도요."),
    ("ko", "2025-2026학년도 입학이에요.", "이천이십오에서 이천이십육 학년도 입학이에요."),
    ("ko", "등록금은 10-15% 올랐어요.", "등록금은 십 퍼센트에서 십오 퍼센트 올랐어요."),
    ("ko", "상담은 18:05~18:30이에요.", "상담은 오후 여섯 시 오 분에서 오후 여섯 시 삼십 분이에요."),
    # phone numbers and codes: digit by digit
    ("ko", "전화번호는 010-1234-5678이에요.", "전화번호는 공일공 일이삼사 오육칠팔이에요."),
    ("ko", "사무실 번호는 +880 1711-123456이에요.", "사무실 번호는 팔팔공 일칠일일 일이삼사오육이에요."),
    ("ko", "번호 01711123456로 연락주세요.", "번호 공일칠일일일이삼사오육로 연락주세요."),
    # counters, money, decimals
    ("ko", "새로 서류 검증된 학생이 3명 있구요, 진행 시트 7개 모두 최신 상태예요!",
     "새로 서류 검증된 학생이 세 명 있구요, 진행 시트 일곱 개 모두 최신 상태예요!"),
    ("ko", "학생 번호 412번이에요.", "학생 번호 사백십이 번이에요."),
    ("ko", "비용은 1,250,000원이에요.", "비용은 백이십오만 원이에요."),
    ("ko", "12.5%가 늘었어요.", "십이 점 오 퍼센트가 늘었어요."),
    # English
    ("en", "The brief goes out at 6:30pm today.", "The brief goes out at 6 30 PM today."),
    ("en", "The brief goes out at 18:05.", "The brief goes out at 6 oh 5 PM."),
    ("en", "It opens at 9:00 a.m. and closes at 5:30 p.m.", "It opens at 9 AM and closes at 5 30 PM."),
    ("en", "Deadline: 2026-09-27.", "Deadline: September twenty-seventh, twenty twenty-six."),
    ("en", "Deadline is 2026-09-27th? No, 2026.09.27!",
     "Deadline is September twenty-seventh, twenty twenty-sixth? No, September twenty-seventh, twenty twenty-six!"),
    ("en", "12.5% more, 1,250 students, the 3rd time.", "12 point 5 percent more, 1250 students, the third time."),
]
for lang, text, want in PREP:
    got = service.prepare_text(text, lang)
    check(f"prepare_text {lang} {text!r}", got == want, f"-> {got!r}" + ("" if got == want else f" (want {want!r})"))

# ---------------------------------------------------------------- log redaction
f = service._RedactFilter()
chunk = "마지막으로 등록금 납부 기한이 다가온 학생은 하산 알리, 파티마 카툰, 김민수 학생이에요."
for msg in (f"synthesis text {chunk}",
            f"synthesis text {chunk} too short than prompt text {service.REF_TEXT}, this may lead to bad performance"):
    rec = logging.LogRecord("root", logging.INFO, __file__, 1, msg, None, None)
    f.filter(rec)
    out = rec.getMessage()
    check("log redaction keeps no chunk text", "하산" not in out and "마지막" not in out and str(len(chunk)) in out,
          repr(out))

# ---------------------------------------------------------------- request guard


def scope(method="POST", path="/tts", **headers):
    hs = [(k.replace("_", "-").encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
    return {"type": "http", "method": method, "path": path, "headers": hs}


GUARD = [
    ("bot /tts", scope(host="127.0.0.1:8765", content_type="application/json", content_length="120"), None),
    ("localhost Host", scope(host="localhost:8765", content_type="application/json; charset=utf-8",
                             content_length="120"), None),
    ("bot /stt", scope(path="/stt", host="127.0.0.1:8765", content_type="multipart/form-data; boundary=x",
                       content_length=str(3 * 1024 * 1024)), None),
    ("watchdog /health", scope(method="GET", path="/health", host="127.0.0.1:8765"), None),
    ("DNS rebinding Host", scope(host="evil.example:8765", content_type="application/json", content_length="10"), 403),
    ("browser Origin", scope(host="127.0.0.1:8765", origin="https://evil.example", content_type="text/plain",
                             content_length="10"), 403),
    ("no Content-Length", scope(host="127.0.0.1:8765", content_type="application/json"), 411),
    ("/tts body too big", scope(host="127.0.0.1:8765", content_type="application/json", content_length="70000"), 413),
    ("/stt body too big", scope(path="/stt", host="127.0.0.1:8765", content_type="multipart/form-data; boundary=x",
                                content_length=str(40 * 1024 * 1024)), 413),
    ("/tts as text/plain", scope(host="127.0.0.1:8765", content_type="text/plain", content_length="10"), 415),
]
for name, sc, want in GUARD:
    got = service._LocalClientsOnly._refusal(sc)
    check(f"guard {name}", (got is None and want is None) or (got is not None and got[0] == want), repr(got))


async def through_guard(sc):
    """The refusal is sent without calling the app or reading the body."""
    sent, called = [], []

    async def app(scope, receive, send):
        called.append(True)

    async def receive():
        raise AssertionError("the body must not be read")

    async def send(message):
        sent.append(message)

    await service._LocalClientsOnly(app)(sc, receive, send)
    return called, sent


called, sent = asyncio.run(through_guard(scope(host="evil.example:8765", content_type="application/json",
                                              content_length="10")))
check("guard answers 403 JSON without reaching the app", not called and sent and sent[0]["status"] == 403
      and b'"error"' in sent[-1].get("body", b""), repr(sent[:1]))

# ---------------------------------------------------------------- words Whisper invents on non-speech


def seg(text, no_speech=0.0, logprob=-0.2):
    return SimpleNamespace(text=text, no_speech_prob=no_speech, avg_logprob=logprob, start=0.0, end=2.0)


HALLU = [
    ("tone on CPU medium", seg(" Thanks for watching!", 0.91, -0.976), True),
    ("tone on GPU turbo", seg(" You", 0.0, -0.992), True),
    ("subtitle credit", seg(" 한글자막 by 한효정", 0.0, -0.39), True),
    ("high no_speech, unsure", seg(" 음 네", 0.8, -0.9), True),
    ("real Korean", seg(" 짜잔! 제니예요.", 0.1, -0.29), False),
    ("real short Korean", seg(" 네.", 0.47, -0.8), False),
    ("confident 'you'", seg(" You.", 0.0, -0.3), False),
    ("real English", seg(" Thank you so much for checking the sheets.", 0.05, -0.25), False),
]
for name, s, want in HALLU:
    check(f"stt filter: {name}", service._hallucinated(s) == want)

# ---------------------------------------------------------------- render stop and error capture
job = service.Job("tts", 0.05)
check("job has time at first", job.stop_reason() is None)
time.sleep(0.1)
check("job stops after its time limit", "time limit" in (job.stop_reason() or ""), job.stop_reason())
job = service.Job("tts", 60)
job.gone.set()
check("job stops when its client leaves", job.stop_reason() == "the client went away")


class FakeLLM:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at

    def inference(self, **kwargs):
        for i in range(1000):
            if i == self.fail_at:
                raise RuntimeError("CUDA out of memory. Tried to allocate 20.00 MiB")
            yield i


def fake_engine(llm):
    e = service.Engine()
    model = SimpleNamespace(llm=llm, flow=SimpleNamespace(decoder=SimpleNamespace(forward_estimator=lambda *a: "mel")),
                            lock=threading.Lock(), tts_speech_token_dict={}, llm_end_dict={}, hift_cache_dict={})
    e.tts = SimpleNamespace(model=model)
    e._install_hooks()
    return e, model


# an out-of-memory in CosyVoice's LLM thread is recorded (not lost) and raised on the request's thread
eng, model = fake_engine(FakeLLM(fail_at=5))
ctl = eng._ctl = service._RenderControl(service.Job("tts", 60))
tokens = []
worker = threading.Thread(target=lambda: tokens.extend(model.llm.inference(text=None)))
worker.start()
worker.join()
check("LLM-thread error is captured", len(tokens) == 5 and ctl.error is not None and service._is_oom(ctl.error),
      f"{len(tokens)} tokens, {ctl.error!r}")
try:
    model.flow.decoder.forward_estimator()
    check("flow step re-raises the LLM-thread error", False)
except RuntimeError as e:
    check("flow step re-raises the LLM-thread error", e is ctl.error)

# a client that leaves stops the LLM at the next token and the flow before its next step
eng, model = fake_engine(FakeLLM())
job = service.Job("tts", 60)
ctl = eng._ctl = service._RenderControl(job)
tokens = []
for t in model.llm.inference(text=None):
    tokens.append(t)
    if t == 9:
        job.gone.set()
check("LLM stops one token after the client leaves", len(tokens) == 10, f"{len(tokens)} tokens")
try:
    model.flow.decoder.forward_estimator()
    check("flow step raises _Stop", False)
except service._Stop as e:
    check("flow step raises _Stop", "went away" in str(e), str(e))
eng._ctl = None
check("no render in progress: hooks pass through", model.flow.decoder.forward_estimator() == "mel"
      and len(list(model.llm.inference(text=None))) == 1000)

print("ALL PASS" if not failures else f"{failures} CHECK(S) FAILED", flush=True)
sys.exit(1 if failures else 0)
