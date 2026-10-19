---
status: canonical
document_role: admin-change-contract
audience: coding-agents, reviewers
updated: 2026-10-19
verified_product_source_sha: 11b087d8441cb109b50b1d1e863fdcfa73201d07
depends_on: docs/admin-panel-guide.md, docs/context/admin-control-center.md
production_status_role: none
---

# Admin change contract

Контракт связывает admin-область с routes, ownership, API, effects, risk,
controls и targeted tests. Применяется после `AI_START_HERE.md`, Task Contract
и `docs/context/admin-control-center.md`; production/provider action не разрешает.

## Как использовать

1. Найти область по `id`; объявить только нужные frontend/backend/tests/docs.
2. Сверить `side_effects`; при `risk_escalates_when` поднять риск до
   `risk_escalates_to`.
3. Проверить каждый `required_control` в backend route: это требование,
   а не blanket claim о legacy-коде.
4. Production/provider state требует `live_action_risk`; поле не даёт разрешения.
5. Выполнить recipe; записать непроверенные live-границы.
6. Для 19 routes из `docs/admin-mutation-audit.md` перенести `status`, все
   `gap_ids` и обязательный replay/race test в Task Contract до remediation.

`api_examples` репрезентативны; полный inventory — `backend/SYMBOL_MAP.md`
и modular routers.

## Машинно-читаемый контракт

<!-- admin-change-contract-json:start -->
```json
{
  "version": 1,
  "source_sha": "11b087d8441cb109b50b1d1e863fdcfa73201d07",
  "areas": [
    {
      "id": "dashboard",
      "label": "Дашборд",
      "entry_route": "/admin/dashboard",
      "frontend": ["frontend/src/AdminApp.tsx"],
      "backend": ["backend/main.py", "backend/app/services/admin_analytics.py"],
      "api_examples": ["/api/admin/summary", "/api/admin/dashboard-v2"],
      "side_effects": [],
      "risk_floor": "standard",
      "risk_escalates_to": "high-assurance",
      "risk_escalates_when": ["меняется telemetry contract или public diagnostics"],
      "live_action_risk": "release-ops",
      "required_controls": ["trusted-admin-read", "no-public-operator-diagnostics"],
      "tests": ["backend/test_admin_analytics.py", "frontend/e2e-admin-dashboard-layout.mjs"]
    },
    {
      "id": "crm",
      "label": "CRM",
      "entry_route": "/admin/crm",
      "frontend": ["frontend/src/adminAnalytics.tsx", "frontend/src/adminCommand.ts"],
      "backend": ["backend/main.py", "backend/app/services/admin_analytics.py", "backend/app/services/admin_commands.py", "backend/app/services/admin_entitlement_commands.py", "backend/app/database/admin_command_schema.py"],
      "api_examples": ["/api/admin/users-analytics-v2", "/api/admin/users/{internal_user_id}/v2", "/api/admin/users/{internal_user_id}/tokens-v2", "/api/admin/users/{internal_user_id}/plan-v2"],
      "side_effects": ["user-profile", "role", "plan", "tokens", "billing", "sessions", "media"],
      "risk_floor": "standard",
      "risk_escalates_to": "high-assurance",
      "risk_escalates_when": ["меняется identity, role, tokens, billing, security, media ownership или destructive action"],
      "live_action_risk": "release-ops",
      "required_controls": ["trusted-admin", "verify-per-endpoint", "reason", "audit", "idempotency-for-finance"],
      "tests": ["backend/test_admin_v2.py", "backend/test_admin_actions.py", "backend/test_admin_analytics.py", "backend/test_admin_password_reset.py", "backend/test_admin_command_idempotency.py", "backend/test_admin_command_transactions.py", "backend/test_admin_command_migration.py", "frontend/adminCommand.test.ts", "frontend/e2e-admin-command-retry.mjs"]
    },
    {
      "id": "models",
      "label": "Модели",
      "entry_route": "/admin/models/openrouter/text",
      "frontend": ["frontend/src/adminModels.tsx", "frontend/src/adminModelsRoutes.ts", "frontend/src/adminTextModelCatalog.tsx"],
      "backend": ["backend/main.py", "backend/app/api/routers/admin_operations.py"],
      "api_examples": ["/api/admin/models-page", "/api/admin/openrouter/catalog/status-v2", "/api/admin/config-ui/status-v2", "/api/admin/config-ui/reload-v2", "/api/admin/config-ui/switch-v2", "/api/admin/config-ui/interrupt-v2"],
      "side_effects": ["catalog-publication", "tariff-access", "pricing", "provider-secret", "local-runtime"],
      "risk_floor": "standard",
      "risk_escalates_to": "high-assurance",
      "risk_escalates_when": ["меняется публикация, цена, quote/reservation/settlement, API key или provider call"],
      "live_action_risk": "release-ops",
      "required_controls": ["trusted-admin", "verify-per-endpoint", "audit", "publication-access-settlement-consistency", "fake-provider-tests"],
      "tests": ["backend/test_admin_v2.py", "backend/test_openrouter_admin_cache_v2.py", "backend/test_phone_chat_model_catalog.py", "backend/test_tariff_model_counts.py", "frontend/e2e-admin-model-pages.mjs", "frontend/adminImageModelPublication.test.ts", "frontend/adminVideoPublication.test.ts"]
    },
    {
      "id": "notifications",
      "label": "Уведомления",
      "entry_route": "/admin/notifications",
      "frontend": ["frontend/src/adminNotifications.tsx"],
      "backend": ["backend/app/api/routers/admin_operations.py", "backend/app/services/admin_notifications.py", "backend/app/services/admin_notification_delivery.py"],
      "api_examples": ["/api/admin/notifications-v2", "/api/admin/notifications/settings-v2"],
      "side_effects": ["read-state", "delivery-settings", "durable-worker"],
      "risk_floor": "standard",
      "risk_escalates_to": "high-assurance",
      "risk_escalates_when": ["меняется persistent worker, retry/idempotency или реальная доставка"],
      "live_action_risk": "release-ops",
      "required_controls": ["trusted-admin", "audit", "durable-state", "fake-provider-tests"],
      "tests": ["backend/test_admin_notifications.py", "backend/test_social_providers.py"]
    },
    {
      "id": "social",
      "label": "Соцсети",
      "entry_route": "/admin/social",
      "frontend": ["frontend/src/adminSocial.tsx"],
      "backend": ["backend/app/api/routers/admin_operations.py", "backend/app/services/social_delivery.py"],
      "api_examples": ["/api/admin/social-v2", "/api/admin/social/{network}/check-v2"],
      "side_effects": ["provider-credentials", "publication-settings", "external-delivery"],
      "risk_floor": "standard",
      "risk_escalates_to": "high-assurance",
      "risk_escalates_when": ["выполняется live verify, test delivery, credential change или publication"],
      "live_action_risk": "release-ops",
      "required_controls": ["trusted-admin", "audit", "secret-store", "explicit-live-authorization", "fake-provider-tests"],
      "tests": ["backend/test_admin_social_router.py", "backend/test_social_providers.py", "backend/test_social_delivery.py"]
    },
    {
      "id": "tariffs",
      "label": "Тарифы",
      "entry_route": "/admin/tariffs",
      "frontend": ["frontend/src/AdminApp.tsx"],
      "backend": ["backend/main.py"],
      "api_examples": ["/api/admin/settings", "/api/admin/promos"],
      "side_effects": ["tariff-access", "limits", "promo", "pricing-input"],
      "risk_floor": "standard",
      "risk_escalates_to": "high-assurance",
      "risk_escalates_when": ["изменяется пользовательский доступ, цена, скидка, лимит или промокод"],
      "live_action_risk": "release-ops",
      "required_controls": ["trusted-admin", "verify-per-endpoint", "audit", "financial-consistency"],
      "tests": ["backend/test_tariff_model_counts.py", "backend/test_promo_bonus_referral_v2.py", "backend/test_product_consistency_20e2b.py"]
    },
    {
      "id": "payments",
      "label": "Платежи",
      "entry_route": "/admin/payments",
      "frontend": ["frontend/src/adminPayments.tsx"],
      "backend": ["backend/main.py", "backend/app/billing/contracts.py", "backend/app/billing/outbox.py"],
      "api_examples": ["/api/admin/payments/status-v2", "/api/admin/payments/config-v2", "/api/admin/payments/check-v2", "/api/admin/payments/{payment_id}/refund-v2"],
      "side_effects": ["payment-config", "checkout-package", "invoice", "refund", "provider-call"],
      "risk_floor": "high-assurance",
      "risk_escalates_to": "high-assurance",
      "risk_escalates_when": ["любое изменение денег, webhook, outbox, refund, reconcile или provider state"],
      "live_action_risk": "release-ops",
      "required_controls": ["trusted-admin", "reason", "audit", "transaction", "idempotency", "explicit-live-authorization"],
      "tests": ["backend/test_admin_actions.py", "backend/test_billing_v2.py", "backend/test_billing_notification_outbox.py", "backend/test_yookassa_connection_check.py"],
      "coverage_gaps": ["PUT /api/admin/payments/config-v2 не имеет focused route test; до изменения config mutation добавить characterization"]
    },
    {
      "id": "mail",
      "label": "Почта",
      "entry_route": "/admin/mail",
      "frontend": ["frontend/src/adminMail.tsx"],
      "backend": ["backend/main.py"],
      "api_examples": ["/api/admin/mail/status-v2", "/api/admin/mail/config-v2", "/api/admin/mail/test-v2"],
      "side_effects": ["smtp-secret", "provider-config", "external-email"],
      "risk_floor": "standard",
      "risk_escalates_to": "high-assurance",
      "risk_escalates_when": ["сохраняется secret, выполняется verify или отправляется письмо"],
      "live_action_risk": "release-ops",
      "required_controls": ["trusted-admin", "audit", "secret-store", "explicit-live-authorization", "fake-provider-tests"],
      "tests": ["backend/test_admin_mail_v2.py"],
      "coverage_gaps": ["PUT /api/admin/mail/config-v2 and POST /api/admin/mail/test-v2 lack focused fake-provider route tests"]
    },
    {
      "id": "bots",
      "label": "Боты",
      "entry_route": "/admin/bots",
      "frontend": ["frontend/src/adminBots.tsx"],
      "backend": ["backend/app/api/routers/bots_admin.py", "backend/app/services/bot_admin.py", "backend/app/services/bot_workers.py"],
      "api_examples": ["/api/admin/bots/status-v2", "/api/admin/bots/config-v2", "/api/admin/bots/telegram/set-webhook-v2"],
      "side_effects": ["bot-secret", "delivery-mode", "polling-owner", "webhook", "provider-call"],
      "risk_floor": "standard",
      "risk_escalates_to": "high-assurance",
      "risk_escalates_when": ["меняется token, cursor, polling/webhook owner или выполняется provider action"],
      "live_action_risk": "release-ops",
      "required_controls": ["trusted-admin", "audit", "secret-store", "single-delivery-owner", "explicit-live-authorization", "fake-provider-tests"],
      "tests": ["backend/test_admin_bots_v2.py", "backend/test_polling_health.py", "backend/test_bot_runtime.py"]
    },
    {
      "id": "logs",
      "label": "Логи",
      "entry_route": "/admin/logs",
      "frontend": ["frontend/src/AdminApp.tsx"],
      "backend": ["backend/main.py"],
      "api_examples": ["/api/admin/logs-v2", "/api/admin/audit-logs-v2"],
      "side_effects": [],
      "risk_floor": "standard",
      "risk_escalates_to": "high-assurance",
      "risk_escalates_when": ["меняется redaction, retention, public diagnostics или privacy boundary"],
      "live_action_risk": "release-ops",
      "required_controls": ["trusted-admin-read", "redaction", "no-secrets", "no-public-operator-diagnostics"],
      "tests": ["backend/test_admin_v2.py", "backend/test_public_status_redaction.py"],
      "coverage_gaps": ["authenticated success and redaction coverage is absent for GET /api/admin/logs-v2 and GET /api/admin/audit-logs-v2"]
    }
  ],
  "model_pages": [
    {"id": "api", "label": "OpenRouter", "path": "/admin/models/openrouter/text"},
    {"id": "config", "label": "Config UI", "path": "/admin/models/config-ui"},
    {"id": "energy", "label": "Энергопотребление", "path": "/admin/models/energy"},
    {"id": "voice", "label": "Голосовой ввод", "path": "/admin/models/voice-input"},
    {"id": "improve", "label": "Улучшение промпта", "path": "/admin/models/prompt-improvement"}
  ],
  "openrouter_pages": [
    {"id": "text", "label": "Текст", "path": "/admin/models/openrouter/text"},
    {"id": "images", "label": "Изображения", "path": "/admin/models/openrouter/images"},
    {"id": "video", "label": "Видео", "path": "/admin/models/openrouter/video"},
    {"id": "audio", "label": "Звук", "path": "/admin/models/openrouter/audio"},
    {"id": "3d", "label": "3D", "path": "/admin/models/openrouter/3d"},
    {"id": "settings", "label": "Настройки", "path": "/admin/models/openrouter/settings"}
  ]
}
```
<!-- admin-change-contract-json:end -->

## Change recipes

### 1. Документация или route contract

Подходит, когда product behavior не меняется.

```powershell
python -m pytest -q tools/test_admin_docs_contract.py tools/test_context_docs.py tools/test_agent_instructions.py
git diff --check
```

При изменении route обновить source, таблицу в `docs/admin-panel-guide.md` и
JSON-контракт в одном commit. Тест требует точного равенства множеств и обнаружит
как забытый новый route, так и устаревший лишний route.

### 2. Navigation, dashboard или read-only layout

```powershell
python -m pytest -q tools/test_admin_docs_contract.py backend/test_admin_analytics.py
npm --prefix frontend run lint
npm --prefix frontend run build
```

Для route-mocked dashboard E2E запустить из isolated worktree отдельный Vite
server, затем тест:

```powershell
npm --prefix frontend run admin:dev -- --host 127.0.0.1 --port 5174
$env:QA_ADMIN_BASE_URL = "http://127.0.0.1:5174"
npm --prefix frontend run e2e:admin-dashboard
```

Не направлять `VITE_API_BASE_URL` на production. Server и E2E запускаются в
разных терминалах; после проверки dev server останавливается.

### 3. CRM mutation

```powershell
python -m pytest -q tools/test_admin_mutation_audit.py
python -m pytest -q backend/test_admin_v2.py backend/test_admin_actions.py backend/test_admin_analytics.py backend/test_admin_password_reset.py
```

До правки зафиксировать target user state и rollback boundary только на
временной test DB. Для role/tokens/billing/security проверить trusted identity,
reason, audit и idempotency. Если route присутствует в mutation audit, package
обязан включить все его `gap_ids`; `partial` и `gap` нельзя трактовать как
готовое покрытие. Live CRM E2E не запускать как обычный тест: он
требует операторские QA credentials и имеет известную устаревшую 7-KPI
предпосылку.

Для `tokens-v2`/`plan-v2` дополнительно обязателен
[контракт команды и приёмки](admin-entitlement-command-contract.md): atomic
key binding, сохранённый CRM retry, targeted tests и реальный Docker/CRM gate.

### 4. Model catalog, publication или pricing

```powershell
python -m pytest -q backend/test_admin_v2.py::test_config_ui_reload_requires_reason_clears_cache_and_logs backend/test_admin_v2.py::test_config_ui_interrupt_requires_reason_calls_comfy_and_logs backend/test_admin_v2.py::test_config_ui_switch_updates_global_profile_and_routes backend/test_openrouter_admin_cache_v2.py backend/test_phone_chat_model_catalog.py backend/test_tariff_model_counts.py backend/test_product_consistency_20e2b.py
npm --prefix frontend run test:admin-image-publication
node frontend/adminVideoPublication.test.ts
npm --prefix frontend run lint
npm --prefix frontend run build
```

Для route-mocked model navigation/responsive E2E запустить из isolated worktree
отдельный Vite server, затем тест:

```powershell
npm --prefix frontend run admin:dev -- --host 127.0.0.1 --port 5174
$env:QA_ADMIN_BASE_URL = "http://127.0.0.1:5174"
npm --prefix frontend run e2e:admin-model-pages
```

Server и E2E запускаются в разных терминалах; `VITE_API_BASE_URL` не направлять
на production, после проверки dev server остановить.

Если меняется цена или публикация, добавить focused quote/reservation/settlement
tests из затронутого продукта. Route-mocked visual E2E не доказывает фактическое
списание или provider availability.

### 5. Notifications, social, mail или bots

```powershell
python -m pytest -q backend/test_admin_notifications.py backend/test_admin_social_router.py backend/test_social_providers.py backend/test_social_delivery.py backend/test_admin_mail_v2.py backend/test_admin_bots_v2.py backend/test_polling_health.py backend/test_bot_runtime.py
```

Тесты используют fake providers и temporary roots. Реальные verify, письмо,
публикация, webhook или token action запрещены без отдельного owner-authorized
release-ops package.

CURRENT COVERAGE GAP: `PUT /api/admin/mail/config-v2` и
`POST /api/admin/mail/test-v2` не имеют focused route tests. Package, меняющий
mail config или test-send, сначала добавляет characterization с fake SMTP для
trusted-admin, validation, audit и redacted response; live SMTP запрещён.

### 6. Payments, auth и persistent workers

Пример для payment ledger/outbox: запустить только точные focused
race/idempotency tests пять раз, не весь Full:

```powershell
1..5 | ForEach-Object {
  python -m pytest -q `
    backend/test_billing_v2.py::test_mark_paid_grants_tokens_once_through_ledger `
    backend/test_billing_notification_outbox.py::test_outbox_claim_prevents_duplicate_processing_and_recovers_expired_lease
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

Для другого package эти node IDs заменяются тестом конкретного изменённого
invariant. Production money, provider webhook и live secrets не используются.

Для payment status/provider check использовать fake-provider coverage:

```powershell
python -m pytest -q backend/test_yookassa_connection_check.py
```

CURRENT COVERAGE GAP: `PUT /api/admin/payments/config-v2` не имеет focused route
test. Package, меняющий config mutation, сначала добавляет characterization для
trusted-admin, validation, persistence, audit и secret handling.

CURRENT COVERAGE GAP: authenticated success/redaction для
`GET /api/admin/logs-v2` и `GET /api/admin/audit-logs-v2` не покрыты focused
tests. Package, меняющий serialization, retention или redaction, сначала
добавляет characterization для обеих routes и доказывает отсутствие secrets,
config presence и internal operator details в ответах.

### 7. Package gate

После targeted checks завершённого non-release package:

```powershell
python -m pytest -q tools/test_admin_docs_contract.py
pwsh -File tools/verify.ps1 -Mode Quick
```

Новый admin-doc contract test запускается явно перед Quick и автоматически
попадает в CI/Full через pytest collection `tools/test_*.py`.

## Review checklist

- Exact source routes, guide tables и JSON contract совпадают.
- Все declared paths и tests существуют.
- Каждый API example найден в symbol map или modular router.
- Mutation не снижает `risk_floor` и учитывает escalation conditions.
- Required controls подтверждены source/tests, а не только текстом документа.
- Route-mocked UI evidence не назван live/operational evidence.
- Product code, generated evidence и документация обновлены вместе, если менялся
  их contract.
- Состояния `IMPLEMENTED`, `TESTED`, `COMMITTED`, `PUSHED/PR`, `MERGED`,
  `DEPLOYED`, `OPERATIONALLY VERIFIED` разделены.
