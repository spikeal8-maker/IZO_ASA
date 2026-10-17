# IZO_ASA repository rules for every coding agent

This is the repository-wide policy for Codex, Claude, Copilot, Gemini and other
automation. Domain-specific rules belong to the nearest scoped `AGENTS.md`; a
scoped file may narrow this policy but must not duplicate, weaken or contradict it.

`AI_START_HERE.md` is the sole owner of reading order. `docs/NOW.md` is the sole
current-status/program router. Follow both before opening source.

## 1. Repository identity and Agent Control Plane

- Confirm the Git root and that `origin` identifies `spikeal8-maker/IZO_ASA`.
- Portable tooling must discover the checkout; never depend on a drive letter.
- Ordinary implementation runs through `tools/agent.ps1` in one feature
  branch/worktree. Coding agents do not write directly to remote `main`.
- One package has one writer. Preserve unrelated work; never use stash,
  `reset --hard`, checkout-overwrite or cleanup to erase another package.
- Repository-wide mutable operations use `tools/repository-operation-lock.ps1`.
  Do not bypass, duplicate or weaken its ownership semantics.

## 2. Task Contract and bounded scope

- One package addresses one bounded problem with explicit before/after,
  non-goals, domain, risk class, declared files/patterns, acceptance, evidence
  and rollback boundary.
- The tracked `tasks/<ID>.toml` manifest is machine authority for write scope.
- Never expand scope silently. Use `agent scope-add` with a reason and re-check
  overlap before touching newly discovered paths.
- Prefer scoped context, generated maps, symbol maps and bounded line ranges to
  broad scans or full reads of protected hotspots.
- Generated evidence changes only through its generator and in the same package
  that changes the source/contract it describes.

## 3. Production, secrets and external effects

- Production DB/media/secrets/providers are never test fixtures. Tests use
  isolated temporary state and fake providers.
- Documentation, analysis or tests do not authorize deploy, restart, provider,
  payment, mail, webhook, production-data or network operations.
- Do not change VPS, FRP, DNS, tunnel or AdGuard configuration without explicit
  owner scope for that production-network change.
- Secrets never enter Git, logs, screenshots, chat, API output or generated
  evidence. Use approved environment/DPAPI sources outside the repository.
- Real money movement, messages, email, token rotation or provider mutation
  requires explicit operator authorization and a redacted receipt.

## 4. Architecture and change locality

- Keep the product a modular monolith unless an owner-approved architecture
  package explicitly changes that decision.
- Protected file/symbol budgets are non-growth constraints. Never raise a limit
  or add an exception merely to make a package pass; extraction lowers its
  measured budget in the same package.
- New handwritten source follows the reviewed architecture size contract; do
  not replace one monolith with another.
- For document and test file layout/size, use `docs/documentation-standards.md`
  and `docs/testing-file-standards.md`; CI checks live in `tools/file_hygiene.py`.
- Architecture, product behavior and production operations stay in separate
  packages unless the Task Contract explicitly requires their combination.

## 5. Verification, commits and review

- Match gates to the change: docs/tools use focused/CI checks; app/container
  changes need relevant runtime tests. Legacy `Quick` needs host runtime;
  absence is never PASS. Declare gates in the Task Contract.
- Full/integration verification is single-flight and belongs to the integration
  candidate; do not launch duplicate Full runs.
- High-assurance auth/billing/migration/storage/worker races repeat the focused
  race/idempotency case, not the whole suite.
- Before commit inspect complete diff, scope receipt, generated evidence and
  secret exposure. A code-bearing commit is self-contained and green.
- Do not merge until required exact-head CI/review is complete and every finding
  is fixed or explicitly waived with evidence.

Report states precisely: `CODE COMPLETE`, `VERIFIED`, `DEPLOYED`,
`OPERATIONALLY VERIFIED`, or `BLOCKED`. Never infer deployment from GitHub.

## 6. Documentation and completion

- Follow `AI_START_HERE.md`; do not create a second reading-order hierarchy.
- `docs/NOW.md` alone owns current package/backlog routing.
- `docs/context/` and generated maps are bounded evidence, not parallel plans.
- Historical plans and completed Task Contracts remain evidence only.
- A package is complete when implementation, tests, generated evidence,
  documentation, clean commit and requested PR/merge are complete. Deployment
  remains separate unless explicitly authorized.
