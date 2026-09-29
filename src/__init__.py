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

# The Supabase keys (src/cloud publishes with the secret key): the new-style secret and
# publishable keys, the CLI's personal access token, and the older JWT-shaped keys, also after
# "apikey:" / "Authorization: Bearer" wherever a request's headers get printed.
_SECRET_PATTERNS = (
    (_TOKEN_RE, "bot<token>"),
    (_re.compile(r"(?i)(bearer\s+)(?!<)[A-Za-z0-9._~+/=-]{8,}"), r"\1<redacted>"),
    (_re.compile(r"""(?i)(apikey['"]?\s*[:=,]\s*b?['"]?)(?!<)[A-Za-z0-9._~+/=-]{8,}"""), r"\1<redacted>"),
    (_re.compile(r"sb_secret_[A-Za-z0-9_-]{6,}"), "sb_secret_<redacted>"),
    (_re.compile(r"sb_publishable_[A-Za-z0-9_-]{6,}"), "sb_publishable_<redacted>"),
    (_re.compile(r"sbp_[A-Za-z0-9_-]{16,}"), "sbp_<redacted>"),
    (_re.compile(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}"), "<jwt>"),
)


def redact(text: str) -> str:
    """`text` with every bot token and Supabase key (or JWT) in it replaced by a marker."""
    for pattern, marker in _SECRET_PATTERNS:
        text = pattern.sub(marker, text)
    return text


class _RedactBotToken(_logging.Filter):
    """Replaces the bot token and the Supabase keys in a log line (the name is kept from when it
    covered the bot token only)."""

    def filter(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        return True


# A filter on a logger does not see its children's records, so each logger that can print a
# request (httpx's own, and httpcore's per-module loggers at DEBUG) gets one.
_REDACTOR = _RedactBotToken()
for _name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2",
              "httpcore.proxy", "httpcore.socks", "hangeul.cloud"):
    _logging.getLogger(_name).addFilter(_REDACTOR)
