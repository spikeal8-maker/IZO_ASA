# IZO_ASA repository rules for every coding agent

This file is the repository-wide policy for Codex, Claude, Copilot, Gemini and
any other automation that reads or changes this repository. Tool-specific
adapters may point here, but they must not duplicate, weaken or contradict it.

`AI_START_HERE.md` is the sole owner of the repository reading order. After this
policy, open that file and follow its sequence. Do not invent or restate another
order in policy, status, program or package documents.

## 1. Repository identity and worktrees

- On the current production computer, the canonical integration and deployment
  checkout is `E:\IZO_ASA_WORKSPACE`.
- Portable tooling discovers the active checkout with
  `git rev-parse --show-toplevel`; it must not depend on a drive letter.
- Verify `git remote get-url origin` identifies `spikeal8-maker/IZO_ASA`.
- Ordinary development uses a feature branch/worktree. Never deploy from a
  feature worktree, sibling copy, attachment, temporary export or resolved
  symlink target.
- `E:\Yandex.Disk\IZO_ASA` is a quarantined historical copy affected by live
  `.git` synchronization conflicts. Do not use, repair or delete it without a
  separate owner-authorized maintenance package.
- Yandex.Disk may receive immutable backup snapshots only. It must not
  synchronize live `.git`, SQLite/WAL/SHM, media working state, runtime
  manifests or secrets.
- The application runs on the Windows host and the VPS carries the existing
  public transport. Do not change VPS, FRP, DNS, tunnel or AdGuard configuration
  unless the owner explicitly places that production-network change in scope.
- Preserve unrelated work. Never use `reset --hard`, automatic stash,
  checkout-overwrite or cleanup to make another package disappear.

## 2. Mandatory preflight and Task Contract

Before changing files, record:

```powershell
git rev-parse --show-toplevel
git remote get-url origin
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git worktree list
```

Then follow `AI_START_HERE.md` and:

- check for overlapping work and active verification/release processes;
- identify live DB, media, secrets and providers and keep tests away from them;
- state the user-visible before/after scenario, non-goals, domain, risk class,
  declared files/patterns, acceptance, evidence and rollback boundary;
- use a bounded discovery package instead of implementation when the requested
  outcome or routing remains materially ambiguous.

One package addresses one bounded problem. Discovered scope must record its
reason and re-check overlap. Crossing into a new domain or materially enlarging
the package requires an updated Task Contract.

## 3. Ownership, main and single-flight operations

- Ordinary coding agents do not work directly in `main`.
- There is one integration owner for `main` and one release owner.
- Repository-wide mutable operations use
  `tools/repository-operation-lock.ps1`; do not bypass or reimplement its
  locking, stale-owner or re-entry behavior.
- Do not run a second Full verification, publisher, promotion or backend restart
  while the corresponding repository operation is owned.
- Generated maps are deterministic shared artifacts. Verify and regenerate them
  as required, but do not create false exclusive ownership of the whole backend.

## 4. Production and data safety

- Production SQLite, WAL/SHM, media, secrets, models and runtime manifests are
  never test fixtures.
- Tests use temporary DB, media and secret roots plus fake providers.
- Never delete or rewrite `backend/onenode.sqlite3`, `backend/media`, `.runtime`
  or external backup roots during ordinary implementation.
- Never copy an open SQLite database with a normal file copy. Use the SQLite
  Backup API and repository backup/restore tools.
- Schema changes are additive and versioned through
  `backend/app/database/migrations.py`. Never reuse a migration version/name or
  change an applied checksum.
- Destructive migration requires a separate owner-approved maintenance package,
  verified backup and rehearsed rollback.
- Keep a single live SQLite writer application process.
- Documentation, analysis and tests do not authorize deploy or restart.

## 5. Secrets, providers and financial actions

- Secrets never enter Git, logs, screenshots, chat, API responses or snapshots.
- Use environment overrides or the Windows DPAPI store outside the repository.
- Automated tests use fake Telegram, MAX, YooKassa, UniSender, SMTP, OpenRouter,
  ComfyUI and Ollama adapters. They must not charge money, send messages or
  email, consume paid generation or mutate real provider state.
- Real payments, refunds, mail, webhook switches, token rotations and provider
  verification require explicit operator authorization and a redacted receipt.
- Payment and webhook state changes must be authenticated, idempotent,
  transactional and auditable.

## 6. Identity, privacy and public APIs

- Never trust `X-OneNode-User`, `onenode_user`, frontend `user_id`, unsigned
  Telegram data or unverified MAX data as identity.
- Protected routes resolve a trusted server-side session. Admin routes use
  `require_trusted_admin`; every admin mutation writes an audit event.
- Do not create a second authentication system. Legacy compatibility is frozen
  and removed only through characterization and migration packages.
- Public endpoints must not expose absolute paths, secret/config presence,
  internal URLs, TLS/proxy details, stack traces, database statistics or
  operator diagnostics.
- Private media access is owner-checked. Public derivatives and avatars are
  deliberate separate surfaces with lifecycle tests.
- User-facing image model branding remains `Flux2`; technical model names and
  workflow identifiers are internal/admin-only.

## 7. Bots, jobs and persistent workers

- Telegram/MAX have exactly one delivery owner each. Polling and webhook
  delivery must not overlap without an explicit handoff protocol.
- Do not automatically delete webhooks, reset cursors or rotate tokens.
- Every persistent worker declares owner, process role, durable state, startup,
  retry/recovery, idempotency and watchdog behavior in the architecture map.
- In-process queues are wake-up mechanisms, not the durable source of truth.
  Jobs, publications, financial events and mail obligations survive restart.
- Worker health requires recent success/failure evidence, not only a running
  process or configured token.

## 8. Architecture and large files

- Keep the system a modular monolith. Do not migrate to microservices,
  Docker/Linux/PostgreSQL or an external queue merely for style.
- `backend/main.py` is a frozen compatibility/composition shell. New business
  logic belongs in `backend/app/*`; move behavior only behind characterization
  tests.
- Do not raise protected-file budgets, symbol limits or allowlists just to pass
  a gate. After an extraction, lower the measured budget in the same commit.
- Prefer cohesive modules around 500 lines or less; do not replace one monolith
  with another.
- `LegacyApp.tsx` is frozen compatibility. New product work belongs in the
  current UI. Removal requires telemetry, parity and rollback gates.
- Split CSS by feature/component/layout without mixing decomposition with
  redesign or breaking desktop/mobile class contracts.
- Do not read `backend/main.py`, `newUi.tsx`, `LegacyApp.tsx`,
  `adminModels.tsx` or large CSS in full when a context card, generated map,
  symbol map or bounded line range is sufficient.

## 9. Commits, generated artifacts and review

- Keep architecture, product behavior and operational deployment in separate
  packages unless the Task Contract explicitly requires the combination.
- Every code-bearing commit is self-contained and green: behavior, tests,
  generated maps and relevant context documentation change together.
- Generate maps with repository scripts; never hand-edit generated output.
- Inspect the complete diff and secret scan before commit.
- Commit only package-owned files and hand off one clean commit/PR.
- Do not merge until required CI and automated review have completed and every
  finding is fixed or explicitly waived with evidence.
- Never claim CI success when a workflow executed zero steps.

## 10. Verification policy

Use the smallest gate that proves the current change:

1. characterization/regression test before a risky move;
2. targeted tests after each small edit;
3. architecture/map checks for structural changes;
4. frontend type/lint/build and focused Playwright for UI changes;
5. `tools/verify.ps1 -Mode Quick` for a completed non-release package;
6. one clean `tools/verify.ps1 -Mode Full` receipt for an integration/release
   candidate.

For auth, payments, release locking, concurrent storage and persistent workers,
repeat the focused race/idempotency test five times. Do not run the whole Full
suite five times and do not start duplicate Full suites.

Report states exactly:

- `CODE COMPLETE`: implemented and locally tested.
- `VERIFIED`: acceptance checks passed in the stated environment.
- `DEPLOYED`: the exact commit/release is active.
- `OPERATIONALLY VERIFIED`: a real provider/user flow produced redacted evidence.
- `BLOCKED`: an external dependency prevents the next gate.

## 11. Release and live verification

- Read `docs/production-release-runbook.md` before release, rollback or live
  diagnosis.
- Detect installed topology from runtime evidence. On the installed
  Windows-service topology, use its updater/promoter workflow and maintenance
  flag; do not substitute legacy start/restart scripts.
- Deploy only clean canonical `main` when `HEAD == origin/main` and the receipt
  names that exact SHA. Never deploy uncommitted WIP.
- After an authorized deploy, verify local and public routes, health/version,
  listener ownership, release identity and logs. UI work also needs
  desktop/mobile browser evidence.
- HTTP 200 alone does not prove UI behavior or provider operation.

## 12. Documentation and current state

- Follow the reading order owned by `AI_START_HERE.md`.
- `docs/NOW.md` is the only current-status aggregator and program router.
- `docs/context/*.md` are scoped domain maps; extend them instead of creating a
  parallel context hierarchy.
- `docs/generated/*`, `backend/SYMBOL_MAP.md` and other generated maps are
  evidence, not manually maintained plans.
- `docs/agent-control-plane.md` is the active agent-development program but is
  not daily context.
- Historical roadmaps and completed Task Contracts remain evidence only.
- `README.md` describes the product and basic operations; it is not a backlog.
- A package is complete only when implementation, tests, generated evidence,
  documentation, commit and requested push/PR are complete. Deployment remains
  separate unless explicitly included.
