"""
Telegram reachability fix (no admin rights needed).

On this network the DNS answer for api.telegram.org points at a Telegram
address that cannot be reached, while other Telegram front-end addresses work
fine with a valid TLS certificate. Editing the Windows hosts file needs admin,
so instead we probe a list of known Telegram addresses at startup and, if the
normal DNS answer is dead, transparently override name resolution for
api.telegram.org inside this process only.

Set TELEGRAM_API_IP in .env to force a specific address, or
TELEGRAM_DNS_FIX=false to disable the probe entirely.
"""
import logging
import os
import socket

logger = logging.getLogger("hangeul.netfix")

TELEGRAM_HOST = "api.telegram.org"
TELEGRAM_PORT = 443
PROBE_TIMEOUT = 3.0

# Known Telegram Bot API front-end addresses (DC2 / DC4 / DC5 ranges).
CANDIDATE_IPS = [
    "149.154.167.99",
    "149.154.167.220",
    "149.154.166.110",
    "149.154.167.50",
    "149.154.167.51",
    "149.154.167.91",
    "149.154.167.220",
    "149.154.175.50",
    "91.108.4.200",
    "91.108.56.100",
]

_original_getaddrinfo = socket.getaddrinfo
_chosen_ip = None


def _tcp_ok(ip: str) -> bool:
    try:
        with socket.create_connection((ip, TELEGRAM_PORT), timeout=PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def _dns_ips() -> list:
    try:
        infos = _original_getaddrinfo(TELEGRAM_HOST, TELEGRAM_PORT, socket.AF_INET, socket.SOCK_STREAM)
        seen, out = set(), []
        for info in infos:
            ip = info[4][0]
            if ip not in seen:
                seen.add(ip)
                out.append(ip)
        return out
    except OSError:
        return []


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    # httpx/anyio may pass the host as bytes; normalise before comparing.
    name = host.decode("ascii", "ignore") if isinstance(host, (bytes, bytearray)) else host
    if _chosen_ip and isinstance(name, str) and name.lower() == TELEGRAM_HOST:
        return _original_getaddrinfo(_chosen_ip, port, socket.AF_INET, type, proto, flags)
    return _original_getaddrinfo(host, port, family, type, proto, flags)


def apply_telegram_dns_fix() -> str | None:
    """Probe Telegram; patch resolution if the DNS answer is unreachable.
    Returns the IP now used for api.telegram.org, or None if no override."""
    global _chosen_ip

    if os.environ.get("TELEGRAM_DNS_FIX", "true").strip().lower() in ("0", "false", "no", "off"):
        logger.info("Telegram DNS fix disabled via TELEGRAM_DNS_FIX.")
        return None

    forced = os.environ.get("TELEGRAM_API_IP", "").strip()
    if forced:
        _chosen_ip = forced
        socket.getaddrinfo = _patched_getaddrinfo
        logger.info("Telegram API forced to %s via TELEGRAM_API_IP.", forced)
        return forced

    dns_ips = _dns_ips()
    for ip in dns_ips:
        if _tcp_ok(ip):
            logger.info("Telegram reachable via normal DNS (%s); no override needed.", ip)
            return None

    logger.warning("Telegram unreachable via DNS answer %s; probing alternate addresses...", dns_ips or "n/a")
    for ip in CANDIDATE_IPS:
        if ip in dns_ips:
            continue
        if _tcp_ok(ip):
            _chosen_ip = ip
            socket.getaddrinfo = _patched_getaddrinfo
            logger.warning("Telegram DNS override active: %s -> %s", TELEGRAM_HOST, ip)
            return ip

    logger.error("No reachable Telegram address found. Bot startup will likely time out.")
    return None
