---
status: historical
document_role: superseded-phase-spec
phase: 19
superseded_by: docs/admin-panel-guide.md
current_context: docs/context/admin-control-center.md
updated: 2026-08-31
---

# Admin Panel — Product / UX Spec (Phase 19)

> Историческая design-spec этапа Phase 19. Она сохраняется как evidence и не
> описывает текущую навигацию, security boundary, release или активный backlog.
> Текущее общее описание: `docs/admin-panel-guide.md`; контекст для изменений:
> `docs/context/admin-control-center.md`.

Design only. No code/DB/auth changes. Targets a single product control center built on
existing endpoints + the new Phase 18 analytics, replacing the chaotic mixed admin.

---

## Block 1 — Current admin audit

**Tabs today** (`AdminView`, legacy header-auth via `apiFetch` → `X-OneNode-User`):
Дашборд, Модели, Токены, Пользователи, Очередь, Ошибки. Plus the Phase-18
`AdminAnalyticsV2` panel (cookie-auth) injected at the top of the Users area.

| tab | shows | actions |
|-----|-------|---------|
| Дашборд | provider/model/queue text + quick links | navigate |
| Модели | model config text | (mostly display) |
| Токены | rate limits, finance inputs (manual numbers), promo create, plans text | save limits/finance, create promo |
| Пользователи | **legacy table** (raw `item.id`, ФИО/contacts, geo, role/plan, balance, activity, promo, status) **+ new analytics table on top** | edit, ban toggle, Снять/Админ, Тариф (cycle), +50, −50, delete |
| Очередь | queue length + `JSON.stringify(queue)` | none |
| Ошибки | error count + raw `recentErrors` + raw admin summary JSON | none |

3–5. **Actions reality:** edit/role/plan/+50/−50/delete/create/limits/finance/promo all
go through **legacy** `require_admin` (X-OneNode-User, insecure). **Trusted admin-v2**
exists only for: block/unblock, password-reset, dashboard, users-analytics, user detail,
security-events, audit-logs.

6. **Duplication:** two user tables (analytics + legacy); two "totals" KPI blocks;
provider/queue/errors repeated across tabs.

7. **Wrong UI:** raw `item.id` (web_/telegram_/UUID) as primary label; `JSON.stringify`
dumps for queue/errors; finance numbers are free-text inputs with no "estimate" label;
Тариф button silently cycles free→mini→plus→pro; +50/−50 with no reason/confirmation.

8. **Odd column/button names:** "Ред.", "ID", "Промо", "Удалить" as a column, "Снять",
"Тариф" (ambiguous), bare "+50/−50", "Сырой admin summary".

9. **Keep:** dashboard KPI idea, model config, rate limits, promo create, plans concept,
queue/errors data, the Phase-18 analytics table + drawer data, export.

10. **Replace:** the legacy users table (header-auth) → cookie-auth CRM; raw-ID labels →
public_user_code+display_name; JSON dumps → real tables; cycle/instant token buttons →
confirmed reason-gated actions through trusted admin-v2.

---

## Block 2 — Target structure (8 tabs)

`Обзор · Пользователи · Генерации · Модели · Токены и тарифы · Промокоды · Логи и ошибки · Система`

Per tab: purpose / top KPIs / tables / filters / actions / endpoints (existing + missing).
(Detailed below; promocodes can be a Токены subtab but is listed top-level for clarity.)

---

## Block 3 — Пользователи (CRM) — priority

**KPI strip** (from `GET /api/admin/dashboard-v2`): всего, новые сегодня, новые 7д,
активные сегодня, активные сессии, Web, Telegram, MAX, ошибки входа 24ч.

**Filters** (extend `GET /api/admin/users-analytics-v2`): search (public_user_code / name
/ email / username — exists), source provider (exists), status active/banned/admin
(status exists; admin = role filter — **missing**), activity today/7d/30d (**missing**),
sort by last activity / generations / tokens / created (**missing** — needs `sort`/`order`).

**Table columns:** Пользователь (display_name + public_user_code) · Источник (Web/TG/MAX
badges) · Контакты (email/username/phone) · Активность (last_seen, last_platform,
last_ip) · Генерации (count) · Токены (balance/spent) · Роль · Статус · Действия (open
drawer). **Never** show internal_user_id / legacy id / session id / raw provider_user_id
as primary text — only inside the expanded drawer.

Endpoints: list = `users-analytics-v2` (exists, add sort + admin-status filter). Row →
drawer = `users/{internal_user_id}/analytics-v2` (exists).

---

## Block 4 — User drawer / card

Open from a row (right-side drawer). Source: `GET /api/admin/users/{iuid}/analytics-v2`
(exists, returns summary/identities/sessions/devices/recent_events/security/token_summary/
admin_actions).

Sections: 1) Профиль (display_name, public_user_code, email, username, phone, provider
badges, role, status, created_at, last_seen_at) · 2) Источники/Identities · 3) Сессии ·
4) Устройства · 5) Генерации · 6) Токены (balance/spent/ledger) · 7) Логи и ошибки ·
8) Админ-действия · plus a collapsed "Технические данные" (internal_user_id, legacy id,
session ids).

**Admin actions** (each: confirm + required reason + writes audit_logs + shows result):
изменить имя, изменить роль / сделать-снять админа, изменить тариф, начислить токены,
списать токены, сбросить пароль, забанить, разбанить, отключить аккаунт, тех. данные.

Endpoint mapping:
- ban/unban → `block-v2` / `unblock-v2` (exist).
- reset password → `password-reset-v2` (exists).
- **MISSING (new trusted, reason+audit):** `PATCH /api/admin/users/{iuid}/profile-v2`
  (name/email/phone/display_name), `POST .../role-v2`, `POST .../plan-v2`,
  `POST .../tokens-v2` (delta ±, reason → token_ledger + users.token_balance + audit),
  `POST .../disable-v2` (+ enable, if distinct from ban).

Never show in UI: session/refresh/code/password hashes, raw tokens/cookies,
initData/WebAppData, full raw_profile_json.

---

## Block 5 — Обзор

KPI: пользователей всего, активные сегодня, генераций сегодня, ошибок 24ч, токенов
списано, выручка*, себестоимость*, прибыль*, активные сессии, ComfyUI status, очередь.
Blocks: состояние генератора · последние события · последние ошибки · быстрые действия.
*Financial figures are estimates → UI must label **«оценка / тестовые данные / реальные
платежи не подключены»**. Endpoints: `dashboard-v2` (exists) + `GET /api/admin/system-v2`
(**missing**, for ComfyUI/queue/build) + `health`/`version` (exist).

### Реализованный компактный дашборд — 2026-08-21

- первая строка содержит семь оперативных показателей без отдельной служебной
  панели и без повторения тех же чисел карточками ниже;
- вторая строка является единой навигацией по разделам админки;
- обзор использует один график с сериями «Всего», «Базовая модель», «Платные
  изображения» и «Видео» и периодами от 1 часа до 90 дней;
- базовая модель определяется сервером по `provider=comfyui`, видео — по
  каноническому набору video-режимов, остальные image-режимы относятся к
  платным изображениям;
- мобильный интерфейс не расширяет страницу: показатели, вкладки, периоды и
  сам график прокручиваются внутри своих областей.

---

## Block 6 — Генерации

Subviews: Очередь · Running · Done · Error · История. Columns: пользователь
(display_name+code) · модель · размер · токены · время генерации · статус · ошибка ·
действия (отменить / открыть пользователя / открыть изображение). **Очередь becomes a
subsection here** (remove the separate top-level Очередь tab). Endpoints: `GET /api/admin/jobs`
exists (legacy/header) → **add `GET /api/admin/generations-v2`** (trusted, joined to
public_user_code, with status filter + pagination); cancel = existing `/api/jobs/{id}/cancel`
(owner-scoped) → **need admin cancel** `POST /api/admin/jobs/{id}/cancel-v2`.

---

## Block 7 — Модели

Sections: пользовательские режимы качества · локальные ComfyUI модели · OpenRouter/API ·
fallback routes · файлы ComfyUI · стоимость/списание токенов. Show: user-facing name,
technical model name, provider, workflow, token cost, status (active/hidden/fallback),
quality, speed, availability. Endpoints: `GET /api/models`, `GET /api/flux-klein/*`
(exist) + `GET /api/admin/models-v2` (**missing**, for cost/status/fallback config).

---

## Block 8 — Токены и тарифы

Sections: правила списания (per-mode token cost, read-only from `estimate_token_cost`
logic) · тарифы (free/mini/plus/pro: what's included) · балансы (aggregate) · финансы
(estimates, clearly labeled) · ручные корректировки (link to user drawer tokens action).
Endpoints: `dashboard-v2` (tokens_spent_total), `admin/settings` (finance, exists) +
**`GET /api/admin/token-rules-v2`** (missing) to surface per-mode costs.

---

## Block 9 — Промокоды

Fields: код, тип, токены/скидка/тариф, лимит использований, использовано, дата начала,
дата окончания, статус, кто создал. Endpoints: `GET/POST /api/admin/promos` (exist,
header-auth) → **migrate to `promos-v2`** (trusted) and add start/end/type/created_by
fields (current table has code/tokens/activation_limit/activation_count/enabled only →
**additive columns** in a later phase).

---

## Block 10 — Логи и ошибки

Sections: ошибки приложения · ошибки входа · ошибки генерации · security_events ·
audit_logs · system/runtime. Fields: дата, тип, пользователь+public_user_code,
provider/platform, IP, endpoint, результат, причина, admin actor. Endpoints:
`security-events-v2`, `audit-logs-v2` (exist) + **`GET /api/admin/login-attempts-v2`**
and **`GET /api/admin/event-logs-v2`** (missing) for login/generation errors; app/runtime
errors from `admin/summary.recentErrors` (exists, legacy).

---

## Block 11 — Система

Show: backend build (`/api/version`), frontend build (`APP_BUILD_LABEL` / diag),
dist vs dev mode, DB status (`/api/health`), ComfyUI status, tunnel mode, public URL,
warnings, diagnostics (reuse `?diag=1` panel data). Endpoint: **`GET /api/admin/system-v2`**
(missing) consolidating non-sensitive build/runtime info; никаких secrets.

---

## Block 12 — Data / endpoints map

| UI block | needed data | existing endpoint | missing endpoint | priority |
|----------|-------------|-------------------|------------------|----------|
| Users CRM list | per-user analytics | `users-analytics-v2` | + sort/admin-filter params | P0 |
| User drawer | full detail | `users/{iuid}/analytics-v2` | — | P0 |
| Ban/Unban | lifecycle | `block-v2`/`unblock-v2` | — | P0 |
| Reset password | password | `password-reset-v2` | — | P0 |
| Edit profile | name/email/phone | — | `PATCH .../profile-v2` | P1 |
| Change role | role | — | `POST .../role-v2` | P1 |
| Change plan | plan | — | `POST .../plan-v2` | P1 |
| Adjust tokens | ±delta + ledger | — | `POST .../tokens-v2` | P1 |
| Dashboard/Overview | KPIs | `dashboard-v2` | `system-v2` | P1 |
| Logs/errors | events | `security-events-v2`,`audit-logs-v2` | `login-attempts-v2`,`event-logs-v2` | P2 |
| Generations | jobs | `admin/jobs`(legacy) | `generations-v2`,`jobs/{id}/cancel-v2` | P2 |
| Models | model cfg | `/models`,`/flux-klein/*` | `models-v2` | P3 |
| Promocodes | promos | `promos`(legacy) | `promos-v2` (+ schema cols) | P3 |
| System | build/runtime | `health`,`version` | `system-v2` | P2 |

All new endpoints: `require_trusted_admin`, reason+audit on mutations, no hashes/secrets.

---

## Block 13 — Implementation phases

- **20A — Users CRM table.** Files: `App.tsx` (replace legacy users-tab table with the
  cookie-auth CRM; keep legacy code path but remove from primary UI), `adminAnalytics.tsx`
  (table + filters), `index.css`. Endpoints: `users-analytics-v2` (+ add sort/admin
  filter). Tests: backend list filter/sort tests; frontend smoke (no raw ids, badges,
  public_user_code, single table). Live: admin loads, list renders, no-session
  generate/gallery still 401.
- **20B — User drawer.** Files: new `adminUserDrawer.tsx`, mount in `adminAnalytics`.
  Endpoint: `users/{iuid}/analytics-v2`. Tests: smoke drawer opens, sections render, no
  hashes. Live: open a user.
- **20C — Admin actions in drawer.** Files: backend `main.py` (+ `profile-v2`/`role-v2`/
  `plan-v2`/`tokens-v2`), frontend drawer actions. Move role/plan/tokens off legacy.
  Tests: backend reason-required + audit + token-ledger + no-hash; frontend confirm flow.
  Live: perform each action on a disposable account.
- **21 — Overview** (`dashboard-v2` + `system-v2`; estimate labels).
- **22 — Logs/errors** (`security-events-v2`/`audit-logs-v2` + `login-attempts-v2`/`event-logs-v2`).
- **23 — Generations/queue** (`generations-v2`, admin cancel; merge Очередь into Генерации).
- **24 — Models/tokens/promocodes/system cleanup** (`models-v2`, `token-rules-v2`,
  `promos-v2`, `system-v2`; retire legacy header-auth admin endpoints from UI).

Each phase: small, additive, tested, live-verified; never touch users.id/auth/generation.

---

## Block 14 — Acceptance criteria

- single users table (no duplicate analytics+legacy); no raw internal_user_id/legacy id
  as primary text; public_user_code visible; Web/TG/MAX badges visible; user drawer opens;
  all old admin actions preserved (role/plan/tokens/ban/unban/reset); risky actions
  require reason + confirm; audit_logs written; no token/password/session hashes in UI;
  admin actions use trusted cookie auth (not X-OneNode-User); frontend build green;
  backend tests green; live no-session `/api/generate` & `/api/gallery` still 401.

---

## Notes
- The biggest correctness gain: move admin **mutations** from legacy `require_admin`
  (X-OneNode-User, insecure) to `require_trusted_admin` (cookie session) — closes a real
  privilege gap while cleaning the UI.
- Keep legacy admin endpoints in code (do not delete) until 24, but remove from the UI as
  each trusted replacement lands.
