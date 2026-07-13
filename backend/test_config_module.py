from __future__ import annotations

import os
from pathlib import Path

from backend.app.config import (
    DEFAULT_CORS_ALLOWED_ORIGINS,
    env_bool,
    is_production_like_environment,
    load_bot_delivery_policy,
    load_http_security_policy,
    load_local_env,
    load_provider_endpoint_policy,
    load_runtime_environment_policy,
    sqlite_path_from_database_url,
)


def test_sqlite_path_parsing(tmp_path: Path) -> None:
    assert sqlite_path_from_database_url("sqlite:///C:/data/app.sqlite3") == Path("C:/data/app.sqlite3")
    assert sqlite_path_from_database_url("sqlite:C:/data/app.sqlite3") == Path("C:/data/app.sqlite3")
    assert sqlite_path_from_database_url("C:/data/app.sqlite3") == Path("C:/data/app.sqlite3")
    assert sqlite_path_from_database_url(None, tmp_path) == tmp_path / "onenode.sqlite3"


def test_env_bool(monkeypatch) -> None:
    monkeypatch.delenv("CONFIG_BOOL_TEST", raising=False)
    assert env_bool("CONFIG_BOOL_TEST") is False
    assert env_bool("CONFIG_BOOL_TEST", True) is True
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("CONFIG_BOOL_TEST", value)
        assert env_bool("CONFIG_BOOL_TEST") is True
    monkeypatch.setenv("CONFIG_BOOL_TEST", "false")
    assert env_bool("CONFIG_BOOL_TEST", True) is False


def test_local_env_loader_does_not_override_process_environment(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nCONFIG_EXISTING=file-value\nCONFIG_NEW='new value'\nINVALID_LINE\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_EXISTING", "process-value")
    monkeypatch.delenv("CONFIG_NEW", raising=False)

    load_local_env(tmp_path)

    assert os.environ["CONFIG_EXISTING"] == "process-value"
    assert os.environ["CONFIG_NEW"] == "new value"


def test_http_security_policy_development_defaults() -> None:
    policy = load_http_security_policy({}, app_env="development")

    assert policy.session_cookie_name == "onenode_session"
    assert policy.refresh_cookie_name == "onenode_refresh"
    assert policy.cookie_secure is False
    assert policy.cookie_samesite == "lax"
    assert policy.cookie_domain is None
    assert policy.cookie_path == "/"
    assert policy.bot_login_challenge_cookie_name == "onenode_bot_login"
    assert policy.bot_login_challenge_ttl_seconds == 600
    assert policy.trust_proxy_headers is False
    assert policy.trust_cloudflare_headers is False
    assert policy.cors_allowed_origins == DEFAULT_CORS_ALLOWED_ORIGINS


def test_http_security_policy_production_secure_default() -> None:
    assert load_http_security_policy({}, app_env="production").cookie_secure is True
    assert load_http_security_policy({}, app_env="prod").cookie_secure is False


def test_http_security_policy_preserves_exact_environment_overrides() -> None:
    policy = load_http_security_policy(
        {
            "TRUSTED_SESSION_COOKIE_NAME": "session_test",
            "TRUSTED_REFRESH_COOKIE_NAME": "refresh_test",
            "TRUSTED_COOKIE_SECURE": "TRUE",
            "TRUSTED_COOKIE_SAMESITE": "none",
            "TRUSTED_COOKIE_DOMAIN": ".example.test",
            "TRUSTED_COOKIE_PATH": "/app",
            "BOT_LOGIN_CHALLENGE_COOKIE_NAME": "challenge_test",
            "BOT_LOGIN_CHALLENGE_TTL_SECONDS": "42",
            "TRUST_PROXY_HEADERS": "true",
            "TRUST_CLOUDFLARE_HEADERS": "true",
            "CORS_ALLOWED_ORIGINS": " https://one.example, ,https://two.example ",
        },
        app_env="development",
    )

    assert policy.session_cookie_name == "session_test"
    assert policy.refresh_cookie_name == "refresh_test"
    assert policy.cookie_secure is True
    assert policy.cookie_samesite == "none"
    assert policy.cookie_domain == ".example.test"
    assert policy.cookie_path == "/app"
    assert policy.bot_login_challenge_cookie_name == "challenge_test"
    assert policy.bot_login_challenge_ttl_seconds == 42
    assert policy.trust_proxy_headers is True
    assert policy.trust_cloudflare_headers is True
    assert policy.cors_allowed_origins == ("https://one.example", "https://two.example")


def test_http_security_policy_does_not_broaden_legacy_true_semantics() -> None:
    policy = load_http_security_policy(
        {
            "TRUSTED_COOKIE_SECURE": "1",
            "TRUST_PROXY_HEADERS": "yes",
            "TRUST_CLOUDFLARE_HEADERS": " true ",
        },
        app_env="production",
    )

    assert policy.cookie_secure is False
    assert policy.trust_proxy_headers is False
    assert policy.trust_cloudflare_headers is False


def test_provider_endpoint_policy_defaults_match_legacy_main_contract() -> None:
    policy = load_provider_endpoint_policy({})

    assert policy.comfyui_base_url == "http://127.0.0.1:8188"
    assert policy.comfyui_required is False
    assert policy.comfyui_mock_fallback is False
    assert policy.comfyui_timeout_seconds == 900
    assert policy.comfyui_face_timeout_seconds == 240
    assert policy.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert policy.openrouter_timeout_seconds == 120
    assert policy.prompt_improve_model == "deepseek/deepseek-v4-flash"
    assert policy.prompt_improve_timeout_seconds == 10
    assert policy.cbr_daily_xml_url == "https://www.cbr.ru/scripts/XML_daily.asp"
    assert policy.usd_rub_fallback_url == "https://open.er-api.com/v6/latest/USD"


def test_provider_endpoint_policy_preserves_legacy_normalization_and_bounds() -> None:
    policy = load_provider_endpoint_policy(
        {
            "COMFYUI_BASE_URL": " http://comfy.example/ ",
            "COMFYUI_REQUIRED": "TRUE",
            "COMFYUI_MOCK_FALLBACK": "1",
            "COMFYUI_TIMEOUT_SECONDS": "100",
            "COMFYUI_FACE_TIMEOUT_SECONDS": "200",
            "OPENROUTER_BASE_URL": "https://router.example///",
            "OPENROUTER_TIMEOUT_SECONDS": "999",
            "PROMPT_IMPROVE_MODEL": "  provider/model  ",
            "PROMPT_IMPROVE_TIMEOUT_SECONDS": "-1",
            "CBR_DAILY_XML_URL": " cbr-url ",
            "USD_RUB_FALLBACK_URL": " fallback-url ",
        }
    )

    assert policy.comfyui_base_url == " http://comfy.example/ "
    assert policy.comfyui_required is True
    assert policy.comfyui_mock_fallback is False
    assert policy.comfyui_timeout_seconds == 100
    assert policy.comfyui_face_timeout_seconds == 100
    assert policy.openrouter_base_url == "https://router.example"
    assert policy.openrouter_timeout_seconds == 300
    assert policy.prompt_improve_model == "provider/model"
    assert policy.prompt_improve_timeout_seconds == 3
    assert policy.cbr_daily_xml_url == " cbr-url "
    assert policy.usd_rub_fallback_url == " fallback-url "


def test_provider_endpoint_policy_preserves_face_timeout_floor_order() -> None:
    policy = load_provider_endpoint_policy(
        {
            "COMFYUI_TIMEOUT_SECONDS": "50",
            "COMFYUI_FACE_TIMEOUT_SECONDS": "10",
        }
    )

    assert policy.comfyui_timeout_seconds == 50
    assert policy.comfyui_face_timeout_seconds == 60


def test_provider_endpoint_policy_rejects_invalid_integer_like_legacy_main() -> None:
    try:
        load_provider_endpoint_policy({"OPENROUTER_TIMEOUT_SECONDS": "invalid"})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid numeric provider configuration must fail fast")


def test_runtime_environment_policy_defaults_and_production_markers() -> None:
    policy = load_runtime_environment_policy({})

    assert policy.app_env == "development"
    assert policy.environment_name == ""
    assert policy.mode_name == ""
    assert policy.production_like is False
    assert is_production_like_environment(" Development ", " PROD ", "") is True
    assert is_production_like_environment("", "", "LiVe") is True
    assert is_production_like_environment("production-like", "", "") is False


def test_bot_delivery_policy_defaults_match_legacy_main_contract() -> None:
    policy = load_bot_delivery_policy({})

    assert policy.telegram_updates_mode == "disabled"
    assert policy.telegram_polling_enabled is True
    assert policy.max_polling_enabled is True
    assert policy.max_updates_mode == "disabled"


def test_bot_delivery_policy_normalizes_modes_and_polling_flags() -> None:
    policy = load_bot_delivery_policy(
        {
            "BOT_UPDATES_MODE": " WEBHOOK ",
            "TELEGRAM_POLLING_ENABLED": " off ",
            "MAX_POLLING_ENABLED": " YES ",
            "MAX_UPDATES_MODE": " POLLING ",
        }
    )

    assert policy.telegram_updates_mode == "webhook"
    assert policy.telegram_polling_enabled is False
    assert policy.max_polling_enabled is True
    assert policy.max_updates_mode == "polling"


def test_bot_delivery_policy_preserves_legacy_fallback_order() -> None:
    fallback = load_bot_delivery_policy({"BOT_MODE": " Polling "})
    explicit_empty = load_bot_delivery_policy(
        {
            "BOT_UPDATES_MODE": "",
            "BOT_MODE": "webhook",
            "MAX_UPDATES_MODE": "invalid",
        }
    )
    invalid_max = load_bot_delivery_policy(
        {
            "BOT_UPDATES_MODE": "webhook",
            "MAX_UPDATES_MODE": "invalid",
        }
    )

    assert fallback.telegram_updates_mode == "polling"
    assert fallback.max_updates_mode == "polling"
    assert explicit_empty.telegram_updates_mode == "disabled"
    assert explicit_empty.max_updates_mode == "disabled"
    assert invalid_max.max_updates_mode == "webhook"
