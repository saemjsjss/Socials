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


# Keep the Telegram bot token out of the logs.
#
# httpx logs every request URL at INFO, and a Telegram API URL carries the bot token
# (https://api.telegram.org/bot<token>/sendMessage), so anyone who could read
# hangeul_bot.log could take over the bot.  The request lines stay, as they help diagnose
# the portal and Telegram, but the token itself is replaced.  This package is imported by
# the bot and by every scheduled job, so they all get the filter.
import logging as _logging
import re as _re

# The ":" is URL-encoded as "%3A" in file-download URLs (api.telegram.org/file/bot<token>/...).
_TOKEN_RE = _re.compile(r"bot\d{6,}(?::|%3[Aa])[A-Za-z0-9_-]{30,}")


class _RedactBotToken(_logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if _TOKEN_RE.search(msg):
            record.msg, record.args = _TOKEN_RE.sub("bot<token>", msg), ()
        return True


_logging.getLogger("httpx").addFilter(_RedactBotToken())
