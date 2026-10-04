"""Real VRAM cost of one model at num_ctx 4096: nvidia-smi before, after load, after a generation
(compute buffers allocated), compared with /api/ps. Unloads the model at the end."""
import json
import subprocess
import sys
import time
import urllib.request

OLLAMA = "http://127.0.0.1:11434"


def call(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(OLLAMA + path, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def smi():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout
    return int(out.strip().splitlines()[0])


for model in sys.argv[1:]:
    before = smi()
    call("/api/generate", {"model": model, "prompt": "", "keep_alive": "2m", "options": {"num_ctx": 4096}})
    loaded = smi()
    payload = {"model": model, "prompt": "Say hello in Korean.", "stream": False, "keep_alive": "2m",
               "options": {"num_ctx": 4096, "num_predict": 20, "temperature": 0.3, "seed": 42}}
    if model.startswith("qwen3"):
        payload["think"] = False
    call("/api/generate", payload)
    after = smi()
    p = next((m for m in call("/api/ps")["models"] if m["name"] == model), {})
    call("/api/generate", {"model": model, "keep_alive": 0})
    time.sleep(3)
    print(json.dumps({"model": model, "smi_before_mib": before, "smi_loaded_mib": loaded,
                      "smi_after_gen_mib": after, "smi_delta_gib": round((after - before) / 1024, 2),
                      "ps_size_gib": round(p.get("size", 0) / 2**30, 2),
                      "ps_size_vram_gib": round(p.get("size_vram", 0) / 2**30, 2),
                      "smi_after_unload_mib": smi()}))
