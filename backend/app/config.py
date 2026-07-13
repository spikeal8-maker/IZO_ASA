"""Pure configuration helpers extracted from the legacy backend entrypoint.

This module must stay safe to import: it does not create directories, connect to
SQLite, start workers or import the FastAPI application.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORS_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://izo.alikinas.ru",
)


@dataclass(frozen=True)
class HttpSecurityPolicy:
    session_cookie_name: str
    refresh_cookie_name: str
    cookie_secure: bool
    cookie_samesite: str
    cookie_domain: str | None
    cookie_path: str
    bot_login_challenge_cookie_name: str
    bot_login_challenge_ttl_seconds: int
    trust_proxy_headers: bool
    trust_cloudflare_headers: bool
    cors_allowed_origins: tuple[str, ...]


@dataclass(frozen=True)
class ProviderEndpointPolicy:
    comfyui_base_url: str
    comfyui_required: bool
    comfyui_mock_fallback: bool
    comfyui_timeout_seconds: int
    comfyui_face_timeout_seconds: int
    openrouter_base_url: str
    openrouter_timeout_seconds: int
    prompt_improve_model: str
    prompt_improve_timeout_seconds: int
    cbr_daily_xml_url: str
    usd_rub_fallback_url: str


@dataclass(frozen=True)
class RuntimeEnvironmentPolicy:
    app_env: str
    environment_name: str
    mode_name: str

    @property
    def production_like(self) -> bool:
        return is_production_like_environment(
            self.app_env,
            self.environment_name,
            self.mode_name,
        )


@dataclass(frozen=True)
class BotDeliveryPolicy:
    telegram_updates_mode: str
    telegram_polling_enabled: bool
    max_polling_enabled: bool
    max_updates_mode: str


def load_local_env(root: Path | None = None) -> None:
    """Load `root/.env` without overriding process-level environment values."""
    env_path = (root or BACKEND_ROOT) / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_production_like_environment(
    app_env: str,
    environment_name: str = "",
    mode_name: str = "",
) -> bool:
    return any(
        (value or "").strip().lower() in {"production", "prod", "live"}
        for value in (app_env, environment_name, mode_name)
    )


def load_runtime_environment_policy(
    environment: Mapping[str, str] | None = None,
) -> RuntimeEnvironmentPolicy:
    """Parse runtime environment labels without validating production secrets."""

    source = os.environ if environment is None else environment
    return RuntimeEnvironmentPolicy(
        app_env=source.get("APP_ENV", "development"),
        environment_name=source.get("ENV", ""),
        mode_name=source.get("MODE", ""),
    )


def load_bot_delivery_policy(
    environment: Mapping[str, str] | None = None,
) -> BotDeliveryPolicy:
    """Parse Telegram/MAX delivery modes without starting workers or making requests."""

    source = os.environ if environment is None else environment
    valid_modes = {"webhook", "polling", "disabled"}

    telegram_updates_mode = source.get(
        "BOT_UPDATES_MODE",
        source.get("BOT_MODE", "disabled"),
    ).strip().lower()
    if telegram_updates_mode not in valid_modes:
        telegram_updates_mode = "disabled"

    max_updates_mode = source.get(
        "MAX_UPDATES_MODE",
        telegram_updates_mode,
    ).strip().lower()
    if max_updates_mode not in valid_modes:
        max_updates_mode = telegram_updates_mode

    def polling_enabled(name: str) -> bool:
        value = source.get(name)
        if value is None:
            return True
        return value.strip().lower() in {"1", "true", "yes", "on"}

    return BotDeliveryPolicy(
        telegram_updates_mode=telegram_updates_mode,
        telegram_polling_enabled=polling_enabled("TELEGRAM_POLLING_ENABLED"),
        max_polling_enabled=polling_enabled("MAX_POLLING_ENABLED"),
        max_updates_mode=max_updates_mode,
    )


def load_http_security_policy(
    environment: Mapping[str, str] | None = None,
    *,
    app_env: str | None = None,
) -> HttpSecurityPolicy:
    """Parse the legacy cookie, proxy-header and CORS environment contract.

    Boolean parsing intentionally remains exact: these security switches were
    historically enabled only by the literal value ``true`` (case-insensitive).
    Broadening that behavior during extraction could enable trust unexpectedly.
    """

    source = os.environ if environment is None else environment
    current_app_env = source.get("APP_ENV", "development") if app_env is None else app_env
    secure_default = "true" if current_app_env.lower() == "production" else "false"
    cors_raw = source.get("CORS_ALLOWED_ORIGINS", ",".join(DEFAULT_CORS_ALLOWED_ORIGINS))

    return HttpSecurityPolicy(
        session_cookie_name=source.get("TRUSTED_SESSION_COOKIE_NAME", "onenode_session"),
        refresh_cookie_name=source.get("TRUSTED_REFRESH_COOKIE_NAME", "onenode_refresh"),
        cookie_secure=source.get("TRUSTED_COOKIE_SECURE", secure_default).lower() == "true",
        cookie_samesite=source.get("TRUSTED_COOKIE_SAMESITE", "lax"),
        cookie_domain=source.get("TRUSTED_COOKIE_DOMAIN", "") or None,
        cookie_path=source.get("TRUSTED_COOKIE_PATH", "/"),
        bot_login_challenge_cookie_name=source.get(
            "BOT_LOGIN_CHALLENGE_COOKIE_NAME", "onenode_bot_login"
        ),
        bot_login_challenge_ttl_seconds=int(source.get("BOT_LOGIN_CHALLENGE_TTL_SECONDS", "600")),
        trust_proxy_headers=source.get("TRUST_PROXY_HEADERS", "false").lower() == "true",
        trust_cloudflare_headers=source.get("TRUST_CLOUDFLARE_HEADERS", "false").lower() == "true",
        cors_allowed_origins=tuple(origin.strip() for origin in cors_raw.split(",") if origin.strip()),
    )


def load_provider_endpoint_policy(
    environment: Mapping[str, str] | None = None,
) -> ProviderEndpointPolicy:
    """Parse provider endpoints and request timeouts without side effects.

    Normalization and clamping intentionally mirror the legacy ``main.py``
    expressions exactly. In particular, ComfyUI booleans accept only literal
    ``true`` (case-insensitive), while endpoint whitespace is preserved unless
    the legacy expression explicitly stripped it.
    """

    source = os.environ if environment is None else environment
    comfyui_timeout_seconds = int(source.get("COMFYUI_TIMEOUT_SECONDS", "900"))
    comfyui_face_timeout_seconds = max(
        60,
        min(
            comfyui_timeout_seconds,
            int(source.get("COMFYUI_FACE_TIMEOUT_SECONDS", "240")),
        ),
    )

    return ProviderEndpointPolicy(
        comfyui_base_url=source.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188"),
        comfyui_required=source.get("COMFYUI_REQUIRED", "false").lower() == "true",
        comfyui_mock_fallback=source.get("COMFYUI_MOCK_FALLBACK", "false").lower() == "true",
        comfyui_timeout_seconds=comfyui_timeout_seconds,
        comfyui_face_timeout_seconds=comfyui_face_timeout_seconds,
        openrouter_base_url=source.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/"),
        openrouter_timeout_seconds=max(
            30,
            min(300, int(source.get("OPENROUTER_TIMEOUT_SECONDS", "120"))),
        ),
        prompt_improve_model=source.get(
            "PROMPT_IMPROVE_MODEL", "deepseek/deepseek-v4-flash"
        ).strip(),
        prompt_improve_timeout_seconds=max(
            3,
            min(30, int(source.get("PROMPT_IMPROVE_TIMEOUT_SECONDS", "10"))),
        ),
        cbr_daily_xml_url=source.get(
            "CBR_DAILY_XML_URL", "https://www.cbr.ru/scripts/XML_daily.asp"
        ),
        usd_rub_fallback_url=source.get(
            "USD_RUB_FALLBACK_URL", "https://open.er-api.com/v6/latest/USD"
        ),
    )


def sqlite_path_from_database_url(value: str | None, root: Path | None = None) -> Path:
    raw = (value or "").strip()
    if raw.startswith("sqlite:///"):
        return Path(raw.replace("sqlite:///", "", 1))
    if raw.startswith("sqlite:"):
        return Path(raw.replace("sqlite:", "", 1))
    return Path(raw) if raw else (root or BACKEND_ROOT) / "onenode.sqlite3"
