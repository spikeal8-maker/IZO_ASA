"""Pure configuration helpers extracted from the legacy backend entrypoint.

This module must stay safe to import: it does not create directories, connect to
SQLite, start workers or import the FastAPI application.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORS_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://izo.alikinas.ru",
)
DEFAULT_TRUSTED_HOSTS = (
    "localhost",
    "127.0.0.1",
    "::1",
    "testserver",
    "izo.alikinas.ru",
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
    trusted_hosts: tuple[str, ...]


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


@dataclass(frozen=True)
class MediaProcessingPolicy:
    comfyui_input_max_side: int
    comfyui_face_input_max_side: int
    comfyui_face_source_megapixels: float
    gallery_image_max_side: int
    gallery_image_webp_quality: int
    gallery_full_quality_count: int
    gallery_archive_max_side: int
    gallery_archive_webp_quality: int
    source_thumb_max_side: int
    source_thumb_webp_quality: int


@dataclass(frozen=True)
class StoragePathPolicy:
    media_dir: Path
    avatar_dir: Path
    database_path: Path


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


def load_media_processing_policy(
    environment: Mapping[str, str] | None = None,
) -> MediaProcessingPolicy:
    """Parse bounded image-processing limits without touching image or media files."""

    source = os.environ if environment is None else environment
    comfyui_input_max_side = max(
        512,
        min(2048, int(source.get("COMFYUI_INPUT_MAX_SIDE", "1536"))),
    )
    gallery_image_max_side = max(
        1024,
        min(4096, int(source.get("GALLERY_IMAGE_MAX_SIDE", "2048"))),
    )

    return MediaProcessingPolicy(
        comfyui_input_max_side=comfyui_input_max_side,
        comfyui_face_input_max_side=max(
            512,
            min(
                comfyui_input_max_side,
                int(source.get("COMFYUI_FACE_INPUT_MAX_SIDE", "1024")),
            ),
        ),
        comfyui_face_source_megapixels=max(
            0.15,
            min(1.0, float(source.get("COMFYUI_FACE_SOURCE_MEGAPIXELS", "0.35"))),
        ),
        gallery_image_max_side=gallery_image_max_side,
        gallery_image_webp_quality=max(
            70,
            min(95, int(source.get("GALLERY_IMAGE_WEBP_QUALITY", "90"))),
        ),
        gallery_full_quality_count=max(
            1,
            min(50, int(source.get("GALLERY_FULL_QUALITY_COUNT", "10"))),
        ),
        gallery_archive_max_side=max(
            768,
            min(
                gallery_image_max_side,
                int(source.get("GALLERY_ARCHIVE_MAX_SIDE", "1536")),
            ),
        ),
        gallery_archive_webp_quality=max(
            75,
            min(92, int(source.get("GALLERY_ARCHIVE_WEBP_QUALITY", "86"))),
        ),
        source_thumb_max_side=max(
            192,
            min(768, int(source.get("SOURCE_THUMB_MAX_SIDE", "384"))),
        ),
        source_thumb_webp_quality=max(
            55,
            min(90, int(source.get("SOURCE_THUMB_WEBP_QUALITY", "76"))),
        ),
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
    trusted_hosts_raw = source.get("TRUSTED_HOSTS", ",".join(DEFAULT_TRUSTED_HOSTS))

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
        trusted_hosts=tuple(host.strip() for host in trusted_hosts_raw.split(",") if host.strip()),
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


def load_storage_path_policy(
    root: Path,
    environment: Mapping[str, str] | None = None,
) -> StoragePathPolicy:
    """Compute storage paths without creating, reading or moving storage content."""

    source = os.environ if environment is None else environment
    media_dir = Path(source.get("MEDIA_DIR", str(root / "media"))).expanduser().resolve()
    return StoragePathPolicy(
        media_dir=media_dir,
        avatar_dir=media_dir / "avatars",
        database_path=sqlite_path_from_database_url(source.get("DATABASE_URL"), root),
    )


def _loopback_http_or_https_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return False
    if parsed.scheme == "https" and hostname and not parsed.username and not parsed.password:
        return True
    if parsed.scheme != "http" or not hostname or parsed.username or parsed.password:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _valid_cors_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
    )


def production_configuration_errors(
    *,
    runtime: RuntimeEnvironmentPolicy,
    http_security: HttpSecurityPolicy,
    providers: ProviderEndpointPolicy,
    storage: StoragePathPolicy,
) -> tuple[str, ...]:
    """Return secret-free error codes for unsafe production-only configuration."""

    if not runtime.production_like:
        return ()

    errors: list[str] = []
    if runtime.app_env.lower() != "production":
        errors.append("APP_ENV_MUST_BE_PRODUCTION")
    if not http_security.cookie_secure:
        errors.append("COOKIE_SECURE_REQUIRED")
    if http_security.cookie_samesite.lower() not in {"lax", "strict", "none"}:
        errors.append("COOKIE_SAMESITE_INVALID")
    if not http_security.cors_allowed_origins:
        errors.append("CORS_ORIGINS_REQUIRED")
    for index, origin in enumerate(http_security.cors_allowed_origins):
        if origin == "*":
            errors.append("CORS_WILDCARD_FORBIDDEN")
        elif not _valid_cors_origin(origin):
            errors.append(f"CORS_ORIGIN_INVALID_{index}")
    if not http_security.trusted_hosts:
        errors.append("TRUSTED_HOSTS_REQUIRED")
    elif "*" in http_security.trusted_hosts:
        errors.append("TRUSTED_HOSTS_WILDCARD_FORBIDDEN")
    if providers.comfyui_mock_fallback:
        errors.append("COMFYUI_MOCK_FALLBACK_FORBIDDEN")
    if not _loopback_http_or_https_url(providers.comfyui_base_url):
        errors.append("COMFYUI_URL_INSECURE")
    if not _loopback_http_or_https_url(providers.openrouter_base_url):
        errors.append("OPENROUTER_URL_INSECURE")
    if not providers.prompt_improve_model.strip():
        errors.append("PROMPT_MODEL_REQUIRED")
    if not _loopback_http_or_https_url(providers.cbr_daily_xml_url):
        errors.append("CBR_URL_INSECURE")
    if not _loopback_http_or_https_url(providers.usd_rub_fallback_url):
        errors.append("USD_RUB_FALLBACK_URL_INSECURE")
    if not storage.media_dir.is_absolute():
        errors.append("MEDIA_PATH_MUST_BE_ABSOLUTE")
    if not storage.database_path.is_absolute():
        errors.append("DATABASE_PATH_MUST_BE_ABSOLUTE")
    return tuple(errors)


def validate_production_configuration(
    *,
    runtime: RuntimeEnvironmentPolicy,
    http_security: HttpSecurityPolicy,
    providers: ProviderEndpointPolicy,
    storage: StoragePathPolicy,
) -> None:
    errors = production_configuration_errors(
        runtime=runtime,
        http_security=http_security,
        providers=providers,
        storage=storage,
    )
    if errors:
        raise RuntimeError("Unsafe production configuration: " + ",".join(errors))
