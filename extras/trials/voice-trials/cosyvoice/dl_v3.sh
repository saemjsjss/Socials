#!/bin/sh
BASE=/c/Hangeul/JARVIS/voice-trials/cosyvoice/repo/pretrained_models
repo=FunAudioLLM/Fun-CosyVoice3-0.5B-2512
for f in CosyVoice-BlankEN/config.json CosyVoice-BlankEN/generation_config.json CosyVoice-BlankEN/merges.txt CosyVoice-BlankEN/model.safetensors CosyVoice-BlankEN/tokenizer_config.json CosyVoice-BlankEN/vocab.json campplus.onnx config.json configuration.json cosyvoice3.yaml hift.pt speech_tokenizer_v3.onnx flow.pt llm.pt README.md; do
  out="$BASE/Fun-CosyVoice3-0.5B/$f"
  mkdir -p "$(dirname "$out")"
  if [ -s "$out" ]; then echo "skip $f"; continue; fi
  curl -sSL --retry 3 -o "$out.part" "https://huggingface.co/$repo/resolve/main/$f" && mv "$out.part" "$out" && echo "ok $f $(stat -c %s "$out")" || echo "FAIL $f"
done
echo DONE
