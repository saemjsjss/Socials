import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# The bot folder (the one holding run.py and .env), wherever it has been copied to.
BOT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = BOT_ROOT / ".env"


def _folder(value: str, default: Path) -> Path:
    """A folder setting: empty = the default; a relative path counts from BOT_ROOT."""
    value = str(value or "").strip()
    if not value:
        return default
    path = Path(value)
    return path if path.is_absolute() else BOT_ROOT / path


class Settings(BaseSettings):
    # App Settings
    MOCK_MODE: bool = True
    
    # Hangeul Admin
    HANGEUL_BASE_URL: str = "https://hangeul.com.bd/admin"
    HANGEUL_USERNAME: str = "admin"
    HANGEUL_PASSWORD: str = "password"
    
    # Local LLM ("Jennie's brain"): one model for everything (typed questions, the daily brief,
    # e-mails, voice notes), kept resident in VRAM. 127.0.0.1, not localhost: on this PC
    # "localhost" tries IPv6 first and loses ~2 s on every new connection.
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "qwen3:4b-instruct"
    # Context window of EVERY Ollama call. Ollama reloads the model whenever this differs from
    # the loaded copy, so it is one number for all calls. Measured with qwen3:4b-instruct on the
    # RTX 5060 (Ollama /api/ps, 28 Sep 2026): 2048 -> 2.68 GiB, 3072 -> 2.82 GiB. 3072 fits the
    # daily brief (~1,300-1,600 tokens + its answer; 2048 would cut it) and leaves ~3.2-3.4 GiB beside
    # the desktop and the idle voice service, while a Korean speech render peaks at ~3.6 GiB: right at
    # the edge (some renders spill into shared memory and slow down). Setting OLLAMA_FLASH_ATTENTION=1
    # and OLLAMA_KV_CACHE_TYPE=q8_0 on the Ollama server (Windows environment, not this file) makes
    # the model ~0.35 GiB smaller at the same num_ctx (measured: 3072 -> 2.81 GB instead of 3.18 GB).
    # Ollama cuts an over-long prompt silently; ollama_client logs a warning when one may not fit.
    OLLAMA_NUM_CTX: int = 3072
    
    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ADMIN_CHAT_ID: str = ""
    # Extra Telegram user IDs allowed to use the bot (comma/space separated).
    # The primary TELEGRAM_ADMIN_CHAT_ID above is always allowed; add colleagues here,
    # e.g. TELEGRAM_AUTHORIZED_CHAT_IDS=6958042267,123456789
    TELEGRAM_AUTHORIZED_CHAT_IDS: str = ""
    # Who receives the 15-minute portal-sync / document-check summaries and the 09:05
    # missing-information report (comma/space separated). Leave empty = everyone who can
    # use the bot gets them. Set it to restrict them to specific people (list yourself here
    # too if you want them). The daily brief and the passport alerts go only to
    # TELEGRAM_ADMIN_CHAT_ID (skipped while it is empty).
    TELEGRAM_BRIEF_CHAT_IDS: str = ""
    DAILY_REPORT_TIME: str = "18:05"
    REPORT_TIMEZONE: str = "Asia/Dhaka"
    ENABLE_SCHEDULED_REPORTS: bool = True

    # Gmail — lets the /sendmail command send email from Telegram.
    # GMAIL_APP_PASSWORD must be a Google APP PASSWORD (16 chars), NOT your normal
    # password: Google Account -> Security -> 2-Step Verification -> App passwords.
    GMAIL_ADDRESS: str = ""
    GMAIL_APP_PASSWORD: str = ""

    # Jennie's voice — the local voice service (speech-to-text + CosyVoice2 speech) on this PC.
    # Off by default: while it is false the bot ignores voice notes exactly as before.
    JENNIE_VOICE_ENABLED: bool = False
    JENNIE_VOICE_URL: str = "http://127.0.0.1:8765"   # must be this PC (127.0.0.1 / localhost)
    JENNIE_SPOKEN_BRIEF: bool = True                  # also speak the daily brief (needs the above on)
    # Keep the brain (OLLAMA_MODEL) in VRAM for good. Off by default: it is pinned only while
    # JENNIE_VOICE_ENABLED is on; otherwise it loads for a question and unloads after
    # BRAIN_IDLE_UNLOAD of no use, so the GPU is free the rest of the time.
    BRAIN_ALWAYS_LOADED: bool = False
    BRAIN_IDLE_UNLOAD: str = "5m"

    # API Server
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Local folders. Empty = the default beside the bot folder, so with the bot in
    # E:\BOT they are E:\VERIFIED STUDENT DOCUMENTS etc., exactly as before.
    DOCS_ROOT: str = ""              # downloaded documents: <PROGRAM>\<NAME (PASSPORT)>\
    DOCS_ORIGINALS_ROOT: str = ""    # untouched originals of files shrunk below 2 MB
    KONYANG_ROOT: str = ""           # older Konyang downloads; skipped when absent
    VERIFICATION_DIR: str = ""       # OCR text cache, results.json, the check reports

    def docs_root(self) -> Path:
        return _folder(self.DOCS_ROOT, BOT_ROOT.parent / "VERIFIED STUDENT DOCUMENTS")

    def docs_originals_root(self) -> Path:
        return _folder(self.DOCS_ORIGINALS_ROOT,
                       BOT_ROOT.parent / "VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB")

    def konyang_root(self) -> Path:
        return _folder(self.KONYANG_ROOT, BOT_ROOT.parent / "KONYANG DOCUMENTS")

    def verification_dir(self) -> Path:
        return _folder(self.VERIFICATION_DIR, BOT_ROOT / "data" / "verification")

    def authorized_ids(self) -> set:
        """Every Telegram user ID allowed to use the bot: the primary admin plus
        any extra IDs listed in TELEGRAM_AUTHORIZED_CHAT_IDS."""
        ids = set()
        primary = str(self.TELEGRAM_ADMIN_CHAT_ID or "").strip()
        if primary:
            ids.add(primary)
        raw = str(self.TELEGRAM_AUTHORIZED_CHAT_IDS or "")
        for part in raw.replace(";", ",").replace(" ", ",").split(","):
            part = part.strip()
            if part:
                ids.add(part)
        return ids

    def brief_recipient_ids(self) -> set:
        """Who receives the portal-sync summaries and the missing-information report.
        Defaults to all authorized users; if TELEGRAM_BRIEF_CHAT_IDS is set, only those IDs get them."""
        raw = str(self.TELEGRAM_BRIEF_CHAT_IDS or "").strip()
        if not raw:
            return self.authorized_ids()
        ids = set()
        for part in raw.replace(";", ",").replace(" ", ",").split(","):
            part = part.strip()
            if part:
                ids.add(part)
        return ids

    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
