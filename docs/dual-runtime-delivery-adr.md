# ADR — ONE SOURCE → TWO DELIVERIES for IZO_ASA

**Status:** PROPOSED, DUAL-00, 2026-10-25.  
**Decision owner:** [#238](https://github.com/spikeal8-maker/IZO_ASA/issues/238). **Discovery:** [inventory](dual-runtime-delivery-inventory.md).  
**Source baseline:** 51543df2b6a559d693e3ed75b11baeacdb9033d3; **scope:** architecture/delivery decision only, not production authorization.

## Context and invariants

IZO_ASA currently has a Windows service-promoter contract in main, isolated Docker DEV in main and additional unmerged Docker/shadow/preprod work. These are not two accepted releases. [Repository policy](../AGENTS.md), [production runbook](production-release-runbook.md), [backup runbook](backup-restore-runbook-20260713.md), [Docker acceptance](docker-delivery-acceptance.md) and [program #238](https://github.com/spikeal8-maker/IZO_ASA/issues/238) govern the work.

The source of truth for business rules remains **one backend, one frontend, one schema/migration chain, one accounting and authorization policy, one provider interface set**. Installation identity is separate: each deployment has its own DB, media, encryption keys, runtime processes and operator-owned configuration. No shared writable SQLite or unguarded cross-platform secret copy is allowed.

## Decision

1. Retain **spikeal8-maker/IZO_ASA**, a modular monolith; no new product repository, second application backend or duplicated React frontend. **izo-asa-platform** remains unrelated.
2. Delivery adapters own only configuration/profile validation, service or container process orchestration, file/secret locations, provider network bridges, installation, updates and rollback. Product APIs, durable worker logic and payment rules stay platform-neutral.
3. Windows Native reuses the existing installed **release promoter** and its exact-source verification; extend it with clean install/bundle packaging rather than building another updater. Never infer installed state from repo main.
4. Docker Production evolves the existing DEV/Shadow/Preprod work through review. Publish immutable OCI image digests and a hardened Compose profile; default non-root, persistent SQLite/media, stable secrets, network allowlisting, service/readiness checks and durable worker ownership. DEV Compose is not promoted by renaming its environment.
5. A **single release factory** builds Windows x64 bundle and OCI/Compose from the **same merged source SHA**. A machine-readable manifest binds semver/tag, full SHA, artifact checksums, image digests, schema compatibility/migrations, runtime capabilities, build IDs and exact-head test/review receipts. Unproven target stays unreleased.
6. Build source can be identical while capability activation depends on tested profile and explicit provider availability. GPU services may remain host-native behind reviewed adapters. No fabricated GPU or paid-provider PASS.
7. SQLite backup uses SQLite Backup API; media hashes, DB↔media links, ledger invariants and migrations are verified together. Portable restore requires supported schema, quiesced writers, isolated target and authorized secret re-enrollment (Windows DPAPI cannot be copied into Linux).
8. No public cutover, service restart, DNS/FRP/network edits, production DB/provider usage or change to repository visibility without separate owner-approved **release-ops** scope. Published candidate is not an installed release.

## Ownership and sequencing

| Scope | Result | Prerequisite / gate |
|---|---|---|
| DUAL-00 | Source/PR inventory + this proposed ADR | [#239](https://github.com/spikeal8-maker/IZO_ASA/issues/239); review, required CI |
| DUAL-01 | Shared configuration, lifecycle and health/readiness contract | Review accepted ADR and map; characterize existing runtime before edits |
| DUAL-02 | Native Windows bundle/install/update/rollback wrapper | DUAL-01; existing promoter and restore contract, no parallel updater |
| DUAL-03 | Production Docker Compose/OCI + worker ownership | DUAL-01; resolve and integrate applicable #195→#217 plus #218/#219 P0; no cutover |
| DUAL-04 | Exact-SHA GitHub release factory for both targets | DUAL-02 and DUAL-03 packaging contracts; supply-chain and CI |
| DUAL-05 | Independent parity/negative/fault/financial tests on both packages | DUAL-04 candidate artifacts; fake providers, isolated state |
| DUAL-06 | Windows↔Docker export/restore rehearsal and schema compatibility | Both clean installs, storage/ledger contracts and worker quiescence |
| DUAL-07 | Release candidate, guides, GO/NO-GO and optional later cutover | All gates passed; live migration needs separate owner approval |

Work on unrelated safe scopes may run independently with one writer per path. Each scope gets its own Task Contract, PR, exact-SHA checks and independent reviewer. Existing governance owner remains [NOW](NOW.md); stale routing is repaired in a separate package.

## Alternatives rejected

- **Two repositories/backends/frontends:** causes business-rule, billing and schema drift; rejects portability requirement.
- **Rewriting the Windows promoter:** creates competing release authority and bypasses existing rollback/preflight.
- **Making DEV Compose production by flags:** lacks mandatory production/recovery/security evidence.
- **Forcing PostgreSQL or containerized GPU now:** unrelated migration risk without proven product need.
- **Immediate Docker cutover:** risks live image/video/media/ledger and violates separate authorized operational acceptance.
- **Blind cherry-pick of stacked PRs:** loses ancestry, fixes and independent source receipts.

## Consequences and required proof

This decision deliberately preserves two packaging implementations but no duplicate product behavior. Releases are blocked until Windows Native and Docker **both** pass clean install, same-SHA identity, updates, persistent data/restore, account/media isolation, paid idempotency, crash recovery, secrets, supply-chain and platform-specific E2E. A green build or HTTP 200 is insufficient. See [inventory status/gaps](dual-runtime-delivery-inventory.md).

**Decision status does not change to ACCEPTED** until DUAL-00 passes exact-head required CI, independent review, and the owner-approved merge route. The current document authorizes no production operations.
