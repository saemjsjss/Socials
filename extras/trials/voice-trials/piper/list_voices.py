"""Fetch piper-voices catalogue and list en_GB and any Korean voices."""
import json
import urllib.request
from pathlib import Path

URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
out = Path(__file__).with_name("voices.json")
with urllib.request.urlopen(URL, timeout=60) as r:
    data = r.read()
out.write_bytes(data)
voices = json.loads(data)
print("total voices:", len(voices))

langs = sorted({v["language"]["code"] for v in voices.values()})
print("language codes:", ", ".join(langs))

for key, v in sorted(voices.items()):
    code = v["language"]["code"]
    if code.startswith("en_GB") or code.lower().startswith("ko"):
        size = sum(f.get("size_bytes", 0) for f in v["files"].values())
        onnx = [p for p in v["files"] if p.endswith(".onnx")]
        print(f"{key:40s} quality={v['quality']:7s} speakers={v['num_speakers']:4d} "
              f"size={size/1e6:6.1f}MB  {onnx[0] if onnx else ''}")
