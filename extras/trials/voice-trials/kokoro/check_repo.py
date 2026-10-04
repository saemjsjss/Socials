"""Inspect the hexgrad/Kokoro-82M repo: licence metadata, voice list, model card text."""
import json
import re
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

REPO = "hexgrad/Kokoro-82M"
OUT = Path(__file__).parent / "repo_info"
OUT.mkdir(exist_ok=True)

api = HfApi()
info = api.model_info(REPO)
card = info.card_data.to_dict() if info.card_data else {}
print("sha:", info.sha)
print("card_data:", json.dumps(card, indent=1))
tags = [t for t in (info.tags or []) if "license" in t]
print("license tags:", tags)

files = api.list_repo_files(REPO)
voices = sorted(f for f in files if f.startswith("voices/"))
print("n files:", len(files))
print("voices:", len(voices))
print([Path(v).stem for v in voices])
print("british:", [Path(v).stem for v in voices if Path(v).stem[:2] in ("bf", "bm")])

readme = Path(hf_hub_download(REPO, "README.md"))
(OUT / "README.md").write_text(readme.read_text(encoding="utf-8"), encoding="utf-8")
txt = readme.read_text(encoding="utf-8")
print("README length:", len(txt))
for kw in ["icense", "Korean", "korean", "language", "Apache"]:
    for m in re.finditer(kw, txt):
        s = max(0, m.start() - 150)
        print(f"--- [{kw}] ...{txt[s:m.end()+150]!r}")
        break

try:
    voices_md = Path(hf_hub_download(REPO, "VOICES.md"))
    (OUT / "VOICES.md").write_text(voices_md.read_text(encoding="utf-8"), encoding="utf-8")
    print("VOICES.md saved")
except Exception as e:
    print("no VOICES.md:", e)
