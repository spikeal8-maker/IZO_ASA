---
status: canonical
document_role: admin-entitlement-command-contract
scope: tokens-v2, plan-v2
updated: 2026-10-20
production_status_role: none
---

# CRM: контракт команды и приёмки tokens/plan

Обязательный контракт `ADMIN-COMMAND-IDEMPOTENCY-001` для
`POST /api/admin/users/{internal_user_id}/tokens-v2` и `plan-v2`.
[Mutation audit](admin-mutation-audit.md) сохраняет 19 route contracts,
25 artifact fingerprints, test nodes и все девять AM-записей.
AM-001/002 имеют статус `implemented-with-exact-head-gates`;
AM-006 разрешён только для этих двух routes. AM-003–009 вне этого scope открыты.
Документ задаёт gates, но не является CI/Docker receipt, разрешением live action
или подтверждением `DEPLOYED`, `OPERATIONALLY VERIFIED` либо полной Д3.

## Действия оператора при потере ответа

В CRM откройте карточку → «Управление» → «Своя сумма» или «Изменить тариф».
Укажите значение и непустую причину, подтвердите. Эти два действия сохраняют
идентификатор и payload **до отправки**. Повторный клик, потеря ответа и reload
используют ту же команду; сервер возвращает первый результат без нового
изменения баланса, grant или дат тарифа.

Если исход неизвестен, откройте то же действие в той же вкладке и подтвердите
сохранённые значения. Другой payload не заменяет pending command. Новое действие
получает новый key после подтверждённого успеха. Не очищайте данные вкладки
для обхода неизвестного исхода: сначала проверьте результат. Закрытие вкладки
или ручная очистка session storage не гарантирует сохранение pending key.
Каждый повтор проверяет текущие admin permissions; сохранённый ключ не обходит
их отзыв. Остальные invoice/loyalty/payment-maintenance gaps не закрыты.

## Атомарность и совместимость

Main handlers делегируют изменения в
`backend/app/services/admin_entitlement_commands.py`; durable control находится
в `backend/app/services/admin_commands.py`.
`BEGIN IMMEDIATE` предшествует чтению actor, command и balance.
Обязательный глобально уникальный key связан с actor, target, operation и
нормализованным payload. Текущие права проверяются до replay; конфликт binding
даёт generic 409. Финансовый effect, audit и сохранённый первый response входят
в одну SQLite transaction. Ошибка audit/receipt откатывает всю команду;
разные concurrent debits не теряют обновления и не дают отрицательный balance.

`tokens-v2` применяет относительный delta однократно; `plan-v2` связывает
source id, grant и исходные даты с командой. Исторически первый route писал
новый ledger на каждый вызов, а второй создавал UUID source id и новый grant key,
повторно начислял тарифные токены и сбрасывал период. История исходного audit
сохранена в его `historical_evidence` и `source_sha`.

`frontend/src/adminCommand.ts` хранит pending key/payload в session storage и
в отправившем клиенте до подтверждения. ACK удаляет только свою попытку;
повтор увеличивает общий номер. Иной shared key блокирует старый pending retry.
Первый 400 освобождает key лишь при неизменной первой попытке и успешной очистке.
Проверять unknown response, close/reopen, reload, двойной клик и ошибки storage.
В `frontend/src/adminAnalytics.tsx` ответ закрытого dialog не управляет новым.

Additive migration 8 (`backend/app/database/admin_command_schema.py`, registry
в `backend/app/database/migrations.py`) сохраняет прежние users/ledger/tariff
records, проверяет metadata/schema и допускает повтор. Startup сначала проверяет
поддерживаемую максимальную версию; незнакомая будущая DB отклоняется.
Rollback для старого binary — проверенное восстановление pre-upgrade
SQLite/media snapshot. Изменение schema version на обновлённой DB не является
rollback; installed/production state не используется как fixture.

## Проверки и актуализация evidence

До изменения audited route найдите exact method/path, его symbol и test nodes.
Перенесите status и все gap_ids в Task Contract, проверьте overlap и читайте
только нужные symbols. Сначала получите failing-before characterization,
затем fixed-after. Для money/token/entitlement/concurrency повторите точный
race/idempotency node пять раз на temporary DB, без повторения всего Full.

Все 19 audited handlers требуют `require_trusted_admin`; audit вызывается
в handler либо явно связанном service в DB transaction. Для 16 routes причина
непуста; три payment-maintenance routes сохраняют whitespace gap AM-008.
Route fingerprint включает decorator и всё тело handler. Полные fingerprints
main, map, services и test artifacts связывают также helper/model dependencies.
Старый discovery SHA не подменяет текущую идентичность source или результат CI.

После изменения source сначала выполните repository generators для backend
symbol map, architecture, frontend и context maps. Затем обновите **только**
fingerprints штатным CLI; классификацию и scope проверяют отдельно по source
и независимому review. Не переписывайте hashes вручную.

```powershell
python tools/test_admin_mutation_audit.py --refresh-fingerprints
python -m pytest -q tools/test_admin_mutation_audit.py
python -m pytest -q backend/test_admin_command_idempotency.py backend/test_admin_command_transactions.py backend/test_admin_command_migration.py backend/test_admin_actions.py backend/test_product_consistency_20e2b.py backend/test_promo_bonus_referral_v2.py
node frontend/adminCommand.test.ts
python -m unittest tools.test_docker_admin_commands -v
```

Пять повторов соответствующих race tests встроены в параметризацию. Проверять
missing/invalid key, current auth, changed actor/target/operation/payload,
stored response, single ledger/grant/audit, plan dates, distinct debits,
audit/receipt failure, additive upgrade и snapshot restore.
Frontend tests проверяют pending key и late-response races. Общие lint/build
и package gates заданы в [change contract](admin-change-contract.md).
Положительные unit tests не закрывают реальный Docker gate.

## Реальный Docker и CRM gate

`.github/workflows/admin-command-docker.yml` собирает существующий DEV Dockerfile
на точном SHA в отдельной GitHub Ubuntu VM. `tools/docker_admin_commands.py`
допускает только hosted Linux, чистый checkout и explicit local Unix socket;
чужие Docker contexts/TLS/builders отклоняются. Имена и три ownership labels
привязаны к run/SHA. Контейнеры работают без сети и опубликованных портов;
cleanup повторно проверяет labels каждого ресурса, без global prune.

Fixtures — собственные synthetic admin/session/targets и disposable volumes.
`tools/docker_admin_commands_runtime.py` вызывает реальные loopback HTTP
handlers через uvicorn и связывает response с одной command/ledger/audit
записью, grant, балансом и точными plan dates. Verifier сверяет запрошенный
тариф/срок, ожидаемый grant и redacted row digests, а не только counts.

`frontend/e2e-admin-command-retry.mjs` открывает реальную desktop/mobile CRM:
close/reopen до ACK, поздний ACK первого запроса, потеря ответа повтора
**после commit**, reload и двойной клик. Все три запроса имеют один key и effect.
API bridge передаёт лишь конечный список
разрешённых путей в owned контейнер; mutation success не подменяется.
Recreate контейнера проверяет те же session, response, row digests и media marker.
Workflow artifacts сохраняют source SHA, image id/revision, redacted state
баланса/тарифа и digests до/после recreate, screenshots и cleanup status.
Секретные fixture sessions остаются только в disposable volume.

Приёмка/слияние требуют совпадающих SHA у source, CI, image revision и receipts,
PASS workflow и независимого review. Это отдельный scoped gate; старый
`e2e-admin-crm-live.mjs` с известной 7-KPI предпосылкой его не заменяет.
Production DB, реальная YooKassa/SMTP и развернутый release этим gate не проверены.
Live provider/mail/payment/refund требуют отдельного owner-authorized
release-ops package; тесты используют temporary state и fake providers.

## Следующие bounded packages

Все gaps одним PR не исправлять. Сохраняется порядок mutation audit:

1. `ADMIN-ROLE-LAST-ADMIN-RACE-001`: две admin sessions и transactional last-admin invariant.
2. `ADMIN-COMMAND-IDEMPOTENCY-001`: tokens/plan contract; принятие только после gates выше.
3. `ADMIN-INVOICE-IDEMPOTENCY-001`: invoice creation и mandatory/conflict-safe key.
4. `ADMIN-LOYALTY-IDEMPOTENCY-001`: bonus/promo/referral command identity.
5. `ADMIN-PAYMENT-MAINTENANCE-001`: fake-provider replay/error/race для simulate,
   reconcile и notification processing; explicit operator authorization и
   redacted receipt до любой live-capable ветки. Durable pre-action intent,
   send-before-ack и whitespace gaps остаются в AM-005/007/008.
