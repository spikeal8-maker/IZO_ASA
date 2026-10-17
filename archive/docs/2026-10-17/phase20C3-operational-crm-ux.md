# Phase 20C.3 — Operational CRM Admin UX

Turn the Users CRM into a usable operator console: dense table with trusted quick actions
in every row + a compact two-column user card with actions above the fold. Frontend-only;
no backend/DB/auth/generation changes; legacy block kept (collapsed, renamed).

## Block 1 — UX audit (honest)
- **Old legacy table/modal did better:** dense rows, all key fields at a glance, quick
  actions inline, one edit modal with fields+actions together.
- **Old did dangerously:** legacy `apiFetch` → `X-OneNode-User`/`require_admin`; direct
  balance/role overwrite with no reason/audit; hard delete.
- **New (20A–20C.2) did securely:** cookie-auth trusted-v2 only, reason + audit on every
  risky action, masked contacts, no hashes/raw profile.
- **New (20C.2) did poorly:** the card was a tall single-column "landing" dossier with a
  left section-nav; **actions lived at the bottom** → you had to scroll past every section
  to ban/adjust tokens/reset. Verdict: 20C.2 card was **not operationally usable**.
- **Kept from old UX (without legacy endpoints):** dense table, inline quick actions, a
  combined card — all now mapped to trusted-v2 + reason + audit.

## Block 2 — Dense Users table
Compact rows show Пользователь(name+code) · Источник(badges) · Контакты(masked) · Роль·Тариф
· Баланс/Списано · Генерации · Активность(last_seen·platform·ip) · Статус, plus a wrapping
**quick-actions cell** per row: Карточка · +50 · −50 · Бан/Разбан · Снять/Админ · Тариф ·
Пароль · Ред. Sticky header, search, source/status/admin filters, compact KPI strip,
diagnostics collapsed by default (auto-opens only when there is no admin session).

## Block 3 — Compact card (centered modal, ≤1200px, 86vh)
- Sticky header: name, public_user_code, badges, status/role, KPIs (balance/spent/
  generations/plan/created/last_seen).
- **Left column (~63%):** Профиль и контакты, Источники входа, Сессии + Устройства (compact
  panels), then collapsed accordions for Логи / Токены и генерации / Технические
  идентификаторы — no endless scroll.
- **Right sticky column (~37%):** Админ-действия **above the fold** — +50/−50/Токены…,
  Забанить/отключить, Снять/Сделать админом, Изменить тариф, Изменить профиль, Сбросить
  пароль, with «Каждое действие требует причину и пишется в audit log».

## Block 4 — Edit pattern (trusted, no raw save-all)
«Изменить профиль» edits only safe fields (display_name, email) via `profile-v2`. Balance →
`tokens-v2` (never a direct balance overwrite); role → `role-v2`; plan → `plan-v2`. No
audit-bypassing "save all fields" mutation.

## Block 5 — One compact confirm popover (shared)
A single `ActionConfirm` popover serves both row and card: action title + target, optional
value (token delta presets +50/−50/+1/−1, plan select, display_name/email, password with
`autoComplete="off"`), required reason, «Действие будет записано в audit log», confirm/cancel,
loading/success/error. Success refreshes the table (and the open card).

## Block 6 — Parsing
display_name fallback chain; masked email/phone; language/city/country; session
browser/os/ip; short installation/anonymous/provider ids; raw-профиль да/нет (no JSON).
Missing values render a compact «—», not large empty blocks.

## Block 7 — Density
Reduced padding, compact KPI cards, compact session/device/log panels, accordions for deep
detail, actions above the fold, diagnostics collapsed unless auth/env problem.

## Block 8 — Legacy
Kept collapsed; warning already reads «Эти действия устаревают. Используйте карточку
пользователя…». Not deleted, not visually promoted; the new CRM is now faster than it.

## Block 9 — Tests / visuals
`tsc -b` 0 · `vite build` 0 · smokes admin-analytics (dense table + row quick actions +
trusted endpoints + reason + audit note + compact card + accordions + no old nav/drawer) /
auth-v2 / auth-modal / generation-lock OK. Screenshots (route-mocked, real components) in
`frontend/visual-out/`: `crm-table.png`, `crm-confirm.png`, `crm-card.png`. Env parity:
`visual-admin-parity.mjs`.

## Block 10 — Security
Cookie auth only (`credentials:include`); **no `X-OneNode-User`** in any CRM action; every
risky action reason-gated and audited; no `password_hash`/`session_token_hash`/
`refresh_token_hash`/`code_hash`/`raw_profile_json`/`initData`/`WebAppData` in UI.

## Build / serving
Frontend label `20C.3-2026-06-27`, dist `index-DGI07G9p.js`, served on `127.0.0.1:5173`
(vite preview up, HTTP 200). Backend (`20C.2`, unchanged this phase) up on :8000.
**Public note:** the `cloudflared` tunnel was down at hand-off (https://izo.alikinas.ru →
530; cloudflared process not running). `start-public.bat` does NOT manage cloudflared — the
owner restarts the tunnel; once it points back at :5173 the public site serves this build
with no further build/restart.

## Files changed
- `frontend/src/adminAnalytics.tsx` (dense table + row quick actions + ActionConfirm +
  compact two-column UserCard + diagnostics)
- `frontend/src/index.css` (operational CRM styles)
- `frontend/smoke-admin-analytics.mjs` (operational checks)
- `frontend/visual-crm-shots.mjs` (new — route-mocked screenshots)
- `frontend/src/diag.tsx` (label 20C.3)
- `docs/phase20C3-operational-crm-ux.md`
