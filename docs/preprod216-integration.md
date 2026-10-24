# D2R2-PREPROD-INTEGRATION-001 — single-app isolation and acceptance

Issue [#216](https://github.com/spikeal8-maker/IZO_ASA/issues/216).
Integration source is stacked on the existing protected native4b OpenRouter candidate, PR #215 exact `1fede386664c41141c0611919a2d15c31cfd4d5f`, which itself includes PR #211 and PR #209. PR #200 Ollama UI remains a separate unresolved Draft.

## Local identity and immutable source

- User-facing site: **http://127.0.0.1:48314** on D2-R2 itself only.
- Internal diagnostics API: `http://127.0.0.1:48315`.
- Host-initiated ComfyUI control: `127.0.0.1:48316`; 96-character random token in `%LOCALAPPDATA%\IZO_ASA_Preprod216Runtime\bridge.token` with restricted Windows ACL. Never log or share this token.
- Docker Compose project: `izo-asa-preprod-d2r2-001`, new `10.249.221.0/28` isolated Docker network; guard at `.2`, OpenRouter-only HTTPS proxy at `.3:3128`. Public inbound ports: **none**.
- Separate named volumes for `sqlite-data`, `media-data`, `seed-data`, `openrouter-secrets` and `openrouter-master`. No mounts of previous Shadow volumes; the OpenRouter key and master from the old 48145 site are deliberately **not** copied.
- Source baseline, read-only: `D:\IZO_ASA_RestoreSandbox\full-20261024T082359.324871Z\baseline`; verified archive snapshot `20261024T082359.324871Z`, source database SHA256 `01d229746d493360c3e4ff1752915699a30297416787ddcb387a69ce982a8f2d`, media **2564 files / 696059427 bytes**.
- Source 48155 restore-only Docker volumes are **not imported**, because the mutable restore preview recorded an extra failed job (1843 versus the immutable baseline's 1842).

## Isolation and data migration

A one-shot, network-disabled restore helper must copy and SHA-verify the baseline SQLite and each media object into **fresh empty named volumes**. The clone preserves all 59 historical user rows, 26 password records, published feed, 1941 image records, 59 video rows, 1842 jobs, 18 chat threads and 90 messages. Only the cloned `auth_sessions` rows are revoked (without changing user/password/roles) and side-effect settings for bot integrations, mail, payment and external syndication are dropped from that clone. External Telegram/MAX polling, email, webhook, payment processing and public publishing stay disabled by backend environment. No personal data are committed to GitHub, uploaded elsewhere or placed in screenshots.

An initial post-copy audit verifies the DB receipts and hashes, user/media/feed/chat counts, SQLite integrity, 0 non-revoked historical sessions, and unchanged original source. Existing account login is verified by the **actual owner using the official form**; the automation neither knows nor resets any real user's password. Synthetic QA identity is created via official UI only. Historical private gallery/image IDs are never used as OpenRouter prompts.

## Cloud and local provider boundaries

- **Cloud text default: OpenRouter**. The backend's `HTTPS_PROXY` points to the new strict proxy. The only allowed CONNECT request is `openrouter.ai:443`; the app network namespace's nftables OUTPUT policy is DROP except loopback, stateful replies and TCP to the fixed proxy container IP. The proxy is not host-published. The owner must provide a fresh rotated API key via the new site's secure administrator UI; no existing key from 48145 or database is reused. Actual paid calls require explicit scope/budget authorization.
- **Local images: native FLUX.2 Klein 4B**. The Comfy bridge is the already-reviewed strict native4b graph, only 704×704/4 steps for the Studio supported preset, Windows-initiated polling to preprod's own token-protected control port. A dedicated owned Windows agent script is used. ComfyUI Portable, its installed GPU models and the 48214 agent are unchanged.
- **Ollama: fail-closed until a separately approved channel.** It remains configured as `127.0.0.1:1` inside preprod. Issue #201 requires independent security approval before opening a new Docker↔Windows host route. Do not enable Docker host gateway, `OLLAMA_HOST=0.0.0.0`, arbitrary CONNECT, or route Ollama through the OpenRouter proxy. The admin page from PR #200 is a separate candidate and is not automatically considered integrated.
- The physical RTX 4070 is shared with other services. No unattended five-cycle GPU alternation, model unloading or cross-program interruption is authorized until exclusive resource admission, provider approval and real-user authentication are verified. Cloud chat stays separate from heavy local GPU work.

## Verification and release gates

The final operational acceptance requires a **single, authenticated site** preserving the 89 historic published feed records (75 image, 14 video), private gallery and old chat history, followed by new saved text and image jobs, exact-once ledger, reload/restart and desktop 1440×900 / mobile 390×844 trials. Test public media byte ranges (206) and the previously reported one missing private thumbnail; any thumbnail recovery happens in the writable clone only. Do not assert PASS without these actual runtime proofs.

Snapshot and new candidate data remain private. A separate independent reviewer must check CSRF/auth, private-media isolation, outbound allowlists, Comfy host ownership and financial idempotency. GitHub Actions was previously blocked on the owner's billing/spending limit; local tests do not replace required hosted gates. Integration PR stays Draft and `main` untouched until all gates are fulfilled.

**Rollback:** stop only the preprod216 Docker project and its owned Windows agent; preserve receipts and named volumes until separately authorized deletion. Do not remove 48155/48145/48214/48135/48125 containers or their data, and do not alter the baseline.

## One known missing private thumbnail — scoped repair procedure

A read-only audit found exactly one historic `image_sources.thumb_url` referring to a missing private 384×384 WebP. The corresponding image belongs to the same user as its source and has a valid separate 512×512 WebP thumbnail. Historic private URLs contain a `userId` query: the repair parser preserves and validates this owner constraint; it does not treat the query as disposable. No private image, name, ID or path is published.

`tools/preprod216_repair_thumb.py` defaults to **dry-run**, requires exactly one missing thumbnail, verifies matching ownership, safe relative path, image content and size, and refuses to overwrite existing targets. Apply is permitted **only with the preprod216 site stopped, its owned media volume writable, candidate DB read-only, and a private receipt output in the same candidate's data volume**. Generated thumbnail is a single derived WebP, not a replacement for an original user image or a database mutation. `tools/preprod216_verify_runtime.py` accepts 2564 baseline media and exactly one new derivative only with a matching private receipt, SHA and byte size. The source baseline and old 48155 preview remain untouched.

The completed repair and authenticated private gallery display are distinct gates. A successful file-level repair does not prove that the historic user sees the thumbnail in the browser until legitimate account login is performed.

## Ollama administration UI integration (PR #200 scoped adoption)

The compact existing Ollama admin component from Draft PR #200, exact source `a9a3883e20bde8b00081bb6b3e0b604409be3832`, has been integrated into the preprod216 frontend without overwriting the overlapping existing OpenRouter, OpenAI or Config UI components from PR #215/#209. The administrative route `/admin/models/ollama` displays only backend-returned connectivity, model inventory and resident VRAM data, and uses the same server-side `/admin/assistants` setting endpoints as the original UI. Editing local model settings cannot implicitly publish paid/cloud chat models.

**Fail closed:** the route does not contact host Ollama directly; the actual candidate backend's `OLLAMA_BASE_URL=http://127.0.0.1:1` remains deliberately unreachable until a separately approved, restricted Issue #201 transport is implemented and independently reviewed. An unavailable/non-installed model cannot be switched on, tested or visually shown as enabled. This is a frontend integration and does **not** satisfy actual Ollama inference, combined GPU lease or privileged admin acceptance.

Frontend lint, production compilation and a dedicated offline admin-route safety contract are required on the final exact source commit. Authenticated administrator browser acceptance remains operator-gated: no fake session or restored owner's impersonation is permitted.

## 24 October 2026 — post-owner generation audit and effective-resolution guard

The operator's existing Pro/admin account performed **nine new completed jobs** in the owned candidate after the immutable restore: **seven native FLUX.2 Klein 4B** text-to-image jobs at 704×704/4 steps, **one OpenRouter** `openai/gpt-5-image-mini` image at 1024×1024, and **one OpenRouter** `bytedance/seedance-1-5-pro` text-to-video at 480p/4 seconds. Source baseline and user content were only queried read-only for the investigation; the candidate currently has 1949 image rows, 60 video rows, 1851 jobs and 90 unchanged historical chat messages. Eight PNG originals and eight WebP previews passed physical format/dimension and SHA256 readback and each maps to a distinct completed, owner-matching job. The video MP4 passed header, byte size (2,686,862) and SHA256 readback, with exactly one owner-matching gallery video row. Private job identifiers and content hashes remain on D2-R2; no prompts, user IDs, media paths, credentials or cookies are published here.

New internal token-ledger records show **seven daily-budget debits** for local jobs (one daily unit each, zero primary balance change), **one primary-balance charge of 1 token for cloud image**, **one charge of 4 tokens for cloud video**, an independent **+500 monthly tariff grant**, and one idempotent, zero-delta post-generation cloud-image reconciliation. The provider usage-derived token quote for that image was **2**, but **1** was reserved/charged. Existing `generation_accounting.reconcile_openrouter_token_charge` intentionally does not surprise-charge the user after completion and records `underestimated_tokens=1`, `settled_tokens=1`, and refund=0. This is economically under-recovered, not double-charged; any product-policy change to preauthorization/quote accuracy needs separate review, never retroactive billing. Provider-reported USD costs were **$0.03335 image** and **$0.0487128 video**; these are job metadata, **not** an independently reconciled provider invoice. The recorded 11 new ledger events correspond to the nine jobs, adjustment and tariff grant without duplicate job charge entries. No new paid provider requests were performed for this audit.

The native4b adapter in this environment is limited to 512–768 pixels per side, exactly four steps, and only the existing 704×704 shared Studio preset. The saved Pro plan's broader SD/HD/FHD permissions **do not override model execution**. New model-access publication intersects stored tariff IDs with model/provider-supported IDs, local 4B advertises only text-to-image, desktop/mobile selection is constrained to that effective intersection, and Config UI normalizes the native4b profile accordingly. Extending local 4B beyond the adapter's limits requires a distinct controlled RTX 4070 measurement and independent safety gates, not a Pro entitlement toggle.

The resolution-patch predecessor `8a3632e79b9aad4bfae1af2281039d06adc6f5e5` had Task Contract violations (unregistered source paths, forbidden Studio path, 1–4 line protected-file growth), despite passing targeted feature tests. The follow-up corrective slice explicitly records owner-authorized scope expansions, restores all three protected file line budgets **without increasing limits**, regenerates the architecture inventory, and must pass exact-SHA Task Contract, Linux backend tests, frontend build and real browser checks before replacement of the installed preprod images. No real user session or provider key is copied, reconstructed or exported.

**Not yet independently accepted:** signed-in desktop/mobile feature selection after deployment, F5 and authenticated private gallery, server-side prohibited-resolution billing denial on the live owner account, zero duplicate charges across idempotent retries, higher-than-704 local GPU proof, and externally approved hosted GitHub CI/security-review. Existing paid jobs must not be rerun merely to create new evidence.
