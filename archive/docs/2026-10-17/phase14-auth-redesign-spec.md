# Phase 14.3 — Auth Flow Redesign Spec (browser email+password, platform-first TG/MAX)

Specification only. No code, DB, frontend, or backend changes in this phase.

## 1. Current auth inventory

**Endpoints (all cookie-based v2):** `bootstrap-v2`, `telegram-v2`, `max-v2`,
`email/request-code-v2`, `email/verify-code-v2`, `me-v2`, `whoami-v2`,
`session/refresh-v2`, `session/logout-v2`, `sessions-v2`; legacy `web-login`.

**Tables present:** users, auth_identities, auth_sessions, session_events,
auth_login_attempts, device_installations, user_consents, security_events,
audit_logs, auth_otp_challenges, event_logs (+ legacy jobs/images/token_ledger/…).

**Password auth artifacts:** NONE. No `password_hash`, `password_updated_at`,
`password_*_attempts`, `password_reset_*`, `email_verified_at`, `phone_verified_at`.

**Password hashing deps:** NONE (requirements.txt = fastapi, uvicorn, pydantic,
httpx, Pillow, python-multipart, pytest). No argon2/bcrypt/passlib/pwdlib.

**users columns relevant:** `email` and `phone` exist; no verified-at columns.

**Frontend:** `AuthV2Modal` shows **Email OTP as primary** (email → код), with
Telegram/MAX as secondary buttons disabled when no `initData`/`webAppData`.
That is the product bug: in a plain browser it pushes email OTP (no provider wired),
and in TG/MAX it still leads with email instead of platform login.

## 2. Target login model (recommended)

- **Browser/web:** Email + **password** with Вход / Регистрация tabs. (Email OTP
  demoted to optional/"другой способ"; it needs an email provider anyway.)
- **Telegram Mini App:** platform-first — `initData` present ⇒ "Войти через Telegram"
  primary (or silent auto-login); no email/password required. Absent ⇒ disabled
  "Доступно в Telegram Mini App".
- **MAX Mini App:** same, platform-first via raw WebAppData.
- **Fallback (platform unknown):** browser email+password.

## 3. Password auth backend design

### POST /api/auth/password/register-v2
Request: `{ email, password, password_repeat, accepted_terms, accepted_privacy, accepted_personal_data }`.
- normalize email; validate password length (≥ 8, ≤ 128); `password == password_repeat`;
  all three `accepted_*` must be true (else 400).
- if email has no `web_email` identity: create user (legacy-safe `web_<uuid>` id),
  `auth_identities(provider='web_email', provider_user_id=email, provider_email=email,
  verified_at=now)`, `auth_passwords` row (hash only), `user_consents` rows, session
  + HttpOnly cookies; return me summary.
- **if email already has an account (enumeration handling):** recommended interim =
  **409 generic** "Не удалось создать аккаунт. Попробуйте войти или восстановить
  пароль." (does not confirm which field). Full anti-enumeration (always-200 + email)
  requires the email provider — defer. Owner decision (§11).
- logs: `event_logs(login_succeeded/register)`, `security_events` on validation abuse,
  `audit_logs` not required (self-service). Never log raw password.

### POST /api/auth/password/login-v2
Request: `{ email, password }`.
- generic error **"Неверная почта или пароль"** for unknown email OR bad password.
- constant-time verify (hash verify is constant-time by construction); rate-limit by
  email-hash + IP + installation (reuse `auth_login_attempts` + an OTP-style window).
- success ⇒ session + HttpOnly cookies + me summary.
- banned/deleted ⇒ 403 generic.
- never reveal account existence; `security_events('password_login_failed')`,
  `event_logs('login_succeeded'/'login_failed')`.

### POST /api/auth/password/forgot-v2 (design only, not now)
- accept email; always generic 200; if account exists, create
  `password_reset_challenges` (token hash) and email a link (needs email provider).

### POST /api/auth/password/reset-v2 (design only, not now)
- validate reset token (hash compare), TTL, one-time (consumed_at), rate-limited;
  set new `auth_passwords` hash; revoke active sessions.

## 4. Password storage design
- Never store raw password.
- **Algorithm — two options:**
  - **(A) Argon2id** via `argon2-cffi` — ideal, but adds a dependency (needs owner
    approval per project rules).
  - **(B) PBKDF2-HMAC-SHA256** via stdlib `hashlib.pbkdf2_hmac` — **zero new
    dependency**, salt per-record, high iteration count (e.g. 600k), versioned. Stored
    as `pbkdf2_sha256$<iters>$<salt_b64>$<hash_b64>`.
  - **Recommendation:** start with **(B) PBKDF2 (stdlib)** to avoid dependency friction;
    keep the `algorithm` column so a later upgrade to Argon2id is a drop-in (re-hash on
    next login). Owner decision (§11).
- `auth_passwords`: `password_hash`, `algorithm`, `created_at`, `updated_at`,
  `disabled_at`. Salt embedded in the hash string (no separate column).
- Failed attempts tracked via `auth_login_attempts` (+ window), not a counter column.
- `security_events` on failures; `event_logs` succeeded/failed without raw password.

## 5. Consent design
- Use `user_consents`. Required at registration: `terms`, `privacy`,
  `personal_data_processing`. Optional/separate: `cookies`, `ai_generation_rules`,
  `analytics`, `marketing`.
- **Recommended UX (legally safe):** checkboxes **unchecked by default** OR a single
  explicit primary action "Создать аккаунт и принять условия" with visible links to
  Terms/Privacy. Either way, account creation is the explicit affirmative action → write
  one `user_consents` row per accepted type (accepted=1, accepted_at=now, document_version).
- **Never** pre-check, and **never** write a consent row without the user's explicit
  click. Owner legal decision (§11).

## 6. Phone login (analysis, not implemented)
Needs: SMS provider + cost control, phone verification + OTP, normalization (E.164),
anti-abuse/rate-limit, legal/privacy storage of phone numbers. **Recommendation:
postpone.** Do email+password first; Telegram/MAX platform login first-class. Phone is
a later, provider-gated phase.

## 7. DB schema proposal (additive-only; no users.id change)

```sql
ALTER TABLE users ADD COLUMN email_verified_at TEXT;   -- nullable
ALTER TABLE users ADD COLUMN phone_verified_at TEXT;   -- nullable (phone column already exists)

CREATE TABLE IF NOT EXISTS auth_passwords (
    id TEXT PRIMARY KEY,
    internal_user_id TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    disabled_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_auth_passwords_user ON auth_passwords(internal_user_id) WHERE disabled_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_auth_passwords_user ON auth_passwords(internal_user_id);

CREATE TABLE IF NOT EXISTS password_reset_challenges (
    id TEXT PRIMARY KEY,
    internal_user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    created_at TEXT NOT NULL,
    ip_address TEXT,
    user_agent_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_pwd_reset_user ON password_reset_challenges(internal_user_id);
CREATE INDEX IF NOT EXISTS idx_pwd_reset_expires ON password_reset_challenges(expires_at);
```
All additive (`ADD COLUMN` nullable, `CREATE TABLE/INDEX IF NOT EXISTS`); no DROP, no
rename, no `users.id` change. Fits the existing `init_db()` additive pattern.

## 8. Frontend UX proposal
`AuthV2Modal` becomes platform-aware:
- **Browser:** tabs **Вход / Регистрация**.
  - Login: email, password, "Войти", "Создать аккаунт" (switch tab), "Забыли пароль?"
    (disabled/"скоро" until reset shipped).
  - Register: email, password, repeat password, consent block, "Создать аккаунт".
  - Errors generic ("Неверная почта или пароль"); no existence disclosure.
- **Telegram:** primary "Войти через Telegram" (or silent); email/password under
  "Другой способ".
- **MAX:** primary "Войти через MAX" (or silent); email/password under "Другой способ".
Email OTP demoted (kept only if/when an email provider is wired).

## 9. Implementation phases
- **14.4** — password schema (additive) + hashing helpers + isolated tests.
- **14.5** — register/login-v2 endpoints + cookies + tests (forgot/reset designed only).
- **14.6** — frontend password login/register modal (browser).
- **14.7** — Telegram/MAX platform-first modal behavior (+ optional silent login).
- **14.8** — auth UX + live smoke.
- **15** — backend generation protection (gate /api/generate on trusted session).

## 10. Decisions needed from owner
1. **email+password**: confirm yes (recommended) for browser.
2. **phone**: now or later (recommended: later).
3. **consent checkbox**: unchecked checkboxes vs explicit "Создать аккаунт и принять
   условия" button (recommended: explicit button + links, no pre-check).
4. **email provider**: connect now (enables OTP + forgot/reset + anti-enumeration) or
   later (recommended: later; ship password first).
5. **Telegram/MAX silent login**: auto-login on detect, or show an explicit button
   (recommended: explicit button first; silent later).
6. **password hashing**: PBKDF2 stdlib (no dep) vs Argon2id (`argon2-cffi`, needs dep
   approval) — recommended: PBKDF2 now, Argon2id-ready via `algorithm` column.
7. **register-when-email-exists**: 409 generic now vs always-200+email (needs provider).
