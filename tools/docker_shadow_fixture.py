"""Explicit, bounded acceptance-only entrypoint using the existing Comfy fixture."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time

try:
    from tools.docker_shadow_provider import ControlledProvider
except ModuleNotFoundError:
    from docker_shadow_provider import ControlledProvider

MARKER = "controlled-comfyui-v1"
PROVIDER_PORT = 48991
CONTROL_PORT = 48992
LIFETIME_SECONDS = 300
RECEIPT = Path("/tmp/izo-shadow-provider-receipt.json")
DISABLED_ENDPOINTS = ("OLLAMA_BASE_URL", "QWEN_ASR_BASE_URL", "OPENROUTER_BASE_URL",
                      "MAX_API_BASE_URL", "LOCAL_LTX_COMFYUI_BASE_URL")
SECRET_KEYS = ("TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN", "OPENROUTER_API_KEY",
               "PAYMENT_PROVIDER_TOKEN", "YOOKASSA_SECRET_KEY", "SMTP_PASSWORD",
               "SMTP_TOKEN", "UNISENDER_API_KEY", "VK_ACCESS_TOKEN")


def validate_environment(environment: dict) -> None:
    """Refuse accidental provider fallback or a non-test application profile."""
    required = {"IZO_SHADOW_FIXTURE": MARKER, "APP_ENV": "test", "ENV": "test",
                "MODE": "test", "BOT_MODE": "disabled", "MAX_UPDATES_MODE": "disabled",
                "COMFYUI_BASE_URL": f"http://127.0.0.1:{PROVIDER_PORT}",
                "COMFYUI_MOCK_FALLBACK": "false"}
    if any(environment.get(key) != value for key, value in required.items()):
        raise RuntimeError("SHADOW_FIXTURE_PROFILE_REQUIRED")
    if any(environment.get(key) != "http://127.0.0.1:1" for key in DISABLED_ENDPOINTS):
        raise RuntimeError("SHADOW_FIXTURE_EXTERNAL_ENDPOINT_FORBIDDEN")
    if any(environment.get(key, "") for key in SECRET_KEYS):
        raise RuntimeError("SHADOW_FIXTURE_EXTERNAL_CREDENTIAL_FORBIDDEN")


def write_receipt(provider: ControlledProvider, path: Path = RECEIPT) -> None:
    """Only the existing provider's secret-free receipt crosses this boundary."""
    data = {"fixture": MARKER, "lifetimeSeconds": LIFETIME_SECONDS,
            "provider": provider.receipt()}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def run() -> None:
    validate_environment(dict(os.environ))
    import uvicorn

    server = uvicorn.Server(uvicorn.Config("main:app", host="0.0.0.0", port=8000,
                                         workers=1, log_level="warning"))
    stop = threading.Event()
    failures = []
    with ControlledProvider(bind="127.0.0.1", port=PROVIDER_PORT,
                            control_port=CONTROL_PORT,
                            lifetime_seconds=LIFETIME_SECONDS) as provider:
        write_receipt(provider)
        deadline = time.monotonic() + LIFETIME_SECONDS

        def record() -> None:
            try:
                while not stop.wait(.2):
                    write_receipt(provider)
                    if time.monotonic() >= deadline:
                        server.should_exit = True
                        return
            except (OSError, ValueError, TypeError):
                failures.append("SHADOW_FIXTURE_RECEIPT_FAILED")
                server.should_exit = True

        recorder = threading.Thread(target=record, name="shadow-fixture-receipt", daemon=True)
        recorder.start()
        try:
            server.run()
        finally:
            stop.set()
            recorder.join(timeout=2)
            write_receipt(provider)
        if recorder.is_alive() or failures:
            raise RuntimeError("SHADOW_FIXTURE_RECEIPT_FAILED")


if __name__ == "__main__":
    try:
        run()
    except (RuntimeError, OSError, ValueError, TypeError):
        print("SHADOW_FIXTURE_FAILED", flush=True)
        raise SystemExit(1) from None
