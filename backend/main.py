from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import secrets
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import hmac
import hashlib
from urllib.parse import parse_qs

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent
MEDIA = ROOT / "media"
MEDIA.mkdir(exist_ok=True)
AVATAR_DIR = MEDIA / "avatars"
AVATAR_DIR.mkdir(exist_ok=True)


def load_local_env() -> None:
    env_path = ROOT / ".env"
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


load_local_env()

# Identity Core session service (Phase 4 + 4.1). Keying material for token hashing
# comes from the environment when available. Only hashes are persisted — raw tokens
# never reach the database or logs.
APP_ENV = os.getenv("APP_ENV", "development")
ENV_NAME = os.getenv("ENV", "")
MODE_NAME = os.getenv("MODE", "")


def is_production_like_env() -> bool:
    return any((value or "").strip().lower() in {"production", "prod", "live"} for value in (APP_ENV, ENV_NAME, MODE_NAME))


def sqlite_path_from_database_url(value: str | None) -> Path:
    raw = (value or "").strip()
    if raw.startswith("sqlite:///"):
        return Path(raw.replace("sqlite:///", "", 1))
    if raw.startswith("sqlite:"):
        return Path(raw.replace("sqlite:", "", 1))
    return Path(raw) if raw else ROOT / "onenode.sqlite3"


DB_PATH = sqlite_path_from_database_url(os.getenv("DATABASE_URL"))

COMFYUI_BASE_URL = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
COMFYUI_REQUIRED = os.getenv("COMFYUI_REQUIRED", "false").lower() == "true"
COMFYUI_MOCK_FALLBACK = os.getenv("COMFYUI_MOCK_FALLBACK", "false").lower() == "true"
COMFYUI_TIMEOUT_SECONDS = int(os.getenv("COMFYUI_TIMEOUT_SECONDS", "900"))


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


BOT_UPDATES_MODE = os.getenv("BOT_UPDATES_MODE", os.getenv("BOT_MODE", "disabled")).strip().lower()
if BOT_UPDATES_MODE not in {"webhook", "polling", "disabled"}:
    BOT_UPDATES_MODE = "disabled"
BOT_MODE = BOT_UPDATES_MODE
TELEGRAM_POLLING_ENABLED = env_bool("TELEGRAM_POLLING_ENABLED", True)
MAX_POLLING_ENABLED = env_bool("MAX_POLLING_ENABLED", True)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_INIT_DATA_TTL_SECONDS = int(os.getenv("TELEGRAM_INIT_DATA_TTL_SECONDS", str(60 * 60 * 24)))
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "")
MAX_WEB_APP_DATA_TTL_SECONDS = int(os.getenv("MAX_WEB_APP_DATA_TTL_SECONDS", str(60 * 60 * 24)))
MAX_API_BASE_URL = os.getenv("MAX_API_BASE_URL", "https://platform-api.max.ru")
MAX_WEBHOOK_SECRET = os.getenv("MAX_WEBHOOK_SECRET", "")
DEFAULT_NEG_PROMPT = "low quality, deformed, blurry, watermark, ugly, bad anatomy, disfigured, mutated, extra limbs, poorly drawn face, bad proportions, jpeg artifacts"
SESSION_HMAC_SECRET = os.getenv("SESSION_HMAC_SECRET", "")
# Backward-compatible fallback default for the access/session lifetime.
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60 * 24 * 30)))
# Phase 4.1: split access/session and refresh lifetimes.
SESSION_ACCESS_TTL_SECONDS = int(os.getenv("SESSION_ACCESS_TTL_SECONDS", os.getenv("SESSION_TTL_SECONDS", "3600")))
SESSION_REFRESH_TTL_SECONDS = int(os.getenv("SESSION_REFRESH_TTL_SECONDS", str(60 * 60 * 24 * 30)))

# Phase 13: HttpOnly trusted-session cookies. The session cookie name stays
# "onenode_session" so the existing resolver keeps working. Cookies are the
# transport for raw tokens; the DB still stores only hashes.
TRUSTED_SESSION_COOKIE_NAME = os.getenv("TRUSTED_SESSION_COOKIE_NAME", "onenode_session")
TRUSTED_REFRESH_COOKIE_NAME = os.getenv("TRUSTED_REFRESH_COOKIE_NAME", "onenode_refresh")
TRUSTED_COOKIE_SECURE = os.getenv(
    "TRUSTED_COOKIE_SECURE", "true" if APP_ENV.lower() == "production" else "false"
).lower() == "true"
TRUSTED_COOKIE_SAMESITE = os.getenv("TRUSTED_COOKIE_SAMESITE", "lax")
TRUSTED_COOKIE_DOMAIN = os.getenv("TRUSTED_COOKIE_DOMAIN", "") or None
TRUSTED_COOKIE_PATH = os.getenv("TRUSTED_COOKIE_PATH", "/")
SESSION_COOKIE_NAME = TRUSTED_SESSION_COOKIE_NAME
BOT_LOGIN_CHALLENGE_COOKIE_NAME = os.getenv("BOT_LOGIN_CHALLENGE_COOKIE_NAME", "onenode_bot_login")
BOT_LOGIN_CHALLENGE_TTL_SECONDS = int(os.getenv("BOT_LOGIN_CHALLENGE_TTL_SECONDS", "600"))
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "")
TELEGRAM_BOT_DEEP_LINK_BASE = os.getenv("TELEGRAM_BOT_DEEP_LINK_BASE", "")
MAX_BOT_DEEP_LINK_BASE = os.getenv("MAX_BOT_DEEP_LINK_BASE", "")

# Phase 18: client-IP trust. Default OFF (use the direct socket peer). Behind the
# Cloudflare tunnel the socket peer is 127.0.0.1, so the real client IP arrives in
# CF-Connecting-IP — trust it ONLY when explicitly enabled (the origin is reachable
# only via the tunnel, so the header cannot be spoofed by direct internet clients).
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true"
TRUST_CLOUDFLARE_HEADERS = os.getenv("TRUST_CLOUDFLARE_HEADERS", "false").lower() == "true"

# Phase 13.2: explicit CORS origins. A wildcard origin together with credentials is
# rejected by browsers and is unsafe, so we read an explicit allowlist from
# CORS_ALLOWED_ORIGINS (comma-separated) and fall back to the known dev + tunnel
# origins. allow_credentials stays True so cookie auth works.
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,https://izo.alikinas.ru",
    ).split(",")
    if o.strip()
]

# Email OTP login (Phase 8). No real email is sent in dev/test; a mock sender is
# used. EMAIL_OTP_DEBUG_RETURN_CODE may only be enabled outside production.
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "")
EMAIL_OTP_TTL_SECONDS = int(os.getenv("EMAIL_OTP_TTL_SECONDS", "300"))
EMAIL_OTP_MAX_ATTEMPTS = int(os.getenv("EMAIL_OTP_MAX_ATTEMPTS", "5"))
EMAIL_OTP_LENGTH = int(os.getenv("EMAIL_OTP_LENGTH", "6"))
EMAIL_OTP_DEBUG_RETURN_CODE = os.getenv("EMAIL_OTP_DEBUG_RETURN_CODE", "false").lower() == "true"

# Phase 8.1: email-OTP abuse controls (cooldown, per-email / per-IP windows,
# active-challenge cap, and cleanup of stale challenges).
EMAIL_OTP_REQUEST_COOLDOWN_SECONDS = int(os.getenv("EMAIL_OTP_REQUEST_COOLDOWN_SECONDS", "60"))
EMAIL_OTP_MAX_REQUESTS_PER_EMAIL_WINDOW = int(os.getenv("EMAIL_OTP_MAX_REQUESTS_PER_EMAIL_WINDOW", "5"))
EMAIL_OTP_EMAIL_WINDOW_SECONDS = int(os.getenv("EMAIL_OTP_EMAIL_WINDOW_SECONDS", "900"))
EMAIL_OTP_MAX_REQUESTS_PER_IP_WINDOW = int(os.getenv("EMAIL_OTP_MAX_REQUESTS_PER_IP_WINDOW", "20"))
EMAIL_OTP_IP_WINDOW_SECONDS = int(os.getenv("EMAIL_OTP_IP_WINDOW_SECONDS", "900"))
EMAIL_OTP_MAX_ACTIVE_CHALLENGES_PER_EMAIL = int(os.getenv("EMAIL_OTP_MAX_ACTIVE_CHALLENGES_PER_EMAIL", "3"))
EMAIL_OTP_CLEANUP_EXPIRED_AFTER_SECONDS = int(os.getenv("EMAIL_OTP_CLEANUP_EXPIRED_AFTER_SECONDS", "86400"))

# Dev/test mock email outbox. Records destination + timestamp only — never the OTP.
_mock_email_outbox: list[dict[str, str]] = []

app = FastAPI(title="OneNode Image Studio API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/media", StaticFiles(directory=MEDIA), name="media")


class Lora(BaseModel):
    id: str
    strength: float = 1.0
    triggerWord: str | None = None


class EditImage(BaseModel):
    # Один слот edit-режима: index (1=основа, 2..4=референсы), role и сам image (data-url или media-url).
    index: int = 0
    role: str = ""
    image: str | None = None


class GenerateRequest(BaseModel):
    mode: Literal["text_to_image", "image_to_image", "edit", "paint", "inpaint", "outpaint", "faceswap", "remove_background", "try_on", "texture_transfer"]
    provider: Literal["comfyui", "openrouter"] = "comfyui"
    prompt: str = ""
    negativePrompt: str = ""
    seed: int = 42
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=1024, ge=256, le=2048)
    steps: int = Field(default=28, ge=1, le=80)
    cfg: float = Field(default=3.5, ge=0, le=20)
    guidance: float = Field(default=3.5, ge=0, le=20)
    strength: float = Field(default=0.45, ge=0, le=1)
    modelProfile: str = "local_flux_klein"
    loras: list[Lora] = []
    inputImage1: str | None = None
    inputImage2: str | None = None
    inputImages: list[EditImage] = []
    maskImage: str | None = None
    outpaintMask: str | None = None
    canvas: str | None = None
    outpaint: dict[str, int | bool] | None = None


class TranslateRequest(BaseModel):
    text: str
    target: Literal["en", "ru"] = "en"


class MiniAppAuthRequest(BaseModel):
    platform: Literal["web", "telegram", "max"] = "web"
    userId: str | None = None
    username: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    middleName: str | None = None
    phone: str | None = None
    email: str | None = None
    language: str = "ru"
    timezone: str | None = None
    country: str | None = None
    city: str | None = None
    ref: str | None = None
    screen: str | None = None
    userAgent: str | None = None
    initData: str | None = None
    themeParams: dict[str, Any] | None = None


class WebLoginRequest(BaseModel):
    code: str


class SessionRefreshRequest(BaseModel):
    # Optional: when omitted, the refresh token is read from the HttpOnly cookie.
    refresh_token: str | None = None


class SessionLogoutRequest(BaseModel):
    # Optional: when omitted, the session token is read from the HttpOnly cookie.
    session_token: str | None = None


class BootstrapV2Client(BaseModel):
    language: str | None = None
    timezone: str | None = None
    screen_width: int | None = None
    screen_height: int | None = None
    device_pixel_ratio: float | None = None
    app_version: str | None = None


class BootstrapV2Utm(BaseModel):
    source: str | None = None
    medium: str | None = None
    campaign: str | None = None


class TelegramAuthV2Request(BaseModel):
    # init_data is the RAW Telegram initData string. initDataUnsafe and any
    # client-supplied user id are never accepted. Default "" so a missing value
    # yields a clean 401 (not a 422) handled inside the endpoint.
    init_data: str = ""
    installation_id: str | None = None
    anonymous_id: str | None = None
    platform: Literal["telegram_mini_app"] = "telegram_mini_app"


class MaxAuthV2Request(BaseModel):
    # web_app_data is the RAW MAX WebAppData string. A client-supplied user id is
    # never accepted. Default "" so a missing value yields a clean 401, not a 422.
    web_app_data: str = ""
    installation_id: str | None = None
    anonymous_id: str | None = None
    platform: Literal["max_mini_app"] = "max_mini_app"


class BotLoginStartRequest(BaseModel):
    provider: Literal["telegram", "max"]


class EmailRequestCodeV2Request(BaseModel):
    email: str = ""
    installation_id: str | None = None
    anonymous_id: str | None = None
    platform: Literal["web_desktop", "web_mobile", "pwa", "unknown"] = "unknown"


class EmailVerifyCodeV2Request(BaseModel):
    challenge_id: str = ""
    code: str = ""
    installation_id: str | None = None
    anonymous_id: str | None = None
    platform: Literal["web_desktop", "web_mobile", "pwa", "unknown"] = "unknown"


class PasswordRegisterV2Request(BaseModel):
    email: str = ""
    password: str = ""
    password_repeat: str = ""
    accepted_terms: bool = False
    accepted_privacy: bool = False
    accepted_personal_data: bool = False
    installation_id: str | None = None
    anonymous_id: str | None = None
    platform: str = "unknown"


class PasswordLoginV2Request(BaseModel):
    email: str = ""
    password: str = ""
    installation_id: str | None = None
    anonymous_id: str | None = None
    platform: str = "unknown"


class AdminBlockV2Request(BaseModel):
    reason: str = ""


class AdminPasswordResetV2Request(BaseModel):
    new_password: str = ""
    reason: str = ""


class AdminRoleV2Request(BaseModel):
    role: Literal["user", "admin"]
    reason: str = ""


class AdminTokensV2Request(BaseModel):
    delta: int = 0
    reason: str = ""


class AdminPlanV2Request(BaseModel):
    plan: Literal["free", "mini", "plus", "pro"]
    reason: str = ""


class AdminProfileV2Request(BaseModel):
    display_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    avatar_preset: str | None = None
    reason: str = ""


class BillingInvoiceItemV2Request(BaseModel):
    package_code: str | None = None
    title: str = ""
    description: str | None = None
    quantity: int = 1
    unit_amount: int = 0
    token_amount: int = 0


class BillingCreateInvoiceV2Request(BaseModel):
    items: list[BillingInvoiceItemV2Request] = Field(default_factory=list)
    currency: str = "RUB"
    due_at: str | None = None
    reason: str = ""
    status: Literal["draft", "issued"] = "issued"


class BillingMarkPaidV2Request(BaseModel):
    amount: int = 0
    method: Literal["manual"] = "manual"
    reason: str = ""
    idempotency_key: str | None = None


class BillingCancelInvoiceV2Request(BaseModel):
    reason: str = ""


class BillingRefundV2Request(BaseModel):
    amount: int = 0
    reason: str = ""
    idempotency_key: str | None = None


class BonusGrantV2Request(BaseModel):
    token_amount: int = 0
    bonus_type: Literal["manual", "compensation", "campaign", "referral"] = "manual"
    reason: str = ""
    idempotency_key: str | None = None


class BonusCancelV2Request(BaseModel):
    reason: str = ""


class ApplyPromoV2Request(BaseModel):
    promo_code: str = ""
    reason: str = ""
    idempotency_key: str | None = None


class UserApplyPromoV2Request(BaseModel):
    promo_code: str = ""


class ReferralRewardV2Request(BaseModel):
    token_amount: int = 0
    child_internal_user_id: str | None = None
    referral_relation_id: str | None = None
    reason: str = ""
    idempotency_key: str | None = None


class ProfileUpdateV2Request(BaseModel):
    # Only these safe profile fields can be patched. role/banned/internal_user_id/
    # users.id are absent here, so they can never be changed via this endpoint.
    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    timezone: str | None = None
    city: str | None = None
    country_code: str | None = None
    avatar_url: str | None = None
    avatar_preset: str | None = None


class ConsentV2Request(BaseModel):
    consent_type: str = ""
    document_version: str = ""
    accepted: bool = True


class BootstrapV2Request(BaseModel):
    # Unknown/extra fields (user_id, internal_user_id, legacy_user_id, role, admin, ...)
    # are silently ignored: Pydantic's default is to drop fields not declared here,
    # so client-supplied identity can never enter this flow.
    platform: Literal[
        "web_desktop", "web_mobile", "telegram_mini_app", "max_mini_app",
        "pwa", "ios_app", "android_app", "unknown",
    ] = "unknown"
    installation_id: str | None = None
    anonymous_id: str | None = None
    client: BootstrapV2Client | None = None
    utm: BootstrapV2Utm | None = None


class BotCommandRequest(BaseModel):
    platform: Literal["telegram", "max"]
    text: str = "/start"
    chatId: str | None = None


class BotSendMessageRequest(BaseModel):
    chatId: str | None = None
    userId: str | None = None
    text: str


class SendImageRequest(BaseModel):
    platform: Literal["telegram", "max"]
    chatId: str | None = None
    userId: str | None = None


class FavoriteRequest(BaseModel):
    isFavorite: bool


class UseAsRequest(BaseModel):
    target: str


class AdminLimitRequest(BaseModel):
    hourly: int = Field(default=10, ge=1, le=1000)
    daily: int = Field(default=50, ge=1, le=5000)


class AdminUserRequest(BaseModel):
    userId: str
    username: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    middleName: str | None = None
    phone: str | None = None
    email: str | None = None
    country: str | None = None
    city: str | None = None
    role: Literal["user", "admin"] = "user"
    plan: Literal["free", "mini", "plus", "pro"] = "mini"
    tokenBalance: int = Field(default=50, ge=0, le=1_000_000)
    galleryEnabled: bool = True


class AdminUserUpdateRequest(BaseModel):
    role: Literal["user", "admin"] | None = None
    plan: Literal["free", "mini", "plus", "pro"] | None = None
    tokenBalance: int | None = Field(default=None, ge=0, le=1_000_000)
    galleryEnabled: bool | None = None
    banned: bool | None = None
    phone: str | None = None
    email: str | None = None
    country: str | None = None
    city: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    middleName: str | None = None


class HeartbeatRequest(BaseModel):
    userId: str | None = None
    platform: Literal["web", "telegram", "max"] = "web"
    seconds: int = Field(default=60, ge=1, le=600)


class AdminPromoRequest(BaseModel):
    code: str
    tokens: int = Field(default=50, ge=1, le=100_000)
    activationLimit: int = Field(default=100, ge=1, le=100_000)


class AdminSettingsRequest(BaseModel):
    settings: dict[str, Any]


rate_limits = {"hourly": 10, "daily": 50}
PROMO_REFERRAL_REWARD_TOKENS = 50
PLAN_ORDER = ("free", "mini", "plus", "pro")
DEFAULT_TARIFFS: dict[str, dict[str, int]] = {
    "free": {"daily_tokens": 10, "gallery_slots": 1},
    "mini": {"daily_tokens": 50, "gallery_slots": 10},
    "plus": {"daily_tokens": 100, "gallery_slots": 50},
    "pro": {"daily_tokens": 200, "gallery_slots": 100},
}


@dataclass
class ComfyUIResult:
    prompt_id: str
    image_path: Path
    thumbnail_path: Path
    history: dict[str, Any]


jobs: dict[str, dict[str, Any]] = {}
images: dict[str, dict[str, Any]] = {}
queue: asyncio.Queue[str] = asyncio.Queue()
worker_started = False
bot_polling_started = False
bot_polling_tasks: dict[str, asyncio.Task] = {}


def request_user_id(request: Request | None = None) -> str:
    if not request:
        return "demo_user"
    user_id = request.headers.get("X-OneNode-User") or request.cookies.get("onenode_user") or "demo_user"
    if is_production_like_env() and user_id == "demo_user":
        raise HTTPException(401, "Authentication required")
    return user_id


def require_admin(request: Request) -> str:
    user_id = request_user_id(request)
    if user_id in ("demo_user",):
        raise HTTPException(403, "Admin access required")
    with db() as conn:
        row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or row["role"] != "admin":
            raise HTTPException(403, "Admin access required")
    return user_id


def validate_telegram_init_data(init_data: str) -> dict[str, str] | None:
    if not init_data or not TELEGRAM_BOT_TOKEN:
        return None
    parsed = parse_qs(init_data)
    data = {k: v[0] for k, v in parsed.items()}
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None
    check_arr = [f"{k}={v}" for k, v in sorted(data.items())]
    data_check_string = "\n".join(check_arr)
    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if computed_hash != received_hash:
        return None
    return data


class TelegramAuthError(Exception):
    """Carries a sanitized failure reason (never raw initData) for security logs."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def validate_telegram_init_data_strict(init_data: str, ttl_seconds: int | None = None) -> dict[str, Any]:
    """Strict Telegram Mini Apps initData validation (Phase 6).

    Unlike the legacy validate_telegram_init_data() (which uses the Login Widget
    secret and no freshness check), this implements the Mini Apps algorithm:
      secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
      hash       = HMAC_SHA256(key=secret_key, msg=data_check_string)
    plus constant-time comparison and an auth_date freshness window. Never trusts
    initDataUnsafe or any client-supplied user id. Raises TelegramAuthError with a
    sanitized reason; never logs/returns raw initData.
    """
    ttl = TELEGRAM_INIT_DATA_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    if not init_data or not TELEGRAM_BOT_TOKEN:
        raise TelegramAuthError("invalid_telegram_signature")
    parsed = parse_qs(init_data, keep_blank_values=True)
    data = {k: v[0] for k, v in parsed.items()}
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise TelegramAuthError("invalid_telegram_signature")
    data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        raise TelegramAuthError("invalid_telegram_signature")
    # Signature is valid from here on; remaining checks are structural.
    auth_date_raw = data.get("auth_date")
    if not auth_date_raw:
        raise TelegramAuthError("telegram_auth_date_missing")
    try:
        auth_date = int(auth_date_raw)
    except ValueError:
        raise TelegramAuthError("telegram_auth_date_missing")
    if ttl and ttl > 0 and (time.time() - auth_date) > ttl:
        raise TelegramAuthError("expired_init_data")
    user_raw = data.get("user")
    if not user_raw:
        raise TelegramAuthError("telegram_user_missing")
    try:
        user = json.loads(user_raw)
    except (json.JSONDecodeError, TypeError):
        raise TelegramAuthError("telegram_user_missing")
    if not isinstance(user, dict) or not user.get("id"):
        raise TelegramAuthError("telegram_user_missing")
    data["_user"] = user
    return data


class MaxAuthError(Exception):
    """Carries a sanitized failure reason (never raw WebAppData) for security logs."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def validate_max_web_app_data_strict(web_app_data: str, ttl_seconds: int | None = None) -> dict[str, Any]:
    """Strict MAX Mini App WebAppData validation (Phase 7).

    MAX uses the same HMAC scheme as Telegram Mini Apps:
      secret_key = HMAC_SHA256(key="WebAppData", msg=MAX_BOT_TOKEN)
      hash       = HMAC_SHA256(key=secret_key, msg=launch_params)
    where launch_params is the sorted, newline-joined "key=value" string with the
    hash excluded. Requires the hash to appear exactly once, a constant-time
    comparison, and a fresh auth_date. Never trusts a client-supplied user id.
    Raises MaxAuthError with a sanitized reason; never logs/returns raw WebAppData.
    """
    ttl = MAX_WEB_APP_DATA_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    if not web_app_data or not MAX_BOT_TOKEN:
        raise MaxAuthError("invalid_max_signature")
    parsed = parse_qs(web_app_data, keep_blank_values=True)
    hash_values = parsed.get("hash")
    if not hash_values:
        raise MaxAuthError("invalid_max_signature")          # missing hash
    if len(hash_values) > 1:
        raise MaxAuthError("invalid_max_signature")          # duplicate hash
    received_hash = hash_values[0]
    data = {k: v[0] for k, v in parsed.items() if k != "hash"}
    launch_params = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret_key = hmac.new(b"WebAppData", MAX_BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, launch_params.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        raise MaxAuthError("invalid_max_signature")
    auth_date_raw = data.get("auth_date")
    if not auth_date_raw:
        raise MaxAuthError("max_auth_date_missing")
    try:
        auth_date = int(auth_date_raw)
    except ValueError:
        raise MaxAuthError("max_auth_date_missing")
    if ttl and ttl > 0 and (time.time() - auth_date) > ttl:
        raise MaxAuthError("expired_init_data")
    user_raw = data.get("user")
    if not user_raw:
        raise MaxAuthError("max_user_missing")
    try:
        user = json.loads(user_raw)
    except (json.JSONDecodeError, TypeError):
        raise MaxAuthError("max_user_missing")
    if not isinstance(user, dict) or not user.get("id"):
        raise MaxAuthError("max_user_missing")
    data["_user"] = user
    return data


class DbGuardError(RuntimeError):
    pass


DB_GUARD_MIN_SIZE_MB = float(os.getenv("DB_GUARD_MIN_SIZE_MB", "10"))
DB_GUARD_MIN_USERS = int(os.getenv("DB_GUARD_MIN_USERS", "5"))
DB_GUARD_MIN_ACTIVE_ADMINS = int(os.getenv("DB_GUARD_MIN_ACTIVE_ADMINS", "1"))
DB_GUARD_REQUIRED_TABLES = {"users", "images", "jobs", "token_ledger", "auth_identities", "auth_sessions", "auth_passwords"}
DB_GUARD_REQUIRED_COLUMNS = {
    "users": {"id", "internal_user_id", "role", "plan", "banned", "token_balance"},
    "images": {"id", "user_id", "deleted_at"},
    "token_ledger": {"id", "user_id", "delta", "reason", "created_at"},
}
DB_GUARD_STATUS: dict[str, Any] = {
    "ok": False,
    "status": "not_checked",
    "reason": "not_checked",
    "migration_status": "unknown",
}
STARTED_AT = datetime.now(timezone.utc).isoformat()


def safe_backend_commit() -> str | None:
    env_commit = (os.getenv("GIT_COMMIT") or os.getenv("BACKEND_COMMIT") or "").strip()
    if env_commit:
        return env_commit[:40]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(ROOT.parent),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        value = result.stdout.strip()
        return value[:40] if value else None
    except Exception:
        return None


def mask_db_path(path: Path | None = None) -> str:
    p = path or DB_PATH
    try:
        resolved = p.resolve()
        return f".../{resolved.parent.name}/{resolved.name}"
    except Exception:
        return f".../{p.name}"


def db_size_mb(path: Path | None = None) -> float:
    p = path or DB_PATH
    try:
        return round(p.stat().st_size / 1024 / 1024, 2)
    except OSError:
        return 0.0


def allowed_db_paths() -> set[Path]:
    raw = os.getenv("DB_GUARD_ALLOWED_PATHS", "")
    parts = [p.strip() for p in re.split(r"[;|]", raw) if p.strip()]
    return {sqlite_path_from_database_url(part).resolve() for part in parts}


def safe_db_guard_payload(status: dict[str, Any] | None = None) -> dict[str, Any]:
    s = dict(status or DB_GUARD_STATUS)
    return {
        "ok": bool(s.get("ok")),
        "status": str(s.get("status") or "unknown"),
        "reason": truncate_admin_text(s.get("reason") or "", 160),
        "migration_status": str(s.get("migration_status") or "unknown"),
    }


def db_guard_fail(reason: str, *, migration_status: str = "fail") -> None:
    DB_GUARD_STATUS.update({"ok": False, "status": "fail", "reason": reason, "migration_status": migration_status})
    print(f"DB guard failed: {reason}")
    raise DbGuardError(reason)


def db_guard_preflight() -> None:
    if not is_production_like_env():
        return
    if not (os.getenv("DATABASE_URL") or "").strip():
        db_guard_fail("DATABASE_URL is required in production/live mode.", migration_status="not_started")
    resolved = DB_PATH.resolve()
    allowed = allowed_db_paths()
    if allowed and resolved not in allowed:
        db_guard_fail(f"DB path is not in production allowlist: {mask_db_path(resolved)}", migration_status="not_started")
    if not DB_PATH.exists():
        db_guard_fail(f"DB file does not exist: {mask_db_path(DB_PATH)}", migration_status="not_started")
    min_bytes = int(DB_GUARD_MIN_SIZE_MB * 1024 * 1024)
    try:
        size = DB_PATH.stat().st_size
    except OSError:
        size = 0
    if size < min_bytes:
        db_guard_fail(f"DB file is suspiciously small: {db_size_mb(DB_PATH)} MB", migration_status="not_started")


def collect_db_guard_status() -> dict[str, Any]:
    status: dict[str, Any] = {
        "ok": False,
        "status": "fail",
        "reason": "",
        "migration_status": "fail",
        "db_type": "sqlite",
        "db_path": mask_db_path(DB_PATH),
        "db_size_mb": db_size_mb(DB_PATH),
        "users_count": 0,
        "active_admin_count": 0,
    }
    if not DB_PATH.exists():
        status["reason"] = f"DB file does not exist: {mask_db_path(DB_PATH)}"
        return status
    with db() as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        missing_tables = sorted(DB_GUARD_REQUIRED_TABLES - tables)
        if missing_tables:
            status["reason"] = f"Missing required tables: {', '.join(missing_tables)}"
            return status
        for table, required in DB_GUARD_REQUIRED_COLUMNS.items():
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            missing_columns = sorted(required - columns)
            if missing_columns:
                status["reason"] = f"Missing required columns: {table}.{', '.join(missing_columns)}"
                return status
        users_count = int(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] or 0)
        active_admin_count = int(conn.execute("SELECT COUNT(*) AS c FROM users WHERE role='admin' AND COALESCE(banned,0)=0").fetchone()["c"] or 0)
        status["users_count"] = users_count
        status["active_admin_count"] = active_admin_count
        if is_production_like_env() and users_count < DB_GUARD_MIN_USERS:
            status["reason"] = f"Users count below production minimum: {users_count}"
            return status
        if is_production_like_env() and active_admin_count < DB_GUARD_MIN_ACTIVE_ADMINS:
            status["reason"] = f"Active admin count below production minimum: {active_admin_count}"
            return status
    status.update({"ok": True, "status": "ok", "reason": "ok", "migration_status": "ok"})
    return status


def enforce_db_guard_after_migrations() -> None:
    status = collect_db_guard_status()
    DB_GUARD_STATUS.update(status)
    if is_production_like_env() and not status["ok"]:
        db_guard_fail(str(status.get("reason") or "DB guard failed after migrations."))


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                telegram_id TEXT,
                max_id TEXT,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language TEXT NOT NULL DEFAULT 'ru',
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL,
                last_login_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                mode TEXT NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                prompt_original TEXT,
                prompt_translated TEXT,
                result_image_id TEXT,
                error_message TEXT,
                settings_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS images (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                job_id TEXT,
                url TEXT NOT NULL,
                thumbnail_url TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                mode TEXT NOT NULL,
                provider TEXT NOT NULL,
                prompt_original TEXT,
                prompt_translated TEXT,
                settings_json TEXT NOT NULL DEFAULT '{}',
                is_favorite INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS presets (
                id TEXT PRIMARY KEY,
                owner_user_id TEXT,
                is_system INTEGER NOT NULL DEFAULT 1,
                name_ru TEXT NOT NULL,
                name_en TEXT NOT NULL,
                description_ru TEXT,
                description_en TEXT,
                mode TEXT NOT NULL,
                prompt_template_ru TEXT,
                prompt_template_en TEXT,
                required_inputs TEXT NOT NULL DEFAULT '[]',
                settings_json TEXT NOT NULL DEFAULT '{}',
                is_visible INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS loras (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT,
                trigger_word TEXT,
                default_strength REAL NOT NULL DEFAULT 1,
                description TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                compatible_modes TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS model_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider TEXT NOT NULL,
                model_name TEXT NOT NULL,
                default_width INTEGER NOT NULL DEFAULT 1024,
                default_height INTEGER NOT NULL DEFAULT 1024,
                default_steps INTEGER NOT NULL DEFAULT 28,
                default_cfg REAL NOT NULL DEFAULT 3.5,
                supports_text_to_image INTEGER NOT NULL DEFAULT 1,
                supports_image_to_image INTEGER NOT NULL DEFAULT 1,
                supports_edit INTEGER NOT NULL DEFAULT 1,
                supports_paint INTEGER NOT NULL DEFAULT 1,
                supports_inpaint INTEGER NOT NULL DEFAULT 1,
                supports_outpaint INTEGER NOT NULL DEFAULT 1,
                supports_faceswap INTEGER NOT NULL DEFAULT 1,
                supports_lora INTEGER NOT NULL DEFAULT 1,
                settings_json TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS admin_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bot_polling_state (
                provider TEXT PRIMARY KEY,
                cursor TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS auth_login_challenges (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                browser_nonce_hash TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                internal_user_id TEXT,
                provider_user_id TEXT,
                provider_username TEXT,
                approved_at TEXT,
                consumed_at TEXT,
                created_at TEXT NOT NULL,
                created_ip TEXT,
                user_agent TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_auth_login_challenges_provider_status ON auth_login_challenges(provider, status);
            CREATE INDEX IF NOT EXISTS idx_auth_login_challenges_expires ON auth_login_challenges(expires_at);

            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                tokens INTEGER NOT NULL DEFAULT 0,
                activation_limit INTEGER NOT NULL DEFAULT 1,
                activation_count INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS token_ledger (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                delta INTEGER NOT NULL,
                reason TEXT NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS billing_packages (
                id TEXT PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                price_amount INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'RUB',
                token_amount INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS invoices (
                id TEXT PRIMARY KEY,
                invoice_code TEXT NOT NULL UNIQUE,
                internal_user_id TEXT NOT NULL,
                user_id TEXT,
                status TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'RUB',
                subtotal_amount INTEGER NOT NULL DEFAULT 0,
                discount_amount INTEGER NOT NULL DEFAULT 0,
                total_amount INTEGER NOT NULL DEFAULT 0,
                tokens_total INTEGER NOT NULL DEFAULT 0,
                due_at TEXT,
                issued_at TEXT,
                paid_at TEXT,
                cancelled_at TEXT,
                refunded_at TEXT,
                created_by_admin_id TEXT,
                updated_by_admin_id TEXT,
                reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS invoice_items (
                id TEXT PRIMARY KEY,
                invoice_id TEXT NOT NULL,
                package_code TEXT,
                title TEXT NOT NULL,
                description TEXT,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_amount INTEGER NOT NULL DEFAULT 0,
                total_amount INTEGER NOT NULL DEFAULT 0,
                token_amount INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                invoice_id TEXT NOT NULL,
                internal_user_id TEXT NOT NULL,
                user_id TEXT,
                status TEXT NOT NULL,
                amount INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'RUB',
                method TEXT NOT NULL DEFAULT 'manual',
                provider TEXT NOT NULL DEFAULT 'manual',
                provider_payment_id TEXT,
                paid_at TEXT,
                created_by_admin_id TEXT,
                reason TEXT,
                token_ledger_id TEXT,
                idempotency_key TEXT UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS refunds (
                id TEXT PRIMARY KEY,
                payment_id TEXT NOT NULL,
                invoice_id TEXT NOT NULL,
                internal_user_id TEXT NOT NULL,
                amount INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'RUB',
                status TEXT NOT NULL,
                reason TEXT,
                created_by_admin_id TEXT,
                token_reversal_ledger_id TEXT,
                idempotency_key TEXT UNIQUE,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS promo_redemptions (
                id TEXT PRIMARY KEY,
                promo_code_id TEXT,
                promo_code TEXT NOT NULL,
                internal_user_id TEXT NOT NULL,
                user_id TEXT,
                status TEXT NOT NULL,
                discount_amount INTEGER,
                token_bonus INTEGER,
                reason TEXT,
                token_ledger_id TEXT,
                created_by_admin_id TEXT,
                idempotency_key TEXT UNIQUE,
                created_at TEXT NOT NULL,
                cancelled_at TEXT
            );

            CREATE TABLE IF NOT EXISTS bonus_grants (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT NOT NULL,
                user_id TEXT,
                bonus_type TEXT NOT NULL,
                token_amount INTEGER NOT NULL DEFAULT 0,
                money_amount INTEGER,
                currency TEXT,
                status TEXT NOT NULL,
                reason TEXT,
                token_ledger_id TEXT,
                cancelled_ledger_id TEXT,
                created_by_admin_id TEXT,
                idempotency_key TEXT UNIQUE,
                created_at TEXT NOT NULL,
                cancelled_at TEXT
            );

            CREATE TABLE IF NOT EXISTS referral_links (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT NOT NULL,
                user_id TEXT,
                referral_code TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                disabled_at TEXT
            );

            CREATE TABLE IF NOT EXISTS referral_relations (
                id TEXT PRIMARY KEY,
                parent_internal_user_id TEXT NOT NULL,
                child_internal_user_id TEXT NOT NULL,
                referral_code TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                cancelled_at TEXT
            );

            CREATE TABLE IF NOT EXISTS referral_rewards (
                id TEXT PRIMARY KEY,
                referral_relation_id TEXT,
                parent_internal_user_id TEXT NOT NULL,
                child_internal_user_id TEXT,
                reward_type TEXT NOT NULL,
                token_amount INTEGER,
                money_amount INTEGER,
                currency TEXT,
                status TEXT NOT NULL,
                reason TEXT,
                token_ledger_id TEXT,
                created_by_admin_id TEXT,
                idempotency_key TEXT UNIQUE,
                created_at TEXT NOT NULL,
                granted_at TEXT,
                cancelled_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_invoices_user_created ON invoices(internal_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_invoices_status_created ON invoices(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_payments_user_created ON payments(internal_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
            CREATE INDEX IF NOT EXISTS idx_refunds_user_created ON refunds(internal_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);
            CREATE INDEX IF NOT EXISTS idx_promo_redemptions_user_created ON promo_redemptions(internal_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_bonus_grants_user_created ON bonus_grants(internal_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_referral_links_code ON referral_links(referral_code);
            CREATE INDEX IF NOT EXISTS idx_referral_relations_parent_created ON referral_relations(parent_internal_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_referral_relations_child_created ON referral_relations(child_internal_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_referral_rewards_parent_created ON referral_rewards(parent_internal_user_id, created_at);
            """
        )
        existing_user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "plan" not in existing_user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'mini'")
        if "token_balance" not in existing_user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN token_balance INTEGER NOT NULL DEFAULT 50")
        if "gallery_enabled" not in existing_user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN gallery_enabled INTEGER NOT NULL DEFAULT 1")
        for column, definition in {
            "phone": "TEXT",
            "email": "TEXT",
            "middle_name": "TEXT",
            "country": "TEXT",
            "city": "TEXT",
            "timezone": "TEXT",
            "ref_code": "TEXT",
            "last_user_agent": "TEXT",
            "last_screen": "TEXT",
            "last_seen_at": "TEXT",
            "total_time_seconds": "INTEGER NOT NULL DEFAULT 0",
            "generation_count": "INTEGER NOT NULL DEFAULT 0",
            "tokens_used": "INTEGER NOT NULL DEFAULT 0",
            "promo_used_count": "INTEGER NOT NULL DEFAULT 0",
            "referrals_count": "INTEGER NOT NULL DEFAULT 0",
            "banned": "INTEGER NOT NULL DEFAULT 0",
            "display_name": "TEXT",
            "email_verified_at": "TEXT",
            "phone_verified_at": "TEXT",
            "public_user_code": "TEXT",
            "avatar_url": "TEXT",
            "avatar_preset": "TEXT",
            "daily_tokens_used": "INTEGER NOT NULL DEFAULT 0",
            "last_daily_reset": "TEXT",
        }.items():
            if column not in existing_user_columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
        existing_image_columns = {row["name"] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
        if "deleted_at" not in existing_image_columns:
            conn.execute("ALTER TABLE images ADD COLUMN deleted_at TEXT")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT OR IGNORE INTO users (id, username, first_name, language, role, created_at, last_login_at)
            VALUES ('demo_user', 'demo', 'Demo', 'ru', 'admin', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO model_profiles (id, name, provider, model_name)
            VALUES ('local_flux_klein', 'Local Flux Klein', 'comfyui', 'flux-2-klein-9b-fp8.safetensors')
            """,
        )
        # MODEL PROFILE: canonical 4B/9B profiles. We must support both free models and
        # never hardcode a single one. supports_pose is additive (default 0). The exact
        # required-file fingerprints live in settings_json so the admin status endpoint can
        # cross-check them against the live ComfyUI install.
        existing_profile_columns = {row["name"] for row in conn.execute("PRAGMA table_info(model_profiles)").fetchall()}
        if "supports_pose" not in existing_profile_columns:
            conn.execute("ALTER TABLE model_profiles ADD COLUMN supports_pose INTEGER NOT NULL DEFAULT 0")
        seed_profiles = [
            (
                "flux_klein_4b", "FLUX.2 [klein] 4B", "flux-2-klein-4b-fp8.safetensors", 0,
                {
                    "variant": "4b",
                    "unet": "flux-2-klein-4b-fp8.safetensors",
                    "text_encoder": "qwen_3_4b",
                    "vae": "flux2-vae.safetensors",
                    "faceswap_lora": "bfs_head_v1_flux-klein_4b",
                    "node": "FluxKleinOneNode",
                    "pose": {"supported": False, "reason": "repo refcontrol pose LoRA is published for 9B only"},
                },
            ),
            (
                "flux_klein_9b", "FLUX.2 [klein] 9B", "flux-2-klein-9b-fp8.safetensors", 1,
                {
                    "variant": "9b",
                    "unet": "flux-2-klein-9b-fp8.safetensors",
                    "text_encoder": "qwen_3_8b",
                    "vae": "flux2-vae.safetensors",
                    "faceswap_lora": "bfs_head_v1_flux-klein_9b",
                    "node": "FluxKleinOneNode",
                    "pose": {
                        "supported": True,
                        "lora": "refcontrol_v2_poses.safetensors",
                        "preprocessor_node": "DWPreprocessor",
                        "workflow": "pose",
                    },
                },
            ),
        ]
        for pid, pname, model_name, supports_pose, settings in seed_profiles:
            conn.execute(
                """
                INSERT OR IGNORE INTO model_profiles (id, name, provider, model_name, supports_pose, settings_json)
                VALUES (?, ?, 'comfyui', ?, ?, ?)
                """,
                (pid, pname, model_name, supports_pose, json.dumps(settings, ensure_ascii=False)),
            )
        seed_presets = [
            ("portrait", "Кинематографичный портрет", "Cinematic portrait", "text_to_image"),
            ("enhance", "Улучшить качество", "Enhance quality", "edit"),
            ("collage", "Коллаж в сцену", "Collage to scene", "paint"),
        ]
        for preset_id, name_ru, name_en, mode in seed_presets:
            conn.execute(
                """
                INSERT OR IGNORE INTO presets (id, name_ru, name_en, mode, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (preset_id, name_ru, name_en, mode, now, now),
            )

        # --- Identity Core: additive-only schema (Phase 3) ---------------------
        # Does NOT change auth behaviour. Adds canonical identity scaffolding
        # alongside the legacy provider-based users.id, plus idempotent backfill.
        if "internal_user_id" not in existing_user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN internal_user_id TEXT")

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS auth_identities (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT NOT NULL,
                legacy_user_id TEXT,
                provider TEXT NOT NULL,
                provider_user_id TEXT NOT NULL,
                provider_username TEXT,
                provider_email TEXT,
                provider_phone TEXT,
                provider_first_name TEXT,
                provider_last_name TEXT,
                provider_avatar_url TEXT,
                provider_language_code TEXT,
                raw_profile_json TEXT,
                verified_at TEXT,
                linked_at TEXT NOT NULL,
                last_login_at TEXT,
                UNIQUE(provider, provider_user_id)
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT NOT NULL,
                legacy_user_id TEXT,
                session_token_hash TEXT NOT NULL UNIQUE,
                refresh_token_hash TEXT UNIQUE,
                provider TEXT,
                platform TEXT,
                ip_address TEXT,
                user_agent_hash TEXT,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                revoke_reason TEXT,
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS session_events (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                internal_user_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                ip_address TEXT,
                user_agent_hash TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS auth_login_attempts (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT,
                provider TEXT NOT NULL,
                identifier TEXT,
                success INTEGER NOT NULL,
                failure_reason TEXT,
                ip_address TEXT,
                user_agent_hash TEXT,
                platform TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS device_installations (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT,
                legacy_user_id TEXT,
                installation_id TEXT NOT NULL UNIQUE,
                anonymous_id TEXT,
                platform TEXT NOT NULL,
                storage_type TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS user_consents (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT NOT NULL,
                consent_type TEXT NOT NULL,
                document_version TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                accepted_at TEXT NOT NULL,
                revoked_at TEXT,
                ip_address TEXT,
                user_agent_hash TEXT,
                platform TEXT,
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS security_events (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT,
                session_id TEXT,
                severity TEXT NOT NULL,
                event_type TEXT NOT NULL,
                ip_address TEXT,
                user_agent_hash TEXT,
                details_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                actor_internal_user_id TEXT,
                target_internal_user_id TEXT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                before_json TEXT,
                after_json TEXT,
                ip_address TEXT,
                user_agent_hash TEXT,
                created_at TEXT NOT NULL
            );

            -- Preparatory table for future email OTP (Phase 6). No endpoints yet.
            CREATE TABLE IF NOT EXISTS auth_otp_challenges (
                id TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                destination TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                purpose TEXT NOT NULL,
                attempts_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                expires_at TEXT NOT NULL,
                consumed_at TEXT,
                ip_address TEXT,
                user_agent_hash TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_internal_user_id ON users(internal_user_id);
            CREATE INDEX IF NOT EXISTS idx_auth_identities_internal ON auth_identities(internal_user_id);
            CREATE INDEX IF NOT EXISTS idx_auth_identities_legacy ON auth_identities(legacy_user_id);
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_internal ON auth_sessions(internal_user_id);
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires ON auth_sessions(expires_at);
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_revoked ON auth_sessions(revoked_at);
            CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events(session_id);
            CREATE INDEX IF NOT EXISTS idx_session_events_internal ON session_events(internal_user_id);
            CREATE INDEX IF NOT EXISTS idx_login_attempts_provider_ident ON auth_login_attempts(provider, identifier);
            CREATE INDEX IF NOT EXISTS idx_login_attempts_created ON auth_login_attempts(created_at);
            CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON auth_login_attempts(ip_address);
            CREATE INDEX IF NOT EXISTS idx_device_internal ON device_installations(internal_user_id);
            CREATE INDEX IF NOT EXISTS idx_consents_internal ON user_consents(internal_user_id);
            CREATE INDEX IF NOT EXISTS idx_consents_type ON user_consents(internal_user_id, consent_type);
            CREATE INDEX IF NOT EXISTS idx_security_events_internal ON security_events(internal_user_id);
            CREATE INDEX IF NOT EXISTS idx_security_events_created ON security_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_security_events_type ON security_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor_internal_user_id);
            CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_logs(target_internal_user_id);
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_otp_destination ON auth_otp_challenges(channel, destination);
            CREATE INDEX IF NOT EXISTS idx_otp_expires ON auth_otp_challenges(expires_at);

            CREATE TABLE IF NOT EXISTS event_logs (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT,
                legacy_user_id TEXT,
                anonymous_id TEXT,
                installation_id TEXT,
                session_id TEXT,
                event_name TEXT NOT NULL,
                platform TEXT,
                device_type TEXT,
                ip_address TEXT,
                user_agent_hash TEXT,
                properties_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_event_logs_internal ON event_logs(internal_user_id);
            CREATE INDEX IF NOT EXISTS idx_event_logs_anonymous ON event_logs(anonymous_id);
            CREATE INDEX IF NOT EXISTS idx_event_logs_installation ON event_logs(installation_id);
            CREATE INDEX IF NOT EXISTS idx_event_logs_event_name ON event_logs(event_name);
            CREATE INDEX IF NOT EXISTS idx_event_logs_created ON event_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_event_logs_platform ON event_logs(platform);

            -- Phase 14.4: password auth foundation (schema only; no endpoints yet).
            CREATE TABLE IF NOT EXISTS auth_passwords (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                algorithm TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                disabled_at TEXT,
                password_updated_at TEXT,
                metadata_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_auth_passwords_internal_user_id ON auth_passwords(internal_user_id);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_auth_passwords_active
                ON auth_passwords(internal_user_id) WHERE disabled_at IS NULL;

            CREATE TABLE IF NOT EXISTS password_reset_challenges (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT,
                created_at TEXT NOT NULL,
                ip_address TEXT,
                user_agent_hash TEXT,
                metadata_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_password_reset_internal_user_id ON password_reset_challenges(internal_user_id);
            CREATE INDEX IF NOT EXISTS idx_password_reset_token_hash ON password_reset_challenges(token_hash);
            CREATE INDEX IF NOT EXISTS idx_password_reset_expires_at ON password_reset_challenges(expires_at);
            """
        )

        # Phase 4.1: refresh tokens get their own lifetime, tracked separately from
        # the access/session expires_at. Additive, safe ALTER for existing DBs.
        auth_sessions_columns = {row["name"] for row in conn.execute("PRAGMA table_info(auth_sessions)").fetchall()}
        if "refresh_expires_at" not in auth_sessions_columns:
            conn.execute("ALTER TABLE auth_sessions ADD COLUMN refresh_expires_at TEXT")

        backfill_identity_core(conn, now)

        # Canonical-identity uniqueness, created AFTER backfill so it validates
        # the populated values. Partial index keeps NULLs allowed during rollout.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_internal_user_id "
            "ON users(internal_user_id) WHERE internal_user_id IS NOT NULL"
        )

        # Phase 18: human-readable public_user_code (stable, unique, not an auth key).
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_public_user_code "
            "ON users(public_user_code) WHERE public_user_code IS NOT NULL"
        )
        for row in conn.execute(
            "SELECT internal_user_id FROM users WHERE public_user_code IS NULL AND internal_user_id IS NOT NULL"
        ).fetchall():
            ensure_public_user_code(conn, row["internal_user_id"])


PROVIDER_CODE_PREFIX = {"web_email": "WEB", "telegram": "TG", "max": "MAX"}


def resolve_primary_provider(conn: sqlite3.Connection, internal_user_id: str) -> str | None:
    """Primary provider = most recent successful-login identity, else first linked."""
    row = conn.execute(
        "SELECT provider FROM auth_identities WHERE internal_user_id = ? "
        "ORDER BY (last_login_at IS NULL), last_login_at DESC, linked_at ASC LIMIT 1",
        (internal_user_id,),
    ).fetchone()
    return row["provider"] if row else None


def ensure_public_user_code(conn: sqlite3.Connection, internal_user_id: str) -> str | None:
    """Assign a stable public_user_code once (e.g. WEB-000001). Idempotent: returns
    the existing code if already set. Prefix reflects the primary provider at creation
    and stays stable afterward. Never an auth key."""
    if not internal_user_id:
        return None
    row = conn.execute("SELECT public_user_code FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
    if row is None:
        return None
    if row["public_user_code"]:
        return row["public_user_code"]
    provider = resolve_primary_provider(conn, internal_user_id)
    legacy_id = conn.execute("SELECT id FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
    prefix = PROVIDER_CODE_PREFIX.get(provider or "")
    if not prefix and legacy_id:
        lid = str(legacy_id["id"])
        prefix = "TG" if lid.startswith("telegram_") else "MAX" if lid.startswith("max_") else "WEB" if lid.startswith("web_") else None
    prefix = prefix or "USR"
    # Global monotonic number across all codes keeps every code unique.
    nums = [
        int(m.group(1))
        for (code,) in conn.execute("SELECT public_user_code FROM users WHERE public_user_code IS NOT NULL")
        if (m := re.search(r"-(\d+)$", code or ""))
    ]
    next_num = (max(nums) + 1) if nums else 1
    code = f"{prefix}-{next_num:06d}"
    conn.execute("UPDATE users SET public_user_code = ? WHERE internal_user_id = ? AND public_user_code IS NULL", (code, internal_user_id))
    return code


def resolve_display_name(urow: sqlite3.Row | None, identity: sqlite3.Row | None = None) -> str:
    """display_name priority: users.display_name → provider first+last → provider_username
    → email local-part → public_user_code → 'Пользователь'."""
    dn = _row_get(urow, "display_name")
    if dn:
        return str(dn)
    first = _row_get(urow, "first_name") or _row_get(identity, "provider_first_name")
    last = _row_get(urow, "last_name") or _row_get(identity, "provider_last_name")
    full = " ".join(p for p in (first, last) if p).strip()
    if full:
        return full
    username = _row_get(urow, "username") or _row_get(identity, "provider_username")
    if username:
        return str(username)
    email = _row_get(urow, "email") or _row_get(identity, "provider_email")
    if email and "@" in str(email):
        return str(email).split("@", 1)[0]
    code = _row_get(urow, "public_user_code")
    if code:
        return str(code)
    return "Пользователь"


def backfill_identity_core(conn: sqlite3.Connection, now: str) -> None:
    """Idempotent, additive backfill for Identity Core.

    1. Assign a canonical internal_user_id (uuid4 hex) to every user missing one.
       Never touches users.id.
    2. Backfill auth_identities from legacy users.telegram_id / users.max_id, only
       when those columns exist and hold a non-empty value. INSERT OR IGNORE plus
       UNIQUE(provider, provider_user_id) guarantee no duplicates on re-runs.

    Does NOT guess web/email identities from legacy/unverified data.
    Raises RuntimeError if duplicate provider ids are detected, rather than
    silently merging distinct users.
    """
    # 1. internal_user_id for users that don't have one yet (id is never updated).
    for row in conn.execute("SELECT id FROM users WHERE internal_user_id IS NULL").fetchall():
        conn.execute(
            "UPDATE users SET internal_user_id = ? WHERE id = ? AND internal_user_id IS NULL",
            (uuid.uuid4().hex, row["id"]),
        )

    user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}

    # 2. auth_identities backfill from each legacy provider column.
    for provider, column in (("telegram", "telegram_id"), ("max", "max_id")):
        if column not in user_columns:
            continue
        duplicates = conn.execute(
            f"SELECT {column} AS pid, COUNT(*) AS c FROM users "
            f"WHERE {column} IS NOT NULL AND {column} <> '' "
            f"GROUP BY {column} HAVING c > 1"
        ).fetchall()
        if duplicates:
            raise RuntimeError(
                f"Duplicate {column} values detected across distinct users "
                f"({[d['pid'] for d in duplicates]}); refusing to backfill "
                f"auth_identities to avoid silently merging users."
            )
        for row in conn.execute(
            f"SELECT id, internal_user_id, {column} AS pid FROM users "
            f"WHERE {column} IS NOT NULL AND {column} <> ''"
        ).fetchall():
            conn.execute(
                """
                INSERT OR IGNORE INTO auth_identities
                    (id, internal_user_id, legacy_user_id, provider, provider_user_id, linked_at, verified_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (uuid.uuid4().hex, row["internal_user_id"], row["id"], provider, str(row["pid"]), now),
            )


# ---------------------------------------------------------------------------
# Identity Core session service (Phase 4)
#
# Server-issued, hash-only sessions. The client receives raw session/refresh
# tokens; the database stores only their hashes. This service is ADDITIVE and
# does NOT replace request_user_id()/require_admin() yet — it is the trusted
# foundation that later phases will switch onto.
# ---------------------------------------------------------------------------


def generate_secure_token() -> str:
    """Cryptographically secure, opaque token with no embedded PII."""
    return secrets.token_urlsafe(48)


def generate_bot_login_token() -> str:
    """Short opaque token that fits Telegram callback_data; DB stores only hash."""
    return secrets.token_urlsafe(18)


def hash_token(raw_token: str) -> str:
    """Deterministic hash of a raw token. Raw tokens are never stored or logged."""
    if SESSION_HMAC_SECRET:
        return hmac.new(SESSION_HMAC_SECRET.encode(), raw_token.encode(), hashlib.sha256).hexdigest()
    return hashlib.sha256(raw_token.encode()).hexdigest()


def validate_session_crypto_config() -> None:
    """Refuse the unkeyed SHA-256 fallback in production.

    Development/test may run without SESSION_HMAC_SECRET (plain SHA-256). In
    production the keyed HMAC secret is mandatory; we fail loudly rather than
    silently weakening token hashing. The secret value is never included in the
    error message.
    """
    if APP_ENV.lower() == "production" and not SESSION_HMAC_SECRET:
        raise RuntimeError(
            "SESSION_HMAC_SECRET is required when APP_ENV=production; "
            "refusing to fall back to unkeyed session-token hashing."
        )


def get_client_ip(request: Request | None) -> str | None:
    """Best-effort client IP for ANALYTICS only (never an auth decision).
    Trusts CF-Connecting-IP / X-Forwarded-For only when explicitly configured."""
    if not request:
        return None
    if TRUST_CLOUDFLARE_HEADERS:
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf.strip()
    if TRUST_PROXY_HEADERS:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _client_ip(request: Request | None) -> str | None:
    return get_client_ip(request)


def parse_user_agent(ua: str | None) -> dict[str, str]:
    """Coarse, dependency-free UA classification for analytics (no raw UA stored)."""
    s = (ua or "").lower()
    if not s:
        return {"device_type": "unknown", "browser": "unknown", "os": "unknown"}
    if "telegram" in s:
        browser = "telegram_webview"
    elif "max" in s and "webview" in s:
        browser = "max_webview"
    elif "edg/" in s or "edge" in s:
        browser = "edge"
    elif "chrome" in s or "crios" in s:
        browser = "chrome"
    elif "firefox" in s or "fxios" in s:
        browser = "firefox"
    elif "safari" in s:
        browser = "safari"
    else:
        browser = "unknown"
    if "android" in s:
        os_name = "android"
    elif "iphone" in s or "ipad" in s or "ios" in s:
        os_name = "ios"
    elif "windows" in s:
        os_name = "windows"
    elif "mac os" in s or "macintosh" in s:
        os_name = "macos"
    elif "linux" in s:
        os_name = "linux"
    else:
        os_name = "unknown"
    if "ipad" in s or "tablet" in s:
        device_type = "tablet"
    elif "mobi" in s or "android" in s or "iphone" in s:
        device_type = "mobile"
    else:
        device_type = "desktop"
    return {"device_type": device_type, "browser": browser, "os": os_name}


def _hash_user_agent(request: Request | None) -> str | None:
    if not request:
        return None
    ua = request.headers.get("user-agent")
    return hashlib.sha256(ua.encode()).hexdigest() if ua else None


def _extract_session_token(request: Request) -> str | None:
    """Read the bearer token from Authorization, else the session cookie.

    Never reads X-OneNode-User or the legacy onenode_user cookie.
    """
    header = request.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(SESSION_COOKIE_NAME)


def record_session_event(
    conn: sqlite3.Connection,
    session_id: str,
    internal_user_id: str,
    event_type: str,
    request: Request | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO session_events (id, session_id, internal_user_id, event_type, ip_address, user_agent_hash, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            session_id,
            internal_user_id,
            event_type,
            _client_ip(request),
            _hash_user_agent(request),
            json.dumps(metadata, ensure_ascii=False) if metadata else None,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def record_security_event(
    conn: sqlite3.Connection,
    event_type: str,
    severity: str = "warning",
    internal_user_id: str | None = None,
    session_id: str | None = None,
    request: Request | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    # details must never contain raw tokens, cookies or Authorization headers.
    conn.execute(
        """
        INSERT INTO security_events (id, internal_user_id, session_id, severity, event_type, ip_address, user_agent_hash, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            internal_user_id,
            session_id,
            severity,
            event_type,
            _client_ip(request),
            _hash_user_agent(request),
            json.dumps(details, ensure_ascii=False) if details else None,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def record_event_log(
    event_name: str,
    internal_user_id: str | None = None,
    legacy_user_id: str | None = None,
    anonymous_id: str | None = None,
    installation_id: str | None = None,
    session_id: str | None = None,
    platform: str | None = None,
    device_type: str | None = None,
    request: Request | None = None,
    properties: dict[str, Any] | None = None,
) -> None:
    """Product analytics event. Opens its own transaction so a failed write never
    rolls back the caller's work.

    Privacy: never stores cookies, Authorization headers, raw session/refresh
    tokens, OTP, raw Telegram initData or raw MAX WebAppData. The user agent is
    only ever persisted as a hash. The caller is responsible for passing an
    already-sanitized `properties` dict.
    """
    with db() as conn:
        conn.execute(
            """
            INSERT INTO event_logs
                (id, internal_user_id, legacy_user_id, anonymous_id, installation_id, session_id,
                 event_name, platform, device_type, ip_address, user_agent_hash, properties_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                internal_user_id,
                legacy_user_id,
                anonymous_id,
                installation_id,
                session_id,
                event_name,
                platform,
                device_type,
                _client_ip(request),
                _hash_user_agent(request),
                json.dumps(properties, ensure_ascii=False) if properties else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def record_login_attempt(
    conn: sqlite3.Connection,
    provider: str,
    success: bool,
    identifier: str | None = None,
    internal_user_id: str | None = None,
    failure_reason: str | None = None,
    platform: str | None = None,
    request: Request | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO auth_login_attempts
            (id, internal_user_id, provider, identifier, success, failure_reason, ip_address, user_agent_hash, platform, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            internal_user_id,
            provider,
            identifier,
            1 if success else 0,
            failure_reason,
            _client_ip(request),
            _hash_user_agent(request),
            platform,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def telegram_upsert_identity(conn: sqlite3.Connection, user: dict[str, Any], now: str) -> tuple[str, str]:
    """Resolve/create the canonical identity for a verified Telegram user.

    Returns (internal_user_id, legacy_user_id). Never changes an existing
    users.id; only assigns internal_user_id where missing. raw_profile_json holds
    the verified Telegram user object only (no tokens, no raw initData).
    """
    pid = str(user["id"])
    username = user.get("username")
    first = user.get("first_name")
    last = user.get("last_name")
    photo = user.get("photo_url")
    lang = user.get("language_code")
    raw_profile = json.dumps(user, ensure_ascii=False)

    existing = conn.execute(
        "SELECT id, internal_user_id, legacy_user_id FROM auth_identities WHERE provider = 'telegram' AND provider_user_id = ?",
        (pid,),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE auth_identities
            SET provider_username = ?, provider_first_name = ?, provider_last_name = ?,
                provider_avatar_url = ?, provider_language_code = ?, raw_profile_json = ?,
                verified_at = ?, last_login_at = ?
            WHERE id = ?
            """,
            (username, first, last, photo, lang, raw_profile, now, now, existing["id"]),
        )
        if existing["legacy_user_id"]:
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, existing["legacy_user_id"]))
        return existing["internal_user_id"], existing["legacy_user_id"]

    # No identity yet: try to adopt a legacy user keyed by users.telegram_id.
    user_columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    internal_user_id: str | None = None
    legacy_user_id: str | None = None
    if "telegram_id" in user_columns:
        legacy = conn.execute("SELECT id, internal_user_id FROM users WHERE telegram_id = ?", (pid,)).fetchone()
        if legacy:
            legacy_user_id = legacy["id"]
            internal_user_id = legacy["internal_user_id"]
            if not internal_user_id:
                internal_user_id = uuid.uuid4().hex
                conn.execute("UPDATE users SET internal_user_id = ? WHERE id = ?", (internal_user_id, legacy_user_id))
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, legacy_user_id))

    if internal_user_id is None:
        # Create a new user using the project's legacy-safe id format (never altered).
        legacy_user_id = f"telegram_{pid}"
        internal_user_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (id, telegram_id, username, first_name, last_name, language, role, plan, gallery_enabled,
                 created_at, last_login_at, internal_user_id)
            VALUES (?, ?, ?, ?, ?, ?, 'user', 'mini', 1, ?, ?, ?)
            """,
            (legacy_user_id, pid, username, first, last, lang or "ru", now, now, internal_user_id),
        )
        row = conn.execute("SELECT id, internal_user_id FROM users WHERE id = ?", (legacy_user_id,)).fetchone()
        if row:
            legacy_user_id = row["id"]
            if row["internal_user_id"]:
                internal_user_id = row["internal_user_id"]
            else:
                conn.execute("UPDATE users SET internal_user_id = ? WHERE id = ?", (internal_user_id, legacy_user_id))

    conn.execute(
        """
        INSERT OR IGNORE INTO auth_identities
            (id, internal_user_id, legacy_user_id, provider, provider_user_id, provider_username,
             provider_first_name, provider_last_name, provider_avatar_url, provider_language_code,
             raw_profile_json, verified_at, linked_at, last_login_at)
        VALUES (?, ?, ?, 'telegram', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, internal_user_id, legacy_user_id, pid, username, first, last, photo, lang, raw_profile, now, now, now),
    )
    return internal_user_id, legacy_user_id


def max_upsert_identity(conn: sqlite3.Connection, user: dict[str, Any], now: str) -> tuple[str, str]:
    """Resolve/create the canonical identity for a verified MAX user.

    Mirror of telegram_upsert_identity for provider='max', keyed on users.max_id
    with the legacy id format max_<id>. Never changes an existing users.id.
    """
    pid = str(user["id"])
    username = user.get("username")
    first = user.get("first_name")
    last = user.get("last_name")
    photo = user.get("photo_url")
    lang = user.get("language_code")
    raw_profile = json.dumps(user, ensure_ascii=False)

    existing = conn.execute(
        "SELECT id, internal_user_id, legacy_user_id FROM auth_identities WHERE provider = 'max' AND provider_user_id = ?",
        (pid,),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE auth_identities
            SET provider_username = ?, provider_first_name = ?, provider_last_name = ?,
                provider_avatar_url = ?, provider_language_code = ?, raw_profile_json = ?,
                verified_at = ?, last_login_at = ?
            WHERE id = ?
            """,
            (username, first, last, photo, lang, raw_profile, now, now, existing["id"]),
        )
        if existing["legacy_user_id"]:
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, existing["legacy_user_id"]))
        return existing["internal_user_id"], existing["legacy_user_id"]

    user_columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    internal_user_id: str | None = None
    legacy_user_id: str | None = None
    if "max_id" in user_columns:
        legacy = conn.execute("SELECT id, internal_user_id FROM users WHERE max_id = ?", (pid,)).fetchone()
        if legacy:
            legacy_user_id = legacy["id"]
            internal_user_id = legacy["internal_user_id"]
            if not internal_user_id:
                internal_user_id = uuid.uuid4().hex
                conn.execute("UPDATE users SET internal_user_id = ? WHERE id = ?", (internal_user_id, legacy_user_id))
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, legacy_user_id))

    if internal_user_id is None:
        legacy_user_id = f"max_{pid}"
        internal_user_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (id, max_id, username, first_name, last_name, language, role, plan, gallery_enabled,
                 created_at, last_login_at, internal_user_id)
            VALUES (?, ?, ?, ?, ?, ?, 'user', 'mini', 1, ?, ?, ?)
            """,
            (legacy_user_id, pid, username, first, last, lang or "ru", now, now, internal_user_id),
        )
        row = conn.execute("SELECT id, internal_user_id FROM users WHERE id = ?", (legacy_user_id,)).fetchone()
        if row:
            legacy_user_id = row["id"]
            if row["internal_user_id"]:
                internal_user_id = row["internal_user_id"]
            else:
                conn.execute("UPDATE users SET internal_user_id = ? WHERE id = ?", (internal_user_id, legacy_user_id))

    conn.execute(
        """
        INSERT OR IGNORE INTO auth_identities
            (id, internal_user_id, legacy_user_id, provider, provider_user_id, provider_username,
             provider_first_name, provider_last_name, provider_avatar_url, provider_language_code,
             raw_profile_json, verified_at, linked_at, last_login_at)
        VALUES (?, ?, ?, 'max', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, internal_user_id, legacy_user_id, pid, username, first, last, photo, lang, raw_profile, now, now, now),
    )
    return internal_user_id, legacy_user_id


def bot_login_deep_link(provider: Literal["telegram", "max"], token: str) -> str:
    payload = f"login_{token}"
    if provider == "telegram":
        base = TELEGRAM_BOT_DEEP_LINK_BASE.strip()
        if base:
            sep = "&" if "?" in base else "?"
            return f"{base}{sep}start={payload}"
        if TELEGRAM_BOT_USERNAME.strip():
            return f"https://t.me/{TELEGRAM_BOT_USERNAME.strip().lstrip('@')}?start={payload}"
    base = MAX_BOT_DEEP_LINK_BASE.strip()
    if base:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}start={payload}"
    raise HTTPException(503, "provider_not_configured")


def bot_login_available(provider: Literal["telegram", "max"]) -> bool:
    if provider == "telegram":
        return bool(TELEGRAM_BOT_TOKEN and (TELEGRAM_BOT_DEEP_LINK_BASE.strip() or TELEGRAM_BOT_USERNAME.strip()))
    return bool(MAX_BOT_TOKEN and MAX_BOT_DEEP_LINK_BASE.strip())


def auth_capabilities_payload() -> dict[str, Any]:
    password_register_available = bool(email_otp_available() or APP_ENV.lower() != "production")
    return {
        "ok": True,
        "password_login_available": True,
        "password_register_available": password_register_available,
        "email_otp_available": email_otp_available(),
        "bot_login": {
            "telegram_bot_login_available": bot_login_available("telegram"),
            "max_bot_login_available": bot_login_available("max"),
        },
    }


def set_bot_login_cookie(response: Response, provider: str, nonce: str) -> None:
    common = {
        "httponly": True,
        "secure": TRUSTED_COOKIE_SECURE,
        "samesite": TRUSTED_COOKIE_SAMESITE,
        "path": TRUSTED_COOKIE_PATH,
    }
    if TRUSTED_COOKIE_DOMAIN:
        common["domain"] = TRUSTED_COOKIE_DOMAIN
    response.set_cookie(
        BOT_LOGIN_CHALLENGE_COOKIE_NAME,
        f"{provider}:{nonce}",
        max_age=BOT_LOGIN_CHALLENGE_TTL_SECONDS,
        **common,
    )


def clear_bot_login_cookie(response: Response) -> None:
    kwargs: dict[str, Any] = {"path": TRUSTED_COOKIE_PATH}
    if TRUSTED_COOKIE_DOMAIN:
        kwargs["domain"] = TRUSTED_COOKIE_DOMAIN
    response.delete_cookie(BOT_LOGIN_CHALLENGE_COOKIE_NAME, **kwargs)


def parse_bot_login_cookie(request: Request) -> tuple[str, str] | None:
    raw = request.cookies.get(BOT_LOGIN_CHALLENGE_COOKIE_NAME) or ""
    if ":" not in raw:
        return None
    provider, nonce = raw.split(":", 1)
    if provider not in {"telegram", "max"} or not nonce:
        return None
    return provider, nonce


def bot_login_payload_from_text(text: str | None) -> str | None:
    if not isinstance(text, str):
        return None
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return None
    payload = parts[1].strip() if parts[0].lower() == "/start" and len(parts) > 1 else parts[0].strip()
    return payload if payload.startswith("login_") else None


def bot_login_token_from_payload(payload: str | None) -> str | None:
    if not payload or not payload.startswith("login_"):
        return None
    token = payload.replace("login_", "", 1).strip()
    return token if token else None


def telegram_user_from_update(update: dict[str, Any]) -> dict[str, Any] | None:
    callback = update.get("callback_query") or {}
    if isinstance(callback, dict) and isinstance(callback.get("from"), dict):
        return callback["from"]
    message = update.get("message") or {}
    if isinstance(message, dict) and isinstance(message.get("from"), dict):
        return message["from"]
    return None


def max_user_from_message(message: dict[str, Any]) -> dict[str, Any] | None:
    sender = message.get("sender") or message.get("user") or {}
    if isinstance(sender, dict):
        provider_id = sender.get("user_id") or sender.get("id")
        if provider_id:
            user = dict(sender)
            user["id"] = provider_id
            return user
    user_id = message.get("user_id")
    if user_id:
        return {"id": user_id}
    return None


def max_login_payload_from_update(update: dict[str, Any], text: str | None) -> str | None:
    for key in ("payload", "start_payload", "startPayload"):
        value = update.get(key)
        if isinstance(value, str) and value.startswith("login_"):
            return value
    bot_started = update.get("bot_started") or update.get("botStarted") or {}
    if isinstance(bot_started, dict):
        for key in ("payload", "start_payload", "startPayload"):
            value = bot_started.get(key)
            if isinstance(value, str) and value.startswith("login_"):
                return value
    return bot_login_payload_from_text(text)


def approve_bot_login_challenge(
    provider: Literal["telegram", "max"],
    token: str,
    provider_user: dict[str, Any],
) -> bool:
    provider_user_id = str(provider_user.get("id") or "")
    if not provider_user_id:
        return False
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM auth_login_challenges WHERE provider = ? AND token_hash = ?",
            (provider, hash_token(token)),
        ).fetchone()
        if not row or row["status"] != "pending" or row["expires_at"] <= now:
            return False
        if provider == "telegram":
            internal_user_id, _legacy_user_id = telegram_upsert_identity(conn, provider_user, now)
        else:
            internal_user_id, _legacy_user_id = max_upsert_identity(conn, provider_user, now)
        conn.execute(
            """
            UPDATE auth_login_challenges
            SET status = 'approved', internal_user_id = ?, provider_user_id = ?,
                provider_username = ?, approved_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (internal_user_id, provider_user_id, provider_user.get("username"), now, row["id"]),
        )
        record_login_attempt(conn, provider, True, identifier=provider_user_id, internal_user_id=internal_user_id, platform=f"{provider}_bot")
    return True


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str | None) -> str | None:
    """Trim + lowercase; return None for empty or clearly invalid format."""
    if not email:
        return None
    normalized = email.strip().lower()
    if not normalized or len(normalized) > 254 or not _EMAIL_RE.match(normalized):
        return None
    return normalized


def generate_otp_code(length: int = EMAIL_OTP_LENGTH) -> str:
    """Numeric OTP using cryptographically secure randomness (leading zeros kept)."""
    return "".join(secrets.choice("0123456789") for _ in range(max(1, length)))


def hash_otp(code: str) -> str:
    """Hash an OTP for storage. HMAC-keyed when a secret is set, else SHA-256.
    Domain-separated from session tokens. Raw OTP is never stored or logged."""
    if SESSION_HMAC_SECRET:
        return hmac.new(SESSION_HMAC_SECRET.encode(), f"otp:{code}".encode(), hashlib.sha256).hexdigest()
    return hashlib.sha256(f"otp:{code}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Password hashing (Phase 14.4). Argon2id only. Raw passwords and password
# hashes are NEVER logged. No endpoints in this phase — helpers + schema only.
# ---------------------------------------------------------------------------
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
PASSWORD_ALGORITHM = "argon2id"
# argon2-cffi defaults to Argon2id; explicit, modern parameters.
_password_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
# Fixed Argon2id hash used to equalize verify timing when an account is not found,
# so password login cannot be used to enumerate which emails exist.
_DUMMY_PASSWORD_HASH = _password_hasher.hash("argon2-timing-equalizer-not-a-real-password")


def validate_password_policy(password: str) -> list[str]:
    """Return machine-readable error codes (empty list = OK). No complexity rules yet."""
    errors: list[str] = []
    length = len(password or "")
    if length < PASSWORD_MIN_LENGTH:
        errors.append("password_too_short")
    if length > PASSWORD_MAX_LENGTH:
        errors.append("password_too_long")
    return errors


def hash_password_argon2(password: str) -> str:
    """Hash a password with Argon2id. Rejects empty/too-short/too-long before hashing.
    Never logs the password or the resulting hash."""
    if not password:
        raise ValueError("password_required")
    policy_errors = validate_password_policy(password)
    if policy_errors:
        raise ValueError(policy_errors[0])
    return _password_hasher.hash(password)


def verify_password_argon2(password: str, password_hash: str) -> bool:
    """Constant-time verify via argon2. Returns False on mismatch or any invalid/
    malformed hash — never raises to the caller, never logs password/hash."""
    if not password or not password_hash:
        return False
    try:
        return _password_hasher.verify(password_hash, password)
    except Argon2Error:
        return False
    except Exception:
        # Defensive: malformed hash string, type errors, etc.
        return False


def password_hash_needs_rehash(password_hash: str) -> bool:
    """True if the stored hash should be re-hashed with current parameters."""
    if not password_hash:
        return False
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


def email_provider_configured() -> bool:
    return bool(EMAIL_PROVIDER)


def email_otp_available() -> bool:
    """True when an email OTP can actually be delivered: a real provider in
    production, or the dev/test debug path that returns the code in the response.
    Gates the post-registration email-verification flow and the bootstrap
    'email_otp' method so we never demand a code we cannot send."""
    if email_provider_configured():
        return True
    return EMAIL_OTP_DEBUG_RETURN_CODE and APP_ENV.lower() != "production"


def validate_email_otp_config() -> None:
    """Refuse unsafe email-OTP configuration in production.

    - EMAIL_OTP_DEBUG_RETURN_CODE must never be on in production.
    - A real email provider must be configured in production (no fake sending).
    Dev/test may run with neither (mock sender, optional debug code).
    """
    if APP_ENV.lower() == "production":
        if EMAIL_OTP_DEBUG_RETURN_CODE:
            raise RuntimeError("EMAIL_OTP_DEBUG_RETURN_CODE must be disabled in production.")
        if not email_provider_configured():
            raise RuntimeError("No email provider configured for production email OTP.")


def send_email_otp(destination: str, code: str) -> None:
    """Deliver an OTP. In production a real provider would be called here. In
    dev/test we use a mock outbox that stores ONLY the destination + timestamp —
    never the code. Raw OTP is never logged."""
    if APP_ENV.lower() == "production" and email_provider_configured():
        # Real provider integration belongs here; not implemented in this phase.
        raise RuntimeError("Email provider integration not implemented.")
    _mock_email_outbox.append({"to": destination, "sent_at": datetime.now(timezone.utc).isoformat()})


def cleanup_expired_otp_challenges(now: str | None = None) -> int:
    """Idempotently delete stale OTP challenges (consumed or expired) that are
    older than EMAIL_OTP_CLEANUP_EXPIRED_AFTER_SECONDS. Active, unexpired
    challenges are never touched. Failure evidence lives in security_events /
    auth_login_attempts, so deleting old challenges loses no audit trail."""
    now_dt = datetime.now(timezone.utc)
    now_iso = now or now_dt.isoformat()
    cutoff = (now_dt - timedelta(seconds=EMAIL_OTP_CLEANUP_EXPIRED_AFTER_SECONDS)).isoformat()
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM auth_otp_challenges WHERE created_at < ? AND (consumed_at IS NOT NULL OR expires_at < ?)",
            (cutoff, now_iso),
        )
        return cur.rowcount


def _email_hash(email_norm: str) -> str:
    return hashlib.sha256(email_norm.encode()).hexdigest()


def _otp_rate_limited(
    reason: str,
    window_seconds: int,
    email_norm: str,
    request: Request,
    anonymous_id: str | None,
    installation_id: str | None,
    platform: str | None,
):
    """Record a rate-limit hit and raise a generic 429 (no email-existence
    disclosure, no OTP). Stores only the email HASH, not the raw address."""
    with db() as conn:
        record_security_event(
            conn,
            "otp_request_rate_limited",
            internal_user_id=None,
            request=request,
            details={"reason": reason, "email_hash": _email_hash(email_norm), "window_seconds": window_seconds},
        )
    try:
        record_event_log(
            "login_rate_limited",
            anonymous_id=anonymous_id,
            installation_id=installation_id,
            platform=platform,
            properties={"provider": "web_email", "reason": reason},
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"email-otp: login_rate_limited event log error: {type(exc).__name__}")
    raise HTTPException(429, "Too many requests")


def enforce_email_otp_rate_limits(
    email_norm: str,
    request: Request,
    anonymous_id: str | None,
    installation_id: str | None,
    platform: str | None,
) -> None:
    """Reject abusive request-code traffic. Chosen policy for the active-challenge
    cap: REJECT with 429 (we do not silently expire older challenges)."""
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    ip = _client_ip(request)
    cooldown_cut = (now_dt - timedelta(seconds=EMAIL_OTP_REQUEST_COOLDOWN_SECONDS)).isoformat()
    email_cut = (now_dt - timedelta(seconds=EMAIL_OTP_EMAIL_WINDOW_SECONDS)).isoformat()
    ip_cut = (now_dt - timedelta(seconds=EMAIL_OTP_IP_WINDOW_SECONDS)).isoformat()

    with db() as conn:
        cooldown_hits = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_otp_challenges WHERE destination = ? AND created_at > ?",
            (email_norm, cooldown_cut),
        ).fetchone()["c"]
        email_window_count = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_otp_challenges WHERE destination = ? AND created_at > ?",
            (email_norm, email_cut),
        ).fetchone()["c"]
        ip_window_count = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_otp_challenges WHERE ip_address = ? AND created_at > ?",
            (ip, ip_cut),
        ).fetchone()["c"] if ip else 0
        active_count = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_otp_challenges WHERE destination = ? AND consumed_at IS NULL AND expires_at > ?",
            (email_norm, now_iso),
        ).fetchone()["c"]

    if EMAIL_OTP_REQUEST_COOLDOWN_SECONDS > 0 and cooldown_hits > 0:
        _otp_rate_limited("cooldown", EMAIL_OTP_REQUEST_COOLDOWN_SECONDS, email_norm, request, anonymous_id, installation_id, platform)
    if email_window_count >= EMAIL_OTP_MAX_REQUESTS_PER_EMAIL_WINDOW:
        _otp_rate_limited("email_window", EMAIL_OTP_EMAIL_WINDOW_SECONDS, email_norm, request, anonymous_id, installation_id, platform)
    if ip and ip_window_count >= EMAIL_OTP_MAX_REQUESTS_PER_IP_WINDOW:
        _otp_rate_limited("ip_window", EMAIL_OTP_IP_WINDOW_SECONDS, email_norm, request, anonymous_id, installation_id, platform)
    if active_count >= EMAIL_OTP_MAX_ACTIVE_CHALLENGES_PER_EMAIL:
        _otp_rate_limited("max_active_challenges", EMAIL_OTP_EMAIL_WINDOW_SECONDS, email_norm, request, anonymous_id, installation_id, platform)


def email_otp_upsert_identity(conn: sqlite3.Connection, email_norm: str, now: str) -> tuple[str, str]:
    """Resolve/create the canonical identity for a verified email (provider='web_email').

    provider_user_id is the normalized email. We do NOT link by the legacy
    users.email column (it is client-supplied and unverified, so linking could
    hijack a Telegram/MAX account) — repeated logins reuse via the auth_identities
    lookup instead. Never changes an existing users.id; never auto-merges with
    Telegram/MAX identities.
    """
    existing = conn.execute(
        "SELECT id, internal_user_id, legacy_user_id FROM auth_identities WHERE provider = 'web_email' AND provider_user_id = ?",
        (email_norm,),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE auth_identities SET provider_email = ?, verified_at = ?, last_login_at = ? WHERE id = ?",
            (email_norm, now, now, existing["id"]),
        )
        if existing["legacy_user_id"]:
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, existing["legacy_user_id"]))
        return existing["internal_user_id"], existing["legacy_user_id"]

    legacy_user_id = f"web_{uuid.uuid4().hex}"
    internal_user_id = uuid.uuid4().hex
    user_columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    has_email_col = "email" in user_columns
    if has_email_col:
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (id, email, language, role, plan, gallery_enabled, created_at, last_login_at, internal_user_id)
            VALUES (?, ?, 'ru', 'user', 'mini', 1, ?, ?, ?)
            """,
            (legacy_user_id, email_norm, now, now, internal_user_id),
        )
    else:
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (id, language, role, created_at, last_login_at, internal_user_id)
            VALUES (?, 'ru', 'user', ?, ?, ?)
            """,
            (legacy_user_id, now, now, internal_user_id),
        )
    row = conn.execute("SELECT id, internal_user_id FROM users WHERE id = ?", (legacy_user_id,)).fetchone()
    if row and row["internal_user_id"]:
        internal_user_id = row["internal_user_id"]

    conn.execute(
        """
        INSERT OR IGNORE INTO auth_identities
            (id, internal_user_id, legacy_user_id, provider, provider_user_id, provider_email,
             raw_profile_json, verified_at, linked_at, last_login_at)
        VALUES (?, ?, ?, 'web_email', ?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, internal_user_id, legacy_user_id, email_norm, email_norm,
         json.dumps({"email": email_norm}, ensure_ascii=False), now, now, now),
    )
    return internal_user_id, legacy_user_id


def _user_is_banned(conn: sqlite3.Connection, internal_user_id: str | None, legacy_user_id: str | None) -> bool:
    row = None
    if internal_user_id:
        row = conn.execute("SELECT banned FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
    if row is None and legacy_user_id:
        row = conn.execute("SELECT banned FROM users WHERE id = ?", (legacy_user_id,)).fetchone()
    if row is None:
        return False
    try:
        return bool(row["banned"])
    except (KeyError, IndexError):
        return False


def normalize_tariffs(raw: Any | None = None, *, strict: bool = False) -> dict[str, dict[str, int]]:
    if strict and (not isinstance(raw, dict) or not raw):
        raise HTTPException(400, "Tariff config must not be empty.")
    data = raw if isinstance(raw, dict) else {}
    if strict:
        unknown = sorted(str(key) for key in data if str(key).lower() not in PLAN_ORDER)
        if unknown:
            raise HTTPException(400, f"Unknown tariff plan: {', '.join(unknown)}")
    result: dict[str, dict[str, int]] = {}
    for plan in PLAN_ORDER:
        source = data.get(plan) if isinstance(data.get(plan), dict) else {}
        daily = source.get("daily_tokens", source.get("dailyTokens", DEFAULT_TARIFFS[plan]["daily_tokens"]))
        slots = source.get("gallery_slots", source.get("gallerySlots", DEFAULT_TARIFFS[plan]["gallery_slots"]))
        try:
            daily_int = int(daily)
            slots_int = int(slots)
        except (TypeError, ValueError):
            if strict:
                raise HTTPException(400, f"Invalid tariff values for {plan}.")
            daily_int = DEFAULT_TARIFFS[plan]["daily_tokens"]
            slots_int = DEFAULT_TARIFFS[plan]["gallery_slots"]
        if strict and (daily_int < 0 or slots_int < 0):
            raise HTTPException(400, f"Tariff values for {plan} must be non-negative.")
        result[plan] = {
            "daily_tokens": max(0, min(daily_int, 100_000)),
            "gallery_slots": max(0, min(slots_int, 100_000)),
        }
    return result


def get_tariff_config(conn: sqlite3.Connection | None = None) -> dict[str, dict[str, int]]:
    try:
        if conn is not None:
            row = conn.execute("SELECT value_json FROM admin_settings WHERE key = 'tariffs'").fetchone()
            return normalize_tariffs(json.loads(row["value_json"] or "{}") if row else None)
        with db() as local_conn:
            row = local_conn.execute("SELECT value_json FROM admin_settings WHERE key = 'tariffs'").fetchone()
            return normalize_tariffs(json.loads(row["value_json"] or "{}") if row else None)
    except Exception:
        return normalize_tariffs()


def gallery_quota_for_user(conn: sqlite3.Connection, user_row: sqlite3.Row | None, legacy_user_id: str | None = None) -> dict[str, Any]:
    plan = str(_row_get(user_row, "plan") or "mini").lower()
    if plan not in PLAN_ORDER:
        plan = "mini"
    tariff = get_tariff_config(conn)[plan]
    user_id = legacy_user_id or _row_get(user_row, "id")
    used = 0
    if user_id:
        used = int(conn.execute(
            "SELECT COUNT(*) AS c FROM images WHERE user_id = ? AND (deleted_at IS NULL OR deleted_at = '')",
            (user_id,),
        ).fetchone()["c"])
    total = int(tariff["gallery_slots"])
    return {
        "plan": plan,
        "daily_tokens": int(tariff["daily_tokens"]),
        "gallery_slots": total,
        "gallery_used": used,
        "gallery_free": max(0, total - used),
        "gallery_full": used >= total,
    }


def user_gallery_allowed(conn: sqlite3.Connection, internal_user_id: str | None, legacy_user_id: str | None) -> bool:
    row = None
    if internal_user_id:
        row = conn.execute("SELECT role, plan, gallery_enabled FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
    if row is None and legacy_user_id:
        row = conn.execute("SELECT role, plan, gallery_enabled FROM users WHERE id = ?", (legacy_user_id,)).fetchone()
    if row is None:
        return False
    return True


def create_auth_session(
    internal_user_id: str,
    legacy_user_id: str | None = None,
    provider: str | None = None,
    platform: str | None = None,
    request: Request | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Create a session, persist only token hashes, return raw tokens to caller."""
    validate_session_crypto_config()
    raw_session_token = generate_secure_token()
    raw_refresh_token = generate_secure_token()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    # Access/session token lifetime drives auth_sessions.expires_at; the refresh
    # token gets its own, longer lifetime tracked in refresh_expires_at.
    expires_at = (now + timedelta(seconds=SESSION_ACCESS_TTL_SECONDS)).isoformat()
    refresh_expires_at = (now + timedelta(seconds=SESSION_REFRESH_TTL_SECONDS)).isoformat()
    session_id = uuid.uuid4().hex
    # Analytics-only device classification (no raw UA stored).
    session_meta = dict(metadata) if metadata else {}
    if request is not None:
        session_meta.setdefault("device", parse_user_agent(request.headers.get("user-agent")))
    with db() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions
                (id, internal_user_id, legacy_user_id, session_token_hash, refresh_token_hash,
                 provider, platform, ip_address, user_agent_hash, created_at, last_seen_at,
                 expires_at, refresh_expires_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                internal_user_id,
                legacy_user_id,
                hash_token(raw_session_token),
                hash_token(raw_refresh_token),
                provider,
                platform,
                get_client_ip(request),
                _hash_user_agent(request),
                now_iso,
                now_iso,
                expires_at,
                refresh_expires_at,
                json.dumps(session_meta, ensure_ascii=False) if session_meta else None,
            ),
        )
        record_session_event(conn, session_id, internal_user_id, "created", request)
        # Phase 18 analytics: stamp last activity + ensure a public code on every login.
        conn.execute("UPDATE users SET last_seen_at = ? WHERE internal_user_id = ?", (now_iso, internal_user_id))
        ensure_public_user_code(conn, internal_user_id)
    return {
        "session_id": session_id,
        "session_token": raw_session_token,
        "refresh_token": raw_refresh_token,
        "expires_at": expires_at,
        "refresh_expires_at": refresh_expires_at,
    }


def resolve_auth_session_from_request(
    request: Request, *, raise_on_failure: bool = True
) -> dict[str, Any] | None:
    """Resolve the trusted session for a request, or fail/None.

    Does NOT trust X-OneNode-User or the legacy onenode_user cookie.
    Writes security_events on any invalid/expired/revoked/banned outcome.
    """
    token = _extract_session_token(request)
    now_iso = datetime.now(timezone.utc).isoformat()

    def fail(event_type: str, status: int, message: str, *, severity: str = "warning",
             internal_user_id: str | None = None, session_id: str | None = None):
        # Recorded in its own committed transaction, then we raise — so the
        # security event survives even though the request fails.
        with db() as conn:
            record_security_event(conn, event_type, severity=severity, internal_user_id=internal_user_id, session_id=session_id, request=request)
        if raise_on_failure:
            raise HTTPException(status, message)
        return None

    if not token:
        return fail("session_missing_token", 401, "Missing session token.")
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM auth_sessions WHERE session_token_hash = ?", (hash_token(token),)
        ).fetchone()
    if row is None:
        return fail("session_invalid", 401, "Invalid session.")
    if row["revoked_at"] is not None:
        return fail("session_revoked", 401, "Session revoked.", internal_user_id=row["internal_user_id"], session_id=row["id"])
    if row["expires_at"] <= now_iso:
        return fail("session_expired", 401, "Session expired.", internal_user_id=row["internal_user_id"], session_id=row["id"])
    with db() as conn:
        banned = _user_is_banned(conn, row["internal_user_id"], row["legacy_user_id"])
    if banned:
        return fail("session_user_banned", 403, "User is banned.", severity="critical", internal_user_id=row["internal_user_id"], session_id=row["id"])
    with db() as conn:
        conn.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?", (now_iso, row["id"]))
    return {
        "session_id": row["id"],
        "internal_user_id": row["internal_user_id"],
        "legacy_user_id": row["legacy_user_id"],
        "provider": row["provider"],
        "platform": row["platform"],
        "created_at": row["created_at"],
        "last_seen_at": now_iso,
        "expires_at": row["expires_at"],
    }


def refresh_auth_session(refresh_token: str, request: Request | None = None) -> dict[str, str]:
    """Validate a refresh token, rotate it, and issue a fresh session.

    Refresh validity is governed by refresh_expires_at (its own lifetime), NOT by
    the access token's expires_at — so a refresh still works after the access
    token has lapsed. Legacy rows predating refresh_expires_at (NULL) are treated
    conservatively: rejected in production; in dev/test they fall back to
    expires_at so older fixtures/sessions keep working.
    """
    validate_session_crypto_config()
    now_iso = datetime.now(timezone.utc).isoformat()

    def fail(event_type: str, status: int, message: str, *, severity: str = "warning",
             internal_user_id: str | None = None, session_id: str | None = None):
        with db() as conn:
            record_security_event(conn, event_type, severity=severity, internal_user_id=internal_user_id, session_id=session_id, request=request)
        raise HTTPException(status, message)

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM auth_sessions WHERE refresh_token_hash = ?", (hash_token(refresh_token),)
        ).fetchone()
    if row is None:
        fail("refresh_invalid", 401, "Invalid refresh token.")
    if row["revoked_at"] is not None:
        fail("refresh_revoked", 401, "Refresh token revoked.", internal_user_id=row["internal_user_id"], session_id=row["id"])
    refresh_expires_at = row["refresh_expires_at"] if "refresh_expires_at" in row.keys() else None
    if refresh_expires_at is None:
        if APP_ENV.lower() == "production":
            fail("refresh_expired", 401, "Refresh token expired.", internal_user_id=row["internal_user_id"], session_id=row["id"])
        refresh_expires_at = row["expires_at"]  # dev/test fallback for legacy rows
    if refresh_expires_at is None or refresh_expires_at <= now_iso:
        fail("refresh_expired", 401, "Refresh token expired.", internal_user_id=row["internal_user_id"], session_id=row["id"])
    with db() as conn:
        banned = _user_is_banned(conn, row["internal_user_id"], row["legacy_user_id"])
    if banned:
        fail("refresh_user_banned", 403, "User is banned.", severity="critical", internal_user_id=row["internal_user_id"], session_id=row["id"])
    # Rotation: revoke the old session so the old refresh token cannot be reused.
    with db() as conn:
        conn.execute(
            "UPDATE auth_sessions SET revoked_at = ?, revoke_reason = 'rotated' WHERE id = ?",
            (now_iso, row["id"]),
        )
        record_session_event(conn, row["id"], row["internal_user_id"], "refreshed", request)
    return create_auth_session(
        row["internal_user_id"], row["legacy_user_id"], row["provider"], row["platform"], request
    )


def revoke_auth_session(
    session_id: str,
    reason: str = "logout",
    request: Request | None = None,
    event_type: str | None = None,
) -> bool:
    now_iso = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute(
            "SELECT internal_user_id, revoked_at FROM auth_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return False
        if row["revoked_at"] is None:
            conn.execute(
                "UPDATE auth_sessions SET revoked_at = ?, revoke_reason = ? WHERE id = ?",
                (now_iso, reason, session_id),
            )
        record_session_event(
            conn,
            session_id,
            row["internal_user_id"],
            event_type or ("logout" if reason == "logout" else "revoked"),
            request,
        )
    return True


def set_trusted_auth_cookies(
    response: Response,
    session_token: str,
    refresh_token: str,
    expires_at: str | None = None,
    refresh_expires_at: str | None = None,
) -> None:
    """Set HttpOnly session + refresh cookies carrying the raw tokens.

    The DB still stores only hashes; the cookie is just secure transport. Raw
    cookie values are never logged. secure/samesite/domain/path come from config.
    """
    common = {
        "httponly": True,  # always
        "secure": TRUSTED_COOKIE_SECURE,
        "samesite": TRUSTED_COOKIE_SAMESITE,
        "path": TRUSTED_COOKIE_PATH,
    }
    if TRUSTED_COOKIE_DOMAIN:
        common["domain"] = TRUSTED_COOKIE_DOMAIN
    response.set_cookie(
        TRUSTED_SESSION_COOKIE_NAME, session_token, max_age=SESSION_ACCESS_TTL_SECONDS, **common
    )
    response.set_cookie(
        TRUSTED_REFRESH_COOKIE_NAME, refresh_token, max_age=SESSION_REFRESH_TTL_SECONDS, **common
    )


def clear_trusted_auth_cookies(response: Response) -> None:
    """Clear both trusted cookies (used on logout). Matches name/path/domain."""
    kwargs: dict[str, Any] = {"path": TRUSTED_COOKIE_PATH}
    if TRUSTED_COOKIE_DOMAIN:
        kwargs["domain"] = TRUSTED_COOKIE_DOMAIN
    response.delete_cookie(TRUSTED_SESSION_COOKIE_NAME, **kwargs)
    response.delete_cookie(TRUSTED_REFRESH_COOKIE_NAME, **kwargs)


def _extract_refresh_token(request: Request) -> str | None:
    return request.cookies.get(TRUSTED_REFRESH_COOKIE_NAME)


# ---------------------------------------------------------------------------
# Trusted user resolution (Phase 9) — the new v2 authorization layer.
# Used ONLY by new v2 endpoints; legacy request_user_id()/require_admin() stay.
# ---------------------------------------------------------------------------


def resolve_trusted_user(request: Request) -> dict[str, Any]:
    """Resolve the current user strictly from a trusted server session.

    Never trusts X-OneNode-User, the onenode_user cookie, or any client-supplied
    user id. 401 for invalid/expired/revoked session, 403 for banned/deleted user.
    A mismatching X-OneNode-User header is logged as a spoof attempt but never
    changes the resolved identity and never fails a request with a valid session.
    """
    session = resolve_auth_session_from_request(request)  # raises 401/403
    internal_user_id = session["internal_user_id"]
    legacy_user_id = session["legacy_user_id"]

    with db() as conn:
        urow = conn.execute("SELECT id FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
        if urow is None and legacy_user_id:
            urow = conn.execute("SELECT id FROM users WHERE id = ?", (legacy_user_id,)).fetchone()
    if urow is None:
        with db() as conn:
            record_security_event(conn, "trusted_user_missing", severity="critical", internal_user_id=internal_user_id, session_id=session["session_id"], request=request)
        raise HTTPException(403, "User not found.")

    header_user = request.headers.get("x-onenode-user")
    if header_user and header_user != legacy_user_id and header_user != "demo_user":
        with db() as conn:
            record_security_event(
                conn,
                "legacy_identity_spoof_attempt",
                internal_user_id=internal_user_id,
                session_id=session["session_id"],
                request=request,
                details={
                    "trusted_legacy_user_id": legacy_user_id,
                    "spoofed_header_hash": hashlib.sha256(header_user.encode()).hexdigest(),
                },
            )

    return {
        "internal_user_id": internal_user_id,
        "legacy_user_id": legacy_user_id,
        "session_id": session["session_id"],
        "provider": session["provider"],
        "platform": session["platform"],
    }


def require_trusted_user(request: Request) -> dict[str, Any]:
    """Thin wrapper over resolve_trusted_user for new v2 endpoints."""
    return resolve_trusted_user(request)


def require_trusted_admin(request: Request) -> dict[str, Any]:
    """Trusted admin gate. Uses the existing users.role model via the trusted
    session only — never X-OneNode-User and never the static admin code."""
    user = require_trusted_user(request)
    with db() as conn:
        row = conn.execute("SELECT role FROM users WHERE internal_user_id = ?", (user["internal_user_id"],)).fetchone()
        if row is None and user["legacy_user_id"]:
            row = conn.execute("SELECT role FROM users WHERE id = ?", (user["legacy_user_id"],)).fetchone()
    if not row or row["role"] != "admin":
        with db() as conn:
            record_security_event(conn, "trusted_admin_denied", internal_user_id=user["internal_user_id"], session_id=user["session_id"], request=request)
        raise HTTPException(403, "Admin access required")
    return user


def _row_get(row: sqlite3.Row | None, key: str) -> Any:
    if row is None:
        return None
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Account layer (Phase 11) — profile / devices / consents over trusted session.
# ---------------------------------------------------------------------------

# API field -> users column. Fields absent here (role, banned, internal_user_id,
# id) can never be read/written through the profile endpoints.
PROFILE_FIELD_COLUMNS = {
    "display_name": "display_name",
    "first_name": "first_name",
    "last_name": "last_name",
    "middle_name": "middle_name",
    "username": "username",
    "language_code": "language",
    "timezone": "timezone",
    "city": "city",
    "country_code": "country",
    "avatar_url": "avatar_url",
    "avatar_preset": "avatar_preset",
}

CONSENT_TYPES = {
    "terms", "privacy", "personal_data_processing", "cookies", "analytics",
    "marketing", "public_gallery", "ai_generation_rules", "age_confirmation",
}

PROFILE_FIELD_MAX_LEN = 200


def build_profile(row: sqlite3.Row | None) -> dict[str, Any]:
    """Safe profile projection — only whitelisted columns, null where missing."""
    return {api_field: _row_get(row, col) for api_field, col in PROFILE_FIELD_COLUMNS.items()}


AVATAR_PRESET_IDS = {f"preset-{i}" for i in range(1, 11)}
AVATAR_MAX_BYTES = 2 * 1024 * 1024
AVATAR_ALLOWED_CONTENT_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def validate_avatar_choice(avatar_url: str | None, avatar_preset: str | None) -> tuple[str | None, str | None]:
    preset = (avatar_preset or "").strip()
    url = (avatar_url or "").strip()
    if preset:
        if preset not in AVATAR_PRESET_IDS:
            raise HTTPException(400, "Unknown avatar preset.")
        expected = f"/avatars/{preset}.svg"
        return expected, preset
    if url and not url.startswith("/media/avatars/"):
        raise HTTPException(400, "Avatar URL is not allowed.")
    return url or None, None


def sanitize_device_metadata(metadata_json: str | None) -> dict[str, Any]:
    """Expose only language/timezone/app_version from the stored client summary."""
    data = safe_json_load(metadata_json) or {}
    client = data.get("client") if isinstance(data, dict) else {}
    client = client if isinstance(client, dict) else {}
    return {
        "language": client.get("language"),
        "timezone": client.get("timezone"),
        "app_version": client.get("app_version"),
    }


# ---------------------------------------------------------------------------
# Admin v2 helpers (Phase 10) — read/format and audit. Trusted-session only.
# ---------------------------------------------------------------------------


def mask_email(email: str | None) -> str | None:
    """Mask an email for admin views: a***z@domain. Never returns the raw local part."""
    if not email:
        return None
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked = (local[0] if local else "*") + "*"
    else:
        masked = local[0] + ("*" * (len(local) - 2)) + local[-1]
    return f"{masked}@{domain}"


def mask_phone(phone: str | None) -> str | None:
    """Mask a phone for admin views: keep last 2 digits, e.g. +*******89."""
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) <= 2:
        return "***"
    prefix = "+" if phone.strip().startswith("+") else ""
    return f"{prefix}{'*' * (len(digits) - 2)}{digits[-2:]}"


def safe_json_load(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def short_public_id(value: Any, n: int = 10) -> str | None:
    if value is None:
        return None
    s = str(value)
    if not s:
        return None
    return s[:n] + ("…" if len(s) > n else "")


def truncate_admin_text(value: Any, limit: int = 180) -> str:
    if value is None:
        return ""
    s = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    return s[:limit] + ("…" if len(s) > limit else "")


def safe_app_url(value: Any) -> str | None:
    if not value:
        return None
    s = str(value)
    if s.startswith("/api/media/") or s.startswith("/media/"):
        return s
    return None


def safe_error_message(value: Any, limit: int = 180) -> str | None:
    if not value:
        return None
    s = truncate_admin_text(value, limit)
    for marker in (str(ROOT), str(MEDIA), "\\", "sqlite:///", "Traceback"):
        if marker and marker in s:
            return "Ошибка генерации. Детали скрыты."
    return s


def safe_ledger_metadata(meta_json: str | None) -> dict[str, Any]:
    data = safe_json_load(meta_json) or {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for src, dst in (("jobId", "job_id"), ("mode", "mode"), ("provider", "provider"), ("reason", "reason")):
        if data.get(src):
            out[dst] = truncate_admin_text(data.get(src), 80)
    if data.get("actor_internal_user_id"):
        out["actor"] = short_public_id(data.get("actor_internal_user_id"), 8)
    return out


def safe_device_from_metadata(metadata_json: str | None) -> dict[str, Any]:
    data = safe_json_load(metadata_json) or {}
    device = data.get("device") if isinstance(data, dict) else {}
    device = device if isinstance(device, dict) else {}
    client = data.get("client") if isinstance(data, dict) else {}
    client = client if isinstance(client, dict) else {}
    return {
        "browser": device.get("browser"),
        "os": device.get("os"),
        "device_type": device.get("device_type"),
        "app_build": client.get("app_version") or data.get("app_version"),
        "mac_status": "MAC: недоступен",
    }


def admin_user_summary(row: sqlite3.Row | None) -> dict[str, Any]:
    banned = bool(_row_get(row, "banned"))
    return {
        "internal_user_id": _row_get(row, "internal_user_id"),
        "legacy_user_id": _row_get(row, "id"),
        "status": "banned" if banned else "active",
        "role": _row_get(row, "role"),
        "created_at": _row_get(row, "created_at"),
        "last_seen_at": _row_get(row, "last_seen_at"),
        "avatar_url": _row_get(row, "avatar_url"),
        "avatar_preset": _row_get(row, "avatar_preset"),
    }


def record_audit_log(
    conn: sqlite3.Connection,
    action: str,
    actor_internal_user_id: str | None = None,
    target_internal_user_id: str | None = None,
    entity_type: str = "user",
    entity_id: str | None = None,
    before: Any = None,
    after: Any = None,
    request: Request | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_logs
            (id, actor_internal_user_id, target_internal_user_id, action, entity_type, entity_id,
             before_json, after_json, ip_address, user_agent_hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            actor_internal_user_id,
            target_internal_user_id,
            action,
            entity_type,
            entity_id,
            json.dumps(before, ensure_ascii=False) if before is not None else None,
            json.dumps(after, ensure_ascii=False) if after is not None else None,
            _client_ip(request),
            _hash_user_agent(request),
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def _clamp_limit(limit: int, default: int = 50, maximum: int = 200) -> int:
    if limit is None:
        return default
    return max(1, min(int(limit), maximum))


def row_to_image(row: sqlite3.Row) -> dict[str, Any]:
    settings = json.loads(row["settings_json"] or "{}")
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "url": row["url"],
        "thumbnailUrl": row["thumbnail_url"],
        "mode": row["mode"],
        "provider": row["provider"],
        "promptOriginal": row["prompt_original"] or "",
        "promptTranslated": row["prompt_translated"] or "",
        "seed": settings.get("seed", 0),
        "width": row["width"],
        "height": row["height"],
        "modelProfile": settings.get("modelProfile", ""),
        "loras": settings.get("loras", []),
        "preset": settings.get("preset"),
        "generationTimeMs": settings.get("generationTimeMs", 0),
        "isFavorite": bool(row["is_favorite"]),
        "createdAt": row["created_at"],
        "comfyuiPromptId": settings.get("comfyuiPromptId"),
        "comfyuiHistory": settings.get("comfyuiHistory"),
        "deletedAt": _row_get(row, "deleted_at"),
    }


def load_db_state() -> None:
    jobs.clear()
    images.clear()
    with db() as conn:
        for row in conn.execute("SELECT * FROM images WHERE deleted_at IS NULL ORDER BY created_at DESC"):
            images[row["id"]] = row_to_image(row)
        for row in conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100"):
            jobs[row["id"]] = {
                "id": row["id"],
                "userId": row["user_id"],
                "mode": row["mode"],
                "provider": row["provider"],
                "status": row["status"],
                "progress": row["progress"],
                "message": row["error_message"] or row["status"],
                "resultImageId": row["result_image_id"],
                "createdAt": row["created_at"],
                "completedAt": row["completed_at"],
            }


def persist_job(job: dict[str, Any], request: GenerateRequest | None = None) -> None:
    settings = request.model_dump() if request else job.get("request", {})
    with db() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, user_id, mode, provider, status, progress, prompt_original, prompt_translated,
                              result_image_id, error_message, settings_json, created_at, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                progress=excluded.progress,
                result_image_id=excluded.result_image_id,
                error_message=excluded.error_message,
                settings_json=excluded.settings_json,
                completed_at=excluded.completed_at
            """,
            (
                job["id"],
                job.get("userId", "demo_user"),
                job.get("mode", request.mode if request else ""),
                job.get("provider", request.provider if request else ""),
                job.get("status", "queued"),
                int(job.get("progress", 0)),
                (request.prompt if request else settings.get("prompt", "")) or "",
                "",
                job.get("resultImageId"),
                job.get("error"),
                json.dumps(settings, ensure_ascii=False),
                job.get("createdAt") or datetime.now(timezone.utc).isoformat(),
                job.get("startedAt"),
                job.get("completedAt"),
            ),
        )


def persist_image(record: dict[str, Any], job_id: str) -> None:
    settings = {
        "seed": record.get("seed"),
        "modelProfile": record.get("modelProfile"),
        "loras": record.get("loras", []),
        "preset": record.get("preset"),
        "generationTimeMs": record.get("generationTimeMs"),
        "comfyuiPromptId": record.get("comfyuiPromptId"),
        "comfyuiHistory": record.get("comfyuiHistory"),
    }
    with db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider,
                                           prompt_original, prompt_translated, settings_json, is_favorite, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record.get("userId", "demo_user"),
                job_id,
                record["url"],
                record["thumbnailUrl"],
                record["width"],
                record["height"],
                record["mode"],
                record["provider"],
                record["promptOriginal"],
                record.get("promptTranslated", ""),
                json.dumps(settings, ensure_ascii=False),
                1 if record.get("isFavorite") else 0,
                record["createdAt"],
            ),
        )


def local_media_path_from_url(url: str) -> Path | None:
    if url.startswith("/api/media/"):
        filename = url.removeprefix("/api/media/").split("?", 1)[0]
    elif url.startswith("/media/"):
        filename = url.removeprefix("/media/").split("?", 1)[0]
    else:
        return None
    path = (MEDIA / filename).resolve()
    try:
        path.relative_to(MEDIA.resolve())
    except ValueError:
        raise RuntimeError("Недопустимый путь media-файла.")
    return path if path.exists() else None


def upsert_user(auth: MiniAppAuthRequest) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    raw_id = auth.userId or ""
    # Strip ALL existing platform prefixes to avoid double-/triple-/quadruple-prefixing
    while raw_id:
        stripped = raw_id
        for prefix in ("web_", "telegram_", "max_"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):]
                break
        if stripped == raw_id:
            break
        raw_id = stripped
    user_id = f"{auth.platform}_{raw_id}" if raw_id else "demo_user"
    with db() as conn:
        conn.execute(
            """
            INSERT INTO users (id, telegram_id, max_id, username, first_name, last_name, middle_name, phone, email, language, role, plan, gallery_enabled, created_at, last_login_at,
                               country, city, timezone, ref_code, last_user_agent, last_screen, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'user', 'mini', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                username=COALESCE(excluded.username, users.username),
                first_name=COALESCE(excluded.first_name, users.first_name),
                last_name=COALESCE(excluded.last_name, users.last_name),
                middle_name=COALESCE(excluded.middle_name, users.middle_name),
                phone=COALESCE(excluded.phone, users.phone),
                email=COALESCE(excluded.email, users.email),
                language=excluded.language,
                country=COALESCE(excluded.country, users.country),
                city=COALESCE(excluded.city, users.city),
                timezone=COALESCE(excluded.timezone, users.timezone),
                ref_code=COALESCE(users.ref_code, excluded.ref_code),
                last_user_agent=COALESCE(excluded.last_user_agent, users.last_user_agent),
                last_screen=COALESCE(excluded.last_screen, users.last_screen),
                last_seen_at=excluded.last_seen_at,
                last_login_at=excluded.last_login_at
            """,
            (
                user_id,
                auth.userId if auth.platform == "telegram" else None,
                auth.userId if auth.platform == "max" else None,
                auth.username,
                auth.firstName,
                auth.lastName,
                auth.middleName,
                auth.phone,
                auth.email,
                auth.language,
                now,
                now,
                auth.country,
                auth.city,
                auth.timezone,
                auth.ref,
                auth.userAgent,
                auth.screen,
                now,
            ),
        )
        row = conn.execute(
            "SELECT username, first_name, last_name, middle_name, phone, email, language, role, plan, token_balance, gallery_enabled, country, city, timezone, total_time_seconds, generation_count, tokens_used, promo_used_count, referrals_count, banned FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        quota = gallery_quota_for_user(conn, row, user_id)
    return {
        "id": user_id,
        "platform": auth.platform,
        "username": row["username"] if row else auth.username,
        "firstName": row["first_name"] if row else auth.firstName,
        "lastName": row["last_name"] if row else auth.lastName,
        "middleName": row["middle_name"] if row else auth.middleName,
        "phone": row["phone"] if row else auth.phone,
        "email": row["email"] if row else auth.email,
        "language": (row["language"] if row else auth.language) or auth.language,
        "role": (row["role"] if row else None) or "user",
        "plan": (row["plan"] if row else None) or "mini",
        "tokenBalance": int(row["token_balance"] if row else 50),
        "galleryEnabled": bool(row["gallery_enabled"] if row else True),
        "galleryAccess": True,
        "dailyTokens": quota["daily_tokens"],
        "gallerySlots": quota["gallery_slots"],
        "galleryUsed": quota["gallery_used"],
        "galleryFree": quota["gallery_free"],
        "galleryFull": quota["gallery_full"],
        "country": row["country"] if row else auth.country,
        "city": row["city"] if row else auth.city,
        "timezone": row["timezone"] if row else auth.timezone,
        "totalTimeSeconds": int(row["total_time_seconds"] if row else 0),
        "generationCount": int(row["generation_count"] if row else 0),
        "tokensUsed": int(row["tokens_used"] if row else 0),
        "promoUsedCount": int(row["promo_used_count"] if row else 0),
        "referralsCount": int(row["referrals_count"] if row else 0),
        "banned": bool(row["banned"] if row else False),
    }


def estimate_token_cost(req: GenerateRequest) -> int:
    if req.provider == "openrouter":
        return max(2, 2 * (1 if req.steps <= 4 else 2 if req.steps <= 5 else 4))
    if "9b" in (req.modelProfile or "").lower():
        if req.steps <= 4:
            return 1
        if req.steps == 5:
            return 2
        if req.steps == 6:
            return 4
        return 6
    if req.steps <= 4:
        return 1
    if req.steps == 5:
        return 2
    return 3


def mini_app_url(platform: str = "web") -> str:
    base = os.getenv("APP_PUBLIC_URL", "http://127.0.0.1:5173")
    return f"{base}?platform={platform}"


def bot_command_response(platform: Literal["telegram", "max"], command: str) -> dict[str, Any]:
    app_url = mini_app_url(platform)
    normalized = command.split()[0].lower() if command else "/start"
    login_payload = bot_login_payload_from_text(command)
    if login_payload:
        text = "Подтвердите вход в OneNode Image Studio. Если это были не вы, просто закройте сообщение."
        buttons = [{"text": "Подтвердить вход", "callback_data": f"approve:{login_payload}"}]
    elif normalized == "/start":
        text = "Добро пожаловать в OneNode Image Studio. Здесь можно открыть генератор, галерею и настройки."
        buttons = [{"text": "Открыть приложение", "url": app_url}]
    elif normalized == "/app":
        text = "Открыть генератор OneNode Image Studio"
        buttons = [{"text": "Открыть генератор", "url": app_url}]
    elif normalized == "/help":
        text = "Выберите режим, загрузите изображение или напишите prompt, затем нажмите «Сгенерировать»."
        buttons = [{"text": "Открыть генератор", "url": app_url}]
    elif normalized == "/gallery":
        latest = list(images.values())[:5]
        text = "Последние изображения: " + (", ".join(item["id"] for item in latest) if latest else "пока пусто")
        buttons = [{"text": "Открыть галерею", "url": f"{app_url}#gallery"}]
    elif normalized == "/settings":
        text = "Настройки приложения"
        buttons = [{"text": "Открыть настройки", "url": f"{app_url}#settings"}]
    else:
        text = "Команда не распознана. Используйте /app, /help, /gallery или /settings."
        buttons = [{"text": "Открыть генератор", "url": app_url}]
    return {"ok": True, "platform": platform, "command": normalized, "text": text, "buttons": buttons}


def bot_status_payload() -> dict[str, Any]:
    backend_public = os.getenv("BACKEND_PUBLIC_URL", "http://127.0.0.1:8000")
    app_public = os.getenv("APP_PUBLIC_URL", "http://127.0.0.1:5173")
    return {
        "mode": BOT_MODE,
        "domainRequired": BOT_MODE == "webhook",
        "tokens": {
            "telegram": bool(TELEGRAM_BOT_TOKEN),
            "max": bool(MAX_BOT_TOKEN),
        },
        "publicUrls": {
            "backend": backend_public,
            "app": app_public,
            "telegramWebhook": f"{backend_public}/api/telegram/webhook",
            "maxWebhook": f"{backend_public}/api/max/webhook",
        },
        "manualWebhookDisable": {
            "telegram": "POST /api/telegram/delete-webhook, only as an explicit admin/operator action.",
            "max": "Disable the MAX subscription in the MAX bot console/API before enabling polling.",
            "autoDisable": False,
        },
        "telegram": {
            "local": True,
            "pollingReady": bool(TELEGRAM_BOT_TOKEN),
            "webhookReady": bool(TELEGRAM_BOT_TOKEN and backend_public.startswith("https://")),
            "commands": ["/start", "/app", "/help", "/gallery", "/settings"],
        },
        "max": {
            "local": True,
            "pollingReady": bool(MAX_BOT_TOKEN and MAX_API_BASE_URL),
            "webhookReady": bool(MAX_BOT_TOKEN and MAX_API_BASE_URL and backend_public.startswith("https://")),
            "commands": ["/start", "/app", "/help", "/gallery", "/settings"],
        },
    }


async def telegram_api(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(400, "TELEGRAM_BOT_TOKEN is required for real Telegram API calls.")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}", json=payload or {})
        response.raise_for_status()
        data = response.json()
    if not data.get("ok"):
        raise HTTPException(502, f"Telegram API error: {data}")
    return data


async def max_api(method: str, path: str, payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not MAX_BOT_TOKEN:
        raise HTTPException(400, "MAX_BOT_TOKEN is required for real MAX API calls.")
    headers = {"Authorization": MAX_BOT_TOKEN, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(method, f"{MAX_API_BASE_URL.rstrip('/')}{path}", headers=headers, json=payload, params=params)
        response.raise_for_status()
        return response.json()


def telegram_answer_payload(chat_id: Any, answer: dict[str, Any]) -> dict[str, Any]:
    buttons = []
    for button in answer.get("buttons", []):
        callback_data = button.get("callback_data")
        if callback_data:
            buttons.append({"text": button["text"], "callback_data": callback_data})
            continue
        url = button.get("url", "")
        if url.startswith("https://"):
            buttons.append({"text": button["text"], "web_app": {"url": url}})
        else:
            buttons.append({"text": button["text"], "url": url})
    payload: dict[str, Any] = {"chat_id": chat_id, "text": answer["text"]}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": [buttons]}
    return payload


def max_message_payload(answer: dict[str, Any]) -> dict[str, Any]:
    buttons = answer.get("buttons", [])
    text = answer["text"]
    if buttons:
        first = buttons[0]
        if first.get("url"):
            text = f"{text}\n{first['text']}: {first['url']}"
        elif first.get("callback_data"):
            text = f"{text}\n{first['text']}: /approve {first['callback_data'].replace('approve:', '')}"
    return {"text": text}


def get_bot_polling_cursor(provider: Literal["telegram", "max"]) -> str | None:
    with db() as conn:
        row = conn.execute("SELECT cursor FROM bot_polling_state WHERE provider = ?", (provider,)).fetchone()
        return row["cursor"] if row and row["cursor"] else None


def set_bot_polling_cursor(provider: Literal["telegram", "max"], cursor: str | int | None) -> None:
    if cursor is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO bot_polling_state (provider, cursor, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET cursor = excluded.cursor, updated_at = excluded.updated_at
            """,
            (provider, str(cursor), now),
        )


def telegram_message_from_update(update: dict[str, Any]) -> tuple[str, dict[str, Any], Any, str | None]:
    message = update.get("message") or {}
    callback = update.get("callback_query") or {}
    callback_id = callback.get("id") if isinstance(callback, dict) else None
    if callback:
        message = callback.get("message") or {}
        text = callback.get("data") or message.get("text") or ""
    else:
        text = message.get("text") or ""
    chat = message.get("chat") or {}
    return text, message, chat.get("id"), callback_id


async def handle_telegram_update(update: dict[str, Any], send_replies: bool) -> dict[str, Any] | None:
    update_id = update.get("update_id")
    text, _message, chat_id, callback_id = telegram_message_from_update(update)
    if isinstance(text, str) and text.startswith("approve:"):
        token = bot_login_token_from_payload(text.replace("approve:", "", 1))
        user = telegram_user_from_update(update)
        approved = bool(token and user and approve_bot_login_challenge("telegram", token, user))
        if send_replies and callback_id:
            await telegram_api(
                "answerCallbackQuery",
                {"callback_query_id": callback_id, "text": "Вход подтверждён" if approved else "Ссылка устарела"},
            )
        if send_replies and chat_id is not None:
            await telegram_api(
                "sendMessage",
                {"chat_id": chat_id, "text": "Готово. Вернитесь в браузер." if approved else "Ссылка входа устарела. Попробуйте снова."},
            )
        return {"updateId": update_id, "chatId": chat_id, "botLogin": "approved" if approved else "rejected"}
    if isinstance(text, str) and text.startswith("/"):
        answer = bot_command_response("telegram", text)
        if send_replies and chat_id is not None:
            await telegram_api("sendMessage", telegram_answer_payload(chat_id, answer))
        if send_replies and callback_id:
            try:
                await telegram_api("answerCallbackQuery", {"callback_query_id": callback_id})
            except Exception as exc:
                print("telegram callback answer error", type(exc).__name__)
        return {"updateId": update_id, "chatId": chat_id, "answer": answer}
    return None


async def handle_telegram_updates(updates: list[dict[str, Any]], send_replies: bool) -> list[dict[str, Any]]:
    handled = []
    for update in updates:
        result = await handle_telegram_update(update, send_replies)
        if result:
            handled.append(result)
    return handled


def extract_max_command(update: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    message = update.get("message") or update.get("message_created", {}).get("message") or update.get("bot_started", {}).get("message") or {}
    body = message.get("body") or {}
    callback = update.get("callback") or update.get("message_callback") or {}
    text = callback.get("payload") or callback.get("data") or message.get("text") or body.get("text") or ""
    return text, message


def max_recipient_params(message: dict[str, Any]) -> dict[str, Any]:
    chat_id = message.get("chat_id") or (message.get("recipient") or {}).get("chat_id")
    user_id = message.get("user_id") or message.get("sender", {}).get("user_id") or message.get("sender", {}).get("id")
    params: dict[str, Any] = {}
    if chat_id:
        params["chat_id"] = chat_id
    elif user_id:
        params["user_id"] = user_id
    return params


async def handle_max_updates(updates: list[dict[str, Any]], send_replies: bool) -> list[dict[str, Any]]:
    handled = []
    for update in updates:
        result = await handle_max_update(update, send_replies)
        if result:
            handled.append(result)
    return handled


async def handle_max_update(update: dict[str, Any], send_replies: bool) -> dict[str, Any] | None:
    text, message = extract_max_command(update)
    if isinstance(text, str) and (text.startswith("approve:") or text.startswith("/approve ")):
        token_source = text.replace("approve:", "", 1) if text.startswith("approve:") else text.split(maxsplit=1)[1]
        token = bot_login_token_from_payload(token_source)
        user = max_user_from_message(message)
        approved = bool(token and user and approve_bot_login_challenge("max", token, user))
        params = max_recipient_params(message)
        if send_replies and params:
            await max_api(
                "POST",
                "/messages",
                {"text": "Готово. Вернитесь в браузер." if approved else "Ссылка входа устарела. Попробуйте снова."},
                params=params,
            )
        return {"update": update, "recipient": params, "botLogin": "approved" if approved else "rejected"}
    login_payload = max_login_payload_from_update(update, text)
    if login_payload:
        answer = bot_command_response("max", login_payload)
        params = max_recipient_params(message)
        if send_replies and params:
            await max_api("POST", "/messages", max_message_payload(answer), params=params)
        return {"update": update, "recipient": params, "answer": answer}
    if isinstance(text, str) and text.startswith("/"):
        answer = bot_command_response("max", text)
        params = max_recipient_params(message)
        if send_replies and params:
            await max_api("POST", "/messages", max_message_payload(answer), params=params)
        return {"update": update, "recipient": params, "answer": answer}
    return None


def polling_retry_after(exc: Exception, default: float = 5.0) -> float:
    response = getattr(exc, "response", None)
    if response is None:
        return default
    try:
        payload = response.json()
        retry_after = payload.get("parameters", {}).get("retry_after") or payload.get("retry_after")
        if retry_after:
            return float(retry_after)
    except Exception:
        pass
    header_value = getattr(response, "headers", {}).get("Retry-After") if getattr(response, "headers", None) else None
    if header_value:
        try:
            return float(header_value)
        except ValueError:
            return default
    return default


def is_auth_polling_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    return bool(response is not None and getattr(response, "status_code", None) in {401, 403})


async def telegram_poll_once_from_api(timeout: int = 0, limit: int = 10) -> dict[str, Any]:
    cursor = get_bot_polling_cursor("telegram")
    payload: dict[str, Any] = {
        "timeout": timeout,
        "limit": limit,
        "allowed_updates": ["message", "callback_query"],
    }
    if cursor:
        try:
            payload["offset"] = int(cursor)
        except ValueError:
            payload["offset"] = cursor
    data = await telegram_api("getUpdates", payload)
    updates = data.get("result", [])
    handled = await handle_telegram_updates(updates, send_replies=True)
    max_update_id = max((u.get("update_id") for u in updates if isinstance(u.get("update_id"), int)), default=None)
    if max_update_id is not None:
        set_bot_polling_cursor("telegram", max_update_id + 1)
    return {"ok": True, "handled": handled, "rawCount": len(updates), "cursor": get_bot_polling_cursor("telegram")}


async def max_poll_once_from_api(timeout: int = 0, limit: int = 10) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit, "timeout": timeout}
    marker = get_bot_polling_cursor("max")
    if marker:
        params["marker"] = marker
    data = await max_api("GET", "/updates", params=params)
    updates = data.get("updates", [])
    handled = await handle_max_updates(updates, send_replies=True)
    response_marker = data.get("marker")
    if response_marker:
        set_bot_polling_cursor("max", response_marker)
    return {"ok": True, "handled": handled, "rawCount": len(updates), "marker": get_bot_polling_cursor("max")}


async def telegram_polling_worker() -> None:
    while BOT_UPDATES_MODE == "polling" and TELEGRAM_POLLING_ENABLED and TELEGRAM_BOT_TOKEN:
        try:
            await telegram_poll_once_from_api(timeout=25, limit=20)
        except Exception as exc:
            if is_auth_polling_error(exc):
                with db() as conn:
                    record_security_event(conn, "telegram_polling_auth_error", severity="critical")
                print("telegram polling stopped after auth error")
                break
            delay = polling_retry_after(exc)
            print("telegram polling error", type(exc).__name__)
            await asyncio.sleep(delay)


async def max_polling_worker() -> None:
    while BOT_UPDATES_MODE == "polling" and MAX_POLLING_ENABLED and MAX_BOT_TOKEN and MAX_API_BASE_URL:
        try:
            await max_poll_once_from_api(timeout=25, limit=20)
        except Exception as exc:
            if is_auth_polling_error(exc):
                with db() as conn:
                    record_security_event(conn, "max_polling_auth_error", severity="critical")
                print("max polling stopped after auth error")
                break
            delay = polling_retry_after(exc)
            print("max polling error", type(exc).__name__)
            await asyncio.sleep(delay)


def start_bot_polling_tasks() -> list[str]:
    global bot_polling_started
    started: list[str] = []
    if BOT_UPDATES_MODE != "polling":
        return started
    if TELEGRAM_POLLING_ENABLED and TELEGRAM_BOT_TOKEN and "telegram" not in bot_polling_tasks:
        bot_polling_tasks["telegram"] = asyncio.create_task(telegram_polling_worker())
        started.append("telegram")
    if MAX_POLLING_ENABLED and MAX_BOT_TOKEN and MAX_API_BASE_URL and "max" not in bot_polling_tasks:
        bot_polling_tasks["max"] = asyncio.create_task(max_polling_worker())
        started.append("max")
    bot_polling_started = bool(bot_polling_tasks)
    return started


def public_url(path: Path, user_id: str = "demo_user") -> str:
    return f"/api/media/{path.name}?userId={user_id}"


def delete_image_files_from_disk(url: str | None = None, thumbnail_url: str | None = None) -> None:
    """Remove image files from disk. Safe — never raises."""
    for u in (url, thumbnail_url):
        if not u:
            continue
        try:
            fname = u.split("/api/media/")[-1].split("?")[0]
            fpath = MEDIA / fname
            if fpath.exists():
                fpath.unlink()
        except Exception:
            pass


def create_thumbnail(image_path: Path) -> Path:
    thumb_path = image_path.with_name(f"{image_path.stem}_thumb.webp")
    with Image.open(image_path) as image:
        image.thumbnail((512, 512))
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")
        image.save(thumb_path, "WEBP", quality=88)
    return thumb_path


async def comfyui_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            response = await client.get(f"{COMFYUI_BASE_URL}/object_info")
            response.raise_for_status()
            data = response.json()
            return "FluxKleinOneNode" in data
    except Exception:
            return False


async def comfyui_node_names() -> set[str]:
    """Registered ComfyUI node class names (e.g. FluxKleinOneNode, DWPreprocessor).
    Used to verify pose readiness. Returns an empty set if ComfyUI is unreachable."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{COMFYUI_BASE_URL}/object_info")
            response.raise_for_status()
            return set(response.json().keys())
    except Exception:
        return set()


async def get_comfyui_models() -> dict[str, list[str]]:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{COMFYUI_BASE_URL}/flux_klein/models")
        response.raise_for_status()
        data = response.json()
    return {
        "diffusion_models": data.get("diffusion_models", []),
        "text_encoders": data.get("text_encoders", []),
        "vaes": data.get("vaes", []),
        "loras": data.get("loras", []),
    }


async def get_flux_klein_config() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{COMFYUI_BASE_URL}/flux_klein/config")
        response.raise_for_status()
        data = response.json()
    return {
        "autofill_prompts": data.get("autofill_prompts", {}),
        "lora_triggers_custom": data.get("lora_triggers_custom", {}),
        "t2i_templates": data.get("t2i_templates", []),
        "discover_prompts": data.get("discover_prompts", {}),
    }


async def get_flux_bgremoval_models() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{COMFYUI_BASE_URL}/flux_klein/bgremoval_models")
        response.raise_for_status()
        return response.json()


async def get_flux_lora_triggers(name: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{COMFYUI_BASE_URL}/flux_klein/lora_triggers", params={"name": name})
        response.raise_for_status()
        return response.json()


def resolve_profile_model(requested: str) -> str:
    """Map a model_profiles id (e.g. 'flux_klein_9b' / 'local_flux_klein') to its
    diffusion model filename. Returns the input unchanged if it is not a known profile id
    (so passing a raw filename still works)."""
    if not requested:
        return ""
    try:
        with db() as conn:
            row = conn.execute("SELECT model_name FROM model_profiles WHERE id = ? AND enabled = 1", (requested,)).fetchone()
        if row and row["model_name"]:
            return row["model_name"]
    except Exception:
        pass
    return requested


def get_model_settings() -> dict[str, Any]:
    """Admin-configured model selection. editModelProfile is the default for all modes;
    poseModelProfile is used for the Pose role and falls back to the edit model."""
    defaults = {"editModelProfile": "flux_klein_9b", "poseModelProfile": ""}
    try:
        with db() as conn:
            row = conn.execute("SELECT value_json FROM admin_settings WHERE key = 'models'").fetchone()
        if row:
            defaults.update(json.loads(row["value_json"] or "{}"))
    except Exception:
        pass
    return defaults


def effective_edit_profile(requested: str) -> str:
    """Resolve which profile id to use: an explicit non-generic request wins, otherwise the
    admin default edit model. Never hardcodes a single model."""
    if requested and requested not in ("", "local_flux_klein", "default"):
        return requested
    return get_model_settings().get("editModelProfile") or "flux_klein_9b"


def effective_pose_profile(requested: str) -> str:
    """Pose routing: poseModelProfile wins; otherwise fall back to the edit model.
    So edit=4B + pose=9B routes Pose through 9B, exactly as configured in admin."""
    return get_model_settings().get("poseModelProfile") or effective_edit_profile(requested)


def get_profile_row(profile_id: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT id, name, model_name, supports_pose, settings_json FROM model_profiles WHERE id = ? AND enabled = 1",
            (profile_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["settings"] = json.loads(d.get("settings_json") or "{}")
    return d


# Embedded pose workflow template — bundled in-repo so Pose does NOT depend on the version
# of the installed one-node-flux-2-klein custom node (the local one ships without it).
POSE_WORKFLOW_PATH = Path(__file__).resolve().parent / "workflows" / "flux_klein_9b_pose_workflow.json"


def build_pose_workflow(models: dict[str, list[str]], profile: dict[str, Any], ref_image_name: str, pose_image_name: str, req: GenerateRequest) -> dict[str, Any]:
    """RefControl pose graph: identity/clothing/background come from the reference image
    (Image 1); only the DWPose skeleton is extracted from the pose image."""
    model, text_encoder, vae = choose_model(models, profile["id"])
    loras = models.get("loras", [])
    pose_meta = (profile.get("settings") or {}).get("pose", {}) or {}
    pose_lora = next((x for x in loras if "refcontrol" in x.lower()), pose_meta.get("lora", ""))
    graph = json.loads(POSE_WORKFLOW_PATH.read_text(encoding="utf-8"))
    graph["FKP:unet"]["inputs"]["unet_name"] = model
    graph["FKP:clip"]["inputs"]["clip_name"] = text_encoder
    graph["FKP:vae"]["inputs"]["vae_name"] = vae
    graph["FKP:lora"]["inputs"]["lora_name"] = pose_lora
    graph["FKP:refimg"]["inputs"]["image"] = ref_image_name
    graph["FKP:poseimg"]["inputs"]["image"] = pose_image_name
    graph["FKP:noise"]["inputs"]["noise_seed"] = int(req.seed or 0)
    return graph


def choose_model(models: dict[str, list[str]], requested: str) -> tuple[str, str, str]:
    diffusion = models.get("diffusion_models", [])
    text_encoders = models.get("text_encoders", [])
    vaes = models.get("vaes", [])

    requested = resolve_profile_model(requested)
    model = requested if requested in diffusion else ""
    if not model:
        model = next((item for item in diffusion if "klein-9b" in item and "fp8" in item), "")
    if not model:
        model = next((item for item in diffusion if "klein" in item), "")
    if not model and diffusion:
        model = diffusion[0]

    is_4b = "4b" in model.lower()
    preferred_te = "qwen_3_4b" if is_4b else "qwen_3_8b"
    text_encoder = next((item for item in text_encoders if preferred_te in item), "")
    if not text_encoder:
        text_encoder = next((item for item in text_encoders if "qwen_3" in item), "")
    if not text_encoder and text_encoders:
        text_encoder = text_encoders[0]

    vae = "flux2-vae.safetensors" if "flux2-vae.safetensors" in vaes else (vaes[0] if vaes else "")
    if not model or not text_encoder or not vae:
        raise RuntimeError("Модель, text encoder или VAE не найдены в ComfyUI. Откройте настройки модели.")
    return model, text_encoder, vae


async def upload_to_comfyui(path: Path) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        with path.open("rb") as file:
            files = {"image": (path.name, file, "image/png")}
            data = {"overwrite": "true", "type": "input"}
            response = await client.post(f"{COMFYUI_BASE_URL}/upload/image", files=files, data=data)
        response.raise_for_status()
        payload = response.json()
    return payload.get("name") or path.name


async def fetch_workflow(mode: str) -> dict[str, Any]:
    workflow_by_mode = {
        "text_to_image": "workflow_t2i",
        "image_to_image": "workflow_i2i",
        "edit": "workflow_edit",
        "paint": "workflow_edit",
        "inpaint": "workflow_inpaint",
        "outpaint": "workflow_outpaint",
        "faceswap": "workflow_faceswap",
        "remove_background": "workflow_remove_bg",
        "try_on": "workflow_edit",
        "texture_transfer": "workflow_edit",
    }
    endpoint = workflow_by_mode.get(mode, "workflow_t2i")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{COMFYUI_BASE_URL}/flux_klein/{endpoint}")
        response.raise_for_status()
        return response.json()


def set_input(prompt: dict[str, Any], node_id: str, key: str, value: Any) -> None:
    if node_id in prompt:
        prompt[node_id].setdefault("inputs", {})[key] = value


def patch_shared_flux_nodes(prompt: dict[str, Any], req: GenerateRequest, model: str, text_encoder: str, vae: str) -> None:
    set_input(prompt, "FK:165", "unet_name", model)
    set_input(prompt, "FK:155", "clip_name", text_encoder)
    set_input(prompt, "FK:153", "vae_name", vae)
    set_input(prompt, "FK:166", "text", req.prompt)
    # Edit-режим намеренно не использует negative prompt: ограничения уходят в основной
    # prompt. Для остальных режимов сохраняем прежний дефолтный negative как fallback.
    set_input(prompt, "FK:156", "text", "" if req.mode == "edit" else (req.negativePrompt or DEFAULT_NEG_PROMPT))
    set_input(prompt, "FK:170", "width", req.width)
    set_input(prompt, "FK:170", "height", req.height)
    set_input(prompt, "FK:171", "seed", req.seed)
    set_input(prompt, "FK:171", "steps", req.steps)
    set_input(prompt, "FK:171", "cfg", req.cfg)
    set_input(prompt, "FK:171", "denoise", 1 if req.mode == "text_to_image" else req.strength)
    set_input(prompt, "FK:171", "sampler_name", "er_sde")
    set_input(prompt, "FK:171", "scheduler", "simple")
    set_input(prompt, "FK:86", "filename_prefix", "one-node-flux-2-klein/FK")


# FLUX.2 Klein multi-reference edit: каждое изображение подаётся как ReferenceLatent в
# цепочку conditioning. Сэмплер денойзит пустой латент (размер = изображение 1), поэтому
# denoise обязан быть 1.0 — иначе пустой латент денойзится частично и даёт «мусорное полотно».
# Слоты 1-2 уже есть в workflow_edit (FK:*), слоты 3-4 создаются здесь по тому же шаблону.
EDIT_SLOT_NODES = [
    {"load": "FK:91", "scale": "FK:163", "vae": "FK:132", "pos": "FK:133", "neg": "FK:131"},
    {"load": "FK:88", "scale": "FK:163b", "vae": "FK:232", "pos": "FK:233", "neg": "FK:231"},
    {"load": "FKE:301", "scale": "FKE:303", "vae": "FKE:305", "pos": "FKE:307", "neg": "FKE:309"},
    {"load": "FKE:401", "scale": "FKE:403", "vae": "FKE:405", "pos": "FKE:407", "neg": "FKE:409"},
]


def _ensure_edit_slot_nodes(prompt: dict[str, Any], slot: int) -> None:
    s = EDIT_SLOT_NODES[slot]
    n = slot + 1
    prompt.setdefault(s["load"], {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}, "_meta": {"title": f"Load Image {n}"}})
    prompt.setdefault(s["scale"], {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": [s["load"], 0], "upscale_method": "nearest-exact", "megapixels": 1, "resolution_steps": 1}, "_meta": {"title": f"Scale Image {n} to 1MP"}})
    prompt.setdefault(s["vae"], {"class_type": "VAEEncode", "inputs": {"pixels": [s["scale"], 0], "vae": ["FK:153", 0]}, "_meta": {"title": f"VAE Encode Image {n}"}})
    prompt.setdefault(s["pos"], {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["FK:166", 0], "latent": [s["vae"], 0]}, "_meta": {"title": f"Reference Latent Positive Img{n}"}})
    prompt.setdefault(s["neg"], {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["FK:156", 0], "latent": [s["vae"], 0]}, "_meta": {"title": f"Reference Latent Negative Img{n}"}})


EDIT_REFERENCE_ROLES = {"face", "clothing", "style", "object", "pose", "background", "color_material", "other"}


def validate_edit_request(req: GenerateRequest) -> None:
    """Серверная валидация edit-запроса (frontend тоже блокирует, но backend не доверяет клиенту)."""
    images = req.inputImages
    if not images:
        # Legacy-путь (inputImage1/2) — основа обязательна.
        if not req.inputImage1:
            raise HTTPException(422, "Edit: нужна основа (изображение 1).")
        return
    by_index = {}
    for item in images:
        if not item.image:
            continue
        if not (1 <= (item.index or 0) <= 4):
            raise HTTPException(422, f"Edit: index должен быть 1–4 (получен {item.index}).")
        if item.index in by_index:
            raise HTTPException(422, f"Edit: повторяющийся index {item.index}.")
        by_index[item.index] = item
    if 1 not in by_index:
        raise HTTPException(422, "Edit: нужна основа (index 1, role=base).")
    for idx, item in by_index.items():
        if idx == 1:
            continue
        role = (item.role or "").strip()
        if not role:
            raise HTTPException(422, f"Edit: для референса (index {idx}) не выбрана роль.")
        if role not in EDIT_REFERENCE_ROLES:
            raise HTTPException(422, f"Edit: неизвестная роль '{role}' (index {idx}).")


def patch_edit_reference_chain(prompt: dict[str, Any], image_files: list[str]) -> None:
    present = [f for f in image_files if f][:4]
    if not present:
        raise RuntimeError("Для редактирования нужно хотя бы одно изображение (основа).")
    prev_pos, prev_neg = "FK:166", "FK:156"
    for i, fname in enumerate(present):
        _ensure_edit_slot_nodes(prompt, i)
        s = EDIT_SLOT_NODES[i]
        set_input(prompt, s["load"], "image", fname)
        # Перепривязываем conditioning этого слота к концу уже построенной цепочки.
        set_input(prompt, s["pos"], "conditioning", [prev_pos, 0])
        set_input(prompt, s["neg"], "conditioning", [prev_neg, 0])
        prev_pos, prev_neg = s["pos"], s["neg"]
    # Удаляем неиспользуемые слоты (по умолчанию workflow приходит с 2 изображениями).
    for i in range(len(present), 4):
        for nid in EDIT_SLOT_NODES[i].values():
            prompt.pop(nid, None)
    # Сэмплер читает конец цепочки референсов; пустой латент → denoise=1.
    set_input(prompt, "FK:171", "positive", [prev_pos, 0])
    set_input(prompt, "FK:171", "negative", [prev_neg, 0])
    set_input(prompt, "FK:171", "denoise", 1)


def patch_mode_nodes(prompt: dict[str, Any], req: GenerateRequest, uploads: dict[str, str], model: str, text_encoder: str, vae: str) -> None:
    patch_shared_flux_nodes(prompt, req, model, text_encoder, vae)

    if req.mode == "image_to_image":
        set_input(prompt, "FKI2I:img", "image", uploads["input1"])
        set_input(prompt, "FK:171", "denoise", req.strength)
    elif req.mode == "remove_background":
        set_input(prompt, "rmbg:load", "bg_removal_name", "birefnet.safetensors")
        set_input(prompt, "rmbg:img", "image", uploads["input1"])
        set_input(prompt, "rmbg:save", "filename_prefix", "one-node-flux-2-klein/assets/rmbg")
    elif req.mode in {"edit", "paint", "try_on", "texture_transfer"}:
        # 1..4 изображения в порядке слотов; цепочка ReferenceLatent + denoise=1.
        image_files = [uploads.get(f"input{i}") for i in range(1, 5)]
        patch_edit_reference_chain(prompt, image_files)
    elif req.mode == "inpaint":
        set_input(prompt, "FKI:194", "unet_name", model)
        set_input(prompt, "FKI:195", "clip_name", text_encoder)
        set_input(prompt, "FKI:196", "vae_name", vae)
        set_input(prompt, "FKI:6", "text", req.prompt)
        set_input(prompt, "FKI:198", "image", uploads["input1"])
        set_input(prompt, "FKI:199", "image", uploads.get("mask", uploads["input1"]))
        set_input(prompt, "FKI:209", "preresize_min_width", req.width)
        set_input(prompt, "FKI:209", "preresize_min_height", req.height)
        set_input(prompt, "FKI:209", "output_target_width", req.width)
        set_input(prompt, "FKI:209", "output_target_height", req.height)
        set_input(prompt, "FKI:163", "seed", req.seed)
        set_input(prompt, "FKI:163", "steps", req.steps)
        set_input(prompt, "FKI:163", "cfg", req.cfg)
        set_input(prompt, "FKI:163", "denoise", req.strength)
        set_input(prompt, "FKI:203", "filename_prefix", "one-node-flux-2-klein/FK")
    elif req.mode == "outpaint":
        set_input(prompt, "FKO:194", "unet_name", model)
        set_input(prompt, "FKO:195", "clip_name", text_encoder)
        set_input(prompt, "FKO:196", "vae_name", vae)
        set_input(prompt, "FKO:6", "text", req.prompt)
        set_input(prompt, "FKO:198", "image", uploads["input1"])
        set_input(prompt, "FKO:maskload", "image", uploads.get("mask", uploads["input1"]))
        set_input(prompt, "FKO:163", "seed", req.seed)
        set_input(prompt, "FKO:163", "steps", req.steps)
        set_input(prompt, "FKO:163", "cfg", req.cfg)
        set_input(prompt, "FKO:163", "denoise", req.strength)
        set_input(prompt, "FKO:203", "filename_prefix", "one-node-flux-2-klein/FK")
    elif req.mode == "faceswap":
        face_lora = req.loras[0] if req.loras else None
        set_input(prompt, "FKF:225", "unet_name", model)
        set_input(prompt, "FKF:223", "clip_name", text_encoder)
        set_input(prompt, "FKF:235", "vae_name", vae)
        if face_lora:
            set_input(prompt, "FKF:226", "lora_name", face_lora.id)
            set_input(prompt, "FKF:226", "strength_model", face_lora.strength)
        set_input(prompt, "FKF:234", "image", uploads["input1"])
        set_input(prompt, "FKF:236", "image", uploads["input2"])
        if req.prompt.strip():
            set_input(prompt, "FKF:227", "text", req.prompt)
        set_input(prompt, "FKF:229", "text", "")
        set_input(prompt, "FKF:228", "seed", req.seed)
        set_input(prompt, "FKF:228", "steps", req.steps)
        set_input(prompt, "FKF:228", "cfg", req.cfg)
        set_input(prompt, "FKF:228", "denoise", 1)
        set_input(prompt, "FKF:228", "sampler_name", "er_sde")
        set_input(prompt, "FKF:228", "scheduler", "simple")
        set_input(prompt, "FKF:239", "model", ["FKF:226", 0])
        set_input(prompt, "FKF:232", "filename_prefix", "one-node-flux-2-klein/FK")


async def submit_workflow(workflow: dict[str, Any], job: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{COMFYUI_BASE_URL}/prompt",
            json={"prompt": workflow, "client_id": f"onenode-backend-{job['id']}", "extra_data": {"enable_previews": True}},
        )
        response.raise_for_status()
        data = response.json()
    if data.get("error"):
        raise RuntimeError(f"ComfyUI workflow error: {data['error']}")
    node_errors = data.get("node_errors") or {}
    if node_errors:
        raise RuntimeError(f"ComfyUI node errors: {json.dumps(node_errors, ensure_ascii=False)}")
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError("ComfyUI не вернул prompt_id.")
    history = await wait_for_history(prompt_id, job)
    return prompt_id, history, extract_images_from_history(history)


def extract_images_from_history(history: dict[str, Any]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    outputs = history.get("outputs", {})
    for output in outputs.values():
        for image in output.get("images", []):
            if image.get("filename"):
                found.append(
                    {
                        "filename": image["filename"],
                        "subfolder": image.get("subfolder", ""),
                        "type": image.get("type", "output"),
                    }
                )
    return found


async def wait_for_history(prompt_id: str, job: dict[str, Any]) -> dict[str, Any]:
    deadline = time.monotonic() + COMFYUI_TIMEOUT_SECONDS
    async with httpx.AsyncClient(timeout=20) as client:
        while time.monotonic() < deadline:
            if job.get("status") == "cancelled":
                raise RuntimeError("Задача отменена")
            response = await client.get(f"{COMFYUI_BASE_URL}/history/{prompt_id}")
            response.raise_for_status()
            payload = response.json()
            if prompt_id in payload:
                return payload[prompt_id]
            job["progress"] = min(94, int(job.get("progress", 24)) + 2)
            await asyncio.sleep(2)
    raise TimeoutError("ComfyUI не вернул результат до истечения таймаута.")


async def download_comfyui_image(image: dict[str, str], job_id: str) -> tuple[Path, Path]:
    params = {"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")}
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.get(f"{COMFYUI_BASE_URL}/view", params=params)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        extension = "png" if "png" in content_type else "jpg"
        image_path = MEDIA / f"{job_id}_comfyui.{extension}"
        image_path.write_bytes(response.content)
    return image_path, create_thumbnail(image_path)


async def send_to_comfyui(payload: GenerateRequest, job: dict[str, Any]) -> ComfyUIResult | None:
    if not await comfyui_available():
        if COMFYUI_REQUIRED:
            raise RuntimeError("FluxKleinOneNode не найден или ComfyUI недоступен. Проверьте установку custom node.")
        if not COMFYUI_MOCK_FALLBACK:
            raise RuntimeError("ComfyUI недоступен. Проверьте, что сервер запущен.")
        return None

    models = await get_comfyui_models()
    model, text_encoder, vae = choose_model(models, effective_edit_profile(payload.modelProfile))
    available_loras = models.get("loras", [])
    is_4b = "4b" in model.lower()
    target_lora_tag = "4b" if is_4b else "9b"
    for lora in payload.loras:
        if lora.id == "none" or not lora.id:
            continue
        if target_lora_tag not in lora.id.lower():
            fallback = next(
                (item for item in available_loras
                 if target_lora_tag in item.lower() and any(kw in item.lower() for kw in ("bfs", "face", "head"))),
                "",
            )
            if not fallback:
                fallback = next((item for item in available_loras if target_lora_tag in item.lower()), "")
            if fallback:
                lora.id = fallback
    workflow = await fetch_workflow(payload.mode)
    pose_graph: dict[str, Any] | None = None

    uploads: dict[str, str] = {}
    input1_path = local_media_path_from_url(payload.inputImage1 or "") or save_data_url(payload.inputImage1, f"{job['id']}_input1")
    input2_path = local_media_path_from_url(payload.inputImage2 or "") or save_data_url(payload.inputImage2, f"{job['id']}_input2")
    mask_source = payload.maskImage or payload.outpaintMask
    mask_path = local_media_path_from_url(mask_source or "") or save_data_url(mask_source, f"{job['id']}_mask")
    canvas_path = save_canvas_json(payload.canvas, f"{job['id']}_canvas")
    primary_input = input1_path or canvas_path
    if payload.mode == "edit":
        # До 4 изображений. Источник — payload.inputImages (новый формат) или legacy inputImage1/2.
        edit_sources: list[tuple[str, str]] = []
        if payload.inputImages:
            for item in sorted(payload.inputImages, key=lambda x: x.index or 0):
                if item.image:
                    edit_sources.append((item.role or "", item.image))
        else:
            if payload.inputImage1:
                edit_sources.append(("base", payload.inputImage1))
            if payload.inputImage2:
                edit_sources.append(("", payload.inputImage2))
        edit_roles: list[str] = []
        pose_image_name: str | None = None
        for i, (role, src) in enumerate(edit_sources[:4]):
            slot_path = local_media_path_from_url(src) or save_data_url(src, f"{job['id']}_edit{i + 1}")
            if not slot_path:
                continue
            uploads[f"input{i + 1}"] = await upload_to_comfyui(slot_path)
            edit_roles.append(role or ("base" if i == 0 else "?"))
            if role == "pose" and i > 0:
                pose_image_name = uploads[f"input{i + 1}"]
        if "input1" not in uploads:
            raise RuntimeError("Для редактирования нужна основа (изображение 1).")
        print(f"edit-generate job={job['id']} images={sum(1 for k in uploads if k.startswith('input'))} roles={edit_roles}")

        # role=Pose: separate workflow branch (DWPose skeleton + RefControl LoRA). Identity,
        # clothing and background come from Image 1; only the pose transfers from the pose ref.
        if "pose" in edit_roles:
            other_roles = [r for r in edit_roles if r not in ("base", "pose", "?", "")]
            if other_roles:
                raise RuntimeError("Pose пока поддерживается только отдельно — без сочетания с другими ролями (" + ", ".join(other_roles) + ") в одном запросе.")
            if not pose_image_name:
                raise RuntimeError("Для роли Поза нужен референс с позой (изображение 2).")
            pose_profile_id = effective_pose_profile(payload.modelProfile)
            status = await compute_model_status()
            prof = next((p for p in status["profiles"] if p["id"] == pose_profile_id), None)
            if not prof or not prof.get("supportsPose"):
                raise RuntimeError(f"Pose workflow is not supported for {pose_profile_id}.")
            if prof.get("pose") != "available":
                miss = ", ".join(prof.get("poseMissing", [])) or "зависимости"
                raise RuntimeError(f"Pose workflow is not available for selected pose model profile ({pose_profile_id}): отсутствует {miss}.")
            profile_row = get_profile_row(pose_profile_id)
            pose_graph = build_pose_workflow(models, profile_row, uploads["input1"], pose_image_name, payload)
            print(f"pose-generate job={job['id']} profile={pose_profile_id} ref=input1 pose={pose_image_name}")
    elif payload.mode in {"image_to_image", "paint", "inpaint", "outpaint", "faceswap", "remove_background", "try_on", "texture_transfer"}:
        if not primary_input:
            raise RuntimeError("Для выбранного режима нужно входное изображение.")
        uploads["input1"] = await upload_to_comfyui(primary_input)
    if payload.mode in {"faceswap", "try_on", "texture_transfer"}:
        if not input2_path:
            raise RuntimeError("Для выбранного режима нужно два изображения.")
        uploads["input2"] = await upload_to_comfyui(input2_path)
    if payload.mode in {"inpaint", "outpaint"} and mask_path:
        uploads["mask"] = await upload_to_comfyui(mask_path)

    if pose_graph is not None:
        workflow = pose_graph
    else:
        patch_mode_nodes(workflow, payload, uploads, model, text_encoder, vae)
    try:
        prompt_id, history, output_images = await submit_workflow(workflow, job)
    except Exception as exc:
        if payload.mode not in {"inpaint", "outpaint", "faceswap", "remove_background", "try_on", "texture_transfer"}:
            raise
        prompt_id = "fallback_after_workflow_error"
        history = {"error": str(exc)}
        output_images = []
    if not output_images and payload.mode in {"inpaint", "outpaint", "faceswap", "remove_background", "try_on", "texture_transfer"}:
        try:
            fallback = await fetch_workflow("edit")
            fallback_req = payload.model_copy(update={"mode": "edit"})
            patch_mode_nodes(fallback, fallback_req, uploads, model, text_encoder, vae)
            prompt_id, history, output_images = await submit_workflow(fallback, job)
        except Exception as exc:
            history = {"fallback": "edit_workflow_error", "error": str(exc)}
            output_images = []
    if not output_images and payload.mode in {"inpaint", "outpaint", "faceswap", "remove_background", "try_on", "texture_transfer"}:
        try:
            fallback = await fetch_workflow("text_to_image")
            fallback_req = payload.model_copy(
                update={
                    "mode": "text_to_image",
                    "prompt": f"{payload.mode.replace('_', ' ')} result: {payload.prompt}",
                }
            )
            patch_mode_nodes(fallback, fallback_req, {}, model, text_encoder, vae)
            prompt_id, history, output_images = await submit_workflow(fallback, job)
        except Exception as exc:
            history = {"fallback": "text_to_image_workflow_error", "error": str(exc)}
            output_images = []
    if not output_images and payload.mode in {"inpaint", "outpaint", "faceswap", "remove_background", "try_on", "texture_transfer"}:
        image_path, thumb_path = mock_image(payload, job["id"])
        return ComfyUIResult(prompt_id=prompt_id, image_path=image_path, thumbnail_path=thumb_path, history={"fallback": "no_comfyui_output_image", **history})
    if not output_images:
        raise RuntimeError("ComfyUI завершил задачу, но не вернул изображения в history.")
    image_path, thumb_path = await download_comfyui_image(output_images[-1], job["id"])
    return ComfyUIResult(prompt_id=prompt_id, image_path=image_path, thumbnail_path=thumb_path, history=history)


def save_data_url(data_url: str | None, prefix: str) -> Path | None:
    if not data_url or not data_url.startswith("data:image"):
        return None
    header, encoded = data_url.split(",", 1)
    extension = "png"
    if "jpeg" in header or "jpg" in header:
        extension = "jpg"
    path = MEDIA / f"{prefix}_{uuid.uuid4().hex}.{extension}"
    path.write_bytes(base64.b64decode(encoded))
    return path


def save_canvas_json(canvas: str | None, prefix: str) -> Path | None:
    if not canvas:
        return None
    if canvas.startswith("data:image"):
        return save_data_url(canvas, prefix)
    path = MEDIA / f"{prefix}.png"
    image = Image.new("RGB", (1024, 1024), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text((48, 48), "Paint canvas input", fill="#172033")
    image.save(path, "PNG")
    return path


def mock_image(req: GenerateRequest, job_id: str) -> tuple[Path, Path]:
    width = min(max(req.width, 512), 2048)
    height = min(max(req.height, 512), 2048)
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    palette = ["#117865", "#2f6fed", "#d97706", "#be123c", "#172033"]
    for i, color in enumerate(palette):
        draw.rectangle([i * width / 5, 0, (i + 1) * width / 5, height], fill=color)
    draw.rounded_rectangle([40, 40, width - 40, height - 40], radius=24, fill=(255, 255, 255, 232), outline="#d9e1ea", width=4)
    text = f"{req.mode.replace('_', ' ').title()}\n{req.prompt[:180]}\nseed {req.seed}"
    try:
        font = ImageFont.truetype("arial.ttf", max(26, width // 34))
    except Exception:
        font = ImageFont.load_default()
    draw.multiline_text((72, 72), text, fill="#172033", font=font, spacing=14)
    out = MEDIA / f"{job_id}.png"
    thumb = MEDIA / f"{job_id}_thumb.webp"
    image.save(out, "PNG")
    image.thumbnail((512, 512))
    image.save(thumb, "WEBP", quality=88)
    return out, thumb


async def worker() -> None:
    while True:
        job_id = await queue.get()
        job = jobs[job_id]
        req = GenerateRequest(**job["request"])
        started = time.perf_counter()
        try:
            if job.get("status") == "cancelled":
                persist_job(job, req)
                continue
            job.update(status="uploading", progress=12, message="Загружаем изображения")
            persist_job(job, req)
            save_data_url(req.inputImage1, f"{job_id}_input1")
            save_data_url(req.inputImage2, f"{job_id}_input2")
            await asyncio.sleep(0.5)
            job.update(status="sent_to_comfyui", progress=24, message="Отправляем в ComfyUI")
            persist_job(job, req)
            prompt_id = None
            image_path = None
            thumb_path = None
            comfyui_history = None
            if req.provider == "comfyui":
                result = await send_to_comfyui(req, job)
                if result:
                    prompt_id = result.prompt_id
                    image_path = result.image_path
                    thumb_path = result.thumbnail_path
                    comfyui_history = result.history
            if not image_path:
                if req.provider == "comfyui" and not COMFYUI_MOCK_FALLBACK:
                    raise RuntimeError("ComfyUI не вернул изображение, mock fallback отключён.")
                await asyncio.sleep(0.8)
                for progress in (38, 52, 67, 81, 94):
                    if job["status"] == "cancelled":
                        break
                    job.update(status="running", progress=progress, message="Генерация изображения")
                    persist_job(job, req)
                    await asyncio.sleep(0.45)
            if job["status"] == "cancelled":
                persist_job(job, req)
                continue
            if not image_path or not thumb_path:
                image_path, thumb_path = mock_image(req, job_id)
            user_id = job.get("userId", "demo_user")
            with db() as conn:
                user_row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                gallery_quota = gallery_quota_for_user(conn, user_row, user_id)
            image_id = f"img_{uuid.uuid4().hex[:12]}"
            created_at = datetime.now(timezone.utc).isoformat()
            record = {
                "id": image_id,
                "userId": user_id,
                "url": public_url(image_path, user_id),
                "thumbnailUrl": public_url(thumb_path, user_id),
                "mode": req.mode,
                "provider": req.provider,
                "promptOriginal": req.prompt,
                "promptTranslated": req.prompt if req.prompt.isascii() else "",
                "seed": req.seed,
                "width": req.width,
                "height": req.height,
                "modelProfile": req.modelProfile,
                "loras": [item.id for item in req.loras],
                "preset": None,
                "generationTimeMs": int((time.perf_counter() - started) * 1000),
                "isFavorite": False,
                "createdAt": created_at,
                "comfyuiPromptId": prompt_id,
                "comfyuiHistory": comfyui_history,
            }
            if gallery_quota["gallery_full"]:
                with db() as conn:
                    oldest = conn.execute(
                        "SELECT id, url, thumbnail_url FROM images WHERE user_id = ? AND (deleted_at IS NULL OR deleted_at = '') ORDER BY created_at ASC LIMIT 1",
                        (user_id,),
                    ).fetchone()
                    if oldest:
                        conn.execute("UPDATE images SET deleted_at = ? WHERE id = ?", (created_at, oldest["id"]))
                        delete_image_files_from_disk(url=oldest["url"], thumbnail_url=oldest["thumbnail_url"])
                        if oldest["id"] in images:
                            images.pop(oldest["id"])
                images[image_id] = record
                persist_image(record, job_id)
                with db() as conn:
                    saved_user_row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                    gallery_quota = gallery_quota_for_user(conn, saved_user_row, user_id)
                job.update(
                    status="completed",
                    progress=100,
                    message="Готово",
                    resultImageId=image_id,
                    resultUrl=record["url"],
                    gallerySaveStatus="saved",
                    galleryQuota=gallery_quota,
                    completedAt=created_at,
                )
            else:
                images[image_id] = record
                persist_image(record, job_id)
                with db() as conn:
                    saved_user_row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                    gallery_quota = gallery_quota_for_user(conn, saved_user_row, user_id)
                job.update(
                    status="completed",
                    progress=100,
                    message="Готово",
                    resultImageId=image_id,
                    resultUrl=record["url"],
                    gallerySaveStatus="saved",
                    galleryQuota=gallery_quota,
                    completedAt=created_at,
                )
            persist_job(job, req)
        except Exception as exc:
            job.update(status="failed", progress=100, message="Генерация не выполнена.", error=str(exc), completedAt=datetime.now(timezone.utc).isoformat())
            persist_job(job, req)
        finally:
            queue.task_done()


@app.on_event("startup")
async def startup() -> None:
    global worker_started, bot_polling_started
    db_guard_preflight()
    validate_session_crypto_config()
    init_db()
    enforce_db_guard_after_migrations()
    load_db_state()
    if not worker_started:
        asyncio.create_task(worker())
        worker_started = True
    if BOT_UPDATES_MODE == "polling":
        start_bot_polling_tasks()
    elif BOT_UPDATES_MODE == "webhook":
        backend_public = os.getenv("BACKEND_PUBLIC_URL", "http://127.0.0.1:8000")
        if TELEGRAM_BOT_TOKEN and backend_public.startswith("https://"):
            try:
                wh_url = f"{backend_public}/api/telegram/webhook"
                await telegram_api("setWebhook", {"url": wh_url})
                print(f"Telegram webhook set to {wh_url}")
            except Exception as exc:
                print(f"Failed to set Telegram webhook: {exc}")
        if MAX_BOT_TOKEN and backend_public.startswith("https://"):
            try:
                wh_url = f"{backend_public}/api/max/webhook"
                await max_api("POST", "/webhooks", {"url": wh_url, "secret": MAX_WEBHOOK_SECRET})
                print(f"MAX webhook set to {wh_url}")
            except Exception as exc:
                print(f"Failed to set MAX webhook: {exc}")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    guard = collect_db_guard_status()
    DB_GUARD_STATUS.update(guard)
    return {
        "ok": True,
        "app": "izo-asa",
        "version": APP_BUILD,
        "environment": "production" if is_production_like_env() else "development",
        "comfyuiBaseUrl": COMFYUI_BASE_URL,
        "fluxKleinOneNode": await comfyui_available(),
        "database": {
            "type": "sqlite",
            "ready": bool(guard.get("ok")),
            "path": mask_db_path(DB_PATH),
            "size_mb": guard.get("db_size_mb", db_size_mb(DB_PATH)),
            "users_count": guard.get("users_count", 0),
            "active_admin_count": guard.get("active_admin_count", 0),
            "migration_status": guard.get("migration_status", "unknown"),
        },
        "db_guard": safe_db_guard_payload(guard),
        "platforms": {"web": True, "telegram": True, "max": True},
    }


# Minimal, non-sensitive version marker so operators can tell which backend build
# is actually live. No secrets, no env values, no raw DB URLs.
APP_BUILD = os.getenv("APP_BUILD", "20E.2E-2026-06-28")


@app.get("/api/version")
async def version() -> dict[str, Any]:
    routes = {r.path for r in app.routes}
    return {
        "ok": True,
        "app": "izo-asa",
        "build": APP_BUILD,
        "backend_commit": safe_backend_commit(),
        "frontend_build": os.getenv("FRONTEND_BUILD_LABEL", "unknown"),
        "started_at": STARTED_AT,
        "db_guard": safe_db_guard_payload(DB_GUARD_STATUS),
        "auth_v2": True,
        "password_login": "/api/auth/password/login-v2" in routes,
        "generation_protected": True,  # /api/generate calls require_trusted_user
    }


def ensure_rate_limit(user_id: str) -> None:
    now = datetime.now(timezone.utc)
    with db() as conn:
        rows = conn.execute("SELECT created_at FROM jobs WHERE user_id = ?", (user_id,)).fetchall()
    hour_count = 0
    day_count = 0
    for row in rows:
        try:
            created = datetime.fromisoformat(row["created_at"])
        except Exception:
            continue
        delta = now - created
        if delta.total_seconds() <= 3600:
            hour_count += 1
        if delta.total_seconds() <= 86400:
            day_count += 1
    if hour_count >= rate_limits["hourly"]:
        raise HTTPException(429, f"Rate limit exceeded: {rate_limits['hourly']} generations per hour.")
    if day_count >= rate_limits["daily"]:
        raise HTTPException(429, f"Rate limit exceeded: {rate_limits['daily']} generations per day.")


@app.post("/api/generate")
async def generate(req: GenerateRequest, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    internal_user_id = trusted["internal_user_id"]
    session_id = trusted.get("session_id")
    token_cost = estimate_token_cost(req)
    used_daily = False
    with db() as conn:
        user_row = conn.execute("SELECT id, token_balance, plan, daily_tokens_used, last_daily_reset FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_row is None:
            raise HTTPException(404, "User not found.")
        if user_id != "demo_user":
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            daily_used = int(user_row["daily_tokens_used"] or 0)
            last_reset = user_row["last_daily_reset"]
            if last_reset != today:
                daily_used = 0
            tariff = get_tariff_config(conn)[str(user_row["plan"] or "mini").lower()]
            daily_limit = int(tariff["daily_tokens"])
            if daily_used + token_cost <= daily_limit:
                used_daily = True
                conn.execute(
                    "UPDATE users SET daily_tokens_used = ?, last_daily_reset = ? WHERE id = ?",
                    (daily_used + token_cost, today, user_id),
                )
            else:
                if int(user_row["token_balance"] or 0) < token_cost:
                    raise HTTPException(402, "Not enough tokens.")
        else:
            if int(user_row["token_balance"] or 0) < token_cost:
                raise HTTPException(402, "Not enough tokens.")
    if req.mode == "faceswap":
        face_lora = next((item for item in req.loras if item.id and item.id != "none"), None)
        if face_lora is None:
            raise HTTPException(422, "FaceSwap mode requires a FaceSwap LoRA. Select bfs_head or another face LoRA.")
    if req.mode == "edit":
        validate_edit_request(req)
    ensure_rate_limit(user_id)
    job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    job = {
        "id": job_id,
        "userId": user_id,
        "mode": req.mode,
        "provider": req.provider,
        "status": "queued",
        "progress": 0,
        "message": "В очереди",
        "request": req.model_dump(),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    jobs[job_id] = job
    persist_job(job, req)
    with db() as conn:
        balance_delta = 0 if (used_daily or user_id == "demo_user") else token_cost
        conn.execute(
            """
            UPDATE users
            SET token_balance = CASE WHEN id = 'demo_user' THEN token_balance ELSE MAX(0, token_balance - ?) END,
                tokens_used = tokens_used + ?,
                generation_count = generation_count + 1,
                last_seen_at = ?
            WHERE id = ?
            """,
            (balance_delta, token_cost, datetime.now(timezone.utc).isoformat(), user_id),
        )
        conn.execute(
            "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, 'generation', ?, ?)",
            (str(uuid.uuid4()), user_id, -balance_delta, json.dumps({"jobId": job_id, "mode": req.mode, "provider": req.provider, "used_daily_budget": used_daily}, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )
    await queue.put(job_id)
    try:
        record_event_log(
            "generation_started",
            internal_user_id=internal_user_id,
            legacy_user_id=user_id,
            session_id=session_id,
            platform=trusted.get("platform", "web"),
            properties={"mode": req.mode, "provider": req.provider, "size": f"{req.width}x{req.height}", "token_cost": token_cost},
        )
    except Exception:
        pass
    return {k: v for k, v in job.items() if k != "request"} | {"queuePosition": queue.qsize(), "tokenCost": token_cost, "usedDailyBudget": used_daily}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict[str, Any]:
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    if jobs[job_id].get("userId") != user_id:
        raise HTTPException(404, "Job not found")
    return {k: v for k, v in jobs[job_id].items() if k != "request"}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    if jobs[job_id].get("userId") != user_id:
        raise HTTPException(404, "Job not found")
    jobs[job_id].update(status="cancelled", progress=100, message="Отменено")
    persist_job(jobs[job_id])
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{COMFYUI_BASE_URL}/interrupt")
    except Exception:
        pass
    return {k: v for k, v in jobs[job_id].items() if k != "request"}


@app.get("/api/models")
async def models() -> dict[str, Any]:
    try:
        data = await get_comfyui_models()
        model, text_encoder, vae = choose_model(data, "")
        return {"ok": True, "selected": {"model": model, "textEncoder": text_encoder, "vae": vae}, **data}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "diffusion_models": [], "text_encoders": [], "vaes": [], "loras": []}


@app.get("/api/flux-klein/config")
async def flux_klein_config() -> dict[str, Any]:
    try:
        return {"ok": True, **await get_flux_klein_config()}
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "autofill_prompts": {},
            "lora_triggers_custom": {},
            "t2i_templates": [],
            "discover_prompts": {},
        }


@app.get("/api/flux-klein/bgremoval-models")
async def flux_klein_bgremoval_models() -> dict[str, Any]:
    try:
        return {"ok": True, **await get_flux_bgremoval_models()}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "models": []}


@app.get("/api/flux-klein/lora-triggers")
async def flux_klein_lora_triggers(name: str) -> dict[str, Any]:
    try:
        return await get_flux_lora_triggers(name)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "triggers": [], "name": name}


@app.get("/api/tariffs")
async def tariffs() -> dict[str, Any]:
    return {"ok": True, "tariffs": get_tariff_config()}


@app.get("/api/gallery")
async def gallery(request: Request) -> list[dict[str, Any]]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        if not user_gallery_allowed(conn, trusted["internal_user_id"], user_id):
            raise HTTPException(403, "Gallery is not available for this plan.")
    if not images and DB_PATH.exists():
        load_db_state()
    return sorted([item for item in images.values() if item.get("userId", "demo_user") == user_id], key=lambda item: item["createdAt"], reverse=True)


@app.get("/api/gallery/{image_id}")
async def gallery_detail(image_id: str, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        if not user_gallery_allowed(conn, trusted["internal_user_id"], user_id):
            raise HTTPException(403, "Gallery is not available for this plan.")
    if image_id not in images and DB_PATH.exists():
        load_db_state()
    if image_id not in images or images[image_id].get("userId", "demo_user") != user_id:
        raise HTTPException(404, "Image not found")
    return images[image_id]


@app.post("/api/gallery/{image_id}/favorite")
async def gallery_favorite(image_id: str, req: FavoriteRequest, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        if not user_gallery_allowed(conn, trusted["internal_user_id"], user_id):
            raise HTTPException(403, "Gallery is not available for this plan.")
    if image_id not in images and DB_PATH.exists():
        load_db_state()
    if image_id not in images or images[image_id].get("userId", "demo_user") != user_id:
        raise HTTPException(404, "Image not found")
    images[image_id]["isFavorite"] = req.isFavorite
    with db() as conn:
        conn.execute("UPDATE images SET is_favorite = ? WHERE id = ?", (1 if req.isFavorite else 0, image_id))
    return images[image_id]


@app.delete("/api/gallery/{image_id}")
async def gallery_delete(image_id: str, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        if not user_gallery_allowed(conn, trusted["internal_user_id"], user_id):
            raise HTTPException(403, "Gallery is not available for this plan.")
    if image_id not in images and DB_PATH.exists():
        load_db_state()
    if image_id not in images or images[image_id].get("userId", "demo_user") != user_id:
        raise HTTPException(404, "Image not found")
    record = images.pop(image_id)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute("UPDATE images SET deleted_at = ? WHERE id = ? AND user_id = ?", (now, image_id, user_id))
    delete_image_files_from_disk(url=record.get("url"), thumbnail_url=record.get("thumbnailUrl"))
    return {"ok": True, "deleted": image_id, "url": record["url"]}


@app.post("/api/gallery/{image_id}/use-as")
async def gallery_use_as(image_id: str, req: UseAsRequest, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        if not user_gallery_allowed(conn, trusted["internal_user_id"], user_id):
            raise HTTPException(403, "Gallery is not available for this plan.")
    if image_id not in images and DB_PATH.exists():
        load_db_state()
    if image_id not in images or images[image_id].get("userId", "demo_user") != user_id:
        raise HTTPException(404, "Image not found")
    record = images[image_id]
    return {
        "ok": True,
        "imageId": image_id,
        "target": req.target,
        "inputImage": record["url"],
        "prompt": record["promptOriginal"],
        "seed": record["seed"],
        "width": record["width"],
        "height": record["height"],
    }


@app.get("/api/media/{filename}")
async def secure_media(filename: str, request: Request) -> FileResponse:
    try:
        trusted = require_trusted_user(request)
        user_id = trusted["legacy_user_id"]
    except HTTPException:
        user_id = request.query_params.get("userId") or "demo_user"
    path = (MEDIA / filename).resolve()
    try:
        path.relative_to(MEDIA.resolve())
    except ValueError:
        raise HTTPException(404, "Image not found")
    if not path.exists():
        raise HTTPException(404, "Image not found")
    if filename.endswith("_thumb.webp"):
        stem = filename.removesuffix("_thumb.webp")
        allowed = any(
            item.get("thumbnailUrl", "").startswith(f"/api/media/{filename}") and item.get("userId", "demo_user") == user_id
            for item in images.values()
        )
    else:
        allowed = any(
            item.get("url", "").startswith(f"/api/media/{filename}") and item.get("userId", "demo_user") == user_id
            for item in images.values()
        )
    if not allowed:
        raise HTTPException(404, "Image not found")
    return FileResponse(path)


@app.post("/api/app/bootstrap")
async def bootstrap(auth: MiniAppAuthRequest, response: Response) -> dict[str, Any]:
    # In production, never accept an empty or demo_user identity silently.
    if is_production_like_env() and (not auth.userId or auth.userId == "demo_user"):
        raise HTTPException(401, "Authentication required")
    # Validate Telegram initData server-side
    if auth.platform == "telegram":
        if not auth.initData:
            print("bootstrap: telegram platform but no initData — falling back to web")
            auth.platform = "web"
            if not auth.userId or auth.userId == "demo_user":
                auth.userId = "demo_user"
        else:
            valid = validate_telegram_init_data(auth.initData)
            if not valid:
                print("bootstrap: invalid Telegram initData, rejecting")
                raise HTTPException(403, "Invalid Telegram initData")
            # Override userId and user info from server-verified data
            tg_user_raw = valid.get("user")
            if tg_user_raw:
                try:
                    tg_user = json.loads(tg_user_raw)
                    auth.userId = str(tg_user.get("id", auth.userId))
                    auth.username = tg_user.get("username") or auth.username
                    auth.firstName = tg_user.get("first_name") or auth.firstName
                    auth.lastName = tg_user.get("last_name") or auth.lastName
                    auth.language = tg_user.get("language_code") or auth.language
                    print(f"bootstrap: Telegram user verified — id={auth.userId} username={auth.username}")
                except (json.JSONDecodeError, KeyError) as exc:
                    print(f"bootstrap: failed to parse Telegram user from initData: {exc}")
    user = upsert_user(auth)
    response.set_cookie("onenode_user", user["id"], httponly=False, samesite="lax")
    flux_klein_config: dict[str, Any] = {"ok": False, "autofill_prompts": {}, "lora_triggers_custom": {}, "t2i_templates": [], "discover_prompts": {}}
    models_payload: dict[str, Any] = {"ok": False}
    bgremoval_payload: dict[str, Any] = {"ok": False, "models": []}
    try:
        flux_klein_config = {"ok": True, **await get_flux_klein_config()}
    except Exception as exc:
        flux_klein_config["error"] = str(exc)
    try:
        models_payload = {"ok": True, **await get_comfyui_models()}
    except Exception as exc:
        models_payload["error"] = str(exc)
    try:
        bgremoval_payload = {"ok": True, **await get_flux_bgremoval_models()}
    except Exception as exc:
        bgremoval_payload["error"] = str(exc)
    return {
        "ok": True,
        "user": user,
        "platform": auth.platform,
        "miniAppUrl": mini_app_url(auth.platform),
        "fluxKleinConfig": flux_klein_config,
        "models": models_payload,
        "bgRemovalModels": bgremoval_payload,
        "features": {
            "web": True,
            "telegramMiniApp": True,
            "maxMiniApp": True,
            "database": DB_PATH.exists(),
            "ruEn": True,
            "modes": ["text_to_image", "image_to_image", "edit", "paint", "faceswap"],
        },
    }


@app.post("/api/app/heartbeat")
async def app_heartbeat(req: HeartbeatRequest) -> dict[str, Any]:
    raw_id = req.userId or ""
    while raw_id:
        stripped = raw_id
        for prefix in ("web_", "telegram_", "max_"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):]
                break
        if stripped == raw_id:
            break
        raw_id = stripped
    user_id = f"{req.platform}_{raw_id}" if raw_id else "demo_user"
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            "UPDATE users SET total_time_seconds = total_time_seconds + ?, last_seen_at = ? WHERE id = ?",
            (req.seconds, now, user_id),
        )
    return {"ok": True, "userId": user_id}


@app.post("/api/auth/web-login")
async def web_login(req: WebLoginRequest, response: Response) -> dict[str, Any]:
    expected = os.getenv("ADMIN_ONE_TIME_CODE", "admin-demo")
    if req.code != expected:
        raise HTTPException(403, "Invalid one-time admin code.")
    auth = MiniAppAuthRequest(platform="web", userId="admin", username="admin", firstName="Admin", language="ru")
    user = upsert_user(auth)
    with db() as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (user["id"],))
    user["role"] = "admin"
    response.set_cookie("onenode_user", user["id"], httponly=False, samesite="lax")
    return {"ok": True, "user": user}


BOOTSTRAP_REQUIRED_CONSENTS = ["terms", "privacy", "personal_data_processing", "cookies"]


def _bootstrap_auth_methods(platform: str) -> list[str]:
    methods: list[str] = []
    if platform == "telegram_mini_app":
        methods.append("telegram")
    elif platform == "max_mini_app":
        methods.append("max")
    # Advertise email OTP only when it can actually be delivered (provider configured,
    # or dev debug). Password login/register is always available and not listed here.
    if email_otp_available():
        methods.append("email_otp")
    return methods


def _bootstrap_storage_type(platform: str) -> str:
    return "server_only" if platform in {"ios_app", "android_app"} else "local_storage"


@app.post("/api/auth/bootstrap-v2")
async def auth_bootstrap_v2(req: BootstrapV2Request) -> dict[str, Any]:
    """Anonymous initialization. NOT a login.

    Never reads X-OneNode-User or the onenode_user cookie, never trusts a
    client-supplied identity, and never creates a user / identity / session.
    The only side effect is an upsert into device_installations.
    """
    now = datetime.now(timezone.utc).isoformat()
    has_installation_id_from_client = bool(req.installation_id)
    has_anonymous_id_from_client = bool(req.anonymous_id)
    installation_id = req.installation_id or uuid.uuid4().hex
    anonymous_id = req.anonymous_id or uuid.uuid4().hex
    metadata = {
        "client": req.client.model_dump() if req.client else {},
        "utm": req.utm.model_dump() if req.utm else {},
    }
    metadata_json = json.dumps(metadata, ensure_ascii=False)
    with db() as conn:
        existing = conn.execute(
            "SELECT anonymous_id FROM device_installations WHERE installation_id = ?",
            (installation_id,),
        ).fetchone()
        if existing:
            # Preserve the original anonymous_id; never overwrite internal/legacy id here.
            if existing["anonymous_id"]:
                anonymous_id = existing["anonymous_id"]
            conn.execute(
                """
                UPDATE device_installations
                SET last_seen_at = ?, platform = ?,
                    anonymous_id = COALESCE(anonymous_id, ?), metadata_json = ?
                WHERE installation_id = ?
                """,
                (now, req.platform, anonymous_id, metadata_json, installation_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO device_installations
                    (id, internal_user_id, legacy_user_id, installation_id, anonymous_id,
                     platform, storage_type, first_seen_at, last_seen_at, metadata_json)
                VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    installation_id,
                    anonymous_id,
                    req.platform,
                    _bootstrap_storage_type(req.platform),
                    now,
                    now,
                    metadata_json,
                ),
            )
    auth_methods = _bootstrap_auth_methods(req.platform)
    required_consents = list(BOOTSTRAP_REQUIRED_CONSENTS)

    # Product analytics: app_opened. Never fails the bootstrap; on error we emit a
    # debug-safe note (no identity, no tokens, no PII) instead of hiding it.
    try:
        record_event_log(
            "app_opened",
            anonymous_id=anonymous_id,
            installation_id=installation_id,
            platform=req.platform,
            properties={
                "auth_methods": auth_methods,
                "required_consents": required_consents,
                "has_installation_id_from_client": has_installation_id_from_client,
                "has_anonymous_id_from_client": has_anonymous_id_from_client,
                "client": req.client.model_dump() if req.client else {},
                "utm": req.utm.model_dump() if req.utm else {},
            },
        )
    except Exception as exc:  # pragma: no cover - defensive; bootstrap must not fail
        print(f"bootstrap-v2: app_opened event log failed: {type(exc).__name__}")

    return {
        "anonymous_id": anonymous_id,
        "installation_id": installation_id,
        "is_authenticated": False,
        "auth_methods": auth_methods,
        "auth_capabilities": auth_capabilities_payload(),
        "required_consents": required_consents,
        "server_time": now,
    }


@app.get("/api/auth/capabilities-v2")
async def auth_capabilities_v2() -> dict[str, Any]:
    return auth_capabilities_payload()


@app.post("/api/auth/bot-login/start")
async def auth_bot_login_start(req: BotLoginStartRequest, request: Request, response: Response) -> dict[str, Any]:
    provider = req.provider
    if not bot_login_available(provider):
        raise HTTPException(503, "provider_not_configured")
    token = generate_bot_login_token()
    nonce = generate_bot_login_token()
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=BOT_LOGIN_CHALLENGE_TTL_SECONDS)).isoformat()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO auth_login_challenges
                (id, provider, token_hash, browser_nonce_hash, status, expires_at,
                 created_at, created_ip, user_agent)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                provider,
                hash_token(token),
                hash_token(nonce),
                expires_at,
                now.isoformat(),
                _client_ip(request),
                _hash_user_agent(request),
            ),
        )
    set_bot_login_cookie(response, provider, nonce)
    return {
        "ok": True,
        "provider": provider,
        "deep_link": bot_login_deep_link(provider, token),
        "poll_interval_ms": 2000,
        "expires_at": expires_at,
    }


@app.get("/api/auth/bot-login/status")
async def auth_bot_login_status(request: Request, response: Response) -> dict[str, Any]:
    parsed = parse_bot_login_cookie(request)
    if not parsed:
        raise HTTPException(401, "bot_login_challenge_missing")
    provider, nonce = parsed
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM auth_login_challenges WHERE provider = ? AND browser_nonce_hash = ?",
            (provider, hash_token(nonce)),
        ).fetchone()
        if not row:
            raise HTTPException(401, "bot_login_challenge_missing")
        if row["status"] == "consumed":
            clear_bot_login_cookie(response)
            raise HTTPException(409, "bot_login_challenge_consumed")
        if row["expires_at"] <= now:
            conn.execute("UPDATE auth_login_challenges SET status = 'expired' WHERE id = ? AND status = 'pending'", (row["id"],))
            clear_bot_login_cookie(response)
            return {"ok": True, "status": "expired"}
        if row["status"] != "approved":
            return {"ok": True, "status": row["status"]}
        internal_user_id = row["internal_user_id"]
        if not internal_user_id:
            raise HTTPException(409, "bot_login_identity_missing")
        user_row = conn.execute("SELECT id FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
        legacy_user_id = user_row["id"] if user_row else None
        conn.execute(
            "UPDATE auth_login_challenges SET status = 'consumed', consumed_at = ? WHERE id = ? AND status = 'approved'",
            (now, row["id"]),
        )

    session = create_auth_session(
        internal_user_id,
        legacy_user_id,
        provider=provider,
        platform=f"{provider}_bot",
        request=request,
    )
    set_trusted_auth_cookies(
        response,
        session["session_token"],
        session["refresh_token"],
        session["expires_at"],
        session["refresh_expires_at"],
    )
    clear_bot_login_cookie(response)
    return {"ok": True, "status": "authenticated"}


@app.post("/api/auth/telegram-v2")
async def auth_telegram_v2(req: TelegramAuthV2Request, request: Request, response: Response) -> dict[str, Any]:
    """Strict Telegram Mini App login: verify raw initData, resolve identity,
    issue a trusted session. Never trusts client identity / X-OneNode-User /
    onenode_user / initDataUnsafe. Raw initData and raw tokens are never logged."""
    platform = "telegram_mini_app"
    now = datetime.now(timezone.utc).isoformat()

    def fail(reason: str, status: int = 401):
        with db() as conn:
            record_security_event(conn, reason, internal_user_id=None, request=request)
            record_login_attempt(conn, "telegram", False, failure_reason=reason, platform=platform, request=request)
        try:
            record_event_log(
                "login_failed",
                anonymous_id=req.anonymous_id,
                installation_id=req.installation_id,
                platform=platform,
                properties={"provider": "telegram", "reason": reason},
            )
        except Exception as exc:  # pragma: no cover - defensive
            print(f"telegram-v2: login_failed event log error: {type(exc).__name__}")
        raise HTTPException(status, reason)

    if not req.init_data:
        fail("telegram_init_data_missing")

    try:
        data = validate_telegram_init_data_strict(req.init_data)
    except TelegramAuthError as exc:
        fail(exc.reason)
    user = data["_user"]

    with db() as conn:
        internal_user_id, legacy_user_id = telegram_upsert_identity(conn, user, now)

    session = create_auth_session(
        internal_user_id, legacy_user_id, provider="telegram", platform=platform, request=request
    )

    with db() as conn:
        if req.installation_id:
            existing = conn.execute(
                "SELECT id FROM device_installations WHERE installation_id = ?", (req.installation_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE device_installations SET internal_user_id = ?, legacy_user_id = ?, last_seen_at = ? WHERE installation_id = ?",
                    (internal_user_id, legacy_user_id, now, req.installation_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO device_installations
                        (id, internal_user_id, legacy_user_id, installation_id, anonymous_id, platform, storage_type, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (uuid.uuid4().hex, internal_user_id, legacy_user_id, req.installation_id, req.anonymous_id, platform, "local_storage", now, now),
                )
        record_login_attempt(
            conn, "telegram", True, identifier=str(user["id"]), internal_user_id=internal_user_id, platform=platform, request=request
        )

    try:
        record_event_log(
            "login_succeeded",
            internal_user_id=internal_user_id,
            legacy_user_id=legacy_user_id,
            anonymous_id=req.anonymous_id,
            installation_id=req.installation_id,
            session_id=session["session_id"],
            platform=platform,
            properties={"provider": "telegram", "telegram_user_id": str(user["id"])},
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"telegram-v2: login_succeeded event log error: {type(exc).__name__}")

    # Phase 13: trusted session is delivered via HttpOnly cookies. Tokens remain in
    # JSON for backward compat; the Phase 13 frontend ignores them.
    set_trusted_auth_cookies(
        response, session["session_token"], session["refresh_token"],
        session["expires_at"], session["refresh_expires_at"],
    )
    return {
        "internal_user_id": internal_user_id,
        "legacy_user_id": legacy_user_id,
        "session_token": session["session_token"],
        "refresh_token": session["refresh_token"],
        "expires_at": session["expires_at"],
        "refresh_expires_at": session["refresh_expires_at"],
        "profile_completed": False,
        "required_consents": [],
    }


@app.post("/api/auth/max-v2")
async def auth_max_v2(req: MaxAuthV2Request, request: Request, response: Response) -> dict[str, Any]:
    """Strict MAX Mini App login: verify raw WebAppData, resolve identity, issue a
    trusted session. Never trusts client identity / X-OneNode-User / onenode_user.
    Raw WebAppData and raw tokens are never logged."""
    platform = "max_mini_app"
    now = datetime.now(timezone.utc).isoformat()

    def fail(reason: str, status: int = 401):
        with db() as conn:
            record_security_event(conn, reason, internal_user_id=None, request=request)
            record_login_attempt(conn, "max", False, failure_reason=reason, platform=platform, request=request)
        try:
            record_event_log(
                "login_failed",
                anonymous_id=req.anonymous_id,
                installation_id=req.installation_id,
                platform=platform,
                properties={"provider": "max", "reason": reason},
            )
        except Exception as exc:  # pragma: no cover - defensive
            print(f"max-v2: login_failed event log error: {type(exc).__name__}")
        raise HTTPException(status, reason)

    if not req.web_app_data:
        fail("max_web_app_data_missing")

    try:
        data = validate_max_web_app_data_strict(req.web_app_data)
    except MaxAuthError as exc:
        fail(exc.reason)
    user = data["_user"]

    with db() as conn:
        internal_user_id, legacy_user_id = max_upsert_identity(conn, user, now)

    session = create_auth_session(
        internal_user_id, legacy_user_id, provider="max", platform=platform, request=request
    )

    with db() as conn:
        if req.installation_id:
            existing = conn.execute(
                "SELECT id FROM device_installations WHERE installation_id = ?", (req.installation_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE device_installations SET internal_user_id = ?, legacy_user_id = ?, last_seen_at = ? WHERE installation_id = ?",
                    (internal_user_id, legacy_user_id, now, req.installation_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO device_installations
                        (id, internal_user_id, legacy_user_id, installation_id, anonymous_id, platform, storage_type, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (uuid.uuid4().hex, internal_user_id, legacy_user_id, req.installation_id, req.anonymous_id, platform, "local_storage", now, now),
                )
        record_login_attempt(
            conn, "max", True, identifier=str(user["id"]), internal_user_id=internal_user_id, platform=platform, request=request
        )

    try:
        record_event_log(
            "login_succeeded",
            internal_user_id=internal_user_id,
            legacy_user_id=legacy_user_id,
            anonymous_id=req.anonymous_id,
            installation_id=req.installation_id,
            session_id=session["session_id"],
            platform=platform,
            properties={"provider": "max", "max_user_id": str(user["id"])},
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"max-v2: login_succeeded event log error: {type(exc).__name__}")

    set_trusted_auth_cookies(
        response, session["session_token"], session["refresh_token"],
        session["expires_at"], session["refresh_expires_at"],
    )
    return {
        "internal_user_id": internal_user_id,
        "legacy_user_id": legacy_user_id,
        "session_token": session["session_token"],
        "refresh_token": session["refresh_token"],
        "expires_at": session["expires_at"],
        "refresh_expires_at": session["refresh_expires_at"],
        "profile_completed": False,
        "required_consents": [],
    }


@app.post("/api/auth/email/request-code-v2")
async def auth_email_request_code_v2(req: EmailRequestCodeV2Request, request: Request) -> dict[str, Any]:
    """Issue an email OTP challenge. Same response shape whether or not the email
    already has an account (no user-existence disclosure). Stores only the OTP
    hash; never logs or returns the raw OTP (except debug_code in non-production
    when explicitly enabled). No real email is sent in dev/test."""
    try:
        validate_email_otp_config()
    except RuntimeError:
        # Safe, generic error — no fake email, no challenge created.
        raise HTTPException(503, "Email login is currently unavailable.")

    email_norm = normalize_email(req.email)
    if not email_norm:
        raise HTTPException(400, "A valid email address is required.")

    # Opportunistic cleanup of stale challenges, then abuse controls. Both run
    # AFTER normalization and never reveal whether the email exists.
    cleanup_expired_otp_challenges()
    enforce_email_otp_rate_limits(email_norm, request, req.anonymous_id, req.installation_id, req.platform)

    now = datetime.now(timezone.utc).isoformat()
    challenge_id = uuid.uuid4().hex
    code = generate_otp_code(EMAIL_OTP_LENGTH)
    code_hash = hash_otp(code)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=EMAIL_OTP_TTL_SECONDS)).isoformat()

    with db() as conn:
        conn.execute(
            """
            INSERT INTO auth_otp_challenges
                (id, channel, destination, code_hash, purpose, attempts_count, max_attempts,
                 expires_at, consumed_at, ip_address, user_agent_hash, created_at)
            VALUES (?, 'email', ?, ?, 'login', 0, ?, ?, NULL, ?, ?, ?)
            """,
            (challenge_id, email_norm, code_hash, EMAIL_OTP_MAX_ATTEMPTS, expires_at,
             _client_ip(request), _hash_user_agent(request), now),
        )

    # Deliver via mock (dev/test) — never includes the code in any log.
    send_email_otp(email_norm, code)

    try:
        record_event_log(
            "login_started",
            anonymous_id=req.anonymous_id,
            installation_id=req.installation_id,
            platform=req.platform,
            properties={"provider": "web_email", "challenge_id": challenge_id},
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"email-otp: login_started event log error: {type(exc).__name__}")

    response: dict[str, Any] = {"challenge_id": challenge_id, "expires_in_seconds": EMAIL_OTP_TTL_SECONDS}
    if EMAIL_OTP_DEBUG_RETURN_CODE and APP_ENV.lower() != "production":
        response["debug_code"] = code
    return response


@app.post("/api/auth/email/verify-code-v2")
async def auth_email_verify_code_v2(req: EmailVerifyCodeV2Request, request: Request, response: Response) -> dict[str, Any]:
    """Verify an email OTP and issue a trusted session. Never trusts client
    identity / X-OneNode-User / onenode_user. Raw OTP and raw tokens are never
    stored or logged."""
    platform = req.platform
    now = datetime.now(timezone.utc).isoformat()
    now_iso = now

    def fail(reason: str, status: int = 401, internal_user_id: str | None = None):
        with db() as conn:
            record_security_event(conn, reason, internal_user_id=internal_user_id, request=request)
            record_login_attempt(conn, "web_email", False, failure_reason=reason, internal_user_id=internal_user_id, platform=platform, request=request)
        try:
            record_event_log(
                "login_failed",
                anonymous_id=req.anonymous_id,
                installation_id=req.installation_id,
                platform=platform,
                properties={"provider": "web_email", "reason": reason},
            )
        except Exception as exc:  # pragma: no cover - defensive
            print(f"email-otp: login_failed event log error: {type(exc).__name__}")
        raise HTTPException(status, reason)

    if not req.challenge_id or not req.code:
        fail("otp_challenge_missing")

    with db() as conn:
        ch = conn.execute("SELECT * FROM auth_otp_challenges WHERE id = ?", (req.challenge_id,)).fetchone()
    if ch is None:
        fail("otp_challenge_missing")
    if ch["consumed_at"] is not None:
        fail("otp_consumed")
    if ch["expires_at"] < now_iso:
        fail("otp_expired")
    if int(ch["attempts_count"]) >= int(ch["max_attempts"]):
        fail("otp_max_attempts", status=429)

    if not hmac.compare_digest(hash_otp(req.code), ch["code_hash"]):
        with db() as conn:
            conn.execute("UPDATE auth_otp_challenges SET attempts_count = attempts_count + 1 WHERE id = ?", (req.challenge_id,))
        fail("otp_failed")

    email_norm = ch["destination"]
    with db() as conn:
        conn.execute("UPDATE auth_otp_challenges SET consumed_at = ? WHERE id = ?", (now, req.challenge_id))
        internal_user_id, legacy_user_id = email_otp_upsert_identity(conn, email_norm, now)
        # Mark the email as verified (idempotent). The trusted session below is the
        # real access gate; this records the confirmation timestamp for the account.
        conn.execute(
            "UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?) WHERE internal_user_id = ?",
            (now, internal_user_id),
        )

    session = create_auth_session(
        internal_user_id, legacy_user_id, provider="web_email", platform=platform, request=request
    )

    with db() as conn:
        if req.installation_id:
            existing = conn.execute(
                "SELECT id FROM device_installations WHERE installation_id = ?", (req.installation_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE device_installations SET internal_user_id = ?, legacy_user_id = ?, last_seen_at = ? WHERE installation_id = ?",
                    (internal_user_id, legacy_user_id, now, req.installation_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO device_installations
                        (id, internal_user_id, legacy_user_id, installation_id, anonymous_id, platform, storage_type, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (uuid.uuid4().hex, internal_user_id, legacy_user_id, req.installation_id, req.anonymous_id, platform, "local_storage", now, now),
                )
        record_login_attempt(conn, "web_email", True, identifier=email_norm, internal_user_id=internal_user_id, platform=platform, request=request)

    try:
        record_event_log(
            "login_succeeded",
            internal_user_id=internal_user_id,
            legacy_user_id=legacy_user_id,
            anonymous_id=req.anonymous_id,
            installation_id=req.installation_id,
            session_id=session["session_id"],
            platform=platform,
            properties={"provider": "web_email"},
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"email-otp: login_succeeded event log error: {type(exc).__name__}")

    set_trusted_auth_cookies(
        response, session["session_token"], session["refresh_token"],
        session["expires_at"], session["refresh_expires_at"],
    )
    return {
        "internal_user_id": internal_user_id,
        "legacy_user_id": legacy_user_id,
        "session_token": session["session_token"],
        "refresh_token": session["refresh_token"],
        "expires_at": session["expires_at"],
        "refresh_expires_at": session["refresh_expires_at"],
        "profile_completed": False,
        "required_consents": [],
    }


@app.post("/api/auth/password/register-v2")
async def auth_password_register_v2(req: PasswordRegisterV2Request, request: Request, response: Response) -> dict[str, Any]:
    """Browser email+password registration. Creates/attaches a web_email identity +
    Argon2id password, and records consents. If email verification is available,
    no trusted session is issued until verify-code-v2 succeeds; in non-production
    no-provider/dev flows, a trusted cookie session may still be issued. Never
    stores/logs the raw password. Generic 409 if an account already has a password."""
    platform = "web"
    email_norm = normalize_email(req.email)
    if not email_norm:
        raise HTTPException(400, "Введите корректный email.")
    if validate_password_policy(req.password):
        raise HTTPException(400, "Пароль должен быть от 8 до 128 символов.")
    if req.password != req.password_repeat:
        raise HTTPException(400, "Пароли не совпадают.")
    if not (req.accepted_terms and req.accepted_privacy and req.accepted_personal_data):
        raise HTTPException(400, "Необходимо принять условия.")
    if is_production_like_env() and not email_provider_configured():
        raise HTTPException(503, "email_provider_required")

    password_hash = hash_password_argon2(req.password)  # CPU work outside the txn
    now = datetime.now(timezone.utc).isoformat()

    with db() as conn:
        existing = conn.execute(
            "SELECT internal_user_id FROM auth_identities WHERE provider = 'web_email' AND provider_user_id = ?",
            (email_norm,),
        ).fetchone()
        if existing:
            iuid = existing["internal_user_id"]
            # Check if linked user exists (separate connection so log survives rollback)
            urow = conn.execute("SELECT banned FROM users WHERE internal_user_id = ?", (iuid,)).fetchone()
            if urow is None:
                try:
                    with db() as log_conn:
                        record_security_event(log_conn, "password_register_orphan_identity", severity="warning", internal_user_id=iuid, request=request)
                except Exception:
                    pass
                raise HTTPException(409, "Аккаунт уже существует или данные некорректны.")
            if urow["banned"]:
                raise HTTPException(409, "Аккаунт уже существует или данные некорректны.")
            active = conn.execute(
                "SELECT 1 FROM auth_passwords WHERE internal_user_id = ? AND disabled_at IS NULL",
                (iuid,),
            ).fetchone()
            if active:
                raise HTTPException(409, "Аккаунт уже существует или данные некорректны.")
            # Identity + user exist, but no active password — attach password to existing user
            internal_user_id = iuid
            legacy_user_id = conn.execute("SELECT id FROM users WHERE internal_user_id = ?", (iuid,)).fetchone()["id"]
        else:
            internal_user_id, legacy_user_id = email_otp_upsert_identity(conn, email_norm, now)
        conn.execute(
            """
            INSERT INTO auth_passwords
                (id, internal_user_id, password_hash, algorithm, created_at, updated_at, password_updated_at)
            VALUES (?, ?, ?, 'argon2id', ?, ?, ?)
            """,
            (uuid.uuid4().hex, internal_user_id, password_hash, now, now, now),
        )
        for consent_type in ("terms", "privacy", "personal_data_processing"):
            conn.execute(
                """
                INSERT INTO user_consents
                    (id, internal_user_id, consent_type, document_version, accepted, accepted_at,
                     ip_address, user_agent_hash, platform)
                VALUES (?, ?, ?, 'v1', 1, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, internal_user_id, consent_type, now, _client_ip(request), _hash_user_agent(request), platform),
            )
        record_login_attempt(conn, "web_email", True, identifier=email_norm, internal_user_id=internal_user_id, platform=platform, request=request)

    # Email verification gate. When email OTP is actually deliverable we do NOT issue a
    # trusted session here — the account+password exist, but login is unlocked only after
    # the user confirms the email via request-code-v2 / verify-code-v2 (which then creates
    # the trusted session). Without a usable email channel we keep the legacy behavior
    # (immediate session) so non-email environments are not locked out.
    if email_otp_available():
        try:
            record_event_log("password_register_pending_verification", internal_user_id=internal_user_id,
                              legacy_user_id=legacy_user_id, platform=platform, properties={"provider": "web_email"})
        except Exception as exc:  # pragma: no cover - defensive
            print(f"password-register: event log error: {type(exc).__name__}")
        return {"ok": True, "requires_email_verification": True, "internal_user_id": internal_user_id,
                "legacy_user_id": legacy_user_id, "profile_completed": False}

    session = create_auth_session(internal_user_id, legacy_user_id, provider="web_email", platform=platform, request=request)
    set_trusted_auth_cookies(response, session["session_token"], session["refresh_token"], session["expires_at"], session["refresh_expires_at"])
    try:
        record_event_log("password_register_succeeded", internal_user_id=internal_user_id, legacy_user_id=legacy_user_id,
                          session_id=session["session_id"], platform=platform, properties={"provider": "web_email"})
    except Exception as exc:  # pragma: no cover - defensive
        print(f"password-register: event log error: {type(exc).__name__}")
    return {"ok": True, "requires_email_verification": False, "internal_user_id": internal_user_id, "legacy_user_id": legacy_user_id, "profile_completed": False}


@app.post("/api/auth/password/login-v2")
async def auth_password_login_v2(req: PasswordLoginV2Request, request: Request, response: Response) -> dict[str, Any]:
    """Browser email+password login. Generic 401 for any bad email/password (no
    account enumeration); 403 for banned. Issues a trusted cookie session on success.
    Never stores/logs the raw password."""
    platform = "web"
    email_norm = normalize_email(req.email)

    def fail_invalid():
        with db() as conn:
            record_security_event(conn, "password_login_failed", request=request)
            record_login_attempt(conn, "web_email", False, failure_reason="invalid_credentials",
                                 identifier=email_norm, platform=platform, request=request)
        try:
            record_event_log("password_login_failed", platform=platform, properties={"provider": "web_email"})
        except Exception as exc:  # pragma: no cover - defensive
            print(f"password-login: failed event log error: {type(exc).__name__}")
        raise HTTPException(401, "Неверная почта или пароль.")

    # Look up identity + active password (if any). Always run a verify to equalize timing.
    internal_user_id: str | None = None
    legacy_user_id: str | None = None
    stored_hash = _DUMMY_PASSWORD_HASH
    user_missing = False
    user_banned = False
    email_verified_at: str | None = None
    if email_norm:
        with db() as conn:
            ident = conn.execute(
                "SELECT internal_user_id, legacy_user_id FROM auth_identities WHERE provider = 'web_email' AND provider_user_id = ?",
                (email_norm,),
            ).fetchone()
            if ident:
                internal_user_id = ident["internal_user_id"]
                legacy_user_id = ident["legacy_user_id"]
                urow = conn.execute("SELECT banned, email_verified_at FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
                if urow is None:
                    user_missing = True
                    try:
                        record_security_event(conn, "password_login_orphan_identity", severity="warning", internal_user_id=internal_user_id, request=request)
                    except Exception:
                        pass
                else:
                    if urow["banned"]:
                        user_banned = True
                    email_verified_at = urow["email_verified_at"]
                    # Always try to fetch password hash for timing equalization
                    pw = conn.execute(
                        "SELECT password_hash FROM auth_passwords WHERE internal_user_id = ? AND disabled_at IS NULL",
                        (internal_user_id,),
                    ).fetchone()
                    if pw:
                        stored_hash = pw["password_hash"]

    valid = verify_password_argon2(req.password, stored_hash)
    if not valid or internal_user_id is None or stored_hash is _DUMMY_PASSWORD_HASH or user_missing:
        fail_invalid()

    with db() as conn:
        if user_banned or _user_is_banned(conn, internal_user_id, legacy_user_id):
            record_security_event(conn, "password_login_banned", severity="critical", internal_user_id=internal_user_id, request=request)
            raise HTTPException(403, "Вход недоступен.")
        if email_otp_available() and not email_verified_at:
            record_login_attempt(conn, "web_email", False, failure_reason="email_verification_required",
                                 identifier=email_norm, internal_user_id=internal_user_id, platform=platform, request=request)
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "email_verification_required",
                    "requires_email_verification": True,
                    "email": email_norm,
                },
            )
        record_login_attempt(conn, "web_email", True, identifier=email_norm, internal_user_id=internal_user_id, platform=platform, request=request)

    session = create_auth_session(internal_user_id, legacy_user_id, provider="web_email", platform=platform, request=request)
    set_trusted_auth_cookies(response, session["session_token"], session["refresh_token"], session["expires_at"], session["refresh_expires_at"])
    try:
        record_event_log("password_login_succeeded", internal_user_id=internal_user_id, legacy_user_id=legacy_user_id,
                          session_id=session["session_id"], platform=platform, properties={"provider": "web_email"})
    except Exception as exc:  # pragma: no cover - defensive
        print(f"password-login: event log error: {type(exc).__name__}")
    return {"ok": True, "internal_user_id": internal_user_id, "legacy_user_id": legacy_user_id, "profile_completed": False}


@app.get("/api/me-v2")
async def me_v2(request: Request) -> dict[str, Any]:
    """Current user, resolved strictly from the trusted session. Exposes no token
    hashes, no OTP/code hashes, no raw tokens, and no full raw_profile_json."""
    user = require_trusted_user(request)
    iuid = user["internal_user_id"]
    legacy = user["legacy_user_id"]
    with db() as conn:
        sess = conn.execute(
            "SELECT provider, platform, expires_at, refresh_expires_at FROM auth_sessions WHERE id = ?",
            (user["session_id"],),
        ).fetchone()
        urow = conn.execute("SELECT * FROM users WHERE internal_user_id = ?", (iuid,)).fetchone()
        if urow is None and legacy:
            urow = conn.execute("SELECT * FROM users WHERE id = ?", (legacy,)).fetchone()
        identities = conn.execute(
            "SELECT provider, provider_username, provider_email, linked_at, last_login_at FROM auth_identities WHERE internal_user_id = ?",
            (iuid,),
        ).fetchall()
        gallery_access = bool(user_gallery_allowed(conn, iuid, legacy))
        gallery_quota = gallery_quota_for_user(conn, urow, legacy)

    primary_identity = identities[0] if identities else None
    profile = {
        "display_name": resolve_display_name(urow, primary_identity),
        "public_user_code": _row_get(urow, "public_user_code"),
        "first_name": _row_get(urow, "first_name"),
        "last_name": _row_get(urow, "last_name"),
        "username": _row_get(urow, "username"),
        "email": _row_get(urow, "email"),
        "language_code": _row_get(urow, "language"),
        "avatar_url": _row_get(urow, "avatar_url"),
        "avatar_preset": _row_get(urow, "avatar_preset"),
        "providers": sorted({i["provider"] for i in identities}),
    }

    try:
        record_event_log(
            "me_opened",
            internal_user_id=iuid,
            legacy_user_id=legacy,
            session_id=user["session_id"],
            platform=user["platform"],
            properties={"provider": user["provider"]},
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"me-v2: me_opened event log error: {type(exc).__name__}")

    return {
        "internal_user_id": iuid,
        "legacy_user_id": legacy,
        "status": "active",
        "account": {
            "role": _row_get(urow, "role"),
            "plan": _row_get(urow, "plan") or "mini",
            "token_balance": int(_row_get(urow, "token_balance") or 0),
            "daily_tokens_used": int(_row_get(urow, "daily_tokens_used") or 0),
            "daily_tokens_limit": gallery_quota["daily_tokens"],
            "gallery_enabled": bool(_row_get(urow, "gallery_enabled")),
            "gallery_access": gallery_access,
            "daily_tokens": gallery_quota["daily_tokens"],
            "gallery_slots": gallery_quota["gallery_slots"],
            "gallery_used": gallery_quota["gallery_used"],
            "gallery_free": gallery_quota["gallery_free"],
            "gallery_full": gallery_quota["gallery_full"],
        },
        "session": {
            "session_id": user["session_id"],
            "provider": _row_get(sess, "provider") or user["provider"],
            "platform": _row_get(sess, "platform") or user["platform"],
            "expires_at": _row_get(sess, "expires_at"),
            "refresh_expires_at": _row_get(sess, "refresh_expires_at"),
        },
        "identities": [
            {
                "provider": r["provider"],
                "provider_username": r["provider_username"],
                "provider_email": r["provider_email"],
                "linked_at": r["linked_at"],
                "last_login_at": r["last_login_at"],
            }
            for r in identities
        ],
        "profile": profile,
        "created_at": _row_get(urow, "created_at"),
        "last_seen_at": _row_get(urow, "last_seen_at"),
    }


@app.get("/api/auth/whoami-v2")
async def whoami_v2(request: Request) -> dict[str, Any]:
    """Minimal diagnostic: the trusted identity only, no profile/token data."""
    user = require_trusted_user(request)
    return {
        "internal_user_id": user["internal_user_id"],
        "legacy_user_id": user["legacy_user_id"],
        "session_id": user["session_id"],
        "provider": user["provider"],
        "platform": user["platform"],
    }


@app.get("/api/me/profile-v2")
async def me_profile_v2(request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    iuid = user["internal_user_id"]
    legacy = user["legacy_user_id"]
    with db() as conn:
        urow = conn.execute("SELECT * FROM users WHERE internal_user_id = ?", (iuid,)).fetchone()
        if urow is None and legacy:
            urow = conn.execute("SELECT * FROM users WHERE id = ?", (legacy,)).fetchone()
        identities = conn.execute(
            "SELECT provider, provider_username, provider_email, linked_at, last_login_at FROM auth_identities WHERE internal_user_id = ?",
            (iuid,),
        ).fetchall()
    return {
        "internal_user_id": iuid,
        "legacy_user_id": legacy,
        "profile": build_profile(urow),
        "identities": [
            {
                "provider": r["provider"],
                "provider_username": r["provider_username"],
                "provider_email": r["provider_email"],
                "linked_at": r["linked_at"],
                "last_login_at": r["last_login_at"],
            }
            for r in identities
        ],
    }


@app.patch("/api/me/profile-v2")
async def me_profile_update_v2(req: ProfileUpdateV2Request, request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    iuid = user["internal_user_id"]
    legacy = user["legacy_user_id"]
    provided = req.model_dump(exclude_unset=True)  # only fields the client actually sent

    with db() as conn:
        user_columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        set_cols: list[str] = []
        values: list[Any] = []
        for api_field, value in provided.items():
            col = PROFILE_FIELD_COLUMNS.get(api_field)
            if not col or col not in user_columns:
                continue  # unsupported field is ignored, never an injection vector
            if isinstance(value, str):
                value = value.strip()[:PROFILE_FIELD_MAX_LEN]
            if api_field in {"avatar_url", "avatar_preset"}:
                avatar_url, avatar_preset = validate_avatar_choice(
                    provided.get("avatar_url"), provided.get("avatar_preset")
                )
                value = avatar_url if api_field == "avatar_url" else avatar_preset
            set_cols.append(f"{col} = ?")
            values.append(value)
        if provided.get("avatar_preset") and "avatar_url" not in provided and "avatar_url" in user_columns:
            avatar_url, _avatar_preset = validate_avatar_choice(None, provided.get("avatar_preset"))
            set_cols.append("avatar_url = ?")
            values.append(avatar_url)
        if set_cols:
            # Scoped to the trusted user's internal_user_id — id/role/banned untouched.
            conn.execute(
                f"UPDATE users SET {', '.join(set_cols)} WHERE internal_user_id = ?",
                (*values, iuid),
            )
        urow = conn.execute("SELECT * FROM users WHERE internal_user_id = ?", (iuid,)).fetchone()
        if urow is None and legacy:
            urow = conn.execute("SELECT * FROM users WHERE id = ?", (legacy,)).fetchone()

    updated_fields = sorted(k for k in provided if PROFILE_FIELD_COLUMNS.get(k) in user_columns)
    try:
        record_event_log(
            "profile_updated",
            internal_user_id=iuid,
            legacy_user_id=legacy,
            session_id=user["session_id"],
            platform=user["platform"],
            properties={"fields": updated_fields},
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"profile-v2: profile_updated event log error: {type(exc).__name__}")

    return {"internal_user_id": iuid, "legacy_user_id": legacy, "profile": build_profile(urow)}


@app.post("/api/me/avatar-upload-v2")
async def me_avatar_upload_v2(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    user = require_trusted_user(request)
    iuid = user["internal_user_id"]
    legacy = user["legacy_user_id"]
    content_type = (file.content_type or "").lower()
    suffix = AVATAR_ALLOWED_CONTENT_TYPES.get(content_type)
    if not suffix:
        raise HTTPException(400, "Avatar must be PNG, JPEG or WEBP.")
    data = await file.read(AVATAR_MAX_BYTES + 1)
    if len(data) > AVATAR_MAX_BYTES:
        raise HTTPException(413, "Avatar file is too large.")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
    except Exception:
        raise HTTPException(400, "Avatar file is not a valid image.")

    filename = f"{iuid}-{uuid.uuid4().hex[:12]}{suffix}"
    dest = AVATAR_DIR / filename
    dest.write_bytes(data)
    avatar_url = f"/media/avatars/{filename}"
    with db() as conn:
        conn.execute(
            "UPDATE users SET avatar_url = ?, avatar_preset = NULL WHERE internal_user_id = ?",
            (avatar_url, iuid),
        )
        urow = conn.execute("SELECT * FROM users WHERE internal_user_id = ?", (iuid,)).fetchone()
    try:
        record_event_log(
            "avatar_uploaded",
            internal_user_id=iuid,
            legacy_user_id=legacy,
            session_id=user["session_id"],
            platform=user["platform"],
            properties={"content_type": content_type},
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"avatar-upload-v2: event log error: {type(exc).__name__}")
    return {"ok": True, "avatar_url": avatar_url, "profile": build_profile(urow)}


@app.get("/api/me/devices-v2")
async def me_devices_v2(request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    with db() as conn:
        rows = conn.execute(
            "SELECT installation_id, platform, storage_type, first_seen_at, last_seen_at, metadata_json "
            "FROM device_installations WHERE internal_user_id = ? ORDER BY last_seen_at DESC",
            (user["internal_user_id"],),
        ).fetchall()
    return {
        "items": [
            {
                "installation_id": r["installation_id"],
                "platform": r["platform"],
                "storage_type": r["storage_type"],
                "first_seen_at": r["first_seen_at"],
                "last_seen_at": r["last_seen_at"],
                "metadata": sanitize_device_metadata(r["metadata_json"]),
            }
            for r in rows
        ]
    }


@app.get("/api/me/sessions-v2")
async def me_sessions_v2(request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    current_session_id = user["session_id"]
    with db() as conn:
        rows = conn.execute(
            "SELECT id, provider, platform, created_at, last_seen_at, expires_at, refresh_expires_at, revoked_at, revoke_reason "
            "FROM auth_sessions WHERE internal_user_id = ? ORDER BY created_at DESC",
            (user["internal_user_id"],),
        ).fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "provider": r["provider"],
                "platform": r["platform"],
                "created_at": r["created_at"],
                "last_seen_at": r["last_seen_at"],
                "expires_at": r["expires_at"],
                "refresh_expires_at": r["refresh_expires_at"],
                "revoked_at": r["revoked_at"],
                "revoke_reason": r["revoke_reason"],
                "is_current": r["id"] == current_session_id,
            }
            for r in rows
        ]
    }


@app.get("/api/me/consents-v2")
async def me_consents_v2(request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    with db() as conn:
        rows = conn.execute(
            "SELECT consent_type, document_version, accepted, accepted_at, revoked_at FROM user_consents "
            "WHERE internal_user_id = ? ORDER BY accepted_at DESC",
            (user["internal_user_id"],),
        ).fetchall()
    return {
        "items": [
            {
                "consent_type": r["consent_type"],
                "document_version": r["document_version"],
                "accepted": bool(r["accepted"]),
                "accepted_at": r["accepted_at"],
                "revoked_at": r["revoked_at"],
            }
            for r in rows
        ]
    }


@app.post("/api/me/consents-v2")
async def me_consents_create_v2(req: ConsentV2Request, request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    consent_type = (req.consent_type or "").strip()
    document_version = (req.document_version or "").strip()
    if consent_type not in CONSENT_TYPES:
        raise HTTPException(400, "Unsupported consent_type.")
    if not document_version:
        raise HTTPException(400, "document_version is required.")

    now = datetime.now(timezone.utc).isoformat()
    accepted = bool(req.accepted)
    revoked_at = None if accepted else now
    with db() as conn:
        # Always append a new historical row; never overwrite prior consents.
        conn.execute(
            """
            INSERT INTO user_consents
                (id, internal_user_id, consent_type, document_version, accepted, accepted_at, revoked_at,
                 ip_address, user_agent_hash, platform)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex, user["internal_user_id"], consent_type, document_version,
                1 if accepted else 0, now, revoked_at,
                _client_ip(request), _hash_user_agent(request), user["platform"],
            ),
        )

    try:
        record_event_log(
            "consent_accepted" if accepted else "consent_revoked",
            internal_user_id=user["internal_user_id"],
            legacy_user_id=user["legacy_user_id"],
            session_id=user["session_id"],
            platform=user["platform"],
            properties={"consent_type": consent_type, "document_version": document_version},
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"consents-v2: consent event log error: {type(exc).__name__}")

    return {
        "consent_type": consent_type,
        "document_version": document_version,
        "accepted": accepted,
        "accepted_at": now,
        "revoked_at": revoked_at,
    }


@app.get("/api/admin/users-v2")
async def admin_users_v2(
    request: Request,
    status: str | None = None,
    provider: str | None = None,
    platform: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    require_trusted_admin(request)
    limit = _clamp_limit(limit)
    offset = max(0, int(offset))
    now_iso = datetime.now(timezone.utc).isoformat()

    clauses: list[str] = ["u.internal_user_id IS NOT NULL"]
    params: list[Any] = []
    if status == "banned":
        clauses.append("u.banned = 1")
    elif status == "active":
        clauses.append("u.banned = 0")
    if provider:
        clauses.append("EXISTS (SELECT 1 FROM auth_identities ai WHERE ai.internal_user_id = u.internal_user_id AND ai.provider = ?)")
        params.append(provider)
    if platform:
        clauses.append("EXISTS (SELECT 1 FROM auth_sessions s WHERE s.internal_user_id = u.internal_user_id AND s.platform = ?)")
        params.append(platform)
    if q:
        like = f"%{q}%"
        clauses.append(
            "(u.id LIKE ? OR u.internal_user_id LIKE ? OR EXISTS (SELECT 1 FROM auth_identities ai2 "
            "WHERE ai2.internal_user_id = u.internal_user_id AND (ai2.provider_username LIKE ? OR ai2.provider_email LIKE ?)))"
        )
        params += [like, like, like, like]
    where = "WHERE " + " AND ".join(clauses)

    items: list[dict[str, Any]] = []
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM users u {where}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM users u {where} ORDER BY u.last_seen_at DESC, u.created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        for row in rows:
            iuid = row["internal_user_id"]
            providers = [r["provider"] for r in conn.execute("SELECT DISTINCT provider FROM auth_identities WHERE internal_user_id = ?", (iuid,))]
            active_sessions = conn.execute(
                "SELECT COUNT(*) AS c FROM auth_sessions WHERE internal_user_id = ? AND revoked_at IS NULL AND expires_at > ?",
                (iuid, now_iso),
            ).fetchone()["c"]
            last_session = conn.execute(
                "SELECT provider, platform FROM auth_sessions WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 1",
                (iuid,),
            ).fetchone()
            summary = admin_user_summary(row)
            summary.update({
                "providers": providers,
                "active_sessions_count": active_sessions,
                "last_provider": _row_get(last_session, "provider"),
                "last_platform": _row_get(last_session, "platform"),
            })
            items.append(summary)
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@app.get("/api/admin/users/{internal_user_id}/v2")
async def admin_user_detail_v2(internal_user_id: str, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    with db() as conn:
        urow = conn.execute("SELECT * FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
        if urow is None:
            raise HTTPException(404, "User not found.")
        identities = conn.execute(
            "SELECT provider, provider_user_id, provider_username, provider_email, linked_at, last_login_at, verified_at "
            "FROM auth_identities WHERE internal_user_id = ?",
            (internal_user_id,),
        ).fetchall()
        sessions = conn.execute(
            "SELECT id, provider, platform, created_at, last_seen_at, expires_at, refresh_expires_at, revoked_at, revoke_reason "
            "FROM auth_sessions WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 50",
            (internal_user_id,),
        ).fetchall()
        sec_events = conn.execute(
            "SELECT id, severity, event_type, ip_address, details_json, created_at FROM security_events "
            "WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 20",
            (internal_user_id,),
        ).fetchall()
        evt_logs = conn.execute(
            "SELECT id, event_name, platform, properties_json, created_at FROM event_logs "
            "WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 20",
            (internal_user_id,),
        ).fetchall()

    return {
        "user": admin_user_summary(urow),
        "identities": [
            {
                "provider": r["provider"],
                "provider_user_id": r["provider_user_id"],
                "provider_username": r["provider_username"],
                "provider_email": mask_email(r["provider_email"]),
                "linked_at": r["linked_at"],
                "last_login_at": r["last_login_at"],
                "verified_at": r["verified_at"],
            }
            for r in identities
        ],
        "sessions": [
            {
                "id": r["id"],
                "provider": r["provider"],
                "platform": r["platform"],
                "created_at": r["created_at"],
                "last_seen_at": r["last_seen_at"],
                "expires_at": r["expires_at"],
                "refresh_expires_at": r["refresh_expires_at"],
                "revoked_at": r["revoked_at"],
                "revoke_reason": r["revoke_reason"],
            }
            for r in sessions
        ],
        "recent_security_events": [
            {
                "id": r["id"],
                "severity": r["severity"],
                "event_type": r["event_type"],
                "ip_address": r["ip_address"],
                "details": safe_json_load(r["details_json"]),
                "created_at": r["created_at"],
            }
            for r in sec_events
        ],
        "recent_event_logs": [
            {
                "id": r["id"],
                "event_name": r["event_name"],
                "platform": r["platform"],
                "properties": safe_json_load(r["properties_json"]),
                "created_at": r["created_at"],
            }
            for r in evt_logs
        ],
    }


@app.get("/api/admin/security-events-v2")
async def admin_security_events_v2(
    request: Request,
    event_type: str | None = None,
    internal_user_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    require_trusted_admin(request)
    limit = _clamp_limit(limit)
    offset = max(0, int(offset))
    clauses: list[str] = []
    params: list[Any] = []
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if internal_user_id:
        clauses.append("internal_user_id = ?")
        params.append(internal_user_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM security_events {where}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT id, internal_user_id, session_id, severity, event_type, ip_address, details_json, created_at "
            f"FROM security_events {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "internal_user_id": r["internal_user_id"],
                "session_id": r["session_id"],
                "severity": r["severity"],
                "event_type": r["event_type"],
                "ip_address": r["ip_address"],
                "details": safe_json_load(r["details_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@app.get("/api/admin/audit-logs-v2")
async def admin_audit_logs_v2(
    request: Request,
    actor_internal_user_id: str | None = None,
    target_internal_user_id: str | None = None,
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    require_trusted_admin(request)
    limit = _clamp_limit(limit)
    offset = max(0, int(offset))
    clauses: list[str] = []
    params: list[Any] = []
    if actor_internal_user_id:
        clauses.append("actor_internal_user_id = ?")
        params.append(actor_internal_user_id)
    if target_internal_user_id:
        clauses.append("target_internal_user_id = ?")
        params.append(target_internal_user_id)
    if action:
        clauses.append("action = ?")
        params.append(action)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM audit_logs {where}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT id, actor_internal_user_id, target_internal_user_id, action, entity_type, entity_id, "
            f"before_json, after_json, ip_address, created_at FROM audit_logs {where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "actor_internal_user_id": r["actor_internal_user_id"],
                "target_internal_user_id": r["target_internal_user_id"],
                "action": r["action"],
                "entity_type": r["entity_type"],
                "entity_id": r["entity_id"],
                "before": safe_json_load(r["before_json"]),
                "after": safe_json_load(r["after_json"]),
                "ip_address": r["ip_address"],
                "created_at": r["created_at"],
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@app.post("/api/admin/users/{internal_user_id}/block-v2")
async def admin_block_user_v2(internal_user_id: str, req: AdminBlockV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = (req.reason or "").strip()
    if not reason:
        raise HTTPException(400, "A non-empty reason is required.")
    if internal_user_id == admin["internal_user_id"]:
        raise HTTPException(403, "You cannot block yourself.")
    now_iso = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        urow = conn.execute("SELECT id, banned FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
        if urow is None:
            raise HTTPException(404, "User not found.")
        conn.execute("UPDATE users SET banned = 1 WHERE internal_user_id = ?", (internal_user_id,))
        revoked = conn.execute(
            "UPDATE auth_sessions SET revoked_at = ?, revoke_reason = 'admin_block' "
            "WHERE internal_user_id = ? AND revoked_at IS NULL",
            (now_iso, internal_user_id),
        ).rowcount
        record_audit_log(
            conn, "admin_block_user",
            actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=internal_user_id,
            entity_id=urow["id"],
            before={"banned": bool(urow["banned"])},
            after={"banned": True, "reason": reason, "sessions_revoked": revoked},
            request=request,
        )
        record_security_event(
            conn, "admin_user_blocked", severity="warning",
            internal_user_id=internal_user_id, request=request,
            details={"actor_internal_user_id": admin["internal_user_id"], "reason": reason},
        )
    return {"ok": True, "internal_user_id": internal_user_id, "status": "banned", "sessions_revoked": revoked}


@app.post("/api/admin/users/{internal_user_id}/unblock-v2")
async def admin_unblock_user_v2(internal_user_id: str, req: AdminBlockV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = (req.reason or "").strip()
    if not reason:
        raise HTTPException(400, "A non-empty reason is required.")
    with db() as conn:
        urow = conn.execute("SELECT id, banned FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
        if urow is None:
            raise HTTPException(404, "User not found.")
        conn.execute("UPDATE users SET banned = 0 WHERE internal_user_id = ?", (internal_user_id,))
        record_audit_log(
            conn, "admin_unblock_user",
            actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=internal_user_id,
            entity_id=urow["id"],
            before={"banned": bool(urow["banned"])},
            after={"banned": False, "reason": reason},
            request=request,
        )
        record_security_event(
            conn, "admin_user_unblocked", severity="info",
            internal_user_id=internal_user_id, request=request,
            details={"actor_internal_user_id": admin["internal_user_id"], "reason": reason},
        )
    # Revoked sessions are intentionally NOT restored.
    return {"ok": True, "internal_user_id": internal_user_id, "status": "active"}


@app.post("/api/admin/users/{internal_user_id}/password-reset-v2")
async def admin_password_reset_v2(internal_user_id: str, req: AdminPasswordResetV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = (req.reason or "").strip()
    new_password = req.new_password
    if not reason:
        raise HTTPException(400, "A non-empty reason is required.")
    if validate_password_policy(new_password):
        raise HTTPException(400, "Пароль должен быть от 8 до 128 символов.")
    password_hash = hash_password_argon2(new_password)
    now = datetime.now(timezone.utc).isoformat()
    revoked = 0
    with db() as conn:
        urow = conn.execute("SELECT id, banned FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
        if urow is None:
            raise HTTPException(404, "User not found.")
        # Disable old active passwords
        conn.execute(
            "UPDATE auth_passwords SET disabled_at = ? WHERE internal_user_id = ? AND disabled_at IS NULL",
            (now, internal_user_id),
        )
        # Insert new password row
        conn.execute(
            "INSERT INTO auth_passwords (id, internal_user_id, password_hash, algorithm, created_at, updated_at, password_updated_at) VALUES (?, ?, ?, 'argon2id', ?, ?, ?)",
            (uuid.uuid4().hex, internal_user_id, password_hash, now, now, now),
        )
        # Revoke all active sessions
        revoked = conn.execute(
            "UPDATE auth_sessions SET revoked_at = ?, revoke_reason = 'admin_password_reset' WHERE internal_user_id = ? AND revoked_at IS NULL",
            (now, internal_user_id),
        ).rowcount
        record_audit_log(
            conn, "admin_password_reset",
            actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=internal_user_id,
            entity_id=urow["id"],
            before={"banned": bool(urow["banned"])},
            after={"reason": reason, "sessions_revoked": revoked},
            request=request,
        )
        record_security_event(
            conn, "admin_password_reset", severity="warning",
            internal_user_id=internal_user_id, request=request,
            details={"actor_internal_user_id": admin["internal_user_id"], "reason": reason, "sessions_revoked": revoked},
        )
    try:
        record_event_log("admin_password_reset_succeeded", internal_user_id=internal_user_id,
                          platform=admin.get("platform", "web"), properties={"sessions_revoked": revoked})
    except Exception:
        pass
    return {"ok": True, "internal_user_id": internal_user_id, "sessions_revoked": revoked}


# ---------------------------------------------------------------------------
# Phase 20C — trusted per-user admin actions (require_trusted_admin, reason+audit).
# ---------------------------------------------------------------------------
ADMIN_TOKENS_MAX_ABS = 100000


def _admin_load_target(conn: sqlite3.Connection, internal_user_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT id, internal_user_id, role, banned, token_balance, plan, display_name, email FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "User not found.")
    return row


BILLING_INVOICE_STATUSES = {"draft", "issued", "paid", "cancelled", "refunded", "partially_refunded"}
BILLING_PAYMENT_STATUSES = {"pending", "paid", "failed", "cancelled", "refunded", "partially_refunded"}
BILLING_REFUND_STATUSES = {"pending", "completed", "failed", "cancelled"}


def _billing_currency(value: str | None) -> str:
    currency = (value or "RUB").strip().upper()[:12]
    return currency or "RUB"


def _billing_reason(value: str | None) -> str:
    reason = truncate_admin_text(value, 300).strip()
    if not reason:
        raise HTTPException(400, "Укажите причину.")
    return reason


def _billing_idempotency(value: str | None, prefix: str) -> str:
    raw = (value or "").strip()
    if raw:
        return raw[:120]
    return f"{prefix}-{uuid.uuid4().hex}"


def _invoice_code(conn: sqlite3.Connection) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    for _ in range(20):
        code = f"INV-{day}-{secrets.token_hex(3).upper()}"
        if conn.execute("SELECT 1 FROM invoices WHERE invoice_code = ?", (code,)).fetchone() is None:
            return code
    return f"INV-{day}-{uuid.uuid4().hex[:10].upper()}"


def _billing_invoice_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "id_short": short_public_id(row["id"], 10),
        "invoice_code": row["invoice_code"],
        "internal_user_id": row["internal_user_id"],
        "user_id_short": short_public_id(row["user_id"], 8),
        "status": row["status"],
        "currency": row["currency"],
        "subtotal_amount": int(row["subtotal_amount"] or 0),
        "discount_amount": int(row["discount_amount"] or 0),
        "total_amount": int(row["total_amount"] or 0),
        "tokens_total": int(row["tokens_total"] or 0),
        "due_at": row["due_at"],
        "issued_at": row["issued_at"],
        "paid_at": row["paid_at"],
        "cancelled_at": row["cancelled_at"],
        "refunded_at": row["refunded_at"],
        "reason": truncate_admin_text(row["reason"], 120),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _billing_payment_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "id_short": short_public_id(row["id"], 10),
        "invoice_id": row["invoice_id"],
        "invoice_id_short": short_public_id(row["invoice_id"], 10),
        "internal_user_id": row["internal_user_id"],
        "user_id_short": short_public_id(row["user_id"], 8),
        "status": row["status"],
        "amount": int(row["amount"] or 0),
        "currency": row["currency"],
        "method": row["method"],
        "provider": row["provider"],
        "provider_payment_id": short_public_id(row["provider_payment_id"], 10),
        "paid_at": row["paid_at"],
        "reason": truncate_admin_text(row["reason"], 120),
        "token_ledger_id": short_public_id(row["token_ledger_id"], 10),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _billing_refund_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "id_short": short_public_id(row["id"], 10),
        "payment_id": row["payment_id"],
        "payment_id_short": short_public_id(row["payment_id"], 10),
        "invoice_id": row["invoice_id"],
        "invoice_id_short": short_public_id(row["invoice_id"], 10),
        "internal_user_id": row["internal_user_id"],
        "amount": int(row["amount"] or 0),
        "currency": row["currency"],
        "status": row["status"],
        "reason": truncate_admin_text(row["reason"], 120),
        "token_reversal_ledger_id": short_public_id(row["token_reversal_ledger_id"], 10),
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "token_reversal_policy": "deferred",
    }


def _billing_package_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "description": truncate_admin_text(row["description"], 160),
        "price_amount": int(row["price_amount"] or 0),
        "currency": row["currency"],
        "token_amount": int(row["token_amount"] or 0),
        "is_active": bool(row["is_active"]),
        "sort_order": int(row["sort_order"] or 0),
    }


def _billing_projection(conn: sqlite3.Connection, internal_user_id: str) -> dict[str, Any]:
    summary = conn.execute(
        """
        SELECT
            COUNT(*) AS invoice_count,
            COALESCE(SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END),0) AS paid_count,
            COALESCE(SUM(CASE WHEN status IN ('draft','issued') THEN 1 ELSE 0 END),0) AS unpaid_count,
            MAX(created_at) AS last_invoice_at
        FROM invoices WHERE internal_user_id = ?
        """,
        (internal_user_id,),
    ).fetchone()
    totals = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN status IN ('paid','refunded','partially_refunded') THEN amount ELSE 0 END),0) AS total_paid,
            MAX(paid_at) AS last_payment_at
        FROM payments WHERE internal_user_id = ?
        """,
        (internal_user_id,),
    ).fetchone()
    refunds_total = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN status = 'completed' THEN amount ELSE 0 END),0) AS total_refunded FROM refunds WHERE internal_user_id = ?",
        (internal_user_id,),
    ).fetchone()["total_refunded"]
    invoices = conn.execute("SELECT * FROM invoices WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 20", (internal_user_id,)).fetchall()
    payments = conn.execute("SELECT * FROM payments WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 20", (internal_user_id,)).fetchall()
    refunds = conn.execute("SELECT * FROM refunds WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 20", (internal_user_id,)).fetchall()
    return {
        "billing_summary": {
            "invoice_count": int(summary["invoice_count"] or 0),
            "paid_count": int(summary["paid_count"] or 0),
            "unpaid_count": int(summary["unpaid_count"] or 0),
            "total_paid": int(totals["total_paid"] or 0),
            "total_refunded": int(refunds_total or 0),
            "last_invoice_at": summary["last_invoice_at"],
            "last_payment_at": totals["last_payment_at"],
        },
        "invoices_recent": [_billing_invoice_dict(r) for r in invoices],
        "payments_recent": [_billing_payment_dict(r) for r in payments],
        "refunds_recent": [_billing_refund_dict(r) for r in refunds],
    }


def _loyalty_promo_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "id_short": short_public_id(row["id"], 10),
        "promo_code": truncate_admin_text(row["promo_code"], 80),
        "status": row["status"],
        "discount_amount": int(row["discount_amount"] or 0),
        "token_bonus": int(row["token_bonus"] or 0),
        "reason": truncate_admin_text(row["reason"], 120),
        "token_ledger_id": short_public_id(row["token_ledger_id"], 10),
        "created_at": row["created_at"],
        "cancelled_at": row["cancelled_at"],
    }


def _loyalty_bonus_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "id_short": short_public_id(row["id"], 10),
        "bonus_type": row["bonus_type"],
        "token_amount": int(row["token_amount"] or 0),
        "money_amount": int(row["money_amount"] or 0),
        "currency": row["currency"],
        "status": row["status"],
        "reason": truncate_admin_text(row["reason"], 120),
        "token_ledger_id": short_public_id(row["token_ledger_id"], 10),
        "cancelled_ledger_id": short_public_id(row["cancelled_ledger_id"], 10),
        "created_at": row["created_at"],
        "cancelled_at": row["cancelled_at"],
    }


def _loyalty_link_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "id_short": short_public_id(row["id"], 10),
        "referral_code": row["referral_code"],
        "status": row["status"],
        "created_at": row["created_at"],
        "disabled_at": row["disabled_at"],
    }


def _loyalty_relation_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "id_short": short_public_id(row["id"], 10),
        "parent_internal_user_id": short_public_id(row["parent_internal_user_id"], 10),
        "child_internal_user_id": short_public_id(row["child_internal_user_id"], 10),
        "referral_code": row["referral_code"],
        "status": row["status"],
        "created_at": row["created_at"],
        "cancelled_at": row["cancelled_at"],
    }


def _loyalty_reward_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "id_short": short_public_id(row["id"], 10),
        "referral_relation_id": short_public_id(row["referral_relation_id"], 10),
        "parent_internal_user_id": short_public_id(row["parent_internal_user_id"], 10),
        "child_internal_user_id": short_public_id(row["child_internal_user_id"], 10),
        "reward_type": row["reward_type"],
        "token_amount": int(row["token_amount"] or 0),
        "money_amount": int(row["money_amount"] or 0),
        "currency": row["currency"],
        "status": row["status"],
        "reason": truncate_admin_text(row["reason"], 120),
        "token_ledger_id": short_public_id(row["token_ledger_id"], 10),
        "created_at": row["created_at"],
        "granted_at": row["granted_at"],
        "cancelled_at": row["cancelled_at"],
    }


def _ensure_referral_link(conn: sqlite3.Connection, target: sqlite3.Row, now: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM referral_links WHERE internal_user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1", (target["internal_user_id"],)).fetchone()
    if row is not None:
        return row
    base = (target["id"] or target["internal_user_id"] or uuid.uuid4().hex).replace("-", "")[:8].upper()
    code = f"REF-{base}"
    n = 1
    while conn.execute("SELECT 1 FROM referral_links WHERE referral_code = ?", (code,)).fetchone() is not None:
        n += 1
        code = f"REF-{base}-{n}"
    link_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO referral_links (id, internal_user_id, user_id, referral_code, status, created_at) VALUES (?, ?, ?, ?, 'active', ?)",
        (link_id, target["internal_user_id"], target["id"], code, now),
    )
    return conn.execute("SELECT * FROM referral_links WHERE id = ?", (link_id,)).fetchone()


def _loyalty_projection(conn: sqlite3.Connection, internal_user_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    target = _admin_load_target(conn, internal_user_id)
    link = _ensure_referral_link(conn, target, now)
    promo_rows = conn.execute("SELECT * FROM promo_redemptions WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 20", (internal_user_id,)).fetchall()
    bonus_rows = conn.execute("SELECT * FROM bonus_grants WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 20", (internal_user_id,)).fetchall()
    relations = conn.execute(
        "SELECT * FROM referral_relations WHERE parent_internal_user_id = ? OR child_internal_user_id = ? ORDER BY created_at DESC LIMIT 30",
        (internal_user_id, internal_user_id),
    ).fetchall()
    reward_rows = conn.execute("SELECT * FROM referral_rewards WHERE parent_internal_user_id = ? ORDER BY created_at DESC LIMIT 20", (internal_user_id,)).fetchall()
    summary = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM promo_redemptions WHERE internal_user_id = ? AND status = 'applied') AS promo_count,
            (SELECT COUNT(*) FROM bonus_grants WHERE internal_user_id = ? AND status = 'granted') AS bonus_count,
            (SELECT COUNT(*) FROM referral_relations WHERE parent_internal_user_id = ? AND status = 'active') AS children_count,
            (SELECT COALESCE(SUM(CASE WHEN status = 'granted' THEN COALESCE(token_amount,0) ELSE 0 END),0) FROM referral_rewards WHERE parent_internal_user_id = ?) AS rewards_total
        """,
        (internal_user_id, internal_user_id, internal_user_id, internal_user_id),
    ).fetchone()
    return {
        "loyalty_summary": {
            "promo_redemption_count": int(summary["promo_count"] or 0),
            "bonus_count": int(summary["bonus_count"] or 0),
            "referral_children_count": int(summary["children_count"] or 0),
            "referral_rewards_total": int(summary["rewards_total"] or 0),
            "active_referral_code": link["referral_code"] if link else None,
        },
        "promo_redemptions_recent": [_loyalty_promo_dict(r) for r in promo_rows],
        "bonus_grants_recent": [_loyalty_bonus_dict(r) for r in bonus_rows],
        "referral_link": _loyalty_link_dict(link),
        "referral_relations": [_loyalty_relation_dict(r) for r in relations],
        "referral_rewards_recent": [_loyalty_reward_dict(r) for r in reward_rows],
    }


def _grant_tokens_with_ledger(
    conn: sqlite3.Connection,
    *,
    target: sqlite3.Row,
    delta: int,
    reason: str,
    ledger_reason: str,
    meta: dict[str, Any],
) -> tuple[str, int]:
    old_balance = int(target["token_balance"] or 0)
    new_balance = old_balance + int(delta)
    if new_balance < 0:
        raise HTTPException(400, "Баланс не может стать отрицательным.")
    ledger_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (ledger_id, target["id"], int(delta), ledger_reason, json.dumps({**meta, "reason": reason}, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
    )
    conn.execute("UPDATE users SET token_balance = ? WHERE internal_user_id = ?", (new_balance, target["internal_user_id"]))
    return ledger_id, new_balance


@app.post("/api/admin/users/{internal_user_id}/role-v2")
async def admin_role_v2(internal_user_id: str, req: AdminRoleV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = (req.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Укажите причину.")
    if internal_user_id == admin["internal_user_id"] and req.role != "admin":
        raise HTTPException(403, "Нельзя снять роль администратора с себя.")
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        target = _admin_load_target(conn, internal_user_id)
        if target["role"] == "admin" and req.role != "admin":
            admin_count = conn.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'").fetchone()["c"]
            if admin_count <= 1:
                raise HTTPException(403, "Нельзя снять последнего администратора.")
        conn.execute("UPDATE users SET role = ? WHERE internal_user_id = ?", (req.role, internal_user_id))
        record_audit_log(conn, "admin_change_role", actor_internal_user_id=admin["internal_user_id"],
                         target_internal_user_id=internal_user_id, entity_id=target["id"],
                         before={"role": target["role"]}, after={"role": req.role, "reason": reason}, request=request)
        record_security_event(conn, "admin_role_changed", severity="warning", internal_user_id=internal_user_id,
                              request=request, details={"actor_internal_user_id": admin["internal_user_id"], "role": req.role, "reason": reason})
    _ = now
    return {"ok": True, "internal_user_id": internal_user_id, "role": req.role}


@app.post("/api/admin/users/{internal_user_id}/tokens-v2")
async def admin_tokens_v2(internal_user_id: str, req: AdminTokensV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = (req.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Укажите причину.")
    if req.delta == 0:
        raise HTTPException(400, "Изменение баланса не может быть нулевым.")
    if abs(req.delta) > ADMIN_TOKENS_MAX_ABS:
        raise HTTPException(400, "Слишком большое изменение баланса.")
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        target = _admin_load_target(conn, internal_user_id)
        old_balance = int(target["token_balance"] or 0)
        new_balance = old_balance + req.delta
        if new_balance < 0:
            raise HTTPException(400, "Баланс не может стать отрицательным.")
        conn.execute("UPDATE users SET token_balance = ? WHERE internal_user_id = ?", (new_balance, internal_user_id))
        conn.execute(
            "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, 'admin_adjust', ?, ?)",
            (uuid.uuid4().hex, target["id"], req.delta,
             json.dumps({"actor_internal_user_id": admin["internal_user_id"], "reason": reason}, ensure_ascii=False), now),
        )
        record_audit_log(conn, "admin_adjust_tokens", actor_internal_user_id=admin["internal_user_id"],
                         target_internal_user_id=internal_user_id, entity_id=target["id"],
                         before={"token_balance": old_balance}, after={"token_balance": new_balance, "delta": req.delta, "reason": reason}, request=request)
    try:
        record_event_log("admin_tokens_adjusted", internal_user_id=internal_user_id, platform="web",
                         properties={"delta": req.delta, "new_balance": new_balance})
    except Exception:
        pass
    return {"ok": True, "internal_user_id": internal_user_id, "old_balance": old_balance, "new_balance": new_balance, "delta": req.delta}


@app.post("/api/admin/users/{internal_user_id}/plan-v2")
async def admin_plan_v2(internal_user_id: str, req: AdminPlanV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = (req.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Укажите причину.")
    with db() as conn:
        target = _admin_load_target(conn, internal_user_id)
        conn.execute("UPDATE users SET plan = ?, gallery_enabled = 1 WHERE internal_user_id = ?",
                     (req.plan, internal_user_id))
        record_audit_log(conn, "admin_change_plan", actor_internal_user_id=admin["internal_user_id"],
                         target_internal_user_id=internal_user_id, entity_id=target["id"],
                         before={"plan": target["plan"]}, after={"plan": req.plan, "reason": reason}, request=request)
    return {"ok": True, "internal_user_id": internal_user_id, "plan": req.plan}


@app.post("/api/admin/users/{internal_user_id}/profile-v2")
async def admin_profile_v2(internal_user_id: str, req: AdminProfileV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = (req.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Укажите причину.")
    updates: list[str] = []
    values: list[Any] = []
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    with db() as conn:
        target = _admin_load_target(conn, internal_user_id)
        if req.display_name is not None:
            v = req.display_name.strip()[:200]
            updates.append("display_name = ?"); values.append(v)
            before["display_name"] = target["display_name"]; after["display_name"] = v
        if req.email is not None:
            v = (normalize_email(req.email) or req.email.strip()[:200])
            updates.append("email = ?"); values.append(v)
            before["email"] = target["email"]; after["email"] = v
        if req.avatar_url is not None or req.avatar_preset is not None:
            avatar_url, avatar_preset = validate_avatar_choice(req.avatar_url, req.avatar_preset)
            updates.append("avatar_url = ?"); values.append(avatar_url)
            updates.append("avatar_preset = ?"); values.append(avatar_preset)
            before["avatar_url"] = _row_get(target, "avatar_url")
            before["avatar_preset"] = _row_get(target, "avatar_preset")
            after["avatar_url"] = avatar_url
            after["avatar_preset"] = avatar_preset
        if not updates:
            raise HTTPException(400, "Нет полей для изменения.")
        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE internal_user_id = ?", (*values, internal_user_id))
        after["reason"] = reason
        record_audit_log(conn, "admin_update_user_profile", actor_internal_user_id=admin["internal_user_id"],
                         target_internal_user_id=internal_user_id, entity_id=target["id"], before=before, after=after, request=request)
    return {
        "ok": True,
        "internal_user_id": internal_user_id,
        "display_name": after.get("display_name"),
        "email": after.get("email"),
        "avatar_url": after.get("avatar_url"),
        "avatar_preset": after.get("avatar_preset"),
    }


@app.get("/api/admin/users/{internal_user_id}/billing-v2")
async def admin_user_billing_v2(internal_user_id: str, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    with db() as conn:
        _admin_load_target(conn, internal_user_id)
        packages = conn.execute(
            "SELECT * FROM billing_packages WHERE is_active = 1 ORDER BY sort_order ASC, price_amount ASC, code ASC"
        ).fetchall()
        projection = _billing_projection(conn, internal_user_id)
    return {"ok": True, "packages": [_billing_package_dict(r) for r in packages], **projection}


@app.post("/api/admin/users/{internal_user_id}/invoices-v2")
async def admin_create_invoice_v2(internal_user_id: str, req: BillingCreateInvoiceV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = _billing_reason(req.reason)
    if not req.items:
        raise HTTPException(400, "Добавьте хотя бы одну позицию счёта.")
    currency = _billing_currency(req.currency)
    now = datetime.now(timezone.utc).isoformat()
    normalized_items: list[dict[str, Any]] = []
    subtotal = 0
    tokens_total = 0
    for item in req.items:
        title = truncate_admin_text(item.title, 180).strip()
        if not title:
            raise HTTPException(400, "Укажите название позиции.")
        quantity = int(item.quantity or 0)
        unit_amount = int(item.unit_amount or 0)
        token_amount = int(item.token_amount or 0)
        if quantity <= 0 or unit_amount < 0 or token_amount < 0:
            raise HTTPException(400, "Некорректная позиция счёта.")
        total = quantity * unit_amount
        subtotal += total
        tokens_total += quantity * token_amount
        normalized_items.append({
            "package_code": truncate_admin_text(item.package_code, 80) or None,
            "title": title,
            "description": truncate_admin_text(item.description, 240) or None,
            "quantity": quantity,
            "unit_amount": unit_amount,
            "total_amount": total,
            "token_amount": token_amount,
        })
    invoice: dict[str, Any] | None = None
    legacy_user_id: str | None = None
    with db() as conn:
        target = _admin_load_target(conn, internal_user_id)
        legacy_user_id = target["id"]
        invoice_id = uuid.uuid4().hex
        invoice_code = _invoice_code(conn)
        status = "draft" if req.status == "draft" else "issued"
        conn.execute(
            """
            INSERT INTO invoices
                (id, invoice_code, internal_user_id, user_id, status, currency, subtotal_amount,
                 discount_amount, total_amount, tokens_total, due_at, issued_at, created_by_admin_id,
                 updated_by_admin_id, reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id, invoice_code, internal_user_id, legacy_user_id, status, currency, subtotal,
                subtotal, tokens_total, req.due_at, now if status == "issued" else None,
                admin["internal_user_id"], admin["internal_user_id"], reason, now, now,
            ),
        )
        for item in normalized_items:
            conn.execute(
                """
                INSERT INTO invoice_items
                    (id, invoice_id, package_code, title, description, quantity, unit_amount, total_amount, token_amount, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, invoice_id, item["package_code"], item["title"], item["description"],
                 item["quantity"], item["unit_amount"], item["total_amount"], item["token_amount"], now),
            )
        row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        invoice = _billing_invoice_dict(row)
        record_audit_log(
            conn, "billing_invoice_created", actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=internal_user_id, entity_type="invoice", entity_id=invoice_id,
            after={"invoice_code": invoice_code, "status": status, "total_amount": subtotal, "tokens_total": tokens_total, "reason": reason},
            request=request,
        )
    try:
        record_event_log(
            "billing_invoice_created", internal_user_id=internal_user_id, legacy_user_id=legacy_user_id,
            platform=admin.get("platform", "web"), request=request,
            properties={"invoice_id": invoice["id"] if invoice else None, "invoice_code": invoice["invoice_code"] if invoice else None,
                        "total_amount": subtotal, "tokens_total": tokens_total, "status": req.status},
        )
    except Exception:
        pass
    return {"ok": True, "invoice": invoice}


@app.post("/api/admin/invoices/{invoice_id}/mark-paid-v2")
async def admin_mark_invoice_paid_v2(invoice_id: str, req: BillingMarkPaidV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = _billing_reason(req.reason)
    amount = int(req.amount or 0)
    if amount <= 0:
        raise HTTPException(400, "Сумма оплаты должна быть больше нуля.")
    idem = _billing_idempotency(req.idempotency_key, f"manual-pay-{invoice_id}")
    now = datetime.now(timezone.utc).isoformat()
    payment: dict[str, Any] | None = None
    invoice_out: dict[str, Any] | None = None
    new_balance = 0
    target_iuid: str | None = None
    legacy_user_id: str | None = None
    with db() as conn:
        existing = conn.execute("SELECT * FROM payments WHERE idempotency_key = ?", (idem,)).fetchone()
        if existing is not None:
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (existing["invoice_id"],)).fetchone()
            bal = conn.execute("SELECT token_balance FROM users WHERE internal_user_id = ?", (existing["internal_user_id"],)).fetchone()
            return {"ok": True, "payment": _billing_payment_dict(existing), "invoice": _billing_invoice_dict(inv), "new_token_balance": int(_row_get(bal, "token_balance") or 0), "idempotent": True}
        inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if inv is None:
            raise HTTPException(404, "Invoice not found.")
        if inv["status"] in {"cancelled", "refunded", "partially_refunded"}:
            raise HTTPException(400, "Нельзя оплатить отменённый или возвращённый счёт.")
        if inv["status"] == "paid":
            raise HTTPException(400, "Счёт уже оплачен.")
        if amount != int(inv["total_amount"] or 0):
            raise HTTPException(400, "Для ручной оплаты сумма должна совпадать с суммой счёта.")
        target_iuid = inv["internal_user_id"]
        legacy_user_id = inv["user_id"]
        target = _admin_load_target(conn, target_iuid)
        payment_id = uuid.uuid4().hex
        ledger_id: str | None = None
        tokens_total = int(inv["tokens_total"] or 0)
        old_balance = int(target["token_balance"] or 0)
        new_balance = old_balance
        if tokens_total > 0:
            ledger_id = uuid.uuid4().hex
            new_balance = old_balance + tokens_total
            conn.execute(
                "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, 'payment_grant', ?, ?)",
                (
                    ledger_id, legacy_user_id, tokens_total,
                    json.dumps({"invoice_id": invoice_id, "payment_id": payment_id, "invoice_code": inv["invoice_code"],
                                "actor_internal_user_id": admin["internal_user_id"], "reason": reason}, ensure_ascii=False),
                    now,
                ),
            )
            conn.execute("UPDATE users SET token_balance = ? WHERE internal_user_id = ?", (new_balance, target_iuid))
        conn.execute(
            """
            INSERT INTO payments
                (id, invoice_id, internal_user_id, user_id, status, amount, currency, method, provider,
                 paid_at, created_by_admin_id, reason, token_ledger_id, idempotency_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'paid', ?, ?, 'manual', 'manual', ?, ?, ?, ?, ?, ?, ?)
            """,
            (payment_id, invoice_id, target_iuid, legacy_user_id, amount, inv["currency"], now,
             admin["internal_user_id"], reason, ledger_id, idem, now, now),
        )
        conn.execute(
            "UPDATE invoices SET status = 'paid', paid_at = ?, updated_at = ?, updated_by_admin_id = ? WHERE id = ?",
            (now, now, admin["internal_user_id"], invoice_id),
        )
        payment_row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        inv_row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        payment = _billing_payment_dict(payment_row)
        invoice_out = _billing_invoice_dict(inv_row)
        record_audit_log(
            conn, "billing_invoice_mark_paid", actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=target_iuid, entity_type="payment", entity_id=payment_id,
            before={"invoice_status": inv["status"], "token_balance": old_balance},
            after={"invoice_status": "paid", "amount": amount, "tokens_granted": tokens_total, "token_balance": new_balance, "reason": reason},
            request=request,
        )
    try:
        record_event_log(
            "billing_payment_recorded", internal_user_id=target_iuid, legacy_user_id=legacy_user_id,
            platform=admin.get("platform", "web"), request=request,
            properties={"invoice_id": invoice_id, "payment_id": payment["id"] if payment else None, "amount": amount},
        )
    except Exception:
        pass
    return {"ok": True, "payment": payment, "invoice": invoice_out, "new_token_balance": new_balance}


@app.post("/api/admin/invoices/{invoice_id}/cancel-v2")
async def admin_cancel_invoice_v2(invoice_id: str, req: BillingCancelInvoiceV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = _billing_reason(req.reason)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if inv is None:
            raise HTTPException(404, "Invoice not found.")
        if inv["status"] in {"paid", "refunded", "partially_refunded"}:
            raise HTTPException(400, "Оплаченный счёт отменяется только через возврат.")
        if inv["status"] == "cancelled":
            raise HTTPException(400, "Счёт уже отменён.")
        conn.execute(
            "UPDATE invoices SET status = 'cancelled', cancelled_at = ?, updated_at = ?, updated_by_admin_id = ?, reason = ? WHERE id = ?",
            (now, now, admin["internal_user_id"], reason, invoice_id),
        )
        row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        record_audit_log(
            conn, "billing_invoice_cancelled", actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=inv["internal_user_id"], entity_type="invoice", entity_id=invoice_id,
            before={"status": inv["status"]}, after={"status": "cancelled", "reason": reason}, request=request,
        )
    return {"ok": True, "invoice": _billing_invoice_dict(row)}


@app.post("/api/admin/payments/{payment_id}/refund-v2")
async def admin_refund_payment_v2(payment_id: str, req: BillingRefundV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = _billing_reason(req.reason)
    amount = int(req.amount or 0)
    if amount <= 0:
        raise HTTPException(400, "Сумма возврата должна быть больше нуля.")
    idem = _billing_idempotency(req.idempotency_key, f"manual-refund-{payment_id}")
    now = datetime.now(timezone.utc).isoformat()
    refund: dict[str, Any] | None = None
    payment_out: dict[str, Any] | None = None
    invoice_out: dict[str, Any] | None = None
    target_iuid: str | None = None
    legacy_user_id: str | None = None
    with db() as conn:
        existing = conn.execute("SELECT * FROM refunds WHERE idempotency_key = ?", (idem,)).fetchone()
        if existing is not None:
            pay = conn.execute("SELECT * FROM payments WHERE id = ?", (existing["payment_id"],)).fetchone()
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (existing["invoice_id"],)).fetchone()
            return {"ok": True, "refund": _billing_refund_dict(existing), "payment": _billing_payment_dict(pay), "invoice": _billing_invoice_dict(inv), "idempotent": True}
        pay = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if pay is None:
            raise HTTPException(404, "Payment not found.")
        if pay["status"] not in {"paid", "partially_refunded"}:
            raise HTTPException(400, "Возврат возможен только по оплаченной записи.")
        refunded = int(conn.execute("SELECT COALESCE(SUM(amount),0) AS c FROM refunds WHERE payment_id = ? AND status = 'completed'", (payment_id,)).fetchone()["c"] or 0)
        remaining = int(pay["amount"] or 0) - refunded
        if amount > remaining:
            raise HTTPException(400, "Сумма возврата превышает остаток платежа.")
        target_iuid = pay["internal_user_id"]
        legacy_user_id = pay["user_id"]
        refund_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO refunds
                (id, payment_id, invoice_id, internal_user_id, amount, currency, status, reason,
                 created_by_admin_id, token_reversal_ledger_id, idempotency_key, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?, NULL, ?, ?, ?)
            """,
            (refund_id, payment_id, pay["invoice_id"], target_iuid, amount, pay["currency"], reason,
             admin["internal_user_id"], idem, now, now),
        )
        new_refunded = refunded + amount
        new_payment_status = "refunded" if new_refunded >= int(pay["amount"] or 0) else "partially_refunded"
        conn.execute("UPDATE payments SET status = ?, updated_at = ? WHERE id = ?", (new_payment_status, now, payment_id))
        invoice_paid = int(conn.execute("SELECT COALESCE(SUM(amount),0) AS c FROM payments WHERE invoice_id = ? AND status IN ('paid','partially_refunded','refunded')", (pay["invoice_id"],)).fetchone()["c"] or 0)
        invoice_refunded = int(conn.execute("SELECT COALESCE(SUM(amount),0) AS c FROM refunds WHERE invoice_id = ? AND status = 'completed'", (pay["invoice_id"],)).fetchone()["c"] or 0)
        new_invoice_status = "refunded" if invoice_refunded >= invoice_paid else "partially_refunded"
        conn.execute(
            "UPDATE invoices SET status = ?, refunded_at = ?, updated_at = ?, updated_by_admin_id = ? WHERE id = ?",
            (new_invoice_status, now, now, admin["internal_user_id"], pay["invoice_id"]),
        )
        refund_row = conn.execute("SELECT * FROM refunds WHERE id = ?", (refund_id,)).fetchone()
        pay_row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        inv_row = conn.execute("SELECT * FROM invoices WHERE id = ?", (pay["invoice_id"],)).fetchone()
        refund = _billing_refund_dict(refund_row)
        payment_out = _billing_payment_dict(pay_row)
        invoice_out = _billing_invoice_dict(inv_row)
        record_audit_log(
            conn, "billing_payment_refunded", actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=target_iuid, entity_type="refund", entity_id=refund_id,
            before={"payment_status": pay["status"], "remaining": remaining},
            after={"amount": amount, "payment_status": new_payment_status, "invoice_status": new_invoice_status, "reason": reason, "token_reversal_policy": "deferred"},
            request=request,
        )
    try:
        record_event_log(
            "billing_refund_recorded", internal_user_id=target_iuid, legacy_user_id=legacy_user_id,
            platform=admin.get("platform", "web"), request=request,
            properties={"payment_id": payment_id, "amount": amount, "token_reversal_policy": "deferred"},
        )
    except Exception:
        pass
    return {"ok": True, "refund": refund, "payment": payment_out, "invoice": invoice_out}


@app.get("/api/admin/users/{internal_user_id}/promos-v2")
async def admin_user_promos_v2(internal_user_id: str, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    with db() as conn:
        _admin_load_target(conn, internal_user_id)
        projection = _loyalty_projection(conn, internal_user_id)
    return {"ok": True, **projection}


@app.get("/api/admin/users/{internal_user_id}/referrals-v2")
async def admin_user_referrals_v2(internal_user_id: str, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    with db() as conn:
        _admin_load_target(conn, internal_user_id)
        projection = _loyalty_projection(conn, internal_user_id)
    return {
        "ok": True,
        "loyalty_summary": projection["loyalty_summary"],
        "referral_link": projection["referral_link"],
        "referral_relations": projection["referral_relations"],
        "referral_rewards_recent": projection["referral_rewards_recent"],
    }


@app.post("/api/admin/users/{internal_user_id}/bonus-v2")
async def admin_bonus_grant_v2(internal_user_id: str, req: BonusGrantV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = _billing_reason(req.reason)
    amount = int(req.token_amount or 0)
    if amount <= 0:
        raise HTTPException(400, "Сумма бонуса должна быть больше нуля.")
    idem = _billing_idempotency(req.idempotency_key, f"bonus-{internal_user_id}")
    now = datetime.now(timezone.utc).isoformat()
    bonus: dict[str, Any] | None = None
    new_balance = 0
    legacy_user_id: str | None = None
    with db() as conn:
        existing = conn.execute("SELECT * FROM bonus_grants WHERE idempotency_key = ?", (idem,)).fetchone()
        if existing is not None:
            bal = conn.execute("SELECT token_balance FROM users WHERE internal_user_id = ?", (existing["internal_user_id"],)).fetchone()
            return {"ok": True, "bonus": _loyalty_bonus_dict(existing), "new_token_balance": int(_row_get(bal, "token_balance") or 0), "idempotent": True}
        target = _admin_load_target(conn, internal_user_id)
        legacy_user_id = target["id"]
        bonus_id = uuid.uuid4().hex
        ledger_reason = "admin_bonus_compensation" if req.bonus_type == "compensation" else "bonus_grant"
        ledger_id, new_balance = _grant_tokens_with_ledger(
            conn, target=target, delta=amount, reason=reason, ledger_reason=ledger_reason,
            meta={"bonus_id": bonus_id, "bonus_type": req.bonus_type, "actor_internal_user_id": admin["internal_user_id"]},
        )
        conn.execute(
            """
            INSERT INTO bonus_grants
                (id, internal_user_id, user_id, bonus_type, token_amount, status, reason, token_ledger_id,
                 created_by_admin_id, idempotency_key, created_at)
            VALUES (?, ?, ?, ?, ?, 'granted', ?, ?, ?, ?, ?)
            """,
            (bonus_id, internal_user_id, legacy_user_id, req.bonus_type, amount, reason, ledger_id, admin["internal_user_id"], idem, now),
        )
        row = conn.execute("SELECT * FROM bonus_grants WHERE id = ?", (bonus_id,)).fetchone()
        bonus = _loyalty_bonus_dict(row)
        record_audit_log(
            conn, "crm_bonus_granted", actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=internal_user_id, entity_type="bonus", entity_id=bonus_id,
            after={"bonus_type": req.bonus_type, "token_amount": amount, "token_balance": new_balance, "reason": reason},
            request=request,
        )
    try:
        record_event_log("crm_bonus_granted", internal_user_id=internal_user_id, legacy_user_id=legacy_user_id,
                         platform=admin.get("platform", "web"), request=request,
                         properties={"bonus_id": bonus["id"] if bonus else None, "bonus_type": req.bonus_type, "token_amount": amount})
    except Exception:
        pass
    return {"ok": True, "bonus": bonus, "new_token_balance": new_balance}


@app.post("/api/admin/users/{internal_user_id}/bonus/{bonus_id}/cancel-v2")
async def admin_bonus_cancel_v2(internal_user_id: str, bonus_id: str, req: BonusCancelV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = _billing_reason(req.reason)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        target = _admin_load_target(conn, internal_user_id)
        bonus = conn.execute("SELECT * FROM bonus_grants WHERE id = ? AND internal_user_id = ?", (bonus_id, internal_user_id)).fetchone()
        if bonus is None:
            raise HTTPException(404, "Bonus not found.")
        if bonus["status"] != "granted":
            raise HTTPException(400, "Бонус уже отменён или недоступен.")
        amount = int(bonus["token_amount"] or 0)
        ledger_id, new_balance = _grant_tokens_with_ledger(
            conn, target=target, delta=-amount, reason=reason, ledger_reason="bonus_cancel",
            meta={"bonus_id": bonus_id, "actor_internal_user_id": admin["internal_user_id"]},
        )
        conn.execute(
            "UPDATE bonus_grants SET status = 'cancelled', cancelled_ledger_id = ?, cancelled_at = ? WHERE id = ?",
            (ledger_id, now, bonus_id),
        )
        row = conn.execute("SELECT * FROM bonus_grants WHERE id = ?", (bonus_id,)).fetchone()
        record_audit_log(
            conn, "crm_bonus_cancelled", actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=internal_user_id, entity_type="bonus", entity_id=bonus_id,
            before={"status": bonus["status"], "token_balance": int(target["token_balance"] or 0)},
            after={"status": "cancelled", "token_amount": -amount, "token_balance": new_balance, "reason": reason},
            request=request,
        )
    return {"ok": True, "bonus": _loyalty_bonus_dict(row), "new_token_balance": new_balance}


@app.post("/api/admin/users/{internal_user_id}/apply-promo-v2")
async def admin_apply_promo_v2(internal_user_id: str, req: ApplyPromoV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = _billing_reason(req.reason)
    promo_code = (req.promo_code or "").strip().upper()[:80]
    if not promo_code:
        raise HTTPException(400, "Укажите промокод.")
    idem = _billing_idempotency(req.idempotency_key, f"promo-{internal_user_id}-{promo_code}")
    now = datetime.now(timezone.utc).isoformat()
    redemption: dict[str, Any] | None = None
    new_balance = 0
    legacy_user_id: str | None = None
    token_bonus = 0
    with db() as conn:
        existing = conn.execute("SELECT * FROM promo_redemptions WHERE idempotency_key = ?", (idem,)).fetchone()
        if existing is not None:
            bal = conn.execute("SELECT token_balance FROM users WHERE internal_user_id = ?", (existing["internal_user_id"],)).fetchone()
            return {"ok": True, "redemption": _loyalty_promo_dict(existing), "new_token_balance": int(_row_get(bal, "token_balance") or 0), "idempotent": True}
        target = _admin_load_target(conn, internal_user_id)
        legacy_user_id = target["id"]
        promo = conn.execute("SELECT code, tokens, activation_limit, activation_count, enabled FROM promo_codes WHERE code = ?", (promo_code,)).fetchone()
        if promo is None:
            raise HTTPException(404, "Промокод не найден.")
        if not int(promo["enabled"] or 0):
            raise HTTPException(400, "Промокод отключён.")
        if int(promo["activation_count"] or 0) >= int(promo["activation_limit"] or 0):
            raise HTTPException(400, "Лимит активаций промокода исчерпан.")
        duplicate = conn.execute(
            "SELECT 1 FROM promo_redemptions WHERE internal_user_id = ? AND promo_code = ? AND status = 'applied'",
            (internal_user_id, promo_code),
        ).fetchone()
        if duplicate is not None:
            raise HTTPException(400, "Промокод уже применён к этому пользователю.")
        redemption_id = uuid.uuid4().hex
        token_bonus = max(0, int(promo["tokens"] or PROMO_REFERRAL_REWARD_TOKENS))
        ledger_id: str | None = None
        new_balance = int(target["token_balance"] or 0)
        if token_bonus > 0:
            ledger_id, new_balance = _grant_tokens_with_ledger(
                conn, target=target, delta=token_bonus, reason=reason, ledger_reason="promo_code_redeemed",
                meta={"promo_redemption_id": redemption_id, "promo_code": promo_code, "actor_internal_user_id": admin["internal_user_id"]},
            )
        conn.execute(
            """
            INSERT INTO promo_redemptions
                (id, promo_code_id, promo_code, internal_user_id, user_id, status, token_bonus, reason,
                 token_ledger_id, created_by_admin_id, idempotency_key, created_at)
            VALUES (?, ?, ?, ?, ?, 'applied', ?, ?, ?, ?, ?, ?)
            """,
            (redemption_id, promo_code, promo_code, internal_user_id, legacy_user_id, token_bonus, reason, ledger_id, admin["internal_user_id"], idem, now),
        )
        conn.execute("UPDATE promo_codes SET activation_count = activation_count + 1, updated_at = ? WHERE code = ?", (now, promo_code))
        row = conn.execute("SELECT * FROM promo_redemptions WHERE id = ?", (redemption_id,)).fetchone()
        redemption = _loyalty_promo_dict(row)
        record_audit_log(
            conn, "crm_promo_applied", actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=internal_user_id, entity_type="promo_redemption", entity_id=redemption_id,
            after={"promo_code": promo_code, "token_bonus": token_bonus, "token_balance": new_balance, "reason": reason},
            request=request,
        )
    try:
        record_event_log("crm_promo_applied", internal_user_id=internal_user_id, legacy_user_id=legacy_user_id,
                         platform=admin.get("platform", "web"), request=request,
                         properties={"promo_code": promo_code, "token_bonus": token_bonus})
    except Exception:
        pass
    return {"ok": True, "redemption": redemption, "new_token_balance": new_balance}


@app.post("/api/account/apply-promo-v2")
async def account_apply_promo_v2(req: UserApplyPromoV2Request, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    internal_user_id = trusted["internal_user_id"]
    promo_code = (req.promo_code or "").strip().upper()[:80]
    if not promo_code:
        raise HTTPException(400, "Укажите промокод.")
    now = datetime.now(timezone.utc).isoformat()
    reason = "promo_code_redeemed"
    redemption: dict[str, Any] | None = None
    new_balance = 0
    legacy_user_id: str | None = trusted.get("legacy_user_id")
    with db() as conn:
        target = conn.execute("SELECT * FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
        if target is None:
            raise HTTPException(404, "User not found.")
        legacy_user_id = target["id"]
        promo = conn.execute("SELECT code, tokens, activation_limit, activation_count, enabled FROM promo_codes WHERE code = ?", (promo_code,)).fetchone()
        if promo is None:
            raise HTTPException(404, "Промокод не найден.")
        if not int(promo["enabled"] or 0):
            raise HTTPException(400, "Промокод отключён.")
        if int(promo["activation_count"] or 0) >= int(promo["activation_limit"] or 0):
            raise HTTPException(400, "Лимит активаций промокода исчерпан.")
        duplicate = conn.execute(
            "SELECT 1 FROM promo_redemptions WHERE internal_user_id = ? AND promo_code = ? AND status = 'applied'",
            (internal_user_id, promo_code),
        ).fetchone()
        if duplicate is not None:
            raise HTTPException(400, "Промокод уже применён.")
        redemption_id = uuid.uuid4().hex
        token_bonus = max(0, int(promo["tokens"] or PROMO_REFERRAL_REWARD_TOKENS))
        ledger_id, new_balance = _grant_tokens_with_ledger(
            conn, target=target, delta=token_bonus, reason=reason, ledger_reason=reason,
            meta={"promo_redemption_id": redemption_id, "promo_code": promo_code},
        )
        conn.execute(
            """
            INSERT INTO promo_redemptions
                (id, promo_code_id, promo_code, internal_user_id, user_id, status, token_bonus, reason,
                 token_ledger_id, created_by_admin_id, idempotency_key, created_at)
            VALUES (?, ?, ?, ?, ?, 'applied', ?, ?, ?, NULL, ?, ?)
            """,
            (redemption_id, promo_code, promo_code, internal_user_id, legacy_user_id, token_bonus, reason, ledger_id,
             f"user-promo-{internal_user_id}-{promo_code}", now),
        )
        conn.execute("UPDATE promo_codes SET activation_count = activation_count + 1, updated_at = ? WHERE code = ?", (now, promo_code))
        row = conn.execute("SELECT * FROM promo_redemptions WHERE id = ?", (redemption_id,)).fetchone()
        redemption = _loyalty_promo_dict(row)
    try:
        record_event_log("promo_code_redeemed", internal_user_id=internal_user_id, legacy_user_id=legacy_user_id,
                         platform=trusted.get("platform", "web"), request=request,
                         properties={"promo_code": promo_code, "token_bonus": token_bonus})
    except Exception:
        pass
    return {
        "ok": True,
        "redemption": redemption,
        "token_bonus": token_bonus,
        "new_token_balance": new_balance,
    }


@app.post("/api/admin/users/{internal_user_id}/referral-reward-v2")
async def admin_referral_reward_v2(internal_user_id: str, req: ReferralRewardV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = _billing_reason(req.reason)
    amount = int(req.token_amount or PROMO_REFERRAL_REWARD_TOKENS)
    if amount <= 0:
        amount = PROMO_REFERRAL_REWARD_TOKENS
    idem = _billing_idempotency(req.idempotency_key, f"referral-reward-{internal_user_id}")
    now = datetime.now(timezone.utc).isoformat()
    reward: dict[str, Any] | None = None
    new_balance = 0
    legacy_user_id: str | None = None
    with db() as conn:
        existing = conn.execute("SELECT * FROM referral_rewards WHERE idempotency_key = ?", (idem,)).fetchone()
        if existing is not None:
            bal = conn.execute("SELECT token_balance FROM users WHERE internal_user_id = ?", (existing["parent_internal_user_id"],)).fetchone()
            return {"ok": True, "reward": _loyalty_reward_dict(existing), "new_token_balance": int(_row_get(bal, "token_balance") or 0), "idempotent": True}
        target = _admin_load_target(conn, internal_user_id)
        legacy_user_id = target["id"]
        relation_id = (req.referral_relation_id or "").strip() or None
        child_iuid = (req.child_internal_user_id or "").strip() or None
        if relation_id:
            rel = conn.execute("SELECT * FROM referral_relations WHERE id = ? AND parent_internal_user_id = ?", (relation_id, internal_user_id)).fetchone()
            if rel is None:
                raise HTTPException(404, "Referral relation not found.")
            child_iuid = rel["child_internal_user_id"]
        reward_id = uuid.uuid4().hex
        ledger_id, new_balance = _grant_tokens_with_ledger(
            conn, target=target, delta=amount, reason=reason, ledger_reason="referral_friend_signup",
            meta={"referral_reward_id": reward_id, "referral_relation_id": relation_id, "child_internal_user_id": child_iuid,
                  "actor_internal_user_id": admin["internal_user_id"]},
        )
        conn.execute(
            """
            INSERT INTO referral_rewards
                (id, referral_relation_id, parent_internal_user_id, child_internal_user_id, reward_type, token_amount,
                 status, reason, token_ledger_id, created_by_admin_id, idempotency_key, created_at, granted_at)
            VALUES (?, ?, ?, ?, 'tokens', ?, 'granted', ?, ?, ?, ?, ?, ?)
            """,
            (reward_id, relation_id, internal_user_id, child_iuid, amount, reason, ledger_id, admin["internal_user_id"], idem, now, now),
        )
        row = conn.execute("SELECT * FROM referral_rewards WHERE id = ?", (reward_id,)).fetchone()
        reward = _loyalty_reward_dict(row)
        record_audit_log(
            conn, "crm_referral_reward_granted", actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=internal_user_id, entity_type="referral_reward", entity_id=reward_id,
            after={"token_amount": amount, "token_balance": new_balance, "reason": reason},
            request=request,
        )
    return {"ok": True, "reward": reward, "new_token_balance": new_balance}


# ---------------------------------------------------------------------------
# Phase 18 — Admin auth analytics (trusted-admin only). Clean, human-readable.
# No token/password/code hashes, no raw tokens/cookies/initData/WebAppData.
# ---------------------------------------------------------------------------


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _today_start_iso() -> str:
    n = datetime.now(timezone.utc)
    return n.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def admin_user_analytics_row(conn: sqlite3.Connection, urow: sqlite3.Row, now_iso: str) -> dict[str, Any]:
    iuid = urow["internal_user_id"]
    legacy = urow["id"]
    identities = conn.execute(
        "SELECT provider, provider_username, provider_email, provider_first_name, provider_last_name, last_login_at "
        "FROM auth_identities WHERE internal_user_id = ? ORDER BY (last_login_at IS NULL), last_login_at DESC, linked_at ASC",
        (iuid,),
    ).fetchall()
    primary = identities[0]["provider"] if identities else resolve_primary_provider(conn, iuid)
    last_session = conn.execute(
        "SELECT platform, ip_address, provider, created_at, metadata_json FROM auth_sessions "
        "WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 1",
        (iuid,),
    ).fetchone()
    active_sessions = conn.execute(
        "SELECT COUNT(*) AS c FROM auth_sessions WHERE internal_user_id = ? AND revoked_at IS NULL AND expires_at > ?",
        (iuid, now_iso),
    ).fetchone()["c"]
    device_count = conn.execute(
        "SELECT COUNT(*) AS c FROM device_installations WHERE internal_user_id = ?", (iuid,)
    ).fetchone()["c"]
    device_meta = safe_json_load(_row_get(last_session, "metadata_json")) or {}
    device = device_meta.get("device") if isinstance(device_meta, dict) else {}
    gallery_quota = gallery_quota_for_user(conn, urow, legacy)
    return {
        "internal_user_id": iuid,  # used by the admin drawer fetch + technical section only
        "internal_user_id_short": (iuid[:8] + "…") if iuid else None,
        "public_user_code": _row_get(urow, "public_user_code"),
        "display_name": resolve_display_name(urow, identities[0] if identities else None),
        "avatar_url": _row_get(urow, "avatar_url"),
        "avatar_preset": _row_get(urow, "avatar_preset"),
        "primary_provider": primary,
        "providers": sorted({i["provider"] for i in identities}),
        "email": mask_email(_row_get(urow, "email")),
        "username": _row_get(urow, "username"),
        "phone": _row_get(urow, "phone"),
        "first_seen_at": _row_get(urow, "created_at"),
        "last_seen_at": _row_get(urow, "last_seen_at"),
        "last_login_at": _row_get(urow, "last_login_at"),
        "last_platform": _row_get(last_session, "platform"),
        "last_ip": _row_get(last_session, "ip_address"),
        "last_device": device if isinstance(device, dict) else {},
        "country": _row_get(urow, "country"),
        "city": _row_get(urow, "city"),
        "device_count": device_count,
        "active_sessions_count": active_sessions,
        "generations_count": int(_row_get(urow, "generation_count") or 0),
        "tokens_spent": int(_row_get(urow, "tokens_used") or 0),
        "token_balance": int(_row_get(urow, "token_balance") or 0),
        "daily_tokens_used": int(_row_get(urow, "daily_tokens_used") or 0),
        "daily_tokens_limit": gallery_quota["daily_tokens"],
        "plan": _row_get(urow, "plan") or "mini",
        "gallery_enabled": bool(_row_get(urow, "gallery_enabled")),
        "gallery_access": bool(user_gallery_allowed(conn, iuid, legacy)),
        "daily_tokens": gallery_quota["daily_tokens"],
        "gallery_slots": gallery_quota["gallery_slots"],
        "gallery_used": gallery_quota["gallery_used"],
        "gallery_free": gallery_quota["gallery_free"],
        "gallery_full": gallery_quota["gallery_full"],
        "status": "banned" if _row_get(urow, "banned") else "active",
        "role": _row_get(urow, "role"),
    }


@app.get("/api/admin/dashboard-v2")
async def admin_dashboard_v2(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    now_iso = datetime.now(timezone.utc).isoformat()
    today = _today_start_iso()
    with db() as conn:
        def scalar(q, p=()):
            return conn.execute(q, p).fetchone()["c"]
        users_where = "internal_user_id IS NOT NULL"
        total_users = scalar(f"SELECT COUNT(*) AS c FROM users WHERE {users_where}")
        providers = {r["provider"]: r["c"] for r in conn.execute(
            "SELECT provider, COUNT(DISTINCT internal_user_id) AS c FROM auth_identities GROUP BY provider")}
        platforms = {(r["platform"] or "unknown"): r["c"] for r in conn.execute(
            "SELECT platform, COUNT(DISTINCT internal_user_id) AS c FROM auth_sessions GROUP BY platform")}
        login_events = "('login_succeeded','password_login_succeeded','password_register_succeeded')"
        data = {
            "total_users": total_users,
            "active_today": scalar(f"SELECT COUNT(*) AS c FROM users WHERE {users_where} AND last_seen_at >= ?", (today,)),
            "active_7d": scalar(f"SELECT COUNT(*) AS c FROM users WHERE {users_where} AND last_seen_at >= ?", (_iso_days_ago(7),)),
            "active_30d": scalar(f"SELECT COUNT(*) AS c FROM users WHERE {users_where} AND last_seen_at >= ?", (_iso_days_ago(30),)),
            "new_today": scalar(f"SELECT COUNT(*) AS c FROM users WHERE {users_where} AND created_at >= ?", (today,)),
            "new_7d": scalar(f"SELECT COUNT(*) AS c FROM users WHERE {users_where} AND created_at >= ?", (_iso_days_ago(7),)),
            "logins_today": scalar(f"SELECT COUNT(*) AS c FROM event_logs WHERE event_name IN {login_events} AND created_at >= ?", (today,)),
            "generations_today": scalar("SELECT COUNT(*) AS c FROM jobs WHERE created_at >= ?", (today,)),
            "generations_total": scalar("SELECT COUNT(*) AS c FROM jobs"),
            "tokens_spent_total": int(conn.execute("SELECT COALESCE(SUM(-delta),0) AS c FROM token_ledger WHERE delta < 0").fetchone()["c"]),
            "users_by_provider": providers,
            "users_by_platform": platforms,
            "sessions_active": scalar("SELECT COUNT(*) AS c FROM auth_sessions WHERE revoked_at IS NULL AND expires_at > ?", (now_iso,)),
            "failed_logins_24h": scalar("SELECT COUNT(*) AS c FROM auth_login_attempts WHERE success = 0 AND created_at >= ?", (_iso_days_ago(1),)),
            "banned_users": scalar("SELECT COUNT(*) AS c FROM users WHERE banned = 1"),
        }
    return {"ok": True, "dashboard": data}


@app.get("/api/admin/users-analytics-v2")
async def admin_users_analytics_v2(request: Request, q: str | None = None, provider: str | None = None,
                                   status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    require_trusted_admin(request)
    limit = _clamp_limit(limit)
    offset = max(0, int(offset))
    now_iso = datetime.now(timezone.utc).isoformat()
    clauses = ["u.internal_user_id IS NOT NULL"]
    params: list[Any] = []
    if status == "banned":
        clauses.append("u.banned = 1")
    elif status == "active":
        clauses.append("u.banned = 0")
    if provider:
        clauses.append("EXISTS (SELECT 1 FROM auth_identities ai WHERE ai.internal_user_id = u.internal_user_id AND ai.provider = ?)")
        params.append(provider)
    if q:
        like = f"%{q}%"
        clauses.append("(u.public_user_code LIKE ? OR u.display_name LIKE ? OR u.username LIKE ? OR u.email LIKE ? OR u.id LIKE ?)")
        params += [like, like, like, like, like]
    where = "WHERE " + " AND ".join(clauses)
    items = []
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM users u {where}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM users u {where} ORDER BY u.last_seen_at DESC, u.created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        for r in rows:
            items.append(admin_user_analytics_row(conn, r, now_iso))
    return {"ok": True, "items": items, "limit": limit, "offset": offset, "total": total}


@app.get("/api/admin/users/{internal_user_id}/analytics-v2")
async def admin_user_detail_analytics_v2(internal_user_id: str, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    now_iso = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        urow = conn.execute("SELECT * FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
        if urow is None:
            raise HTTPException(404, "User not found.")
        summary = admin_user_analytics_row(conn, urow, now_iso)
        identities = conn.execute(
            "SELECT provider, provider_user_id, provider_username, provider_email, provider_first_name, "
            "provider_last_name, provider_phone, provider_language_code, linked_at, verified_at, last_login_at, "
            "(raw_profile_json IS NOT NULL AND raw_profile_json != '') AS has_raw_profile "
            "FROM auth_identities WHERE internal_user_id = ?", (internal_user_id,),
        ).fetchall()
        sessions = conn.execute(
            "SELECT id, provider, platform, ip_address, created_at, last_seen_at, expires_at, revoked_at, revoke_reason, metadata_json "
            "FROM auth_sessions WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 30", (internal_user_id,),
        ).fetchall()
        devices = conn.execute(
            "SELECT installation_id, anonymous_id, platform, storage_type, first_seen_at, last_seen_at, metadata_json "
            "FROM device_installations WHERE internal_user_id = ? ORDER BY last_seen_at DESC LIMIT 30", (internal_user_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT event_name, platform, created_at FROM event_logs WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 30", (internal_user_id,),
        ).fetchall()
        sec = conn.execute(
            "SELECT severity, event_type, ip_address, created_at FROM security_events WHERE internal_user_id = ? ORDER BY created_at DESC LIMIT 30", (internal_user_id,),
        ).fetchall()
        ledger = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN delta<0 THEN -delta ELSE 0 END),0) AS spent, COUNT(*) AS entries "
            "FROM token_ledger WHERE user_id = ?", (urow["id"],),
        ).fetchone()
        ledger_rows = conn.execute(
            "SELECT id, delta, reason, meta_json, created_at FROM token_ledger WHERE user_id = ? ORDER BY created_at DESC LIMIT 30",
            (urow["id"],),
        ).fetchall()
        jobs_rows = conn.execute(
            "SELECT id, mode, provider, status, prompt_original, result_image_id, error_message, settings_json, created_at, completed_at "
            "FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT 30",
            (urow["id"],),
        ).fetchall()
        image_rows = conn.execute(
            "SELECT id, job_id, url, thumbnail_url, mode, provider, prompt_original, is_favorite, created_at "
            "FROM images WHERE user_id = ? AND (deleted_at IS NULL OR deleted_at = '') ORDER BY created_at DESC LIMIT 30",
            (urow["id"],),
        ).fetchall()
        audits = conn.execute(
            "SELECT action, actor_internal_user_id, after_json, created_at FROM audit_logs WHERE target_internal_user_id = ? ORDER BY created_at DESC LIMIT 20", (internal_user_id,),
        ).fetchall()
        failed_login_count = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_login_attempts WHERE internal_user_id = ? AND success = 0", (internal_user_id,),
        ).fetchone()["c"]
        password_reset_count = conn.execute(
            "SELECT COUNT(*) AS c FROM security_events WHERE internal_user_id = ? AND event_type LIKE '%password_reset%'", (internal_user_id,),
        ).fetchone()["c"]
        ban_count = conn.execute(
            "SELECT COUNT(*) AS c FROM audit_logs WHERE target_internal_user_id = ? AND action IN ('admin_block_user','admin_unblock_user')", (internal_user_id,),
        ).fetchone()["c"]
        role_change_count = conn.execute(
            "SELECT COUNT(*) AS c FROM audit_logs WHERE target_internal_user_id = ? AND action = 'admin_change_role'", (internal_user_id,),
        ).fetchone()["c"]
        session_revocation_count = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_sessions WHERE internal_user_id = ? AND revoked_at IS NOT NULL", (internal_user_id,),
        ).fetchone()["c"]
        suspicious_ip_count = conn.execute(
            "SELECT COUNT(DISTINCT ip_address) AS c FROM security_events WHERE internal_user_id = ? AND severity IN ('warning','critical') AND ip_address IS NOT NULL",
            (internal_user_id,),
        ).fetchone()["c"]
        billing = _billing_projection(conn, internal_user_id)
        loyalty = _loyalty_projection(conn, internal_user_id)
    image_by_job = {r["job_id"]: r for r in image_rows if r["job_id"]}
    spent_by_job: dict[str, int] = {}
    for r in ledger_rows:
        meta = safe_ledger_metadata(r["meta_json"])
        job_id = meta.get("job_id")
        if job_id and int(r["delta"]) < 0:
            spent_by_job[str(job_id)] = abs(int(r["delta"]))
    return {
        "ok": True,
        "summary": summary,
        **billing,
        **loyalty,
        "identities": [{
            "provider": r["provider"], "provider_user_id": r["provider_user_id"],
            "provider_username": r["provider_username"], "provider_email": mask_email(r["provider_email"]),
            "first_name": r["provider_first_name"], "last_name": r["provider_last_name"],
            "phone": mask_phone(r["provider_phone"]) if r["provider_phone"] else None,
            "language_code": r["provider_language_code"], "linked_at": r["linked_at"],
            "verified_at": r["verified_at"], "last_login_at": r["last_login_at"],
            "has_raw_profile": bool(r["has_raw_profile"]),
        } for r in identities],
        "sessions": [{
            "id": r["id"], "provider": r["provider"], "platform": r["platform"], "ip_address": r["ip_address"],
            "device": safe_device_from_metadata(r["metadata_json"]),
            "created_at": r["created_at"], "last_seen_at": r["last_seen_at"], "expires_at": r["expires_at"],
            "revoked_at": r["revoked_at"], "revoke_reason": r["revoke_reason"],
        } for r in sessions],
        "devices": [{
            "installation_id": short_public_id(r["installation_id"]), "anonymous_id": short_public_id(r["anonymous_id"]),
            "platform": r["platform"], "storage_type": r["storage_type"],
            "first_seen_at": r["first_seen_at"], "last_seen_at": r["last_seen_at"],
            "metadata": {**sanitize_device_metadata(r["metadata_json"]), **safe_device_from_metadata(r["metadata_json"])},
            "mac_status": "MAC: недоступен",
        } for r in devices],
        "recent_generations": [{
            "id": short_public_id(r["id"]),
            "mode": r["mode"],
            "provider": r["provider"],
            "model": (safe_json_load(r["settings_json"]) or {}).get("modelProfile") if isinstance(safe_json_load(r["settings_json"]) or {}, dict) else None,
            "status": r["status"],
            "prompt": truncate_admin_text(r["prompt_original"], 180),
            "token_cost": spent_by_job.get(r["id"]),
            "created_at": r["created_at"],
            "completed_at": r["completed_at"],
            "result_image_id": short_public_id(r["result_image_id"]),
            "result_image_url": safe_app_url(_row_get(image_by_job.get(r["id"]), "url")),
            "error": safe_error_message(r["error_message"]),
        } for r in jobs_rows],
        "recent_gallery": [{
            "id": short_public_id(r["id"]),
            "thumbnail_url": safe_app_url(r["thumbnail_url"]),
            "job_id": short_public_id(r["job_id"]),
            "mode": r["mode"],
            "provider": r["provider"],
            "prompt": truncate_admin_text(r["prompt_original"], 140),
            "created_at": r["created_at"],
            "favorite": bool(r["is_favorite"]),
        } for r in image_rows if safe_app_url(r["thumbnail_url"])],
        "token_ledger_recent": [{
            "id": short_public_id(r["id"]),
            "delta": int(r["delta"]),
            "reason": r["reason"],
            "source": (safe_ledger_metadata(r["meta_json"]).get("provider") or r["reason"]),
            "job_id": short_public_id(safe_ledger_metadata(r["meta_json"]).get("job_id")),
            "admin_action": "admin_adjust_tokens" if r["reason"] == "admin_adjust" else None,
            "created_at": r["created_at"],
            "metadata": safe_ledger_metadata(r["meta_json"]),
        } for r in ledger_rows],
        "recent_events": [{"event_name": r["event_name"], "platform": r["platform"], "created_at": r["created_at"]} for r in events],
        "recent_security_events": [{"severity": r["severity"], "event_type": r["event_type"], "ip_address": r["ip_address"], "created_at": r["created_at"]} for r in sec],
        "token_summary": {"spent": int(ledger["spent"]), "entries": int(ledger["entries"]), "balance": int(_row_get(urow, "token_balance") or 0)},
        "security_summary": {
            "failed_login_count": int(failed_login_count),
            "password_reset_count": int(password_reset_count),
            "ban_count": int(ban_count),
            "role_change_count": int(role_change_count),
            "session_revocation_count": int(session_revocation_count),
            "suspicious_ip_count": int(suspicious_ip_count),
        },
        "admin_actions": [{"action": r["action"], "actor": (r["actor_internal_user_id"] or "")[:8], "reason": truncate_admin_text((safe_json_load(r["after_json"]) or {}).get("reason"), 80), "created_at": r["created_at"]} for r in audits],
    }


@app.get("/api/admin/diagnostics-v2")
async def admin_diagnostics_v2(request: Request) -> dict[str, Any]:
    """Safe admin-only environment diagnostics (Phase 20C.2). No secrets: only the DB
    file basename, build label, and mode — enough to see why local vs prod differ."""
    admin = require_trusted_admin(request)
    with db() as conn:
        urow = conn.execute(
            "SELECT public_user_code FROM users WHERE internal_user_id = ?", (admin["internal_user_id"],)
        ).fetchone()
        user_count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    return {
        "ok": True,
        "backend_build": APP_BUILD,
        "db_file": DB_PATH.name,  # basename only — never the full path
        "user_count": user_count,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "auth_mode": "trusted_cookie_session",
        "admin_role": "admin",
        "admin_user_code": _row_get(urow, "public_user_code"),
        "admin_provider": admin.get("provider"),
    }


@app.post("/api/auth/session/refresh-v2")
async def auth_session_refresh_v2(req: SessionRefreshRequest, request: Request, response: Response) -> dict[str, Any]:
    # Body refresh_token wins; otherwise read it from the HttpOnly refresh cookie.
    refresh_token = req.refresh_token or _extract_refresh_token(request)
    if not refresh_token:
        raise HTTPException(401, "No refresh token provided.")
    new_session = refresh_auth_session(refresh_token, request)
    # Rotation: set fresh cookies; the old refresh cookie's token is now revoked.
    set_trusted_auth_cookies(
        response, new_session["session_token"], new_session["refresh_token"],
        new_session["expires_at"], new_session["refresh_expires_at"],
    )
    return {
        "session_token": new_session["session_token"],
        "refresh_token": new_session["refresh_token"],
        "expires_at": new_session["expires_at"],
    }


@app.post("/api/auth/session/logout-v2")
async def auth_session_logout_v2(req: SessionLogoutRequest, request: Request, response: Response) -> dict[str, Any]:
    # Body session_token wins; otherwise read it from the HttpOnly session cookie.
    token = req.session_token or _extract_session_token(request)
    if token:
        with db() as conn:
            row = conn.execute(
                "SELECT id FROM auth_sessions WHERE session_token_hash = ?", (hash_token(token),)
            ).fetchone()
            session_id = row["id"] if row else None
        if session_id:
            revoke_auth_session(session_id, reason="logout", request=request, event_type="logout")
    # Safe UX: always clear cookies and return ok, even if no token was found
    # (idempotent logout — never leaks whether a session existed).
    clear_trusted_auth_cookies(response)
    return {"ok": True}


@app.get("/api/auth/sessions-v2")
async def auth_sessions_list_v2(request: Request) -> dict[str, Any]:
    session = resolve_auth_session_from_request(request)
    now_iso = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, provider, platform, ip_address, user_agent_hash, created_at, last_seen_at, expires_at
            FROM auth_sessions
            WHERE internal_user_id = ? AND revoked_at IS NULL AND expires_at > ?
            ORDER BY created_at DESC
            """,
            (session["internal_user_id"], now_iso),
        ).fetchall()
    return {
        "ok": True,
        "currentSessionId": session["session_id"],
        "sessions": [dict(r) for r in rows],
    }


@app.get("/api/platforms")
async def platforms() -> dict[str, Any]:
    return {
        "web": {"ready": True, "url": mini_app_url("web")},
        "telegram": {
            "ready": True,
            "url": mini_app_url("telegram"),
            "commands": ["/start", "/app", "/help", "/gallery", "/settings"],
            "buttonText": "Открыть генератор",
        },
        "max": {
            "ready": True,
            "url": mini_app_url("max"),
            "commands": ["/start", "/app", "/help", "/gallery", "/settings"],
            "buttonText": "Открыть генератор",
        },
        "database": {"ready": DB_PATH.exists(), "path": str(DB_PATH)},
    }


@app.get("/api/bots/status")
async def bots_status() -> dict[str, Any]:
    return bot_status_payload()


@app.post("/api/bots/local-command")
async def bots_local_command(req: BotCommandRequest) -> dict[str, Any]:
    response = bot_command_response(req.platform, req.text)
    response["chatId"] = req.chatId
    response["delivery"] = "local"
    return response


@app.post("/api/telegram/send-message")
async def telegram_send_message(req: BotSendMessageRequest) -> dict[str, Any]:
    if not req.chatId:
        raise HTTPException(400, "chatId is required for Telegram sendMessage.")
    return await telegram_api("sendMessage", {"chat_id": req.chatId, "text": req.text})


@app.get("/api/telegram/me")
async def telegram_me() -> dict[str, Any]:
    return await telegram_api("getMe")


@app.post("/api/telegram/poll-once")
async def telegram_poll_once() -> dict[str, Any]:
    return await telegram_poll_once_from_api(timeout=0, limit=10)


@app.post("/api/telegram/set-webhook")
async def telegram_set_webhook() -> dict[str, Any]:
    public_url = os.getenv("BACKEND_PUBLIC_URL", "")
    if not public_url.startswith("https://"):
        raise HTTPException(400, "BACKEND_PUBLIC_URL must be an HTTPS URL for Telegram webhook mode.")
    return await telegram_api("setWebhook", {"url": f"{public_url.rstrip('/')}/api/telegram/webhook"})


@app.post("/api/telegram/configure-bot")
async def telegram_configure_bot() -> dict[str, Any]:
    commands = [
        {"command": "start", "description": "Открыть генератор"},
        {"command": "app", "description": "Открыть Mini App"},
        {"command": "help", "description": "Инструкция"},
        {"command": "gallery", "description": "Последние изображения"},
        {"command": "settings", "description": "Настройки"},
    ]
    result: dict[str, Any] = {"commands": await telegram_api("setMyCommands", {"commands": commands})}
    app_url = os.getenv("APP_PUBLIC_URL", "")
    if app_url.startswith("https://"):
        result["menuButton"] = await telegram_api(
            "setChatMenuButton",
            {"menu_button": {"type": "web_app", "text": "Открыть генератор", "web_app": {"url": app_url}}},
        )
    else:
        result["menuButton"] = {"ok": False, "reason": "APP_PUBLIC_URL must be HTTPS for Telegram Mini App menu button."}
    return result


@app.post("/api/telegram/delete-webhook")
async def telegram_delete_webhook() -> dict[str, Any]:
    return await telegram_api("deleteWebhook", {"drop_pending_updates": False})


@app.post("/api/max/send-message")
async def max_send_message(req: BotSendMessageRequest) -> dict[str, Any]:
    if not req.chatId and not req.userId:
        raise HTTPException(400, "chatId or userId is required for MAX messages.")
    params: dict[str, Any] = {}
    if req.chatId:
        params["chat_id"] = req.chatId
    if req.userId:
        params["user_id"] = req.userId
    return await max_api("POST", "/messages", {"text": req.text}, params=params)


@app.post("/api/gallery/{image_id}/send")
async def send_gallery_image(image_id: str, req: SendImageRequest, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        if not user_gallery_allowed(conn, trusted["internal_user_id"], user_id):
            raise HTTPException(403, "Gallery is not available for this plan.")
    if image_id not in images and DB_PATH.exists():
        load_db_state()
    if image_id not in images or images[image_id].get("userId", "demo_user") != user_id:
        raise HTTPException(404, "Image not found")
    image = images[image_id]
    text = f"Изображение готово: {image['url']}"
    if req.platform == "telegram":
        if TELEGRAM_BOT_TOKEN and req.chatId:
            return await telegram_api("sendMessage", {"chat_id": req.chatId, "text": text})
        return {"ok": True, "delivery": "local", "platform": "telegram", "text": text, "imageId": image_id}
    if MAX_BOT_TOKEN and (req.chatId or req.userId):
        params: dict[str, Any] = {}
        if req.chatId:
            params["chat_id"] = req.chatId
        if req.userId:
            params["user_id"] = req.userId
        return await max_api("POST", "/messages", {"text": text}, params=params)
    return {"ok": True, "delivery": "local", "platform": "max", "text": text, "imageId": image_id}


@app.get("/api/max/me")
async def max_me() -> dict[str, Any]:
    return await max_api("GET", "/me")


@app.post("/api/max/poll-once")
async def max_poll_once() -> dict[str, Any]:
    return await max_poll_once_from_api(timeout=0, limit=10)


@app.post("/api/max/set-webhook")
async def max_set_webhook() -> dict[str, Any]:
    public_url = os.getenv("BACKEND_PUBLIC_URL", "")
    if not public_url.startswith("https://"):
        raise HTTPException(400, "BACKEND_PUBLIC_URL must be an HTTPS URL for MAX webhook mode.")
    body: dict[str, Any] = {
        "url": f"{public_url.rstrip('/')}/api/max/webhook",
        "update_types": ["message_created", "bot_started", "message_callback"],
    }
    if MAX_WEBHOOK_SECRET:
        body["secret"] = MAX_WEBHOOK_SECRET
    return await max_api("POST", "/subscriptions", body)


@app.post("/api/translate")
async def translate(req: TranslateRequest) -> dict[str, str]:
    if req.target == "en" and not req.text.isascii():
        translated = f"{req.text} (translated to English draft)"
    elif req.target == "ru" and req.text.isascii():
        translated = f"{req.text} (черновой перевод на русский)"
    else:
        translated = req.text
    return {"translated": translated}


@app.get("/api/presets")
async def get_presets() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT id, name_ru, name_en, mode FROM presets WHERE is_visible = 1 ORDER BY id").fetchall()
    return [dict(row) for row in rows]


@app.get("/api/admin/summary")
async def admin_summary(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    failed = [item for item in jobs.values() if item["status"] == "failed"]
    completed_today = [item for item in jobs.values() if item["status"] == "completed"]
    now_iso = datetime.now(timezone.utc).isoformat()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with db() as conn:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        job_db_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        image_count = conn.execute("SELECT COUNT(*) FROM images WHERE deleted_at IS NULL OR deleted_at = ''").fetchone()[0]
        token_total = conn.execute("SELECT COALESCE(SUM(token_balance), 0) FROM users").fetchone()[0]
        tokens_spent = conn.execute("SELECT COALESCE(SUM(-delta), 0) FROM token_ledger WHERE delta < 0").fetchone()[0]
        active_today = conn.execute("SELECT COUNT(*) FROM users WHERE last_seen_at >= ?", (today_start,)).fetchone()[0]
        generations_today = conn.execute("SELECT COUNT(*) FROM jobs WHERE created_at >= ?", (today_start,)).fetchone()[0]
        active_sessions = conn.execute("SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL AND expires_at > ?", (now_iso,)).fetchone()[0]
        errors_24h = conn.execute("SELECT COUNT(*) FROM auth_login_attempts WHERE success = 0 AND created_at >= ?", (today_start,)).fetchone()[0]
        settings_row = conn.execute("SELECT value_json FROM admin_settings WHERE key = 'finance'").fetchone()
        finance = json.loads(settings_row["value_json"]) if settings_row else {"tokenRevenue": 0, "tokenCost": 0, "electricity": 0, "promoBudget": 0}
    return {
        "users": user_count,
        "activeToday": active_today,
        "jobs": max(len(jobs), job_db_count),
        "generationsToday": generations_today,
        "images": image_count,
        "errors": len(failed),
        "errors24h": errors_24h,
        "completedToday": len(completed_today),
        "tokenBalanceTotal": token_total,
        "tokensSpentTotal": tokens_spent,
        "activeSessions": active_sessions,
        "finance": finance,
        "availableModels": ["local_flux_klein", "server_flux_klein", "openrouter_cloud"],
        "loras": ["lora_arcane", "product_photo"],
        "recentErrors": [item.get("error") for item in failed[-5:]],
        "queue": [{k: v for k, v in item.items() if k != "request"} for item in jobs.values() if item.get("status") in ("queued", "running", "uploading", "sent_to_comfyui")],
        "rateLimits": rate_limits,
    }


@app.get("/api/admin/users")
async def admin_users(request: Request) -> list[dict[str, Any]]:
    require_trusted_admin(request)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, telegram_id, max_id, username, first_name, last_name, middle_name, phone, email, language, role, plan, token_balance,
                   gallery_enabled, country, city, timezone, total_time_seconds, generation_count, tokens_used,
                   promo_used_count, referrals_count, banned, last_seen_at, created_at, last_login_at
            FROM users ORDER BY last_login_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/admin/users")
async def admin_create_user(req: AdminUserRequest, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO users (id, username, first_name, last_name, middle_name, phone, email, country, city, language, role, plan, token_balance, gallery_enabled, created_at, last_login_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ru', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                username=COALESCE(excluded.username, users.username),
                first_name=COALESCE(excluded.first_name, users.first_name),
                last_name=COALESCE(excluded.last_name, users.last_name),
                middle_name=COALESCE(excluded.middle_name, users.middle_name),
                phone=COALESCE(excluded.phone, users.phone),
                email=COALESCE(excluded.email, users.email),
                country=COALESCE(excluded.country, users.country),
                city=COALESCE(excluded.city, users.city),
                role=excluded.role,
                plan=excluded.plan,
                token_balance=excluded.token_balance,
                gallery_enabled=excluded.gallery_enabled,
                last_login_at=excluded.last_login_at
            """,
            (req.userId, req.username, req.firstName, req.lastName, req.middleName, req.phone, req.email, req.country, req.city, req.role, req.plan, req.tokenBalance, int(req.galleryEnabled), now, now),
        )
        conn.execute(
            "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, 'admin_register', '{}', ?)",
            (str(uuid.uuid4()), req.userId, req.tokenBalance, now),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (req.userId,)).fetchone()
    return {"ok": True, "user": dict(row)}


@app.patch("/api/admin/users/{user_id}")
async def admin_update_user(user_id: str, req: AdminUserUpdateRequest, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    updates: list[str] = []
    values: list[Any] = []
    if req.role is not None:
        updates.append("role = ?")
        values.append(req.role)
    if req.plan is not None:
        updates.append("plan = ?")
        values.append(req.plan)
    if req.tokenBalance is not None:
        updates.append("token_balance = ?")
        values.append(req.tokenBalance)
    if req.galleryEnabled is not None:
        updates.append("gallery_enabled = ?")
        values.append(int(req.galleryEnabled))
    if req.banned is not None:
        updates.append("banned = ?")
        values.append(int(req.banned))
    if req.phone is not None:
        updates.append("phone = ?")
        values.append(req.phone)
    if req.firstName is not None:
        updates.append("first_name = ?")
        values.append(req.firstName)
    if req.lastName is not None:
        updates.append("last_name = ?")
        values.append(req.lastName)
    if req.middleName is not None:
        updates.append("middle_name = ?")
        values.append(req.middleName)
    if req.email is not None:
        updates.append("email = ?")
        values.append(req.email)
    if req.country is not None:
        updates.append("country = ?")
        values.append(req.country)
    if req.city is not None:
        updates.append("city = ?")
        values.append(req.city)
    if not updates:
        raise HTTPException(400, "No updates provided.")
    with db() as conn:
        values.append(user_id)
        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found.")
    return {"ok": True, "user": dict(row)}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: str, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    protected = {"demo_user", "web_admin"}
    if user_id in protected:
        raise HTTPException(400, "Protected user cannot be disabled.")
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute("SELECT id, internal_user_id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found.")
        iuid = row["internal_user_id"]
        # Safe-disable: set banned, disable password, revoke sessions — keep identity for audit
        conn.execute("UPDATE users SET banned = 1 WHERE id = ?", (user_id,))
        conn.execute(
            "UPDATE auth_passwords SET disabled_at = ? WHERE internal_user_id = ? AND disabled_at IS NULL",
            (now, iuid),
        )
        conn.execute(
            "UPDATE auth_sessions SET revoked_at = ?, revoke_reason = 'admin_disable_user' WHERE internal_user_id = ? AND revoked_at IS NULL",
            (now, iuid),
        )
        try:
            record_security_event(conn, "admin_user_disabled", severity="warning", internal_user_id=iuid, request=request)
        except Exception:
            pass
        try:
            record_event_log("admin_disable_user", internal_user_id=iuid, legacy_user_id=user_id, platform="web")
        except Exception:
            pass
    return {"ok": True, "disabled": user_id}


@app.get("/api/admin/users/{user_id}/history")
async def admin_user_history(user_id: str, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "User not found.")
        user_jobs = conn.execute("SELECT id, mode, provider, status, prompt_original, result_image_id, error_message, created_at, completed_at FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT 100", (user_id,)).fetchall()
        user_images = conn.execute("SELECT id, url, thumbnail_url, mode, provider, prompt_original, created_at FROM images WHERE user_id = ? ORDER BY created_at DESC LIMIT 100", (user_id,)).fetchall()
        ledger = conn.execute("SELECT id, delta, reason, meta_json, created_at FROM token_ledger WHERE user_id = ? ORDER BY created_at DESC LIMIT 100", (user_id,)).fetchall()
    return {
        "ok": True,
        "user": dict(user),
        "jobs": [dict(row) for row in user_jobs],
        "images": [dict(row) for row in user_images],
        "ledger": [dict(row) for row in ledger],
    }


@app.get("/api/admin/promos")
async def admin_promos(request: Request) -> list[dict[str, Any]]:
    require_trusted_admin(request)
    with db() as conn:
        rows = conn.execute("SELECT code, tokens, activation_limit, activation_count, enabled, created_at, updated_at FROM promo_codes ORDER BY updated_at DESC").fetchall()
    return [dict(row) for row in rows]


@app.post("/api/admin/promos")
async def admin_create_promo(req: AdminPromoRequest, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    now = datetime.now(timezone.utc).isoformat()
    code = req.code.strip().upper()
    if not code:
        raise HTTPException(400, "Promo code is required.")
    with db() as conn:
        conn.execute(
            """
            INSERT INTO promo_codes (code, tokens, activation_limit, activation_count, enabled, created_at, updated_at)
            VALUES (?, ?, ?, 0, 1, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                tokens=excluded.tokens,
                activation_limit=excluded.activation_limit,
                enabled=1,
                updated_at=excluded.updated_at
            """,
            (code, req.tokens, req.activationLimit, now, now),
        )
        row = conn.execute("SELECT code, tokens, activation_limit, activation_count, enabled, created_at, updated_at FROM promo_codes WHERE code = ?", (code,)).fetchone()
    return {"ok": True, "promo": dict(row)}


@app.get("/api/admin/settings")
async def admin_get_settings(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    with db() as conn:
        rows = conn.execute("SELECT key, value_json FROM admin_settings").fetchall()
        settings = {row["key"]: json.loads(row["value_json"] or "{}") for row in rows}
        settings["tariffs"] = get_tariff_config(conn)
    return settings


@app.post("/api/admin/settings/{key}")
async def admin_save_settings(key: str, req: AdminSettingsRequest, request: Request) -> dict[str, Any]:
    if key == "tariffs":
        settings = normalize_tariffs(req.settings, strict=True)
    else:
        settings = req.settings
    require_trusted_admin(request)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO admin_settings (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
            """,
            (key, json.dumps(settings, ensure_ascii=False), now),
        )
    return {"ok": True, "key": key, "settings": settings}


async def compute_model_status() -> dict[str, Any]:
    """Cross-check every enabled model profile against the live ComfyUI install:
    which model/encoder/vae/lora files are present, whether base edit and pose can run,
    and exactly which files/nodes are missing. No guessing — all checked against ComfyUI."""
    with db() as conn:
        rows = conn.execute(
            "SELECT id, name, model_name, supports_pose, settings_json FROM model_profiles WHERE enabled = 1 AND provider = 'comfyui'"
        ).fetchall()

    comfy_up = await comfyui_available()
    try:
        models = await get_comfyui_models() if comfy_up else {}
    except Exception:
        models = {}
    nodes = await comfyui_node_names() if comfy_up else set()

    diffusion = models.get("diffusion_models", [])
    text_encoders = models.get("text_encoders", [])
    vaes = models.get("vaes", [])
    loras = models.get("loras", [])

    def has(items: list[str], needle: str) -> bool:
        n = (needle or "").lower()
        return bool(n) and any(n in item.lower() for item in items)

    selection = get_model_settings()
    profiles: list[dict[str, Any]] = []
    for row in rows:
        meta = json.loads(row["settings_json"] or "{}")
        # Only canonical MODEL PROFILEs (those carrying a variant fingerprint) appear in the
        # admin status; the legacy 'local_flux_klein' alias is kept for back-compat but hidden.
        if not meta.get("variant"):
            continue
        pose_meta = meta.get("pose", {}) or {}
        unet_ok = (row["model_name"] in diffusion)
        te_ok = has(text_encoders, meta.get("text_encoder", ""))
        vae_ok = has(vaes, meta.get("vae", "flux2-vae"))
        faceswap_ok = has(loras, meta.get("faceswap_lora", ""))

        missing: list[str] = []
        if not unet_ok:
            missing.append(row["model_name"])
        if not te_ok and meta.get("text_encoder"):
            missing.append(meta["text_encoder"])
        if not vae_ok:
            missing.append(meta.get("vae", "flux2-vae.safetensors"))

        base_edit_ok = unet_ok and te_ok and vae_ok

        pose_missing: list[str] = []
        pose_supported = bool(row["supports_pose"]) and bool(pose_meta.get("supported"))
        pose_available = False
        if pose_supported:
            pose_lora = pose_meta.get("lora", "")
            pose_node = pose_meta.get("preprocessor_node", "DWPreprocessor")
            lora_ok = has(loras, pose_lora)
            node_ok = pose_node in nodes
            if not lora_ok:
                pose_missing.append(pose_lora)
            if not node_ok:
                pose_missing.append(f"ComfyUI node: {pose_node}")
            pose_available = base_edit_ok and lora_ok and node_ok

        profiles.append({
            "id": row["id"],
            "name": row["name"],
            "modelName": row["model_name"],
            "installed": unet_ok,
            "baseEdit": "available" if base_edit_ok else "missing",
            "supportsPose": pose_supported,
            "pose": ("available" if pose_available else "missing"),
            "requiredNode": meta.get("node", "FluxKleinOneNode"),
            "faceswapLora": "available" if faceswap_ok else "missing",
            "missingFiles": missing,
            "poseMissing": pose_missing,
        })

    return {
        "comfyuiAvailable": comfy_up,
        "editModelProfile": selection.get("editModelProfile"),
        "poseModelProfile": selection.get("poseModelProfile") or "",
        "profiles": profiles,
    }


@app.get("/api/admin/model-status")
async def admin_model_status(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    return await compute_model_status()


# ── Админ → Модели v2 ───────────────────────────────────────────────────────
# Provider-aware каталог: local ComfyUI и OpenRouter — разные слои. Реальные данные:
# наличие локальных файлов/нод (ComfyUI), скан LoRA, готовность pose, наличие ключа
# OpenRouter. Тарифная матрица, маршруты и цены — admin-конфиг (дефолты пересчитываются,
# переопределения хранятся в admin_settings и НЕ ломают estimate_token_cost генерации).

# Известные LoRA: назначение / совместимость / целевой workflow.
KNOWN_LORAS: dict[str, dict[str, Any]] = {
    "bfs_head_v1_flux-klein_4b": {"purpose": "face / head consistency", "compatible": ["flux_klein_4b"], "routes": ["face", "edit"], "requires": []},
    "bfs_head_v1_flux-klein_9b": {"purpose": "face / identity", "compatible": ["flux_klein_9b"], "routes": ["face", "edit"], "requires": []},
    "refcontrol_v2_poses": {"purpose": "pose ref-control", "compatible": ["flux_klein_9b"], "routes": ["edit_pose"], "requires": ["DWPreprocessor"]},
}

OPENROUTER_CATALOG = [
    {"id": "openrouter_gpt_image", "provider": "openrouter", "displayName": "GPT Image", "modelId": "openai/gpt-image-1", "capabilities": ["txt2img", "image input", "transparent"], "tokenCost": 7, "minimumPlan": "pro"},
    {"id": "openrouter_gemini_image", "provider": "openrouter", "displayName": "Gemini Image", "modelId": "google/gemini-image", "capabilities": ["txt2img", "image input"], "tokenCost": 7, "minimumPlan": "pro"},
    {"id": "openrouter_recraft", "provider": "openrouter", "displayName": "Recraft", "modelId": "recraft/recraft-v3", "capabilities": ["logos", "vector", "style"], "tokenCost": 5, "minimumPlan": "pro"},
]

ROUTE_DEFS = [
    {"routeId": "text_to_image", "displayName": "Текст → Изо", "icon": "T"},
    {"routeId": "image_to_image", "displayName": "Изо → Изо", "icon": "I"},
    {"routeId": "edit", "displayName": "Редактор", "icon": "E"},
    {"routeId": "edit_pose", "displayName": "Редактор - поза", "icon": "P"},
    {"routeId": "face", "displayName": "Лицо → Изо", "icon": "F"},
]


async def scan_loras() -> list[dict[str, Any]]:
    """Реальный скан LoRA из ComfyUI (или пусто, если недоступен) + сопоставление с
    известными назначениями. Незнакомые файлы помечаются untested."""
    try:
        models = await get_comfyui_models()
    except Exception:
        models = {}
    files = models.get("loras", [])
    nodes = await comfyui_node_names()
    out: list[dict[str, Any]] = []
    for f in files:
        base = f.lower()
        meta = None
        for key, m in KNOWN_LORAS.items():
            if key.lower() in base:
                meta = m
                break
        if meta:
            requires_ok = all(n in nodes for n in meta["requires"])
            status = "active" if (meta["routes"] == ["edit_pose"] and requires_ok) else ("found" if requires_ok else "missing")
            out.append({
                "fileName": f, "purpose": meta["purpose"], "compatible": meta["compatible"],
                "routes": meta["routes"], "requires": meta["requires"], "status": status,
            })
        else:
            # Не относится к klein (например wan/video LoRA) — показываем как untested style/other.
            if any(k in base for k in ("klein", "flux", "style", "lora")):
                out.append({"fileName": f, "purpose": "стиль / прочее (проверить)", "compatible": [], "routes": [], "requires": [], "status": "untested"})
    return out


@app.get("/api/admin/loras")
async def admin_loras(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    return {"loras": await scan_loras()}


def _saved_setting(key: str) -> dict[str, Any]:
    try:
        with db() as conn:
            row = conn.execute("SELECT value_json FROM admin_settings WHERE key = ?", (key,)).fetchone()
        if row:
            return json.loads(row["value_json"] or "{}")
    except Exception:
        pass
    return {}


def default_tariff_matrix() -> list[dict[str, Any]]:
    # Дефолтные правила доступности/цены (calculated). Переопределяются admin_settings 'tariff_matrix'.
    def cell(enabled, cost, default, formula):
        return {"enabled": enabled, "tokenCost": cost, "isDefault": default, "formula": formula}
    f4 = "txt 1 / img 2 / refs +1"
    f9 = "txt 3 / img 5 / pose 3"
    fo = "txt 7 / img 10 / refs +3"
    return [
        {"modelProfileId": "flux_klein_4b", "provider": "local", "displayName": "Flux 2 Klein 4B", "modelId": "comfyui:flux_klein_4b",
         "tariffs": {"free": cell(True, 1, True, f4), "basic": cell(True, 1, True, f4), "pro": cell(True, 1, True, f4), "admin": cell(True, 1, True, f4)}},
        {"modelProfileId": "flux_klein_9b", "provider": "local", "displayName": "Flux 2 Klein 9B", "modelId": "comfyui:flux_klein_9b",
         "tariffs": {"free": cell(False, 0, False, "скрыть"), "basic": cell(True, 3, False, f9), "pro": cell(True, 3, True, f9), "admin": cell(True, 3, False, f9)}},
        {"modelProfileId": "openrouter_gpt_image", "provider": "openrouter", "displayName": "GPT Image", "modelId": "openai/gpt-image-1",
         "tariffs": {"free": cell(False, 0, False, "Pro only"), "basic": cell(False, 0, False, "Pro only"), "pro": cell(True, 7, False, fo), "admin": cell(True, 7, False, fo)}},
        {"modelProfileId": "openrouter_gemini_image", "provider": "openrouter", "displayName": "Gemini Image", "modelId": "google/gemini-image",
         "tariffs": {"free": cell(False, 0, False, "Pro only"), "basic": cell(False, 0, False, "Pro only"), "pro": cell(True, 7, False, "txt 7 / img 11 / refs +3"), "admin": cell(True, 7, False, "txt 7 / img 11 / refs +3")}},
        {"modelProfileId": "openrouter_recraft", "provider": "openrouter", "displayName": "Recraft", "modelId": "recraft/recraft-v3",
         "tariffs": {"free": cell(False, 0, False, "скрыть"), "basic": cell(False, 0, False, "скрыть"), "pro": cell(True, 5, False, "logos / style"), "admin": cell(True, 5, False, "logos / style")}},
    ]


def default_routes(model_status: dict[str, Any]) -> list[dict[str, Any]]:
    sel = get_model_settings()
    edit_model = sel.get("editModelProfile") or "flux_klein_9b"
    pose_model = sel.get("poseModelProfile") or "flux_klein_9b"
    base = {
        "text_to_image": {"provider": "local", "modelProfileId": "flux_klein_4b"},
        "image_to_image": {"provider": "local", "modelProfileId": "flux_klein_4b"},
        "edit": {"provider": "local", "modelProfileId": edit_model},
        # Pose ВСЕГДА Local ComfyUI → 9B + DWPose (не OpenRouter). 4B не поддерживается.
        "edit_pose": {"provider": "local", "modelProfileId": "flux_klein_9b", "locked": True, "label": "Flux 2 Klein 9B + DWPose"},
        "face": {"provider": "local", "modelProfileId": "flux_klein_9b"},
    }
    prof_by_id = {p["id"]: p for p in model_status.get("profiles", [])}
    out = []
    for r in ROUTE_DEFS:
        cfg = base[r["routeId"]]
        prof = prof_by_id.get(cfg["modelProfileId"])
        if r["routeId"] == "edit_pose":
            ok = bool(prof and prof.get("pose") == "available")
            state = "pose ready" if ok else "pose: нет зависимостей"
            status = "ok" if ok else "warn"
        else:
            ok = bool(prof and prof.get("baseEdit") == "available")
            state = "доступна" if ok else "недоступна"
            status = "ok" if ok else "bad"
        out.append({**r, **cfg, "state": state, "status": status})
    return out


@app.get("/api/admin/models-page")
async def admin_models_page(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    status = await compute_model_status()
    loras = await scan_loras()
    routes = _saved_setting("generation_routes").get("routes") or default_routes(status)
    matrix = _saved_setting("tariff_matrix").get("matrix") or default_tariff_matrix()
    openrouter_key = bool(os.getenv("OPENROUTER_API_KEY", "").strip())

    # Каталог: local (из profiles) + openrouter.
    catalog: list[dict[str, Any]] = []
    for p in status.get("profiles", []):
        caps = ["txt2img", "i2i", "editor"]
        if p.get("supportsPose"):
            caps = ["editor", "pose", "face"]
        catalog.append({"provider": "local", "displayName": p["name"], "modelId": p["modelName"],
                        "capabilities": caps, "cost": "локально", "margin": "высокая" if "4b" in p["id"] else "средняя",
                        "status": "active" if p["baseEdit"] == "available" else "missing"})
    for o in OPENROUTER_CATALOG:
        catalog.append({"provider": "openrouter", "displayName": o["displayName"], "modelId": o["modelId"],
                        "capabilities": o["capabilities"], "cost": "$ API", "margin": "контролировать",
                        "status": "active" if openrouter_key else "нужен API key"})

    # Сводка экономики (calculated).
    active_models = sum(1 for m in matrix if any(t.get("enabled") for t in m["tariffs"].values()))
    routes_assigned = sum(1 for r in routes if r.get("modelProfileId"))
    expensive = sum(1 for m in matrix if m["provider"] == "openrouter" and m["tariffs"].get("pro", {}).get("enabled"))
    conflicts = 0
    if any(l["status"] == "untested" for l in loras):
        conflicts += 1
    if not openrouter_key and any(m["provider"] == "openrouter" and any(t.get("enabled") for t in m["tariffs"].values()) for m in matrix):
        conflicts += 1

    user_choice = _saved_setting("user_choice") or {
        "simple": [
            {"key": "fast", "label": "Быстро", "model": "Flux 2 Klein 4B", "cost": 1, "plan": "default"},
            {"key": "quality", "label": "Качество", "model": "Flux 2 Klein 9B", "cost": 3, "plan": "Basic+"},
            {"key": "pose", "label": "Поза", "model": "9B + DWPose", "cost": 3, "plan": "Pro"},
        ],
        "pro": [
            {"label": "Flux 2 Klein 4B", "provider": "local", "cost": 1},
            {"label": "Flux 2 Klein 9B", "provider": "local", "cost": 3},
            {"label": "OpenRouter - GPT Image", "provider": "openrouter", "cost": 7},
            {"label": "OpenRouter - Gemini Image", "provider": "openrouter", "cost": 7},
            {"label": "Recraft", "provider": "openrouter", "cost": 5},
        ],
    }

    return {
        "economy": {"activeModels": active_models, "routesAssigned": f"{routes_assigned}/{len(ROUTE_DEFS)}", "expensiveRoutes": expensive, "priceConflicts": conflicts},
        "routes": routes,
        "userChoice": user_choice,
        "matrix": matrix,
        "catalog": catalog,
        "loras": loras,
        "comfyuiAvailable": status.get("comfyuiAvailable"),
        "openrouter": {"keyConfigured": openrouter_key},
        "comfyFiles": {"modelFile": "flux-2-klein-4b-fp8.safetensors", "textEncoder": "qwen_3_4b / qwen_3_8b", "vae": "flux2-vae.safetensors", "sampler": "er_sde", "width": 1024, "height": 1024, "steps": 4, "seed": "random"},
        "profiles": status.get("profiles", []),
    }


@app.get("/api/admin/jobs")
async def admin_jobs(request: Request) -> list[dict[str, Any]]:
    require_trusted_admin(request)
    return [{k: v for k, v in item.items() if k != "request"} for item in jobs.values()]


@app.post("/api/admin/limits")
async def admin_limits(req: AdminLimitRequest, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    rate_limits.update({"hourly": req.hourly, "daily": req.daily})
    return {"ok": True, "rateLimits": rate_limits}


@app.post("/api/telegram/webhook")
async def telegram_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        await handle_telegram_update(payload, send_replies=True)
    except Exception as exc:
        print("telegram webhook handler error", type(exc).__name__)
    return {"ok": True}


@app.post("/api/max/webhook")
async def max_webhook(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    if MAX_WEBHOOK_SECRET and request.headers.get("X-Max-Bot-Api-Secret") != MAX_WEBHOOK_SECRET:
        raise HTTPException(403, "Invalid MAX webhook secret.")
    try:
        await handle_max_update(payload, send_replies=True)
    except Exception as exc:
        print("max webhook handler error", type(exc).__name__)
    return {"ok": True}
