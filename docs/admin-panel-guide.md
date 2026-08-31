---
status: canonical
document_role: admin-current-guide
audience: owner, operators, developers
updated: 2026-08-31
verified_source_sha: 11b087d8441cb109b50b1d1e863fdcfa73201d07
production_status_role: none
---

# Админка IZO_ASA — актуальное руководство

Это общее описание действующей административной поверхности IZO_ASA. Оно
объясняет, что доступно владельцу и оператору, где проходят границы безопасности
и какие сведения нельзя считать подтверждёнными без отдельной проверки.

Документ описывает source-состояние на указанном SHA. Он не подтверждает
deployment: установленный release всегда проверяется по runtime manifest и
`/api/version` в рамках разрешённой live-проверки.

Для изменений coding-агент использует scoped-карту
`docs/context/admin-control-center.md`. Порядок чтения репозитория остаётся только
в `AI_START_HERE.md`.

## Доступ

- Точка входа: `/admin`; `/admin` и `/admin/dashboard` открывают дашборд.
- Интерфейс использует server-side cookie session и отправляет запросы с
  `credentials: include`.
- Доступ разрешён только аутентифицированной учётной записи, у которой
  `account.role == admin`.
- `401` означает, что доверенная сессия отсутствует или истекла; `403` — что
  сессия есть, но административной роли нет.
- Клиентский `user_id`, `X-OneNode-User` и другие неподписанные значения не
  являются административной идентичностью.

## Текущая навигация

<!-- admin-top-routes:start -->
| Раздел | Маршрут | Назначение | Важная граница |
|---|---|---|---|
| Дашборд | `/admin/dashboard` | Оперативные показатели, графики генераций, активности, оплат и энергопотребления | «Потрачено» и «Заработано» в верхней полосе пока отображаются как незаполненные показатели |
| CRM | `/admin/crm` | Пользователи, активность, профиль, баланс, тариф, лояльность, счета, платежи, сессии, безопасность и медиа | Изменения пользователя являются реальными административными мутациями |
| Модели | `/admin/models/openrouter/text` | Каталоги, публикация, доступ по тарифам, экономика и локальные модели | Публикация модели должна совпадать с серверным доступом и фактическим списанием |
| Уведомления | `/admin/notifications` | Административные уведомления, прочтение, настройки доставки и состояние worker | Наличие worker не доказывает успешную доставку |
| Соцсети | `/admin/social` | Каналы публикации, credentials, проверка и тестовая доставка | Реальная доставка меняет состояние внешнего провайдера |
| Тарифы | `/admin/tariffs` | Тарифные модели, лимиты, сроки и промокоды | Финансовые параметры влияют на пользовательскую доступность и расчёты |
| Платежи | `/admin/payments` | Готовность провайдера, юридические настройки и пакеты | Настройки и connection check обращаются к реальному платёжному контуру; ручные счета и возвраты находятся в CRM |
| Почта | `/admin/mail` | Состояние SMTP/UniSender, конфигурация и тестовое письмо | Принято провайдером не означает доставлено адресату |
| Боты | `/admin/bots` | Telegram/MAX, polling/webhook, токены, проверка и диагностика | У каждого бота должен быть ровно один delivery owner |
| Логи | `/admin/logs` | Ошибки, события безопасности и аудит | Публичные ответы не должны раскрывать внутренние diagnostics или секреты |
<!-- admin-top-routes:end -->

Навигация адаптивная: на узком экране используется мобильное меню, на широком —
сворачиваемая боковая панель. Выбранное состояние свёрнутой панели хранится
локально в браузере.

## Раздел «Модели»

Верхний уровень:

<!-- admin-model-routes:start -->
| Страница | Маршрут | Что показывает |
|---|---|---|
| OpenRouter | `/admin/models/openrouter/text` | Облачные каталоги и общие настройки провайдера |
| Config UI | `/admin/models/config-ui` | Локальные модели, профили, LoRA и состояние локального сервера |
| Энергопотребление | `/admin/models/energy` | Мощность, стоимость электричества и оценку локальной себестоимости |
| Голосовой ввод | `/admin/models/voice-input` | Распознавание речи, маршрутизацию и проверку ввода |
| Улучшение промпта | `/admin/models/prompt-improvement` | Локальный/облачный маршрут, инструкции, fallback и экономику |
<!-- admin-model-routes:end -->

### OpenRouter

<!-- admin-openrouter-routes:start -->
| Подстраница | Маршрут |
|---|---|
| Текст | `/admin/models/openrouter/text` |
| Изображения | `/admin/models/openrouter/images` |
| Видео | `/admin/models/openrouter/video` |
| Звук | `/admin/models/openrouter/audio` |
| 3D | `/admin/models/openrouter/3d` |
| Настройки | `/admin/models/openrouter/settings` |
<!-- admin-openrouter-routes:end -->

Страница 3D пока является подготовленной заглушкой, а не подтверждённым рабочим
каталогом. Сведения о ценах, моделях и возможностях провайдера являются
наблюдаемыми данными и могут устаревать независимо от кода.

Пользовательский бренд генерации изображений остаётся `Flux2`. Технические
workflow и внутренние имена моделей не должны попадать на обычную
пользовательскую поверхность.

## CRM и административные действия

CRM объединяет список пользователей и досье выбранного пользователя. Доступны
контакты и identities, активность, генерации, галерея, тариф, токены, скидка,
лояльность, промокоды, рефералы, счета, платежи, сессии и события безопасности.

Критичные CRM v2 действия требуют причины и должны создавать audit event. Для
финансовых действий дополнительно нужны идемпотентность и транзакционность.
Наличие административной роли само по себе не является разрешением выполнять
реальный возврат, отправку, webhook-переключение или provider test.

В кодовой базе остаются compatibility routes с более старыми именами. Их нельзя
автоматически считать безопасными или небезопасными только по названию. Для
каждой изменяемой операции проверяются фактические trusted-admin gate, audit,
reason, idempotency и тесты. Для bounded-набора из 19 критичных
identity/CRM/finance mutations сначала используется
`docs/admin-mutation-audit.md`: он даёт exact symbol/test nodes, статусы
`verified`/`partial`/`gap` и обязательные `gap_ids`. Ещё 39 mutation routes в
эту карту не входят и не считаются проверенными автоматически.

## Секреты и внешние провайдеры

- Сырые API keys, bot tokens, webhook secrets, SMTP passwords, cookies и OTP не
  показываются, не логируются и не попадают в Git или документацию.
- Секреты сохраняются вне репозитория через разрешённый secret store; интерфейс
  показывает только безопасный статус наличия/проверки.
- Автоматические тесты используют fake providers и временные данные.
- Реальные платежи, возвраты, письма, публикации, paid generation, смена
  webhook и ротация токена требуют явного operator authorization.
- Production SQLite, media, secrets и runtime manifests не являются тестовыми
  fixtures.

## Что означает состояние на экране

- `configured` — настройки сохранены, но внешний сервис может быть недоступен.
- `verified` — конкретная проверка завершилась успешно в указанное время; это не
  бессрочная гарантия.
- `running` — процесс существует; это не доказывает недавнюю успешную работу.
- `accepted` — провайдер принял запрос; это не равно `delivered` или
  `published`.
- HTTP `200` доказывает ответ маршрута, но не пользовательский сценарий,
  финансовый результат или provider operation.

## Проверки, относящиеся к админке

Backend-покрытие включает CRM/actions, dashboard analytics, trusted access,
ботов, почту, уведомления и соцсети. Основные файлы:

- `backend/test_admin_v2.py`;
- `backend/test_admin_actions.py`;
- `backend/test_admin_analytics.py`;
- `backend/test_admin_bots_v2.py`;
- `backend/test_admin_mail_v2.py`;
- `backend/test_admin_notifications.py`;
- `backend/test_admin_social_router.py`.

Route-level contract критичных compatibility mutations проверяется отдельно:

- `python -m pytest -q tools/test_admin_mutation_audit.py`.

Frontend-проверки:

- `frontend/e2e-admin-dashboard-layout.mjs` — структура и responsive dashboard;
- `frontend/e2e-admin-model-pages.mjs` — каталоги моделей и responsive layout;
- `frontend/e2e-admin-crm-live.mjs` — live QA CRM-сценарий с явными session token
  и user code;
- `frontend/e2e-security-admin.mjs` — административная граница;
- `frontend/smoke-admin-analytics.mjs` — статический contract;
- `frontend/visual-admin-parity.mjs` — визуальная parity-проверка.

Часть browser-тестов работает с подменёнными API-ответами. Такой тест доказывает
UI-контракт, но не реальную provider delivery и не production deployment.
Текущий `e2e-admin-crm-live.mjs` всё ещё ожидает семь верхних KPI, тогда как
shell и dashboard-layout contract используют шесть. До исправления этой
предпосылки его нельзя считать зелёным доказательством текущего интерфейса.

## Карта документации

Текущие источники:

- `docs/admin-panel-guide.md` — это общее актуальное руководство;
- `docs/context/admin-control-center.md` — bounded-контекст для coding-агентов;
- `docs/admin-change-contract.md` — проверяемая ownership/API/risk/test матрица
  и исполняемые change recipes;
- `docs/admin-mutation-audit.md` — bounded route-level evidence и remediation
  gaps для 19 критичных compatibility mutations;
- `docs/generated/frontend-map.md` и `backend/SYMBOL_MAP.md` — генерируемое
  структурное evidence;
- `docs/admin-bots-openrouter-operations-20260716.md` — узкий runbook по ботам;
- `docs/mail-unisender-operations.md` — узкий runbook по почте;
- `docs/production-release-runbook.md` — единственный release/live runbook.

`docs/admin-panel-product-spec.md`, Phase 18/20 документы, датированные model
plans и remediation checklists являются historical/design evidence. Они могут
объяснять решение или незавершённую программу, но не определяют текущую
навигацию, текущий release или активный backlog.

## Поддержание актуальности

При изменении навигации, административной роли, API ownership, обязательного
аудита или проверок в одном commit обновляются это руководство, scoped context и
релевантные generated maps. Изменение provider catalog или production release
не должно вручную переписывать source-факты: наблюдаемое состояние фиксируется
отдельным датированным evidence/receipt.

До заявления `DEPLOYED` или `OPERATIONALLY VERIFIED` нужны отдельные exact-release
и реальные redacted evidence. Документация и локальные тесты дают только
`IMPLEMENTED`/`TESTED` в своей среде.
