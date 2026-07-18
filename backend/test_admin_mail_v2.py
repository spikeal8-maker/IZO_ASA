from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

import main
from app.integrations.smtp import SmtpError


@pytest.fixture
def admin_mail_app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "admin-mail.sqlite3")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "APP_ENV", "test")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", False)
    main.init_db()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, role, token_balance, language, created_at, last_login_at) "
            "VALUES ('admin', 'iuid-admin', 'admin', 0, 'ru', '2026-01-01', '2026-01-01')"
        )
    token = main.create_auth_session("iuid-admin", "admin", provider="web_email", platform="web_desktop")["session_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "monkeypatch": monkeypatch}


def mail_payload(password: str | None = "application-password") -> dict:
    return {
        "host": "smtp.mail.ru",
        "port": 465,
        "username": "mail@alikinas.ru",
        "password": password,
        "sender_name": "ИЗО АСА",
        "sender_email": "mail@alikinas.ru",
        "use_ssl": True,
        "save": True,
    }


def test_failed_verification_keeps_config_but_does_not_enable_mail(admin_mail_app) -> None:
    def fail(_config):
        raise SmtpError("Mail.ru не принял пароль приложения.")

    admin_mail_app["monkeypatch"].setattr(main, "verify_smtp_connection", fail)
    with TestClient(main.app) as client:
        response = client.post("/api/admin/mail/verify-v2", json=mail_payload(), headers=admin_mail_app["headers"])
        status = client.get("/api/admin/mail/status-v2", headers=admin_mail_app["headers"])

    assert response.status_code == 502
    config = status.json()["config"]
    assert config["configured"] is True
    assert config["verified"] is False
    assert config["password"] is True
    assert config["username"] == "mail@alikinas.ru"
    assert "пароль приложения" in config["last_error"]
    assert status.json()["service_ready"] is False

    with main.db() as conn:
        row = conn.execute("SELECT value_json FROM admin_settings WHERE key='mail_provider'").fetchone()
    saved = json.loads(row["value_json"])
    assert saved["username"] == "mail@alikinas.ru"
    assert saved["verified_at"] is None


def test_successful_verification_activates_saved_mail(admin_mail_app) -> None:
    admin_mail_app["monkeypatch"].setattr(main, "verify_smtp_connection", lambda _config: None)
    with TestClient(main.app) as client:
        response = client.post("/api/admin/mail/verify-v2", json=mail_payload(), headers=admin_mail_app["headers"])
        status = client.get("/api/admin/mail/status-v2", headers=admin_mail_app["headers"])

    assert response.status_code == 200, response.text
    assert response.json()["verified"] is True
    config = status.json()["config"]
    assert config["configured"] is True
    assert config["verified"] is True
    assert config["verified_at"]
    assert config["last_error"] is None
    assert status.json()["service_ready"] is True


def test_unisender_verification_creates_list_and_sends_real_probe(admin_mail_app) -> None:
    secret = {"value": ""}
    sent: list = []
    admin_mail_app["monkeypatch"].setattr(main, "save_unisender_api_key", lambda value: secret.__setitem__("value", value))
    admin_mail_app["monkeypatch"].setattr(main, "unisender_api_key", lambda: secret["value"])
    admin_mail_app["monkeypatch"].setattr(main, "get_unisender_lists", lambda _key: [])
    admin_mail_app["monkeypatch"].setattr(
        main,
        "create_unisender_list",
        lambda _key, title: {"id": 77, "title": title},
    )
    admin_mail_app["monkeypatch"].setattr(
        main,
        "send_unisender_email",
        lambda _key, message: sent.append(message) or "mail-77",
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/mail/unisender/verify-v2",
            json={
                "api_key": "unisender-secret-key",
                "sender_name": "ИЗО АСА",
                "sender_email": "mail@alikinas.ru",
                "create_list_if_missing": True,
            },
            headers=admin_mail_app["headers"],
        )
        status = client.get("/api/admin/mail/status-v2", headers=admin_mail_app["headers"])

    assert response.status_code == 200, response.text
    assert response.json()["list_id"] == 77
    assert sent[0].to == "mail@alikinas.ru"
    payload = status.json()
    assert payload["provider"] == "unisender"
    assert payload["service_ready"] is True
    assert payload["providers"]["unisender"]["verified"] is True
    assert payload["providers"]["unisender"]["api_key"] is True
    assert "unisender-secret-key" not in status.text


def test_unisender_failed_probe_preserves_auto_created_list(admin_mail_app) -> None:
    secret = {"value": ""}
    admin_mail_app["monkeypatch"].setattr(main, "save_unisender_api_key", lambda value: secret.__setitem__("value", value))
    admin_mail_app["monkeypatch"].setattr(main, "unisender_api_key", lambda: secret["value"])
    admin_mail_app["monkeypatch"].setattr(main, "get_unisender_lists", lambda _key: [])
    admin_mail_app["monkeypatch"].setattr(
        main,
        "create_unisender_list",
        lambda _key, title: {"id": 91, "title": title},
    )
    admin_mail_app["monkeypatch"].setattr(
        main,
        "send_unisender_email",
        lambda _key, _message: (_ for _ in ()).throw(main.UniSenderError("Отправитель не подтвержден.")),
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/mail/unisender/verify-v2",
            json={
                "api_key": "unisender-secret-key",
                "sender_name": "ИЗО АСА",
                "sender_email": "mail@alikinas.ru",
                "create_list_if_missing": True,
            },
            headers=admin_mail_app["headers"],
        )

    assert response.status_code == 502
    config = main.unisender_config()
    assert config["list_id"] == 91
    assert config["verified_at"] is None
    assert config["last_error"] == "Отправитель не подтвержден."


def test_email_otp_prefers_verified_unisender(admin_mail_app) -> None:
    sent: list = []
    admin_mail_app["monkeypatch"].setattr(main, "unisender_api_key", lambda: "saved-key")
    admin_mail_app["monkeypatch"].setattr(
        main,
        "unisender_config",
        lambda: {
            "source": "admin",
            "sender_name": "ИЗО АСА",
            "sender_email": "mail@alikinas.ru",
            "list_id": 77,
            "verified_at": "2026-07-18T00:00:00+00:00",
            "last_error": None,
        },
    )
    admin_mail_app["monkeypatch"].setattr(
        main,
        "send_unisender_email",
        lambda _key, message: sent.append(message) or "mail-otp",
    )

    main.send_email_otp("user@example.test", "123456")

    assert sent[0].to == "user@example.test"
    assert "123456" in sent[0].html
