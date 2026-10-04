"""Read-only check of the Ollama registry: does each candidate tag exist, how big is it,
and what licence ships with it. Downloads only the manifest and the small licence/params
text layers, never the model weights."""
import json
import urllib.request
import urllib.error

CANDIDATES = ["qwen2.5:7b", "qwen2.5:3b", "qwen3:4b", "gemma3:4b", "qwen3:1.7b"]
REG = "https://registry.ollama.ai/v2/library"
ACCEPT = "application/vnd.docker.distribution.manifest.v2+json"


def get(url, accept=None, limit=None):
    req = urllib.request.Request(url, headers={"Accept": accept} if accept else {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(limit) if limit else r.read()


out = {}
for tag in CANDIDATES:
    name, ver = tag.split(":")
    info = {"tag": tag}
    try:
        man = json.loads(get(f"{REG}/{name}/manifests/{ver}", ACCEPT))
    except urllib.error.HTTPError as e:
        info["exists"] = False
        info["error"] = f"HTTP {e.code}"
        out[tag] = info
        continue
    info["exists"] = True
    total = 0
    for layer in man.get("layers", []):
        mt = layer["mediaType"].rsplit(".", 1)[-1]
        total += layer["size"]
        if mt == "model":
            info["weights_gb"] = round(layer["size"] / 1e9, 2)
        if mt in ("license", "params"):
            blob = get(f"{REG}/{name}/blobs/{layer['digest']}", limit=1500).decode("utf-8", "replace")
            if mt == "license":
                info.setdefault("license_heads", []).append(" ".join(blob.split())[:300])
            else:
                info["params"] = blob.strip()[:300]
    info["total_gb"] = round(total / 1e9, 2)
    out[tag] = info

with open("C:/Hangeul/JARVIS/brain-trial/registry.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(json.dumps(out, ensure_ascii=False, indent=2))
