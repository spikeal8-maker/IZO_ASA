---
status: ready-for-review
package: CHAT-STRUCTURED-TOOLS-001
owner: codex
updated: 2026-09-04
---

# Task Contract: CHAT-STRUCTURED-TOOLS-001

```yaml
id: CHAT-STRUCTURED-TOOLS-001
goal: Replace the desktop chat hidden tool-forcing text prefix with one validated structured request field for the two currently supported tools.
userOutcome: A user can choose automatic mode, web search, or image generation without a hidden instruction being inserted into the visible or persisted message.
beforeScenario: Select web search or image generation in `/chat`, submit a message, and observe that the frontend prepends an internal Russian instruction to the content sent to the backend and saved in history.
afterScenario: Select web search or image generation in `/chat`; the original message is sent and persisted unchanged, while the backend enforces the selected supported tool through a separate `toolChoice` field. Automatic mode retains current model-driven behavior.
nonGoals:
  - Add video, speech, music, sound-effect, document, or 3D tools.
  - Change providers, prompts, model publication, tariffs, billing, auth, database schema, or production runtime.
  - Redesign the chat, model picker, media studios, admin UI, or mobile surface.
  - Merge, deploy, restart services, or call live providers.
domain: desktop chat frontend and shared chat request orchestration
riskClass: high-assurance
declaredFiles:
  - frontend/src/desktopChat/DesktopChatWorkspace.tsx
  - frontend/src/phone/features/chat/api.ts
  - frontend/e2e-desktop-chat.mjs
  - backend/app/api/routers/phone_chat.py
  - backend/app/services/chat_tool_policy.py
  - backend/app/services/chat_request_lifecycle.py
  - backend/SYMBOL_MAP.md
  - docs/generated/architecture-inventory.json
  - docs/generated/architecture-inventory.md
  - docs/admin-mutation-audit.md
  - backend/test_phone_chat_tools.py
  - docs/context/chat.md
  - docs/chat-system.md
  - docs/chat-assistant-contract.md
  - docs/agent-tasks/CHAT-STRUCTURED-TOOLS-001.md
allowedPatterns:
  - validated `auto`, `web_search`, and `generate_image` request choice
  - backend enforcement of an explicitly selected existing tool
  - regression evidence that user content and persisted history remain unchanged
  - documentation updates limited to this externally observable contract
  - correction of stale idempotency text where the new fingerprint field is documented
acceptance:
  - Desktop sends the exact trimmed user text without a hidden forcing prefix.
  - `toolChoice=web_search` executes web search even when the message contains no automatic-search trigger.
  - `toolChoice=generate_image` produces a validated image intent even when the model does not independently call the tool.
  - `toolChoice=auto` preserves existing automatic tool behavior.
  - Existing auto requests retain their pre-field fingerprint so completed replay and stale refund recovery survive deployment.
  - Forced image selection lets the model derive prompt and ratio from bounded history and attachments before the deterministic fallback runs.
  - The image fallback preserves prior turns and an explicitly requested supported aspect ratio.
  - Forced web search lets the model derive a self-contained query from bounded history and attachments; vague or missing queries fall back to bounded conversation context.
  - A provider-returned tool call that differs from an explicit `toolChoice` is rejected without executing or exposing the unselected action.
  - Every paid OpenRouter main round and provider-backed tool round contributes to final settlement cost.
  - Unsupported tool choices fail validation before provider or billing work.
  - Existing request idempotency and history ownership remain green.
  - Reusing one `requestId` with a different `toolChoice` is rejected before a second provider call or charge.
  - Desktop E2E proves the structured field and unchanged message content.
requiredEvidence:
  - focused backend tool tests using fake providers and temporary data
  - desktop chat fake-API E2E
  - frontend lint and build
  - Quick verification or an explicit isolated-worktree boundary
targetedTests:
  - backend/test_phone_chat_tools.py
  - backend/test_phone_chat_idempotency.py
  - repeat the focused idempotency suite five times
  - frontend/e2e-desktop-chat.mjs
  - frontend lint
  - frontend build
forbiddenOperations:
  - live provider calls or paid generation
  - production database, media, secrets, payment, runtime, or network access
  - deployment, service restart, release promotion, merge, or direct edits in main
rollbackBoundary: Revert the single package commit; no schema, provider, production data, or runtime state is changed.
```

## Overlap check

- Canonical `main` was clean at `4ed17f0849b291ccb493513dcf3f599312739004` and matched `origin/main` when the package started.
- `USER-MEDIA-STUDIO-FOUNDATION-001` owns audio/video presentation files and does not overlap the declared chat request files.
- `codex/chat-contrast-20260904` changes chat presentation; this package does not claim `desktopChat.css`.
- No Full verification, publisher, promotion, backend restart, pytest, or Playwright process was active. Existing Vite preview processes belong to separate UI previews and are not reused by this package.
- Discovery added `backend/app/services/chat_request_lifecycle.py`: `toolChoice` changes provider/tool work and therefore must participate in the durable request fingerprint. This is required to preserve collision safety, does not change the lifecycle schema, and does not overlap the active media presentation work.
- The same bounded documentation section still described pre-`CHAT-IDEMPOTENCY-001` replay behavior. Because it directly contradicts the fingerprint being extended here, this package corrects that stale paragraph without changing any other backlog item.
- Quick verification reported the deterministic `backend/SYMBOL_MAP.md` stale after the request schema/helper change. The generated map is added to scope and regenerated with the repository script; no handwritten map content or unrelated backend ownership is introduced.
- After the backend map was refreshed, Quick verification identified its dependent architecture inventory as stale. Both deterministic inventory outputs are added to scope and regenerated with the repository tool; this is the same structural evidence chain, not a new product domain.
- CI proved that `docs/admin-mutation-audit.md` pins the complete `backend/SYMBOL_MAP.md` fingerprint. The route audit itself is unchanged, but its exact evidence hash must follow the generated map. The audit document is added only for that mechanical fingerprint refresh; admin behavior and findings remain out of scope.
- Automated review of rebased commit `034b0b8` found that always hashing `toolChoice=auto` broke legacy request-ledger replay/recovery and that eager forced-image execution lost conversational/image context and non-square ratios. All three findings remain within the declared lifecycle/tool contract and are repaired with compatibility and provider/fallback regression tests before merge.
- Automated review of follow-up commit `6341b24` found that the paid OpenRouter response immediately before forced-image fallback was overwritten and omitted from settlement cost. The obsolete CI run was cancelled, and all continued OpenRouter main rounds are now accumulated alongside provider-backed tool payloads.
- Automated review of follow-up commit `cbdd9f7` found that eager forced web search discarded earlier conversation/image context and that broad Russian `альбом*` matching misclassified «квадратная обложка альбома» as landscape. Both findings stay inside the declared structured-tool contract: forced search is now provider-first with a bounded contextual fallback, and landscape wording is matched only as an explicit orientation/format instruction. Superseded CI run `33904271047` was cancelled; no passing result is claimed for it.
- Automated review of commit `6b54588` found that a provider could hallucinate an unadvertised tool name and both loops would still execute it despite explicit `toolChoice`. CI run `33905757027` passed for that SHA, but the review finding makes it unmergeable; both provider loops now reject mismatched calls before any tool side effect.
- Automated review of commit `0084372` found that the generic noun «портрет» still overrode an explicit square request. Superseded CI run `33907146599` was cancelled; square wording now wins, and portrait/landscape nouns affect ratio only as explicit orientation/format phrases.
- Automated review of commit `d16afde` found that a rejected format in «Не квадрат, сделай горизонтально» could still win through fixed keyword priority. Superseded CI run `33908010261` was cancelled; the parser now ignores negated mentions, selects the last affirmative format in the latest relevant user turn, and does not resurrect a format rejected by a newer turn.
- Automated review of commit `e6019e2` found that postposed rejection such as «16:9 не надо» was not covered by prefix-only negation. The parser now recognizes bounded rejection phrases after a format while preserving valid composition instructions such as «квадрат без рамки».
- Before the next push, the same correction was hardened so unrelated composition wording before a format (for example «без рамки горизонтальное изображение») is not mistaken for format negation; punctuation and common modifiers around a rejection are covered by regression tests.
- Automated review of commit `3d135e0` found that two affirmative ratios can describe the output canvas and an object inside it, so position alone is unsafe. The backend now overrides provider ratio only when the conversation yields one unambiguous affirmative value; competing values are left to the context-aware provider.
- Automated review of commit `0c73b2c` found that the new policy enlarged the already oversized router and that rejected-only square wording still became square in the synthetic fallback. The forced-tool policy/protocol is now isolated in `backend/app/services/chat_tool_policy.py`; fallback ratio selection excludes explicitly rejected supported values.

## Completion evidence

- `python -m pytest backend/test_phone_chat_tools.py backend/test_phone_chat_idempotency.py -q` — 53 passed after the final review repair. Tests cover legacy-compatible auto hashing, validated explicit choices, provider-first forced search/image arguments from history/attachment, rejection of mismatched provider tool calls, vague search fallback, Russian/English ratio corrections, ambiguity deferral, rejected-only non-square fallback, complete multi-round OpenRouter cost capture, tool-message serialization, unchanged user content, replay, refund and collision behavior.
- Final `backend/test_phone_chat_idempotency.py` — repeated five times as required; every run passed 11/11. Reusing one `requestId` with another explicit `toolChoice` is rejected before a second provider call or charge.
- `npm run lint` — passed.
- `FRONTEND_BUILD_LABEL=chat-structured-tools-test npm run build` — passed; 1,922 modules transformed.
- `E2E_BASE_URL=http://127.0.0.1:4182 npm run e2e:desktop-chat` — passed. The fake API captured `toolChoice=web_search` and the exact unmodified user message while the existing desktop/mobile-width chat scenarios stayed green.
- Backend symbol map and architecture inventory were regenerated by repository scripts; their checks passed.
- `tools/verify.ps1 -Mode Quick` passed backend preflight, Python compilation, backend map, architecture inventory, frontend map and runtime listener contract. Its final `caddy_edge_live` step stopped because an isolated feature worktree has no active frontend release manifest when `ReleasePath` is omitted. No deployment, restart, promotion or runtime mutation was attempted.
- Scoped secret scan found zero candidate secrets; `git diff --check` passed with line-ending conversion notices only.
- `npm ci` reported four pre-existing high-severity dependency advisories. No broad dependency mutation or automatic audit fix was included in this chat contract package.
- First CI run `33896814979` reached 1,908 passed tests and reported three failures: the package-owned symbol-map audit fingerprint and one-line context budget are repaired here; the admin analytics fixture failure reproduces unchanged on clean canonical `main` because its fixed 2026-08-20 event is outside the moving 14-day window on 2026-09-04.
- The independent date-sensitive baseline repair passed CI and automated review in PR #90 and was merged to `main` as `fb6ff57`. Rebased chat commit `034b0b8` then passed CI run `33899715470` in 11m30s; its automated review findings above were accepted instead of merging that revision.
- After the final review repair, the tool/context/audit regression selection passed 59/59 and both generated-map checks passed. A new exact-SHA CI and automated review are still required after the amended commit is pushed.
- CI run `33903137323` for `6341b24` was cancelled once its review produced a blocking financial finding; a passing result from that superseded SHA is deliberately not claimed.
- Final local evidence: 53/53 combined chat tests, 5 sequential runs of the 11-test idempotency suite, 59/59 tool/context/audit checks, generated-map checks, frontend lint and production build all passed. Quick again reached only the documented isolated-worktree release-manifest boundary after all applicable steps passed.
