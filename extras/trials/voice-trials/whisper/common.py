"""Shared helpers for the Jennie "ears" check (faster-whisper STT + CER)."""
import os
import re
import sys
import time
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ["HF_HOME"] = os.path.join(ROOT, "hf_home")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Make the pip-installed CUDA libs (cuBLAS / cuDNN / NVRTC) visible to CTranslate2.
_SP = os.path.join(ROOT, "venv", "Lib", "site-packages", "nvidia")
for _sub in ("cublas", "cudnn", "cuda_nvrtc"):
    _bin = os.path.join(_SP, _sub, "bin")
    if os.path.isdir(_bin):
        os.environ["PATH"] = _bin + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(_bin)
        except OSError:
            pass

GPU_LOCK = r"C:\Hangeul\JARVIS\voice-trials\gpu.lock"

EXPECTED = {
    "en": "Good evening! The portal sync just finished. One new student was document-verified, "
          "and all seven progress sheets are up to date. Anything else I can check for you?",
    "kr-neutral": "안녕하세요. 방금 포털 동기화가 끝났습니다. 새로 서류 검증된 학생이 한 명 있고, "
                  "진행 시트 일곱 개가 모두 최신 상태입니다.",
    "kr-aegyo": "짜잔! 제니예요! 방금 포털 동기화가 끝났어용. 새로 서류 검증된 학생이 한 명 있구요, "
                "진행 시트 일곱 개 모두 최신 상태예요! 헤헤, 또 궁금한 거 있으세용?",
}

MODEL_REPOS = {
    "large-v3": "Systran/faster-whisper-large-v3",
    "medium": "Systran/faster-whisper-medium",
}


def _strip_punct(s):
    # Replace every Unicode punctuation/symbol char with a space.
    return "".join(" " if unicodedata.category(ch)[0] in ("P", "S") else ch for ch in s)


# Numerals are a transcription-formatting choice, not a pronunciation error.
_EN_NUM = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
           "6": "six", "7": "seven", "8": "eight", "9": "nine"}
_KR_NUM_COUNTER = [
    (re.compile(r"7\s*개"), "일곱개"),
    (re.compile(r"1\s*명"), "한명"),
]


def normalize(text, kind, numerals=True):
    text = unicodedata.normalize("NFC", text)
    if kind == "en":
        t = text.lower()
        if numerals:
            t = re.sub(r"\b(\d)\b", lambda m: _EN_NUM[m.group(1)], t)
        t = _strip_punct(t)
        return " ".join(t.split())
    # Korean: strip punctuation and all spaces
    t = text
    if numerals:
        for rx, rep in _KR_NUM_COUNTER:
            t = rx.sub(rep, t)
    t = _strip_punct(t)
    return re.sub(r"\s+", "", t).lower()


def levenshtein(a, b):
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(hyp, kind, numerals=True):
    ref_n = normalize(EXPECTED[kind], kind, numerals)
    hyp_n = normalize(hyp, kind, numerals)
    if not ref_n:
        return 0.0
    return levenshtein(ref_n, hyp_n) / len(ref_n)


def model_path(name):
    from huggingface_hub import snapshot_download
    return snapshot_download(MODEL_REPOS[name])


def gpu_free_mib():
    import subprocess
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20).stdout.strip().splitlines()
        return int(out[0])
    except Exception:
        return 0


class GpuLock:
    """Exclusive-create gpu.lock; refuse if it already exists."""

    def __init__(self, owner="whisper-ears-check"):
        self.owner = owner
        self.held = False

    def acquire(self):
        try:
            fd = os.open(GPU_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"owner={self.owner}\npid={os.getpid()}\nsince={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self.held = True
        return True

    def release(self):
        if self.held:
            try:
                os.remove(GPU_LOCK)
            except FileNotFoundError:
                pass
            self.held = False


def audio_seconds(path):
    import soundfile as sf
    info = sf.info(path)
    return info.frames / float(info.samplerate)


def log(*a):
    print(*a, flush=True)
    sys.stdout.flush()
