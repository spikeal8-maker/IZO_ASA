# IZO_ASA repository rules for every coding agent

This file is the repository-wide source of truth for Codex, Claude, Copilot,
Gemini and any other automation that changes this project. Tool-specific files
may add instructions, but they may not weaken or contradict this file.

## 1. Scope and canonical workspace

- The only canonical integration and deployment source on this computer is
  `E:\IZO_ASA_WORKSPACE`.
- `E:\Yandex.Disk\IZO_ASA` is a quarantined historical copy affected by live
  `.git` synchronization conflicts. Do not use it for Git operations, testing,
  deployment or recovery, and do not delete, rename or repair it without a
  separate owner-authorized cleanup package.
- `E:\Yandex.Disk` may be an offsite synchronization target only for immutable,
  versioned backup snapshots. It must never synchronize a live `.git`
  directory, open SQLite database or WAL/SHM, production media working state,
  runtime manifests or secrets.
- Do not delete files or directories from `E:\Yandex.Disk` during project
  implementation, synchronization or deployment.
- Do not deploy from a sibling copy, attachment, temporary worktree or resolved
  symlink target. Inspect `git worktree list` and resolve reparse points when the
  source is uncertain.
- The application stack runs on this Windows computer. The VPS carries only the
  existing domain tunnel. Do not change VPS, FRP, DNS or tunnel configuration
  without an explicit owner request.
- Preserve unrelated user and agent work. Never discard, reset or overwrite a
  dirty worktree to make a package easier to merge.

## 2. Mandatory preflight and ownership

Before changing files:

1. Read this file and any narrower `AGENTS.md` in the target directory.
2. Record `git status --short --branch`, `git rev-parse HEAD`,
   `git rev-parse origin/main` and `git worktree list`.
3. Check for active `pytest`, `verify.ps1`, `start-public`, publisher and deploy
   processes before starting another expensive or mutating operation.
4. Identify live runtime data and keep tests away from it.
5. If another agent owns overlapping files or a release, coordinate first. Do
   not race it.

There must be a single release owner. Until the repository operation lock from
`REL-LOCK-001` is implemented, no agent may run `start-public.bat`, a frontend
publisher, a backend restart or a second Full verification while another such
operation is active.

## 3. Production and data safety

- Production DB, WAL/SHM, media, secrets, models and runtime manifests are not
  test fixtures. Tests must use temporary paths and fake providers.
- Never copy an open SQLite file with a normal file copy. Use the SQLite Backup
  API and the repository backup/restore tools.
- Never delete or rewrite `backend/onenode.sqlite3`, `backend/media`, `.runtime`
  or external backup roots during ordinary implementation.
- Schema changes are additive and versioned through
  `backend/app/database/migrations.py`. Never reuse a migration version/name or
  change an applied checksum. Destructive migration needs an explicit,
  rehearsed maintenance package and verified backup.
- Keep a single SQLite writer application process. Do not start a second live
  backend against the same database.
- A restart or deploy is allowed only when the requested task needs it, the
  source is clean and verified, and the user has authorized production change.
  Documentation, analysis and ordinary tests do not authorize a deploy.

## 4. Secrets and external providers

- Secrets never enter Git, logs, screenshots, chat, API responses or test
  snapshots. On Windows, use environment overrides or the repository DPAPI
  secret store outside the repository. DPAPI material is account- and
  computer-bound and must be re-entered on a new host.
- Automated tests use fake Telegram, MAX, YooKassa, UniSender, SMTP, OpenRouter,
  ComfyUI and Ollama adapters. They must not charge money, send real email,
  consume paid generation or mutate real bot state.
- A real payment, refund, email send, webhook switch or token rotation requires
  an explicit operator action and a redacted receipt.
- Payment/webhook processing must be authenticated, idempotent and auditable.
  Financial state changes belong in one transaction service, not route-local SQL.

## 5. Authentication, privacy and public APIs

- Never trust `X-OneNode-User`, `onenode_user`, frontend `user_id`, unsigned
  Telegram data or unverified MAX data as identity.
- Protected routes resolve a trusted server-side session. Admin routes use
  `require_trusted_admin`; every admin mutation writes an audit event.
- Do not create a second auth system. Legacy compatibility paths are frozen and
  must be removed through explicit characterization and migration packages.
- Public endpoints expose only product-safe fields. They must not reveal
  absolute paths, provider token presence, internal service URLs, TLS/proxy
  details, stack traces, database statistics or operator diagnostics.
- Private media access is owner-checked. Public feed derivatives and public
  avatars are separate, deliberate surfaces. New media lifecycle tests cover
  publish, private-source deletion and public read behavior.
- User-facing model branding remains `Flux2`; technical model filenames and
  workflow identifiers are internal/admin-only.

## 6. Bots and background workers

- Exactly one delivery owner exists per Telegram/MAX bot. Polling and webhook
  delivery must never be active simultaneously unless a documented handoff
  protocol makes the overlap impossible.
- Do not automatically delete a webhook, reset an update cursor or rotate a
  token. Those are explicit operator actions.
- Every persistent worker declares owner, process role, durable state, startup,
  retry/recovery, idempotency and watchdog behavior in the architecture map.
- In-process queues are wake-up mechanisms, not the source of truth. Jobs,
  publications, financial events and mail obligations must survive restart in
  SQLite until a measured scale trigger justifies another queue.
- Worker health claims require recent success/failure timestamps, not merely a
  running process or configured token.

## 7. Architecture and large-file policy

- The project remains a modular monolith. Do not rewrite it into microservices
  and do not migrate to Docker/Linux/PostgreSQL merely for style.
- `backend/main.py` is frozen as a compatibility/composition shell. Put new
  business logic in `backend/app/*`; new route groups use routers or thin
  adapters. Move behavior only behind characterization tests.
- Do not increase protected-file budgets, symbol limits or allowlists merely to
  make an architecture gate pass. A temporary increase requires explicit owner
  approval, a named incident rationale and a scheduled ratchet-down package.
- After every successful extraction, lower the corresponding line/symbol budget
  to the new measured value in the same commit.
- Do not replace one monolith with another. Prefer modules around 500 lines or
  less; a larger module needs one cohesive responsibility and a documented
  reason.
- Freeze `LegacyApp.tsx` for compatibility. New product work belongs in the
  current UI. Legacy UI removal requires telemetry, parity and rollback gates.
- Split CSS by component/feature/layout boundary while preserving class
  contracts and desktop/mobile visual behavior.

## 8. Commit and generated-artifact discipline

- One package addresses one bounded problem. Avoid mixing architecture,
  unrelated UI changes and operational deployment in one commit.
- Every code-bearing commit must be self-contained and green. Update generated
  backend symbol maps, architecture inventory, tests and relevant docs in the
  same commit as the behavior change. A later "refresh map" commit is not an
  acceptable normal workflow.
- Generate files with the repository scripts; do not hand-edit generated maps.
- Inspect the staged diff and secret scan before committing. Commit only files
  owned by the current package. Push only after local gates pass.
- Never claim GitHub/CI success when a run has zero steps. Report external
  billing/plan failures separately from code failures.

## 9. Verification policy

Use the smallest gate that proves the change, then broaden it in proportion to
risk:

1. Characterization or regression test before a risky move.
2. Targeted tests after each small edit.
3. Architecture/map check for structural changes.
4. Frontend lint/build and focused Playwright checks for UI changes.
5. `tools/verify.ps1 -Mode Quick` for a completed non-release package.
6. One clean `tools/verify.ps1 -Mode Full` receipt for a release candidate.

For auth, payments, release locking, concurrent storage changes and persistent
workers, repeat the focused race/idempotency test five times. Do not run the
entire Full suite five times and do not start duplicate Full suites; that wastes
CPU and can create false operational races.

Tests passing means code is verified in isolation. It does not prove a feature is
deployed or a provider is operational. Use these exact states:

- `CODE COMPLETE`: implemented and locally tested.
- `DEPLOYED`: the exact commit/release is active.
- `VERIFIED`: its acceptance checks passed in the stated environment.
- `OPERATIONALLY VERIFIED`: a real provider/user flow produced redacted evidence.
- `BLOCKED`: an external dependency prevents the next acceptance gate.

## 10. Release and live verification

- Deploy only clean canonical `main` when `HEAD == origin/main` and the receipt
  names that exact SHA. Never deploy uncommitted WIP.
- A successful publisher must bind frontend/backend release identity and retain
  rollback artifacts. Keep VPS/FRP untouched unless explicitly in scope.
- After an authorized deploy, verify local and public `/`, `/feed`, `/gallery`,
  `/api/health` and `/api/version`, listener ownership, release identity and
  relevant logs. UI work also needs desktop/mobile browser evidence.
- Report implemented, deployed, verified and blocked work separately. HTTP 200
  alone is not proof that a UI control or external integration works.

## 11. Documentation and plan control

- The current executable backlog is
  `docs/engineering-optimization-master-plan-20260719.md`.
- The current evidence audit is `docs/agent-compliance-audit-20260719.md`.
- Older roadmaps remain historical evidence and must not silently become the
  current backlog again.
- When a discovered defect changes priority or acceptance criteria, update the
  current plan in the same package. Record exact SHA/receipt/PID/run identifiers
  as timestamped evidence, not timeless facts.
- A package is complete only when code, tests, generated maps, documentation,
  commit and requested push are complete. Deployment is a separate explicit
  state unless the package includes it.
