"""Third licence pass: Lessac research licence terms and a VCTK speaker-info mirror."""
import re
import urllib.request


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 piper-licence-check"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


html = get("https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html")
text = re.sub(r"(?s)<[^>]+>", " ", html)
text = re.sub(r"\s+", " ", text)
for m in re.finditer(r"(?i)(commercial|research purposes|non-commercial|derivative|synthe)", text):
    s = max(0, m.start() - 250)
    print("...", text[s:m.end() + 250], "...\n")

print("=" * 30, "VCTK speaker info")
for url in (
    "https://datashare.ed.ac.uk/bitstream/handle/10283/3443/speaker-info.txt",
    "https://raw.githubusercontent.com/nii-yamagishilab/vctk-corpus/master/speaker-info.txt",
    "https://huggingface.co/datasets/CSTR-Edinburgh/vctk/raw/main/speaker-info.txt",
):
    try:
        body = get(url)
        print("OK", url)
        print(body[:6000])
        break
    except Exception as e:  # noqa: BLE001
        print("FAIL", url, e)
