from __future__ import annotations

import os
from pathlib import Path

from backend.app.config import (
    DEFAULT_CORS_ALLOWED_ORIGINS,
    env_bool,
    load_http_security_policy,
    load_local_env,
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
