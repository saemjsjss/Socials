"""CPU timing benchmark (no files written): 3 reps per voice, offline."""
import os
import sys
import time
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HOME", os.path.join(HERE, "hf_cache"))
os.environ.setdefault("NLTK_DATA", os.path.join(HERE, "nltk_data"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, os.path.join(HERE, "src"))

import g2pkk.g2pkk as _g2pkk_mod  # noqa: E402
import mecab as _mecab  # noqa: E402

_g2pkk_mod.G2p.check_mecab = lambda self: None
_g2pkk_mod.G2p.get_mecab = lambda self: _mecab.MeCab()

from melo.api import TTS  # noqa: E402

EN = ("Good evening. The portal sync finished a minute ago: one new student was "
      "document-verified, and all seven progress sheets are up to date. Shall I read "
      "you today's missing-information report?")
KR = ("안녕하세요. 방금 포털 동기화가 끝났습니다. 새로 서류 검증된 학생이 한 명 있고, "
      "진행 시트 일곱 개가 모두 최신 상태입니다.")

for lang, spk, text in [("EN", "EN-BR", EN), ("EN", "EN-US", EN), ("KR", "KR", KR)]:
    m = TTS(language=lang, device="cpu")
    sid = m.hps.data.spk2id[spk]
    m.tts_to_file("Warm up." if lang == "EN" else "안녕하세요.", sid, output_path=None, quiet=True)
    ts = []
    for _ in range(3):
        t0 = time.perf_counter()
        a = m.tts_to_file(text, sid, output_path=None, quiet=True)
        ts.append(time.perf_counter() - t0)
    dur = len(a) / m.hps.data.sampling_rate
    print(f"{spk}: audio {dur:.2f}s  synth min {min(ts):.2f}s  median {statistics.median(ts):.2f}s  "
          f"max {max(ts):.2f}s  best RTF {min(ts)/dur:.3f}", flush=True)
