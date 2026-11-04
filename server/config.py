"""Runtime configuration, read from ``PRISM_*`` environment variables.

Every setting has a safe single-node default so ``prism serve`` works
out of the box; production deployments override them via the compose
``.env`` file. ``secret_key`` is generated and persisted to the data
directory on first start when not supplied, so restarts never silently
invalidate sessions and share links.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide settings. Construct via :func:`get_settings`."""

    model_config = SettingsConfigDict(env_prefix="PRISM_", env_file=".env", extra="ignore")

    env: Literal["development", "production", "test"] = "development"
    data_dir: Path = Field(default=Path("./var"), description="Root for datasets, uploads, keys.")
    database_url: str | None = Field(
        default=None,
        description="SQLAlchemy URL. Defaults to SQLite inside data_dir.",
    )
    database_password: str | None = Field(
        default=None,
        description="Database password, kept out of database_url so any character is safe.",
    )
    client_ip_header: str | None = Field(
        default=None,
        description="Real client IP header from a trusted edge (e.g. CF-Connecting-IP).",
    )
    secret_key: str | None = Field(default=None, description="HMAC key for tokens.")
    base_url: str = Field(default="http://localhost:8080", description="Public URL of the app.")
    host: str = "0.0.0.0"
    port: int = 8080

    max_upload_mb: int = Field(default=100, ge=1, le=2048)
    session_hours: int = Field(default=24 * 7, ge=1)
    cookie_secure: bool | None = Field(
        default=None, description="Force Secure cookies. Defaults to True when base_url is https."
    )
    query_row_limit: int = Field(default=50_000, ge=100)
    query_timeout_s: float = Field(default=30.0, gt=0)
    login_rate_limit: int = Field(default=10, description="Failed logins per IP per 15 minutes.")

    license_key: str | None = Field(default=None, description="Signed license key (Pro/Business).")
    license_public_key: str | None = Field(
        default=None, description="Override the vendor license verification key (testing)."
    )

    log_level: str = "INFO"
    log_json: bool = True
    static_dir: Path | None = Field(
        default=None, description="Built web UI directory. Auto-detected when unset."
    )

    @field_validator("data_dir")
    @classmethod
    def _expand(cls, v: Path) -> Path:
        return v.expanduser().resolve()

    # ------------------------------------------------------------------
    # Derived paths
    # ------------------------------------------------------------------

    @property
    def datasets_dir(self) -> Path:
        return self.data_dir / "datasets"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            if not self.database_password:
                return self.database_url
            from sqlalchemy.engine import make_url

            url = make_url(self.database_url).set(password=self.database_password)
            return url.render_as_string(hide_password=False)
        return f"sqlite:///{self.data_dir / 'prism.db'}"

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.base_url.startswith("https://")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.datasets_dir, self.uploads_dir, self.backups_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolved_secret_key(self) -> str:
        """Return the configured secret, or a persisted generated one."""
        if self.secret_key:
            return self.secret_key
        self.ensure_dirs()
        key_file = self.data_dir / ".secret_key"
        if key_file.exists():
            return key_file.read_text().strip()
        key = secrets.token_urlsafe(48)
        key_file.write_text(key)
        key_file.chmod(0o600)
        return key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process settings."""
    return Settings()
