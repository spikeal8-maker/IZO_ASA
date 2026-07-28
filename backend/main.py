from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import mimetypes
import os
import platform
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import hmac
import hashlib
from html import escape as html_escape
from urllib.parse import parse_qs, quote

import httpx
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, ConfigDict, Field

try:
    from .app.integrations.smtp import SmtpConfig, SmtpError, SmtpMessage, send_smtp_email, verify_smtp_connection
except ImportError:  # Direct `python backend/main.py` execution.
    from app.integrations.smtp import SmtpConfig, SmtpError, SmtpMessage, send_smtp_email, verify_smtp_connection
try:
    from .app.integrations.unisender import (
        UniSenderError,
        UniSenderMessage,
        create_unisender_list,
        get_unisender_lists,
        send_unisender_email,
    )
    from .app.integrations import unisender as unisender_service
except ImportError:  # Direct `python backend/main.py` execution.
    from app.integrations.unisender import (
        UniSenderError,
        UniSenderMessage,
        create_unisender_list,
        get_unisender_lists,
        send_unisender_email,
    )
    from app.integrations import unisender as unisender_service
try:
    from .app.integrations.yookassa import YooKassaError, check_yookassa_connection, create_yookassa_payment, fetch_yookassa_payment
except ImportError:  # Direct `python backend/main.py` execution.
    from app.integrations.yookassa import YooKassaError, check_yookassa_connection, create_yookassa_payment, fetch_yookassa_payment
try:
    from .app.billing import (
        PaymentCreateCommand,
        PaymentProviderError,
        PaymentReceipt,
        PaymentReceiptItem,
        SimulatedPaymentProvider,
        build_yookassa_receipt,
        claim_pending_messages as claim_payment_notifications,
        enqueue_payment_notification,
        ensure_outbox_schema,
        mark_retry as mark_payment_notification_retry,
        mark_sent as mark_payment_notification_sent,
    )
except ImportError:  # Direct `python backend/main.py` execution.
    from app.billing import (
        PaymentCreateCommand,
        PaymentProviderError,
        PaymentReceipt,
        PaymentReceiptItem,
        SimulatedPaymentProvider,
        build_yookassa_receipt,
        claim_pending_messages as claim_payment_notifications,
        enqueue_payment_notification,
        ensure_outbox_schema,
        mark_retry as mark_payment_notification_retry,
        mark_sent as mark_payment_notification_sent,
    )

try:
    from .resolution_policy import (
        IMAGE_RESOLUTIONS,
        CONFIG_UI_RESOLUTION_IDS,
        RESOLUTION_BY_ID,
        normalize_resolution_ids,
        resolution_id_for_size,
        supported_resolution_ids_from_capability,
    )
except ImportError:  # Direct `python backend/main.py` execution.
    from resolution_policy import (
        IMAGE_RESOLUTIONS,
        CONFIG_UI_RESOLUTION_IDS,
        RESOLUTION_BY_ID,
        normalize_resolution_ids,
        resolution_id_for_size,
        supported_resolution_ids_from_capability,
    )

try:
    from .app.services.tariff_lifecycle import (
        TERM_MONTHS,
        add_calendar_months,
        build_offer,
        normalize_term_settings,
        package_code as tariff_package_code,
        parse_package_code as parse_tariff_package_code,
        prorated_monthly_tokens,
    )
except ImportError:  # Direct `python backend/main.py` execution.
    from app.services.tariff_lifecycle import (
        TERM_MONTHS,
        add_calendar_months,
        build_offer,
        normalize_term_settings,
        package_code as tariff_package_code,
        parse_package_code as parse_tariff_package_code,
        prorated_monthly_tokens,
    )

try:
    from .app.config import (
        env_bool,
        is_production_like_environment,
        load_bot_delivery_policy,
        load_http_security_policy,
        load_local_env,
        load_media_processing_policy,
        load_provider_endpoint_policy,
        load_runtime_environment_policy,
        load_storage_path_policy,
        validate_production_configuration as validate_config_production_configuration,
    )

except ImportError:  # Direct `python backend/main.py` execution.
    from app.config import (
        env_bool,
        is_production_like_environment,
        load_bot_delivery_policy,
        load_http_security_policy,
        load_local_env,
        load_media_processing_policy,
        load_provider_endpoint_policy,
        load_runtime_environment_policy,
        load_storage_path_policy,
        validate_production_configuration as validate_config_production_configuration,
    )

try:
    from .app.security.bot_login import BotLoginAccessError, BotLoginRateLimits, BotLoginRuntime, bot_login_approval_retry_result, create_bot_login_challenge as security_create_bot_login_challenge, pending_bot_login_challenges_count
    from .app.security.http_requests import AvatarImageError, compress_allowlisted_avatar
    from .app.security.http_middleware import install_http_security_middleware
except ImportError:  # Direct `python backend/main.py` execution.
    from app.security.bot_login import BotLoginAccessError, BotLoginRateLimits, BotLoginRuntime, bot_login_approval_retry_result, create_bot_login_challenge as security_create_bot_login_challenge, pending_bot_login_challenges_count
    from app.security.http_requests import AvatarImageError, compress_allowlisted_avatar
    from app.security.http_middleware import install_http_security_middleware

try:
    from .app.release_identity import (
        ReleaseIdentity,
        assert_release_schema_compatible,
        load_runtime_release_identity,
    )
except ImportError:  # Direct `python backend/main.py` execution.
    from app.release_identity import (
        ReleaseIdentity,
        assert_release_schema_compatible,
        load_runtime_release_identity,
    )

try:
    from .app.integrations import (
        ComfyUIHistoryClient as IntegrationComfyUIHistoryClient,
        build_max_http_verify,
        build_openrouter_image_request_metadata,
        build_openrouter_image_request_body,
        build_openrouter_image_request_plan,
        comfyui_flux_klein_available as integration_comfyui_available,
        extract_openrouter_generation_cost,
        extract_openrouter_error_payload,
        fetch_comfyui_image_bytes as integration_fetch_comfyui_image_bytes,
        fetch_comfyui_models as integration_fetch_comfyui_models,
        fetch_comfyui_node_names as integration_fetch_comfyui_node_names,
        fetch_comfyui_workflow as integration_fetch_comfyui_workflow,
        fetch_flux_bgremoval_models as integration_fetch_flux_bgremoval_models,
        fetch_flux_klein_config as integration_fetch_flux_klein_config,
        fetch_flux_lora_triggers as integration_fetch_flux_lora_triggers,
        fetch_ollama_models_status,
        fetch_openrouter_image_model_documents,
        fetch_openrouter_key_details,
        fetch_openrouter_audio_input_models,
        fetch_openrouter_text_models,
        fetch_openrouter_video_models,
        poll_openrouter_video,
        format_openrouter_public_error,
        free_comfyui_memory as integration_free_comfyui_memory,
        is_openrouter_size_error,
        image_edit_influence_instruction,
        interrupt_comfyui as integration_interrupt_comfyui,
        load_openrouter_response_image,
        normalize_openrouter_endpoint_capability,
        normalize_openrouter_image_response_metadata,
        normalize_openrouter_model_capability,
        normalize_openrouter_video_config,
        normalize_max_tls_trust_store,
        openrouter_descriptor_values,
        openrouter_error_message,
        openrouter_ratio_size,
        request_ollama_chat_message,
        request_max_api,
        request_max_bot_me,
        probe_max_bot,
        probe_telegram_bot,
        request_openrouter_chat_completion,
        request_openrouter_image,
        submit_openrouter_video,
        requested_orientation,
        resolve_openrouter_image_model,
        resolve_openrouter_reference_value,
        select_openrouter_first_image,
        submit_comfyui_workflow as integration_submit_comfyui_workflow,
        TelegramApiError,
        TelegramConfigurationError,
        request_telegram_bot_api,
        telegram_file_url,
        upload_comfyui_image as integration_upload_comfyui_image,
    )

except ImportError:  # Direct `python backend/main.py` execution.
    from app.integrations import (
        ComfyUIHistoryClient as IntegrationComfyUIHistoryClient,
        build_max_http_verify,
        build_openrouter_image_request_metadata,
        build_openrouter_image_request_body,
        build_openrouter_image_request_plan,
        comfyui_flux_klein_available as integration_comfyui_available,
        extract_openrouter_generation_cost,
        extract_openrouter_error_payload,
        fetch_comfyui_image_bytes as integration_fetch_comfyui_image_bytes,
        fetch_comfyui_models as integration_fetch_comfyui_models,
        fetch_comfyui_node_names as integration_fetch_comfyui_node_names,
        fetch_comfyui_workflow as integration_fetch_comfyui_workflow,
        fetch_flux_bgremoval_models as integration_fetch_flux_bgremoval_models,
        fetch_flux_klein_config as integration_fetch_flux_klein_config,
        fetch_flux_lora_triggers as integration_fetch_flux_lora_triggers,
        fetch_ollama_models_status,
        fetch_openrouter_image_model_documents,
        fetch_openrouter_key_details,
        fetch_openrouter_audio_input_models,
        fetch_openrouter_text_models,
        fetch_openrouter_video_models,
        poll_openrouter_video,
        format_openrouter_public_error,
        free_comfyui_memory as integration_free_comfyui_memory,
        is_openrouter_size_error,
        image_edit_influence_instruction,
        interrupt_comfyui as integration_interrupt_comfyui,
        load_openrouter_response_image,
        normalize_openrouter_endpoint_capability,
        normalize_openrouter_image_response_metadata,
        normalize_openrouter_model_capability,
        normalize_openrouter_video_config,
        normalize_max_tls_trust_store,
        openrouter_descriptor_values,
        openrouter_error_message,
        openrouter_ratio_size,
        request_ollama_chat_message,
        request_max_api,
        request_max_bot_me,
        probe_max_bot,
        probe_telegram_bot,
        request_openrouter_chat_completion,
        request_openrouter_image,
        submit_openrouter_video,
        requested_orientation,
        resolve_openrouter_image_model,
        resolve_openrouter_reference_value,
        select_openrouter_first_image,
        submit_comfyui_workflow as integration_submit_comfyui_workflow,
        TelegramApiError,
        TelegramConfigurationError,
        request_telegram_bot_api,
        telegram_file_url,
        upload_comfyui_image as integration_upload_comfyui_image,
    )

try:
    from .app.integrations.qwen_asr import (
        DEFAULT_QWEN_ASR_BASE_URL,
        DEFAULT_QWEN_ASR_MODEL,
        fetch_qwen_asr_status,
        request_qwen_asr_transcription,
    )
except ImportError:  # Direct `python backend/main.py` execution.
    from app.integrations.qwen_asr import (
        DEFAULT_QWEN_ASR_BASE_URL,
        DEFAULT_QWEN_ASR_MODEL,
        fetch_qwen_asr_status,
        request_qwen_asr_transcription,
    )

try:
    from .app.services import (
        ComfyUIResult,
        MaxUpdateRuntime,
        TelegramUpdateRuntime,
        comfyui_results,
        comfyui_inputs,
        comfyui_watchdog,
        comfyui_workflows,
        generation_jobs,
        generation_recovery,
        generation_results,
        generation_worker,
        generation_queue,
        gallery_policy,
        gallery_eviction,
        gallery_query,
        gallery_presentation,
        gallery_items,
        ltx_video,
        video_storage,
        video_pricing,
        video_presentation,
        video_download,
        feed_presentation,
        feed_sources,
        feed_downloads,
        feed_policy,
        extract_max_command,
        handle_max_update_with_runtime,
        handle_max_updates_with_runtime,
        handle_telegram_update_with_runtime,
        handle_telegram_updates_with_runtime,
        max_login_payload_from_update,
        max_message_payload,
        max_recipient_params,
        max_update_type,
        max_user_from_message,
        max_user_from_update,
        sanitized_payload_prefix,
        telegram_answer_payload,
        telegram_message_from_update,
        telegram_user_from_update,
    )
except ImportError:  # Direct `python backend/main.py` execution.
    from app.services import (
        ComfyUIResult,
        MaxUpdateRuntime,
        TelegramUpdateRuntime,
        comfyui_results,
        comfyui_inputs,
        comfyui_watchdog,
        comfyui_workflows,
        generation_jobs,
        generation_recovery,
        generation_results,
        generation_worker,
        generation_queue,
        gallery_policy,
        gallery_eviction,
        gallery_query,
        gallery_presentation,
        gallery_items,
        ltx_video,
        video_storage,
        video_pricing,
        video_presentation,
        video_download,
        feed_presentation,
        feed_sources,
        feed_downloads,
        feed_policy,
        extract_max_command,
        handle_max_update_with_runtime,
        handle_max_updates_with_runtime,
        handle_telegram_update_with_runtime,
        handle_telegram_updates_with_runtime,
        max_login_payload_from_update,
        max_message_payload,
        max_recipient_params,
        max_update_type,
        max_user_from_message,
        max_user_from_update,
        sanitized_payload_prefix,
        telegram_answer_payload,
        telegram_message_from_update,
        telegram_user_from_update,
    )

try:
    from .app.services.platform_status import (
        mini_app_public_url,
        public_bots_status_payload,
        public_platforms_payload,
    )
    from .app.services.polling_health import (
        PollingHealthRegistry,
        is_auth_polling_error,
        polling_retry_after,
    )
    from .app.services.bot_workers import (
        BotRuntime,
        BotRuntimeDependencies,
        ProviderConfigSnapshot,
        create_bot_runtime,
    )
    from .app.lifespan.worker_registry import start_bot_workers, stop_bot_workers
    from .app.api.routers.bots_admin import (
        BotAdminConfigOps,
        BotAdminDependencies,
        BotAdminInfrastructure,
        BotAdminProviderOps,
        BotAdminSecretOps,
        create_bots_admin_router,
    )
    from .app.api.routers.bots_public import (
        BotPublicConfig,
        BotPublicDependencies,
        BotPublicMessaging,
        BotPublicTransport,
        create_bots_public_router,
    )
    from .app.api.routers.admin_operations import AdminOperationsDependencies, create_admin_operations_router
except ImportError:  # Direct `python backend/main.py` execution.
    from app.services.platform_status import (
        mini_app_public_url,
        public_bots_status_payload,
        public_platforms_payload,
    )
    from app.services.polling_health import (
        PollingHealthRegistry,
        is_auth_polling_error,
        polling_retry_after,
    )
    from app.services.bot_workers import (
        BotRuntime,
        BotRuntimeDependencies,
        ProviderConfigSnapshot,
        create_bot_runtime,
    )
    from app.lifespan.worker_registry import start_bot_workers, stop_bot_workers
    from app.api.routers.bots_admin import (
        BotAdminConfigOps,
        BotAdminDependencies,
        BotAdminInfrastructure,
        BotAdminProviderOps,
        BotAdminSecretOps,
        create_bots_admin_router,
    )
    from app.api.routers.bots_public import (
        BotPublicConfig,
        BotPublicDependencies,
        BotPublicMessaging,
        BotPublicTransport,
        create_bots_public_router,
    )
    from app.api.routers.admin_operations import AdminOperationsDependencies, create_admin_operations_router

try:
    from .app.services.bot_admin import (
        DEFAULT_BOT_INTEGRATIONS,
        normalize_bot_integrations,
        safe_bot_error,
        webhook_url as configured_bot_webhook_url,
    )
except ImportError:  # Direct `python backend/main.py` execution.
    from app.services.bot_admin import (
        DEFAULT_BOT_INTEGRATIONS,
        normalize_bot_integrations,
        safe_bot_error,
        webhook_url as configured_bot_webhook_url,
    )

try:
    from .app.database import (
        ADMIN_NOTIFICATION_DELIVERY_MIGRATION, ADMIN_NOTIFICATIONS_MIGRATION,
        DbGuardError,
        LEGACY_BASELINE_MIGRATION,
        apply_admin_notification_delivery_migration, apply_admin_notifications_migration,
        backfill_identity_core,
        collect_sqlite_guard_status,
        database_size_mb,
        ensure_migration_ledger,
        finalize_legacy_schema_baseline,
        finalize_identity_schema_group,
        initialize_media_schema_group,
        mask_database_path,
        open_sqlite,
        parse_allowed_database_paths,
        prepare_core_schema_group,
        prepare_identity_schema_group,
        preflight_sqlite_database,
        safe_guard_payload,
        seed_core_defaults,
        seed_default_challenge,
    )

except ImportError:  # Direct `python backend/main.py` execution.
    from app.database import (
        ADMIN_NOTIFICATION_DELIVERY_MIGRATION, ADMIN_NOTIFICATIONS_MIGRATION,
        DbGuardError,
        LEGACY_BASELINE_MIGRATION,
        apply_admin_notification_delivery_migration, apply_admin_notifications_migration,
        backfill_identity_core,
        collect_sqlite_guard_status,
        database_size_mb,
        ensure_migration_ledger,
        finalize_legacy_schema_baseline,
        finalize_identity_schema_group,
        initialize_media_schema_group,
        mask_database_path,
        open_sqlite,
        parse_allowed_database_paths,
        prepare_core_schema_group,
        prepare_identity_schema_group,
        preflight_sqlite_database,
        safe_guard_payload,
        seed_core_defaults,
        seed_default_challenge,
    )

try:
    from .app.services.admin_notification_delivery import AdminNotificationDeliveryWorker, build_admin_delivery_transports
    from .app.services.social_delivery import SocialDeliveryWorker, build_max_social_sender, build_social_deletion_sender, build_telegram_social_sender, build_vk_social_sender, build_vk_story_sender, enqueue_social_deletions
    from .app.services.admin_notifications import enqueue_configured_social_deliveries
    from .app.integrations.social_providers import probe_social_provider
    from .app.integrations.vk_client import request_vk_api; from .app.integrations.social_media_uploads import publish_max_video, publish_vk_story, publish_vk_wall_image, publish_vk_wall_video, send_telegram_photo_url, send_telegram_video_url
except ImportError:  # Direct `python backend/main.py` execution.
    from app.services.admin_notification_delivery import AdminNotificationDeliveryWorker, build_admin_delivery_transports
    from app.services.social_delivery import SocialDeliveryWorker, build_max_social_sender, build_social_deletion_sender, build_telegram_social_sender, build_vk_social_sender, build_vk_story_sender, enqueue_social_deletions
    from app.services.admin_notifications import enqueue_configured_social_deliveries
    from app.integrations.social_providers import probe_social_provider
    from app.integrations.vk_client import request_vk_api
    from app.integrations.social_media_uploads import publish_max_video, publish_vk_story, publish_vk_wall_image, publish_vk_wall_video, send_telegram_photo_url, send_telegram_video_url

try:
    from .app.database.demo_feed import restore_demo_feed_bundle
except ImportError:  # Direct `python backend/main.py` execution.
    from app.database.demo_feed import restore_demo_feed_bundle

try:
    from .app.security import (
        DUMMY_PASSWORD_HASH as SECURITY_DUMMY_PASSWORD_HASH,
        DpapiSecretStore,
        PASSWORD_ALGORITHM as SECURITY_PASSWORD_ALGORITHM,
        PASSWORD_HASHER as SECURITY_PASSWORD_HASHER,
        PASSWORD_MAX_LENGTH as SECURITY_PASSWORD_MAX_LENGTH,
        PASSWORD_MIN_LENGTH as SECURITY_PASSWORD_MIN_LENGTH,
        EventRuntime,
        OtpAccessError,
        OtpRateLimits,
        OtpRuntime,
        PermissionAccessError,
        PermissionRuntime,
        SessionAccessError,
        SessionRuntime,
        SecretStoreError,
        WebhookPayloadError,
        build_max_subscription_payload,
        build_telegram_set_webhook_payload,
        assert_secret_store_outside_repository,
        create_session as security_create_session,
        cleanup_expired_otp_challenges as security_cleanup_expired_otp_challenges,
        enforce_email_otp_rate_limits as security_enforce_email_otp_rate_limits,
        default_secret_store_dir,
        generate_otp_code as security_generate_otp_code,
        generate_bot_login_token as security_generate_bot_login_token,
        generate_secure_token as security_generate_secure_token,
        hash_password as security_hash_password,
        hash_token as security_hash_token,
        hash_otp as security_hash_otp,
        password_hash_needs_rehash as security_password_hash_needs_rehash,
        migrate_sqlite_secret_to_store,
        parse_webhook_json_object,
        refresh_session as security_refresh_session,
        record_login_attempt as security_record_login_attempt,
        record_product_event as security_record_product_event,
        record_security_event as security_record_security_event,
        record_session_event as security_record_session_event,
        resolve_client_ip as security_resolve_client_ip,
        resolve_country_code as security_resolve_country_code,
        require_admin as security_require_admin,
        resolve_trusted_identity as security_resolve_trusted_identity,
        resolve_session as security_resolve_session,
        revoke_session as security_revoke_session,
        send_email_otp as security_send_email_otp,
        validate_email_otp_config as security_validate_email_otp_config,
        validate_password_policy as security_validate_password_policy,
        validate_session_crypto_config as security_validate_session_crypto_config,
        validate_max_webhook_secret,
        validate_telegram_webhook_secret,
        verify_password as security_verify_password,
        webhook_secret_matches,
        user_is_admin as security_user_is_admin,
    )
except ImportError:  # Direct `python backend/main.py` execution.
    from app.security import (
        DUMMY_PASSWORD_HASH as SECURITY_DUMMY_PASSWORD_HASH,
        DpapiSecretStore,
        PASSWORD_ALGORITHM as SECURITY_PASSWORD_ALGORITHM,
        PASSWORD_HASHER as SECURITY_PASSWORD_HASHER,
        PASSWORD_MAX_LENGTH as SECURITY_PASSWORD_MAX_LENGTH,
        PASSWORD_MIN_LENGTH as SECURITY_PASSWORD_MIN_LENGTH,
        EventRuntime,
        OtpAccessError,
        OtpRateLimits,
        OtpRuntime,
        PermissionAccessError,
        PermissionRuntime,
        SessionAccessError,
        SessionRuntime,
        SecretStoreError,
        WebhookPayloadError,
        build_max_subscription_payload,
        build_telegram_set_webhook_payload,
        assert_secret_store_outside_repository,
        create_session as security_create_session,
        cleanup_expired_otp_challenges as security_cleanup_expired_otp_challenges,
        enforce_email_otp_rate_limits as security_enforce_email_otp_rate_limits,
        default_secret_store_dir,
        generate_otp_code as security_generate_otp_code,
        generate_bot_login_token as security_generate_bot_login_token,
        generate_secure_token as security_generate_secure_token,
        hash_password as security_hash_password,
        hash_token as security_hash_token,
        hash_otp as security_hash_otp,
        password_hash_needs_rehash as security_password_hash_needs_rehash,
        migrate_sqlite_secret_to_store,
        parse_webhook_json_object,
        refresh_session as security_refresh_session,
        record_login_attempt as security_record_login_attempt,
        record_product_event as security_record_product_event,
        record_security_event as security_record_security_event,
        record_session_event as security_record_session_event,
        resolve_client_ip as security_resolve_client_ip,
        resolve_country_code as security_resolve_country_code,
        require_admin as security_require_admin,
        resolve_trusted_identity as security_resolve_trusted_identity,
        resolve_session as security_resolve_session,
        revoke_session as security_revoke_session,
        send_email_otp as security_send_email_otp,
        validate_email_otp_config as security_validate_email_otp_config,
        validate_password_policy as security_validate_password_policy,
        validate_session_crypto_config as security_validate_session_crypto_config,
        validate_max_webhook_secret,
        validate_telegram_webhook_secret,
        verify_password as security_verify_password,
        webhook_secret_matches,
        user_is_admin as security_user_is_admin,
    )

try:
    from .app.security.account_password import PasswordChangeRuntime, install_password_change_route, password_is_configured
except ImportError:  # Direct `python backend/main.py` execution.
    from app.security.account_password import PasswordChangeRuntime, install_password_change_route, password_is_configured

try:
    from .app.storage import (
        PrivateMediaAccessError,
        PrivateMediaRuntime,
        PublicMediaAccessError,
        PublicMediaRuntime,
        SourceCleanupRuntime,
        SourceAvailabilityRuntime,
        SourceRepairRuntime,
        SourcePersistenceRuntime,
        SourceRowRepairRuntime,
        SourceTreeRuntime,
        SourceThumbnailRuntime,
        VideoSourcePersistenceRuntime,
        StoragePathError,
        count_active_gallery_images as storage_count_active_gallery_images,
        select_gallery_eviction_candidates as storage_select_gallery_eviction_candidates,
        find_gallery_media_owner as storage_find_gallery_media_owner,
        local_media_path_from_url as storage_local_media_path_from_url,
        media_filename_from_url as storage_media_filename_from_url,
        public_media_url as storage_public_media_url,
        resolve_feed_media as storage_resolve_feed_media,
        resolve_private_media as storage_resolve_private_media,
        resolve_public_avatar as storage_resolve_public_avatar,
        reconcile_orphan_source_rows as storage_reconcile_orphan_source_rows,
        reconcile_source_availability as storage_reconcile_source_availability,
        repair_unavailable_sources_from_jobs as storage_repair_unavailable_sources_from_jobs,
        read_image_source_tree as storage_read_image_source_tree,
        repair_image_source_rows_from_job as storage_repair_image_source_rows_from_job,
        persist_image_source_rows as storage_persist_image_source_rows,
        save_source_thumbnail as storage_save_source_thumbnail,
        persist_video_sources as storage_persist_video_sources,
        video_generation_source_inputs as storage_video_generation_source_inputs,
        generation_source_inputs as storage_generation_source_inputs,
        source_role_label as storage_source_role_label,
        find_owned_active_image as storage_find_owned_active_image,
        MediaInputValidationError,
        MediaInputValidationRuntime,
        validate_owned_media_inputs as storage_validate_owned_media_inputs,
        startup_storage_maintenance_allowed,
        resolve_under_root as storage_resolve_under_root,
    )
except ImportError:  # Direct `python backend/main.py` execution.
    from app.storage import (
        PrivateMediaAccessError,
        PrivateMediaRuntime,
        PublicMediaAccessError,
        PublicMediaRuntime,
        SourceCleanupRuntime,
        SourceAvailabilityRuntime,
        SourceRepairRuntime,
        SourcePersistenceRuntime,
        SourceRowRepairRuntime,
        SourceTreeRuntime,
        SourceThumbnailRuntime,
        VideoSourcePersistenceRuntime,
        StoragePathError,
        count_active_gallery_images as storage_count_active_gallery_images,
        select_gallery_eviction_candidates as storage_select_gallery_eviction_candidates,
        find_gallery_media_owner as storage_find_gallery_media_owner,
        local_media_path_from_url as storage_local_media_path_from_url,
        media_filename_from_url as storage_media_filename_from_url,
        public_media_url as storage_public_media_url,
        resolve_feed_media as storage_resolve_feed_media,
        resolve_private_media as storage_resolve_private_media,
        resolve_public_avatar as storage_resolve_public_avatar,
        reconcile_orphan_source_rows as storage_reconcile_orphan_source_rows,
        reconcile_source_availability as storage_reconcile_source_availability,
        repair_unavailable_sources_from_jobs as storage_repair_unavailable_sources_from_jobs,
        read_image_source_tree as storage_read_image_source_tree,
        repair_image_source_rows_from_job as storage_repair_image_source_rows_from_job,
        persist_image_source_rows as storage_persist_image_source_rows,
        save_source_thumbnail as storage_save_source_thumbnail,
        persist_video_sources as storage_persist_video_sources,
        video_generation_source_inputs as storage_video_generation_source_inputs,
        generation_source_inputs as storage_generation_source_inputs,
        source_role_label as storage_source_role_label,
        find_owned_active_image as storage_find_owned_active_image,
        MediaInputValidationError,
        MediaInputValidationRuntime,
        validate_owned_media_inputs as storage_validate_owned_media_inputs,
        startup_storage_maintenance_allowed,
        resolve_under_root as storage_resolve_under_root,
    )


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
GALLERY_PAGE_FILE = STATIC_DIR / "gallery" / "index.html"
FEED_PAGE_FILE = STATIC_DIR / "feed" / "index.html"
FAVICON_FILE = next(
    (
        path
        for path in (
            ROOT.parent / "frontend" / "public" / "favicon.svg",
            ROOT.parent / "frontend" / "dist" / "favicon.svg",
        )
        if path.exists()
    ),
    None,
)
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
MEDIA_PROCESSING_POLICY = load_media_processing_policy()
COMFYUI_INPUT_MAX_SIDE = MEDIA_PROCESSING_POLICY.comfyui_input_max_side
COMFYUI_FACE_INPUT_MAX_SIDE = MEDIA_PROCESSING_POLICY.comfyui_face_input_max_side
COMFYUI_FACE_SOURCE_MEGAPIXELS = MEDIA_PROCESSING_POLICY.comfyui_face_source_megapixels
COMFYUI_INPUT_MIN_SIDE = 256
GALLERY_IMAGE_MAX_SIDE = MEDIA_PROCESSING_POLICY.gallery_image_max_side
GALLERY_IMAGE_WEBP_QUALITY = MEDIA_PROCESSING_POLICY.gallery_image_webp_quality
GALLERY_FULL_QUALITY_COUNT = MEDIA_PROCESSING_POLICY.gallery_full_quality_count
GALLERY_ARCHIVE_MAX_SIDE = MEDIA_PROCESSING_POLICY.gallery_archive_max_side
GALLERY_ARCHIVE_WEBP_QUALITY = MEDIA_PROCESSING_POLICY.gallery_archive_webp_quality
SOURCE_THUMB_MAX_SIDE = MEDIA_PROCESSING_POLICY.source_thumb_max_side
SOURCE_THUMB_WEBP_QUALITY = MEDIA_PROCESSING_POLICY.source_thumb_webp_quality


load_local_env(ROOT)
mimetypes.add_type("image/webp", ".webp")
STORAGE_PATH_POLICY = load_storage_path_policy(ROOT)
MEDIA = STORAGE_PATH_POLICY.media_dir
MEDIA.mkdir(parents=True, exist_ok=True)
AVATAR_DIR = STORAGE_PATH_POLICY.avatar_dir
AVATAR_DIR.mkdir(parents=True, exist_ok=True)

OPENROUTER_SECRET_NAME = "openrouter_api_key"
SMTP_SECRET_NAME = "smtp_password"
UNISENDER_SECRET_NAME = "unisender_api_key"
YOOKASSA_SECRET_NAME = "yookassa_secret_key"
TELEGRAM_BOT_SECRET_NAME = "telegram_bot_token"
TELEGRAM_WEBHOOK_SECRET_NAME = "telegram_webhook_secret"
MAX_BOT_SECRET_NAME = "max_bot_token"
MAX_WEBHOOK_SECRET_NAME = "max_webhook_secret"
OPENROUTER_SECRET_STORE_DIR = default_secret_store_dir()
assert_secret_store_outside_repository(OPENROUTER_SECRET_STORE_DIR, ROOT.parent)
OPENROUTER_SECRET_STORE = DpapiSecretStore(OPENROUTER_SECRET_STORE_DIR)


def initial_runtime_secret(name: str, env_name: str) -> str:
    from_environment = os.getenv(env_name, "").strip()
    if from_environment:
        return from_environment
    try:
        return OPENROUTER_SECRET_STORE.get(name)
    except SecretStoreError:
        return ""

# Identity Core session service (Phase 4 + 4.1). Keying material for token hashing
# comes from the environment when available. Only hashes are persisted — raw tokens
# never reach the database or logs.
RUNTIME_ENVIRONMENT_POLICY = load_runtime_environment_policy()
APP_ENV = RUNTIME_ENVIRONMENT_POLICY.app_env
ENV_NAME = RUNTIME_ENVIRONMENT_POLICY.environment_name
MODE_NAME = RUNTIME_ENVIRONMENT_POLICY.mode_name
RELEASE_IDENTITY: ReleaseIdentity = load_runtime_release_identity(
    environment=os.environ,
    repo_root=ROOT.parent,
    backend_root=ROOT,
    python_executable=Path(sys.executable),
    python_version=platform.python_version(),
)
APP_BUILD = RELEASE_IDENTITY.release_id
FRONTEND_BUILD_LABEL = RELEASE_IDENTITY.frontend_build_id


def is_production_like_env() -> bool:
    return is_production_like_environment(APP_ENV, ENV_NAME, MODE_NAME)


DB_PATH = STORAGE_PATH_POLICY.database_path

PROVIDER_ENDPOINT_POLICY = load_provider_endpoint_policy()
COMFYUI_BASE_URL = PROVIDER_ENDPOINT_POLICY.comfyui_base_url
COMFYUI_REQUIRED = PROVIDER_ENDPOINT_POLICY.comfyui_required
COMFYUI_MOCK_FALLBACK = PROVIDER_ENDPOINT_POLICY.comfyui_mock_fallback
COMFYUI_TIMEOUT_SECONDS = PROVIDER_ENDPOINT_POLICY.comfyui_timeout_seconds
COMFYUI_FACE_TIMEOUT_SECONDS = PROVIDER_ENDPOINT_POLICY.comfyui_face_timeout_seconds
COMFYUI_IMAGE_TIMEOUT_SECONDS = PROVIDER_ENDPOINT_POLICY.comfyui_image_timeout_seconds
COMFYUI_HISTORY_REQUEST_TIMEOUT_SECONDS = PROVIDER_ENDPOINT_POLICY.comfyui_history_request_timeout_seconds
COMFYUI_RECOVERY_WAIT_SECONDS = PROVIDER_ENDPOINT_POLICY.comfyui_recovery_wait_seconds
COMFYUI_WATCHDOG_REQUEST_PATH = comfyui_watchdog.default_restart_request_path()
COMFYUI_RECOVERY_GATE = comfyui_watchdog.RecoveryGate(COMFYUI_WATCHDOG_REQUEST_PATH, COMFYUI_RECOVERY_WAIT_SECONDS)
LOCAL_LTX_ENABLED = env_bool("LOCAL_LTX_ENABLED", False)
LOCAL_LTX_COMFYUI_BASE_URL = os.getenv("LOCAL_LTX_COMFYUI_BASE_URL", COMFYUI_BASE_URL).rstrip("/")
LOCAL_LTX_WORKFLOW_API_PATH = Path(
    os.getenv(
        "LOCAL_LTX_WORKFLOW_API_PATH",
        str(ROOT / "workflows" / "ltx23_t2v_api.json"),
    )
).expanduser()
OPENROUTER_BASE_URL = PROVIDER_ENDPOINT_POLICY.openrouter_base_url
OPENROUTER_TIMEOUT_SECONDS = PROVIDER_ENDPOINT_POLICY.openrouter_timeout_seconds
PROMPT_IMPROVE_MODEL = PROVIDER_ENDPOINT_POLICY.prompt_improve_model
PROMPT_IMPROVE_TIMEOUT_SECONDS = PROVIDER_ENDPOINT_POLICY.prompt_improve_timeout_seconds
CBR_DAILY_XML_URL = PROVIDER_ENDPOINT_POLICY.cbr_daily_xml_url
USD_RUB_FALLBACK_URL = PROVIDER_ENDPOINT_POLICY.usd_rub_fallback_url


BOT_DELIVERY_POLICY = load_bot_delivery_policy()
BOT_UPDATES_MODE = BOT_DELIVERY_POLICY.telegram_updates_mode
BOT_MODE = BOT_UPDATES_MODE
TELEGRAM_POLLING_ENABLED = BOT_DELIVERY_POLICY.telegram_polling_enabled
MAX_POLLING_ENABLED = BOT_DELIVERY_POLICY.max_polling_enabled
TELEGRAM_BOT_TOKEN = initial_runtime_secret(TELEGRAM_BOT_SECRET_NAME, "TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET = initial_runtime_secret(TELEGRAM_WEBHOOK_SECRET_NAME, "TELEGRAM_WEBHOOK_SECRET")
TELEGRAM_INIT_DATA_TTL_SECONDS = int(os.getenv("TELEGRAM_INIT_DATA_TTL_SECONDS", str(60 * 60 * 24)))
MAX_BOT_TOKEN = initial_runtime_secret(MAX_BOT_SECRET_NAME, "MAX_BOT_TOKEN")
MAX_WEB_APP_DATA_TTL_SECONDS = int(os.getenv("MAX_WEB_APP_DATA_TTL_SECONDS", str(60 * 60 * 24)))
MAX_UPDATES_MODE = BOT_DELIVERY_POLICY.max_updates_mode
MAX_API_BASE_URL = os.getenv("MAX_API_BASE_URL", "https://platform-api2.max.ru")
MAX_TLS_TRUST_STORE = normalize_max_tls_trust_store(os.getenv("MAX_TLS_TRUST_STORE", "system"))
MAX_HTTP_VERIFY = build_max_http_verify(MAX_TLS_TRUST_STORE)
MAX_WEBHOOK_URL = os.getenv("MAX_WEBHOOK_URL", "")
MAX_WEBHOOK_SECRET = initial_runtime_secret(MAX_WEBHOOK_SECRET_NAME, "MAX_WEBHOOK_SECRET")
# MAX deep-link cache and MAX polling diagnostics are worker-owned mutable
# state; they live on BOT_RUNTIME.max_deep_link_cache / .max_polling_diag
# (ARCH-BE-BOTS-001).
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
_HTTP_SECURITY_POLICY = load_http_security_policy(app_env=APP_ENV)
TRUSTED_SESSION_COOKIE_NAME = _HTTP_SECURITY_POLICY.session_cookie_name
TRUSTED_REFRESH_COOKIE_NAME = _HTTP_SECURITY_POLICY.refresh_cookie_name
TRUSTED_COOKIE_SECURE = _HTTP_SECURITY_POLICY.cookie_secure
TRUSTED_COOKIE_SAMESITE = _HTTP_SECURITY_POLICY.cookie_samesite
TRUSTED_COOKIE_DOMAIN = _HTTP_SECURITY_POLICY.cookie_domain
TRUSTED_COOKIE_PATH = _HTTP_SECURITY_POLICY.cookie_path
SESSION_COOKIE_NAME = TRUSTED_SESSION_COOKIE_NAME
BOT_LOGIN_CHALLENGE_COOKIE_NAME = _HTTP_SECURITY_POLICY.bot_login_challenge_cookie_name
BOT_LOGIN_CHALLENGE_TTL_SECONDS = _HTTP_SECURITY_POLICY.bot_login_challenge_ttl_seconds
BOT_LOGIN_REQUEST_WINDOW_SECONDS = max(60, int(os.getenv("BOT_LOGIN_REQUEST_WINDOW_SECONDS", "300")))
BOT_LOGIN_MAX_REQUESTS_PER_IP_WINDOW = max(1, int(os.getenv("BOT_LOGIN_MAX_REQUESTS_PER_IP_WINDOW", "10")))
BOT_LOGIN_MAX_ACTIVE_PER_IP_PROVIDER = max(1, int(os.getenv("BOT_LOGIN_MAX_ACTIVE_PER_IP_PROVIDER", "3")))
BOT_LOGIN_MAX_GLOBAL_PENDING = max(10, int(os.getenv("BOT_LOGIN_MAX_GLOBAL_PENDING", "1000")))
BOT_LOGIN_RETENTION_SECONDS = max(3600, int(os.getenv("BOT_LOGIN_RETENTION_SECONDS", "86400")))
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "")
TELEGRAM_BOT_DEEP_LINK_BASE = os.getenv("TELEGRAM_BOT_DEEP_LINK_BASE", "")
MAX_BOT_DEEP_LINK_BASE = os.getenv("MAX_BOT_DEEP_LINK_BASE", "")

# Phase 18/A7: Uvicorn preserves the direct socket peer. Application code accepts
# validated proxy metadata only when its explicit flag is enabled and that peer is
# loopback; see app/security/proxy_headers.py.
TRUST_PROXY_HEADERS = _HTTP_SECURITY_POLICY.trust_proxy_headers
TRUST_CLOUDFLARE_HEADERS = _HTTP_SECURITY_POLICY.trust_cloudflare_headers

# CORS/TrustedHost/body-limit/CSRF composition lives in
# app/security/http_middleware.py (AUTH-LEGACY-001B seam).
CORS_ALLOWED_ORIGINS = list(_HTTP_SECURITY_POLICY.cors_allowed_origins)
TRUSTED_HOSTS = list(_HTTP_SECURITY_POLICY.trusted_hosts)
REQUEST_BODY_MAX_BYTES = max(1024 * 1024, int(os.getenv("REQUEST_BODY_MAX_BYTES", str(128 * 1024 * 1024))))

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
install_http_security_middleware(
    app, policy=_HTTP_SECURITY_POLICY, request_body_max_bytes=REQUEST_BODY_MAX_BYTES
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if AVATAR_PRESET_DIR is not None:
    app.mount("/avatars", StaticFiles(directory=AVATAR_PRESET_DIR), name="avatars")


@app.get("/favicon.svg", include_in_schema=False)
async def favicon() -> FileResponse:
    if FAVICON_FILE is None:
        raise HTTPException(404, "Favicon is not installed.")
    return FileResponse(
        FAVICON_FILE,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


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
        headers={"Cache-Control": "no-store", "X-IZO-Release": RELEASE_IDENTITY.release_id},
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
        headers={"Cache-Control": "no-store", "X-IZO-Release": RELEASE_IDENTITY.release_id},
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
    width: int = Field(default=1024, ge=256, le=4096)
    height: int = Field(default=1024, ge=256, le=4096)
    resolutionId: str | None = None
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


class VideoGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["text_to_video", "image_to_video", "first_last_frame", "reference_to_video"] = "text_to_video"
    model: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=3000)
    duration: int = Field(ge=1, le=60)
    resolution: str = Field(min_length=2, max_length=20)
    aspectRatio: str = Field(default="16:9", min_length=3, max_length=12)
    generateAudio: bool = False
    firstFrame: str | None = Field(default=None, max_length=16_000_000)
    lastFrame: str | None = Field(default=None, max_length=16_000_000)
    references: list[str] = Field(default_factory=list, max_length=4)

    @property
    def provider(self) -> str:
        if self.model.startswith(ltx_video.LOCAL_LTX_MODEL_PREFIX):
            return "local_ltx"
        return "openrouter"


LOCAL_TEXT_TO_IMAGE_STEPS = 4


def normalize_generation_request(req: GenerateRequest) -> GenerateRequest:
    """Apply server-owned generation invariants before pricing and queueing."""
    if req.provider == "comfyui" and req.mode == "text_to_image" and req.steps != LOCAL_TEXT_TO_IMAGE_STEPS:
        return req.model_copy(update={"steps": LOCAL_TEXT_TO_IMAGE_STEPS})
    return req


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


class ImprovePromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=3000)
    mode: Literal[
        "text", "i2i", "edit", "sketch", "mask", "outpaint", "remove_bg",
        "text_to_video", "image_to_video", "first_last_frame", "reference_to_video",
    ] = "text"
    language: Literal["ru", "en"] = "ru"
    technicalPrompt: str = Field(default="", max_length=4000)


class ClientRuntimeErrorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=6, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    signature: str = Field(min_length=6, max_length=80, pattern=r"^[a-fA-F0-9]+$")
    region: Literal["root", "studio-form", "preview", "history", "gallery-picker", "global"]
    route: str = Field(min_length=1, max_length=160)
    mode: str = Field(default="default", max_length=48)
    release: str = Field(default="unknown", max_length=80)
    kind: str = Field(default="Error", max_length=80)


class SyntheticResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "error"]
    release: str = Field(default="unknown", max_length=80)
    checked_routes: list[str] = Field(default_factory=list, max_length=10)
    duration_ms: int = Field(ge=0, le=600_000)


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


class AdminDiscountV2Request(BaseModel):
    percent: int = Field(default=0, ge=0, le=90)
    reason: str = ""


class AdminPlanV2Request(BaseModel):
    plan: Literal["free", "mini", "plus", "pro", "business"]
    duration_days: int = Field(default=30, ge=1, le=3660)
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


class AdminMailConfigV2Request(BaseModel):
    host: str = Field(default="smtp.mail.ru", min_length=3, max_length=253)
    port: int = Field(default=465, ge=1, le=65535)
    username: str = Field(min_length=5, max_length=254)
    password: str | None = Field(default=None, min_length=8, max_length=512)
    sender_name: str = Field(default="ИЗО АСА", min_length=1, max_length=100)
    sender_email: str = Field(min_length=5, max_length=254)
    use_ssl: bool = True


class AdminMailVerifyV2Request(BaseModel):
    host: str = Field(default="smtp.mail.ru", min_length=3, max_length=253)
    port: int = Field(default=465, ge=1, le=65535)
    username: str = Field(min_length=5, max_length=254)
    password: str | None = Field(default=None, min_length=8, max_length=512)
    sender_name: str = Field(default="ИЗО АСА", min_length=1, max_length=100)
    sender_email: str = Field(min_length=5, max_length=254)
    use_ssl: bool = True
    save: bool = True


class AdminUniSenderVerifyV2Request(BaseModel):
    api_key: str | None = Field(default=None, min_length=8, max_length=512)
    sender_name: str = Field(default="ИЗО АСА", min_length=1, max_length=100)
    sender_email: str = Field(min_length=5, max_length=254)
    list_id: int | None = Field(default=None, ge=1)
    create_list_if_missing: bool = True


class AdminUniSenderListV2Request(BaseModel):
    title: str = Field(default="Пользователи ИЗО АСА", min_length=1, max_length=200)


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


class AdminYooKassaConfigV2Request(BaseModel):
    shop_id: str = Field(min_length=2, max_length=100)
    secret_key: str | None = Field(default=None, min_length=8, max_length=512)
    test_mode: bool = True
    receipt_vat_code: int | None = Field(default=None, ge=1, le=12)
    payment_subject: str = Field(default="service", min_length=2, max_length=40)


class BillingCheckoutV2Request(BaseModel):
    package_code: str = Field(min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=12, max_length=120)
    offer_accepted: bool = False
    receipt_contact: str | None = Field(default=None, max_length=200)


class BillingScheduleFreeV2Request(BaseModel):
    confirm: bool = True


class BillingSimulationV2Request(BaseModel):
    status: Literal["succeeded", "canceled"]
    reason: str = Field(min_length=3, max_length=500)


class AdminPaymentMaintenanceV2Request(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    reason: str = Field(min_length=3, max_length=500)


class AdminTokenPackageV2Request(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    price_amount: int = Field(ge=1, le=10_000_000)
    token_amount: int = Field(ge=1, le=1_000_000)
    is_active: bool = True


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


class SendImageRequest(BaseModel):
    platform: Literal["telegram", "max"]
    chatId: str | None = None
    userId: str | None = None


class FavoriteRequest(BaseModel):
    isFavorite: bool


class UseAsRequest(BaseModel):
    target: str


class FeedModerationRequest(BaseModel):
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=3, max_length=500)


class FeedEngagementEventRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=48)
    publication_id: str | None = Field(default=None, max_length=128)
    duration_ms: int | None = Field(default=None, ge=0, le=1_800_000)
    context: dict[str, Any] = Field(default_factory=dict)


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


class AdminConfigUiSwitchRequest(BaseModel):
    profileId: Literal["flux_klein_9b", "flux_klein_4b"]
    reason: str = Field(default="глобальное переключение Config UI", min_length=3, max_length=300)


class AdminSecretKeyRequest(BaseModel):
    key: str = Field(min_length=12, max_length=512)


class AdminOpenRouterTestRequest(BaseModel):
    model: str = "black-forest-labs/flux.2-klein-4b"
    prompt: str = "A small clean test image of a lime green cube on a white background."
    width: int = Field(default=1024, ge=512, le=1536)
    height: int = Field(default=1024, ge=512, le=1536)


class AdminAssistantTestRequest(BaseModel):
    provider: Literal["local", "api"]
    prompt: str = Field(default="девушка стоит у окна вечером", min_length=1, max_length=1000)
    mode: Literal["text", "i2i", "edit", "sketch", "mask", "outpaint", "remove_bg"] = "text"
    config: dict[str, Any] | None = None


rate_limits = {"hourly": 0, "daily": 0}
PROMO_REFERRAL_REWARD_TOKENS = 50
PLAN_ORDER = ("free", "mini", "plus", "pro", "business")
DEFAULT_TARIFFS: dict[str, dict[str, Any]] = {
    "free": {"title": "Free", "note": "Базовый доступ", "price_rub_month": 0, "daily_tokens": 10, "monthly_tokens": 0, "gallery_slots": 20, "quality_label": "SD", "model_defaults": {"fast": "server:local_flux_klein", "standard": "server:local_flux_klein", "max": "server:local_flux_klein"}, "queue_label": "Обычная", "pro_mode_enabled": 0, "allowed_resolutions": ["sq-sd", "v-sd", "h-sd", "p-sd"], "video_enabled": 0, "video_slots": 0},
    "mini": {"title": "Mini", "note": "Оптимальный старт", "price_rub_month": 490, "daily_tokens": 50, "monthly_tokens": 100, "gallery_slots": 80, "quality_label": "HD", "model_defaults": {"fast": "server:local_flux_klein", "standard": "server:local_flux_klein", "max": "server:local_flux_klein"}, "queue_label": "Обычная", "pro_mode_enabled": 0, "allowed_resolutions": [item["id"] for item in IMAGE_RESOLUTIONS if item["tier"] in {"sd", "hd"}], "video_enabled": 1, "video_slots": 1},
    "plus": {"title": "Plus", "note": "Больше возможностей", "price_rub_month": 990, "daily_tokens": 100, "monthly_tokens": 250, "gallery_slots": 200, "quality_label": "Full HD", "model_defaults": {"fast": "server:local_flux_klein", "standard": "black-forest-labs/flux.2-klein-4b", "max": "openai/gpt-image-1-mini"}, "queue_label": "Ускоренная", "pro_mode_enabled": 1, "allowed_resolutions": [item["id"] for item in IMAGE_RESOLUTIONS if item["tier"] != "four_k"], "video_enabled": 1, "video_slots": 5},
    "pro": {"title": "Pro", "note": "Видео и приоритет", "price_rub_month": 1990, "daily_tokens": 200, "monthly_tokens": 500, "gallery_slots": 500, "quality_label": "Full HD", "model_defaults": {"fast": "server:local_flux_klein", "standard": "black-forest-labs/flux.2-klein-4b", "max": "black-forest-labs/flux.2-pro"}, "queue_label": "Приоритетная", "pro_mode_enabled": 1, "allowed_resolutions": [item["id"] for item in IMAGE_RESOLUTIONS if item["tier"] != "four_k"], "video_enabled": 1, "video_slots": 10},
    "business": {"title": "Бизнес", "note": "Для команды и видео", "price_rub_month": 4990, "daily_tokens": 500, "monthly_tokens": 1200, "gallery_slots": 500, "quality_label": "4K", "model_defaults": {"fast": "server:local_flux_klein", "standard": "black-forest-labs/flux.2-pro", "max": "openai/gpt-image-1"}, "queue_label": "Бизнес", "pro_mode_enabled": 1, "allowed_resolutions": list(RESOLUTION_BY_ID), "video_enabled": 1, "video_slots": 25},
}
VIDEO_STORAGE_TARIFF_LIMITS = {"free": 0, "mini": 1, "plus": 5, "pro": 10, "business": 25}
VIDEO_STORAGE_TARIFF_MIGRATION_KEY = "video_storage_tariffs_v1"


@dataclass
class OpenRouterResult:
    image_path: Path
    thumbnail_path: Path
    response_id: str | None
    model: str
    usage: dict[str, Any]
    cost_usd: float | None
    width: int
    height: int
    raw: dict[str, Any]


jobs: dict[str, dict[str, Any]] = {}
images: dict[str, dict[str, Any]] = {}
queue: asyncio.Queue[str] = asyncio.Queue()
worker_started = False
# bot_polling_started / bot_polling_tasks are worker-owned mutable state on
# BOT_RUNTIME.polling_started / .polling_tasks (ARCH-BE-BOTS-001).


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
    return RELEASE_IDENTITY.git_sha


def mask_db_path(path: Path | None = None) -> str:
    return mask_database_path(path or DB_PATH)


def db_size_mb(path: Path | None = None) -> float:
    return database_size_mb(path or DB_PATH)


def allowed_db_paths() -> set[Path]:
    return parse_allowed_database_paths(os.getenv("DB_GUARD_ALLOWED_PATHS", ""))


def safe_db_guard_payload(status: dict[str, Any] | None = None) -> dict[str, Any]:
    return safe_guard_payload(status or DB_GUARD_STATUS)


def db_guard_fail(reason: str, *, migration_status: str = "fail") -> None:
    DB_GUARD_STATUS.update({"ok": False, "status": "fail", "reason": reason, "migration_status": migration_status})
    print(f"DB guard failed: {reason}")
    raise DbGuardError(reason)


def db_guard_preflight() -> None:
    try:
        preflight_sqlite_database(
            production_like=is_production_like_env(),
            database_url=os.getenv("DATABASE_URL") or "",
            path=DB_PATH,
            allowed_paths=allowed_db_paths(),
            min_size_mb=DB_GUARD_MIN_SIZE_MB,
        )
    except DbGuardError as exc:
        db_guard_fail(str(exc), migration_status="not_started")


def collect_db_guard_status() -> dict[str, Any]:
    return collect_sqlite_guard_status(
        path=DB_PATH,
        connection_factory=db,
        required_tables=DB_GUARD_REQUIRED_TABLES,
        required_columns=DB_GUARD_REQUIRED_COLUMNS,
        production_like=is_production_like_env(),
        min_users=DB_GUARD_MIN_USERS,
        min_active_admins=DB_GUARD_MIN_ACTIVE_ADMINS,
    )


def enforce_db_guard_after_migrations() -> None:
    status = collect_db_guard_status()
    DB_GUARD_STATUS.update(status)
    if is_production_like_env() and not status["ok"]:
        db_guard_fail(str(status.get("reason") or "DB guard failed after migrations."))


def db() -> sqlite3.Connection:
    return open_sqlite(DB_PATH)


def init_db() -> None:
    with db() as conn:
        ensure_migration_ledger(
            conn,
            supported_version=ADMIN_NOTIFICATION_DELIVERY_MIGRATION.version,
        )
        prepare_core_schema_group(conn)
        ensure_outbox_schema(conn)
        now = datetime.now(timezone.utc).isoformat()
        seed_core_defaults(conn, now=now)

        prepare_identity_schema_group(conn, now=now)

        initialize_media_schema_group(conn)
        migrate_video_storage_tariffs(conn, now=now)
        seed_default_challenge(conn, now=now)
        if is_production_like_env():
            report = restore_demo_feed_bundle(conn, MEDIA, apply=True)
            print(f"demo feed bundle: {report}")

        finalize_identity_schema_group(
            conn,
            now=now,
            ensure_public_user_code=ensure_public_user_code,
        )
        finalize_legacy_schema_baseline(conn, applied_at=now)
        apply_admin_notifications_migration(conn, applied_at=now)
        apply_admin_notification_delivery_migration(conn, applied_at=now)

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
    return security_generate_secure_token()


def generate_bot_login_token() -> str:
    """Short opaque token that fits Telegram callback_data; DB stores only hash."""
    return security_generate_bot_login_token()


def hash_token(raw_token: str) -> str:
    """Deterministic hash of a raw token. Raw tokens are never stored or logged."""
    return security_hash_token(raw_token, hmac_secret=SESSION_HMAC_SECRET)


def validate_session_crypto_config() -> None:
    """Refuse the unkeyed SHA-256 fallback in production.

    Development/test may run without SESSION_HMAC_SECRET (plain SHA-256). In
    production the keyed HMAC secret is mandatory; we fail loudly rather than
    silently weakening token hashing. The secret value is never included in the
    error message.
    """
    security_validate_session_crypto_config(app_env=APP_ENV, hmac_secret=SESSION_HMAC_SECRET)


def get_client_ip(request: Request | None) -> str | None:
    """Best-effort client IP for ANALYTICS only (never an auth decision).
    Trusts validated CF/XFF metadata only from a direct loopback proxy peer."""
    return security_resolve_client_ip(
        request,
        trust_cloudflare=TRUST_CLOUDFLARE_HEADERS,
        trust_forwarded=TRUST_PROXY_HEADERS,
    )


def _client_ip(request: Request | None) -> str | None:
    return get_client_ip(request)


def request_country_code(request: Request | None) -> str | None:
    """Best-effort country code for profile analytics from trusted CF headers only."""
    return security_resolve_country_code(request, trust_cloudflare=TRUST_CLOUDFLARE_HEADERS)


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


def _event_runtime() -> EventRuntime:
    return EventRuntime(connect=db, get_client_ip=_client_ip, hash_user_agent=_hash_user_agent)


def record_session_event(
    conn: sqlite3.Connection,
    session_id: str,
    internal_user_id: str,
    event_type: str,
    request: Request | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    security_record_session_event(
        _event_runtime(), conn, session_id, internal_user_id, event_type, request, metadata
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
    security_record_security_event(
        _event_runtime(),
        conn,
        event_type,
        severity,
        internal_user_id,
        session_id,
        request,
        details,
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
    security_record_product_event(
        _event_runtime(),
        event_name,
        internal_user_id,
        legacy_user_id,
        anonymous_id,
        installation_id,
        session_id,
        platform,
        device_type,
        request,
        properties,
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
    security_record_login_attempt(
        _event_runtime(),
        conn,
        provider,
        success,
        identifier,
        internal_user_id,
        failure_reason,
        platform,
        request,
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
    _initialize_intro_tariff_if_new(conn, legacy_user_id, now)
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
    _initialize_intro_tariff_if_new(conn, legacy_user_id, now)
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
    cache = BOT_RUNTIME.max_deep_link_cache
    explicit = MAX_BOT_DEEP_LINK_BASE.strip()
    if explicit:
        cache.update({
            "attempted": True,
            "base": explicit,
            "source": "env",
            "resolved": True,
            "api_status": None,
            "fields": [],
        })
        return explicit
    if not MAX_BOT_TOKEN:
        cache.update({
            "attempted": True,
            "base": None,
            "source": "failed",
            "resolved": False,
            "api_status": None,
            "fields": [],
        })
        return None
    if cache.get("attempted"):
        return cache.get("base")
    status: int | None = None
    fields: list[str] = []
    try:
        payload, status = request_max_bot_me(
            token=MAX_BOT_TOKEN,
            base_url=MAX_API_BASE_URL,
            verify=MAX_HTTP_VERIFY,
        )
        fields = sorted(set(_flatten_field_names(payload)))[:80]
        base = _max_base_from_me_payload(payload if isinstance(payload, dict) else {})
        if base:
            cache.update({
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
        typed_status = getattr(exc, "status_code", None)
        if isinstance(typed_status, int):
            status = typed_status
        print(f"MAX deep link base source=failed; MAX bot nickname resolved=false; MAX API /me status={status}; error={type(exc).__name__}")
        cache.update({
            "attempted": True,
            "base": None,
            "source": "failed",
            "resolved": False,
            "api_status": status,
            "fields": fields,
        })
        return None
    print(f"MAX deep link base source=failed; MAX bot nickname resolved=false; MAX API /me status={status}; fields={fields}")
    cache.update({
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


def approve_bot_login_challenge(
    provider: Literal["telegram", "max"],
    token: str,
    provider_user: dict[str, Any],
) -> bool:
    if not (provider_user_id := str(provider_user.get("id") or "")):
        return False
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM auth_login_challenges WHERE provider = ? AND token_hash = ?",
            (provider, hash_token(token)),
        ).fetchone()
        if (retry_result := bot_login_approval_retry_result(row, provider_user_id=provider_user_id, now=now)) is not None:
            return retry_result
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
    return security_generate_otp_code(length)


def hash_otp(code: str) -> str:
    return security_hash_otp(code, hmac_secret=SESSION_HMAC_SECRET)


# ---------------------------------------------------------------------------
# Password hashing (Phase 14.4). Argon2id only. Raw passwords and password
# hashes are NEVER logged. No endpoints in this phase — helpers + schema only.
# ---------------------------------------------------------------------------
PASSWORD_MIN_LENGTH = SECURITY_PASSWORD_MIN_LENGTH
PASSWORD_MAX_LENGTH = SECURITY_PASSWORD_MAX_LENGTH
PASSWORD_ALGORITHM = SECURITY_PASSWORD_ALGORITHM
_password_hasher = SECURITY_PASSWORD_HASHER
_DUMMY_PASSWORD_HASH = SECURITY_DUMMY_PASSWORD_HASH


validate_password_policy = security_validate_password_policy
hash_password_argon2 = security_hash_password
verify_password_argon2 = security_verify_password
password_hash_needs_rehash = security_password_hash_needs_rehash


def email_provider_configured() -> bool:
    # EMAIL_PROVIDER remains a development-test switch. Production readiness
    # requires a verified provider, not only an environment label.
    return unisender_ready() or smtp_ready() or (bool(EMAIL_PROVIDER) and APP_ENV.lower() != "production")


def email_otp_available() -> bool:
    """True when an email OTP can actually be delivered: a real provider in
    production, or the dev/test debug path that returns the code in the response.
    Gates the post-registration email-verification flow and the bootstrap
    'email_otp' method so we never demand a code we cannot send."""
    if email_provider_configured():
        return True
    return EMAIL_OTP_DEBUG_RETURN_CODE and APP_ENV.lower() != "production"


def validate_email_otp_config() -> None:
    security_validate_email_otp_config(
        app_env=APP_ENV,
        debug_return_code=EMAIL_OTP_DEBUG_RETURN_CODE,
        provider_configured=email_provider_configured(),
    )


def send_email_otp(destination: str, code: str) -> None:
    if unisender_ready() or smtp_ready():
        send_transactional_email(
            destination,
            "Код подтверждения ИЗО АСА",
            (
                "<p>Ваш код подтверждения:</p>"
                f"<p style='font-size:28px;font-weight:700;letter-spacing:4px'>{code}</p>"
                f"<p>Код действует {max(1, EMAIL_OTP_TTL_SECONDS // 60)} мин.</p>"
            ),
        )
        return
    security_send_email_otp(
        destination,
        code,
        app_env=APP_ENV,
        provider_configured=email_provider_configured(),
        mock_outbox=_mock_email_outbox,
    )


def cleanup_expired_otp_challenges(now: str | None = None) -> int:
    return security_cleanup_expired_otp_challenges(
        db,
        retention_seconds=EMAIL_OTP_CLEANUP_EXPIRED_AFTER_SECONDS,
        now=now,
    )


def _otp_runtime() -> OtpRuntime:
    return OtpRuntime(
        connect=db,
        get_client_ip=_client_ip,
        record_security_event=record_security_event,
        record_product_event=record_event_log,
    )


def _otp_rate_limits() -> OtpRateLimits:
    return OtpRateLimits(
        request_cooldown_seconds=EMAIL_OTP_REQUEST_COOLDOWN_SECONDS,
        max_requests_per_email_window=EMAIL_OTP_MAX_REQUESTS_PER_EMAIL_WINDOW,
        email_window_seconds=EMAIL_OTP_EMAIL_WINDOW_SECONDS,
        max_requests_per_ip_window=EMAIL_OTP_MAX_REQUESTS_PER_IP_WINDOW,
        ip_window_seconds=EMAIL_OTP_IP_WINDOW_SECONDS,
        max_active_challenges_per_email=EMAIL_OTP_MAX_ACTIVE_CHALLENGES_PER_EMAIL,
    )


def enforce_email_otp_rate_limits(
    email_norm: str,
    request: Request,
    anonymous_id: str | None,
    installation_id: str | None,
    platform: str | None,
) -> None:
    try:
        security_enforce_email_otp_rate_limits(
            _otp_runtime(),
            _otp_rate_limits(),
            email_norm,
            request,
            anonymous_id,
            installation_id,
            platform,
        )
    except OtpAccessError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


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
    _initialize_intro_tariff_if_new(conn, legacy_user_id, now)
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


ALLOWED_RESOLUTION_IDS = set(RESOLUTION_BY_ID)
QUALITY_PRESETS = ("fast", "standard", "max")
ALLOWED_TARIFF_MODEL_IDS = {
    "server:local_flux_klein",
}


def _tariff_resolutions(source: dict[str, Any], plan: str) -> list[str]:
    raw = source.get("allowed_resolutions", source.get("allowedResolutions", DEFAULT_TARIFFS[plan]["allowed_resolutions"]))
    values = raw if isinstance(raw, list) else []
    result = normalize_resolution_ids(values)
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
        monthly = source.get("monthly_tokens", source.get("monthlyTokens", source.get("openrouter_monthly_tokens", source.get("openrouterMonthlyTokens", DEFAULT_TARIFFS[plan]["monthly_tokens"]))))
        slots = source.get("gallery_slots", source.get("gallerySlots", DEFAULT_TARIFFS[plan]["gallery_slots"]))
        video_slots = source.get(
            "video_slots",
            source.get("video_storage_slots", source.get("videoSlots", DEFAULT_TARIFFS[plan]["video_slots"])),
        )
        try:
            price_int = int(price)
            daily_int = int(daily)
            monthly_int = int(monthly)
            slots_int = int(slots)
            video_slots_int = int(video_slots)
        except (TypeError, ValueError):
            if strict:
                raise HTTPException(400, f"Invalid tariff values for {plan}.")
            price_int = DEFAULT_TARIFFS[plan]["price_rub_month"]
            daily_int = DEFAULT_TARIFFS[plan]["daily_tokens"]
            monthly_int = DEFAULT_TARIFFS[plan]["monthly_tokens"]
            slots_int = DEFAULT_TARIFFS[plan]["gallery_slots"]
            video_slots_int = DEFAULT_TARIFFS[plan]["video_slots"]
        if strict and (price_int < 0 or daily_int < 0 or monthly_int < 0 or slots_int < 0 or video_slots_int < 0):
            raise HTTPException(400, f"Tariff values for {plan} must be non-negative.")
        result[plan] = {
            "title": _tariff_text(source, plan, "title", max_len=40),
            "note": _tariff_text(source, plan, "note", max_len=160),
            "price_rub_month": max(0, min(price_int, 10_000_000)),
            "daily_tokens": max(0, min(daily_int, 100_000)),
            "monthly_tokens": max(0, min(monthly_int, 100_000)),
            # Temporary read alias for older clients. This is not a third balance.
            "openrouter_monthly_tokens": max(0, min(monthly_int, 100_000)),
            "gallery_slots": max(0, min(slots_int, 100_000)),
            "quality_label": _tariff_text(source, plan, "quality_label", max_len=80),
            "model_defaults": _tariff_model_defaults(source, plan),
            "queue_label": _tariff_text(source, plan, "queue_label", max_len=80),
            "pro_mode_enabled": 1 if _boolish(source.get("pro_mode_enabled", source.get("proModeEnabled", DEFAULT_TARIFFS[plan]["pro_mode_enabled"]))) else 0,
            "allowed_resolutions": _tariff_resolutions(source, plan),
            "video_enabled": 1 if video_slots_int > 0 else 0,
            "video_slots": max(0, min(video_slots_int, 100_000)),
        }
    return result


def get_tariff_config(conn: sqlite3.Connection | None = None) -> dict[str, dict[str, Any]]:
    def load(current_conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        tariff_row = current_conn.execute("SELECT value_json FROM admin_settings WHERE key = 'tariffs'").fetchone()
        config = normalize_tariffs(json.loads(tariff_row["value_json"] or "{}") if tariff_row else None)
        access_row = current_conn.execute("SELECT value_json FROM admin_settings WHERE key = 'config_ui_resolution_access'").fetchone()
        access = json.loads(access_row["value_json"] or "{}") if access_row else {}
        plans = access.get("plans") if isinstance(access, dict) and isinstance(access.get("plans"), dict) else {}
        for plan in PLAN_ORDER:
            values = plans.get(plan)
            if isinstance(values, list):
                config[plan]["allowed_resolutions"] = normalize_resolution_ids(values, config[plan]["allowed_resolutions"])
        return config
    try:
        if conn is not None:
            return load(conn)
        with db() as local_conn:
            return load(local_conn)
    except Exception:
        return normalize_tariffs()


def get_tariff_term_settings(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    def load(current_conn: sqlite3.Connection) -> dict[str, Any]:
        row = current_conn.execute(
            "SELECT value_json FROM admin_settings WHERE key='tariff_terms'"
        ).fetchone()
        return normalize_term_settings(json.loads(row["value_json"] or "{}") if row else {})

    try:
        if conn is not None:
            return load(conn)
        with db() as local_conn:
            return load(local_conn)
    except Exception:
        return normalize_term_settings({})


def tariff_term_offers(conn: sqlite3.Connection | None = None) -> dict[str, list[dict[str, Any]]]:
    tariffs = get_tariff_config(conn)
    settings = get_tariff_term_settings(conn)
    discounts = settings["discount_percent"]
    estimated_cost = float(settings["estimated_token_cost_rub"] or 0)
    return {
        plan: [
            {
                "code": tariff_package_code(plan, months),
                **build_offer(
                    monthly_price_rub=int(tariffs[plan]["price_rub_month"]),
                    monthly_tokens=int(tariffs[plan]["monthly_tokens"]),
                    months=months,
                    discount_percent=int(discounts[str(months)]),
                    estimated_token_cost_rub=estimated_cost,
                ).as_dict(),
            }
            for months in TERM_MONTHS
        ]
        for plan in ("mini", "plus", "pro", "business")
    }


def public_tariff_term_offers(conn: sqlite3.Connection | None = None) -> dict[str, list[dict[str, Any]]]:
    private_fields = {"estimated_cost_rub", "estimated_profit_rub", "estimated_margin_percent"}
    return {
        plan: [
            {key: value for key, value in offer.items() if key not in private_fields}
            for offer in offers
        ]
        for plan, offers in tariff_term_offers(conn).items()
    }


def _as_utc_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _grant_tariff_tokens(
    conn: sqlite3.Connection,
    *,
    user_row: sqlite3.Row,
    plan: str,
    amount: int,
    grant_key: str,
    source: str,
    source_id: str | None,
    period_start: datetime,
) -> bool:
    amount = max(0, int(amount))
    if amount <= 0:
        return False
    now = datetime.now(timezone.utc).isoformat()
    grant_id = uuid.uuid4().hex
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO tariff_token_grants
            (id, internal_user_id, user_id, grant_key, plan, amount, source, source_id, period_start, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            grant_id,
            user_row["internal_user_id"],
            user_row["id"],
            grant_key,
            plan,
            amount,
            source,
            source_id,
            period_start.isoformat(),
            now,
        ),
    )
    if cursor.rowcount != 1:
        return False
    conn.execute(
        "UPDATE users SET token_balance=token_balance+? WHERE internal_user_id=?",
        (amount, user_row["internal_user_id"]),
    )
    conn.execute(
        "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, 'tariff_monthly_grant', ?, ?)",
        (
            uuid.uuid4().hex,
            user_row["id"],
            amount,
            json.dumps(
                {
                    "plan": plan,
                    "grant_key": grant_key,
                    "source": source,
                    "source_id": source_id,
                    "period_start": period_start.isoformat(),
                },
                ensure_ascii=False,
            ),
            now,
        ),
    )
    return True


def _activate_tariff_now(
    conn: sqlite3.Connection,
    *,
    internal_user_id: str,
    plan: str,
    now: datetime,
    source: str,
    source_id: str | None = None,
    term_months: int = 1,
    duration_days: int | None = None,
    reset_balance: bool = False,
) -> dict[str, Any]:
    if plan not in PLAN_ORDER:
        raise ValueError("unknown tariff plan")
    row = conn.execute(
        "SELECT * FROM users WHERE internal_user_id=?", (internal_user_id,)
    ).fetchone()
    if row is None:
        raise ValueError("user not found")
    tariffs = get_tariff_config(conn)
    monthly_amount = int(tariffs[plan]["monthly_tokens"])
    if plan == "free":
        monthly_amount = 0
        expires_at = None
        next_grant_at = None
        term_months = 1
    elif duration_days is not None:
        days = max(1, min(int(duration_days), 3660))
        expires_at = now + timedelta(days=days)
        next_grant_at = add_calendar_months(now, 1) if days > 30 else None
        monthly_amount = prorated_monthly_tokens(monthly_amount, days) if days < 30 else monthly_amount
        term_months = max(1, int(round(days / 30)))
    else:
        if term_months not in TERM_MONTHS:
            raise ValueError("unsupported tariff term")
        expires_at = add_calendar_months(now, term_months)
        next_grant_at = add_calendar_months(now, 1)
    if reset_balance:
        conn.execute("UPDATE users SET token_balance=0 WHERE internal_user_id=?", (internal_user_id,))
        row = conn.execute("SELECT * FROM users WHERE internal_user_id=?", (internal_user_id,)).fetchone()
    conn.execute(
        """
        UPDATE users SET
            plan=?, plan_started_at=?, plan_expires_at=?, plan_next_token_grant_at=?,
            plan_monthly_token_grant=?, plan_term_months=?, plan_grant_source=?,
            pending_plan_json=NULL, gallery_enabled=1, daily_tokens_used=0, last_daily_reset=?,
            openrouter_monthly_tokens_used=0, last_openrouter_month_reset=?
        WHERE internal_user_id=?
        """,
        (
            plan,
            now.isoformat(),
            expires_at.isoformat() if expires_at else None,
            next_grant_at.isoformat() if next_grant_at and expires_at and next_grant_at < expires_at else None,
            int(tariffs[plan]["monthly_tokens"]) if plan != "free" else 0,
            term_months,
            source,
            now.date().isoformat(),
            now.strftime("%Y-%m"),
            internal_user_id,
        ),
    )
    grant_key = f"tariff:{source}:{source_id or internal_user_id}:{now.isoformat()}"
    granted = _grant_tariff_tokens(
        conn,
        user_row=row,
        plan=plan,
        amount=monthly_amount,
        grant_key=grant_key,
        source=source,
        source_id=source_id,
        period_start=now,
    )
    return {
        "plan": plan,
        "plan_started_at": now.isoformat(),
        "plan_expires_at": expires_at.isoformat() if expires_at else None,
        "monthly_tokens_granted": monthly_amount if granted else 0,
        "term_months": term_months,
    }


def _schedule_or_activate_paid_tariff(
    conn: sqlite3.Connection,
    *,
    internal_user_id: str,
    plan: str,
    term_months: int,
    source: str,
    source_id: str,
    now: datetime,
) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM users WHERE internal_user_id=?", (internal_user_id,)).fetchone()
    if row is None:
        raise ValueError("user not found")
    current_plan = str(row["plan"] or "free").lower()
    current_expiry = _as_utc_datetime(row["plan_expires_at"])
    current_active = current_plan != "free" and current_expiry is not None and current_expiry > now
    if current_active and PLAN_ORDER.index(plan) < PLAN_ORDER.index(current_plan):
        pending = {
            "plan": plan,
            "term_months": term_months,
            "source": source,
            "source_id": source_id,
        }
        conn.execute(
            "UPDATE users SET pending_plan_json=? WHERE internal_user_id=?",
            (json.dumps(pending, ensure_ascii=False), internal_user_id),
        )
        return {"scheduled": True, "starts_at": current_expiry.isoformat(), **pending}
    if current_active and plan == current_plan:
        expires_at = add_calendar_months(current_expiry, term_months)
        current_next_grant = _as_utc_datetime(row["plan_next_token_grant_at"])
        next_grant_at = current_next_grant or current_expiry
        conn.execute(
            "UPDATE users SET plan_expires_at=?, plan_next_token_grant_at=?, plan_term_months=COALESCE(plan_term_months, 1)+?, plan_grant_source=?, pending_plan_json=NULL WHERE internal_user_id=?",
            (
                expires_at.isoformat(),
                next_grant_at.isoformat() if next_grant_at < expires_at else None,
                term_months,
                source,
                internal_user_id,
            ),
        )
        return {"scheduled": False, "extended": True, "plan": plan, "plan_expires_at": expires_at.isoformat()}
    return _activate_tariff_now(
        conn,
        internal_user_id=internal_user_id,
        plan=plan,
        term_months=term_months,
        source=source,
        source_id=source_id,
        now=now,
    )


def _reconcile_user_tariff(conn: sqlite3.Connection, internal_user_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    row = conn.execute("SELECT * FROM users WHERE internal_user_id=?", (internal_user_id,)).fetchone()
    if row is None:
        return {"changed": False}
    plan = str(row["plan"] or "free").lower()
    expiry = _as_utc_datetime(row["plan_expires_at"])
    next_grant = _as_utc_datetime(row["plan_next_token_grant_at"])
    monthly_amount = max(0, int(row["plan_monthly_token_grant"] or 0))
    grants = 0
    while plan != "free" and expiry and next_grant and next_grant < expiry and next_grant <= now:
        key = f"tariff:period:{internal_user_id}:{next_grant.isoformat()}"
        if _grant_tariff_tokens(
            conn,
            user_row=row,
            plan=plan,
            amount=monthly_amount,
            grant_key=key,
            source="recurring",
            source_id=None,
            period_start=next_grant,
        ):
            grants += 1
        next_grant = add_calendar_months(next_grant, 1)
        conn.execute(
            "UPDATE users SET plan_next_token_grant_at=? WHERE internal_user_id=?",
            (next_grant.isoformat() if next_grant < expiry else None, internal_user_id),
        )
    if plan != "free" and expiry and expiry <= now:
        pending_raw = row["pending_plan_json"]
        pending = None
        if pending_raw:
            try:
                pending = json.loads(pending_raw)
            except (TypeError, ValueError):
                pending = None
        if isinstance(pending, dict) and pending.get("plan") in PLAN_ORDER:
            activated = _activate_tariff_now(
                conn,
                internal_user_id=internal_user_id,
                plan=str(pending["plan"]),
                term_months=int(pending.get("term_months") or 1),
                source=str(pending.get("source") or "scheduled"),
                source_id=str(pending.get("source_id") or "") or None,
                now=now,
            )
            return {"changed": True, "grants": grants, "activated": activated}
        conn.execute(
            """
            UPDATE users SET plan='free', plan_started_at=?, plan_expires_at=NULL,
                plan_next_token_grant_at=NULL, plan_monthly_token_grant=0,
                plan_term_months=1, plan_grant_source='expiry', pending_plan_json=NULL
            WHERE internal_user_id=?
            """,
            (now.isoformat(), internal_user_id),
        )
        return {"changed": True, "grants": grants, "plan": "free"}
    return {"changed": grants > 0, "grants": grants, "plan": plan}


def _initialize_intro_tariff_if_new(conn: sqlite3.Connection, legacy_user_id: str, created_at: str) -> bool:
    row = conn.execute(
        "SELECT internal_user_id, created_at, plan_started_at FROM users WHERE id=?",
        (legacy_user_id,),
    ).fetchone()
    if (
        row is None
        or not row["internal_user_id"]
        or str(row["created_at"] or "") != str(created_at)
        or row["plan_started_at"]
    ):
        return False
    _activate_tariff_now(
        conn,
        internal_user_id=row["internal_user_id"],
        plan="mini",
        term_months=1,
        source="signup",
        source_id=row["internal_user_id"],
        now=_as_utc_datetime(created_at) or datetime.now(timezone.utc),
        reset_balance=True,
    )
    return True


def gallery_quota_for_user(conn: sqlite3.Connection, user_row: sqlite3.Row | None, legacy_user_id: str | None = None) -> dict[str, Any]:
    plan = gallery_policy.normalize_gallery_plan(_row_get(user_row, "plan"), PLAN_ORDER)
    tariff = get_tariff_config(conn)[plan]
    user_id = legacy_user_id or _row_get(user_row, "id")
    used = 0
    if user_id:
        used = storage_count_active_gallery_images(conn, user_id)
    return gallery_policy.build_gallery_quota(plan=plan, tariff=tariff, gallery_used=used)


def video_storage_state_for_user(
    conn: sqlite3.Connection,
    user_row: sqlite3.Row | None,
    legacy_user_id: str,
    *,
    exclude_job_id: str | None = None,
) -> video_storage.VideoStorageState:
    quota = gallery_quota_for_user(conn, user_row, legacy_user_id)
    return video_storage.storage_state(
        conn,
        legacy_user_id,
        limit=int(quota["video_slots"] or 0),
        exclude_job_id=exclude_job_id,
    )


ACTIVE_IMAGE_WHERE = "deleted_at IS NULL"


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
    target = gallery_policy.gallery_eviction_target(quota)
    if not target:
        return 0
    rows = storage_select_gallery_eviction_candidates(conn, legacy_user_id, limit=target)
    runtime = gallery_eviction.GalleryEvictionRuntime(
        soft_delete=lambda image_id: conn.execute(
            "UPDATE images SET deleted_at = ? WHERE id = ?",
            (now_iso, image_id),
        ),
        # Public feed variants are independent from the private gallery source.
        # Quota eviction must not silently unpublish an explicitly posted work.
        delete_files=lambda url, thumbnail_url: delete_image_files_from_disk(
            url=url,
            thumbnail_url=thumbnail_url,
        ),
        drop_cached_image=lambda image_id: images.pop(image_id) if image_id in images else None,
    )
    return gallery_eviction.apply_gallery_evictions(runtime, rows)


def gallery_cursor_from_row(row: sqlite3.Row) -> str:
    return gallery_query.encode_gallery_cursor(_row_get(row, "created_at"), _row_get(row, "id"))


def parse_gallery_cursor(cursor: str | None) -> tuple[str, str] | None:
    try:
        return gallery_query.decode_gallery_cursor(cursor)
    except gallery_query.GalleryCursorError as exc:
        raise HTTPException(400, "invalid gallery cursor") from exc


def gallery_fts_query(value: str) -> str:
    return gallery_query.build_gallery_fts_query(value)


def gallery_media_owner_row(conn: sqlite3.Connection, filename: str, legacy_user_id: str) -> sqlite3.Row | None:
    return storage_find_gallery_media_owner(
        conn,
        filename,
        legacy_user_id,
        active_image_where=ACTIVE_IMAGE_WHERE,
    )


def gallery_image_id_from_media_url(conn: sqlite3.Connection, url: str | None, legacy_user_id: str) -> str | None:
    filename = media_filename_from_url(url)
    if not filename:
        return None
    row = storage_find_owned_active_image(
        conn,
        filename,
        legacy_user_id,
        active_image_where=ACTIVE_IMAGE_WHERE,
    )
    return row["id"] if row is not None else None


def cleanup_orphan_image_sources(*, grace_seconds: int = 3600) -> dict[str, int]:
    runtime = SourceCleanupRuntime(connect=db, filename_from_url=media_filename_from_url)
    return storage_reconcile_orphan_source_rows(
        runtime,
        MEDIA,
        grace_seconds=grace_seconds,
    )


def reconcile_image_source_availability(user_id: str | None = None) -> dict[str, int]:
    runtime = SourceAvailabilityRuntime(connect=db, path_from_url=local_media_path_from_url)
    return storage_reconcile_source_availability(
        runtime,
        active_image_where=ACTIVE_IMAGE_WHERE,
        user_id=user_id,
    )


def user_gallery_allowed(conn: sqlite3.Connection, internal_user_id: str | None, legacy_user_id: str | None) -> bool:
    row = None
    if internal_user_id:
        row = conn.execute("SELECT role, plan, gallery_enabled FROM users WHERE internal_user_id = ?", (internal_user_id,)).fetchone()
    if row is None and legacy_user_id:
        row = conn.execute("SELECT role, plan, gallery_enabled FROM users WHERE id = ?", (legacy_user_id,)).fetchone()
    if row is None:
        return False
    return True


def _session_runtime() -> SessionRuntime:
    return SessionRuntime(
        connect=db,
        validate_crypto=validate_session_crypto_config,
        generate_token=generate_secure_token,
        hash_token=hash_token,
        record_session_event=record_session_event,
        record_security_event=record_security_event,
        user_is_banned=_user_is_banned,
        ensure_public_user_code=ensure_public_user_code,
        get_client_ip=get_client_ip,
        hash_user_agent=_hash_user_agent,
        parse_user_agent=parse_user_agent,
    )


def create_auth_session(
    internal_user_id: str,
    legacy_user_id: str | None = None,
    provider: str | None = None,
    platform: str | None = None,
    request: Request | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Compatibility wrapper around the extracted trusted-session service."""
    return security_create_session(
        _session_runtime(),
        internal_user_id,
        legacy_user_id,
        provider,
        platform,
        request,
        metadata,
        access_ttl_seconds=SESSION_ACCESS_TTL_SECONDS,
        refresh_ttl_seconds=SESSION_REFRESH_TTL_SECONDS,
    )


def resolve_auth_session_from_request(
    request: Request, *, raise_on_failure: bool = True
) -> dict[str, Any] | None:
    """Resolve a trusted session without accepting legacy identity inputs."""
    try:
        return security_resolve_session(
            _session_runtime(),
            _extract_session_token(request),
            request,
            raise_on_failure=raise_on_failure,
        )
    except SessionAccessError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


def refresh_auth_session(refresh_token: str, request: Request | None = None) -> dict[str, str]:
    """Rotate a trusted refresh token through the extracted session service."""
    try:
        return security_refresh_session(
            _session_runtime(),
            refresh_token,
            request,
            app_env=APP_ENV,
            access_ttl_seconds=SESSION_ACCESS_TTL_SECONDS,
            refresh_ttl_seconds=SESSION_REFRESH_TTL_SECONDS,
        )
    except SessionAccessError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


def revoke_auth_session(
    session_id: str,
    reason: str = "logout",
    request: Request | None = None,
    event_type: str | None = None,
) -> bool:
    return security_revoke_session(_session_runtime(), session_id, reason, request, event_type)


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


def _permission_runtime() -> PermissionRuntime:
    return PermissionRuntime(
        connect=db,
        resolve_session=resolve_auth_session_from_request,
        record_security_event=record_security_event,
    )


def resolve_trusted_user(request: Request) -> dict[str, Any]:
    """Resolve identity only from a trusted server-side session."""
    try:
        return security_resolve_trusted_identity(_permission_runtime(), request)
    except PermissionAccessError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


def expire_paid_plan_if_needed(internal_user_id: str) -> bool:
    with db() as conn:
        result = _reconcile_user_tariff(conn, internal_user_id)
    return bool(result.get("changed"))


def require_trusted_user(request: Request) -> dict[str, Any]:
    """Thin wrapper over resolve_trusted_user for new v2 endpoints."""
    trusted = resolve_trusted_user(request)
    expire_paid_plan_if_needed(trusted["internal_user_id"])
    return trusted


def require_trusted_admin(request: Request) -> dict[str, Any]:
    """Require an admin role resolved exclusively through the trusted session."""
    try:
        return security_require_admin(_permission_runtime(), request)
    except PermissionAccessError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


def trusted_user_is_admin(user: dict[str, Any]) -> bool:
    return security_user_is_admin(_permission_runtime(), user)


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
AVATAR_MAX_SIDE = 4096
AVATAR_MAX_PIXELS = 16 * 1024 * 1024
AVATAR_OUTPUT_SIZE = 512
AVATAR_WEBP_QUALITY = 86
AVATAR_ALLOWED_CONTENT_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
AVATAR_ALLOWED_FORMAT_TYPES = {
    "PNG": {"image/png"},
    "JPEG": {"image/jpeg"},
    "WEBP": {"image/webp"},
}


def random_avatar_choice() -> tuple[str, str]:
    preset = f"avatar-{secrets.randbelow(AVATAR_PRESET_COUNT) + 1:03d}"
    return f"/avatars/{preset}.webp", preset


def repair_missing_user_avatars() -> dict[str, int]:
    """Replace only broken local custom avatars with an available preset."""
    stats = {"checked": 0, "repaired": 0}
    with db() as conn:
        rows = conn.execute(
            "SELECT id, avatar_url, avatar_preset FROM users "
            "WHERE avatar_url LIKE '/media/avatars/%' AND (avatar_preset IS NULL OR avatar_preset = '')"
        ).fetchall()
        for row in rows:
            stats["checked"] += 1
            rel = str(row["avatar_url"] or "").removeprefix("/media/").split("?", 1)[0]
            path = (MEDIA / rel).resolve()
            try:
                path.relative_to(MEDIA.resolve())
            except ValueError:
                path = MEDIA / "__invalid_avatar_path__"
            if path.is_file():
                continue
            avatar_url, avatar_preset = random_avatar_choice()
            conn.execute(
                "UPDATE users SET avatar_url = ?, avatar_preset = ? WHERE id = ? AND avatar_url = ?",
                (avatar_url, avatar_preset, row["id"], row["avatar_url"]),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                stats["repaired"] += 1
    return stats


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


def compress_avatar_image(data: bytes, content_type: str | None = None) -> bytes:
    try:
        return compress_allowlisted_avatar(
            data, content_type, allowed_format_types=AVATAR_ALLOWED_FORMAT_TYPES,
            max_side=AVATAR_MAX_SIDE, max_pixels=AVATAR_MAX_PIXELS,
            output_size=AVATAR_OUTPUT_SIZE, webp_quality=AVATAR_WEBP_QUALITY,
        )
    except AvatarImageError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


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
    """Return a user-facing model label without exposing technical provider ids."""
    if not raw:
        return "ИЗО Base"
    catalog = globals().get("OPENROUTER_PRICE_CATALOG") or {}
    if raw in catalog:
        return catalog[raw].name
    lowered = raw.lower()
    if any(kw in lowered for kw in ("local_flux", "server_flux", "comfyui", "klein")):
        return "ИЗО Base"
    if "/" in raw:
        return raw.split("/")[-1].replace("-", " ").replace("_", " ").title()
    return "ИЗО Base"


def _media_file_size_from_url(url: str | None) -> int | None:
    try:
        path = local_media_path_from_url(url or "")
        if path and path.exists() and path.is_file():
            return int(path.stat().st_size)
    except Exception:
        return None
    return None


def _format_public_bytes(value: int | None) -> str | None:
    return gallery_presentation.format_gallery_public_bytes(value)


def _format_public_duration(ms: Any) -> str | None:
    return gallery_presentation.format_gallery_public_duration(ms)


def _format_public_datetime(value: Any) -> str | None:
    return gallery_presentation.format_gallery_public_datetime(value)


def _public_token_cost(settings: dict[str, Any]) -> int | None:
    return gallery_presentation.gallery_public_token_cost(settings)


MODEL_RELEASE_YEAR_BY_ID = {
    "local_flux_klein": "2026",
    "black-forest-labs/flux.2-klein-4b": "2026",
    "black-forest-labs/flux.2-pro": "2026",
    "black-forest-labs/flux.2-max": "2026",
    "black-forest-labs/flux.2-flex": "2026",
    "openai/gpt-image-1-mini": "2026",
    "openai/gpt-5-image-mini": "2026",
    "openai/gpt-image-1": "2026",
    "openai/gpt-5-image": "2026",
    "openai/gpt-image-2": "2026",
    "openai/gpt-5.4-image-2": "2026",
    "google/gemini-3.1-flash-lite-image": "2026",
    "google/gemini-3.1-flash-image": "2026",
    "google/gemini-3.1-flash-image-preview": "2026",
    "google/gemini-3-pro-image": "2026",
    "google/gemini-3-pro-image-preview": "2026",
    "google/gemini-2.5-flash-image": "2026",
    "google/gemini-2.5-flash-image-preview": "2026",
    "microsoft/mai-image-2.5": "2026",
    "x-ai/grok-imagine-image-quality": "2026",
}


def _gallery_model_info(settings: dict[str, Any], provider: str | None = None) -> dict[str, str]:
    return gallery_presentation.gallery_model_info(
        settings,
        provider,
        price_catalog=globals().get("OPENROUTER_PRICE_CATALOG") or {},
        release_years=MODEL_RELEASE_YEAR_BY_ID,
        model_display_name=_user_model_name,
    )


def _gallery_public_params(
    *,
    image_id: str,
    mode: str | None,
    provider: str | None,
    width: int | None,
    height: int | None,
    url: str | None,
    created_at: str | None,
    settings: dict[str, Any],
) -> list[dict[str, str]]:
    return gallery_presentation.gallery_public_params(
        mode=mode,
        provider=provider,
        width=width,
        height=height,
        url=url,
        created_at=created_at,
        settings=settings,
        model_info=_gallery_model_info,
        token_cost=_public_token_cost,
        aspect_ratio=_gallery_aspect_ratio,
        media_file_size=_media_file_size_from_url,
        format_bytes=_format_public_bytes,
        format_duration=_format_public_duration,
        format_datetime=_format_public_datetime,
        mode_label=_gallery_mode_label,
    )


def row_to_image(row: sqlite3.Row) -> dict[str, Any]:
    return gallery_presentation.gallery_row_to_image(
        row,
        load_settings=json.loads,
        media_file_size=_media_file_size_from_url,
        model_display_name=_user_model_name,
        model_info=_gallery_model_info,
        public_params=_gallery_public_params,
        row_get=_row_get,
    )


def _gallery_aspect_ratio(width: int | None, height: int | None) -> str | None:
    return gallery_presentation.gallery_aspect_ratio(width, height)


def _gallery_mode_label(mode: str | None) -> str:
    return gallery_presentation.gallery_mode_label(mode)


def _gallery_source_ids(settings: dict[str, Any]) -> list[str]:
    return gallery_presentation.gallery_source_ids(settings)


def _feed_publication_ready(publication: sqlite3.Row | None) -> bool:
    return gallery_items.feed_publication_ready(publication, row_get=_row_get)


def _gallery_page_item(
    row: sqlite3.Row,
    publication: sqlite3.Row | None = None,
    *,
    include_feed_media: bool = False,
) -> dict[str, Any]:
    return gallery_items.gallery_page_item(
        row,
        publication,
        include_feed_media=include_feed_media,
        load_settings=json.loads,
        row_get=_row_get,
        publication_ready=_feed_publication_ready,
        media_file_size=_media_file_size_from_url,
        mode_label=_gallery_mode_label,
        model_display_name=_user_model_name,
        model_info=_gallery_model_info,
        aspect_ratio=_gallery_aspect_ratio,
        public_params=_gallery_public_params,
        source_ids=_gallery_source_ids,
    )


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
    image_favorites_used = int(conn.execute(
        """
        SELECT COUNT(*) AS c FROM images
        WHERE user_id = ? AND is_favorite = 1 AND (deleted_at IS NULL OR deleted_at = '')
        """,
        (legacy_user_id,),
    ).fetchone()["c"])
    video_state = video_storage_state_for_user(conn, user_row, legacy_user_id)
    video_used = video_state.active
    video_favorites_used = int(conn.execute(
        "SELECT COUNT(*) AS c FROM videos WHERE user_id = ? AND is_favorite = 1 AND deleted_at IS NULL",
        (legacy_user_id,),
    ).fetchone()["c"])
    favorites_used = image_favorites_used + video_favorites_used
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
        "videos": {
            "used": video_used,
            "limit": video_state.limit,
            "free": video_state.free,
            "full": video_state.full,
            "storedBytes": video_state.stored_bytes,
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


def reconcile_stale_generation_state() -> dict[str, int]:
    completed_at = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        report = generation_recovery.reconcile_stale_generation_jobs(
            conn,
            completed_at=completed_at,
            refund_job=refund_generation_tokens,
        )
    return report.as_dict()


def job_response_from_row(row: sqlite3.Row, image_row: sqlite3.Row | None = None) -> dict[str, Any]:
    return generation_jobs.job_response_from_row(row, image_row, model_display_name=_user_model_name)


def get_persisted_job_response(job_id: str, user_id: str) -> dict[str, Any] | None:
    with db() as conn:
        return generation_jobs.get_persisted_job_response(
            conn,
            job_id,
            user_id,
            model_display_name=_user_model_name,
        )


def persist_job(job: dict[str, Any], request: GenerateRequest | None = None, conn: sqlite3.Connection | None = None) -> None:
    request_data = request.model_dump() if request else job.get("request", {})
    request_mode = request.mode if request else ""
    request_provider = request.provider if request else ""
    request_prompt = request.prompt if request else request_data.get("prompt", "")

    def write(target_conn: sqlite3.Connection) -> None:
        generation_jobs.persist_job(
            target_conn,
            job,
            request_data=request_data,
            request_mode=request_mode,
            request_provider=request_provider,
            request_prompt=request_prompt,
            now_iso=datetime.now(timezone.utc).isoformat(),
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
        "tokenCost": record.get("tokenCost"),
        "comfyuiPromptId": record.get("comfyuiPromptId"),
        "comfyuiHistory": record.get("comfyuiHistory"),
        "openrouterModel": record.get("openrouterModel"),
        "openrouterResponseId": record.get("openrouterResponseId"),
        "openrouterUsage": record.get("openrouterUsage"),
        "openrouterCostUsd": record.get("openrouterCostUsd"),
        "openrouterBilling": record.get("openrouterBilling"),
        "openrouterRequest": record.get("openrouterRequest"),
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
    feed_match = re.fullmatch(r"/api/feed/media/([A-Za-z0-9_-]+)(?:\?[^#]*)?", str(url or ""))
    if feed_match:
        try:
            return storage_resolve_feed_media(
                _public_media_runtime(),
                MEDIA,
                feed_match.group(1),
                variant="large",
            )
        except PublicMediaAccessError:
            return None
    try:
        return storage_local_media_path_from_url(MEDIA, url)
    except StoragePathError as exc:
        raise RuntimeError("Недопустимый путь media-файла.") from exc


def media_filename_from_url(url: str | None) -> str | None:
    return storage_media_filename_from_url(MEDIA, url)


def _source_role_label(role: str | None, slot_index: int, mode: str | None = None) -> str:
    return storage_source_role_label(role, slot_index, mode)


def _generation_source_inputs(req: GenerateRequest) -> list[dict[str, Any]]:
    return storage_generation_source_inputs(req)


def _save_source_thumb(source_value: str | None, image_id: str, slot_index: int) -> tuple[Path, int, int, int] | None:
    runtime = SourceThumbnailRuntime(
        media_dir=MEDIA,
        resolve_local_media=local_media_path_from_url,
        max_side=SOURCE_THUMB_MAX_SIDE,
        webp_quality=SOURCE_THUMB_WEBP_QUALITY,
    )
    return storage_save_source_thumbnail(runtime, source_value, image_id, slot_index)


def persist_image_sources(image_id: str, user_id: str, req: GenerateRequest, created_at: str) -> list[dict[str, Any]]:
    tree = SourceTreeRuntime(load_json=safe_json_load, role_label=_source_role_label)
    runtime = SourcePersistenceRuntime(
        connect=db,
        tree=tree,
        save_source_thumb=_save_source_thumb,
        find_source_image_id=gallery_image_id_from_media_url,
        role_label=_source_role_label,
        public_url=public_url,
        media_filename_from_url=media_filename_from_url,
        delete_media_rel=_delete_media_rel,
    )
    with db() as conn:
        library_limit = int(gallery_quota_for_user(conn, None, user_id)["gallery_slots"])
    return storage_persist_image_source_rows(
        runtime,
        image_id,
        user_id,
        _generation_source_inputs(req),
        created_at,
        mode=req.mode,
        library_limit=library_limit,
    )


def repair_unavailable_image_sources_from_jobs(
    user_id: str | None = None,
    *,
    limit: int = 500,
) -> dict[str, int]:
    def source_candidates(settings_json: str | None, slot_index: int) -> list[str]:
        req = GenerateRequest(**safe_json_load(settings_json))
        for position, source in enumerate(_generation_source_inputs(req), start=1):
            slot = int(source.get("slot") or position)
            if slot == slot_index:
                return [str(source.get("value") or "")]
        return []

    runtime = SourceRepairRuntime(
        connect=db,
        source_candidates_from_settings=source_candidates,
        save_source_thumb=_save_source_thumb,
        public_url=public_url,
    )
    return storage_repair_unavailable_sources_from_jobs(runtime, user_id, limit=limit)


def gallery_sources_for_image(
    conn: sqlite3.Connection,
    image_id: str,
    user_id: str,
    *,
    depth: int = 3,
    visited: set[str] | None = None,
) -> list[dict[str, Any]]:
    runtime = SourceTreeRuntime(load_json=safe_json_load, role_label=_source_role_label)
    return storage_read_image_source_tree(
        runtime,
        conn,
        image_id,
        user_id,
        depth=depth,
        visited=visited,
    )
def persist_video_sources(job_id: str, user_id: str, req: VideoGenerateRequest, created_at: str) -> list[dict[str, Any]]:
    return storage_persist_video_sources(
        VideoSourcePersistenceRuntime(
            connect=db, save_source_thumb=_save_source_thumb,
            find_source_image_id=gallery_image_id_from_media_url,
            read_image_children=lambda conn, image_id, owner_id: gallery_sources_for_image(
                conn, image_id, owner_id, depth=2, visited=set()),
            public_url=public_url,
        ),
        job_id, user_id, storage_video_generation_source_inputs(req), created_at,
    )


def repair_image_sources_from_job(image_id: str, user_id: str) -> list[dict[str, Any]]:
    def restore_from_job_settings(
        settings_json: str | None,
        target_image_id: str,
        target_user_id: str,
        created_at: str,
    ) -> list[dict[str, Any]]:
        try:
            req = GenerateRequest(**(safe_json_load(settings_json) or {}))
        except Exception:
            return []
        if not _generation_source_inputs(req):
            return []
        return persist_image_sources(target_image_id, target_user_id, req, created_at)

    tree = SourceTreeRuntime(load_json=safe_json_load, role_label=_source_role_label)
    runtime = SourceRowRepairRuntime(
        connect=db,
        active_image_where=ACTIVE_IMAGE_WHERE,
        tree=tree,
        restore_from_job_settings=restore_from_job_settings,
    )
    return storage_repair_image_source_rows_from_job(runtime, image_id, user_id)


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

    runtime = MediaInputValidationRuntime(
        connect=db,
        filename_from_url=media_filename_from_url,
        resolve_local_media=local_media_path_from_url,
        active_image_where=ACTIVE_IMAGE_WHERE,
    )
    try:
        storage_validate_owned_media_inputs(runtime, candidates, user_id)
    except MediaInputValidationError as exc:
        raise HTTPException(400, {"code": exc.code, "field": exc.field}) from exc


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
        internal_user_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO users (id, telegram_id, max_id, username, first_name, last_name, middle_name, phone, email, language, role, plan, gallery_enabled, created_at, last_login_at,
                               country, city, timezone, ref_code, last_user_agent, last_screen, last_seen_at, avatar_url, avatar_preset, internal_user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'user', 'mini', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                internal_user_id,
            ),
        )
        assigned = conn.execute("SELECT internal_user_id FROM users WHERE id=?", (user_id,)).fetchone()
        if assigned is not None and not assigned["internal_user_id"]:
            conn.execute("UPDATE users SET internal_user_id=? WHERE id=?", (internal_user_id, user_id))
        _initialize_intro_tariff_if_new(conn, user_id, now)
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

    There are exactly two accounts: the daily tariff allowance and the main
    balance. Local server generations consume daily tokens first and then the
    main balance. API generations consume the main balance only.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    today = now.strftime("%Y-%m-%d")
    user_row = conn.execute(
        "SELECT id, internal_user_id, token_balance, plan, daily_tokens_used, last_daily_reset FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if user_row is None:
        raise HTTPException(404, "User not found.")
    if user_row["internal_user_id"]:
        _reconcile_user_tariff(conn, str(user_row["internal_user_id"]), now=now)
        user_row = conn.execute(
            "SELECT id, internal_user_id, token_balance, plan, daily_tokens_used, last_daily_reset FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    old_balance = int(user_row["token_balance"] or 0)
    daily_limit = 0
    daily_used_before = int(user_row["daily_tokens_used"] or 0)
    if user_row["last_daily_reset"] != today:
        daily_used_before = 0
    daily_part = 0
    balance_part = 0

    if user_id != "demo_user":
        tariff = get_tariff_config(conn)[str(user_row["plan"] or "mini").lower()]
        daily_limit = int(tariff["daily_tokens"])
        if req.provider != "openrouter":
            daily_part = min(token_cost, max(0, daily_limit - daily_used_before))
        balance_part = max(0, token_cost - daily_part)
        if old_balance < balance_part:
            raise HTTPException(402, "Not enough tokens.")

    daily_used_after = daily_used_before + daily_part
    new_balance = old_balance - balance_part if user_id != "demo_user" else old_balance
    ledger_reason = "daily_generation" if daily_part > 0 and balance_part == 0 else "generation"
    conn.execute(
        """
        UPDATE users
        SET token_balance = ?,
            daily_tokens_used = ?,
            last_daily_reset = ?,
            tokens_used = tokens_used + ?,
            generation_count = generation_count + 1,
            last_seen_at = ?
        WHERE id = ?
        """,
        (new_balance, daily_used_after, today, token_cost, now_iso, user_id),
    )
    conn.execute(
        "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            user_id,
            -balance_part,
            ledger_reason,
            json.dumps(
                {
                    "jobId": job_id,
                    "mode": req.mode,
                    "provider": req.provider,
                    "token_cost": token_cost,
                    "billing": billing_snapshot or None,
                    "used_daily_budget": daily_part > 0,
                    "daily_part": daily_part,
                    "balance_part": balance_part,
                    "daily_tokens_used_before": daily_used_before,
                    "daily_tokens_used_after": daily_used_after,
                    "daily_tokens_limit": daily_limit,
                    "balance_delta": -balance_part,
                },
                ensure_ascii=False,
            ),
            now_iso,
        ),
    )
    return {
        "used_daily": daily_part > 0,
        "old_balance": old_balance,
        "new_balance": new_balance,
        "balance_delta": -balance_part,
        "daily_part": daily_part,
        "balance_part": balance_part,
        "daily_tokens_used": daily_used_after,
        "daily_tokens_limit": daily_limit,
        "daily_tokens_remaining": max(0, daily_limit - daily_used_after),
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
    if "daily_part" in meta or "balance_part" in meta:
        daily_part = max(0, int(meta.get("daily_part") or 0))
        balance_part = max(0, int(meta.get("balance_part") or 0))
        user_row = conn.execute(
            "SELECT daily_tokens_used, last_daily_reset FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if user_row is not None and user_row["last_daily_reset"] == today and daily_part > 0:
            conn.execute(
                "UPDATE users SET daily_tokens_used = MAX(0, daily_tokens_used - ?) WHERE id = ?",
                (daily_part, user_id),
            )
        if balance_part > 0:
            conn.execute(
                "UPDATE users SET token_balance = token_balance + ? WHERE id = ?",
                (balance_part, user_id),
            )
        refund_delta = balance_part
        refund_reason = "generation_refund" if balance_part > 0 else "daily_generation_refund"
    elif charge["reason"] == "daily_generation":
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
            json.dumps(
                {
                    "jobId": job_id,
                    "reason": reason,
                    "refunded_ledger_id": charge["id"],
                    "token_cost": token_cost,
                    "daily_part": max(0, int(meta.get("daily_part") or 0)),
                    "balance_part": refund_delta,
                },
                ensure_ascii=False,
            ),
            now_iso,
        ),
    )
    return True


mini_app_url = mini_app_public_url


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


async def telegram_api(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return await request_telegram_bot_api(
            token=TELEGRAM_BOT_TOKEN,
            method=method,
            payload=payload,
        )
    except TelegramConfigurationError as exc:
        raise HTTPException(400, "TELEGRAM_BOT_TOKEN is required for real Telegram API calls.") from exc
    except TelegramApiError as exc:
        raise HTTPException(502, f"Telegram API error: {exc.payload}") from exc


async def max_api(method: str, path: str, payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not MAX_BOT_TOKEN:
        raise HTTPException(400, "MAX_BOT_TOKEN is required for real MAX API calls.")
    return await request_max_api(
        token=MAX_BOT_TOKEN,
        base_url=MAX_API_BASE_URL,
        verify=MAX_HTTP_VERIFY,
        method=method,
        path=path,
        payload=payload,
        params=params,
    )


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
        return telegram_file_url(TELEGRAM_BOT_TOKEN, file_path)
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
    return pending_bot_login_challenges_count(
        _bot_login_runtime(), "max", retention_seconds=BOT_LOGIN_RETENTION_SECONDS
    )


def _bot_login_runtime() -> BotLoginRuntime:
    return BotLoginRuntime(db, _client_ip, _hash_user_agent, hash_token, record_security_event)


def _bot_login_limits() -> BotLoginRateLimits:
    return BotLoginRateLimits(
        BOT_LOGIN_REQUEST_WINDOW_SECONDS, BOT_LOGIN_MAX_REQUESTS_PER_IP_WINDOW,
        BOT_LOGIN_MAX_ACTIVE_PER_IP_PROVIDER, BOT_LOGIN_MAX_GLOBAL_PENDING,
        BOT_LOGIN_RETENTION_SECONDS,
    )


def create_bot_login_challenge(
    provider: Literal["telegram", "max"],
    request: Request,
    *,
    internal_user_id: str | None = None,
) -> tuple[str, str, str]:
    token, nonce = generate_bot_login_token(), generate_bot_login_token()
    try:
        expires_at = security_create_bot_login_challenge(
            _bot_login_runtime(), _bot_login_limits(), provider, request,
            token=token, nonce=nonce, ttl_seconds=BOT_LOGIN_CHALLENGE_TTL_SECONDS,
            internal_user_id=internal_user_id,
            previous_browser_challenge=parse_bot_login_cookie(request),
        )
    except BotLoginAccessError as exc:
        raise HTTPException(429, "Too many bot login requests. Try again later.", headers={"Retry-After": str(exc.retry_after)}) from exc
    return token, nonce, expires_at


def telegram_update_runtime() -> TelegramUpdateRuntime:
    return TelegramUpdateRuntime(
        api_call=telegram_api,
        login_token_from_payload=bot_login_token_from_payload,
        approve_login=lambda token, user: approve_bot_login_challenge("telegram", token, user),
        schedule_avatar=lambda provider_user_id: schedule_avatar_cache("telegram", provider_user_id),
        command_response=lambda text: bot_command_response("telegram", text),
        report_callback_error=lambda exc: print("telegram callback answer error", type(exc).__name__),
    )


async def handle_telegram_update(update: dict[str, Any], send_replies: bool) -> dict[str, Any] | None:
    return await handle_telegram_update_with_runtime(update, send_replies, telegram_update_runtime())


async def handle_telegram_updates(updates: list[dict[str, Any]], send_replies: bool) -> list[dict[str, Any]]:
    return await handle_telegram_updates_with_runtime(updates, send_replies, telegram_update_runtime())


def max_update_runtime() -> MaxUpdateRuntime:
    return MaxUpdateRuntime(
        api_call=lambda method, path, payload, params: max_api(method, path, payload, params),
        login_token_from_payload=bot_login_token_from_payload,
        approve_login=lambda token, user: approve_bot_login_challenge("max", token, user),
        schedule_avatar=lambda provider_user_id: schedule_avatar_cache("max", provider_user_id),
        command_response=lambda text: bot_command_response("max", text),
        now_iso=lambda: datetime.now(timezone.utc).isoformat(),
        set_diagnostic=lambda key, value: BOT_RUNTIME.max_polling_diag.__setitem__(key, value),
        log=print,
    )


async def handle_max_updates(updates: list[dict[str, Any]], send_replies: bool) -> list[dict[str, Any]]:
    return await handle_max_updates_with_runtime(updates, send_replies, max_update_runtime())


async def handle_max_update(update: dict[str, Any], send_replies: bool) -> dict[str, Any] | None:
    return await handle_max_update_with_runtime(update, send_replies, max_update_runtime())


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
    diag = BOT_RUNTIME.max_polling_diag
    now_iso = datetime.now(timezone.utc).isoformat()
    params: dict[str, Any] = {"limit": limit, "timeout": timeout}
    marker = get_bot_polling_cursor("max")
    if marker:
        params["marker"] = marker
    diag.update({
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
        diag.update({
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
        diag.update({
            "lastPollStatus": status,
            "lastPollError": type(exc).__name__,
            "lastRawCount": None,
        })
        print(f"MAX_POLL_RESPONSE status={status or 'error'} rawCount=0 nextMarker=null error={type(exc).__name__}")
        raise


def bot_provider_config(provider: str) -> ProviderConfigSnapshot:
    """Point-in-time provider config read from the canonical main globals.

    Provider configuration stays canonical in main.py for commit 1; workers
    read this snapshot each start/cycle so runtime config changes (admin
    settings) keep their existing dynamic effect. Token stays out of repr.
    """
    if provider == "telegram":
        return ProviderConfigSnapshot(
            provider="telegram",
            mode=BOT_UPDATES_MODE,
            polling_enabled=TELEGRAM_POLLING_ENABLED,
            token=TELEGRAM_BOT_TOKEN,
        )
    if provider == "max":
        return ProviderConfigSnapshot(
            provider="max",
            mode=MAX_UPDATES_MODE,
            polling_enabled=MAX_POLLING_ENABLED,
            token=MAX_BOT_TOKEN,
            api_base_url=MAX_API_BASE_URL,
            webhook_url=MAX_WEBHOOK_URL,
        )
    raise KeyError(f"Unknown bot provider: {provider}")


def build_bot_runtime() -> BotRuntime:
    """Construct the single shared worker runtime (ARCH-BE-BOTS-001, commit 1).

    Owns only mutable worker state (health/tasks/diag/cache). Provider config
    is not mirrored here; it is read on demand via `bot_provider_config`.
    """
    dependencies = BotRuntimeDependencies(
        connect=db,
        record_security_event=record_security_event,
        get_provider_config=bot_provider_config,
        now_iso=lambda: datetime.now(timezone.utc).isoformat(),
        log=print,
    )
    return create_bot_runtime(
        polling_health=PollingHealthRegistry(),
        dependencies=dependencies,
    )


BOT_RUNTIME = build_bot_runtime()


def public_url(path: Path, user_id: str = "demo_user") -> str:
    return storage_public_media_url(path, user_id)


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
        target = storage_resolve_under_root(MEDIA, rel)
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
    out = MEDIA / f"{job_id}.png"
    prepared = ImageOps.exif_transpose(image)
    if prepared.mode not in {"RGB", "RGBA"}:
        prepared = prepared.convert("RGB")
    prepared.thumbnail((GALLERY_IMAGE_MAX_SIDE, GALLERY_IMAGE_MAX_SIDE), Image.Resampling.LANCZOS)
    prepared.save(out, "PNG", optimize=True)
    return out


def optimize_gallery_storage_for_user(
    user_id: str,
    *,
    keep_recent: int = GALLERY_FULL_QUALITY_COUNT,
    limit: int | None = None,
) -> dict[str, int]:
    """Move older active gallery images to a compact, idempotent storage tier."""
    stats = {"checked": 0, "optimized": 0, "bytes_before": 0, "bytes_after": 0, "errors": 0}
    fetch_limit = max(1, int(limit)) if limit is not None else 1_000_000
    with db() as conn:
        ordered_rows = conn.execute(
            f"""
            SELECT id, url, storage_tier FROM images
            WHERE user_id = ? AND {ACTIVE_IMAGE_WHERE}
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,),
        ).fetchall()
    rows = [
        row for row in ordered_rows[max(0, int(keep_recent)) :]
        if str(row["storage_tier"] or "original") == "original"
    ][:fetch_limit]

    for row in rows:
        stats["checked"] += 1
        with db() as conn:
            conn.execute(
                "UPDATE images SET storage_tier = 'optimizing' "
                "WHERE id = ? AND user_id = ? AND COALESCE(storage_tier, 'original') = 'original'",
                (row["id"], user_id),
            )
            claimed = conn.execute("SELECT changes()").fetchone()[0]
        if not claimed:
            continue
        source = local_media_path_from_url(str(row["url"] or ""))
        if source is None or not source.is_file():
            with db() as conn:
                conn.execute("UPDATE images SET storage_tier = 'missing' WHERE id = ?", (row["id"],))
            stats["errors"] += 1
            continue
        target = source.with_name(f"{source.stem}_archive.webp")
        temporary = source.with_name(f".{source.stem}_{uuid.uuid4().hex}.tmp.webp")
        try:
            before = source.stat().st_size
            with Image.open(source) as opened:
                prepared = ImageOps.exif_transpose(opened)
                if prepared.mode not in {"RGB", "RGBA"}:
                    prepared = prepared.convert("RGB")
                prepared.thumbnail((GALLERY_ARCHIVE_MAX_SIDE, GALLERY_ARCHIVE_MAX_SIDE), Image.Resampling.LANCZOS)
                prepared.save(temporary, "WEBP", quality=GALLERY_ARCHIVE_WEBP_QUALITY, method=6)
                optimized_width, optimized_height = prepared.size
            with Image.open(temporary) as verification:
                verification.verify()
            after = temporary.stat().st_size
            now = datetime.now(timezone.utc).isoformat()
            stats["bytes_before"] += before
            if after >= before:
                temporary.unlink(missing_ok=True)
                with db() as conn:
                    conn.execute(
                        "UPDATE images SET storage_tier = 'checked', optimized_at = ?, "
                        "original_bytes = ?, stored_bytes = ? WHERE id = ? AND user_id = ?",
                        (now, before, before, row["id"], user_id),
                    )
                stats["bytes_after"] += before
                continue
            temporary.replace(target)
            new_url = public_url(target, user_id)
            try:
                with db() as conn:
                    current = conn.execute("SELECT thumbnail_url FROM images WHERE id = ?", (row["id"],)).fetchone()
                    thumbnail_url = _row_get(current, "thumbnail_url") if current else None
                    source_name = media_filename_from_url(str(row["url"] or ""))
                    thumbnail_name = media_filename_from_url(thumbnail_url)
                    new_thumbnail_url = new_url if source_name and thumbnail_name == source_name else thumbnail_url
                    conn.execute(
                        "UPDATE images SET url = ?, thumbnail_url = ?, width = ?, height = ?, storage_tier = 'optimized', "
                        "optimized_at = ?, original_bytes = ?, stored_bytes = ? "
                        "WHERE id = ? AND user_id = ? AND storage_tier = 'optimizing'",
                        (new_url, new_thumbnail_url, optimized_width, optimized_height, now, before, after, row["id"], user_id),
                    )
                    changed = conn.execute("SELECT changes()").fetchone()[0]
                if not changed:
                    target.unlink(missing_ok=True)
                    continue
            except Exception:
                target.unlink(missing_ok=True)
                raise
            source.unlink(missing_ok=True)
            cached = images.get(str(row["id"]))
            if cached is not None:
                cached.update(url=new_url, width=optimized_width, height=optimized_height, storageTier="optimized")
            stats["optimized"] += 1
            stats["bytes_after"] += after
        except Exception:
            temporary.unlink(missing_ok=True)
            with db() as conn:
                conn.execute(
                    "UPDATE images SET storage_tier = 'original' WHERE id = ? AND storage_tier = 'optimizing'",
                    (row["id"],),
                )
            stats["errors"] += 1
    return stats


def repair_missing_gallery_thumbnails() -> dict[str, int]:
    """Rebuild missing active thumbnails from an available gallery original."""
    stats = {"checked": 0, "repaired": 0, "unrecoverable": 0, "errors": 0}
    with db() as conn:
        rows = conn.execute(
            f"SELECT id, user_id, url, thumbnail_url FROM images WHERE {ACTIVE_IMAGE_WHERE}"
        ).fetchall()
    for row in rows:
        if local_media_path_from_url(str(row["thumbnail_url"] or "")) is not None:
            continue
        stats["checked"] += 1
        source = local_media_path_from_url(str(row["url"] or ""))
        if source is None:
            stats["unrecoverable"] += 1
            continue
        try:
            thumbnail = create_thumbnail(source)
            thumbnail_url = public_url(thumbnail, str(row["user_id"] or "demo_user"))
            with db() as conn:
                conn.execute(
                    "UPDATE images SET thumbnail_url = ? WHERE id = ? AND user_id = ?",
                    (thumbnail_url, row["id"], row["user_id"]),
                )
            cached = images.get(str(row["id"]))
            if cached is not None:
                cached["thumbnailUrl"] = thumbnail_url
            stats["repaired"] += 1
        except Exception:
            stats["errors"] += 1
    return stats


def recover_missing_optimized_gallery_files() -> dict[str, int]:
    """Restore an unavailable gallery file from the best retained derivative."""
    stats = {"checked": 0, "recovered_from_feed": 0, "recovered_from_thumbnail": 0, "unrecoverable": 0}
    with db() as conn:
        conn.execute("UPDATE images SET storage_tier = 'original' WHERE storage_tier = 'optimizing'")
        rows = conn.execute(
            f"SELECT id, user_id, url, thumbnail_url FROM images WHERE {ACTIVE_IMAGE_WHERE}"
        ).fetchall()
    for row in rows:
        target = local_media_path_from_url(str(row["url"] or ""))
        if target is not None:
            continue
        stats["checked"] += 1
        filename = media_filename_from_url(row["url"])
        if not filename:
            stats["unrecoverable"] += 1
            continue
        target = MEDIA / filename
        candidate = None
        source_kind = ""
        with db() as conn:
            publication = conn.execute(
                "SELECT feed_large_name FROM feed_publications WHERE image_id = ? "
                "AND feed_large_name IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
        if publication:
            feed_path = (MEDIA / str(publication["feed_large_name"])).resolve()
            if feed_path.is_file():
                candidate, source_kind = feed_path, "feed"
        if candidate is None:
            thumbnail = local_media_path_from_url(str(row["thumbnail_url"] or ""))
            if thumbnail is not None:
                candidate, source_kind = thumbnail, "thumbnail"
        if candidate is None:
            stats["unrecoverable"] += 1
            continue
        try:
            with Image.open(candidate) as opened:
                restored = ImageOps.exif_transpose(opened)
                if restored.mode not in {"RGB", "RGBA"}:
                    restored = restored.convert("RGB")
                if target.suffix.lower() == ".webp":
                    restored.save(target, "WEBP", quality=GALLERY_ARCHIVE_WEBP_QUALITY, method=6)
                else:
                    restored.save(target, "PNG", optimize=True)
                width, height = restored.size
            size = target.stat().st_size
            with db() as conn:
                conn.execute(
                    "UPDATE images SET width = ?, height = ?, storage_tier = 'optimized', "
                    "optimized_at = ?, stored_bytes = ? WHERE id = ?",
                    (width, height, datetime.now(timezone.utc).isoformat(), size, row["id"]),
                )
            stats[f"recovered_from_{source_kind}"] += 1
        except Exception:
            target.unlink(missing_ok=True)
            stats["unrecoverable"] += 1
    return stats


def optimize_existing_gallery_storage(limit_per_user: int = 250) -> dict[str, int]:
    totals = {"users": 0, "checked": 0, "optimized": 0, "bytes_before": 0, "bytes_after": 0, "errors": 0}
    with db() as conn:
        user_ids = [
            str(row["user_id"])
            for row in conn.execute(
                f"SELECT DISTINCT user_id FROM images WHERE user_id IS NOT NULL AND {ACTIVE_IMAGE_WHERE}"
            ).fetchall()
        ]
    for user_id in user_ids:
        result = optimize_gallery_storage_for_user(user_id, limit=limit_per_user)
        totals["users"] += 1
        for key in ("checked", "optimized", "bytes_before", "bytes_after", "errors"):
            totals[key] += result[key]
    return totals


def delete_admin_secret(key: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM admin_secrets WHERE key = ?", (key,))
    _admin_models_page_cache["ts"] = 0.0
    _admin_models_page_cache["data"] = None


def _bot_secret_value(name: str, env_name: str) -> str:
    return os.getenv(env_name, "").strip() or OPENROUTER_SECRET_STORE.get(name)


def _bot_secret_source(name: str, env_name: str) -> str:
    if os.getenv(env_name, "").strip():
        return "environment"
    return "dpapi" if OPENROUTER_SECRET_STORE.exists(name) else "none"


def _bot_secret_updated_at(name: str) -> str | None:
    path = OPENROUTER_SECRET_STORE.path_for(name)
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        value = document.get("updatedAt")
        return str(value) if value else None
    except Exception:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def bot_integrations_config() -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            "SELECT value_json FROM admin_settings WHERE key = 'bot_integrations'"
        ).fetchone()
    stored = safe_json_load(row["value_json"]) if row else {}
    try:
        return normalize_bot_integrations(stored, production=is_production_like_env())
    except ValueError:
        return normalize_bot_integrations(DEFAULT_BOT_INTEGRATIONS, production=False)


def save_bot_integrations_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_bot_integrations(
        config,
        production=is_production_like_env(),
    )
    with db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('bot_integrations', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (
                json.dumps(normalized, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return normalized


def has_saved_bot_integrations_config() -> bool:
    with db() as conn:
        row = conn.execute(
            "SELECT 1 FROM admin_settings WHERE key = 'bot_integrations'"
        ).fetchone()
    return row is not None


def telegram_admin_token() -> str:
    return _bot_secret_value(TELEGRAM_BOT_SECRET_NAME, "TELEGRAM_BOT_TOKEN")


def telegram_admin_webhook_secret() -> str:
    return _bot_secret_value(
        TELEGRAM_WEBHOOK_SECRET_NAME,
        "TELEGRAM_WEBHOOK_SECRET",
    )


def max_admin_token() -> str:
    return _bot_secret_value(MAX_BOT_SECRET_NAME, "MAX_BOT_TOKEN")


def max_admin_webhook_secret() -> str:
    return _bot_secret_value(MAX_WEBHOOK_SECRET_NAME, "MAX_WEBHOOK_SECRET")


def _save_bot_secret(name: str, value: str) -> None:
    clean = str(value or "").strip()
    if not clean:
        raise SecretStoreError("Secret value must not be empty.")
    OPENROUTER_SECRET_STORE.set(name, clean)
    if not hmac.compare_digest(OPENROUTER_SECRET_STORE.get(name), clean):
        raise SecretStoreError("DPAPI secret readback verification failed.")


def apply_saved_bot_runtime_configuration() -> dict[str, Any]:
    global BOT_UPDATES_MODE, BOT_MODE, TELEGRAM_POLLING_ENABLED
    global MAX_UPDATES_MODE, MAX_POLLING_ENABLED, MAX_API_BASE_URL, MAX_WEBHOOK_URL
    global TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, TELEGRAM_BOT_USERNAME, TELEGRAM_BOT_DEEP_LINK_BASE, MAX_BOT_TOKEN, MAX_WEBHOOK_SECRET, MAX_BOT_DEEP_LINK_BASE
    source = "environment"
    if has_saved_bot_integrations_config():
        config = bot_integrations_config()
        TELEGRAM_BOT_TOKEN = telegram_admin_token()
        TELEGRAM_WEBHOOK_SECRET = telegram_admin_webhook_secret()
        MAX_BOT_TOKEN = max_admin_token()
        MAX_WEBHOOK_SECRET = max_admin_webhook_secret()
        BOT_UPDATES_MODE = str(config["telegram"]["mode"])
        BOT_MODE = BOT_UPDATES_MODE
        TELEGRAM_POLLING_ENABLED = bool(config["telegram"]["pollingEnabled"])
        TELEGRAM_BOT_USERNAME, TELEGRAM_BOT_DEEP_LINK_BASE = str(config["telegram"]["botUsername"] or os.getenv("TELEGRAM_BOT_USERNAME", "")), str(config["telegram"]["deepLinkBase"] or os.getenv("TELEGRAM_BOT_DEEP_LINK_BASE", ""))
        MAX_UPDATES_MODE = str(config["max"]["mode"])
        MAX_POLLING_ENABLED = bool(config["max"]["pollingEnabled"])
        MAX_API_BASE_URL, MAX_BOT_DEEP_LINK_BASE = str(config["max"]["apiBaseUrl"]), str(config["max"]["deepLinkBase"] or os.getenv("MAX_BOT_DEEP_LINK_BASE", ""))
        MAX_WEBHOOK_URL = configured_bot_webhook_url(config, "max")
        source = "admin_settings"
    return {
        "source": source,
        "telegramMode": BOT_UPDATES_MODE,
        "maxMode": MAX_UPDATES_MODE,
        "telegramTokenConfigured": bool(TELEGRAM_BOT_TOKEN),
        "maxTokenConfigured": bool(MAX_BOT_TOKEN),
    }


def openrouter_api_key_source() -> str:
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        return "env"
    if OPENROUTER_SECRET_STORE.exists(OPENROUTER_SECRET_NAME):
        return "dpapi"
    return "none"


def openrouter_api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip() or OPENROUTER_SECRET_STORE.get(OPENROUTER_SECRET_NAME)


def migrate_openrouter_secret_from_sqlite() -> str:
    with db() as conn:
        return migrate_sqlite_secret_to_store(conn, OPENROUTER_SECRET_STORE, OPENROUTER_SECRET_NAME)


def save_openrouter_api_key(value: str) -> None:
    OPENROUTER_SECRET_STORE.set(OPENROUTER_SECRET_NAME, value)
    verified = OPENROUTER_SECRET_STORE.get(OPENROUTER_SECRET_NAME)
    if not hmac.compare_digest(verified.encode("utf-8"), value.encode("utf-8")):
        raise SecretStoreError("OpenRouter DPAPI secret readback verification failed.")
    delete_admin_secret(OPENROUTER_SECRET_NAME)
    invalidate_openrouter_admin_caches(authorization_changed=True)


def delete_openrouter_api_key() -> None:
    OPENROUTER_SECRET_STORE.delete(OPENROUTER_SECRET_NAME)
    delete_admin_secret(OPENROUTER_SECRET_NAME)
    invalidate_openrouter_admin_caches(authorization_changed=True)


def smtp_password() -> str:
    return os.getenv("SMTP_PASSWORD", "").strip() or OPENROUTER_SECRET_STORE.get(SMTP_SECRET_NAME)


def smtp_config() -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT value_json FROM admin_settings WHERE key = 'mail_provider'").fetchone()
    value = safe_json_load(row["value_json"]) if row else {}
    current = value if isinstance(value, dict) and value.get("provider") == "smtp" else {}
    return {
        "provider": "smtp",
        "source": "admin" if current else "environment",
        "host": str(current.get("host") or os.getenv("SMTP_HOST", "smtp.mail.ru")).strip(),
        "port": int(current.get("port") or os.getenv("SMTP_PORT", "465")),
        "username": str(current.get("username") or os.getenv("SMTP_USERNAME", "")).strip(),
        "sender_name": str(current.get("sender_name") or os.getenv("SMTP_SENDER_NAME", "ИЗО АСА")).strip(),
        "sender_email": str(current.get("sender_email") or os.getenv("SMTP_SENDER_EMAIL", "")).strip(),
        "use_ssl": bool(current.get("use_ssl", True)),
        "verified_at": str(current.get("verified_at") or "").strip() or None,
        "last_error": str(current.get("last_error") or "").strip() or None,
    }


def smtp_configured(config: dict[str, Any] | None = None) -> bool:
    current = config if config is not None else smtp_config()
    return bool(smtp_password() and current.get("host") and current.get("username") and current.get("sender_email"))


def smtp_ready(config: dict[str, Any] | None = None) -> bool:
    current = config if config is not None else smtp_config()
    if not smtp_configured(current):
        return False
    # Environment credentials are provisioned outside the admin UI and keep
    # their previous ready semantics. Credentials entered in the UI become
    # active only after a successful SMTP handshake.
    return current.get("source") == "environment" or bool(current.get("verified_at"))


def smtp_connection_config(config: dict[str, Any], password: str | None = None) -> SmtpConfig:
    return SmtpConfig(
        host=str(config.get("host") or "smtp.mail.ru"),
        port=int(config.get("port") or 465),
        username=str(config.get("username") or ""),
        password=password if password is not None else smtp_password(),
        use_ssl=bool(config.get("use_ssl", True)),
    )


def save_smtp_config(
    req: AdminMailConfigV2Request | AdminMailVerifyV2Request,
    *,
    verified_at: str | None = None,
    last_error: str | None = None,
) -> None:
    username = normalize_email(req.username)
    sender_email = normalize_email(req.sender_email)
    if not username or not sender_email:
        raise ValueError("Введите корректный адрес почтового ящика.")
    if username != sender_email:
        raise ValueError("Почтовый ящик и email отправителя должны совпадать.")
    if req.password:
        save_smtp_password(req.password)
    with db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('mail_provider', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (
                json.dumps(
                    {
                        "provider": "smtp",
                        "host": req.host.strip(),
                        "port": req.port,
                        "username": username,
                        "sender_name": req.sender_name.strip(),
                        "sender_email": sender_email,
                        "use_ssl": bool(req.use_ssl),
                        "verified_at": verified_at,
                        "last_error": last_error,
                    },
                    ensure_ascii=False,
                ),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def save_smtp_password(value: str) -> None:
    clean = value.strip()
    if not clean:
        raise SecretStoreError("Пароль приложения пуст.")
    OPENROUTER_SECRET_STORE.set(SMTP_SECRET_NAME, clean)
    verified = OPENROUTER_SECRET_STORE.get(SMTP_SECRET_NAME)
    if not hmac.compare_digest(verified.encode("utf-8"), clean.encode("utf-8")):
        raise SecretStoreError("Не удалось проверить сохраненный пароль приложения.")


def unisender_api_key() -> str:
    return os.getenv("UNISENDER_API_KEY", "").strip() or OPENROUTER_SECRET_STORE.get(UNISENDER_SECRET_NAME)


def unisender_config() -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT value_json FROM admin_settings WHERE key = 'mail_provider_unisender'").fetchone()
    value = safe_json_load(row["value_json"]) if row else {}
    return unisender_service.build_unisender_config(value, os.environ)


def unisender_configured(config: dict[str, Any] | None = None) -> bool:
    current = config if config is not None else unisender_config()
    return unisender_service.is_unisender_configured(unisender_api_key(), current)


def unisender_ready(config: dict[str, Any] | None = None) -> bool:
    current = config if config is not None else unisender_config()
    return unisender_service.is_unisender_ready(unisender_api_key(), current)


def save_unisender_api_key(value: str) -> None:
    clean = value.strip()
    if not clean:
        raise SecretStoreError("API-ключ UniSender пуст.")
    OPENROUTER_SECRET_STORE.set(UNISENDER_SECRET_NAME, clean)
    verified = OPENROUTER_SECRET_STORE.get(UNISENDER_SECRET_NAME)
    if not hmac.compare_digest(verified.encode("utf-8"), clean.encode("utf-8")):
        raise SecretStoreError("Не удалось проверить сохраненный API-ключ UniSender.")


def save_unisender_config(
    *,
    sender_name: str,
    sender_email: str,
    list_id: int,
    verified_at: str | None,
    last_error: str | None,
) -> None:
    email = normalize_email(sender_email)
    if not email:
        raise ValueError("Введите корректный email отправителя.")
    if list_id < 0:
        raise ValueError("Некорректный список контактов UniSender.")
    _save_setting("mail_provider_unisender", {
        "provider": "unisender",
        "sender_name": sender_name.strip() or "ИЗО АСА",
        "sender_email": email,
        "list_id": int(list_id),
        "verified_at": verified_at,
        "last_error": last_error,
    })


def send_transactional_email(destination: str, subject: str, html: str) -> str:
    recipient = normalize_email(destination)
    uni_config = unisender_config()
    smtp_current = smtp_config()
    return unisender_service.deliver_transactional_email(
        recipient, subject, html, unisender_api_key(),
        uni_config if unisender_ready(uni_config) else None,
        smtp_connection_config(smtp_current) if smtp_ready(smtp_current) else None,
        smtp_current, send_unisender_email, send_smtp_email,
    )
ADMIN_NOTIFICATION_DELIVERY_WORKER = AdminNotificationDeliveryWorker()
send_admin_telegram_notification, send_admin_email_notification = build_admin_delivery_transports(telegram_api=telegram_api, send_transactional_email=send_transactional_email, html_escape=html_escape)
SOCIAL_DELIVERY_WORKER = SocialDeliveryWorker()
send_social_telegram_publication = build_telegram_social_sender(telegram_api=request_telegram_bot_api, telegram_image_api=send_telegram_photo_url, telegram_video_api=send_telegram_video_url, settings_getter=lambda: _saved_setting("social_syndication"), token_getter=lambda: OPENROUTER_SECRET_STORE.get("social_telegram_access_token"), public_site_url_getter=lambda: os.getenv("PUBLIC_SITE_URL", ""))
async def send_social_max_api(*, token: str, target_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await request_max_api(token=token, base_url=MAX_API_BASE_URL, verify=MAX_HTTP_VERIFY,
                                 method="POST", path="/messages", params={"chat_id": target_id}, payload=payload)
send_social_max_publication = build_max_social_sender(max_api=send_social_max_api, max_video_publisher=lambda **kwargs: publish_max_video(max_api=request_max_api, api_base_url=MAX_API_BASE_URL, verify=MAX_HTTP_VERIFY, **kwargs), settings_getter=lambda: _saved_setting("social_syndication"), token_getter=lambda: OPENROUTER_SECRET_STORE.get("social_max_access_token"), public_site_url_getter=lambda: os.getenv("PUBLIC_SITE_URL", ""))
send_social_vk_publication = build_vk_social_sender(vk_api=request_vk_api, vk_image_publisher=publish_vk_wall_image, vk_video_publisher=publish_vk_wall_video, settings_getter=lambda: _saved_setting("social_syndication"), token_getter=lambda: OPENROUTER_SECRET_STORE.get("social_vk_access_token"), media_token_getter=lambda: OPENROUTER_SECRET_STORE.get("social_vk_media_access_token"), public_site_url_getter=lambda: os.getenv("PUBLIC_SITE_URL", "")); send_social_vk_story = build_vk_story_sender(settings_getter=lambda: _saved_setting("social_syndication"), media_token_getter=lambda: OPENROUTER_SECRET_STORE.get("social_vk_media_access_token"), public_site_url_getter=lambda: os.getenv("PUBLIC_SITE_URL", ""), vk_story_publisher=lambda **kwargs: publish_vk_story(vk_api=request_vk_api, **kwargs))
delete_social_publication = build_social_deletion_sender(settings_getter=lambda: _saved_setting("social_syndication"), secret_getter=OPENROUTER_SECRET_STORE.get, telegram_api=request_telegram_bot_api, max_api=lambda **kwargs: request_max_api(base_url=MAX_API_BASE_URL, verify=MAX_HTTP_VERIFY, **kwargs), vk_api=request_vk_api)
async def send_social_test(*, network: str, token: str, target_id: str, text: str) -> dict[str, Any]:
    if network == "telegram":
        return await request_telegram_bot_api(token=token, method="sendMessage", payload={"chat_id": target_id, "text": text})
    if network == "max":
        return await request_max_api(token=token, base_url=MAX_API_BASE_URL, verify=MAX_HTTP_VERIFY, method="POST", path="/messages", params={"chat_id": target_id}, payload={"text": text})
    if network == "vk":
        return await request_vk_api(token=token, method="wall.post", params={"owner_id": f"-{target_id.lstrip('-')}", "from_group": 1, "message": text})
    raise RuntimeError("Неподдерживаемая тестовая доставка.")
def yookassa_secret_key() -> str:
    return os.getenv("YOOKASSA_SECRET_KEY", "").strip() or OPENROUTER_SECRET_STORE.get(YOOKASSA_SECRET_NAME)
def yookassa_config() -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT value_json FROM admin_settings WHERE key = 'yookassa'").fetchone()
    value = safe_json_load(row["value_json"]) if row else {}
    return value if isinstance(value, dict) else {}
def yookassa_ready(config: dict[str, Any] | None = None) -> bool:
    current = config if config is not None else yookassa_config()
    return bool(current.get("shop_id") and yookassa_secret_key())


def yookassa_checkout_ready(config: dict[str, Any] | None = None) -> bool:
    current = config if config is not None else yookassa_config()
    vat_code = current.get("receipt_vat_code")
    return yookassa_ready(current) and isinstance(vat_code, int) and 1 <= vat_code <= 12


_SIMULATED_PAYMENT_PROVIDER: SimulatedPaymentProvider | None = None


def billing_simulator_enabled() -> bool:
    return env_bool("BILLING_SIMULATOR_ENABLED", False) and not is_production_like_env()


def simulated_payment_provider() -> SimulatedPaymentProvider:
    global _SIMULATED_PAYMENT_PROVIDER
    if not billing_simulator_enabled():
        raise PaymentProviderError("Payment simulator is disabled.")
    if _SIMULATED_PAYMENT_PROVIDER is None:
        _SIMULATED_PAYMENT_PROVIDER = SimulatedPaymentProvider(
            enabled=True,
            app_env=APP_ENV,
            confirmation_base_url=os.getenv("PUBLIC_SITE_URL", "http://127.0.0.1:5173/payment"),
        )
    return _SIMULATED_PAYMENT_PROVIDER


def active_billing_provider() -> str | None:
    if yookassa_checkout_ready():
        return "yookassa"
    if billing_simulator_enabled():
        return "simulator"
    return None


def billing_payments_available() -> bool:
    return active_billing_provider() is not None


DEFAULT_LEGAL_SETTINGS: dict[str, Any] = {
    "brand_name": "ИЗО АСА",
    "seller_name": "",
    "seller_status": "",
    "inn": "",
    "ogrn": "",
    "legal_address": "",
    "support_email": "mail@alikinas.ru",
    "support_phone": "",
    "support_hours": "Ежедневно, 10:00–20:00 по московскому времени",
    "site_url": "https://izo.alikinas.ru",
    "service_description": "Онлайн-сервис генерации и редактирования изображений с использованием моделей искусственного интеллекта.",
    "offer_version": "2026-07-15",
}


def normalize_legal_settings(source: Any) -> dict[str, Any]:
    raw = source if isinstance(source, dict) else {}
    limits = {
        "brand_name": 120, "seller_name": 300, "seller_status": 160, "inn": 12,
        "ogrn": 15, "legal_address": 500, "support_email": 200,
        "support_phone": 80, "support_hours": 200, "site_url": 300,
        "service_description": 1000, "offer_version": 40,
    }
    result: dict[str, Any] = {}
    for key, limit in limits.items():
        value = str(raw.get(key, DEFAULT_LEGAL_SETTINGS[key]) or "").strip()
        result[key] = value[:limit]
    if result["support_email"] and not normalize_email(result["support_email"]):
        result["support_email"] = ""
    if result["inn"] and not re.fullmatch(r"\d{10}|\d{12}", result["inn"]):
        result["inn"] = ""
    if result["ogrn"] and not re.fullmatch(r"\d{13}|\d{15}", result["ogrn"]):
        result["ogrn"] = ""
    return result


def legal_settings(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    def load(current_conn: sqlite3.Connection) -> dict[str, Any]:
        row = current_conn.execute("SELECT value_json FROM admin_settings WHERE key = 'legal'").fetchone()
        return normalize_legal_settings(safe_json_load(row["value_json"]) if row else {})
    if conn is not None:
        return load(conn)
    with db() as current_conn:
        return load(current_conn)


def legal_readiness(settings: dict[str, Any]) -> dict[str, Any]:
    labels = {
        "seller_name": "полное имя или наименование исполнителя",
        "seller_status": "правовой статус исполнителя",
        "inn": "ИНН",
        "legal_address": "адрес исполнителя",
        "support_email": "email поддержки",
    }
    missing = [label for key, label in labels.items() if not str(settings.get(key) or "").strip()]
    return {"ready": not missing, "missing": missing}


def seller_is_self_employed(settings: dict[str, Any] | None = None) -> bool:
    current = settings or legal_settings()
    status = str(current.get("seller_status") or "").strip().lower()
    return "самозанят" in status or re.search(r"(?:^|\W)нпд(?:$|\W)", status) is not None


def billing_profile_email(conn: sqlite3.Connection, internal_user_id: str) -> str:
    row = conn.execute(
        "SELECT receipt_email FROM user_billing_profiles WHERE internal_user_id = ?",
        (internal_user_id,),
    ).fetchone()
    return str(row["receipt_email"] or "").strip() if row else ""


def save_billing_profile_email(
    conn: sqlite3.Connection,
    internal_user_id: str,
    email: str,
    *,
    updated_at: str,
) -> None:
    conn.execute(
        "INSERT INTO user_billing_profiles (internal_user_id, receipt_email, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(internal_user_id) DO UPDATE SET receipt_email=excluded.receipt_email, updated_at=excluded.updated_at",
        (internal_user_id, email, updated_at),
    )


def save_yookassa_config(req: AdminYooKassaConfigV2Request) -> None:
    if req.secret_key:
        OPENROUTER_SECRET_STORE.set(YOOKASSA_SECRET_NAME, req.secret_key.strip())
    with db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('yookassa', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (
                json.dumps(
                    {
                        "provider": "yookassa",
                        "shop_id": req.shop_id.strip(),
                        "test_mode": bool(req.test_mode),
                        "receipt_vat_code": req.receipt_vat_code,
                        "payment_subject": req.payment_subject.strip(),
                        "last_check_ok": False,
                        "last_checked_at": None,
                        "last_check_message": "Настройки изменены. Проверьте подключение заново.",
                    },
                    ensure_ascii=False,
                ),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def save_yookassa_connection_check(*, ok: bool, message: str) -> dict[str, Any]:
    config = yookassa_config()
    checked_at = datetime.now(timezone.utc).isoformat()
    config.update(
        {
            "last_check_ok": bool(ok),
            "last_checked_at": checked_at,
            "last_check_message": str(message).strip()[:500],
        }
    )
    with db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('yookassa', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (json.dumps(config, ensure_ascii=False), checked_at),
        )
    return config


def public_site_url(request: Request) -> str:
    configured = os.getenv("PUBLIC_SITE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    return "https://izo.alikinas.ru"


OPENROUTER_GENERATION_MODES = {"text_to_image", "image_to_image", "edit"}
OPENROUTER_VIDEO_MODES = ("text_to_video", "image_to_video", "first_last_frame", "reference_to_video")
OPENROUTER_CAPABILITY_CACHE_TTL_SECONDS = 6 * 60 * 60
OPENROUTER_KEY_STATUS_CACHE_TTL_SECONDS = 30
_openrouter_capability_cache: dict[str, Any] = {"ts": 0.0, "models": []}
_openrouter_video_catalog_cache: dict[str, Any] = {"ts": 0.0, "models": []}
_openrouter_key_status_cache: dict[str, Any] = {"ts": 0.0, "data": None, "keyMarker": None}
_openrouter_catalog_refresh_task: asyncio.Task[Any] | None = None
_openrouter_catalog_state: dict[str, Any] = {
    "refreshing": False,
    "lastAttemptAt": None,
    "lastSuccessAt": None,
    "lastError": None,
    "source": "fallback",
    "modelCount": 0,
    "videoModelCount": 0,
}


def invalidate_openrouter_admin_caches(*, authorization_changed: bool = False) -> None:
    models_page_cache = globals().get("_admin_models_page_cache")
    if isinstance(models_page_cache, dict):
        models_page_cache["ts"] = {}
        models_page_cache["data"] = {}
    _openrouter_key_status_cache.update({"ts": 0.0, "data": None, "keyMarker": None})
    if authorization_changed:
        # Keep the last successful catalog available, but make it immediately stale.
        _openrouter_capability_cache["ts"] = 0.0
        _openrouter_video_catalog_cache["ts"] = 0.0


def fallback_openrouter_capabilities() -> list[dict[str, Any]]:
    price_catalog = globals().get("OPENROUTER_PRICE_CATALOG")
    if not isinstance(price_catalog, dict):
        return []
    return [
        {
            "id": model.id,
            "name": model.name,
            "description": "Встроенный резервный каталог. Возможности endpoint будут уточнены в фоне.",
            "inputModalities": ["image", "text"],
            "outputModalities": ["image"],
            "parameters": [],
            "parameterDescriptors": {},
            "maxInputReferences": 1,
            "supportsStreaming": False,
            "modes": ["image_to_image", "paint", "text_to_image"],
            "features": {
                "seed": False,
                "quality": False,
                "aspectRatio": True,
                "resolution": True,
                "transparentBackground": False,
                "multipleOutputs": False,
            },
            "endpointVerified": False,
            "catalogSource": "fallback",
        }
        for model in price_catalog.values()
    ]


def openrouter_key_status_snapshot() -> dict[str, Any]:
    cached = _openrouter_key_status_cache.get("data")
    if isinstance(cached, dict):
        return dict(cached)
    configured = bool(openrouter_api_key())
    return {
        "configured": configured,
        "source": openrouter_api_key_source(),
        "ok": False,
        "pending": configured,
        "error": None if configured else "OPENROUTER_API_KEY не задан",
    }


def openrouter_catalog_snapshot() -> dict[str, Any]:
    now = time.monotonic()
    cached_models = _openrouter_capability_cache.get("models")
    cached_videos = _openrouter_video_catalog_cache.get("models")
    image_models = list(cached_models) if isinstance(cached_models, list) and cached_models else fallback_openrouter_capabilities()
    video_models = list(cached_videos) if isinstance(cached_videos, list) else []
    image_ts = float(_openrouter_capability_cache.get("ts") or 0)
    source = "live-cache" if cached_models else "fallback"
    return {
        "models": image_models,
        "videoModels": video_models,
        "meta": {
            **_openrouter_catalog_state,
            "source": source,
            "modelCount": len(image_models),
            "videoModelCount": len(video_models),
            "cacheAgeSeconds": int(max(0.0, now - image_ts)) if image_ts else None,
        },
    }


def openrouter_catalog_refresh_needed(snapshot: dict[str, Any] | None = None) -> bool:
    current = snapshot or openrouter_catalog_snapshot()
    meta = current.get("meta") if isinstance(current, dict) else {}
    age = meta.get("cacheAgeSeconds") if isinstance(meta, dict) else None
    return (
        not _openrouter_capability_cache.get("models")
        or age is None
        or int(age) >= OPENROUTER_CAPABILITY_CACHE_TTL_SECONDS
        or bool(openrouter_key_status_snapshot().get("pending"))
    )


async def refresh_openrouter_catalog() -> dict[str, Any]:
    _openrouter_catalog_state.update(
        {
            "refreshing": True,
            "lastAttemptAt": datetime.now(timezone.utc).isoformat(),
            "lastError": None,
        }
    )
    results = await asyncio.gather(
        fetch_openrouter_key_status(force=True),
        fetch_openrouter_image_capabilities(force=True),
        fetch_openrouter_video_catalog(force=True),
        return_exceptions=True,
    )
    errors = [
        safe_bot_error(result)
        for result in results
        if isinstance(result, BaseException)
    ]
    successful_catalog = any(
        not isinstance(result, BaseException) and isinstance(result, list)
        for result in results[1:]
    )
    if successful_catalog:
        _openrouter_catalog_state["lastSuccessAt"] = datetime.now(timezone.utc).isoformat()
        _openrouter_catalog_state["source"] = "live-api"
    _openrouter_catalog_state.update(
        {
            "refreshing": False,
            "lastError": "; ".join(errors) if errors else None,
            "modelCount": len(_openrouter_capability_cache.get("models") or []),
            "videoModelCount": len(_openrouter_video_catalog_cache.get("models") or []),
        }
    )
    models_page_cache = globals().get("_admin_models_page_cache")
    if isinstance(models_page_cache, dict):
        models_page_cache["ts"] = {}
        models_page_cache["data"] = {}
    return openrouter_catalog_snapshot()


def schedule_openrouter_catalog_refresh() -> bool:
    global _openrouter_catalog_refresh_task
    if _openrouter_catalog_refresh_task and not _openrouter_catalog_refresh_task.done():
        return False
    _openrouter_catalog_refresh_task = asyncio.create_task(refresh_openrouter_catalog())
    return True


def openrouter_model_capability(model: dict[str, Any]) -> dict[str, Any]:
    return normalize_openrouter_model_capability(model)


def openrouter_endpoint_capability(model: dict[str, Any], endpoint: dict[str, Any]) -> dict[str, Any]:
    return normalize_openrouter_endpoint_capability(model, endpoint)


async def fetch_openrouter_image_capabilities(force: bool = False) -> list[dict[str, Any]]:
    now = time.monotonic()
    cached = _openrouter_capability_cache.get("models")
    if not force and isinstance(cached, list) and cached and now - float(_openrouter_capability_cache.get("ts") or 0) < OPENROUTER_CAPABILITY_CACHE_TTL_SECONDS:
        return cached
    headers = openrouter_headers() if openrouter_api_key() else {"Content-Type": "application/json"}
    documents = await fetch_openrouter_image_model_documents(
        base_url=OPENROUTER_BASE_URL,
        headers=headers,
        timeout_seconds=20,
        max_concurrency=8,
    )
    models: list[dict[str, Any]] = []
    for document in documents:
        item = document["model"]
        base = openrouter_model_capability(item)
        candidates = document.get("endpoints") if isinstance(document.get("endpoints"), list) else []
        if document.get("endpoint_status", 500) is not None and document.get("endpoint_status", 500) < 400 and candidates:
            selected = max(candidates, key=lambda entry: len(entry.get("supported_parameters") or {}))
            models.append(openrouter_endpoint_capability(item, selected))
        else:
            models.append({**base, "endpointVerified": False})
    models.sort(key=lambda item: (item["name"].lower(), item["id"]))
    _openrouter_capability_cache.update({"ts": now, "models": models})
    return models


async def fetch_openrouter_video_catalog(force: bool = False) -> list[dict[str, Any]]:
    now = time.monotonic()
    cached = _openrouter_video_catalog_cache.get("models")
    if not force and isinstance(cached, list) and cached and now - float(_openrouter_video_catalog_cache.get("ts") or 0) < OPENROUTER_CAPABILITY_CACHE_TTL_SECONDS:
        return cached
    headers = openrouter_headers() if openrouter_api_key() else {"Content-Type": "application/json"}
    models = await fetch_openrouter_video_models(
        base_url=OPENROUTER_BASE_URL,
        headers=headers,
        timeout_seconds=20,
    )
    _openrouter_video_catalog_cache.update({"ts": now, "models": models})
    return models


def openrouter_prompt_influence_instruction(strength: float) -> str:
    return image_edit_influence_instruction(strength)


def openrouter_reference_value(source: str | None) -> str:
    return resolve_openrouter_reference_value(
        source,
        local_path_resolver=local_media_path_from_url,
    )


def build_openrouter_image_body(payload: GenerateRequest, model: str, request_plan: dict[str, Any], capability: dict[str, Any]) -> dict[str, Any]:
    return build_openrouter_image_request_body(
        payload,
        model,
        request_plan,
        capability,
        reference_resolver=openrouter_reference_value,
    )


def openrouter_headers() -> dict[str, str]:
    headers = {"Authorization": f"Bearer {openrouter_api_key()}", "Content-Type": "application/json"}
    referer = os.getenv("OPENROUTER_SITE_URL", "").strip()
    title = os.getenv("OPENROUTER_SITE_NAME", "IZO ASA").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-Title"] = title
    return headers


_prompt_improve_semaphore = asyncio.Semaphore(max(1, min(8, int(os.getenv("PROMPT_IMPROVE_CONCURRENCY", "2")))))

PROMPT_IMPROVE_MODE_RULES = {
    "text": "Составь подробный промпт для генерации изображения: уточни главный объект, сцену, композицию, освещение, материалы и визуальное качество, не меняя исходную идею.",
    "i2i": "Чётко опиши требуемое преобразование и обязательно сохрани элементы исходного изображения, которые пользователь не просил менять.",
    "edit": "Уточни, как объединить основу и референсы. Не придумывай роли изображений, которые пользователь не указал.",
    "sketch": "Опиши превращение эскиза в законченное изображение с сохранением композиции, линий и читаемых форм.",
    "mask": "Опиши только изменение внутри выделенной маски и потребуй естественного соединения с нетронутой частью изображения.",
    "outpaint": "Опиши логичное продолжение сцены за границами кадра с сохранением перспективы, света и целостности пространства.",
    "remove_bg": "Опиши аккуратное сохранение краёв, волос и мелких деталей. Не добавляй посторонних изменений главного объекта.",
    "text_to_video": "Составь цельный промпт для видео: опиши сцену, действия, движение камеры, темп, свет и атмосферу. Не добавляй новых героев, предметы или события, которых пользователь не просил.",
    "image_to_video": "Опиши движение исходного кадра: действия объектов, движение камеры и естественную динамику. Обязательно сохрани внешность, композицию и детали загруженного изображения.",
    "first_last_frame": "Опиши логичный переход между начальным и конечным кадрами, движение объектов и камеры. Не меняй содержимое граничных кадров и не придумывай лишние промежуточные события.",
    "reference_to_video": "Опиши ролик по загруженным референсам, сохраняя их персонажей, окружение, предметы и стиль. Не назначай референсам роли, которые пользователь не указал.",
}

DEFAULT_ASSISTANT_MODELS_CONFIG: dict[str, Any] = {
    "voice": {
        "localModel": "gemma4:12b",
        "qwenModel": DEFAULT_QWEN_ASR_MODEL,
        "qwenBaseUrl": DEFAULT_QWEN_ASR_BASE_URL,
        "apiModel": "google/gemini-3.1-flash-lite",
        "route": "local",
        "queueTimeoutSeconds": 1,
        "requestTimeoutSeconds": 45,
        "minRecordingSeconds": 1,
    },
    "improve": {
        "route": "auto",
        "localModel": "gemma4:31b-cloud",
        "apiModel": "deepseek/deepseek-v4-flash",
        "localTimeoutSeconds": 10,
        "apiTimeoutSeconds": 10,
        "systemPrompt": (
            "Ты улучшаешь пользовательские промпты для студии генерации изображений и видео. Сохраняй исходный смысл, главные объекты, "
            "их количество, идентичность персонажей, требуемые действия и язык пользователя. Можно уточнять композицию, свет и "
            "визуальное качество, только если это не меняет запрос. Не придумывай одежду, внешность, позу, место, марки камер, "
            "объективы, новые предметы или события. Не добавляй объяснения, служебный текст и Markdown."
        ),
        "modePrompts": dict(PROMPT_IMPROVE_MODE_RULES),
    },
}


def assistant_models_config() -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT value_json FROM admin_settings WHERE key = 'assistant_models'").fetchone()
    stored = safe_json_load(row["value_json"]) if row else {}
    stored = stored if isinstance(stored, dict) else {}
    voice = {**DEFAULT_ASSISTANT_MODELS_CONFIG["voice"], **(stored.get("voice") if isinstance(stored.get("voice"), dict) else {})}
    if voice.get("localModel") == "qwen3-asr:1.7b":
        voice["localModel"] = "gemma4:12b"
    voice["route"] = voice["route"] if voice.get("route") in {"local", "qwen", "api", "auto"} else "local"
    voice["qwenModel"] = str(voice.get("qwenModel") or DEFAULT_QWEN_ASR_MODEL).strip()
    voice["qwenBaseUrl"] = str(voice.get("qwenBaseUrl") or DEFAULT_QWEN_ASR_BASE_URL).strip().rstrip("/")
    improve = {**DEFAULT_ASSISTANT_MODELS_CONFIG["improve"], **(stored.get("improve") if isinstance(stored.get("improve"), dict) else {})}
    improve["modePrompts"] = {
        **DEFAULT_ASSISTANT_MODELS_CONFIG["improve"]["modePrompts"],
        **(improve.get("modePrompts") if isinstance(improve.get("modePrompts"), dict) else {}),
    }
    improve["route"] = improve["route"] if improve.get("route") in {"local", "api", "auto"} else "api"
    return {"voice": voice, "improve": improve}


async def ollama_models_status() -> dict[str, Any]:
    return await fetch_ollama_models_status()


async def qwen_asr_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or assistant_models_config()["voice"]
    return await fetch_qwen_asr_status(base_url=str(config.get("qwenBaseUrl") or DEFAULT_QWEN_ASR_BASE_URL))


_openrouter_text_model_cache: dict[str, Any] = {"ts": 0.0, "models": []}
_openrouter_audio_model_cache: dict[str, Any] = {"ts": 0.0, "models": []}


async def openrouter_text_models(force: bool = False) -> list[dict[str, Any]]:
    now = time.monotonic()
    cached = _openrouter_text_model_cache.get("models")
    if not force and isinstance(cached, list) and cached and now - float(_openrouter_text_model_cache.get("ts") or 0) < 3600:
        return cached
    headers = openrouter_headers() if openrouter_api_key() else {"Content-Type": "application/json"}
    models = await fetch_openrouter_text_models(
        base_url=OPENROUTER_BASE_URL,
        headers=headers,
        timeout_seconds=15,
    )
    _openrouter_text_model_cache.update({"ts": now, "models": models})
    return models


async def openrouter_audio_models(force: bool = False) -> list[dict[str, Any]]:
    now = time.monotonic()
    cached = _openrouter_audio_model_cache.get("models")
    if not force and isinstance(cached, list) and cached and now - float(_openrouter_audio_model_cache.get("ts") or 0) < 3600:
        return cached
    headers = openrouter_headers() if openrouter_api_key() else {"Content-Type": "application/json"}
    models = await fetch_openrouter_audio_input_models(
        base_url=OPENROUTER_BASE_URL,
        headers=headers,
        timeout_seconds=15,
    )
    _openrouter_audio_model_cache.update({"ts": now, "models": models})
    return models


def _openrouter_text_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("OpenRouter не вернул текст улучшенного промпта.")
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                value = part.get("text") or part.get("content") or part.get("value")
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, dict):
                    parts.append(json.dumps(value, ensure_ascii=False))
        if parts:
            return "".join(parts).strip()
    parsed = message.get("parsed")
    if isinstance(parsed, dict):
        return json.dumps(parsed, ensure_ascii=False)
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            function = call.get("function") if isinstance(call, dict) and isinstance(call.get("function"), dict) else {}
            arguments = function.get("arguments")
            if isinstance(arguments, str) and arguments.strip():
                return arguments.strip()
            if isinstance(arguments, dict):
                return json.dumps(arguments, ensure_ascii=False)
    choice_text = choices[0].get("text")
    if isinstance(choice_text, str) and choice_text.strip():
        return choice_text.strip()
    raise RuntimeError("OpenRouter вернул неподдерживаемый формат текста.")


def _parse_improved_prompt(content: str) -> str:
    value = content.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        value = str(parsed.get("improved_prompt") or "").strip()
    if not value:
        raise RuntimeError("Модель вернула пустой улучшенный промпт.")
    return value[:2000]


def _improve_system_message(req: ImprovePromptRequest, config: dict[str, Any]) -> str:
    language_rule = "Ответ верни на русском языке." if req.language == "ru" else "Return the answer in English."
    system_prompt = str(config.get("systemPrompt") or DEFAULT_ASSISTANT_MODELS_CONFIG["improve"]["systemPrompt"]).strip()
    mode_prompts = config.get("modePrompts") if isinstance(config.get("modePrompts"), dict) else {}
    mode_rule = str(mode_prompts.get(req.mode) or PROMPT_IMPROVE_MODE_RULES[req.mode]).strip()
    return f"{system_prompt} {language_rule} {mode_rule} Верни только JSON с одним строковым полем improved_prompt."


async def improve_prompt_openrouter(req: ImprovePromptRequest, config: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    if not openrouter_api_key():
        raise RuntimeError("OpenRouter API-ключ не настроен.")
    config = config or assistant_models_config()["improve"]
    technical_context = req.technicalPrompt.strip()
    body = {
        "model": str(config.get("apiModel") or PROMPT_IMPROVE_MODEL),
        "messages": [
            {
                "role": "system",
                "content": _improve_system_message(req, config),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"prompt": req.prompt.strip(), "technical_context": technical_context or None},
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.25,
        "max_tokens": 500,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "improved_image_prompt",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"improved_prompt": {"type": "string"}},
                    "required": ["improved_prompt"],
                    "additionalProperties": False,
                },
            },
        },
    }
    async with _prompt_improve_semaphore:
        timeout = max(3, min(30, int(config.get("apiTimeoutSeconds") or PROMPT_IMPROVE_TIMEOUT_SECONDS)))
        status_code, data = await request_openrouter_chat_completion(
            base_url=OPENROUTER_BASE_URL,
            headers=openrouter_headers(),
            body=body,
            timeout_seconds=timeout,
        )
    if status_code >= 400:
        raise RuntimeError(_openrouter_public_error(status_code, data if isinstance(data, dict) else {}))
    if not isinstance(data, dict):
        raise RuntimeError("OpenRouter вернул некорректный ответ.")
    return _parse_improved_prompt(_openrouter_text_content(data)), data


async def improve_prompt_ollama(req: ImprovePromptRequest, config: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    config = config or assistant_models_config()["improve"]
    body = {
        "model": str(config.get("localModel") or "gemma4:12b"),
        "stream": False,
        "think": False,
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "-1").strip() or "-1",
        "format": {
            "type": "object",
            "properties": {"improved_prompt": {"type": "string"}},
            "required": ["improved_prompt"],
        },
        "messages": [
            {"role": "system", "content": _improve_system_message(req, config)},
            {"role": "user", "content": json.dumps({"prompt": req.prompt.strip(), "technical_context": req.technicalPrompt.strip() or None}, ensure_ascii=False)},
        ],
        "options": {"temperature": 0.25, "num_predict": 500},
    }
    timeout = max(3, min(120, int(config.get("localTimeoutSeconds") or 10)))
    async with _prompt_improve_semaphore:
        content, data = await request_ollama_chat_message(body=body, timeout_seconds=timeout)
    return _parse_improved_prompt(content), data


async def improve_prompt_routed(req: ImprovePromptRequest, force_provider: str | None = None) -> tuple[str, dict[str, Any], str, str]:
    config = assistant_models_config()["improve"]
    route = force_provider or str(config.get("route") or "local")
    if route == "local":
        improved, payload = await improve_prompt_ollama(req, config)
        return improved, payload, "local", str(config.get("localModel") or "gemma4:12b")
    if route == "auto":
        try:
            improved, payload = await improve_prompt_ollama(req, config)
            return improved, payload, "local", str(config.get("localModel") or "gemma4:12b")
        except Exception:
            pass
    improved, payload = await improve_prompt_openrouter(req, config)
    return improved, payload, "api", str(config.get("apiModel") or PROMPT_IMPROVE_MODEL)


async def transcribe_audio_openrouter(audio: bytes, audio_format: str, language: str, config: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    if not openrouter_api_key():
        raise RuntimeError("OpenRouter API-ключ не настроен.")
    config = config or assistant_models_config()["voice"]
    model = str(config.get("apiModel") or "google/gemini-3.1-flash-lite")
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": f"Точно расшифруй речь на языке {language}. Верни только произнесённый текст без пояснений и кавычек."},
                {"type": "input_audio", "input_audio": {"data": base64.b64encode(audio).decode("ascii"), "format": audio_format}},
            ],
        }],
        "temperature": 0,
        "max_tokens": 1000,
    }
    timeout = max(3, min(60, int(config.get("requestTimeoutSeconds") or 8)))
    status_code, payload = await request_openrouter_chat_completion(
        base_url=OPENROUTER_BASE_URL,
        headers=openrouter_headers(),
        body=body,
        timeout_seconds=timeout,
    )
    if status_code >= 400:
        raise RuntimeError(_openrouter_public_error(status_code, payload if isinstance(payload, dict) else {}))
    if not isinstance(payload, dict):
        raise RuntimeError("OpenRouter вернул некорректный ответ транскрибации.")
    text = _openrouter_text_content(payload).strip()
    if not text:
        raise RuntimeError("Модель не распознала речь.")
    return text[:2000], payload


def normalize_audio_to_wav(audio: bytes, suffix: str) -> bytes:
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError("На сервере не установлен аудиоконвертер imageio-ffmpeg.") from exc
    input_path = output_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as source:
            source.write(audio)
            input_path = source.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as target:
            output_path = target.name
        process = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", input_path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", output_path],
            capture_output=True, timeout=20, check=False,
        )
        if process.returncode != 0 or not Path(output_path).exists():
            raise RuntimeError("Не удалось подготовить запись для локального распознавания.")
        return Path(output_path).read_bytes()
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Подготовка голосовой записи заняла слишком много времени.") from exc
    finally:
        for path in (input_path, output_path):
            if path:
                Path(path).unlink(missing_ok=True)


async def transcribe_audio_ollama(audio: bytes, audio_format: str, language: str, config: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    config = config or assistant_models_config()["voice"]
    model = str(config.get("localModel") or "gemma4:12b")
    if model.startswith("gemma4:31b") or model.startswith("gemma4:26b"):
        raise RuntimeError(f"Модель {model} не имеет аудиоэнкодера.")
    wav = audio if audio_format == "wav" else await asyncio.to_thread(normalize_audio_to_wav, audio, audio_format)
    body = {
        "model": model, "stream": False, "think": False, "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "-1").strip() or "-1",
        "messages": [{
            "role": "user",
            "images": [base64.b64encode(wav).decode("ascii")],
            "content": f"Транскрибируй речь на {language} языке. Верни только произнесённый текст без пояснений, кавычек и переносов строк.",
        }],
        "options": {"temperature": 0, "num_predict": 256, "num_ctx": 8192},
    }
    timeout = max(10, min(180, int(config.get("requestTimeoutSeconds") or 45)))
    content, payload = await request_ollama_chat_message(body=body, timeout_seconds=timeout)
    text = content.strip()
    if not text:
        raise RuntimeError("Локальная модель не распознала речь.")
    return text[:2000], payload


async def transcribe_audio_qwen(audio: bytes, audio_format: str, language: str, config: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    config = config or assistant_models_config()["voice"]
    wav = audio if audio_format == "wav" else await asyncio.to_thread(normalize_audio_to_wav, audio, audio_format)
    timeout = max(10, min(180, int(config.get("requestTimeoutSeconds") or 45)))
    return await request_qwen_asr_transcription(
        audio=wav,
        audio_format="wav",
        language="Russian" if language.startswith("рус") else "English",
        model=str(config.get("qwenModel") or DEFAULT_QWEN_ASR_MODEL),
        base_url=str(config.get("qwenBaseUrl") or DEFAULT_QWEN_ASR_BASE_URL),
        timeout_seconds=timeout,
    )


async def transcribe_audio_routed(
    audio: bytes,
    audio_format: str,
    language: str,
    config: dict[str, Any] | None = None,
    force_provider: str | None = None,
) -> tuple[str, dict[str, Any], str, str]:
    config = config or assistant_models_config()["voice"]
    route = force_provider or str(config.get("route") or "local")
    providers = ["qwen", "local", "api"] if route == "auto" else [route]
    errors: list[str] = []
    for provider in providers:
        try:
            if provider == "qwen":
                text, payload = await transcribe_audio_qwen(audio, audio_format, language, config)
                return text, payload, provider, str(config.get("qwenModel") or DEFAULT_QWEN_ASR_MODEL)
            if provider == "local":
                text, payload = await transcribe_audio_ollama(audio, audio_format, language, config)
                return text, payload, provider, str(config.get("localModel") or "gemma4:12b")
            if provider == "api":
                text, payload = await transcribe_audio_openrouter(audio, audio_format, language, config)
                return text, payload, provider, str(config.get("apiModel") or "google/gemini-3.1-flash-lite")
            raise RuntimeError("Неизвестный маршрут транскрибации.")
        except (httpx.HTTPError, RuntimeError) as exc:
            errors.append(f"{provider}: {exc}")
            if route != "auto":
                raise
    raise RuntimeError("Ни один маршрут транскрибации не сработал: " + "; ".join(errors))


def resolve_openrouter_model(req: GenerateRequest) -> str:
    return resolve_openrouter_image_model(req.modelProfile)


def openrouter_image_request_metadata(
    payload: GenerateRequest,
    request_plan: dict[str, Any],
    body: dict[str, Any],
) -> dict[str, Any]:
    return build_openrouter_image_request_metadata(
        request_plan,
        mode=payload.mode,
        strength=payload.strength,
        body=body,
    )


def _requested_orientation(width: int, height: int) -> str:
    return requested_orientation(width, height)


def _openrouter_ratio_size(width: int, height: int) -> str:
    return openrouter_ratio_size(width, height)


def _openrouter_descriptor_values(capability: dict[str, Any] | None, key: str) -> list[str]:
    return openrouter_descriptor_values(capability, key)


def openrouter_image_request_plan(model_id: str, width: int, height: int, capability: dict[str, Any] | None = None) -> dict[str, Any]:
    resolution_id = resolution_id_for_size(width, height)
    resolution_tier = RESOLUTION_BY_ID.get(resolution_id or "", {}).get("tier", "hd")
    return build_openrouter_image_request_plan(
        model_id,
        width,
        height,
        capability,
        resolution_tier=resolution_tier,
    )


def _openrouter_generation_cost(payload: dict[str, Any]) -> float | None:
    return extract_openrouter_generation_cost(payload)


def _openrouter_first_image(payload: dict[str, Any]) -> dict[str, Any]:
    return select_openrouter_first_image(payload)


async def _openrouter_image_to_pil(image_payload: dict[str, Any]) -> Image.Image:
    return await load_openrouter_response_image(
        image_payload,
        timeout_seconds=OPENROUTER_TIMEOUT_SECONDS,
    )


def _openrouter_error_payload(data: dict[str, Any]) -> Any:
    return extract_openrouter_error_payload(data)


def _openrouter_error_message(data: dict[str, Any]) -> str:
    return openrouter_error_message(data)


def _openrouter_is_size_error(data: dict[str, Any]) -> bool:
    return is_openrouter_size_error(data)


def _openrouter_public_error(status_code: int, data: dict[str, Any]) -> str:
    return format_openrouter_public_error(
        status_code,
        data,
        truncate=truncate_admin_text,
    )


async def fetch_openrouter_key_status(force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    key = openrouter_api_key()
    source = openrouter_api_key_source()
    key_marker = (
        hashlib.sha256(f"{source}\0{key}".encode("utf-8")).hexdigest()[:16]
        if key
        else ""
    )
    cached = _openrouter_key_status_cache.get("data")
    if (
        not force
        and isinstance(cached, dict)
        and _openrouter_key_status_cache.get("keyMarker") == key_marker
        and now - float(_openrouter_key_status_cache.get("ts") or 0)
        < OPENROUTER_KEY_STATUS_CACHE_TTL_SECONDS
    ):
        return dict(cached)
    if not key:
        result = {"configured": False, "ok": False, "error": "OPENROUTER_API_KEY не задан"}
        _openrouter_key_status_cache.update({"ts": now, "data": result, "keyMarker": key_marker})
        return result
    try:
        details = await fetch_openrouter_key_details(
            base_url=OPENROUTER_BASE_URL,
            key_headers=openrouter_headers(),
            credits_headers=openrouter_headers(),
            timeout_seconds=15,
        )
        result = {"configured": True, "source": source, **details}
    except Exception as exc:
        result = {
            "configured": True,
            "source": source,
            "ok": False,
            "error": str(exc),
        }
    _openrouter_key_status_cache.update({"ts": now, "data": result, "keyMarker": key_marker})
    return dict(result)


async def send_to_openrouter(payload: GenerateRequest, job: dict[str, Any]) -> OpenRouterResult:
    if not openrouter_api_key():
        raise RuntimeError("OPENROUTER_API_KEY не задан. Добавьте ключ перед включением OpenRouter.")
    model = resolve_openrouter_model(payload)
    capabilities = await fetch_openrouter_image_capabilities()
    capability = next((item for item in capabilities if item.get("id") == model), None)
    if capability is None:
        raise RuntimeError(f"Модель {model} отсутствует в актуальном каталоге OpenRouter.")
    request_plan = openrouter_image_request_plan(model, payload.width, payload.height, capability)
    body = build_openrouter_image_body(payload, model, request_plan, capability)
    request_meta = openrouter_image_request_metadata(payload, request_plan, body)
    job.update(status="sent_to_openrouter", progress=24, message="Отправляем в OpenRouter", openrouterRequest=request_meta)
    persist_job(job, payload)

    def record_size_fallback() -> None:
        job.update(message="OpenRouter подбирает безопасный формат", openrouterRequest={**request_meta, "fallbackSize": "auto"})
        persist_job(job, payload)

    status_code, data = await request_openrouter_image(
        base_url=OPENROUTER_BASE_URL,
        headers_provider=openrouter_headers,
        body=body,
        timeout_seconds=OPENROUTER_TIMEOUT_SECONDS,
        is_size_error=_openrouter_is_size_error,
        before_size_fallback=record_size_fallback,
    )
    if status_code >= 400:
        raise RuntimeError(_openrouter_public_error(status_code, data))
    image_payload = _openrouter_first_image(data)
    with await _openrouter_image_to_pil(image_payload) as opened:
        image_path = save_gallery_original(opened, f"{job['id']}_openrouter")
    with Image.open(image_path) as saved:
        saved_width, saved_height = saved.size
    metadata = normalize_openrouter_image_response_metadata(data)
    return OpenRouterResult(
        image_path=image_path,
        thumbnail_path=create_thumbnail(image_path),
        response_id=metadata["response_id"],
        model=model,
        usage=metadata["usage"],
        cost_usd=metadata["cost_usd"],
        width=saved_width,
        height=saved_height,
        raw=metadata["raw"],
    )


def feed_media_dir() -> Path:
    path = MEDIA / "feed"
    path.mkdir(exist_ok=True)
    return path


def _media_file_path_from_url(url: str | None) -> Path | None:
    name = _feed_media_name(url)
    if not name:
        return None
    try:
        return storage_resolve_under_root(MEDIA, name)
    except StoragePathError:
        return None


async def comfyui_available() -> bool:
    return await integration_comfyui_available(base_url=COMFYUI_BASE_URL)


async def comfyui_node_names() -> set[str]:
    """Registered ComfyUI node class names (e.g. FluxKleinOneNode, DWPreprocessor).
    Used to verify pose readiness. Returns an empty set if ComfyUI is unreachable."""
    return await integration_fetch_comfyui_node_names(base_url=COMFYUI_BASE_URL)


async def get_comfyui_models() -> dict[str, list[str]]:
    return await integration_fetch_comfyui_models(base_url=COMFYUI_BASE_URL)


async def get_flux_klein_config() -> dict[str, Any]:
    return await integration_fetch_flux_klein_config(base_url=COMFYUI_BASE_URL)


async def get_flux_bgremoval_models() -> dict[str, Any]:
    return await integration_fetch_flux_bgremoval_models(base_url=COMFYUI_BASE_URL)


async def get_flux_lora_triggers(name: str) -> dict[str, Any]:
    return await integration_fetch_flux_lora_triggers(base_url=COMFYUI_BASE_URL, name=name)


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
    return comfyui_workflows.fallback_model_for_profile(requested)


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


def effective_face_profile(requested: str = "") -> str:
    """Face follows the single global Klein profile selected by the administrator."""
    return effective_edit_profile(requested)


def server_lora_enabled(file_name: str) -> bool:
    """An omitted LoRA is enabled by default; explicit admin switches win."""
    enabled = ((_saved_setting("server_model_loras") or {}).get("enabled") or {})
    value = enabled.get(file_name)
    if value is None:
        lowered = file_name.lower()
        value = next((flag for name, flag in enabled.items() if str(name).lower() in lowered), True)
    return bool(value)


SERVER_MODEL_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "flux_klein_9b": {"width": 1024, "height": 1024, "steps": 4, "sampler": "er_sde", "seedMode": "random", "seed": 42},
    "flux_klein_4b": {"width": 1024, "height": 1024, "steps": 4, "sampler": "er_sde", "seedMode": "random", "seed": 42},
}


def normalize_server_model_profiles(value: dict[str, Any] | None) -> dict[str, Any]:
    value = value or {}
    source = value.get("profiles") or {}
    profiles: dict[str, dict[str, Any]] = {}
    allowed_samplers = {"er_sde", "euler", "dpmpp_2m"}
    for profile_id, defaults in SERVER_MODEL_PROFILE_DEFAULTS.items():
        raw = {**defaults, **(source.get(profile_id) or {})}
        try:
            width, height = int(raw.get("width")), int(raw.get("height"))
            steps, seed = int(raw.get("steps")), int(raw.get("seed"))
        except (TypeError, ValueError):
            raise HTTPException(422, f"Некорректные числовые параметры {profile_id}.")
        sampler = str(raw.get("sampler") or defaults["sampler"])
        if sampler not in allowed_samplers:
            raise HTTPException(422, f"Sampler {sampler} не разрешён для Config UI.")
        profiles[profile_id] = {"width": max(512, min(2048, width)), "height": max(512, min(2048, height)), "steps": max(1, min(80, steps)), "sampler": sampler, "seedMode": "fixed" if raw.get("seedMode") == "fixed" else "random", "seed": max(0, seed)}
    return {"profiles": profiles}


def get_server_model_profiles() -> dict[str, dict[str, Any]]:
    return normalize_server_model_profiles(_saved_setting("server_model_profiles"))["profiles"]


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
    graph = json.loads(POSE_WORKFLOW_PATH.read_text(encoding="utf-8"))
    return comfyui_workflows.build_pose_workflow(
        graph,
        models,
        profile,
        ref_image_name,
        pose_image_name,
        model=model,
        text_encoder=text_encoder,
        vae=vae,
        seed=int(req.seed or 0),
    )


def build_outpaint_workflow(graph: dict[str, Any], models: dict[str, list[str]], req: GenerateRequest, uploads: dict[str, str]) -> dict[str, Any]:
    """Patch outpaint for the globally selected Klein profile."""
    model, text_encoder, vae = choose_model(models, effective_edit_profile(req.modelProfile))
    return comfyui_workflows.build_outpaint_workflow(
        graph,
        models,
        req,
        uploads,
        model=model, text_encoder=text_encoder, vae=vae,
        lora_enabled=server_lora_enabled,
        default_negative_prompt=DEFAULT_NEG_PROMPT,
        model_profiles=get_server_model_profiles(),
    )


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
    selected_id, strength = comfyui_workflows.select_faceswap_lora(
        available_loras,
        requested.id if requested else "",
        requested.strength if requested else 1.0,
        model,
        enabled=server_lora_enabled,
    )
    return Lora(id=selected_id, strength=strength)


async def upload_to_comfyui(path: Path) -> str:
    return await integration_upload_comfyui_image(base_url=COMFYUI_BASE_URL, path=path)


def prepare_comfyui_input_image(
    image_path: Path | None,
    prefix: str,
    req: GenerateRequest,
    max_side: int | None = None,
    max_megapixels: float | None = None,
) -> Path | None:
    return comfyui_inputs.prepare_reference_image(
        image_path,
        output_directory=MEDIA,
        prefix=prefix,
        target_box=(req.width, req.height),
        max_side=min(COMFYUI_INPUT_MAX_SIDE, int(max_side or COMFYUI_INPUT_MAX_SIDE)),
        minimum_side=COMFYUI_INPUT_MIN_SIDE,
        max_megapixels=max_megapixels,
        log=print,
    )


def prepare_comfyui_outpaint_inputs(input_path: Path | None, prefix: str, req: GenerateRequest) -> tuple[Path | None, Path | None]:
    """Build a real outpaint canvas and mask for ComfyUI.

    The source image is placed inside the requested output frame. White mask
    pixels mark the empty border areas to regenerate, black pixels preserve the
    original source region.
    """
    if not input_path or not input_path.exists():
        return input_path, None
    padding = comfyui_inputs.outpaint_padding(req.outpaint or {})
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
            placement = comfyui_inputs.outpaint_placement(
                req.outpaint or {},
                target_size=(target_w, target_h),
                default_frame_size=(req.width or target_w, req.height or target_h),
            )
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
    endpoint = comfyui_workflows.workflow_endpoint_for_mode(mode)
    return await integration_fetch_comfyui_workflow(base_url=COMFYUI_BASE_URL, endpoint=endpoint)


def set_input(prompt: dict[str, Any], node_id: str, key: str, value: Any) -> None:
    comfyui_workflows.set_input(prompt, node_id, key, value)


def patch_shared_flux_nodes(prompt: dict[str, Any], req: GenerateRequest, model: str, text_encoder: str, vae: str) -> None:
    comfyui_workflows.patch_shared_flux_nodes(
        prompt,
        req,
        model,
        text_encoder,
        vae,
        default_negative_prompt=DEFAULT_NEG_PROMPT,
        model_profiles=get_server_model_profiles(),
    )


def patch_optional_lora(prompt: dict[str, Any], lora: Lora | None) -> None:
    comfyui_workflows.patch_optional_lora(prompt, lora)


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
    comfyui_workflows.patch_edit_reference_chain(prompt, image_files)


def patch_mode_nodes(
    prompt: dict[str, Any],
    req: GenerateRequest,
    uploads: dict[str, str],
    model: str,
    text_encoder: str,
    vae: str,
    *,
    edit_reference_megapixels: list[float | None] | None = None,
) -> None:
    comfyui_workflows.patch_mode_nodes(
        prompt,
        req,
        uploads,
        model,
        text_encoder,
        vae,
        default_negative_prompt=DEFAULT_NEG_PROMPT,
        model_profiles=get_server_model_profiles(),
        edit_reference_megapixels=edit_reference_megapixels,
    )


async def submit_workflow(workflow: dict[str, Any], job: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
    data = await integration_submit_comfyui_workflow(
        base_url=COMFYUI_BASE_URL,
        workflow=workflow,
        job_id=job["id"],
    )
    prompt_id = comfyui_results.prompt_id_from_submission(data)
    history = await wait_for_history(prompt_id, job)
    return prompt_id, history, extract_images_from_history(history)


async def interrupt_comfyui_prompt() -> None:
    try:
        await integration_interrupt_comfyui(base_url=COMFYUI_BASE_URL)
    except Exception:
        pass


async def wait_for_comfyui_recovery_gate() -> None:
    await COMFYUI_RECOVERY_GATE.wait(available=comfyui_available, sleep=asyncio.sleep)


async def recover_timed_out_comfyui_image(
    prompt_id: str,
    job: dict[str, Any],
    reason: str,
) -> None:
    await COMFYUI_RECOVERY_GATE.recover(
        prompt_id=prompt_id,
        job_id=str(job.get("id") or ""),
        reason=reason,
        interrupt=interrupt_comfyui_prompt,
        free_memory=lambda: integration_free_comfyui_memory(base_url=COMFYUI_BASE_URL),
        available=comfyui_available,
        monotonic=time.monotonic,
        sleep=asyncio.sleep,
    )


def extract_images_from_history(history: dict[str, Any]) -> list[dict[str, str]]:
    return comfyui_results.extract_images_from_history(history)


async def wait_for_history(prompt_id: str, job: dict[str, Any]) -> dict[str, Any]:
    async with IntegrationComfyUIHistoryClient(
        base_url=COMFYUI_BASE_URL,
        timeout_seconds=COMFYUI_HISTORY_REQUEST_TIMEOUT_SECONDS,
    ) as history_client:
        return await comfyui_watchdog.poll_prompt_history(
            prompt_id=prompt_id,
            job=job,
            timeout_seconds=COMFYUI_IMAGE_TIMEOUT_SECONDS,
            fetch=history_client.fetch,
            recover=lambda reason: recover_timed_out_comfyui_image(
                prompt_id,
                job,
                reason,
            ),
            monotonic=time.monotonic,
            sleep=asyncio.sleep,
            transient_errors=(httpx.TimeoutException,),
        )


async def download_comfyui_image(image: dict[str, str], job_id: str) -> tuple[Path, Path]:
    content = await integration_fetch_comfyui_image_bytes(base_url=COMFYUI_BASE_URL, image=image)
    return comfyui_results.persist_downloaded_image(
        content,
        job_id,
        save_original=save_gallery_original,
        create_thumbnail=create_thumbnail,
    )


async def send_to_comfyui(payload: GenerateRequest, job: dict[str, Any]) -> ComfyUIResult | None:
    if _saved_setting("config_ui_runtime").get("imageEnabled") is False:
        raise RuntimeError("Локальная генерация изображений отключена администратором.")
    await wait_for_comfyui_recovery_gate()
    if not await comfyui_available():
        if COMFYUI_REQUIRED:
            raise RuntimeError("FluxKleinOneNode не найден или ComfyUI недоступен. Проверьте установку custom node.")
        if not COMFYUI_MOCK_FALLBACK:
            raise RuntimeError("ComfyUI недоступен. Проверьте, что сервер запущен.")
        return None

    profile_id = effective_face_profile(payload.modelProfile) if payload.mode == "faceswap" else effective_edit_profile(payload.modelProfile)
    models = await get_comfyui_models()
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
        payload.loras = [lora for lora in payload.loras if lora.id in {"", "none"} or server_lora_enabled(lora.id)]
        for lora in payload.loras:
            if lora.id == "none" or not lora.id:
                continue
            if target_lora_tag not in lora.id.lower():
                fallback = next(
                    (item for item in available_loras
                     if target_lora_tag in item.lower() and server_lora_enabled(item) and any(kw in item.lower() for kw in ("bfs", "face", "head"))),
                    "",
                )
                if fallback:
                    lora.id = fallback
                else:
                    raise RuntimeError(f"LoRA {lora.id} несовместима с активной Klein {target_lora_tag.upper()} и безопасной замены нет.")
    workflow = await fetch_workflow(payload.mode)
    special_edit_graph: dict[str, Any] | None = None
    uploads: dict[str, str] = {}
    input1_path = local_media_path_from_url(payload.inputImage1 or "") or save_data_url(payload.inputImage1, f"{job['id']}_input1")
    input2_path = local_media_path_from_url(payload.inputImage2 or "") or save_data_url(payload.inputImage2, f"{job['id']}_input2")
    mask_source = payload.maskImage or payload.outpaintMask
    mask_path = local_media_path_from_url(mask_source or "") or save_data_url(mask_source, f"{job['id']}_mask")
    canvas_path = save_canvas_json(payload.canvas, f"{job['id']}_canvas")
    primary_input = input1_path or canvas_path
    outpaint_generated_mask = False
    edit_reference_megapixels: list[float | None] = []
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
        pose_image_name: str | None = None; requested_roles = [role for role, _src in edit_sources[:4]]
        for i, (role, src) in enumerate(edit_sources[:4]):
            slot_path = local_media_path_from_url(src) or save_data_url(src, f"{job['id']}_edit{i + 1}")
            if not slot_path:
                continue
            slot_path = prepare_comfyui_input_image(
                slot_path,
                f"{job['id']}_edit{i + 1}",
                payload,
                max_megapixels=comfyui_workflows.edit_reference_megapixel_limit(
                    profile_id=profile_id, roles=requested_roles, role=role,
                    face_limit=COMFYUI_FACE_SOURCE_MEGAPIXELS,
                ),
            )
            if slot_path:
                try:
                    with Image.open(slot_path) as prepared:
                        edit_reference_megapixels.append(
                            comfyui_inputs.image_megapixels(prepared.size)
                        )
                except Exception:
                    edit_reference_megapixels.append(None)
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
            special_edit_graph = build_pose_workflow(models, profile_row, uploads["input1"], pose_image_name, payload)
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
            mask_path = comfyui_inputs.prepare_mask_image(
                mask_path, primary_input, output_directory=MEDIA, prefix=f"{job['id']}_mask", log=print,
            )
        uploads["mask"] = await upload_to_comfyui(mask_path)

    if special_edit_graph is not None:
        workflow = special_edit_graph
    elif payload.mode == "outpaint":
        workflow = build_outpaint_workflow(workflow, models, payload, uploads)
    else:
        patch_mode_nodes(
            workflow,
            payload,
            uploads,
            model,
            text_encoder,
            vae,
            edit_reference_megapixels=edit_reference_megapixels or None,
        )
    try:
        prompt_id, history, output_images = await submit_workflow(workflow, job)
    except Exception as exc:
        if payload.mode == "faceswap":
            raise RuntimeError(f"FaceSwap workflow failed: {exc}") from exc
        if not COMFYUI_MOCK_FALLBACK or payload.mode not in {"inpaint", "outpaint", "remove_background", "try_on", "texture_transfer"}:
            raise
        prompt_id = "fallback_after_workflow_error"
        history = {"error": str(exc)}
        output_images = []
    if payload.mode == "faceswap" and not output_images:
        raise RuntimeError("FaceSwap workflow completed without output image.")
    if COMFYUI_MOCK_FALLBACK and not output_images and payload.mode in {"inpaint", "outpaint", "remove_background", "try_on", "texture_transfer"}:
        try:
            fallback = await fetch_workflow("edit")
            fallback_req = payload.model_copy(update={"mode": "edit"})
            patch_mode_nodes(fallback, fallback_req, uploads, model, text_encoder, vae)
            prompt_id, history, output_images = await submit_workflow(fallback, job)
        except Exception as exc:
            history = {"fallback": "edit_workflow_error", "error": str(exc)}
            output_images = []
    if COMFYUI_MOCK_FALLBACK and not output_images and payload.mode in {"inpaint", "outpaint", "remove_background", "try_on", "texture_transfer"}:
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
    if COMFYUI_MOCK_FALLBACK and not output_images and payload.mode in {"inpaint", "outpaint", "remove_background", "try_on", "texture_transfer"}:
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


def _worker_refund_tokens(job_id: str, reason: str) -> bool:
    with db() as conn:
        return refund_generation_tokens(conn, job_id, reason=reason)


def _worker_settle_openrouter(
    job_id: str,
    job: dict[str, Any],
    result: OpenRouterResult,
) -> generation_worker.OpenRouterSettlement:
    billing = finalize_openrouter_billing_snapshot(job.get("openrouterBilling") or {}, result.cost_usd)
    actual_tokens = int(
        billing.get("actualTokens")
        or billing.get("chargedTokens")
        or job.get("tokenCost")
        or 1
    )
    with db() as conn:
        token_adjustment = reconcile_openrouter_token_charge(conn, job_id, actual_tokens)
    return generation_worker.OpenRouterSettlement(
        billing=billing,
        actual_tokens=actual_tokens,
        token_adjustment=token_adjustment,
    )


def _worker_gallery_quota(user_id: str) -> dict[str, Any]:
    with db() as conn:
        user_row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return gallery_quota_for_user(conn, user_row, user_id)


def _worker_evict_gallery(user_id: str, quota: dict[str, Any], created_at: str) -> int:
    with db() as conn:
        return evict_gallery_images_for_new_save(conn, user_id, quota, created_at)


async def _worker_save_image(
    record: dict[str, Any],
    job_id: str,
    user_id: str,
    request: GenerateRequest,
    created_at: str,
) -> None:
    image_id = record["id"]
    images[image_id] = record
    persist_image(record, job_id)
    sources = persist_image_sources(image_id, user_id, request, created_at)
    if sources:
        images[image_id]["sources"] = sources
    await asyncio.to_thread(optimize_gallery_storage_for_user, user_id, limit=2)


def _worker_register_transient_image(record: dict[str, Any]) -> None:
    images[record["id"]] = record


def _generation_worker_runtime() -> generation_worker.GenerationWorkerRuntime:
    return generation_worker.GenerationWorkerRuntime(
        comfyui_mock_fallback=COMFYUI_MOCK_FALLBACK,
        persist_job=persist_job,
        refund_tokens=_worker_refund_tokens,
        send_to_comfyui=send_to_comfyui,
        send_to_openrouter=send_to_openrouter,
        settle_openrouter=_worker_settle_openrouter,
        mock_image=mock_image,
        gallery_quota=_worker_gallery_quota,
        evict_gallery=_worker_evict_gallery,
        public_url=public_url,
        new_image_id=lambda: f"img_{uuid.uuid4().hex[:12]}",
        now_iso=lambda: datetime.now(timezone.utc).isoformat(),
        perf_counter=time.perf_counter,
        sleep=asyncio.sleep,
        save_image=_worker_save_image,
        register_transient_image=_worker_register_transient_image,
    )


def _generation_queue_runtime() -> generation_queue.GenerationQueueRuntime:
    return generation_queue.GenerationQueueRuntime(
        queue=queue,
        jobs=jobs,
        parse_request=lambda payload: GenerateRequest(**payload),
        perf_counter=time.perf_counter,
        build_worker_runtime=_generation_worker_runtime,
        process_job=generation_worker.process_generation_job,
    )


async def worker() -> None:
    await generation_queue.consume_generation_queue(_generation_queue_runtime())


@app.on_event("startup")
async def startup() -> None:
    global worker_started
    validate_config_production_configuration(
        runtime=RUNTIME_ENVIRONMENT_POLICY,
        http_security=_HTTP_SECURITY_POLICY,
        providers=PROVIDER_ENDPOINT_POLICY,
        storage=STORAGE_PATH_POLICY,
    )
    validate_telegram_webhook_secret(BOT_UPDATES_MODE, TELEGRAM_WEBHOOK_SECRET)
    validate_max_webhook_secret(MAX_UPDATES_MODE, MAX_WEBHOOK_SECRET)
    db_guard_preflight()
    if RELEASE_IDENTITY.managed:
        with db() as conn:
            schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        assert_release_schema_compatible(RELEASE_IDENTITY, schema_version)
    validate_session_crypto_config()
    init_db()
    video_cleanup = drain_video_file_deletions(limit=200)
    if video_cleanup["checked"]:
        print(f"video file deletion queue: {video_cleanup}")
    bot_runtime = apply_saved_bot_runtime_configuration()
    validate_telegram_webhook_secret(BOT_UPDATES_MODE, TELEGRAM_WEBHOOK_SECRET)
    validate_max_webhook_secret(MAX_UPDATES_MODE, MAX_WEBHOOK_SECRET)
    print(
        "bot runtime configuration "
        f"source={bot_runtime['source']} "
        f"telegramMode={bot_runtime['telegramMode']} "
        f"maxMode={bot_runtime['maxMode']}"
    )
    openrouter_secret_migration = migrate_openrouter_secret_from_sqlite()
    if openrouter_secret_migration != "not_configured":
        print(f"OpenRouter secret store status={openrouter_secret_migration} source={openrouter_api_key_source()}")
    ADMIN_NOTIFICATION_DELIVERY_WORKER.start(connection_factory=db, send_telegram=send_admin_telegram_notification, send_email=send_admin_email_notification)
    SOCIAL_DELIVERY_WORKER.start(
        connection_factory=db,
        send_telegram=send_social_telegram_publication,
        send_max=send_social_max_publication,
        send_vk=send_social_vk_publication, send_vk_story=send_social_vk_story, delete_social=delete_social_publication,
    )
    enforce_db_guard_after_migrations()
    generation_recovery_report = reconcile_stale_generation_state()
    if generation_recovery_report["checked"]:
        print(f"generation startup reconciliation: {generation_recovery_report}")
    storage_maintenance_enabled = startup_storage_maintenance_allowed(os.environ)
    if storage_maintenance_enabled:
        recovered_gallery = recover_missing_optimized_gallery_files()
        if any(value for key, value in recovered_gallery.items() if key != "checked"):
            print(f"gallery storage recovery: {recovered_gallery}")
        repaired_thumbnails = repair_missing_gallery_thumbnails()
        if any(value for key, value in repaired_thumbnails.items() if key != "checked"):
            print(f"gallery thumbnail repair: {repaired_thumbnails}")
        repaired_avatars = repair_missing_user_avatars()
        if repaired_avatars["repaired"]:
            print(f"user avatar repair: {repaired_avatars}")
        source_cleanup = cleanup_orphan_image_sources()
        if any(source_cleanup.values()):
            print(f"image source cleanup: {source_cleanup}")
        source_availability = reconcile_image_source_availability()
        if source_availability["missing"]:
            print(f"image source availability: {source_availability}")
        repaired_sources = repair_unavailable_image_sources_from_jobs()
        if repaired_sources["repaired"] or repaired_sources["errors"]:
            print(f"image source repair: {repaired_sources}")
    else:
        print("startup storage maintenance skipped by runtime safety policy")
    backfilled_feed = backfill_feed_generation_snapshots()
    if backfilled_feed:
        print(f"feed generation snapshots backfilled: {backfilled_feed}")
    recovered_feed_videos = start_feed_video_publication_worker()
    if recovered_feed_videos:
        print(f"feed video publications requeued: {recovered_feed_videos}")
    load_db_state()
    if storage_maintenance_enabled:
        asyncio.create_task(asyncio.to_thread(optimize_existing_gallery_storage))
    worker_started = generation_queue.start_generation_consumer_once(
        already_started=worker_started,
        create_task=asyncio.create_task,
        consumer=worker,
    )
    start_bot_workers(
        BOT_RUNTIME,
        telegram_poll=telegram_poll_once_from_api,
        max_poll=max_poll_once_from_api,
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    await ADMIN_NOTIFICATION_DELIVERY_WORKER.stop()
    await SOCIAL_DELIVERY_WORKER.stop()
    await stop_feed_video_publication_worker()
    await stop_bot_workers(BOT_RUNTIME)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    guard = collect_db_guard_status()
    DB_GUARD_STATUS.update(guard)
    return {
        "ok": True,
        "app": "izo-asa",
        "release_id": RELEASE_IDENTITY.release_id,
        "ready": bool(guard.get("ok")),
    }


_runtime_error_rate: dict[str, list[float]] = {}
_runtime_alerted_signatures: dict[str, float] = {}
_runtime_error_window: list[float] = []
_runtime_threshold_alerted_at = 0.0


async def _send_runtime_alert(payload: dict[str, Any]) -> None:
    webhook = os.getenv("RUNTIME_ALERT_WEBHOOK_URL", "").strip()
    if not webhook:
        return
    try:
        async with httpx.AsyncClient(timeout=3, follow_redirects=False) as client:
            await client.post(webhook, json={"event": "frontend_runtime_error", **payload})
    except (httpx.HTTPError, RuntimeError):
        return


def _check_runtime_error_rate(request: Request) -> None:
    key = _client_ip(request) or "unknown"
    now = time.monotonic()
    recent = [stamp for stamp in _runtime_error_rate.get(key, []) if now - stamp < 60]
    if len(recent) >= 20:
        raise HTTPException(429, "runtime_error_rate_limited")
    recent.append(now)
    _runtime_error_rate[key] = recent


@app.get("/api/version")
async def version() -> dict[str, Any]:
    return {
        "ok": True,
        "app": "izo-asa",
        **RELEASE_IDENTITY.public_payload(),
        "started_at": STARTED_AT,
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


@app.post("/api/tools/improve-prompt")
async def improve_prompt(req: ImprovePromptRequest, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    original = req.prompt.strip()
    if not original:
        raise HTTPException(400, "Сначала напишите, что нужно изобразить или изменить.")
    started = time.monotonic()
    try:
        improved, provider_payload, provider, model = await asyncio.wait_for(
            improve_prompt_routed(req.model_copy(update={"prompt": original})),
            timeout=122,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(504, "Улучшение заняло слишком много времени. Исходный текст сохранён.") from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(502, str(exc)) from exc
    usage = provider_payload.get("usage") if isinstance(provider_payload.get("usage"), dict) else {}
    cost = _openrouter_generation_cost(provider_payload) if provider == "api" else 0
    record_event_log(
        "prompt_improved",
        internal_user_id=trusted.get("internal_user_id"),
        legacy_user_id=trusted.get("legacy_user_id"),
        session_id=trusted.get("session_id"),
        platform="web",
        request=request,
        properties={
            "mode": req.mode,
            "model": model,
            "provider": provider,
            "input_chars": len(original),
            "output_chars": len(improved),
            "latency_ms": round((time.monotonic() - started) * 1000),
            "cost_usd": cost,
        },
    )
    return {
        "ok": True,
        "improvedPrompt": improved,
        "model": model,
        "provider": provider,
        "usage": usage,
        "costUsd": cost,
    }


@app.post("/api/client-errors", status_code=202)
async def client_runtime_error(req: ClientRuntimeErrorRequest, request: Request) -> dict[str, Any]:
    global _runtime_error_window, _runtime_threshold_alerted_at
    _check_runtime_error_rate(request)
    properties = {
        "incident_id": req.incident_id,
        "signature": req.signature,
        "region": req.region,
        "route": req.route,
        "mode": req.mode,
        "release": req.release,
        "kind": req.kind,
    }
    record_event_log(
        "frontend_runtime_error",
        platform="web",
        device_type=parse_user_agent(request.headers.get("user-agent"))["device_type"],
        request=None,
        properties=properties,
    )
    now = time.monotonic()
    last_alert = _runtime_alerted_signatures.get(req.signature, 0.0)
    if now - last_alert >= 600:
        _runtime_alerted_signatures[req.signature] = now
        asyncio.create_task(_send_runtime_alert(properties))
    _runtime_error_window = [stamp for stamp in _runtime_error_window if now - stamp < 300]
    _runtime_error_window.append(now)
    if len(_runtime_error_window) >= 5 and now - _runtime_threshold_alerted_at >= 600:
        _runtime_threshold_alerted_at = now
        asyncio.create_task(_send_runtime_alert({
            "kind": "runtime_error_threshold",
            "count": len(_runtime_error_window),
            "window_seconds": 300,
            "release": req.release,
        }))
    return {"accepted": True, "incidentId": req.incident_id}


@app.post("/api/runtime/synthetic-result", status_code=202)
async def runtime_synthetic_result(req: SyntheticResultRequest, request: Request) -> dict[str, Any]:
    expected = os.getenv("RUNTIME_SYNTHETIC_KEY", "").strip()
    supplied = request.headers.get("x-izo-synthetic-key", "")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "invalid_synthetic_key")
    properties = {
        "status": req.status,
        "release": req.release,
        "checked_routes": [route[:160] for route in req.checked_routes],
        "duration_ms": req.duration_ms,
    }
    record_event_log(
        f"frontend_synthetic_{req.status}",
        platform="monitor",
        request=None,
        properties=properties,
    )
    if req.status == "error":
        asyncio.create_task(_send_runtime_alert({"kind": "synthetic_error", **properties}))
    return {"accepted": True}


@app.get("/api/admin/runtime-health-v2")
async def admin_runtime_health_v2(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM event_logs WHERE event_name = 'frontend_runtime_error' AND created_at >= ?",
            (since,),
        ).fetchone()["c"]
        rows = conn.execute(
            "SELECT properties_json, created_at FROM event_logs WHERE event_name = 'frontend_runtime_error' "
            "ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        synthetic_row = conn.execute(
            "SELECT event_name, properties_json, created_at FROM event_logs "
            "WHERE event_name IN ('frontend_synthetic_ok', 'frontend_synthetic_error') "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    incidents = []
    for row in rows:
        details = safe_json_load(row["properties_json"]) or {}
        incidents.append({
            "incident_id": details.get("incident_id"),
            "signature": details.get("signature"),
            "region": details.get("region"),
            "route": details.get("route"),
            "release": details.get("release"),
            "kind": details.get("kind"),
            "created_at": row["created_at"],
        })
    latest_synthetic = None
    if synthetic_row:
        latest_synthetic = safe_json_load(synthetic_row["properties_json"]) or {}
        latest_synthetic["event"] = synthetic_row["event_name"]
        latest_synthetic["created_at"] = synthetic_row["created_at"]
    guard = collect_db_guard_status()
    DB_GUARD_STATUS.update(guard)
    return {
        "ok": True,
        "release": RELEASE_IDENTITY.public_payload(),
        "system": {
            "environment": "production" if is_production_like_env() else "development",
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
            "comfyui_base_url": COMFYUI_BASE_URL,
            "comfyui_ready": await comfyui_available(),
            "platforms": {"web": True, "telegram": True, "max": True},
        },
        "runtime_errors_24h": int(total or 0),
        "alert_webhook_configured": bool(os.getenv("RUNTIME_ALERT_WEBHOOK_URL", "").strip()),
        "latest_synthetic": latest_synthetic,
        "recent_incidents": incidents,
    }


@app.post("/api/tools/transcribe")
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    duration_ms: int = 0,
    language: str = "ru",
) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    config = assistant_models_config()["voice"]
    minimum_ms = max(500, min(10_000, int(float(config.get("minRecordingSeconds") or 1) * 1000)))
    if duration_ms < minimum_ms:
        raise HTTPException(400, f"Говорите не меньше {minimum_ms / 1000:g} сек.")
    audio = await file.read(8 * 1024 * 1024 + 1)
    if not audio:
        raise HTTPException(400, "Запись голоса пустая.")
    if len(audio) > 8 * 1024 * 1024:
        raise HTTPException(413, "Запись голоса слишком большая.")
    content_type = (file.content_type or "").lower()
    format_by_type = {
        "audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a",
        "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
    }
    audio_format = format_by_type.get(content_type)
    if not audio_format:
        suffix = Path(file.filename or "").suffix.lower().lstrip(".")
        audio_format = {"webm": "webm", "ogg": "ogg", "m4a": "m4a", "mp3": "mp3", "wav": "wav"}.get(suffix)
    if not audio_format:
        raise HTTPException(415, "Формат записи голоса не поддерживается.")
    started = time.monotonic()
    try:
        spoken_language = "русском" if language == "ru" else "английском"
        text, payload, provider, model = await transcribe_audio_routed(audio, audio_format, spoken_language, config)
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(502, str(exc)) from exc
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    record_event_log(
        "voice_transcribed",
        internal_user_id=trusted.get("internal_user_id"), legacy_user_id=trusted.get("legacy_user_id"),
        session_id=trusted.get("session_id"), platform="web", request=request,
        properties={"model": model, "provider": provider, "duration_ms": duration_ms, "bytes": len(audio), "latency_ms": round((time.monotonic() - started) * 1000)},
    )
    return {"ok": True, "text": text, "model": model, "provider": provider, "usage": usage}


@app.post("/api/generate")
async def generate(req: GenerateRequest, request: Request) -> dict[str, Any]:
    req = normalize_generation_request(req)
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    internal_user_id = trusted["internal_user_id"]
    session_id = trusted.get("session_id")
    openrouter_billing: dict[str, Any] | None = None
    with db() as conn:
        user_row = conn.execute("SELECT id, plan FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_row is None:
            raise HTTPException(404, "User not found.")
    plan = str(user_row["plan"] or "mini").lower()
    if plan not in PLAN_ORDER:
        plan = "mini"
    requested_resolution_id = resolution_id_for_size(req.width, req.height)
    dynamic_local_editor_size = (
        req.provider == "comfyui"
        and req.mode in {"outpaint", "inpaint", "remove_background"}
        and requested_resolution_id is None
    )
    if dynamic_local_editor_size:
        normalized_base_ids = normalize_resolution_ids([req.resolutionId] if req.resolutionId else [])
        requested_resolution_id = normalized_base_ids[0] if normalized_base_ids else None
        safe_dynamic_size = (
            req.width % 16 == 0
            and req.height % 16 == 0
            and 512 <= req.width <= 1792
            and 512 <= req.height <= 1792
            and req.width * req.height <= 2_050_000
        )
        if not safe_dynamic_size:
            raise HTTPException(422, "Размер изображения редактора выходит за безопасные пределы локальной модели.")
    if requested_resolution_id is None:
        raise HTTPException(422, "Выбран нестандартный размер изображения. Выберите доступное разрешение в интерфейсе.")
    if requested_resolution_id not in get_tariff_config()[plan]["allowed_resolutions"]:
        raise HTTPException(403, "Это разрешение недоступно на вашем тарифе.")
    if req.provider == "comfyui":
        if requested_resolution_id not in CONFIG_UI_RESOLUTION_IDS:
            raise HTTPException(422, "Это разрешение ещё не подтверждено для серверной модели.")
    if req.provider == "openrouter":
        if req.mode not in OPENROUTER_GENERATION_MODES:
            raise HTTPException(501, "OpenRouter для этой вкладки пока не подключён.")
        if req.mode == "image_to_image" and not req.inputImage1:
            raise HTTPException(400, "Для режима «По фото» требуется исходное изображение.")
        if req.mode == "edit":
            references = [item for item in req.inputImages if item.image]
            capabilities = await fetch_openrouter_image_capabilities()
            resolved_model = resolve_openrouter_model(req)
            capability = next((item for item in capabilities if item.get("id") == resolved_model), None)
            if capability is None or "edit" not in (capability.get("modes") or []):
                raise HTTPException(400, "Выбранная модель не поддерживает «Сборку» из нескольких изображений.")
            reference_limit = min(4, int(capability.get("maxInputReferences") or 0))
            if len(references) < 2:
                raise HTTPException(400, "Для «Сборки» нужны основа и хотя бы один референс.")
            if len(references) > reference_limit:
                raise HTTPException(400, f"Выбранная модель принимает не больше {reference_limit} изображений.")
        openrouter_config = get_openrouter_config()
        if not openrouter_model_allowed(openrouter_config, req.mode, plan, req.modelProfile):
            raise HTTPException(403, "This OpenRouter model is not available for this mode and tariff.")
        capabilities = await fetch_openrouter_image_capabilities()
        resolved_model = resolve_openrouter_model(req)
        capability = next((item for item in capabilities if item.get("id") == resolved_model), None)
        if req.mode != "text_to_image" and (
            capability is None or req.mode not in (capability.get("modes") or [])
        ):
            raise HTTPException(400, "Выбранная модель не поддерживает этот режим генерации.")
        if requested_resolution_id not in supported_resolution_ids_from_capability(capability):
            raise HTTPException(422, "Выбранное разрешение не поддерживается этой моделью.")
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
    if req.mode == "outpaint" and not any(comfyui_inputs.outpaint_padding(req.outpaint or {}).values()):
        raise HTTPException(422, "Задайте ненулевое поле расширения слева, справа, сверху или снизу.")
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
        "tokenCost": token_cost,
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
        "mainBalanceTokens": token_charge["new_balance"],
        "dailyTokenPart": token_charge["daily_part"],
        "mainBalanceTokenPart": token_charge["balance_part"],
        "dailyTokensUsed": token_charge["daily_tokens_used"],
        "dailyTokensLimit": token_charge["daily_tokens_limit"],
        "dailyTokensRemaining": token_charge["daily_tokens_remaining"],
    }


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    job = jobs.get(job_id)
    if job is not None:
        if job.get("userId") != user_id:
            raise HTTPException(404, "Job not found")
        response = {k: v for k, v in job.items() if k != "request"}
        if response.get("status") == "completed" and not response.get("resultUrl"):
            persisted = get_persisted_job_response(job_id, user_id)
            if persisted:
                response.update({k: v for k, v in persisted.items() if v is not None})
                job.update({k: v for k, v in response.items() if k != "request"})
        return response
    persisted = get_persisted_job_response(job_id, user_id)
    if persisted is None:
        raise HTTPException(404, "Job not found")
    return persisted


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
    await interrupt_comfyui_prompt()
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


def _request_plan_or_default(request: Request | None, default: str = "mini") -> str:
    if request is None:
        return default
    try:
        trusted = resolve_trusted_user(request)
    except HTTPException:
        return default
    expire_paid_plan_if_needed(trusted["internal_user_id"])
    with db() as conn:
        row = conn.execute("SELECT plan FROM users WHERE internal_user_id = ?", (trusted["internal_user_id"],)).fetchone()
        if row is None and trusted["legacy_user_id"]:
            row = conn.execute("SELECT plan FROM users WHERE id = ?", (trusted["legacy_user_id"],)).fetchone()
    plan = str(row["plan"] if row else default).lower()
    return plan if plan in PLAN_ORDER else default


@app.get("/api/tariffs")
async def tariffs(request: Request) -> dict[str, Any]:
    economy = openrouter_economy_settings()
    plan = _request_plan_or_default(request)
    exchange = await fetch_usd_rub_rate()
    try:
        capability_catalog = await fetch_openrouter_image_capabilities()
    except Exception:
        capability_catalog = []
    return {
        "ok": True,
        "tariffs": tariff_config_with_model_counts(),
        "termOffers": public_tariff_term_offers(),
        "tariffTerms": get_tariff_term_settings()["discount_percent"],
        "modelAccess": public_model_access_for_plan(plan, capability_catalog),
        "openrouterPricing": public_openrouter_pricing(exchange),
        "economy": {
            "tokenRub": economy["tokenRub"],
        },
    }


@app.get("/api/public/commerce-v2")
async def public_commerce_v2() -> dict[str, Any]:
    """Public storefront data without credentials or user-specific fields."""
    with db() as conn:
        _sync_tariff_billing_packages(conn)
        tariffs_config = tariff_config_with_model_counts(conn)
        packages = conn.execute(
            "SELECT * FROM billing_packages WHERE is_active = 1 AND (code LIKE 'tokens_%' OR code LIKE 'tariff_%') ORDER BY sort_order, price_amount"
        ).fetchall()
        public_legal = legal_settings(conn)
        term_offers = public_tariff_term_offers(conn)
    return {
        "ok": True,
        "tariffs": tariffs_config,
        "termOffers": term_offers,
        "tariffTerms": get_tariff_term_settings()["discount_percent"],
        "packages": [_billing_package_dict(row) for row in packages],
        "legal": public_legal,
        "legal_readiness": legal_readiness(public_legal),
        "payments_available": billing_payments_available(),
        "payment_provider": active_billing_provider(),
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


@app.get("/api/gallery/items")
async def gallery_items_page(
    request: Request,
    limit: int = 24,
    cursor: str | None = None,
    q: str = "",
    filter: str = "all",
) -> dict[str, Any]:
    """Small cursor page for the primary gallery grid; no secondary collections."""
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    limit = _clamp_limit(limit, default=24, maximum=60)
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
        _backfill_completed_video_gallery(conn, user_id)
        where_sql = ["user_id = ?", ACTIVE_IMAGE_WHERE]
        params: list[Any] = [user_id]
        if search:
            fts_query = gallery_fts_query(search)
            if fts_query:
                where_sql.append(
                    "images.rowid IN (SELECT rowid FROM images_search WHERE images_search MATCH ? AND user_id = ?)"
                )
                params.extend([fts_query, user_id])
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
        elif gallery_filter == "9:16":
            where_sql.append("width > 0 AND height > 0 AND width * 16 = height * 9")
        elif gallery_filter == "4:5":
            where_sql.append("width > 0 AND height > 0 AND width * 5 = height * 4")
        elif gallery_filter == "1:1":
            where_sql.append("width > 0 AND height > 0 AND width = height")
        elif gallery_filter == "face":
            where_sql.append("mode IN ('face', 'face_swap', 'faceswap')")
        where_clause = " AND ".join(f"({part})" for part in where_sql)
        page_params = list(params)
        cursor_clause = ""
        if cursor_value:
            cursor_created_at, cursor_id = cursor_value
            cursor_clause = "AND (created_at < ? OR (created_at = ? AND id < ?))"
            page_params.extend([cursor_created_at, cursor_created_at, cursor_id])
        page_params.append(limit + 1)
        image_rows = conn.execute(
            f"""
            SELECT * FROM images
            WHERE {where_clause} {cursor_clause}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            page_params,
        ).fetchall()
        has_more = len(image_rows) > limit
        page_rows = image_rows[:limit]
        page_ids = [str(row["id"]) for row in page_rows]
        publications: dict[str, sqlite3.Row] = {}
        if page_ids:
            placeholders = ",".join("?" for _ in page_ids)
            publications = {
                row["image_id"]: row
                for row in conn.execute(
                    f"SELECT * FROM feed_publications WHERE legacy_user_id = ? AND status = 'published' "
                    f"AND image_id IN ({placeholders})",
                    [user_id, *page_ids],
                ).fetchall()
            }
        image_items = [_gallery_page_item(row, publications.get(row["id"])) for row in page_rows]
        video_where = ["user_id = ?", "deleted_at IS NULL"]
        video_params: list[Any] = [user_id]
        if search:
            like = f"%{search}%"
            video_where.append("(id LIKE ? OR prompt_original LIKE ? OR mode LIKE ? OR provider LIKE ? OR settings_json LIKE ?)")
            video_params.extend([like, like, like, like, like])
        if gallery_filter == "favorite":
            video_where.append("is_favorite = 1")
        elif gallery_filter == "published":
            video_where.append("EXISTS (SELECT 1 FROM feed_publications p WHERE p.video_id = videos.id AND p.legacy_user_id = ? AND p.status = 'published')")
            video_params.append(user_id)
        elif gallery_filter == "unpublished":
            video_where.append("NOT EXISTS (SELECT 1 FROM feed_publications p WHERE p.video_id = videos.id AND p.legacy_user_id = ? AND p.status = 'published')")
            video_params.append(user_id)
        elif gallery_filter == "face" or gallery_filter == "image":
            video_where.append("0 = 1")
        elif gallery_filter == "16:9":
            video_where.append("aspect_ratio = '16:9'")
        elif gallery_filter == "9:16":
            video_where.append("aspect_ratio = '9:16'")
        elif gallery_filter == "1:1":
            video_where.append("aspect_ratio = '1:1'")
        elif gallery_filter == "video":
            pass
        if cursor_value:
            video_where.append("(created_at < ? OR (created_at = ? AND id < ?))")
            video_params.extend([cursor_value[0], cursor_value[0], cursor_value[1]])
        video_rows = conn.execute(
            f"SELECT * FROM videos WHERE {' AND '.join(f'({part})' for part in video_where)} "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            [*video_params, limit + 1],
        ).fetchall()
        video_ids = [str(row["id"]) for row in video_rows]
        video_publications: dict[str, sqlite3.Row] = {}
        if video_ids:
            placeholders = ",".join("?" for _ in video_ids)
            video_publications = {
                str(row["video_id"]): row
                for row in conn.execute(
                    f"SELECT * FROM feed_publications WHERE legacy_user_id = ? AND video_id IN ({placeholders})",
                    [user_id, *video_ids],
                ).fetchall()
            }
        video_items = [_video_gallery_item(row, video_publications.get(str(row["id"]))) for row in video_rows]
        if gallery_filter == "video":
            image_items = []
        combined_items = sorted(
            [*image_items, *video_items],
            key=lambda item: (str(item.get("createdAt") or ""), str(item.get("id") or "")),
            reverse=True,
        )
        has_more = len(combined_items) > limit or len(image_rows) > limit or len(video_rows) > limit
        items = combined_items[:limit]
        limits = _gallery_page_limits(conn, user_row, user_id)
    return {
        "ok": True,
        "limits": limits,
        "capabilities": {"videoFeedPublication": FEED_VIDEO_PUBLICATION_ENABLED},
        "items": items,
        "hasMore": has_more,
        "nextCursor": gallery_query.encode_gallery_cursor(items[-1]["createdAt"], items[-1]["id"]) if has_more and items else None,
    }


@app.get("/api/gallery/secondary")
async def gallery_secondary(request: Request, limit: int = 24, q: str = "", filter: str = "all") -> dict[str, Any]:
    payload = await _gallery_page_payload(
        request=request,
        limit=limit,
        cursor=None,
        q=q,
        filter=filter,
        secondary_only=True,
    )
    return {
        "ok": True,
        "limits": payload["limits"],
        "capabilities": payload.get("capabilities", {}),
        "feedItems": payload["feedItems"],
        "uploadedItems": payload["uploadedItems"],
        "uploadedUnavailableCount": payload["uploadedUnavailableCount"],
    }


async def _gallery_page_payload(
    request: Request,
    limit: int = 60,
    cursor: str | None = None,
    q: str = "",
    filter: str = "all",
    *,
    secondary_only: bool = False,
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
        if secondary_only:
            image_rows = []
        elif cursor_value:
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
        publication_rows = conn.execute(
            """
            SELECT * FROM feed_publications
            WHERE legacy_user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()
        image_publications = {
            str(row["image_id"]): row
            for row in publication_rows
            if row["image_id"] and row["status"] == "published"
        }
        video_publications = {
            str(row["video_id"]): row
            for row in publication_rows
            if row["video_id"]
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
        items = [_gallery_page_item(row, image_publications.get(str(row["id"]))) for row in page_rows]
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
        elif gallery_filter == "video":
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
            _gallery_page_item(row, image_publications[str(row["id"])], include_feed_media=True)
            for row in feed_rows
            if str(row["id"]) in image_publications and _feed_publication_ready(image_publications[str(row["id"])])
        ]
        video_feed_where = [
            "videos.user_id = ?",
            "videos.deleted_at IS NULL",
            "p.legacy_user_id = ?",
            "p.status = 'published'",
            "p.media_ready_at IS NOT NULL",
            "p.video_poster_name IS NOT NULL",
            "p.video_preview_name IS NOT NULL",
            "p.video_full_name IS NOT NULL",
        ]
        video_feed_params: list[Any] = [user_id, user_id]
        if search:
            like = f"%{search}%"
            video_feed_where.append(
                "(videos.id LIKE ? OR videos.prompt_original LIKE ? OR videos.mode LIKE ? OR videos.provider LIKE ? OR videos.settings_json LIKE ?)"
            )
            video_feed_params.extend([like, like, like, like, like])
        if gallery_filter == "favorite":
            video_feed_where.append("videos.is_favorite = 1")
        elif gallery_filter == "unpublished" or gallery_filter == "image" or gallery_filter == "face":
            video_feed_where.append("0 = 1")
        elif gallery_filter in {"16:9", "9:16", "4:5", "1:1"}:
            video_feed_where.append("videos.aspect_ratio = ?")
            video_feed_params.append(gallery_filter)
        video_feed_rows = conn.execute(
            f"""
            SELECT DISTINCT videos.*
            FROM videos
            JOIN feed_publications p ON p.video_id = videos.id
            WHERE {' AND '.join(f'({part})' for part in video_feed_where)}
            ORDER BY p.created_at DESC, videos.created_at DESC, videos.id DESC
            LIMIT ?
            """,
            [*video_feed_params, limit],
        ).fetchall()
        video_feed_items = [
            _video_gallery_item(row, video_publications.get(str(row["id"])), include_feed_media=True)
            for row in video_feed_rows
            if str(row["id"]) in video_publications and _feed_publication_ready(video_publications[str(row["id"])])
        ]
        feed_items = sorted(
            [*feed_items, *video_feed_items],
            key=lambda item: (str(item.get("publishedAt") or item.get("createdAt") or ""), str(item.get("id") or "")),
            reverse=True,
        )[:limit]
        for item in feed_items:
            counts = reaction_counts.get(item["feedPublicationId"])
            item["likes"] = int(_row_get(counts, "likes") or 0)
            item["saves"] = int(_row_get(counts, "saves") or 0)
            item["remixes"] = int(_row_get(counts, "remixes") or 0)
        uploaded_where = [
            "s.user_id = ?",
            "s.source_kind IN ('upload', 'media')",
            "(s.library_deleted_at IS NULL OR s.library_deleted_at = '')",
        ]
        uploaded_params: list[Any] = [user_id]
        if search:
            like = f"%{search}%"
            uploaded_where.append("(s.role LIKE ? OR s.source_kind LIKE ? OR images.prompt_original LIKE ?)")
            uploaded_params.extend([like, like, like])
        unavailable_uploaded_count = int(conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM image_sources s
            LEFT JOIN images ON images.id = s.image_id AND images.user_id = s.user_id
            WHERE {' AND '.join(f'({part})' for part in uploaded_where)}
              AND s.availability_status = 'missing'
            """,
            uploaded_params,
        ).fetchone()["count"] or 0)
        uploaded_where.append("s.availability_status = 'available'")
        uploaded_rows = conn.execute(
            f"""
            SELECT s.*, images.mode AS owner_mode
            FROM image_sources s
            LEFT JOIN images ON images.id = s.image_id AND images.user_id = s.user_id
            WHERE {' AND '.join(f'({part})' for part in uploaded_where)}
            ORDER BY s.created_at DESC, s.slot_index ASC
            LIMIT ?
            """,
            [*uploaded_params, min(limit * 2, 120)],
        ).fetchall()
        uploaded_items = [
            {
                "id": row["id"],
                "imageId": row["image_id"],
                "sourceImageId": row["source_image_id"],
                "sourceKind": row["source_kind"],
                "role": row["role"],
                "roleLabel": _source_role_label(row["role"], int(row["slot_index"] or 0), row["owner_mode"]),
                "slotIndex": int(row["slot_index"] or 0),
                "thumbnailUrl": row["thumb_url"],
                "width": int(row["thumb_width"] or 0),
                "height": int(row["thumb_height"] or 0),
                "fileSizeBytes": int(row["thumb_bytes"] or 0),
                "favorite": bool(row["is_favorite"]),
                "createdAt": row["created_at"],
            }
            for row in uploaded_rows
        ]
        limits = _gallery_page_limits(conn, user_row, user_id)
    return {
        "ok": True,
        "limits": limits,
        "capabilities": {"videoFeedPublication": FEED_VIDEO_PUBLICATION_ENABLED},
        "items": items,
        "feedItems": feed_items,
        "uploadedItems": uploaded_items,
        "uploadedUnavailableCount": unavailable_uploaded_count,
        "hasMore": has_more,
        "nextCursor": gallery_cursor_from_row(page_rows[-1]) if has_more and page_rows else None,
    }


@app.get("/api/gallery/page")
async def gallery_page(
    request: Request,
    limit: int = 60,
    cursor: str | None = None,
    q: str = "",
    filter: str = "all",
) -> dict[str, Any]:
    """Compatibility aggregate for clients that still consume every gallery section."""
    return await _gallery_page_payload(
        request=request,
        limit=limit,
        cursor=cursor,
        q=q,
        filter=filter,
    )


@app.post("/api/gallery/sources/{source_id}/use-as")
async def gallery_source_use_as(source_id: str, req: UseAsRequest, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        if not user_gallery_allowed(conn, trusted["internal_user_id"], user_id):
            raise HTTPException(403, "Gallery is not available for this plan.")
        row = conn.execute(
            """
            SELECT s.* FROM image_sources s
            WHERE s.id = ? AND s.user_id = ?
              AND (s.library_deleted_at IS NULL OR s.library_deleted_at = '')
              AND s.availability_status = 'available'
            LIMIT 1
            """,
            (source_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Source image not found")
        source_path = local_media_path_from_url(row["thumb_url"])
        if source_path is None or not source_path.is_file() or source_path.stat().st_size <= 0:
            checked_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE image_sources SET availability_status = 'missing', availability_checked_at = ?, unavailable_at = ? WHERE id = ?",
                (checked_at, checked_at, source_id),
            )
            raise HTTPException(410, "Source image is unavailable")
    return {
        "ok": True,
        "sourceId": source_id,
        "target": req.target,
        "inputImage": row["thumb_url"],
        "width": int(row["thumb_width"] or 0),
        "height": int(row["thumb_height"] or 0),
        "role": row["role"],
    }


@app.post("/api/gallery/sources/{source_id}/favorite")
async def gallery_source_favorite(source_id: str, req: FavoriteRequest, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM image_sources WHERE id = ? AND user_id = ?",
            (source_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Source image not found")
        conn.execute(
            "UPDATE image_sources SET is_favorite = ? WHERE id = ? AND user_id = ?",
            (1 if req.isFavorite else 0, source_id, user_id),
        )
    return {"ok": True, "sourceId": source_id, "favorite": req.isFavorite}


@app.delete("/api/gallery/sources/{source_id}")
async def gallery_source_delete(source_id: str, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM image_sources WHERE id = ? AND user_id = ?",
            (source_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Source image not found")
        conn.execute(
            "UPDATE image_sources SET library_deleted_at = ?, is_favorite = 0 WHERE id = ? AND user_id = ?",
            (now, source_id, user_id),
        )
    return {"ok": True, "sourceId": source_id, "retainedForHistory": True}


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
        row = conn.execute(
            f"SELECT * FROM images WHERE id = ? AND user_id = ? AND {ACTIVE_IMAGE_WHERE}",
            (image_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Image not found")
        record = row_to_image(row)
    image_path = local_media_path_from_url(record["url"])
    if image_path is None or not image_path.is_file() or image_path.stat().st_size <= 0:
        raise HTTPException(410, "Image file is unavailable")
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


def _private_media_runtime() -> PrivateMediaRuntime:
    return PrivateMediaRuntime(
        connect=db,
        resolve_trusted_user=require_trusted_user,
        owner_exists=lambda conn, filename, user_id: gallery_media_owner_row(conn, filename, user_id) is not None,
        cached_images=lambda: images.values(),
        resolve_path=storage_resolve_under_root,
    )


def _public_media_runtime() -> PublicMediaRuntime:
    return PublicMediaRuntime(connect=db, resolve_path=storage_resolve_under_root)


def private_media_response(filename: str, request: Request) -> FileResponse:
    try:
        path = storage_resolve_private_media(_private_media_runtime(), MEDIA, filename, request)
    except PrivateMediaAccessError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/media/{filename}")
async def secure_media(filename: str, request: Request) -> FileResponse:
    return private_media_response(filename, request)


@app.get("/media/avatars/{filename}")
async def public_custom_avatar(filename: str) -> FileResponse:
    """Serve only custom avatars that are currently referenced by a user.

    User avatars are part of public feed/profile payloads. Keeping this narrow
    route preserves those public profiles without exposing the rest of MEDIA.
    """
    try:
        path = storage_resolve_public_avatar(_public_media_runtime(), AVATAR_DIR, filename)
    except PublicMediaAccessError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/media/{filename:path}")
async def legacy_secure_media(filename: str, request: Request) -> FileResponse:
    """Compatibility route for old database URLs, protected like `/api/media`."""
    return private_media_response(filename, request)


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
    token, nonce, expires_at = create_bot_login_challenge(provider, request)
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
    token, nonce, expires_at = create_bot_login_challenge(
        provider,
        request,
        internal_user_id=user["internal_user_id"],
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


install_password_change_route(app, PasswordChangeRuntime(
    db, require_trusted_user, validate_password_policy, verify_password_argon2, hash_password_argon2,
    record_security_event, revoke_auth_session, record_event_log,
))


@app.get("/api/me-v2")
async def me_v2(request: Request) -> dict[str, Any]:
    """Current user, resolved strictly from the trusted session. Exposes no token
    hashes, no OTP/code hashes, no raw tokens, and no full raw_profile_json."""
    user = require_trusted_user(request)
    iuid = user["internal_user_id"]
    legacy = user["legacy_user_id"]
    with db() as conn:
        _reconcile_user_tariff(conn, iuid)
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
        password_configured = password_is_configured(conn, iuid)
        gallery_access = bool(user_gallery_allowed(conn, iuid, legacy))
        gallery_quota = gallery_quota_for_user(conn, urow, legacy)
        video_state = video_storage_state_for_user(conn, urow, legacy)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_tokens_used = int(_row_get(urow, "daily_tokens_used") or 0)
        if _row_get(urow, "last_daily_reset") != today:
            daily_tokens_used = 0
        daily_tokens_limit = int(gallery_quota["daily_tokens"])
        daily_tokens_remaining = max(0, daily_tokens_limit - daily_tokens_used)
        monthly_tokens_grant = int(gallery_quota.get("monthly_tokens", 0) or 0)
        pending_plan = safe_json_load(_row_get(urow, "pending_plan_json")) or None

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
            "monthly_tokens_grant": monthly_tokens_grant,
            "plan_started_at": _row_get(urow, "plan_started_at"),
            "plan_expires_at": _row_get(urow, "plan_expires_at"),
            "plan_next_token_grant_at": _row_get(urow, "plan_next_token_grant_at"),
            "plan_term_months": int(_row_get(urow, "plan_term_months") or 1),
            "pending_plan": pending_plan if isinstance(pending_plan, dict) else None,
            "gallery_slots": gallery_quota["gallery_slots"],
            "gallery_used": gallery_quota["gallery_used"],
            "gallery_free": gallery_quota["gallery_free"],
            "gallery_full": gallery_quota["gallery_full"],
            "video_enabled": gallery_quota["video_enabled"],
            "video_slots": gallery_quota["video_slots"],
            "video_used": video_state.active,
            "video_free": video_state.free,
            "password_configured": password_configured,
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


TOKEN_HISTORY_REASONS = {
    "generation",
    "daily_generation",
    "openrouter_monthly_generation",
    "generation_refund",
    "daily_generation_refund",
    "openrouter_monthly_generation_refund",
    "admin_adjust",
    "admin_register",
    "payment_grant",
    "bonus_grant",
    "promo_apply",
    "referral_reward",
    "tariff_monthly_grant",
}


def _token_history_spent(row: sqlite3.Row, meta: dict[str, Any]) -> int:
    delta = int(row["delta"] or 0)
    reason = str(row["reason"] or "")
    if reason in {"generation", "daily_generation", "openrouter_monthly_generation"} and meta.get("token_cost") is not None:
        return max(0, int(meta.get("token_cost") or 0))
    if delta < 0:
        return abs(delta)
    return 0


def _token_history_source(row: sqlite3.Row, meta: dict[str, Any]) -> str:
    reason = str(row["reason"] or "")
    provider = str(meta.get("provider") or "")
    if reason == "daily_generation":
        return "дневной пакет"
    if reason == "openrouter_monthly_generation":
        return "основной баланс"
    if reason == "tariff_monthly_grant":
        return "тарифное начисление"
    if provider == "openrouter":
        return "баланс токенов"
    if reason.endswith("_refund"):
        return "возврат"
    if reason in {"payment_grant", "bonus_grant", "promo_apply", "referral_reward", "admin_register", "admin_adjust", "tariff_monthly_grant"}:
        return "начисление"
    return "баланс токенов"


@app.get("/api/account/token-history-v2")
async def account_token_history_v2(request: Request, days: int = 30, limit: int = 80) -> dict[str, Any]:
    user = require_trusted_user(request)
    legacy_user_id = user["legacy_user_id"]
    days = max(1, min(int(days or 30), 365))
    limit = max(1, min(int(limit or 80), 200))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db() as conn:
        urow = conn.execute("SELECT * FROM users WHERE id = ?", (legacy_user_id,)).fetchone()
        if urow is None:
            raise HTTPException(404, "User not found.")
        rows = conn.execute(
            """
            SELECT id, delta, reason, meta_json, created_at
            FROM token_ledger
            WHERE user_id = ? AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (legacy_user_id, since, limit),
        ).fetchall()
    items: list[dict[str, Any]] = []
    spent_total = 0
    balance_spent = 0
    included_spent = 0
    refunded = 0
    for row in rows:
        raw_meta = safe_json_load(row["meta_json"]) or {}
        meta = raw_meta if isinstance(raw_meta, dict) else {}
        spent = _token_history_spent(row, meta)
        delta = int(row["delta"] or 0)
        reason = str(row["reason"] or "")
        if spent > 0:
            spent_total += spent
            if delta < 0:
                balance_spent += abs(delta)
                included_spent += max(0, spent - abs(delta))
            else:
                included_spent += spent
        if delta > 0 and reason.endswith("_refund"):
            refunded += delta
        billing = meta.get("billing") if isinstance(meta.get("billing"), dict) else {}
        items.append({
            "id": short_public_id(row["id"], 10),
            "delta": delta,
            "spentTokens": spent,
            "reason": reason,
            "source": _token_history_source(row, meta),
            "mode": meta.get("mode"),
            "provider": meta.get("provider"),
            "jobId": short_public_id(meta.get("jobId") or meta.get("job_id")),
            "model": billing.get("modelName") or billing.get("modelId"),
            "createdAt": row["created_at"],
        })
    return {
        "ok": True,
        "days": days,
        "limit": limit,
        "summary": {
            "spentTokens": spent_total,
            "balanceSpentTokens": balance_spent,
            "includedSpentTokens": included_spent,
            "refundedTokens": refunded,
            "balance": int(_row_get(urow, "token_balance") or 0),
        },
        "items": items,
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
        receipt_email = billing_profile_email(conn, iuid)
    return {
        "internal_user_id": iuid,
        "legacy_user_id": legacy,
        "profile": build_profile(urow),
        "billing": {"receipt_email": receipt_email or None},
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
    avatar_bytes = compress_avatar_image(data, content_type)

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
    row = conn.execute(
        "SELECT id, internal_user_id, role, banned, token_balance, plan, plan_expires_at, "
        "display_name, email, personal_discount_percent FROM users WHERE internal_user_id = ?",
        (internal_user_id,),
    ).fetchone()
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


def _billing_discount(base_amount: int, percent: int | None) -> tuple[int, int, int]:
    subtotal = max(0, int(base_amount or 0))
    safe_percent = max(0, min(90, int(percent or 0)))
    discount = min(subtotal, (subtotal * safe_percent + 50) // 100)
    return subtotal, discount, max(1, subtotal - discount)


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


def _sync_tariff_billing_packages(conn: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    tariffs = get_tariff_config(conn)
    offers = tariff_term_offers(conn)
    for plan_index, plan in enumerate(("mini", "plus", "pro", "business"), start=1):
        tariff = tariffs[plan]
        active_codes: list[str] = []
        for term_index, offer in enumerate(offers[plan]):
            code = str(offer["code"])
            months = int(offer["months"])
            active_codes.append(code)
            conn.execute(
                """
                INSERT INTO billing_packages
                    (id, code, name, description, price_amount, currency, token_amount, is_active, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'RUB', 0, 1, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET name=excluded.name, description=excluded.description,
                    price_amount=excluded.price_amount, token_amount=0, is_active=1,
                    sort_order=excluded.sort_order, updated_at=excluded.updated_at
                """,
                (
                    uuid.uuid4().hex,
                    code,
                    f"Тариф {tariff['title']} на {months} мес.",
                    f"{tariff['note']} · {months} мес.",
                    int(offer["price_total_rub"]),
                    100 + plan_index * 10 + term_index,
                    now,
                    now,
                ),
            )
        placeholders = ",".join("?" for _ in active_codes)
        conn.execute(
            f"UPDATE billing_packages SET is_active=0, updated_at=? WHERE code LIKE ? AND code NOT IN ({placeholders})",
            (now, f"tariff_{plan}%", *active_codes),
        )


def _billing_projection(conn: sqlite3.Connection, internal_user_id: str) -> dict[str, Any]:
    user = conn.execute(
        "SELECT personal_discount_percent FROM users WHERE internal_user_id = ?",
        (internal_user_id,),
    ).fetchone()
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
            "personal_discount_percent": int(user["personal_discount_percent"] or 0) if user else 0,
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


@app.post("/api/admin/users/{internal_user_id}/discount-v2")
async def admin_discount_v2(internal_user_id: str, req: AdminDiscountV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = (req.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Укажите причину.")
    with db() as conn:
        target = _admin_load_target(conn, internal_user_id)
        old_percent = int(target["personal_discount_percent"] or 0)
        conn.execute(
            "UPDATE users SET personal_discount_percent = ? WHERE internal_user_id = ?",
            (req.percent, internal_user_id),
        )
        record_audit_log(
            conn,
            "admin_change_personal_discount",
            actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=internal_user_id,
            entity_id=target["id"],
            before={"personal_discount_percent": old_percent},
            after={"personal_discount_percent": req.percent, "reason": reason},
            request=request,
        )
    return {
        "ok": True,
        "internal_user_id": internal_user_id,
        "old_percent": old_percent,
        "personal_discount_percent": req.percent,
    }


@app.post("/api/admin/users/{internal_user_id}/plan-v2")
async def admin_plan_v2(internal_user_id: str, req: AdminPlanV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = (req.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Укажите причину.")
    with db() as conn:
        target = _admin_load_target(conn, internal_user_id)
        activation = _activate_tariff_now(
            conn,
            internal_user_id=internal_user_id,
            plan=req.plan,
            now=datetime.now(timezone.utc),
            source="admin",
            source_id=uuid.uuid4().hex,
            duration_days=req.duration_days,
        )
        record_audit_log(conn, "admin_change_plan", actor_internal_user_id=admin["internal_user_id"],
                         target_internal_user_id=internal_user_id, entity_id=target["id"],
                         before={"plan": target["plan"]},
                         after={"plan": req.plan, "duration_days": req.duration_days, "reason": reason}, request=request)
    return {"ok": True, "internal_user_id": internal_user_id, "plan": req.plan, "activation": activation}


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


@app.get("/api/billing/packages-v2")
async def billing_packages_v2(request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    with db() as conn:
        _sync_tariff_billing_packages(conn)
        rows = conn.execute(
            "SELECT * FROM billing_packages WHERE is_active = 1 AND (code LIKE 'tokens_%' OR code LIKE 'tariff_%') ORDER BY sort_order, price_amount"
        ).fetchall()
        user = _admin_load_target(conn, trusted["internal_user_id"])
        _reconcile_user_tariff(conn, trusted["internal_user_id"])
        settings = legal_settings(conn)
        receipt_email = billing_profile_email(conn, trusted["internal_user_id"])
        discount_percent = int(user["personal_discount_percent"] or 0)
        offers_by_code = {
            str(offer["code"]): (plan, offer)
            for plan, offers in public_tariff_term_offers(conn).items()
            for offer in offers
        }
        packages = []
        for row in rows:
            item = _billing_package_dict(row)
            subtotal, discount_amount, total = _billing_discount(item["price_amount"], discount_percent)
            item.update(
                {
                    "base_price_amount": subtotal,
                    "discount_percent": discount_percent,
                    "discount_amount": discount_amount,
                    "price_amount": total,
                }
            )
            offer_data = offers_by_code.get(str(item["code"]))
            if offer_data:
                plan, offer = offer_data
                item.update(
                    {
                        "kind": "tariff",
                        "plan": plan,
                        "term_months": int(offer["months"]),
                        "monthly_price_amount": int(offer["monthly_price_rub"]),
                        "term_discount_percent": int(offer["discount_percent"]),
                        "term_base_price_amount": int(offer["base_total_rub"]),
                        "term_savings_amount": int(offer["savings_rub"]),
                        "included_tokens": int(offer["included_tokens"]),
                        "effective_token_price_rub": offer["effective_token_price_rub"],
                        "personal_discount_percent": discount_percent,
                    }
                )
            else:
                item["kind"] = "tokens"
            packages.append(item)
    return {
        "ok": True,
        "provider_ready": billing_payments_available(),
        "provider": active_billing_provider(),
        "personal_discount_percent": discount_percent,
        "packages": packages,
        "checkout": {
            "fiscalization_mode": "self_employed_manual" if seller_is_self_employed(settings) else "yookassa_54fz",
            "contact_type": "email",
            "receipt_delivery": "seller" if seller_is_self_employed(settings) else "provider",
            "receipt_email": receipt_email or None,
        },
        "legal": {
            key: settings.get(key)
            for key in (
                "brand_name", "seller_name", "seller_status", "inn", "ogrn",
                "legal_address", "support_email", "support_phone", "support_hours",
                "site_url", "offer_version",
            )
        },
    }


@app.post("/api/account/tariff-v2/schedule-free")
async def account_schedule_free_v2(req: BillingScheduleFreeV2Request, request: Request) -> dict[str, Any]:
    """Schedule Free for the end of a paid term without touching the main balance."""
    trusted = require_trusted_user(request)
    if not req.confirm:
        raise HTTPException(400, "Подтвердите переход на бесплатный тариф.")
    now = datetime.now(timezone.utc)
    with db() as conn:
        _reconcile_user_tariff(conn, trusted["internal_user_id"], now=now)
        row = conn.execute(
            "SELECT plan, plan_expires_at, token_balance FROM users WHERE internal_user_id=?",
            (trusted["internal_user_id"],),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Пользователь не найден.")
        if str(row["plan"] or "free").lower() == "free":
            return {
                "ok": True,
                "already_free": True,
                "plan": "free",
                "token_balance": int(row["token_balance"] or 0),
            }
        lifecycle = _schedule_or_activate_paid_tariff(
            conn,
            internal_user_id=trusted["internal_user_id"],
            plan="free",
            term_months=1,
            source="user_downgrade",
            source_id=uuid.uuid4().hex,
            now=now,
        )
        updated = conn.execute(
            "SELECT plan, plan_expires_at, pending_plan_json, token_balance FROM users WHERE internal_user_id=?",
            (trusted["internal_user_id"],),
        ).fetchone()
    return {
        "ok": True,
        "plan": str(updated["plan"] or "free"),
        "plan_expires_at": updated["plan_expires_at"],
        "pending_plan": safe_json_load(updated["pending_plan_json"]) or None,
        "token_balance": int(updated["token_balance"] or 0),
        "lifecycle": lifecycle,
    }


@app.post("/api/billing/checkout-v2")
async def billing_checkout_v2(req: BillingCheckoutV2Request, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    if not req.offer_accepted:
        raise HTTPException(400, "Подтвердите принятие публичной оферты и условий оплаты.")
    settings = legal_settings()
    self_employed = seller_is_self_employed(settings)
    receipt_contact = str(req.receipt_contact or "").strip()
    if not receipt_contact:
        raise HTTPException(400, "Укажите email для получения чека.")
    normalized_receipt_email = normalize_email(receipt_contact)
    valid_contact = bool(normalized_receipt_email) if self_employed or "@" in receipt_contact else len(re.sub(r"\D", "", receipt_contact)) >= 10
    if not valid_contact:
        raise HTTPException(400, "Введите корректный email для получения чека." if self_employed else "Введите корректный email или номер телефона для электронного чека.")
    readiness = legal_readiness(settings)
    if not readiness["ready"]:
        raise HTTPException(503, "Прием платежей временно недоступен: публичные реквизиты продавца не заполнены.")
    provider_name = active_billing_provider()
    if provider_name is None:
        raise HTTPException(503, "Прием платежей пока не настроен.")
    config = yookassa_config()
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _sync_tariff_billing_packages(conn)
        existing = conn.execute("SELECT * FROM payments WHERE idempotency_key = ?", (req.idempotency_key,)).fetchone()
        if existing is not None:
            return {
                "ok": True,
                "payment_id": existing["id"],
                "provider_payment_id": existing["provider_payment_id"],
                "status": existing["status"],
                "payment": _billing_payment_dict(existing),
                "confirmation_url": f"{public_site_url(request)}/payment?payment_id={existing['id']}",
                "idempotent": True,
            }
        package = conn.execute("SELECT * FROM billing_packages WHERE code = ? AND is_active = 1", (req.package_code,)).fetchone()
        if package is None:
            raise HTTPException(404, "Пакет токенов не найден.")
        target = _admin_load_target(conn, trusted["internal_user_id"])
        subtotal_amount, discount_amount, total_amount = _billing_discount(
            int(package["price_amount"]),
            int(target["personal_discount_percent"] or 0),
        )
        invoice_id = uuid.uuid4().hex
        payment_id = uuid.uuid4().hex
        invoice_code = _invoice_code(conn)
        conn.execute(
            "INSERT INTO invoices (id, invoice_code, internal_user_id, user_id, status, currency, subtotal_amount, discount_amount, total_amount, tokens_total, reason, created_at, updated_at) VALUES (?, ?, ?, ?, 'draft', 'RUB', ?, ?, ?, ?, 'user_checkout', ?, ?)",
            (invoice_id, invoice_code, trusted["internal_user_id"], target["id"], subtotal_amount, discount_amount, total_amount, package["token_amount"], now, now),
        )
        conn.execute(
            "INSERT INTO invoice_items (id, invoice_id, package_code, title, description, quantity, unit_amount, total_amount, token_amount, created_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (uuid.uuid4().hex, invoice_id, package["code"], package["name"], package["description"], total_amount, total_amount, package["token_amount"], now),
        )
        conn.execute(
            "INSERT INTO payments (id, invoice_id, internal_user_id, user_id, status, amount, currency, method, provider, reason, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', ?, 'RUB', 'bank_card', ?, 'user_checkout', ?, ?, ?)",
            (payment_id, invoice_id, trusted["internal_user_id"], target["id"], total_amount, provider_name, req.idempotency_key, now, now),
        )
        offer_version = legal_settings(conn)["offer_version"]
        conn.execute(
            "INSERT INTO legal_acceptances (id, internal_user_id, payment_id, document_type, document_version, receipt_contact, ip_address, user_agent, accepted_at) VALUES (?, ?, ?, 'public_offer', ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                trusted["internal_user_id"],
                payment_id,
                offer_version,
                receipt_contact or None,
                request.client.host if request.client else None,
                (request.headers.get("user-agent") or "")[:500],
                now,
            ),
        )
        if normalized_receipt_email:
            save_billing_profile_email(
                conn,
                trusted["internal_user_id"],
                normalized_receipt_email,
                updated_at=now,
            )
    receipt = None
    if not self_employed:
        receipt = PaymentReceipt(
            contact=receipt_contact,
            items=(
                PaymentReceiptItem(
                    description=str(package["name"]),
                    quantity=1,
                    amount=total_amount,
                ),
            ),
        )
    command = PaymentCreateCommand(
        amount=total_amount,
        currency="RUB",
        idempotency_key=req.idempotency_key,
        return_url=f"{public_site_url(request)}/payment?payment_id={payment_id}",
        description=f"ИЗО АСА: {package['name']}",
        metadata={"invoice_id": invoice_id, "payment_id": payment_id},
        receipt=receipt,
    )
    try:
        if provider_name == "simulator":
            provider_payment = await simulated_payment_provider().create_payment(command)
        else:
            raw_payment = await create_yookassa_payment(
                shop_id=str(config["shop_id"]),
                secret_key=yookassa_secret_key(),
                amount=command.amount,
                idempotency_key=command.idempotency_key,
                return_url=command.return_url,
                description=command.description,
                metadata=dict(command.metadata),
                receipt=(
                    build_yookassa_receipt(
                        command,
                        vat_code=config.get("receipt_vat_code"),
                        payment_subject=str(config.get("payment_subject") or "service"),
                    )
                    if command.receipt is not None
                    else None
                ),
            )
            provider_payment = raw_payment
    except (YooKassaError, PaymentProviderError, ValueError) as exc:
        with db() as conn:
            failed_at = datetime.now(timezone.utc).isoformat()
            conn.execute("UPDATE payments SET status='failed', updated_at=? WHERE id=?", (failed_at, payment_id))
            conn.execute("UPDATE invoices SET status='cancelled', cancelled_at=?, updated_at=? WHERE id=?", (failed_at, failed_at, invoice_id))
        raise HTTPException(502, str(exc)) from exc
    with db() as conn:
        conn.execute("UPDATE payments SET provider_payment_id=?, status='pending', updated_at=? WHERE id=?", (provider_payment.id, datetime.now(timezone.utc).isoformat(), payment_id))
        conn.execute("UPDATE invoices SET status='issued', issued_at=?, updated_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), invoice_id))
    completed = None
    if provider_payment.status == "succeeded" and provider_payment.paid:
        verified_amount = provider_payment.amount_value if provider_name == "yookassa" else f"{provider_payment.amount:.2f}"
        completed = _complete_provider_payment(provider_name, provider_payment.id, verified_amount=verified_amount, verified_currency=provider_payment.currency)
    return {"ok": True, "payment_id": payment_id, "provider_payment_id": provider_payment.id, "status": provider_payment.status, "confirmation_url": provider_payment.confirmation_url, "completed": completed}


@app.get("/api/billing/payments/{payment_id}/status-v2")
async def billing_payment_status_v2(payment_id: str, request: Request) -> dict[str, Any]:
    """Return a user's payment status and reconcile pending YooKassa payments."""
    trusted = require_trusted_user(request)
    with db() as conn:
        payment = conn.execute(
            "SELECT * FROM payments WHERE id=? AND internal_user_id=?",
            (payment_id, trusted["internal_user_id"]),
        ).fetchone()
    if payment is None:
        raise HTTPException(404, "Платеж не найден.")

    verification_error = None
    if payment["status"] == "pending" and payment["provider_payment_id"]:
        try:
            if payment["provider"] == "simulator" and billing_simulator_enabled():
                simulated = await simulated_payment_provider().fetch_payment(str(payment["provider_payment_id"]))
                verified_status = simulated.status
                verified_paid = simulated.paid
                verified_id = simulated.id
                verified_amount = f"{simulated.amount:.2f}"
                verified_currency = simulated.currency
            elif payment["provider"] == "yookassa" and yookassa_checkout_ready():
                config = yookassa_config()
                verified = await fetch_yookassa_payment(
                    str(payment["provider_payment_id"]),
                    shop_id=str(config["shop_id"]),
                    secret_key=yookassa_secret_key(),
                )
                verified_status = verified.status
                verified_paid = verified.paid
                verified_id = verified.id
                verified_amount = verified.amount_value
                verified_currency = verified.currency
            else:
                verified_status = "pending"
                verified_paid = False
                verified_id = str(payment["provider_payment_id"])
                verified_amount = f"{int(payment['amount'] or 0):.2f}"
                verified_currency = str(payment["currency"])
            if verified_status == "succeeded" and verified_paid:
                _complete_provider_payment(
                    str(payment["provider"]),
                    verified_id,
                    verified_amount=verified_amount,
                    verified_currency=verified_currency,
                )
            elif verified_status == "canceled":
                _cancel_provider_payment(str(payment["provider"]), verified_id)
        except (YooKassaError, PaymentProviderError, HTTPException) as exc:
            verification_error = str(getattr(exc, "detail", exc))

    with db() as conn:
        row = conn.execute(
            """
            SELECT p.*, i.invoice_code, i.tokens_total, ii.package_code, ii.title AS item_title
            FROM payments p
            JOIN invoices i ON i.id=p.invoice_id
            LEFT JOIN invoice_items ii ON ii.invoice_id=i.id
            WHERE p.id=? AND p.internal_user_id=?
            ORDER BY ii.created_at LIMIT 1
            """,
            (payment_id, trusted["internal_user_id"]),
        ).fetchone()
        user = conn.execute("SELECT plan, plan_expires_at, token_balance FROM users WHERE internal_user_id=?", (trusted["internal_user_id"],)).fetchone()
    if row is None:
        raise HTTPException(404, "Платеж не найден.")
    return {
        "ok": True,
        "payment": {
            "id": row["id"],
            "status": row["status"],
            "amount": int(row["amount"] or 0),
            "currency": row["currency"],
            "title": row["item_title"] or "Оплата ИЗО АСА",
            "package_code": row["package_code"],
            "tokens": int(row["tokens_total"] or 0),
            "invoice_code": row["invoice_code"],
            "paid_at": row["paid_at"],
        },
        "account": {
            "plan": _row_get(user, "plan") or "free",
            "plan_expires_at": _row_get(user, "plan_expires_at"),
            "token_balance": int(_row_get(user, "token_balance") or 0),
        },
        "verification_error": verification_error,
    }


@app.post("/api/billing/yookassa/webhook-v2")
async def billing_yookassa_webhook_v2(request: Request) -> dict[str, Any]:
    config = yookassa_config()
    if not yookassa_ready(config):
        raise HTTPException(503, "YooKassa is not configured.")
    payload = await request.json()
    event_type = str(payload.get("event") or "") if isinstance(payload, dict) else ""
    obj = payload.get("object") if isinstance(payload, dict) and isinstance(payload.get("object"), dict) else {}
    provider_payment_id = str(obj.get("id") or "")
    if not event_type or not provider_payment_id:
        raise HTTPException(400, "Invalid YooKassa event.")
    event_key = f"{event_type}:{provider_payment_id}"
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        existing = conn.execute("SELECT * FROM payment_provider_events WHERE event_key = ?", (event_key,)).fetchone()
        if existing is not None and existing["processed_at"]:
            return {"ok": True, "idempotent": True}
        conn.execute(
            "INSERT OR IGNORE INTO payment_provider_events (id, provider, event_key, event_type, provider_payment_id, status, received_at) VALUES (?, 'yookassa', ?, ?, ?, 'received', ?)",
            (uuid.uuid4().hex, event_key, event_type, provider_payment_id, now),
        )
    try:
        verified = await fetch_yookassa_payment(provider_payment_id, shop_id=str(config["shop_id"]), secret_key=yookassa_secret_key())
        if verified.status == "succeeded" and verified.paid:
            _complete_provider_payment("yookassa", provider_payment_id, verified_amount=verified.amount_value, verified_currency=verified.currency)
        elif verified.status == "canceled":
            _cancel_provider_payment("yookassa", provider_payment_id)
        with db() as conn:
            conn.execute("UPDATE payment_provider_events SET status=?, processed_at=?, error=NULL WHERE event_key=?", (verified.status, datetime.now(timezone.utc).isoformat(), event_key))
    except (YooKassaError, HTTPException) as exc:
        with db() as conn:
            conn.execute("UPDATE payment_provider_events SET status='failed', error=? WHERE event_key=?", (truncate_admin_text(str(exc), 300), event_key))
        raise HTTPException(502, "YooKassa event verification failed.") from exc
    return {"ok": True, "status": verified.status}


@app.post("/api/admin/payments/{payment_id}/simulate-v2")
async def admin_simulate_payment_v2(
    payment_id: str,
    req: BillingSimulationV2Request,
    request: Request,
) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    if not billing_simulator_enabled():
        raise HTTPException(404, "Payment simulator is unavailable.")
    with db() as conn:
        payment = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        if payment is None:
            raise HTTPException(404, "Платеж не найден.")
        if payment["provider"] != "simulator" or not payment["provider_payment_id"]:
            raise HTTPException(409, "Этот платеж создан не симулятором.")
        before = {"status": payment["status"]}
    try:
        simulated = simulated_payment_provider().transition(str(payment["provider_payment_id"]), req.status)
        if simulated.status == "succeeded":
            result = _complete_provider_payment(
                "simulator",
                simulated.id,
                verified_amount=f"{simulated.amount:.2f}",
                verified_currency=simulated.currency,
            )
        else:
            _cancel_provider_payment("simulator", simulated.id)
            result = None
    except (PaymentProviderError, HTTPException) as exc:
        raise HTTPException(409, str(getattr(exc, "detail", exc))) from exc
    with db() as conn:
        updated = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        record_audit_log(
            conn,
            "admin_simulate_payment",
            actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=payment["internal_user_id"],
            entity_id=payment_id,
            before=before,
            after={"status": updated["status"], "reason": req.reason.strip()},
            request=request,
        )
    return {"ok": True, "payment": _billing_payment_dict(updated), "completed": result}


@app.post("/api/admin/payments/reconcile-v2")
async def admin_reconcile_payments_v2(
    req: AdminPaymentMaintenanceV2Request,
    request: Request,
) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM payments WHERE status='pending' AND provider_payment_id IS NOT NULL "
            "ORDER BY updated_at, id LIMIT ?",
            (req.limit,),
        ).fetchall()
    report: dict[str, Any] = {"checked": 0, "paid": 0, "canceled": 0, "pending": 0, "errors": []}
    for payment in rows:
        report["checked"] += 1
        try:
            if payment["provider"] == "simulator":
                if not billing_simulator_enabled():
                    raise PaymentProviderError("Payment simulator is disabled.")
                snapshot = await simulated_payment_provider().fetch_payment(str(payment["provider_payment_id"]))
                status, paid = snapshot.status, snapshot.paid
                amount, currency = f"{snapshot.amount:.2f}", snapshot.currency
            elif payment["provider"] == "yookassa":
                config = yookassa_config()
                if not yookassa_checkout_ready(config):
                    raise PaymentProviderError("YooKassa checkout is not configured.")
                snapshot = await fetch_yookassa_payment(
                    str(payment["provider_payment_id"]),
                    shop_id=str(config["shop_id"]),
                    secret_key=yookassa_secret_key(),
                )
                status, paid = snapshot.status, snapshot.paid
                amount, currency = snapshot.amount_value, snapshot.currency
            else:
                raise PaymentProviderError(f"Unsupported payment provider: {payment['provider']}")
            if status == "succeeded" and paid:
                _complete_provider_payment(
                    str(payment["provider"]),
                    str(payment["provider_payment_id"]),
                    verified_amount=amount,
                    verified_currency=currency,
                )
                report["paid"] += 1
            elif status == "canceled":
                _cancel_provider_payment(str(payment["provider"]), str(payment["provider_payment_id"]))
                report["canceled"] += 1
            else:
                report["pending"] += 1
        except (YooKassaError, PaymentProviderError, HTTPException) as exc:
            report["errors"].append({
                "payment_id": payment["id"],
                "error": truncate_admin_text(str(getattr(exc, "detail", exc)), 200),
            })
    with db() as conn:
        record_audit_log(
            conn,
            "admin_reconcile_payments",
            actor_internal_user_id=admin["internal_user_id"],
            entity_id="payments",
            after={**report, "reason": req.reason.strip()},
            request=request,
        )
    return {"ok": True, **report}


@app.post("/api/admin/payments/notifications/process-v2")
async def admin_process_payment_notifications_v2(
    req: AdminPaymentMaintenanceV2Request,
    request: Request,
) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    with db() as conn:
        messages = claim_payment_notifications(conn, limit=req.limit)
    report: dict[str, Any] = {"checked": len(messages), "sent": 0, "retried": 0, "errors": []}
    for message in messages:
        try:
            if message.channel == "in_app":
                pass
            elif message.channel == "email":
                if not message.destination or not email_provider_configured():
                    raise RuntimeError("Почтовый провайдер не подключен для уведомлений об оплате.")
                payload = message.payload
                await asyncio.to_thread(
                    send_transactional_email,
                    message.destination,
                    "Оплата в ИЗО АСА подтверждена",
                    (
                        "<p>Оплата подтверждена.</p>"
                        f"<p>Счет: {html_escape(str(payload.get('invoice_code') or ''))}<br>"
                        f"Начислено токенов: {int(payload.get('tokens') or 0)}<br>"
                        f"Баланс токенов: {int(payload.get('new_token_balance') or 0)}</p>"
                    ),
                )
            else:
                raise RuntimeError(f"Unsupported notification channel: {message.channel}")
            with db() as conn:
                mark_payment_notification_sent(conn, message.id)
            report["sent"] += 1
        except (SmtpError, RuntimeError, ValueError) as exc:
            with db() as conn:
                mark_payment_notification_retry(conn, message.id, str(exc))
            report["retried"] += 1
            report["errors"].append({"message_id": message.id, "error": truncate_admin_text(str(exc), 200)})
    with db() as conn:
        record_audit_log(
            conn,
            "admin_process_payment_notifications",
            actor_internal_user_id=admin["internal_user_id"],
            entity_id="payment_notification_outbox",
            after={**report, "reason": req.reason.strip()},
            request=request,
        )
    return {"ok": True, **report}


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
        if str(pay["provider"] or "").lower() == "yookassa":
            raise HTTPException(
                409,
                "Автоматический возврат в ЮKassa пока не подключен. "
                "Выполните возврат в кабинете ЮKassa и не отмечайте его завершенным только в CRM.",
            )
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
        "SELECT provider, provider_username, provider_email, provider_phone, provider_first_name, provider_last_name, last_login_at "
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
    video_state = video_storage_state_for_user(conn, urow, legacy)
    identity_email = next((str(i["provider_email"]).strip() for i in identities if i["provider_email"]), None)
    identity_username = next((str(i["provider_username"]).strip() for i in identities if i["provider_username"]), None)
    identity_phone = next((str(i["provider_phone"]).strip() for i in identities if i["provider_phone"]), None)
    is_demo = legacy == "demo_user" or str(_row_get(urow, "username") or "").lower() == "demo"
    account_group = "demo" if is_demo else ("admin" if _row_get(urow, "role") == "admin" else "customer")
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
        # This endpoint is trusted-admin-only. Full contacts are necessary for support
        # searches; password/session secrets and raw provider profiles remain excluded.
        "email": _row_get(urow, "email") or identity_email,
        "username": _row_get(urow, "username") or identity_username,
        "phone": _row_get(urow, "phone") or identity_phone,
        "account_group": account_group,
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
        "monthly_tokens": gallery_quota.get("monthly_tokens", 0),
        "plan_started_at": _row_get(urow, "plan_started_at"),
        "plan_expires_at": _row_get(urow, "plan_expires_at"),
        "plan_next_token_grant_at": _row_get(urow, "plan_next_token_grant_at"),
        "plan_term_months": int(_row_get(urow, "plan_term_months") or 1),
        "pending_plan": safe_json_load(_row_get(urow, "pending_plan_json")) or None,
        "gallery_slots": gallery_quota["gallery_slots"],
        "gallery_used": gallery_quota["gallery_used"],
        "gallery_free": gallery_quota["gallery_free"],
        "gallery_full": gallery_quota["gallery_full"],
        "video_enabled": gallery_quota["video_enabled"],
        "video_slots": gallery_quota["video_slots"],
        "video_used": video_state.active,
        "video_free": video_state.free,
        "status": "banned" if _row_get(urow, "banned") else "active",
        "role": _row_get(urow, "role"),
    }


def _cancel_provider_payment(provider: str, provider_payment_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        payment = conn.execute(
            "SELECT id, invoice_id, status FROM payments WHERE provider=? AND provider_payment_id=?",
            (provider, provider_payment_id),
        ).fetchone()
        if payment is None or payment["status"] != "pending":
            return
        conn.execute("UPDATE payments SET status='canceled', updated_at=? WHERE id=?", (now, payment["id"]))
        conn.execute(
            "UPDATE invoices SET status='cancelled', cancelled_at=?, updated_at=? WHERE id=? AND status!='paid'",
            (now, now, payment["invoice_id"]),
        )


def _verified_payment_email(conn: sqlite3.Connection, internal_user_id: str) -> str | None:
    user = conn.execute(
        "SELECT email, email_verified_at FROM users WHERE internal_user_id=?",
        (internal_user_id,),
    ).fetchone()
    if user is not None and user["email"] and user["email_verified_at"]:
        return str(user["email"]).strip().lower()
    identity = conn.execute(
        """
        SELECT provider_email FROM auth_identities
        WHERE internal_user_id=? AND provider_email IS NOT NULL AND verified_at IS NOT NULL
        ORDER BY last_login_at DESC, linked_at DESC LIMIT 1
        """,
        (internal_user_id,),
    ).fetchone()
    return str(identity["provider_email"]).strip().lower() if identity else None


def _enqueue_payment_success_notifications(
    conn: sqlite3.Connection,
    *,
    payment: sqlite3.Row,
    invoice: sqlite3.Row,
    new_token_balance: int,
    created_at: str,
) -> None:
    payload = {
        "payment_id": payment["id"],
        "invoice_code": invoice["invoice_code"],
        "amount": int(payment["amount"] or 0),
        "currency": payment["currency"],
        "tokens": int(invoice["tokens_total"] or 0),
        "new_token_balance": new_token_balance,
    }
    common = {
        "payment_id": payment["id"],
        "internal_user_id": payment["internal_user_id"],
        "event_type": "payment_succeeded",
        "payload": payload,
        "now": created_at,
    }
    enqueue_payment_notification(conn, channel="in_app", destination=None, **common)
    email = _verified_payment_email(conn, payment["internal_user_id"])
    if email:
        enqueue_payment_notification(conn, channel="email", destination=email, **common)


def _complete_provider_payment(
    provider: str,
    provider_payment_id: str,
    *,
    verified_amount: str,
    verified_currency: str,
) -> dict[str, Any]:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        payment = conn.execute(
            "SELECT * FROM payments WHERE provider = ? AND provider_payment_id = ?",
            (provider, provider_payment_id),
        ).fetchone()
        if payment is None:
            raise HTTPException(404, "Payment not found.")
        invoice = conn.execute("SELECT * FROM invoices WHERE id = ?", (payment["invoice_id"],)).fetchone()
        if invoice is None:
            raise HTTPException(409, "Payment invoice not found.")
        expected_amount = f"{int(payment['amount'] or 0):.2f}"
        if verified_amount != expected_amount or verified_currency != payment["currency"]:
            raise HTTPException(409, "YooKassa payment amount does not match the invoice.")
        if payment["status"] == "paid":
            user = conn.execute("SELECT token_balance FROM users WHERE internal_user_id = ?", (payment["internal_user_id"],)).fetchone()
            return {"payment": _billing_payment_dict(payment), "invoice": _billing_invoice_dict(invoice), "new_token_balance": int(_row_get(user, "token_balance") or 0), "idempotent": True}
        target = _admin_load_target(conn, payment["internal_user_id"])
        tokens_total = int(invoice["tokens_total"] or 0)
        old_balance = int(target["token_balance"] or 0)
        new_balance = old_balance + tokens_total
        ledger_id = None
        if tokens_total > 0:
            ledger_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, 'payment_grant', ?, ?)",
                (ledger_id, payment["user_id"], tokens_total, json.dumps({"invoice_id": invoice["id"], "payment_id": payment["id"], "provider_payment_id": provider_payment_id}, ensure_ascii=False), now),
            )
            conn.execute("UPDATE users SET token_balance = ? WHERE internal_user_id = ?", (new_balance, payment["internal_user_id"]))
        item = conn.execute("SELECT package_code FROM invoice_items WHERE invoice_id = ? ORDER BY created_at LIMIT 1", (invoice["id"],)).fetchone()
        package_code = str(_row_get(item, "package_code") or "")
        parsed_tariff = parse_tariff_package_code(package_code)
        lifecycle = None
        if parsed_tariff:
            plan, term_months = parsed_tariff
            if plan not in PLAN_ORDER or plan == "free":
                raise HTTPException(409, "Invalid tariff package.")
            lifecycle = _schedule_or_activate_paid_tariff(
                conn,
                internal_user_id=payment["internal_user_id"],
                plan=plan,
                term_months=term_months,
                source="payment",
                source_id=payment["id"],
                now=now_dt,
            )
            current_user = conn.execute(
                "SELECT token_balance FROM users WHERE internal_user_id=?",
                (payment["internal_user_id"],),
            ).fetchone()
            new_balance = int(_row_get(current_user, "token_balance") or 0)
        conn.execute("UPDATE payments SET status='paid', paid_at=?, token_ledger_id=?, updated_at=? WHERE id=?", (now, ledger_id, now, payment["id"]))
        conn.execute("UPDATE invoices SET status='paid', paid_at=?, updated_at=? WHERE id=?", (now, now, invoice["id"]))
        payment = conn.execute("SELECT * FROM payments WHERE id = ?", (payment["id"],)).fetchone()
        invoice = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice["id"],)).fetchone()
        _enqueue_payment_success_notifications(
            conn,
            payment=payment,
            invoice=invoice,
            new_token_balance=new_balance,
            created_at=now,
        )
    return {
        "payment": _billing_payment_dict(payment),
        "invoice": _billing_invoice_dict(invoice),
        "new_token_balance": new_balance,
        "tariff_lifecycle": lifecycle,
        "idempotent": False,
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
        if item.get("status") in ("queued", "running", "uploading", "sent_to_comfyui", "sent_to_openrouter")
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
    "activity_asc": "COALESCE(u.last_seen_at, u.last_login_at, u.created_at) ASC, u.created_at ASC",
    "created_desc": "u.created_at DESC",
    "created_asc": "u.created_at ASC",
    "generations_desc": "COALESCE(u.generation_count, 0) DESC, COALESCE(u.last_seen_at, u.created_at) DESC",
    "generations_asc": "COALESCE(u.generation_count, 0) ASC, COALESCE(u.last_seen_at, u.created_at) DESC",
    "tokens_desc": "COALESCE(u.tokens_used, 0) DESC, COALESCE(u.last_seen_at, u.created_at) DESC",
    "tokens_asc": "COALESCE(u.tokens_used, 0) ASC, COALESCE(u.last_seen_at, u.created_at) DESC",
    "balance_desc": "COALESCE(u.token_balance, 0) DESC, COALESCE(u.last_seen_at, u.created_at) DESC",
    "balance_asc": "COALESCE(u.token_balance, 0) ASC, COALESCE(u.last_seen_at, u.created_at) DESC",
    "code_asc": "u.public_user_code ASC, u.created_at ASC",
    "name_asc": "LOWER(COALESCE(NULLIF(u.display_name,''), NULLIF(u.username,''), NULLIF(u.email,''), u.public_user_code, u.id)) ASC",
    "name_desc": "LOWER(COALESCE(NULLIF(u.display_name,''), NULLIF(u.username,''), NULLIF(u.email,''), u.public_user_code, u.id)) DESC",
    "plan_asc": "u.plan ASC, COALESCE(u.last_seen_at, u.created_at) DESC",
    "plan_desc": "u.plan DESC, COALESCE(u.last_seen_at, u.created_at) DESC",
    "source_asc": "COALESCE((SELECT MIN(ai.provider) FROM auth_identities ai WHERE ai.internal_user_id=u.internal_user_id),'') ASC, COALESCE(u.last_seen_at,u.created_at) DESC",
    "source_desc": "COALESCE((SELECT MIN(ai.provider) FROM auth_identities ai WHERE ai.internal_user_id=u.internal_user_id),'') DESC, COALESCE(u.last_seen_at,u.created_at) DESC",
    "contact_asc": "LOWER(COALESCE(NULLIF(u.email,''), NULLIF(u.username,''), NULLIF(u.phone,''), (SELECT MIN(COALESCE(NULLIF(ai.provider_email,''),NULLIF(ai.provider_username,''),NULLIF(ai.provider_phone,''))) FROM auth_identities ai WHERE ai.internal_user_id=u.internal_user_id),'')) ASC",
    "contact_desc": "LOWER(COALESCE(NULLIF(u.email,''), NULLIF(u.username,''), NULLIF(u.phone,''), (SELECT MIN(COALESCE(NULLIF(ai.provider_email,''),NULLIF(ai.provider_username,''),NULLIF(ai.provider_phone,''))) FROM auth_identities ai WHERE ai.internal_user_id=u.internal_user_id),'')) DESC",
}


@app.get("/api/admin/users-analytics-v2")
async def admin_users_analytics_v2(request: Request, q: str | None = None, provider: str | None = None,
                                   status: str | None = None, group: str | None = None, sort: str = "recent",
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
    if group == "admin":
        clauses.append("u.role = 'admin' AND u.id != 'demo_user'")
    elif group == "demo":
        clauses.append("(u.id = 'demo_user' OR LOWER(COALESCE(u.username,'')) = 'demo')")
    elif group == "customer":
        clauses.append("u.role != 'admin' AND u.id != 'demo_user' AND LOWER(COALESCE(u.username,'')) != 'demo'")
    if provider:
        clauses.append("EXISTS (SELECT 1 FROM auth_identities ai WHERE ai.internal_user_id = u.internal_user_id AND ai.provider = ?)")
        params.append(provider)
    if q:
        like = f"%{q}%"
        clauses.append(
            "(u.public_user_code LIKE ? OR u.display_name LIKE ? OR u.username LIKE ? OR u.email LIKE ? "
            "OR u.phone LIKE ? OR u.id LIKE ? OR EXISTS (SELECT 1 FROM auth_identities ai2 "
            "WHERE ai2.internal_user_id=u.internal_user_id AND (ai2.provider_user_id LIKE ? OR ai2.provider_username LIKE ? "
            "OR ai2.provider_email LIKE ? OR ai2.provider_phone LIKE ?)))"
        )
        params += [like] * 10
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
        raw_meta = safe_json_load(r["meta_json"]) or {}
        meta = raw_meta if isinstance(raw_meta, dict) else {}
        job_id = meta.get("jobId") or meta.get("job_id")
        if job_id and int(r["delta"]) < 0:
            spent_by_job[str(job_id)] = abs(int(r["delta"]))
        elif job_id and r["reason"] in {"daily_generation", "openrouter_monthly_generation"}:
            spent_by_job[str(job_id)] = int(meta.get("token_cost") or 0)
    return {
        "ok": True,
        "summary": summary,
        **billing,
        **loyalty,
        "identities": [{
            "provider": r["provider"], "provider_user_id": r["provider_user_id"],
            "provider_username": r["provider_username"], "provider_email": r["provider_email"],
            "first_name": r["provider_first_name"], "last_name": r["provider_last_name"],
            "phone": r["provider_phone"],
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
            "job_id": short_public_id(safe_ledger_metadata(r["meta_json"]).get("jobId") or safe_ledger_metadata(r["meta_json"]).get("job_id")),
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
    smtp_provider_config = smtp_config()
    smtp_is_configured = smtp_configured(smtp_provider_config)
    smtp_is_verified = smtp_ready(smtp_provider_config)
    unisender_provider_config = unisender_config()
    unisender_is_configured = unisender_configured(unisender_provider_config)
    unisender_is_verified = unisender_ready(unisender_provider_config)
    configured = unisender_is_configured or smtp_is_configured
    verified = unisender_is_verified or smtp_is_verified
    provider = (
        "unisender" if unisender_is_verified or unisender_is_configured
        else "smtp" if smtp_is_verified or smtp_is_configured
        else EMAIL_PROVIDER.strip()
    )
    production = APP_ENV.lower() == "production"
    delivery_implemented = provider in {"unisender", "smtp"} or not (production and bool(provider))
    service_ready = email_otp_available()
    return {
        "ok": True,
        "generated_at": now.isoformat(),
        "service_ready": service_ready,
        "status": "ready" if service_ready else ("provider_not_verified" if configured and not verified else ("provider_adapter_missing" if provider else "provider_not_configured")),
        "provider": provider or None,
        "environment": APP_ENV,
        "otp_available": email_otp_available(),
        "delivery_implemented": delivery_implemented,
        "debug_return_code": EMAIL_OTP_DEBUG_RETURN_CODE and not production,
        "providers": {
            "unisender": {
                "api_key": bool(unisender_api_key()),
                "configured": unisender_is_configured,
                "verified": unisender_is_verified,
                "verified_at": unisender_provider_config.get("verified_at"),
                "last_error": unisender_provider_config.get("last_error"),
                "sender_name": unisender_provider_config.get("sender_name") or "ИЗО АСА",
                "sender_email": unisender_provider_config.get("sender_email") or "",
                "list_id": int(unisender_provider_config.get("list_id") or 0),
            },
            "smtp": {
                "password": bool(smtp_password()),
                "configured": smtp_is_configured,
                "verified": smtp_is_verified,
                "verified_at": smtp_provider_config.get("verified_at"),
                "last_error": smtp_provider_config.get("last_error"),
                "host": smtp_provider_config.get("host") or "smtp.mail.ru",
                "port": int(smtp_provider_config.get("port") or 465),
                "username": smtp_provider_config.get("username") or "",
                "sender_name": smtp_provider_config.get("sender_name") or "",
                "sender_email": smtp_provider_config.get("sender_email") or "",
                "use_ssl": bool(smtp_provider_config.get("use_ssl", True)),
            },
        },
        "config": {
            "password": bool(smtp_password()),
            "configured": smtp_is_configured,
            "verified": smtp_is_verified,
            "verified_at": smtp_provider_config.get("verified_at"),
            "last_error": smtp_provider_config.get("last_error"),
            "host": smtp_provider_config.get("host") or "smtp.mail.ru",
            "port": int(smtp_provider_config.get("port") or 465),
            "username": smtp_provider_config.get("username") or "",
            "sender_name": smtp_provider_config.get("sender_name") or "",
            "sender_email": smtp_provider_config.get("sender_email") or "",
            "use_ssl": bool(smtp_provider_config.get("use_ssl", True)),
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


def max_webhook_url() -> str:
    if MAX_WEBHOOK_URL.strip():
        return MAX_WEBHOOK_URL.strip()
    backend_public = os.getenv("BACKEND_PUBLIC_URL", "")
    if backend_public.startswith("https://"):
        return f"{backend_public.rstrip('/')}/api/max/webhook"
    return ""


async def configure_max_webhook_subscription() -> dict[str, Any]:
    diag = BOT_RUNTIME.max_polling_diag
    validate_max_webhook_secret("webhook", MAX_WEBHOOK_SECRET)
    wh_url = max_webhook_url()
    if not wh_url.startswith("https://"):
        diag.update({
            "webhookConfigured": False,
            "webhookUrlSet": False,
            "subscriptionStatus": "missing_https_url",
            "updateTypes": ["bot_started", "message_callback", "message_created"],
        })
        raise HTTPException(400, "MAX_WEBHOOK_URL or BACKEND_PUBLIC_URL must be an HTTPS URL.")
    body = build_max_subscription_payload(
        wh_url,
        MAX_WEBHOOK_SECRET,
        ["bot_started", "message_callback", "message_created"],
    )
    try:
        result = await max_api("POST", "/subscriptions", body)
        diag.update({
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
        diag.update({
            "webhookConfigured": False,
            "webhookUrlSet": True,
            "subscriptionStatus": f"error:{status or type(exc).__name__}",
            "updateTypes": body["update_types"],
        })
        print(f"MAX webhook subscription status=error apiStatus={status or 'unknown'} error={type(exc).__name__}")
        raise


BOT_PUBLIC_DEPENDENCIES = BotPublicDependencies(
    transport=BotPublicTransport(
        # Transports stay canonical in main (workers, gallery delivery, avatar
        # caching also use them); late-bound so test fakes on main are observed.
        telegram_api=lambda *args, **kwargs: telegram_api(*args, **kwargs),
        max_api=lambda *args, **kwargs: max_api(*args, **kwargs),
    ),
    messaging=BotPublicMessaging(
        telegram_poll_once=lambda **kwargs: telegram_poll_once_from_api(**kwargs),
        max_poll_once=lambda **kwargs: max_poll_once_from_api(**kwargs),
        handle_telegram_update=lambda *args, **kwargs: handle_telegram_update(*args, **kwargs),
        handle_max_update=lambda *args, **kwargs: handle_max_update(*args, **kwargs),
        bot_command_response=lambda platform, text: bot_command_response(platform, text),
        pending_max_login_count=lambda: pending_max_login_challenges_count(),
        configure_max_webhook=lambda: configure_max_webhook_subscription(),
    ),
    config=BotPublicConfig(
        require_trusted_admin=lambda request: require_trusted_admin(request),
        telegram_webhook_secret=lambda: TELEGRAM_WEBHOOK_SECRET,
        max_webhook_secret=lambda: MAX_WEBHOOK_SECRET,
        bot_updates_mode=lambda: BOT_UPDATES_MODE,
        max_updates_mode=lambda: MAX_UPDATES_MODE,
    ),
)
app.include_router(create_bots_public_router(BOT_RUNTIME, BOT_PUBLIC_DEPENDENCIES))


def migrate_video_storage_tariffs(conn: sqlite3.Connection, *, now: str) -> bool:
    """Install the agreed storage limits once without overriding later admin edits."""
    marker = conn.execute(
        "SELECT 1 FROM admin_settings WHERE key = ?",
        (VIDEO_STORAGE_TARIFF_MIGRATION_KEY,),
    ).fetchone()
    if marker is not None:
        return False
    row = conn.execute("SELECT value_json FROM admin_settings WHERE key = 'tariffs'").fetchone()
    if row is not None:
        stored = safe_json_load(row["value_json"])
        tariffs = normalize_tariffs(stored if isinstance(stored, dict) else {})
        for plan, limit in VIDEO_STORAGE_TARIFF_LIMITS.items():
            tariffs[plan]["video_slots"] = limit
            tariffs[plan]["video_enabled"] = 1 if limit > 0 else 0
        conn.execute(
            "UPDATE admin_settings SET value_json = ?, updated_at = ? WHERE key = 'tariffs'",
            (json.dumps(tariffs, ensure_ascii=False), now),
        )
    conn.execute(
        "INSERT INTO admin_settings (key, value_json, updated_at) VALUES (?, ?, ?)",
        (
            VIDEO_STORAGE_TARIFF_MIGRATION_KEY,
            json.dumps({"limits": VIDEO_STORAGE_TARIFF_LIMITS}, ensure_ascii=False),
            now,
        ),
    )
    return True


async def _admin_bot_public_https_status(config: dict[str, Any]) -> dict[str, Any]:
    backend_url = str(config["public"]["backendUrl"]).rstrip("/")
    if not backend_url.startswith("https://"):
        return {"ok": False, "url": backend_url, "error": "Публичный HTTPS не настроен."}
    try:
        async with httpx.AsyncClient(timeout=3, follow_redirects=True) as client:
            response = await client.get(f"{backend_url}/api/health")
        return {
            "ok": response.status_code < 500,
            "url": backend_url,
            "statusCode": response.status_code,
            "source": "admin_settings",
        }
    except Exception as exc:
        return {
            "ok": False,
            "url": backend_url,
            "error": safe_bot_error(exc),
            "source": "admin_settings",
        }


async def _admin_telegram_probe() -> dict[str, Any]:
    token = telegram_admin_token()
    health = await probe_telegram_bot(token=token)
    result = health.as_dict()
    if health.ok:
        try:
            payload = await request_telegram_bot_api(token=token, method="getMe")
            profile = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            result["name"] = str(profile.get("first_name") or "")[:120] or None
        except Exception:
            pass
        try:
            webhook_payload = await request_telegram_bot_api(token=token, method="getWebhookInfo")
            webhook = webhook_payload.get("result") if isinstance(webhook_payload.get("result"), dict) else {}
            result["webhook"] = {
                "configured": bool(webhook.get("url")),
                "url": str(webhook.get("url") or "")[:500] or None,
                "pendingUpdateCount": int(webhook.get("pending_update_count") or 0),
                "lastErrorDate": webhook.get("last_error_date"),
            }
        except Exception:
            result["webhook"] = {"configured": None, "error": "Статус webhook временно недоступен."}
    return result


async def _admin_max_probe(config: dict[str, Any]) -> dict[str, Any]:
    token = max_admin_token()
    base_url = str(config["max"]["apiBaseUrl"])
    health = await probe_max_bot(
        token=token,
        base_url=base_url,
        verify=MAX_HTTP_VERIFY,
    )
    result = health.as_dict()
    if health.ok:
        try:
            profile = await request_max_api(
                token=token,
                base_url=base_url,
                verify=MAX_HTTP_VERIFY,
                method="GET",
                path="/me",
                timeout_seconds=5,
            )
            result.update(
                {
                    "bot_id": profile.get("id"),
                    "name": str(profile.get("name") or profile.get("first_name") or "")[:120] or None,
                    "nickname": str(profile.get("nickname") or profile.get("username") or "")[:120] or None,
                }
            )
        except Exception:
            pass
        try:
            subscriptions = await request_max_api(
                token=token,
                base_url=base_url,
                verify=MAX_HTTP_VERIFY,
                method="GET",
                path="/subscriptions",
                timeout_seconds=5,
            )
            raw_items = subscriptions.get("subscriptions")
            if not isinstance(raw_items, list):
                raw_items = subscriptions.get("items")
            result["subscriptions"] = [
                {
                    "url": str(item.get("url") or "")[:500],
                    "updateTypes": item.get("update_types") if isinstance(item.get("update_types"), list) else [],
                }
                for item in (raw_items if isinstance(raw_items, list) else [])
                if isinstance(item, dict)
            ]
        except Exception:
            result["subscriptions"] = None
    return result


BOT_ADMIN_DEPENDENCIES = BotAdminDependencies(
    config=BotAdminConfigOps(
        get_config=bot_integrations_config,
        save_config=save_bot_integrations_config,
        has_saved_config=has_saved_bot_integrations_config,
        configured_webhook_url=configured_bot_webhook_url,
        apply_runtime_config=apply_saved_bot_runtime_configuration,
        normalize_config=normalize_bot_integrations,
        is_production=is_production_like_env,
        default_integrations=DEFAULT_BOT_INTEGRATIONS,
    ),
    secret=BotAdminSecretOps(
        telegram_token=telegram_admin_token,
        max_token=max_admin_token,
        telegram_webhook_secret=telegram_admin_webhook_secret,
        max_webhook_secret=max_admin_webhook_secret,
        secret_source=_bot_secret_source,
        secret_updated_at=_bot_secret_updated_at,
        save_secret=_save_bot_secret,
        # Late-bound to the module global so tests that replace
        # OPENROUTER_SECRET_STORE observe the swap; the sensitive store object
        # itself is never held inside the dependency dataclass.
        secret_exists=lambda name: OPENROUTER_SECRET_STORE.exists(name),
        secret_delete=lambda name: OPENROUTER_SECRET_STORE.delete(name),
        secret_error=SecretStoreError,
        telegram_token_name=TELEGRAM_BOT_SECRET_NAME,
        max_token_name=MAX_BOT_SECRET_NAME,
        telegram_webhook_name=TELEGRAM_WEBHOOK_SECRET_NAME,
        max_webhook_name=MAX_WEBHOOK_SECRET_NAME,
    ),
    provider=BotAdminProviderOps(
        # probe_* is late-bound so provider fakes injected on main are observed.
        probe_telegram=lambda **kwargs: probe_telegram_bot(**kwargs),
        probe_max=lambda **kwargs: probe_max_bot(**kwargs),
        telegram_api=request_telegram_bot_api,
        max_api=request_max_api,
        build_max_subscription=build_max_subscription_payload,
        validate_telegram_webhook_secret=validate_telegram_webhook_secret,
        validate_max_webhook_secret=validate_max_webhook_secret,
        safe_bot_error=safe_bot_error,
        max_http_verify=MAX_HTTP_VERIFY,
        # Status probes stay canonical in main and are injected late-bound so
        # admin-status tests can override the whole provider round-trip.
        telegram_status_probe=lambda: _admin_telegram_probe(),
        max_status_probe=lambda config: _admin_max_probe(config),
        public_https_status=lambda config: _admin_bot_public_https_status(config),
    ),
    infra=BotAdminInfrastructure(
        require_trusted_admin=require_trusted_admin,
        connect=db,
        audit=record_audit_log,
        json_load=safe_json_load,
    ),
)
app.include_router(create_bots_admin_router(BOT_RUNTIME, BOT_ADMIN_DEPENDENCIES))


@app.get("/api/admin/max/status")
async def admin_max_status(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    diag = BOT_RUNTIME.max_polling_diag
    return {
        "ok": True,
        "tokenSet": bool(MAX_BOT_TOKEN),
        "botNicknameResolved": bool(resolve_max_bot_deep_link_base()),
        "deepLinkBaseSource": BOT_RUNTIME.max_deep_link_cache.get("source"),
        "apiBaseUrl": MAX_API_BASE_URL,
        "tlsTrustStore": MAX_TLS_TRUST_STORE,
        "mode": MAX_UPDATES_MODE,
        "pollingReady": bool(MAX_BOT_TOKEN and MAX_API_BASE_URL),
        "webhookSecretConfigured": bool(MAX_WEBHOOK_SECRET),
        "webhookConfigured": bool(diag.get("webhookConfigured")),
        "webhookUrlSet": bool(diag.get("webhookUrlSet")),
        "subscriptionStatus": diag.get("subscriptionStatus"),
        "updateTypes": diag.get("updateTypes"),
        "lastPollAt": diag.get("lastPollAt"),
        "lastPollStatus": diag.get("lastPollStatus"),
        "lastPollError": diag.get("lastPollError"),
        "lastRawCount": diag.get("lastRawCount"),
        "lastBotStartedAt": diag.get("lastBotStartedAt"),
        "lastCallbackAt": diag.get("lastCallbackAt"),
        "lastWebhookAt": diag.get("lastWebhookAt"),
        "pendingLoginChallengesCount": pending_max_login_challenges_count(),
    }


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
        "queue": [{k: v for k, v in item.items() if k != "request"} for item in jobs.values() if item.get("status") in ("queued", "running", "uploading", "sent_to_comfyui", "sent_to_openrouter")],
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
        settings["tariffs"] = tariff_config_with_model_counts(conn)
        settings["tariff_terms"] = get_tariff_term_settings(conn)
        settings["tariff_offers"] = tariff_term_offers(conn)
    return settings


@app.post("/api/admin/settings/{key}")
async def admin_save_settings(key: str, req: AdminSettingsRequest, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    if key == "tariffs":
        settings = normalize_tariffs(req.settings, strict=True)
    elif key == "tariff_terms":
        settings = normalize_term_settings(req.settings)
    elif key == "config_ui_resolution_access":
        raw_plans = req.settings.get("plans") if isinstance(req.settings.get("plans"), dict) else {}
        settings = {"plans": {plan: normalize_resolution_ids(raw_plans.get(plan), DEFAULT_TARIFFS[plan]["allowed_resolutions"]) for plan in PLAN_ORDER}}
    elif key == "server_model_profiles":
        settings = normalize_server_model_profiles(req.settings)
    elif key == "openrouter_video_models":
        try:
            video_catalog = await fetch_openrouter_video_catalog()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Каталог видеомоделей временно недоступен: {truncate_admin_text(str(exc), 180)}") from exc
        settings = normalize_openrouter_video_config(req.settings, video_catalog)
    elif key == "config_ui_runtime":
        with db() as conn: active_video = conn.execute("SELECT 1 FROM jobs WHERE provider='local_ltx' AND status IN ('submitting','queued','pending','in_progress','finalizing') LIMIT 1").fetchone()
        try:
            settings = ltx_video.normalize_runtime_settings(req.settings, _saved_setting("config_ui_runtime"), has_active_job=active_video is not None)
        except ltx_video.LocalLtxRequestError as exc: raise HTTPException(exc.status_code, str(exc)) from exc
    elif key == "legal":
        settings = normalize_legal_settings(req.settings)
    else:
        settings = req.settings
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
        if key in {"tariffs", "tariff_terms"}:
            _sync_tariff_billing_packages(conn)
    if key in {"generation_routes", "server_model_loras", "server_model_profiles", "models", "tariff_matrix", "user_choice", "tariffs", "tariff_terms", "config_ui_resolution_access", "openrouter_economy", "openrouter_video_models"}:
        _admin_models_page_cache["ts"] = 0.0
        _admin_models_page_cache["data"] = None
    return {"ok": True, "key": key, "settings": settings}


@app.get("/api/admin/assistants")
async def admin_assistants(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    config = assistant_models_config()
    try:
        text_models = await openrouter_text_models()
        text_models_error = None
    except Exception as exc:
        text_models = []
        text_models_error = type(exc).__name__
    try:
        audio_models = await openrouter_audio_models()
        audio_models_error = None
    except Exception as exc:
        audio_models = []
        audio_models_error = type(exc).__name__
    return {
        "ok": True,
        "config": config,
        "ollama": await ollama_models_status(),
        "qwen": await qwen_asr_status(config["voice"]),
        "openrouterConfigured": bool(openrouter_api_key()),
        "openrouterModels": text_models,
        "openrouterModelsError": text_models_error,
        "openrouterAudioModels": audio_models,
        "openrouterAudioModelsError": audio_models_error,
    }


@app.put("/api/admin/mail/config-v2")
async def admin_mail_config_v2(req: AdminMailConfigV2Request, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    try:
        save_smtp_config(req)
    except (ValueError, SecretStoreError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "configured": smtp_configured(), "verified": smtp_ready(), "provider": "smtp"}


@app.post("/api/admin/mail/verify-v2")
async def admin_mail_verify_v2(req: AdminMailVerifyV2Request, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    candidate_password = (req.password or "").strip() or smtp_password()
    candidate_config = {
        "host": req.host.strip(),
        "port": req.port,
        "username": normalize_email(req.username),
        "sender_name": req.sender_name.strip(),
        "sender_email": normalize_email(req.sender_email),
        "use_ssl": bool(req.use_ssl),
    }
    if not candidate_password:
        raise HTTPException(400, "Введите пароль приложения для почтового ящика.")
    if not candidate_config["username"] or candidate_config["username"] != candidate_config["sender_email"]:
        raise HTTPException(400, "Почтовый ящик и email отправителя должны совпадать.")
    try:
        if req.save:
            # Persist first so a failed handshake never erases the form. The
            # provider remains disabled until the successful verification below.
            save_smtp_config(req, verified_at=None, last_error=None)
        await asyncio.to_thread(verify_smtp_connection, smtp_connection_config(candidate_config, candidate_password))
        if req.save:
            save_smtp_config(req, verified_at=datetime.now(timezone.utc).isoformat(), last_error=None)
    except SmtpError as exc:
        if req.save:
            try:
                save_smtp_config(req, verified_at=None, last_error=str(exc))
            except (ValueError, SecretStoreError):
                pass
        raise HTTPException(502, str(exc)) from exc
    except (ValueError, SecretStoreError) as exc:
        raise HTTPException(500, str(exc)) from exc
    return {"ok": True, "provider": "smtp", "configured": smtp_configured(), "verified": smtp_ready(), "message": "SMTP подключен и настройки сохранены."}


@app.post("/api/admin/mail/unisender/verify-v2")
async def admin_mail_unisender_verify_v2(
    req: AdminUniSenderVerifyV2Request,
    request: Request,
) -> dict[str, Any]:
    require_trusted_admin(request)
    sender_email = normalize_email(req.sender_email)
    if not sender_email:
        raise HTTPException(400, "Введите корректный email отправителя.")
    selected_list_id = int(req.list_id or 0)
    try:
        if req.api_key:
            save_unisender_api_key(req.api_key)
        api_key = unisender_api_key()
        if not api_key:
            raise ValueError("Введите API-ключ UniSender.")
        lists = await asyncio.to_thread(get_unisender_lists, api_key)
        available_ids = {int(item["id"]) for item in lists}
        if selected_list_id and selected_list_id not in available_ids:
            raise ValueError("Выбранный список контактов не найден в UniSender.")
        if not selected_list_id and lists:
            selected_list_id = int(lists[0]["id"])
        if not selected_list_id and req.create_list_if_missing:
            created = await asyncio.to_thread(create_unisender_list, api_key, "Пользователи ИЗО АСА")
            lists.append(created)
            selected_list_id = int(created["id"])
        if not selected_list_id:
            raise ValueError("В UniSender нет списка контактов. Разрешите создать список автоматически.")

        # A successful account probe is not enough: this real message also
        # confirms that UniSender accepts the selected sender address.
        message_id = await asyncio.to_thread(
            send_unisender_email,
            api_key,
            UniSenderMessage(
                to=sender_email,
                subject="Проверка почты ИЗО АСА",
                html=(
                    "<p>Почта ИЗО АСА подключена к UniSender.</p>"
                    "<p>Это автоматическое проверочное письмо из админки.</p>"
                ),
                sender_name=req.sender_name.strip() or "ИЗО АСА",
                sender_email=sender_email,
                list_id=selected_list_id,
                reference_key=f"izo-mail-check-{uuid.uuid4().hex}",
            ),
        )
        verified_at = datetime.now(timezone.utc).isoformat()
        save_unisender_config(
            sender_name=req.sender_name,
            sender_email=sender_email,
            list_id=selected_list_id,
            verified_at=verified_at,
            last_error=None,
        )
    except (UniSenderError, SecretStoreError, ValueError) as exc:
        try:
            save_unisender_config(
                sender_name=req.sender_name,
                sender_email=sender_email,
                list_id=selected_list_id,
                verified_at=None,
                last_error=str(exc),
            )
        except (ValueError, SecretStoreError):
            pass
        status_code = 502 if isinstance(exc, UniSenderError) else 400
        raise HTTPException(status_code, str(exc)) from exc
    return {
        "ok": True,
        "provider": "unisender",
        "configured": True,
        "verified": True,
        "verified_at": verified_at,
        "sender_email": sender_email,
        "list_id": selected_list_id,
        "lists": lists,
        "message_id": message_id,
        "message": "UniSender подключен. Проверочное письмо принято к отправке.",
    }


@app.post("/api/admin/mail/unisender/lists-v2")
async def admin_mail_unisender_create_list_v2(
    req: AdminUniSenderListV2Request,
    request: Request,
) -> dict[str, Any]:
    require_trusted_admin(request)
    api_key = unisender_api_key()
    if not api_key:
        raise HTTPException(400, "Сначала сохраните и проверьте API-ключ UniSender.")
    try:
        created = await asyncio.to_thread(create_unisender_list, api_key, req.title)
    except UniSenderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "provider": "unisender", "list": created}


@app.get("/api/admin/payments/status-v2")
async def admin_payments_status_v2(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    config = yookassa_config()
    with db() as conn:
        _sync_tariff_billing_packages(conn)
        summary = conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN status='paid' THEN 1 ELSE 0 END),0) AS paid, COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) AS pending, COALESCE(SUM(CASE WHEN status='paid' THEN amount ELSE 0 END),0) AS revenue FROM payments"
        ).fetchone()
        payments = conn.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT 50").fetchall()
        events = conn.execute("SELECT event_type, provider_payment_id, status, received_at, processed_at, error FROM payment_provider_events ORDER BY received_at DESC LIMIT 50").fetchall()
        packages = conn.execute("SELECT * FROM billing_packages WHERE code LIKE 'tokens_%' ORDER BY sort_order, price_amount").fetchall()
        tariffs_config = get_tariff_config(conn)
        tariff_products = [
            {
                **offer,
                "plan": plan,
                "title": tariffs_config[plan]["title"],
                "price_amount": int(offer["price_total_rub"]),
                "source": "tariffs",
            }
            for plan, offers in tariff_term_offers(conn).items()
            for offer in offers
        ]
        public_legal = legal_settings(conn)
    return {
        "ok": True,
        "provider": active_billing_provider() or "yookassa",
        "configured": yookassa_checkout_ready(config),
        "simulator_enabled": billing_simulator_enabled(),
        "config": {
            "shop_id": config.get("shop_id") or "",
            "secret_key": bool(yookassa_secret_key()),
            "test_mode": bool(config.get("test_mode", True)),
            "receipt_vat_code": config.get("receipt_vat_code"),
            "payment_subject": config.get("payment_subject") or "service",
        },
        "connection_check": {
            "ok": bool(config.get("last_check_ok")),
            "checked_at": config.get("last_checked_at"),
            "message": config.get("last_check_message") or "",
        },
        "webhook_url": f"{os.getenv('PUBLIC_SITE_URL', 'https://izo.alikinas.ru').rstrip('/')}/api/billing/yookassa/webhook-v2",
        "summary": {"total": int(summary["total"] or 0), "paid": int(summary["paid"] or 0), "pending": int(summary["pending"] or 0), "revenue_rub": int(summary["revenue"] or 0)},
        "packages": [_billing_package_dict(row) for row in packages],
        "tariff_products": tariff_products,
        "legal": public_legal,
        "legal_readiness": legal_readiness(public_legal),
        "payments": [_billing_payment_dict(row) for row in payments],
        "events": [dict(row) for row in events],
    }


@app.put("/api/admin/payments/config-v2")
async def admin_payments_config_v2(req: AdminYooKassaConfigV2Request, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    try:
        save_yookassa_config(req)
    except SecretStoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "configured": yookassa_checkout_ready(), "provider": "yookassa"}


@app.post("/api/admin/payments/check-v2")
async def admin_payments_check_v2(request: Request) -> dict[str, Any]:
    actor = require_trusted_admin(request)
    config = yookassa_config()
    shop_id = str(config.get("shop_id") or "").strip()
    secret_key = yookassa_secret_key()
    if not shop_id or not secret_key:
        raise HTTPException(400, "Сначала сохраните shopId и секретный ключ.")
    try:
        result = await check_yookassa_connection(shop_id=shop_id, secret_key=secret_key)
        message = "Подключение к ЮKassa работает. Реквизиты магазина приняты API."
        saved = save_yookassa_connection_check(ok=True, message=message)
        status_code = 200
    except YooKassaError as exc:
        message = str(exc)
        saved = save_yookassa_connection_check(ok=False, message=message)
        status_code = 502
        result = None
    with db() as conn:
        record_audit_log(
            conn,
            "admin_check_yookassa",
            actor_internal_user_id=actor.get("internal_user_id"),
            entity_type="billing_provider",
            entity_id="yookassa",
            after={"ok": bool(saved.get("last_check_ok")), "checked_at": saved.get("last_checked_at")},
            request=request,
        )
    payload = {
        "ok": bool(saved.get("last_check_ok")),
        "provider": "yookassa",
        "checked_at": saved.get("last_checked_at"),
        "message": message,
        "payments_visible": result.payments_visible if result else 0,
    }
    if status_code != 200:
        return JSONResponse(status_code=status_code, content=payload)
    return payload


@app.put("/api/admin/payments/packages/{code}-v2")
async def admin_payment_package_v2(code: str, req: AdminTokenPackageV2Request, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    if not re.fullmatch(r"tokens_[a-z0-9_]{1,60}", code):
        raise HTTPException(400, "Редактировать здесь можно только пакеты токенов.")
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute("SELECT * FROM billing_packages WHERE code = ?", (code,)).fetchone()
        if row is None:
            raise HTTPException(404, "Пакет не найден.")
        conn.execute(
            "UPDATE billing_packages SET name=?, price_amount=?, token_amount=?, is_active=?, updated_at=? WHERE code=?",
            (req.name.strip(), req.price_amount, req.token_amount, 1 if req.is_active else 0, now, code),
        )
        updated = conn.execute("SELECT * FROM billing_packages WHERE code = ?", (code,)).fetchone()
    return {"ok": True, "package": _billing_package_dict(updated)}


@app.post("/api/admin/assistants/test")
async def admin_test_assistant(req: AdminAssistantTestRequest, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    started = time.monotonic()
    improve_req = ImprovePromptRequest(prompt=req.prompt.strip(), mode=req.mode, language="ru")
    saved_config = assistant_models_config()["improve"]
    test_config = {**saved_config, **(req.config if isinstance(req.config, dict) else {})}
    test_config["modePrompts"] = {
        **saved_config["modePrompts"],
        **(test_config.get("modePrompts") if isinstance(test_config.get("modePrompts"), dict) else {}),
    }
    try:
        if req.provider == "local":
            improved, payload = await improve_prompt_ollama(improve_req, test_config)
            provider, model = "local", str(test_config.get("localModel") or "gemma4:31b-cloud")
        else:
            improved, payload = await improve_prompt_openrouter(improve_req, test_config)
            provider, model = "api", str(test_config.get("apiModel") or PROMPT_IMPROVE_MODEL)
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "ok": True,
        "provider": provider,
        "model": model,
        "improvedPrompt": improved,
        "latencyMs": round((time.monotonic() - started) * 1000),
        "costUsd": _openrouter_generation_cost(payload) if provider == "api" else 0,
    }


@app.post("/api/admin/assistants/voice-test")
async def admin_test_voice_assistant(
    request: Request,
    file: UploadFile = File(...),
    provider: str = "configured",
    language: str = "ru",
) -> dict[str, Any]:
    require_trusted_admin(request)
    if provider not in {"configured", "local", "qwen", "api", "auto"}:
        raise HTTPException(400, "Неизвестный голосовой провайдер.")
    audio = await file.read(8 * 1024 * 1024 + 1)
    if not audio:
        raise HTTPException(400, "Аудиофайл пуст.")
    if len(audio) > 8 * 1024 * 1024:
        raise HTTPException(413, "Аудиофайл слишком большой.")
    content_type = (file.content_type or "").lower()
    audio_format = {
        "audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a",
        "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
    }.get(content_type) or Path(file.filename or "").suffix.lower().lstrip(".")
    if audio_format not in {"webm", "ogg", "m4a", "mp3", "wav"}:
        raise HTTPException(415, "Формат аудиофайла не поддерживается.")
    started = time.monotonic()
    config = assistant_models_config()["voice"]
    try:
        text, payload, used_provider, model = await transcribe_audio_routed(
            audio,
            audio_format,
            "русском" if language == "ru" else "английском",
            config,
            None if provider == "configured" else provider,
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "ok": True,
        "text": text,
        "provider": used_provider,
        "model": model,
        "latencyMs": round((time.monotonic() - started) * 1000),
        "usage": payload.get("usage") if isinstance(payload, dict) and isinstance(payload.get("usage"), dict) else {},
    }


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
    models_cache_data = _admin_models_page_cache.get("data")
    models_cache_ts = _admin_models_page_cache.get("ts")
    if isinstance(models_cache_ts, dict):
        newest_cache_ts = max((float(value or 0) for value in models_cache_ts.values()), default=0.0)
    else:
        newest_cache_ts = float(models_cache_ts or 0)
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
        if item.get("status") in {"queued", "running", "uploading", "sent_to_comfyui", "sent_to_openrouter"}
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
        dwpose_ready = any("dwpreprocessor" in name.lower() or "dwpose" in name.lower() for name in nodes)
        nodes_status = {
            "ok": bool(nodes) or bool(models_status.get("ok")),
            "count": len(nodes),
            "required": {
                "Flux Klein API": bool(models_status.get("ok")),
                "DWPose (только для позы)": dwpose_ready,
            },
        }
    except Exception as exc:
        nodes_status = {"ok": False, "error": truncate_admin_text(str(exc), 180)}

    nodes_ready = bool(nodes_status.get("ok")) and bool(models_status.get("ok"))
    status = "ready" if comfy_up and config_status["ok"] and models_status["ok"] and nodes_ready else "degraded"
    runtime_settings = _saved_setting("config_ui_runtime")
    video_status = await ltx_video.admin_runtime_status(client=ltx_video.ComfyLtxClient(LOCAL_LTX_COMFYUI_BASE_URL, COMFYUI_TIMEOUT_SECONDS), enabled=runtime_settings.get("videoEnabled", LOCAL_LTX_ENABLED) is not False, base_url=LOCAL_LTX_COMFYUI_BASE_URL, open_db=db)
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
        "runtime": {"imageEnabled": runtime_settings.get("imageEnabled", True) is not False, "videoEnabled": runtime_settings.get("videoEnabled", LOCAL_LTX_ENABLED) is not False},
        **video_status,
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
    await interrupt_comfyui_prompt()
    freed = await free_comfyui_models()
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
            after={"reason": reason, "status": status.get("status"), "memory_freed": freed},
            request=request,
        )
    return {"ok": True, "reloaded": True, "memoryFreed": freed, "status": status}


@app.post("/api/admin/config-ui/switch-v2")
async def admin_config_ui_switch_v2(req: AdminConfigUiSwitchRequest, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    before = get_model_settings().get("editModelProfile") or "flux_klein_9b"
    await interrupt_comfyui_prompt()
    freed = await free_comfyui_models()
    _save_setting("models", {"editModelProfile": req.profileId, "poseModelProfile": req.profileId})
    current_routes = (_saved_setting("generation_routes") or {}).get("routes") or []
    if current_routes:
        _save_setting("generation_routes", {"routes": [{**route, "modelProfileId": req.profileId} if route.get("provider") == "local" else route for route in current_routes]})
    _admin_models_page_cache["ts"] = 0.0
    _admin_models_page_cache["data"] = None
    status = await compute_config_ui_status()
    with db() as conn:
        record_audit_log(conn, "admin_config_ui_switch", actor_internal_user_id=admin["internal_user_id"], entity_type="system", entity_id="config-ui", before={"profileId": before}, after={"profileId": req.profileId, "reason": req.reason, "memory_freed": freed}, request=request)
    return {"ok": True, "profileId": req.profileId, "memoryFreed": freed, "status": status}


@app.post("/api/admin/config-ui/interrupt-v2")
async def admin_config_ui_interrupt_v2(req: AdminConfigUiActionV2Request, request: Request) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = truncate_admin_text(req.reason, 300).strip()
    if not reason:
        raise HTTPException(400, "Укажите причину.")
    active_before = [
        item.get("id")
        for item in jobs.values()
        if item.get("status") in {"queued", "running", "uploading", "sent_to_comfyui", "sent_to_openrouter"}
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
    "flux2_klein_4b_outpaint_comfy": {"purpose": "outpaint / image extension", "compatible": ["Flux 2 Klein 4B"], "routes": ["outpaint"], "requires": [], "requiredModel": "klein-4b", "kind": "klein-outpaint", "recommended": True, "workflowReady": True},
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
    diffusion_models = models.get("diffusion_models", [])
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
            required_model = str(meta.get("requiredModel") or "")
            model_ok = not required_model or any(required_model in model.lower() for model in diffusion_models)
            workflow_ready = meta.get("workflowReady", True)
            status = "active" if requires_ok and model_ok and workflow_ready else "model_missing" if not model_ok else "workflow_pending" if requires_ok else "missing"
            out.append({
                "fileName": f, "purpose": meta["purpose"], "compatible": meta["compatible"],
                "routes": meta["routes"], "requires": meta["requires"], "status": status,
                "kind": meta.get("kind", "klein"), "recommended": bool(meta.get("recommended")),
                "installed": True, "forKlein": True, "workflowReady": workflow_ready, "requiredModel": required_model,
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
                "installed": False, "forKlein": True, "workflowReady": bool(meta.get("workflowReady", True)),
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


async def free_comfyui_models() -> bool:
    return await integration_free_comfyui_memory(base_url=COMFYUI_BASE_URL)


def reconcile_openrouter_token_charge(conn: sqlite3.Connection, job_id: str, actual_tokens: int) -> dict[str, int | bool]:
    """Idempotently refund an OpenRouter estimate that exceeded actual token cost."""
    existing = conn.execute(
        "SELECT meta_json FROM token_ledger WHERE reason = 'openrouter_generation_adjustment' AND meta_json LIKE ? ORDER BY created_at DESC LIMIT 1",
        (f'%"jobId": "{job_id}"%',),
    ).fetchone()
    if existing is not None:
        meta = safe_json_load(existing["meta_json"]) or {}
        actual = int(meta.get("actual_tokens") or actual_tokens)
        return {"adjusted": False, "refund": int(meta.get("refund_tokens") or 0), "actual": actual, "settled": int(meta.get("settled_tokens") or actual)}
    charge = conn.execute(
        "SELECT * FROM token_ledger WHERE reason IN ('generation', 'openrouter_monthly_generation') AND meta_json LIKE ? ORDER BY created_at DESC LIMIT 1",
        (f'%"jobId": "{job_id}"%',),
    ).fetchone()
    if charge is None:
        actual = max(1, int(actual_tokens))
        return {"adjusted": False, "refund": 0, "actual": actual, "settled": actual}
    meta = safe_json_load(charge["meta_json"]) or {}
    charged = max(0, int(meta.get("token_cost") or 0))
    actual = max(1, int(actual_tokens))
    refund = max(0, charged - actual)
    balance_charged = abs(int(charge["delta"] or 0))
    balance_refund = min(refund, balance_charged)
    monthly_refund = max(0, refund - balance_refund)
    user_id = str(charge["user_id"])
    if balance_refund:
        conn.execute("UPDATE users SET token_balance = token_balance + ? WHERE id = ?", (balance_refund, user_id))
    if monthly_refund:
        conn.execute(
            "UPDATE users SET openrouter_monthly_tokens_used = MAX(0, openrouter_monthly_tokens_used - ?) WHERE id = ?",
            (monthly_refund, user_id),
        )
    if refund:
        conn.execute("UPDATE users SET tokens_used = MAX(0, tokens_used - ?) WHERE id = ?", (refund, user_id))
    adjustment_meta = {
        "jobId": job_id,
        "charged_tokens": charged,
        "actual_tokens": actual,
        "settled_tokens": min(charged, actual),
        "refund_tokens": refund,
        "balance_refund": balance_refund,
        "monthly_refund": monthly_refund,
        "underestimated_tokens": max(0, actual - charged),
        "charged_ledger_id": charge["id"],
    }
    conn.execute(
        "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) VALUES (?, ?, ?, 'openrouter_generation_adjustment', ?, ?)",
        (str(uuid.uuid4()), user_id, balance_refund, json.dumps(adjustment_meta, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
    )
    return {"adjusted": True, "refund": refund, "actual": actual, "settled": min(charged, actual)}


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


def usd_rub_rate_snapshot() -> dict[str, Any]:
    cached = _saved_setting("exchange_usd_rub")
    if isinstance(cached.get("rate"), (int, float)):
        return {**cached, "cache": "snapshot"}
    return {
        "rate": None,
        "currency": "USD",
        "base": "RUB",
        "source": "none",
        "sourceUrl": CBR_DAILY_XML_URL,
        "cache": "empty",
    }


OPENROUTER_USD_FEE_RATE = 0.30
OPENROUTER_DEFAULT_TOKEN_RUB = 5.0
OPENROUTER_DEFAULT_MIN_MARGIN_PERCENT = 40.0
OPENROUTER_SHORT_PROMPT_TEXT_TOKENS = 40
OPENROUTER_OUTPUT_IMAGE_TOKENS_1MP = 1300
OPENROUTER_ADMIN_FORMATS: list[dict[str, Any]] = [
    {"id": "square", "label": "Квадрат", "short": "1:1", "width": 1024, "height": 1024},
    {"id": "portrait", "label": "Высокая", "short": "9:16", "width": 1024, "height": 1536},
    {"id": "wide", "label": "Широкая", "short": "16:9", "width": 1280, "height": 720},
    {"id": "soft_wide", "label": "Средняя", "short": "3:2", "width": 1536, "height": 1024},
]
OPENROUTER_RESOLUTION_FORMATS: list[dict[str, Any]] = [
    {
        "id": item["id"],
        "label": f"{item['tier'].upper()} {item['width']}×{item['height']}",
        "short": {"square": "1:1", "portrait": "9:16", "wide": "16:9", "photo": "3:2"}[item["format"]],
        "width": item["width"],
        "height": item["height"],
    }
    for item in IMAGE_RESOLUTIONS
]


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
    model_id = resolve_openrouter_model(req)
    plan = openrouter_image_request_plan(model_id, req.width, req.height)
    pixels = max(1, int(plan.get("billing_width") or req.width or 0)) * max(1, int(plan.get("billing_height") or req.height or 0))
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


def openrouter_format_economics(
    model: OpenRouterPriceModel,
    fmt: dict[str, Any],
    effective_rate: float | None,
    economy: dict[str, float],
) -> dict[str, Any]:
    width = int(fmt["width"])
    height = int(fmt["height"])
    plan = openrouter_image_request_plan(model.id, width, height)
    billing_width = int(plan.get("billing_width") or width)
    billing_height = int(plan.get("billing_height") or height)
    megapixels = max(1.0, (billing_width * billing_height) / 1_000_000)
    cost_usd = openrouter_estimated_usd(model, megapixels)
    cost_rub = cost_usd * effective_rate if effective_rate is not None else None
    tokens = openrouter_tokens_for_cost(cost_rub, model.min_tokens, economy) if cost_rub is not None else None
    revenue_rub = tokens * float(economy["tokenRub"]) if tokens is not None else None
    profit_rub = revenue_rub - cost_rub if revenue_rub is not None and cost_rub is not None else None
    margin_percent = (profit_rub / revenue_rub * 100) if revenue_rub and profit_rub is not None else None
    return {
        "id": fmt["id"],
        "label": fmt["label"],
        "short": fmt["short"],
        "inputWidth": width,
        "inputHeight": height,
        "requestSize": plan.get("size"),
        "requestSizeStrategy": plan.get("strategy"),
        "billingWidth": billing_width,
        "billingHeight": billing_height,
        "megapixels": round(megapixels, 6),
        "costUsd": round(cost_usd, 6),
        "costRub": round(cost_rub, 4) if cost_rub is not None else None,
        "tokens": tokens,
        "revenueRub": round(revenue_rub, 4) if revenue_rub is not None else None,
        "profitRub": round(profit_rub, 4) if profit_rub is not None else None,
        "marginPercent": round(margin_percent, 2) if margin_percent is not None else None,
        "supported": "vector" not in model.id.lower(),
    }


def openrouter_admin_pricing_rows(exchange: dict[str, Any], economy: dict[str, float]) -> list[dict[str, Any]]:
    rate = exchange.get("rate")
    effective_rate = float(rate) * (1 + OPENROUTER_USD_FEE_RATE) if isinstance(rate, (int, float)) else None
    rows: list[dict[str, Any]] = []
    for model in OPENROUTER_PRICE_CATALOG.values():
        item = model.model_dump()
        item["formats"] = [
            openrouter_format_economics(model, fmt, effective_rate, economy)
            for fmt in OPENROUTER_ADMIN_FORMATS
        ]
        item["resolutions"] = [
            openrouter_format_economics(model, fmt, effective_rate, economy)
            for fmt in OPENROUTER_RESOLUTION_FORMATS
        ]
        rows.append(item)
    return rows


def public_openrouter_pricing(exchange: dict[str, Any]) -> dict[str, Any]:
    economy = openrouter_economy_settings()
    rows = openrouter_admin_pricing_rows(exchange, economy)
    return {
        "formats": [
            {"id": fmt["id"], "label": fmt["label"], "short": fmt["short"]}
            for fmt in OPENROUTER_ADMIN_FORMATS
        ],
        "models": [
            {
                "id": row["id"],
                "label": row["name"],
                "formats": [
                    {
                        "id": fmt["id"],
                        "label": fmt["label"],
                        "short": fmt["short"],
                        "tokens": fmt.get("tokens"),
                        "requestSize": fmt.get("requestSize"),
                        "billingWidth": fmt.get("billingWidth"),
                        "billingHeight": fmt.get("billingHeight"),
                        "supported": fmt.get("supported", True),
                    }
                    for fmt in row.get("formats", [])
                ],
                "resolutions": [
                    {
                        "id": item["id"],
                        "label": item["label"],
                        "short": item["short"],
                        "tokens": item.get("tokens"),
                        "requestSize": item.get("requestSize"),
                        "billingWidth": item.get("billingWidth"),
                        "billingHeight": item.get("billingHeight"),
                    }
                    for item in row.get("resolutions", [])
                ],
            }
            for row in rows
        ],
    }


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
    request_plan = openrouter_image_request_plan(model_id, req.width, req.height)
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
        "requestSize": request_plan.get("size"),
        "requestSizeStrategy": request_plan.get("strategy"),
        "billingWidth": request_plan.get("billing_width"),
        "billingHeight": request_plan.get("billing_height"),
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


def _openrouter_video_billing_from_exchange(
    model: dict[str, Any],
    req: VideoGenerateRequest,
    *,
    rate: float,
    economy: dict[str, float],
    pricing_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pricing_rate = video_pricing.resolve_video_rate(
        model,
        model_id=str(model.get("id") or req.model), mode=req.mode, resolution=req.resolution,
        aspect_ratio=req.aspectRatio, generate_audio=req.generateAudio,
        samples=pricing_history if pricing_history is not None else video_pricing.load_actual_pricing_samples(db, safe_json_load),
    )
    rate_usd, unit = pricing_rate.usd_rate, pricing_rate.unit
    billed_units = float(req.duration)
    size = video_pricing.video_size(model, req.resolution, req.aspectRatio)
    if unit == "video_token":
        if not size:
            raise HTTPException(422, "Модель требует точный размер кадра для расчёта стоимости.")
        billed_units = (size[0] * size[1] * req.duration * 24) / 1024
    input_count = (1 if req.firstFrame else 0) + (1 if req.lastFrame else 0) + len(req.references)
    image_fee = float((model.get("pricingSkus") or {}).get("cents_per_image_input") or 0) / 100 * input_count
    cost_usd = rate_usd * billed_units + image_fee
    effective_rate = float(rate) * (1 + OPENROUTER_USD_FEE_RATE)
    cost_rub = cost_usd * effective_rate
    tokens = openrouter_tokens_for_cost(cost_rub, 1, economy)
    revenue = tokens * float(economy["tokenRub"])
    return {
        "billingStatus": "estimated", "modelId": model["id"], "pricingKey": pricing_rate.source_key,
        "pricingSource": pricing_rate.source,
        "pricingFallback": pricing_rate.fallback,
        "pricingSampleCount": pricing_rate.sample_count,
        "unit": unit, "rateUsd": rate_usd, "billedUnits": round(billed_units, 4),
        "estimatedCostUsd": round(cost_usd, 6), "estimatedCostRub": round(cost_rub, 4),
        "effectiveUsdRub": round(effective_rate, 6), "exchangeRate": float(rate),
        "tokenRub": economy["tokenRub"], "minMarginPercent": economy["minMarginPercent"],
        "chargedTokens": tokens, "revenueRub": round(revenue, 4),
        "profitRub": round(revenue - cost_rub, 4), "size": f"{size[0]}x{size[1]}" if size else None,
    }


async def estimate_openrouter_video_billing(
    model: dict[str, Any], req: VideoGenerateRequest, *, pricing_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    exchange = await fetch_usd_rub_rate()
    rate = exchange.get("rate")
    if not isinstance(rate, (int, float)):
        raise HTTPException(503, "Курс USD/RUB недоступен для расчёта видео.")
    return _openrouter_video_billing_from_exchange(
        model,
        req,
        rate=float(rate),
        economy=openrouter_economy_settings(),
        pricing_history=pricing_history,
    )


def _video_model_public_pricing(
    model: dict[str, Any],
    mode: str,
    *,
    rate: float | None,
    economy: dict[str, float],
    pricing_history: list[dict[str, Any]],
) -> dict[str, Any]:
    durations = [int(value) for value in (model.get("supportedDurations") or []) if int(value) > 0]
    resolutions = [str(value) for value in (model.get("supportedResolutions") or []) if str(value)]
    ratios = [str(value) for value in (model.get("supportedAspectRatios") or []) if str(value)]
    if rate is None or not durations or not resolutions or not ratios:
        return {"fromTokens": None, "examples": []}
    examples: list[dict[str, Any]] = []
    for duration in sorted(set(durations)):
        for resolution in resolutions:
            try:
                sample = VideoGenerateRequest(
                    mode=mode,
                    model=str(model.get("id") or ""),
                    prompt="preview",
                    duration=duration,
                    resolution=resolution,
                    aspectRatio=ratios[0],
                    generateAudio=False,
                    firstFrame="preview" if mode in {"image_to_video", "first_last_frame"} else None,
                    lastFrame="preview" if mode == "first_last_frame" else None,
                    references=["preview"] if mode == "reference_to_video" else [],
                )
                billing = _openrouter_video_billing_from_exchange(
                    model,
                    sample,
                    rate=rate,
                    economy=economy,
                    pricing_history=pricing_history,
                )
            except (HTTPException, ValueError, TypeError):
                continue
            examples.append({
                "duration": duration,
                "resolution": resolution,
                "aspectRatio": ratios[0],
                "tokens": int(billing["chargedTokens"]),
                "pricingSource": billing["pricingSource"],
            })
    return {
        "fromTokens": min((item["tokens"] for item in examples), default=None),
        "examples": examples,
        "estimated": any(item["pricingSource"] != "catalog" for item in examples),
    }


def _video_job_payload(row: sqlite3.Row, publication: sqlite3.Row | None = None) -> dict[str, Any]:
    settings = safe_json_load(row["settings_json"]) or {}
    return video_presentation.job_payload(
        row, settings, publication=publication,
        row_get=_row_get, publication_ready=_feed_publication_ready,
    )
def _video_gallery_item(
    row: sqlite3.Row,
    publication: sqlite3.Row | None = None,
    *,
    include_feed_media: bool = False,
) -> dict[str, Any]:
    settings = safe_json_load(row["settings_json"]) or {}
    return video_presentation.gallery_item(
        row, settings, publication=publication,
        include_feed_media=include_feed_media,
        row_get=_row_get,
        publication_ready=_feed_publication_ready,
    )
VIDEO_DOWNLOAD_MAX_BYTES = 300 * 1024 * 1024
VIDEO_FINALIZATION_STALE_SECONDS = 10 * 60
def _video_storage_reservation(
    conn: sqlite3.Connection,
    user_row: sqlite3.Row | None,
    user_id: str,
) -> video_storage.VideoStorageState:
    quota = gallery_quota_for_user(conn, user_row, user_id)
    state = video_storage.storage_state(conn, user_id, limit=int(quota["video_slots"] or 0))
    if not quota["video_enabled"] or state.limit <= 0:
        raise HTTPException(403, "Хранение видео не входит в ваш тариф.")
    if not state.can_reserve:
        raise HTTPException(
            409,
            "Все видеослоты защищены сердечком или заняты текущими генерациями. "
            "Снимите сердечко, удалите видео или дождитесь завершения генерации.",
        )
    return state


def _queue_video_file_deletion(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    now: str,
) -> None:
    settings = safe_json_load(row["job_settings"]) or {}
    filename = str(settings.get("localFile") or "")
    settings.pop("localFile", None)
    settings["galleryDeleted"] = True
    conn.execute(
        "UPDATE videos SET deleted_at=?,is_favorite=0 WHERE id=? AND user_id=?",
        (now, row["id"], row["user_id"]),
    )
    conn.execute(
        "UPDATE jobs SET settings_json=? WHERE id=? AND user_id=?",
        (json.dumps(settings, ensure_ascii=False), row["job_id"], row["user_id"]),
    )
    if filename:
        conn.execute(
            "INSERT INTO video_file_deletions "
            "(id,video_id,job_id,filename,attempts,last_error,created_at) "
            "VALUES (?,?,?,?,0,NULL,?)",
            (uuid.uuid4().hex, row["id"], row["job_id"], filename, now),
        )


def drain_video_file_deletions(*, limit: int = 50) -> dict[str, int]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM video_file_deletions ORDER BY created_at ASC, id ASC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    removed = 0
    failed = 0
    for row in rows:
        try:
            path = storage_resolve_under_root(MEDIA, str(row["filename"] or ""))
            if path and path.is_file():
                path.unlink(missing_ok=True)
            with db() as conn:
                conn.execute("DELETE FROM video_file_deletions WHERE id=?", (row["id"],))
            removed += 1
        except Exception as exc:  # pragma: no cover - filesystem dependent
            failed += 1
            with db() as conn:
                conn.execute(
                    "UPDATE video_file_deletions SET attempts=attempts+1,last_error=? WHERE id=?",
                    (truncate_admin_text(str(exc), 500), row["id"]),
                )
    return {"checked": len(rows), "removed": removed, "failed": failed}


def _evict_videos_for_new_result(
    conn: sqlite3.Connection,
    user_row: sqlite3.Row | None,
    user_id: str,
    *,
    now: str,
) -> int:
    quota = gallery_quota_for_user(conn, user_row, user_id)
    rows = video_storage.select_eviction_candidates(
        conn,
        user_id,
        limit=int(quota["video_slots"] or 0),
    )
    for row in rows:
        _queue_video_file_deletion(conn, row, now=now)
    return len(rows)


def _claim_video_finalization(job_id: str) -> tuple[bool, sqlite3.Row]:
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if current is None:
            raise HTTPException(404, "Видео-задание не найдено.")
        settings = safe_json_load(current["settings_json"]) or {}
        if current["status"] == "completed":
            return False, current
        if current["status"] == "finalizing" and video_storage.finalization_is_fresh(
            settings, stale_seconds=VIDEO_FINALIZATION_STALE_SECONDS
        ):
            return False, current
        settings["finalizingAt"] = datetime.now(timezone.utc).isoformat()
        settings.pop("finalizingError", None)
        conn.execute(
            "UPDATE jobs SET status='finalizing',progress=90,settings_json=? WHERE id=?",
            (json.dumps(settings, ensure_ascii=False), job_id),
        )
        return True, conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def _release_video_finalization(job_id: str, error: str) -> None:
    with db() as conn:
        row = conn.execute("SELECT settings_json FROM jobs WHERE id=?", (job_id,)).fetchone()
        settings = safe_json_load(row["settings_json"]) if row else {}
        settings = settings if isinstance(settings, dict) else {}
        settings.pop("finalizingAt", None)
        settings["finalizingError"] = truncate_admin_text(error, 500)
        conn.execute(
            "UPDATE jobs SET status='pending',progress=85,error_message=?,settings_json=? WHERE id=?",
            (truncate_admin_text(error, 500), json.dumps(settings, ensure_ascii=False), job_id),
        )
async def _download_video_result(
    url: str,
    job_id: str,
    *,
    use_openrouter_auth: bool = True,
) -> tuple[str, int]:
    filename = f"{job_id}.mp4"
    target = storage_resolve_under_root(MEDIA, filename)
    temporary = storage_resolve_under_root(MEDIA, f"{filename}.part")
    if target is None or temporary is None:
        raise HTTPException(500, "Некорректный путь хранения видео.")
    total, _path = await video_download.download_video(
        url, target=target, temporary=temporary, max_bytes=VIDEO_DOWNLOAD_MAX_BYTES,
        headers=openrouter_headers() if use_openrouter_auth else {},
        error_factory=HTTPException,
    )
    return filename, total
@app.get("/api/video/config")
async def video_generation_config(request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        user = conn.execute("SELECT plan, role FROM users WHERE id = ?", (user_id,)).fetchone()
        quota = gallery_quota_for_user(conn, user, user_id)
        storage_state = video_storage.storage_state(
            conn,
            user_id,
            limit=int(quota["video_slots"] or 0),
        )
    plan = str(_row_get(user, "plan") or "free").lower()
    is_admin = str(_row_get(user, "role") or "") == "admin"
    catalog = await fetch_openrouter_video_catalog()
    config = normalize_openrouter_video_config(_saved_setting("openrouter_video_models"), catalog)
    exchange = await fetch_usd_rub_rate()
    exchange_rate = exchange.get("rate") if isinstance(exchange.get("rate"), (int, float)) else None
    economy = openrouter_economy_settings()
    pricing_history = video_pricing.load_actual_pricing_samples(db, safe_json_load)
    runtime_settings = _saved_setting("config_ui_runtime"); local_video_enabled = LOCAL_LTX_ENABLED and runtime_settings.get("videoEnabled") is not False; local_video_profile = str(runtime_settings.get("videoProfile") or "local/ltx-2.3-fast-q3")
    modes: dict[str, list[dict[str, Any]]] = {}
    for mode in OPENROUTER_VIDEO_MODES:
        modes[mode] = ltx_video.catalog_for_mode(mode, enabled=local_video_enabled, profile_model_id=local_video_profile)
        for model in video_pricing.allowed_models(catalog, config, mode, plan, is_admin):
            public_model = dict(model)
            public_model["publicPricing"] = _video_model_public_pricing(
                model,
                mode,
                rate=float(exchange_rate) if exchange_rate is not None else None,
                economy=economy,
                pricing_history=pricing_history,
            )
            modes[mode].append(public_model)
    return {
        "modes": modes,
        "plan": plan,
        "videoSlots": quota["video_slots"],
        "feedPublicationEnabled": FEED_VIDEO_PUBLICATION_ENABLED,
        "videoStorage": {
            "used": storage_state.active,
            "limit": storage_state.limit,
            "free": storage_state.free,
            "full": storage_state.full,
            "storedBytes": storage_state.stored_bytes,
        },
        "availability": {
            mode: {
                "enabled": len((config.get("enabled") or {}).get(mode) or []) + len(ltx_video.catalog_for_mode(mode, enabled=local_video_enabled, profile_model_id=local_video_profile)),
                "tariff": len((((config.get("access") or {}).get(mode) or {}).get(plan)) or []) + len(ltx_video.catalog_for_mode(mode, enabled=local_video_enabled, profile_model_id=local_video_profile)),
                "reason": (
                    "В админке не включены модели для этого режима."
                    if not (config.get("enabled") or {}).get(mode) and not ltx_video.catalog_for_mode(mode, enabled=local_video_enabled, profile_model_id=local_video_profile)
                    else f"Для тарифа {plan.title()} не назначены модели этого режима."
                    if not is_admin and not (((config.get("access") or {}).get(mode) or {}).get(plan)) and not ltx_video.catalog_for_mode(mode, enabled=local_video_enabled, profile_model_id=local_video_profile)
                    else ""
                ),
            }
            for mode in OPENROUTER_VIDEO_MODES
        },
        "economy": economy,
        "exchange": {
            "usdRub": exchange_rate,
            "source": exchange.get("source"),
            "fetchedAt": exchange.get("fetchedAt"),
        },
    }
async def _generate_local_ltx_video(
    req: VideoGenerateRequest,
    *,
    user_id: str,
    profile: ltx_video.LtxProfile,
) -> dict[str, Any]:
    client = ltx_video.ComfyLtxClient(LOCAL_LTX_COMFYUI_BASE_URL, COMFYUI_TIMEOUT_SECONDS)
    try:
        return await ltx_video.validate_and_submit_local_ltx_job(
            req, user_id=user_id, profile=profile,
            workflow_path=LOCAL_LTX_WORKFLOW_API_PATH, client=client,
            open_db=db, reserve_storage=_video_storage_reservation,
            charge_tokens=charge_generation_tokens, refund_tokens=refund_generation_tokens,
        )
    except Exception as exc:
        if isinstance(exc, ltx_video.LocalLtxRequestError):
            raise HTTPException(exc.status_code, str(exc)) from exc
        raise HTTPException(502, f"Не удалось запустить LTX: {truncate_admin_text(str(exc), 300)}") from exc
@app.post("/api/video/generate")
async def generate_video(req: VideoGenerateRequest, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        user = conn.execute("SELECT plan, role FROM users WHERE id = ?", (user_id,)).fetchone()
    plan = str(_row_get(user, "plan") or "free").lower()
    is_admin = str(_row_get(user, "role") or "") == "admin"
    runtime_settings = _saved_setting("config_ui_runtime"); local = ltx_video.resolve_catalog_model(req.model, req.mode, enabled=LOCAL_LTX_ENABLED and runtime_settings.get("videoEnabled") is not False, profile_model_id=str(runtime_settings.get("videoProfile") or "local/ltx-2.3-fast-q3"))
    if local is not None:
        _local_model, profile = local
        return await _generate_local_ltx_video(
            req,
            user_id=user_id,
            profile=profile,
        )
    catalog = await fetch_openrouter_video_catalog()
    config = normalize_openrouter_video_config(_saved_setting("openrouter_video_models"), catalog)
    model = next((item for item in video_pricing.allowed_models(catalog, config, req.mode, plan, is_admin) if item.get("id") == req.model), None)
    if model is None:
        raise HTTPException(403, "Эта видеомодель недоступна для режима и тарифа.")
    if req.duration not in (model.get("supportedDurations") or []):
        raise HTTPException(422, "Модель не поддерживает выбранную длительность.")
    if req.resolution not in (model.get("supportedResolutions") or []):
        raise HTTPException(422, "Модель не поддерживает выбранное разрешение.")
    if req.aspectRatio not in (model.get("supportedAspectRatios") or []):
        raise HTTPException(422, "Модель не поддерживает выбранный формат кадра.")
    if req.mode == "image_to_video" and not req.firstFrame:
        raise HTTPException(422, "Добавьте исходный кадр.")
    if req.mode == "first_last_frame" and (not req.firstFrame or not req.lastFrame):
        raise HTTPException(422, "Добавьте начальный и конечный кадры.")
    if req.mode == "reference_to_video" and not req.references:
        raise HTTPException(422, "Добавьте хотя бы один референс.")
    billing = await estimate_openrouter_video_billing(model, req)
    body: dict[str, Any] = {"model": req.model, "prompt": req.prompt.strip(), "duration": req.duration, "resolution": req.resolution, "aspect_ratio": req.aspectRatio, "generate_audio": req.generateAudio}
    if req.firstFrame:
        body["frame_images"] = [{"type": "image_url", "image_url": {"url": openrouter_reference_value(req.firstFrame)}, "frame_type": "first_frame"}]
    if req.lastFrame:
        body.setdefault("frame_images", []).append({"type": "image_url", "image_url": {"url": openrouter_reference_value(req.lastFrame)}, "frame_type": "last_frame"})
    if req.references:
        body["input_references"] = [{"type": "image_url", "image_url": {"url": openrouter_reference_value(value)}} for value in req.references]
    job_id = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"; now = datetime.now(timezone.utc).isoformat()
    try:
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            locked_user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            _video_storage_reservation(conn, locked_user, user_id)
            charge = charge_generation_tokens(conn, user_id, int(billing["chargedTokens"]), job_id, req, billing)
            conn.execute("INSERT INTO jobs (id,user_id,mode,provider,status,progress,prompt_original,settings_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (job_id, user_id, req.mode, "openrouter", "submitting", 5, req.prompt.strip(), json.dumps({"openrouterModel": req.model, "duration": req.duration, "resolution": req.resolution, "aspectRatio": req.aspectRatio, "generateAudio": req.generateAudio, "tokenCost": billing["chargedTokens"], "openrouterBilling": billing}, ensure_ascii=False), now))
        persist_video_sources(job_id, user_id, req, now)
        submitted = await submit_openrouter_video(base_url=OPENROUTER_BASE_URL, headers=openrouter_headers(), payload=body)
    except Exception as exc:
        with db() as conn:
            refund_generation_tokens(conn, job_id, reason="video_submit_failed")
            row = conn.execute("SELECT settings_json FROM jobs WHERE id=?", (job_id,)).fetchone()
            failure = video_presentation.video_submit_failure(exc, safe_json_load(row["settings_json"]) if row else {})
            conn.execute("UPDATE jobs SET status='failed',progress=100,error_message=?,settings_json=?,completed_at=? WHERE id=?", (failure["public"], json.dumps(failure["settings"], ensure_ascii=False), datetime.now(timezone.utc).isoformat(), job_id))
        if isinstance(exc, HTTPException): raise
        raise HTTPException(failure["status"], failure["public"]) from exc
    with db() as conn:
        row = conn.execute("SELECT settings_json FROM jobs WHERE id=?", (job_id,)).fetchone()
        settings = safe_json_load(row["settings_json"]) or {}
        settings.update({"openrouterJobId": submitted["id"], "pollingUrl": submitted.get("polling_url"), "generationId": submitted.get("generation_id")})
        conn.execute("UPDATE jobs SET status='queued',progress=10,settings_json=? WHERE id=?", (json.dumps(settings, ensure_ascii=False), job_id))
    return {"id": job_id, "status": "queued", "progress": 10, "tokenCost": billing["chargedTokens"], "tokenBalance": charge["new_balance"]}
@app.post("/api/video/estimate")
async def estimate_video(req: VideoGenerateRequest, request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    with db() as conn:
        user = conn.execute("SELECT plan, role FROM users WHERE id = ?", (user_id,)).fetchone()
    plan = str(_row_get(user, "plan") or "free").lower()
    is_admin = str(_row_get(user, "role") or "") == "admin"
    runtime_settings = _saved_setting("config_ui_runtime"); local = ltx_video.resolve_catalog_model(req.model, req.mode, enabled=LOCAL_LTX_ENABLED and runtime_settings.get("videoEnabled") is not False, profile_model_id=str(runtime_settings.get("videoProfile") or "local/ltx-2.3-fast-q3"))
    if local is not None:
        model, profile = local
        if req.duration not in model["supportedDurations"]:
            raise HTTPException(422, "Локальный LTX поддерживает ролики длительностью 2 или 4 секунды.")
        if req.resolution not in model["supportedResolutions"]:
            raise HTTPException(422, "Локальный LTX сейчас работает в 480p.")
        if req.aspectRatio not in model["supportedAspectRatios"]:
            raise HTTPException(422, "Локальный LTX сейчас работает в формате 16:9.")
        if req.generateAudio:
            raise HTTPException(422, "Локальный LTX пока работает без генерации звука.")
        return ltx_video.estimate_local_ltx_billing(profile, duration=req.duration)
    catalog = await fetch_openrouter_video_catalog()
    config = normalize_openrouter_video_config(_saved_setting("openrouter_video_models"), catalog)
    model = next((item for item in video_pricing.allowed_models(catalog, config, req.mode, plan, is_admin) if item.get("id") == req.model), None)
    if model is None:
        raise HTTPException(403, "Эта видеомодель недоступна для режима и тарифа.")
    if req.duration not in (model.get("supportedDurations") or []):
        raise HTTPException(422, "Модель не поддерживает выбранную длительность.")
    if req.resolution not in (model.get("supportedResolutions") or []):
        raise HTTPException(422, "Модель не поддерживает выбранное разрешение.")
    if req.aspectRatio not in (model.get("supportedAspectRatios") or []):
        raise HTTPException(422, "Модель не поддерживает выбранный формат кадра.")
    return await estimate_openrouter_video_billing(model, req)
async def _refresh_video_job(row: sqlite3.Row) -> sqlite3.Row:
    initial_settings = safe_json_load(row["settings_json"]) or {}
    if row["status"] == "finalizing" and video_storage.finalization_is_fresh(
        initial_settings, stale_seconds=VIDEO_FINALIZATION_STALE_SECONDS
    ):
        return row
    if row["status"] not in {"submitting", "queued", "pending", "in_progress", "finalizing"}:
        return row
    settings = initial_settings
    is_local_ltx = str(row["provider"] or "") == "local_ltx"
    external_key = "comfyPromptId" if is_local_ltx else "openrouterJobId"
    external_id = str(settings.get(external_key) or "")
    if not external_id:
        return row
    try:
        if is_local_ltx:
            local_client = ltx_video.ComfyLtxClient(LOCAL_LTX_COMFYUI_BASE_URL, COMFYUI_TIMEOUT_SECONDS)
            state = await local_client.status(external_id)
        else:
            state = await poll_openrouter_video(base_url=OPENROUTER_BASE_URL, headers=openrouter_headers(), job_id=external_id, polling_url=settings.get("pollingUrl"))
    except Exception:
        return row
    status = str(state.get("status") or "pending")
    if is_local_ltx:
        state = ltx_video.recover_missing_job_state(state, row["created_at"])
        if state is None: return row
        status = str(state.get("status") or status)
    progress = 55 if status == "in_progress" else 15
    completed_at = None
    error = None
    downloaded_filename: str | None = None
    stored_bytes: int | None = None
    if status == "completed":
        if is_local_ltx and isinstance(state.get("output"), dict):
            urls = [local_client.view_url(state["output"])]
        else:
            urls = state.get("unsigned_urls") if isinstance(state.get("unsigned_urls"), list) else []
        if not urls:
            status = "failed"
            progress = 100
            error = "Провайдер завершил генерацию без видеофайла."
            completed_at = datetime.now(timezone.utc).isoformat()
            with db() as conn:
                refund_generation_tokens(conn, row["id"], reason="video_missing_result")
        else:
            claimed, claimed_row = _claim_video_finalization(row["id"])
            if not claimed:
                return claimed_row
            row = claimed_row
            settings = safe_json_load(row["settings_json"]) or {}
            try:
                if is_local_ltx:
                    downloaded_filename, stored_bytes = await _download_video_result(
                        str(urls[0]),
                        row["id"],
                        use_openrouter_auth=False,
                    )
                else:
                    downloaded_filename, stored_bytes = await _download_video_result(
                        str(urls[0]),
                        row["id"],
                    )
            except Exception as exc:
                _release_video_finalization(row["id"], str(exc))
                if isinstance(exc, HTTPException):
                    raise
                raise HTTPException(502, "Не удалось сохранить полученное видео.") from exc
            progress = 100
            settings["localFile"] = downloaded_filename
            settings["galleryVideoId"] = f"gallery_{row['id']}"
            settings.pop("galleryDeleted", None)
            settings.pop("finalizingAt", None)
            settings.pop("finalizingError", None)
            if not is_local_ltx:
                settings["openrouterUsage"] = state.get("usage") or {}
                settings["openrouterCostUsd"] = (state.get("usage") or {}).get("cost")
                billing = settings.get("openrouterBilling") if isinstance(settings.get("openrouterBilling"), dict) else {}
                actual = (state.get("usage") or {}).get("cost")
                if isinstance(actual, (int, float)):
                    # Video is sold at the server quote accepted before submission. Keep the
                    # provider's actual cost for margin reporting without changing that price.
                    settings["openrouterBilling"] = finalize_openrouter_billing_snapshot(billing, float(actual))
            completed_at = datetime.now(timezone.utc).isoformat()
    elif status in {"failed", "cancelled", "expired"}:
        progress = 100
        error = str(state.get("error") or "Провайдер не завершил генерацию видео.")
        completed_at = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            refund_generation_tokens(conn, row["id"], reason=f"video_{status}")
    settings["pollingUrl"] = state.get("polling_url") or settings.get("pollingUrl")
    try:
        with db() as conn:
            if status == "completed" and settings.get("localFile"):
                conn.execute("BEGIN IMMEDIATE")
                user_row = conn.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
                _evict_videos_for_new_result(conn, user_row, row["user_id"], now=completed_at or datetime.now(timezone.utc).isoformat())
                size = video_pricing.video_size(
                    {"supportedSizes": []},
                    str(settings.get("resolution") or "720p"),
                    str(settings.get("aspectRatio") or "16:9"),
                ) or (0, 0)
                conn.execute(
                    """
                    INSERT INTO videos (
                        id, user_id, job_id, url, width, height, duration_seconds,
                        aspect_ratio, mode, provider, prompt_original, settings_json,
                        stored_bytes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        url=excluded.url, width=excluded.width, height=excluded.height,
                        duration_seconds=excluded.duration_seconds, aspect_ratio=excluded.aspect_ratio,
                        prompt_original=excluded.prompt_original, settings_json=excluded.settings_json,
                        stored_bytes=excluded.stored_bytes, deleted_at=NULL
                    """,
                    (
                        settings["galleryVideoId"], row["user_id"], row["id"],
                        f"/api/video/media/{row['id']}", int(size[0]), int(size[1]),
                        int(settings.get("duration") or 0), settings.get("aspectRatio"),
                        row["mode"], str(row["provider"] or "openrouter"), row["prompt_original"] or "",
                        json.dumps(settings, ensure_ascii=False), stored_bytes, row["created_at"],
                    ),
                )
            conn.execute("UPDATE jobs SET status=?,progress=?,error_message=?,settings_json=?,completed_at=COALESCE(?,completed_at) WHERE id=?", (status, progress, error, json.dumps(settings, ensure_ascii=False), completed_at, row["id"]))
            result = conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
    except Exception as exc:
        if downloaded_filename:
            path = storage_resolve_under_root(MEDIA, downloaded_filename)
            if path:
                path.unlink(missing_ok=True)
            _release_video_finalization(row["id"], str(exc))
        raise
    if status == "completed":
        drain_video_file_deletions(limit=10)
    if is_local_ltx and status in {"completed", "failed", "cancelled", "expired"}:
        with suppress(Exception):
            await local_client.free_memory()
    return result


@app.get("/api/video/jobs/{job_id}")
async def get_video_job(job_id: str, request: Request) -> dict[str, Any]:
    user_id = require_trusted_user(request)["legacy_user_id"]
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=? AND user_id=? AND mode IN ('text_to_video','image_to_video','first_last_frame','reference_to_video')", (job_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Видео-задание не найдено.")
    row = await _refresh_video_job(row)
    return _video_job_payload(row)


def _backfill_completed_video_gallery(conn: sqlite3.Connection, user_id: str) -> int:
    rows = conn.execute(
        "SELECT * FROM jobs WHERE user_id=? AND status='completed' "
        "AND mode IN ('text_to_video','image_to_video','first_last_frame','reference_to_video')",
        (user_id,),
    ).fetchall()
    inserted = 0
    for row in rows:
        settings = safe_json_load(row["settings_json"]) or {}
        filename = str(settings.get("localFile") or "")
        path = storage_resolve_under_root(MEDIA, filename) if filename else None
        if path is None or not path.is_file():
            continue
        gallery_id = str(settings.get("galleryVideoId") or f"gallery_{row['id']}")
        settings["galleryVideoId"] = gallery_id
        size = video_pricing.video_size(
            {"supportedSizes": []},
            str(settings.get("resolution") or "720p"),
            str(settings.get("aspectRatio") or "16:9"),
        ) or (0, 0)
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO videos (
                id,user_id,job_id,url,width,height,duration_seconds,aspect_ratio,
                mode,provider,prompt_original,settings_json,stored_bytes,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                gallery_id, user_id, row["id"], f"/api/video/media/{row['id']}",
                int(size[0]), int(size[1]), int(settings.get("duration") or 0),
                settings.get("aspectRatio"), row["mode"], str(row["provider"] or "openrouter"),
                row["prompt_original"] or "", json.dumps(settings, ensure_ascii=False),
                path.stat().st_size, row["created_at"],
            ),
        )
        if conn.total_changes > before:
            conn.execute(
                "UPDATE jobs SET settings_json=? WHERE id=?",
                (json.dumps(settings, ensure_ascii=False), row["id"]),
            )
            inserted += 1
    return inserted


@app.get("/api/video/history")
async def video_history(request: Request, limit: int = 30) -> dict[str, Any]:
    user_id = require_trusted_user(request)["legacy_user_id"]
    with db() as conn:
        _backfill_completed_video_gallery(conn, user_id)
        rows = conn.execute("SELECT * FROM jobs WHERE user_id=? AND mode IN ('text_to_video','image_to_video','first_last_frame','reference_to_video') ORDER BY created_at DESC LIMIT ?", (user_id, max(1, min(limit, 60)))).fetchall()
    refreshed = [await _refresh_video_job(row) for row in rows[:5]] + list(rows[5:])
    job_ids = [str(row["id"]) for row in refreshed]
    publications: dict[str, sqlite3.Row] = {}
    if job_ids:
        placeholders = ",".join("?" for _ in job_ids)
        with db() as conn:
            publications = {
                str(row["source_job_id"]): row
                for row in conn.execute(
                    f"SELECT * FROM feed_publications WHERE media_type = 'video' AND source_job_id IN ({placeholders})",
                    job_ids,
                ).fetchall()
            }
    return {"items": [_video_job_payload(row, publications.get(str(row["id"]))) for row in refreshed]}


@app.get("/api/video/media/{job_id}")
async def video_media(job_id: str, request: Request) -> FileResponse:
    user_id = require_trusted_user(request)["legacy_user_id"]
    with db() as conn:
        row = conn.execute("SELECT settings_json FROM jobs WHERE id=? AND user_id=? AND status='completed'", (job_id, user_id)).fetchone()
    settings = safe_json_load(row["settings_json"]) if row else {}
    filename = str((settings or {}).get("localFile") or "")
    path = storage_resolve_under_root(MEDIA, filename) if filename else None
    if path is None or not path.exists():
        raise HTTPException(404, "Видеофайл не найден.")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/gallery/videos/{video_id}/favorite")
async def gallery_video_favorite(video_id: str, req: FavoriteRequest, request: Request) -> dict[str, Any]:
    user_id = require_trusted_user(request)["legacy_user_id"]
    with db() as conn:
        row = conn.execute(
            "SELECT id,is_favorite FROM videos WHERE id=? AND user_id=? AND deleted_at IS NULL",
            (video_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Видео не найдено.")
        if req.isFavorite and not bool(row["is_favorite"]):
            user_row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            state = video_storage_state_for_user(conn, user_row, user_id)
            if state.limit <= 0 or state.protected >= state.limit:
                raise HTTPException(
                    409,
                    "Нельзя защитить еще одно видео: все видеослоты уже защищены или зарезервированы.",
                )
        conn.execute(
            "UPDATE videos SET is_favorite=? WHERE id=? AND user_id=?",
            (1 if req.isFavorite else 0, video_id, user_id),
        )
    return {"ok": True, "videoId": video_id, "favorite": req.isFavorite}


@app.delete("/api/gallery/videos/{video_id}")
async def gallery_video_delete(video_id: str, request: Request) -> dict[str, Any]:
    user_id = require_trusted_user(request)["legacy_user_id"]
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT v.*, j.settings_json AS job_settings FROM videos v "
            "LEFT JOIN jobs j ON j.id=v.job_id "
            "WHERE v.id=? AND v.user_id=? AND v.deleted_at IS NULL",
            (video_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Видео не найдено.")
        preparing_publication = conn.execute(
            "SELECT id FROM feed_publications WHERE video_id = ? AND status = 'preparing'",
            (video_id,),
        ).fetchone()
        if preparing_publication is not None:
            raise HTTPException(409, "Дождитесь подготовки публикации или снимите её с ленты.")
        _queue_video_file_deletion(conn, row, now=now)
    cleanup = drain_video_file_deletions(limit=10)
    return {"ok": True, "videoId": video_id, "cleanupQueued": cleanup["failed"] > 0}


def openrouter_video_usage_stats() -> dict[str, Any]:
    """Summarize completed OpenRouter video jobs without inventing missing costs."""
    with db() as conn:
        rows = conn.execute(
            "SELECT mode, settings_json FROM jobs "
            "WHERE provider = 'openrouter' AND status = 'completed' "
            "AND mode IN ('text_to_video', 'image_to_video', 'first_last_frame', 'reference_to_video') "
            "ORDER BY completed_at DESC LIMIT 500"
        ).fetchall()
    models: dict[str, dict[str, Any]] = {}
    modes: dict[str, dict[str, Any]] = {}
    total_count = 0
    total_priced = 0
    total_cost_usd = 0.0
    for row in rows:
        settings = safe_json_load(row["settings_json"]) or {}
        if not isinstance(settings, dict):
            settings = {}
        mode = str(row["mode"] or "unknown")
        model = str(settings.get("openrouterModel") or settings.get("modelProfile") or "unknown")
        try:
            cost_usd: float | None = float(settings.get("openrouterCostUsd"))
        except (TypeError, ValueError):
            cost_usd = None
        total_count += 1
        mode_bucket = modes.setdefault(mode, {"count": 0, "priced": 0, "costUsd": 0.0})
        model_bucket = models.setdefault(model, {"count": 0, "priced": 0, "costUsd": 0.0})
        mode_bucket["count"] += 1
        model_bucket["count"] += 1
        if cost_usd is not None:
            total_priced += 1
            total_cost_usd += cost_usd
            mode_bucket["priced"] += 1
            mode_bucket["costUsd"] += cost_usd
            model_bucket["priced"] += 1
            model_bucket["costUsd"] += cost_usd

    def rows_for(source: dict[str, dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
        result = []
        for key, item in source.items():
            count = int(item["count"] or 0)
            priced = int(item["priced"] or 0)
            cost = float(item["costUsd"] or 0)
            result.append({
                key_name: key,
                "count": count,
                "priced": priced,
                "costUsd": round(cost, 6),
                "avgCostUsd": round(cost / priced, 6) if priced else None,
            })
        result.sort(key=lambda item: int(item["count"]), reverse=True)
        return result

    return {
        "count": total_count,
        "priced": total_priced,
        "costUsd": round(total_cost_usd, 6),
        "avgCostUsd": round(total_cost_usd / total_priced, 6) if total_priced else None,
        "models": rows_for(models, "model"),
        "modes": rows_for(modes, "mode"),
    }


OPENROUTER_ADMIN_MODES = {
    "text_to_image", "image_to_image", "edit", "paint", "inpaint", "outpaint", "remove_background"
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


def tariff_model_counts(
    image_config: dict[str, Any] | None = None,
    video_config: dict[str, Any] | None = None,
) -> dict[str, dict[str, int]]:
    """Derive tariff model totals from the access matrices configured by admins."""
    normalized_images = normalize_openrouter_config(
        _saved_setting("openrouter_models") if image_config is None else image_config
    )
    raw_video = _saved_setting("openrouter_video_models") if video_config is None else video_config
    raw_video = raw_video if isinstance(raw_video, dict) else {}
    image_access = normalized_images.get("access") if isinstance(normalized_images.get("access"), dict) else {}
    video_enabled = raw_video.get("enabled") if isinstance(raw_video.get("enabled"), dict) else {}
    video_access = raw_video.get("access") if isinstance(raw_video.get("access"), dict) else {}

    result: dict[str, dict[str, int]] = {}
    for plan in PLAN_ORDER:
        image_ids = {"server:local_flux_klein"}
        if plan != "free":
            for mode_access in image_access.values():
                if not isinstance(mode_access, dict):
                    continue
                image_ids.update(
                    model_id
                    for model_id in mode_access.get(plan, [])
                    if isinstance(model_id, str) and model_id
                )

        video_ids: set[str] = set()
        if plan != "free":
            for mode in OPENROUTER_VIDEO_MODES:
                enabled_ids = {
                    model_id
                    for model_id in video_enabled.get(mode, [])
                    if isinstance(model_id, str) and model_id
                }
                mode_access = video_access.get(mode) if isinstance(video_access.get(mode), dict) else {}
                plan_ids = {
                    model_id
                    for model_id in mode_access.get(plan, [])
                    if isinstance(model_id, str) and model_id
                }
                video_ids.update(enabled_ids.intersection(plan_ids))
        result[plan] = {
            "image_model_count": len(image_ids),
            "video_model_count": len(video_ids),
        }
    return result


def tariff_config_with_model_counts(
    conn: sqlite3.Connection | None = None,
) -> dict[str, dict[str, Any]]:
    tariffs = get_tariff_config(conn)
    counts = tariff_model_counts()
    return {
        plan: {**tariff, **counts[plan]}
        for plan, tariff in tariffs.items()
    }


def filter_openrouter_config_by_capabilities(config: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = normalize_openrouter_config(config)
    allowed = {
        mode: {str(model.get("id")) for model in catalog if mode in (model.get("modes") or [])}
        for mode in OPENROUTER_ADMIN_MODES
    }
    enabled = normalized.get("enabled") if isinstance(normalized.get("enabled"), dict) else {}
    access = normalized.get("access") if isinstance(normalized.get("access"), dict) else {}
    quality = normalized.get("qualityDefaults") if isinstance(normalized.get("qualityDefaults"), dict) else {}
    defaults = normalized.get("defaults") if isinstance(normalized.get("defaults"), dict) else {}
    for mode in OPENROUTER_ADMIN_MODES:
        valid = allowed.get(mode, set())
        enabled[mode] = [model_id for model_id in enabled.get(mode, []) if model_id in valid]
        if mode in defaults and defaults[mode] not in valid:
            defaults.pop(mode, None)
        mode_access = access.get(mode) if isinstance(access.get(mode), dict) else {}
        for tier in list(mode_access):
            mode_access[tier] = [model_id for model_id in mode_access.get(tier, []) if model_id in valid]
        mode_quality = quality.get(mode) if isinstance(quality.get(mode), dict) else {}
        for preset in list(mode_quality):
            if mode_quality[preset] not in valid:
                mode_quality.pop(preset, None)
    return normalized


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


PUBLIC_MODEL_MODE_LABELS = {
    "text_to_image": "По тексту",
    "image_to_image": "По фото",
    "edit": "Сборка",
    "paint": "Редактор - рисунок",
    "inpaint": "Редактор - маска",
    "outpaint": "Редактор - расширение",
    "remove_background": "Удаление фона",
}


def _public_model_option(model_id: str, capability: dict[str, Any] | None = None) -> dict[str, Any]:
    if model_id == "server:local_flux_klein":
        return {
            "id": "server:local_flux_klein",
            "label": "ИЗО Base",
            "provider": "comfyui",
            "modelProfile": "local_flux_klein",
            "tokenHint": 1,
            "supportedResolutionIds": [item["id"] for item in IMAGE_RESOLUTIONS if item["tier"] != "four_k"],
            "generation": {
                "fixedSteps": LOCAL_TEXT_TO_IMAGE_STEPS,
                "allowsExactRepeat": False,
                "supportsSeed": True,
                "maxInputReferences": 4,
            },
        }
    price = OPENROUTER_PRICE_CATALOG.get(model_id)
    return {
        "id": model_id,
        "label": price.name if price else model_id.split("/")[-1].replace("-", " ").title(),
        "provider": "openrouter",
        "modelProfile": model_id,
        "tokenHint": price.min_tokens if price else 1,
        "supportedResolutionIds": supported_resolution_ids_from_capability(capability),
        "generation": {
            "fixedSteps": None,
            "allowsExactRepeat": True,
            "supportsSeed": False,
            "maxInputReferences": min(4, int((capability or {}).get("maxInputReferences") or 2)),
        },
    }


def public_model_access_for_plan(plan: str, capability_catalog: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if plan not in PLAN_ORDER:
        plan = "mini"
    tariff = get_tariff_config()[plan]
    config = get_openrouter_config()
    capabilities = {item.get("id"): item for item in (capability_catalog or []) if item.get("id")}
    access = config.get("access") if isinstance(config.get("access"), dict) else {}
    modes: dict[str, Any] = {}
    for mode in sorted(PUBLIC_MODEL_MODE_LABELS.keys()):
        ids = ["server:local_flux_klein"]
        mode_access = access.get(mode) if isinstance(access.get(mode), dict) else {}
        tier_ids = mode_access.get(plan) if isinstance(mode_access.get(plan), list) else []
        for model_id in tier_ids:
            capability = capabilities.get(model_id)
            compatible = not capability_catalog or (capability is not None and mode in (capability.get("modes") or []))
            if isinstance(model_id, str) and model_id not in ids and compatible:
                ids.append(model_id)
        models = [_public_model_option(model_id, capabilities.get(model_id)) for model_id in ids]
        presets: dict[str, str] = {}
        tariff_defaults = tariff.get("model_defaults") if isinstance(tariff.get("model_defaults"), dict) else {}
        for preset in QUALITY_PRESETS:
            default_id = str(tariff_defaults.get(preset) or "server:local_flux_klein")
            if default_id == "server:local_flux_klein" or default_id in ids:
                presets[preset] = default_id
                continue
            mode_default = openrouter_quality_model(config, mode, preset, plan)
            presets[preset] = mode_default if mode_default in ids else "server:local_flux_klein"
        modes[mode] = {
            "id": mode,
            "label": PUBLIC_MODEL_MODE_LABELS[mode],
            "models": models,
            "presets": presets,
        }
    return {"plan": plan, "modes": modes}


@app.get("/api/model-access")
async def model_access(request: Request) -> dict[str, Any]:
    trusted = require_trusted_user(request)
    with db() as conn:
        row = conn.execute("SELECT plan FROM users WHERE internal_user_id = ?", (trusted["internal_user_id"],)).fetchone()
        if row is None and trusted["legacy_user_id"]:
            row = conn.execute("SELECT plan FROM users WHERE id = ?", (trusted["legacy_user_id"],)).fetchone()
    plan = str(row["plan"] if row else "mini").lower()
    try:
        capability_catalog = await fetch_openrouter_image_capabilities()
    except Exception:
        capability_catalog = []
    return {"ok": True, **public_model_access_for_plan(plan, capability_catalog), "openrouterPricing": public_openrouter_pricing(await fetch_usd_rub_rate())}


app.include_router(create_admin_operations_router(AdminOperationsDependencies(
    db=db,
    require_admin=require_trusted_admin,
    saved_setting=_saved_setting,
    save_setting=_save_setting,
    record_audit=record_audit_log,
    fetch_openrouter_key_status=fetch_openrouter_key_status,
    openrouter_usage_stats=openrouter_usage_stats,
    get_openrouter_config=get_openrouter_config,
    fetch_usd_rub_rate=fetch_usd_rub_rate,
    openrouter_catalog_snapshot=openrouter_catalog_snapshot,
    schedule_openrouter_catalog_refresh=schedule_openrouter_catalog_refresh,
    openrouter_economy_settings=openrouter_economy_settings,
    openrouter_price_catalog=lambda: OPENROUTER_PRICE_CATALOG,
    invalidate_openrouter_admin_caches=invalidate_openrouter_admin_caches,
    filter_openrouter_config=filter_openrouter_config_by_capabilities,
    normalize_openrouter_config=normalize_openrouter_config,
    secret_exists=OPENROUTER_SECRET_STORE.exists,
    secret_get=OPENROUTER_SECRET_STORE.get,
    secret_set=_save_bot_secret,
    secret_delete=OPENROUTER_SECRET_STORE.delete,
    probe_social=lambda network, **kwargs: probe_social_provider(network, max_verify=MAX_HTTP_VERIFY, **kwargs),
    send_social_test=send_social_test,
    notification_worker_status=ADMIN_NOTIFICATION_DELIVERY_WORKER.status,
    social_worker_status=SOCIAL_DELIVERY_WORKER.status,
)))


@app.put("/api/admin/openrouter/key")
async def admin_save_openrouter_key(req: AdminSecretKeyRequest, request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    key = req.key.strip()
    if not key.startswith("sk-or-"):
        raise HTTPException(400, "OpenRouter key должен начинаться с sk-or-")
    try:
        save_openrouter_api_key(key)
    except SecretStoreError as exc:
        raise HTTPException(503, "OpenRouter secret store is unavailable.") from exc
    key_status = await fetch_openrouter_key_status()
    refresh_started = schedule_openrouter_catalog_refresh()
    return {
        "ok": bool(key_status.get("ok")),
        "key": key_status,
        "usage": openrouter_usage_stats(),
        "config": get_openrouter_config(),
        "catalogRefreshStarted": refresh_started,
    }


@app.delete("/api/admin/openrouter/key")
async def admin_delete_openrouter_key(request: Request) -> dict[str, Any]:
    require_trusted_admin(request)
    try:
        delete_openrouter_api_key()
    except SecretStoreError as exc:
        raise HTTPException(503, "OpenRouter secret store is unavailable.") from exc
    key_status = await fetch_openrouter_key_status()
    refresh_started = schedule_openrouter_catalog_refresh()
    return {
        "ok": True,
        "key": key_status,
        "usage": openrouter_usage_stats(),
        "config": get_openrouter_config(),
        "catalogRefreshStarted": refresh_started,
    }


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
    pose_model = sel.get("poseModelProfile") or edit_model
    base = {
        "text_to_image": {"provider": "local", "modelProfileId": edit_model},
        "image_to_image": {"provider": "local", "modelProfileId": edit_model},
        "edit": {"provider": "local", "modelProfileId": edit_model},
        "edit_pose": {"provider": "local", "modelProfileId": pose_model, "locked": True, "label": f"Flux 2 Klein {'4B' if '4b' in pose_model else '9B'} + DWPose"},
        "face": {"provider": "local", "modelProfileId": edit_model},
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
    openrouter_status = openrouter_key_status_snapshot()
    openrouter_key = bool(openrouter_status.get("configured"))
    openrouter_usage = openrouter_usage_stats()
    exchange = usd_rub_rate_snapshot()
    catalog_snapshot = openrouter_catalog_snapshot()
    openrouter_capabilities = catalog_snapshot["models"]
    openrouter_video_catalog = catalog_snapshot["videoModels"]
    catalog_meta = catalog_snapshot["meta"]
    openrouter_capability_error = catalog_meta.get("lastError")
    openrouter_video_error = catalog_meta.get("lastError")
    refresh_started = (
        schedule_openrouter_catalog_refresh()
        if openrouter_catalog_refresh_needed(catalog_snapshot)
        else False
    )

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
        "loraSettings": _saved_setting("server_model_loras") or {"enabled": {}},
        "serverModelProfiles": {"profiles": get_server_model_profiles()},
        "comfyuiAvailable": status.get("comfyuiAvailable"),
        "openrouter": {
            "keyConfigured": openrouter_key,
            "status": openrouter_status,
            "usage": openrouter_usage,
            "config": filter_openrouter_config_by_capabilities(get_openrouter_config(), openrouter_capabilities) if openrouter_capabilities else get_openrouter_config(),
            "exchange": exchange,
            "economy": openrouter_economy,
            "backendPricing": openrouter_admin_pricing_rows(exchange, openrouter_economy),
            "capabilityCatalog": openrouter_capabilities,
            "capabilityError": openrouter_capability_error,
            "capabilityCacheTtlSeconds": OPENROUTER_CAPABILITY_CACHE_TTL_SECONDS,
            "catalogState": {
                **catalog_meta,
                "refreshStarted": refresh_started,
            },
            "videoCatalog": openrouter_video_catalog,
            "videoConfig": normalize_openrouter_video_config(_saved_setting("openrouter_video_models"), openrouter_video_catalog),
            "videoUsage": openrouter_video_usage_stats(),
            "videoCatalogError": openrouter_video_error,
            "videoCatalogSource": "openrouter:/api/v1/videos/models",
        },
        "comfyFiles": comfyui_workflows.active_profile_admin_files(status.get("profiles", []), get_model_settings().get("editModelProfile") or "flux_klein_9b", get_server_model_profiles().get(get_model_settings().get("editModelProfile") or "flux_klein_9b", {})) if include_local else {},
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


# ---------------------------------------------------------------------------
# Live Feed MVP. Публикации из личной галереи + публичная лента + реакции.
# Auth: чтение ленты публичное (viewerState только при trusted session);
# публикация и реакции — только trusted cookie session (require_trusted_user).
# Легаси-заголовки/куки здесь не читаются никогда.
# ---------------------------------------------------------------------------

FEED_PROMPT_VISIBILITIES = {"open", "partial", "hidden"}
FEED_PUBLICATION_CATEGORIES = {"art", "photo", "design", "character", "product", "architecture", "other"}
FEED_PARTIAL_PROMPT_CHARS = 140
FEED_THUMB_MAX_SIDE = 640
FEED_LARGE_MAX_SIDE = 1536
FEED_DISPLAY_POLICY = "preserve_aspect_ratio"
FEED_VIDEO_PUBLICATION_ENABLED = os.getenv("FEED_VIDEO_PUBLICATION_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
FEED_VIDEO_FULL_MAX_EDGE = max(720, min(3840, int(os.getenv("FEED_VIDEO_FULL_MAX_EDGE", "1920"))))
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

feed_video_publication_queue: asyncio.Queue[str | None] | None = None
feed_video_publication_worker_task: asyncio.Task[None] | None = None
feed_video_publication_worker_stopping = False


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


@dataclass
class FeedVideoAssetInfo:
    poster_name: str
    poster_width: int
    poster_height: int
    poster_bytes: int
    preview_name: str
    preview_bytes: int
    full_name: str
    full_bytes: int
    native_aspect_ratio: str
    orientation: str
    duration_ms: int
    has_audio: bool


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
        "text_to_video": "По тексту",
        "image_to_video": "По изображению",
        "first_last_frame": "По двум кадрам",
        "reference_to_video": "По референсам",
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


def _feed_ffmpeg_executable() -> str:
    configured = str(os.getenv("FFMPEG_BINARY") or "").strip()
    if configured:
        return configured
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception as exc:  # pragma: no cover - installation dependent
        raise RuntimeError("FFmpeg is unavailable for feed video derivatives") from exc


def _run_feed_ffmpeg(arguments: list[str], *, timeout: int = 180) -> None:
    try:
        subprocess.run(
            [
                _feed_ffmpeg_executable(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-filter_threads", "1", *arguments,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Feed video derivative generation failed") from exc


def create_feed_video_assets(
    publication_id: str,
    source_path: Path,
    *,
    width: int,
    height: int,
    duration_seconds: int,
    has_audio: bool,
) -> FeedVideoAssetInfo:
    if not source_path.is_file():
        raise FileNotFoundError("Feed source video file not found")
    target_dir = feed_media_dir()
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", publication_id)
    poster_rel = f"feed/{safe_id}_video_poster.webp"
    preview_rel = f"feed/{safe_id}_video_preview.mp4"
    full_rel = f"feed/{safe_id}_video_full.mp4"
    poster_path = MEDIA / poster_rel
    preview_path = MEDIA / preview_rel
    full_path = MEDIA / full_rel
    poster_temp = poster_path.with_name(f"{poster_path.stem}.part.webp")
    preview_temp = preview_path.with_name(f"{preview_path.stem}.part.mp4")
    full_temp = full_path.with_name(f"{full_path.stem}.part.mp4")
    outputs = [poster_path, preview_path, full_path]
    temporary_outputs = [poster_temp, preview_temp, full_temp]
    for path in [*outputs, *temporary_outputs]:
        path.unlink(missing_ok=True)
    try:
        _run_feed_ffmpeg([
            "-ss", "0.2", "-i", str(source_path), "-frames:v", "1",
            "-vf", "scale='min(640,iw)':'min(640,ih)':force_original_aspect_ratio=decrease",
            "-c:v", "libwebp", "-quality", "78", "-threads", "1", str(poster_temp),
        ])
        preview_seconds = max(1, min(int(duration_seconds or 3), 3))
        _run_feed_ffmpeg([
            "-i", str(source_path), "-t", str(preview_seconds), "-an",
            "-vf", "scale='min(480,iw)':'min(480,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "29",
            "-pix_fmt", "yuv420p", "-threads", "1", "-movflags", "+faststart", str(preview_temp),
        ])
        full_arguments = [
            "-i", str(source_path), "-map", "0:v:0", "-sn", "-dn",
            "-vf", f"scale='min({FEED_VIDEO_FULL_MAX_EDGE},iw)':'min({FEED_VIDEO_FULL_MAX_EDGE},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
            "-pix_fmt", "yuv420p", "-threads", "1", "-map_metadata", "-1",
        ]
        if has_audio:
            full_arguments.extend(["-map", "0:a?", "-c:a", "aac", "-b:a", "128k"])
        else:
            full_arguments.append("-an")
        full_arguments.extend(["-movflags", "+faststart", str(full_temp)])
        _run_feed_ffmpeg(full_arguments, timeout=300)
        if any(not path.is_file() or path.stat().st_size <= 16 for path in temporary_outputs):
            raise RuntimeError("Feed video derivative is empty")
        for temporary, final in zip(temporary_outputs, outputs):
            os.replace(temporary, final)
        with Image.open(poster_path) as poster:
            poster_width, poster_height = poster.size
    except Exception:
        for path in [*outputs, *temporary_outputs]:
            path.unlink(missing_ok=True)
        raise
    final_width = int(width or poster_width)
    final_height = int(height or poster_height)
    return FeedVideoAssetInfo(
        poster_name=poster_rel,
        poster_width=poster_width,
        poster_height=poster_height,
        poster_bytes=poster_path.stat().st_size,
        preview_name=preview_rel,
        preview_bytes=preview_path.stat().st_size,
        full_name=full_rel,
        full_bytes=full_path.stat().st_size,
        native_aspect_ratio=_feed_aspect_ratio(final_width, final_height),
        orientation=_feed_orientation(final_width, final_height),
        duration_ms=max(0, int(duration_seconds or 0) * 1000),
        has_audio=bool(has_audio),
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
    followers_count = int(conn.execute(
        "SELECT COUNT(*) AS c FROM feed_author_follows WHERE author_internal_user_id = ?",
        (internal_user_id,),
    ).fetchone()["c"])
    following_count = int(conn.execute(
        "SELECT COUNT(*) AS c FROM feed_author_follows WHERE follower_internal_user_id = ?",
        (internal_user_id,),
    ).fetchone()["c"])
    return _feed_author_profile_payload(
        row,
        internal_user_id,
        _row_get(identity, "provider_avatar_url"),
        followers_count,
        following_count,
    )


def _feed_author_profile_payload(
    row: sqlite3.Row | None,
    internal_user_id: str,
    provider_avatar_url: str | None,
    followers_count: int,
    following_count: int,
) -> dict[str, Any]:
    name = (
        _row_get(row, "display_name")
        or _row_get(row, "username")
        or _row_get(row, "first_name")
        or "Пользователь ИЗО"
    )
    return {
        "id": internal_user_id,
        "displayName": name,
        "username": _row_get(row, "username"),
        "avatarUrl": _row_get(row, "avatar_url") or provider_avatar_url,
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
        "followersCount": followers_count,
        "followingCount": following_count,
    }


def _feed_author_profiles(
    conn: sqlite3.Connection,
    author_keys: set[tuple[str, str | None]],
) -> dict[str, dict[str, Any]]:
    if not author_keys:
        return {}
    internal_ids = sorted({internal_id for internal_id, _legacy_id in author_keys})
    legacy_ids = sorted({legacy_id for _internal_id, legacy_id in author_keys if legacy_id})
    internal_slots = ",".join("?" for _ in internal_ids)
    user_where = f"internal_user_id IN ({internal_slots})"
    user_params: list[Any] = list(internal_ids)
    if legacy_ids:
        legacy_slots = ",".join("?" for _ in legacy_ids)
        user_where += f" OR id IN ({legacy_slots})"
        user_params.extend(legacy_ids)
    user_rows = conn.execute(
        f"""
        SELECT id, internal_user_id, display_name, username, first_name, avatar_url, avatar_preset,
               public_about, public_website, public_focus, public_phone,
               public_links_json, gender, age, city, country
        FROM users WHERE {user_where}
        """,
        user_params,
    ).fetchall()
    by_internal = {str(row["internal_user_id"]): row for row in user_rows if _row_get(row, "internal_user_id")}
    by_legacy = {str(row["id"]): row for row in user_rows}
    identity_rows = conn.execute(
        f"""
        SELECT internal_user_id, provider_avatar_url
        FROM auth_identities
        WHERE internal_user_id IN ({internal_slots})
          AND provider_avatar_url IS NOT NULL AND provider_avatar_url != ''
        ORDER BY last_login_at DESC
        """,
        internal_ids,
    ).fetchall()
    avatars: dict[str, str] = {}
    for identity in identity_rows:
        avatars.setdefault(str(identity["internal_user_id"]), str(identity["provider_avatar_url"]))
    followers = {
        str(row["author_internal_user_id"]): int(row["c"])
        for row in conn.execute(
            f"SELECT author_internal_user_id, COUNT(*) AS c FROM feed_author_follows "
            f"WHERE author_internal_user_id IN ({internal_slots}) GROUP BY author_internal_user_id",
            internal_ids,
        ).fetchall()
    }
    following = {
        str(row["follower_internal_user_id"]): int(row["c"])
        for row in conn.execute(
            f"SELECT follower_internal_user_id, COUNT(*) AS c FROM feed_author_follows "
            f"WHERE follower_internal_user_id IN ({internal_slots}) GROUP BY follower_internal_user_id",
            internal_ids,
        ).fetchall()
    }
    return {
        internal_id: _feed_author_profile_payload(
            by_internal.get(internal_id) or (by_legacy.get(str(legacy_id)) if legacy_id else None),
            internal_id,
            avatars.get(internal_id),
            followers.get(internal_id, 0),
            following.get(internal_id, 0),
        )
        for internal_id, legacy_id in author_keys
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
    return feed_sources.feed_source_history_payload(
        conn,
        image_id,
        load_children=safe_json_load,
        row_get=_row_get,
        role_label=_source_role_label,
    )


def _feed_generation_snapshot(conn: sqlite3.Connection, image: sqlite3.Row) -> dict[str, Any]:
    return feed_presentation.feed_generation_snapshot(
        conn,
        image,
        load_settings=safe_json_load,
        row_get=_row_get,
        model_info=_gallery_model_info,
        model_display_name=_user_model_name,
        aspect_ratio=_feed_aspect_ratio,
        public_params=_gallery_public_params,
        source_history=_feed_source_history_payload,
        token_cost=_public_token_cost,
        media_file_size=_media_file_size_from_url,
    )


def backfill_feed_generation_snapshots() -> int:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT p.id AS publication_id, i.*
            FROM feed_publications p
            JOIN images i ON i.id = p.image_id
            WHERE p.generation_snapshot_json IS NULL OR p.generation_snapshot_json = ''
            """
        ).fetchall()
        for row in rows:
            snapshot = _feed_generation_snapshot(conn, row)
            conn.execute(
                """
                UPDATE feed_publications
                SET generation_snapshot_json = ?, category = COALESCE(NULLIF(category, ''), 'other'),
                    tags_json = COALESCE(NULLIF(tags_json, ''), '[]')
                WHERE id = ?
                """,
                (json.dumps(snapshot, ensure_ascii=False), row["publication_id"]),
            )
    return len(rows)


def _feed_aspect_ratio(width: int, height: int) -> str:
    if not width or not height:
        return "1:1"
    from math import gcd

    g = gcd(int(width), int(height)) or 1
    return f"{int(width) // g}:{int(height) // g}"


def _feed_payload_context(
    conn: sqlite3.Connection,
    publications: list[sqlite3.Row],
    viewer_internal_user_id: str | None,
) -> dict[str, Any]:
    publication_ids = [str(row["id"]) for row in publications]
    image_ids = [str(row["image_id"]) for row in publications if _row_get(row, "image_id")]
    publication_slots = ",".join("?" for _ in publication_ids)
    image_slots = ",".join("?" for _ in image_ids)
    images: dict[str, sqlite3.Row] = {}
    reaction_counts: dict[str, dict[str, int]] = {}
    viewer_kinds: dict[str, set[str]] = {}
    if image_ids:
        images = {
            str(row["id"]): row
            for row in conn.execute(
                f"SELECT id, url, thumbnail_url, width, height, prompt_original, settings_json, "
                f"provider, mode, created_at FROM images WHERE id IN ({image_slots})",
                image_ids,
            ).fetchall()
        }
    if publication_ids:
        for row in conn.execute(
            f"SELECT publication_id, kind, COUNT(*) AS c FROM feed_reactions "
            f"WHERE publication_id IN ({publication_slots}) GROUP BY publication_id, kind",
            publication_ids,
        ).fetchall():
            reaction_counts.setdefault(str(row["publication_id"]), {})[str(row["kind"])] = int(row["c"])
        if viewer_internal_user_id:
            for row in conn.execute(
                f"SELECT publication_id, kind FROM feed_reactions "
                f"WHERE internal_user_id = ? AND publication_id IN ({publication_slots})",
                (viewer_internal_user_id, *publication_ids),
            ).fetchall():
                viewer_kinds.setdefault(str(row["publication_id"]), set()).add(str(row["kind"]))
    author_keys = {
        (str(row["internal_user_id"]), _row_get(row, "legacy_user_id"))
        for row in publications
    }
    author_profiles = _feed_author_profiles(conn, author_keys)
    followed_authors: set[str] = set()
    viewer_role: str | None = None
    if viewer_internal_user_id:
        followed_authors = {
            str(row["author_internal_user_id"])
            for row in conn.execute(
                "SELECT author_internal_user_id FROM feed_author_follows WHERE follower_internal_user_id = ?",
                (viewer_internal_user_id,),
            ).fetchall()
        }
        viewer_row = conn.execute(
            "SELECT role FROM users WHERE internal_user_id = ?",
            (viewer_internal_user_id,),
        ).fetchone()
        viewer_role = _row_get(viewer_row, "role")
    challenges = {
        category: _feed_challenge_payload(conn, category)
        for category in {_row_get(row, "category") for row in publications if _row_get(row, "category")}
    }
    return {
        "images": images,
        "reaction_counts": reaction_counts,
        "viewer_kinds": viewer_kinds,
        "author_profiles": author_profiles,
        "followed_authors": followed_authors,
        "viewer_role": viewer_role,
        "challenges": challenges,
        "source_histories": {},
    }


def _feed_item_payload(
    conn: sqlite3.Connection,
    pub: sqlite3.Row,
    viewer_internal_user_id: str | None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or {}
    media_type = str(_row_get(pub, "media_type") or "image")
    image_id = _row_get(pub, "image_id")
    image = context.get("images", {}).get(str(image_id)) if image_id else None
    if image is None and image_id:
        image = conn.execute(
            "SELECT id, url, thumbnail_url, width, height, prompt_original, settings_json, provider, mode, created_at "
            "FROM images WHERE id = ?",
            (image_id,),
        ).fetchone()
    settings: dict[str, Any] = {}
    if image is not None:
        try:
            settings = json.loads(image["settings_json"] or "{}")
        except (TypeError, ValueError):
            settings = {}
    snapshot = safe_json_load(_row_get(pub, "generation_snapshot_json")) or {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    visibility = pub["prompt_visibility"]
    raw_prompt = str(snapshot.get("prompt") or _row_get(image, "prompt_original") or "").strip()
    if visibility == "open":
        prompt: str | None = raw_prompt or None
    elif visibility == "partial":
        prompt = (raw_prompt[:FEED_PARTIAL_PROMPT_CHARS] + "…") if len(raw_prompt) > FEED_PARTIAL_PROMPT_CHARS else (raw_prompt or None)
    else:
        prompt = None
    counts = context.get("reaction_counts", {}).get(str(pub["id"]))
    if counts is None:
        counts = {
            r["kind"]: r["c"]
            for r in conn.execute(
                "SELECT kind, COUNT(*) AS c FROM feed_reactions WHERE publication_id = ? GROUP BY kind",
                (pub["id"],),
            ).fetchall()
        }
    viewer_kinds: set[str] = context.get("viewer_kinds", {}).get(str(pub["id"]), set())
    is_followed_by_me = str(pub["internal_user_id"]) in context.get("followed_authors", set())
    viewer_role: str | None = context.get("viewer_role")
    if viewer_internal_user_id and not context:
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
    width = int(snapshot.get("width") or _row_get(image, "width") or 0)
    height = int(snapshot.get("height") or _row_get(image, "height") or 0)
    media_ready = bool(_row_get(pub, "feed_thumb_name") and _row_get(pub, "feed_large_name") and _row_get(pub, "media_ready_at"))
    native_aspect_ratio = _row_get(pub, "native_aspect_ratio") or _feed_aspect_ratio(width, height)
    source_type = _row_get(pub, "source_type") or _feed_source_type(snapshot.get("mode") or _row_get(image, "mode"))
    is_mine = viewer_internal_user_id == pub["internal_user_id"]
    viewer_is_admin = viewer_role == "admin"
    author_profile = context.get("author_profiles", {}).get(str(pub["internal_user_id"]))
    if author_profile is None:
        author_profile = _feed_author_profile(conn, pub["internal_user_id"], pub["legacy_user_id"])
    category = _row_get(pub, "category")
    challenge = context.get("challenges", {}).get(category) if category else None
    if category and category not in context.get("challenges", {}):
        challenge = _feed_challenge_payload(conn, category)
    source_histories = context.setdefault("source_histories", {})
    source_history = snapshot.get("sourceHistory")
    if not source_history and image_id:
        if image_id not in source_histories:
            source_histories[image_id] = _feed_source_history_payload(conn, image_id)
        source_history = source_histories[image_id]
    if not source_history and media_type == "video":
        source_history = feed_presentation.video_source_history(snapshot.get("mode"))
    source_history = source_history or []
    public_model_info, snapshot_generation_params = gallery_presentation.sanitize_snapshot_model_presentation(snapshot, _gallery_model_info(settings, _row_get(image, "provider")))
    stored_source_label = _row_get(pub, "source_label")
    if media_type == "video" and stored_source_label == "Видео":
        stored_source_label = None
    return {
        "id": pub["id"],
        "media_type": media_type,
        "image_id": image_id,
        "video_id": _row_get(pub, "video_id"),
        "status": _row_get(pub, "status"),
        "feed_url": f"/feed?tab=new#work-{pub['id']}" if _feed_publication_ready(pub) else None,
        "moderation_status": _row_get(pub, "moderation_status") or "approved",
        "moderation_reason": _row_get(pub, "moderation_reason"),
        "image_url": f"/api/feed/media/{pub['id']}?variant=large",
        "thumbnail_url": f"/api/feed/media/{pub['id']}?variant=thumb",
        "video_preview_url": f"/api/feed/video/{pub['id']}?variant=preview" if media_type == "video" else None,
        "video_url": f"/api/feed/video/{pub['id']}?variant=full" if media_type == "video" else None,
        "duration_ms": int(_row_get(pub, "duration_ms") or snapshot.get("durationMs") or 0),
        "has_audio": bool(_row_get(pub, "has_audio")) if media_type == "video" else False,
        "media_status": "ready" if media_ready else "missing",
        "user_id": pub["internal_user_id"],
        "author": author_profile,
        "author_name": author_profile["displayName"],
        "title": pub["title"],
        "description": pub["description"],
        "prompt": prompt,
        "prompt_visibility": visibility,
        "allow_recreate": bool(pub["allow_recreate"]),
        "style": snapshot.get("style") or settings.get("styleName") or None,
        "model": snapshot.get("model") or _user_model_name(settings.get("modelProfile") or _row_get(image, "provider")),
        "model_info": public_model_info,
        "mode": snapshot.get("mode") or _row_get(image, "mode"),
        "aspect_ratio": native_aspect_ratio,
        "native_aspect_ratio": native_aspect_ratio,
        "orientation": _row_get(pub, "orientation") or _feed_orientation(width, height),
        "source_type": source_type,
        "source_label": stored_source_label or _feed_source_label(source_type),
        "display_policy": _row_get(pub, "display_policy") or FEED_DISPLAY_POLICY,
        "remix_policy": _row_get(pub, "remix_policy") or ("allowed" if bool(pub["allow_recreate"]) else "disabled"),
        "category": _row_get(pub, "category"),
        "tags": safe_json_load(_row_get(pub, "tags_json")) or [],
        "challenge": challenge,
        "source_history": source_history,
        "resolution": f"{width}×{height}" if width and height else None,
        "generation_params": snapshot_generation_params or _gallery_public_params(
            image_id=image_id,
            mode=_row_get(image, "mode"),
            provider=_row_get(image, "provider"),
            width=width,
            height=height,
            url=_row_get(image, "url"),
            created_at=_row_get(image, "created_at"),
            settings=settings,
        ),
        "token_cost": snapshot.get("tokenCost") if "tokenCost" in snapshot else _public_token_cost(settings),
        "generation_time_ms": snapshot.get("generationTimeMs") if "generationTimeMs" in snapshot else settings.get("generationTimeMs"),
        "file_size_bytes": snapshot.get("fileSizeBytes") if "fileSizeBytes" in snapshot else _media_file_size_from_url(_row_get(image, "url")),
        "seed": snapshot.get("seed") if "seed" in snapshot else settings.get("seed"),
        "created_at": pub["created_at"],
        "view_count": int(_row_get(pub, "view_count") or 0),
        "metric_origin": _row_get(pub, "metric_origin") or "organic",
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

FEED_CURSOR_VERSION = 1
FEED_VIEW_WINDOW = timedelta(hours=6)
FEED_VIEW_RETENTION = timedelta(days=90)
FEED_ENGAGEMENT_RETENTION = timedelta(days=90)
FEED_ENGAGEMENT_EVENT_TYPES = {
    "impression",
    "detail_open",
    "dwell",
    "remix_start",
    "remix_completion",
    "creation_entry",
    "video_play",
    "qualified_video_view",
    "video_completion",
}
FEED_PUBLICATION_EVENT_TYPES = FEED_ENGAGEMENT_EVENT_TYPES - {"creation_entry"}
FEED_SEARCH_MAX_CHARS = 120


def _feed_viewer_key(request: Request, viewer_internal_user_id: str | None) -> str:
    if viewer_internal_user_id:
        raw = f"user:{viewer_internal_user_id}"
    else:
        installation_id = str(request.headers.get("x-installation-id") or "").strip()
        if installation_id and len(installation_id) <= 128 and re.fullmatch(r"[A-Za-z0-9._:-]+", installation_id):
            raw = f"installation:{installation_id}"
        else:
            client_host = request.client.host if request.client else "unknown"
            user_agent = str(request.headers.get("user-agent") or "")[:240]
            raw = f"guest:{client_host}:{user_agent}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _encode_feed_cursor(payload: dict[str, Any]) -> str:
    data = {"v": FEED_CURSOR_VERSION, **payload}
    return base64.urlsafe_b64encode(
        json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")


def _decode_feed_cursor(
    cursor: str | None,
    *,
    feed_type: str,
    query: str,
    signal: str,
) -> dict[str, Any] | None:
    if not cursor:
        return None
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "invalid feed cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") != FEED_CURSOR_VERSION:
        raise HTTPException(400, "invalid feed cursor")
    if payload.get("type") != feed_type or payload.get("q", "") != query or payload.get("signal", "all") != signal:
        raise HTTPException(400, "feed cursor does not match request")
    return payload


def _feed_subscription_unread_count(conn: sqlite3.Connection, viewer: str | None) -> int:
    if not viewer:
        return 0
    row = conn.execute(
        "SELECT last_read_at FROM feed_subscription_reads WHERE internal_user_id = ?",
        (viewer,),
    ).fetchone()
    last_read_at = _row_get(row, "last_read_at") or "1970-01-01T00:00:00+00:00"
    return int(conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM feed_publications p
        JOIN feed_author_follows f ON f.author_internal_user_id = p.internal_user_id
        WHERE f.follower_internal_user_id = ?
          AND p.status = 'published'
          AND p.media_ready_at IS NOT NULL
          AND p.feed_thumb_name IS NOT NULL
          AND p.feed_large_name IS NOT NULL
          AND p.created_at > ?
          AND p.internal_user_id != ?
        """,
        (viewer, last_read_at, viewer),
    ).fetchone()["c"])


def _feed_cursor_for_row(
    row: sqlite3.Row,
    *,
    feed_type: str,
    query: str,
    signal: str,
) -> str:
    payload: dict[str, Any] = {
        "type": feed_type,
        "q": query,
        "signal": signal,
        "created": str(_row_get(row, "created_at") or ""),
        "id": str(_row_get(row, "id") or ""),
    }
    if feed_type == "remix":
        payload["remix"] = int(_row_get(row, "recreate_count") or 0)
        payload["saves"] = int(_row_get(row, "save_count") or 0)
    elif feed_type in {"for_you", "top"}:
        payload["score"] = int(_row_get(row, "rank_score") or 0)
    return _encode_feed_cursor(payload)


def _feed_list_rows(
    conn: sqlite3.Connection,
    *,
    feed_type: str,
    viewer: str | None,
    viewer_key: str,
    limit: int,
    challenge_id: str | None,
    query: str,
    signal: str,
    cursor: dict[str, Any] | None,
) -> list[sqlite3.Row]:
    where = [
        "p.status = 'published'",
        "p.media_ready_at IS NOT NULL",
        "p.feed_thumb_name IS NOT NULL",
        "p.feed_large_name IS NOT NULL",
        "(? IS NULL OR NOT EXISTS (SELECT 1 FROM feed_reactions hidden "
        "WHERE hidden.publication_id = p.id AND hidden.internal_user_id = ? AND hidden.kind = 'hide'))",
    ]
    where_params: list[Any] = [viewer, viewer]
    joins = ""
    if feed_type == "following":
        if not viewer:
            return []
        joins += " JOIN feed_author_follows followed ON followed.author_internal_user_id = p.internal_user_id"
        where.append("followed.follower_internal_user_id = ?")
        where_params.append(viewer)
    if feed_type == "challenge":
        category = "challenge_moscow_2120"
        if challenge_id:
            challenge = conn.execute(
                "SELECT category FROM challenges WHERE id = ? AND status = 'active'",
                (challenge_id,),
            ).fetchone()
            category = _row_get(challenge, "category") or category
        where.append("p.category = ?")
        where_params.append(category)
    if query:
        search_value = f"%{query}%"
        where.append(
            "(p.title LIKE ? OR COALESCE(p.description, '') LIKE ? OR COALESCE(p.source_label, '') LIKE ? "
            "OR COALESCE(p.category, '') LIKE ? OR COALESCE(p.tags_json, '') LIKE ? "
            "OR EXISTS (SELECT 1 FROM users author_search WHERE "
            "(author_search.internal_user_id = p.internal_user_id OR author_search.id = p.legacy_user_id) "
            "AND (COALESCE(author_search.display_name, '') LIKE ? OR COALESCE(author_search.username, '') LIKE ? "
            "OR COALESCE(author_search.first_name, '') LIKE ?)))"
        )
        where_params.extend([search_value] * 8)
    if signal in {"liked", "saved"}:
        if not viewer:
            return []
        kind = "like" if signal == "liked" else "save"
        where.append(
            "EXISTS (SELECT 1 FROM feed_reactions selected_signal "
            "WHERE selected_signal.publication_id = p.id "
            "AND selected_signal.internal_user_id = ? AND selected_signal.kind = ?)"
        )
        where_params.extend([viewer, kind])
    elif signal == "remixable":
        where.append("p.allow_recreate = 1 AND COALESCE(p.remix_policy, 'allowed') != 'disabled'")

    score_sql = "0"
    score_params: list[Any] = []
    if feed_type == "for_you":
        score_sql = """
            CASE WHEN ? IS NOT NULL AND EXISTS (
                SELECT 1 FROM feed_author_follows preferred_author
                WHERE preferred_author.follower_internal_user_id = ?
                  AND preferred_author.author_internal_user_id = p.internal_user_id
            ) THEN 18 ELSE 0 END
          + CASE WHEN ? IS NOT NULL AND EXISTS (
                SELECT 1 FROM feed_reactions viewer_preference
                JOIN feed_publications preferred_publication ON preferred_publication.id = viewer_preference.publication_id
                WHERE viewer_preference.internal_user_id = ?
                  AND viewer_preference.kind IN ('like', 'save', 'recreate')
                  AND preferred_publication.id != p.id
                  AND ((preferred_publication.category IS NOT NULL AND preferred_publication.category = p.category)
                    OR (preferred_publication.source_type IS NOT NULL AND preferred_publication.source_type = p.source_type))
            ) THEN 7 ELSE 0 END
          + CASE WHEN p.created_at >= datetime('now', '-7 days') THEN 6
                 WHEN p.created_at >= datetime('now', '-30 days') THEN 3 ELSE 0 END
          + COALESCE(rt.recreate_count, 0) * 8
          + COALESCE(rt.save_count, 0) * 4
          + COALESCE(rt.like_count, 0)
          - CASE WHEN EXISTS (
                SELECT 1 FROM feed_view_events recent_view
                WHERE recent_view.publication_id = p.id AND recent_view.viewer_key = ?
                  AND recent_view.last_viewed_at >= ?
            ) THEN 12 ELSE 0 END
        """
        score_params = [viewer, viewer, viewer, viewer, viewer_key, (datetime.now(timezone.utc) - FEED_VIEW_WINDOW).isoformat()]
    elif feed_type == "top":
        score_sql = "COALESCE(rt.recreate_count, 0) * 8 + COALESCE(rt.save_count, 0) * 4 + COALESCE(rt.like_count, 0)"

    ranked_sql = f"""
        WITH reaction_totals AS (
            SELECT publication_id,
                   SUM(CASE WHEN kind = 'like' THEN 1 ELSE 0 END) AS like_count,
                   SUM(CASE WHEN kind = 'save' THEN 1 ELSE 0 END) AS save_count,
                   SUM(CASE WHEN kind = 'recreate' THEN 1 ELSE 0 END) AS recreate_count
            FROM feed_reactions GROUP BY publication_id
        ), ranked AS (
            SELECT p.*,
                   COALESCE(rt.like_count, 0) AS like_count,
                   COALESCE(rt.save_count, 0) AS save_count,
                   COALESCE(rt.recreate_count, 0) AS recreate_count,
                   ({score_sql}) AS rank_score
            FROM feed_publications p
            LEFT JOIN reaction_totals rt ON rt.publication_id = p.id
            {joins}
            WHERE {' AND '.join(where)}
        )
        SELECT * FROM ranked
    """
    params = [*score_params, *where_params]
    if feed_type == "remix":
        if cursor:
            ranked_sql += " WHERE (recreate_count < ? OR (recreate_count = ? AND (save_count < ? OR (save_count = ? AND (created_at < ? OR (created_at = ? AND id < ?))))))"
            params.extend([cursor["remix"], cursor["remix"], cursor["saves"], cursor["saves"], cursor["created"], cursor["created"], cursor["id"]])
        ranked_sql += " ORDER BY recreate_count DESC, save_count DESC, created_at DESC, id DESC"
    elif feed_type in {"for_you", "top"}:
        if cursor:
            ranked_sql += " WHERE (rank_score < ? OR (rank_score = ? AND (created_at < ? OR (created_at = ? AND id < ?))))"
            params.extend([cursor["score"], cursor["score"], cursor["created"], cursor["created"], cursor["id"]])
        ranked_sql += " ORDER BY rank_score DESC, created_at DESC, id DESC"
    else:
        if cursor:
            ranked_sql += " WHERE (created_at < ? OR (created_at = ? AND id < ?))"
            params.extend([cursor["created"], cursor["created"], cursor["id"]])
        ranked_sql += " ORDER BY created_at DESC, id DESC"
    ranked_sql += " LIMIT ?"
    params.append(limit + 1)
    return conn.execute(ranked_sql, params).fetchall()


@app.get("/api/feed")
async def feed_list(
    request: Request,
    type: str = "for_you",
    limit: int = 30,
    challenge_id: str | None = None,
    cursor: str | None = None,
    q: str | None = None,
    signal: str = "all",
) -> dict[str, Any]:
    aliases = {"all": "for_you", "new": "fresh"}
    feed_type = aliases.get(type, type)
    if feed_type not in {"for_you", "fresh", "top", "remix", "challenge", "following"}:
        feed_type = "for_you"
    limit = max(1, min(int(limit or 30), 60))
    query = str(q or "").strip()[:FEED_SEARCH_MAX_CHARS]
    signal = signal if signal in {"all", "liked", "saved", "remixable"} else "all"
    viewer = _feed_optional_viewer(request)
    viewer_key = _feed_viewer_key(request, viewer)
    cursor_payload = _decode_feed_cursor(
        cursor,
        feed_type=feed_type,
        query=query,
        signal=signal,
    )
    with db() as conn:
        rows = _feed_list_rows(
            conn,
            feed_type=feed_type,
            viewer=viewer,
            viewer_key=viewer_key,
            limit=limit,
            challenge_id=challenge_id,
            query=query,
            signal=signal,
            cursor=cursor_payload,
        )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        payload_context = _feed_payload_context(conn, page_rows, viewer)
        items = [_feed_item_payload(conn, pub, viewer, payload_context) for pub in page_rows]
        unread_count = _feed_subscription_unread_count(conn, viewer)
    return {
        "ok": True,
        "type": feed_type,
        "items": items,
        "nextCursor": _feed_cursor_for_row(
            page_rows[-1],
            feed_type=feed_type,
            query=query,
            signal=signal,
        ) if has_more and page_rows else None,
        "hasMore": has_more,
        "followingUnreadCount": unread_count,
    }


def _feed_video_publication_status_payload(publication: sqlite3.Row) -> dict[str, Any]:
    status = str(publication["status"] or "preparing")
    return {
        "id": publication["id"],
        "image_id": None,
        "video_id": publication["video_id"],
        "media_type": "video",
        "title": publication["title"],
        "status": status,
        "media_status": "ready" if status == "published" and publication["media_ready_at"] else status,
        "media_error": _row_get(publication, "media_error"),
        "feed_url": f"/feed?tab=new#work-{publication['id']}" if status == "published" else None,
    }


def _prepare_feed_video_publication(publication_id: str) -> None:
    assets: FeedVideoAssetInfo | None = None
    try:
        with db() as conn:
            publication = conn.execute(
                """
                SELECT p.*, v.width AS source_width, v.height AS source_height,
                       v.duration_seconds AS source_duration_seconds,
                       v.settings_json AS video_settings, v.deleted_at AS video_deleted_at,
                       j.status AS job_status, j.settings_json AS job_settings
                FROM feed_publications p
                JOIN videos v ON v.id = p.video_id
                JOIN jobs j ON j.id = v.job_id
                WHERE p.id = ? AND p.media_type = 'video' AND p.status = 'preparing'
                """,
                (publication_id,),
            ).fetchone()
        if publication is None:
            return
        if publication["video_deleted_at"] or publication["job_status"] != "completed":
            raise RuntimeError("Video source is no longer available")
        settings = safe_json_load(publication["job_settings"]) or safe_json_load(publication["video_settings"]) or {}
        source_name = str(settings.get("localFile") or "").strip()
        source_path = storage_resolve_under_root(MEDIA, source_name) if source_name else None
        if source_path is None or not source_path.is_file():
            raise FileNotFoundError("Video source file not found")
        assets = create_feed_video_assets(
            publication_id,
            source_path,
            width=int(publication["source_width"] or 0),
            height=int(publication["source_height"] or 0),
            duration_seconds=int(publication["source_duration_seconds"] or 0),
            has_audio=bool(settings.get("generateAudio")),
        )
        snapshot = safe_json_load(publication["generation_snapshot_json"]) or {}
        snapshot["fileSizeBytes"] = assets.full_bytes
        snapshot["publicVideoCodec"] = "h264"
        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            updated = conn.execute(
                """
                UPDATE feed_publications SET
                    status = 'published', feed_thumb_name = ?, feed_large_name = ?,
                    feed_thumb_width = ?, feed_thumb_height = ?, feed_thumb_bytes = ?,
                    feed_large_width = ?, feed_large_height = ?, feed_large_bytes = ?,
                    video_poster_name = ?, video_poster_width = ?, video_poster_height = ?,
                    video_poster_bytes = ?, video_preview_name = ?, video_preview_bytes = ?,
                    video_full_name = ?, video_full_bytes = ?, duration_ms = ?, has_audio = ?,
                    media_ready_at = ?, media_error = NULL, generation_snapshot_json = ?, updated_at = ?
                WHERE id = ? AND status = 'preparing'
                """,
                (
                    assets.poster_name, assets.poster_name,
                    assets.poster_width, assets.poster_height, assets.poster_bytes,
                    assets.poster_width, assets.poster_height, assets.poster_bytes,
                    assets.poster_name, assets.poster_width, assets.poster_height, assets.poster_bytes,
                    assets.preview_name, assets.preview_bytes, assets.full_name, assets.full_bytes,
                    assets.duration_ms, int(assets.has_audio), now,
                    json.dumps(snapshot, ensure_ascii=False), now, publication_id,
                ),
            )
            if updated.rowcount == 1:
                enqueue_configured_social_deliveries(conn, publication_id)
        if updated.rowcount != 1:
            for media_name in {assets.poster_name, assets.preview_name, assets.full_name}:
                _delete_media_rel(media_name)
    except Exception as exc:
        if assets is not None:
            for media_name in {assets.poster_name, assets.preview_name, assets.full_name}:
                _delete_media_rel(media_name)
        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            conn.execute(
                """
                UPDATE feed_publications
                SET status = 'failed', media_ready_at = NULL,
                    media_error = 'video_derivative_failed', updated_at = ?
                WHERE id = ? AND status = 'preparing'
                """,
                (now, publication_id),
            )
        print(f"feed video publication failed id={short_public_id(publication_id)} error={type(exc).__name__}")


async def feed_video_publication_worker() -> None:
    queue_ref = feed_video_publication_queue
    if queue_ref is None:
        return
    while True:
        publication_id = await queue_ref.get()
        try:
            if publication_id is None:
                return
            await asyncio.to_thread(_prepare_feed_video_publication, publication_id)
        finally:
            queue_ref.task_done()


def start_feed_video_publication_worker() -> int:
    global feed_video_publication_queue, feed_video_publication_worker_task, feed_video_publication_worker_stopping
    if feed_video_publication_worker_task is not None and not feed_video_publication_worker_task.done():
        return 0
    feed_video_publication_worker_stopping = False
    feed_video_publication_queue = asyncio.Queue()
    feed_video_publication_worker_task = asyncio.create_task(feed_video_publication_worker())
    if not FEED_VIDEO_PUBLICATION_ENABLED:
        return 0
    with db() as conn:
        pending_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM feed_publications WHERE media_type = 'video' AND status = 'preparing' ORDER BY created_at"
            ).fetchall()
        ]
    for publication_id in pending_ids:
        feed_video_publication_queue.put_nowait(publication_id)
    return len(pending_ids)


async def stop_feed_video_publication_worker() -> None:
    global feed_video_publication_queue, feed_video_publication_worker_task, feed_video_publication_worker_stopping
    task = feed_video_publication_worker_task
    queue_ref = feed_video_publication_queue
    if task is None:
        feed_video_publication_queue = None
        feed_video_publication_worker_stopping = False
        return
    feed_video_publication_worker_stopping = True
    try:
        if not task.done() and queue_ref is not None:
            while True:
                try:
                    queue_ref.get_nowait()
                except asyncio.QueueEmpty:
                    break
                else:
                    queue_ref.task_done()
            await queue_ref.put(None)
        await task
    finally:
        feed_video_publication_worker_task = None
        feed_video_publication_queue = None
        feed_video_publication_worker_stopping = False


async def enqueue_feed_video_publication(publication_id: str) -> None:
    if feed_video_publication_worker_stopping:
        raise RuntimeError("Feed video publication worker is stopping")
    if feed_video_publication_worker_task is None or feed_video_publication_worker_task.done() or feed_video_publication_queue is None:
        start_feed_video_publication_worker()
    if feed_video_publication_queue is None:
        raise RuntimeError("Feed video publication worker is unavailable")
    await feed_video_publication_queue.put(publication_id)


async def _publish_feed_video(
    *,
    video_id: str,
    title: str,
    description: str | None,
    visibility: str,
    category: str,
    tags: list[str],
    user: dict[str, Any],
    request: Request,
) -> dict[str, Any] | JSONResponse:
    if not FEED_VIDEO_PUBLICATION_ENABLED:
        raise HTTPException(503, "Video publication is not enabled")
    with db() as conn:
        video = conn.execute(
            """
            SELECT v.*, j.status AS job_status, j.settings_json AS job_settings
            FROM videos v
            JOIN jobs j ON j.id = v.job_id
            WHERE v.id = ? AND v.deleted_at IS NULL
            """,
            (video_id,),
        ).fetchone()
    if video is None or video["user_id"] != user["legacy_user_id"]:
        with db() as conn:
            record_security_event(
                conn,
                "feed_video_publish_denied",
                internal_user_id=user["internal_user_id"],
                session_id=user.get("session_id"),
                request=request,
            )
        raise HTTPException(404, "Video not found")
    if video["job_status"] != "completed":
        raise HTTPException(400, "Only completed generated videos can be published")
    settings = safe_json_load(video["job_settings"]) or safe_json_load(video["settings_json"]) or {}
    source_name = str(settings.get("localFile") or "").strip()
    source_path = storage_resolve_under_root(MEDIA, source_name) if source_name else None
    if source_path is None or not source_path.is_file():
        raise HTTPException(404, "Video file not found")

    now = datetime.now(timezone.utc).isoformat()
    video_mode = str(video["mode"] or "text_to_video")
    source_label = _feed_source_label(video_mode)
    snapshot = {
        "prompt": video["prompt_original"] or "",
        "mode": video["mode"],
        "provider": video["provider"],
        "model": settings.get("openrouterModel") or video["provider"],
        "width": int(video["width"] or 0),
        "height": int(video["height"] or 0),
        "durationMs": max(0, int(video["duration_seconds"] or 0) * 1000),
        "fileSizeBytes": source_path.stat().st_size,
        "generationParams": [
            {"label": "Способ", "value": source_label},
            {"label": "Модель", "value": settings.get("openrouterModel") or video["provider"]},
            {"label": "Формат", "value": video["aspect_ratio"] or _feed_aspect_ratio(int(video["width"] or 0), int(video["height"] or 0))},
            {"label": "Длительность", "value": f"{int(video['duration_seconds'] or 0)} сек."},
            {"label": "Разрешение", "value": settings.get("resolution") or f"{video['width']}×{video['height']}"},
            {"label": "Звук", "value": "Есть" if settings.get("generateAudio") else "Без звука"},
        ],
        "sourceHistory": settings.get("sourceHistory") if isinstance(settings.get("sourceHistory"), list) else feed_presentation.video_source_history(video_mode),
    }
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM feed_publications WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        if existing is not None and _feed_publication_ready(existing):
            return {"ok": True, "publication": _feed_item_payload(conn, existing, user["internal_user_id"]), "moderation": "approved"}
        pub_id = existing["id"] if existing else uuid.uuid4().hex
        values = {
            "id": pub_id,
            "video_id": video_id,
            "internal_user_id": user["internal_user_id"],
            "legacy_user_id": user["legacy_user_id"],
            "title": title,
            "description": description,
            "prompt_visibility": visibility,
            "created_at": now,
            "duration_ms": max(0, int(video["duration_seconds"] or 0) * 1000),
            "has_audio": int(bool(settings.get("generateAudio"))),
            "native_aspect_ratio": _feed_aspect_ratio(int(video["width"] or 0), int(video["height"] or 0)),
            "orientation": _feed_orientation(int(video["width"] or 0), int(video["height"] or 0)),
            "category": category,
            "tags_json": json.dumps(tags, ensure_ascii=False),
            "snapshot_json": json.dumps(snapshot, ensure_ascii=False),
            "display_policy": FEED_DISPLAY_POLICY,
            "source_job_id": video["job_id"],
            "source_type": video_mode,
            "source_label": source_label,
        }
        if existing:
            conn.execute(
                """
                UPDATE feed_publications SET
                    image_id = NULL, video_id = :video_id, media_type = 'video', title = :title,
                    description = :description, prompt_visibility = :prompt_visibility,
                    allow_recreate = 0, status = 'preparing', feed_thumb_name = NULL,
                    feed_large_name = NULL, feed_thumb_width = NULL,
                    feed_thumb_height = NULL, feed_thumb_bytes = NULL,
                    feed_large_width = NULL, feed_large_height = NULL,
                    feed_large_bytes = NULL, video_poster_name = NULL,
                    video_poster_width = NULL, video_poster_height = NULL,
                    video_poster_bytes = NULL, video_preview_name = NULL,
                    video_preview_bytes = NULL, video_full_name = NULL,
                    video_full_bytes = NULL, duration_ms = :duration_ms, has_audio = :has_audio,
                    media_ready_at = NULL, media_error = NULL,
                    native_aspect_ratio = :native_aspect_ratio, orientation = :orientation,
                    source_type = :source_type, source_label = :source_label, display_policy = :display_policy,
                    remix_policy = 'disabled', category = :category, tags_json = :tags_json,
                    generation_snapshot_json = :snapshot_json, moderation_status = 'approved',
                    moderation_reason = NULL, moderated_at = :created_at,
                    moderated_by_internal_user_id = NULL, source_job_id = :source_job_id,
                    updated_at = :created_at
                WHERE id = :id
                """,
                values,
            )
        else:
            conn.execute(
                """
                INSERT INTO feed_publications (
                    id,image_id,video_id,media_type,internal_user_id,legacy_user_id,title,description,
                    prompt_visibility,allow_recreate,status,created_at,media_ready_at,native_aspect_ratio,orientation,source_type,source_label,
                    display_policy,remix_policy,category,tags_json,generation_snapshot_json,moderation_status,
                    moderated_at,source_job_id,updated_at,duration_ms,has_audio
                ) VALUES (
                    :id,NULL,:video_id,'video',:internal_user_id,:legacy_user_id,:title,:description,
                    :prompt_visibility,0,'preparing',:created_at,NULL,:native_aspect_ratio,:orientation,:source_type,:source_label,
                    :display_policy,'disabled',:category,:tags_json,:snapshot_json,'approved',
                    :created_at,:source_job_id,:created_at,:duration_ms,:has_audio
                )
                """,
                values,
            )
        pub = conn.execute("SELECT * FROM feed_publications WHERE id = ?", (pub_id,)).fetchone()
    await enqueue_feed_video_publication(pub_id)
    return JSONResponse(
        status_code=202,
        content={"ok": True, "publication": _feed_video_publication_status_payload(pub), "moderation": "approved"},
    )


@app.post("/api/feed/publications")
async def feed_publish(payload: dict[str, Any], request: Request) -> Any:
    user = require_trusted_user(request)
    image_id = str(payload.get("imageId") or "").strip()
    video_id = str(payload.get("videoId") or "").strip()
    title = str(payload.get("title") or "").strip()
    description = str(payload.get("description") or "").strip() or None
    visibility = str(payload.get("promptVisibility") or "open").strip()
    allow_recreate = bool(payload.get("allowRecreate", True))
    category = str(payload.get("category") or "other").strip().lower()
    raw_tags = payload.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.split(",")
    tags = list(dict.fromkeys(str(tag).strip().lstrip("#")[:24] for tag in raw_tags if str(tag).strip()))[:8]
    if not image_id and not video_id:
        raise HTTPException(400, "imageId or videoId required")
    if image_id and video_id:
        raise HTTPException(400, "Choose exactly one media item")
    if not title:
        raise HTTPException(400, "title required")
    if len(title) > 120:
        raise HTTPException(400, "title too long")
    if description and len(description) > 700:
        raise HTTPException(400, "description too long")
    if visibility not in FEED_PROMPT_VISIBILITIES:
        raise HTTPException(400, "invalid promptVisibility")
    if category not in FEED_PUBLICATION_CATEGORIES:
        raise HTTPException(400, "invalid category")
    if video_id:
        return await _publish_feed_video(
            video_id=video_id,
            title=title,
            description=description,
            visibility=visibility,
            category=category,
            tags=tags,
            user=user,
            request=request,
        )
    with db() as conn:
        image = conn.execute(
            """
            SELECT i.id, i.user_id, i.job_id, i.url, i.width, i.height, i.mode, i.provider,
                   i.prompt_original, i.settings_json, i.created_at,
                   j.status AS job_status, j.result_image_id AS job_result_image_id
            FROM images i
            LEFT JOIN jobs j ON j.id = i.job_id
            WHERE i.id = ? AND i.deleted_at IS NULL
            """,
            (image_id,),
        ).fetchone()
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
    decision = feed_policy.publication_decision(
        _row_get(image, "mode"),
        has_verified_generation=bool(
            _row_get(image, "job_id")
            and _row_get(image, "job_status") == "completed"
            and _row_get(image, "job_result_image_id") == image_id
        ),
    )
    if decision.blocked:
        with db() as conn:
            record_security_event(
                conn,
                "feed_publish_policy_denied",
                internal_user_id=user["internal_user_id"],
                session_id=user.get("session_id"),
                request=request,
                details={"image_id": short_public_id(image_id), "reason": decision.reason},
            )
        if str(decision.reason or "").startswith("source_mode_not_publishable"):
            raise HTTPException(400, "This generation mode cannot be published to the feed yet")
        raise HTTPException(400, "Only verified generated results can be published")
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
        publication_status = "pending_review" if decision.requires_review else "published"
        moderation_status = "pending_review" if decision.requires_review else "approved"
        remix_policy = "allowed" if allow_recreate else "disabled"
        generation_snapshot = _feed_generation_snapshot(conn, image)
        tags_json = json.dumps(tags, ensure_ascii=False)
        snapshot_json = json.dumps(generation_snapshot, ensure_ascii=False)
        if existing:
            conn.execute(
                "UPDATE feed_publications SET title = ?, description = ?, prompt_visibility = ?, "
                "allow_recreate = ?, status = ?, feed_thumb_name = ?, feed_large_name = ?, "
                "feed_thumb_width = ?, feed_thumb_height = ?, feed_thumb_bytes = ?, "
                "feed_large_width = ?, feed_large_height = ?, feed_large_bytes = ?, "
                "media_ready_at = ?, media_error = NULL, native_aspect_ratio = ?, orientation = ?, "
                "source_type = ?, source_label = ?, display_policy = ?, remix_policy = ?, category = ?, "
                "tags_json = ?, generation_snapshot_json = ?, moderation_status = ?, moderation_reason = ?, "
                "moderated_at = ?, moderated_by_internal_user_id = NULL, source_job_id = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    title,
                    description,
                    visibility,
                    int(allow_recreate),
                    publication_status,
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
                    category,
                    tags_json,
                    snapshot_json,
                    moderation_status,
                    decision.reason,
                    now if moderation_status == "approved" else None,
                    _row_get(image, "job_id"),
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
                "native_aspect_ratio, orientation, source_type, source_label, display_policy, remix_policy, category, "
                "tags_json, generation_snapshot_json, moderation_status, moderation_reason, moderated_at, "
                "moderated_by_internal_user_id, source_job_id, updated_at) "
                "VALUES (:id, :image_id, :internal_user_id, :legacy_user_id, :title, :description, "
                ":prompt_visibility, :allow_recreate, :status, :created_at, :feed_thumb_name, :feed_large_name, "
                ":feed_thumb_width, :feed_thumb_height, :feed_thumb_bytes, :feed_large_width, :feed_large_height, "
                ":feed_large_bytes, :media_ready_at, NULL, :native_aspect_ratio, :orientation, :source_type, "
                ":source_label, :display_policy, :remix_policy, :category, :tags_json, :snapshot_json, "
                ":moderation_status, :moderation_reason, :moderated_at, NULL, :source_job_id, :updated_at)",
                {
                    "id": pub_id,
                    "image_id": image_id,
                    "internal_user_id": user["internal_user_id"],
                    "legacy_user_id": user["legacy_user_id"],
                    "title": title,
                    "description": description,
                    "prompt_visibility": visibility,
                    "allow_recreate": int(allow_recreate),
                    "status": publication_status,
                    "created_at": now,
                    "feed_thumb_name": assets.feed_thumb_name,
                    "feed_large_name": assets.feed_large_name,
                    "feed_thumb_width": assets.feed_thumb_width,
                    "feed_thumb_height": assets.feed_thumb_height,
                    "feed_thumb_bytes": assets.feed_thumb_bytes,
                    "feed_large_width": assets.feed_large_width,
                    "feed_large_height": assets.feed_large_height,
                    "feed_large_bytes": assets.feed_large_bytes,
                    "media_ready_at": now,
                    "native_aspect_ratio": assets.native_aspect_ratio,
                    "orientation": assets.orientation,
                    "source_type": source_type,
                    "source_label": source_label,
                    "display_policy": FEED_DISPLAY_POLICY,
                    "remix_policy": remix_policy,
                    "category": category,
                    "tags_json": tags_json,
                    "snapshot_json": snapshot_json,
                    "moderation_status": moderation_status,
                    "moderation_reason": decision.reason,
                    "moderated_at": now if moderation_status == "approved" else None,
                    "source_job_id": _row_get(image, "job_id"),
                    "updated_at": now,
                },
            )
        pub = conn.execute("SELECT * FROM feed_publications WHERE id = ?", (pub_id,)).fetchone()
        item = _feed_item_payload(conn, pub, user["internal_user_id"])
        if publication_status == "published":
            enqueue_configured_social_deliveries(conn, pub_id)
    return {"ok": True, "publication": item, "moderation": moderation_status}


@app.get("/api/feed/publications/{publication_id}/status")
async def feed_publication_status(publication_id: str, request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    with db() as conn:
        publication = conn.execute(
            "SELECT * FROM feed_publications WHERE id = ? AND internal_user_id = ?",
            (publication_id, user["internal_user_id"]),
        ).fetchone()
        if publication is None:
            raise HTTPException(404, "Publication not found")
        if _feed_publication_ready(publication):
            return {
                "ok": True,
                "publication": _feed_item_payload(conn, publication, user["internal_user_id"]),
            }
        if publication["media_type"] == "video":
            return {"ok": True, "publication": _feed_video_publication_status_payload(publication)}
        return {
            "ok": True,
            "publication": {
                "id": publication["id"],
                "image_id": publication["image_id"],
                "video_id": None,
                "media_type": "image",
                "title": publication["title"],
                "status": publication["status"],
                "media_status": publication["status"],
                "media_error": _row_get(publication, "media_error"),
            },
        }


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


def _feed_engagement_context(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"surface", "feed_type", "media_type", "source", "completion_percent"}
    result: dict[str, Any] = {}
    for key, raw in list(value.items())[:12]:
        key = str(key).strip().lower()
        if key not in allowed or isinstance(raw, (dict, list, tuple, set)):
            continue
        if isinstance(raw, str):
            result[key] = raw.strip()[:80]
        elif isinstance(raw, (bool, int, float)):
            result[key] = raw
    return result


@app.post("/api/feed/events")
async def feed_engagement_event(payload: FeedEngagementEventRequest, request: Request) -> dict[str, Any]:
    event_type = payload.event_type.strip().lower()
    if event_type not in FEED_ENGAGEMENT_EVENT_TYPES:
        raise HTTPException(422, "Unsupported feed event")
    publication_id = (payload.publication_id or "").strip() or None
    if event_type in FEED_PUBLICATION_EVENT_TYPES and publication_id is None:
        raise HTTPException(422, "publication_id is required")
    if event_type == "dwell" and payload.duration_ms is None:
        raise HTTPException(422, "duration_ms is required")

    viewer = _feed_optional_viewer(request)
    viewer_key = _feed_viewer_key(request, viewer)
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    dedupe_seconds = {"impression": 6 * 3600, "detail_open": 30 * 60, "creation_entry": 5 * 60}.get(event_type)
    if dedupe_seconds:
        bucket = int(now_dt.timestamp() // dedupe_seconds)
        raw_key = f"{viewer_key}:{publication_id or '-'}:{event_type}:{bucket}"
        event_id = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    else:
        event_id = uuid.uuid4().hex
    context = _feed_engagement_context(payload.context)

    with db() as conn:
        if publication_id is not None:
            exists = conn.execute(
                "SELECT 1 FROM feed_publications WHERE id = ? AND status = 'published'",
                (publication_id,),
            ).fetchone()
            if exists is None:
                raise HTTPException(404, "Publication not found")
        inserted = conn.execute(
            """
            INSERT OR IGNORE INTO feed_engagement_events
                (id, publication_id, viewer_key, event_type, duration_ms, context_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                publication_id,
                viewer_key,
                event_type,
                payload.duration_ms,
                json.dumps(context, ensure_ascii=False, separators=(",", ":")),
                now,
            ),
        ).rowcount > 0
        retention_cutoff = (now_dt - FEED_ENGAGEMENT_RETENTION).isoformat()
        conn.execute(
            "DELETE FROM feed_engagement_events WHERE rowid IN ("
            "SELECT rowid FROM feed_engagement_events WHERE created_at < ? LIMIT 200)",
            (retention_cutoff,),
        )
    return {"ok": True, "accepted": inserted, "eventType": event_type}


@app.post("/api/feed/publications/{publication_id}/view")
async def feed_publication_view(publication_id: str, request: Request) -> dict[str, Any]:
    viewer = _feed_optional_viewer(request)
    viewer_key = _feed_viewer_key(request, viewer)
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    cutoff = (now_dt - FEED_VIEW_WINDOW).isoformat()
    with db() as conn:
        pub = conn.execute(
            "SELECT * FROM feed_publications WHERE id = ? AND status = 'published'",
            (publication_id,),
        ).fetchone()
        if pub is None:
            raise HTTPException(404, "Publication not found")
        event = conn.execute(
            "SELECT last_viewed_at FROM feed_view_events WHERE publication_id = ? AND viewer_key = ?",
            (publication_id, viewer_key),
        ).fetchone()
        accepted = event is None or str(event["last_viewed_at"]) < cutoff
        if accepted:
            conn.execute(
                "UPDATE feed_publications SET view_count = COALESCE(view_count, 0) + 1, updated_at = ? WHERE id = ?",
                (now, publication_id),
            )
            conn.execute(
                """
                INSERT INTO feed_view_events
                    (publication_id, viewer_key, first_viewed_at, last_viewed_at, accepted_view_count)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(publication_id, viewer_key) DO UPDATE SET
                    last_viewed_at = excluded.last_viewed_at,
                    accepted_view_count = feed_view_events.accepted_view_count + 1
                """,
                (publication_id, viewer_key, now, now),
            )
            retention_cutoff = (now_dt - FEED_VIEW_RETENTION).isoformat()
            conn.execute(
                "DELETE FROM feed_view_events WHERE rowid IN ("
                "SELECT rowid FROM feed_view_events WHERE last_viewed_at < ? LIMIT 200)",
                (retention_cutoff,),
            )
        updated = conn.execute("SELECT * FROM feed_publications WHERE id = ?", (publication_id,)).fetchone()
        item = _feed_item_payload(conn, updated, viewer)
    return {"ok": True, "accepted": accepted, "windowHours": int(FEED_VIEW_WINDOW.total_seconds() // 3600), "publication": item}


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


@app.post("/api/feed/publications/{publication_id}/use-as")
async def feed_publication_use_as(publication_id: str, req: UseAsRequest, request: Request) -> dict[str, Any]:
    """Prepare a server-selected public feed image for a trusted editing workflow."""
    require_trusted_user(request)
    target = str(req.target or "").strip().lower()
    allowed_targets = {"image", "editor", "face_source", "face_target", "prompt"}
    if target not in allowed_targets:
        raise HTTPException(400, "Unsupported feed editing target")
    with db() as conn:
        publication = conn.execute(
            """
            SELECT * FROM feed_publications
            WHERE id = ?
              AND status = 'published'
              AND media_ready_at IS NOT NULL
              AND feed_thumb_name IS NOT NULL
              AND feed_large_name IS NOT NULL
            """,
            (publication_id,),
        ).fetchone()
        if publication is None:
            raise HTTPException(404, "Publication not found")
        item = _feed_item_payload(conn, publication, None)
    if item.get("media_type") == "video" and target != "prompt":
        raise HTTPException(400, "Video publications can only provide a prompt")
    return {
        "ok": True,
        "publicationId": publication_id,
        "target": target,
        "inputImage": None if item.get("media_type") == "video" else f"/api/feed/media/{publication_id}?variant=large",
        "prompt": item.get("prompt") if target in {"image", "editor", "prompt"} else None,
        "aspectRatio": item.get("native_aspect_ratio"),
        "source": "feed",
    }


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
        context = _feed_payload_context(conn, rows, viewer)
        items = [_feed_item_payload(conn, pub, viewer, context) for pub in rows]
        summary = conn.execute(
            """
            WITH reaction_totals AS (
                SELECT r.kind, COUNT(*) AS c
                FROM feed_reactions r
                JOIN feed_publications publication ON publication.id = r.publication_id
                WHERE publication.internal_user_id = ? AND publication.status = 'published'
                GROUP BY r.kind
            )
            SELECT
                (SELECT COUNT(*) FROM feed_publications WHERE internal_user_id = ? AND status = 'published') AS publications,
                (SELECT COALESCE(SUM(view_count), 0) FROM feed_publications WHERE internal_user_id = ? AND status = 'published') AS views,
                COALESCE((SELECT c FROM reaction_totals WHERE kind = 'like'), 0) AS likes,
                COALESCE((SELECT c FROM reaction_totals WHERE kind = 'save'), 0) AS saves,
                COALESCE((SELECT c FROM reaction_totals WHERE kind = 'recreate'), 0) AS remixes
            """,
            (author_id, author_id, author_id),
        ).fetchone()
    return {"ok": True, "authorId": author_id, "items": items, "summary": dict(summary)}


@app.post("/api/feed/following/read")
async def feed_following_mark_read(request: Request) -> dict[str, Any]:
    user = require_trusted_user(request)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO feed_subscription_reads (internal_user_id, last_read_at)
            VALUES (?, ?)
            ON CONFLICT(internal_user_id) DO UPDATE SET last_read_at = excluded.last_read_at
            """,
            (user["internal_user_id"], now),
        )
    return {"ok": True, "lastReadAt": now, "unreadCount": 0}


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
    with db() as conn:
        publication = conn.execute(
            "SELECT media_type, allow_recreate, remix_policy FROM feed_publications WHERE id = ? AND status = 'published'",
            (publication_id,),
        ).fetchone()
    if publication is None:
        raise HTTPException(404, "Publication not found")
    if publication["media_type"] != "image" or not publication["allow_recreate"] or publication["remix_policy"] == "disabled":
        raise HTTPException(400, "Publication cannot be remixed")
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
        if pub["media_type"] != "image" or not pub["allow_recreate"] or pub["remix_policy"] == "disabled":
            raise HTTPException(400, "Publication cannot be remixed")
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


@app.get("/api/admin/feed/moderation")
async def admin_feed_moderation_queue(request: Request, limit: int = 50) -> dict[str, Any]:
    require_trusted_admin(request)
    limit = max(1, min(int(limit or 50), 100))
    with db() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.image_id, p.internal_user_id, p.title, p.description, p.source_type,
                   p.source_label, p.moderation_status, p.moderation_reason, p.created_at,
                   COALESCE(u.display_name, u.first_name, 'Автор') AS author_name
            FROM feed_publications p
            LEFT JOIN users u ON u.internal_user_id = p.internal_user_id
            WHERE p.status = 'pending_review' AND p.moderation_status = 'pending_review'
            ORDER BY p.created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {
        "ok": True,
        "items": [
            {
                **dict(row),
                "review_image_url": f"/api/admin/feed/publications/{row['id']}/media",
            }
            for row in rows
        ],
    }


@app.get("/api/admin/feed/publications/{publication_id}/media")
async def admin_feed_moderation_media(publication_id: str, request: Request) -> FileResponse:
    require_trusted_admin(request)
    with db() as conn:
        publication = conn.execute(
            "SELECT feed_large_name FROM feed_publications WHERE id = ? AND status = 'pending_review'",
            (publication_id,),
        ).fetchone()
    if publication is None or not publication["feed_large_name"]:
        raise HTTPException(404, "Publication not found")
    try:
        path = storage_resolve_under_root(MEDIA, publication["feed_large_name"])
    except StoragePathError as exc:
        raise HTTPException(404, "Image file not found") from exc
    if not path.is_file():
        raise HTTPException(404, "Image file not found")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, no-store"})


@app.post("/api/admin/feed/publications/{publication_id}/moderate")
async def admin_moderate_feed_publication(
    publication_id: str,
    req: FeedModerationRequest,
    request: Request,
) -> dict[str, Any]:
    admin = require_trusted_admin(request)
    reason = req.reason.strip()
    now = datetime.now(timezone.utc).isoformat()
    rejected_media: list[str | None] = []
    with db() as conn:
        publication = conn.execute(
            "SELECT * FROM feed_publications WHERE id = ? AND status = 'pending_review'",
            (publication_id,),
        ).fetchone()
        if publication is None:
            raise HTTPException(404, "Publication not found")
        next_status = "published" if req.action == "approve" else "hidden"
        moderation_status = "approved" if req.action == "approve" else "rejected"
        conn.execute(
            """
            UPDATE feed_publications
            SET status = ?, moderation_status = ?, moderation_reason = ?, moderated_at = ?,
                moderated_by_internal_user_id = ?, media_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                next_status,
                moderation_status,
                reason,
                now,
                admin["internal_user_id"],
                None if req.action == "approve" else "moderation_rejected",
                now,
                publication_id,
            ),
        )
        if req.action == "reject":
            rejected_media = [
                publication["feed_thumb_name"],
                publication["feed_large_name"],
                _row_get(publication, "video_poster_name"),
                _row_get(publication, "video_preview_name"),
                _row_get(publication, "video_full_name"),
                *feed_downloads.video_download_names(publication_id),
            ]
            conn.execute(
                """
                UPDATE feed_publications
                SET feed_thumb_name = NULL,
                    feed_large_name = NULL,
                    video_poster_name = NULL,
                    video_preview_name = NULL,
                    video_full_name = NULL,
                    media_ready_at = NULL
                WHERE id = ?
                """,
                (publication_id,),
            )
        record_audit_log(
            conn,
            "moderate_feed_publication",
            actor_internal_user_id=admin["internal_user_id"],
            target_internal_user_id=publication["internal_user_id"],
            entity_type="feed_publication",
            entity_id=publication_id,
            before={"status": publication["status"], "moderation_status": publication["moderation_status"]},
            after={"status": next_status, "moderation_status": moderation_status, "reason": reason},
            request=request,
        )
    for media_name in rejected_media:
        _delete_media_rel(media_name)
    return {"ok": True, "publicationId": publication_id, "status": next_status, "moderation": moderation_status}


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
            SELECT id, image_id, video_id, media_type, internal_user_id, legacy_user_id, title, status,
                   feed_thumb_name, feed_large_name, video_poster_name, video_preview_name,
                   video_full_name, created_at
            FROM feed_publications
            WHERE id = ?
            """,
            (publication_id,),
        ).fetchone()
        if pub is None or pub["status"] not in {"published", "preparing", "failed"}:
            raise HTTPException(404, "Publication not found.")
        thumb_name = _row_get(pub, "feed_thumb_name")
        large_name = _row_get(pub, "feed_large_name")
        video_media_names = {_row_get(pub, "video_poster_name"), _row_get(pub, "video_preview_name"), _row_get(pub, "video_full_name"), *feed_downloads.video_download_names(publication_id)}
        remote_deletions = enqueue_social_deletions(conn, publication_id, now=now)
        conn.execute(
            """
            UPDATE feed_publications
            SET status = 'hidden',
                feed_thumb_name = NULL,
                feed_large_name = NULL,
                video_poster_name = NULL,
                video_preview_name = NULL,
                video_full_name = NULL,
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
    for media_name in {thumb_name, large_name, *video_media_names}:
        _delete_media_rel(media_name)
    return {
        "ok": True,
        "publicationId": short_public_id(publication_id),
        "status": "hidden",
        "deleted_at": now,
        "remoteDeletionsQueued": remote_deletions,
    }


@app.delete("/api/feed/publications/{publication_id}")
async def delete_own_feed_publication(publication_id: str, request: Request) -> dict[str, Any]:
    """Снять свою публикацию с публичной ленты, не удаляя исходник из галереи."""
    user = require_trusted_user(request)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        pub = conn.execute(
            """
            SELECT id, image_id, video_id, media_type, internal_user_id, legacy_user_id, title, status,
                   feed_thumb_name, feed_large_name, video_poster_name, video_preview_name,
                   video_full_name, created_at
            FROM feed_publications
            WHERE id = ?
            """,
            (publication_id,),
        ).fetchone()
        if pub is None or pub["status"] not in {"published", "preparing", "failed"}:
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
        video_media_names = {_row_get(pub, "video_poster_name"), _row_get(pub, "video_preview_name"), _row_get(pub, "video_full_name"), *feed_downloads.video_download_names(publication_id)}
        remote_deletions = enqueue_social_deletions(conn, publication_id, now=now)
        conn.execute(
            """
            UPDATE feed_publications
            SET status = 'hidden',
                feed_thumb_name = NULL,
                feed_large_name = NULL,
                video_poster_name = NULL,
                video_preview_name = NULL,
                video_full_name = NULL,
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
    for media_name in {thumb_name, large_name, *video_media_names}:
        _delete_media_rel(media_name)
    return {
        "ok": True,
        "publicationId": short_public_id(publication_id),
        "status": "hidden",
        "deleted_at": now,
        "remoteDeletionsQueued": remote_deletions,
    }


@app.get("/api/feed/media/{publication_id}")
async def feed_media(publication_id: str, request: Request, variant: str = "large", thumb: int = 0) -> FileResponse:
    """Файл ОПУБЛИКОВАННОЙ работы. Доступен любому (публичная лента) — но только
    через публикацию: приватный /api/media остаётся закрытым как был."""
    try:
        path = storage_resolve_feed_media(
            _public_media_runtime(),
            MEDIA,
            publication_id,
            variant=variant,
            thumb=thumb,
        )
    except PublicMediaAccessError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/api/feed/video/{publication_id}")
async def feed_video_media(publication_id: str, request: Request, variant: str = "preview") -> FileResponse:
    selected = "full" if variant == "full" else "preview"
    column = "video_full_name" if selected == "full" else "video_preview_name"
    with db() as conn:
        publication = conn.execute(
            f"SELECT media_type, status, media_ready_at, {column} AS media_name "
            "FROM feed_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
    if (
        publication is None
        or publication["status"] != "published"
        or publication["media_type"] != "video"
        or not publication["media_ready_at"]
    ):
        raise HTTPException(404, "Video publication not found")
    media_name = str(publication["media_name"] or "")
    path = storage_resolve_under_root(MEDIA, media_name) if media_name else None
    if path is None or not path.is_file() or not media_name.startswith("feed/"):
        raise HTTPException(404, "Video media not found")
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Accept-Ranges": "bytes",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/feed/publications/{publication_id}/download")
async def feed_publication_download(publication_id: str, request: Request, format: str = "jpeg") -> Response:
    """Download branded public media without exposing the private gallery original."""
    requested_format = str(format or "jpeg").strip().lower()
    if requested_format == "mp4":
        with db() as conn:
            publication = conn.execute(
                """
                SELECT media_type, status, media_ready_at, video_full_name,
                       video_poster_width, video_poster_height
                FROM feed_publications
                WHERE id = ?
                """,
                (publication_id,),
            ).fetchone()
        if (
            publication is None
            or publication["status"] != "published"
            or publication["media_type"] != "video"
            or not publication["media_ready_at"]
        ):
            raise HTTPException(404, "Video publication not found")
        source_name = str(publication["video_full_name"] or "")
        source_path = storage_resolve_under_root(MEDIA, source_name) if source_name else None
        if source_path is None or not source_path.is_file() or not source_name.startswith("feed/"):
            raise HTTPException(404, "Video media not found")
        try:
            target_path = await asyncio.to_thread(
                feed_downloads.ensure_video_download,
                publication_id,
                source_path,
                media_dir=MEDIA,
                width=int(publication["video_poster_width"] or 1280),
                height=int(publication["video_poster_height"] or 720),
                run_ffmpeg=_run_feed_ffmpeg,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(422, "Video cannot be prepared for download") from exc
        safe_publication_id = re.sub(r"[^a-zA-Z0-9_-]", "-", publication_id)[:80] or "publication"
        return FileResponse(
            target_path,
            media_type="video/mp4",
            filename=f"izo-asa-{safe_publication_id}.mp4",
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-Content-Type-Options": "nosniff",
                "X-IZO-Watermark-Version": feed_downloads.WATERMARK_VERSION,
            },
        )
    try:
        selected_format = feed_downloads.normalize_download_format(format)
        source_path = storage_resolve_feed_media(
            _public_media_runtime(),
            MEDIA,
            publication_id,
            variant="large",
        )
        content = feed_downloads.render_feed_download(source_path, output_format=selected_format)
    except feed_downloads.FeedDownloadError as exc:
        raise HTTPException(400, str(exc)) from exc
    except PublicMediaAccessError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "Image cannot be prepared for download") from exc
    extension = "jpg" if selected_format == "jpeg" else "png"
    safe_publication_id = re.sub(r"[^a-zA-Z0-9_-]", "-", publication_id)[:80] or "publication"
    return Response(
        content=content,
        media_type="image/jpeg" if selected_format == "jpeg" else "image/png",
        headers={
            "Content-Disposition": f'attachment; filename="izo-asa-{safe_publication_id}.{extension}"',
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            "X-IZO-Watermark-Version": feed_downloads.WATERMARK_VERSION,
        },
    )
