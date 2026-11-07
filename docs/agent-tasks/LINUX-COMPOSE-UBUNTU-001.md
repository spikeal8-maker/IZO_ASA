# LINUX-COMPOSE-UBUNTU-001

## Contract

The [machine contract](../../tasks/LINUX-COMPOSE-UBUNTU-001.toml) owns this
four-file source-only fix, based on actual PR274 merge `a25bc81fc65f070d07a38279af5449f4174030a6`.
Its predecessor was closed **UNMERGED_ACCEPTANCE_NOT_MET**, not accepted or deployed.

The comparator supports only exact version `2.40.3+ds1-0ubuntu1~24.04.1` and
profile `compose-2.40.3-ubuntu24.04-json-v1`. It preserves explicit raw bind
policy, source/image pins, both raw JSON hashes and type-strict whole-object comparison.
Only expected-dependent null inheritance, empty IPAM, existing empty bind options,
implicit guard dependencies and two guard-port representations are allowed.
The actual unchanged-fixture observation has 21 differences; count alone authorizes nothing.

## Acceptance Boundary

Both modes require positive and adversarial regressions, native config-only old
DRIFT/new PASS with the exact installed plugin, independent review and exact-head CI.
The fixture, CLI argument builder, native-base policy and renderer remain unchanged.
Native receipts and reviewed hashes belong in the PR evidence, not this stable contract.
No provider, authentication, history, image build, container lifecycle or deployment
is authorized here; a later release requires separate operations ownership.
