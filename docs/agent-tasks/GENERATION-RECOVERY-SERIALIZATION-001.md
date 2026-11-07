# GENERATION-RECOVERY-SERIALIZATION-001

## Boundary

The native [Task Contract](../../tasks/GENERATION-RECOVERY-SERIALIZATION-001.toml)
limits this high-assurance fix to the existing startup-recovery service.
The reviewed base is `bf2d60b508da4e4de52905561b8db0a9f27ea721`.
`main.py` and the original OpenRouter owner scope remain unchanged.

## Transaction Contract

Acquire the SQLite writer before reading jobs, images or refund state.
An open deferred/read transaction is not itself a writer reservation.
A fresh connection needs an explicit transaction, including autocommit mode.
An existing caller transaction must upgrade safely or fail before any refund.
Stale WAL snapshots propagate their conflict; do not restart or retry them.
The service never commits or rolls back the caller's transaction.
Any zero-row reservation must change no rows and fire no row triggers.

## Required Evidence

Preserve pinned baseline code and actual 2/5/10-connection race output.
Wired regressions use canonical temporary databases and the real refund callback.
Record WAL, timeout, isolation and transaction boundaries without a live provider.
Cover legacy/autocommit, deferred/read and already-write callers, writer conflicts,
stale snapshots, callback failure and caller-controlled rollback.
Retain saved-image, deleted-image, terminal, resumable-video and second-run behavior.
Synchronize outside a held writer reservation; repeat only the focused race suite.
Pass scoped checks, applicable generators, exact-head CI and independent review.
This document defines acceptance; actual execution results remain separate evidence.

## Limits

This fix serializes cooperating recovery calls, not direct refund callers or
POST generation admission. It does not fence all historical workers or outboxes.
No historical data, login, build, deployment, GPU result or public switch is authorized.
Do not present source tests or this package as complete no-replay or an accepted beta.
