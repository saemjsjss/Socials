"""Print MeloTTS text-frontend output for the trial sentences (sanity check, offline)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HOME", os.path.join(HERE, "hf_cache"))
os.environ.setdefault("NLTK_DATA", os.path.join(HERE, "nltk_data"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
sys.path.insert(0, os.path.join(HERE, "src"))

import g2pkk.g2pkk as _g2pkk_mod  # noqa: E402
import mecab as _mecab  # noqa: E402

_g2pkk_mod.G2p.check_mecab = lambda self: None
_g2pkk_mod.G2p.get_mecab = lambda self: _mecab.MeCab()

from melo.text.cleaner import clean_text  # noqa: E402

KR = "안녕하세요. 방금 포털 동기화가 끝났습니다. 새로 서류 검증된 학생이 한 명 있고, 진행 시트 일곱 개가 모두 최신 상태입니다."
EN = "one new student was document-verified, and all seven progress sheets are up to date."
for lang, text in [("KR", KR), ("EN", EN)]:
    norm, phones, tones, w2p = clean_text(text, lang)
    print(lang, "norm:", norm)
    print(lang, "n_phones:", len(phones), "unk('_' inside):", phones[1:-1].count("_"))
    print(lang, "phones:", "".join(phones) if lang == "KR" else " ".join(phones))
