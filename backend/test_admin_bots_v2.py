from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
# Browser-faithful contract: cookie-auth mutations carry an allowlisted Origin
# to pass the CSRF boundary (AUTH-LEGACY-001B). GET requests stay untouched.
from test_support.browser_origin import BROWSER_ORIGIN


NOW = "2026-07-16T00:00:00+00:00"


class MemorySecretStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.values: dict[str, str] = {}

    def path_for(self, name: str) -> Path:
        return self.root / f"{name}.dpapi.json"

    def exists(self, name: str) -> bool:
        return name in self.values

    def get(self, name: str) -> str:
        return self.values.get(name, "")

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> bool:
        return self.values.pop(name, None) is not None


@pytest.fixture
def bot_admin_env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "bots.sqlite3")
    monkeypatch.setattr(main, "OPENROUTER_SECRET_STORE", MemorySecretStore(tmp_path / "secrets"))
    for name in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
        "MAX_BOT_TOKEN",
        "MAX_WEBHOOK_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(main, "BOT_UPDATES_MODE", "disabled")
    monkeypatch.setattr(main, "BOT_MODE", "disabled")
    monkeypatch.setattr(main, "MAX_UPDATES_MODE", "disabled")
    monkeypatch.setattr(main, "TELEGRAM_POLLING_ENABLED", False)
    monkeypatch.setattr(main, "MAX_POLLING_ENABLED", False)
    monkeypatch.setattr(main.BOT_RUNTIME, "polling_tasks", {})
    main.init_db()

    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, username, first_name, language, role, "
            "created_at, last_login_at, banned, last_seen_at) "
            "VALUES ('admin-legacy', 'admin-internal', 'admin', 'Admin', 'ru', 'admin', ?, ?, 0, ?)",
            (NOW, NOW, NOW),
        )
    session = main.create_auth_session(
        "admin-internal",
        "admin-legacy",
        provider="telegram",
        platform="telegram_mini_app",
    )
    return {
        "cookies": {"onenode_session": session["session_token"]},
        "store": main.OPENROUTER_SECRET_STORE,
    }


def healthy(**values):
    payload = {"configured": True, "ok": True, "status": "ok", **values}
    return SimpleNamespace(ok=True, as_dict=lambda: payload)


def test_bots_admin_requires_trusted_admin(bot_admin_env):
    with TestClient(main.app) as client:
        assert client.get("/api/admin/bots/config-v2").status_code == 401
        assert client.get("/api/admin/bots/status-v2").status_code == 401


def test_default_modes_are_disabled_and_token_save_is_inert(bot_admin_env, monkeypatch):
    async def fake_probe(*, token: str, **_kwargs):
        assert token == "telegram-test-token"
        return healthy(bot_id=42, username="izo_test_bot")

    monkeypatch.setattr(main, "probe_telegram_bot", fake_probe)
    started_before = dict(main.BOT_RUNTIME.polling_tasks)
    with TestClient(main.app) as client:
        config = client.get("/api/admin/bots/config-v2", cookies=bot_admin_env["cookies"])
        saved = client.put(
            "/api/admin/bots/telegram/token-v2",
            json={"token": "telegram-test-token", "verify": True},
            cookies=bot_admin_env["cookies"],
            headers=BROWSER_ORIGIN,
        )

    assert config.status_code == 200
    assert config.json()["config"]["telegram"]["mode"] == "disabled"
    assert config.json()["config"]["max"]["mode"] == "disabled"
    assert saved.status_code == 200
    assert saved.json()["activated"] is False
    assert main.BOT_RUNTIME.polling_tasks == started_before
    assert bot_admin_env["store"].get(main.TELEGRAM_BOT_SECRET_NAME) == "telegram-test-token"
    assert "telegram-test-token" not in saved.text

    with main.db() as conn:
        settings = "\n".join(str(row["value_json"]) for row in conn.execute("SELECT value_json FROM admin_settings"))
        audits = "\n".join(str(row["after_json"]) for row in conn.execute("SELECT after_json FROM audit_logs"))
    assert "telegram-test-token" not in settings
    assert "telegram-test-token" not in audits


def test_bot_secret_can_be_replaced_and_deleted(bot_admin_env, monkeypatch):
    async def fake_probe(**_kwargs):
        return healthy(bot_id=7, username="safe_bot")

    monkeypatch.setattr(main, "probe_telegram_bot", fake_probe)
    with TestClient(main.app) as client:
        for token in ("telegram-token-one", "telegram-token-two"):
            response = client.put(
                "/api/admin/bots/telegram/token-v2",
                json={"token": token},
                cookies=bot_admin_env["cookies"],
            headers=BROWSER_ORIGIN,
            )
            assert response.status_code == 200
            assert token not in response.text
        deleted = client.delete(
            "/api/admin/bots/telegram/token-v2",
            cookies=bot_admin_env["cookies"],
            headers=BROWSER_ORIGIN,
        )
    assert deleted.status_code == 200
    assert bot_admin_env["store"].get(main.TELEGRAM_BOT_SECRET_NAME) == ""


def test_max_token_is_saved_without_exposure(bot_admin_env, monkeypatch):
    async def fake_probe(**_kwargs):
        return healthy()

    monkeypatch.setattr(main, "probe_max_bot", fake_probe)
    with TestClient(main.app) as client:
        response = client.put(
            "/api/admin/bots/max/token-v2",
            json={"token": "max-private-test-token"},
            cookies=bot_admin_env["cookies"],
            headers=BROWSER_ORIGIN,
        )
    assert response.status_code == 200
    assert response.json()["activated"] is False
    assert bot_admin_env["store"].get(main.MAX_BOT_SECRET_NAME) == "max-private-test-token"
    assert "max-private-test-token" not in response.text


def test_safe_status_contains_diagnostics_but_no_secrets(bot_admin_env, monkeypatch):
    bot_admin_env["store"].set(main.TELEGRAM_BOT_SECRET_NAME, "telegram-private-token")
    bot_admin_env["store"].set(main.TELEGRAM_WEBHOOK_SECRET_NAME, "telegram-private-secret")
    bot_admin_env["store"].set(main.MAX_BOT_SECRET_NAME, "max-private-token")
    bot_admin_env["store"].set(main.MAX_WEBHOOK_SECRET_NAME, "max-private-secret")

    async def telegram_probe():
        return {
            "configured": True,
            "ok": True,
            "status": "ok",
            "bot_id": 42,
            "username": "safe_telegram_bot",
            "name": "Safe Telegram",
            "webhook": {"configured": False, "url": None},
        }

    async def max_probe(_config):
        return {
            "configured": True,
            "ok": True,
            "status": "ok",
            "bot_id": "max-42",
            "nickname": "safe_max_bot",
            "name": "Safe MAX",
            "subscriptions": [],
        }

    async def public_status(_config):
        return {
            "ok": True,
            "url": "https://izo.alikinas.ru",
            "source": "admin_settings",
        }

    monkeypatch.setattr(main, "_admin_telegram_probe", telegram_probe)
    monkeypatch.setattr(main, "_admin_max_probe", max_probe)
    monkeypatch.setattr(main, "_admin_bot_public_https_status", public_status)
    with TestClient(main.app) as client:
        response = client.get(
            "/api/admin/bots/status-v2",
            cookies=bot_admin_env["cookies"],
        )
    assert response.status_code == 200
    assert response.json()["telegram"]["probe"]["username"] == "safe_telegram_bot"
    assert response.json()["max"]["probe"]["nickname"] == "safe_max_bot"
    for secret in (
        "telegram-private-token",
        "telegram-private-secret",
        "max-private-token",
        "max-private-secret",
    ):
        assert secret not in response.text


def test_saved_runtime_config_reads_dpapi_after_restart(bot_admin_env):
    bot_admin_env["store"].set(main.TELEGRAM_BOT_SECRET_NAME, "telegram-runtime-token")
    bot_admin_env["store"].set(main.MAX_BOT_SECRET_NAME, "max-runtime-token")
    main.save_bot_integrations_config(
        {
            **main.DEFAULT_BOT_INTEGRATIONS,
            "telegram": {
                **main.DEFAULT_BOT_INTEGRATIONS["telegram"],
                "mode": "disabled",
            },
            "max": {
                **main.DEFAULT_BOT_INTEGRATIONS["max"],
                "mode": "disabled",
            },
        }
    )
    applied = main.apply_saved_bot_runtime_configuration()
    assert applied["source"] == "admin_settings"
    assert main.TELEGRAM_BOT_TOKEN == "telegram-runtime-token"
    assert main.MAX_BOT_TOKEN == "max-runtime-token"
    assert main.BOT_UPDATES_MODE == "disabled"
    assert main.MAX_UPDATES_MODE == "disabled"


def test_polling_and_webhook_require_complete_configuration(bot_admin_env):
    polling_config = main.normalize_bot_integrations(
        {
            **main.DEFAULT_BOT_INTEGRATIONS,
            "telegram": {
                **main.DEFAULT_BOT_INTEGRATIONS["telegram"],
                "mode": "polling",
                "pollingEnabled": True,
            },
        },
        production=False,
    )
    webhook_config = main.normalize_bot_integrations(
        {
            **main.DEFAULT_BOT_INTEGRATIONS,
            "telegram": {
                **main.DEFAULT_BOT_INTEGRATIONS["telegram"],
                "mode": "webhook",
            },
        },
        production=False,
    )
    with TestClient(main.app) as client:
        polling = client.put(
            "/api/admin/bots/config-v2",
            json={"config": polling_config, "confirmModeChange": True},
            cookies=bot_admin_env["cookies"],
            headers=BROWSER_ORIGIN,
        )
        webhook = client.put(
            "/api/admin/bots/config-v2",
            json={"config": webhook_config, "confirmModeChange": True},
            cookies=bot_admin_env["cookies"],
            headers=BROWSER_ORIGIN,
        )
    assert polling.status_code == 400
    assert webhook.status_code == 400


def test_mode_change_requires_explicit_confirmation(bot_admin_env):
    config = {
        **main.DEFAULT_BOT_INTEGRATIONS,
        "telegram": {
            **main.DEFAULT_BOT_INTEGRATIONS["telegram"],
            "mode": "polling",
            "pollingEnabled": True,
        },
    }
    with TestClient(main.app) as client:
        response = client.put(
            "/api/admin/bots/config-v2",
            json={"config": config, "confirmModeChange": False},
            cookies=bot_admin_env["cookies"],
            headers=BROWSER_ORIGIN,
        )
    assert response.status_code == 409


def test_generated_webhook_secret_is_never_returned(bot_admin_env):
    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/bots/max/webhook-secret-v2",
            cookies=bot_admin_env["cookies"],
            headers=BROWSER_ORIGIN,
        )
    assert response.status_code == 200
    assert response.json()["configured"] is True
    stored = bot_admin_env["store"].get(main.MAX_WEBHOOK_SECRET_NAME)
    assert stored
    assert stored not in response.text


def test_bot_url_validation_rejects_credentials_and_non_https_webhook():
    with pytest.raises(ValueError):
        main.normalize_bot_integrations(
            {
                **main.DEFAULT_BOT_INTEGRATIONS,
                "max": {
                    **main.DEFAULT_BOT_INTEGRATIONS["max"],
                    "webhookUrl": "http://example.test/hook",
                },
            },
            production=False,
        )
    with pytest.raises(ValueError):
        main.normalize_bot_integrations(
            {
                **main.DEFAULT_BOT_INTEGRATIONS,
                "public": {
                    "siteUrl": "https://user:password@example.test",
                    "backendUrl": "https://example.test",
                },
            },
            production=True,
        )


def test_secret_store_failure_returns_safe_error(bot_admin_env, monkeypatch):
    def fail_set(_name: str, _value: str) -> None:
        raise main.SecretStoreError("sensitive internal failure")

    monkeypatch.setattr(bot_admin_env["store"], "set", fail_set)
    with TestClient(main.app) as client:
        response = client.put(
            "/api/admin/bots/max/token-v2",
            json={"token": "max-test-token"},
            cookies=bot_admin_env["cookies"],
            headers=BROWSER_ORIGIN,
        )
    assert response.status_code == 503
    assert "sensitive internal failure" not in response.text
    assert "Защищённое хранилище недоступно" in response.text
