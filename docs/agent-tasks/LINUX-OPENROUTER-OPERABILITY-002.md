# LINUX-OPENROUTER-OPERABILITY-002

## Outcome and carry-forward boundary

Complete OpenRouter Save/Check and restart persistence on the existing closed
Linux beta. The implementation and runtime acceptance requirements remain in
[the retained implementation contract](LINUX-OPENROUTER-OPERABILITY-001.md).
Current machine scope is `tasks/LINUX-OPENROUTER-OPERABILITY-002.toml`, based on
`4ccd61920a63f0b0961c992efca2fe75be020d35`.

Package 001 is superseded, not released. Its clean native commit
`2cf33d711c32f9416443f9cbcb544d15e687daab`, tree
`28f9f09e0859b45b5defb53a265674ae69a0cd7e`, and published candidate
`a20e0b7fe8e07e2fdeb3264b1a316346d21aee94` remain preserved. Windows run
`42491172145` stopped before full pytest because the pinned dependency's dual
license expression required a tracked review. Its native focused tests and
independent source reviews do not constitute full CI or runtime acceptance.

The normal `finish` released only 001's ownership. The private handoff receipt
records `SUPERSEDED_CI_BLOCKED`; normal `start` registered this successor with
the license policy declared upfront. The old worktree is retained. Only the
002 task manifest is present in the candidate diff against main.

## Narrow corrective scope

- Carry all 13 reviewed production files forward byte-for-byte, with their
  existing backend requirements, network assets and operational helpers.
- Add the exact-version [cryptography license review](../cryptography-50.0.2-license-review.md)
  under [#281](https://github.com/spikeal8-maker/IZO_ASA/issues/281).
- Extend the existing policy-data test's exact review set without weakening
  prior reviews, approved expressions, scanners or expiry checks.
- Route current status and scope to this package. The bundled contract filename
  and secret-volume protocol labels retain `OPERABILITY-001` for compatibility.

Limits remain 24 production files and 7000 changed handwritten lines. No
architecture, context or test-health budget increases. No changes to historical
data, public routing, unrelated projects, real keys, paid providers or global GPU
state are authorized by this corrective step.

## Required verification and release

Verify the immutable PyPI/upstream license bytes, preserve both older review
objects, and replay the actual failed license report through the unchanged
evaluator. The exact tuple must pass; future version, altered expression,
classification/ecosystem/package and expired-review cases must fail.

Run existing supply-chain, context, audit and scope checks; verify official maps
and unchanged production hashes. Obtain independent review of the exact delta
before committing. Publication must reproduce the native tree. New exact-head
mandatory CI and actual-image POSIX/backup probes are still required before the
reviewed native 1Panel update and owner UI Save/Check, restart, restore and sealed
history acceptance. Preserve the accepted 80b release and rollback boundary.
