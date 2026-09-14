---
status: active-program-amendment
record_role: dependency-amendment
id: AI-EVAL-BASELINE-DEFER-001
updated: 2026-09-14
master_spec: docs/stabilization-optimization-master-spec.md
current_status_owner: docs/NOW.md
production_change_authorized: false
---

# AI-EVAL-BASELINE-DEFER-001

## Decision

`AI-EVAL-BASELINE-001` issue #71 remains mandatory and its frozen source remains:

```text
ecb02bf84ae21a46711c9b38b61784147fb9fc0a
```

The dependency edge `AI-EVAL-BASELINE-001 -> AI-PACKAGE-001` is temporarily removed.
The frozen baseline is deferred, not waived.

`AI-PACKAGE-001`, `STAB-MAIN-GUARD-001`, `AI-ENFORCE-001`, `STAB-SIZE-001`,
`AI-INSTRUCTION-SCOPE-001` and `AI-CONTEXT-SCHEMA-001` may proceed while the
independent evaluator is unavailable.

Baseline #71 becomes a hard prerequisite again before:

- `AI-CONTEXT-PILOT-001` (#107), because that phase performs before/after locality comparison;
- `AI-EVAL-001` (#123), because final program acceptance requires the frozen point A.

## Why this preserves methodology

The baseline evaluates an immutable historical commit, not mutable current main.
Starting foundational safety/tooling packages does not modify that frozen source.
A future independent evaluator can still checkout the exact SHA and run Case A/B/C
without seeing implementation history.

The measurement stays comparable provided that:

1. evaluator sessions are genuinely independent;
2. each session receives only its case prompt and baseline protocol;
3. repository checkout is exactly the frozen SHA;
4. no expected answer/current implementation history is supplied;
5. receipts record factual reads/tool calls/tokens only;
6. all three receipts exist before #107 starts.

## External blocker evidence

At this decision point:

- authorized Remote Desktop executor is offline;
- DigitalOcean reports an inconsistent account/team droplet quota while listing no droplets;
- no existing repository evaluator workflow can launch an independent LLM session;
- no historical Case A/B/C receipts exist in issue #71.

This is an executor-availability problem, not a source-integrity problem.

## What this amendment does not authorize

It does not:

- mark #71 complete;
- change the frozen SHA;
- lower final cold-agent targets;
- permit #107 or #123 without all three baseline receipts;
- authorize product behavior changes beyond each later bounded package;
- authorize deploy, restart, provider, production DB/media/secrets or network actions.

## Execution order under this amendment

```text
AI-PACKAGE-001 (#101)
-> STAB-MAIN-GUARD-001 (#102)
-> AI-ENFORCE-001 (#103)
-> STAB-SIZE-001 (#104)
-> AI-INSTRUCTION-SCOPE-001 (#105)
-> AI-CONTEXT-SCHEMA-001 (#106)
-> REQUIRED: complete AI-EVAL-BASELINE-001 (#71)
-> AI-CONTEXT-PILOT-001 (#107)
-> continue canonical master sequence
```

If an independent evaluator becomes available earlier, run #71 immediately on the
frozen SHA; doing so does not interrupt an unrelated bounded implementation package.

## Removal condition

This amendment is fully consumed when #71 has three accepted independent receipts.
After that, `docs/NOW.md` should stop carrying a deferred-baseline blocker and the
canonical master sequence proceeds normally.

NOT DEPLOYED. No product/runtime change.