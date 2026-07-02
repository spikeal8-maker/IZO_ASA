# UI 2.0 `/new` Review Log

Append to this file after each `/new` working session. Do not replace older entries
unless correcting a factual mistake.

## Current Baseline

Status: WIP / not accepted.

Known current concerns:

- `/new` work currently exists as local WIP and must be isolated into a feature branch.
- `frontend/src/newUi.tsx` must not contain legacy `X-OneNode-User`, `onenode_user`, or
  `demo_user` auth paths.
- Visual and generation acceptance for `/new` is not complete.

## 2026-07-03 — Branch isolation, docs adoption, legacy-auth removal

```text
Date/time: 2026-07-03 ~01:40 (local)
Branch: feature/new-ui-v2 (created from main; WIP carried over from main working tree)
Commit or WIP: first commit on feature/new-ui-v2 (this entry is part of it)
Files changed:
  - frontend/src/newUi.tsx (apiFetch: cookie-session only; удалены X-OneNode-User /
    onenode_user / demo_user)
  - frontend/src/newUi.css, frontend/src/stylePresets.ts (перенос WIP из main)
  - frontend/src/App.tsx (маршрут /new + импорт общих пресетов; ВНИМАНИЕ: файл также
    содержит более ранний незакоммиченный WIP основного UI — outpaint pan/zoom,
    расширенные resolutionPresets, queueMicrotask-фиксы двух lint-ошибок этого WIP;
    разделить его на отдельный коммит без интерактивного git невозможно — зафиксировано
    здесь как известное смешение, требует внимания при merge)
  - README.md, TEST_PLAN.md, docs/* (карта документации и план /new — созданы
    параллельной doc-сессией, включены в этот коммит, чтобы README не имел битых ссылок)
Documents read: README.md, TEST_PLAN.md, CLAUDE.md, .claude/rules/*,
  docs/public-launch.md, docs/identity-core-plan.md, docs/identity-core-risks.md,
  docs/admin-panel-product-spec.md, docs/collaboration-rules.md,
  docs/new-ui-v2-plan.md, docs/new-ui-v2-review.md
What changed:
  - Создана ветка feature/new-ui-v2; backup: wip_tracked_*.patch +
    wip_untracked_*.tar.gz в %LOCALAPPDATA%/Temp/claude/backups/ (20260703_013156)
  - apiFetch в newUi.tsx переведён на credentials:'include' без legacy-заголовков
What did not change:
  - backend/main.py, backend/test_comfyui_adapter.py, frontend/src/index.css —
    чужой незакоммиченный WIP, оставлен незакоммиченным, не тронут
  - authV2.tsx, тарифы, gallery backend, admin, deploy-скрипты — не тронуты
Tests run:
  - rg "X-OneNode-User|onenode_user|demo_user" frontend/src/newUi.tsx → пусто
  - npx tsc -b → OK
  - npx vite build → OK (warning про chunk >500kB — существующий, не ошибка)
  - dev-превью: / открывается (старый UI), /new открывается,
    GET /api/gallery только с cookie-сессией → 200, console errors → нет
Screenshots: не делались в этой записи; актуальные desktop 1440x900 / mobile 375x812
  сняты в предыдущей рабочей сессии (генерация end-to-end проверена там же)
Security checks: newUi.tsx не содержит legacy auth-паттернов (rg пуст);
  generate без сессии открывает AuthV2Modal (проверено ранее, не перепроверено сегодня)
Known blockers:
  - App.tsx содержит смешанный WIP (см. выше) — при merge в main нужен аккуратный review
  - Галерея тест-профиля почти пуста: «предпросмотр = последняя генерация» проверен
    на одном изображении
Next step: продолжать UI-работу по docs/new-ui-v2-plan.md (Редактор/Рисунок/Лицо,
  шаблоны через API — отдельная фаза с разрешением на backend)
Verdict: DOCS READY
```

Correction (2026-07-03, later): verdict of the entry above is downgraded to
PARTIAL, BLOCKERS REMAIN — App.tsx in that commit mixed /new with unrelated outpaint
WIP, the acceptance checklist was not fully re-run, and screenshots were not fresh.

## 2026-07-03 — Clean branch: App.tsx reduced to /new route hook only

```text
Date/time: 2026-07-03 ~02:10 (local)
Branch: feature/new-ui-v2-clean (создана от main 032c95f)
Commit or WIP: этот коммит (первый на clean-ветке)
Files changed:
  - frontend/src/App.tsx — ТОЛЬКО маршрут /new: +7 строк (import NewStudio,
    const newUiRoute, early return). Outpaint/unrelated WIP НЕ входит — он остался
    в ветке feature/new-ui-v2 и в backup-патчах
    (%LOCALAPPDATA%/Temp/claude/backups/branch_full_20260703_020024.patch,
    uncommitted_20260703_020024.patch)
  - frontend/src/newUi.tsx, newUi.css, stylePresets.ts — перенесены как есть
  - README.md, TEST_PLAN.md, docs/new-ui-v2-plan.md (+ раздел Known Gaps),
    docs/new-ui-v2-review.md
  - docs/documentation-map.md, collaboration-rules.md, auth-current-state.md,
    current-architecture.md, release-checklist.md, bot-work-instructions.md —
    вне разрешённого списка ТЗ; перенесены сознательно: README «Documentation map»
    ссылается на них, без переноса ссылки битые. Чистый markdown, код не трогают.
    Если нужно — легко исключить отдельным коммитом.
What did not change:
  - backend/main.py, backend/test_comfyui_adapter.py, frontend/src/index.css —
    чужой незакоммиченный WIP, остаётся незакоммиченным в working tree
  - authV2.tsx, тарифы, gallery backend, admin, deploy, DB — не тронуты
Tests run (сегодня, на clean-ветке):
  - rg "X-OneNode-User|onenode_user|demo_user" frontend/src/newUi.tsx → пусто
  - rg по newUi.tsx + App.tsx + stylePresets.ts → 6 вхождений ТОЛЬКО в App.tsx,
    все — унаследованный auth-код старой страницы / из main (строки 199-204, 923+),
    не из diff этой ветки; править запрещено без отдельного разрешения
  - npx tsc -b → OK; npx vite build → exit 0 (warning chunk>500kB — существующий)
Проверено вручную (dev-превью, сегодня):
  - / открывается (старый UI), /new открывается
  - generate с cookie-сессией → job создан → прогресс-полоса → результат отображён
    (/api/media/job_20260703_020243_*)
  - галерея открывается (2 изображения), выбор из галереи подставляется в Изо → Изо
  - мобильный скролл работает, горизонтального переполнения нет
  - СВЕЖИЕ скриншоты: desktop 1440x900 и mobile 375x812 (сняты в этой сессии,
    в превью-инструменте; в репозиторий не сохранялись)
НЕ проверено (честно):
  - auth modal без сессии / generate без сессии: в превью-браузере есть живая
    httpOnly-сессия, удалить её из JS нельзя — не перепроверялось сегодня
    (проверялось 2026-07-02 кликом по generate до логина)
  - i2i-генерация end-to-end сегодня не запускалась (только выбор источника);
    t2i end-to-end запускалась и прошла
  - eslint полный прогон на clean-ветке не выполнялся (tsc+build выполнены)
Риски:
  - ветка feature/new-ui-v2 (старая) содержит смешанный App.tsx — НЕ мержить её;
    канонической считать feature/new-ui-v2-clean
  - незакоммиченный чужой WIP (backend/index.css) живёт в working tree обеих веток
  - дублирование данных стилей App.tsx ↔ stylePresets.ts (см. Known Gaps плана)
Next step: владельцу — подтвердить перенос 6 доп. docs (или попросить исключить);
  затем продолжать UI-работу на feature/new-ui-v2-clean
Verdict: PARTIAL, BLOCKERS REMAIN → основные блокеры сняты этим коммитом; остаётся
  неперепроверенным auth-без-сессии и перенос доп. docs ждёт подтверждения владельца
```

## 2026-07-03 — Scope cleanup: extra docs removed, no-session auth verified

```text
Дата/время: 2026-07-03 ~02:30 (local)
Ветка: feature/new-ui-v2-clean
Коммит или WIP: этот коммит (второй на clean-ветке)
Файлы изменены:
  - удалены из ветки: docs/documentation-map.md, collaboration-rules.md,
    auth-current-state.md, current-architecture.md, release-checklist.md,
    bot-work-instructions.md (вне scope /new; упоминания в старых записях этого
    лога — история, не навигация)
  - README.md — карта документации сокращена до разрешённого списка
    (public-launch, identity-core-plan, identity-core-risks,
    admin-panel-product-spec, new-ui-v2-plan, new-ui-v2-review); битых ссылок нет
  - docs/new-ui-v2-review.md — эта запись
Что сделано:
  - Проверка auth БЕЗ сессии на /new (Playwright, чистый context без cookies):
    GET /api/me-v2 → 401; клик «Сгенерировать» открыл auth-модалку;
    запросов POST /api/generate отправлено 0 (job не создаётся)
  - npm run lint → exit 0; npx tsc -b → OK; npx vite build → exit 0
  - / открывается (старый UI), /new открывается (после удаления docs код не менялся)
Что НЕ сделано:
  - i2i-генерация end-to-end сегодня не запускалась (t2i end-to-end — прошла ранее
    сегодня, см. предыдущую запись)
  - скриншоты после этого коммита не переснимались (код /new не менялся;
    свежие скриншоты 1440x900 и 375x812 — из предыдущей записи этой же сессии)
Какие тесты запущены: lint, tsc -b, vite build, Playwright no-session check,
  rg legacy-auth (пусто в newUi.tsx)
Результат тестов: все зелёные (см. выше)
Скриншоты: desktop 1440x900 и mobile 375x812 — свежие от 2026-07-03 (пред. запись);
  после удаления markdown-доков не переснимались
Найденные риски:
  - удалённые 6 доков существуют только в ветке feature/new-ui-v2 (архив) и в
    backup-патчах; если они нужны проекту — вернуть отдельной doc-веткой
  - чужой WIP (backend/main.py, test_comfyui_adapter.py, index.css) по-прежнему
    незакоммичен в working tree
Следующий шаг: продолжать UI-работу на feature/new-ui-v2-clean по плану
Verdict: DOCS READY, UI WORK CAN CONTINUE
```

## Entry Template

```text
Date/time:
Branch:
Commit or WIP:
Files changed:
Documents read:
What changed:
What did not change:
Tests run:
Screenshots:
Security checks:
Known blockers:
Next step:
Verdict: DOCS READY / PARTIAL / FAIL
```

