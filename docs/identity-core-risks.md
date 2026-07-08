# Identity Core — Risk Register

Risks that the phased Identity Core migration must address, with mitigations. References are to
the current code in `backend/main.py` and `frontend/src/App.tsx`.

---

## 1. `X-OneNode-User` spoofing

**Risk.** `request_user_id()` reads the `X-OneNode-User` header (and `onenode_user` cookie) and
trusts it as the current user. Any client can set this header to any value, including an admin
id, fully bypassing authentication and authorization (`require_admin()` keys off the same value).

**Mitigation.** Introduce server-issued trusted sessions (Phase 2). Resolve the current user
from the session, not from client headers (Phase 7). Keep legacy behavior only behind a
compatibility path until cutover; cover with a spoofing negative test.

## 2. JS-readable `onenode_user` cookie

**Risk.** The `onenode_user` cookie is set with `httponly=False`, so page JavaScript (and XSS)
can read and overwrite it. It is treated as identity, so it is an impersonation vector.

**Mitigation.** Move identity to an httponly, server-signed session cookie/token whose value is
stored only as a hash server-side (Phases 2, 11). Stop treating the legacy cookie as
authentication.

## 3. MAX without signature

**Risk.** MAX `userId` is accepted from the client with no server-side `WebAppData` signature
check, so MAX identity is forgeable.

**Mitigation.** Require server-side `WebAppData` signature validation before trusting any MAX
identity (Phase 5). Reject unsigned/invalid data; write `security_events` on failure. Add a test
asserting unsigned MAX auth fails.

## 4. Telegram fallback on empty `initData`

**Risk.** `bootstrap` validates Telegram `initData`, but when `initData` is empty it silently
falls back to a `web` identity and accepts the client-supplied `userId`, weakening the Telegram
guarantee.

**Mitigation.** Make Telegram auth strict (Phase 4): no valid `initData` ⇒ no Telegram auth, no
fallback that accepts client identity. Write `security_events` on invalid attempts. Add a test
asserting Telegram without valid `initData` fails.

## 5. Provider-based `users.id`

**Risk.** `users.id` is `telegram_xxx` / `max_xxx` / `web_xxx`, i.e. the provider user id is used
as the internal id. The same person across providers becomes multiple users (duplicates), and
there is no single canonical identity.

**Mitigation.** Introduce `users.internal_user_id` additively and `auth_identities` with a UNIQUE
`(provider, provider_user_id)` mapping to the canonical id (Phases 1–2). Repeated provider login
must reuse the same `internal_user_id` (covered by test). Keep legacy `users.id` stable.

## 6. SQLite destructive migration

**Risk.** A migration that drops/renames columns, rewrites the `users` table, or mass-updates
`users.id` on the live SQLite file could corrupt or lose existing `users`/`jobs`/`images`/
`token_ledger` data and is hard to reverse.

**Mitigation.** Additive-only changes (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`,
safe `ALTER TABLE ADD COLUMN`). No `DROP`, no rename of `users.id`, no mass update. Keep `init_db`
idempotent; require a backup before any migration; never touch the production DB. See
`.claude/rules/sqlite-migrations.md`.

## 7. Secrets in `backend/.env`

**Risk.** `backend/.env` contains real provider tokens and an admin code. Exposure (commit,
log, screenshot) leaks credentials; logging raw tokens/initData/WebAppData would compound it.

**Mitigation.** Never log tokens, cookies, `Authorization` headers, OTP, passwords, or full raw
`initData`/`WebAppData` (see `.claude/rules/security.md`). Do not modify `.env` in code phases.
Treat credential rotation as an owner action outside this migration. Store all auth secrets
(session/refresh/OTP) only as hashes.

## 8. Two parallel auth systems

**Risk.** Adding a new Identity Core beside the old one without a cutover plan yields two
competing notions of "current user," causing inconsistent authorization and security gaps.

**Mitigation.** The new Identity Core must become the trusted layer **gradually** (Phases 3, 7,
9, 10), not as a permanent parallel system. Each phase narrows reliance on the legacy path until
cutover; no long-lived duplicate auth. See Implementation Rules in `CLAUDE.md`.

## 9. Mass refactor of `backend/main.py`

**Risk.** `backend/main.py` is a single large monolith holding identity, auth, admin, migrations
and generation. A broad refactor (splitting into many modules, reordering) risks breaking
unrelated, working features (generation, gallery, tokens, templates).

**Mitigation.** Do not split `main.py` unless explicitly approved. Make surgical, localized
edits per phase, preserving existing data and behavior. Every security-sensitive change ships
with tests; keep compatibility with the current project.

## 10. Production cookie flags breaking local login

**Risk.** Production cookie flags (`Secure=true`, `SameSite=None`) are correct for HTTPS, but
on local HTTP the browser will not persist/send the trusted session cookie. The login endpoint
can return success while `/api/me-v2` immediately sees an anonymous user.

**Mitigation.** Keep env production flags intact, but derive actual cookie transport flags from
the incoming request in `trusted_cookie_common(request)`: local HTTP uses `Secure=false` and
`SameSite=lax`; public HTTPS keeps the production values. Reuse the helper for session,
refresh and bot-login cookies. See `docs/auth-cookie-local-production-guide-20260708.md`.

## 11. Mitigation summary

| # | Risk | Primary mitigation | Phase(s) |
|---|------|--------------------|----------|
| 1 | `X-OneNode-User` spoofing | Trusted server sessions; resolve user from session | 2, 7 |
| 2 | JS-readable cookie | httponly signed session; hash stored server-side | 2, 11 |
| 3 | MAX without signature | Server-side `WebAppData` validation; reject unsigned | 5 |
| 4 | Telegram empty-`initData` fallback | Strict Telegram auth, no fallback identity | 4 |
| 5 | Provider-based `users.id` | Additive `internal_user_id` + `auth_identities` UNIQUE | 1, 2 |
| 6 | SQLite destructive migration | Additive-only, backups, idempotent `init_db` | 1 |
| 7 | Secrets in `.env` | No secret logging; only hashes stored; no `.env` edits | all |
| 8 | Two parallel auth systems | Gradual cutover to single trusted layer | 3, 7, 9, 10 |
| 9 | Mass `main.py` refactor | Surgical edits only; no unapproved module split | all |
| 10 | Secure production cookies on local HTTP | Request-aware cookie flags; no env weakening | 11 |
