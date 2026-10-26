---
status: canonical
domain: chat
read_when: ["chat","phone-chat","chat-models-tools-history"]
source_paths: ["frontend/src/newUi.tsx","frontend/src/desktopChat/DesktopChatWorkspace.tsx","frontend/src/phone/features/chat/PhoneChatWorkspace.tsx","backend/app/api/routers/phone_chat.py","backend/app/services/phone_chat_history.py","backend/app/services/chat_billing.py"]
test_paths: ["frontend/phoneChat.test.ts","backend/test_phone_chat_history.py","backend/test_phone_chat_tools.py","backend/test_chat_billing.py"]
related_domains: ["backend-auth-bots"]
forbidden_paths: ["frontend/src/LegacyApp.tsx","backend/main.py"]
owner: chat-platform
role: chat-agent-context
scope: /chat and shared /phone/chat core
audience: coding-agents
evidence_base_sha: 4ed17f0849b291ccb493513dcf3f599312739004
evidence_package: CHAT-STRUCTURED-TOOLS-001
status_effective_when: merged-to-main
updated: 2026-09-16
---
# Context: продуктовый чат `/chat`

Назначение: bounded routing для desktop `/chat`, mobile `/phone/chat`, общей
истории, моделей, tools и billing. Детальный reference после Task Contract:
`docs/chat-system.md` и `docs/chat-assistant-contract.md`.

## Первый маршрут для локальной UI-задачи

1. `frontend/src/newUi.tsx` — только route/composition range, не full-read.
2. `frontend/src/desktopChat/DesktopChatWorkspace.tsx` — desktop owner.
3. shared chat contracts/API в phone feature только по нужному symbol.
4. backend router/service ниже, если изменение пересекает HTTP/history/billing.

## Frontend ownership

- `DesktopChatWorkspace.tsx` owns desktop scroll/layout, composer shell,
  model selector presentation and desktop interactions.
- `PhoneChatWorkspace.tsx` owns mobile composition for `/phone/chat`.
- Shared phone chat contracts/API may be reused by desktop; reuse does not make
  the entire phone platform part of a desktop UI package.
- For CSS/layout, locate the target selector/component first; do not load large
  global CSS merely because the route is chat.

## Backend ownership

The shared `qwen3.8:27b` profile uses the model-supported maximum reasoning
level `xhigh`, a120000-token context and `num_predict:-1` (no fixed generation
token cap). The integration overrides legacy short-call settings, including
prompt improvement. Local inference can wait1800 seconds. Chat transport and
history preserve complete assistant answers without8000/12000-character slices.
Other model reasoning settings are unchanged. Runtime service configuration and
the other clients must use the same context; weights and quantization are unchanged.

- `backend/app/api/routers/phone_chat.py` — trusted chat HTTP/model/tool routing.
- `backend/app/services/phone_chat_history.py` — thread/message persistence.
- `backend/app/services/chat_billing.py` — quote/settlement semantics.
- Auth/permission changes additionally load `backend-auth-bots` context.
- New chat business logic does not return to `backend/main.py`.

## Request boundaries

- `/chat` and `/phone/chat` share trusted identity/history, not every UI detail.
- Provider calls, billing, history and tool execution are separate ownership
  boundaries; a layout fix must not casually modify them.
- Stored tool state and best-effort follow-up updates can diverge; verify the
  exact flow before changing persistence semantics.

## Focused verification

For scroll/model-selector work start with:

- `frontend/phoneChat.test.ts` for shared chat UI/contracts;
- targeted frontend lint/build for changed desktop code;
- `backend/test_phone_chat_history.py` only if history is touched;
- `backend/test_phone_chat_tools.py` only if tool routing is touched;
- `backend/test_chat_billing.py` only if economics/settlement is touched.

Browser/live-provider evidence is separate from unit/contract verification.
Deployment and production operations are outside a normal chat package.

## Guardrails

- Treat `newUi.tsx` as a route/composition pointer; use bounded ranges.
- `LegacyApp.tsx` is outside `/chat` ownership.
- `backend/main.py` is a compatibility/composition hotspot, not the place for
  new chat business logic.
- A desktop layout task does not implicitly include auth, billing, history or
  provider behavior; expand scope explicitly when needed.
- Use isolated test data and fake adapters for side-effecting paths.

If deeper protocol detail is required, use the reference docs above instead of
expanding this routing card into another master specification.

## Deeper references

- [Chat system architecture](../chat-system.md) — protocol, ownership and
  cross-layer request flow.
- [Assistant contract](../chat-assistant-contract.md) — assistant/tool behavior
  and product-level invariants.
- Use these only after the routing card identifies the relevant layer.

## Change routing table

| Task | Start here | Add only when needed |
|---|---|---|
| Desktop scroll/layout | `DesktopChatWorkspace.tsx` | target CSS/selectors |
| Model selector UI | `DesktopChatWorkspace.tsx` | shared model contract/API |
| Mobile chat UI | `PhoneChatWorkspace.tsx` | phone chat tests |
| History issue | `phone_chat_history.py` | router + history tests |
| Tool routing | `phone_chat.py` | tool policy/tests |
| Billing/economics | `chat_billing.py` | billing tests/ledger evidence |

## Explicit unknowns

- A visual symptom does not prove whether ownership is desktop-only or shared.
- Live provider/model availability is runtime evidence, not source truth.
- Generated maps guide discovery but do not replace focused source/test checks.
