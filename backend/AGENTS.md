# Backend scoped policy

Root `AGENTS.md` and `AI_START_HERE.md` remain mandatory. This file owns only
rules for `backend/**`; it does not own reading order, current status or backlog.

## Composition and service boundaries

- `backend/main.py` is a frozen compatibility/composition shell. New business
  logic belongs in cohesive `backend/app/*` modules; move behavior only behind
  characterization/regression coverage.
- Keep routes, services, storage, integrations and background work separated by
  responsibility. Do not introduce a second application/container architecture
  inside an ordinary backend package.
- Use generated architecture/symbol evidence and bounded ranges before reading
  `backend/main.py` or other protected hotspots broadly.

## Data and migrations

- Production SQLite/WAL/SHM and media are never tests or scratch state.
- Tests use temporary database, media and secret roots.
- Schema changes are additive and versioned in
  `backend/app/database/migrations.py`; never reuse an applied migration
  version/name or alter an applied checksum.
- Destructive data migration needs a separate owner-approved maintenance
  package, verified backup and rehearsed rollback.
- Keep one live SQLite writer application process. Copy live SQLite only through
  the Backup API/repository backup tools, never normal file copy.

## Identity, APIs and media

- Never trust `X-OneNode-User`, `onenode_user`, frontend `user_id`, unsigned
  Telegram data or unverified MAX data as identity.
- Protected routes resolve a trusted server session. Admin routes use
  `require_trusted_admin`; admin mutations are auditable.
- Do not build a second authentication system. Legacy compatibility moves only
  through characterization and migration packages.
- Public APIs must not leak absolute paths, internal URLs, secret/config
  presence, TLS/proxy detail, stack traces or operator diagnostics.
- Private media access is owner-checked; public derivatives are explicit
  surfaces with lifecycle coverage.

## Providers, jobs and workers

- Tests fake Telegram, MAX, YooKassa, UniSender, SMTP, OpenRouter, ComfyUI and
  Ollama. They must not send, charge or mutate real provider state.
- Payment and webhook mutations stay authenticated, idempotent, transactional
  and auditable.
- Telegram/MAX polling and webhook delivery require one owner and explicit
  handoff; never reset cursors, delete webhooks or rotate tokens automatically.
- Persistent workers declare owner, process role, durable state, startup,
  recovery/retry, idempotency and watchdog behavior in architecture evidence.
- In-process queues wake work; durable DB state remains source of truth across
  restart. Worker health needs recent success/failure evidence, not just a task.

## Backend verification

- Новые `test_*.py`: обычный предел из архитектурного контракта — 500 строк и дополнительный лимит 24 КиБ; до 750 строк/36 КиБ требуется `sizeReviews` текущего Task Contract. Старые превышения не увеличивать. Подробности: `docs/testing-file-standards.md`.

- Extend the nearest backend test module rather than broad unrelated suites.
- Auth, billing, migrations, durable workers and concurrent storage use
  high-assurance characterization plus focused race/idempotency repetition.
- Regenerate backend/architecture evidence when its scanned contract changes.
