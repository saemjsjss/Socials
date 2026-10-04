"""End-to-end check of a RUNNING Jennie voice service (start it first; this script never starts or stops it).

  .venv\\Scripts\\python.exe smoke_test.py

Calls /health, /stt on Korean and English samples (WAV and a Telegram-style OGG/Opus copy), /tts for one
Korean aegyo line and one English line (saved as test_out_ko.ogg / test_out_en.ogg and decoded again),
sends each rendered voice note back through /stt (also Korean times and dates with a particle attached),
checks that a client giving up after 3 s stops the render and frees the lock, checks the error answers
(including the local-clients-only refusals), and samples device-wide VRAM with nvidia-smi the whole time.
Writes smoke_test.json beside this script.
"""
import io
import json
import os
import re
import subprocess
import threading
import time
import unicodedata

import numpy as np
import requests
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:8765"
SAMPLES = r"C:\Hangeul\JARVIS\voice-samples"
KO_WAV = os.path.join(SAMPLES, "real__cosyvoice__v2-zeroshot-krfemale__kr-aegyo.wav")
EN_WAVS = [os.path.join(SAMPLES, "real__cosyvoice__v2-crosslingual-krfemale__en.wav"),
           os.path.join(SAMPLES, "kokoro__bm_george__en.wav")]
KO_WAV_TEXT = ("짜잔! 제니예요! 방금 포털 동기화가 끝났어용. 새로 서류 검증된 학생이 한 명 있구요, "
               "진행 시트 일곱 개 모두 최신 상태예요! 헤헤, 또 궁금한 거 있으세용?")
EN_WAV_TEXTS = ["Good evening! The portal sync just finished. One new student was document-verified, "
                "and all seven progress sheets are up to date. Anything else I can check for you?",
                "Good evening. The portal sync finished a minute ago: one new student was "
                "document-verified, and all seven progress sheets are up to date. Shall I read "
                "you today's missing-information report?"]

# (language, style, text sent, what it should sound like, output file)
TTS_CASES = [
    ("ko", "aegyo",
     "짜잔! 제니예요~ 방금 포털 동기화가 끝났어용. 새로 서류 검증된 학생이 3명 있구요, 진행 시트 7개 모두 "
     "최신 상태예요! 헤헤, 또 궁금한 거 있으세용?",
     "짜잔! 제니예요! 방금 포털 동기화가 끝났어용. 새로 서류 검증된 학생이 세 명 있구요, 진행 시트 일곱 개 모두 "
     "최신 상태예요! 헤헤, 또 궁금한 거 있으세용?", "test_out_ko.ogg"),
    ("en", "neutral",
     "Good evening! The portal sync just finished. 3 new students were document-verified today, and all 7 "
     "progress sheets are up to date. Anything else I can check for you?",
     "Good evening! The portal sync just finished. three new students were document-verified today, and all "
     "seven progress sheets are up to date. Anything else I can check for you?", "test_out_en.ogg"),
]
SHORT_KO = ("ko", "aegyo", "네, 알겠어요! 바로 확인해 볼게요.", "네, 알겠어요! 바로 확인해 볼게요.", None)
# Korean numbers with a particle attached: (text sent, what the heard text must contain once spaces are removed;
# Whisper writes numbers as digits or as words)
PARTICLE_CASES = [
    ("브리핑은 18:05에 보내드려요~", ("6시5분에", "여섯시오분에")),
    ("마감일은 2026-09-27까지예요!", ("9월27일까지", "구월이십칠일까지")),
]
LONG_KO = ("짜잔! 오늘의 브리핑이에요. 새로 서류 검증된 학생은 세 명이고, 진행 시트 일곱 개는 모두 최신 상태예요. "
           "등록금 납부 기한이 다가온 학생은 다섯 명이에요. 여권 정보가 맞지 않는 학생은 두 명 있어요. "
           "내일 오전 열 시에는 한양대 입학 서류 마감이 있어요. 상담 문의는 오늘 열두 건 들어왔고요, "
           "그중 네 건은 이미 답장했어요. 헤헤, 또 궁금한 거 있으면 언제든지 물어봐 주세용!")


def norm(text):
    t = unicodedata.normalize("NFC", text).lower()
    t = "".join(" " if unicodedata.category(ch)[0] in ("P", "S") else ch for ch in t)
    return re.sub(r"\s+", "", t)


def cer(ref, hyp):
    r, h = norm(ref), norm(hyp)
    prev = list(range(len(h) + 1))
    for i, cr in enumerate(r, 1):
        cur = [i]
        for j, ch in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (cr != ch)))
        prev = cur
    return round(prev[-1] / max(1, len(r)), 3)


def smi_used_mib():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=20).stdout.strip()
    return int(out.splitlines()[0])


class VramWatch:
    """Samples device-wide used VRAM while a request runs."""

    def __init__(self):
        self.samples = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.samples.append(smi_used_mib())
            except Exception:
                pass
            time.sleep(0.2)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join()

    @property
    def peak(self):
        return max(self.samples) if self.samples else None


class HealthProbe:
    """Calls /health every 0.5 s while a long request runs: the watchdog must never see a hang."""

    def __init__(self):
        self.latencies, self.failures, self.busy_max = [], 0, 0.0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            t = time.perf_counter()
            try:
                r = requests.get(BASE + "/health", timeout=10)
                r.raise_for_status()
                self.latencies.append(time.perf_counter() - t)
                self.busy_max = max(self.busy_max, r.json().get("busy_s", 0.0))
            except Exception:
                self.failures += 1
            time.sleep(0.5)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join()


def post_stt(path, name=None, mime="audio/wav"):
    with open(path, "rb") as f, VramWatch() as vw:
        t = time.perf_counter()
        r = requests.post(BASE + "/stt", files={"audio": (name or os.path.basename(path), f, mime)}, timeout=600)
        wall = time.perf_counter() - t
    return r, wall, vw.peak


def audio_stats(data):
    wav, sr = sf.read(io.BytesIO(data), dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    hop = int(sr * 0.01)
    fr = np.sqrt(np.mean(wav[: len(wav) // hop * hop].reshape(-1, hop) ** 2, axis=1))
    voiced = np.where(fr >= 0.03 * np.percentile(fr, 95))[0]
    return {"sr": sr, "duration_s": round(len(wav) / sr, 2), "channels": 1,
            "rms_dbfs": round(20 * np.log10(np.sqrt(np.mean(wav ** 2)) + 1e-9), 1),
            "voiced_rms_dbfs": round(20 * np.log10(np.sqrt(np.mean(fr[voiced] ** 2)) + 1e-9), 1),
            "peak_dbfs": round(20 * np.log10(np.max(np.abs(wav)) + 1e-9), 1),
            "lead_silence_s": round(voiced[0] * 0.01, 2), "trail_silence_s": round((len(fr) - 1 - voiced[-1]) * 0.01, 2)}


def main():
    report = {"when": time.strftime("%Y-%m-%d %H:%M:%S")}
    ok = True
    for f in ("test_out_ko.ogg", "test_out_en.ogg"):
        if os.path.exists(os.path.join(HERE, f)):
            os.remove(os.path.join(HERE, f))

    def check(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}", flush=True)
        report.setdefault("checks", []).append({"check": name, "pass": bool(cond), "detail": str(detail)})

    t = time.perf_counter()
    h = requests.get(BASE + "/health", timeout=10)
    body = h.json()
    check("health 200 + contract keys", h.status_code == 200
          and {"ok", "stt", "tts", "device", "tts_on_gpu"} <= set(body) and body["ok"] is True
          and body.get("busy_s") == 0, f"{body} in {time.perf_counter() - t:.3f} s")
    report["health_before"] = body
    report["vram_idle_mib"] = smi_used_mib()
    print("VRAM used, idle (device-wide):", report["vram_idle_mib"], "MiB", flush=True)

    # Telegram sends voice notes as OGG/Opus: make one from the approved Korean sample
    wav, sr = sf.read(KO_WAV, dtype="float32")
    import soxr
    ogg_in = os.path.join(HERE, "test_in_ko.ogg")
    sf.write(ogg_in, soxr.resample(wav, sr, 48000), 48000, format="OGG", subtype="OPUS")

    report["stt"] = []
    for path, ref, lang, mime in [(KO_WAV, KO_WAV_TEXT, "ko", "audio/wav"), (ogg_in, KO_WAV_TEXT, "ko", "audio/ogg"),
                                  (EN_WAVS[0], EN_WAV_TEXTS[0], "en", "audio/wav"),
                                  (EN_WAVS[1], EN_WAV_TEXTS[1], "en", "audio/wav")]:
        r, wall, peak = post_stt(path, mime=mime)
        j = r.json()
        row = {"file": os.path.basename(path), "status": r.status_code, **j, "wall_s": round(wall, 2),
               "cer": cer(ref, j.get("text", "")), "vram_peak_mib": peak}
        report["stt"].append(row)
        check(f"stt {os.path.basename(path)}", r.status_code == 200 and set(j) == {"text", "language", "duration_s", "seconds"}
              and j["language"] == lang and row["cer"] < 0.1,
              f"lang={j.get('language')} cer={row['cer']} dur={j.get('duration_s')} stt={j.get('seconds')}s "
              f"wall={wall:.2f}s vram_peak={peak} MiB :: {j.get('text')}")

    # a voice note with nothing said: must not invent words, and must still answer with en or ko
    silence = io.BytesIO()
    sf.write(silence, np.zeros(16000 * 3, dtype=np.float32), 16000, format="WAV")
    r = requests.post(BASE + "/stt", files={"audio": ("silence.wav", silence.getvalue(), "audio/wav")}, timeout=300)
    j = r.json()
    report["stt_silence"] = j
    check("stt 3 s of silence", r.status_code == 200 and len(j.get("text", "x")) <= 10 and j.get("language") in ("en", "ko"),
          json.dumps(j, ensure_ascii=False))

    report["tts"] = []
    for lang, style, text, expect, out in TTS_CASES + [SHORT_KO, TTS_CASES[0]]:
        with VramWatch() as vw, HealthProbe() as hp:
            t = time.perf_counter()
            r = requests.post(BASE + "/tts", json={"text": text, "language": lang, "style": style}, timeout=900)
            wall = time.perf_counter() - t
        row = {"language": lang, "style": style, "chars": len(text), "status": r.status_code, "wall_s": round(wall, 2),
               "x_duration": r.headers.get("X-Duration"), "x_seconds": r.headers.get("X-Seconds"),
               "content_type": r.headers.get("Content-Type"), "bytes": len(r.content), "vram_peak_mib": vw.peak,
               "health_during_max_s": round(max(hp.latencies), 3) if hp.latencies else None,
               "health_during_failures": hp.failures, "health_busy_max_s": hp.busy_max}
        if r.status_code == 200:
            row.update(audio_stats(r.content))
            if out and not os.path.exists(os.path.join(HERE, out)):
                with open(os.path.join(HERE, out), "wb") as f:
                    f.write(r.content)
                row["saved"] = out
            back = requests.post(BASE + "/stt", files={"audio": ("reply.ogg", r.content, "audio/ogg")}, timeout=600).json()
            row.update(heard=back.get("text"), heard_language=back.get("language"), roundtrip_cer=cer(expect, back.get("text", "")))
        report["tts"].append(row)
        check(f"tts {lang}/{style} {len(text)} chars", r.status_code == 200 and row["content_type"] == "audio/ogg"
              and row.get("sr") in (24000, 48000) and row.get("heard_language") == lang and row.get("roundtrip_cer", 1) < 0.15
              and hp.failures == 0,
              f"render={row['x_seconds']}s wall={wall:.2f}s audio={row.get('duration_s')}s sr={row.get('sr')} "
              f"voiced={row.get('voiced_rms_dbfs')}dBFS peak={row.get('peak_dbfs')}dBFS lead/trail="
              f"{row.get('lead_silence_s')}/{row.get('trail_silence_s')}s vram_peak={vw.peak} MiB "
              f"health_max={row['health_during_max_s']}s cer={row.get('roundtrip_cer')} :: {row.get('heard')}")

    for f in ("test_out_ko.ogg", "test_out_en.ogg"):
        p = os.path.join(HERE, f)
        info = sf.info(p)
        check(f"{f} decodes", info.format == "OGG" and info.subtype == "OPUS" and info.frames > 0,
              f"{info.samplerate} Hz, {info.channels} ch, {info.frames / info.samplerate:.2f} s, {info.subtype}")

    # Korean times and dates with a particle attached, heard back through /stt
    report["tts_particles"] = []
    for text, wanted in PARTICLE_CASES:
        r = requests.post(BASE + "/tts", json={"text": text, "language": "ko", "style": "aegyo"}, timeout=300)
        heard = ""
        if r.status_code == 200:
            heard = requests.post(BASE + "/stt", files={"audio": ("p.ogg", r.content, "audio/ogg")}, timeout=300
                                  ).json().get("text", "")
        report["tts_particles"].append({"text": text, "status": r.status_code, "x_duration": r.headers.get("X-Duration"),
                                        "heard": heard})
        flat = re.sub(r"\s+", "", heard)
        check(f"tts particles {text!r}", r.status_code == 200 and any(w in flat for w in wanted),
              f"audio={r.headers.get('X-Duration')}s render={r.headers.get('X-Seconds')}s :: {heard}")

    # a client that gives up: the render stops and the lock is free again within seconds
    t = time.perf_counter()
    try:
        requests.post(BASE + "/tts", json={"text": LONG_KO, "language": "ko", "style": "aegyo"}, timeout=3)
        gave_up = False
    except requests.exceptions.ReadTimeout:
        gave_up = True
    freed_after, busy = None, None
    while time.perf_counter() - t < 60:
        busy = requests.get(BASE + "/health", timeout=10).json().get("busy_s")
        if busy == 0:
            freed_after = time.perf_counter() - t
            break
        time.sleep(0.25)
    report["client_gone"] = {"gave_up": gave_up, "lock_free_after_s": freed_after}
    check("client gives up after 3 s -> render stops, lock free", gave_up and freed_after is not None
          and freed_after < 12, f"lock free {freed_after if freed_after is None else round(freed_after, 1)} s after "
                                f"the request was sent ({len(LONG_KO)} chars)")

    # error answers: JSON {"error": ...}
    r = requests.post(BASE + "/tts", json={"text": "가" * 601, "language": "ko", "style": "aegyo"}, timeout=30)
    check("tts 601 chars -> 413", r.status_code == 413 and "error" in r.json(), r.text)
    r = requests.post(BASE + "/tts", json={"text": "hi", "language": "bn", "style": "neutral"}, timeout=30)
    check("tts bad language -> 400", r.status_code == 400 and "error" in r.json(), r.text)
    r = requests.post(BASE + "/tts", data="not json", headers={"Content-Type": "application/json"}, timeout=30)
    check("tts not JSON -> 400", r.status_code == 400 and "error" in r.json(), r.text)
    r = requests.post(BASE + "/tts", data='{"text": "hi", "language": "en"}', timeout=30)
    check("tts without JSON Content-Type -> 415", r.status_code == 415 and "error" in r.json(), r.text)
    r = requests.post(BASE + "/tts", json={"text": "hi", "language": "en"}, headers={"Origin": "https://example.com"},
                      timeout=30)
    check("tts from a web page (Origin) -> 403", r.status_code == 403 and "error" in r.json(), r.text)
    r = requests.get(BASE + "/health", headers={"Host": "rebound.example:8765"}, timeout=30)
    check("foreign Host (DNS rebinding) -> 403", r.status_code == 403 and "error" in r.json(), r.text)
    r = requests.post(BASE + "/stt", files={"file": ("x.ogg", b"abc", "audio/ogg")}, timeout=30)
    check("stt without 'audio' field -> 422", r.status_code == 422 and "error" in r.json(), r.text)
    r = requests.post(BASE + "/stt", files={"audio": ("x.ogg", b"this is not audio", "audio/ogg")}, timeout=30)
    check("stt garbage -> 400", r.status_code == 400 and "error" in r.json(), r.text)
    r = requests.get(BASE + "/nope", timeout=30)
    check("unknown path -> 404 JSON", r.status_code == 404 and "error" in r.json(), r.text)

    report["health_after"] = requests.get(BASE + "/health", timeout=10).json()
    report["vram_after_mib"] = smi_used_mib()
    print("health after:", report["health_after"], "VRAM used:", report["vram_after_mib"], "MiB", flush=True)
    report["all_pass"] = ok
    with open(os.path.join(HERE, "smoke_test.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("ALL PASS" if ok else "SOME CHECKS FAILED", flush=True)


if __name__ == "__main__":
    main()
