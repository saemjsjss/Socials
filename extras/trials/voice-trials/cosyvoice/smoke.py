"""CPU-only smoke test: imports + load CosyVoice-300M-SFT + list stock speakers (no GPU use)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HOME"] = os.path.join(HERE, "hf")
os.environ["MODELSCOPE_CACHE"] = os.path.join(HERE, "ms")
REPO = os.path.join(HERE, "repo")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "third_party", "Matcha-TTS"))

from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402

m = AutoModel(model_dir=os.path.join(REPO, "pretrained_models", "CosyVoice-300M-SFT"))
print("frontend:", repr(m.frontend.text_frontend), "sr:", m.sample_rate)
print("SPEAKERS:", m.list_available_spks())
