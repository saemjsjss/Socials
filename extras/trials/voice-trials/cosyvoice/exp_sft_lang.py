"""A/B: CosyVoice-300M-SFT 韩语女 with and without the <|ko|> language tag (renders to exp/, not samples)."""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "repo")
os.environ["HF_HOME"] = os.path.join(HERE, "hf")
os.environ["MODELSCOPE_CACHE"] = os.path.join(HERE, "ms")
for p in (HERE, os.path.join(HERE, "stubs"), REPO, os.path.join(REPO, "third_party", "Matcha-TTS")):
    sys.path.insert(0, p)
import gpulock  # noqa: E402

dev = gpulock.acquire()
if dev == "cpu":
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
try:
    import numpy as np
    import soundfile as sf
    import torch
    from cosyvoice.cli.cosyvoice import AutoModel
    from cosyvoice.utils.common import set_all_random_seed
    from synth_texts import KR_NEUTRAL, KR_AEGYO, REF_KO_TEXT

    EXP = os.path.join(HERE, "exp")
    os.makedirs(EXP, exist_ok=True)
    m = AutoModel(model_dir=os.path.join(REPO, "pretrained_models", "CosyVoice-300M-SFT"))
    tok = m.frontend.tokenizer
    print("tokens plain:", len(tok.encode(KR_NEUTRAL, allowed_special="all")),
          "tagged:", tok.encode("<|ko|>" + KR_NEUTRAL, allowed_special="all")[:3], flush=True)
    for tag in ("plain", "ko"):
        for kind, text in (("kr-neutral", KR_NEUTRAL), ("kr-aegyo", KR_AEGYO), ("ref", REF_KO_TEXT)):
            t = text if tag == "plain" else "<|ko|>" + text
            for seed in (1234, 7):
                set_all_random_seed(seed)
                t0 = time.time()
                wav = torch.cat([o["tts_speech"].cpu() for o in m.inference_sft(t, "韩语女")], dim=1).squeeze(0).numpy()
                path = os.path.join(EXP, f"sft__{tag}__s{seed}__{kind}.wav")
                sf.write(path, wav.astype(np.float32), m.sample_rate, subtype="PCM_16")
                print(path, round(time.time() - t0, 2), "s", round(len(wav) / m.sample_rate, 2), "dur", flush=True)
finally:
    if dev == "cuda":
        gpulock.release()
