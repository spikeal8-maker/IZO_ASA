"""Base SQLite schema declarations extracted from the legacy initializer.

Importing this module performs no I/O. Execution order remains controlled by
`main.init_db()` while the schema migration is decomposed incrementally.
"""

from __future__ import annotations


BASE_SCHEMA_SQL = """
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

            CREATE TABLE IF NOT EXISTS power_samples (
                sampled_at TEXT PRIMARY KEY,
                server_estimated_watts REAL NOT NULL,
                ups_reference_watts REAL,
                overhead_watts REAL NOT NULL,
                gpu_3090_watts REAL NOT NULL DEFAULT 0,
                gpu_4070_watts REAL NOT NULL DEFAULT 0,
                cpu_percent REAL NOT NULL DEFAULT 0,
                active_local_jobs INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'ups_calibrated_gpu'
            );
            CREATE INDEX IF NOT EXISTS idx_power_samples_sampled_at
                ON power_samples(sampled_at DESC);

            CREATE TABLE IF NOT EXISTS generation_energy_usage (
                job_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                mode TEXT NOT NULL,
                model TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                sample_count INTEGER NOT NULL,
                average_watts REAL NOT NULL,
                peak_watts REAL NOT NULL,
                energy_wh REAL NOT NULL,
                incremental_wh REAL NOT NULL,
                measured_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_generation_energy_completed
                ON generation_energy_usage(completed_at DESC);

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
                created_at TEXT NOT NULL,
                storage_tier TEXT NOT NULL DEFAULT 'original',
                optimized_at TEXT,
                original_bytes INTEGER,
                stored_bytes INTEGER
            );

            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                job_id TEXT NOT NULL UNIQUE,
                url TEXT NOT NULL,
                width INTEGER NOT NULL DEFAULT 0,
                height INTEGER NOT NULL DEFAULT 0,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                aspect_ratio TEXT,
                mode TEXT NOT NULL,
                provider TEXT NOT NULL,
                prompt_original TEXT,
                settings_json TEXT NOT NULL DEFAULT '{}',
                stored_bytes INTEGER,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                deleted_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_videos_user_created
                ON videos(user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_videos_job
                ON videos(job_id);

            CREATE TABLE IF NOT EXISTS video_file_deletions (
                id TEXT PRIMARY KEY,
                video_id TEXT,
                job_id TEXT,
                filename TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_video_file_deletions_created
                ON video_file_deletions(created_at, id);

            CREATE TABLE IF NOT EXISTS video_sources (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
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
            CREATE INDEX IF NOT EXISTS idx_video_sources_job
                ON video_sources(job_id, slot_index);
            CREATE INDEX IF NOT EXISTS idx_video_sources_user
                ON video_sources(user_id, created_at);

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
                is_favorite INTEGER NOT NULL DEFAULT 0,
                library_deleted_at TEXT,
                availability_status TEXT NOT NULL DEFAULT 'unknown',
                availability_checked_at TEXT,
                unavailable_at TEXT,
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

            CREATE TABLE IF NOT EXISTS tariff_token_grants (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                grant_key TEXT NOT NULL UNIQUE,
                plan TEXT NOT NULL,
                amount INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                source_id TEXT,
                period_start TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tariff_token_grants_user_created
                ON tariff_token_grants(internal_user_id, created_at);

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

            CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_provider_payment
                ON payments(provider, provider_payment_id) WHERE provider_payment_id IS NOT NULL;

            CREATE TABLE IF NOT EXISTS legal_acceptances (
                id TEXT PRIMARY KEY,
                internal_user_id TEXT NOT NULL,
                payment_id TEXT,
                document_type TEXT NOT NULL,
                document_version TEXT NOT NULL,
                receipt_contact TEXT,
                ip_address TEXT,
                user_agent TEXT,
                accepted_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_legal_acceptances_user_time
                ON legal_acceptances(internal_user_id, accepted_at);

            CREATE TABLE IF NOT EXISTS user_billing_profiles (
                internal_user_id TEXT PRIMARY KEY,
                receipt_email TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payment_provider_events (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                event_key TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                provider_payment_id TEXT NOT NULL,
                status TEXT NOT NULL,
                received_at TEXT NOT NULL,
                processed_at TEXT,
                error TEXT
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
            CREATE INDEX IF NOT EXISTS idx_payment_provider_events_received ON payment_provider_events(received_at);
            CREATE INDEX IF NOT EXISTS idx_refunds_user_created ON refunds(internal_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);
            CREATE INDEX IF NOT EXISTS idx_promo_redemptions_user_created ON promo_redemptions(internal_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_bonus_grants_user_created ON bonus_grants(internal_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_referral_links_code ON referral_links(referral_code);
            CREATE INDEX IF NOT EXISTS idx_referral_relations_parent_created ON referral_relations(parent_internal_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_referral_relations_child_created ON referral_relations(child_internal_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_referral_rewards_parent_created ON referral_rewards(parent_internal_user_id, created_at);
"""


IDENTITY_SCHEMA_SQL = """
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

            -- Five-minute presence buckets power the real online/activity charts.
            -- One row per user and bucket prevents the 60-second heartbeat from
            -- growing the table without bounds.
            CREATE TABLE IF NOT EXISTS user_presence_samples (
                bucket_at TEXT NOT NULL,
                user_id TEXT NOT NULL,
                internal_user_id TEXT,
                platform TEXT,
                active_seconds INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (bucket_at, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_presence_bucket ON user_presence_samples(bucket_at);
            CREATE INDEX IF NOT EXISTS idx_presence_internal_bucket
                ON user_presence_samples(internal_user_id, bucket_at);

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
                image_id TEXT UNIQUE,
                video_id TEXT UNIQUE,
                media_type TEXT NOT NULL DEFAULT 'image',
                internal_user_id TEXT NOT NULL,
                legacy_user_id TEXT,
                title TEXT NOT NULL,
                description TEXT,
                prompt_visibility TEXT NOT NULL DEFAULT 'open',
                allow_recreate INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'published',
                view_count INTEGER NOT NULL DEFAULT 0,
                moderation_status TEXT NOT NULL DEFAULT 'approved',
                moderation_reason TEXT,
                moderated_at TEXT,
                moderated_by_internal_user_id TEXT,
                source_job_id TEXT,
                metric_origin TEXT NOT NULL DEFAULT 'organic',
                video_poster_name TEXT,
                video_poster_width INTEGER,
                video_poster_height INTEGER,
                video_poster_bytes INTEGER,
                video_preview_name TEXT,
                video_preview_bytes INTEGER,
                video_full_name TEXT,
                video_full_bytes INTEGER,
                duration_ms INTEGER,
                has_audio INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                CHECK (media_type IN ('image', 'video')),
                CHECK ((media_type = 'image' AND image_id IS NOT NULL AND video_id IS NULL)
                    OR (media_type = 'video' AND video_id IS NOT NULL AND image_id IS NULL))
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
            CREATE INDEX IF NOT EXISTS idx_feed_reactions_viewer_kind
                ON feed_reactions(internal_user_id, kind, publication_id);

            CREATE TABLE IF NOT EXISTS feed_author_follows (
                follower_internal_user_id TEXT NOT NULL,
                author_internal_user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (follower_internal_user_id, author_internal_user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_feed_author_follows_author
                ON feed_author_follows(author_internal_user_id);

            CREATE TABLE IF NOT EXISTS feed_view_events (
                publication_id TEXT NOT NULL,
                viewer_key TEXT NOT NULL,
                first_viewed_at TEXT NOT NULL,
                last_viewed_at TEXT NOT NULL,
                accepted_view_count INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (publication_id, viewer_key)
            );
            CREATE INDEX IF NOT EXISTS idx_feed_view_events_viewer_recent
                ON feed_view_events(viewer_key, last_viewed_at DESC, publication_id);
            CREATE INDEX IF NOT EXISTS idx_feed_view_events_last_viewed
                ON feed_view_events(last_viewed_at);

            CREATE TABLE IF NOT EXISTS feed_engagement_events (
                id TEXT PRIMARY KEY,
                publication_id TEXT,
                viewer_key TEXT NOT NULL,
                event_type TEXT NOT NULL,
                duration_ms INTEGER,
                context_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_feed_engagement_events_type_created
                ON feed_engagement_events(event_type, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_feed_engagement_events_publication_created
                ON feed_engagement_events(publication_id, event_type, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_feed_engagement_events_viewer_created
                ON feed_engagement_events(viewer_key, created_at DESC);

            CREATE TABLE IF NOT EXISTS feed_subscription_reads (
                internal_user_id TEXT PRIMARY KEY,
                last_read_at TEXT NOT NULL
            );

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


IMAGE_SEARCH_SCHEMA_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS images_search USING fts5(
                image_id UNINDEXED,
                user_id UNINDEXED,
                search_text,
                tokenize='unicode61'
            );
            CREATE TRIGGER IF NOT EXISTS images_search_insert AFTER INSERT ON images BEGIN
                INSERT INTO images_search(rowid, image_id, user_id, search_text)
                VALUES (new.rowid, new.id, new.user_id,
                    COALESCE(new.id, '') || ' ' || COALESCE(new.prompt_original, '') || ' ' ||
                    COALESCE(new.prompt_translated, '') || ' ' || COALESCE(new.mode, '') || ' ' ||
                    COALESCE(new.provider, '') || ' ' || COALESCE(new.settings_json, ''));
            END;
            CREATE TRIGGER IF NOT EXISTS images_search_delete AFTER DELETE ON images BEGIN
                DELETE FROM images_search WHERE rowid = old.rowid;
            END;
            CREATE TRIGGER IF NOT EXISTS images_search_update AFTER UPDATE OF
                id, user_id, prompt_original, prompt_translated, mode, provider, settings_json ON images BEGIN
                DELETE FROM images_search WHERE rowid = old.rowid;
                INSERT INTO images_search(rowid, image_id, user_id, search_text)
                VALUES (new.rowid, new.id, new.user_id,
                    COALESCE(new.id, '') || ' ' || COALESCE(new.prompt_original, '') || ' ' ||
                    COALESCE(new.prompt_translated, '') || ' ' || COALESCE(new.mode, '') || ' ' ||
                    COALESCE(new.provider, '') || ' ' || COALESCE(new.settings_json, ''));
            END;
"""
