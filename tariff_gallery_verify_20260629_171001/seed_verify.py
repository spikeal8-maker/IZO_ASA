import os, json
from pathlib import Path
os.environ['DATABASE_URL'] = r'''D:\\Google Drive\\My progact\\Генератор картинок\\tariff_gallery_verify_20260629_171001\\verify.sqlite3'''
os.environ['TRUSTED_COOKIE_SECURE'] = '0'
import backend.main as main
main.DB_PATH = main.sqlite_path_from_database_url(os.environ['DATABASE_URL'])
main.init_db()
now = '2026-06-29T12:00:00+00:00'
with main.db() as conn:
    conn.execute("INSERT INTO users (id, internal_user_id, username, first_name, email, role, plan, gallery_enabled, token_balance, created_at, last_login_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 500, ?, ?, ?)", ('telegram_admin_verify', 'iuid-admin-verify', 'admin_verify', 'Admin Verify', 'admin.verify@example.com', 'admin', 'pro', now, now, now))
    for legacy, iuid, plan, count in [('web_free_verify','iuid-free-verify','free',1),('web_mini_verify','iuid-mini-verify','mini',2),('web_plus_verify','iuid-plus-verify','plus',0),('web_pro_verify','iuid-pro-verify','pro',0)]:
        conn.execute("INSERT INTO users (id, internal_user_id, username, first_name, email, role, plan, gallery_enabled, token_balance, created_at, last_login_at, last_seen_at) VALUES (?, ?, ?, ?, ?, 'user', ?, 1, 100, ?, ?, ?)", (legacy, iuid, legacy, plan.title(), f'{legacy}@example.com', plan, now, now, now))
        for n in range(count):
            conn.execute("INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,prompt_translated,settings_json,is_favorite,created_at) VALUES (?, ?, ?, ?, ?, 512,512,'text_to_image','verify','prompt','','{}',0,?)", (f'img-{legacy}-{n}', legacy, f'job-{legacy}-{n}', f'/api/media/verify-{legacy}-{n}.png', f'/api/media/verify-{legacy}-{n}.webp', now))
    conn.execute("INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('tariffs', ?, ?)", (json.dumps(main.DEFAULT_TARIFFS), now))
session = main.create_auth_session('iuid-admin-verify', 'telegram_admin_verify', provider='web_email', platform='web_desktop')
print(main.DB_PATH)
print(session['session_token'])
