# LINUX-COMPOSE-ROUNDTRIP-001 — administrative closeout

## Status

**UNMERGED_ACCEPTANCE_NOT_MET.** This is an evidence-preserving retirement,
not a completed feature, a passed native acceptance or a deployment.

Native registration used actual base `a25bc81fc65f070d07a38279af5449f4174030a6`
and retained the original machine contract in
[`tasks/LINUX-COMPOSE-ROUNDTRIP-001.toml`](../../tasks/LINUX-COMPOSE-ROUNDTRIP-001.toml).
The candidate implementation was not published, merged or deployed; it has no
candidate PR or mandatory candidate CI result.

## Verified Evidence And Blocker

- Registration: operation `8a9c3561f4074789873f73eb29a69f57` observed `AGENT_PACKAGE_STARTED`.
- Focused verification: operation `111c60bf2f5544b7ad1d2cd6c85520bb` passed 238 profile and 140 bundle tests, with no skips.
- Scope verification accepted four files and 342 changed lines against the original 400-line limit.
- Native probe `514fb251b6b34a8cbafe74c26eb39767` stopped with `NATIVE_COMPOSE_VERSION_CHANGED` before either checker ran; it is not a red/green result.
- Normal and isolated native commands both returned exact version `2.40.3+ds1-0ubuntu1~24.04.1`, not the contract's literal `2.40.3`.
- Installed plugin SHA256: `d87a11e944c990dc9f2186115b1136c1cbffffc870845caff0cbdcce0780f41d`.
- Static binary dependency records identify compose-go `v2.9.1`; that evidence does not authorize stripping the native version suffix or accepting another version.

Passing focused tests and an independent source review do not replace the
unmet native-version acceptance. No synthetic or nominal-version PASS is
reported, and the original task manifest is not rewritten to fit the host.

## Preservation And Handoff

Before restoring files, preserve the exact four-file candidate, its hashes,
all focused/scope receipts, failed probe output and subsequent diagnostic
observations in private operation evidence. Keep the original evidence intact.
Restore only the two owned tool files to their exact base bytes; retain the
original manifest and this truthful closeout as the administrative commit.
Do not present that commit or the standard owner finish as feature completion.

Successor: **LINUX-COMPOSE-UBUNTU-001**, registered separately from the actual
current main after review of its own contract. Its proposed supported version
is the exact observed Ubuntu build string, with comparison profile
`compose-2.40.3-ubuntu24.04-json-v1`; no generic version normalization is allowed.

No historical or public data, application runtime, provider, authentication,
Docker lifecycle or 1Panel deployment is changed by this administrative handoff.
