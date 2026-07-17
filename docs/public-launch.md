# IZO_ASA public launch and release identity

This is the operational contract for the current Windows single-computer
production. The domain transport uses the existing FRP path through the VPS. The
scripts in this repository do not modify the VPS configuration.

## Development and public launchers

| Script | Purpose | Frontend on 5173 |
|---|---|---|
| `start-project.bat` | local development only | Vite dev server |
| `start-public.bat` | controlled public release | immutable release directory through Vite preview |
| `start-public-autostart.bat` | public release plus local FRP verification | immutable release directory through Vite preview |
| `stop-public.bat` | stop local public processes | none |

Never expose the Vite dev server through the public domain. A public page must
have hashed assets, no `/@vite/client`, no raw `/src/main.tsx`, and a matching
`izo-release` meta marker.

## Required local runtimes

The tracked pins are authoritative:

- `.python-version`: Python 3.11.9;
- `.node-version`: Node.js 24.14.1;
- backend runtime: `backend/.venv/Scripts/python.exe` only;
- frontend dependencies: `frontend/node_modules` installed from `package-lock.json`.

Create the backend environment from the repository root:

```powershell
& 'C:\Program Files\Python311\python.exe' -m venv .\backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
.\backend\.venv\Scripts\python.exe -m pip check
```

Production startup fails before listener mutation if the project environment is
missing, has the wrong Python version, or a global Python executable is selected.

## Immutable release identity

Every public candidate gets a unique directory under
`.runtime/releases/frontend/<release_id>`. Its `release-manifest.json` contains
only non-secret build facts:

- manifest version and release ID;
- full Git SHA and `dirty=false`;
- UTC build time;
- deterministic frontend asset count and SHA-256 inventory hash;
- exact Python and Node.js versions;
- supported SQLite schema-version range.

The release ID begins with the first 12 characters of the same full Git SHA. The
manifest filename, parent directory, checkout SHA, clean-worktree state, runtime
versions, frontend asset contents and SQLite `PRAGMA user_version` are all checked
before the old backend is stopped. Do not edit a generated release directory.

The frontend build ID has one source: the value injected by Vite into both the JS
bundle and `<meta name="izo-release">`. There is no manual source-code build label
to bump.

## Required verification before a public release

From the canonical project directory:

```powershell
.\tools\verify.ps1 -Mode CI
.\tools\verify.ps1 -Mode Full
.\tools\verify.ps1 -Mode Quick
git status --short
git branch --show-current
```

The release checkout must be clean and on `main`. `CI` runs the complete isolated
backend/tools and frontend gates. `Full` runs the same code gates plus read-only
live listener/media checks. `Quick` runs the smaller contract suite plus those live
checks without restarting or mutating data.

The normal launcher has no verification bypass. When no receipt is supplied,
`publish-frontend-release.ps1` runs `Full`, writes a four-hour exact-SHA receipt
under `.runtime/verification`, validates it, and only then builds a candidate. A
fresh receipt may be reused for the same clean SHA by setting
`IZO_VERIFICATION_RECEIPT`; a changed verifier hash, missing gate, dirty checkout,
different SHA or expired receipt fails before candidate build and listener changes.

## What `start-public.bat` does

1. Verifies the PRIMARY server role and live SQLite path/size guard.
2. Runs or validates the exact-SHA verification receipt.
3. Builds a new frontend candidate with an exact release ID.
4. Generates and validates `release-manifest.json` from a clean `main` checkout.
5. Starts an isolated candidate preview on port 5197 and runs browser smoke for
   `/`, `/feed`, `/gallery` and `/profile`.
6. Starts the candidate on `127.0.0.1:5173`, verifies its exact meta, then atomically
   changes the active manifest. An activation failure restores the previous listener
   while the old manifest remains active.
7. Calls `tools/restart-backend.ps1` with the same manifest and project `.venv`.
8. Requires the new backend to be ready and to report the exact manifest release,
   frontend release and full commit.
9. Verifies the release meta actually served on 5173, `/api/version`, and the
   expected unauthenticated 401 responses for generation, gallery and identity.
   Because `/feed` and `/gallery` are backend-owned static shells, their post-switch
   `X-IZO-Release` headers must also match the same manifest.

Run it interactively:

```powershell
.\start-public.bat
```

For Task Scheduler/Startup-folder execution, `start-public-autostart.bat` sets the
non-interactive mode and verifies the existing FRP client after local activation.

## Emergency break-glass

Break-glass bypasses only the full test receipt. It does not bypass a clean `main`,
TypeScript/Vite build, immutable manifest, candidate browser smoke, release identity,
backend restart checks or final auth smoke. Use it only when waiting for the full
gate creates a larger incident than an unverified release:

```powershell
.\tools\publish-frontend-release-break-glass.ps1 `
  -Operator '<operator>' `
  -Reason '<at least 20 characters describing the incident>' `
  -Acknowledgement 'I_ACCEPT_UNVERIFIED_RELEASE_RISK'
```

The command creates a ten-minute single-use authorization and appends requested plus
completed/failed events to
`.runtime/audit/release-break-glass/release-break-glass.jsonl`. It runs the complete
`start-public.bat` flow and reports success only when active frontend/backend release
IDs match. Authorization and audit files contain no provider secrets, but they are
local evidence and must be included in later offsite/observability work.

## Health and diagnostics

- `GET /api/health` is public and intentionally minimal: application, release ID
  and readiness only.
- `GET /api/version` returns only the immutable release identity plus process
  start time.
- `GET /api/admin/runtime-health-v2` contains database, environment, ComfyUI and
  runtime details and requires a trusted administrator session.

Useful read-only checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/version
.\tools\check-runtime-listeners.ps1
```

## Backend restart and rollback boundary

Do not run an ad hoc `python -m uvicorn` command for public production. A managed
restart requires the active manifest:

```powershell
$active = Get-Content .\.runtime\active-frontend.json -Raw | ConvertFrom-Json
.\tools\restart-backend.ps1 `
  -RepoRoot $PWD.Path `
  -PythonPath .\backend\.venv\Scripts\python.exe `
  -ReleaseManifestPath $active.release_manifest
```

The helper validates ownership of the existing `127.0.0.1:8000` listener and
requires `--no-proxy-headers`. If the replacement fails after the old process was
stopped, it attempts an availability rollback and reports that rollback explicitly.
On a true cold boot, only the public launcher passes `-AllowColdStart` after it has
created and validated the release manifest.

On Windows, the virtual-environment redirector remains as the launcher while its
base `python.exe` child owns the listening socket. This is accepted only when the
listener's direct parent is the exact project `.venv` executable and both processes
carry the expected bind, port and `--no-proxy-headers` Uvicorn command. The active
backend receipt records both PIDs and `runtime_ownership=windows-venv-child`.

Frontend rollback validates the selected artifact before replacing port 5173:

```powershell
.\tools\rollback-frontend-release.ps1 -PlanOnly
.\tools\rollback-frontend-release.ps1 -ReleaseId <previous_release_id>
```

REL-001 now restores the previous frontend when listener activation fails. A true
zero-downtime edge/API A/B switch and immutable old-backend artifact are still
tracked in `EDGE-001` and `REL-002`; do not describe those as already solved.

## Windows autostart

`tools/start-production-stack.ps1` starts or verifies Ollama, ComfyUI, FRP and the
public launcher. It no longer starts an unmanaged bootstrap backend. A cold backend
is created by the same manifest-controlled path as a normal release.

The Startup-folder launcher runs under the intended Windows account, not `SYSTEM`,
because CurrentUser DPAPI secrets and local model stores are account-bound. The
existing `C:\izo-generator` junction may be used to avoid Cyrillic-path parsing
issues during logon.

Read-only stack verification:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\start-production-stack.ps1 -CheckOnly
```

Vite preview remains a transitional local server. Replacing it with local Caddy is
the separate `EDGE-001` package and does not require changing the VPS tunnel.
