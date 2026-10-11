# Isolated Docker Shadow — SHADOW-TOPOLOGY-01

This is the first implementation slice of Issue #125, not acceptance of the
whole shadow migration. It reuses `ops/docker/dev/compose.yml` and its backend
image and persistent SQLite/media volumes. The opt-in `compose.shadow.yml`
overlay adds a built frontend and loopback access on separate ports. It does
not replace the accepted, unpublished, network-disabled DEV default.

## Topology and boundaries

```text
localhost:48125 -> shadow web -> shadow backend:8000
localhost:48126 --------------------^
                         own SQLite/media volumes
                         internal Compose network only
```

- Docker Desktop Linux context; Compose 2.24+ (`!reset`) is required.
- The project name must start with `izo-asa-shadow-`. Each project owns its
  network and two named volumes. No bind mounts, Docker socket, GPU access,
  production directories, host network or public routing are used.
- Both published ports bind to `127.0.0.1`; accepted ports are distinct and
  between 20000 and 65535. The default ports avoid native production listeners.
- All services join only the project-owned internal network. Real provider
  URLs and credentials remain disabled; the existing mock image fallback and
  fake TTS are enabled. There are no provider endpoint overrides in this slice.
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
- The web process is non-root/read-only with temporary files in tmpfs. Backend
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

The smoke command checks image revisions, running/healthy state, loopback-only
bindings, internal network membership, mounts, empty provider credentials,
frontend assets, `/`, `/feed`, `/gallery`, health and API access. It probes TCP
access to native host listeners and an external address and requires failure.

It creates a dedicated fixture SQLite file in the shadow data volume and a
media marker, then performs **two actual down/build/up cycles** with the same
named volumes. Marker contents, application table counts and read-only SQLite
integrity must survive both cycles. It never writes directly to application
tables or impersonates an application user. The fixture proves storage topology,
not complete authentication/generation/gallery/billing acceptance.

The JSON receipt under `.runtime/shadow/<project>.json` records source/config
identity, container/image IDs, ports, volumes, checks, timestamps, resource
sample, failures and limitations. A failed attempt stays FAIL. A separate
receipt path (`--receipt`) preserves each attempt instead of overwriting it.
The successful smoke leaves the shadow running for inspection. Test marker
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
