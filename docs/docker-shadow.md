# Isolated Docker Shadow вЂ” SHADOW-TOPOLOGY-01

This is the first implementation slice of Issue #125, not acceptance of the
whole shadow migration. It reuses `ops/docker/dev/compose.yml` and its backend
image and persistent SQLite/media volumes. The opt-in `compose.shadow.yml`
overlay adds a built frontend and loopback access on separate ports. It does
not replace the accepted, unpublished, network-disabled DEV default.

## Topology and boundaries

```text
localhost:48125 -> shadow web -> 127.0.0.1:8000 backend
localhost:48126 --------------------^
                  shared guarded network namespace
                         own SQLite/media volumes
                         own bridge, stateful OUTPUT deny, IPv6 disabled
```

- Docker Desktop Linux context; Compose with `up --wait` is required.
- The project name must start with `izo-asa-shadow-`. Each project owns its
  network and two named volumes. No bind mounts, Docker socket, GPU access,
  production directories, host network or public routing are used.
- Both published ports bind to `127.0.0.1`; accepted ports are distinct and
  between 20000 and 65535. The default ports avoid native production listeners.
- Docker Desktop suppresses published ports on `internal: true` bridges (the
  first preserved smoke attempt failed with healthy containers but no ingress).
  A project-owned namespace guard installs an atomic nftables OUTPUT policy
  before readiness: accept loopback, accept established/related replies, then
  count and drop everything else. Default deny also covers the numeric gateway
  IP and other directly connected bridge nodes. Routes stay intact so published
  ingress replies work. IPv6 is disabled; DNS forwarding is limited to loopback.
  Guard uses the existing pinned Python base plus the necessary nftables OS
  package. No Windows/host namespace/firewall or Docker-wide settings change.
  The initializer has NET_ADMIN/SETUID/SETGID, then drops root IDs and effective
  capabilities. Backend/web have no added capabilities and cannot alter policy.
  The guard-only health subprocess reads the exact kernel rules with NET_ADMIN;
  missing, reordered or extra rules fail readiness. Both apps require a healthy
  guard before startup. Real providers and credentials stay disabled.
- The frontend is built using the repository's Node pin and lockfile. Base
  images are digest-pinned. Both application images carry the exact source SHA;
  frontend HTML/JavaScript embeds it too. The backend intentionally retains the
  accepted **unmanaged DEV release identity**. Its `/api/version` is not a
  production release receipt; source is proven by checkout/image labels.
- Cookie origins are restricted to the selected local web port. Nginx rejects
  foreign Host values and forwards Origin unchanged to the existing API checks.
- The launcher drops ambient Compose files, `.env`, credentials, proxy settings
  and provider overrides. Only OS/tool discovery variables and explicit shadow
  identity/ports reach the Docker CLI; containers receive Compose's fixed env.
- Startup requires a clean exact-SHA checkout of this repository. Existing
  containers, networks or volumes with foreign ownership cause a hard failure.
- Before starting or recreating containers, the launcher inspects all three
  local images and requires the exact source revision and repository labels.
  Compose receives their checked immutable image IDs through a temporary
  override, with build and pull disabled. Retagging an image after inspection
  cannot change the selected image. The override is removed on success/failure.
- Image builds run sequentially, with the frontend Node heap capped at 1 GiB,
  to limit peak Docker Desktop memory use. A failed build does not start or
  replace the running shadow containers.
- The web and running guard processes are non-root/read-only with temporary
  files in tmpfs. Backend
  resource limits/non-root settings come from DEV. Shutdown has bounded grace.

## Run from a clean feature checkout

```powershell
$sha = git rev-parse HEAD
python -m tools.docker_shadow config --project izo-asa-shadow-local --source-sha $sha
python -m tools.docker_shadow up --project izo-asa-shadow-local --source-sha $sha
python -m tools.docker_shadow smoke --project izo-asa-shadow-local --source-sha $sha
```

Open `http://127.0.0.1:48125/`. The API is also available at
`http://127.0.0.1:48126/api/health`. For additional isolated instances, supply a
new project and distinct `--web-port`/`--api-port` values on every command.

The repair smoke captures a read-only production baseline, performs an owned
`up`, checks topology/HTTP/network/storage, then performs `recreate` and repeats
those checks. It records a comparable production snapshot even after a failure.
Snapshots contain selected version fields, service/process PID/start identities,
owned service listeners, service-definition/routing-config hashes and foreign
Docker resource identities. Config contents, command lines and secrets are never
included. This proves only the newly controlled window; the missing baseline
before the original implementation cannot be reconstructed retroactively.

Network proof reads the actual gateway from Docker network inspect. Numeric
connections to gateway, a controlled bridge peer and an external IP must time
out AND increment the exact kernel DROP counter. ECONNREFUSED, DNS errors and
missing routes are not accepted. A separate unfiltered client on the same owned
bridge must reach the controlled listener. Test containers have no host mounts,
published ports or capabilities and only their verified IDs are removed.

**GATEWAY_LISTENER_PROOF_BLOCKED:** the actual Docker bridge gateway is owned by
Docker Desktop's host VM. A listener there would require forbidden host networking.
The numeric-gateway kernel DROP evidence and controlled bridge-peer listener are
reported separately; they do not claim a listener on the gateway itself. Until
that criterion has safe independent evidence, the receipt remains BLOCKED, smoke
exits nonzero and the PR stays Draft. No policy is weakened to pass a probe.

Storage proof uses a dedicated fixture SQLite row and media marker. The app DB
is opened read-only for integrity/table counts. Markers and counts must survive
recreate. Original two down/build/up receipts remain historical evidence; the
repair does not retrospectively give them a production baseline or replace
full user-flow persistence acceptance.

The JSON receipt under `.runtime/shadow/<project>.json` records source/config
identity, container/image IDs, ports, volumes, checks, timestamps, resource
sample, failures and limitations. A failed attempt stays FAIL. A separate
receipt path (`--receipt`) preserves each attempt instead of overwriting it.
The repair smoke leaves the shadow running for inspection, including a BLOCKED result. Test marker
files and owned volumes remain; these are deliberate safe fixture resources.

```powershell
python -m tools.docker_shadow status --project izo-asa-shadow-local --source-sha $sha
python -m tools.docker_shadow recreate --project izo-asa-shadow-local --source-sha $sha
python -m tools.docker_shadow down --project izo-asa-shadow-local --source-sha $sha
```

`down` stops only the named, ownership-checked project and **retains volumes**.
It is allowed from a dirty checkout to permit recovery after edits. There is no
global cleanup, volume deletion, orphan deletion or production switching command.

## Still required before Issue #125 acceptance

- Three independent fixture runs covering genuine login/session, queued image
  generation, tokens, ownership, favorite/use-as and publication/moderation flows.
- Worker crash/recovery, cancellation/idempotency, isolated backup/restore and
  bad-backup/storage failure evidence required by D2 and Issues #118/#119.
- Supported-feature parity matrix, native comparison and agreed resource/load
  baseline required by D3 and Issue #120. This smoke takes only a resource sample.
- Stable portable test-secret configuration and explicit container release
  identity semantics before a production-like acceptance.
- Independent review and exact-head CI for this package.

Real host GPU/provider access is deliberately a separate reviewed slice; no
real provider is claimed verified here. Issue #126 and production traffic/data,
services, Caddy, FRP, DNS and VPN remain outside this package.
