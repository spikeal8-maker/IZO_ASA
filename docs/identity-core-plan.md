# Identity Core — Migration Plan

Safe, phased replacement of the weak user/login layer with a strong Identity/Auth core,
without rebuilding the project and without breaking the running app.

---

## 1. Current identity/auth problem

The project currently has no trustworthy identity layer:

* `request_user_id()` derives the current user from the `X-OneNode-User` header or the
  `onenode_user` cookie. Both are client-controlled, so any caller can claim any
  `user_id` — including an admin id. This is a full authentication and authorization bypass.
* The `onenode_user` cookie is set with `httponly=False`, so it is readable/writable from
  page JavaScript.
* `users.id` is a provider-based string (`telegram_xxx` / `max_xxx` / `web_xxx`). The provider
  user id is effectively used as the internal user id, which means the same person signing in
  via two providers becomes two different users (duplicate accounts), and there is no single
  canonical identity.
* MAX `userId` is accepted from the client without any server-side `WebAppData` signature
  validation, so MAX identity is currently untrusted.
* Telegram has server-side `initData` validation, but `bootstrap` silently falls back to a
  `web` identity when `initData` is empty, weakening the guarantee.
* There is no concept of server-issued sessions, refresh tokens, OTP, security events, or
  admin audit logs. Secrets (provider tokens, admin code) are simple values.

Goal: introduce a real Identity Core that becomes the trusted layer **gradually**, without a
second parallel auth system and without destructive changes to existing data.

## 2. Why `users.id` cannot be changed immediately

`users.id` is the primary key of the `users` table and is referenced as a logical foreign key
throughout the app:

* `jobs.user_id`, `images.user_id`, `token_ledger.user_id` all store the legacy `users.id`.
* The frontend persists it in `localStorage('onenode_user')` and sends it back via header/cookie.
* Bootstrap, generation, gallery, tokens, heartbeat and admin flows all key off it.

Rewriting `users.id` in place (rename / mass UPDATE / PK swap) would require touching every
dependent row and the frontend simultaneously — a high-risk, hard-to-reverse change on a live
SQLite file. Instead we keep `users.id` stable and introduce a new canonical id additively, then
migrate consumers later, one phase at a time.

## 3. Transitional identity model

We keep the legacy id and layer the canonical identity beside it. New tables are additive only.

* **`users.id`** — legacy provider-based id (`telegram_xxx` / `max_xxx` / `web_xxx`). Stays stable.
* **`users.internal_user_id`** — new canonical, provider-independent identity id (opaque/UUID).
  Added via `ALTER TABLE ADD COLUMN`; backfilled idempotently from existing rows.
* **`auth_identities`** — maps `(provider, provider_user_id)` → `internal_user_id`
  (UNIQUE on `provider` + `provider_user_id`). Prevents duplicate users for the same provider
  identity and allows linking multiple providers to one canonical user.
* **`auth_sessions`** — trusted, server-issued sessions. Maps a session (stored as a token
  **hash**) to `internal_user_id` and the legacy `users.id`. Supports expiry and revocation.
* **`session_events`** — lifecycle of sessions (created, refreshed, revoked, expired) for
  observability.
* **`auth_login_attempts`** — record of login attempts per provider/identity for rate limiting
  and abuse detection.
* **`device_installations`** — known devices/installs tied to `internal_user_id`
  (platform, app surface), without storing raw secrets.
* **`user_consents`** — consent records (terms, privacy, etc.) per `internal_user_id`.
* **`security_events`** — security-relevant events, especially auth failures and suspicious
  activity. Never contains raw tokens/OTP/initData/WebAppData.
* **`audit_logs`** — admin mutations (who changed what, when), for accountability.

Refresh tokens and OTP codes are stored only as hashes (table shapes defined when their phase
lands). Existing `jobs`/`images`/`token_ledger` continue to use legacy `users.id` until a later,
explicitly approved migration.

## 4. Implementation phases

Each phase is small, additive, reversible, and ships with tests. Do not start a phase before
the previous one is approved.

* **Phase 1 — Additive schema (this phase is docs/rules only; schema lands next).**
  Define rules and plan. Then add `users.internal_user_id` and the new tables via additive
  SQLite changes inside `init_db()`, with idempotent backfill. No behavior change yet.
* **Phase 2 — Session service.** Server-side session issuance/verification: cryptographically
  secure tokens, store only hashes, expiry + revocation, `session_events`.
* **Phase 3 — Bootstrap-v2.** New bootstrap path that issues a trusted session and returns
  `internal_user_id`, running alongside the legacy bootstrap (no removal yet).
* **Phase 4 — Telegram auth v2 (strict).** No valid `initData` ⇒ no Telegram auth. Remove the
  silent fallback to `web`. Failures write `security_events`.
* **Phase 5 — MAX auth v2 (strict).** Server-side `WebAppData` signature validation required
  before any MAX identity is trusted. Failures write `security_events`.
* **Phase 6 — Email OTP v2.** OTP login with hashed OTP storage, attempt limits via
  `auth_login_attempts`. (No real email/SMS sending until explicitly approved.)
* **Phase 7 — Trusted `request_user`.** Resolve the current user from the trusted session
  instead of `X-OneNode-User`/cookie, behind compatibility until cutover.
* **Phase 8 — Profile / devices / consents.** Wire `device_installations` and `user_consents`,
  expose minimal profile read/update on the trusted identity.
* **Phase 9 — Admin hardening.** `require_admin()` based on trusted session/role; admin
  mutations write `audit_logs`.
* **Phase 10 — Minimal frontend migration.** Smallest possible `App.tsx` change to stop relying
  on client-set identity and use the trusted session.
* **Phase 11 — Security hardening.** Cookie flags, logging hygiene, session revocation/expiry
  enforcement, banned-user refresh denial, negative-test coverage.
* **Phase 12 — Final docs.** Update plan/risks/rules to reflect the shipped state.

## 4.1. Cookie environment rule

Trusted auth cookies must keep production security on the public HTTPS domain, but local HTTP
must still be testable:

* `https://izo.alikinas.ru`: use env values (`Secure=true`, `SameSite=None`).
* `http://localhost`, `http://127.0.0.1`, `http://[::1]`: downgrade only the cookie transport
  to `Secure=false`, `SameSite=lax`, based on the incoming request host/scheme.

This rule is implemented centrally in `trusted_cookie_common(request)` and must be reused for
session, refresh and bot-login challenge cookies. See
`docs/auth-cookie-local-production-guide-20260708.md`.

## 5. Out of scope right now

The following are explicitly **not** part of this migration at this time:

* PostgreSQL migration.
* ORM introduction.
* Destructive `users.id` migration.
* Public feed.
* Payments.
* Full gallery refactor.
* Full templates refactor.
