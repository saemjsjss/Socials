# Build a clean reference clip for Chatterbox voice conditioning from the
# MeloTTS KR stock voice output (synthetic, MIT-licensed stock voice).
import numpy as np
import librosa
import soundfile as sf
from pathlib import Path

SRC = Path(r"C:\Hangeul\JARVIS\voice-samples\melotts__kr__kr.wav")
OUT_DIR = Path(r"C:\Hangeul\JARVIS\voice-trials\chatterbox\ref")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT = OUT_DIR / "melotts_kr_ref_24k.wav"

info = sf.info(str(SRC))
print("source:", SRC.name, info.samplerate, "Hz", info.channels, "ch", round(info.duration, 2), "s")

wav, sr = librosa.load(str(SRC), sr=24000, mono=True)
# trim leading/trailing silence
wav, idx = librosa.effects.trim(wav, top_db=35)
# keep at most 10 s (Chatterbox uses <=10 s of the prompt for the decoder, 6 s for T3)
max_len = 10 * 24000
if len(wav) > max_len:
    # cut at a low-energy point near 10 s to avoid chopping mid-syllable
    frame = 480
    rms = librosa.feature.rms(y=wav, frame_length=frame * 2, hop_length=frame)[0]
    lo = int(8.5 * 24000 / frame)
    hi = min(len(rms) - 1, int(10 * 24000 / frame))
    cut = (lo + int(np.argmin(rms[lo:hi + 1]))) * frame
    wav = wav[:cut]
# peak normalise to -1 dBFS
peak = float(np.max(np.abs(wav)))
if peak > 0:
    wav = wav / peak * 10 ** (-1 / 20)
sf.write(str(OUT), wav, 24000, subtype="PCM_16")
print("wrote:", OUT, round(len(wav) / 24000, 2), "s")
