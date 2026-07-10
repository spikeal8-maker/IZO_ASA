from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import mimetypes
import os
import re
import secrets
import sqlite3
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import hmac
import hashlib
from urllib.parse import parse_qs, quote

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent
MEDIA = ROOT / "media"
MEDIA.mkdir(exist_ok=True)
STATIC_DIR = ROOT / "static"
GALLERY_PAGE_FILE = STATIC_DIR / "gallery" / "index.html"
FEED_PAGE_FILE = STATIC_DIR / "feed" / "index.html"
AVATAR_DIR = MEDIA / "avatars"
AVATAR_DIR.mkdir(exist_ok=True)
AVATAR_PRESET_DIR = next(
    (
        path
        for path in (
            ROOT.parent / "frontend" / "public" / "avatars",
            ROOT.parent / "frontend" / "dist" / "avatars",
        )
        if path.exists()
    ),
    None,
)
COMFYUI_INPUT_MAX_SIDE = max(512, min(2048, int(os.getenv("COMFYUI_INPUT_MAX_SIDE", "1536"))))
COMFYUI_FACE_INPUT_MAX_SIDE = max(512, min(COMFYUI_INPUT_MAX_SIDE, int(os.getenv("COMFYUI_FACE_INPUT_MAX_SIDE", "1024"))))
COMFYUI_FACE_SOURCE_MEGAPIXELS = max(0.15, min(1.0, float(os.getenv("COMFYUI_FACE_SOURCE_MEGAPIXELS", "0.35"))))
COMFYUI_INPUT_MIN_SIDE = 256
GALLERY_IMAGE_MAX_SIDE = max(1024, min(4096, int(os.getenv("GALLERY_IMAGE_MAX_SIDE", "2048"))))
GALLERY_IMAGE_WEBP_QUALITY = max(70, min(95, int(os.getenv("GALLERY_IMAGE_WEBP_QUALITY", "90"))))
SOURCE_THUMB_MAX_SIDE = max(192, min(768, int(os.getenv("SOURCE_THUMB_MAX_SIDE", "384"))))
SOURCE_THUMB_WEBP_QUALITY = max(55, min(90, int(os.getenv("SOURCE_THUMB_WEBP_QUALITY", "76"))))


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
mimetypes.add_type("image/webp", ".webp")

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
COMFYUI_FACE_TIMEOUT_SECONDS = max(60, min(COMFYUI_TIMEOUT_SECONDS, int(os.getenv("COMFYUI_FACE_TIMEOUT_SECONDS", "240"))))
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
OPENROUTER_TIMEOUT_SECONDS = max(30, min(300, int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "120"))))
CBR_DAILY_XML_URL = os.getenv("CBR_DAILY_XML_URL", "https://www.cbr.ru/scripts/XML_daily.asp")
USD_RUB_FALLBACK_URL = os.getenv("USD_RUB_FALLBACK_URL", "https://open.er-api.com/v6/latest/USD")


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
MAX_UPDATES_MODE = os.getenv("MAX_UPDATES_MODE", BOT_UPDATES_MODE).strip().lower()
if MAX_UPDATES_MODE not in {"webhook", "polling", "disabled"}:
    MAX_UPDATES_MODE = BOT_UPDATES_MODE
MAX_API_BASE_URL = os.getenv("MAX_API_BASE_URL", "https://platform-api2.max.ru")
MAX_WEBHOOK_URL = os.getenv("MAX_WEBHOOK_URL", "")
MAX_WEBHOOK_SECRET = os.getenv("MAX_WEBHOOK_SECRET", "")
_MAX_BOT_DEEP_LINK_CACHE: dict[str, Any] = {
    "attempted": False,
    "base": None,
    "source": "unresolved",
    "resolved": False,
    "api_status": None,
    "fields": [],
}
MAX_POLLING_DIAG: dict[str, Any] = {
    "lastPollAt": None,
    "lastPollStatus": None,
    "lastPollError": None,
    "lastPollMarker": None,
    "lastPollNextMarker": None,
    "lastRawCount": None,
    "lastBotStartedAt": None,
    "lastCallbackAt": None,
    "lastWebhookAt": None,
    "lastWebhookError": None,
    "subscriptionStatus": None,
    "webhookConfigured": False,
    "webhookUrlSet": False,
    "updateTypes": [],
}
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
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/media", StaticFiles(directory=MEDIA), name="media")
if AVATAR_PRESET_DIR is not None:
    app.mount("/avatars", StaticFiles(directory=AVATAR_PRESET_DIR), name="avatars")


@app.get("/", include_in_schema=False)
async def home_page_shell() -> FileResponse:
    return await gallery_page_shell()


@app.get("/gallery", include_in_schema=False)
async def gallery_page_shell() -> FileResponse:
    if not GALLERY_PAGE_FILE.exists():
        raise HTTPException(404, "Gallery page is not installed.")
    return FileResponse(
        GALLERY_PAGE_FILE,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/gallery/", include_in_schema=False)
async def gallery_page_shell_slash() -> FileResponse:
    return await gallery_page_shell()


@app.get("/feed", include_in_schema=False)
async def feed_page_shell() -> FileResponse:
    if not FEED_PAGE_FILE.exists():
        raise HTTPException(404, "Feed page is not installed.")
    return FileResponse(
        FEED_PAGE_FILE,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/feed/", include_in_schema=False)
async def feed_page_shell_slash() -> FileResponse:
    return await feed_page_shell()


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


class OpenRouterPriceModel(BaseModel):
    id: str
    name: str
    provider: str
    pricing_type: Literal["mp", "image", "token_estimate"]
    usd: float
    min_tokens: int = 1
    source: str = "admin_snapshot_2026-07-09"


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


class LinkEmailRequestCodeV2Request(BaseModel):
    email: str = ""


class LinkEmailVerifyCodeV2Request(BaseModel):
    challenge_id: str = ""
    code: str = ""


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
    plan: Literal["free", "mini", "plus", "pro", "business"]
    reason: str = ""


class AdminProfileV2Request(BaseModel):
    display_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    avatar_preset: str | None = None
    gender: Literal["female", "male"] | None = None
    age: int | None = None
    reason: str = ""


class AdminDeleteImageV2Request(BaseModel):
    reason: str = ""


class AdminConfigUiActionV2Request(BaseModel):
    reason: str = ""


class AdminMailTestV2Request(BaseModel):
    email: str = ""
    template: Literal["verify_email", "support_reply", "system_notice"] = "verify_email"


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
    gender: str | None = None
    age: int | str | None = None
    public_about: str | None = None
    public_website: str | None = None
    public_focus: str | None = None
    public_phone: str | None = None
    public_links: list[dict[str, str]] | None = None


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
    hourly: int = Field(default=0, ge=0, le=1000)
    daily: int = Field(default=0, ge=0, le=5000)


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
    plan: Literal["free", "mini", "plus", "pro", "business"] = "mini"
    tokenBalance: int = Field(default=50, ge=0, le=1_000_000)
    galleryEnabled: bool = True


class AdminUserUpdateRequest(BaseModel):
    role: Literal["user", "admin"] | None = None
    plan: Literal["free", "mini", "plus", "pro", "business"] | None = None
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


class AdminSecretKeyRequest(BaseModel):
    key: str = Field(min_length=12, max_length=512)


class AdminOpenRouterConfigRequest(BaseModel):
    config: dict[str, Any]


class AdminOpenRouterTestRequest(BaseModel):
    model: str = "black-forest-labs/flux.2-klein-4b"
    prompt: str = "A small clean test image of a lime green cube on a white background."
    width: int = Field(default=1024, ge=512, le=1536)
    height: int = Field(default=1024, ge=512, le=1536)


rate_limits = {"hourly": 0, "daily": 0}
PROMO_REFERRAL_REWARD_TOKENS = 50
PLAN_ORDER = ("free", "mini", "plus", "pro", "business")
DEFAULT_TARIFFS: dict[str, dict[str, Any]] = {
    "free": {"title": "Free", "note": "Базовый доступ", "price_rub_month": 0, "daily_tokens": 10, "openrouter_monthly_tokens": 0, "gallery_slots": 20, "quality_label": "Базовое качество", "model_defaults": {"fast": "server:local_flux_klein", "standard": "server:local_flux_klein", "max": "server:local_flux_klein"}, "queue_label": "Обычная", "pro_mode_enabled": 0, "allowed_resolutions": ["sq-1024"], "video_enabled": 0, "video_slots": 0},
    "mini": {"title": "Mini", "note": "Оптимальный старт", "price_rub_month": 490, "daily_tokens": 50, "openrouter_monthly_tokens": 100, "gallery_slots": 80, "quality_label": "HD", "model_defaults": {"fast": "server:local_flux_klein", "standard": "server:local_flux_klein", "max": "server:local_flux_klein"}, "queue_label": "Обычная", "pro_mode_enabled": 0, "allowed_resolutions": ["sq-1024", "h-1280", "v-720"], "video_enabled": 0, "video_slots": 0},
    "plus": {"title": "Plus", "note": "Больше возможностей", "price_rub_month": 990, "daily_tokens": 100, "openrouter_monthly_tokens": 250, "gallery_slots": 200, "quality_label": "Full HD", "model_defaults": {"fast": "server:local_flux_klein", "standard": "black-forest-labs/flux.2-klein-4b", "max": "openai/gpt-image-1-mini"}, "queue_label": "Ускоренная", "pro_mode_enabled": 1, "allowed_resolutions": ["sq-1024", "h-1280", "v-720", "h-1536", "v-1024"], "video_enabled": 0, "video_slots": 0},
    "pro": {"title": "Pro", "note": "Видео и приоритет", "price_rub_month": 1990, "daily_tokens": 200, "openrouter_monthly_tokens": 500, "gallery_slots": 500, "quality_label": "4K", "model_defaults": {"fast": "server:local_flux_klein", "standard": "black-forest-labs/flux.2-klein-4b", "max": "black-forest-labs/flux.2-pro"}, "queue_label": "Приоритетная", "pro_mode_enabled": 1, "allowed_resolutions": ["sq-1024", "h-1280", "v-720", "h-1536", "v-1024", "h-1920", "v-1088"], "video_enabled": 1, "video_slots": 10},
    "business": {"title": "Бизнес", "note": "Для команды и видео", "price_rub_month": 4990, "daily_tokens": 500, "openrouter_monthly_tokens": 1200, "gallery_slots": 500, "quality_label": "4K", "model_defaults": {"fast": "server:local_flux_klein", "standard": "black-forest-labs/flux.2-pro", "max": "openai/gpt-image-1"}, "queue_label": "Бизнес", "pro_mode_enabled": 1, "allowed_resolutions": ["sq-1024", "h-1280", "v-720", "h-1536", "v-1024", "h-1920", "v-1088"], "video_enabled": 1, "video_slots": 50},
}


@dataclass
class ComfyUIResult:
    prompt_id: str
    image_path: Path
    thumbnail_path: Path
    history: dict[str, Any]


@dataclass
class OpenRouterResult:
    image_path: Path
    thumbnail_path: Path
    response_id: str | None
    model: str
    usage: dict[str, Any]
    cost_usd: float | None
    raw: dict[str, Any]


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
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        # Some test/temp DBs may not support WAL; busy_timeout still protects
        # the common concurrent writer case without weakening correctness.
        pass
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

            CREATE TABLE IF NOT EXISTS image_sources (
                id TEXT PRIMARY KEY,
                image_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                source_image_id TEXT,
                source_kind TEXT NOT NULL,
                role TEXT,
                slot_index INTEGER NOT NULL DEFAULT 0,
                thumb_url TEXT NOT NULL,
                thumb_width INTEGER NOT NULL DEFAULT 0,
                thumb_height INTEGER NOT NULL DEFAULT 0,
                thumb_bytes INTEGER NOT NULL DEFAULT 0,
                children_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_image_sources_image
                ON image_sources(image_id, slot_index);
            CREATE INDEX IF NOT EXISTS idx_image_sources_user
                ON image_sources(user_id, created_at);

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

            CREATE TABLE IF NOT EXISTS admin_secrets (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
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
            "public_about": "TEXT",
            "public_website": "TEXT",
            "public_focus": "TEXT",
            "public_phone": "TEXT",
            "public_links_json": "TEXT",
            "gender": "TEXT",
            "age": "INTEGER",
            "daily_tokens_used": "INTEGER NOT NULL DEFAULT 0",
            "last_daily_reset": "TEXT",
            "openrouter_monthly_tokens_used": "INTEGER NOT NULL DEFAULT 0",
            "last_openrouter_month_reset": "TEXT",
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
        conn.execute(
            """
            INSERT OR IGNORE INTO users (
                id, username, first_name, display_name, language, role, plan,
                token_balance, gallery_enabled, internal_user_id, created_at, last_login_at
            )
            VALUES (
                'seed_editorial', 'seed_editorial', 'Выбор редакции', 'Выбор редакции',
                'ru', 'user', 'mini', 0, 0, 'seed_editorial', ?, ?
            )
            """,
            (now, now),
        )

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

            -- Live Feed MVP: публикации из личной галереи + реакции (like/save).
            -- Additive-only. Публикация ссылается на существующую строку images;
            -- prompt_visibility: open | partial | hidden. status: published | hidden.
            CREATE TABLE IF NOT EXISTS feed_publications (
                id TEXT PRIMARY KEY,
                image_id TEXT NOT NULL UNIQUE,
                internal_user_id TEXT NOT NULL,
                legacy_user_id TEXT,
                title TEXT NOT NULL,
                description TEXT,
                prompt_visibility TEXT NOT NULL DEFAULT 'open',
                allow_recreate INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'published',
                view_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_feed_publications_status_created
                ON feed_publications(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_feed_publications_user
                ON feed_publications(internal_user_id);

            CREATE TABLE IF NOT EXISTS feed_reactions (
                publication_id TEXT NOT NULL,
                internal_user_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (publication_id, internal_user_id, kind)
            );
            CREATE INDEX IF NOT EXISTS idx_feed_reactions_publication
                ON feed_reactions(publication_id, kind);

            CREATE TABLE IF NOT EXISTS feed_author_follows (
                follower_internal_user_id TEXT NOT NULL,
                author_internal_user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (follower_internal_user_id, author_internal_user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_feed_author_follows_author
                ON feed_author_follows(author_internal_user_id);

            CREATE TABLE IF NOT EXISTS challenges (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                rules TEXT NOT NULL,
                prompt_hint TEXT,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                reward_pool INTEGER NOT NULL DEFAULT 0,
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS challenge_entries (
                id TEXT PRIMARY KEY,
                challenge_id TEXT NOT NULL,
                publication_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                judge_score REAL,
                final_score REAL,
                created_at TEXT NOT NULL,
                UNIQUE (challenge_id, publication_id)
            );
            CREATE INDEX IF NOT EXISTS idx_challenge_entries_challenge
                ON challenge_entries(challenge_id, status);

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

        # Feed media architecture: additive-only public feed asset metadata.
        # Some live DBs already have early feed columns, so check every column
        # individually. Originals stay in images; public feed variants live here.
        feed_publication_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(feed_publications)").fetchall()
        }
        for column, definition in {
            "feed_thumb_name": "TEXT",
            "feed_large_name": "TEXT",
            "feed_thumb_width": "INTEGER",
            "feed_thumb_height": "INTEGER",
            "feed_thumb_bytes": "INTEGER",
            "feed_large_width": "INTEGER",
            "feed_large_height": "INTEGER",
            "feed_large_bytes": "INTEGER",
            "media_ready_at": "TEXT",
            "media_error": "TEXT",
            "native_aspect_ratio": "TEXT",
            "orientation": "TEXT",
            "source_type": "TEXT",
            "source_label": "TEXT",
            "display_policy": "TEXT",
            "category": "TEXT",
            "remix_policy": "TEXT",
            "tags_json": "TEXT",
            "updated_at": "TEXT",
            "view_count": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if column not in feed_publication_columns:
                conn.execute(f"ALTER TABLE feed_publications ADD COLUMN {column} {definition}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feed_publications_media_ready "
            "ON feed_publications(status, media_ready_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feed_publications_category_ready_created "
            "ON feed_publications(category, status, media_ready_at, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feed_publications_legacy_ready_created "
            "ON feed_publications(legacy_user_id, status, media_ready_at, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_images_user_deleted_created "
            "ON images(user_id, deleted_at, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_images_user_favorite_deleted_created "
            "ON images(user_id, is_favorite, deleted_at, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_images_job_id "
            "ON images(job_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_image_sources_image "
            "ON image_sources(image_id, slot_index)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_image_sources_user "
            "ON image_sources(user_id, created_at)"
        )
        image_source_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(image_sources)").fetchall()
        }
        if "children_json" not in image_source_columns:
            conn.execute("ALTER TABLE image_sources ADD COLUMN children_json TEXT NOT NULL DEFAULT '[]'")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_user_created "
            "ON jobs(user_id, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_result_image "
            "ON jobs(result_image_id)"
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO challenges (
                id, title, description, rules, prompt_hint, category, status,
                reward_pool, starts_at, ends_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
            """,
            (
                "moscow_2120_week",
                "Москва 2120",
                "Покажите город будущего. Лучшие работы получают токены и место в витрине.",
                "Создайте образ Москвы будущего: город, транспорт, люди, архитектура или повседневная сцена. Без логотипов, текста на изображении и копирования чужих работ.",
                "Футуристическая Москва 2120 года, город будущего, выразительная архитектура, живые люди, кинематографичный свет",
                "challenge_moscow_2120",
                10000,
                "2026-07-01T00:00:00+00:00",
                "2026-07-14T23:59:59+00:00",
                now,
            ),
        )

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


def _safe_country_code(value: str | None) -> str | None:
    code = (value or "").strip().upper()
    if code == "XX":
        return None
    return code if re.fullmatch(r"[A-Z]{2}", code) else None


def request_country_code(request: Request | None) -> str | None:
    """Best-effort country code for profile analytics from trusted CF headers only."""
    if not request or not TRUST_CLOUDFLARE_HEADERS:
        return None
    return _safe_country_code(request.headers.get("cf-ipcountry"))


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


def _fill_user_profile_if_empty(conn: sqlite3.Connection, legacy_user_id: str | None, user: dict[str, Any]) -> None:
    """Populate users.first_name/last_name/username from a verified provider
    profile, but only for columns that are currently empty — never overwrite a
    value the user has already set or customised."""
    if not legacy_user_id:
        return
    conn.execute(
        """
        UPDATE users SET
            first_name = COALESCE(NULLIF(first_name, ''), ?),
            last_name  = COALESCE(NULLIF(last_name, ''), ?),
            username   = COALESCE(NULLIF(username, ''), ?)
        WHERE id = ?
        """,
        (user.get("first_name"), user.get("last_name"), user.get("username"), legacy_user_id),
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
        avatar_url, avatar_preset = random_avatar_choice()
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (id, telegram_id, username, first_name, last_name, language, role, plan, gallery_enabled,
                 avatar_url, avatar_preset, created_at, last_login_at, internal_user_id)
            VALUES (?, ?, ?, ?, ?, ?, 'user', 'mini', 1, ?, ?, ?, ?, ?)
            """,
            (legacy_user_id, pid, username, first, last, lang or "ru", avatar_url, avatar_preset, now, now, internal_user_id),
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
    _fill_user_profile_if_empty(conn, legacy_user_id, user)
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
        avatar_url, avatar_preset = random_avatar_choice()
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (id, max_id, username, first_name, last_name, language, role, plan, gallery_enabled,
                 avatar_url, avatar_preset, created_at, last_login_at, internal_user_id)
            VALUES (?, ?, ?, ?, ?, ?, 'user', 'mini', 1, ?, ?, ?, ?, ?)
            """,
            (legacy_user_id, pid, username, first, last, lang or "ru", avatar_url, avatar_preset, now, now, internal_user_id),
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
    _fill_user_profile_if_empty(conn, legacy_user_id, user)
    return internal_user_id, legacy_user_id


def bot_login_deep_link(provider: Literal["telegram", "max"], token: str) -> str:
    payload = f"login_{token}"
    if provider == "max" and len(payload) > 128:
        print(f"MAX deep link payload too long length={len(payload)}")
        raise HTTPException(500, "config_error")
    if provider == "telegram":
        base = TELEGRAM_BOT_DEEP_LINK_BASE.strip()
        if base:
            sep = "&" if "?" in base else "?"
            return f"{base}{sep}start={payload}"
        if TELEGRAM_BOT_USERNAME.strip():
            return f"https://t.me/{TELEGRAM_BOT_USERNAME.strip().lstrip('@')}?start={payload}"
    base = resolve_max_bot_deep_link_base()
    if base:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}start={payload}"
    raise HTTPException(503, "provider_not_configured")


def _flatten_field_names(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        names: list[str] = []
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            names.append(name)
            names.extend(_flatten_field_names(child, name))
        return names
    if isinstance(value, list):
        names = []
        for child in value[:3]:
            names.extend(_flatten_field_names(child, f"{prefix}[]"))
        return names
    return []


def _pick_nested_string(value: Any, names: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for name in names:
            candidate = value.get(name)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for child in value.values():
            nested = _pick_nested_string(child, names)
            if nested:
                return nested
    elif isinstance(value, list):
        for child in value:
            nested = _pick_nested_string(child, names)
            if nested:
                return nested
    return None


def mask_short(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= 12:
        return text
    return f"{text[:4]}...{text[-4:]}"


def max_update_type(update: dict[str, Any]) -> str:
    for key in ("bot_started", "botStarted", "message_callback", "callback", "message_created", "message"):
        if isinstance(update.get(key), dict):
            return key
    value = update.get("update_type") or update.get("type")
    return str(value or "unknown")


def sanitized_payload_prefix(payload: str | None) -> str | None:
    if not isinstance(payload, str) or not payload:
        return None
    if payload.startswith("login_"):
        return "login_"
    if payload.startswith("approve:login_") or payload.startswith("approve:"):
        return "approve_"
    return payload[:16]


def _max_base_from_me_payload(payload: dict[str, Any]) -> str | None:
    link = _pick_nested_string(payload, ("link", "url", "deep_link", "deeplink", "bot_link"))
    if link and re.match(r"^https://(?:www\.)?max\.ru/[^\s]+$", link):
        return link
    nickname = _pick_nested_string(payload, ("username", "nickname", "nick", "login"))
    if not nickname:
        return None
    nickname = nickname.strip().lstrip("@").strip("/")
    if not re.match(r"^[A-Za-z0-9_.-]{2,64}$", nickname):
        return None
    return f"https://max.ru/{quote(nickname, safe='._-')}"


def resolve_max_bot_deep_link_base() -> str | None:
    explicit = MAX_BOT_DEEP_LINK_BASE.strip()
    if explicit:
        _MAX_BOT_DEEP_LINK_CACHE.update({
            "attempted": True,
            "base": explicit,
            "source": "env",
            "resolved": True,
            "api_status": None,
            "fields": [],
        })
        return explicit
    if not MAX_BOT_TOKEN:
        _MAX_BOT_DEEP_LINK_CACHE.update({
            "attempted": True,
            "base": None,
            "source": "failed",
            "resolved": False,
            "api_status": None,
            "fields": [],
        })
        return None
    if _MAX_BOT_DEEP_LINK_CACHE.get("attempted"):
        return _MAX_BOT_DEEP_LINK_CACHE.get("base")
    status: int | None = None
    fields: list[str] = []
    try:
        headers = {"Authorization": MAX_BOT_TOKEN, "Content-Type": "application/json"}
        with httpx.Client(timeout=10) as client:
            response = client.get(f"{MAX_API_BASE_URL.rstrip('/')}/me", headers=headers)
            status = response.status_code
            response.raise_for_status()
            payload = response.json()
        fields = sorted(set(_flatten_field_names(payload)))[:80]
        base = _max_base_from_me_payload(payload if isinstance(payload, dict) else {})
        if base:
            _MAX_BOT_DEEP_LINK_CACHE.update({
                "attempted": True,
                "base": base,
                "source": "api",
                "resolved": True,
                "api_status": status,
                "fields": fields,
            })
            print(f"MAX deep link base source=api; MAX bot nickname resolved=true; MAX API /me status={status}")
            return base
    except Exception as exc:
        print(f"MAX deep link base source=failed; MAX bot nickname resolved=false; MAX API /me status={status}; error={type(exc).__name__}")
        _MAX_BOT_DEEP_LINK_CACHE.update({
            "attempted": True,
            "base": None,
            "source": "failed",
            "resolved": False,
            "api_status": status,
            "fields": fields,
        })
        return None
    print(f"MAX deep link base source=failed; MAX bot nickname resolved=false; MAX API /me status={status}; fields={fields}")
    _MAX_BOT_DEEP_LINK_CACHE.update({
        "attempted": True,
        "base": None,
        "source": "failed",
        "resolved": False,
        "api_status": status,
        "fields": fields,
    })
    return None


def bot_login_available(provider: Literal["telegram", "max"]) -> bool:
    if provider == "telegram":
        return bool(TELEGRAM_BOT_TOKEN and (TELEGRAM_BOT_DEEP_LINK_BASE.strip() or TELEGRAM_BOT_USERNAME.strip()))
    return bool(MAX_BOT_TOKEN and resolve_max_bot_deep_link_base())


def auth_capabilities_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "password_login_available": True,
        "password_register_available": True,
        "email_otp_available": email_otp_available(),
        "bot_login": {
            "telegram_bot_login_available": bot_login_available("telegram"),
            "max_bot_login_available": bot_login_available("max"),
        },
    }


def set_bot_login_cookie(response: Response, provider: str, nonce: str, request: Request | None = None) -> None:
    common = trusted_cookie_common(request)
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


def _enrich_max_user_profile(user: dict[str, Any], update: dict[str, Any] | None) -> dict[str, Any]:
    """Map MAX-specific field names onto the canonical keys the identity upsert
    already reads (`photo_url`, `language_code`). MAX exposes the avatar as
    `avatar_url`/`full_avatar_url` on the user object and the locale as a
    top-level `user_locale` on the update. No-op when values are already present."""
    if not user.get("photo_url"):
        avatar = user.get("full_avatar_url") or user.get("avatar_url")
        if isinstance(avatar, str) and avatar.startswith("https://"):
            user["photo_url"] = avatar
    if not user.get("language_code") and isinstance(update, dict):
        locale = update.get("user_locale")
        if isinstance(locale, str) and locale.strip():
            user["language_code"] = locale.strip()
    return user


def max_user_from_update(update: dict[str, Any], message: dict[str, Any]) -> dict[str, Any] | None:
    user = max_user_from_message(message)
    if not user:
        for container_key in ("callback", "message_callback", "bot_started", "botStarted"):
            container = update.get(container_key)
            if not isinstance(container, dict):
                continue
            for user_key in ("user", "sender", "from"):
                candidate = container.get(user_key)
                if isinstance(candidate, dict):
                    provider_id = candidate.get("user_id") or candidate.get("id")
                    if provider_id:
                        user = dict(candidate)
                        user["id"] = provider_id
                        break
            if user is None:
                provider_id = container.get("user_id") or container.get("sender_id")
                if provider_id:
                    user = {"id": provider_id}
            if user is not None:
                break
    if not user:
        # Real MAX bot_started shape: user object and user_id live at the top level.
        top_user = update.get("user")
        if isinstance(top_user, dict):
            provider_id = top_user.get("user_id") or top_user.get("id")
            if provider_id:
                user = dict(top_user)
                user["id"] = provider_id
        if not user and update.get("user_id"):
            user = {"id": update.get("user_id")}
    if not user:
        return None
    return _enrich_max_user_profile(user, update)


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
        target_internal_user_id = _row_get(row, "internal_user_id")
        if target_internal_user_id:
            linked = link_verified_provider_identity(conn, target_internal_user_id, provider, provider_user, now)
            if linked is None:
                conn.execute(
                    "UPDATE auth_login_challenges SET status = 'conflict', approved_at = ? WHERE id = ? AND status = 'pending'",
                    (now, row["id"]),
                )
                record_login_attempt(conn, provider, False, identifier=provider_user_id, internal_user_id=target_internal_user_id, failure_reason="identity_conflict", platform=f"{provider}_link")
                return False
            internal_user_id = target_internal_user_id
            if linked:
                grant_auth_link_reward(conn, internal_user_id, provider, now)
            platform = f"{provider}_link"
        elif provider == "telegram":
            internal_user_id, _legacy_user_id = telegram_upsert_identity(conn, provider_user, now)
            platform = f"{provider}_bot"
        else:
            internal_user_id, _legacy_user_id = max_upsert_identity(conn, provider_user, now)
            platform = f"{provider}_bot"
        conn.execute(
            """
            UPDATE auth_login_challenges
            SET status = 'approved', internal_user_id = ?, provider_user_id = ?,
                provider_username = ?, approved_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (internal_user_id, provider_user_id, provider_user.get("username"), now, row["id"]),
        )
        record_login_attempt(conn, provider, True, identifier=provider_user_id, internal_user_id=internal_user_id, platform=platform)
    return True


def link_verified_provider_identity(
    conn: sqlite3.Connection,
    internal_user_id: str,
    provider: Literal["telegram", "max"],
    provider_user: dict[str, Any],
    now: str,
) -> bool | None:
    """Attach a verified bot identity to the current account.

    Returns True when a new identity was linked, False when already linked to the
    same account, and None when the identity belongs to a different account.
    """
    provider_user_id = str(provider_user.get("id") or "")
    if not provider_user_id:
        return None
    existing = conn.execute(
        "SELECT internal_user_id FROM auth_identities WHERE provider = ? AND provider_user_id = ?",
        (provider, provider_user_id),
    ).fetchone()
    if existing and existing["internal_user_id"] != internal_user_id:
        return None
    username = provider_user.get("username")
    first = provider_user.get("first_name")
    last = provider_user.get("last_name")
    photo = provider_user.get("photo_url")
    lang = provider_user.get("language_code")
    raw_profile = json.dumps(provider_user, ensure_ascii=False)
    legacy_row = conn.execute("SELECT id FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
    legacy_user_id = _row_get(legacy_row, "id")
    if existing:
        conn.execute(
            """
            UPDATE auth_identities
            SET provider_username = ?, provider_first_name = ?, provider_last_name = ?,
                provider_avatar_url = ?, provider_language_code = ?, raw_profile_json = ?,
                verified_at = COALESCE(verified_at, ?), last_login_at = ?
            WHERE provider = ? AND provider_user_id = ?
            """,
            (username, first, last, photo, lang, raw_profile, now, now, provider, provider_user_id),
        )
        return False
    conn.execute(
        """
        INSERT INTO auth_identities
            (id, internal_user_id, legacy_user_id, provider, provider_user_id, provider_username,
             provider_first_name, provider_last_name, provider_avatar_url, provider_language_code,
             raw_profile_json, verified_at, linked_at, last_login_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, internal_user_id, legacy_user_id, provider, provider_user_id, username, first, last, photo, lang, raw_profile, now, now, now),
    )
    user_columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if provider == "telegram" and "telegram_id" in user_columns:
        conn.execute("UPDATE users SET telegram_id = COALESCE(telegram_id, ?) WHERE internal_user_id = ?", (provider_user_id, internal_user_id))
    if provider == "max" and "max_id" in user_columns:
        conn.execute("UPDATE users SET max_id = COALESCE(max_id, ?) WHERE internal_user_id = ?", (provider_user_id, internal_user_id))
    _fill_user_profile_if_empty(conn, legacy_user_id, provider_user)
    return True


def grant_auth_link_reward(conn: sqlite3.Connection, internal_user_id: str, provider: str, now: str) -> bool:
    reward_type = f"auth_link_{provider}"
    idem = f"{reward_type}:{internal_user_id}"
    existing = conn.execute("SELECT id FROM bonus_grants WHERE idempotency_key = ?", (idem,)).fetchone()
    if existing:
        return False
    target = conn.execute("SELECT * FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
    if not target:
        return False
    ledger_id, _new_balance = _grant_tokens_with_ledger(
        conn,
        target=target,
        delta=10,
        reason=f"Подключение {provider.upper()}",
        ledger_reason="auth_link_reward",
        meta={"provider": provider, "reward_type": reward_type},
    )
    conn.execute(
        """
        INSERT INTO bonus_grants
            (id, internal_user_id, user_id, bonus_type, token_amount, status, reason,
             token_ledger_id, created_by_admin_id, idempotency_key, created_at)
        VALUES (?, ?, ?, ?, 10, 'granted', ?, ?, NULL, ?, ?)
        """,
        (uuid.uuid4().hex, internal_user_id, target["id"], reward_type, f"Подключение {provider.upper()}", ledger_id, idem, now),
    )
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
    avatar_url, avatar_preset = random_avatar_choice()
    if has_email_col:
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (id, email, language, role, plan, gallery_enabled, avatar_url, avatar_preset, created_at, last_login_at, internal_user_id)
            VALUES (?, ?, 'ru', 'user', 'mini', 1, ?, ?, ?, ?, ?)
            """,
            (legacy_user_id, email_norm, avatar_url, avatar_preset, now, now, internal_user_id),
        )
    else:
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (id, language, role, avatar_url, avatar_preset, created_at, last_login_at, internal_user_id)
            VALUES (?, 'ru', 'user', ?, ?, ?, ?, ?)
            """,
            (legacy_user_id, avatar_url, avatar_preset, now, now, internal_user_id),
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


def _boolish(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "да"}
    return bool(value)


def _tariff_text(source: dict[str, Any], plan: str, key: str, *, max_len: int = 160) -> str:
    value = source.get(key, DEFAULT_TARIFFS[plan][key])
    text = str(value if value is not None else DEFAULT_TARIFFS[plan][key]).strip()
    return (text or str(DEFAULT_TARIFFS[plan][key]))[:max_len]


ALLOWED_RESOLUTION_IDS = {"sq-1024", "h-1280", "v-720", "h-1536", "v-1024", "h-1920", "v-1088"}
QUALITY_PRESETS = ("fast", "standard", "max")
ALLOWED_TARIFF_MODEL_IDS = {
    "server:local_flux_klein",
}


def _tariff_resolutions(source: dict[str, Any], plan: str) -> list[str]:
    raw = source.get("allowed_resolutions", source.get("allowedResolutions", DEFAULT_TARIFFS[plan]["allowed_resolutions"]))
    values = raw if isinstance(raw, list) else []
    result = [str(item) for item in values if str(item) in ALLOWED_RESOLUTION_IDS]
    return result or list(DEFAULT_TARIFFS[plan]["allowed_resolutions"])


def _tariff_model_defaults(source: dict[str, Any], plan: str) -> dict[str, str]:
    raw = source.get("model_defaults", source.get("modelDefaults", DEFAULT_TARIFFS[plan]["model_defaults"]))
    values = raw if isinstance(raw, dict) else {}
    result: dict[str, str] = {}
    for preset in QUALITY_PRESETS:
        value = values.get(preset, DEFAULT_TARIFFS[plan]["model_defaults"][preset])
        model_id = str(value).strip()
        result[preset] = model_id if model_id in ALLOWED_TARIFF_MODEL_IDS or ("/" in model_id and len(model_id) <= 160) else DEFAULT_TARIFFS[plan]["model_defaults"][preset]
    return result


def normalize_tariffs(raw: Any | None = None, *, strict: bool = False) -> dict[str, dict[str, Any]]:
    if strict and (not isinstance(raw, dict) or not raw):
        raise HTTPException(400, "Tariff config must not be empty.")
    data = raw if isinstance(raw, dict) else {}
    if strict:
        unknown = sorted(str(key) for key in data if str(key).lower() not in PLAN_ORDER)
        if unknown:
            raise HTTPException(400, f"Unknown tariff plan: {', '.join(unknown)}")
    result: dict[str, dict[str, Any]] = {}
    for plan in PLAN_ORDER:
        source = data.get(plan) if isinstance(data.get(plan), dict) else {}
        price = source.get("price_rub_month", source.get("priceRubMonth", DEFAULT_TARIFFS[plan]["price_rub_month"]))
        daily = source.get("daily_tokens", source.get("dailyTokens", DEFAULT_TARIFFS[plan]["daily_tokens"]))
        openrouter_monthly = source.get("openrouter_monthly_tokens", source.get("openrouterMonthlyTokens", DEFAULT_TARIFFS[plan]["openrouter_monthly_tokens"]))
        slots = source.get("gallery_slots", source.get("gallerySlots", DEFAULT_TARIFFS[plan]["gallery_slots"]))
        video_enabled = source.get("video_enabled", source.get("videoEnabled", DEFAULT_TARIFFS[plan]["video_enabled"]))
        video_slots = source.get("video_slots", source.get("videoSlots", DEFAULT_TARIFFS[plan]["video_slots"]))
        try:
            price_int = int(price)
            daily_int = int(daily)
            openrouter_monthly_int = int(openrouter_monthly)
            slots_int = int(slots)
            video_slots_int = int(video_slots)
        except (TypeError, ValueError):
            if strict:
                raise HTTPException(400, f"Invalid tariff values for {plan}.")
            price_int = DEFAULT_TARIFFS[plan]["price_rub_month"]
            daily_int = DEFAULT_TARIFFS[plan]["daily_tokens"]
            openrouter_monthly_int = DEFAULT_TARIFFS[plan]["openrouter_monthly_tokens"]
            slots_int = DEFAULT_TARIFFS[plan]["gallery_slots"]
            video_slots_int = DEFAULT_TARIFFS[plan]["video_slots"]
        if strict and (price_int < 0 or daily_int < 0 or openrouter_monthly_int < 0 or slots_int < 0 or video_slots_int < 0):
            raise HTTPException(400, f"Tariff values for {plan} must be non-negative.")
        result[plan] = {
            "title": _tariff_text(source, plan, "title", max_len=40),
            "note": _tariff_text(source, plan, "note", max_len=160),
            "price_rub_month": max(0, min(price_int, 10_000_000)),
            "daily_tokens": max(0, min(daily_int, 100_000)),
            "openrouter_monthly_tokens": max(0, min(openrouter_monthly_int, 100_000)),
            "gallery_slots": max(0, min(slots_int, 100_000)),
            "quality_label": _tariff_text(source, plan, "quality_label", max_len=80),
            "model_defaults": _tariff_model_defaults(source, plan),
            "queue_label": _tariff_text(source, plan, "queue_label", max_len=80),
            "pro_mode_enabled": 1 if _boolish(source.get("pro_mode_enabled", source.get("proModeEnabled", DEFAULT_TARIFFS[plan]["pro_mode_enabled"]))) else 0,
            "allowed_resolutions": _tariff_resolutions(source, plan),
            "video_enabled": 1 if _boolish(video_enabled) else 0,
            "video_slots": max(0, min(video_slots_int, 100_000)),
        }
    return result


def get_tariff_config(conn: sqlite3.Connection | None = None) -> dict[str, dict[str, Any]]:
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
        "openrouter_monthly_tokens": int(tariff.get("openrouter_monthly_tokens") or 0),
        "gallery_slots": total,
        "video_enabled": bool(tariff.get("video_enabled")),
        "video_slots": int(tariff.get("video_slots") or 0),
        "gallery_used": used,
        "gallery_free": max(0, total - used),
        "gallery_full": used >= total,
    }


ACTIVE_IMAGE_WHERE = "(deleted_at IS NULL OR deleted_at = '')"


def evict_gallery_images_for_new_save(
    conn: sqlite3.Connection,
    legacy_user_id: str,
    quota: dict[str, Any],
    now_iso: str,
) -> int:
    """Free space for a new generated image without touching favorite-protected rows.

    When a user is already above the current tariff limit, evict two old
    unprotected images before saving one new image. That lets historical
    over-limit galleries shrink gradually with continued use instead of staying
    permanently above quota.
    """
    total = int(quota.get("gallery_slots") or 0)
    used = int(quota.get("gallery_used") or 0)
    if total <= 0 or used < total:
        return 0
    target = 2 if used > total else 1
    rows = conn.execute(
        """
        SELECT id, url, thumbnail_url FROM images
        WHERE user_id = ? AND is_favorite = 0 AND (deleted_at IS NULL OR deleted_at = '')
        ORDER BY created_at ASC, id ASC
        LIMIT ?
        """,
        (legacy_user_id, target),
    ).fetchall()
    for row in rows:
        delete_image_source_files(conn, row["id"])
        conn.execute("UPDATE images SET deleted_at = ? WHERE id = ?", (now_iso, row["id"]))
        retire_feed_publications_for_image(conn, row["id"], now_iso)
        delete_image_files_from_disk(url=row["url"], thumbnail_url=row["thumbnail_url"])
        if row["id"] in images:
            images.pop(row["id"])
    return len(rows)


def gallery_cursor_from_row(row: sqlite3.Row) -> str:
    payload = {"created_at": _row_get(row, "created_at") or "", "id": _row_get(row, "id") or ""}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_gallery_cursor(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception:
        raise HTTPException(400, "invalid gallery cursor")
    created_at = str(payload.get("created_at") or "")
    image_id = str(payload.get("id") or "")
    if not created_at or not image_id:
        raise HTTPException(400, "invalid gallery cursor")
    return created_at, image_id


def gallery_media_owner_row(conn: sqlite3.Connection, filename: str, legacy_user_id: str) -> sqlite3.Row | None:
    media_url_prefix = f"/api/media/{filename}"
    image_row = conn.execute(
        f"""
        SELECT id, user_id, url, thumbnail_url FROM images
        WHERE user_id = ? AND {ACTIVE_IMAGE_WHERE}
          AND (url LIKE ? OR thumbnail_url LIKE ?)
        LIMIT 1
        """,
        (legacy_user_id, f"{media_url_prefix}%", f"{media_url_prefix}%"),
    ).fetchone()
    if image_row is not None:
        return image_row
    return conn.execute(
        """
        SELECT id, user_id, image_id, thumb_url FROM image_sources
        WHERE user_id = ? AND thumb_url LIKE ?
        LIMIT 1
        """,
        (legacy_user_id, f"{media_url_prefix}%"),
    ).fetchone()


def gallery_image_id_from_media_url(conn: sqlite3.Connection, url: str | None, legacy_user_id: str) -> str | None:
    filename = media_filename_from_url(url)
    if not filename:
        return None
    row = conn.execute(
        f"""
        SELECT id FROM images
        WHERE user_id = ? AND {ACTIVE_IMAGE_WHERE}
          AND (url LIKE ? OR thumbnail_url LIKE ?)
        LIMIT 1
        """,
        (legacy_user_id, f"/api/media/{filename}%", f"/api/media/{filename}%"),
    ).fetchone()
    return row["id"] if row is not None else None


def delete_image_source_files(conn: sqlite3.Connection, image_id: str) -> None:
    rows = conn.execute("SELECT thumb_url FROM image_sources WHERE image_id = ?", (image_id,)).fetchall()
    for row in rows:
        name = media_filename_from_url(row["thumb_url"])
        if name:
            _delete_media_rel(name)
    conn.execute("DELETE FROM image_sources WHERE image_id = ?", (image_id,))


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


def trusted_cookie_common(request: Request | None = None) -> dict[str, Any]:
    cookie_secure = TRUSTED_COOKIE_SECURE
    cookie_samesite = TRUSTED_COOKIE_SAMESITE
    if request is not None:
        host = (request.url.hostname or request.headers.get("host") or "").split(":", 1)[0].lower()
        if request.url.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}:
            cookie_secure = False
            if cookie_samesite.lower() == "none":
                cookie_samesite = "lax"
    common = {
        "httponly": True,  # always
        "secure": cookie_secure,
        "samesite": cookie_samesite,
        "path": TRUSTED_COOKIE_PATH,
    }
    if TRUSTED_COOKIE_DOMAIN:
        common["domain"] = TRUSTED_COOKIE_DOMAIN
    return common


def set_trusted_auth_cookies(
    response: Response,
    session_token: str,
    refresh_token: str,
    expires_at: str | None = None,
    refresh_expires_at: str | None = None,
    request: Request | None = None,
) -> None:
    """Set HttpOnly session + refresh cookies carrying the raw tokens.

    The DB still stores only hashes; the cookie is just secure transport. Raw
    cookie values are never logged. secure/samesite/domain/path come from config.
    """
    common = trusted_cookie_common(request)
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


def trusted_user_is_admin(user: dict[str, Any]) -> bool:
    with db() as conn:
        row = conn.execute("SELECT role FROM users WHERE internal_user_id = ?", (user["internal_user_id"],)).fetchone()
        if row is None and user.get("legacy_user_id"):
            row = conn.execute("SELECT role FROM users WHERE id = ?", (user["legacy_user_id"],)).fetchone()
    return bool(row and row["role"] == "admin")


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
    "public_about": "public_about",
    "public_website": "public_website",
    "public_focus": "public_focus",
    "public_phone": "public_phone",
    "public_links": "public_links_json",
    "gender": "gender",
    "age": "age",
}

CONSENT_TYPES = {
    "terms", "privacy", "personal_data_processing", "cookies", "analytics",
    "marketing", "public_gallery", "ai_generation_rules", "age_confirmation",
}

PROFILE_FIELD_MAX_LEN = 200
PROFILE_FIELD_MAX_LEN_BY_FIELD = {
    "public_about": 700,
    "public_website": 240,
    "public_focus": 120,
    "public_phone": 40,
}
PUBLIC_LINKS_MAX_COUNT = 6
PUBLIC_LINK_LABEL_MAX_LEN = 40


def normalize_public_website(value: str | None) -> str | None:
    if value is None:
        return None
    url = value.strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        url = f"https://{url}"
    if len(url) > PROFILE_FIELD_MAX_LEN_BY_FIELD["public_website"]:
        url = url[:PROFILE_FIELD_MAX_LEN_BY_FIELD["public_website"]]
    if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", url, flags=re.IGNORECASE):
        raise HTTPException(400, "Ссылка публичного профиля должна быть корректным URL.")
    return url


def normalize_public_links(value: Any) -> str:
    if value is None:
        return "[]"
    if not isinstance(value, list):
        raise HTTPException(400, "Публичные ссылки должны быть списком.")
    result: list[dict[str, str]] = []
    for raw in value[:PUBLIC_LINKS_MAX_COUNT]:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("title") or "").strip()[:PUBLIC_LINK_LABEL_MAX_LEN]
        url = normalize_public_website(str(raw.get("url") or "").strip())
        if not url:
            continue
        result.append({"label": label or "Ссылка", "url": url})
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def parse_public_links(value: Any) -> list[dict[str, str]]:
    if not value:
        return []
    try:
        loaded = json.loads(str(value))
    except (TypeError, ValueError):
        return []
    if not isinstance(loaded, list):
        return []
    result: list[dict[str, str]] = []
    for raw in loaded[:PUBLIC_LINKS_MAX_COUNT]:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()[:PUBLIC_LINK_LABEL_MAX_LEN]
        url = str(raw.get("url") or "").strip()[:PROFILE_FIELD_MAX_LEN_BY_FIELD["public_website"]]
        if url:
            result.append({"label": label or "Ссылка", "url": url})
    return result


def build_profile(row: sqlite3.Row | None) -> dict[str, Any]:
    """Safe profile projection — only whitelisted columns, null where missing."""
    profile = {api_field: _row_get(row, col) for api_field, col in PROFILE_FIELD_COLUMNS.items() if api_field != "public_links"}
    profile["public_links"] = parse_public_links(_row_get(row, "public_links_json"))
    return profile


AVATAR_PRESET_COUNT = 71
AVATAR_PRESET_IDS = {f"avatar-{i:03d}" for i in range(1, AVATAR_PRESET_COUNT + 1)}
LEGACY_AVATAR_PRESET_IDS = {f"preset-{i}": f"avatar-{i:03d}" for i in range(1, 11)}
AVATAR_MAX_BYTES = 8 * 1024 * 1024
AVATAR_OUTPUT_SIZE = 512
AVATAR_WEBP_QUALITY = 86
AVATAR_ALLOWED_CONTENT_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def random_avatar_choice() -> tuple[str, str]:
    preset = f"avatar-{secrets.randbelow(AVATAR_PRESET_COUNT) + 1:03d}"
    return f"/avatars/{preset}.webp", preset


def validate_avatar_choice(avatar_url: str | None, avatar_preset: str | None) -> tuple[str | None, str | None]:
    preset = (avatar_preset or "").strip()
    url = (avatar_url or "").strip()
    if preset in LEGACY_AVATAR_PRESET_IDS:
        preset = LEGACY_AVATAR_PRESET_IDS[preset]
    if preset:
        if preset not in AVATAR_PRESET_IDS:
            raise HTTPException(400, "Unknown avatar preset.")
        expected = f"/avatars/{preset}.webp"
        return expected, preset
    if url and not url.startswith("/media/avatars/"):
        raise HTTPException(400, "Avatar URL is not allowed.")
    return url or None, None


def compress_avatar_image(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            if img.mode == "RGBA":
                bg = Image.new("RGBA", img.size, (18, 22, 20, 255))
                bg.alpha_composite(img)
                img = bg.convert("RGB")
            else:
                img = img.convert("RGB")
            img = ImageOps.fit(
                img,
                (AVATAR_OUTPUT_SIZE, AVATAR_OUTPUT_SIZE),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            out = io.BytesIO()
            img.save(out, format="WEBP", quality=AVATAR_WEBP_QUALITY, method=6)
            return out.getvalue()
    except Exception:
        raise HTTPException(400, "Avatar file is not a valid image.")


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


def _user_model_name(raw: str | None) -> str:
    """Пользователь видит только «Flux2» — никогда точный идентификатор модели.
    Flux Klein 4B/9B, local_flux_klein и другие flux-варианты → «Flux2».
    OpenRouter → «OpenRouter». Всё остальное → «Flux2» (безопасное умолчание)."""
    if not raw:
        return "Flux2"
    lowered = raw.lower()
    if any(kw in lowered for kw in ("flux", "klein", "local_flux")):
        return "Flux2"
    if "openrouter" in lowered:
        return "OpenRouter"
    return "Flux2"


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
        "modelProfile": _user_model_name(settings.get("modelProfile")),
        "loras": settings.get("loras", []),
        "preset": settings.get("preset"),
        "generationTimeMs": settings.get("generationTimeMs", 0),
        "isFavorite": bool(row["is_favorite"]),
        "createdAt": row["created_at"],
        "comfyuiPromptId": settings.get("comfyuiPromptId"),
        "comfyuiHistory": settings.get("comfyuiHistory"),
        "deletedAt": _row_get(row, "deleted_at"),
    }


def _gallery_aspect_ratio(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    gcd = math.gcd(int(width), int(height))
    if gcd <= 0:
        return None
    return f"{int(width) // gcd}:{int(height) // gcd}"


def _gallery_mode_label(mode: str | None) -> str:
    models_cache_data = _admin_models_page_cache.get("data")
    models_cache_ts = _admin_models_page_cache.get("ts")
    if isinstance(models_cache_ts, dict):
        newest_cache_ts = max((float(v or 0) for v in models_cache_ts.values()), default=0.0)
    else:
        newest_cache_ts = float(models_cache_ts or 0)
    return {
        "text_to_image": "По тексту",
        "image_to_image": "По фото",
        "edit": "Сборка",
        "paint": "Редактор",
        "inpaint": "Инпейнт",
        "outpaint": "Аутпейнт",
        "try_on": "Примерка",
        "texture_transfer": "Перенос текстуры",
        "remove_background": "Удаление фона",
        "faceswap": "Лицо",
        "face": "Лицо",
        "face_swap": "Лицо",
        "drawing": "Редактор",
        "editor": "Сборка",
    }.get(str(mode or "").strip(), str(mode or "По тексту"))


def _gallery_source_ids(settings: dict[str, Any]) -> list[str]:
    raw = (
        settings.get("sourceImageIds")
        or settings.get("source_image_ids")
        or settings.get("sourceIds")
        or []
    )
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw[:4] if str(item or "").strip()]


def _feed_publication_ready(publication: sqlite3.Row | None) -> bool:
    return bool(
        publication is not None
        and _row_get(publication, "status") == "published"
        and _row_get(publication, "media_ready_at")
        and _row_get(publication, "feed_thumb_name")
        and _row_get(publication, "feed_large_name")
    )


def _gallery_page_item(
    row: sqlite3.Row,
    publication: sqlite3.Row | None = None,
    *,
    include_feed_media: bool = False,
) -> dict[str, Any]:
    settings = json.loads(row["settings_json"] or "{}")
    publication_id = _row_get(publication, "id") if publication is not None else None
    feed_ready = _feed_publication_ready(publication)
    published = bool(publication_id and feed_ready)
    thumb_url = row["thumbnail_url"]
    image_url = row["url"]
    if include_feed_media and publication_id and feed_ready:
        thumb_url = f"/api/feed/media/{publication_id}?variant=thumb"
        image_url = f"/api/feed/media/{publication_id}?variant=large"
    prompt = row["prompt_original"] or row["prompt_translated"] or ""
    width = int(row["width"] or 0)
    height = int(row["height"] or 0)
    return {
        "id": row["id"],
        "imageId": row["id"],
        "src": thumb_url,
        "thumbnailUrl": thumb_url,
        "viewerSrc": image_url,
        "downloadUrl": image_url,
        "prompt": prompt,
        "promptOriginal": row["prompt_original"] or "",
        "promptTranslated": row["prompt_translated"] or "",
        "mode": row["mode"],
        "modeLabel": _gallery_mode_label(row["mode"]),
        "provider": row["provider"],
        "model": _user_model_name(settings.get("modelProfile") or row["provider"]),
        "modelProfile": _user_model_name(settings.get("modelProfile") or row["provider"]),
        "preset": settings.get("preset") or settings.get("styleName"),
        "loras": settings.get("loras") if isinstance(settings.get("loras"), list) else [],
        "seed": settings.get("seed"),
        "width": width,
        "height": height,
        "aspect": _gallery_aspect_ratio(width, height),
        "aspectRatio": _gallery_aspect_ratio(width, height),
        "createdAt": row["created_at"],
        "date": row["created_at"],
        "generationTimeMs": settings.get("generationTimeMs", 0),
        "genTime": settings.get("generationTimeMs", 0),
        "favorite": bool(row["is_favorite"]),
        "isFavorite": bool(row["is_favorite"]),
        "published": published,
        "feedPublicationId": publication_id,
        "publishedAt": _row_get(publication, "created_at") if publication is not None else None,
        "feedMediaStatus": "ready" if feed_ready else ("missing" if publication is not None else None),
        "views": _row_get(publication, "view_count") if publication is not None else 0,
        "likes": 0,
        "saves": 0,
        "remixes": 0,
        "sourceIds": _gallery_source_ids(settings),
    }


def _gallery_page_limits(
    conn: sqlite3.Connection,
    user_row: sqlite3.Row | None,
    legacy_user_id: str,
) -> dict[str, Any]:
    quota = gallery_quota_for_user(conn, user_row, legacy_user_id)
    feed_used = int(conn.execute(
        """
        SELECT COUNT(*) AS c FROM feed_publications
        WHERE legacy_user_id = ?
          AND status = 'published'
          AND media_ready_at IS NOT NULL
          AND feed_thumb_name IS NOT NULL
          AND feed_large_name IS NOT NULL
        """,
        (legacy_user_id,),
    ).fetchone()["c"])
    favorites_used = int(conn.execute(
        """
        SELECT COUNT(*) AS c FROM images
        WHERE user_id = ? AND is_favorite = 1 AND (deleted_at IS NULL OR deleted_at = '')
        """,
        (legacy_user_id,),
    ).fetchone()["c"])
    feed_likes = int(conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM feed_reactions r
        JOIN feed_publications p ON p.id = r.publication_id
        WHERE p.legacy_user_id = ?
          AND p.status = 'published'
          AND r.kind = 'like'
        """,
        (legacy_user_id,),
    ).fetchone()["c"])
    favorite_limit = max(0, int(quota["gallery_slots"]) * 80 // 100)
    return {
        "plan": quota["plan"],
        "originals": {
            "used": quota["gallery_used"],
            "limit": quota["gallery_slots"],
            "free": quota["gallery_free"],
            "full": quota["gallery_full"],
        },
        "feed": {
            "used": feed_used,
            "limit": quota["gallery_slots"],
        },
        "favorites": {
            "used": favorites_used,
            "limit": favorite_limit,
        },
        "likes": {
            "used": feed_likes,
        },
    }


def recover_gallery_index_from_media(conn: sqlite3.Connection) -> int:
    """Rebuild missing gallery rows from token ledger + existing media files.

    This is a safe self-heal path for cases where SQLite gallery metadata was
    lost while generated files and token ledger rows remained. It only restores
    jobs that have a ledger-owned user_id; loose files and smoke artifacts stay
    out of user galleries.
    """
    existing = {
        row["job_id"]
        for row in conn.execute("SELECT job_id FROM images WHERE job_id IS NOT NULL AND job_id != ''")
    }
    rows = conn.execute(
        """
        SELECT user_id, meta_json, created_at
        FROM token_ledger
        WHERE meta_json LIKE '%"jobId": "job_%'
        ORDER BY created_at ASC
        """
    ).fetchall()
    restored = 0
    for row in rows:
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except Exception:
            continue
        job_id = str(meta.get("jobId") or "").strip()
        user_id = str(row["user_id"] or "").strip()
        if not job_id.startswith("job_") or not user_id or job_id in existing:
            continue
        image_path = next(
            (MEDIA / f"{job_id}_comfyui{ext}" for ext in (".png", ".jpg", ".jpeg", ".webp") if (MEDIA / f"{job_id}_comfyui{ext}").exists()),
            None,
        )
        if image_path is None:
            continue
        thumb_path = next(
            (MEDIA / f"{job_id}_comfyui_thumb{ext}" for ext in (".webp", ".png", ".jpg", ".jpeg") if (MEDIA / f"{job_id}_comfyui_thumb{ext}").exists()),
            None,
        )
        if thumb_path is None:
            try:
                thumb_path = create_thumbnail(image_path)
            except Exception:
                thumb_path = image_path
        try:
            with Image.open(image_path) as opened:
                width, height = opened.size
        except Exception:
            width = int(meta.get("width") or 1024)
            height = int(meta.get("height") or 1024)
        image_id = f"img_{hashlib.sha1(job_id.encode('utf-8')).hexdigest()[:12]}"
        settings = {
            "seed": meta.get("seed"),
            "modelProfile": meta.get("modelProfile", ""),
            "loras": meta.get("loras", []),
            "preset": None,
            "generationTimeMs": meta.get("generationTimeMs", 0),
            "comfyuiPromptId": meta.get("promptId"),
            "recoveredFrom": "token_ledger_media",
        }
        conn.execute(
            """
            INSERT OR IGNORE INTO images
                (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider,
                 prompt_original, prompt_translated, settings_json, is_favorite, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                image_id,
                user_id,
                job_id,
                public_url(image_path, user_id),
                public_url(thumb_path, user_id),
                width,
                height,
                str(meta.get("mode") or "text_to_image"),
                str(meta.get("provider") or "comfyui"),
                "",
                "",
                json.dumps(settings, ensure_ascii=False),
                row["created_at"],
            ),
        )
        existing.add(job_id)
        restored += 1
    if restored:
        print(f"gallery recovery restored {restored} image rows from token ledger/media")
    return restored


def load_db_state() -> None:
    jobs.clear()
    images.clear()
    with db() as conn:
        restored_gallery_rows = recover_gallery_index_from_media(conn)
        if restored_gallery_rows:
            conn.commit()
        for row in conn.execute(f"SELECT * FROM images WHERE {ACTIVE_IMAGE_WHERE} ORDER BY created_at DESC"):
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


def persist_job(job: dict[str, Any], request: GenerateRequest | None = None, conn: sqlite3.Connection | None = None) -> None:
    settings = request.model_dump() if request else job.get("request", {})
    for key in ("openrouterModel", "openrouterResponseId", "openrouterUsage", "openrouterCostUsd", "openrouterBilling"):
        if key in job:
            settings[key] = job.get(key)
    def write(target_conn: sqlite3.Connection) -> None:
        target_conn.execute(
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
    if conn is not None:
        write(conn)
        return
    with db() as own_conn:
        write(own_conn)


def persist_image(record: dict[str, Any], job_id: str) -> None:
    settings = {
        "seed": record.get("seed"),
        "modelProfile": record.get("modelProfile"),
        "loras": record.get("loras", []),
        "preset": record.get("preset"),
        "generationTimeMs": record.get("generationTimeMs"),
        "comfyuiPromptId": record.get("comfyuiPromptId"),
        "comfyuiHistory": record.get("comfyuiHistory"),
        "openrouterModel": record.get("openrouterModel"),
        "openrouterResponseId": record.get("openrouterResponseId"),
        "openrouterUsage": record.get("openrouterUsage"),
        "openrouterCostUsd": record.get("openrouterCostUsd"),
        "openrouterBilling": record.get("openrouterBilling"),
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


def media_filename_from_url(url: str | None) -> str | None:
    if not url:
        return None
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
        return None
    return filename


def _source_role_label(role: str | None, slot_index: int, mode: str | None = None) -> str:
    key = str(role or "").strip().lower()
    labels = {
        "base": "Основа",
        "image": "Изображение",
        "reference": "Референс",
        "ref": "Референс",
        "pose": "Поза",
        "face": "Лицо",
        "target": "Основа",
        "source": "Источник",
        "style": "Стиль",
        "clothes": "Одежда",
        "clothing": "Одежда",
        "background": "Фон",
        "mask": "Маска",
        "canvas": "Холст",
    }
    if key in labels:
        return labels[key]
    if slot_index == 1:
        return "Основа"
    if mode == "faceswap" and slot_index == 2:
        return "Лицо"
    if mode == "try_on" and slot_index == 2:
        return "Одежда"
    return f"Исходник {slot_index}"


def _generation_source_inputs(req: GenerateRequest) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if req.mode == "edit" and req.inputImages:
        for item in sorted(req.inputImages, key=lambda x: x.index or 0):
            if item.image:
                index = int(item.index or len(sources) + 1)
                sources.append({"slot": index, "role": item.role or ("base" if index == 1 else "reference"), "value": item.image})
    else:
        if req.inputImage1:
            role = "base"
            if req.mode == "faceswap":
                role = "target"
            sources.append({"slot": 1, "role": role, "value": req.inputImage1})
        if req.inputImage2:
            role = "reference"
            if req.mode == "faceswap":
                role = "face"
            elif req.mode == "try_on":
                role = "clothes"
            sources.append({"slot": 2, "role": role, "value": req.inputImage2})
    if req.canvas:
        sources.append({"slot": max([int(s["slot"]) for s in sources] or [0]) + 1, "role": "canvas", "value": req.canvas})
    mask_value = req.maskImage or req.outpaintMask
    if mask_value:
        sources.append({"slot": max([int(s["slot"]) for s in sources] or [0]) + 1, "role": "mask", "value": mask_value})
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources[:8]:
        key = (str(source.get("role") or ""), str(source.get("value") or "")[:500])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _open_source_image(source_value: str | None) -> Image.Image | None:
    if not source_value:
        return None
    if source_value.startswith("data:image"):
        try:
            _header, encoded = source_value.split(",", 1)
            return Image.open(io.BytesIO(base64.b64decode(encoded)))
        except Exception:
            return None
    path = local_media_path_from_url(source_value)
    if path and path.exists():
        try:
            return Image.open(path)
        except Exception:
            return None
    return None


def _save_source_thumb(source_value: str | None, image_id: str, slot_index: int) -> tuple[Path, int, int, int] | None:
    opened = _open_source_image(source_value)
    if opened is None:
        return None
    try:
        with opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((SOURCE_THUMB_MAX_SIDE, SOURCE_THUMB_MAX_SIDE), Image.Resampling.LANCZOS)
            target = MEDIA / f"{image_id}_source{slot_index}_{uuid.uuid4().hex[:10]}.webp"
            image.save(target, "WEBP", quality=SOURCE_THUMB_WEBP_QUALITY, method=6)
            return target, image.width, image.height, target.stat().st_size
    except Exception:
        return None


def persist_image_sources(image_id: str, user_id: str, req: GenerateRequest, created_at: str) -> list[dict[str, Any]]:
    source_inputs = _generation_source_inputs(req)
    if not source_inputs:
        return []
    saved: list[dict[str, Any]] = []
    with db() as conn:
        conn.execute("DELETE FROM image_sources WHERE image_id = ?", (image_id,))
        for pos, source in enumerate(source_inputs, start=1):
            slot = int(source.get("slot") or pos)
            value = str(source.get("value") or "")
            thumb = _save_source_thumb(value, image_id, slot)
            if thumb is None:
                continue
            thumb_path, width, height, byte_size = thumb
            role = str(source.get("role") or "")
            source_id = gallery_image_id_from_media_url(conn, value, user_id)
            children_snapshot = (
                gallery_sources_for_image(conn, source_id, user_id, depth=2, visited={image_id})
                if source_id
                else []
            )
            kind = "gallery_image" if source_id else ("upload" if value.startswith("data:image") else "media")
            source_row = {
                "id": uuid.uuid4().hex,
                "imageId": image_id,
                "sourceImageId": source_id,
                "sourceKind": kind,
                "role": role,
                "roleLabel": _source_role_label(role, slot, req.mode),
                "slotIndex": slot,
                "thumbUrl": public_url(thumb_path, user_id),
                "width": width,
                "height": height,
                "bytes": byte_size,
                "children": children_snapshot,
            }
            conn.execute(
                """
                INSERT INTO image_sources
                    (id, image_id, user_id, source_image_id, source_kind, role, slot_index,
                     thumb_url, thumb_width, thumb_height, thumb_bytes, children_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_row["id"],
                    image_id,
                    user_id,
                    source_id,
                    kind,
                    role,
                    slot,
                    source_row["thumbUrl"],
                    width,
                    height,
                    byte_size,
                    json.dumps(children_snapshot, ensure_ascii=False),
                    created_at,
                ),
            )
            saved.append(source_row)
    return saved


def gallery_sources_for_image(
    conn: sqlite3.Connection,
    image_id: str,
    user_id: str,
    *,
    depth: int = 3,
    visited: set[str] | None = None,
) -> list[dict[str, Any]]:
    visited = set(visited or set())
    if depth <= 0 or image_id in visited:
        return []
    visited.add(image_id)
    rows = conn.execute(
        """
        SELECT * FROM image_sources
        WHERE image_id = ? AND user_id = ?
        ORDER BY slot_index ASC, created_at ASC
        """,
        (image_id, user_id),
    ).fetchall()
    sources: list[dict[str, Any]] = []
    for row in rows:
        source_image_id = row["source_image_id"]
        snapshot_children = safe_json_load(_row_get(row, "children_json")) or []
        if not isinstance(snapshot_children, list):
            snapshot_children = []
        live_children = (
            gallery_sources_for_image(conn, source_image_id, user_id, depth=depth - 1, visited=visited)
            if source_image_id
            else []
        )
        children = live_children or snapshot_children
        sources.append({
            "id": row["id"],
            "imageId": row["image_id"],
            "sourceImageId": source_image_id,
            "sourceKind": row["source_kind"],
            "role": row["role"],
            "roleLabel": _source_role_label(row["role"], int(row["slot_index"] or 0)),
            "slotIndex": int(row["slot_index"] or 0),
            "thumbUrl": row["thumb_url"],
            "width": int(row["thumb_width"] or 0),
            "height": int(row["thumb_height"] or 0),
            "bytes": int(row["thumb_bytes"] or 0),
            "children": children,
        })
    return sources


def repair_image_sources_from_job(image_id: str, user_id: str) -> list[dict[str, Any]]:
    with db() as conn:
        image = conn.execute(
            f"SELECT id, user_id, job_id, created_at FROM images WHERE id = ? AND user_id = ? AND {ACTIVE_IMAGE_WHERE}",
            (image_id, user_id),
        ).fetchone()
        if image is None:
            return []
        existing = int(conn.execute(
            "SELECT COUNT(*) AS c FROM image_sources WHERE image_id = ? AND user_id = ?",
            (image_id, user_id),
        ).fetchone()["c"])
        if existing:
            return gallery_sources_for_image(conn, image_id, user_id)
        job = conn.execute("SELECT settings_json FROM jobs WHERE id = ? AND user_id = ?", (image["job_id"], user_id)).fetchone()
    if job is None:
        return []
    try:
        req = GenerateRequest(**(safe_json_load(job["settings_json"]) or {}))
    except Exception:
        return []
    if not _generation_source_inputs(req):
        return []
    return persist_image_sources(image_id, user_id, req, image["created_at"])


def validate_generation_media_inputs(req: GenerateRequest, user_id: str) -> None:
    """Fail fast for stale or foreign /api/media inputs before queue/token charge."""
    candidates: list[tuple[str, str]] = []
    for field in ("inputImage1", "inputImage2", "maskImage", "outpaintMask"):
        value = getattr(req, field, None)
        if value:
            candidates.append((field, value))
    for item in req.inputImages or []:
        if item.image:
            candidates.append((f"inputImages[{item.index or 0}]", item.image))

    with db() as conn:
        for field, value in candidates:
            filename = media_filename_from_url(value)
            if not filename:
                continue
            path = local_media_path_from_url(value)
            if not path:
                raise HTTPException(400, {"code": "input_media_missing", "field": field})
            like = f"%{filename}%"
            active_image = conn.execute(
                "SELECT 1 FROM images WHERE user_id = ? AND (deleted_at IS NULL OR deleted_at = '') "
                "AND (url LIKE ? OR thumbnail_url LIKE ?) LIMIT 1",
                (user_id, like, like),
            ).fetchone()
            if active_image:
                continue
            job_ref = conn.execute(
                "SELECT 1 FROM jobs WHERE user_id = ? AND settings_json LIKE ? LIMIT 1",
                (user_id, like),
            ).fetchone()
            if job_ref:
                continue
            raise HTTPException(400, {"code": "input_media_unavailable", "field": field})


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
        avatar_url, avatar_preset = random_avatar_choice()
        conn.execute(
            """
            INSERT INTO users (id, telegram_id, max_id, username, first_name, last_name, middle_name, phone, email, language, role, plan, gallery_enabled, created_at, last_login_at,
                               country, city, timezone, ref_code, last_user_agent, last_screen, last_seen_at, avatar_url, avatar_preset)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'user', 'mini', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                username=COALESCE(excluded.username, users.username),
                first_name=COALESCE(excluded.first_name, users.first_name),
                last_name=COALESCE(excluded.last_name, users.last_name),
                middle_name=COALESCE(excluded.middle_name, users.middle_name),
                phone=COALESCE(excluded.phone, users.phone),
                email=COALESCE(excluded.email, users.email),
                language=COALESCE(users.language, excluded.language),
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
                avatar_url,
                avatar_preset,
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


def charge_generation_tokens(conn: sqlite3.Connection, user_id: str, token_cost: int, job_id: str, req: GenerateRequest, billing_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reserve tokens for a generation after request validation has passed.

    Daily tariff tokens are a daily included budget, not a balance top-up. The
    ledger records both paths: `daily_generation` for included daily budget
    consumption, and `generation` for paid balance spend.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    today = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")
    user_row = conn.execute(
        "SELECT id, token_balance, plan, daily_tokens_used, last_daily_reset, openrouter_monthly_tokens_used, last_openrouter_month_reset FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if user_row is None:
        raise HTTPException(404, "User not found.")

    old_balance = int(user_row["token_balance"] or 0)
    daily_limit = 0
    daily_used_before = 0
    daily_used_after = 0
    openrouter_monthly_limit = 0
    openrouter_monthly_used_before = 0
    openrouter_monthly_used_after = 0
    used_openrouter_monthly = False
    used_daily = False
    balance_delta = 0
    ledger_reason = "generation"

    if user_id != "demo_user":
        daily_used_before = int(user_row["daily_tokens_used"] or 0)
        if user_row["last_daily_reset"] != today:
            daily_used_before = 0
        tariff = get_tariff_config(conn)[str(user_row["plan"] or "mini").lower()]
        daily_limit = int(tariff["daily_tokens"])
        openrouter_monthly_limit = int(tariff.get("openrouter_monthly_tokens") or 0)
        openrouter_monthly_used_before = int(user_row["openrouter_monthly_tokens_used"] or 0)
        if user_row["last_openrouter_month_reset"] != month_key:
            openrouter_monthly_used_before = 0
        openrouter_monthly_used_after = openrouter_monthly_used_before
        if req.provider == "openrouter":
            remaining_monthly = max(0, openrouter_monthly_limit - openrouter_monthly_used_before)
            monthly_part = min(token_cost, remaining_monthly)
            balance_delta = max(0, token_cost - monthly_part)
            openrouter_monthly_used_after = openrouter_monthly_used_before + monthly_part
            daily_used_after = daily_used_before
            used_openrouter_monthly = monthly_part > 0
            ledger_reason = "openrouter_monthly_generation" if monthly_part > 0 else "generation"
            if old_balance < balance_delta:
                raise HTTPException(402, "Not enough tokens.")
        elif daily_used_before + token_cost <= daily_limit:
            used_daily = True
            daily_used_after = daily_used_before + token_cost
            ledger_reason = "daily_generation"
        else:
            daily_used_after = daily_used_before
            if old_balance < token_cost:
                raise HTTPException(402, "Not enough tokens.")
            balance_delta = token_cost
    else:
        if old_balance < token_cost:
            raise HTTPException(402, "Not enough tokens.")

    new_balance = old_balance - balance_delta if user_id != "demo_user" else old_balance
    conn.execute(
        """
        UPDATE users
        SET token_balance = ?,
            daily_tokens_used = ?,
            last_daily_reset = ?,
            openrouter_monthly_tokens_used = ?,
            last_openrouter_month_reset = ?,
            tokens_used = tokens_used + ?,
            generation_count = generation_count + 1,
            last_seen_at = ?
        WHERE id = ?
        """,
        (new_balance, daily_used_after, today, openrouter_monthly_used_after, month_key, token_cost, now_iso, user_id),
    )
    conn.execute(
        "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            user_id,
            -balance_delta,
            ledger_reason,
            json.dumps(
                {
                    "jobId": job_id,
                    "mode": req.mode,
                    "provider": req.provider,
                    "token_cost": token_cost,
                    "billing": billing_snapshot or None,
                    "used_daily_budget": used_daily,
                    "used_openrouter_monthly": used_openrouter_monthly,
                    "daily_tokens_used_before": daily_used_before,
                    "daily_tokens_used_after": daily_used_after,
                    "daily_tokens_limit": daily_limit,
                    "openrouter_monthly_used_before": openrouter_monthly_used_before,
                    "openrouter_monthly_used_after": openrouter_monthly_used_after,
                    "openrouter_monthly_limit": openrouter_monthly_limit,
                    "balance_delta": -balance_delta,
                },
                ensure_ascii=False,
            ),
            now_iso,
        ),
    )
    return {
        "used_daily": used_daily,
        "old_balance": old_balance,
        "new_balance": new_balance,
        "balance_delta": -balance_delta,
        "daily_tokens_used": daily_used_after,
        "daily_tokens_limit": daily_limit,
        "daily_tokens_remaining": max(0, daily_limit - daily_used_after),
        "openrouter_monthly_tokens_used": openrouter_monthly_used_after,
        "openrouter_monthly_tokens_limit": openrouter_monthly_limit,
        "openrouter_monthly_tokens_remaining": max(0, openrouter_monthly_limit - openrouter_monthly_used_after),
    }


def refund_generation_tokens(conn: sqlite3.Connection, job_id: str, *, reason: str) -> bool:
    """Idempotently reverse a generation charge for failed/cancelled jobs."""
    existing_refund = conn.execute(
        "SELECT 1 FROM token_ledger WHERE reason IN ('generation_refund', 'daily_generation_refund', 'openrouter_monthly_generation_refund') AND meta_json LIKE ?",
        (f'%"jobId": "{job_id}"%',),
    ).fetchone()
    if existing_refund is not None:
        return False
    charge = conn.execute(
        """
        SELECT * FROM token_ledger
        WHERE reason IN ('generation', 'daily_generation', 'openrouter_monthly_generation') AND meta_json LIKE ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (f'%"jobId": "{job_id}"%',),
    ).fetchone()
    if charge is None:
        return False
    meta = safe_json_load(charge["meta_json"]) or {}
    user_id = charge["user_id"]
    token_cost = int(meta.get("token_cost") or abs(int(charge["delta"] or 0)) or 0)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    today = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")
    if charge["reason"] == "daily_generation":
        user_row = conn.execute("SELECT daily_tokens_used, last_daily_reset FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_row is not None and user_row["last_daily_reset"] == today and token_cost > 0:
            new_daily = max(0, int(user_row["daily_tokens_used"] or 0) - token_cost)
            conn.execute("UPDATE users SET daily_tokens_used = ? WHERE id = ?", (new_daily, user_id))
        refund_delta = 0
        refund_reason = "daily_generation_refund"
    elif charge["reason"] == "openrouter_monthly_generation":
        monthly_part = max(0, int(meta.get("openrouter_monthly_used_after") or 0) - int(meta.get("openrouter_monthly_used_before") or 0))
        user_row = conn.execute("SELECT openrouter_monthly_tokens_used, last_openrouter_month_reset FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_row is not None and user_row["last_openrouter_month_reset"] == month_key and monthly_part > 0:
            new_monthly = max(0, int(user_row["openrouter_monthly_tokens_used"] or 0) - monthly_part)
            conn.execute("UPDATE users SET openrouter_monthly_tokens_used = ? WHERE id = ?", (new_monthly, user_id))
        refund_delta = abs(int(charge["delta"] or 0))
        refund_reason = "openrouter_monthly_generation_refund"
        if refund_delta > 0:
            conn.execute("UPDATE users SET token_balance = token_balance + ? WHERE id = ?", (refund_delta, user_id))
    else:
        refund_delta = abs(int(charge["delta"] or 0))
        refund_reason = "generation_refund"
        if refund_delta > 0:
            conn.execute("UPDATE users SET token_balance = token_balance + ? WHERE id = ?", (refund_delta, user_id))
    if token_cost > 0:
        conn.execute(
            """
            UPDATE users
            SET tokens_used = MAX(0, tokens_used - ?),
                generation_count = MAX(0, generation_count - 1)
            WHERE id = ?
            """,
            (token_cost, user_id),
        )
    conn.execute(
        "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            user_id,
            refund_delta,
            refund_reason,
            json.dumps({"jobId": job_id, "reason": reason, "refunded_ledger_id": charge["id"], "token_cost": token_cost}, ensure_ascii=False),
            now_iso,
        ),
    )
    return True


def mini_app_url(platform: str = "web") -> str:
    base = os.getenv("APP_PUBLIC_URL", "http://127.0.0.1:5173")
    return f"{base}?platform={platform}"


def bot_command_response(platform: Literal["telegram", "max"], command: str) -> dict[str, Any]:
    app_url = mini_app_url(platform)
    normalized = command.split()[0].lower() if command else "/start"
    login_payload = bot_login_payload_from_text(command)
    if login_payload:
        text = "Подтвердите вход в ИЗО АСА — ИИ генератор. Если это были не вы, просто закройте сообщение."
        buttons = [{"text": "Подтвердить вход", "callback_data": f"approve:{login_payload}"}]
    elif normalized == "/start":
        text = "Добро пожаловать в ИЗО АСА — ИИ генератор. Здесь можно открыть генератор, галерею и настройки."
        buttons = [{"text": "Открыть приложение", "url": app_url}]
    elif normalized == "/app":
        text = "Открыть генератор ИЗО АСА — ИИ генератор"
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
    max_deep_link_base = resolve_max_bot_deep_link_base() if MAX_BOT_TOKEN else None
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
            "mode": MAX_UPDATES_MODE,
            "apiBaseUrl": MAX_API_BASE_URL,
            "pollingReady": bool(MAX_BOT_TOKEN and MAX_API_BASE_URL),
            "webhookReady": bool(MAX_BOT_TOKEN and MAX_API_BASE_URL and backend_public.startswith("https://")),
            "botNicknameResolved": bool(max_deep_link_base),
            "deepLinkBaseSource": _MAX_BOT_DEEP_LINK_CACHE.get("source"),
            "apiMeStatus": _MAX_BOT_DEEP_LINK_CACHE.get("api_status"),
            "updatesStatus": MAX_POLLING_DIAG.get("lastPollStatus"),
            "lastUpdatesError": MAX_POLLING_DIAG.get("lastPollError"),
            "webhookConfigured": MAX_POLLING_DIAG.get("webhookConfigured"),
            "webhookUrlSet": MAX_POLLING_DIAG.get("webhookUrlSet"),
            "subscriptionStatus": MAX_POLLING_DIAG.get("subscriptionStatus"),
            "updateTypes": MAX_POLLING_DIAG.get("updateTypes"),
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


_AVATAR_FORMAT_SUFFIX = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
_AVATAR_BG_TASKS: set = set()


def schedule_avatar_cache(provider: Literal["telegram", "max"], provider_user_id: str) -> None:
    """Fire-and-forget avatar caching so a login/verify request never blocks on
    provider network I/O. No-op when there is no running event loop."""
    pid = str(provider_user_id or "")
    if not pid:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(ensure_user_avatar_cached(provider, pid))
    _AVATAR_BG_TASKS.add(task)
    task.add_done_callback(_AVATAR_BG_TASKS.discard)


async def _download_avatar_bytes(url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.content
    except Exception as exc:  # pragma: no cover - network/defensive
        print(f"avatar download failed: {type(exc).__name__}")
        return None
    if not data or len(data) > AVATAR_MAX_BYTES:
        return None
    return data


def _avatar_suffix_from_bytes(data: bytes) -> str | None:
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
    except Exception:
        return None
    return _AVATAR_FORMAT_SUFFIX.get((img.format or "").upper())


async def _telegram_avatar_source(provider_user_id: str) -> str | None:
    """Resolve a downloadable avatar URL for a Telegram user via the Bot API.
    Bot-login user objects carry no photo_url, so we fetch the largest profile
    photo and turn its file_id into a file URL."""
    if not TELEGRAM_BOT_TOKEN:
        return None
    try:
        photos = await telegram_api("getUserProfilePhotos", {"user_id": int(provider_user_id), "limit": 1})
        groups = (photos.get("result") or {}).get("photos") or []
        if not groups or not groups[0]:
            return None
        file_id = groups[0][-1].get("file_id")  # largest size
        if not file_id:
            return None
        info = await telegram_api("getFile", {"file_id": file_id})
        file_path = (info.get("result") or {}).get("file_path")
        if not file_path:
            return None
        return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    except Exception as exc:  # pragma: no cover - network/defensive
        print(f"telegram avatar source failed: {type(exc).__name__}")
        return None


async def ensure_user_avatar_cached(provider: Literal["telegram", "max"], provider_user_id: str) -> str | None:
    """Download the provider avatar, cache it under /media/avatars, and set
    users.avatar_url when the user has no avatar yet. Idempotent: once the user
    has any avatar (cached, uploaded or preset) this is a no-op, so it never
    overwrites a user-customised avatar and never re-downloads on every login."""
    provider_user_id = str(provider_user_id or "")
    if not provider_user_id:
        return None
    with db() as conn:
        identity = conn.execute(
            "SELECT id, internal_user_id, provider_avatar_url FROM auth_identities WHERE provider = ? AND provider_user_id = ?",
            (provider, provider_user_id),
        ).fetchone()
        if identity is None:
            return None
        iuid = identity["internal_user_id"]
        urow = conn.execute("SELECT avatar_url, avatar_preset FROM users WHERE internal_user_id = ?", (iuid,)).fetchone()
    # Respect any existing avatar (uploaded file, chosen preset or already cached).
    if _row_get(urow, "avatar_preset") or _row_get(urow, "avatar_url"):
        return _row_get(urow, "avatar_url")

    source = _row_get(identity, "provider_avatar_url")
    if not source and provider == "telegram":
        source = await _telegram_avatar_source(provider_user_id)
        if source:
            with db() as conn:
                conn.execute(
                    "UPDATE auth_identities SET provider_avatar_url = COALESCE(provider_avatar_url, ?) WHERE id = ?",
                    (source, identity["id"]),
                )
    if not source:
        return None
    data = await _download_avatar_bytes(source)
    if not data:
        return None
    try:
        avatar_bytes = compress_avatar_image(data)
    except HTTPException:
        return None
    filename = f"{iuid}-{provider}-{uuid.uuid4().hex[:12]}.webp"
    try:
        (AVATAR_DIR / filename).write_bytes(avatar_bytes)
    except Exception as exc:  # pragma: no cover - filesystem/defensive
        print(f"avatar cache write failed: {type(exc).__name__}")
        return None
    avatar_url = f"/media/avatars/{filename}"
    with db() as conn:
        # Only claim the slot if it is still empty (avoid racing a user upload).
        conn.execute(
            "UPDATE users SET avatar_url = ? WHERE internal_user_id = ? AND (avatar_url IS NULL OR avatar_url = '') AND (avatar_preset IS NULL OR avatar_preset = '')",
            (avatar_url, iuid),
        )
    return avatar_url


def max_webhook_url() -> str:
    if MAX_WEBHOOK_URL.strip():
        return MAX_WEBHOOK_URL.strip()
    backend_public = os.getenv("BACKEND_PUBLIC_URL", "")
    if backend_public.startswith("https://"):
        return f"{backend_public.rstrip('/')}/api/max/webhook"
    return ""


async def configure_max_webhook_subscription() -> dict[str, Any]:
    wh_url = max_webhook_url()
    if not wh_url.startswith("https://"):
        MAX_POLLING_DIAG.update({
            "webhookConfigured": False,
            "webhookUrlSet": False,
            "subscriptionStatus": "missing_https_url",
            "updateTypes": ["bot_started", "message_callback", "message_created"],
        })
        raise HTTPException(400, "MAX_WEBHOOK_URL or BACKEND_PUBLIC_URL must be an HTTPS URL.")
    body: dict[str, Any] = {
        "url": wh_url,
        "update_types": ["bot_started", "message_callback", "message_created"],
    }
    if MAX_WEBHOOK_SECRET:
        body["secret"] = MAX_WEBHOOK_SECRET
    try:
        result = await max_api("POST", "/subscriptions", body)
        MAX_POLLING_DIAG.update({
            "webhookConfigured": True,
            "webhookUrlSet": True,
            "subscriptionStatus": "ok",
            "updateTypes": body["update_types"],
        })
        print("MAX webhook subscription status=ok updateTypes=bot_started,message_callback,message_created")
        return result
    except Exception as exc:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        MAX_POLLING_DIAG.update({
            "webhookConfigured": False,
            "webhookUrlSet": True,
            "subscriptionStatus": f"error:{status or type(exc).__name__}",
            "updateTypes": body["update_types"],
        })
        print(f"MAX webhook subscription status=error apiStatus={status or 'unknown'} error={type(exc).__name__}")
        raise


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
    payload: dict[str, Any] = {"text": answer["text"]}
    if buttons:
        row = []
        for button in buttons:
            if button.get("callback_data"):
                row.append({"type": "callback", "text": button["text"], "payload": button["callback_data"]})
            elif button.get("url"):
                row.append({"type": "link", "text": button["text"], "url": button["url"]})
        if row:
            payload["attachments"] = [
                {
                    "type": "inline_keyboard",
                    "payload": {"buttons": [row]},
                }
            ]
    return payload


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


def pending_max_login_challenges_count() -> int:
    with db() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM auth_login_challenges WHERE provider = 'max' AND status = 'pending'"
        ).fetchone()["c"]


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
        if approved and user:
            schedule_avatar_cache("telegram", str(user.get("id") or ""))
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
    callback = update.get("callback") or update.get("message_callback") or {}
    message = (
        update.get("message")
        or update.get("message_created", {}).get("message")
        or update.get("bot_started", {}).get("message")
        or callback.get("message")
        or {}
    )
    body = message.get("body") or {}
    text = callback.get("payload") or callback.get("data") or message.get("text") or body.get("text") or ""
    return text, message


def max_recipient_params(message: dict[str, Any], update: dict[str, Any] | None = None) -> dict[str, Any]:
    recipient = message.get("recipient") or {}
    chat_id = message.get("chat_id") or recipient.get("chat_id")
    user_id = message.get("user_id") or recipient.get("user_id") or message.get("sender", {}).get("user_id") or message.get("sender", {}).get("id")
    # Real MAX bot_started shape carries no message object; recipient lives at the
    # top level (chat_id + user_id). Fall back to it only when message has none.
    if not chat_id and not user_id and isinstance(update, dict):
        chat_id = update.get("chat_id")
        top_user = update.get("user") if isinstance(update.get("user"), dict) else {}
        user_id = update.get("user_id") or top_user.get("user_id") or top_user.get("id")
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
    update_type = max_update_type(update)
    user_present = bool(max_user_from_update(update, message))
    payload_prefix = sanitized_payload_prefix(text if isinstance(text, str) else None)
    if update_type in {"bot_started", "botStarted"} or payload_prefix in {"login_", "approve_"}:
        print(f"MAX_UPDATE type={update_type} hasPayload={bool(payload_prefix)} payloadPrefix={payload_prefix or 'none'} userIdPresent={user_present}")
    if isinstance(text, str) and (text.startswith("approve:") or text.startswith("/approve ")):
        MAX_POLLING_DIAG["lastCallbackAt"] = datetime.now(timezone.utc).isoformat()
        print(f"MAX approve callback received payloadPrefix={payload_prefix or 'none'} userIdPresent={user_present}")
        token_source = text.replace("approve:", "", 1) if text.startswith("approve:") else text.split(maxsplit=1)[1]
        token = bot_login_token_from_payload(token_source)
        user = max_user_from_update(update, message)
        approved = bool(token and user and approve_bot_login_challenge("max", token, user))
        print(f"MAX challenge status={'approved' if approved else 'rejected'}")
        if approved and user:
            schedule_avatar_cache("max", str(user.get("id") or ""))
        params = max_recipient_params(message, update)
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
        MAX_POLLING_DIAG["lastBotStartedAt"] = datetime.now(timezone.utc).isoformat()
        print(f"MAX payload login_ received userIdPresent={user_present}")
        answer = bot_command_response("max", login_payload)
        params = max_recipient_params(message, update)
        if send_replies and params:
            await max_api("POST", "/messages", max_message_payload(answer), params=params)
            print("MAX confirmation button sent")
        return {"update": update, "recipient": params, "answer": answer}
    if isinstance(text, str) and text.startswith("/"):
        answer = bot_command_response("max", text)
        params = max_recipient_params(message, update)
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
    now_iso = datetime.now(timezone.utc).isoformat()
    params: dict[str, Any] = {"limit": limit, "timeout": timeout}
    marker = get_bot_polling_cursor("max")
    if marker:
        params["marker"] = marker
    MAX_POLLING_DIAG.update({
        "lastPollAt": now_iso,
        "lastPollMarker": marker,
        "lastPollError": None,
    })
    print(f"MAX_POLL_REQUEST marker={mask_short(marker) or 'null'} limit={limit} timeout={timeout}")
    try:
        data = await max_api("GET", "/updates", params=params)
        updates = data.get("updates", [])
        handled = await handle_max_updates(updates, send_replies=True)
        response_marker = data.get("marker")
        if response_marker:
            set_bot_polling_cursor("max", response_marker)
        MAX_POLLING_DIAG.update({
            "lastPollStatus": 200,
            "lastPollError": None,
            "lastPollNextMarker": response_marker,
            "lastRawCount": len(updates),
        })
        print(f"MAX_POLL_RESPONSE status=200 rawCount={len(updates)} nextMarker={mask_short(response_marker) or 'null'}")
        return {"ok": True, "handled": handled, "rawCount": len(updates), "marker": get_bot_polling_cursor("max")}
    except Exception as exc:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        MAX_POLLING_DIAG.update({
            "lastPollStatus": status,
            "lastPollError": type(exc).__name__,
            "lastRawCount": None,
        })
        print(f"MAX_POLL_RESPONSE status={status or 'error'} rawCount=0 nextMarker=null error={type(exc).__name__}")
        raise


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
    while MAX_UPDATES_MODE == "polling" and MAX_POLLING_ENABLED and MAX_BOT_TOKEN and MAX_API_BASE_URL:
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
    if BOT_UPDATES_MODE == "polling" and TELEGRAM_POLLING_ENABLED and TELEGRAM_BOT_TOKEN and "telegram" not in bot_polling_tasks:
        bot_polling_tasks["telegram"] = asyncio.create_task(telegram_polling_worker())
        started.append("telegram")
    if MAX_UPDATES_MODE == "polling" and MAX_POLLING_ENABLED and MAX_BOT_TOKEN and MAX_API_BASE_URL and "max" not in bot_polling_tasks:
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


def _delete_media_rel(rel: str | None) -> None:
    if not rel:
        return
    try:
        target = (MEDIA / rel).resolve()
        target.relative_to(MEDIA.resolve())
        if target.exists() and target.is_file():
            target.unlink()
    except Exception:
        pass


def retire_feed_publications_for_image(conn: sqlite3.Connection, image_id: str, now: str, reason: str = "source_image_deleted") -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(feed_publications)").fetchall()}
    if not columns:
        return
    media_columns = {"feed_thumb_name", "feed_large_name", "media_ready_at", "media_error", "updated_at"}
    rows = conn.execute(
        "SELECT id, feed_thumb_name, feed_large_name FROM feed_publications WHERE image_id = ?",
        (image_id,),
    ).fetchall()
    for row in rows:
        _delete_media_rel(_row_get(row, "feed_thumb_name"))
        _delete_media_rel(_row_get(row, "feed_large_name"))
    if media_columns <= columns:
        conn.execute(
            "UPDATE feed_publications SET status = 'hidden', feed_thumb_name = NULL, feed_large_name = NULL, "
            "media_ready_at = NULL, media_error = ?, updated_at = ? WHERE image_id = ?",
            (reason, now, image_id),
        )
    else:
        conn.execute("UPDATE feed_publications SET status = 'hidden' WHERE image_id = ?", (image_id,))


def create_thumbnail(image_path: Path) -> Path:
    thumb_path = image_path.with_name(f"{image_path.stem}_thumb.webp")
    with Image.open(image_path) as image:
        image.thumbnail((512, 512))
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")
        image.save(thumb_path, "WEBP", quality=88)
    return thumb_path


def save_gallery_original(image: Image.Image, job_id: str) -> Path:
    out = MEDIA / f"{job_id}.webp"
    prepared = ImageOps.exif_transpose(image)
    if prepared.mode not in {"RGB", "RGBA"}:
        prepared = prepared.convert("RGB")
    prepared.thumbnail((GALLERY_IMAGE_MAX_SIDE, GALLERY_IMAGE_MAX_SIDE), Image.Resampling.LANCZOS)
    prepared.save(out, "WEBP", quality=GALLERY_IMAGE_WEBP_QUALITY, method=6)
    return out


def admin_secret_value(key: str) -> str:
    try:
        with db() as conn:
            row = conn.execute("SELECT value FROM admin_secrets WHERE key = ?", (key,)).fetchone()
        return str(row["value"] or "").strip() if row else ""
    except Exception:
        return ""


def save_admin_secret(key: str, value: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            "INSERT INTO admin_secrets (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, now),
        )
    _admin_models_page_cache["ts"] = 0.0
    _admin_models_page_cache["data"] = None


def delete_admin_secret(key: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM admin_secrets WHERE key = ?", (key,))
    _admin_models_page_cache["ts"] = 0.0
    _admin_models_page_cache["data"] = None


def openrouter_api_key_source() -> str:
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        return "env"
    if admin_secret_value("openrouter_api_key"):
        return "admin_ui"
    return "none"


def openrouter_api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip() or admin_secret_value("openrouter_api_key")


def openrouter_headers() -> dict[str, str]:
    headers = {"Authorization": f"Bearer {openrouter_api_key()}", "Content-Type": "application/json"}
    referer = os.getenv("OPENROUTER_SITE_URL", "").strip()
    title = os.getenv("OPENROUTER_SITE_NAME", "IZO ASA").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-Title"] = title
    return headers


def resolve_openrouter_model(req: GenerateRequest) -> str:
    raw = (req.modelProfile or "").strip()
    aliases = {
        "": "black-forest-labs/flux.2-klein-4b",
        "openrouter_cloud": "black-forest-labs/flux.2-klein-4b",
        "openrouter_gpt_image": "openai/gpt-image-1",
        "openrouter_recraft": "recraft/recraft-v3",
        "openrouter_gemini_image": "google/gemini-2.5-flash-image",
        "local_flux_klein": "black-forest-labs/flux.2-klein-4b",
    }
    return aliases.get(raw, raw if "/" in raw else "black-forest-labs/flux.2-klein-4b")


def _openrouter_generation_cost(payload: dict[str, Any]) -> float | None:
    candidates = [
        payload.get("cost"),
        payload.get("total_cost"),
        payload.get("total_cost_usd"),
        (payload.get("usage") or {}).get("cost"),
        (payload.get("usage") or {}).get("total_cost"),
        (payload.get("usage") or {}).get("total_cost_usd"),
    ]
    for value in candidates:
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _openrouter_first_image(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return first
    images_data = payload.get("images")
    if isinstance(images_data, list) and images_data:
        first = images_data[0]
        if isinstance(first, dict):
            return first
        if isinstance(first, str):
            return {"url": first}
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict):
                if item.get("b64_json") or item.get("url"):
                    return item
                content = item.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and (part.get("b64_json") or part.get("url")):
                            return part
    raise RuntimeError("OpenRouter не вернул изображение в ответе.")


async def _openrouter_image_to_pil(image_payload: dict[str, Any]) -> Image.Image:
    b64_value = image_payload.get("b64_json") or image_payload.get("base64") or image_payload.get("image_base64")
    if isinstance(b64_value, str) and b64_value:
        if "," in b64_value and b64_value.split(",", 1)[0].startswith("data:"):
            b64_value = b64_value.split(",", 1)[1]
        return Image.open(io.BytesIO(base64.b64decode(b64_value)))
    url = image_payload.get("url")
    if isinstance(url, str) and url:
        async with httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        return Image.open(io.BytesIO(response.content))
    raise RuntimeError("OpenRouter response не содержит b64_json или url изображения.")


async def fetch_openrouter_key_status() -> dict[str, Any]:
    key = openrouter_api_key()
    if not key:
        return {"configured": False, "ok": False, "error": "OPENROUTER_API_KEY не задан"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{OPENROUTER_BASE_URL}/key", headers=openrouter_headers())
            credits_response = await client.get(f"{OPENROUTER_BASE_URL}/credits", headers=openrouter_headers())
        data = response.json() if response.content else {}
        if response.status_code >= 400:
            return {"configured": True, "source": openrouter_api_key_source(), "ok": False, "status_code": response.status_code, "error": data.get("error") or data}
        key_data = data.get("data") if isinstance(data.get("data"), dict) else data
        credits_payload = credits_response.json() if credits_response.content else {}
        credits_data = credits_payload.get("data") if isinstance(credits_payload.get("data"), dict) else credits_payload
        credits: dict[str, Any] = {"ok": credits_response.status_code < 400, "status_code": credits_response.status_code}
        if credits["ok"] and isinstance(credits_data, dict):
            total_credits = credits_data.get("total_credits")
            total_usage = credits_data.get("total_usage")
            credits.update({"data": credits_data})
            if isinstance(total_credits, (int, float)) and isinstance(total_usage, (int, float)):
                credits["balance"] = round(float(total_credits) - float(total_usage), 6)
        else:
            credits["error"] = credits_payload.get("error") if isinstance(credits_payload, dict) else credits_payload
        return {"configured": True, "source": openrouter_api_key_source(), "ok": True, "status_code": response.status_code, "data": key_data, "credits": credits}
    except Exception as exc:
        return {"configured": True, "source": openrouter_api_key_source(), "ok": False, "error": str(exc)}


async def send_to_openrouter(payload: GenerateRequest, job: dict[str, Any]) -> OpenRouterResult:
    if not openrouter_api_key():
        raise RuntimeError("OPENROUTER_API_KEY не задан. Добавьте ключ перед включением OpenRouter.")
    model = resolve_openrouter_model(payload)
    body: dict[str, Any] = {
        "model": model,
        "prompt": payload.prompt,
        "n": 1,
        "size": f"{payload.width}x{payload.height}",
    }
    job.update(status="sent_to_openrouter", progress=24, message="Отправляем в OpenRouter")
    persist_job(job, payload)
    async with httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT_SECONDS) as client:
        response = await client.post(f"{OPENROUTER_BASE_URL}/images", headers=openrouter_headers(), json=body)
    data = response.json() if response.content else {}
    if response.status_code >= 400:
        raise RuntimeError(f"OpenRouter API error {response.status_code}: {data.get('error') or data}")
    image_payload = _openrouter_first_image(data)
    with await _openrouter_image_to_pil(image_payload) as opened:
        image_path = save_gallery_original(opened, f"{job['id']}_openrouter")
    return OpenRouterResult(
        image_path=image_path,
        thumbnail_path=create_thumbnail(image_path),
        response_id=data.get("id") or data.get("response_id"),
        model=model,
        usage=data.get("usage") if isinstance(data.get("usage"), dict) else {},
        cost_usd=_openrouter_generation_cost(data),
        raw={k: v for k, v in data.items() if k not in {"data", "images", "output"}},
    )


def feed_media_dir() -> Path:
    path = MEDIA / "feed"
    path.mkdir(exist_ok=True)
    return path


def _media_file_path_from_url(url: str | None) -> Path | None:
    name = _feed_media_name(url)
    if not name:
        return None
    path = (MEDIA / name).resolve()
    try:
        path.relative_to(MEDIA.resolve())
    except ValueError:
        return None
    return path


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


def effective_face_profile(_: str = "") -> str:
    """Face mode is pinned to Flux 2 Klein 9B.

    The face/head LoRA we ship and validate is the 9B variant, so this route must
    not follow the generic edit model if an operator temporarily switches edit to
    4B. Keeping the same 9B UNET name lets ComfyUI reuse the already loaded base
    model instead of drifting into a different workflow/model pair.
    """
    return "flux_klein_9b"


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


def choose_faceswap_lora(available_loras: list[str], requested: Lora | None, model: str) -> Lora:
    """Return the face/head LoRA matching the loaded Flux Klein variant."""
    target_tag = "4b" if "4b" in model.lower() else "9b"
    requested_strength = requested.strength if requested else 1.0
    requested_id = (requested.id if requested else "").strip()
    if requested_id and requested_id != "none" and target_tag in requested_id.lower() and requested_id in available_loras:
        return Lora(id=requested_id, strength=requested_strength)
    match = next(
        (
            item for item in available_loras
            if target_tag in item.lower() and any(kw in item.lower() for kw in ("bfs", "face", "head"))
        ),
        "",
    )
    if not match:
        raise RuntimeError(f"FaceSwap LoRA for Flux Klein {target_tag.upper()} not found in ComfyUI.")
    return Lora(id=match, strength=requested_strength)


async def upload_to_comfyui(path: Path) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        with path.open("rb") as file:
            files = {"image": (path.name, file, "image/png")}
            data = {"overwrite": "true", "type": "input"}
            response = await client.post(f"{COMFYUI_BASE_URL}/upload/image", files=files, data=data)
        response.raise_for_status()
        payload = response.json()
    return payload.get("name") or path.name


def _fit_comfyui_input_size(source_size: tuple[int, int], target_box: tuple[int, int] | None = None, max_side: int | None = None) -> tuple[int, int]:
    source_w, source_h = source_size
    if source_w <= 0 or source_h <= 0:
        return (1024, 1024)
    limit = max(COMFYUI_INPUT_MIN_SIDE, min(COMFYUI_INPUT_MAX_SIDE, int(max_side or COMFYUI_INPUT_MAX_SIDE)))
    box_w = target_box[0] if target_box else COMFYUI_INPUT_MAX_SIDE
    box_h = target_box[1] if target_box else COMFYUI_INPUT_MAX_SIDE
    box_w = max(COMFYUI_INPUT_MIN_SIDE, min(limit, int(box_w or limit)))
    box_h = max(COMFYUI_INPUT_MIN_SIDE, min(limit, int(box_h or limit)))
    scale = min(1.0, box_w / source_w, box_h / source_h, limit / max(source_w, source_h))
    width = max(16, int(round((source_w * scale) / 16) * 16))
    height = max(16, int(round((source_h * scale) / 16) * 16))
    if max(width, height) > limit:
        scale = limit / max(width, height)
        width = max(16, int(round((width * scale) / 16) * 16))
        height = max(16, int(round((height * scale) / 16) * 16))
    return width, height


def prepare_comfyui_input_image(image_path: Path | None, prefix: str, req: GenerateRequest, max_side: int | None = None) -> Path | None:
    """Return an input image safe for ComfyUI VRAM: same aspect, bounded size."""
    if not image_path or not image_path.exists():
        return image_path
    try:
        with Image.open(image_path) as opened:
            image = ImageOps.exif_transpose(opened)
            target_size = _fit_comfyui_input_size(image.size, (req.width, req.height), max_side=max_side)
            if image.size == target_size:
                return image_path
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            resized = image.resize(target_size, resample)
            if resized.mode not in ("RGB", "RGBA"):
                resized = resized.convert("RGBA" if "A" in resized.getbands() else "RGB")
            out = MEDIA / f"{prefix}_{uuid.uuid4().hex}_comfy.png"
            resized.save(out, "PNG", optimize=True)
            print(f"comfyui input resized {image_path.name}: {image.size[0]}x{image.size[1]} -> {target_size[0]}x{target_size[1]}")
            return out
    except Exception as exc:
        print(f"comfyui input resize skipped {image_path.name}: {type(exc).__name__}")
        return image_path


def _outpaint_padding(req: GenerateRequest) -> dict[str, int]:
    raw = req.outpaint or {}
    padding: dict[str, int] = {}
    for key in ("left", "right", "top", "bottom"):
        try:
            value = int(raw.get(key, 0))
        except Exception:
            value = 0
        padding[key] = max(0, min(8192, value))
    return padding


def _outpaint_int(raw: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        value = raw.get(key, default)
        if isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _outpaint_placement(req: GenerateRequest, target_w: int, target_h: int) -> dict[str, int] | None:
    raw = req.outpaint or {}
    required = ("sourceX", "sourceY", "sourceW", "sourceH")
    if not all(key in raw for key in required):
        return None
    frame_w = max(1, _outpaint_int(raw, "frameW", req.width or target_w))
    frame_h = max(1, _outpaint_int(raw, "frameH", req.height or target_h))
    source_w = max(1, _outpaint_int(raw, "sourceW", frame_w))
    source_h = max(1, _outpaint_int(raw, "sourceH", frame_h))
    scale_x = target_w / frame_w
    scale_y = target_h / frame_h
    return {
        "x": int(round(_outpaint_int(raw, "sourceX", 0) * scale_x)),
        "y": int(round(_outpaint_int(raw, "sourceY", 0) * scale_y)),
        "w": max(1, int(round(source_w * scale_x))),
        "h": max(1, int(round(source_h * scale_y))),
    }


def prepare_comfyui_outpaint_inputs(input_path: Path | None, prefix: str, req: GenerateRequest) -> tuple[Path | None, Path | None]:
    """Build a real outpaint canvas and mask for ComfyUI.

    The source image is placed inside the requested output frame. White mask
    pixels mark the empty border areas to regenerate, black pixels preserve the
    original source region.
    """
    if not input_path or not input_path.exists():
        return input_path, None
    padding = _outpaint_padding(req)
    if not any(padding.values()):
        prepared = prepare_comfyui_input_image(input_path, prefix, req)
        return prepared, None
    try:
        with Image.open(input_path) as opened:
            source = ImageOps.exif_transpose(opened).convert("RGB")
            source_w, source_h = source.size
            final_w = max(1, source_w + padding["left"] + padding["right"])
            final_h = max(1, source_h + padding["top"] + padding["bottom"])
            target_w = max(16, int(round(req.width / 16) * 16))
            target_h = max(16, int(round(req.height / 16) * 16))
            target_w = min(COMFYUI_INPUT_MAX_SIDE, max(COMFYUI_INPUT_MIN_SIDE, target_w))
            target_h = min(COMFYUI_INPUT_MAX_SIDE, max(COMFYUI_INPUT_MIN_SIDE, target_h))
            placement = _outpaint_placement(req, target_w, target_h)
            if placement is not None:
                resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
                resized = source.resize((placement["w"], placement["h"]), resample)
                left = max(0, placement["x"])
                top = max(0, placement["y"])
                right = min(target_w, placement["x"] + placement["w"])
                bottom = min(target_h, placement["y"] + placement["h"])
                if right <= left or bottom <= top:
                    prepared = prepare_comfyui_input_image(input_path, prefix, req)
                    return prepared, None
                crop = (
                    left - placement["x"],
                    top - placement["y"],
                    right - placement["x"],
                    bottom - placement["y"],
                )
                canvas = Image.new("RGB", (target_w, target_h), "#000000")
                canvas.paste(resized.crop(crop), (left, top))

                mask = Image.new("L", (target_w, target_h), 255)
                draw = ImageDraw.Draw(mask)
                draw.rectangle([left, top, right - 1, bottom - 1], fill=0)

                image_out = MEDIA / f"{prefix}_{uuid.uuid4().hex}_outpaint_input.png"
                mask_out = MEDIA / f"{prefix}_{uuid.uuid4().hex}_outpaint_mask.png"
                canvas.save(image_out, "PNG", optimize=True)
                mask.convert("RGB").save(mask_out, "PNG", optimize=True)
                print(
                    "comfyui outpaint placement prepared "
                    f"{input_path.name}: source={source_w}x{source_h} "
                    f"placement={placement['x']},{placement['y']},{placement['w']},{placement['h']} "
                    f"target={target_w}x{target_h}"
                )
                return image_out, mask_out

            scale_x = target_w / final_w
            scale_y = target_h / final_h
            left = int(round(padding["left"] * scale_x))
            top = int(round(padding["top"] * scale_y))
            right = int(round((padding["left"] + source_w) * scale_x))
            bottom = int(round((padding["top"] + source_h) * scale_y))
            right = max(left + 1, min(target_w, right))
            bottom = max(top + 1, min(target_h, bottom))
            left = max(0, min(target_w - 1, left))
            top = max(0, min(target_h - 1, top))

            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            source_resized = source.resize((right - left, bottom - top), resample)
            canvas = Image.new("RGB", (target_w, target_h), "#000000")
            canvas.paste(source_resized, (left, top))

            mask = Image.new("L", (target_w, target_h), 255)
            draw = ImageDraw.Draw(mask)
            draw.rectangle([left, top, right - 1, bottom - 1], fill=0)

            image_out = MEDIA / f"{prefix}_{uuid.uuid4().hex}_outpaint_input.png"
            mask_out = MEDIA / f"{prefix}_{uuid.uuid4().hex}_outpaint_mask.png"
            canvas.save(image_out, "PNG", optimize=True)
            mask.convert("RGB").save(mask_out, "PNG", optimize=True)
            print(
                "comfyui outpaint prepared "
                f"{input_path.name}: source={source_w}x{source_h} "
                f"padding={padding['left']},{padding['right']},{padding['top']},{padding['bottom']} "
                f"target={target_w}x{target_h}"
            )
            return image_out, mask_out
    except Exception as exc:
        print(f"comfyui outpaint prepare failed {input_path.name}: {type(exc).__name__}")
        prepared = prepare_comfyui_input_image(input_path, prefix, req)
        return prepared, None


async def fetch_workflow(mode: str) -> dict[str, Any]:
    workflow_by_mode = {
        "text_to_image": "workflow_t2i",
        "image_to_image": "workflow_i2i",
        "edit": "workflow_edit",
        "paint": "workflow_edit",
        "inpaint": "workflow_inpaint",
        "outpaint": "workflow_outpaint",
        # Dedicated workflow_faceswap hangs on Flux 2 Klein 9B in production.
        # Use the stable multi-reference edit graph: target image + face reference.
        "faceswap": "workflow_edit",
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
    set_input(prompt, "FK:156", "text", "" if req.mode in {"edit", "faceswap"} else (req.negativePrompt or DEFAULT_NEG_PROMPT))
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
    elif req.mode in {"edit", "paint", "faceswap", "try_on", "texture_transfer"}:
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
        set_input(prompt, "FKO:209", "preresize_min_width", req.width)
        set_input(prompt, "FKO:209", "preresize_min_height", req.height)
        set_input(prompt, "FKO:209", "output_target_width", req.width)
        set_input(prompt, "FKO:209", "output_target_height", req.height)
        set_input(prompt, "FKO:163", "seed", req.seed)
        set_input(prompt, "FKO:163", "steps", req.steps)
        set_input(prompt, "FKO:163", "cfg", req.cfg)
        set_input(prompt, "FKO:163", "denoise", 1)
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
        set_input(prompt, "FKF:scaleSrc", "megapixels", COMFYUI_FACE_SOURCE_MEGAPIXELS)
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


async def interrupt_comfyui_prompt() -> None:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{COMFYUI_BASE_URL}/interrupt")
    except Exception:
        pass


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
    timeout = COMFYUI_FACE_TIMEOUT_SECONDS if job.get("mode") == "faceswap" else COMFYUI_TIMEOUT_SECONDS
    deadline = time.monotonic() + timeout
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
    await interrupt_comfyui_prompt()
    raise TimeoutError("ComfyUI не вернул результат до истечения таймаута.")


async def download_comfyui_image(image: dict[str, str], job_id: str) -> tuple[Path, Path]:
    params = {"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")}
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.get(f"{COMFYUI_BASE_URL}/view", params=params)
        response.raise_for_status()
        with Image.open(io.BytesIO(response.content)) as opened:
            image_path = save_gallery_original(opened, f"{job_id}_comfyui")
    return image_path, create_thumbnail(image_path)


async def send_to_comfyui(payload: GenerateRequest, job: dict[str, Any]) -> ComfyUIResult | None:
    if not await comfyui_available():
        if COMFYUI_REQUIRED:
            raise RuntimeError("FluxKleinOneNode не найден или ComfyUI недоступен. Проверьте установку custom node.")
        if not COMFYUI_MOCK_FALLBACK:
            raise RuntimeError("ComfyUI недоступен. Проверьте, что сервер запущен.")
        return None

    models = await get_comfyui_models()
    profile_id = effective_face_profile(payload.modelProfile) if payload.mode == "faceswap" else effective_edit_profile(payload.modelProfile)
    model, text_encoder, vae = choose_model(models, profile_id)
    available_loras = models.get("loras", [])
    if payload.mode == "faceswap":
        face_lora = choose_faceswap_lora(available_loras, payload.loras[0] if payload.loras else None, model)
        payload.loras = [face_lora]
        print(
            "faceswap-route "
            f"job={job['id']} profile={profile_id} model={model} "
            f"text_encoder={text_encoder} lora={face_lora.id} max_side={COMFYUI_FACE_INPUT_MAX_SIDE}"
        )
    else:
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
    outpaint_generated_mask = False
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
            slot_path = prepare_comfyui_input_image(slot_path, f"{job['id']}_edit{i + 1}", payload)
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
        if payload.mode == "outpaint":
            primary_input, generated_mask = prepare_comfyui_outpaint_inputs(primary_input, f"{job['id']}_input1", payload)
            if generated_mask:
                mask_path = generated_mask
                outpaint_generated_mask = True
        elif payload.mode == "faceswap":
            primary_input = prepare_comfyui_input_image(primary_input, f"{job['id']}_input1", payload, max_side=COMFYUI_FACE_INPUT_MAX_SIDE)
        else:
            primary_input = prepare_comfyui_input_image(primary_input, f"{job['id']}_input1", payload)
        uploads["input1"] = await upload_to_comfyui(primary_input)
    if payload.mode in {"faceswap", "try_on", "texture_transfer"}:
        if not input2_path:
            raise RuntimeError("Для выбранного режима нужно два изображения.")
        input2_path = prepare_comfyui_input_image(
            input2_path,
            f"{job['id']}_input2",
            payload,
            max_side=COMFYUI_FACE_INPUT_MAX_SIDE if payload.mode == "faceswap" else None,
        )
        uploads["input2"] = await upload_to_comfyui(input2_path)
    if payload.mode in {"inpaint", "outpaint"} and mask_path:
        if payload.mode != "outpaint" or not outpaint_generated_mask:
            mask_path = prepare_comfyui_input_image(mask_path, f"{job['id']}_mask", payload)
        uploads["mask"] = await upload_to_comfyui(mask_path)

    if pose_graph is not None:
        workflow = pose_graph
    else:
        patch_mode_nodes(workflow, payload, uploads, model, text_encoder, vae)
    try:
        prompt_id, history, output_images = await submit_workflow(workflow, job)
    except Exception as exc:
        if payload.mode == "faceswap":
            raise RuntimeError(f"FaceSwap workflow failed: {exc}") from exc
        if payload.mode not in {"inpaint", "outpaint", "faceswap", "remove_background", "try_on", "texture_transfer"}:
            raise
        prompt_id = "fallback_after_workflow_error"
        history = {"error": str(exc)}
        output_images = []
    if payload.mode == "faceswap" and not output_images:
        raise RuntimeError("FaceSwap workflow completed without output image.")
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
    out = save_gallery_original(image, job_id)
    return out, create_thumbnail(out)


async def worker() -> None:
    while True:
        job_id = await queue.get()
        job = jobs[job_id]
        req = GenerateRequest(**job["request"])
        started = time.perf_counter()
        try:
            if job.get("status") == "cancelled":
                with db() as conn:
                    refund_generation_tokens(conn, job_id, reason="cancelled_before_start")
                persist_job(job, req)
                continue
            job.update(status="uploading", progress=12, message="Загружаем изображения")
            persist_job(job, req)
            await asyncio.sleep(0.5)
            prompt_id = None
            image_path = None
            thumb_path = None
            comfyui_history = None
            openrouter_result: OpenRouterResult | None = None
            if req.provider == "comfyui":
                job.update(status="sent_to_comfyui", progress=24, message="Отправляем в ComfyUI")
                persist_job(job, req)
                result = await send_to_comfyui(req, job)
                if result:
                    prompt_id = result.prompt_id
                    image_path = result.image_path
                    thumb_path = result.thumbnail_path
                    comfyui_history = result.history
            elif req.provider == "openrouter":
                openrouter_result = await send_to_openrouter(req, job)
                image_path = openrouter_result.image_path
                thumb_path = openrouter_result.thumbnail_path
                openrouter_billing = finalize_openrouter_billing_snapshot(job.get("openrouterBilling") or {}, openrouter_result.cost_usd)
                job.update(
                    openrouterModel=openrouter_result.model,
                    openrouterResponseId=openrouter_result.response_id,
                    openrouterUsage=openrouter_result.usage,
                    openrouterCostUsd=openrouter_result.cost_usd,
                    openrouterBilling=openrouter_billing,
                )
            if not image_path:
                if req.provider == "comfyui" and not COMFYUI_MOCK_FALLBACK:
                    raise RuntimeError("ComfyUI не вернул изображение, mock fallback отключён.")
                if req.provider == "openrouter":
                    raise RuntimeError("OpenRouter не вернул изображение.")
                await asyncio.sleep(0.8)
                for progress in (38, 52, 67, 81, 94):
                    if job["status"] == "cancelled":
                        break
                    job.update(status="running", progress=progress, message="Генерация изображения")
                    persist_job(job, req)
                    await asyncio.sleep(0.45)
            if job["status"] == "cancelled":
                with db() as conn:
                    refund_generation_tokens(conn, job_id, reason="cancelled_during_generation")
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
                "openrouterModel": openrouter_result.model if openrouter_result else None,
                "openrouterResponseId": openrouter_result.response_id if openrouter_result else None,
                "openrouterUsage": openrouter_result.usage if openrouter_result else None,
                "openrouterCostUsd": openrouter_result.cost_usd if openrouter_result else None,
                "openrouterBilling": job.get("openrouterBilling") if openrouter_result else None,
            }
            if gallery_quota["gallery_full"]:
                with db() as conn:
                    evicted_count = evict_gallery_images_for_new_save(conn, user_id, gallery_quota, created_at)
                if evicted_count:
                    images[image_id] = record
                    persist_image(record, job_id)
                    sources = persist_image_sources(image_id, user_id, req, created_at)
                    if sources:
                        images[image_id]["sources"] = sources
                    save_status = "saved"
                    result_image_id = image_id
                else:
                    # All occupied slots are protected by favorites. Do not evict
                    # them automatically; return the generated file for this job
                    # but leave gallery storage unchanged.
                    images[image_id] = record
                    save_status = "quota_full"
                    result_image_id = None
                with db() as conn:
                    saved_user_row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                    gallery_quota = gallery_quota_for_user(conn, saved_user_row, user_id)
                job.update(
                    status="completed",
                    progress=100,
                    message="Готово",
                    resultImageId=result_image_id,
                    resultUrl=record["url"],
                    gallerySaveStatus=save_status,
                    galleryQuota=gallery_quota,
                    completedAt=created_at,
                )
            else:
                images[image_id] = record
                persist_image(record, job_id)
                sources = persist_image_sources(image_id, user_id, req, created_at)
                if sources:
                    images[image_id]["sources"] = sources
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
            with db() as conn:
                refund_generation_tokens(conn, job_id, reason="generation_failed")
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
    start_bot_polling_tasks()
    if BOT_UPDATES_MODE == "webhook":
        backend_public = os.getenv("BACKEND_PUBLIC_URL", "http://127.0.0.1:8000")
        if TELEGRAM_BOT_TOKEN and backend_public.startswith("https://"):
            try:
                wh_url = f"{backend_public}/api/telegram/webhook"
                await telegram_api("setWebhook", {"url": wh_url})
                print(f"Telegram webhook set to {wh_url}")
            except Exception as exc:
                print(f"Failed to set Telegram webhook: {exc}")
    if MAX_UPDATES_MODE == "webhook" and MAX_BOT_TOKEN:
        try:
            await configure_max_webhook_subscription()
        except Exception as exc:
            print(f"Failed to set MAX webhook subscription: {type(exc).__name__}")


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
    hourly_limit = int(rate_limits.get("hourly") or 0)
    daily_limit = int(rate_limits.get("daily") or 0)
    if hourly_limit <= 0 and daily_limit <= 0:
        return
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
    if hourly_limit > 0 and hour_count >= hourly_limit:
        raise HTTPException(429, f"Rate limit exceeded: {hourly_limit} generations per hour.")
    if daily_limit > 0 and day_count >= daily_limit:
        raise HTTPException(429, f"Rate limit exceeded: {daily_limit} generations per day.")


@app.post("/api/generate")
async def generate(req: GenerateRequest, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    internal_user_id = trusted["internal_user_id"]
    session_id = trusted.get("session_id")
    openrouter_billing: dict[str, Any] | None = None
    with db() as conn:
        user_row = conn.execute("SELECT id, plan FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_row is None:
            raise HTTPException(404, "User not found.")
    if req.provider == "openrouter":
        plan = str(user_row["plan"] or "mini").lower()
        if plan not in PLAN_ORDER:
            plan = "mini"
        openrouter_config = get_openrouter_config()
        if not openrouter_model_allowed(openrouter_config, req.mode, plan, req.modelProfile):
            raise HTTPException(403, "This OpenRouter model is not available for this mode and tariff.")
        openrouter_billing = await estimate_openrouter_billing(req)
        token_cost = int(openrouter_billing["chargedTokens"])
    else:
        token_cost = estimate_token_cost(req)
    # FaceSwap lora auto-selection is handled by choose_faceswap_lora() inside
    # send_to_comfyui (worker). Early validation here is redundant and breaks
    # the flow when frontend sends an empty loras list — the worker always
    # resolves the correct face lora from ComfyUI's available models.
    if req.mode == "edit":
        validate_edit_request(req)
    validate_generation_media_inputs(req, user_id)
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
        "openrouterBilling": openrouter_billing,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    with db() as conn:
        token_charge = charge_generation_tokens(conn, user_id, token_cost, job_id, req, openrouter_billing)
        persist_job(job, req, conn=conn)
    jobs[job_id] = job
    await queue.put(job_id)
    try:
        record_event_log(
            "generation_started",
            internal_user_id=internal_user_id,
            legacy_user_id=user_id,
            session_id=session_id,
            platform=trusted.get("platform", "web"),
            properties={"mode": req.mode, "provider": req.provider, "size": f"{req.width}x{req.height}", "token_cost": token_cost, "openrouter_billing": openrouter_billing},
        )
    except Exception:
        pass
    return {k: v for k, v in job.items() if k != "request"} | {
        "queuePosition": queue.qsize(),
        "tokenCost": token_cost,
        "usedDailyBudget": token_charge["used_daily"],
        "tokenBalance": token_charge["new_balance"],
        "dailyTokensUsed": token_charge["daily_tokens_used"],
        "dailyTokensLimit": token_charge["daily_tokens_limit"],
        "dailyTokensRemaining": token_charge["daily_tokens_remaining"],
    }


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
    if jobs[job_id].get("status") in {"completed", "failed", "cancelled"}:
        return {k: v for k, v in jobs[job_id].items() if k != "request"}
    with db() as conn:
        refund_generation_tokens(conn, job_id, reason="user_cancelled")
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
        return {
            "ok": True,
            "selected": {
                "model": _user_model_name(model),
                "textEncoder": "Flux2 CLIP",
                "vae": "Flux2 VAE",
            },
            "diffusion_models": [_user_model_name(m) for m in data.get("diffusion_models", [])],
            "text_encoders": ["Flux2 CLIP" for _ in data.get("text_encoders", [])],
            "vaes": ["Flux2 VAE" for _ in data.get("vaes", [])],
            "loras": data.get("loras", []),
        }
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
    economy = openrouter_economy_settings()
    return {
        "ok": True,
        "tariffs": get_tariff_config(),
        "economy": {
            "tokenRub": economy["tokenRub"],
        },
    }


@app.get("/api/gallery")
async def gallery(request: Request) -> list[dict[str, Any]]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        if not user_gallery_allowed(conn, trusted["internal_user_id"], user_id):
            raise HTTPException(403, "Gallery is not available for this plan.")
        rows = conn.execute(
            f"SELECT * FROM images WHERE user_id = ? AND {ACTIVE_IMAGE_WHERE} ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    restored = [row_to_image(row) for row in rows]
    for item in restored:
        images[item["id"]] = item
    return restored


@app.get("/api/gallery/page")
async def gallery_page(
    request: Request,
    limit: int = 60,
    cursor: str | None = None,
    q: str = "",
    filter: str = "all",
) -> dict[str, Any]:
    """Structured gallery payload for the new visual shell.

    Keeps /api/gallery stable while giving the gallery page counters, original
    cards and separate feed-copy cards in one DB-backed response.
    """
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    limit = _clamp_limit(limit, default=60, maximum=120)
    cursor_value = parse_gallery_cursor(cursor)
    search = str(q or "").strip()[:120]
    gallery_filter = str(filter or "all").strip().lower()
    with db() as conn:
        user_row = conn.execute(
            "SELECT * FROM users WHERE internal_user_id = ? OR id = ?",
            (trusted["internal_user_id"], user_id),
        ).fetchone()
        if not user_gallery_allowed(conn, trusted["internal_user_id"], user_id):
            raise HTTPException(403, "Gallery is not available for this plan.")
        where_sql = [f"user_id = ?", ACTIVE_IMAGE_WHERE]
        params: list[Any] = [user_id]
        if search:
            like = f"%{search}%"
            where_sql.append(
                "(id LIKE ? OR prompt_original LIKE ? OR prompt_translated LIKE ? OR mode LIKE ? OR provider LIKE ? OR settings_json LIKE ?)"
            )
            params.extend([like, like, like, like, like, like])
        if gallery_filter == "favorite":
            where_sql.append("is_favorite = 1")
        elif gallery_filter == "published":
            where_sql.append("EXISTS (SELECT 1 FROM feed_publications p WHERE p.image_id = images.id AND p.legacy_user_id = ? AND p.status = 'published')")
            params.append(user_id)
        elif gallery_filter == "unpublished":
            where_sql.append("NOT EXISTS (SELECT 1 FROM feed_publications p WHERE p.image_id = images.id AND p.legacy_user_id = ? AND p.status = 'published')")
            params.append(user_id)
        elif gallery_filter == "16:9":
            where_sql.append("width > 0 AND height > 0 AND width * 9 = height * 16")
        elif gallery_filter == "4:5":
            where_sql.append("width > 0 AND height > 0 AND width * 5 = height * 4")
        elif gallery_filter == "1:1":
            where_sql.append("width > 0 AND height > 0 AND width = height")
        elif gallery_filter == "face":
            where_sql.append("mode IN ('face', 'face_swap', 'faceswap')")
        where_clause = " AND ".join(f"({part})" for part in where_sql)
        if cursor_value:
            cursor_created_at, cursor_id = cursor_value
            page_params = [*params, cursor_created_at, cursor_created_at, cursor_id, limit + 1]
            image_rows = conn.execute(
                f"""
                SELECT * FROM images
                WHERE {where_clause}
                  AND (created_at < ? OR (created_at = ? AND id < ?))
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                page_params,
            ).fetchall()
        else:
            page_params = [*params, limit + 1]
            image_rows = conn.execute(
                f"""
                SELECT * FROM images
                WHERE {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                page_params,
            ).fetchall()
        has_more = len(image_rows) > limit
        page_rows = image_rows[:limit]
        publications = {
            row["image_id"]: row
            for row in conn.execute(
                """
                SELECT * FROM feed_publications
                WHERE legacy_user_id = ? AND status = 'published'
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        }
        reaction_counts = {
            row["publication_id"]: row
            for row in conn.execute(
                """
                SELECT publication_id,
                       SUM(CASE WHEN kind = 'like' THEN 1 ELSE 0 END) AS likes,
                       SUM(CASE WHEN kind = 'save' THEN 1 ELSE 0 END) AS saves,
                       SUM(CASE WHEN kind = 'recreate' THEN 1 ELSE 0 END) AS remixes
                FROM feed_reactions
                WHERE publication_id IN (
                    SELECT id FROM feed_publications
                    WHERE legacy_user_id = ? AND status = 'published'
                )
                GROUP BY publication_id
                """,
                (user_id,),
            ).fetchall()
        }
        items = [_gallery_page_item(row, publications.get(row["id"])) for row in page_rows]
        feed_where_sql = [
            "images.user_id = ?",
            ACTIVE_IMAGE_WHERE,
            "p.legacy_user_id = ?",
            "p.status = 'published'",
            "p.media_ready_at IS NOT NULL",
            "p.feed_thumb_name IS NOT NULL",
            "p.feed_large_name IS NOT NULL",
        ]
        feed_params: list[Any] = [user_id, user_id]
        if search:
            like = f"%{search}%"
            feed_where_sql.append(
                "(images.id LIKE ? OR images.prompt_original LIKE ? OR images.prompt_translated LIKE ? OR images.mode LIKE ? OR images.provider LIKE ? OR images.settings_json LIKE ?)"
            )
            feed_params.extend([like, like, like, like, like, like])
        if gallery_filter == "favorite":
            feed_where_sql.append("images.is_favorite = 1")
        elif gallery_filter == "unpublished":
            feed_where_sql.append("0 = 1")
        elif gallery_filter == "16:9":
            feed_where_sql.append("images.width > 0 AND images.height > 0 AND images.width * 9 = images.height * 16")
        elif gallery_filter == "4:5":
            feed_where_sql.append("images.width > 0 AND images.height > 0 AND images.width * 5 = images.height * 4")
        elif gallery_filter == "1:1":
            feed_where_sql.append("images.width > 0 AND images.height > 0 AND images.width = images.height")
        elif gallery_filter == "face":
            feed_where_sql.append("images.mode IN ('face', 'face_swap', 'faceswap')")
        feed_where_clause = " AND ".join(f"({part})" for part in feed_where_sql)
        feed_rows = conn.execute(
            f"""
            SELECT DISTINCT images.*
            FROM images
            JOIN feed_publications p ON p.image_id = images.id
            WHERE {feed_where_clause}
            ORDER BY p.created_at DESC, images.created_at DESC, images.id DESC
            LIMIT ?
            """,
            [*feed_params, limit],
        ).fetchall()
        feed_items = [
            _gallery_page_item(row, publications[row["id"]], include_feed_media=True)
            for row in feed_rows
            if row["id"] in publications and _feed_publication_ready(publications[row["id"]])
        ]
        for item in feed_items:
            counts = reaction_counts.get(item["feedPublicationId"])
            item["likes"] = int(_row_get(counts, "likes") or 0)
            item["saves"] = int(_row_get(counts, "saves") or 0)
            item["remixes"] = int(_row_get(counts, "remixes") or 0)
        limits = _gallery_page_limits(conn, user_row, user_id)
    return {
        "ok": True,
        "limits": limits,
        "items": items,
        "feedItems": feed_items,
        "hasMore": has_more,
        "nextCursor": gallery_cursor_from_row(page_rows[-1]) if has_more and page_rows else None,
    }


@app.get("/api/gallery/{image_id}")
async def gallery_detail(image_id: str, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        if not user_gallery_allowed(conn, trusted["internal_user_id"], user_id):
            raise HTTPException(403, "Gallery is not available for this plan.")
        row = conn.execute(
            f"SELECT * FROM images WHERE id = ? AND user_id = ? AND {ACTIVE_IMAGE_WHERE}",
            (image_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Image not found")
        detail = row_to_image(row)
        sources = gallery_sources_for_image(conn, image_id, user_id)
        settings = json.loads(row["settings_json"] or "{}")
        detail["sourceIds"] = _gallery_source_ids(settings)
    if not sources:
        sources = repair_image_sources_from_job(image_id, user_id)
    detail["sources"] = sources
    images[image_id] = {**images.get(image_id, {}), **detail}
    return detail


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
        delete_image_source_files(conn, image_id)
        conn.execute("UPDATE images SET deleted_at = ? WHERE id = ? AND user_id = ?", (now, image_id, user_id))
        retire_feed_publications_for_image(conn, image_id, now)
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
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    path = (MEDIA / filename).resolve()
    try:
        path.relative_to(MEDIA.resolve())
    except ValueError:
        raise HTTPException(404, "Image not found")
    if not path.exists():
        raise HTTPException(404, "Image not found")
    with db() as conn:
        allowed = gallery_media_owner_row(conn, filename, user_id) is not None
    if not allowed:
        allowed = any(
            item.get("userId", "demo_user") == user_id
            and (
                item.get("url", "").startswith(f"/api/media/{filename}")
                or item.get("thumbnailUrl", "").startswith(f"/api/media/{filename}")
            )
            for item in images.values()
        )
    if not allowed:
        raise HTTPException(404, "Image not found")
    return FileResponse(path)


@app.post("/api/app/bootstrap")
async def bootstrap(auth: MiniAppAuthRequest, response: Response, request: Request) -> dict[str, Any]:
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
    auth.country = auth.country or request_country_code(request)
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
        models_raw = await get_comfyui_models()
        models_payload = {
            "ok": True,
            "diffusion_models": [_user_model_name(m) for m in models_raw.get("diffusion_models", [])],
            "text_encoders": ["Flux2 CLIP" for _ in models_raw.get("text_encoders", [])],
            "vaes": ["Flux2 VAE" for _ in models_raw.get("vaes", [])],
            "loras": models_raw.get("loras", []),
        }
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
async def web_login(req: WebLoginRequest, request: Request, response: Response) -> dict[str, Any]:
    expected = (os.getenv("ADMIN_ONE_TIME_CODE") or "").strip()
    if not expected or expected == "admin-demo":
        raise HTTPException(503, "Admin bootstrap code is not configured.")
    if not hmac.compare_digest(req.code.strip(), expected):
        raise HTTPException(403, "Invalid one-time admin code.")
    auth = MiniAppAuthRequest(platform="web", userId="admin", username="admin", firstName="Admin", language="ru")
    user = upsert_user(auth)
    with db() as conn:
        row = conn.execute("SELECT internal_user_id FROM users WHERE id = ?", (user["id"],)).fetchone()
        internal_user_id = _row_get(row, "internal_user_id") or uuid.uuid4().hex
        conn.execute(
            "UPDATE users SET role = 'admin', internal_user_id = COALESCE(internal_user_id, ?) WHERE id = ?",
            (internal_user_id, user["id"]),
        )
        ensure_public_user_code(conn, internal_user_id)
    user["role"] = "admin"
    user["internal_user_id"] = internal_user_id
    session = create_auth_session(
        internal_user_id,
        user["id"],
        provider="web_admin",
        platform="web",
        request=request,
        metadata={"auth_flow": "web_login_bootstrap"},
    )
    set_trusted_auth_cookies(
        response,
        session["session_token"],
        session["refresh_token"],
        session["expires_at"],
        session["refresh_expires_at"],
        request=request,
    )
    response.delete_cookie("onenode_user", path="/")
    return {"ok": True, "user": user, "session": {"expires_at": session["expires_at"]}}


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
    set_bot_login_cookie(response, provider, nonce, request=request)
    deep_link = bot_login_deep_link(provider, token)
    if provider == "max":
        print(f"deep_link created provider=max payloadLength={len(f'login_{token}')}")
    return {
        "ok": True,
        "provider": provider,
        "deep_link": deep_link,
        "poll_interval_ms": 2000,
        "expires_at": expires_at,
    }


@app.post("/api/auth/link/bot/start")
async def auth_bot_link_start(req: BotLoginStartRequest, request: Request, response: Response) -> dict[str, Any]:
    user = require_trusted_user(request)
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
                 internal_user_id, created_at, created_ip, user_agent)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                provider,
                hash_token(token),
                hash_token(nonce),
                expires_at,
                user["internal_user_id"],
                now.isoformat(),
                _client_ip(request),
                _hash_user_agent(request),
            ),
        )
    set_bot_login_cookie(response, provider, nonce, request=request)
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
    print(f"GET /api/auth/bot-login/status provider={provider}")
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM auth_login_challenges WHERE provider = ? AND browser_nonce_hash = ?",
            (provider, hash_token(nonce)),
        ).fetchone()
        if not row:
            raise HTTPException(401, "bot_login_challenge_missing")
        if row["status"] == "consumed":
            print(f"challenge status consumed provider={provider}")
            clear_bot_login_cookie(response)
            raise HTTPException(409, "bot_login_challenge_consumed")
        if row["expires_at"] <= now:
            conn.execute("UPDATE auth_login_challenges SET status = 'expired' WHERE id = ? AND status = 'pending'", (row["id"],))
            print(f"challenge status expired provider={provider}")
            clear_bot_login_cookie(response)
            return {"ok": True, "status": "expired"}
        if row["status"] != "approved":
            print(f"challenge status {row['status']} provider={provider}")
            return {"ok": True, "status": row["status"]}
        print(f"challenge status approved provider={provider}")
        internal_user_id = row["internal_user_id"]
        if not internal_user_id:
            raise HTTPException(409, "bot_login_identity_missing")
        user_row = conn.execute("SELECT id FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
        legacy_user_id = user_row["id"] if user_row else None
        conn.execute(
            "UPDATE auth_login_challenges SET status = 'consumed', consumed_at = ? WHERE id = ? AND status = 'approved'",
            (now, row["id"]),
        )
        print(f"challenge status consumed provider={provider}")

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
        request=request,
    )
    print(f"session created provider={provider}")
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
                request=request,
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

    schedule_avatar_cache("telegram", str(user.get("id") or ""))

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
                    f"""
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
            request=request,
            properties={"provider": "telegram", "telegram_user_id": str(user["id"])},
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"telegram-v2: login_succeeded event log error: {type(exc).__name__}")

    # Phase 13: trusted session is delivered via HttpOnly cookies. Tokens remain in
    # JSON for backward compat; the Phase 13 frontend ignores them.
    set_trusted_auth_cookies(
        response, session["session_token"], session["refresh_token"],
        session["expires_at"], session["refresh_expires_at"],
        request=request,
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
                request=request,
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
            request=request,
            properties={"provider": "max", "max_user_id": str(user["id"])},
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"max-v2: login_succeeded event log error: {type(exc).__name__}")

    set_trusted_auth_cookies(
        response, session["session_token"], session["refresh_token"],
        session["expires_at"], session["refresh_expires_at"],
        request=request,
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
        request=request,
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


@app.post("/api/auth/link/email/request-code-v2")
async def auth_link_email_request_code_v2(req: LinkEmailRequestCodeV2Request, request: Request) -> dict[str, Any]:
    """Start verified email linking for the current trusted account."""
    require_trusted_user(request)
    try:
        validate_email_otp_config()
    except RuntimeError:
        raise HTTPException(503, "Email verification is currently unavailable.")
    email_norm = normalize_email(req.email)
    if not email_norm:
        raise HTTPException(400, "A valid email address is required.")
    with db() as conn:
        existing = conn.execute(
            "SELECT internal_user_id FROM auth_identities WHERE provider = 'web_email' AND provider_user_id = ?",
            (email_norm,),
        ).fetchone()
        if existing:
            current = require_trusted_user(request)["internal_user_id"]
            if existing["internal_user_id"] != current:
                raise HTTPException(409, "email_already_linked")
    cleanup_expired_otp_challenges()
    enforce_email_otp_rate_limits(email_norm, request, None, None, "web_desktop")
    now = datetime.now(timezone.utc).isoformat()
    challenge_id = uuid.uuid4().hex
    code = generate_otp_code(EMAIL_OTP_LENGTH)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=EMAIL_OTP_TTL_SECONDS)).isoformat()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO auth_otp_challenges
                (id, channel, destination, code_hash, purpose, attempts_count, max_attempts,
                 expires_at, consumed_at, ip_address, user_agent_hash, created_at)
            VALUES (?, 'email', ?, ?, 'link_email', 0, ?, ?, NULL, ?, ?, ?)
            """,
            (challenge_id, email_norm, hash_otp(code), EMAIL_OTP_MAX_ATTEMPTS, expires_at, _client_ip(request), _hash_user_agent(request), now),
        )
    send_email_otp(email_norm, code)
    response: dict[str, Any] = {"ok": True, "challenge_id": challenge_id, "expires_in_seconds": EMAIL_OTP_TTL_SECONDS}
    if EMAIL_OTP_DEBUG_RETURN_CODE and APP_ENV.lower() != "production":
        response["debug_code"] = code
    return response


@app.post("/api/auth/link/email/verify-code-v2")
async def auth_link_email_verify_code_v2(req: LinkEmailVerifyCodeV2Request, request: Request) -> dict[str, Any]:
    """Verify an email OTP and attach web_email identity to the current account."""
    user = require_trusted_user(request)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        ch = conn.execute("SELECT * FROM auth_otp_challenges WHERE id = ?", (req.challenge_id,)).fetchone()
        if ch is None or ch["purpose"] != "link_email":
            raise HTTPException(401, "otp_challenge_missing")
        if ch["consumed_at"] is not None:
            raise HTTPException(401, "otp_consumed")
        if ch["expires_at"] < now:
            raise HTTPException(401, "otp_expired")
        if int(ch["attempts_count"]) >= int(ch["max_attempts"]):
            raise HTTPException(429, "otp_max_attempts")
        if not hmac.compare_digest(hash_otp(req.code), ch["code_hash"]):
            conn.execute("UPDATE auth_otp_challenges SET attempts_count = attempts_count + 1 WHERE id = ?", (req.challenge_id,))
            raise HTTPException(401, "otp_failed")
        email_norm = ch["destination"]
        existing = conn.execute(
            "SELECT internal_user_id FROM auth_identities WHERE provider = 'web_email' AND provider_user_id = ?",
            (email_norm,),
        ).fetchone()
        if existing and existing["internal_user_id"] != user["internal_user_id"]:
            raise HTTPException(409, "email_already_linked")
        legacy_row = conn.execute("SELECT id FROM users WHERE internal_user_id = ?", (user["internal_user_id"],)).fetchone()
        legacy_user_id = _row_get(legacy_row, "id")
        if existing:
            conn.execute(
                "UPDATE auth_identities SET provider_email = ?, verified_at = COALESCE(verified_at, ?), last_login_at = ? WHERE provider = 'web_email' AND provider_user_id = ?",
                (email_norm, now, now, email_norm),
            )
            linked_new = False
        else:
            conn.execute(
                """
                INSERT INTO auth_identities
                    (id, internal_user_id, legacy_user_id, provider, provider_user_id,
                     provider_email, verified_at, linked_at, last_login_at)
                VALUES (?, ?, ?, 'web_email', ?, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, user["internal_user_id"], legacy_user_id, email_norm, email_norm, now, now, now),
            )
            linked_new = True
        conn.execute("UPDATE users SET email = COALESCE(email, ?), email_verified_at = COALESCE(email_verified_at, ?) WHERE internal_user_id = ?", (email_norm, now, user["internal_user_id"]))
        conn.execute("UPDATE auth_otp_challenges SET consumed_at = ? WHERE id = ?", (now, req.challenge_id))
        if linked_new:
            grant_auth_link_reward(conn, user["internal_user_id"], "email", now)
    return {"ok": True, "email": email_norm, "reward_tokens": 10 if linked_new else 0}


@app.post("/api/auth/password/register-v2")
async def auth_password_register_v2(req: PasswordRegisterV2Request, request: Request, response: Response) -> dict[str, Any]:
    """Browser email+password registration. Creates/attaches a web_email identity +
    Argon2id password, and records consents. If email verification is available,
    no trusted session is issued until verify-code-v2 succeeds. If email
    verification is unavailable, registration falls back to issuing a trusted
    cookie session after password+consent validation. Never stores/logs the raw
    password. Generic 409 if an account already has a password."""
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
    set_trusted_auth_cookies(response, session["session_token"], session["refresh_token"], session["expires_at"], session["refresh_expires_at"], request=request)
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
    set_trusted_auth_cookies(response, session["session_token"], session["refresh_token"], session["expires_at"], session["refresh_expires_at"], request=request)
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
            "SELECT provider, provider_user_id, provider_username, provider_email, provider_first_name, provider_last_name, provider_avatar_url, verified_at, linked_at, last_login_at FROM auth_identities WHERE internal_user_id = ?",
            (iuid,),
        ).fetchall()
        gallery_access = bool(user_gallery_allowed(conn, iuid, legacy))
        gallery_quota = gallery_quota_for_user(conn, urow, legacy)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_tokens_used = int(_row_get(urow, "daily_tokens_used") or 0)
        if _row_get(urow, "last_daily_reset") != today:
            daily_tokens_used = 0
        daily_tokens_limit = int(gallery_quota["daily_tokens"])
        daily_tokens_remaining = max(0, daily_tokens_limit - daily_tokens_used)

    primary_identity = identities[0] if identities else None
    # Fall back to a provider avatar URL when the user has no local avatar yet.
    avatar_url = _row_get(urow, "avatar_url")
    if not avatar_url:
        avatar_url = next((_row_get(i, "provider_avatar_url") for i in identities if _row_get(i, "provider_avatar_url")), None)
    profile = {
        "display_name": resolve_display_name(urow, primary_identity),
        "public_user_code": _row_get(urow, "public_user_code"),
        "first_name": _row_get(urow, "first_name"),
        "last_name": _row_get(urow, "last_name"),
        "username": _row_get(urow, "username"),
        "email": _row_get(urow, "email"),
        "email_verified_at": _row_get(urow, "email_verified_at"),
        "language_code": _row_get(urow, "language"),
        "timezone": _row_get(urow, "timezone"),
        "city": _row_get(urow, "city"),
        "country_code": _row_get(urow, "country"),
        "avatar_url": avatar_url,
        "avatar_preset": _row_get(urow, "avatar_preset"),
        "public_about": _row_get(urow, "public_about"),
        "public_website": _row_get(urow, "public_website"),
        "public_focus": _row_get(urow, "public_focus"),
        "public_phone": _row_get(urow, "public_phone"),
        "public_links": parse_public_links(_row_get(urow, "public_links_json")),
        "gender": _row_get(urow, "gender"),
        "age": _row_get(urow, "age"),
        "providers": sorted({i["provider"] for i in identities}),
    }

    try:
        record_event_log(
            "me_opened",
            internal_user_id=iuid,
            legacy_user_id=legacy,
            session_id=user["session_id"],
            platform=user["platform"],
            request=request,
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
            "daily_tokens_used": daily_tokens_used,
            "daily_tokens_limit": daily_tokens_limit,
            "daily_tokens_remaining": daily_tokens_remaining,
            "gallery_enabled": bool(_row_get(urow, "gallery_enabled")),
            "gallery_access": gallery_access,
            "daily_tokens": daily_tokens_limit,
            "openrouter_monthly_tokens": gallery_quota.get("openrouter_monthly_tokens", 0),
            "gallery_slots": gallery_quota["gallery_slots"],
            "gallery_used": gallery_quota["gallery_used"],
            "gallery_free": gallery_quota["gallery_free"],
            "gallery_full": gallery_quota["gallery_full"],
            "video_enabled": gallery_quota["video_enabled"],
            "video_slots": gallery_quota["video_slots"],
            "video_used": 0,
            "video_free": gallery_quota["video_slots"],
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
                "provider_user_id": short_public_id(r["provider_user_id"], 10),
                "provider_username": r["provider_username"],
                "provider_email": r["provider_email"],
                "provider_first_name": _row_get(r, "provider_first_name"),
                "provider_last_name": _row_get(r, "provider_last_name"),
                "provider_avatar_url": _row_get(r, "provider_avatar_url"),
                "verified_at": r["verified_at"],
                "linked_at": r["linked_at"],
                "last_login_at": r["last_login_at"],
            }
            for r in identities
        ],
        "profile": profile,
        "created_at": _row_get(urow, "created_at"),
        "last_seen_at": _row_get(urow, "last_seen_at"),
    }


def _session_device_label(meta: dict[str, Any]) -> str | None:
    device = meta.get("device") if isinstance(meta, dict) else None
    if not isinstance(device, dict):
        return None
    parts = [device.get("browser"), device.get("os")]
    label = " · ".join(p for p in parts if p and p != "unknown")
    return label or device.get("device_type") or None


@app.get("/api/auth/sessions")
async def auth_sessions_list(request: Request) -> dict[str, Any]:
    """List the current user's own sessions (devices/IP/login method). Exposes
    no token hashes — only the server session record id used for revocation."""
    user = require_trusted_user(request)
    iuid = user["internal_user_id"]
    current_sid = user["session_id"]
    now_iso = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, provider, platform, ip_address, metadata_json, created_at,
                   last_seen_at, expires_at, revoked_at, revoke_reason
            FROM auth_sessions WHERE internal_user_id = ?
            ORDER BY (revoked_at IS NOT NULL), last_seen_at DESC, created_at DESC
            """,
            (iuid,),
        ).fetchall()
    sessions: list[dict[str, Any]] = []
    for r in rows:
        try:
            meta = json.loads(r["metadata_json"]) if _row_get(r, "metadata_json") else {}
        except Exception:
            meta = {}
        revoked = _row_get(r, "revoked_at")
        expires = _row_get(r, "expires_at")
        active = bool(not revoked and (not expires or expires > now_iso))
        sessions.append({
            "id": r["id"],
            "provider": r["provider"],
            "platform": r["platform"],
            "ip_address": _row_get(r, "ip_address"),
            "device": _session_device_label(meta),
            "created_at": r["created_at"],
            "last_seen_at": _row_get(r, "last_seen_at"),
            "expires_at": expires,
            "revoked_at": revoked,
            "active": active,
            "current": r["id"] == current_sid,
        })
    return {"ok": True, "sessions": sessions, "current_session_id": current_sid}


@app.post("/api/auth/sessions/{session_id}/revoke")
async def auth_session_revoke(session_id: str, request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    with db() as conn:
        row = conn.execute("SELECT internal_user_id FROM auth_sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None or row["internal_user_id"] != user["internal_user_id"]:
        raise HTTPException(404, "session_not_found")
    revoke_auth_session(session_id, reason="user_revoked", request=request, event_type="revoked")
    return {"ok": True, "revoked_session_id": session_id, "was_current": session_id == user["session_id"]}


@app.post("/api/auth/sessions/revoke-others")
async def auth_sessions_revoke_others(request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    iuid = user["internal_user_id"]
    current_sid = user["session_id"]
    with db() as conn:
        rows = conn.execute(
            "SELECT id FROM auth_sessions WHERE internal_user_id = ? AND id != ? AND revoked_at IS NULL",
            (iuid, current_sid),
        ).fetchall()
    revoked = 0
    for r in rows:
        if revoke_auth_session(r["id"], reason="user_revoked_all", request=request, event_type="revoked"):
            revoked += 1
    return {"ok": True, "revoked_count": revoked}


@app.get("/api/account/activity-v2")
async def account_activity_v2(request: Request) -> dict[str, Any]:
    """Per-user activity summary for the account screen: login methods, logins by
    provider, active sessions and account age. Built from existing tables only."""
    user = require_trusted_user(request)
    iuid = user["internal_user_id"]
    now_iso = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        urow = conn.execute("SELECT created_at, last_seen_at FROM users WHERE internal_user_id = ?", (iuid,)).fetchone()
        identities = conn.execute(
            "SELECT provider, last_login_at, linked_at, verified_at FROM auth_identities WHERE internal_user_id = ? ORDER BY last_login_at DESC",
            (iuid,),
        ).fetchall()
        active_sessions = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_sessions WHERE internal_user_id = ? AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > ?)",
            (iuid, now_iso),
        ).fetchone()["c"]
        total_sessions = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_sessions WHERE internal_user_id = ?", (iuid,)
        ).fetchone()["c"]
        login_rows = conn.execute(
            "SELECT provider, COUNT(*) AS c, MAX(created_at) AS last_at FROM auth_sessions WHERE internal_user_id = ? GROUP BY provider",
            (iuid,),
        ).fetchall()
    logins_by_provider = {r["provider"]: {"count": int(r["c"]), "last_at": r["last_at"]} for r in login_rows}
    return {
        "ok": True,
        "account_created_at": _row_get(urow, "created_at"),
        "last_seen_at": _row_get(urow, "last_seen_at"),
        "active_sessions": int(active_sessions or 0),
        "total_sessions": int(total_sessions or 0),
        "total_logins": sum(v["count"] for v in logins_by_provider.values()),
        "logins_by_provider": logins_by_provider,
        "login_methods": [
            {
                "provider": i["provider"],
                "last_login_at": i["last_login_at"],
                "linked_at": i["linked_at"],
                "verified": bool(i["verified_at"]),
            }
            for i in identities
        ],
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
                value = value.strip()[:PROFILE_FIELD_MAX_LEN_BY_FIELD.get(api_field, PROFILE_FIELD_MAX_LEN)]
            if api_field == "public_website":
                value = normalize_public_website(value)
            if api_field == "public_links":
                value = normalize_public_links(value)
            if api_field == "age" and value is not None:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise HTTPException(400, "Возраст должен быть числом.")
                if value < 13 or value > 120:
                    raise HTTPException(400, "Возраст должен быть от 13 до 120.")
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
    if content_type not in AVATAR_ALLOWED_CONTENT_TYPES:
        raise HTTPException(400, "Avatar must be PNG, JPEG or WEBP.")
    data = await file.read(AVATAR_MAX_BYTES + 1)
    if len(data) > AVATAR_MAX_BYTES:
        raise HTTPException(413, "Avatar file is too large.")
    avatar_bytes = compress_avatar_image(data)

    filename = f"{iuid}-{uuid.uuid4().hex[:12]}.webp"
    dest = AVATAR_DIR / filename
    dest.write_bytes(avatar_bytes)
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
            properties={
                "content_type": content_type,
                "stored_content_type": "image/webp",
                "source_bytes": len(data),
                "stored_bytes": len(avatar_bytes),
            },
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


def _empty_daily_series(days: int) -> dict[str, int]:
    today = datetime.now(timezone.utc).date()
    return {
        (today - timedelta(days=offset)).isoformat(): 0
        for offset in range(days - 1, -1, -1)
    }


def _daily_counts(conn: sqlite3.Connection, table: str, column: str, days: int, where: str = "", params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    series = _empty_daily_series(days)
    start = next(iter(series))
    where_sql = f" AND {where}" if where else ""
    rows = conn.execute(
        f"""
        SELECT substr({column}, 1, 10) AS day, COUNT(*) AS c
        FROM {table}
        WHERE {column} >= ?{where_sql}
        GROUP BY substr({column}, 1, 10)
        ORDER BY day
        """,
        (start, *params),
    ).fetchall()
    for row in rows:
        if row["day"] in series:
            series[row["day"]] = int(row["c"] or 0)
    return [{"date": day, "value": value} for day, value in series.items()]


def _empty_hourly_series(hours: int) -> dict[str, int]:
    current = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return {
        (current - timedelta(hours=offset)).isoformat(): 0
        for offset in range(hours - 1, -1, -1)
    }


def _hourly_counts(conn: sqlite3.Connection, table: str, column: str, hours: int, where: str = "", params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    series = _empty_hourly_series(hours)
    start = (datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)).isoformat()
    where_sql = f" AND {where}" if where else ""
    rows = conn.execute(
        f"""
        SELECT substr({column}, 1, 13) AS hour, COUNT(*) AS c
        FROM {table}
        WHERE {column} >= ?{where_sql}
        GROUP BY substr({column}, 1, 13)
        ORDER BY hour
        """,
        (start, *params),
    ).fetchall()
    for row in rows:
        key = f"{row['hour']}:00:00+00:00"
        if key in series:
            series[key] = int(row["c"] or 0)
    return [{"date": hour, "value": value} for hour, value in series.items()]


def _parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _floor_to_bucket(value: datetime, bucket_minutes: int) -> datetime:
    minute = (value.minute // bucket_minutes) * bucket_minutes
    return value.replace(minute=minute, second=0, microsecond=0)


def _rolling_counts(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    minutes: int,
    bucket_minutes: int,
    where: str = "",
    params: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    end_bucket = _floor_to_bucket(now, bucket_minutes)
    bucket_count = max(1, (minutes + bucket_minutes - 1) // bucket_minutes)
    buckets = [
        end_bucket - timedelta(minutes=bucket_minutes * offset)
        for offset in range(bucket_count - 1, -1, -1)
    ]
    series = {bucket.isoformat(): 0 for bucket in buckets}
    start = buckets[0]
    where_sql = f" AND {where}" if where else ""
    rows = conn.execute(
        f"SELECT {column} AS ts FROM {table} WHERE {column} >= ?{where_sql}",
        (start.isoformat(), *params),
    ).fetchall()
    for row in rows:
        ts = _parse_iso_utc(row["ts"])
        if ts is None or ts < start or ts > now:
            continue
        key = _floor_to_bucket(ts, bucket_minutes).isoformat()
        if key in series:
            series[key] += 1
    return [{"date": bucket, "value": value} for bucket, value in series.items()]


def _dashboard_rolling_series(conn: sqlite3.Connection, table: str, column: str, where: str = "") -> dict[str, list[dict[str, Any]]]:
    return {
        "1h": _rolling_counts(conn, table, column, 60, 5, where),
        "6h": _rolling_counts(conn, table, column, 360, 30, where),
        "12h": _rolling_counts(conn, table, column, 720, 60, where),
        "24h": _rolling_counts(conn, table, column, 1440, 60, where),
    }


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
        "gender": _row_get(urow, "gender"),
        "age": _row_get(urow, "age"),
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
        "language_code": _row_get(urow, "language"),
        "timezone": _row_get(urow, "timezone"),
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
        "openrouter_monthly_tokens": gallery_quota.get("openrouter_monthly_tokens", 0),
        "gallery_slots": gallery_quota["gallery_slots"],
        "gallery_used": gallery_quota["gallery_used"],
        "gallery_free": gallery_quota["gallery_free"],
        "gallery_full": gallery_quota["gallery_full"],
        "video_enabled": gallery_quota["video_enabled"],
        "video_slots": gallery_quota["video_slots"],
        "video_used": 0,
        "video_free": gallery_quota["video_slots"],
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


@app.get("/api/admin/logs-v2")
async def admin_logs_v2(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    failed_jobs = [
        {
            "id": item.get("id"),
            "mode": item.get("mode"),
            "provider": item.get("provider"),
            "status": item.get("status"),
            "error": truncate_admin_text(item.get("error"), 240),
            "created_at": item.get("createdAt") or item.get("created_at"),
        }
        for item in jobs.values()
        if item.get("status") == "failed"
    ][-30:]
    active_jobs = [
        {k: v for k, v in item.items() if k in ("id", "mode", "provider", "status", "progress", "message", "createdAt")}
        for item in jobs.values()
        if item.get("status") in ("queued", "running", "uploading", "sent_to_comfyui")
    ]
    try:
        comfy_ok = await comfyui_available()
    except Exception:
        comfy_ok = False
    try:
        model_status = await compute_model_status()
    except Exception as exc:
        model_status = {"comfyuiAvailable": comfy_ok, "profiles": [], "error": type(exc).__name__}
    with db() as conn:
        events = conn.execute(
            "SELECT event_name, platform, ip_address, created_at FROM event_logs ORDER BY created_at DESC LIMIT 40"
        ).fetchall()
        security = conn.execute(
            "SELECT severity, event_type, ip_address, created_at FROM security_events ORDER BY created_at DESC LIMIT 40"
        ).fetchall()
        audit = conn.execute(
            "SELECT action, entity_type, target_internal_user_id, created_at FROM audit_logs ORDER BY created_at DESC LIMIT 30"
        ).fetchall()
        failed_logins_24h = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_login_attempts WHERE success = 0 AND created_at >= ?", (_iso_days_ago(1),)
        ).fetchone()["c"]
        generation_errors_db = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE status = 'failed'"
        ).fetchone()["c"]
        db_failed_jobs = conn.execute(
            """
            SELECT id, mode, provider, status, error_message, created_at, started_at, completed_at
            FROM jobs
            WHERE status = 'failed'
            ORDER BY COALESCE(completed_at, started_at, created_at) DESC
            LIMIT 30
            """
        ).fetchall()
    generated_at = datetime.now(timezone.utc).isoformat()
    db_failed_payload = [
        {
            "id": r["id"],
            "mode": r["mode"],
            "provider": r["provider"],
            "status": r["status"],
            "error": truncate_admin_text(r["error_message"], 240),
            "created_at": r["created_at"],
            "started_at": r["started_at"],
            "completed_at": r["completed_at"],
        }
        for r in db_failed_jobs
    ]
    return {
        "ok": True,
        "generated_at": generated_at,
        "backend": {
            "build": APP_BUILD,
            "started_at": STARTED_AT,
            "db_guard": safe_db_guard_payload(DB_GUARD_STATUS),
        },
        "summary": {
            "generation_errors_memory": len(failed_jobs),
            "generation_errors_db": generation_errors_db,
            "failed_logins_24h": failed_logins_24h,
            "active_jobs": len(active_jobs),
            "comfyui_available": bool(model_status.get("comfyuiAvailable", comfy_ok)),
            "model_profiles": len(model_status.get("profiles") or []),
        },
        "comfyui": {
            "available": bool(model_status.get("comfyuiAvailable", comfy_ok)),
            "profiles": model_status.get("profiles", []),
            "error": model_status.get("error"),
        },
        "active_jobs": active_jobs,
        "generation_errors": db_failed_payload or failed_jobs,
        "event_logs": [{"event_name": r["event_name"], "platform": r["platform"], "ip_address": r["ip_address"], "created_at": r["created_at"]} for r in events],
        "security_events": [{"severity": r["severity"], "event_type": r["event_type"], "ip_address": r["ip_address"], "created_at": r["created_at"]} for r in security],
        "audit_logs": [{"action": r["action"], "entity_type": r["entity_type"], "target": (r["target_internal_user_id"] or "")[:8], "created_at": r["created_at"]} for r in audit],
    }


ADMIN_USERS_SORT_SQL = {
    "recent": "COALESCE(u.last_seen_at, u.last_login_at, u.created_at) DESC, u.created_at DESC",
    "created_desc": "u.created_at DESC",
    "created_asc": "u.created_at ASC",
    "generations_desc": "COALESCE(u.generation_count, 0) DESC, COALESCE(u.last_seen_at, u.created_at) DESC",
    "tokens_desc": "COALESCE(u.tokens_used, 0) DESC, COALESCE(u.last_seen_at, u.created_at) DESC",
    "balance_desc": "COALESCE(u.token_balance, 0) DESC, COALESCE(u.last_seen_at, u.created_at) DESC",
    "balance_asc": "COALESCE(u.token_balance, 0) ASC, COALESCE(u.last_seen_at, u.created_at) DESC",
    "code_asc": "u.public_user_code ASC, u.created_at ASC",
    "plan_asc": "u.plan ASC, COALESCE(u.last_seen_at, u.created_at) DESC",
}


@app.get("/api/admin/users-analytics-v2")
async def admin_users_analytics_v2(request: Request, q: str | None = None, provider: str | None = None,
                                   status: str | None = None, sort: str = "recent",
                                   limit: int = 50, offset: int = 0) -> dict[str, Any]:
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
    order_by = ADMIN_USERS_SORT_SQL.get(sort, ADMIN_USERS_SORT_SQL["recent"])
    items = []
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM users u {where}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM users u {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        for r in rows:
            items.append(admin_user_analytics_row(conn, r, now_iso))
    return {"ok": True, "items": items, "limit": limit, "offset": offset, "total": total, "sort": sort if sort in ADMIN_USERS_SORT_SQL else "recent"}


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
            "provider_last_name, provider_phone, provider_language_code, provider_avatar_url, linked_at, verified_at, last_login_at, "
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
            "language_code": r["provider_language_code"], "avatar_url": r["provider_avatar_url"],
            "linked_at": r["linked_at"],
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
            "admin_delete_id": r["id"],
            "image_url": safe_app_url(r["url"]),
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


@app.post("/api/admin/users/{internal_user_id}/gallery/{image_id}/delete-v2")
async def admin_delete_user_gallery_image_v2(
    internal_user_id: str,
    image_id: str,
    req: AdminDeleteImageV2Request,
    request: Request,
) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = _billing_reason(req.reason)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        target = _admin_load_target(conn, internal_user_id)
        row = conn.execute(
            """
            SELECT id, user_id, url, thumbnail_url, prompt_original, job_id, created_at, deleted_at
            FROM images
            WHERE id = ? AND user_id = ? AND (deleted_at IS NULL OR deleted_at = '')
            """,
            (image_id, target["id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Image not found.")
        conn.execute("UPDATE images SET deleted_at = ? WHERE id = ? AND user_id = ?", (now, row["id"], target["id"]))
        record_audit_log(
            conn,
            "admin_delete_gallery_image",
            actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=internal_user_id,
            entity_type="image",
            entity_id=row["id"],
            before={
                "image_id": short_public_id(row["id"]),
                "job_id": short_public_id(row["job_id"]),
                "created_at": row["created_at"],
            },
            after={"deleted_at": now, "reason": reason},
            request=request,
        )
    images.pop(image_id, None)
    delete_image_files_from_disk(url=row["url"], thumbnail_url=row["thumbnail_url"])
    return {"ok": True, "deleted": short_public_id(image_id), "deleted_at": now}


@app.get("/api/admin/mail/status-v2")
async def admin_mail_status_v2(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    now = datetime.now(timezone.utc)
    day_cutoff = (now - timedelta(hours=24)).isoformat()
    with db() as conn:
        otp_total = conn.execute("SELECT COUNT(*) AS c FROM auth_otp_challenges WHERE channel = 'email'").fetchone()["c"]
        otp_24h = conn.execute("SELECT COUNT(*) AS c FROM auth_otp_challenges WHERE channel = 'email' AND created_at >= ?", (day_cutoff,)).fetchone()["c"]
        otp_active = conn.execute("SELECT COUNT(*) AS c FROM auth_otp_challenges WHERE channel = 'email' AND consumed_at IS NULL AND expires_at > ?", (now.isoformat(),)).fetchone()["c"]
        otp_consumed_24h = conn.execute("SELECT COUNT(*) AS c FROM auth_otp_challenges WHERE channel = 'email' AND consumed_at IS NOT NULL AND consumed_at >= ?", (day_cutoff,)).fetchone()["c"]
        challenges = conn.execute(
            """
            SELECT id, destination, purpose, attempts_count, max_attempts, expires_at, consumed_at, created_at
            FROM auth_otp_challenges
            WHERE channel = 'email'
            ORDER BY created_at DESC
            LIMIT 20
            """
        ).fetchall()
        attempts = conn.execute(
            """
            SELECT success, failure_reason, identifier, platform, created_at
            FROM auth_login_attempts
            WHERE provider = 'web_email'
            ORDER BY created_at DESC
            LIMIT 20
            """
        ).fetchall()
    provider = EMAIL_PROVIDER.strip()
    production = APP_ENV.lower() == "production"
    # Current code has the secure OTP contract, but no production provider adapter yet.
    delivery_implemented = not (production and bool(provider))
    service_ready = email_otp_available() and delivery_implemented
    return {
        "ok": True,
        "generated_at": now.isoformat(),
        "service_ready": service_ready,
        "status": "ready" if service_ready else ("provider_adapter_missing" if provider else "provider_not_configured"),
        "provider": provider or None,
        "environment": APP_ENV,
        "otp_available": email_otp_available(),
        "delivery_implemented": delivery_implemented,
        "debug_return_code": EMAIL_OTP_DEBUG_RETURN_CODE and not production,
        "config": {
            "EMAIL_PROVIDER": bool(provider),
            "EMAIL_FROM": bool(os.getenv("EMAIL_FROM") or os.getenv("SMTP_FROM")),
            "SMTP_HOST": bool(os.getenv("SMTP_HOST")),
            "SMTP_PORT": bool(os.getenv("SMTP_PORT")),
            "SUPPORT_EMAIL": bool(os.getenv("SUPPORT_EMAIL")),
        },
        "summary": {
            "otp_total": int(otp_total or 0),
            "otp_24h": int(otp_24h or 0),
            "otp_active": int(otp_active or 0),
            "otp_consumed_24h": int(otp_consumed_24h or 0),
            "mock_outbox": len(_mock_email_outbox),
        },
        "templates": [
            {"id": "verify_email", "title": "Подтверждение email", "subject": "Код подтверждения ИЗО АСА", "status": "готов шаблон OTP"},
            {"id": "support_reply", "title": "Ответ поддержки", "subject": "Ответ поддержки ИЗО АСА", "status": "черновик"},
            {"id": "system_notice", "title": "Системное уведомление", "subject": "Уведомление ИЗО АСА", "status": "черновик"},
        ],
        "recent_challenges": [{
            "id": short_public_id(r["id"], 10),
            "email": mask_email(r["destination"]),
            "purpose": r["purpose"],
            "attempts": int(r["attempts_count"] or 0),
            "max_attempts": int(r["max_attempts"] or 0),
            "expires_at": r["expires_at"],
            "consumed_at": r["consumed_at"],
            "created_at": r["created_at"],
        } for r in challenges],
        "recent_attempts": [{
            "success": bool(r["success"]),
            "reason": r["failure_reason"],
            "email": mask_email(r["identifier"]),
            "platform": r["platform"],
            "created_at": r["created_at"],
        } for r in attempts],
        "mock_outbox": [{"to": mask_email(r.get("to")), "sent_at": r.get("sent_at")} for r in _mock_email_outbox[-20:]],
    }


@app.post("/api/admin/mail/test-v2")
async def admin_mail_test_v2(req: AdminMailTestV2Request, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    email_norm = normalize_email(req.email)
    if not email_norm:
        raise HTTPException(400, "Введите корректный email.")
    if not email_otp_available():
        raise HTTPException(503, "email_provider_not_configured")
    code = generate_otp_code(EMAIL_OTP_LENGTH)
    try:
        send_email_otp(email_norm, code)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"ok": True, "email": mask_email(email_norm), "template": req.template, "sent_at": datetime.now(timezone.utc).isoformat()}


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
        request=request,
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


@app.get("/api/admin/max/status")
async def admin_max_status(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    return {
        "ok": True,
        "tokenSet": bool(MAX_BOT_TOKEN),
        "botNicknameResolved": bool(resolve_max_bot_deep_link_base()),
        "deepLinkBaseSource": _MAX_BOT_DEEP_LINK_CACHE.get("source"),
        "apiBaseUrl": MAX_API_BASE_URL,
        "mode": MAX_UPDATES_MODE,
        "pollingReady": bool(MAX_BOT_TOKEN and MAX_API_BASE_URL),
        "webhookConfigured": bool(MAX_POLLING_DIAG.get("webhookConfigured")),
        "webhookUrlSet": bool(MAX_POLLING_DIAG.get("webhookUrlSet")),
        "subscriptionStatus": MAX_POLLING_DIAG.get("subscriptionStatus"),
        "updateTypes": MAX_POLLING_DIAG.get("updateTypes"),
        "lastPollAt": MAX_POLLING_DIAG.get("lastPollAt"),
        "lastPollStatus": MAX_POLLING_DIAG.get("lastPollStatus"),
        "lastPollError": MAX_POLLING_DIAG.get("lastPollError"),
        "lastRawCount": MAX_POLLING_DIAG.get("lastRawCount"),
        "lastBotStartedAt": MAX_POLLING_DIAG.get("lastBotStartedAt"),
        "lastCallbackAt": MAX_POLLING_DIAG.get("lastCallbackAt"),
        "lastWebhookAt": MAX_POLLING_DIAG.get("lastWebhookAt"),
        "pendingLoginChallengesCount": pending_max_login_challenges_count(),
    }


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
    if pending_max_login_challenges_count() > 0:
        raise HTTPException(409, "active_max_login_challenge")
    return await max_poll_once_from_api(timeout=0, limit=10)


@app.post("/api/max/set-webhook")
async def max_set_webhook() -> dict[str, Any]:
    return await configure_max_webhook_subscription()


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
    now_iso = datetime.now(timezone.utc).isoformat()
    now_dt = datetime.now(timezone.utc)
    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    last_24h = (now_dt - timedelta(hours=24)).isoformat()
    with db() as conn:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        job_db_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        image_count = conn.execute("SELECT COUNT(*) FROM images WHERE deleted_at IS NULL OR deleted_at = ''").fetchone()[0]
        token_total = conn.execute("SELECT COALESCE(SUM(token_balance), 0) FROM users").fetchone()[0]
        tokens_spent = conn.execute("SELECT COALESCE(SUM(-delta), 0) FROM token_ledger WHERE delta < 0").fetchone()[0]
        active_today = conn.execute("SELECT COUNT(*) FROM users WHERE last_seen_at >= ?", (today_start,)).fetchone()[0]
        generations_today = conn.execute("SELECT COUNT(*) FROM jobs WHERE created_at >= ?", (today_start,)).fetchone()[0]
        active_sessions = conn.execute("SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL AND expires_at > ?", (now_iso,)).fetchone()[0]
        generation_errors_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'failed'").fetchone()[0]
        completed_today_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'completed' AND created_at >= ?", (today_start,)).fetchone()[0]
        errors_24h = conn.execute("SELECT COUNT(*) FROM auth_login_attempts WHERE success = 0 AND created_at >= ?", (last_24h,)).fetchone()[0]
        settings_row = conn.execute("SELECT value_json FROM admin_settings WHERE key = 'finance'").fetchone()
        finance = json.loads(settings_row["value_json"]) if settings_row else {"tokenRevenue": 0, "tokenCost": 0, "electricity": 0, "promoBudget": 0}
        active_users_rolling = _dashboard_rolling_series(conn, "users", "last_seen_at", "internal_user_id IS NOT NULL")
        registrations_rolling = _dashboard_rolling_series(conn, "users", "created_at", "internal_user_id IS NOT NULL")
        logins_rolling = _dashboard_rolling_series(conn, "event_logs", "created_at", "event_name IN ('login_succeeded','password_login_succeeded','password_register_succeeded')")
        login_errors_rolling = _dashboard_rolling_series(conn, "auth_login_attempts", "created_at", "success = 0")
        generations_rolling = _dashboard_rolling_series(conn, "jobs", "created_at")
        generation_errors_rolling = _dashboard_rolling_series(conn, "jobs", "created_at", "status = 'failed'")
        timeline = {
            "days": 90,
            "active_users": _daily_counts(conn, "users", "last_seen_at", 90, "internal_user_id IS NOT NULL"),
            "registrations": _daily_counts(conn, "users", "created_at", 90, "internal_user_id IS NOT NULL"),
            "logins": _daily_counts(conn, "event_logs", "created_at", 90, "event_name IN ('login_succeeded','password_login_succeeded','password_register_succeeded')"),
            "login_errors": _daily_counts(conn, "auth_login_attempts", "created_at", 90, "success = 0"),
            "generations": _daily_counts(conn, "jobs", "created_at", 90),
            "generation_errors": _daily_counts(conn, "jobs", "created_at", 90, "status = 'failed'"),
            "active_users_hourly": _hourly_counts(conn, "users", "last_seen_at", 24, "internal_user_id IS NOT NULL"),
            "registrations_hourly": _hourly_counts(conn, "users", "created_at", 24, "internal_user_id IS NOT NULL"),
            "logins_hourly": _hourly_counts(conn, "event_logs", "created_at", 24, "event_name IN ('login_succeeded','password_login_succeeded','password_register_succeeded')"),
            "login_errors_hourly": _hourly_counts(conn, "auth_login_attempts", "created_at", 24, "success = 0"),
            "generations_hourly": _hourly_counts(conn, "jobs", "created_at", 24),
            "generation_errors_hourly": _hourly_counts(conn, "jobs", "created_at", 24, "status = 'failed'"),
            "active_users_1h": active_users_rolling["1h"],
            "active_users_6h": active_users_rolling["6h"],
            "active_users_12h": active_users_rolling["12h"],
            "active_users_24h": active_users_rolling["24h"],
            "registrations_1h": registrations_rolling["1h"],
            "registrations_6h": registrations_rolling["6h"],
            "registrations_12h": registrations_rolling["12h"],
            "registrations_24h": registrations_rolling["24h"],
            "logins_1h": logins_rolling["1h"],
            "logins_6h": logins_rolling["6h"],
            "logins_12h": logins_rolling["12h"],
            "logins_24h": logins_rolling["24h"],
            "login_errors_1h": login_errors_rolling["1h"],
            "login_errors_6h": login_errors_rolling["6h"],
            "login_errors_12h": login_errors_rolling["12h"],
            "login_errors_24h": login_errors_rolling["24h"],
            "generations_1h": generations_rolling["1h"],
            "generations_6h": generations_rolling["6h"],
            "generations_12h": generations_rolling["12h"],
            "generations_24h": generations_rolling["24h"],
            "generation_errors_1h": generation_errors_rolling["1h"],
            "generation_errors_6h": generation_errors_rolling["6h"],
            "generation_errors_12h": generation_errors_rolling["12h"],
            "generation_errors_24h": generation_errors_rolling["24h"],
        }
    return {
        "users": user_count,
        "activeToday": active_today,
        "jobs": max(len(jobs), job_db_count),
        "generationsToday": generations_today,
        "images": image_count,
        "errors": generation_errors_count,
        "errors24h": errors_24h,
        "completedToday": completed_today_count,
        "tokenBalanceTotal": token_total,
        "tokensSpentTotal": tokens_spent,
        "activeSessions": active_sessions,
        "finance": finance,
        "availableModels": ["local_flux_klein", "server_flux_klein", "openrouter_cloud"],
        "loras": ["lora_arcane", "product_photo"],
        "recentErrors": [item.get("error") for item in failed[-5:]],
        "queue": [{k: v for k, v in item.items() if k != "request"} for item in jobs.values() if item.get("status") in ("queued", "running", "uploading", "sent_to_comfyui")],
        "rateLimits": rate_limits,
        "timeline": timeline,
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
        avatar_url, avatar_preset = random_avatar_choice()
        conn.execute(
            """
            INSERT INTO users (id, username, first_name, last_name, middle_name, phone, email, country, city, language, role, plan, token_balance, gallery_enabled, avatar_url, avatar_preset, created_at, last_login_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ru', ?, ?, ?, ?, ?, ?, ?, ?)
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
            (req.userId, req.username, req.firstName, req.lastName, req.middleName, req.phone, req.email, req.country, req.city, req.role, req.plan, req.tokenBalance, int(req.galleryEnabled), avatar_url, avatar_preset, now, now),
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
    if key in {"generation_routes", "tariff_matrix", "user_choice", "tariffs", "openrouter_economy"}:
        _admin_models_page_cache["ts"] = 0.0
        _admin_models_page_cache["data"] = None
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


async def compute_config_ui_status() -> dict[str, Any]:
    started = time.monotonic()
    checked_at = datetime.now(timezone.utc).isoformat()
    active_jobs = [
        {
            "id": item.get("id"),
            "status": item.get("status"),
            "mode": item.get("mode"),
            "provider": item.get("provider"),
            "progress": item.get("progress"),
            "message": truncate_admin_text(item.get("message"), 120),
        }
        for item in jobs.values()
        if item.get("status") in {"queued", "running", "uploading", "sent_to_comfyui"}
    ]

    comfy_up = await comfyui_available()
    config_status: dict[str, Any] = {"ok": False}
    models_status: dict[str, Any] = {"ok": False}
    nodes_status: dict[str, Any] = {"ok": False}

    try:
        config = await get_flux_klein_config()
        config_status = {
            "ok": True,
            "sections": {
                "autofill_prompts": len(config.get("autofill_prompts") or {}),
                "lora_triggers_custom": len(config.get("lora_triggers_custom") or {}),
                "t2i_templates": len(config.get("t2i_templates") or []),
                "discover_prompts": len(config.get("discover_prompts") or {}),
            },
        }
    except Exception as exc:
        config_status = {"ok": False, "error": truncate_admin_text(str(exc), 180)}

    try:
        model_lists = await get_comfyui_models()
        models_status = {
            "ok": True,
            "counts": {key: len(value or []) for key, value in model_lists.items()},
        }
    except Exception as exc:
        models_status = {"ok": False, "error": truncate_admin_text(str(exc), 180)}

    try:
        nodes = await comfyui_node_names()
        nodes_status = {
            "ok": bool(nodes),
            "count": len(nodes),
            "required": {
                "FluxKleinOneNode": "FluxKleinOneNode" in nodes,
                "DWPreprocessor": "DWPreprocessor" in nodes,
            },
        }
    except Exception as exc:
        nodes_status = {"ok": False, "error": truncate_admin_text(str(exc), 180)}

    required_nodes = nodes_status.get("required") or {}
    nodes_ready = bool(nodes_status.get("ok")) and all(bool(value) for value in required_nodes.values())
    status = "ready" if comfy_up and config_status["ok"] and models_status["ok"] and nodes_ready else "degraded"
    return {
        "ok": True,
        "status": status,
        "checked_at": checked_at,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "comfyui": {
            "available": comfy_up,
            "base_url": COMFYUI_BASE_URL,
        },
        "config_api": config_status,
        "models_api": models_status,
        "nodes": nodes_status,
        "active_jobs": active_jobs,
        "cache": {
            "models_page_ttl_seconds": ADMIN_MODELS_PAGE_CACHE_TTL_SECONDS,
            "models_page_cached": bool(models_cache_data),
            "models_page_cached_age_seconds": int(time.monotonic() - newest_cache_ts) if models_cache_data and newest_cache_ts else None,
        },
    }


@app.get("/api/admin/config-ui/status-v2")
async def admin_config_ui_status_v2(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    return await compute_config_ui_status()


@app.post("/api/admin/config-ui/reload-v2")
async def admin_config_ui_reload_v2(req: AdminConfigUiActionV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = truncate_admin_text(req.reason, 300).strip()
    if not reason:
        raise HTTPException(400, "Укажите причину.")
    _admin_models_page_cache["ts"] = 0.0
    _admin_models_page_cache["data"] = None
    status = await compute_config_ui_status()
    with db() as conn:
        record_audit_log(
            conn,
            "admin_config_ui_reload",
            actor_internal_user_id=admin["internal_user_id"],
            entity_type="system",
            entity_id="config-ui",
            after={"reason": reason, "status": status.get("status")},
            request=request,
        )
    return {"ok": True, "reloaded": True, "status": status}


@app.post("/api/admin/config-ui/interrupt-v2")
async def admin_config_ui_interrupt_v2(req: AdminConfigUiActionV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = truncate_admin_text(req.reason, 300).strip()
    if not reason:
        raise HTTPException(400, "Укажите причину.")
    active_before = [
        item.get("id")
        for item in jobs.values()
        if item.get("status") in {"queued", "running", "uploading", "sent_to_comfyui"}
    ]
    await interrupt_comfyui_prompt()
    status = await compute_config_ui_status()
    with db() as conn:
        record_audit_log(
            conn,
            "admin_config_ui_interrupt",
            actor_internal_user_id=admin["internal_user_id"],
            entity_type="system",
            entity_id="comfyui",
            after={"reason": reason, "active_jobs_before": active_before, "status": status.get("status")},
            request=request,
        )
    return {"ok": True, "interrupted": True, "active_jobs_before": active_before, "status": status}


# ── Админ → Модели v2 ───────────────────────────────────────────────────────
# Provider-aware каталог: local ComfyUI и OpenRouter — разные слои. Реальные данные:
# наличие локальных файлов/нод (ComfyUI), скан LoRA, готовность pose, наличие ключа
# OpenRouter. Тарифная матрица, маршруты и цены — admin-конфиг (дефолты пересчитываются,
# переопределения хранятся в admin_settings и НЕ ломают estimate_token_cost генерации).

# Известные LoRA: назначение / совместимость / целевой workflow.
KNOWN_LORAS: dict[str, dict[str, Any]] = {
    "bfs_head_v1_flux-klein_4b": {"purpose": "face / head consistency", "compatible": ["Flux 2 Klein 4B"], "routes": ["face", "edit"], "requires": [], "kind": "klein-face", "recommended": True},
    "bfs_head_v1_flux-klein_9b": {"purpose": "face / identity", "compatible": ["Flux 2 Klein 9B"], "routes": ["face", "edit"], "requires": [], "kind": "klein-face", "recommended": True},
    "refcontrol_v2_poses": {"purpose": "pose ref-control", "compatible": ["Flux 2 Klein 9B"], "routes": ["edit_pose"], "requires": ["DWPreprocessor"], "kind": "klein-pose", "recommended": True},
}

OPENROUTER_CATALOG = [
    {"id": "openrouter_gpt_image", "provider": "openrouter", "displayName": "GPT Image", "modelId": "openai/gpt-image-1", "capabilities": ["txt2img", "image input", "transparent"], "tokenCost": 7, "minimumPlan": "pro"},
    {"id": "openrouter_gemini_image", "provider": "openrouter", "displayName": "Gemini Image", "modelId": "google/gemini-image", "capabilities": ["txt2img", "image input"], "tokenCost": 7, "minimumPlan": "pro"},
    {"id": "openrouter_recraft", "provider": "openrouter", "displayName": "Recraft", "modelId": "recraft/recraft-v3", "capabilities": ["logos", "vector", "style"], "tokenCost": 5, "minimumPlan": "pro"},
]

ROUTE_DEFS = [
    {"routeId": "text_to_image", "displayName": "По тексту", "icon": "T"},
    {"routeId": "image_to_image", "displayName": "По фото", "icon": "I"},
    {"routeId": "edit", "displayName": "Сборка", "icon": "E"},
    {"routeId": "edit_pose", "displayName": "Сборка - поза", "icon": "P"},
    {"routeId": "face", "displayName": "Лицо", "icon": "F"},
]

ADMIN_MODELS_PAGE_CACHE_TTL_SECONDS = 20
_admin_models_page_cache: dict[str, Any] = {"ts": 0.0, "data": None}


async def scan_loras() -> list[dict[str, Any]]:
    """Реальный скан LoRA из ComfyUI (или пусто, если недоступен) + сопоставление с
    известными назначениями. Незнакомые файлы помечаются untested."""
    try:
        models = await get_comfyui_models()
    except Exception:
        models = {}
    files = models.get("loras", [])
    try:
        nodes = await comfyui_node_names()
    except Exception:
        nodes = set()
    out: list[dict[str, Any]] = []
    seen_known: set[str] = set()
    for f in files:
        base = f.lower()
        meta = None
        matched_key = ""
        for key, m in KNOWN_LORAS.items():
            if key.lower() in base:
                meta = m
                matched_key = key
                break
        if meta:
            seen_known.add(matched_key)
            requires_ok = all(n in nodes for n in meta["requires"])
            status = "active" if requires_ok else "missing"
            out.append({
                "fileName": f, "purpose": meta["purpose"], "compatible": meta["compatible"],
                "routes": meta["routes"], "requires": meta["requires"], "status": status,
                "kind": meta.get("kind", "klein"), "recommended": bool(meta.get("recommended")),
                "installed": True, "forKlein": True,
            })
        else:
            is_video = any(k in base for k in ("wan", "i2v", "x2v", "video", "hunyuan"))
            is_flux_candidate = any(k in base for k in ("klein", "flux", "style"))
            if is_video:
                out.append({
                    "fileName": f, "purpose": "video / Wan, не используется Flux Klein",
                    "compatible": ["Wan / video"], "routes": [], "requires": [],
                    "status": "ignored", "kind": "video", "recommended": False,
                    "installed": True, "forKlein": False,
                })
            elif is_flux_candidate:
                out.append({
                    "fileName": f, "purpose": "Flux/Klein кандидат, нужно протестировать",
                    "compatible": ["Flux/Klein? активация неизвестна"], "routes": [], "requires": [],
                    "status": "untested", "kind": "unknown-flux", "recommended": False,
                    "installed": True, "forKlein": True,
                })
    for key, meta in KNOWN_LORAS.items():
        if key not in seen_known:
            out.append({
                "fileName": key, "purpose": meta["purpose"], "compatible": meta["compatible"],
                "routes": meta["routes"], "requires": meta["requires"], "status": "missing",
                "kind": meta.get("kind", "klein"), "recommended": bool(meta.get("recommended")),
                "installed": False, "forKlein": True,
            })
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


def _save_setting(key: str, value: dict[str, Any]) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )


async def fetch_usd_rub_rate(force: bool = False) -> dict[str, Any]:
    cached = _saved_setting("exchange_usd_rub")
    today = datetime.now(timezone.utc).date().isoformat()
    if not force and cached.get("fetched_date") == today and isinstance(cached.get("rate"), (int, float)):
        return {**cached, "cache": "hit"}
    errors: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            response = await client.get(CBR_DAILY_XML_URL)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        rate: float | None = None
        nominal = 1
        for valute in root.findall("Valute"):
            if (valute.findtext("CharCode") or "").strip().upper() == "USD":
                nominal = int((valute.findtext("Nominal") or "1").strip() or "1")
                value = (valute.findtext("Value") or "").replace(",", ".").strip()
                rate = float(value) / max(1, nominal)
                break
        if rate is None:
            raise RuntimeError("USD не найден в XML ЦБ РФ")
        item = {
            "rate": round(rate, 6),
            "currency": "USD",
            "base": "RUB",
            "source": "ЦБ РФ",
            "sourceUrl": CBR_DAILY_XML_URL,
            "sourceDate": root.attrib.get("Date") or "",
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "fetched_date": today,
        }
        _save_setting("exchange_usd_rub", item)
        return {**item, "cache": "refresh"}
    except Exception as exc:
        errors.append(f"ЦБ РФ: {exc}")
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            response = await client.get(USD_RUB_FALLBACK_URL)
        response.raise_for_status()
        payload = response.json()
        rate = float(((payload.get("rates") or {}).get("RUB")))
        item = {
            "rate": round(rate, 6),
            "currency": "USD",
            "base": "RUB",
            "source": "open.er-api.com",
            "sourceUrl": USD_RUB_FALLBACK_URL,
            "sourceDate": payload.get("time_last_update_utc") or "",
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "fetched_date": today,
            "fallback": True,
            "warning": "; ".join(errors),
        }
        _save_setting("exchange_usd_rub", item)
        return {**item, "cache": "refresh_fallback"}
    except Exception as exc:
        errors.append(f"fallback: {exc}")
    if isinstance(cached.get("rate"), (int, float)):
        return {**cached, "cache": "stale", "error": "; ".join(errors)}
    return {"rate": None, "currency": "USD", "base": "RUB", "source": "none", "sourceUrl": CBR_DAILY_XML_URL, "cache": "error", "error": "; ".join(errors)}


OPENROUTER_USD_FEE_RATE = 0.30
OPENROUTER_DEFAULT_TOKEN_RUB = 5.0
OPENROUTER_DEFAULT_MIN_MARGIN_PERCENT = 40.0
OPENROUTER_SHORT_PROMPT_TEXT_TOKENS = 40
OPENROUTER_OUTPUT_IMAGE_TOKENS_1MP = 1300

OPENROUTER_PRICE_CATALOG: dict[str, OpenRouterPriceModel] = {
    "black-forest-labs/flux.2-klein-4b": OpenRouterPriceModel(id="black-forest-labs/flux.2-klein-4b", name="FLUX.2 Klein 4B", provider="BFL", pricing_type="mp", usd=0.014, min_tokens=1),
    "black-forest-labs/flux.2-pro": OpenRouterPriceModel(id="black-forest-labs/flux.2-pro", name="FLUX.2 Pro", provider="BFL", pricing_type="mp", usd=0.03, min_tokens=2),
    "black-forest-labs/flux.2-max": OpenRouterPriceModel(id="black-forest-labs/flux.2-max", name="FLUX.2 Max", provider="BFL", pricing_type="mp", usd=0.07, min_tokens=3),
    "black-forest-labs/flux.2-flex": OpenRouterPriceModel(id="black-forest-labs/flux.2-flex", name="FLUX.2 Flex", provider="BFL", pricing_type="mp", usd=0.12, min_tokens=4),
    "openai/gpt-image-1-mini": OpenRouterPriceModel(id="openai/gpt-image-1-mini", name="GPT Image 1 Mini", provider="OpenAI", pricing_type="token_estimate", usd=0.000008, min_tokens=1),
    "openai/gpt-5-image-mini": OpenRouterPriceModel(id="openai/gpt-5-image-mini", name="GPT-5 Image Mini", provider="OpenAI", pricing_type="token_estimate", usd=0.000008, min_tokens=1),
    "openai/gpt-image-1": OpenRouterPriceModel(id="openai/gpt-image-1", name="GPT Image 1", provider="OpenAI", pricing_type="token_estimate", usd=0.00004, min_tokens=2),
    "openai/gpt-5-image": OpenRouterPriceModel(id="openai/gpt-5-image", name="GPT-5 Image", provider="OpenAI", pricing_type="token_estimate", usd=0.00004, min_tokens=2),
    "openai/gpt-image-2": OpenRouterPriceModel(id="openai/gpt-image-2", name="GPT Image 2", provider="OpenAI", pricing_type="token_estimate", usd=0.00003, min_tokens=1),
    "openai/gpt-5.4-image-2": OpenRouterPriceModel(id="openai/gpt-5.4-image-2", name="GPT-5.4 Image 2", provider="OpenAI", pricing_type="token_estimate", usd=0.00003, min_tokens=1),
    "google/gemini-3.1-flash-lite-image": OpenRouterPriceModel(id="google/gemini-3.1-flash-lite-image", name="Nano Banana 2 Lite", provider="Google Vertex", pricing_type="token_estimate", usd=0.00003, min_tokens=1),
    "google/gemini-3.1-flash-image": OpenRouterPriceModel(id="google/gemini-3.1-flash-image", name="Nano Banana 2", provider="Google Vertex", pricing_type="token_estimate", usd=0.00006, min_tokens=2),
    "google/gemini-3.1-flash-image-preview": OpenRouterPriceModel(id="google/gemini-3.1-flash-image-preview", name="Nano Banana 2 Preview", provider="Google Vertex", pricing_type="token_estimate", usd=0.00006, min_tokens=2, source="market_estimate_2026-07-10"),
    "google/gemini-3-pro-image": OpenRouterPriceModel(id="google/gemini-3-pro-image", name="Nano Banana Pro", provider="Google Vertex", pricing_type="token_estimate", usd=0.00012, min_tokens=4),
    "google/gemini-3-pro-image-preview": OpenRouterPriceModel(id="google/gemini-3-pro-image-preview", name="Nano Banana Pro Preview", provider="Google Vertex", pricing_type="token_estimate", usd=0.00012, min_tokens=4, source="market_estimate_2026-07-10"),
    "google/gemini-2.5-flash-image": OpenRouterPriceModel(id="google/gemini-2.5-flash-image", name="Gemini 2.5 Flash Image", provider="Google", pricing_type="token_estimate", usd=0.00006, min_tokens=2, source="market_estimate_2026-07-10"),
    "google/gemini-2.5-flash-image-preview": OpenRouterPriceModel(id="google/gemini-2.5-flash-image-preview", name="Gemini 2.5 Flash Image Preview", provider="Google", pricing_type="token_estimate", usd=0.00006, min_tokens=2, source="market_estimate_2026-07-10"),
    "microsoft/mai-image-2.5": OpenRouterPriceModel(id="microsoft/mai-image-2.5", name="MAI-Image-2.5", provider="Microsoft", pricing_type="token_estimate", usd=0.00006, min_tokens=2, source="market_estimate_2026-07-10"),
    "x-ai/grok-imagine-image-quality": OpenRouterPriceModel(id="x-ai/grok-imagine-image-quality", name="Grok Imagine Image Quality", provider="xAI", pricing_type="image", usd=0.07, min_tokens=3, source="market_estimate_2026-07-10"),
    "recraft/recraft-v4.1": OpenRouterPriceModel(id="recraft/recraft-v4.1", name="Recraft V4.1", provider="Recraft", pricing_type="image", usd=0.035, min_tokens=1),
    "recraft/recraft-v4.1-utility": OpenRouterPriceModel(id="recraft/recraft-v4.1-utility", name="Recraft V4.1 Utility", provider="Recraft", pricing_type="image", usd=0.035, min_tokens=1),
    "recraft/recraft-v4.1-pro": OpenRouterPriceModel(id="recraft/recraft-v4.1-pro", name="Recraft V4.1 Pro", provider="Recraft", pricing_type="image", usd=0.21, min_tokens=6),
    "recraft/recraft-v4.1-utility-pro": OpenRouterPriceModel(id="recraft/recraft-v4.1-utility-pro", name="Recraft V4.1 Utility Pro", provider="Recraft", pricing_type="image", usd=0.21, min_tokens=6),
    "recraft/recraft-v4.1-vector": OpenRouterPriceModel(id="recraft/recraft-v4.1-vector", name="Recraft V4.1 Vector", provider="Recraft", pricing_type="image", usd=0.08, min_tokens=3),
    "recraft/recraft-v4.1-pro-vector": OpenRouterPriceModel(id="recraft/recraft-v4.1-pro-vector", name="Recraft V4.1 Pro Vector", provider="Recraft", pricing_type="image", usd=0.30, min_tokens=8),
    "recraft/recraft-v4": OpenRouterPriceModel(id="recraft/recraft-v4", name="Recraft V4", provider="Recraft", pricing_type="image", usd=0.04, min_tokens=1),
    "recraft/recraft-v4-pro": OpenRouterPriceModel(id="recraft/recraft-v4-pro", name="Recraft V4 Pro", provider="Recraft", pricing_type="image", usd=0.25, min_tokens=7),
    "recraft/recraft-v4-vector": OpenRouterPriceModel(id="recraft/recraft-v4-vector", name="Recraft V4 Vector", provider="Recraft", pricing_type="image", usd=0.08, min_tokens=3),
    "recraft/recraft-v4-pro-vector": OpenRouterPriceModel(id="recraft/recraft-v4-pro-vector", name="Recraft V4 Pro Vector", provider="Recraft", pricing_type="image", usd=0.30, min_tokens=8),
    "recraft/recraft-v3": OpenRouterPriceModel(id="recraft/recraft-v3", name="Recraft V3", provider="Recraft", pricing_type="image", usd=0.04, min_tokens=1),
    "sourceful/riverflow-v2-fast": OpenRouterPriceModel(id="sourceful/riverflow-v2-fast", name="Riverflow V2 Fast", provider="Sourceful", pricing_type="image", usd=0.04, min_tokens=1, source="market_estimate_2026-07-10"),
    "sourceful/riverflow-v2-pro": OpenRouterPriceModel(id="sourceful/riverflow-v2-pro", name="Riverflow V2 Pro", provider="Sourceful", pricing_type="image", usd=0.13, min_tokens=3, source="market_estimate_2026-07-10"),
    "sourceful/riverflow-v2.5-fast": OpenRouterPriceModel(id="sourceful/riverflow-v2.5-fast", name="Riverflow V2.5 Fast", provider="Sourceful", pricing_type="image", usd=0.019, min_tokens=1),
    "sourceful/riverflow-v2.5-pro": OpenRouterPriceModel(id="sourceful/riverflow-v2.5-pro", name="Riverflow V2.5 Pro", provider="Sourceful", pricing_type="image", usd=0.13, min_tokens=3),
    "sourceful/riverflow-v2-fast-preview": OpenRouterPriceModel(id="sourceful/riverflow-v2-fast-preview", name="Riverflow V2 Fast Preview", provider="Sourceful", pricing_type="image", usd=0.04, min_tokens=1, source="market_estimate_2026-07-10"),
    "sourceful/riverflow-v2-standard-preview": OpenRouterPriceModel(id="sourceful/riverflow-v2-standard-preview", name="Riverflow V2 Standard Preview", provider="Sourceful", pricing_type="image", usd=0.08, min_tokens=2, source="market_estimate_2026-07-10"),
    "sourceful/riverflow-v2-max-preview": OpenRouterPriceModel(id="sourceful/riverflow-v2-max-preview", name="Riverflow V2 Max Preview", provider="Sourceful", pricing_type="image", usd=0.13, min_tokens=3, source="market_estimate_2026-07-10"),
    "bytedance-seed/seedream-4.5": OpenRouterPriceModel(id="bytedance-seed/seedream-4.5", name="Seedream 4.5", provider="ByteDance Seed", pricing_type="image", usd=0.04, min_tokens=1),
    "openrouter/auto": OpenRouterPriceModel(id="openrouter/auto", name="Auto Router", provider="OpenRouter", pricing_type="image", usd=0.15, min_tokens=4, source="market_estimate_2026-07-10"),
}


def openrouter_economy_settings() -> dict[str, float]:
    raw = _saved_setting("openrouter_economy")
    try:
        min_margin = float(raw.get("minMarginPercent", OPENROUTER_DEFAULT_MIN_MARGIN_PERCENT))
    except (TypeError, ValueError):
        min_margin = OPENROUTER_DEFAULT_MIN_MARGIN_PERCENT
    try:
        token_rub = float(raw.get("tokenRub", OPENROUTER_DEFAULT_TOKEN_RUB))
    except (TypeError, ValueError):
        token_rub = OPENROUTER_DEFAULT_TOKEN_RUB
    return {
        "minMarginPercent": max(0.0, min(95.0, min_margin)),
        "tokenRub": max(0.01, min(100000.0, token_rub)),
        "usdFeePercent": OPENROUTER_USD_FEE_RATE * 100,
    }


def openrouter_requested_megapixels(req: GenerateRequest) -> float:
    pixels = max(1, int(req.width or 0)) * max(1, int(req.height or 0))
    return max(1.0, pixels / 1_000_000)


def openrouter_estimated_usd(model: OpenRouterPriceModel, megapixels: float) -> float:
    if model.pricing_type == "mp":
        return model.usd * megapixels
    if model.pricing_type == "token_estimate":
        return model.usd * OPENROUTER_OUTPUT_IMAGE_TOKENS_1MP * megapixels
    return model.usd


def openrouter_tokens_for_cost(cost_rub: float, min_tokens: int, economy: dict[str, float]) -> int:
    token_rub = float(economy["tokenRub"])
    margin_factor = max(0.05, 1.0 - float(economy["minMarginPercent"]) / 100.0)
    return max(min_tokens, math.ceil(cost_rub / token_rub), math.ceil(cost_rub / (token_rub * margin_factor)))


async def estimate_openrouter_billing(req: GenerateRequest) -> dict[str, Any]:
    model_id = resolve_openrouter_model(req)
    model = OPENROUTER_PRICE_CATALOG.get(model_id)
    if model is None:
        raise HTTPException(400, f"OpenRouter model has no billing price: {model_id}")
    exchange = await fetch_usd_rub_rate()
    rate = exchange.get("rate")
    if not isinstance(rate, (int, float)):
        raise HTTPException(503, "USD/RUB rate is not available for OpenRouter billing.")
    economy = openrouter_economy_settings()
    effective_rate = float(rate) * (1 + OPENROUTER_USD_FEE_RATE)
    megapixels = openrouter_requested_megapixels(req)
    estimated_usd = openrouter_estimated_usd(model, megapixels)
    estimated_rub = estimated_usd * effective_rate
    tokens = openrouter_tokens_for_cost(estimated_rub, model.min_tokens, economy)
    revenue_rub = tokens * float(economy["tokenRub"])
    profit_rub = revenue_rub - estimated_rub
    margin_percent = (profit_rub / revenue_rub * 100) if revenue_rub > 0 else None
    return {
        "provider": "openrouter",
        "billingStatus": "estimated",
        "modelId": model.id,
        "modelName": model.name,
        "modelProvider": model.provider,
        "pricingType": model.pricing_type,
        "pricingSource": model.source,
        "megapixels": round(megapixels, 6),
        "estimatedCostUsd": round(estimated_usd, 6),
        "estimatedCostRub": round(estimated_rub, 4),
        "exchangeRate": round(float(rate), 6),
        "effectiveUsdRub": round(effective_rate, 6),
        "exchangeSource": exchange.get("source"),
        "exchangeSourceDate": exchange.get("sourceDate"),
        "exchangeCache": exchange.get("cache"),
        "usdFeePercent": economy["usdFeePercent"],
        "tokenRub": economy["tokenRub"],
        "minMarginPercent": economy["minMarginPercent"],
        "estimatedTokens": tokens,
        "chargedTokens": tokens,
        "revenueRub": round(revenue_rub, 4),
        "profitRub": round(profit_rub, 4),
        "marginPercent": round(margin_percent, 2) if margin_percent is not None else None,
    }


def finalize_openrouter_billing_snapshot(snapshot: dict[str, Any], actual_cost_usd: float | None) -> dict[str, Any]:
    result = dict(snapshot or {})
    if actual_cost_usd is None:
        result["billingStatus"] = "actual_cost_missing"
        return result
    effective_rate = result.get("effectiveUsdRub")
    economy = {"tokenRub": result.get("tokenRub", OPENROUTER_DEFAULT_TOKEN_RUB), "minMarginPercent": result.get("minMarginPercent", OPENROUTER_DEFAULT_MIN_MARGIN_PERCENT)}
    try:
        actual_rub = float(actual_cost_usd) * float(effective_rate)
        min_tokens = OPENROUTER_PRICE_CATALOG.get(str(result.get("modelId") or ""), OpenRouterPriceModel(id="unknown", name="unknown", provider="unknown", pricing_type="image", usd=0, min_tokens=1)).min_tokens
        actual_tokens = openrouter_tokens_for_cost(actual_rub, min_tokens, economy)
        charged_tokens = int(result.get("chargedTokens") or 0)
        revenue_rub = charged_tokens * float(economy["tokenRub"])
        profit_rub = revenue_rub - actual_rub
        result.update({
            "billingStatus": "actual",
            "actualCostUsd": round(float(actual_cost_usd), 6),
            "actualCostRub": round(actual_rub, 4),
            "actualTokens": actual_tokens,
            "chargedTokens": charged_tokens,
            "tokenDelta": charged_tokens - actual_tokens,
            "revenueRub": round(revenue_rub, 4),
            "profitRub": round(profit_rub, 4),
            "marginPercent": round((profit_rub / revenue_rub) * 100, 2) if revenue_rub > 0 else None,
        })
    except (TypeError, ValueError):
        result["billingStatus"] = "actual_cost_unpriced"
    return result


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


def openrouter_usage_stats() -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute(
            "SELECT width, height, mode, settings_json, created_at FROM images WHERE provider = 'openrouter' ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
    total_cost = 0.0
    total_revenue = 0.0
    total_profit = 0.0
    total_tokens = 0
    total_mp = 0.0
    priced = 0
    last_cost: float | None = None
    last_at: str | None = None
    models: dict[str, dict[str, Any]] = {}
    modes: dict[str, dict[str, Any]] = {}
    for row in rows:
        settings = safe_json_load(row["settings_json"]) or {}
        if not isinstance(settings, dict):
            continue
        try:
            cost = float(settings.get("openrouterCostUsd"))
        except (TypeError, ValueError):
            continue
        billing = settings.get("openrouterBilling") if isinstance(settings.get("openrouterBilling"), dict) else {}
        charged_tokens = int(billing.get("chargedTokens") or 0)
        revenue_rub = float(billing.get("revenueRub") or 0)
        profit_rub = float(billing.get("profitRub") or 0)
        mp = max(0.0001, (int(row["width"] or 0) * int(row["height"] or 0)) / 1_000_000)
        model = str(settings.get("openrouterModel") or "unknown")
        mode = str(row["mode"] or "unknown")
        total_cost += cost
        total_tokens += charged_tokens
        total_revenue += revenue_rub
        total_profit += profit_rub
        total_mp += mp
        priced += 1
        if last_cost is None:
            last_cost = cost
            last_at = row["created_at"]
        bucket = models.setdefault(model, {"count": 0, "costUsd": 0.0, "megapixels": 0.0, "tokens": 0, "revenueRub": 0.0, "profitRub": 0.0})
        bucket["count"] += 1
        bucket["costUsd"] += cost
        bucket["megapixels"] += mp
        bucket["tokens"] += charged_tokens
        bucket["revenueRub"] += revenue_rub
        bucket["profitRub"] += profit_rub
        mode_bucket = modes.setdefault(mode, {"count": 0, "costUsd": 0.0, "megapixels": 0.0, "tokens": 0, "revenueRub": 0.0, "profitRub": 0.0, "models": {}})
        mode_bucket["count"] += 1
        mode_bucket["costUsd"] += cost
        mode_bucket["megapixels"] += mp
        mode_bucket["tokens"] += charged_tokens
        mode_bucket["revenueRub"] += revenue_rub
        mode_bucket["profitRub"] += profit_rub
        mode_models = mode_bucket["models"]
        model_mode_bucket = mode_models.setdefault(model, {"count": 0, "costUsd": 0.0})
        model_mode_bucket["count"] += 1
        model_mode_bucket["costUsd"] += cost
    model_rows = []
    for model, item in models.items():
        mp = float(item["megapixels"] or 0)
        cost = float(item["costUsd"] or 0)
        model_rows.append({
            "model": model,
            "count": item["count"],
            "costUsd": round(cost, 6),
            "avgCostUsd": round(cost / item["count"], 6) if item["count"] else None,
            "avgCostPerMpUsd": round(cost / mp, 6) if mp else None,
            "tokens": int(item.get("tokens") or 0),
            "revenueRub": round(float(item.get("revenueRub") or 0), 4),
            "profitRub": round(float(item.get("profitRub") or 0), 4),
            "marginPercent": round((float(item.get("profitRub") or 0) / float(item.get("revenueRub") or 1)) * 100, 2) if float(item.get("revenueRub") or 0) > 0 else None,
        })
    model_rows.sort(key=lambda x: x["count"], reverse=True)
    mode_rows = []
    for mode, item in modes.items():
        mp = float(item["megapixels"] or 0)
        cost = float(item["costUsd"] or 0)
        model_items = item.get("models") if isinstance(item.get("models"), dict) else {}
        favorite = ""
        favorite_count = 0
        for model, model_item in model_items.items():
            count = int(model_item.get("count") or 0)
            if count > favorite_count:
                favorite = model
                favorite_count = count
        mode_rows.append({
            "mode": mode,
            "count": item["count"],
            "costUsd": round(cost, 6),
            "avgCostUsd": round(cost / item["count"], 6) if item["count"] else None,
            "avgCostPerMpUsd": round(cost / mp, 6) if mp else None,
            "tokens": int(item.get("tokens") or 0),
            "revenueRub": round(float(item.get("revenueRub") or 0), 4),
            "profitRub": round(float(item.get("profitRub") or 0), 4),
            "marginPercent": round((float(item.get("profitRub") or 0) / float(item.get("revenueRub") or 1)) * 100, 2) if float(item.get("revenueRub") or 0) > 0 else None,
            "favoriteModel": favorite or None,
            "favoriteCount": favorite_count,
        })
    mode_rows.sort(key=lambda x: x["count"], reverse=True)
    return {
        "pricedImages": priced,
        "totalCostUsd": round(total_cost, 6),
        "avgCostUsd": round(total_cost / priced, 6) if priced else None,
        "avgCostPerMpUsd": round(total_cost / total_mp, 6) if total_mp else None,
        "tokens": total_tokens,
        "revenueRub": round(total_revenue, 4),
        "profitRub": round(total_profit, 4),
        "marginPercent": round((total_profit / total_revenue) * 100, 2) if total_revenue > 0 else None,
        "lastCostUsd": last_cost,
        "lastAt": last_at,
        "models": model_rows[:20],
        "modes": mode_rows,
    }


OPENROUTER_ADMIN_MODES = {
    "text_to_image", "image_to_image", "edit", "paint", "inpaint", "outpaint", "faceswap", "remove_background"
}
OPENROUTER_ACCESS_TIERS = {"mini", "plus", "pro", "business"}
OPENROUTER_QUALITY_PRESETS = {"fast", "standard", "max"}


def normalize_openrouter_config(config: dict[str, Any]) -> dict[str, Any]:
    raw_enabled = config.get("enabled") if isinstance(config.get("enabled"), dict) else {}
    raw_defaults = config.get("defaults") if isinstance(config.get("defaults"), dict) else {}
    raw_access = config.get("access") if isinstance(config.get("access"), dict) else {}
    raw_quality = config.get("qualityDefaults") if isinstance(config.get("qualityDefaults"), dict) else {}
    enabled: dict[str, list[str]] = {}
    defaults: dict[str, str] = {}
    access: dict[str, dict[str, list[str]]] = {}
    quality_defaults: dict[str, dict[str, str]] = {}
    for mode in OPENROUTER_ADMIN_MODES:
        values = raw_enabled.get(mode)
        if isinstance(values, list):
            clean = sorted({str(v).strip() for v in values if isinstance(v, str) and "/" in v and len(v.strip()) <= 160})
            if clean:
                enabled[mode] = clean
        default = raw_defaults.get(mode)
        if isinstance(default, str) and "/" in default and default.strip() in enabled.get(mode, []):
            defaults[mode] = default.strip()
        mode_access_raw = raw_access.get(mode) if isinstance(raw_access.get(mode), dict) else {}
        mode_access: dict[str, list[str]] = {}
        for tier in OPENROUTER_ACCESS_TIERS:
            tier_values = mode_access_raw.get(tier)
            if tier == "mini" and not isinstance(tier_values, list):
                tier_values = mode_access_raw.get("basic")
            if isinstance(tier_values, list):
                clean_tier = sorted({
                    str(v).strip()
                    for v in tier_values
                    if isinstance(v, str) and str(v).strip() in enabled.get(mode, [])
                })
                if clean_tier:
                    mode_access[tier] = clean_tier
        if mode_access:
            access[mode] = mode_access
        mode_quality_raw = raw_quality.get(mode) if isinstance(raw_quality.get(mode), dict) else {}
        mode_quality: dict[str, str] = {}
        for preset in OPENROUTER_QUALITY_PRESETS:
            preset_value = mode_quality_raw.get(preset)
            if isinstance(preset_value, str) and preset_value.strip() in enabled.get(mode, []):
                mode_quality[preset] = preset_value.strip()
        if mode_quality:
            quality_defaults[mode] = mode_quality
    for mode, values in enabled.items():
        if mode not in defaults and values:
            defaults[mode] = values[0]
        if defaults.get(mode):
            quality_defaults.setdefault(mode, {})
            quality_defaults[mode].setdefault("fast", defaults[mode])
            quality_defaults[mode].setdefault("standard", defaults[mode])
            quality_defaults[mode].setdefault("max", defaults[mode])
    return {"enabled": enabled, "defaults": defaults, "access": access, "qualityDefaults": quality_defaults}


def get_openrouter_config() -> dict[str, Any]:
    return normalize_openrouter_config(_saved_setting("openrouter_models"))


def openrouter_model_allowed(config: dict[str, Any], mode: str, tier: str, model_id: str) -> bool:
    access = config.get("access") if isinstance(config.get("access"), dict) else {}
    mode_access = access.get(mode) if isinstance(access.get(mode), dict) else {}
    values = mode_access.get(tier) if isinstance(mode_access.get(tier), list) else []
    return model_id in values


def openrouter_quality_model(config: dict[str, Any], mode: str, preset: str, tier: str = "mini") -> str | None:
    quality = config.get("qualityDefaults") if isinstance(config.get("qualityDefaults"), dict) else {}
    mode_quality = quality.get(mode) if isinstance(quality.get(mode), dict) else {}
    model_id = mode_quality.get(preset)
    if isinstance(model_id, str) and openrouter_model_allowed(config, mode, tier, model_id):
        return model_id
    defaults = config.get("defaults") if isinstance(config.get("defaults"), dict) else {}
    fallback = defaults.get(mode)
    return fallback if isinstance(fallback, str) and openrouter_model_allowed(config, mode, tier, fallback) else None


@app.get("/api/admin/openrouter/status")
async def admin_openrouter_status(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    key_status = await fetch_openrouter_key_status()
    return {"key": key_status, "usage": openrouter_usage_stats(), "config": get_openrouter_config(), "exchange": await fetch_usd_rub_rate()}


@app.get("/api/admin/openrouter/pricing")
async def admin_openrouter_pricing(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    exchange = await fetch_usd_rub_rate()
    economy = openrouter_economy_settings()
    return {
        "ok": True,
        "exchange": exchange,
        "economy": economy,
        "fee": {"usdFeePercent": economy["usdFeePercent"]},
        "models": [model.model_dump() for model in OPENROUTER_PRICE_CATALOG.values()],
    }


@app.post("/api/admin/openrouter/exchange/refresh")
async def admin_openrouter_refresh_exchange(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    exchange = await fetch_usd_rub_rate(force=True)
    _admin_models_page_cache["ts"] = 0.0
    _admin_models_page_cache["data"] = None
    return {"ok": isinstance(exchange.get("rate"), (int, float)), "exchange": exchange}


@app.post("/api/admin/openrouter/config")
async def admin_save_openrouter_config(req: AdminOpenRouterConfigRequest, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    config = normalize_openrouter_config(req.config)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('openrouter_models', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (json.dumps(config, ensure_ascii=False), now),
        )
    _admin_models_page_cache["ts"] = 0.0
    _admin_models_page_cache["data"] = None
    return {"ok": True, "config": config}


@app.put("/api/admin/openrouter/key")
async def admin_save_openrouter_key(req: AdminSecretKeyRequest, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    key = req.key.strip()
    if not key.startswith("sk-or-"):
        raise HTTPException(400, "OpenRouter key должен начинаться с sk-or-")
    save_admin_secret("openrouter_api_key", key)
    key_status = await fetch_openrouter_key_status()
    return {"ok": bool(key_status.get("ok")), "key": key_status, "usage": openrouter_usage_stats(), "config": get_openrouter_config()}


@app.delete("/api/admin/openrouter/key")
async def admin_delete_openrouter_key(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    delete_admin_secret("openrouter_api_key")
    key_status = await fetch_openrouter_key_status()
    return {"ok": True, "key": key_status, "usage": openrouter_usage_stats(), "config": get_openrouter_config()}


@app.post("/api/admin/openrouter/test-generate")
async def admin_openrouter_test_generate(req: AdminOpenRouterTestRequest, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    if "/" not in req.model:
        raise HTTPException(400, "model должен быть OpenRouter id вида provider/model")
    job_id = f"admin_or_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    gen_req = GenerateRequest(
        mode="text_to_image",
        provider="openrouter",
        prompt=req.prompt,
        width=req.width,
        height=req.height,
        steps=4,
        modelProfile=req.model,
    )
    job = {
        "id": job_id,
        "userId": admin["legacy_user_id"],
        "mode": gen_req.mode,
        "provider": gen_req.provider,
        "status": "queued",
        "progress": 0,
        "message": "Admin OpenRouter test",
        "request": gen_req.model_dump(),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    result = await send_to_openrouter(gen_req, job)
    created_at = datetime.now(timezone.utc).isoformat()
    with Image.open(result.image_path) as opened:
        width, height = opened.size
    image_id = f"img_{uuid.uuid4().hex[:12]}"
    record = {
        "id": image_id,
        "userId": admin["legacy_user_id"],
        "url": public_url(result.image_path, admin["legacy_user_id"]),
        "thumbnailUrl": public_url(result.thumbnail_path, admin["legacy_user_id"]),
        "mode": gen_req.mode,
        "provider": gen_req.provider,
        "promptOriginal": gen_req.prompt,
        "promptTranslated": gen_req.prompt,
        "seed": gen_req.seed,
        "width": width,
        "height": height,
        "modelProfile": gen_req.modelProfile,
        "loras": [],
        "preset": "admin_openrouter_test",
        "generationTimeMs": 0,
        "isFavorite": False,
        "createdAt": created_at,
        "openrouterModel": result.model,
        "openrouterResponseId": result.response_id,
        "openrouterUsage": result.usage,
        "openrouterCostUsd": result.cost_usd,
    }
    images[image_id] = record
    persist_image(record, job_id)
    job.update(
        status="completed",
        progress=100,
        message="OpenRouter test completed",
        resultImageId=image_id,
        resultUrl=record["url"],
        openrouterModel=result.model,
        openrouterResponseId=result.response_id,
        openrouterUsage=result.usage,
        openrouterCostUsd=result.cost_usd,
        completedAt=created_at,
    )
    persist_job(job, gen_req)
    return {"ok": True, "image": record, "costUsd": result.cost_usd, "model": result.model, "usage": result.usage, "stats": openrouter_usage_stats()}


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
    include_local = str(request.query_params.get("local", "1")).lower() not in {"0", "false", "no", "api"}
    cache_key = "local" if include_local else "api"
    now_mono = time.monotonic()
    cache_data = _admin_models_page_cache.get("data")
    cache_ts = _admin_models_page_cache.get("ts")
    cached = cache_data.get(cache_key) if isinstance(cache_data, dict) else None
    cached_ts = cache_ts.get(cache_key, 0.0) if isinstance(cache_ts, dict) else 0.0
    if cached and now_mono - float(cached_ts or 0) < ADMIN_MODELS_PAGE_CACHE_TTL_SECONDS:
        return {**cached, "cache": {"hit": True, "ttl_seconds": ADMIN_MODELS_PAGE_CACHE_TTL_SECONDS}}
    status = await compute_model_status() if include_local else {"profiles": [], "comfyuiAvailable": None}
    loras = await scan_loras() if include_local else []
    routes = (_saved_setting("generation_routes").get("routes") or default_routes(status)) if include_local else []
    matrix = _saved_setting("tariff_matrix").get("matrix") or default_tariff_matrix()
    openrouter_economy = {"minMarginPercent": 40, "tokenRub": 5, **(_saved_setting("openrouter_economy") or {})}
    openrouter_status = await fetch_openrouter_key_status()
    openrouter_key = bool(openrouter_status.get("configured"))
    openrouter_usage = openrouter_usage_stats()
    exchange = await fetch_usd_rub_rate()

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
    if any(l["status"] == "untested" and l.get("forKlein") for l in loras):
        conflicts += 1
    if any(l["status"] == "missing" and l.get("recommended") for l in loras):
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

    payload = {
        "economy": {"activeModels": active_models, "routesAssigned": f"{routes_assigned}/{len(ROUTE_DEFS)}", "expensiveRoutes": expensive, "priceConflicts": conflicts},
        "routes": routes,
        "userChoice": user_choice,
        "matrix": matrix,
        "catalog": catalog,
        "loras": loras,
        "comfyuiAvailable": status.get("comfyuiAvailable"),
        "openrouter": {
            "keyConfigured": openrouter_key,
            "status": openrouter_status,
            "usage": openrouter_usage,
            "config": get_openrouter_config(),
            "exchange": exchange,
            "economy": openrouter_economy,
            "backendPricing": [model.model_dump() for model in OPENROUTER_PRICE_CATALOG.values()],
        },
        "comfyFiles": {"modelFile": "flux-2-klein-4b-fp8.safetensors", "textEncoder": "qwen_3_4b / qwen_3_8b", "vae": "flux2-vae.safetensors", "sampler": "er_sde", "width": 1024, "height": 1024, "steps": 4, "seed": "random"} if include_local else {},
        "profiles": status.get("profiles", []),
    }
    next_data = cache_data if isinstance(cache_data, dict) else {}
    next_ts = cache_ts if isinstance(cache_ts, dict) else {}
    next_data[cache_key] = payload
    next_ts[cache_key] = now_mono
    _admin_models_page_cache["ts"] = next_ts
    _admin_models_page_cache["data"] = next_data
    return {**payload, "cache": {"hit": False, "ttl_seconds": ADMIN_MODELS_PAGE_CACHE_TTL_SECONDS}}


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
    print(f"MAX_WEBHOOK_RECEIVED before secret check type={max_update_type(payload)}")
    if MAX_WEBHOOK_SECRET:
        secret_ok = request.headers.get("X-Max-Bot-Api-Secret") == MAX_WEBHOOK_SECRET
        print(f"MAX_WEBHOOK_SECRET_OK {str(secret_ok).lower()}")
        if not secret_ok:
            raise HTTPException(403, "Invalid MAX webhook secret.")
    MAX_POLLING_DIAG["lastWebhookAt"] = datetime.now(timezone.utc).isoformat()
    MAX_POLLING_DIAG["lastWebhookError"] = None
    print(f"MAX webhook update received type={max_update_type(payload)}")
    try:
        await handle_max_update(payload, send_replies=True)
    except Exception as exc:
        MAX_POLLING_DIAG["lastWebhookError"] = type(exc).__name__
        print("max webhook handler error", type(exc).__name__)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Live Feed MVP. Публикации из личной галереи + публичная лента + реакции.
# Auth: чтение ленты публичное (viewerState только при trusted session);
# публикация и реакции — только trusted cookie session (require_trusted_user).
# Легаси-заголовки/куки здесь не читаются никогда.
# ---------------------------------------------------------------------------

FEED_PROMPT_VISIBILITIES = {"open", "partial", "hidden"}
FEED_PARTIAL_PROMPT_CHARS = 140
FEED_THUMB_MAX_SIDE = 640
FEED_LARGE_MAX_SIDE = 1536
FEED_DISPLAY_POLICY = "preserve_aspect_ratio"
FEED_VIEWER_VISIBLE_SQL = """
  AND (
    ? IS NULL OR NOT EXISTS (
      SELECT 1 FROM feed_reactions hidden
      WHERE hidden.publication_id = p.id
        AND hidden.internal_user_id = ?
        AND hidden.kind = 'hide'
    )
  )
"""


@dataclass
class FeedAssetInfo:
    feed_thumb_name: str
    feed_large_name: str
    feed_thumb_width: int
    feed_thumb_height: int
    feed_thumb_bytes: int
    feed_large_width: int
    feed_large_height: int
    feed_large_bytes: int
    native_aspect_ratio: str
    orientation: str


def _feed_orientation(width: int, height: int) -> str:
    if not width or not height:
        return "custom"
    if width == height:
        return "square"
    return "landscape" if width > height else "portrait"


def _feed_source_label(source_type: str) -> str:
    return {
        "text_to_image": "По тексту",
        "image_to_image": "По фото",
        "multi_reference": "Несколько референсов",
        "drawing_to_image": "Редактор",
        "edit": "Редактировано",
        "inpaint": "Маска",
        "outpaint": "Outpaint",
        "faceswap": "Лицо",
        "remix": "Remix",
        "seed": "Выбор редакции",
    }.get(source_type or "", "По тексту")


def _feed_source_type(mode: str | None, *, is_seed: bool = False) -> str:
    if is_seed:
        return "seed"
    raw = (mode or "text_to_image").strip()
    return {
        "paint": "drawing_to_image",
    }.get(raw, raw)


def _save_feed_variant(source: Image.Image, target: Path, max_side: int, quality: int) -> tuple[int, int, int]:
    image = ImageOps.exif_transpose(source)
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGB")
    else:
        image = image.copy()
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    image.save(target, "WEBP", quality=quality, method=6)
    return image.width, image.height, target.stat().st_size


def create_feed_assets(publication_id: str, source_url: str | None) -> FeedAssetInfo:
    source_path = _media_file_path_from_url(source_url)
    if source_path is None or not source_path.exists():
        raise FileNotFoundError("Feed source image file not found.")
    target_dir = feed_media_dir()
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", publication_id)
    thumb_rel = f"feed/{safe_id}_thumb.webp"
    large_rel = f"feed/{safe_id}_large.webp"
    thumb_path = MEDIA / thumb_rel
    large_path = MEDIA / large_rel
    with Image.open(source_path) as opened:
        source = ImageOps.exif_transpose(opened)
        native_ratio = _feed_aspect_ratio(source.width, source.height)
        orientation = _feed_orientation(source.width, source.height)
        tw, th, tb = _save_feed_variant(source, thumb_path, FEED_THUMB_MAX_SIDE, 82)
        lw, lh, lb = _save_feed_variant(source, large_path, FEED_LARGE_MAX_SIDE, 86)
    return FeedAssetInfo(
        feed_thumb_name=thumb_rel,
        feed_large_name=large_rel,
        feed_thumb_width=tw,
        feed_thumb_height=th,
        feed_thumb_bytes=tb,
        feed_large_width=lw,
        feed_large_height=lh,
        feed_large_bytes=lb,
        native_aspect_ratio=native_ratio,
        orientation=orientation,
    )


def _feed_media_name(url: str | None) -> str | None:
    """Имя файла из внутреннего /api/media-URL записи images."""
    if not url:
        return None
    s = str(url)
    if s.startswith("/api/media/"):
        return s.removeprefix("/api/media/").split("?", 1)[0]
    if s.startswith("/media/"):
        return s.removeprefix("/media/").split("?", 1)[0]
    return None


def _feed_author_name(conn: sqlite3.Connection, internal_user_id: str, legacy_user_id: str | None) -> str:
    row = conn.execute(
        "SELECT display_name, username, first_name FROM users WHERE internal_user_id = ?",
        (internal_user_id,),
    ).fetchone()
    if row is None and legacy_user_id:
        row = conn.execute(
            "SELECT display_name, username, first_name FROM users WHERE id = ?",
            (legacy_user_id,),
        ).fetchone()
    if row is None:
        return "Автор"
    return _row_get(row, "display_name") or _row_get(row, "username") or _row_get(row, "first_name") or "Пользователь ИЗО"


def _feed_author_profile(conn: sqlite3.Connection, internal_user_id: str, legacy_user_id: str | None) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT display_name, username, first_name, avatar_url, avatar_preset,
               public_about, public_website, public_focus, public_phone,
               public_links_json, gender, age, city, country
        FROM users WHERE internal_user_id = ?
        """,
        (internal_user_id,),
    ).fetchone()
    if row is None and legacy_user_id:
        row = conn.execute(
            """
            SELECT display_name, username, first_name, avatar_url, avatar_preset,
                   public_about, public_website, public_focus, public_phone,
                   public_links_json, gender, age, city, country
            FROM users WHERE id = ?
            """,
            (legacy_user_id,),
        ).fetchone()
    identity = conn.execute(
        "SELECT provider_avatar_url FROM auth_identities WHERE internal_user_id = ? AND provider_avatar_url IS NOT NULL AND provider_avatar_url != '' ORDER BY last_login_at DESC LIMIT 1",
        (internal_user_id,),
    ).fetchone()
    name = (
        _row_get(row, "display_name")
        or _row_get(row, "username")
        or _row_get(row, "first_name")
        or "Пользователь ИЗО"
    )
    avatar_url = _row_get(row, "avatar_url") or _row_get(identity, "provider_avatar_url")
    return {
        "id": internal_user_id,
        "displayName": name,
        "username": _row_get(row, "username"),
        "avatarUrl": avatar_url,
        "avatarPreset": _row_get(row, "avatar_preset"),
        "publicAbout": _row_get(row, "public_about"),
        "publicWebsite": _row_get(row, "public_website"),
        "publicFocus": _row_get(row, "public_focus"),
        "publicPhone": _row_get(row, "public_phone"),
        "publicLinks": parse_public_links(_row_get(row, "public_links_json")),
        "gender": _row_get(row, "gender"),
        "age": _row_get(row, "age"),
        "city": _row_get(row, "city"),
        "country": _row_get(row, "country"),
    }


def _feed_challenge_payload(conn: sqlite3.Connection, category: str | None) -> dict[str, Any] | None:
    if not category:
        return None
    row = conn.execute(
        """
        SELECT id, title, description, rules, prompt_hint, category, status,
               reward_pool, starts_at, ends_at
        FROM challenges
        WHERE category = ? AND status = 'active'
        ORDER BY ends_at ASC
        LIMIT 1
        """,
        (category,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "rules": row["rules"],
        "promptHint": row["prompt_hint"],
        "category": row["category"],
        "status": row["status"],
        "rewardPool": row["reward_pool"],
        "startsAt": row["starts_at"],
        "endsAt": row["ends_at"],
    }


def _feed_source_history_payload(conn: sqlite3.Connection, image_id: str | None) -> list[dict[str, Any]]:
    if not image_id:
        return []
    rows = conn.execute(
        """
        SELECT source_kind, role, slot_index, thumb_url, thumb_width, thumb_height, children_json
        FROM image_sources
        WHERE image_id = ?
        ORDER BY slot_index ASC, created_at ASC
        """,
        (image_id,),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        children = safe_json_load(_row_get(row, "children_json")) or []
        items.append({
            "kind": _row_get(row, "source_kind"),
            "role": _row_get(row, "role"),
            "roleLabel": _source_role_label(_row_get(row, "role"), int(_row_get(row, "slot_index") or 0)),
            "slotIndex": int(_row_get(row, "slot_index") or 0),
            "thumbUrl": _row_get(row, "thumb_url"),
            "width": int(_row_get(row, "thumb_width") or 0),
            "height": int(_row_get(row, "thumb_height") or 0),
            "children": children if isinstance(children, list) else [],
        })
    return items


def _feed_aspect_ratio(width: int, height: int) -> str:
    if not width or not height:
        return "1:1"
    from math import gcd

    g = gcd(int(width), int(height)) or 1
    return f"{int(width) // g}:{int(height) // g}"


def _feed_item_payload(
    conn: sqlite3.Connection,
    pub: sqlite3.Row,
    viewer_internal_user_id: str | None,
) -> dict[str, Any]:
    image = conn.execute(
        "SELECT id, url, thumbnail_url, width, height, prompt_original, settings_json, provider, mode "
        "FROM images WHERE id = ?",
        (pub["image_id"],),
    ).fetchone()
    settings: dict[str, Any] = {}
    if image is not None:
        try:
            settings = json.loads(image["settings_json"] or "{}")
        except (TypeError, ValueError):
            settings = {}
    visibility = pub["prompt_visibility"]
    raw_prompt = (_row_get(image, "prompt_original") or "").strip()
    if visibility == "open":
        prompt: str | None = raw_prompt or None
    elif visibility == "partial":
        prompt = (raw_prompt[:FEED_PARTIAL_PROMPT_CHARS] + "…") if len(raw_prompt) > FEED_PARTIAL_PROMPT_CHARS else (raw_prompt or None)
    else:
        prompt = None
    counts = {
        r["kind"]: r["c"]
        for r in conn.execute(
            "SELECT kind, COUNT(*) AS c FROM feed_reactions WHERE publication_id = ? GROUP BY kind",
            (pub["id"],),
        ).fetchall()
    }
    viewer_kinds: set[str] = set()
    is_followed_by_me = False
    viewer_role: str | None = None
    if viewer_internal_user_id:
        viewer_kinds = {
            r["kind"]
            for r in conn.execute(
                "SELECT kind FROM feed_reactions WHERE publication_id = ? AND internal_user_id = ?",
                (pub["id"], viewer_internal_user_id),
            ).fetchall()
        }
        is_followed_by_me = bool(conn.execute(
            """
            SELECT 1 FROM feed_author_follows
            WHERE follower_internal_user_id = ? AND author_internal_user_id = ?
            """,
            (viewer_internal_user_id, pub["internal_user_id"]),
        ).fetchone())
        viewer_row = conn.execute(
            "SELECT role FROM users WHERE internal_user_id = ?",
            (viewer_internal_user_id,),
        ).fetchone()
        viewer_role = _row_get(viewer_row, "role")
    width = int(_row_get(image, "width") or 0)
    height = int(_row_get(image, "height") or 0)
    media_ready = bool(_row_get(pub, "feed_thumb_name") and _row_get(pub, "feed_large_name") and _row_get(pub, "media_ready_at"))
    native_aspect_ratio = _row_get(pub, "native_aspect_ratio") or _feed_aspect_ratio(width, height)
    source_type = _row_get(pub, "source_type") or _feed_source_type(_row_get(image, "mode"))
    is_mine = viewer_internal_user_id == pub["internal_user_id"]
    viewer_is_admin = viewer_role == "admin"
    author_profile = _feed_author_profile(conn, pub["internal_user_id"], pub["legacy_user_id"])
    return {
        "id": pub["id"],
        "image_url": f"/api/feed/media/{pub['id']}?variant=large",
        "thumbnail_url": f"/api/feed/media/{pub['id']}?variant=thumb",
        "media_status": "ready" if media_ready else "missing",
        "user_id": pub["internal_user_id"],
        "author": author_profile,
        "author_name": author_profile["displayName"],
        "title": pub["title"],
        "description": pub["description"],
        "prompt": prompt,
        "prompt_visibility": visibility,
        "allow_recreate": bool(pub["allow_recreate"]),
        "style": settings.get("styleName") or None,
        "model": _user_model_name(settings.get("modelProfile") or _row_get(image, "provider")),
        "mode": _row_get(image, "mode"),
        "aspect_ratio": native_aspect_ratio,
        "native_aspect_ratio": native_aspect_ratio,
        "orientation": _row_get(pub, "orientation") or _feed_orientation(width, height),
        "source_type": source_type,
        "source_label": _row_get(pub, "source_label") or _feed_source_label(source_type),
        "display_policy": _row_get(pub, "display_policy") or FEED_DISPLAY_POLICY,
        "remix_policy": _row_get(pub, "remix_policy") or ("allowed" if bool(pub["allow_recreate"]) else "disabled"),
        "category": _row_get(pub, "category"),
        "challenge": _feed_challenge_payload(conn, _row_get(pub, "category")),
        "source_history": _feed_source_history_payload(conn, pub["image_id"]),
        "resolution": f"{width}×{height}" if width and height else None,
        "seed": settings.get("seed"),
        "created_at": pub["created_at"],
        "view_count": int(_row_get(pub, "view_count") or 0),
        "remix_count": counts.get("recreate", 0),
        "save_count": counts.get("save", 0),
        "like_count": counts.get("like", 0),
        "is_liked_by_me": "like" in viewer_kinds,
        "is_saved_by_me": "save" in viewer_kinds,
        "is_disliked_by_me": "dislike" in viewer_kinds,
        "is_hidden_by_me": "hide" in viewer_kinds,
        "is_reported_by_me": "report" in viewer_kinds,
        "is_followed_by_me": is_followed_by_me,
        "is_mine": is_mine,
        "can_delete_by_me": bool(viewer_internal_user_id and (is_mine or viewer_is_admin)),
        "delete_role": "owner" if is_mine else ("admin" if viewer_is_admin else None),
    }


def _feed_optional_viewer(request: Request) -> str | None:
    """internal_user_id, если есть валидная trusted-сессия; иначе None.
    Ошибок наружу не поднимает — чтение ленты доступно без входа."""
    try:
        return require_trusted_user(request)["internal_user_id"]
    except HTTPException:
        return None

@app.get("/api/feed")
async def feed_list(
    request: Request,
    type: str = "for_you",
    limit: int = 30,
    challenge_id: str | None = None,
) -> dict[str, Any]:
    aliases = {"all": "for_you", "new": "fresh"}
    feed_type = aliases.get(type, type)
    if feed_type not in {"for_you", "fresh", "top", "remix", "challenge", "following"}:
        feed_type = "for_you"
    limit = max(1, min(int(limit or 30), 60))
    viewer = _feed_optional_viewer(request)
    with db() as conn:
        if feed_type == "following":
            if not viewer:
                rows = []
            else:
                rows = conn.execute(
                    f"""
                    SELECT p.* FROM feed_publications p
                    JOIN feed_author_follows f ON f.author_internal_user_id = p.internal_user_id
                    WHERE f.follower_internal_user_id = ?
                      AND p.status = 'published'
                      AND p.media_ready_at IS NOT NULL
                      AND p.feed_thumb_name IS NOT NULL
                      AND p.feed_large_name IS NOT NULL
                      {FEED_VIEWER_VISIBLE_SQL}
                    ORDER BY p.created_at DESC
                    LIMIT ?
                    """,
                    (viewer, viewer, viewer, limit),
                ).fetchall()
        elif feed_type == "challenge":
            challenge = None
            if challenge_id:
                challenge = conn.execute(
                    "SELECT category FROM challenges WHERE id = ? AND status = 'active'",
                    (challenge_id,),
                ).fetchone()
            category = _row_get(challenge, "category") or "challenge_moscow_2120"
            rows = conn.execute(
                f"""
                SELECT p.* FROM feed_publications p
                WHERE p.status = 'published'
                  AND p.category = ?
                  AND p.media_ready_at IS NOT NULL
                  AND p.feed_thumb_name IS NOT NULL
                  AND p.feed_large_name IS NOT NULL
                  {FEED_VIEWER_VISIBLE_SQL}
                ORDER BY p.created_at DESC
                LIMIT ?
                """,
                (category, viewer, viewer, limit),
            ).fetchall()
        elif feed_type == "remix":
            rows = conn.execute(
                f"""
                SELECT p.* FROM feed_publications p
                LEFT JOIN feed_reactions r ON r.publication_id = p.id
                WHERE p.status = 'published'
                  AND p.media_ready_at IS NOT NULL
                  AND p.feed_thumb_name IS NOT NULL
                  AND p.feed_large_name IS NOT NULL
                  {FEED_VIEWER_VISIBLE_SQL}
                GROUP BY p.id
                ORDER BY SUM(CASE WHEN r.kind = 'recreate' THEN 1 ELSE 0 END) DESC,
                         SUM(CASE WHEN r.kind = 'save' THEN 1 ELSE 0 END) DESC,
                         p.created_at DESC
                LIMIT ?
                """,
                (viewer, viewer, limit),
            ).fetchall()
        elif feed_type == "top":
            rows = conn.execute(
                f"""
                SELECT p.* FROM feed_publications p
                LEFT JOIN feed_reactions r ON r.publication_id = p.id
                WHERE p.status = 'published'
                  AND p.media_ready_at IS NOT NULL
                  AND p.feed_thumb_name IS NOT NULL
                  AND p.feed_large_name IS NOT NULL
                  {FEED_VIEWER_VISIBLE_SQL}
                GROUP BY p.id
                ORDER BY SUM(CASE WHEN r.kind IN ('like', 'save', 'recreate') THEN 1 ELSE 0 END) DESC,
                         p.created_at DESC
                LIMIT ?
                """,
                (viewer, viewer, limit),
            ).fetchall()
        elif feed_type == "for_you":
            rows = conn.execute(
                f"""
                SELECT p.* FROM feed_publications p
                LEFT JOIN feed_reactions r ON r.publication_id = p.id
                WHERE p.status = 'published'
                  AND p.media_ready_at IS NOT NULL
                  AND p.feed_thumb_name IS NOT NULL
                  AND p.feed_large_name IS NOT NULL
                  {FEED_VIEWER_VISIBLE_SQL}
                GROUP BY p.id
                ORDER BY
                    SUM(CASE WHEN r.kind = 'recreate' THEN 8 ELSE 0 END)
                  + SUM(CASE WHEN r.kind = 'save' THEN 4 ELSE 0 END)
                  + SUM(CASE WHEN r.kind = 'like' THEN 1 ELSE 0 END) DESC,
                  CASE WHEN p.category = 'challenge_moscow_2120' THEN 1 ELSE 0 END DESC,
                  p.created_at DESC
                LIMIT ?
                """,
                (viewer, viewer, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT p.* FROM feed_publications p
                WHERE p.status = 'published'
                  AND p.media_ready_at IS NOT NULL
                  AND p.feed_thumb_name IS NOT NULL
                  AND p.feed_large_name IS NOT NULL
                  {FEED_VIEWER_VISIBLE_SQL}
                ORDER BY p.created_at DESC
                LIMIT ?
                """,
                (viewer, viewer, limit),
            ).fetchall()
        items = [_feed_item_payload(conn, pub, viewer) for pub in rows]
    return {"ok": True, "type": feed_type, "items": items}


@app.post("/api/feed/publications")
async def feed_publish(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    image_id = str(payload.get("imageId") or "").strip()
    title = str(payload.get("title") or "").strip()
    description = str(payload.get("description") or "").strip() or None
    visibility = str(payload.get("promptVisibility") or "open").strip()
    allow_recreate = bool(payload.get("allowRecreate", True))
    if not image_id:
        raise HTTPException(400, "imageId required")
    if not title:
        raise HTTPException(400, "title required")
    if len(title) > 120:
        raise HTTPException(400, "title too long")
    if visibility not in FEED_PROMPT_VISIBILITIES:
        raise HTTPException(400, "invalid promptVisibility")
    with db() as conn:
        image = conn.execute("SELECT id, user_id, url, width, height, mode FROM images WHERE id = ?", (image_id,)).fetchone()
    # Не раскрываем существование чужих изображений: и «нет», и «не твоё» → 404.
    # security_event пишем отдельным соединением ДО raise — with-блок с raise
    # внутри откатил бы запись (паттерн require_trusted_admin).
    if image is None or image["user_id"] != user["legacy_user_id"]:
        with db() as conn:
            record_security_event(
                conn,
                "feed_publish_denied",
                internal_user_id=user["internal_user_id"],
                session_id=user.get("session_id"),
                request=request,
            )
        raise HTTPException(404, "Image not found")
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM feed_publications WHERE image_id = ?", (image_id,)
        ).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        pub_id = existing["id"] if existing else uuid.uuid4().hex
        try:
            assets = create_feed_assets(pub_id, image["url"])
        except FileNotFoundError:
            raise HTTPException(404, "Image file not found")
        except Exception:
            raise HTTPException(400, "Image cannot be prepared for feed")
        source_type = _feed_source_type(_row_get(image, "mode"))
        source_label = _feed_source_label(source_type)
        remix_policy = "allowed" if allow_recreate else "disabled"
        if existing:
            conn.execute(
                "UPDATE feed_publications SET title = ?, description = ?, prompt_visibility = ?, "
                "allow_recreate = ?, status = 'published', feed_thumb_name = ?, feed_large_name = ?, "
                "feed_thumb_width = ?, feed_thumb_height = ?, feed_thumb_bytes = ?, "
                "feed_large_width = ?, feed_large_height = ?, feed_large_bytes = ?, "
                "media_ready_at = ?, media_error = NULL, native_aspect_ratio = ?, orientation = ?, "
                "source_type = ?, source_label = ?, display_policy = ?, remix_policy = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    title,
                    description,
                    visibility,
                    int(allow_recreate),
                    assets.feed_thumb_name,
                    assets.feed_large_name,
                    assets.feed_thumb_width,
                    assets.feed_thumb_height,
                    assets.feed_thumb_bytes,
                    assets.feed_large_width,
                    assets.feed_large_height,
                    assets.feed_large_bytes,
                    now,
                    assets.native_aspect_ratio,
                    assets.orientation,
                    source_type,
                    source_label,
                    FEED_DISPLAY_POLICY,
                    remix_policy,
                    now,
                    pub_id,
                ),
            )
        else:
            conn.execute(
                "INSERT INTO feed_publications (id, image_id, internal_user_id, legacy_user_id, title, "
                "description, prompt_visibility, allow_recreate, status, created_at, feed_thumb_name, "
                "feed_large_name, feed_thumb_width, feed_thumb_height, feed_thumb_bytes, "
                "feed_large_width, feed_large_height, feed_large_bytes, media_ready_at, media_error, "
                "native_aspect_ratio, orientation, source_type, source_label, display_policy, remix_policy, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pub_id,
                    image_id,
                    user["internal_user_id"],
                    user["legacy_user_id"],
                    title,
                    description,
                    visibility,
                    int(allow_recreate),
                    now,
                    assets.feed_thumb_name,
                    assets.feed_large_name,
                    assets.feed_thumb_width,
                    assets.feed_thumb_height,
                    assets.feed_thumb_bytes,
                    assets.feed_large_width,
                    assets.feed_large_height,
                    assets.feed_large_bytes,
                    now,
                    assets.native_aspect_ratio,
                    assets.orientation,
                    source_type,
                    source_label,
                    FEED_DISPLAY_POLICY,
                    remix_policy,
                    now,
                ),
            )
        pub = conn.execute("SELECT * FROM feed_publications WHERE id = ?", (pub_id,)).fetchone()
        item = _feed_item_payload(conn, pub, user["internal_user_id"])
    return {"ok": True, "publication": item}


@app.patch("/api/feed/publications/{publication_id}")
async def update_own_feed_publication(publication_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    if len(title) > 120:
        raise HTTPException(400, "title too long")
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        pub = conn.execute(
            "SELECT * FROM feed_publications WHERE id = ? AND status = 'published'",
            (publication_id,),
        ).fetchone()
        if pub is None:
            raise HTTPException(404, "Publication not found.")
        if pub["internal_user_id"] != user["internal_user_id"]:
            raise HTTPException(403, "You can edit only your own publication.")
        before_title = pub["title"]
        conn.execute(
            "UPDATE feed_publications SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, publication_id),
        )
        record_audit_log(
            conn,
            "update_own_feed_publication",
            actor_internal_user_id=user["internal_user_id"],
            target_internal_user_id=pub["internal_user_id"],
            entity_type="feed_publication",
            entity_id=pub["id"],
            before={"title": before_title},
            after={"title": title},
            request=request,
        )
        updated = conn.execute("SELECT * FROM feed_publications WHERE id = ?", (publication_id,)).fetchone()
        item = _feed_item_payload(conn, updated, user["internal_user_id"])
    return {"ok": True, "publication": item}


def _feed_reaction_toggle(request: Request, publication_id: str, kind: str, enable: bool) -> dict[str, Any]:
    user = require_trusted_user(request)
    with db() as conn:
        pub = conn.execute(
            "SELECT * FROM feed_publications WHERE id = ? AND status = 'published'",
            (publication_id,),
        ).fetchone()
        if pub is None:
            raise HTTPException(404, "Publication not found")
        if enable:
            conn.execute(
                "INSERT OR IGNORE INTO feed_reactions (publication_id, internal_user_id, kind, created_at) "
                "VALUES (?, ?, ?, ?)",
                (publication_id, user["internal_user_id"], kind, datetime.now(timezone.utc).isoformat()),
            )
        else:
            conn.execute(
                "DELETE FROM feed_reactions WHERE publication_id = ? AND internal_user_id = ? AND kind = ?",
                (publication_id, user["internal_user_id"], kind),
            )
        item = _feed_item_payload(conn, pub, user["internal_user_id"])
    return {"ok": True, "publication": item}


@app.post("/api/feed/publications/{publication_id}/like")
async def feed_like(publication_id: str, request: Request) -> dict[str, Any]:
    return _feed_reaction_toggle(request, publication_id, "like", True)


@app.delete("/api/feed/publications/{publication_id}/like")
async def feed_unlike(publication_id: str, request: Request) -> dict[str, Any]:
    return _feed_reaction_toggle(request, publication_id, "like", False)


@app.post("/api/feed/publications/{publication_id}/save")
async def feed_save(publication_id: str, request: Request) -> dict[str, Any]:
    return _feed_reaction_toggle(request, publication_id, "save", True)


@app.delete("/api/feed/publications/{publication_id}/save")
async def feed_unsave(publication_id: str, request: Request) -> dict[str, Any]:
    return _feed_reaction_toggle(request, publication_id, "save", False)


@app.post("/api/feed/publications/{publication_id}/view")
async def feed_publication_view(publication_id: str, request: Request) -> dict[str, Any]:
    viewer = _feed_optional_viewer(request)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        pub = conn.execute(
            "SELECT * FROM feed_publications WHERE id = ? AND status = 'published'",
            (publication_id,),
        ).fetchone()
        if pub is None:
            raise HTTPException(404, "Publication not found")
        conn.execute(
            "UPDATE feed_publications SET view_count = COALESCE(view_count, 0) + 1, updated_at = ? WHERE id = ?",
            (now, publication_id),
        )
        updated = conn.execute("SELECT * FROM feed_publications WHERE id = ?", (publication_id,)).fetchone()
        item = _feed_item_payload(conn, updated, viewer)
    return {"ok": True, "publication": item}


@app.post("/api/feed/publications/{publication_id}/dislike")
async def feed_dislike(publication_id: str, request: Request) -> dict[str, Any]:
    return _feed_reaction_toggle(request, publication_id, "dislike", True)


@app.delete("/api/feed/publications/{publication_id}/dislike")
async def feed_undislike(publication_id: str, request: Request) -> dict[str, Any]:
    return _feed_reaction_toggle(request, publication_id, "dislike", False)


@app.post("/api/feed/publications/{publication_id}/hide")
async def feed_hide(publication_id: str, request: Request) -> dict[str, Any]:
    return _feed_reaction_toggle(request, publication_id, "hide", True)


@app.delete("/api/feed/publications/{publication_id}/hide")
async def feed_unhide(publication_id: str, request: Request) -> dict[str, Any]:
    return _feed_reaction_toggle(request, publication_id, "hide", False)


@app.post("/api/feed/publications/{publication_id}/report")
async def feed_report(publication_id: str, request: Request) -> dict[str, Any]:
    return _feed_reaction_toggle(request, publication_id, "report", True)


@app.post("/api/feed/authors/{author_id}/follow")
async def feed_follow_author(author_id: str, request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    if author_id == user["internal_user_id"]:
        raise HTTPException(400, "Cannot follow yourself")
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM feed_publications WHERE internal_user_id = ? AND status = 'published' LIMIT 1",
            (author_id,),
        ).fetchone()
        if exists is None:
            raise HTTPException(404, "Author not found")
        conn.execute(
            "INSERT OR IGNORE INTO feed_author_follows (follower_internal_user_id, author_internal_user_id, created_at) "
            "VALUES (?, ?, ?)",
            (user["internal_user_id"], author_id, now),
        )
    return {"ok": True, "authorId": author_id, "following": True}


@app.delete("/api/feed/authors/{author_id}/follow")
async def feed_unfollow_author(author_id: str, request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    with db() as conn:
        conn.execute(
            "DELETE FROM feed_author_follows WHERE follower_internal_user_id = ? AND author_internal_user_id = ?",
            (user["internal_user_id"], author_id),
        )
    return {"ok": True, "authorId": author_id, "following": False}


@app.get("/api/feed/authors/{author_id}/publications")
async def feed_author_publications(
    author_id: str,
    request: Request,
    limit: int = 18,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 18), 60))
    viewer = _feed_optional_viewer(request)
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT p.* FROM feed_publications p
            WHERE p.internal_user_id = ?
              AND p.status = 'published'
              AND p.media_ready_at IS NOT NULL
              AND p.feed_thumb_name IS NOT NULL
              AND p.feed_large_name IS NOT NULL
              {FEED_VIEWER_VISIBLE_SQL}
            ORDER BY p.created_at DESC
            LIMIT ?
            """,
            (author_id, viewer, viewer, limit),
        ).fetchall()
        items = [_feed_item_payload(conn, pub, viewer) for pub in rows]
    return {"ok": True, "authorId": author_id, "items": items}


@app.get("/api/feed/challenges")
async def feed_challenges(request: Request) -> dict[str, Any]:
    viewer = _feed_optional_viewer(request)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT c.*, COUNT(p.id) AS publication_count
            FROM challenges c
            LEFT JOIN feed_publications p
              ON p.category = c.category
             AND p.status = 'published'
             AND p.media_ready_at IS NOT NULL
            WHERE c.status = 'active'
            GROUP BY c.id
            ORDER BY c.ends_at ASC
            """
        ).fetchall()
        challenges = []
        for row in rows:
            payload = _feed_challenge_payload(conn, row["category"]) or {}
            payload["publicationCount"] = int(row["publication_count"] or 0)
            challenges.append(payload)
    return {"ok": True, "viewer": viewer, "items": challenges}


@app.post("/api/feed/publications/{publication_id}/recreate")
async def feed_recreate_mark(publication_id: str, request: Request) -> dict[str, Any]:
    """Счётчик «Повторить» (remix_count). Только отметка события — генерация
    идёт обычным /api/generate."""
    return _feed_reaction_toggle(request, publication_id, "recreate", True)


@app.post("/api/feed/publications/{publication_id}/remix/start")
async def feed_remix_start(publication_id: str, request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    with db() as conn:
        pub = conn.execute(
            "SELECT * FROM feed_publications WHERE id = ? AND status = 'published'",
            (publication_id,),
        ).fetchone()
        if pub is None:
            raise HTTPException(404, "Publication not found")
        item = _feed_item_payload(conn, pub, user["internal_user_id"])
        conn.execute(
            "INSERT OR IGNORE INTO feed_reactions (publication_id, internal_user_id, kind, created_at) "
            "VALUES (?, ?, 'recreate', ?)",
            (publication_id, user["internal_user_id"], datetime.now(timezone.utc).isoformat()),
        )
    return {
        "ok": True,
        "remixSessionId": uuid.uuid4().hex,
        "publication": item,
        "mode": item["mode"],
        "prompt": item["prompt"],
        "style": item["style"],
        "sourceImageUrl": item["image_url"] if item["allow_recreate"] else None,
        "aspectRatio": item["native_aspect_ratio"],
        "lockedPrompt": item["prompt_visibility"] == "hidden",
    }


@app.post("/api/admin/feed/publications/{publication_id}/delete-v2")
async def admin_delete_feed_publication_v2(
    publication_id: str,
    req: AdminDeleteImageV2Request,
    request: Request,
) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = _billing_reason(req.reason)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        pub = conn.execute(
            """
            SELECT id, image_id, internal_user_id, legacy_user_id, title, status,
                   feed_thumb_name, feed_large_name, created_at
            FROM feed_publications
            WHERE id = ?
            """,
            (publication_id,),
        ).fetchone()
        if pub is None or pub["status"] != "published":
            raise HTTPException(404, "Publication not found.")
        thumb_name = _row_get(pub, "feed_thumb_name")
        large_name = _row_get(pub, "feed_large_name")
        conn.execute(
            """
            UPDATE feed_publications
            SET status = 'hidden',
                feed_thumb_name = NULL,
                feed_large_name = NULL,
                media_ready_at = NULL,
                media_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            ("admin_deleted", now, publication_id),
        )
        record_audit_log(
            conn,
            "admin_delete_feed_publication",
            actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=pub["internal_user_id"],
            entity_type="feed_publication",
            entity_id=pub["id"],
            before={
                "publication_id": short_public_id(pub["id"]),
                "image_id": short_public_id(pub["image_id"]),
                "status": pub["status"],
                "created_at": pub["created_at"],
            },
            after={"status": "hidden", "media_error": "admin_deleted", "reason": reason},
            request=request,
        )
        record_security_event(
            conn,
            "admin_feed_publication_deleted",
            severity="warning",
            internal_user_id=pub["internal_user_id"],
            request=request,
            details={
                "actor_internal_user_id": admin["internal_user_id"],
                "publication_id": short_public_id(pub["id"]),
                "image_id": short_public_id(pub["image_id"]),
                "reason": reason,
            },
        )
    _delete_media_rel(thumb_name)
    _delete_media_rel(large_name)
    return {
        "ok": True,
        "publicationId": short_public_id(publication_id),
        "status": "hidden",
        "deleted_at": now,
    }


@app.delete("/api/feed/publications/{publication_id}")
async def delete_own_feed_publication(publication_id: str, request: Request) -> dict[str, Any]:
    """Снять свою публикацию с публичной ленты, не удаляя исходник из галереи."""
    user = require_trusted_user(request)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        pub = conn.execute(
            """
            SELECT id, image_id, internal_user_id, legacy_user_id, title, status,
                   feed_thumb_name, feed_large_name, created_at
            FROM feed_publications
            WHERE id = ?
            """,
            (publication_id,),
        ).fetchone()
        if pub is None or pub["status"] != "published":
            raise HTTPException(404, "Publication not found.")
        if pub["internal_user_id"] != user["internal_user_id"]:
            record_security_event(
                conn,
                "feed_publication_delete_denied",
                severity="warning",
                internal_user_id=user["internal_user_id"],
                request=request,
                details={
                    "publication_id": short_public_id(pub["id"]),
                    "owner_internal_user_id": pub["internal_user_id"],
                },
            )
            conn.commit()
            raise HTTPException(403, "You can delete only your own publication.")

        thumb_name = _row_get(pub, "feed_thumb_name")
        large_name = _row_get(pub, "feed_large_name")
        conn.execute(
            """
            UPDATE feed_publications
            SET status = 'hidden',
                feed_thumb_name = NULL,
                feed_large_name = NULL,
                media_ready_at = NULL,
                media_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            ("owner_deleted", now, publication_id),
        )
        record_audit_log(
            conn,
            "delete_own_feed_publication",
            actor_internal_user_id=user["internal_user_id"],
            target_internal_user_id=pub["internal_user_id"],
            entity_type="feed_publication",
            entity_id=pub["id"],
            before={
                "publication_id": short_public_id(pub["id"]),
                "image_id": short_public_id(pub["image_id"]),
                "status": pub["status"],
                "created_at": pub["created_at"],
            },
            after={"status": "hidden", "media_error": "owner_deleted"},
            request=request,
        )
        record_security_event(
            conn,
            "feed_publication_owner_deleted",
            severity="info",
            internal_user_id=user["internal_user_id"],
            request=request,
            details={
                "publication_id": short_public_id(pub["id"]),
                "image_id": short_public_id(pub["image_id"]),
            },
        )
    _delete_media_rel(thumb_name)
    _delete_media_rel(large_name)
    return {
        "ok": True,
        "publicationId": short_public_id(publication_id),
        "status": "hidden",
        "deleted_at": now,
    }


@app.get("/api/feed/media/{publication_id}")
async def feed_media(publication_id: str, request: Request, variant: str = "large", thumb: int = 0) -> FileResponse:
    """Файл ОПУБЛИКОВАННОЙ работы. Доступен любому (публичная лента) — но только
    через публикацию: приватный /api/media остаётся закрытым как был."""
    selected = "thumb" if int(thumb or 0) else (variant or "large").strip().lower()
    if selected not in {"thumb", "large"}:
        raise HTTPException(400, "Invalid feed media variant")
    with db() as conn:
        pub = conn.execute(
                f"""
            SELECT feed_thumb_name, feed_large_name FROM feed_publications
            WHERE id = ?
              AND status = 'published'
              AND media_ready_at IS NOT NULL
              AND feed_thumb_name IS NOT NULL
              AND feed_large_name IS NOT NULL
            """,
            (publication_id,),
        ).fetchone()
        if pub is None:
            raise HTTPException(404, "Publication not found")
    name = _row_get(pub, "feed_thumb_name") if selected == "thumb" else _row_get(pub, "feed_large_name")
    if not name:
        raise HTTPException(404, "Image file not found")
    path = (MEDIA / name).resolve()
    try:
        path.relative_to(MEDIA.resolve())
    except ValueError:
        raise HTTPException(404, "Image file not found")
    if not path.exists():
        raise HTTPException(404, "Image file not found")
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
