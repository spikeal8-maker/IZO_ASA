---
status: active
canonical: false
record_role: task-contract
package: RELEASE-FINISH-002-FINAL
package_mode: implementation-and-existing-project-activation
base_sha: 3441a4d17ec9503bc5f617b6ffb2a439e979dd08
branch: agent/release-finish-002-final
risk_class: high-assurance
authorized: owner RELEASE-FINISH-002 request
deployment: existing izo-asa-linux-test-a only
verified: 2026-11-07
---

# RELEASE-FINISH-002 — закрытая Linux beta

## Goal and user outcome

Завершить действующий проект 1Panel с реальной генерацией Flux Klein 4B,
прежними аккаунтами, неизменными историческими балансами и защитой от повторов.
Исходный снимок, публичный izo.alikinas.ru и чужие проекты не изменяются.

## Implementation and ownership

Единый проверяемый контракт: `tasks/RELEASE-FINISH-002-FINAL.toml`.
Предыдущие владельцы штатно завершили пакеты; чужой активный scope не переписан.
Закрытые dependency commits сохранены в Git и исходных worktree. Их новые
task-файлы консолидированы в этот пакет, чтобы CI проверял один контракт.

| Dependency | Reviewed source commit |
| --- | --- |
| Durable admission | 90dc0135067532223361e0c8df47cb670f5f72c7 |
| Client retry identity | f22cecd4b99f19615eb5fe67dcd22b816a1a64e1 |
| Historical boundary | 3c2a850dbd32281670ece5bf5215240e6d1a83b9 |
| Historical workers | 0b4c385773026811997f5462dc31ab3d38f634ad |
| Owned lifespan | e2d4f3b0bbb68372e3c26a9ab048bf790bae3eba |
| Cleanup ownership | 77e67557249b82e81b1573e0134849f88ba722cb |
| Schema-aware packaging | 1e8c4f13f1c4fa36618311e36966b269350d1b76 |
| Historical 1Panel profile | 0f25172b18b47c5c4cd7dd90dc57a950f5970d72 |

Admission связывает trusted user, Idempotency-Key, нормализованный SHA256,
задание и учёт одной SQLite-транзакцией. Повтор возвращает сохранённый результат;
другое содержимое получает 409. Отправка начинается только после commit.
Возврат сериализован и имеет долговечную уникальную квитанцию; сбой откатывает
весь возврат. Recovery освобождает или расходует новые trial reservations.

Схема 8 добавляет таблицы операций и неизменяемую границу истории. Sealing —
явное offline-действие на новом клоне; startup никогда не создаёт границу сам.
Старые jobs/outbox/payments/publications/recovery блокируются до побочных эффектов.
Чтение кабинета не выдаёт просроченные гранты и не синхронизирует старый каталог.
Просмотр старого изображения не восстанавливает отсутствующие sources из job settings;
новые изображения прежнего пользователя сохраняют штатное восстановление источников.
В режиме IZO_CLOSED_BETA новые публичные аккаунты запрещены; прежний password
login и проверенные существующие provider identities сохраняют прежнюю логику.

## Verification and acceptance boundary

Реальная UI-генерация: job `job_20261107_215056_1c5622`, image `img_fb4e8f4ec1ec`,
ComfyUI `acdb22d3-7b21-499e-a39e-97b374c5614f`; модель
`flux-2-klein-4b-fp8.safetensors`. Сохранённые RGB-пиксели совпали с GPU-файлом.
Это отдельный тестовый аккаунт, не доказательство входа прежнего пользователя.

Новый клон снимка `20261104T190706.420010Z` подтвердил исходные количества:
60 users, 1952 images, 60 videos, 1854 jobs, 2939 token_ledger.
Исходные DB и media повторно сверены без изменений.
Проверки собранного приложения: 136 focused PASS; дополнительный auth/HTTP
прогон 47 PASS; schema/bridge 663 PASS; policy/recovery 90 PASS без warnings.
Конкурентные HTTP группы 2/5/10 покрывают один job/charge/dispatch и один refund.
Trial, commit-before-enqueue, stale outbox claim и повторный lifespan покрыты.
Gallery source-repair regression и смежные storage/API проверки: 14 PASS без warnings.
Actual-app rehearsal на новом клоне: два lifespan, старые строки/медиа неизменны,
transport attempts=0; исходные 60/1952/60/1854/2939 сохранены.

Test-health policy требует warnings=0 и cleanup exceptions=0. Старые 8/1
сохранены как previousBaseline; срок review не продлён, checks не отключены.
Закрытие #162/#165 требует обязательного exact-head Windows CI, включая DPAPI.
Admin mutation audit сохраняет прежние gap/partial статусы; fingerprints
затронутых handlers обновляются после review, без заявления о полном remediation.

## Runtime evidence and rollback

Приёмку завершает actual-app rehearsal на новом историческом клоне, native
1Panel update, сохранность после restart, внешний HTTPS и личный вход владельца
с прежним паролем. Синтетическая сессия не заменяет password acceptance.
Разрешён только существующий проект, точный namespace и приватный 4B proxy.
Глобальные операции GPU, старые отправки и реальные платежи запрещены.
Старые Compose/image/data pins и исходные копии остаются границей отката.
