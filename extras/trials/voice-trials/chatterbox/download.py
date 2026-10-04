# Download Chatterbox multilingual checkpoints into the trial-local HF cache.
import os
import sys
from pathlib import Path

ROOT = Path(r"C:\Hangeul\JARVIS\voice-trials\chatterbox")
os.environ["HF_HOME"] = str(ROOT / "hf")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from huggingface_hub import snapshot_download

t3 = sys.argv[1] if len(sys.argv) > 1 else "t3_mtl23ls_v3.safetensors"
path = snapshot_download(
    repo_id="ResembleAI/chatterbox",
    repo_type="model",
    revision="main",
    allow_patterns=["ve.pt", t3, "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json", "conds.pt",
                    "Cangjie5_TC.json", "README.md"],
)
print("snapshot:", path)
total = 0
for p in sorted(Path(path).iterdir()):
    sz = p.stat().st_size
    total += sz
    print(f"  {p.name:45s} {sz/1e6:10.1f} MB")
print(f"total {total/1e9:.2f} GB")
