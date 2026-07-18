from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from backend.app.config import (
    DEFAULT_CORS_ALLOWED_ORIGINS,
    DEFAULT_TRUSTED_HOSTS,
    env_bool,
    is_production_like_environment,
    load_bot_delivery_policy,
    load_http_security_policy,
    load_local_env,
    load_media_processing_policy,
    load_provider_endpoint_policy,
    load_runtime_environment_policy,
    load_storage_path_policy,
    production_configuration_errors,
    sqlite_path_from_database_url,
    validate_production_configuration,
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
    assert policy.trusted_hosts == DEFAULT_TRUSTED_HOSTS


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
            "TRUSTED_HOSTS": " one.example, ,two.example ",
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
    assert policy.trusted_hosts == ("one.example", "two.example")


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


def test_media_processing_policy_defaults_match_legacy_main_contract() -> None:
    policy = load_media_processing_policy({})

    assert policy.comfyui_input_max_side == 1536
    assert policy.comfyui_face_input_max_side == 1024
    assert policy.comfyui_face_source_megapixels == 0.35
    assert policy.gallery_image_max_side == 2048
    assert policy.gallery_image_webp_quality == 90
    assert policy.gallery_full_quality_count == 10
    assert policy.gallery_archive_max_side == 1536
    assert policy.gallery_archive_webp_quality == 86
    assert policy.source_thumb_max_side == 384
    assert policy.source_thumb_webp_quality == 76


def test_media_processing_policy_preserves_legacy_bounds() -> None:
    policy = load_media_processing_policy(
        {
            "COMFYUI_INPUT_MAX_SIDE": "1",
            "COMFYUI_FACE_INPUT_MAX_SIDE": "9999",
            "COMFYUI_FACE_SOURCE_MEGAPIXELS": "0.1",
            "GALLERY_IMAGE_MAX_SIDE": "99999",
            "GALLERY_IMAGE_WEBP_QUALITY": "1",
            "GALLERY_FULL_QUALITY_COUNT": "0",
            "GALLERY_ARCHIVE_MAX_SIDE": "99999",
            "GALLERY_ARCHIVE_WEBP_QUALITY": "999",
            "SOURCE_THUMB_MAX_SIDE": "9999",
            "SOURCE_THUMB_WEBP_QUALITY": "1",
        }
    )

    assert policy.comfyui_input_max_side == 512
    assert policy.comfyui_face_input_max_side == 512
    assert policy.comfyui_face_source_megapixels == 0.15
    assert policy.gallery_image_max_side == 4096
    assert policy.gallery_image_webp_quality == 70
    assert policy.gallery_full_quality_count == 1
    assert policy.gallery_archive_max_side == 4096
    assert policy.gallery_archive_webp_quality == 92
    assert policy.source_thumb_max_side == 768
    assert policy.source_thumb_webp_quality == 55


def test_media_processing_policy_preserves_dependent_limit_order() -> None:
    policy = load_media_processing_policy(
        {
            "COMFYUI_INPUT_MAX_SIDE": "2048",
            "COMFYUI_FACE_INPUT_MAX_SIDE": "4096",
            "COMFYUI_FACE_SOURCE_MEGAPIXELS": "2.0",
            "GALLERY_IMAGE_MAX_SIDE": "100",
            "GALLERY_ARCHIVE_MAX_SIDE": "1",
        }
    )

    assert policy.comfyui_face_input_max_side == 2048
    assert policy.comfyui_face_source_megapixels == 1.0
    assert policy.gallery_image_max_side == 1024
    assert policy.gallery_archive_max_side == 768


def test_media_processing_policy_rejects_invalid_numbers_like_legacy_main() -> None:
    invalid_environments = (
        {"GALLERY_IMAGE_MAX_SIDE": "invalid"},
        {"COMFYUI_FACE_SOURCE_MEGAPIXELS": "invalid"},
    )
    for environment in invalid_environments:
        try:
            load_media_processing_policy(environment)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid numeric media configuration must fail fast")


def test_storage_path_policy_defaults_without_creating_directories(tmp_path: Path) -> None:
    root = tmp_path / "backend"
    policy = load_storage_path_policy(root, {})

    assert policy.media_dir == (root / "media").resolve()
    assert policy.avatar_dir == (root / "media" / "avatars").resolve()
    assert policy.database_path == root / "onenode.sqlite3"
    assert not root.exists()


def test_storage_path_policy_preserves_expansion_and_database_url_parsing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "backend"
    media_value = tmp_path / "custom" / ".." / "media"
    policy = load_storage_path_policy(
        root,
        {
            "MEDIA_DIR": str(media_value),
            "DATABASE_URL": "sqlite:///C:/data/app.sqlite3",
        },
    )

    assert policy.media_dir == media_value.resolve()
    assert policy.avatar_dir == media_value.resolve() / "avatars"
    assert policy.database_path == Path("C:/data/app.sqlite3")


def test_storage_path_policy_preserves_empty_media_and_relative_database_semantics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    policy = load_storage_path_policy(
        tmp_path / "backend",
        {
            "MEDIA_DIR": "",
            "DATABASE_URL": "sqlite:relative.sqlite3",
        },
    )

    assert policy.media_dir == tmp_path.resolve()
    assert policy.avatar_dir == tmp_path.resolve() / "avatars"
    assert policy.database_path == Path("relative.sqlite3")


def _valid_production_policies(tmp_path: Path):
    environment = {
        "APP_ENV": "production",
        "TRUSTED_COOKIE_SECURE": "true",
        "TRUSTED_COOKIE_SAMESITE": "none",
        "CORS_ALLOWED_ORIGINS": "https://izo.alikinas.ru,http://127.0.0.1:5173",
        "MEDIA_DIR": str(tmp_path / "media"),
        "DATABASE_URL": str(tmp_path / "onenode.sqlite3"),
    }
    runtime = load_runtime_environment_policy(environment)
    return (
        runtime,
        load_http_security_policy(environment, app_env=runtime.app_env),
        load_provider_endpoint_policy(environment),
        load_storage_path_policy(tmp_path, environment),
    )


def test_production_configuration_accepts_current_safe_contract(tmp_path: Path) -> None:
    runtime, http_security, providers, storage = _valid_production_policies(tmp_path)

    assert production_configuration_errors(
        runtime=runtime,
        http_security=http_security,
        providers=providers,
        storage=storage,
    ) == ()
    validate_production_configuration(
        runtime=runtime,
        http_security=http_security,
        providers=providers,
        storage=storage,
    )


def test_production_configuration_does_not_block_development(tmp_path: Path) -> None:
    runtime, http_security, providers, storage = _valid_production_policies(tmp_path)

    assert production_configuration_errors(
        runtime=replace(runtime, app_env="development"),
        http_security=replace(
            http_security,
            cookie_secure=False,
            cors_allowed_origins=("*",),
        ),
        providers=replace(
            providers,
            comfyui_mock_fallback=True,
            openrouter_base_url="http://external.example",
        ),
        storage=replace(storage, database_path=Path("relative.sqlite3")),
    ) == ()


def test_production_configuration_reports_stable_error_codes(tmp_path: Path) -> None:
    runtime, http_security, providers, storage = _valid_production_policies(tmp_path)
    errors = production_configuration_errors(
        runtime=replace(runtime, app_env="development", environment_name="prod"),
        http_security=replace(
            http_security,
            cookie_secure=False,
            cookie_samesite="invalid",
            cors_allowed_origins=("*", "not-an-origin"),
        ),
        providers=replace(
            providers,
            comfyui_mock_fallback=True,
            comfyui_base_url="http://external.example",
            openrouter_base_url="http://external.example",
            prompt_improve_model=" ",
            cbr_daily_xml_url="not-a-url",
            usd_rub_fallback_url="ftp://external.example/rates",
        ),
        storage=replace(
            storage,
            media_dir=Path("relative-media"),
            database_path=Path("relative.sqlite3"),
        ),
    )

    assert errors == (
        "APP_ENV_MUST_BE_PRODUCTION",
        "COOKIE_SECURE_REQUIRED",
        "COOKIE_SAMESITE_INVALID",
        "CORS_WILDCARD_FORBIDDEN",
        "CORS_ORIGIN_INVALID_1",
        "COMFYUI_MOCK_FALLBACK_FORBIDDEN",
        "COMFYUI_URL_INSECURE",
        "OPENROUTER_URL_INSECURE",
        "PROMPT_MODEL_REQUIRED",
        "CBR_URL_INSECURE",
        "USD_RUB_FALLBACK_URL_INSECURE",
        "MEDIA_PATH_MUST_BE_ABSOLUTE",
        "DATABASE_PATH_MUST_BE_ABSOLUTE",
    )


def test_production_configuration_exception_contains_codes_not_values(tmp_path: Path) -> None:
    runtime, http_security, providers, storage = _valid_production_policies(tmp_path)
    unsafe_url = "http://secret-provider.example/private-path"

    try:
        validate_production_configuration(
            runtime=runtime,
            http_security=http_security,
            providers=replace(providers, openrouter_base_url=unsafe_url),
            storage=storage,
        )
    except RuntimeError as exc:
        message = str(exc)
        assert "OPENROUTER_URL_INSECURE" in message
        assert unsafe_url not in message
    else:
        raise AssertionError("unsafe production configuration must block startup")


def test_production_configuration_rejects_malformed_ports(tmp_path: Path) -> None:
    runtime, http_security, providers, storage = _valid_production_policies(tmp_path)
    errors = production_configuration_errors(
        runtime=runtime,
        http_security=replace(
            http_security,
            cors_allowed_origins=("https://izo.alikinas.ru:not-a-port",),
        ),
        providers=replace(
            providers,
            openrouter_base_url="https://openrouter.ai:not-a-port/api/v1",
        ),
        storage=storage,
    )

    assert errors == (
        "CORS_ORIGIN_INVALID_0",
        "OPENROUTER_URL_INSECURE",
    )
