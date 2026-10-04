"""Fetch licence info from primary sources: HF model cards/API + installed PyPI metadata."""
import os
import sys
import json
from importlib import metadata

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HOME", os.path.join(HERE, "hf_cache"))

from huggingface_hub import HfApi, hf_hub_download  # noqa: E402

api = HfApi()
repos = ["myshell-ai/MeloTTS-English", "myshell-ai/MeloTTS-Korean", "kykim/bert-kor-base",
         "google-bert/bert-base-uncased"]
out = {}
for r in repos:
    rec = {}
    try:
        info = api.model_info(r)
        card = info.card_data.to_dict() if info.card_data else {}
        rec["card_license"] = card.get("license")
        rec["license_tags"] = [t for t in (info.tags or []) if t.startswith("license:")]
        rec["files"] = [s.rfilename for s in (info.siblings or [])]
    except Exception as e:  # noqa: BLE001
        rec["error"] = repr(e)
    try:
        p = hf_hub_download(r, "README.md")
        with open(p, encoding="utf-8") as f:
            txt = f.read()
        rec["readme_head"] = txt[:600]
        low = txt.lower()
        idx = low.find("licen")
        rec["readme_license_ctx"] = txt[max(0, idx - 200): idx + 400] if idx >= 0 else None
    except Exception as e:  # noqa: BLE001
        rec["readme_error"] = repr(e)
    out[r] = rec

pkgs = ["g2pkk", "python-mecab-ko", "python-mecab-ko-dic", "g2p_en", "nltk", "transformers", "torch",
        "jamo", "anyascii", "num2words", "inflect", "txtsplit", "librosa", "soundfile", "cached_path"]
pm = {}
for p in pkgs:
    try:
        m = metadata.metadata(p)
        classifiers = [c for c in (m.get_all("Classifier") or []) if "License" in c]
        pm[p] = {"version": m.get("Version"), "License": (m.get("License") or "")[:120],
                 "License-Expression": m.get("License-Expression"), "classifiers": classifiers}
    except Exception as e:  # noqa: BLE001
        pm[p] = {"error": repr(e)}
out["_pypi"] = pm
json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
