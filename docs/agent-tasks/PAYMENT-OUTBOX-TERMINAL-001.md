# PAYMENT-OUTBOX-TERMINAL-001

## Contract

- Base: `bd0a8132b8779f8589e1f8ee9f440689573d79ca`.
- Domain: billing payments; risk: high assurance.
- Machine scope: `tasks/PAYMENT-OUTBOX-TERMINAL-001.toml`.
- Outcome: a recorded successful payment notification cannot be reopened by a
  late failure callback, and repeated success preserves the first delivery time.
- This is terminal-state hardening, not a historical restore fence or permission
  to start restored historical volumes.

## Implementation

`mark_retry` excludes `sent` both when reading attempts and in its final UPDATE.
The UPDATE predicate is essential: another SQLite connection can commit success
after the read. `mark_sent` also excludes `sent`, preserving the original row on
duplicate success callbacks. Existing callers require no composition changes.

No schema, migration, main.py, API, worker, environment or generated artifact
changes are needed. The existing transitions involving `failed` remain unchanged.
Concurrent retry counting and expired-lease ownership are explicitly outside scope.

## Regression evidence

The exact base was executed against an in-memory SQLite database: enqueue, claim,
success, then late failure changed `sent` to `retry`; the message became pending
again. Another success overwrote the original `sent_at`.

The focused suite covers both callback orders, full-row immutability after sent,
repeated success, a second connection committing sent between the retry read and
write, and unchanged failed-state transitions. Its interleaving closes the read
cursor before the second connection commits and uses no sleep-based scheduling.
All new SQLite connections close before temporary database cleanup.

The local isolated Python 3.12 / pytest 8.3.5 run of this exact test file against
the base module reports 4 failed and 6 passed; the fixed module reports 10 passed.
The failures cover reopening, full-row mutation, timestamp overwrite and the
two-connection interleaving. No provider or historical database was used.
Native verification, generator checks, scope verification, independent review
and required hosted CI remain separate gates before integration.

## CI evidence binding repair

CI run `42347093486`, job `128327087024`, on exact
`b4958e9be9ed4b78d3214d1babe4e5fe6b8b3396` reports 1 failed, 2693 passed,
8 warnings and 0 cleanup issues. The sole failure is the audit's stale
whole-file fingerprint for the extended outbox test module.
Ordinary scope-add covers only `docs/admin-mutation-audit.md`; the unchanged
`tools.test_admin_mutation_audit._artifact_fingerprint` recomputes that binding.
All source SHAs, artifact paths, route fingerprints/statuses, findings and gaps
remain unchanged. No generated artifact, audit gate or 350-line budget changes.
This is evidence rebinding, not a new audit, historical restore or live claim;
fresh exact-head hosted CI and review remain required.

## Rollback

Revert this code package only. No schema or historical outbox rows are rewritten;
no database restore is required. Reverting removes the late-callback protection.
Public deployment and historical restore acceptance remain separate operations.
