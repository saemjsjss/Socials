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
    
    # Local LLM
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"
    
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
