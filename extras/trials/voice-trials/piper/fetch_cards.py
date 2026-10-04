"""Download MODEL_CARD for every en_GB and ko_KR Piper voice and print them."""
import json
import urllib.request
from pathlib import Path

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
here = Path(__file__).parent
voices = json.loads((here / "voices.json").read_text(encoding="utf-8"))
cards = here / "model_cards"
cards.mkdir(exist_ok=True)

for key, v in sorted(voices.items()):
    code = v["language"]["code"]
    if not (code.startswith("en_GB") or code.startswith("ko_KR")):
        continue
    card_paths = [p for p in v["files"] if p.endswith("MODEL_CARD")]
    for p in card_paths:
        try:
            with urllib.request.urlopen(BASE + p, timeout=60) as r:
                txt = r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            txt = f"FETCH ERROR: {e}"
        (cards / f"{key}.MODEL_CARD.txt").write_text(txt, encoding="utf-8")
        print("=" * 20, key, "=" * 20)
        print(txt.strip())
