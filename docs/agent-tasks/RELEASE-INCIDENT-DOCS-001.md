---
status: ready-for-review
canonical: false
record_role: task-contract
package: RELEASE-INCIDENT-DOCS-001
domain: production-release
riskClass: low
base_sha: d223c179d5944bc208cace867d5e93bc1341a3aa
branch: codex/release-incident-docs-20260902
created: 2026-09-02
---

# RELEASE-INCIDENT-DOCS-001 — record the verified release recovery

## Goal and before/after

Record why the 2026-09-01/02 deployment was repeatedly blocked, what code and
operational sequence resolved it, and which evidence proved the exact release.
Before: the runbook describes the installed updater/promoter but does not route
agents to a concise record of this failure, while the root policy does not say
that a generated administrator wrapper is single-use after a failed gate.
After: the incident record, runbook, current-state router and root agent policy
give the same stop/recovery rules and distinguish preflight failure from a
production mutation.

## Non-goals

- No application, release-tool or runtime behavior change.
- No deployment, restart, rollback, provider, database, media or network action.
- No secret, complete transcript, PID or unredacted installed configuration in
  Git.
- No claim that a real authenticated chat/provider flow was operationally
  verified.

## Declared files

- `AGENTS.md`
- `docs/NOW.md`
- `docs/production-release-runbook.md`
- `docs/production-release-incident-20260902.md`
- `docs/agent-tasks/RELEASE-INCIDENT-DOCS-001.md`

## Acceptance and evidence

- The record separates expired-receipt, backend-preflight and promotion stages.
- The healthy installed WinSW/Python topology and its fail-closed checks match
  the merged implementation and tests.
- The successful record names merge SHA, CI, fresh Full receipt, immutable
  candidate, final updater/promotion states and exact local/public version
  evidence.
- `AGENTS.md` remains below its protected line budget and tells future agents
  not to rerun a failed one-shot wrapper or bypass installed-service ownership.
- Documentation contract tests and whitespace/link checks pass.

## Rollback boundary

Revert this documentation-only commit. The package does not touch the installed
runtime or the active production release.

## Verification evidence

- `tools/test_agent_instructions.py` and `tools/test_context_docs.py`:
  `10 passed`.
- All relative Markdown links in the declared files resolve.
- `AGENTS.md`: `220` lines against the protected `230`-line budget;
  `docs/NOW.md`: `124` lines against its `140`-line budget.
- `git diff --check`: clean. No runtime transcript, PID, credential or installed
  XML was added.
