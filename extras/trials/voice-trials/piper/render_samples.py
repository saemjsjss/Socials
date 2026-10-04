"""Render the final Piper samples (CPU only) into C:\\Hangeul\\JARVIS\\voice-samples and verify them."""
import json
import time
import wave
from pathlib import Path

import soundfile as sf
from piper import PiperVoice, SynthesisConfig

HERE = Path(__file__).parent
VOICES = HERE / "voices"
SAMPLES = Path(r"C:\Hangeul\JARVIS\voice-samples")
SAMPLES.mkdir(parents=True, exist_ok=True)

EN = ("Good evening. The portal sync finished a minute ago: one new student was "
      "document-verified, and all seven progress sheets are up to date. Shall I read "
      "you today's missing-information report?")
KR = ("안녕하세요. 방금 포털 동기화가 끝났습니다. 새로 서류 검증된 학생이 한 명 있고, "
      "진행 시트 일곱 개가 모두 최신 상태입니다.")

# (model name, speaker label or None, language tag, text)
JOBS = [
    ("en_GB-cori-high", None, "en", EN),
    ("en_GB-northern_english_male-medium", None, "en", EN),
    ("en_GB-vctk-medium", "p226", "en", EN),
    ("ko_KR-kss-medium", None, "kr", KR),
]

results = []
for model, spk, lang, text in JOBS:
    t0 = time.perf_counter()
    voice = PiperVoice.load(VOICES / f"{model}.onnx", use_cuda=False)
    load_s = time.perf_counter() - t0

    voice_id = model.lower() + (f"-{spk}" if spk else "")
    out = SAMPLES / f"piper__{voice_id}__{lang}.wav"
    cfg = SynthesisConfig(speaker_id=voice.config.speaker_id_map[spk]) if spk else None

    if lang == "kr":
        print("KR phonemes:", voice.phonemize(text))

    t1 = time.perf_counter()
    with wave.open(str(out), "wb") as wf:
        voice.synthesize_wav(text, wf, syn_config=cfg)
    synth_s = time.perf_counter() - t1

    # Verify with stdlib wave and with soundfile.
    with wave.open(str(out), "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
    data, sr2 = sf.read(str(out))
    dur = n / sr
    peak = float(abs(data).max()) if len(data) else 0.0
    ok = dur > 0 and sr == sr2 and 8000 <= sr <= 48000 and peak > 0.01
    rec = {
        "file": str(out), "voice_id": voice_id, "language": lang, "sample_rate": sr,
        "channels": ch, "sample_width_bytes": sw, "duration_s": round(dur, 2),
        "load_s": round(load_s, 2), "synth_s": round(synth_s, 2),
        "rtf": round(synth_s / dur, 3) if dur else None, "peak": round(peak, 3),
        "size_bytes": out.stat().st_size, "verified": ok,
    }
    results.append(rec)
    print(json.dumps(rec, ensure_ascii=False))

(HERE / "render_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
