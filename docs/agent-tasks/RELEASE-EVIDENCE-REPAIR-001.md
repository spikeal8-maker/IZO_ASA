---
status: ready-for-review
canonical: false
record_role: task-contract
package: RELEASE-EVIDENCE-REPAIR-001
domain: release-evidence
riskClass: high-assurance
base_sha: 79ae172222a70a7b15ad29383b2acc30a35544ca
branch: codex/release-evidence-repair-20260831
created: 2026-08-31
---

# RELEASE-EVIDENCE-REPAIR-001 — refresh merged audit fingerprints

## Goal and before/after

Restore deterministic release verification after PR #82 recorded whole-file
fingerprints for `backend/main.py` and `backend/SYMBOL_MAP.md`, then PR #81
legitimately changed both files. Before: local Full and exact-SHA GitHub CI fail
the admin mutation evidence test. After: the bounded audit points at merged main
SHA `79ae172` and records the normalized fingerprints of those two current
artifacts; product behavior is unchanged.

## Non-goals

- No application, admin, chat, billing, migration or generated-map changes.
- No reinterpretation of audit findings, route statuses or source fingerprints.
- No production DB/media/secrets/provider/network changes.
- No deployment in this repair package; deployment resumes only after merge and
  a clean exact-SHA verification receipt.

## Declared files

- `docs/admin-mutation-audit.md`
- `docs/agent-tasks/RELEASE-EVIDENCE-REPAIR-001.md`

The discovered scope is required because independent PRs #82 and #81 changed an
evidence consumer and its whole-file inputs in merge order. The earlier admin
audit worktree is preserved and not modified.

## Acceptance and evidence

- Only `verified_source_sha`, JSON `source_sha` and the two stale whole-file
  fingerprints change in the audit.
- `python -m pytest -q tools/test_admin_mutation_audit.py` passes.
- `git diff --check`, secret scan and complete diff review pass.
- GitHub CI and automated review pass on the repair PR.
- After merge, one clean Full receipt is created for the new exact `origin/main`.

## Rollback

One documentation-only evidence commit. Reverting it reintroduces the known
verification failure but does not change runtime or production data.

## Verification receipt

- Characterization: exact-SHA Full failed after `1 893 passed` with the stale
  `backend/main.py` fingerprint; GitHub CI for `79ae172` failed at the same gate.
- Deterministic comparison found exactly two stale artifacts:
  `backend/main.py` and `backend/SYMBOL_MAP.md`.
- `python -m pytest -q tools/test_admin_mutation_audit.py`: `8 passed`.
- Complete bounded diff, `git diff --check` and credential-pattern scan passed.
- Automated review identified the stale YAML `verified_source_sha`; it was
  synchronized with the same merged SHA as the JSON contract.
- Production services, DB, media, secrets, providers and network were untouched.
