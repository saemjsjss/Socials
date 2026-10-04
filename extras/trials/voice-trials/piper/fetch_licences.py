"""Fetch primary-source licence documents referenced by the chosen voices' model cards."""
import json
import urllib.request

URLS = {
    "hf_repo_api": "https://huggingface.co/api/models/rhasspy/piper-voices",
    "hf_repo_readme": "https://huggingface.co/rhasspy/piper-voices/raw/main/README.md",
    "lessac_card": "https://huggingface.co/rhasspy/piper-voices/raw/main/en/en_US/lessac/medium/MODEL_CARD",
    "ryan_low_card": "https://huggingface.co/rhasspy/piper-voices/raw/main/en/en_US/ryan/low/MODEL_CARD",
    "mimic3_apope_dir": "https://api.github.com/repos/MycroftAI/mimic3-voices/contents/voices/en_UK/apope_low",
    "mimic3_license": "https://raw.githubusercontent.com/MycroftAI/mimic3-voices/master/LICENSE",
    "jenny_readme": "https://raw.githubusercontent.com/dioco-group/jenny-tts-dataset/main/README.md",
}

for name, url in URLS.items():
    print("=" * 15, name, url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "piper-licence-check"})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print("FETCH ERROR:", e)
        continue
    if name == "hf_repo_api":
        d = json.loads(body)
        print("tags:", d.get("tags"))
        print("cardData:", d.get("cardData"))
    elif name == "mimic3_apope_dir":
        for f in json.loads(body):
            print(f["name"], f.get("download_url"))
    else:
        print(body[:4000])
