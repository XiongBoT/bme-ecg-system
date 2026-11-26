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
        port = parsed.port
    except ValueError:
        return None

    if any(ord(c) < 33 for c in cleaned) or "\\" in cleaned or (port is not None and not 1 <= port <= 65535):
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
    cookie_path: str = "/"

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
    ecg_api_base_url: str | None = None
    ecg_client_secret: str = ""

    @field_validator("cookie_path")
    @classmethod
    def _validate_cookie_path(cls, value: str) -> str:
        if value not in ("/", "/heartlife/"):
            raise ValueError("cookie_path must be / or /heartlife/")
        return value

    @field_validator("ecg_api_base_url", mode="before")
    @classmethod
    def _validate_ecg_api_url(cls, value: str | None) -> str | None:
        if not value or not value.strip():
            return None
        value = value.strip().rstrip("/")
        try:
            parsed = urlparse(value)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("ECG API address is invalid") from exc
        if (any(ord(c) < 33 for c in value) or "\\" in value or not parsed.hostname
                or parsed.username or parsed.password or parsed.path or parsed.query
                or parsed.fragment or parsed.params or (port is not None and not 1 <= port <= 65535)):
            raise ValueError("ECG API address must be a fixed origin without credentials or paths")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "::1")
        ):
            raise ValueError("ECG API requires HTTPS or an explicit loopback address")
        return value

    @property
    def is_ecg_integration_enabled(self) -> bool:
        return bool(self.ecg_external_url and self.ecg_api_base_url and len(self.ecg_client_secret) >= 32)

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
