"""Second licence pass: mimic3 apope voice, Lessac/Blizzard 2013 licence, OpenSLR 83, KSS."""
import re
import urllib.request

URLS = {
    "apope_LICENSE": "https://raw.githubusercontent.com/MycroftAI/mimic3-voices/master/voices/en_UK/apope_low/LICENSE",
    "apope_README": "https://raw.githubusercontent.com/MycroftAI/mimic3-voices/master/voices/en_UK/apope_low/README.md",
    "apope_SOURCE": "https://raw.githubusercontent.com/MycroftAI/mimic3-voices/master/voices/en_UK/apope_low/SOURCE",
    "lessac_blizzard_license": "https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html",
    "openslr_83": "https://www.openslr.org/83/",
    "piper_voices_md": "https://raw.githubusercontent.com/OHF-Voice/piper1-gpl/main/docs/VOICES.md",
}


def strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", s))


for name, url in URLS.items():
    print("=" * 15, name, url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 piper-licence-check"})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print("FETCH ERROR:", e)
        continue
    if url.endswith(".html") or url.endswith("/83/"):
        body = strip_html(body)
    if name == "piper_voices_md":
        # only print lines about licences / en_GB / ko
        for line in body.splitlines():
            if any(k in line.lower() for k in ("licen", "en_gb", "korean", "ko_kr", "commercial")):
                print(line)
        continue
    print(body[:3500])
