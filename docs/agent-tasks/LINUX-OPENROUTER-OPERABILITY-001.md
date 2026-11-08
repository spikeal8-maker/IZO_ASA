# LINUX-OPENROUTER-OPERABILITY-001

## Outcome and boundary

The owner can save an OpenRouter inference key in the existing Linux admin UI,
see whether storage and provider verification each succeeded, and check the key
again after a container replacement without entering it again. Acceptance uses
provider GET requests; it does not require a paid generation.

Before: Linux selected Windows DPAPI, so Save failed before provider validation.
The UI cleared input and reported success even on HTTP503. The backend had no
OpenRouter egress or persistent secret volume.

After: Linux uses a private persistent AES-256-GCM store; Windows retains
CurrentUser DPAPI. An opt-in HTTPS proxy permits only the required OpenRouter
origin and methods. Storage failures preserve input. Successful storage with
unavailable provider verification is reported as saved but unverified.

Machine scope is `tasks/LINUX-OPENROUTER-OPERABILITY-001.toml`, based on
`4ccd61920a63f0b0961c992efca2fe75be020d35`. One canonical writer owns the feature
worktree. The product, container and operational pieces belong together here:
storage alone cannot make the existing isolated Linux Save/Check path work.
Limits remain 24 production files and 7000 changed handwritten lines; global
architecture, context and test-health limits are not raised.

Non-goals: paid probes, historical replay, password changes, provider-key
rotation, a new installation, public-domain switching, generic internet access,
ASA Lab or other Docker projects, FRP/DNS/VPS changes and global GPU operations.

## Accepted installation retained

Host `admins-MS-7D22`, installation `asa-test`, project `izo-asa-linux-test-a`,
URL `https://izo-test.asa-lab.ru`. Accepted source is
`80b7698d23b7a94ea674c8c72b5347a7b98a41cc`, release
`80b7698d23b7-20261108111023`, tree
`04ceb1f2f963d1e16bd5334da81d2708c95e446a`. PR279 is merged; the retention package
is CLOSED. The public `izo.alikinas.ru` is not part of this update.

The historical reference remains snapshot `20261104T190706.420010Z`, seal
`8b2f2979eaf028e77f2fe9b81d229b553f1d525a6aa340a732d61e1f150462d1`.
Keep `izo-asa-linux-test-a_history-20261108-sqlite` and
`izo-asa-linux-test-a_history-20261108-media`, their originals and all original
snapshots. Reference counts remain 60 users,1952 images,60 videos,1854 jobs and
2939 ledger rows; authorized later additions are compared separately.

Prior acceptance operation `449bcfdf540d46a78fe3d21c1917e5c9` completed at
2026-11-08 12:32:44 UTC: genuine owner login, Flux Klein 4B, historical media and
restart checks. Post-browser receipt SHA256 is
`a81be5c44c171300369991f3c8ad0c0151a3d46608ebe428a2b968af86c6ab91`;
activation completion receipt is
`7142e4f836bb02d09a17558c2d171c2070cfd07b08222575db9e8225f4014de9`.
These receipts are under the existing release-finish-002 operation directory.

## Implementation contracts

- Linux uses pinned `cryptography==50.0.2`, a 32-byte master, random nonces and
  authenticated provider/version/name binding. Root0700 and files0600 must belong
  to the runtime UID. Original paths are checked without following links.
- Stable flock serialization, atomic replacement, fsync and authenticated
  readback protect concurrent writes. Existing encrypted documents are checked
  before adding another name. Missing/corrupt master material is never replaced.
  An error after replacement means durability could not be confirmed; it does
  not promise rollback. Interrupted restore remains marked and unusable.
- Platform factory preserves Windows DPAPI. Legacy migration uses atomic
  set-if-absent and explicit SQLite apply transactions; different protected
  material is never silently overwritten. Sealed-history startup migration
  remains disabled.
- Trusted admin and existing cookie/Origin CSRF checks precede mutation. Invalid
  input, provider bodies, transport exceptions and validation errors cannot
  echo key material. Audit appends use the existing actor/action/outcome mechanism.
- `keySaved`, `keyVerified` and environment override are distinct. Fresh Check
  uses no-store GET status. An ordinary valid inference key remains valid when
  management-only `/credits` returns403. Unknown or malformed HTTP200 key data
  does not count as verification. UI clears input only after confirmed storage.
- Backend UID10001 gets no direct internet or DNS. Dedicated proxy UID10003
  reaches only prepared public IPv4 addresses on443, with CA/hostname verification,
  TLS>=1.2 and exact SNI/Host `openrouter.ai`. UID10002's existing Comfy route,
  namespace, capabilities and global-GPU prohibitions remain unchanged.
- The opt-in profile is `comfyui-openrouter-v1`; Comfy's own profile remains
  `comfyui-private-v1`. The backend uses `closed-proxy-v1` transport through
  `http://127.0.0.1:18189/api/v1`. No redirects, CONNECT, foreign endpoint
  credentials, environment proxy or remote image downloads can bypass it.
- GET permits only key/credits and bounded image/text/audio/video catalog paths.
  POST permits chat completions and images, never video/payment/key management.
  Upstream and request parsing have absolute deadlines. SSE is streamed with
  bounded memory and valid framing. No POST is retried after request bytes were
  sent. Only the existing explicit size:auto rejection retry is retained.

## Persistent volume and local recovery

External volume `izo-asa-linux-test-a-secrets-v1` mounts only into backend at
`/home/izo/secrets`; `IZO_SECRET_DIR` points there. Canonical
`prepare_linux_secret_volume.py` accepts exact backend image/source and an output
receipt. Without `--apply`, an absent volume is only planned. Apply creates only
the missing owned local volume, verifies its creation nonce and emptiness, then
sets10001:10001/0700 through an isolated root oneoff with only CAP_CHOWN. Existing
volumes are validated read-only and never repaired, chmodded or reinitialized.
All runtime checks use isolated Python and explicit conditions, not assertions.

Labels bind project, protected-secrets purpose, package, version1 and a unique
initialization nonce. READY records identity, ownership/mode/counts and source
pins; it contains no secret filenames, values or secret-derived fingerprints.
Validate readiness before stopping the accepted application.

Secret recovery is LOCAL, outside the DB/media outgoing directory. Do not upload
this volume/archive to Yandex or add it to cloud3. Backup reads a consistent
shared-locked read-only mount and streams master plus authenticated documents
directly into age; no plaintext temporary archive exists. Publish ciphertext
create-only after successful encryption and fsync. Restore accepts only an empty
protected target, validates every size/name/document before writes and confirms
readback before clearing its incomplete marker.

Bundle CLIs run inside the exact verified backend image as UID10001, networknone,
rootfs read-only, no capabilities and no-new-privileges. Use `python -I -B` with
`--backend-root /opt/izo/backend`; production modules come from that image. The
bundle/tool mount is read-only. Backup takes `--secret-dir`, private `--output`,
public `--recipient` and `--age-binary`; restore takes `--secret-dir` and decrypted
stdin. Outside the installed image or explicit owned source runtime, the CLI
fails before touching secret material. Help requires no backend import.

The host privately derives the recipient from
`/srv/izo-asa-deploy/private/backup.agekey`. Never mount this identity in the
container or print either key. The approved `/usr/bin/age`1.1.1 binary has SHA256
`529450dfeaf3055cb24d76789d0b1f5eb8cd23e03dc4add64f84776df1272b02`;
bind it read-only after confirming compatibility with the candidate image.
For restore, host age decrypts directly into the container's stdin; require both
upstream age and downstream restore exits0. A filename alone is not restore proof.

## Data write set and release acceptance

Save changes the external secret document, invalidates memory caches, deletes
only a legacy `admin_secrets.openrouter_api_key` row if present, and appends a
redacted existing admin audit event. The accepted database has no legacy row.
Catalog refresh changes memory only: no `admin_settings`/`model_profiles` writes
or enable flips. Existing jobs, images, balances, ledger, passwords, outboxes,
payments and publications retain the original sealed comparison. Provider
availability must not re-admit old work. Do not rebase historical proofs.

Required sequence: independent frozen-source review; mandatory exact-head CI;
canonical bundle build and bounded profile/secret-volume preparation; checkpoint
and pause only captured maintenance schedules; native1Panel update of the same
project; genuine owner UI Save and fresh Check; restart persistence; local
encrypted backup/empty-target restore; historical comparison; resume captured
schedules and independent external HTTPS/version proof. If private key entry is
needed, the owner enters it in the browser, never chat. Never read the input value.

Every canonical `--build-images` now requires a POSIX probe in the exact built
backend image: UID10001, networknone, no application startup/conftest, production
module hashes and dependency pins, candidate tests/CLIs read-only, no skips or
zero-test success, and owned-container cleanup. It also executes packaged restore
in a separate process against synthetic material. The existing receipt and
inventory-hashed bundle proof carry the result; CI workflows are not bypassed.

Observed candidate evidence: native operation `165d1fc63c774cec89eea730b6d0befd`
ran480 focused tests successfully with2 Windows-only skips, then actual age1.1.1
encryption/decryption and authenticated restore of2 disposable fixture documents;
source bytes were unchanged and all fixture material was removed. Real Windows
DPAPI, full integration CI and actual image/owner runtime acceptance remain
required. No deployment is inferred from these isolated checks.

Rollback restores prior images/source and scoped Compose while keeping current
historical DB/media and the new secret volume/local archive. Never restore an old
database over current state. The old source may leave OpenRouter unavailable;
it does not justify discarding or regenerating protected secret material.
