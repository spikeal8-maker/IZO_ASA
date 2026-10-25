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
