"""CosyVoice trial renders for 'Jennie'.

usage:  python synth.py sft   -> CosyVoice-300M-SFT stock speakers (+ synthetic reference clips)
        python synth.py v2    -> CosyVoice2-0.5B zero-shot / instruct2 / cross-lingual from the SFT reference
        add 'cpu' as 2nd arg to force CPU.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "repo")
os.environ.setdefault("HF_HOME", os.path.join(HERE, "hf"))
os.environ.setdefault("MODELSCOPE_CACHE", os.path.join(HERE, "ms"))
os.environ.setdefault("TORCH_HOME", os.path.join(HERE, "torchhome"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "third_party", "Matcha-TTS"))

import gpulock  # noqa: E402

JOB = sys.argv[1]
FORCE_CPU = len(sys.argv) > 2 and sys.argv[2] == "cpu"

OUT_DIR = r"C:\Hangeul\JARVIS\voice-samples"
REF_DIR = os.path.join(HERE, "ref")
LOG = os.path.join(HERE, "renders.jsonl")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(REF_DIR, exist_ok=True)

from synth_texts import EN, KR_NEUTRAL, KR_AEGYO, REF_KO_TEXT, REF_EN_TEXT  # noqa: E402

device = "cpu"
if not FORCE_CPU:
    device = gpulock.acquire()
if device == "cpu":
    os.environ["CUDA_VISIBLE_DEVICES"] = ""

try:
    import numpy as np
    import soundfile as sf
    import torch
    from cosyvoice.cli.cosyvoice import AutoModel
    from cosyvoice.utils.common import set_all_random_seed

    print("torch", torch.__version__, "cuda available:", torch.cuda.is_available(), flush=True)

    def render(gen_fn, path, meta, seed=1234):
        set_all_random_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        chunks = [o["tts_speech"].detach().cpu() for o in gen_fn()]
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        dt = time.time() - t0
        wav = torch.cat(chunks, dim=1).squeeze(0).numpy().astype(np.float32)
        sf.write(path, wav, model.sample_rate, subtype="PCM_16")
        peak = torch.cuda.max_memory_allocated() / 1024 ** 3 if torch.cuda.is_available() else 0.0
        rec = {"file": path, "synth_s": round(dt, 2), "device": "cuda" if torch.cuda.is_available() else "cpu",
               "sr": model.sample_rate, "dur_s": round(len(wav) / model.sample_rate, 2),
               "peak_alloc_gb": round(peak, 2), "segments": len(chunks), **meta}
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return path

    def out(setting, kind):
        return os.path.join(OUT_DIR, f"real__cosyvoice__{setting}__{kind}.wav")

    if JOB == "sft":
        model = AutoModel(model_dir=os.path.join(REPO, "pretrained_models", "CosyVoice-300M-SFT"))
        spks = model.list_available_spks()
        print("SPEAKERS:", spks, flush=True)
        with open(os.path.join(HERE, "sft_speakers.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(spks))
        ko, en = "韩语女", "英文女"
        assert ko in spks and en in spks, spks
        m = {"model": "CosyVoice-300M-SFT", "mode": "sft"}
        render(lambda: model.inference_sft(KR_NEUTRAL, ko), out("300m-sft-korean-female", "kr-neutral"), {**m, "spk": ko})
        render(lambda: model.inference_sft(KR_AEGYO, ko), out("300m-sft-korean-female", "kr-aegyo"), {**m, "spk": ko})
        render(lambda: model.inference_sft(EN, en), out("300m-sft-english-female", "en"), {**m, "spk": en})
        # synthetic reference clips for CosyVoice2 zero-shot (kept in the trial folder, not delivered as samples)
        render(lambda: model.inference_sft(REF_KO_TEXT, ko), os.path.join(REF_DIR, "ref_sft_ko_female.wav"), {**m, "spk": ko, "ref": True})
        render(lambda: model.inference_sft(REF_EN_TEXT, en), os.path.join(REF_DIR, "ref_sft_en_female.wav"), {**m, "spk": en, "ref": True})

    elif JOB == "v2":
        model = AutoModel(model_dir=os.path.join(REPO, "pretrained_models", "CosyVoice2-0.5B"))
        ref_ko = os.path.join(REF_DIR, "ref_sft_ko_female.wav")
        ref_en = os.path.join(REF_DIR, "ref_sft_en_female.wav")
        m = {"model": "CosyVoice2-0.5B"}
        render(lambda: model.inference_zero_shot(KR_NEUTRAL, REF_KO_TEXT, ref_ko),
               out("v2-zeroshot-krfemale", "kr-neutral"), {**m, "mode": "zero_shot", "ref": "ref_sft_ko_female"})
        render(lambda: model.inference_zero_shot(KR_AEGYO, REF_KO_TEXT, ref_ko),
               out("v2-zeroshot-krfemale", "kr-aegyo"), {**m, "mode": "zero_shot", "ref": "ref_sft_ko_female"})
        for tag, instr in [("sajiao", "用撒娇可爱的语气说这句话<|endofprompt|>"),
                           ("happy", "用非常开心的语气说这句话<|endofprompt|>")]:
            render(lambda: model.inference_instruct2(KR_AEGYO, instr, ref_ko),
                   out(f"v2-instruct-{tag}-krfemale", "kr-aegyo"),
                   {**m, "mode": "instruct2", "instruct": instr, "ref": "ref_sft_ko_female"})
        render(lambda: model.inference_cross_lingual(EN, ref_ko),
               out("v2-crosslingual-krfemale", "en"), {**m, "mode": "cross_lingual", "ref": "ref_sft_ko_female"})
        render(lambda: model.inference_zero_shot(EN, REF_EN_TEXT, ref_en),
               out("v2-zeroshot-enfemale", "en"), {**m, "mode": "zero_shot", "ref": "ref_sft_en_female"})
    elif JOB == "v2b":
        # The stock 300M-SFT Korean speaker is barely intelligible (Whisper CER ~0.5-0.9), so its clip is only
        # usable as a *timbre* prompt. Cross-lingual mode ignores the prompt transcript -> clean Korean content.
        import whisper
        from textmetrics import cer
        model = AutoModel(model_dir=os.path.join(REPO, "pretrained_models", "CosyVoice2-0.5B"))
        ref_ko = os.path.join(REF_DIR, "ref_sft_ko_female.wav")
        m = {"model": "CosyVoice2-0.5B"}
        # 1) clean Korean reference in the same timbre: best of 3 seeds by Whisper CER (CPU)
        asr = whisper.load_model("small", device="cpu", download_root=os.path.join(HERE, "whisper_models"))
        best = None
        for seed in (1234, 7, 42):
            p = os.path.join(REF_DIR, f"ref_v2xl_ko_female_s{seed}.wav")
            render(lambda: model.inference_cross_lingual(REF_KO_TEXT, ref_ko), p,
                   {**m, "mode": "cross_lingual", "ref": "ref_sft_ko_female", "is_ref": True}, seed=seed)
            hyp = asr.transcribe(whisper.load_audio(p), language="ko", fp16=False, temperature=0.0)["text"]
            c = cer(REF_KO_TEXT, hyp)
            print(f"[ref] seed {seed} cer {c:.3f} :: {hyp}", flush=True)
            if best is None or c < best[0]:
                best = (c, p)
        ref_clean = os.path.join(REF_DIR, "ref_v2xl_ko_female.wav")
        import shutil
        shutil.copyfile(best[1], ref_clean)
        print(f"[ref] picked {best[1]} (cer {best[0]:.3f})", flush=True)
        del asr
        # 2) cross-lingual Korean (timbre from the stock SFT Korean female)
        render(lambda: model.inference_cross_lingual(KR_NEUTRAL, ref_ko),
               out("v2-crosslingual-krfemale", "kr-neutral"), {**m, "mode": "cross_lingual", "ref": "ref_sft_ko_female"})
        render(lambda: model.inference_cross_lingual(KR_AEGYO, ref_ko),
               out("v2-crosslingual-krfemale", "kr-aegyo"), {**m, "mode": "cross_lingual", "ref": "ref_sft_ko_female"})
        # 3) zero-shot again, now with a reference whose audio matches its transcript
        render(lambda: model.inference_zero_shot(KR_NEUTRAL, REF_KO_TEXT, ref_clean),
               out("v2-zeroshot-krfemale", "kr-neutral"), {**m, "mode": "zero_shot", "ref": "ref_v2xl_ko_female"})
        render(lambda: model.inference_zero_shot(KR_AEGYO, REF_KO_TEXT, ref_clean),
               out("v2-zeroshot-krfemale", "kr-aegyo"), {**m, "mode": "zero_shot", "ref": "ref_v2xl_ko_female"})
        # 4) instruct 'happy' + fine-grained [laughter] on the giggle, clean reference
        laugh = KR_AEGYO.replace("헤헤,", "[laughter]헤헤,")
        render(lambda: model.inference_instruct2(laugh, "用非常开心的语气说这句话<|endofprompt|>", ref_clean),
               out("v2-instruct-happy-laugh-krfemale", "kr-aegyo"),
               {**m, "mode": "instruct2", "instruct": "用非常开心的语气说这句话<|endofprompt|> + [laughter]", "ref": "ref_v2xl_ko_female"})
    elif JOB == "v3":
        # Fun-CosyVoice3-0.5B-2512 (Apache-2.0). Prompts need the 'You are a helpful assistant.<|endofprompt|>' prefix.
        model = AutoModel(model_dir=os.path.join(REPO, "pretrained_models", "Fun-CosyVoice3-0.5B"))
        ref_clean = os.path.join(REF_DIR, "ref_v2xl_ko_female.wav")
        SYS = "You are a helpful assistant."
        m = {"model": "Fun-CosyVoice3-0.5B-2512"}
        render(lambda: model.inference_zero_shot(KR_NEUTRAL, f"{SYS}<|endofprompt|>{REF_KO_TEXT}", ref_clean, stream=False),
               out("v3-zeroshot-krfemale", "kr-neutral"), {**m, "mode": "zero_shot", "ref": "ref_v2xl_ko_female"})
        render(lambda: model.inference_zero_shot(KR_AEGYO, f"{SYS}<|endofprompt|>{REF_KO_TEXT}", ref_clean, stream=False),
               out("v3-zeroshot-krfemale", "kr-aegyo"), {**m, "mode": "zero_shot", "ref": "ref_v2xl_ko_female"})
        for tag, instr in [("happy", f"{SYS} 请非常开心地说一句话。<|endofprompt|>"),
                           ("sajiao", f"{SYS} 请用撒娇、可爱的语气说这句话。<|endofprompt|>")]:
            render(lambda: model.inference_instruct2(KR_AEGYO, instr, ref_clean, stream=False),
                   out(f"v3-instruct-{tag}-krfemale", "kr-aegyo"),
                   {**m, "mode": "instruct2", "instruct": instr, "ref": "ref_v2xl_ko_female"})
        render(lambda: model.inference_cross_lingual(f"{SYS}<|endofprompt|>{EN}", ref_clean, stream=False),
               out("v3-crosslingual-krfemale", "en"), {**m, "mode": "cross_lingual", "ref": "ref_v2xl_ko_female"})
    else:
        raise SystemExit("unknown job " + JOB)
finally:
    if device == "cuda":
        gpulock.release()
