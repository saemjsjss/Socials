import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
last = {}
for line in open(os.path.join(HERE, "renders.jsonl"), encoding="utf-8"):
    r = json.loads(line)
    last[r["file"]] = r
ver = {v["file"]: v for v in json.load(open(os.path.join(HERE, "verify_results.json"), encoding="utf-8"))}
for f, r in sorted(last.items()):
    if "voice-samples" not in f:
        continue
    v = ver.get(f, {})
    print(os.path.basename(f), r["device"], r["synth_s"], v.get("dur_s"), v.get("sr"), v.get("cer"), r.get("peak_alloc_gb"), v.get("ok"))
