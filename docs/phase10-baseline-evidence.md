# Phase 10 / 10.1 — Baseline Evidence Lock

Machine-verifiable baseline captured after Admin v2 (Phase 10) and its audit (10.1).
The project is not a git repository and lives under a Google Drive sync path, so
working-DB file hashes can drift from external rewrites. This document records
reproducible checks (route table, source guards, static field scan, SQL safety,
and a strong DB-isolation snapshot) rather than relying on mtime/hash alone.

Generated: 2026-06-25. All checks are read-only / isolated; no production code,
DB, or config was modified to produce this report.

## 1. File integrity baseline (SHA-256, first 16 hex)

| file | exists | size_bytes | sha256_prefix | mtime |
|------|--------|-----------|---------------|-------|
| backend/main.py | yes | 189784 | dbd3d2327731cddc | 06-25 21:07 |
| backend/test_admin_v2.py | yes | 12180 | 0aed634891d2d636 | 06-25 21:26 |
| backend/test_trusted_user_v2.py | yes | 10272 | 36d1d2aff609b77a | 06-25 21:01 |
| backend/test_auth_sessions.py | yes | 15510 | 50558675453863db | 06-25 20:01 |
| backend/test_identity_schema.py | yes | 9314 | f5423875091c23a7 | 06-25 19:47 |
| frontend/src/App.tsx | yes | 193803 | e6f9a621dd83d850 | 06-25 19:21 |
| backend/requirements.txt | yes | 128 | 7b07478d31c80211 | 06-21 16:44 |
| CLAUDE.md | yes | 2949 | 94a53a018d468601 | 06-25 19:35 |
| .claude/rules/security.md | yes | 757 | 719933d2b84bdb07 | 06-25 19:35 |
| .claude/rules/backend-identity.md | yes | 755 | 775fbe173978aec5 | 06-25 19:35 |
| .claude/rules/sqlite-migrations.md | yes | 602 | aff962568a1f34b1 | 06-25 19:35 |

mtime is an auxiliary signal only. `frontend/src/App.tsx` (19:21), `.env` (19:28),
`requirements.txt` (16:44) all predate Phase 10 (~21:07) → untouched by Admin v2.

## 2. Route table (admin-v2 = exactly 6)

| method | path | endpoint |
|--------|------|----------|
| GET | /api/admin/users-v2 | admin_users_v2 |
| GET | /api/admin/users/{internal_user_id}/v2 | admin_user_detail_v2 |
| GET | /api/admin/security-events-v2 | admin_security_events_v2 |
| GET | /api/admin/audit-logs-v2 | admin_audit_logs_v2 |
| POST | /api/admin/users/{internal_user_id}/block-v2 | admin_block_user_v2 |
| POST | /api/admin/users/{internal_user_id}/unblock-v2 | admin_unblock_user_v2 |

- create-admin-v2: **absent** · token-adjustment-v2: **absent** · payment/subscription admin: **absent**
- legacy `/api/admin/summary`, `/api/admin/users` still registered (unchanged).

## 3. Source guard proof

| function | has_require_trusted_admin | calls_legacy_request_user | calls_legacy_require_admin | reads_x_header | reads_legacy_cookie | pass |
|----------|---------------------------|---------------------------|----------------------------|----------------|---------------------|------|
| admin_users_v2 | yes | no | no | no | no | PASS |
| admin_user_detail_v2 | yes | no | no | no | no | PASS |
| admin_security_events_v2 | yes | no | no | no | no | PASS |
| admin_audit_logs_v2 | yes | no | no | no | no | PASS |
| admin_block_user_v2 | yes | no | no | no | no | PASS |
| admin_unblock_user_v2 | yes | no | no | no | no | PASS |

## 4. Sensitive-field static proof (admin-v2 response/SQL code)

| field | found_in_admin_response_code | pass |
|-------|------------------------------|------|
| session_token_hash | no | PASS |
| refresh_token_hash | no | PASS |
| code_hash | no | PASS |
| raw_profile_json | no | PASS |
| Authorization | no | PASS |
| cookie | no | PASS |
| session_token | no | PASS |
| refresh_token | no | PASS |
| otp | no | PASS |
| password | no | PASS |

## 5. SQL parameterization proof

- Dynamic SQL interpolates only the pre-built `{where}` fragment (constant clause
  strings). User values for provider / platform / q / status / event_type /
  internal_user_id / actor / target / action / limit / offset are bound as `?`.
- `f"%{q}%"` builds the LIKE *value* (bound as a parameter), not SQL structure.
- Path param `internal_user_id` is bound via `WHERE internal_user_id = ?` (no
  f-string embedding).
- `limit` clamped via `_clamp_limit` (default 50, max 200); `offset` normalized
  via `max(0, int(offset))`.

## 6. DB isolation proof (strong)

Snapshot immediately before and after the isolated suite (same process window):

| metric | before | after |
|--------|--------|-------|
| sha256 (prefix) | ec094f53593fd74f | ec094f53593fd74f |
| size_bytes | 97079296 | 97079296 |
| tables | 9 legacy | 9 legacy (unchanged) |
| users columns | 29, no internal_user_id | unchanged |

Real-DB tables: admin_settings, images, jobs, loras, model_profiles, presets,
promo_codes, token_ledger, users. Identity/admin-v2 tables in real DB: none.
`internal_user_id` in users: no.

Conclusion: in this measurement window the working DB is byte-identical and
schema-identical before/after — provably untouched by the tests. Earlier in the
session the hash drifted while schema stayed constant ("external file rewrite
suspected" — Google Drive sync). Recommendation: before any real migration, move
`backend/onenode.sqlite3` out of the Google Drive sync path (or pause sync) so the
migration's file-hash evidence is trustworthy.

## 7. Test coverage map (requirement → test)

| requirement | test |
|-------------|------|
| no session -> 401 | test_admin_v2_without_session_401 |
| non-admin -> 403 | test_admin_v2_non_admin_403 |
| X-OneNode-User spoof denied | test_x_onenode_user_spoof_does_not_grant_admin |
| legacy cookie spoof denied | test_cookie_spoof_does_not_grant_admin |
| static admin code does not grant admin-v2 | (by construction: require_trusted_admin has no code path; covered by guard proof §3 + 401/403 tests) |
| trusted admin list users | test_admin_can_list_users_no_secrets |
| user list no token hashes | test_admin_can_list_users_no_secrets |
| user detail no token hashes | test_admin_user_detail |
| security events admin-gated | test_security_events_requires_admin |
| audit logs admin-gated | test_audit_logs_requires_admin |
| block requires reason | test_block_requires_reason |
| block forbids self-block | test_block_forbids_self_block |
| block sets banned | test_block_sets_banned_revokes_sessions_and_logs |
| block revokes sessions | test_block_sets_banned_revokes_sessions_and_logs |
| block writes audit_logs | test_block_sets_banned_revokes_sessions_and_logs |
| block writes security_events | test_block_sets_banned_revokes_sessions_and_logs |
| blocked user cannot refresh | test_blocked_user_cannot_refresh |
| unblock requires reason | test_unblock_flow |
| unblock sets banned=0 | test_unblock_flow |
| unblock writes audit_logs | test_unblock_flow |
| unblock does not restore sessions | test_unblock_flow |
| q filter injection-safe | test_users_list_q_filter_is_injection_safe |
| limit clamped | test_users_list_limit_clamped |
| old admin endpoints unchanged | test_old_admin_and_require_admin_unchanged |
| old require_admin unchanged | test_old_admin_and_require_admin_unchanged |
| real DB untouched | Block 6 snapshot (this document) |

## 8. Recommendations before next phase

1. **Initialize git** in the project root so future phases have real, tamper-evident
   diffs instead of mtime/hash heuristics.
2. **Move `backend/onenode.sqlite3` out of Google Drive** (or pause sync) before the
   first real `init_db()` migration, so DB evidence is not muddied by external rewrites.
3. Keep the `admin_user_summary` output whitelist; it shields `SELECT *` on `users`
   from leaking any future sensitive column.
