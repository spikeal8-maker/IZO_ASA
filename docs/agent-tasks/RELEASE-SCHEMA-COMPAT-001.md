---
status: code-complete
id: RELEASE-SCHEMA-COMPAT-001
risk_class: high-assurance
domain: release-schema-compatibility
---

# RELEASE-SCHEMA-COMPAT-001

## Task Contract

```yaml
id: RELEASE-SCHEMA-COMPAT-001
goal: Keep the immutable release manifest compatible with every additive migration implemented by the release.
userOutcome: The production backend can start after migration 7 without weakening release identity checks or restoring the live database.
beforeScenario: Migration 7 is applied, but the generated release manifest declares max_version 6 and both the candidate and rollback backend fail closed.
afterScenario: A new exact-SHA candidate declares max_version 7 and the contract test derives the expected maximum from all declared MigrationDefinition values.
nonGoals:
  - restore or rewrite the production database
  - bypass release identity validation
  - retry the failed fc8da6d promotion
  - change providers, FRP, AdGuard, DNS or VPS configuration
domain: release-schema-compatibility
riskClass: high-assurance
declaredFiles:
  - architecture/contract.json
  - tools/test_build_release_manifest.py
  - docs/generated/architecture-inventory.json
  - docs/generated/architecture-inventory.md
  - docs/agent-tasks/RELEASE-SCHEMA-COMPAT-001.md
allowedPatterns: []
acceptance:
  - release contract max_version equals the highest declared migration version
  - a generated manifest accepts schema version 7
  - focused manifest and release-identity tests pass
requiredEvidence:
  - focused test output
  - regenerated architecture inventory
  - clean commit and exact-SHA CI
  - fresh release receipt before any new promotion
targetedTests:
  - backend/.venv/Scripts/python.exe -m pytest -q tools/test_build_release_manifest.py backend/test_release_identity.py
forbiddenOperations:
  - production database restore or manual mutation
  - editing an immutable candidate
  - rerunning the failed one-shot deployment wrapper
rollbackBoundary: Revert the hotfix commit before a new promotion; production database migration 7 remains additive and is not rolled back.
```

## Incident evidence

The `fc8da6d3917b2a198c114d6b78a1e9514b796cf2` candidate passed CI and Full
verification, then applied migration 7 during its single promotion attempt.
Startup failed because its generated manifest declared `max_version: 6`.
Automatic code/config rollback restored `d223c179...`, which then also failed
closed against the now-additive schema version 7. No database restore is
authorized by this package.
