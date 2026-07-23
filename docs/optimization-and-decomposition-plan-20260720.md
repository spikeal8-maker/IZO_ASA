# IZO_ASA — исполняемый план оптимизации и декомпозиции

**Дата:** 2026-07-20  
**Базовый Git SHA:** `8922e77ea03cd725c88e16ac0ac6cb88d3673e27`  
**Назначение:** единая очередь работ для AI-агентов и разработчиков  
**Важно:** этот документ не разрешает deploy, restart, переключение webhook, реальные платежи, письма или изменение production data.

---

# 1. Решение владельца

Не выбирать между «укрепить систему» и «уменьшить файлы».

Правильное правило:

> Каждый пакет решает одну реальную проблему и одновременно уменьшает связанный монолит. Backend-пакет не должен добавлять business logic в `backend/main.py`. Frontend-пакет должен уменьшать `newUi.tsx` или общий CSS без одновременного redesign.

Нельзя делать один большой рефакторинг всего проекта. Нельзя годами откладывать декомпозицию до завершения всех operational-задач.

---

# 2. Текущее подтверждённое состояние

Завершены:

- `GOV-001` — единые правила агентов;
- `REL-LOCK-001` — single-flight release/Full verification;
- `SEC-DIAG-001` — безопасные публичные status endpoints;
- `BOT-TG-001` — polling health Telegram/MAX;
- `BACKUP-NET-001` — backup route и restore rehearsal.

Решение владельца:

- `MAIL-OPS-001` — `DEFERRED_BY_OWNER`, сейчас не выполнять.

Не завершено:

- локально начат `AUTH-LEGACY-001`, но полного проверенного commit нет;
- его считать `UNVERIFIED LOCAL WIP` до выполнения `PLAN-WIP-001`.

Крупные файлы:

- `backend/main.py` — около 20 257 строк;
- `frontend/src/newUi.tsx` — около 4 378 строк;
- `frontend/src/newStudioV3.css` — около 5 875 строк;
- `frontend/src/newUi.css` — около 3 096 строк;
- `frontend/src/videoStudio.css` — около 2 596 строк;
- `frontend/src/LegacyApp.tsx` — около 3 600 строк, frozen compatibility.

---

# 3. Обязательные правила каждого пакета

До изменения кода агент обязан написать:

```text
ID:
Цель:
Owner:
Файлы в scope:
Файлы вне scope:
Текущее поведение:
Acceptance:
Targeted tests:
Rollback boundary:
Deployment required: yes/no
```

Ограничения:

1. Один пакет — одна проблема.
2. Обычно 1–8 production-файлов и 1–5 test-файлов.
3. Если scope превышает 12 production-файлов — остановиться и разделить задачу.
4. Не удалять, не reset и не stash чужой WIP автоматически.
5. Не повышать architecture/file budgets ради прохождения gate.
6. Не сжимать комментарии и строки ради формального уменьшения файла.
7. Generated maps обновляются в том же code-bearing commit.
8. Production DB/media/secrets/providers не используются в тестах.
9. Deploy/restart выполняется только по отдельному явному разрешению владельца.
10. После extraction исходный монолит и его budget должны реально уменьшиться.

---

# 4. Точная очередь работ

| № | Пакет | Результат | Deploy |
|---:|---|---|---:|
| 0 | `PLAN-WIP-001` | Сохранить и разобрать текущий AUTH-WIP | нет |
| 1 | `PLAN-SYNC-001` | Привести план и статусы в соответствие с фактом | нет |
| 2 | `CTX-001` | Короткие context docs и frontend map | нет |
| 3 | `AUTH-LEGACY-001A` | Route matrix и characterization tests | нет |
| 4 | `AUTH-LEGACY-001B` | Отдельная CSRF boundary | отдельно после Full |
| 5 | `AUTH-LEGACY-001C` | Trusted dependencies для protected routes | отдельно после Full |
| 6 | `AUTH-LEGACY-001D` | Legacy protected consumers = 0 | отдельно после Full |
| 7 | `ARCH-BE-BOTS-001` | Bot routes/workers вынесены из `main.py` | отдельно |
| 8 | `ARCH-FE-STUDIO-001A..D` | `newUi.tsx` становится shell | отдельно |
| 9 | `ARCH-FE-CSS-001` | CSS разделён без redesign | отдельно |
| 10 | `ARCH-FE-VIDEO-001` | Video Studio разделён | отдельно |
| 11 | `OBS-001A` | Метрики и health для следующих пакетов | отдельно |
| 12 | `DB-MIG-002` | Первая настоящая migration v2 | maintenance/release |
| 13 | `WORK-001` | Leases, recovery и watchdogs | отдельно |
| 14 | `OPS-001` | Windows service supervision и reboot recovery | операторский |
| 15 | `REL-002` | Immutable backend A/B и drain | операторский |
| 16 | `BILL-001` | Единая финансовая transaction boundary | отдельно |
| 17 | `ARCH-BE-D/E/F/G` | Поэтапное уменьшение остальных backend-доменов | отдельно |
| 18 | `PORT-001` | Воспроизводимый новый Windows host | maintenance |
| 19 | `SCALE-001` | Linux/PostgreSQL/external queue только по trigger | не сейчас |

Следующий пакет всегда берётся только после завершения предыдущего либо после явного решения владельца об изменении очереди.

---

# 5. Первый пакет: PLAN-WIP-001

До завершения этого пакета запрещено продолжать AUTH-код.

## Действия

В канонической папке выполнить:

```powershell
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git worktree list
git diff --stat
git diff
```

Затем:

1. Перечислить все tracked и untracked изменения.
2. Определить owner текущего WIP.
3. Ничего не удалять.
4. Не выполнять `reset --hard`.
5. Не делать автоматический stash.
6. Разделить diff на категории:
   - characterization/tests;
   - CSRF;
   - trusted identity;
   - legacy cleanup;
   - docs/maps.
7. Указать, что завершено и что не завершено.
8. Указать, какие тесты уже запускались.
9. Подготовить безопасный handoff.
10. Не делать commit, push, deploy или restart.

## Acceptance

- ни одна строка WIP не потеряна;
- известны owner, файлы и назначение изменений;
- WIP разделён на будущие пакеты;
- production не затронут;
- незавершённый AUTH не попал в `main`.

---

# 6. PLAN-SYNC-001 — короткий статус вместо огромного журнала

Создать:

```text
docs/current-status.md
```

Максимум 150 строк. Содержит только:

- current main SHA;
- current live release;
- active package;
- next package;
- deferred packages;
- blockers;
- known local WIP;
- release owner;
- последние verified gates.

В master plan:

- `MAIL-OPS-001` отметить `DEFERRED_BY_OWNER`;
- удалить устаревший next step;
- не складывать туда длинные PID, logs и повторные deployment reports;
- подробное evidence вынести в `docs/checkpoints/<PACKAGE>.md`.

---

# 7. CTX-001 — перестать читать весь проект

Создать только три коротких документа:

```text
docs/context/backend-auth-bots.md
docs/context/frontend-studio.md
docs/context/video-gallery-feed.md
```

Каждый 100–250 строк и содержит:

- назначение подсистемы;
- entrypoints;
- какие source-файлы читать;
- какие tests читать;
- API/state contracts;
- что запрещено менять;
- какие крупные файлы не нужно читать целиком;
- known risks.

Создать frontend map:

```text
tools/generate_frontend_map.mjs
docs/generated/frontend-map.json
docs/generated/frontend-map.md
```

Карта показывает:

```text
route → component → hooks/state → API → CSS → tests
```

Команда `node tools/generate_frontend_map.mjs --check` должна входить в Quick/CI.

Правило AI:

```text
AGENTS.md
+ docs/current-status.md
+ один context doc
+ generated map fragment
+ 3–8 source files
+ relevant tests
```

Агент не читает целиком `main.py`, `newUi.tsx` или общий CSS без доказанной необходимости.

---

# 8. AUTH разбивается на четыре пакета

## AUTH-LEGACY-001A — только characterization

Не менять behavior.

Сделать:

- route matrix: public/optional/session/user/admin/webhook;
- negative tests для `X-OneNode-User`;
- negative tests для изменяемой legacy cookie;
- unsigned Telegram/MAX tests;
- non-admin admin-route tests;
- список legacy consumers;
- CSRF mutation matrix.

Не менять `request_user_id`, middleware или cookies.

## AUTH-LEGACY-001B — CSRF

Целевая граница:

```text
backend/app/security/csrf.py
```

`main.py` содержит только wiring.

Тесты: same-origin, foreign/missing origin, localhost, production HTTPS, Telegram/MAX auth, webhook exclusions, admin mutations. Focused suite 5×.

## AUTH-LEGACY-001C — trusted dependencies

Целевая граница:

```text
backend/app/security/request_identity.py
backend/app/api/dependencies/auth.py
```

Protected routes используют trusted session. Legacy header/cookie не дают доступ к protected state.

## AUTH-LEGACY-001D — удалить legacy consumers

Удалять по одному consumer и сразу убирать allowlist entry.

Acceptance:

```text
legacy protected-route consumers = 0
```

---

# 9. ARCH-BE-BOTS-001 — bots вне main.py

Не создавать десятки файлов.

Использовать существующие:

```text
backend/app/integrations/telegram.py
backend/app/integrations/max_client.py
backend/app/services/bot_admin.py
backend/app/services/polling_health.py
backend/app/services/platform_status.py
```

Добавить только:

```text
backend/app/api/routers/bots_public.py
backend/app/api/routers/bots_admin.py
backend/app/services/bot_workers.py
backend/app/lifespan/worker_registry.py
```

Ответственность:

- `bots_public.py` — только product-safe status;
- `bots_admin.py` — trusted-admin config/token/verify/webhook/audit;
- `bot_workers.py` — polling, cursor, health, backoff, recovery, graceful stop;
- `worker_registry.py` — registration generation/Telegram/MAX/feed-video.

Transport adapters отвечают только за HTTP/provider errors/retry-after/probe.

Acceptance:

- bot routes и lifecycle удалены из `main.py`;
- inventory owner больше не `backend.main`;
- polling/webhook не включаются одновременно;
- cursor не сбрасывается автоматически;
- focused suite 5×;
- `main.py` и budget уменьшены.

---

# 10. ARCH-FE-STUDIO-001 — уменьшить newUi.tsx без сотен файлов

Первая структура — максимум восемь основных файлов:

```text
frontend/src/studio/StudioPage.tsx
frontend/src/studio/studioTypes.ts
frontend/src/studio/studioApi.ts
frontend/src/studio/studioState.ts
frontend/src/studio/StudioLayout.tsx
frontend/src/studio/StudioModes.tsx
frontend/src/studio/StudioPreview.tsx
frontend/src/studio/studio.css
```

Волны:

1. `001A` — types/API/pure helpers, цель `newUi.tsx` примерно ≤ 3300 строк;
2. `001B` — state, цель примерно ≤ 2500 строк;
3. `001C` — layout/preview/history, цель примерно ≤ 1800 строк;
4. `001D` — modes, финальный shell примерно ≤ 800 строк.

Если `StudioModes.tsx` больше 800–1000 строк, только тогда разделить Text/Image/Assembly/Editor.

Нельзя одновременно менять DOM, дизайн и class names.

Каждая волна проверяет:

- generation;
- upload/picker;
- assembly slots;
- preview/result/history;
- 1440×900, 1920×1080, 390×844, 430×932;
- отсутствие horizontal overflow;
- lint/build/Playwright/visual evidence.

---

# 11. ARCH-FE-CSS-001 — разделить CSS без поломки вёрстки

Первая волна — только физический перенос с сохранением selector text и порядка каскада.

```text
frontend/src/studio/styles/tokens.css
frontend/src/studio/styles/base-controls.css
frontend/src/studio/styles/layout.css
frontend/src/studio/styles/prompt.css
frontend/src/studio/styles/preview.css
frontend/src/studio/styles/history.css
frontend/src/studio/styles/assembly.css
frontend/src/studio/styles/editor.css
```

Запрещено одновременно:

- переименовывать классы;
- менять DOM;
- делать redesign;
- переводить всё на CSS Modules;
- менять breakpoints.

CSS Modules — только для новых или уже изолированных компонентов.

Acceptance: screenshot/computed-style comparison, desktop/mobile parity, static `/feed` и `/gallery` проверяются отдельно.

---

# 12. ARCH-FE-VIDEO-001 — Video Studio

Первая структура:

```text
frontend/src/video/VideoStudioPage.tsx
frontend/src/video/videoTypes.ts
frontend/src/video/videoApi.ts
frontend/src/video/videoState.ts
frontend/src/video/VideoInputs.tsx
frontend/src/video/VideoPreview.tsx
frontend/src/video/video.css
```

Один источник состояния для active job, history selection, progress, result, error, estimate и uploaded assets.

Проверить все режимы:

- text-to-video;
- image-to-video;
- first/last frame;
- references-to-video.

Не создавать второй polling loop.

---

# 13. Правильный порядок operational P1

```text
OBS-001A
→ DB-MIG-002
→ WORK-001
→ OPS-001
→ REL-002
→ BILL-001
```

Причина: immutable backend A/B нельзя надёжно доказать до leases, recovery, watchdogs и graceful worker shutdown.

- `OBS-001A` — queue depth/age, last success/error, worker owner, DB/WAL/free space, release/restart metrics;
- `DB-MIG-002` — настоящая migration v2;
- `WORK-001` — atomic claim, lease, attempts, idempotency, dead-letter, watchdog, graceful shutdown;
- `OPS-001` — Windows services, restart backoff, crash/reboot rehearsal;
- `REL-002` — immutable candidate backend, switch, drain, rollback;
- `BILL-001` — invoice/token/refund/ledger в одной transaction.

---

# 14. Долгосрочное уменьшение backend

После критических пакетов по одному домену:

1. gallery/media;
2. feed image/video;
3. generation/models/integrations;
4. mail — только после возврата из `DEFERRED_BY_OWNER`;
5. identity/billing последними после characterization.

Долгосрочная цель:

```text
backend/main.py ≈ composition root <= 2000 строк
```

Он содержит app creation, lifespan, dependency wiring, router includes и временные compatibility adapters.

---

# 15. Stop conditions

Агент обязан остановиться, если:

- найден чужой или неясный WIP;
- уже идёт Full/release;
- scope вырос более 12 production-файлов;
- нужно менять production DB/media;
- нужно отправить реальное письмо, платёж, refund или bot action;
- нужно переключить webhook/polling;
- нужно менять VPS/FRP/DNS;
- нужна destructive migration;
- нужно повысить architecture budget;
- visual regression нельзя объяснить;
- tests проходят только после ослабления assertions;
- deployment не разрешён владельцем.

---

# 16. Definition of Done

Пакет завершён, только если:

- preflight и owner зафиксированы;
- scope/acceptance написаны до кода;
- чужой WIP не затронут;
- characterization/negative/race tests существуют;
- extracted responsibility удалена из монолита;
- line/symbol budget снижен до факта;
- maps обновлены в том же commit;
- targeted tests и Quick зелёные;
- UI имеет desktop/mobile evidence;
- Full выполнен один раз для release candidate;
- secret scan и diff review выполнены;
- commit/push подтверждены;
- deploy отдельно разрешён;
- exact SHA/release ID и статус названы честно.

---

# 17. Команда для бота прямо сейчас

Передать боту дословно:

```text
Прочитай AGENTS.md и docs/optimization-and-decomposition-plan-20260720.md.

Работай только по пакетам этого плана. Сейчас выполни только PLAN-WIP-001.

Не продолжай AUTH-код. Не изменяй приложение. Не делай commit, push, deploy,
restart, webhook switch или real provider action.

1. Выполни canonical preflight и покажи:
   git status --short --branch
   git rev-parse HEAD
   git rev-parse origin/main
   git worktree list
   git diff --stat
   git diff

2. Найди весь текущий AUTH-WIP.
3. Ничего не удаляй, не reset и не stash автоматически.
4. Раздели diff на:
   - characterization/tests;
   - CSRF;
   - trusted identity;
   - legacy cleanup;
   - docs/maps.
5. Укажи owner WIP, назначение каждого файла, что закончено и что не закончено.
6. Укажи уже выполненные tests.
7. Подготовь handoff и остановись.

Не переходи к следующему пакету без моего подтверждения.
```
## ADMIN-NOTIFY-SOCIAL-001 — центр событий и durable social outbox

Статус 2026-07-24: `CODE COMPLETE · VERIFIED (CI) · NOT DEPLOYED`.

Scope первого безопасного пакета:

- additive migration v2 создаёт `admin_notifications` и
  `social_delivery_outbox`;
- ежедневный lifecycle OpenRouter создаёт дедуплицированную сводку только при
  реальных изменениях каталога;
- trusted-admin API поддерживает чтение, mark-all/selected read и настройки
  каналов с audit log;
- `/admin/notifications` показывает журнал и настройки;
- `/admin/social` хранит подготовительную конфигурацию Telegram/VK/Instagram/OK
  и показывает durable очередь;
- опубликованное изображение или полностью подготовленное видео создаёт не
  более одного задания на сеть;
- внешняя доставка и `masterEnabled` принудительно выключены, пока отдельный
  provider package не добавит DPAPI credentials, retry worker и operator test.

Acceptance:

- migration idempotent и отклоняет неизвестную более новую схему;
- notification/social dedupe подтверждён тестами;
- `backend/main.py` не превышает budget 19 517 строк;
- frontend production build и архитектурные карты зелёные;
- реальные сообщения и публикации не отправляются в тестах.

Evidence: focused backend `116 passed`; social outbox idempotency `5/5`;
`VERIFY_OK mode=CI`, full suite `1668 passed`; frontend lint/build,
release-identity, origin-isolation и studio-resilience green.
