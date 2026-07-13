from __future__ import annotations

import asyncio

import pytest

import main


def test_startup_blocks_on_config_before_webhook_and_database(monkeypatch) -> None:
    calls: list[str] = []

    def block_unsafe_config(**_kwargs) -> None:
        calls.append("production_config")
        raise RuntimeError("Unsafe production configuration: TEST_ERROR")

    monkeypatch.setattr(main, "validate_config_production_configuration", block_unsafe_config)
    monkeypatch.setattr(
        main,
        "validate_telegram_webhook_secret",
        lambda *_args: calls.append("telegram_webhook"),
    )
    monkeypatch.setattr(main, "db_guard_preflight", lambda: calls.append("db_guard"))

    with pytest.raises(RuntimeError, match="TEST_ERROR"):
        asyncio.run(main.startup())

    assert calls == ["production_config"]


def test_startup_passes_current_typed_policies_to_validator(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def capture_config(**kwargs) -> None:
        captured.update(kwargs)

    def stop_after_config(*_args) -> None:
        raise RuntimeError("STOP_AFTER_CONFIG")

    monkeypatch.setattr(main, "validate_config_production_configuration", capture_config)
    monkeypatch.setattr(main, "validate_telegram_webhook_secret", stop_after_config)

    with pytest.raises(RuntimeError, match="STOP_AFTER_CONFIG"):
        asyncio.run(main.startup())

    assert captured == {
        "runtime": main.RUNTIME_ENVIRONMENT_POLICY,
        "http_security": main._HTTP_SECURITY_POLICY,
        "providers": main.PROVIDER_ENDPOINT_POLICY,
        "storage": main.STORAGE_PATH_POLICY,
    }
