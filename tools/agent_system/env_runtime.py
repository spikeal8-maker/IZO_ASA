"""Exact sanitized child runtime environment for AI-DEV-ENV-001."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .env import CREDENTIAL_CLASSIFICATIONS

RUNTIME_CONTRACT_ID = "izo.agent-env.runtime.v1"
DISABLED_LOOPBACK_URL = "http://127.0.0.1:1"

EXPLICIT_RUNTIME_SENSITIVE_KEYS = (
    "SESSION_HMAC_SECRET",
    "ADMIN_ONE_TIME_CODE",
    "RUNTIME_SYNTHETIC_KEY",
    "UNISENDER_API_KEY",
)
PROVIDER_CREDENTIAL_KEYS = tuple(
    sorted(set(CREDENTIAL_CLASSIFICATIONS) | {"UNISENDER_API_KEY"})
)
EMPTY_CREDENTIAL_KEYS = tuple(
    sorted(set(PROVIDER_CREDENTIAL_KEYS) | set(EXPLICIT_RUNTIME_SENSITIVE_KEYS))
)

RUNTIME_LABELS = {
    "APP_ENV": "test",
    "ENV": "test",
    "MODE": "test",
}
BOT_CONTROLS = {
    "BOT_MODE": "disabled",
    "BOT_UPDATES_MODE": "disabled",
    "TELEGRAM_POLLING_ENABLED": "false",
    "MAX_UPDATES_MODE": "disabled",
    "MAX_POLLING_ENABLED": "false",
}
RUNTIME_CONTROLS = {
    "EMAIL_OTP_DEBUG_RETURN_CODE": "false",
    "LOCAL_LTX_ENABLED": "false",
}
NEUTRALIZED_EXTERNAL_ENVIRONMENT = {
    "OPENROUTER_BASE_URL": DISABLED_LOOPBACK_URL,
    "MAX_API_BASE_URL": DISABLED_LOOPBACK_URL,
    "MAX_WEBHOOK_URL": "",
    "BACKEND_PUBLIC_URL": "",
    "RUNTIME_ALERT_WEBHOOK_URL": "",
    "CBR_DAILY_XML_URL": DISABLED_LOOPBACK_URL,
    "USD_RUB_FALLBACK_URL": DISABLED_LOOPBACK_URL,
}
LOCAL_PROVIDER_KEYS = (
    "COMFYUI_BASE_URL",
    "OLLAMA_BASE_URL",
    "QWEN_ASR_BASE_URL",
)
ROUTING_KEYS = ("DATABASE_URL", "MEDIA_DIR", "IZO_SECRET_DIR")
REVIEWED_CHILD_ENVIRONMENT_KEYS = frozenset(
    set(ROUTING_KEYS)
    | set(RUNTIME_LABELS)
    | set(BOT_CONTROLS)
    | set(RUNTIME_CONTROLS)
    | set(NEUTRALIZED_EXTERNAL_ENVIRONMENT)
    | set(LOCAL_PROVIDER_KEYS)
    | set(EMPTY_CREDENTIAL_KEYS)
    | {"LOCAL_LTX_COMFYUI_BASE_URL"}
)


def build_exact_child_environment(
    *,
    database_path: Path,
    media_root: Path,
    secret_dir: Path,
    local_provider_endpoints: Mapping[str, str],
) -> dict[str, str]:
    providers = {
        name: str(local_provider_endpoints[name])
        for name in LOCAL_PROVIDER_KEYS
    }
    environment = {
        "DATABASE_URL": str(database_path),
        "MEDIA_DIR": str(media_root),
        "IZO_SECRET_DIR": str(secret_dir),
        **RUNTIME_LABELS,
        **BOT_CONTROLS,
        **providers,
        **RUNTIME_CONTROLS,
        **NEUTRALIZED_EXTERNAL_ENVIRONMENT,
        **{name: "" for name in EMPTY_CREDENTIAL_KEYS},
        "LOCAL_LTX_COMFYUI_BASE_URL": providers["COMFYUI_BASE_URL"],
    }
    if set(environment) != REVIEWED_CHILD_ENVIRONMENT_KEYS:
        raise RuntimeError("RUNTIME_CHILD_ENVIRONMENT_KEYSET_INVALID")
    return environment


def build_runtime_environment_contract(
    *,
    package_id: str,
    database_path: Path,
    media_root: Path,
    secret_dir: Path,
    local_provider_endpoints: Mapping[str, str],
) -> dict[str, object]:
    environment = build_exact_child_environment(
        database_path=database_path,
        media_root=media_root,
        secret_dir=secret_dir,
        local_provider_endpoints=local_provider_endpoints,
    )
    routing = {name: environment[name] for name in ROUTING_KEYS}
    local = {name: environment[name] for name in LOCAL_PROVIDER_KEYS}
    bot_activity = {
        "BOT_MODE": "disabled",
        "BOT_UPDATES_MODE": "disabled",
        "TELEGRAM_POLLING_ENABLED": False,
        "MAX_UPDATES_MODE": "disabled",
        "MAX_POLLING_ENABLED": False,
    }
    credentials = {
        name: {"inherit": False, "productionCredential": "ABSENT"}
        for name in EMPTY_CREDENTIAL_KEYS
    }
    return {
        "contractId": RUNTIME_CONTRACT_ID,
        "packageId": package_id,
        "inheritAmbient": False,
        "backendDotEnvAllowed": False,
        "backendDotEnvInheritance": "FORBIDDEN",
        "hostSecretStoreInheritance": "FORBIDDEN",
        "externalInternetAllowed": False,
        "routing": routing,
        "runtimeLabels": dict(RUNTIME_LABELS),
        "botActivity": bot_activity,
        "localProviders": local,
        "credentials": credentials,
        "neutralizedExternalEnvironment": dict(NEUTRALIZED_EXTERNAL_ENVIRONMENT),
        "protectedEmptyKeys": list(EMPTY_CREDENTIAL_KEYS),
        "environment": environment,
    }
