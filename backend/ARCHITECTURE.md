# Backend architecture map

This document describes the current backend before the incremental split of `main.py`.
It is a navigation aid, not a new architecture contract. Runtime behavior remains defined by code and tests.

## Runtime entrypoint

- ASGI object: `backend/main.py::app`.
- Public launcher starts one Uvicorn process on `127.0.0.1:8000`.
- Startup runs DB preflight, session crypto validation, additive `init_db()`, DB Guard verification, state loading and background workers.
- The live SQLite database and media stay local to this computer.
- The existing external domain tunnel is outside the optimization scope.

## Current state and persistence

| Area | Current source of truth | In-memory state |
|---|---|---|
| Users, identities, sessions | SQLite | selected caches only |
| Jobs | SQLite | `jobs` mirror and `asyncio.Queue` for active work |
| Images/gallery | SQLite + `backend/media` | `images` mirror |
| Feed | SQLite + media derivatives | request-time payloads |
| Token balances/ledger | SQLite | none authoritative |
| Admin settings | SQLite | selected TTL caches |
| Rate limits | mixed: SQLite for OTP, process memory for some generation limits | process local |
| Provider status | providers + short process caches | process local |

## Major responsibilities still in `main.py`

1. Environment/configuration and path setup.
2. Pydantic request/response models.
3. SQLite connection, schema and additive migrations.
4. Identity, sessions, passwords, OTP and permissions.
5. Security/audit/product event recording.
6. Users, account profile and admin CRM.
7. Tariffs, token ledger, promos, referrals and billing records.
8. Media ownership, gallery storage and cleanup/recovery.
9. Generation queue and job lifecycle.
10. ComfyUI workflow construction and result handling.
11. Remaining OpenRouter/Ollama/Telegram/MAX integration orchestration.
12. Gallery, feed, admin and bot routes.

## Existing extracted module

- `backend/resolution_policy.py` owns canonical image resolutions and provider capability mapping.
- `backend/app/config.py` owns import-safe environment and database-path parsing helpers.
- `backend/app/database/connection.py` owns the SQLite connection policy.
- `backend/app/database/guard.py` owns import-safe DB Guard checks; `main.py` retains compatibility wrappers while the split continues.
- `backend/app/database/migrations.py` owns validated additive-column primitives and column declarations used by the legacy initializer.
- `backend/app/database/schema.py` owns import-safe SQL schema declarations; execution and seed/backfill order remain in `main.init_db()` during the incremental split.
- `backend/app/security/tokens.py` owns opaque token generation, HMAC/SHA-256 hashing and production secret validation.
- `backend/app/security/passwords.py` owns the Argon2id policy, hashing, verification and dummy timing hash; `main.py` keeps compatibility wrappers.
- `backend/app/security/sessions.py` owns create/resolve/refresh/revoke through an injected runtime; it does not import FastAPI or application globals.
- `backend/app/security/permissions.py` owns trusted-user resolution, legacy-header spoof auditing and the admin role gate; HTTP error mapping remains in `main.py`.
- `backend/app/security/otp.py` owns OTP generation/hash, production configuration validation, mock delivery, stale-challenge cleanup and request rate limits through an injected runtime.
- `backend/app/security/events.py` owns session, security, login-attempt and product-event persistence; callers remain responsible for passing only sanitized metadata.
- `backend/app/storage/paths.py` owns canonical root containment, private-media URL parsing and compatibility URL creation; filesystem deletion, cleanup and recovery remain separate follow-up packages.
- `backend/app/storage/private_media.py` owns trusted-owner resolution for canonical and legacy private media URLs; filename matching is exact apart from an optional query string.
- `backend/app/storage/public_media.py` owns the narrow public surfaces for referenced custom avatars and ready assets belonging to published feed rows.
- `backend/app/storage/maintenance.py` blocks startup cleanup/repair/optimization inside pytest and supports an explicit operational disable flag.
- `backend/app/storage/cleanup.py` removes orphan source metadata rows but never deletes files; file candidates must go through audited quarantine.
- `backend/app/storage/recovery.py` owns scoped, idempotent source availability reconciliation and unavailable-thumbnail repair through injected parsing, thumbnail and URL adapters.
- `backend/app/storage/source_graph.py` owns recursive gallery source-tree reads, owner-scoped repair decisions, transactional source metadata persistence and ordered source file/row deletion; request parsing, thumbnail creation and path operations stay injected from `main.py`.
- `backend/app/storage/source_thumbnails.py` owns data-URL/local-media decoding, EXIF normalization and bounded WEBP source-thumbnail creation; the legacy persistence/recovery callers keep a thin `_save_source_thumb()` adapter.
- `backend/app/storage/source_inputs.py` owns deterministic source-role labels and generation source normalization, including edit ordering, mode-specific roles, slot assignment, the eight-input cap and legacy deduplication semantics.
- `backend/app/storage/media_references.py` owns exact canonical/legacy media-reference matching for active images, active source rows and URL strings inside valid job JSON; filename substrings never establish ownership.
- `backend/app/storage/input_validation.py` owns owner-scoped generation media validation and typed `missing`/`unavailable` errors; `main.py` only collects request fields and maps typed errors to HTTP 400.
- `backend/app/integrations/ollama.py` owns Ollama base-URL normalization, bounded `/api/tags` discovery and the shared `/api/chat` HTTP/response parsing boundary used by prompt improvement and voice transcription; `main.py` still owns request bodies, timeout policy, concurrency, application parsing, audio-model guards and voice preprocessing.
- `backend/app/integrations/openrouter.py` owns text-model catalog, key/credits, shared `/chat/completions`, image-model/endpoint document collection with bounded concurrency, pure model/endpoint capability normalization, generation response parsing, public error mapping and safe image-response metadata normalization; `main.py` retains compatibility wrappers, API-key/header/source policy, caches, endpoint selection and generation orchestration.
- `backend/app/integrations/openrouter_images.py` owns model-alias resolution, safe request-metadata assembly, pure orientation/aspect-ratio/descriptor/provider request planning and image request-body assembly; application resolution IDs/tiers are passed through compatibility wrappers and local-reference values through callback injection.
- `backend/app/integrations/openrouter_image_io.py` owns remote/data reference passthrough, application-resolved local-file encoding, and response b64/URL loading into PIL; `main.py` retains the production path resolver, timeout, gallery persistence and generation orchestration.
- `backend/app/integrations/openrouter_image_client.py` owns POST `/images`, JSON parsing and the exact one-time `size=auto` retry; `main.py` injects headers, size-error classification and the callback that persists fallback job state before retry.
- `backend/conftest.py` redirects every backend test to a temporary SQLite database, media root and avatar root even when a test forgot its own fixture.
- Keep it independent of FastAPI, SQLite and provider network calls.

## Security boundaries

- New protected routes must use `require_trusted_user()` or `require_trusted_admin()`.
- `X-OneNode-User` and `onenode_user` are legacy identity inputs and must not authorize protected routes.
- Raw session/refresh tokens, OTP, passwords, bot tokens and provider keys must not be logged.
- Private media requires both a trusted session and an ownership check.
- Admin mutations require audit records.

## Dependency direction for extraction

```text
routers → services → repositories/storage/integrations
                    ↓
              database/config
```

- `config` must not import application modules.
- `database` may import config, but must not import routers.
- `security` may use database repositories and config.
- `services` must not depend on FastAPI `Request`/`Response` objects.
- `routers` perform transport validation, authorization dependency calls and response mapping.
- `integrations` do not decide user ownership or token billing.

## Safe extraction order

1. Configuration.
2. Database connection and DB Guard.
3. Schema/migrations.
4. Security/authentication.
5. Media storage.
6. Provider integrations one at a time.
7. Services.
8. Routers.
9. Application factory/lifecycle.

## Generated navigation

Run from the repository root:

```powershell
python tools/generate_backend_map.py
python tools/generate_backend_map.py --check
```

`backend/SYMBOL_MAP.md` lists top-level classes, functions, routes and a conservative static authorization hint. Rows marked `REVIEW` require a code/test review; the generator does not prove security.
