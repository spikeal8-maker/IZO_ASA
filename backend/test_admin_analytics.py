"""Admin/auth analytics tests (Phase 18). Temp SQLite via monkeypatch; no live DB."""
from __future__ import annotations

import re
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from test_support.browser_origin import BROWSER_ORIGIN

PW = "S3cret-Password!"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "analytics_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.init_db()
    return db_file


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


def make_admin():
    iuid = "iuid-admin"
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, role, language, created_at, last_login_at) "
                     "VALUES ('telegram_admin', ?, 'admin', 'ru', '2026-01-01', '2026-01-01')", (iuid,))
    s = main.create_auth_session(iuid, "telegram_admin", provider="telegram", platform="telegram_mini_app")
    return s["session_token"]


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def register(c, email):
    # Repeated calls on a shared client carry the session cookie set by the
    # first register, so an allowlisted Origin is needed to pass the CSRF
    # boundary (AUTH-LEGACY-001B); a real browser always sends it.
    return c.post("/api/auth/password/register-v2", json={"email": email, "password": PW, "password_repeat": PW,
                  "accepted_terms": True, "accepted_privacy": True, "accepted_personal_data": True, "platform": "web_desktop"}, headers=BROWSER_ORIGIN)


# 1, 2, 3
def test_public_code_assigned_stable_unique_prefixed(temp_db):
    with TestClient(main.app) as c:
        register(c, "a@example.com")
        register(c, "b@example.com")
    with main.db() as conn:
        codes = [r["public_user_code"] for r in conn.execute("SELECT public_user_code FROM users WHERE public_user_code IS NOT NULL")]
    assert all(c and re.match(r"^(WEB|TG|MAX|USR)-\d{6}$", c) for c in codes)
    assert len(codes) == len(set(codes))  # unique
    web = [c for c in codes if c.startswith("WEB-")]
    assert len(web) >= 2  # web/email users get WEB prefix
    # stable across re-init
    main.init_db()
    with main.db() as conn:
        codes2 = sorted(r["public_user_code"] for r in conn.execute("SELECT public_user_code FROM users WHERE public_user_code IS NOT NULL"))
    assert sorted(codes) == codes2


# 4
def test_display_name_priority(temp_db):
    class Row(dict):
        def __getitem__(self, k):
            return super().get(k)
        def keys(self):
            return super().keys()
    u = Row(display_name="Custom Name", first_name="F", last_name="L", username="nick", email="x@y.com", public_user_code="WEB-000001")
    assert main.resolve_display_name(u) == "Custom Name"
    assert main.resolve_display_name(Row(first_name="Иван", last_name="Петров")) == "Иван Петров"
    assert main.resolve_display_name(Row(username="cooluser")) == "cooluser"
    assert main.resolve_display_name(Row(email="local.part@mail.com")) == "local.part"
    assert main.resolve_display_name(Row(public_user_code="TG-000009")) == "TG-000009"
    assert main.resolve_display_name(Row()) == "Пользователь"


# 5
def test_password_login_updates_session_platform_lastseen(temp_db):
    with TestClient(main.app) as c:
        register(c, "act@example.com")
    with main.db() as conn:
        u = conn.execute("SELECT internal_user_id, last_seen_at FROM users WHERE email='act@example.com' OR id IN (SELECT legacy_user_id FROM auth_identities WHERE provider_user_id='act@example.com')").fetchone()
        iuid = conn.execute("SELECT internal_user_id FROM auth_identities WHERE provider_user_id='act@example.com'").fetchone()["internal_user_id"]
        sess = conn.execute("SELECT provider, platform FROM auth_sessions WHERE internal_user_id=? ORDER BY created_at DESC LIMIT 1", (iuid,)).fetchone()
        last_seen = conn.execute("SELECT last_seen_at FROM users WHERE internal_user_id=?", (iuid,)).fetchone()["last_seen_at"]
    assert sess["provider"] == "web_email" and sess["platform"] == "web"
    assert last_seen is not None


# 8, 9
def test_get_client_ip_trust(temp_db, monkeypatch):
    class Req:
        def __init__(self, headers, host="1.2.3.4"):
            self.headers = headers
            self.client = type("C", (), {"host": host})()
    # default: ignore forwarded headers
    monkeypatch.setattr(main, "TRUST_PROXY_HEADERS", False)
    monkeypatch.setattr(main, "TRUST_CLOUDFLARE_HEADERS", False)
    assert main.get_client_ip(Req({"x-forwarded-for": "9.9.9.9", "cf-connecting-ip": "8.8.8.8"})) == "1.2.3.4"
    # cloudflare trust on
    monkeypatch.setattr(main, "TRUST_CLOUDFLARE_HEADERS", True)
    assert main.get_client_ip(Req({"cf-connecting-ip": "8.8.8.8"}, host="127.0.0.1")) == "8.8.8.8"
    assert main.get_client_ip(Req({"cf-connecting-ip": "8.8.8.8"}, host="1.2.3.4")) == "1.2.3.4"
    # proxy trust on -> first XFF
    monkeypatch.setattr(main, "TRUST_CLOUDFLARE_HEADERS", False)
    monkeypatch.setattr(main, "TRUST_PROXY_HEADERS", True)
    assert main.get_client_ip(Req({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}, host="127.0.0.1")) == "9.9.9.9"
    assert main.get_client_ip(Req({"x-real-ip": "7.7.7.7", "x-forwarded-for": "9.9.9.9, 10.0.0.1"}, host="127.0.0.1")) == "7.7.7.7"
    assert main.get_client_ip(Req({"x-real-ip": "7.7.7.7"}, host="1.2.3.4")) == "1.2.3.4"


# 10, 11
def test_dashboard_requires_admin(temp_db):
    with TestClient(main.app) as c:
        assert c.get("/api/admin/dashboard-v2").status_code == 401
    # non-admin
    with TestClient(main.app) as c:
        register(c, "nonadmin@example.com")
        r = c.get("/api/admin/dashboard-v2")
    assert r.status_code == 403


# 12
def test_dashboard_counts(temp_db):
    tok = make_admin()
    with TestClient(main.app) as c:
        register(c, "u1@example.com")
        register(c, "u2@example.com")
        r = c.get("/api/admin/dashboard-v2", headers=bearer(tok))
    d = r.json()["dashboard"]
    assert d["total_users"] >= 3
    assert d["new_today"] >= 2
    assert d["logins_today"] >= 2  # two register-succeeded logins
    assert "web_email" in d["users_by_provider"]
    assert d["sessions_active"] >= 1
    assert d["timezone"] == "Europe/Moscow"
    assert set(d["periods"]) == {"today", "yesterday", "last_24h"}
    assert set(d["ranges"]) == {"1h", "6h", "12h", "24h", "7d", "30d", "90d"}
    assert all(set(value) == {"users", "generations", "tokens"} for value in d["ranges"].values())
    assert set(d["periods"]["today"]["tokens"]) == {"total", "daily", "main", "refunds"}


def test_admin_summary_splits_generation_timeline_by_product_kind(temp_db):
    tok = make_admin()
    now = main.datetime.now(main.timezone.utc).isoformat()
    with main.db() as conn:
        conn.executemany(
            "INSERT INTO jobs (id,user_id,mode,provider,status,progress,settings_json,created_at,completed_at) "
            "VALUES (?,?,?,?,?,100,'{}',?,?)",
            [
                ("dash-local", "telegram_admin", "text_to_image", "comfyui", "completed", now, now),
                ("dash-paid", "telegram_admin", "text_to_image", "openrouter", "completed", now, now),
                ("dash-video", "telegram_admin", "text_to_video", "openrouter", "completed", now, now),
            ],
        )

    with TestClient(main.app) as c:
        response = c.get("/api/admin/summary", headers=bearer(tok))

    assert response.status_code == 200
    timeline = response.json()["timeline"]
    assert timeline["generations"][-1]["value"] == 3
    assert timeline["local_images"][-1]["value"] == 1
    assert timeline["paid_images"][-1]["value"] == 1
    assert timeline["videos"][-1]["value"] == 1
    assert sum(point["value"] for point in timeline["local_images_24h"]) == 1
    assert sum(point["value"] for point in timeline["paid_images_24h"]) == 1
    assert sum(point["value"] for point in timeline["videos_24h"]) == 1


# 13, 14
def test_users_analytics_no_hashes_and_clean_ids(temp_db):
    tok = make_admin()
    with TestClient(main.app) as c:
        register(c, "clean@example.com")
        r = c.get("/api/admin/users-analytics-v2", headers=bearer(tok))
    text = r.text
    for forbidden in ("session_token_hash", "refresh_token_hash", "code_hash", "password_hash"):
        assert forbidden not in text
    item = next(i for i in r.json()["items"] if i["public_user_code"] and i["public_user_code"].startswith("WEB-"))
    assert "public_user_code" in item and "display_name" in item and "primary_provider" in item
    # full internal_user_id is provided for the drawer fetch (not a primary display field);
    # a short form is also present for the collapsed technical view
    assert "internal_user_id" in item and item["internal_user_id"]
    assert item["internal_user_id_short"].endswith("…")


def test_trusted_crm_full_contacts_search_sort_and_groups(temp_db):
    tok = make_admin()
    with TestClient(main.app) as c:
        register(c, "support.lookup@example.com")
        with main.db() as conn:
            identity = conn.execute(
                "SELECT internal_user_id FROM auth_identities WHERE provider_user_id='support.lookup@example.com'"
            ).fetchone()
            conn.execute(
                "UPDATE auth_identities SET provider_username='support_nick', provider_phone='+79991234567' "
                "WHERE internal_user_id=?",
                (identity["internal_user_id"],),
            )
        by_phone = c.get(
            "/api/admin/users-analytics-v2?q=9991234567&sort=contact_desc",
            headers=bearer(tok),
        )
        admins = c.get("/api/admin/users-analytics-v2?group=admin&sort=name_asc", headers=bearer(tok))
        detail = c.get(f"/api/admin/users/{identity['internal_user_id']}/analytics-v2", headers=bearer(tok))

    assert by_phone.status_code == 200
    item = by_phone.json()["items"][0]
    assert item["email"] == "support.lookup@example.com"
    assert item["username"] == "support_nick"
    assert item["phone"] == "+79991234567"
    assert item["account_group"] == "customer"
    assert admins.status_code == 200
    assert all(row["account_group"] == "admin" for row in admins.json()["items"])
    assert detail.json()["identities"][0]["provider_email"] == "support.lookup@example.com"
    assert detail.json()["identities"][0]["phone"] == "+79991234567"


# 15
def test_user_detail_analytics_safe(temp_db):
    tok = make_admin()
    with TestClient(main.app) as c:
        register(c, "detail@example.com")
        iuid = None
        with main.db() as conn:
            iuid = conn.execute("SELECT internal_user_id FROM auth_identities WHERE provider_user_id='detail@example.com'").fetchone()["internal_user_id"]
        r = c.get(f"/api/admin/users/{iuid}/analytics-v2", headers=bearer(tok))
    assert r.status_code == 200
    b = r.json()
    assert "summary" in b and "identities" in b and "sessions" in b and "devices" in b
    text = r.text
    for forbidden in ("session_token_hash", "refresh_token_hash", "password_hash", "code_hash", "raw_profile_json"):
        assert forbidden not in text


def test_user_dossier_access_models_and_paginated_history(temp_db):
    event_day = datetime.now(timezone.utc) - timedelta(days=1)

    def event_time(hour: int, minute: int = 0, second: int = 0) -> str:
        return event_day.replace(hour=hour, minute=minute, second=second, microsecond=0).isoformat()

    tok = make_admin()
    with TestClient(main.app) as c:
        register(c, "dossier@example.com")
        with main.db() as conn:
            identity = conn.execute("SELECT internal_user_id, legacy_user_id FROM auth_identities WHERE provider_user_id='dossier@example.com'").fetchone()
            iuid, uid = identity["internal_user_id"], identity["legacy_user_id"]
            conn.execute(
                "INSERT INTO auth_login_attempts (id,internal_user_id,provider,identifier,success,failure_reason,ip_address,platform,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                ("login-dossier-failed", iuid, "web_email", "dossier@example.com", 0, "bad_password", "10.20.30.40", "web", event_time(10)),
            )
            conn.execute(
                "INSERT INTO jobs (id,user_id,mode,provider,status,progress,prompt_original,prompt_translated,settings_json,created_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("job-dossier", uid, "text_to_image", "openrouter", "completed", 100, "real dossier prompt", "", json.dumps({"openrouterModel": "test/image-model", "openrouterCostUsd": 0.125, "openrouterBilling": {"actualCostUsd": 0.125, "actualCostRub": 12.5}}), event_time(11), event_time(11, 0, 5)),
            )
            conn.execute(
                "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,settings_json,stored_bytes,is_favorite,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("image-dossier", uid, "job-dossier", "/api/media/image.webp", "/api/media/image-thumb.webp", 1024, 1024, "text_to_image", "openrouter", "real dossier prompt", json.dumps({"openrouterModel": "test/image-model"}), 2345678, 0, event_time(11, 0, 5)),
            )
            conn.execute("INSERT INTO token_ledger (id,user_id,delta,reason,meta_json,created_at) VALUES (?,?,?,?,?,?)", ("charge-dossier", uid, -3, "generation", json.dumps({"jobId": "job-dossier", "token_cost": 3, "daily_part": 0, "balance_part": 3}), event_time(11)))
            conn.execute("INSERT INTO token_ledger (id,user_id,delta,reason,meta_json,created_at) VALUES (?,?,?,?,?,?)", ("refund-dossier", uid, 1, "generation_refund", json.dumps({"jobId": "job-dossier", "token_cost": 1, "balance_part": 1}), event_time(11, 1)))
            conn.execute("INSERT INTO invoices (id,invoice_code,internal_user_id,user_id,status,currency,total_amount,tokens_total,reason,created_at,updated_at,cancelled_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("invoice-dossier", "INV-DOSSIER", iuid, uid, "cancelled", "RUB", 1990, 0, "user_checkout", event_time(12), event_time(12, 1), event_time(12, 1)))
            conn.execute("INSERT INTO payments (id,invoice_id,internal_user_id,user_id,status,amount,currency,method,provider,reason,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("payment-dossier", "invoice-dossier", iuid, uid, "failed", 1990, "RUB", "bank_card", "yookassa", "user_checkout", event_time(12, 0, 30), event_time(12, 0, 45)))
        detail = c.get(f"/api/admin/users/{iuid}/analytics-v2", headers=bearer(tok))
        logins = c.get(f"/api/admin/users/{iuid}/history-v2?section=logins&limit=1", headers=bearer(tok))
        generations = c.get(f"/api/admin/users/{iuid}/history-v2?section=generations", headers=bearer(tok))
        media = c.get(f"/api/admin/users/{iuid}/history-v2?section=media", headers=bearer(tok))
        finance = c.get(f"/api/admin/users/{iuid}/history-v2?section=finance", headers=bearer(tok))

    assert detail.status_code == 200
    body = detail.json()
    assert body["access_summary"]["failed_logins"] >= 1
    assert any(ip["ip_address"] == "10.20.30.40" for ip in body["ip_history"])
    assert any(row["model"] == "test/image-model" and row["total"] == 1 for row in body["model_usage"])
    assert body["history_totals"]["generations"] >= 1
    assert logins.status_code == 200 and len(logins.json()["items"]) == 1
    assert generations.status_code == 200
    assert generations.json()["items"][0]["prompt"] == "real dossier prompt"
    generation = generations.json()["items"][0]
    assert generation["tokens"] == {"main": 3, "daily": 0, "refunded": 1, "net": 2}
    assert generation["preview_type"] == "image"
    assert generation["preview_url"] == "/api/admin/media/image/image-dossier?variant=thumb"
    assert media.status_code == 200
    assert media.json()["items"][0]["model"] == "test/image-model"
    assert media.json()["items"][0]["stored_bytes"] == 2345678
    assert generation["actual_cost_usd"] == pytest.approx(0.125)
    assert generation["actual_cost_rub"] == pytest.approx(12.5)
    assert body["token_economics"]["main_consumed"] == 2
    assert body["generation_economics"]["actual_api_cost_rub"] == pytest.approx(12.5)
    assert len(body["activity_series"]["days"]) == 14
    assert body["activity_series"]["totals"]["api_images"] >= 1
    assert body["cash_economics"]["margin_before_local_cost_rub"] == pytest.approx(-12.5)
    assert finance.status_code == 200
    payment = next(item for item in finance.json()["items"] if item["kind"] == "payment")
    assert payment["status"] == "failed" and payment["tokens_credited"] is False
    for forbidden in ("session_token_hash", "refresh_token_hash", "user_agent_hash", "raw_profile_json"):
        assert forbidden not in detail.text + logins.text + generations.text


def test_user_dossier_separates_actual_cost_from_calibrated_unreconciled_timeout(temp_db):
    tok = make_admin()
    with TestClient(main.app) as client:
        register(client, "unreconciled@example.com")
        with main.db() as conn:
            identity = conn.execute(
                "SELECT internal_user_id,legacy_user_id FROM auth_identities WHERE provider_user_id='unreconciled@example.com'"
            ).fetchone()
            internal_user_id, user_id = identity["internal_user_id"], identity["legacy_user_id"]
            completed_settings = {
                "openrouterModel": "bytedance/seedance-test",
                "duration": 4,
                "resolution": "480p",
                "aspectRatio": "16:9",
                "generateAudio": False,
                "openrouterCostUsd": 0.28,
                "openrouterBilling": {
                    "estimatedCostUsd": 0.20,
                    "estimatedCostRub": 20.0,
                    "actualCostUsd": 0.28,
                    "actualCostRub": 28.0,
                    "effectiveUsdRub": 100.0,
                },
            }
            timeout_settings = {
                "openrouterModel": "bytedance/seedance-test",
                "duration": 4,
                "resolution": "480p",
                "aspectRatio": "16:9",
                "generateAudio": False,
                "openrouterSubmitError": "",
                "openrouterBilling": {
                    "estimatedCostUsd": 0.20,
                    "estimatedCostRub": 20.0,
                    "effectiveUsdRub": 100.0,
                },
            }
            conn.execute(
                "INSERT INTO jobs (id,user_id,mode,provider,status,progress,prompt_original,settings_json,created_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("job-calibration", user_id, "reference_to_video", "openrouter", "completed", 100, "calibration", json.dumps(completed_settings), "2026-08-20T09:00:00+00:00", "2026-08-20T09:01:00+00:00"),
            )
            conn.execute(
                "INSERT INTO jobs (id,user_id,mode,provider,status,progress,prompt_original,error_message,settings_json,created_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("job-provider-timeout", user_id, "reference_to_video", "openrouter", "failed", 100, "timeout", "temporary failure", json.dumps(timeout_settings), "2026-08-20T10:00:00+00:00", "2026-08-20T10:00:30+00:00"),
            )

        detail = client.get(f"/api/admin/users/{internal_user_id}/analytics-v2", headers=bearer(tok))
        generations = client.get(
            f"/api/admin/users/{internal_user_id}/history-v2?section=generations",
            headers=bearer(tok),
        )

    assert detail.status_code == 200
    economics = detail.json()["generation_economics"]
    assert economics["actual_api_cost_usd"] == pytest.approx(0.28)
    assert economics["unreconciled_api_jobs"] == 1
    assert economics["unreconciled_api_cost_usd"] == pytest.approx(0.28)
    assert economics["potential_api_cost_usd"] == pytest.approx(0.56)
    timed_out = next(item for item in generations.json()["items"] if item["job_id"] == "job-provider-timeout")
    assert timed_out["cost_kind"] == "unreconciled_estimate"
    assert timed_out["unreconciled_cost_usd"] == pytest.approx(0.28)
    assert timed_out["cost_calibration_multiplier"] == pytest.approx(1.4)


def test_presence_and_payment_dashboard_series(temp_db):
    now = main.datetime(2026, 8, 22, 10, 17, tzinfo=main.timezone.utc)
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id,internal_user_id,role,language,created_at,last_login_at) "
            "VALUES ('web-presence-a','presence-a','user','ru',?,?)",
            (now.isoformat(), now.isoformat()),
        )
        conn.execute(
            "INSERT INTO users (id,internal_user_id,role,language,created_at,last_login_at) "
            "VALUES ('web-presence-b','presence-b','user','ru',?,?)",
            (now.isoformat(), now.isoformat()),
        )
        for user_id, internal in (("web-presence-a", "presence-a"), ("web-presence-b", "presence-b")):
            conn.execute(
                "INSERT INTO user_presence_samples "
                "(bucket_at,user_id,internal_user_id,platform,active_seconds,updated_at) VALUES (?,?,?,?,?,?)",
                ("2026-08-22T10:15:00+00:00", user_id, internal, "web", 60, now.isoformat()),
            )
        conn.execute(
            "INSERT INTO payments (id,invoice_id,internal_user_id,user_id,status,amount,currency,method,provider,reason,created_at,updated_at,paid_at) "
            "VALUES ('pay-ok','invoice-ok','presence-a','web-presence-a','paid',500,'RUB','bank_card','yookassa','test',?,?,?)",
            (now.isoformat(), now.isoformat(), now.isoformat()),
        )
        conn.execute(
            "INSERT INTO payments (id,invoice_id,internal_user_id,user_id,status,amount,currency,method,provider,reason,created_at,updated_at) "
            "VALUES ('pay-failed','invoice-failed','presence-b','web-presence-b','failed',700,'RUB','bank_card','yookassa','test',?,?)",
            (now.isoformat(), now.isoformat()),
        )
        presence = main.admin_analytics.dashboard_presence_timeline(conn, now=now)
        payments = main.admin_analytics.dashboard_payment_timeline(conn, now=now)
        summary = main.admin_analytics.dashboard_payment_summary(conn)

    assert presence["active_users_1h"][-1]["value"] == 2
    assert presence["active_users"][-1]["value"] == 2
    assert payments["payments_paid_1h"][-1]["value"] == 1
    assert payments["payments_failed_1h"][-1]["value"] == 1
    assert summary == {"total_attempts": 2, "paid_count": 1, "failed_count": 1, "revenue_rub": 500}


def test_heartbeat_records_bounded_presence_bucket(temp_db):
    with main.db() as conn:
        now = main.datetime.now(main.timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO users (id,internal_user_id,role,language,created_at,last_login_at) "
            "VALUES ('web_heartbeat','heartbeat-iuid','user','ru',?,?)",
            (now, now),
        )
    with TestClient(main.app) as client:
        assert client.post('/api/app/heartbeat', json={"platform": "web", "userId": "heartbeat", "seconds": 60}).status_code == 200
        assert client.post('/api/app/heartbeat', json={"platform": "web", "userId": "heartbeat", "seconds": 60}).status_code == 200
    with main.db() as conn:
        rows = conn.execute(
            "SELECT active_seconds,internal_user_id FROM user_presence_samples WHERE user_id='web_heartbeat'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["active_seconds"] == 120
    assert rows[0]["internal_user_id"] == "heartbeat-iuid"


def test_user_detail_analytics_p0_real_data_and_no_secret_leaks(temp_db):
    tok = make_admin()
    long_prompt = "cinematic neon city " * 30
    with TestClient(main.app) as c:
        register(c, "p0@example.com")
        with main.db() as conn:
            u = conn.execute("SELECT id, internal_user_id FROM auth_identities WHERE provider_user_id='p0@example.com'").fetchone()
            user_id, iuid = u["id"], u["internal_user_id"]
            user_id = conn.execute("SELECT legacy_user_id FROM auth_identities WHERE internal_user_id=?", (iuid,)).fetchone()["legacy_user_id"]
            conn.execute(
                "INSERT INTO jobs (id,user_id,mode,provider,status,progress,prompt_original,prompt_translated,result_image_id,error_message,settings_json,created_at,completed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("job_secret_1234567890", user_id, "text_to_image", "comfyui", "completed", 100, long_prompt, "", "img_safe_1234567890", "C:\\secret\\traceback.txt", json.dumps({"modelProfile": "flux"}, ensure_ascii=False), "2026-06-27T10:00:00+00:00", "2026-06-27T10:01:00+00:00"),
            )
            conn.execute(
                "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,prompt_translated,settings_json,is_favorite,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("img_safe_1234567890", user_id, "job_secret_1234567890", "/api/media/img.png?userId=x", "/api/media/thumb.webp?userId=x", 1024, 1024, "text_to_image", "comfyui", long_prompt, "", "{}", 1, "2026-06-27T10:01:00+00:00"),
            )
            conn.execute(
                "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,prompt_translated,settings_json,is_favorite,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("img_bad", user_id, "job_bad", "C:/media/img.png", "C:/media/thumb.webp", 1024, 1024, "text_to_image", "comfyui", "bad", "", "{}", 0, "2026-06-27T09:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO token_ledger (id,user_id,delta,reason,meta_json,created_at) VALUES (?,?,?,?,?,?)",
                ("ledger_1234567890", user_id, -12, "generation", json.dumps({"jobId": "job_secret_1234567890", "mode": "text_to_image", "provider": "comfyui", "password_hash": "NOPE"}, ensure_ascii=False), "2026-06-27T10:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO auth_sessions (id,internal_user_id,legacy_user_id,session_token_hash,refresh_token_hash,provider,platform,ip_address,user_agent_hash,created_at,last_seen_at,expires_at,revoked_at,revoke_reason,metadata_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("sess1", iuid, user_id, "secret_session_hash", "secret_refresh_hash", "web_email", "web", "1.2.3.4", "ua_hash", "2026-06-27", "2026-06-27", "2099-01-01", "2026-06-27", "logout", json.dumps({"device": {"browser": "Chrome", "os": "Windows", "device_type": "desktop"}, "client": {"app_version": "20D.1"}}, ensure_ascii=False)),
            )
            conn.execute(
                "INSERT INTO device_installations (id,internal_user_id,legacy_user_id,installation_id,anonymous_id,platform,storage_type,first_seen_at,last_seen_at,metadata_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("dev1", iuid, user_id, "installation-secret-long", "anonymous-secret-long", "web", "local", "2026-06-01", "2026-06-27", json.dumps({"device": {"browser": "Chrome", "os": "Windows", "device_type": "desktop"}, "client": {"app_version": "20D.1"}}, ensure_ascii=False)),
            )
            conn.execute("INSERT INTO auth_login_attempts (id,internal_user_id,provider,identifier,success,failure_reason,ip_address,user_agent_hash,platform,created_at) VALUES ('la1',?,'web_email','p0@example.com',0,'bad','1.2.3.4','ua','web','2026-06-27')", (iuid,))
            conn.execute("INSERT INTO security_events (id,internal_user_id,session_id,severity,event_type,ip_address,user_agent_hash,details_json,created_at) VALUES ('sec1',?,NULL,'warning','admin_password_reset','1.2.3.4','ua','{}','2026-06-27')", (iuid,))
            conn.execute("INSERT INTO event_logs (id,internal_user_id,legacy_user_id,session_id,event_name,platform,ip_address,properties_json,created_at) VALUES ('evt1',?,?,?,'profile_updated','web','1.2.3.4',?,'2026-06-27')", (iuid, user_id, 'sess1', json.dumps({"provider": "web_email", "secret": "blocked"}, ensure_ascii=False)))
            conn.execute("INSERT INTO audit_logs (id,actor_internal_user_id,target_internal_user_id,action,entity_type,entity_id,before_json,after_json,ip_address,user_agent_hash,created_at) VALUES ('aud1','admin',?,'admin_change_role','user',?,NULL,?,'1.2.3.4','ua','2026-06-27')", (iuid, user_id, json.dumps({"reason": "test role"}, ensure_ascii=False)))
            conn.execute("INSERT INTO audit_logs (id,actor_internal_user_id,target_internal_user_id,action,entity_type,entity_id,before_json,after_json,ip_address,user_agent_hash,created_at) VALUES ('aud2','admin',?,'admin_block_user','user',?,NULL,?,'1.2.3.4','ua','2026-06-27')", (iuid, user_id, json.dumps({"reason": "test ban"}, ensure_ascii=False)))
        r = c.get(f"/api/admin/users/{iuid}/analytics-v2", headers=bearer(tok))
        events = c.get(f"/api/admin/users/{iuid}/history-v2?section=events", headers=bearer(tok))
    assert r.status_code == 200
    b = r.json()
    assert b["recent_generations"][0]["id"].endswith("…")
    assert b["recent_generations"][0]["token_cost"] == 12
    assert len(b["recent_generations"][0]["prompt"]) < len(long_prompt)
    assert b["recent_generations"][0]["error"] == "Ошибка генерации. Детали скрыты."
    assert b["recent_gallery"][0]["thumbnail_url"].startswith("/api/media/")
    assert all(not g["thumbnail_url"].startswith("C:") for g in b["recent_gallery"])
    generation_ledger = next(item for item in b["token_ledger_recent"] if item["delta"] == -12)
    assert generation_ledger["job_id"].endswith("…")
    assert any(s["device"]["browser"] == "Chrome" for s in b["sessions"])
    assert all(s["device"]["mac_status"] == "MAC: недоступен" for s in b["sessions"])
    assert b["devices"][0]["installation_id"].endswith("…")
    assert any(item["browser"] == "Chrome" and item["os"] == "Windows" for item in b["client_history"])
    assert events.status_code == 200
    linked_event = next(item for item in events.json()["items"] if item["event_name"] == "profile_updated")
    assert linked_event["browser"] == "Chrome"
    assert linked_event["device_type"] == "desktop"
    assert linked_event["details"] == {"provider": "web_email"}
    assert b["security_summary"]["failed_login_count"] == 1
    assert b["security_summary"]["password_reset_count"] == 1
    assert b["security_summary"]["ban_count"] == 1
    assert b["security_summary"]["role_change_count"] == 1
    assert b["security_summary"]["session_revocation_count"] == 1
    text = r.text
    for forbidden in ("session_token_hash", "refresh_token_hash", "password_hash", "raw_profile_json", "secret_session_hash", "secret_refresh_hash", "initData", "WebAppData"):
        assert forbidden not in text


def test_admin_media_preview_supports_images_and_video(temp_db, tmp_path, monkeypatch):
    token = make_admin()
    media = tmp_path / "media"
    media.mkdir()
    (media / "admin-preview.webp").write_bytes(b"RIFFtestWEBP")
    (media / "admin-preview.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42test")
    monkeypatch.setattr(main, "MEDIA", media)
    with main.db() as conn:
        conn.execute(
            "INSERT INTO jobs (id,user_id,mode,provider,status,progress,prompt_original,settings_json,created_at,completed_at) "
            "VALUES ('admin-video-job','telegram_admin','text_to_video','openrouter','completed',100,'test video',?, '2026-08-21T01:00:00+00:00','2026-08-21T01:01:00+00:00')",
            (json.dumps({"localFile": "admin-preview.mp4", "openrouterModel": "test/video"}),),
        )
        conn.execute(
            "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,settings_json,is_favorite,created_at) "
            "VALUES ('admin-image','telegram_admin',NULL,'/api/media/admin-preview.webp','/api/media/admin-preview.webp',1,1,'text_to_image','test','test image','{}',0,'2026-08-21T01:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO videos (id,user_id,job_id,url,width,height,duration_seconds,aspect_ratio,mode,provider,prompt_original,settings_json,stored_bytes,is_favorite,created_at) "
            "VALUES ('admin-video','telegram_admin','admin-video-job','/api/video/media/admin-video-job',640,480,4,'4:3','text_to_video','openrouter','test video','{}',18,0,'2026-08-21T01:01:00+00:00')"
        )
        conn.execute(
            "INSERT INTO image_sources (id,image_id,user_id,source_kind,role,slot_index,thumb_url,thumb_width,thumb_height,thumb_bytes,children_json,created_at) "
            "VALUES ('admin-source','admin-image','telegram_admin','upload','base',1,'/api/media/admin-preview.webp',1,1,15,'[]','2026-08-21T00:59:00+00:00')"
        )
        conn.execute(
            "INSERT INTO feed_publications (id,image_id,internal_user_id,title,status,created_at) "
            "VALUES ('admin-publication','admin-image','iuid-admin','Публичная работа','published','2026-08-21T01:02:00+00:00')"
        )
    with TestClient(main.app) as client:
        image = client.get("/api/admin/media/image/admin-image?variant=thumb", headers=bearer(token))
        video = client.get("/api/admin/media/video/admin-video", headers=bearer(token))
        source = client.get("/api/admin/media/image/admin-source?variant=thumb", headers=bearer(token))
        detail = client.get("/api/admin/users/iuid-admin/analytics-v2", headers=bearer(token)).json()
        media = client.get("/api/admin/users/iuid-admin/history-v2?section=media", headers=bearer(token)).json()
    assert image.status_code == 200
    assert video.status_code == 200
    assert source.status_code == 200
    assert detail["recent_videos"][0]["model"] == "test/video"
    assert detail["recent_videos"][0]["media_url"] == "/api/admin/media/video/admin-video"
    assert media["total"] == 3
    source_item = next(item for item in media["items"] if item["type"] == "source")
    image_item = next(item for item in media["items"] if item["type"] == "image")
    assert source_item["media_url"] == "/api/admin/media/image/admin-source?variant=thumb"
    assert source_item["source_role"] == "base"
    assert image_item["publication"]["status"] == "published"


# 6, 7: provider profile fields captured (telegram/max upsert already store them)
def test_provider_profile_fields_captured(temp_db):
    now = "2026-06-26T00:00:00+00:00"
    with main.db() as conn:
        main.telegram_upsert_identity(conn, {"id": 555, "first_name": "Ольга", "last_name": "И", "username": "olga", "language_code": "ru", "photo_url": "http://x/p.jpg"}, now)
        main.max_upsert_identity(conn, {"id": 777, "first_name": "Max", "username": "maxuser", "language_code": "en"}, now)
        tg = conn.execute("SELECT * FROM auth_identities WHERE provider='telegram' AND provider_user_id='555'").fetchone()
        mx = conn.execute("SELECT * FROM auth_identities WHERE provider='max' AND provider_user_id='777'").fetchone()
    assert tg["provider_username"] == "olga" and tg["provider_first_name"] == "Ольга" and tg["provider_avatar_url"] == "http://x/p.jpg"
    assert mx["provider_username"] == "maxuser" and mx["provider_language_code"] == "en"


# 16-ish: users.id never changed
def test_users_id_unchanged(temp_db):
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) VALUES ('telegram_keep','iuid-keep','ru','user','2026-01-01','2026-01-01')")
    main.init_db()
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM users WHERE id='telegram_keep'").fetchone()["c"] == 1
