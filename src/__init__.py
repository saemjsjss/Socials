"""Hangeul Admin API, Local LLM & Telegram Reporting Bot package."""
__version__ = "1.0.0"

import os as _os
from pathlib import Path as _Path

# Trust the certificates Windows trusts.
#
# Something between this PC and the internet — antivirus HTTPS scanning, or the ISP —
# presents certificates that chain to a root Windows holds but Python's bundled certifi
# list does not.  Every HTTPS call from Python then fails with CERTIFICATE_VERIFY_FAILED
# while the same site opens fine in a browser.  On 26 September 2026 that stopped the
# Google token refreshing and the progress sheets went nine hours without an update; pip
# could not install a fix either, because pip could not reach PyPI for the same reason.
#
# data/windows-ca.pem is exported from the Windows certificate stores.  Rebuild it with
# tools/export_windows_ca.ps1 if the machine's trusted roots change.
_CA = _Path(__file__).resolve().parent.parent / "data" / "windows-ca.pem"
if _CA.exists():
    for _var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
                 "HTTPX_SSL_CERT_FILE", "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"):
        _os.environ.setdefault(_var, str(_CA))
