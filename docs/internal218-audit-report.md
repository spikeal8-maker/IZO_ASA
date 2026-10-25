# IZO_ASA #218 — integration verification checkpoint (25 October 2026)

**Release verdict: NOT_ACCEPTED.** This is a synthetic integration candidate, **not** a deployment or permission to merge into main.

## Exact ancestry and isolation

Base #217 `1030abdafc32a0f11fbc4a6593acd435eb1bbdfd`; sequential descendants #221 `f09f99b3a79dc32ca9e69380ff4013223748ed58` → #224 `77d35f4907fbb976f12bb279af1a66b832229493` → #226 `a28f14e1af1875db0918c3afb2a6dc2208c3df4c`, plus copied exact sibling blobs from #222 `9433610dae9ad8aa57cee7d00187c6fdef887a6f` and #223 `493a0647eeb083939fe1f628418b232ee8b03c93`. No overlapping file paths in sibling patch application.

Combined code commit `c5df5361278480cb0abcdff8a7cc1cada9dccba3`; subsequent commits add only Task Contract and these evidence documents. New tests must be repeated whenever production source changes.

## Executed checks

- Node 22.16 on GitHub-blob-identical `imageGenerationCommand.ts` (`7d1ab3c12ef8b9bbec0404d23a5ba7cd796cbf7e`) and `test_image_generation_idempotency.mjs` (`2d5aace73b73b7e3f5112cb54806913d17b8449d`): **11 PASS / 0 FAIL**. Covers A→B→A, F5 intent persistence, 2/5/10 repeats, loss of auth, invalid and valid synthetic refresh. Standalone TypeScript check PASS.
- Python pytest with exact GitHub blobs `video_submission.py` (`ea74c6798a6f4357c8d76c087104e72822ce4ede`) and `test_video_unknown_reconciliation_guard.py` (`9e9556570bc73236a682f86d378041317036d77e`): **10 PASS / 0 FAIL**. Original four Comfy claim-loss scenarios from #222 were not rerun in this environment.
- Two real Chromium headless runs (1440×900 and 390×844) executed the exact compiled client helper with synthetic trusted-owner resolver and explicitly mocked browser crypto/transport. 2/5/10 concurrent same-intent calls preserved one key/job in both viewports; A→B→A preserved owner identity. An isolated SQLite+separate fake child worker produced **4 jobs, 4 debits, 4 provider dispatches, 4 gallery rows** across the two independent viewport scenarios. SQLite backup/restore reproduced the counts (4/4 each) with `PRAGMA quick_check=ok`.
- **This browser harness is NOT the real IZO_ASA UI/HTTP backend or canonical refresh code.** External browser URL navigation returned `ERR_BLOCKED_BY_ADMINISTRATOR`. It cannot satisfy actual authenticated desktop/mobile E2E or actual `generation_admission`→worker→provider financial acceptance.
- #223 deletion regression on exact service: unresolved receipt blocks when job row exists; after deleting that job row, duplicate guard returns no blocker. **FAIL** for durable retention. #204 requires an independent receipt registry and controlled reconciliation lifecycle.

## Mandatory unfinished gates

Full frontend eslint/tsc/Vite, full backend suites, #222 queue/claim/lease/recovery, real FastAPI and child workers under synthetic HTTP, real browser session cookies/logout and account GET 403/404, fault injection (accepted timeout→refund→late completion), full backup+restore and load percentiles, independent finance/security reviews, hosted exact-head CI, and operator decision. GitHub Actions had 0 runs at checked candidate SHAs; historical billing blocker still requires verification. No fabricated PASS for these gates.

The connected D2-R2 device returned `link_id must identify an eligible linked account`. No read or mutation of the existing site `127.0.0.1:48314`, user SQLite, 59 accounts, restored media, quotas, old Shadows, ComfyUI, Ollama, production or external providers was attempted. No real keys or paid API calls used.

See machine-readable `docs/internal218-audit-matrix.json`. **Do not merge to main or deploy from this Draft.**

## Parallel real implementation under #204 (separate from integrated candidate)

[Draft PR #229](https://github.com/spikeal8-maker/IZO_ASA/pull/229), exact HEAD `58c8bd2c2743d88db5b6707faa22025a2fd846de` from main, adds an isolated durable SQLite provider-receipt state machine and tests. Current source/test Git blobs `86322c2b2ed261239c1f7a3b6b8756d26c2062f6` / `e4a335b30dc0d743a123baa593601667d7abdcc0` have matching local SHA.

Fresh `pytest -q backend/test_provider_reconciliation.py`: **10 PASS / 0 FAIL**. Demonstrated exactly one receipt/dispatch fence for 2/5/10 same-key callers, owner and payload separation, `ACCEPTED→OUTCOME_UNKNOWN→RECONCILIATION_PENDING→COMPLETED`, explicit operator receipt audit and persisted block despite deletion of a synthetic `jobs` row.

Standalone synthetic SQLite replay microbenchmark (250 operations each, own WAL DB):
- 1 thread: p50 1.88ms, p95 5.82ms, p99 9.25ms;
- 5 threads: p50 3.94ms, p95 28.89ms, p99 122.98ms;
- 10 threads: p50 2.24ms, p95 57.79ms, p99 108.63ms.

All three had one receipt and zero errors. These values measure only the receipt helper under local synthetic contention; **not application capacity, real provider latency or accepted production P0**. The core has no production migration, billing adapter, authenticated operator API or actual video invocation, and was intentionally left outside this #228 integration branch until dependencies and independent review are satisfied.


## 25 Oct — mobile account-switch privacy repair

During continued source inspection, unscoped legacy mobile `sessionStorage` keys for image prompt, video prompt and image→video source were found. After A→logout→B, the mobile UI could present A's saved input despite the paid command ledger being partitioned. This is a client privacy/correctness finding, **not evidence of a backend media-authorization bypass**.

[Draft PR #230](https://github.com/spikeal8-maker/IZO_ASA/pull/230) exact HEAD `7fdb7ab4c7069674183bc5c1a0a2aab195cfe7e5` isolates these drafts by server-confirmed `internal_user_id`, ignores ownerless legacy drafts and remounts phone workspaces with an owner-specific React key. `PhoneApp` hides private workspaces until auth verification, fences stale async results by request sequence, and rechecks that the owner did not change during the jobs-list fetch.

Source helper GitHub blob `25e37d2b126f62b8a659fed99906437435aabaa0`; test blob `f3866fb8611df22315752aab83bbefc26c75a68f`. In an isolated Linux Node v22.16 environment, both hashes matched byte-for-byte: **6/6 tests PASS**, standalone TypeScript check **PASS**. Scenarios: A/B/A prompts, video source handoff, legacy isolation, invalid owner, owner-scoped clearing, storage failure.

[Draft PR #226](https://github.com/spikeal8-maker/IZO_ASA/pull/226) current HEAD `45f351903ca27a00c7d265ffbb5b3be06b9201e8` adds an additional post-job-list verification so stale A jobs are not resumed after a cookie switch. Integration code commit `4890272fd47e935d3c7b7ef491dd9ff3d608cafc` includes the exact latest seven phone source/test/contract blobs. Subsequent documentation commits change only receipt files.

**Still blocked:** actual signed-in Chromium `PhoneApp` and Studio with two synthetic users, cookie refresh/logout and in-flight A↔B switch; full project TypeScript/ESLint/Vite, backend/worker/admission provider settlement, fault/rollback and independent review. The container's Chromium navigation is blocked by administrator policy; `Remote Desktop Commander` has no eligible linked D2-R2 device. No live owner data changed.

## 25 Oct — additional logout/refresh gates

- PR #226 https://github.com/spikeal8-maker/IZO_ASA/pull/226 source HEAD `2899663f9d38794d3981d91995faeb43663de1d2`: mobile code verifies account ownership again after loading the private job list. Canonical `fetchMeV2` requests `cache: 'no-store'` before and after refresh-cookie. This is source-only, not a real browser cookie PASS.
- PR #231 https://github.com/spikeal8-maker/IZO_ASA/pull/231 HEAD `a1a89123b88dc540c13548eab55c39cda6f99ece`: the Legacy settings logout distinguishes positive ACK from a lost response and reloads private React state only after confirmed logout. Unconfirmed logout displays an error. Browser acceptance NOT_TESTED.
- Latest combined code SHA before this evidence update: `e0f04d1683f4d2b431bd9c5083820e4f355e9237`. Main, #217, original PRs, D2-R2 and user data remain unchanged.
- Headless Chromium navigation is administrator-blocked in this runtime. Static about:blank content denies native sessionStorage via SecurityError; this is not a substitute for an authenticated IZO_ASA browser/HTTP E2E.

