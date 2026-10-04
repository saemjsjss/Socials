"""Read the full licence text shipped with qwen2.5:3b and gemma3:4b and print the clauses about
commercial use."""
import json
import re
import urllib.request

REG = "https://registry.ollama.ai/v2/library"
ACCEPT = "application/vnd.docker.distribution.manifest.v2+json"


def get(url, accept=None):
    req = urllib.request.Request(url, headers={"Accept": accept} if accept else {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


for tag in ["qwen2.5:3b", "gemma3:4b"]:
    name, ver = tag.split(":")
    man = json.loads(get(f"{REG}/{name}/manifests/{ver}", ACCEPT))
    for layer in man["layers"]:
        if layer["mediaType"].endswith(".license"):
            text = get(f"{REG}/{name}/blobs/{layer['digest']}").decode("utf-8", "replace")
            with open(f"C:/Hangeul/JARVIS/brain-trial/license_{name}_{ver}.txt", "w", encoding="utf-8") as f:
                f.write(text)
            flat = " ".join(text.split())
            print(f"===== {tag}: {len(flat)} chars")
            for m in re.finditer(r"[^.]*\b(commercial|non-commercial|Commercial)\b[^.]*\.", flat):
                print("-", m.group(0).strip()[:400])
