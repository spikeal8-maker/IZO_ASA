# DUAL-00 — verified delivery inventory (Windows Native / Docker)

**Status:** source-level inventory, not operational or release acceptance.  
**Repository:** spikeal8-maker/IZO_ASA · **Discovery date:** 2026-10-25.  
**Exact GitHub main:** 51543df2b6a559d693e3ed75b11baeacdb9033d3.  
**Owners:** [program #238](https://github.com/spikeal8-maker/IZO_ASA/issues/238), [package #239](https://github.com/spikeal8-maker/IZO_ASA/issues/239), [ADR](dual-runtime-delivery-adr.md).  
**Status vocabulary:** VERIFIED (GitHub source/metadata only), UNVERIFIED (no operational receipt), BLOCKED (proven gate). No deployment inferred from main.

## 1. Source and delivery evidence

| Boundary | Evidence observed at exact main / PR | Classification |
|---|---|---|
| Common FastAPI/React product | [Backend](../backend/), [frontend](../frontend/); root [agent rules](../AGENTS.md) require a modular monolith | VERIFIED source ownership, not runtime parity |
| Windows service release | [Promoter](../ops/release/promote-project-release.ps1), [installer](../ops/release/install-project-promoter.ps1), [release README](../ops/release/README.md), [production runbook](production-release-runbook.md) | VERIFIED in main; installed service identity UNVERIFIED |
| Windows native clean installer | Existing promoter switches prepared releases; no end-to-end fresh-user install/bundle acceptance located in this discovery | UNVERIFIED, DUAL-02 |
| Windows rollback | Promoter protects the service/config switch; additive live DB cannot be replaced by an automatic file rollback | VERIFIED source contract; runtime rollback UNVERIFIED |
| Data protection | [Backup runbook](backup-restore-runbook-20260713.md) describes SQLite Backup API, checksum/media manifest; dated rehearsal is historical | VERIFIED source; current restore and RPO/RTO UNVERIFIED |
| Docker in main | [DEV Compose](../ops/docker/dev/compose.yml) and [backend Dockerfile](../ops/docker/dev/Dockerfile.backend) | VERIFIED DEV/TEST only |
| Docker production delivery | No production Compose or [docker-clean-install workflow](https://github.com/spikeal8-maker/IZO_ASA/tree/main/.github/workflows) in main; stack exists in Draft PRs | UNVERIFIED; not a released target |
| Unified release manifest / two artifacts | No accepted paired Windows bundle + OCI digest on one SHA identified; GitHub Releases list was empty at discovery | MISSING acceptance, DUAL-04 |
| Active deployed SHA, data host, volumes, worker ownership, current credentials | Installed runtime needs separate authorized redacted read-only receipts | UNVERIFIED; do not infer from repository |
| Docs routing | [NOW](NOW.md) reports older main 7ab1861b and older active packages; [AI_START_HERE](../AI_START_HERE.md) owns reading order | VERIFIED drift; separate governance fix |

## 2. Existing implementation must be reused

**Windows:** canonical application update is the installed service promoter and its exact-SHA/receipt gates. Its runtime/service configuration, Caddy ownership and rollback are governed by the [release runbook](production-release-runbook.md) and [release context](context/release-ops.md). Existing mechanism is not proof of clean-machine Windows installation; do not write a second updater. Native GPU/providers and installed Python/frontend versions require evidence before release.

**Docker main:** single backend service, non-root UID/GID 10001, a digest-pinned Python base image, OCI source revision label, two persistent named volumes (SQLite and media), isolated default network, bounded resources, no restart, test environment, fake phone TTS and intentionally disabled real bot/provider endpoints. This is a deliberately safe DEV profile, **not production**. No runtime claims about a separate durable worker can be made from this Compose file.

**Data:** the SQLite snapshot uses the SQLite Backup API, not copying active DB/WAL files. Restore must include checksummed media and references, migration ledger and user/ledger ownership. Secrets backed by Windows DPAPI are not Linux-portable and must be reprovisioned to the target platform. Never attach the same writable database to Windows and Docker simultaneously.

## 3. Pending stack and overlap (not merged into main)

| PR / exact HEAD on 2026-10-25 | Base / contribution | State |
|---|---|---|
| [#195](https://github.com/spikeal8-maker/IZO_ASA/pull/195) 6f43f78a7de8f0d82306fbddeb1cfba2c89b0e91 | main; Docker clean-install/shadow/D3 tools and CI workflow | Draft, 214 changed files; not accepted |
| [#209](https://github.com/spikeal8-maker/IZO_ASA/pull/209) 445bf08b24758c8b93dc4132226bf9b2b14fa075 | #195; native OpenAI/admin candidate | Draft |
| [#211](https://github.com/spikeal8-maker/IZO_ASA/pull/211) 3f041ca8c2989e53cbd469dfbe29131a63279ae2 | #209; Linux secret/provider shadow | Draft |
| [#215](https://github.com/spikeal8-maker/IZO_ASA/pull/215) 1fede386664c41141c0611919a2d15c31cfd4d5f | #211; controlled Comfy bridge | Draft |
| [#217](https://github.com/spikeal8-maker/IZO_ASA/pull/217) 1030abdafc32a0f11fbc4a6593acd435eb1bbdfd | #215; integrated D2-R2 preprod, separate test data | Draft; NOT production |
| [#199](https://github.com/spikeal8-maker/IZO_ASA/pull/199) a250aea0bbf0951678162ef4ec3985116058e20c | main; admin/ledger durability | Draft |
| [#221](https://github.com/spikeal8-maker/IZO_ASA/pull/221) f09f99b3a79dc32ca9e69380ff4013223748ed58 | #217; image command idempotency | Draft |
| [#224](https://github.com/spikeal8-maker/IZO_ASA/pull/224) 77d35f4907fbb976f12bb279af1a66b832229493 | #221; account-isolated pending commands | Draft |
| [#226](https://github.com/spikeal8-maker/IZO_ASA/pull/226) 539d4b136a163e7362ad9b8eb1350c1e75bd141a | #224; auth-refresh, logout and cross-tab privacy | Draft |
| [#228](https://github.com/spikeal8-maker/IZO_ASA/pull/228) e60d3f002f09a0b37ea96192c8da8924e8880690 | #217; combined synthetic candidate, full E2E absent | Draft |
| [#222](https://github.com/spikeal8-maker/IZO_ASA/pull/222) 9433610dae9ad8aa57cee7d00187c6fdef887a6f | #217; isolated Comfy test harness | Draft |
| [#223](https://github.com/spikeal8-maker/IZO_ASA/pull/223) 493a0647eeb083939fe1f628418b232ee8b03c93 | #217; fail-closed paid video timeout stopgap | Draft |
| [#229](https://github.com/spikeal8-maker/IZO_ASA/pull/229) 36f9dfe3399e2cee7c0d2d71d918a91a4bc19b33 | main; durable receipt prototype not wired into runtime | Draft |
| [#240](https://github.com/spikeal8-maker/IZO_ASA/pull/240) ea312a9ffd5013c3cbaaecc288901c13d71d5257 | main; required GitHub gate hardening | Draft |

The large #195 change set overlaps existing Compose, CI and docs/NOW; reuse only after review. DUAL-00 modifies none of these paths. Do not cherry-pick stacked PRs blindly. See [reliability audit #218](https://github.com/spikeal8-maker/IZO_ASA/issues/218), [image #219](https://github.com/spikeal8-maker/IZO_ASA/issues/219), [video/provider #204](https://github.com/spikeal8-maker/IZO_ASA/issues/204), and [cutover #126](https://github.com/spikeal8-maker/IZO_ASA/issues/126).

## 4. Capability evidence matrix (no synthetic PASS)

Statuses here describe **delivery acceptance**, not whether a route/component exists in source. Supported production parity requires real, independent installation tests and capability receipts.

| Product capability | Windows Native | Ubuntu Docker | Windows Docker Desktop |
|---|---|---|---|
| Auth, roles, accounts | UNVERIFIED installed behavior | PARTIAL source/shadow candidate | UNVERIFIED |
| Studio images, gallery, feed, media | UNVERIFIED installed behavior | PARTIAL #195/#217 candidate | UNVERIFIED |
| Video and unknown-provider outcomes | UNVERIFIED; #204/#223 gate | BLOCKED for paid reliability | UNVERIFIED |
| Chat, audio/TTS/ASR | UNVERIFIED installed behavior | PARTIAL fake TTS only in main DEV | UNVERIFIED |
| Admin, tariffs, quota and ledger | UNVERIFIED financial acceptance | BLOCKED pending #218/#219/#199 | UNVERIFIED |
| Telegram and MAX | UNVERIFIED installed integrations | UNSUPPORTED in main DEV (disabled) | UNVERIFIED |
| ComfyUI, Ollama, external GPU | UNVERIFIED exact installed provider state | PARTIAL Comfy bridge candidate; real Ollama UNVERIFIED | UNVERIFIED |
| Backup/restore/rollback | PARTIAL documented Windows mechanism | UNVERIFIED end-to-end production | UNVERIFIED |
| Fresh install, update, release identity | PARTIAL installed-promoter contract | UNVERIFIED paired release | UNVERIFIED |

## 5. Current → target → gap → next child

| Current | Target | Blocking gap / priority | Next |
|---|---|---|---|
| Windows service promoter + DEV Compose | One lifecycle/config boundary | Need profiles, readiness, worker ownership; P0 | DUAL-01 |
| Windows script-based existing release | Native bundle install/upgrade/rollback | Clean install and preserved state acceptance; P0 | DUAL-02 |
| DEV Compose and Draft shadow chain | Hardened production Compose + digest images | Merge/reconcile #195–#217 and P0 security; P0 | DUAL-03 |
| Incompatible delivery receipts | Paired artifacts + signed/checksummed manifest on one SHA | Hosted builders, full provenance and release policy; P0 | DUAL-04 |
| Source-level component presence | Windows/Linux/Desktop functional matrix | Isolated E2E, recovery, finance, privacy and performance; P0 | DUAL-05 |
| Windows backup implementation | Portable guarded export/restore | DB/media integrity, DPAPI reprovision, schema range, no shared writers; P0 | DUAL-06 |
| No proven paired release candidate | Two installable, recoverable packages | All gates, independent review, manuals, GO/NO-GO; P0 | DUAL-07 |

## 6. Governance and remaining evidence

The active [ruleset 25818566](https://github.com/spikeal8-maker/IZO_ASA/rules/25818566) requires PR, resolved conversations, **Backend, tooling and frontend gates**, and **Bounded documentation and test file checks**. Its required GitHub approving-review count is **zero**: a process-only independent reviewer must not be misrepresented as enforced GitHub APPROVED.

Recent hosted checks ran (not globally billing-blocked): [CI failure 40186925672](https://github.com/spikeal8-maker/IZO_ASA/actions/runs/40186925672) and [hygiene success 40186925722](https://github.com/spikeal8-maker/IZO_ASA/actions/runs/40186925722) on PR source SHA 36f9dfe3399e2cee7c0d2d71d918a91a4bc19b33. A separate [run 40189159844](https://github.com/spikeal8-maker/IZO_ASA/actions/runs/40189159844) failed on another source SHA. These are **not DUAL-00 CI outcomes**.

**Not established in this GitHub-only audit:** local clean worktree/worktree locks, installed Windows services or promoter hash, active production SQLite/media origin, live Comfy/Ollama state, actual GitHub release artifacts, backup freshness, true runtime parity, Windows Docker Desktop support, Linux staging health. Keep all as UNVERIFIED pending authorized redacted receipts; never turn source inspection into deployment evidence.

**Governance follow-up:** separate Task Contract to correct [NOW](NOW.md), with transition SHA and verified current main distinguished. Do not edit it within DUAL-00.
