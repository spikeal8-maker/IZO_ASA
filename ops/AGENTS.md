# Operations scoped policy

Root `AGENTS.md` and `AI_START_HERE.md` remain mandatory. This file owns only
rules for `ops/**` and authorized release/runtime operations; it does not own
reading order, current status or backlog.

## Production topology and authorization

- Production runs on the Windows host; the VPS provides the existing public
  transport. Detect installed topology from runtime evidence before acting.
- Release, rollback, restart, webhook, provider, network and production-data
  actions require an explicit `release-ops` scope from the owner.
- Read `docs/production-release-runbook.md` before release/rollback/live
  diagnosis. Do not substitute legacy scripts for an installed service updater.
- Deploy only clean canonical `main` when `HEAD == origin/main` and the receipt
  names that exact SHA. A feature worktree is never a deployment source.

## Services, transport and backups

- Do not kill guessed Python/process IDs. Respect service ownership and the
  repository preflight/maintenance gates. A WinSW-owned launcher/base-Python
  listener is valid only when preflight reports installed Windows-service ownership.
- VPS, FRP, DNS, tunnel, AdGuard, webhook and listener topology remain unchanged
  unless individually declared in the authorized Task Contract.
- Yandex.Disk may receive immutable backup snapshots only; never synchronize
  live `.git`, SQLite/WAL/SHM, media work state, runtime manifests or secrets.
- Never copy an open SQLite DB normally; use SQLite Backup API and repository
  backup/restore tooling.
- One-shot administrator wrappers/receipts are evidence, not retry interfaces.
  After expiry/failure, preserve evidence and create a fresh authorized action.

## Release verification

- After an authorized deploy, verify local/public routes, health/version,
  listener ownership, release identity, updater state, promotion completion and
  relevant logs. UI releases also require browser evidence.
- HTTP 200 alone does not prove UI, provider or data behavior.
- Keep release/integration/full verification single-flight under repository
  operation ownership.
