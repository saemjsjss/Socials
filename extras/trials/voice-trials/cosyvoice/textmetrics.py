import re
import unicodedata


def norm(s):
    s = unicodedata.normalize("NFC", s).lower()
    return re.sub(r"[\W_]+", "", s)


def cer(ref, hyp):
    """Character error rate after stripping punctuation/whitespace (numerals are NOT converted,
    so Whisper writing '7' for '일곱' counts as an error)."""
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / max(1, len(r))
