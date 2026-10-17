# Phase 20A — Users CRM Table (primary Users tab)

Frontend-only. No backend/DB/auth/generation changes. Replaces the duplicate/broken
Users tab with one clean cookie-auth CRM; legacy actions preserved but collapsed.

## Block 1 — Before
- `AdminAnalyticsV2` was mounted globally at the top of `admin-page` (showed on every
  admin tab).
- Users tab also rendered the **legacy** users table (raw `item.id`, geo, role/plan,
  +50/−50/Тариф/ban/delete) via legacy header auth (`apiFetch` → `X-OneNode-User`,
  `require_admin`). → two user tables, duplicated KPIs, raw IDs as labels.

## Block 2-6 — Changes
- Removed the global mount. `AdminAnalyticsV2` is now the **primary content of the Users
  tab only** (mounted exactly once).
- CRM (`adminAnalytics.tsx`) reworked: title «Пользователи» + subtitle; KPI strip from
  `dashboard-v2` (Всего/Сегодня/7д/Активные сессии/Генерации/Потрачено токенов/Web/TG/MAX/
  Ошибки входа 24ч); filters (search, source all/web/telegram/max, status all/active/
  banned/admin); clean columns **Пользователь (display_name + public_user_code) · Источник
  (Web/TG/MAX badges) · Контакты · Активность (last_seen·platform·ip) · Генерации · Токены
  (balance/spent) · Роль · Статус · Действия**.
- Actions: «Карточка» opens a lightweight preview shell; «Действия» is **disabled**
  (title «Перенос действий в Phase 20C»).
- Raw `internal_user_id` / legacy id never a primary label (only a short id inside the
  preview's collapsed «Техническая информация»).
- Data via cookie-auth `users-analytics-v2` + `dashboard-v2`; never `X-OneNode-User`,
  never legacy `require_admin`. `provider`/`status` filters use server params; `admin`
  status filtered client-side (server admin filter is a P1 follow-up).

## Block 3 — Legacy preservation
The old table is kept but **collapsed by default** behind a toggle «Открыть старую
таблицу действий», inside a dashed «Старые действия — временно» block with the warning
«Будет перенесено на trusted admin-v2 в Phase 20C.» No new legacy mutations added; no
increased reliance on X-OneNode-User.

## Block 4 — Card preview (shell only)
«Карточка» → right drawer showing display_name, public_user_code, provider badges,
email/username/phone, last_seen+platform, token_balance, role, status, and a collapsed
short technical id. Full drawer sections = Phase 20B.

## Deferred (by design)
- Full user drawer (sessions/devices/events) → 20B.
- Migrating role/plan/token/ban/reset actions to trusted admin-v2 → 20C.
- Server-side sort + admin-status filter → P1.

## Block 6 — Security
CRM uses cookie-auth admin-v2 only; no `X-OneNode-User`, no legacy `require_admin`;
no session/refresh/password/code hashes, no raw tokens/cookies/initData/WebAppData in the
UI (smoke-enforced). Legacy section calls old endpoints only as clearly-labeled temporary
behavior.

## Block 7-8 — Tests / live
- `npx tsc -b` → 0 · `npx vite build` → 0 · smokes auth-v2 / auth-modal / generation-lock /
  admin-analytics → OK.
- Live: frontend dist `index-BM7nJN0f.js` (label 20A); `/api/version` → 200;
  no-session `/api/generate`, `/api/gallery`, `/api/admin/users-analytics-v2` → 401;
  page renders (Playwright: #root 11241 chars, no page errors). Backend build stays
  `18` (no backend change this phase → no restart).

## Files changed
- `frontend/src/adminAnalytics.tsx` (CRM rework + preview)
- `frontend/src/App.tsx` (remove global mount; Users tab = CRM primary + collapsed legacy)
- `frontend/src/index.css` (CRM/preview/legacy-toggle styles, 9-col row)
- `frontend/smoke-admin-analytics.mjs` (CRM smoke)
- `frontend/src/diag.tsx` (build label 20A)
- `docs/phase20A-users-crm-table.md`
