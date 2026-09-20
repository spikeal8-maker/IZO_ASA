---
status: canonical
domain: billing-payments
read_when: ["billing","payments","checkout","refunds"]
source_paths: ["backend/app/billing/contracts.py","backend/app/billing/outbox.py","backend/app/billing/yookassa_provider.py","frontend/src/PaymentResultPage.tsx","frontend/src/phone/core/billing.ts"]
test_paths: ["backend/test_billing_v2.py","backend/test_billing_notification_outbox.py","backend/test_billing_yookassa_provider.py","backend/test_yookassa_checkout_v2.py","backend/test_billing_simulator_checkout_v2.py"]
related_domains: ["admin-control-center","chat"]
forbidden_paths: ["unknown"]
owner: billing-payments-platform
context_role: scoped-domain-map
updated: 2026-09-19
---
# Context: биллинг и платежи

## Назначение

Эта карточка задаёт bounded-контекст для billing contracts, checkout, payment state, refunds и outbox obligations.
Она не является инструкцией для реальных платежей и не разрешает provider mutations.
Административные финансовые действия дополнительно требуют domain `admin-control-center`.

## Billing contracts

`backend/app/billing/contracts.py` задаёт canonical contracts финансового слоя.
Изменение формы запроса или ответа должно сохранять различие между intent, pending, confirmed, failed и refunded state.
UI не может вводить собственную альтернативную интерпретацию settlement.
Provider payload сначала проходит существующий billing boundary.
## Checkout boundary

Checkout является созданием платёжного намерения, а не подтверждением оплаты.
Важно различать:
- создание checkout;
- redirect/provider interaction;
- получение подтверждения;
- нормализацию provider result;
- обновление durable payment state;
- последующие side effects.

Повтор checkout request не должен случайно создавать второе обязательство без contract reason.

## Provider adapter

`backend/app/billing/yookassa_provider.py` является boundary для YooKassa.
Он адаптирует внешний provider protocol к внутреннему contract.
Product policy не должна переезжать в provider adapter.
Наличие provider response не является достаточным доказательством settlement.

Реальные provider calls в обычном coding/test workflow запрещены.

## Durable payment state

Durable billing state является источником истины для подтверждённого финансового перехода.
Временный UI state, redirect result или единичный HTTP response не заменяют durable state.
Повтор одного external event должен быть безопасным.
Неизвестный результат нельзя автоматически трактовать как confirmed или failed.

## Outbox obligations

`backend/app/billing/outbox.py` владеет durable obligations после финансового изменения.
Ошибка доставки notification не должна стирать уже зафиксированное обязательство.
Повторная доставка должна следовать существующему idempotency contract.
Outbox не заменяет billing state и не является его вторым источником истины.

## Refund и idempotency boundary

Refund является отдельным финансовым transition.
Повтор одного refund request не должен повторять финансовый side effect.
Перед изменением refund behavior проверять:
- canonical payment identity;
- текущий durable state;
- idempotency key/contract;
- audit boundary;
- provider adapter behavior;
- повторную доставку side effects.

Реальный refund не выполняется в рамках этой карточки.

## Основные точки входа

- `backend/app/billing/contracts.py` — billing contracts.
- `backend/app/billing/outbox.py` — durable outbox obligations.
- `backend/app/billing/yookassa_provider.py` — provider adapter.
- `frontend/src/PaymentResultPage.tsx` — web UI результата оплаты.
- `frontend/src/phone/core/billing.ts` — phone billing client contract.

Начинать с владельца наблюдаемого transition и расширять чтение только при доказанном contract edge.

## Границы UI

`frontend/src/PaymentResultPage.tsx` отображает результат, но не подтверждает settlement.
UI success state не является source of truth.
Клиентский retry не должен создавать новый payment intent без разрешённого contract.
Если UI показывает устаревшее состояние, сначала определить, где находится canonical durable state.

## Граница admin-control-center

Admin finance UI, manual adjustments, refunds и operator actions относятся к `admin-control-center`.
Эта карточка описывает billing/payment boundary, но не расширяет административные разрешения.
Операция администратора не должна обходить trusted admin, audit, reason или idempotency requirements.

## Граница chat billing

Chat может создавать собственные quote/settlement flows.
Если изменение начинается в chat economics, дополнительно нужен domain `chat`.
`billing-payments` не забирает ownership у chat billing services.
Общий payment provider boundary не означает общий product policy.

## Focused tests
- `backend/test_billing_v2.py`
- `backend/test_billing_notification_outbox.py`
- `backend/test_billing_yookassa_provider.py`
- `backend/test_yookassa_checkout_v2.py`
- `backend/test_billing_simulator_checkout_v2.py`

Выбирать tests по реально изменяемому transition.
Provider adapter changes требуют provider contract tests, но не live provider calls.

## Safety

- Не выполнять реальные платежи.
- Не создавать реальный checkout.
- Не выполнять реальный refund.
- Не отправлять provider mutations.
- Не использовать production payment credentials.
- Не использовать production billing data как test fixture.
- Не считать HTTP 200 доказательством settlement.
- Не логировать секреты или полные provider credentials.

## Unknown live provider state

Repository source не подтверждает:
- доступность YooKassa;
- состояние конкретного live checkout;
- факт реального settlement;
- состояние реального refund;
- актуальность production credentials;
- факт доставки external notification.

Для этих утверждений нужен отдельный разрешённый operational evidence.

## Минимальный handoff

При расширении scope фиксировать:
- какой billing transition меняется;
- затрагивается ли provider adapter;
- меняется ли durable payment state;
- затрагивается ли outbox obligation;
- нужен ли `admin-control-center`;
- нужен ли `chat`;
- какие idempotency tests подтверждают изменение.

Карточка предназначена для маршрутизации и финансовых границ, а не для истории проекта.