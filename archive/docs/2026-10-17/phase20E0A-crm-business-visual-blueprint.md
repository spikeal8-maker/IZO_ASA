# Phase 20E.0A — CRM Business Modules Visual Blueprint

Status: blueprint only. No DB migration, no endpoint implementation, no product UI code.

Verdict target: VISUAL BLUEPRINT READY.

## Principles

- Keep the existing Users CRM density and dark operator style.
- Do not redesign the table/card shell again; extend the current table, modal card, settings panel, and confirm modal patterns.
- Business data is shown only when real backend data exists. Missing modules stay clearly deferred.
- Keep row actions capped at four visible controls: `Карточка`, `+50`, `-50`, `Действия`.
- No fake payments, invoices, bonuses, promos, referrals, risk score, gallery thumbnails, prompts, or MAC.
- Raw hashes, cookies, tokens, initData/WebAppData, and raw profile/settings JSON never appear.

## 1. Users CRM Table

The table remains the main first screen. Business modules are compressed into the existing column language, not added as extra button-heavy columns.

Columns:

- `Клиент`: avatar/initials, activity ring, display name, public code, compact status/role/plan chips.
- `Активность`: online/today/week/month/cold, last seen, session/device hint.
- `Источник`: Web/TG/MAX badge plus first source if known.
- `Контакт`: masked email/phone/username.
- `Сегмент`: role, status, plan, lifecycle flags.
- `Финансы`: token balance, spent, invoice state, payment state.
- `Генерации`: total, last generation, gallery count.
- `Устройство`: IP, browser/app, OS, device type, MAC status only as unavailable unless a real agent exists.
- `Маркетинг`: UTM/source, promo/referral badges.
- `Риск`: risk label/count indicators.
- `Действия`: four visible controls only.

Visual rules:

- Financial state appears as text plus small chips, not many buttons.
- Promo/referral/marketing are badges in the data columns.
- Overdue invoice and failed payment use warning color; paid uses green; draft/unissued stays muted.
- Action dropdown groups all secondary actions.
- Table default state must show useful rows immediately; settings/diagnostics remain collapsed.

## 2. Client Card — Overview

The current client card remains a compact command center:

- Sticky header with avatar/ring, display name, public code, status, role, plan, balance, spent, generations, gallery count, last seen, created date, risk.
- Main left column has compact panels:
  - `Профиль и контакты`
  - `Источники входа`
  - `Контент`
  - `Финансы и токены`
  - `Устройства и сессии`
  - `Безопасность`
- Right sticky action panel remains grouped:
  - `Токены`
  - `Биллинг`
  - `Маркетинг`
  - `Доступ`
  - `Аккаунт`

First-screen priority:

1. Who is the client?
2. Can they use the service now?
3. Money/tokens state.
4. Recent content activity.
5. Security risk.
6. Only then business tabs/details.

Overview must not show every invoice/payment row. It shows compact summaries and latest 2-3 facts.

## 3. Client Card — Finance Tab

Purpose: financial operator work without leaving the card.

Layout:

- Top mini-summary: balance, spent, total added, unpaid invoices, paid amount, refunds.
- Three dense lists in one scroll area:
  - `Счета`: id, created_at, due_at, amount, currency, plan/package, status.
  - `Платежи`: id, provider/manual mark, amount, currency, status, received_at.
  - `Возвраты`: id, amount, status, reason, created_at.
- `Token ledger`: delta, reason, source, linked generation/invoice/admin action, created_at.

Buttons:

- Primary row/section actions live in a compact toolbar: `Выставить счёт`, `Отметить оплату`, `Возврат`, `Начислить токены`, `Экспорт`.
- Dangerous or financial-mutating actions always open confirm modal.
- Export is disabled if role lacks permission.

Empty states:

- `Нет счетов`, `Нет платежей`, `Нет возвратов` as section-level muted rows.
- No placeholder fake totals.

## 4. Promo / Bonus / Referral Tab

Layout:

- Summary strip:
  - active promo if any;
  - used promos count;
  - bonus total;
  - referral children;
  - referral rewards.
- `Активный промокод`: code, value, expires_at, status.
- `Использованные промокоды`: code, reward, source, created_at.
- `Бонусы`: manual, compensation, admin actor short, reason, amount, created_at.
- `Рефералы`: parent, children list, reward amount, status, created_at.

Buttons:

- `Применить промокод`
- `Начислить бонус`
- `Отменить бонус` only if backend state makes it safe
- `Реферальная корректировка`

Rules:

- Promo and bonus mutation must require reason.
- Bonus cancellation must show previous ledger link and audit warning.
- If no schema exists, this tab shows deferred states only.

## 5. Marketing Tab

Layout:

- Attribution summary:
  - first source;
  - last source;
  - UTM source/medium/campaign/content;
  - referrer;
  - first landing page.
- Conversion panel:
  - registration;
  - first generation;
  - first payment;
  - promo use;
  - referral reward.
- Campaign economics:
  - generated revenue;
  - tokens spent;
  - invoices paid;
  - refunds.
- Campaign timeline, dense list of attribution/conversion events.

Rules:

- Marketing data is factual only. If UTM/referrer was never captured, show `Нет данных`.
- Referrer and landing page can be sensitive; keep admin-only and truncate URLs.

## 6. Timeline Tab

Unified chronological event list.

Filters:

- `Все`
- `Контент`
- `Финансы`
- `Маркетинг`
- `Безопасность`
- `Админ`

Event types:

- registration;
- login;
- generation;
- image saved;
- token spent;
- invoice issued;
- payment received;
- refund;
- bonus granted;
- promo used;
- referral reward;
- admin action;
- ban/unban;
- password reset;
- role change;
- security event.

Layout:

- Left timestamp column.
- Middle event icon/type.
- Main summary text.
- Right compact value chip if amount/status exists.
- Details expandable per event, never all expanded by default.

## 7. CRM Settings Screen

Settings stays a dedicated operator configuration surface.

Sections:

- `Колонки списка`: visible, priority, desktop/tablet/mobile toggles.
- `Карточка клиента`: section visibility, first-screen modules, tab order.
- `Сохранённые виды`: Support, Finance, Marketing, Security, Technical audit.
- `Уровни админки`: matrix for Support / Manager / Admin / SuperAdmin.
- `Чувствительные данные`: contacts, prompts, IP, technical IDs, exports.
- `Экспорт`: who can export what, with audit logging.
- `Опасные действия`: reason required, double confirm, role thresholds.

Permission matrix:

- Support: view profile/contact if allowed, view basic timeline, no financial mutation.
- Manager: billing/promo actions if granted, no role/delete.
- Admin: trusted actions, refunds if granted, exports if granted.
- SuperAdmin: dangerous actions, settings, delete/anonymize with double confirm.

## 8. Confirm Modals

All confirm modals reuse one pattern:

- Target user: display name + public code.
- Action name.
- Amount/value/current and resulting value when applicable.
- Required reason field.
- Audit log notice.
- Confirm/cancel.
- Dangerous visual style for destructive/refund/delete/anonymize.

Flows:

- invoice issue: amount, currency, due date, plan/package.
- payment mark paid: invoice/payment target, amount, method, reason.
- refund: original payment, amount, reason, consequence.
- bonus grant: amount, source, reason.
- promo apply: code, reward/value, reason.
- referral correction: parent/child/reward, reason.
- ban/unban: consequence, sessions revoked if applicable, reason.
- delete/anonymize: double confirmation, typed phrase, reason, audit warning.

## Component Map

- `CrmTable`
- `CrmKpiStrip`
- `CrmColumnChip`
- `ActivityRing`
- `BusinessStatusChip`
- `ClientCard`
- `ClientCardHeader`
- `OverviewPanel`
- `FinanceTab`
- `PromoReferralTab`
- `MarketingTab`
- `TimelineTab`
- `RightActionPanel`
- `CrmSettings`
- `RolePermissionMatrix`
- `ConfirmModal`

## Action Map

- Row/card quick actions:
  - `Карточка`
  - `+50`
  - `-50`
  - `Действия`
- Finance:
  - issue invoice;
  - mark payment;
  - refund;
  - export.
- Promo/bonus/referral:
  - apply promo;
  - grant bonus;
  - cancel bonus if safe;
  - referral correction.
- Marketing:
  - view-only in 20E unless schema supports campaign edits.
- Security/admin:
  - ban/unban;
  - reset password;
  - role change;
  - delete/anonymize deferred/double-confirm.

## Responsive Rules

Desktop:

- dense table with horizontal scroll if needed;
- card width around 1100-1200px;
- sticky right action panel.

Tablet:

- table shows P0/P1 columns;
- hide marketing/device subdetails into card;
- card may become single column with action panel below header.

Mobile:

- list row instead of full 11-column table;
- card full-screen;
- tabs become horizontal scroll;
- action panel collapses into grouped bottom action drawer.

## Empty / Deferred Rules

- Never fake business data.
- Missing schema: `Отложено: нет схемы/данных`.
- Existing schema but no rows: `Нет счетов`, `Нет платежей`, `Нет бонусов`, etc.
- Permission missing: disabled action + tooltip/secondary label.
- Loading: skeleton rows with stable height.
- Error: section-level retry, not a global broken page unless auth fails.

## QA Acceptance

- No more than four visible row action controls.
- No long single-column profile page.
- No giant empty panels.
- No ungrouped destructive buttons.
- No raw secrets/hashes.
- No fake MAC.
- Business modules fit into current CRM table/card/settings/modal structure.

## QA / Visual Review

QA/Visual subagent could not complete because the agent usage limit was reached. Controller review takes over for this phase.

Visual acceptance criteria:

- The table must still read like the Users CRM reference: dense, scannable, row-first, with compact chips and clear action grouping.
- The client card must still read like the card reference: profile header, metrics strip, left data column, sticky right actions, tabs for depth.
- The settings screen must still read like the settings/access reference: matrix controls, role permissions, saved views, and sensitive-data rules.
- Business modules must not become separate landing pages.
- Each business module must have a compact summary on overview and dense rows in its tab.
- Buttons must be grouped by domain and role; never scatter 10+ actions across one row or first screen.
- Empty states must be short inline rows, not tall decorative cards.
- Timeline must be filterable and grouped; no unbounded raw event dump.
- Confirm modals must use one consistent compact pattern.
- Mobile must collapse to list/card/drawer patterns, not squeeze the desktop table.

Reject conditions:

- More than four visible row action controls.
- Multiple red destructive buttons visible in the table.
- Any fake payment/invoice/bonus/promo/referral/MAC/risk value represented as real.
- Raw `raw_profile_json`, hashes, raw cookies, raw tokens, initData/WebAppData, or raw settings/meta JSON visible.
- Long prompt/referrer/UTM values displayed untruncated.
- Huge empty finance/marketing/promo panels when no data exists.
- Full-ready wording before backend/schema phases are implemented.

Artifact plan:

- `docs/phase20E0A-crm-business-blueprint-mock.html` is a static HTML artifact, not product code.
- It demonstrates the intended surfaces:
  - expanded Users CRM table with finance, promo/referral, marketing and risk signals;
  - client card overview with finance/promo/marketing/timeline areas;
  - right action panel grouping;
  - settings/access matrix;
  - dangerous confirm modal.
- Screenshots should be generated from the static mock and stored under `docs/phase20E0A-artifacts/`.

## Controller Verdict

VISUAL BLUEPRINT READY for planning the next phases:

- 20E.0B Data / Schema Architecture can now map schemas to the visual surfaces.
- 20E.1 Billing can implement invoices/payments/refunds against the Finance tab blueprint.
- 20E.2 Promo / Bonus / Referrals can implement the loyalty tab.
- 20E.3 Marketing can implement attribution/timeline feeds.
- 20E.4 Settings / Admin levels can implement visibility and permission persistence.
- 20E.5 Timeline can implement unified event aggregation.
