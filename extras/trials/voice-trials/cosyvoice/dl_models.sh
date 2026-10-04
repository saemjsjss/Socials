#!/bin/sh
# Download only the inference files for CosyVoice-300M-SFT and CosyVoice2-0.5B from Hugging Face.
BASE=/c/Hangeul/JARVIS/voice-trials/cosyvoice/repo/pretrained_models
dl() {
  repo=$1; f=$2
  out="$BASE/$(basename $repo)/$f"
  mkdir -p "$(dirname "$out")"
  if [ -s "$out" ]; then echo "skip $repo/$f"; return; fi
  curl -sSL --retry 3 -o "$out" "https://huggingface.co/$repo/resolve/main/$f" && echo "ok $repo/$f $(stat -c %s "$out")" || echo "FAIL $repo/$f"
}
for f in campplus.onnx config.json configuration.json cosyvoice.yaml flow.pt hift.pt llm.pt speech_tokenizer_v1.onnx spk2info.pt README.md; do
  dl FunAudioLLM/CosyVoice-300M-SFT $f
done
for f in CosyVoice-BlankEN/config.json CosyVoice-BlankEN/generation_config.json CosyVoice-BlankEN/merges.txt CosyVoice-BlankEN/model.safetensors CosyVoice-BlankEN/tokenizer_config.json CosyVoice-BlankEN/vocab.json campplus.onnx config.json configuration.json cosyvoice2.yaml flow.pt hift.pt llm.pt speech_tokenizer_v2.onnx README.md; do
  dl FunAudioLLM/CosyVoice2-0.5B $f
done
echo DONE
