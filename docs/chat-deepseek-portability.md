# CHAT-DEEPSEEK-001 portability boundary

## Purpose

CHAT-DEEPSEEK-001 is the first portable text-chat vertical. It adds DeepSeek without making DeepSeek, IZO pages, OpenRouter, billing, or the current phone-chat router the architectural center of Chat Core.

The transfer target is `spikeal8-maker/asa-lab`.

## Backend boundary

Portable and reusable:

- `backend/app/chat_core/contracts.py` — provider-neutral model, request, event, error, and provider protocols.
- `backend/app/chat_core/providers/deepseek.py` — DeepSeek protocol adapter. It owns DeepSeek URL, model IDs, SSE parsing, provider error normalization, and DeepSeek function-call parsing.
- `backend/app/chat_core/user_secrets.py` — per-user provider-secret naming over an injected encrypted secret store.

IZO shell adapter:

- `backend/app/api/routers/chat_portable.py` — trusted-user HTTP boundary, IZO DPAPI adapter/factory, optional IZO chat-history persistence, and normalized NDJSON streaming.
- `backend/app/api/routers/phone_chat.py` composes the portable router alongside the existing chat routes without changing the protected backend composition root.
- The existing IZO image queue remains outside Chat Core. The portable stream emits a `generate_image` tool request; the frontend IZO adapter executes it.

The portable backend modules do not import OpenRouter, IZO pages, billing, SQLite, phone history, or image generation.

## Frontend boundary

Portable and reusable:

- `frontend/src/chatCore/types.ts`
- `frontend/src/chatCore/runtime.ts`
- `frontend/src/chatCore/httpTransport.ts`
- `frontend/src/chatCore/MessageRenderer.tsx`
- `frontend/src/chatCore/deepSeekApi.ts`
- `frontend/src/chatCore/DeepSeekKeyPanel.tsx`
- `frontend/src/chatCore/chatCore.css`

IZO shell adapter:

- `frontend/src/desktopChat/DesktopChatWorkspace.tsx` maps the current IZO thread/message types to the portable runtime and maps the portable `generate_image` event to the existing image job API.

The portable frontend modules do not import `DesktopChatWorkspace`, `newUi`, phone-chat modules, IZO navigation, gallery, billing, or image-generation modules.

## Streaming contract

`POST /api/chat/stream` returns newline-delimited JSON events:

- `state` — request entered streaming state.
- `delta` — append text to the current assistant message.
- `tool` — a provider requested a portable tool.
- `done` — provider stream completed; the shell may include a persisted message ID.
- `error` — sanitized provider/runtime error.

Provider-native wire formats stay behind provider adapters. DeepSeek SSE must never leak into frontend runtime code.

## Secret contract

The browser never persists a DeepSeek key. The key exists only in the password field while editing and is sent to the authenticated backend over the existing same-origin session.

The backend derives a deterministic, non-identifying secret name from trusted user identity plus provider ID and delegates encryption/storage to the injected CurrentUser DPAPI store outside the repository. API responses expose only configuration state, never the key.

No DeepSeek key is stored in SQLite, Git, localStorage, sessionStorage, logs, telemetry, or history.

## Image tool boundary

Chat Core understands only the portable tool shape:

`generate_image(prompt, aspect_ratio)`

The provider may request the tool. The runtime exposes the tool event. IZO converts that event into its existing image-generation job and feeds requested/running/done/error state back into the current message UI.

When moved to ASA Lab, only the image-tool executor is replaced; provider/runtime/renderer code remains reusable.

## Transfer checklist for asa-lab

1. Copy the portable backend `chat_core` modules.
2. Provide ASA Lab trusted-user auth and an implementation of the `SecretStore` protocol.
3. Mount the portable chat HTTP adapter or implement the same normalized stream contract.
4. Copy `frontend/src/chatCore`.
5. Provide an ASA Lab shell that maps its own conversations to `PortableChatRequest`.
6. Implement an ASA Lab `generate_image` executor, or omit that executor while keeping the tool contract.
7. Do not copy IZO phone history, IZO billing, OpenRouter, desktop shell, or IZO image-job code.

## Explicit non-goals of this package

OpenRouter, Pulse AI, voice, RAG, web search, a large admin panel, legacy-page migration, billing redesign, DB migration, Docker changes, deployment, and a monolithic all-provider Chat Core.
