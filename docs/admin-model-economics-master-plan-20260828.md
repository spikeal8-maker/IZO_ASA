# Admin model catalog, pricing and billing master plan

Status date: 2026-08-28. This is the executable source of truth for the model
administration, pricing and product-token program reconstructed from the owner
conversation. It supersedes treating `OPENROUTER-ECON-002` or
`MODEL-CATALOG-001` as the whole program.

## Outcome and non-negotiable rules

The finished system must make the admin catalog, user-visible availability,
quoted price, reserved charge, settled charge and provider cost describe the
same operation.

1. An unpublished model exists only in the admin catalog.
2. A published model is visible only in its enabled operations.
3. Tariff access determines whether a visible model can be selected.
4. A visible but tariff-ineligible model is disabled and names the required
   tariff.
5. A model without a trustworthy price cannot be published for paid use.
6. The user sees the maximum charge before provider work starts.
7. A successful operation never incurs an additional surprise charge.
8. A failed operation returns the complete reservation.
9. Actual provider cost calibrates future quotes, never the accepted quote.
10. Cloud products share USD/RUB, the 30% funding reserve, product-token value
    and minimum margin.
11. Local products use explicit electricity, GPU-time and capacity economics.
12. Every financial value exposes source, observation time and confidence.

Margin means `profit / revenue`. Required revenue is
`cost / (1 - margin)`. The UI must also show the equivalent markup so a 50%
margin is unambiguously a 100% markup. Product tokens are the ceiling of
required revenue divided by the configured rubles per product token.

## Baseline and rollback evidence

- Canonical source: `E:\IZO_ASA_WORKSPACE`; isolated implementation worktree:
  `E:\IZO_ASA_WORKTREES\admin-model-economics-20260828`.
- Starting Git SHA: `05105d37bdb3f8d6a69e1893d215b9a923068db7`.
- Active production SHA at start:
  `071a1c402e285d10010f281600277da1e91585ce`.
- Local rollback checkpoint:
  `C:\IZO_ASA\rollback\20260828-014459-before-admin-model-economics`.
- SQLite backup passed `PRAGMA quick_check`; unrelated chat/mobile WIP is saved
  separately as `uncommitted-user-work.patch` and remains untouched.
- AdGuard VPN, FRP, DNS and VPS routing are outside scope.

## Delivery packages

### Package A — catalog, publication and honest surfaces

- [x] Separate image publication, operation enablement and tariff access.
- [x] Reject unpublished or incompatible image models server-side.
- [x] Remove unpublished image models from user catalogs.
- [x] Show provider and provider-supplied release date without inventing one.
- [ ] Normalize common metadata for image, video, text and audio catalogs:
  provider, release date, catalog-added date, modalities, price status, price
  observation time, sample count and operational health.
- [ ] Make newly discovered provider models admin-only and unpublished.
- [x] Give video and text the same explicit global publication contract.
- [x] Give audio the same explicit global publication contract.
- [ ] Replace stale legacy `tariff_matrix` summaries with canonical access data.
- [x] Hide 3D from user navigation until a real provider contract exists.
- [x] Hide inactive music, cloning and processing controls; label future
  products without invented providers.

Acceptance:

- unpublished models are absent from every user surface and forged requests are
  rejected;
- old saved choices fall back to an available model;
- a no-price model cannot become billable;
- desktop and phone use the same server catalog.

### Package B — common quote engine and shadow economics

- [x] Create a common cloud quote record with provider USD cost, effective
  USD/RUB, funding reserve, required revenue, margin, markup, product-token
  reservation, source, confidence and observation time.
- [x] Use the maximum of official price, last actual cost, comparable-history
  rolling estimate, comparable-history p90 and provider minimum price.
- [x] Partition comparisons by model and all price-affecting inputs.
- [x] Persist an immutable quote before provider submission.
- [x] Add shadow comparison: legacy quote, new quote, actual cost and expected
  margin without changing user charges.
- [x] Backtest representative historical image/video operations and publish
  coverage, underquote and margin distributions.
- [x] Alert after repeated below-margin results or missing actual costs.

The shadow engine must not alter balances until its acceptance evidence is
approved.

### Package C — image and video settlement

Images:

- [ ] Calibrate future quotes using actual comparable image history.
- [ ] Include model, operation, billed resolution and input-image count.
- [ ] Replace generic mobile `tokenHint` with the selected server quote.
- [ ] Requote on resolution, operation or input changes.
- [ ] Disable submission while an exact quote is unavailable or stale.
- [ ] Display per-format cost, tokens, revenue, profit, margin, samples and last
  actual value in admin.

Videos:

- [x] Add one global publication switch above per-mode enablement.
- [ ] Quote exact model, mode, duration, resolution, ratio, audio and inputs.
- [ ] Clearly distinguish exact price from `from N tokens` catalog guidance.
- [ ] Exclude missing-actual-cost jobs from profitability confirmation.
- [ ] Preserve the accepted quote; actual cost changes only future quotes.
- [ ] Model local LTX separately with service state, energy, average GPU time,
  duration prices, profit and its own publication switch.

Settlement for both products reserves the displayed maximum, fully refunds a
failed operation and never charges above the accepted reservation.

### Package D — usage-based text billing

- [x] Remove configured fixed per-response cost as the primary settlement.
- [x] Estimate input history, images and a safe response ceiling before request.
- [x] Reject before provider submission when the reservation is unaffordable.
- [x] Record provider input/output usage and actual cost.
- [x] Compute the final charge with the accepted exchange/reserve/margin
  snapshot and refund the unused reservation.
- [x] Keep exact fractional accounting without allowing a zero whole-token
  balance to fund multiple paid responses.
- [x] User guidance: approximate 1,000 words and one million Russian characters,
  with an explicit usage-dependent disclaimer.
- [x] Admin detail: provider input/output price per million tokens, word/character
  guidance, average actual response cost and actual margin.

### Package E — audio products

Speech recognition:

- [ ] Global publication, model selection, tariff access and duration/file
  limits.
- [ ] Preflight quote/reservation, actual provider cost, settlement/refund,
  history and margin.

Text to speech:

- [x] Expose real local voices consistently on desktop and phone.
- [ ] Add history, download, length-aware local price and tariff limits.
- [ ] Record local runtime/economics rather than pretending it is an API cost.

Music, cloning and processing remain inactive until a real provider, pricing
contract and live test exist.

### Package F — admin layout and accessibility

- [ ] Keep collapsible modality/operation sections.
- [ ] Model row order: publication, name, provider, release date, price status,
  tariffs, compact economics, statistics and details.
- [ ] Sticky header plus sticky publication/name columns.
- [ ] Fixed tariff widths, right-aligned numeric columns and textual profit/loss
  states in addition to color.
- [ ] Expanded content must not change table width.
- [x] Narrow screens render image-model cards rather than a desktop-wide row.
- [ ] Text rows keep access in the summary and move economics/statistics into
  details.
- [ ] Verify 1920x1080, 1440x900, 1366x768, 430x932 and 390x844.

## Release sequence

1. Complete Package A without changing user money.
2. Run Package B in shadow mode and compare historical and new quotes.
3. Enable Package C only after image/video shadow acceptance.
4. Enable Package D independently with race/idempotency tests repeated five
   times.
5. Enable Package E per audio product; do not bundle future audio features.
6. Complete Package F and verify the real public desktop/mobile route.
7. Each production switch uses the installed Windows-service release runbook,
   exact SHA, backup, rollback and local/public release identity checks.

## Global acceptance

The program is complete only when:

- publication and tariff access agree across admin, server, desktop and phone;
- the button quote equals the reservation and maximum charge;
- failure returns the full reservation;
- actual costs are durable and calibrate future quotes;
- minimum margin is monitored automatically;
- text settles from real provider usage;
- speech recognition has explicit financial accounting;
- local speech is consistent on desktop and phone;
- inactive audio and 3D products are honestly hidden;
- admin numbers are sourced, dated and confidence-labelled;
- exact production desktop/mobile evidence and a tested rollback exist.

## Verification log

### 2026-08-28 — Package A text/video publication slice

- Backend compatibility and contract suite: 107 passed.
- Frontend phone contract and video request tests: 5 passed.
- TypeScript compilation, production bundle and lint: passed.
- No production service, database, VPN, FRP or DNS setting changed.

### 2026-08-28 — Package B shadow quote engine

- A common `cloud-quote-v1` snapshot now compares the provider quote, newest
  comparable actual, rolling mean, p90 and provider minimum.
- Exact image comparisons include model, operation, billed dimensions and input
  count. Exact video comparisons additionally include duration, ratio, audio
  and input count.
- Existing user charges remain authoritative; the shadow result records its
  token delta, actual margin and repeated-below-margin alert without changing a
  balance.
- Focused backend suite: 135 passed. Frontend build and lint: passed.

### 2026-08-28 — Package D usage-based chat settlement

- API chat reserves a conservative three-round ceiling at 0.001 product-token
  precision, rejects an unaffordable request before provider submission and
  settles from the provider's actual USD usage without exceeding the reserve.
- Provider failure returns the full reservation; a successful cheap response
  returns the unused fractional reservation idempotently.
- A zero whole-token balance can no longer accumulate paid fractional calls.
- The race/idempotency billing suite passed five consecutive runs; phone-chat
  contracts, history, frontend build, lint and UI tests passed.

### 2026-08-28 — production-history shadow backtest

- Read-only database: `F:\IZO_ASA_StandbyData\active\database.sqlite3`.
- Coverage: 145 of 146 operations with actual cost (99.32%).
- Images: 95 rows, 28 underquotes, 14 below required margin, average actual
  margin 50.98%, no current repeated-margin alert.
- Videos: 50 rows, 27 underquotes, 18 below required margin, average actual
  margin 41.72%, repeated-margin alert active.
- Overall average token delta versus the accepted legacy quote: +0.4; range
  -1 to +5 tokens.
- Decision: keep image/video `cloud-quote-v1` in shadow mode. Package C cannot
  be activated until the video partition/risk reserve is corrected and the
  backtest alert clears.

### 2026-08-28 — Package E publication and local speech slice

- Speech recognition and local text-to-speech have separate admin-owned global
  publication switches enforced by their server endpoints.
- The same real Windows voices, Irina and Pavel, are exposed on desktop and
  phone; WAV output can be played and downloaded.
- Local speech now records voice, character count, execution time and output
  size. Electricity/capacity cost is still pending, so the combined economics
  acceptance item remains open.
  Cloud transcription additionally records returned provider usage and actual
  USD cost as `metered_not_settled`; it is deliberately not presented as a
  completed user settlement.
- Music, voice cloning and speculative processing products remain absent until
  a real provider and verified price contract exist.
- Focused audio/OpenRouter backend suite: 99 passed. Phone audio contracts,
  frontend lint, TypeScript compilation and production bundle: passed.

### 2026-08-28 — full regression and responsive evidence

- Full backend/tools regression after the architecture extraction: 1,862
  passed, 1 skipped, 0 failed.
- All affected frontend contracts passed: image/video publication, phone shell,
  chat, image, video and audio. Frontend lint and production build passed.
- Live-data local frontend inspection at 1440x900 and 390x844 found no page
  horizontal overflow. The image catalog now renders four-field model cards on
  narrow screens (name/release, publication, operation and tariff access)
  instead of compressing the desktop economics table.
- Remaining visual acceptance: text/video model rows and all five target
  viewport sizes still require final public-release evidence.
