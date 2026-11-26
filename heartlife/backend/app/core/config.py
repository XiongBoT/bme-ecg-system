from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SQLITE_URL = f"sqlite:///{(PROJECT_ROOT / 'data' / 'heartlife.db').as_posix()}"


def sanitize_external_ecg_url(raw: str | None) -> str | None:
    """Validate optional external ECG entry URL per PRD §2.2 & EPIC-10.
    Only fixed HTTPS URLs without credentials, query strings, or fragments are accepted.
    Invalid values safely degrade to None so P0 continues unaffected.
    """
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return None

    if parsed.scheme.lower() != "https":
        return None
    if not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    if parsed.query or parsed.fragment or parsed.params:
        return None
    return cleaned


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8010
    frontend_origin: str = "http://localhost:5174"
    database_url: str = DEFAULT_SQLITE_URL
    session_ttl_hours: int = 168
    cookie_secure: bool = False
    session_cookie_name: str = "hl_session"
    csrf_cookie_name: str = "hl_csrf"

    login_rate_limit_count: int = 5
    login_rate_limit_window_seconds: int = 900

    demo_mode: bool = False

    assistant_enabled: bool = False
    assistant_provider: str = "deterministic"
    assistant_api_key: str = ""
    assistant_base_url: str = ""
    assistant_model: str = ""
    assistant_timeout_seconds: float = 8.0

    ecg_external_url: str | None = None

    @field_validator("ecg_external_url", mode="before")
    @classmethod
    def _validate_ecg_url(cls, v: str | None) -> str | None:
        return sanitize_external_ecg_url(v)

    @property
    def is_assistant_available(self) -> bool:
        if not self.assistant_enabled:
            return False
        if self.assistant_provider in ("deterministic", "fake"):
            return True
        return bool(self.assistant_api_key.strip())
