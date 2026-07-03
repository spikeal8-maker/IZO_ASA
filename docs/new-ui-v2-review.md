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

## 2026-07-03 — Draw tab UX structure (Эскиз / Маска / Расширение)

```text
Дата/время: 2026-07-03 ~02:50 (local)
Ветка: feature/new-ui-v2-clean
Коммит или WIP: этот коммит (третий на clean-ветке)
Файлы изменены:
  - frontend/src/newUi.tsx — вкладка «Рисунок»: вместо общего placeholder —
    структура трёх режимов (radiogroup): Эскиз (с бейджем выбранного разрешения
    из общего state формата/разрешения), Маска («Изменить выделенную область
    изображения»), Расширение («Дорисовать края изображения под выбранный
    формат»); выбранный режим подсвечен; зона холста — честный placeholder
    с бейджем «Placeholder — холст в разработке» и кнопкой в текущую версию
  - frontend/src/newUi.css — стили карточек режимов; мобильные (≤1180) —
    компактные строки-карточки вместо трёх больших блоков
  - docs/new-ui-v2-review.md — эта запись
Что сделано: только UX-структура вкладки, без переноса функционала
Что НЕ сделано (осталось placeholder):
  - сам холст (рисование/маска/расширение), загрузка исходника для маски и
    расширения, генерация из этих режимов — отдельная фаза
  - старый WIP из index.css / старого App.tsx НЕ переносился; backend/outpaint
    связка не тронута
Какие тесты запущены:
  - npm run lint → exit 0; npx tsc -b → OK; npx vite build → exit 0
  - rg "X-OneNode-User|onenode_user|demo_user" frontend/src/newUi.tsx → пусто
  - Playwright no-session (повтор сегодня): /api/me-v2 → 401, модалка открылась,
    POST /api/generate → 0 запросов
Результат тестов: все зелёные
Проверено вручную:
  - /new открывается; вкладка «Рисунок» открывается
  - desktop 1440x900: три карточки в ряд, подсветка выбранного, скриншот снят
  - mobile 375x812: компактные строки-карточки, скролл работает, горизонтального
    переполнения нет, скриншот снят
  - переключение режимов: Эскиз (по умолчанию, бейдж 1024×1024) → Маска —
    подсветка переключается
Скриншоты: desktop 1440x900 и mobile 375x812 — свежие, в превью-инструменте
Найденные риски: нет новых; известные (архивная ветка, чужой WIP в working
  tree, дублирование stylePresets) — без изменений
Следующий шаг: аналогичная структура для вкладок «Редактор» и «Лицо», либо
  реализация холста «Эскиз» (потребует решения по konva на /new)
Verdict: UI DRAW TAB CLEANUP DONE
```

## 2026-07-03 — Base layout: единый каркас вкладок /new

```text
Дата/время: 2026-07-03 ~03:30 (local)
Ветка: feature/new-ui-v2-clean
Коммит или WIP: этот коммит (четвёртый на clean-ветке)
Файлы изменены:
  - frontend/src/newUi.tsx — единый каркас вкладок: (1) viewHead (заголовок +
    короткое описание) над рабочей областью Текст → Изо и Изо → Изо;
    (2) у панели предпросмотра появился заголовок «Предпросмотр» со статус-чипом
    единых состояний: Пусто / Генерация… / Готово / Ошибка; (3) Редактор и Лицо
    переведены с голой карточки на каркас как у «Рисунка» (заголовок, описание,
    honest badge «Placeholder — в разработке», карточка с переходом в текущую
    версию); старый helper placeholder() удалён
  - frontend/src/newUi.css — стили n2-view-head, n2-result-head, n2-status-chip;
    сетка result-панели auto/1fr/auto
  - docs/new-ui-v2-review.md — эта запись
Инвентаризация вкладок (до правок):
  - Лента: hero+badge, каркас был; desktop ок / mobile ок
  - Текст → Изо: работает (генерация/стили/шаблоны), но без заголовка вкладки
    и статуса предпросмотра; desktop ок / mobile ок
  - Изо → Изо: работает, те же замечания; desktop ок / mobile ок
  - Редактор: голый placeholder без каркаса — сырой
  - Рисунок: каркас режимов (a4e8d5b) — не трогали функционально
  - Лицо: голый placeholder без каркаса — сырой
Что НЕ сделано:
  - «Рисунок» не развивался: без canvas, без загрузки, без outpaint, без backend
  - функционал вкладок не менялся — только вёрстка/структура
Какие тесты запущены:
  - rg legacy auth по newUi.tsx → пусто
  - npx tsc -b → OK; npx vite build → exit 0
  - npm run lint → FAIL (3 ошибки), все в ЧУЖОМ незакоммиченном WIP App.tsx
    (outpaint: set-state-in-effect 865/2001/2013); with foreign WIP stashed —
    npm run lint → exit 0; мои файлы чистые. App.tsx в этом шаге трогать
    запрещено — ошибки оставлены владельцу WIP
Результат тестов: см. выше
Скриншоты: desktop 1440x900 (Текст → Изо, каркас с «Предпросмотр»+чип) и
  mobile 375x812 (Текст → Изо и Редактор) — свежие, в превью-инструменте
Проверено вручную: /new открывается; заголовки/описания на text/i2i; статус-чип
  «Пусто» при пустой галерее; Редактор/Лицо в новом каркасе; мобильный скролл
  работает; горизонтального переполнения нет
НЕ проверено в этом шаге: auth без сессии (код auth не менялся; проверено ранее
  сегодня Playwright); generate с сессией (код генерации не менялся; проверено
  ранее сегодня); состояния Генерация…/Готово/Ошибка чипа вживую не
  прогонялись (галерея тестового профиля пуста — бекенд-состояние вне scope)
Найденные риски:
  - в working tree появился НОВЫЙ чужой незакоммиченный WIP в App.tsx
    (outpaint, ~174 строки) с 3 lint-ошибками — полный npm run lint красный,
    пока владелец WIP его не починит/закоммитит
  - галерея тестового профиля опустела (вчерашние генерации пропали) — состояние
    backend/БД, вне scope этой ветки; empty-state отработал корректно
Следующий шаг: прогнать статус-чип по живой генерации, когда появится сессия с
  токенами; либо каркас Ленты под будущий API
Verdict: BASE NEW UI LAYOUT STEP DONE
```

## 2026-07-03 — Text/i2i fixes: preview states, style hover, drag-scroll, resolutions

```text
Дата/время: 2026-07-03 ~04:30 (local)
Ветка: feature/new-ui-v2-clean
Коммит или WIP: этот коммит (пятый на clean-ветке)
Файлы изменены: frontend/src/newUi.tsx, frontend/src/newUi.css,
  docs/new-ui-v2-review.md (stylePresets.ts не менялся)
Что сделано:
  1) Preview/result: битый URL результата теперь даёт error-state (onError на
     img, красная карточка «Изображение недоступно»), а не сломанный alt;
     empty/loading/result как раньше; статус-чип получил состояние ошибки.
  2) Hover стиля показывает крупный предпросмотр В ЗОНЕ РЕЗУЛЬТАТА справа
     (временный режим, чип «Предпросмотр стиля»), уход курсора возвращает
     обычное состояние; попап в углу панели удалён.
  3) Лента стилей: drag-scroll мышью по самой ленте (cursor grab/grabbing,
     подавление случайного клика после перетаскивания, user-select: none),
     wheel/trackpad — горизонтально (нативный listener passive:false);
     touch-скролл нативный (pointerType='mouse' only).
  4) Разрешения: полный системный список (7 пресетов: данные из
     resolutionPresets основного UI + средние 1536×1024/1024×1536 — максимум
     генерации); закрытый селект показывает только W×H (overlay), в открытом —
     тип-значок + название + разрешение; формат-кнопки синхронизированы с
     типом выбранного пресета; одна логика для всех вкладок (включая бейдж
     Эскиза в «Рисунке»).
  5) Блок «Разрешение»: селект тонкий (34px), подпись выровнена по верху
     соседних контролов.
  6) Изо → Изо: выбранный стиль виден чипом у промпта («Стиль: … ×», крестик
     снимает); проверено перехватом payload, что стиль (transform-prompt) И
     текст пользователя реально уходят в POST /api/generate — не имитация.
  7) Слайдер «Влияние промпта»: default 75 из state, риска 75 совпадает с
     центром ползунка (calc с учётом ширины thumb), шкала компактнее;
     strength=0.75 подтверждён в payload — реальный параметр backend
     (mode image_to_image), НЕ UI-only.
Что НЕ сделано:
  - реальная i2i-генерация до конца не запускалась: payload проверен
    перехватом fetch с mock-429 (job не создавался, токены не тратились)
  - «Рисунок» не развивался
Какие тесты запущены:
  - rg legacy auth по newUi.tsx → пусто
  - npm run lint → exit 0 (полный; чужой WIP App.tsx владелец обновил,
    его прошлые lint-ошибки исчезли)
  - npx tsc -b → OK; npx vite build → exit 0
Результат тестов: все зелёные
Проверено вручную (dev-превью):
  - drag ленты стилей: scrollLeft 0→160, class dragging, wheel работает,
    случайный выбор стиля подавлен
  - hover стиля → предпросмотр в result area + чип статуса; mouseleave →
    возврат обычного состояния
  - селект разрешений: закрытый «1024×1024», 7 опций с типами
  - i2i: чип «Стиль: Лакшери премиум ×»; payload содержит transform-prompt
    стиля + «сделай волосы рыжими» + strength 0.75, mode image_to_image
  - mobile 375x812: чип, слайдер с риской точно на 75, источник — скриншот
  - desktop 1440x900: hover-превью стиля в правой зоне — скриншот
Скриншоты: desktop 1440x900 и mobile 375x812 — свежие, в превью-инструменте
Найденные риски:
  - state «Готово» чипа может показываться при resultUrl, унаследованном от
    сида пустой галереи прошлых сессий — поведение onError закроет битые URL
  - синтетический mouseleave в автотесте не триггерит React-обработчик
    (артефакт теста, не бага)
Следующий шаг: живой прогон t2i/i2i генерации со статусами чипа при
  доступной сессии с токенами
Verdict: PARTIAL → все 7 пунктов задачи выполнены и проверены; полная живая
  i2i-генерация осталась непрогнанной (payload проверен mock-перехватом)
```

## 2026-07-03 — Feed page MVP (Лента, mock-данные)

```text
Дата/время: 2026-07-03 ~16:00 (local)
Ветка: feature/new-ui-v2-clean (worktree D:/Google Drive/My progact/wt-new-ui,
  dev-сервер http://127.0.0.1:5190; основная hotfix-папка не тронута)
Коммит или WIP: этот коммит (шестой на clean-ветке)
Файлы изменены: frontend/src/newUi.tsx, frontend/src/newUi.css,
  docs/new-ui-v2-review.md. App.tsx НЕ трогался: маршрут /new/feed работает
  через существующий префикс-матч pathName.startsWith('/new/').
Референсы использованы: izo_feed_visual_spec.md (главный spec),
  Лента.html (структура/поведение прототипа), лента_izo_feed_documentation.md
  (продуктовый контекст), компьютерный/телефонный PNG-референсы.
Что сделано:
  - Отдельная страница «Лента» на /new/feed (вкладка Лента ↔ URL синхронизированы
    pushState-ом); свой layout: masonry-сетка карточек + правая detail-панель.
  - Внутренние вкладки: Для вас / Новое / Remix / Челленджи / Подписки —
    переключаются, фильтруют mock-набор, активная подсвечена.
  - Строка активности (онлайн/новые работы/тренд) с явным бейджем «демо-данные».
  - Карточка: изображение (ассеты стилей проекта), метка (Тренд/Открытый
    промпт/Челлендж/Remix-цепочка/Новое), автор+время, название, remix/сохр.,
    кнопки Remix (главная, кислотная) / Сохранить / меню «⋯» (toast-заглушка).
  - Detail-панель (desktop справа, mobile — полноэкранный оверлей с «‹ Назад»):
    большое изображение + метка «Сгенерировано ИИ», автор + Подписаться,
    название, статистика, промпт со статусом (открыт/частично/скрыт) и
    «Показать полностью», параметры (модель/стиль/соотношение/шаги/CFG/seed),
    горизонтальная цепочка ремиксов (кликабельные миниатюры), кнопки
    Remix / Сохранить / Использовать стиль (фиолетовая).
  - Челлендж недели «Москва 2120» (chip «демо», таймер-статика, Участвовать →
    подставляет тему в Текст → Изо + toast).
  - Мобильная нижняя навигация: ИЗО/Лента/Галерея/Челленджи/Профиль.
  - Mock-действия: Сохранить/Подписаться переключают локальный state + toast;
    Remix — префилл промпта поста в «Текст → Изо» + переход + toast (промпт
    скрыт → честный toast); «Использовать стиль» реально применяет стиль из
    stylePresets в генераторе (styleId постов = реальные стили).
  - Состояния: skeleton-карточки при загрузке/смене вкладки, empty-state
    (напр. «Подписки» после отписки/пустой фильтр) с кнопками Сгенерировать/
    Открыть челленджи; not-auth: save/follow/remix без сессии открывают
    настоящую AuthV2Modal (проверено сегодня: превью-контекст оказался без
    сессии, 401).
  - Старый placeholder-блок Ленты и его мёртвый CSS удалены.
Что осталось mock/placeholder:
  - ВСЕ данные ленты захардкожены (10 постов), публикаций/лайков/комментариев/
    начислений нет; таймер челленджа статичен; меню «⋯» — toast; error-state
    сети не реализован (mock не падает) — честно не заявляется.
Что не трогалось: backend, старая страница /, App.tsx, авторизация, тарифы,
  админка, hotfix-ветка/папка, «Рисунок».
Какие тесты запущены (в worktree):
  - rg "X-OneNode-User|onenode_user|demo_user" newUi.tsx → пусто
  - npm run lint → exit 0; npx tsc -b → OK; npx vite build → exit 0
Проверено вручную (http://127.0.0.1:5190, desktop 1440x900 и mobile 375x812):
  - /new открывается; /new/feed открывает Ленту; URL меняется при переключении
  - вкладки ленты фильтруют (Челленджи=3, Подписки=2 карточки)
  - клик карточки обновляет detail («Падший паладин»); на мобиле detail
    открывается оверлеем и закрывается «‹ Назад к ленте»
  - «Показать полностью» раскрывает промпт
  - без сессии save/follow открывают auth-модалку (not-auth hint)
  - нижняя мобильная навигация переключает разделы; горизонтального скролла
    нет; страница скроллится
  - Текст → Изо и Изо → Изо не сломаны (промпт/генерация/источник/слайдер на месте)
  - скриншоты: desktop лента, mobile лента, mobile detail — свежие
НЕ проверено:
  - mock-переключение Сохранить/Подписаться/Remix-префилл ПРИ СЕССИИ — в
    превью-браузере после перезапуска нет живой сессии (me-v2 → 401), логин
    из превью недоступен; код-путь идентичен, но фактическое переключение
    state с сессией сегодня не наблюдалось
  - RU/EN, error-state сети
Риски:
  - Параллельная hotfix-сессия работает в основной папке — коммит сделан из
    изолированного worktree; координация веток по-прежнему обязательна
  - Изображения ленты — превью стилей (могут выглядеть однотипно по жанру);
    для показа владельцу желательно заменить на кураторский набор позже
Следующий шаг: показать владельцу на 5190; после одобрения — кураторские
  mock-изображения и/или первая серверная фаза ленты (отдельное разрешение)
Verdict: FEED PAGE MVP UI DONE (с оговоркой: mock-действия при живой сессии
  не перепроверены — см. НЕ проверено)
```

## 2026-07-03 — Live Feed MVP: реальный backend, публикация из галереи

```text
Дата/время: 2026-07-03 ~19:30 (local)
Ветка: feature/new-ui-v2-clean (worktree wt-new-ui; hotfix-папка не тронута)
Коммит или WIP: этот коммит (седьмой на clean-ветке)
Файлы изменены:
  - backend/main.py — ВПЕРВЫЕ на этой ветке, по явному ТЗ Live Feed:
    additive-таблицы feed_publications (+UNIQUE image_id, upsert) и
    feed_reactions (PK pub+user+kind: like/save/recreate); эндпоинты:
    GET /api/feed?type=new|top (публичное чтение, viewerState по trusted
    cookie-сессии), POST /api/feed/publications (только СВОЁ изображение,
    чужое/несуществующее → 404 + security_event feed_publish_denied),
    POST/DELETE like|save, POST recreate (счётчик «Повторить»),
    GET /api/feed/media/{id}[?thumb=1] — файл только опубликованной работы
    (приватный /api/media не тронут). prompt_visibility: open/partial
    (обрезка 140)/hidden — hidden никогда не покидает сервер.
  - backend/test_feed_v2.py — 6 тестов: 401 без сессии; чужой image → 404 +
    security_event; публичное чтение и невытекание hidden-промпта; toggle
    like/save/recreate с честными счётчиками; feed media для не-владельца;
    идемпотентность init_db с новыми таблицами.
  - frontend/src/App.tsx — route /feed (+ /feed/*) → NewStudio; кнопка
    «Лента»/"Feed" (RU/EN ключи t.ru/t.en) в топбаре старого UI рядом с
    «Галерея» — фиолетово-кислотная (.feed-link, стили в newUi.css, чтобы
    не трогать index.css).
  - frontend/src/newUi.tsx — Лента переведена с mock на живой API: модель
    FeedPublication (контракт backend), загрузка по вкладкам (Для вас→top,
    Новое→new, Популярное→top; Челленджи/Подписки — честные placeholder
    «Скоро»), skeleton/empty/error-state с Retry; карточка: лайк с числом +
    сохранить + главная кнопка «Повторить»; detail: «Сделать похожее»,
    «Взять стиль» (только если style размечен и мапится на stylePresets),
    промпт со статусом видимости, параметры (модель/стиль/соотношение/
    разрешение/seed/режим); публикация из галереи: кнопка «Опубликовать в
    ленту» в просмотре изображения + модалка (название, видимость промпта,
    разрешить «Повторить»); RU/EN словарь FEED_I18N (язык из профиля);
    канонический маршрут Ленты /feed (в /new/feed остаётся синонимом);
    apiUrl(): относительные media-URL корректны при VITE_API_BASE_URL.
    Терминология по ТЗ: «Повторить»/«Сделать похожее»/«Взять стиль» —
    Remix в RU-интерфейсе больше не используется.
  - frontend/src/newUi.css — стили кнопки .feed-link, publish-модалки,
    метки «Ваша работа», error-иконки.
Тесты:
  - rg legacy auth по newUi.tsx → пусто
  - npm run lint → 0; npx tsc -b → OK; npx vite build → 0
  - pytest test_feed_v2.py → 6/6; полный прогон: 447 passed / 19 failed —
    падающие 19 идентичны известному списку на main ДО этой ветки
    (env-зависимые бот-тесты + 4 устаревших legacy-теста; см. запись
    аудита 2026-07-03) — новых падений нет
Проверено вручную (живой стенд: backend worktree на :8001 с ВРЕМЕННОЙ БД
  feed-stand.sqlite3 — продовая onenode.sqlite3 не тронута; vite :5190 с
  VITE_API_BASE_URL на стенд; сессия честная — create_auth_session):
  - старый интерфейс / открывается, все вкладки на месте
  - кнопка «Лента» видна рядом с «Галерея», клик → /feed
  - лента открылась с честным empty-state при пустой БД
  - публикация из галереи через модалку → toast «Опубликовано в ленту» →
    работа в ленте (заголовок, автор, метка «Ваша работа»)
  - повторная публикация того же изображения корректно обновляет (upsert)
  - лайк: ♥ 1 в UI и like_count=1/is_liked_by_me в API; сохранение аналогично
  - «Повторить»: переход в Текст → Изо, промпт подставлен, формат из
    соотношения, счётчик recreate=1, toast; hidden-промпт в detail показан
    как «Промпт скрыт автором» без текста
  - desktop 1440x900 и mobile 375x812 — скриншоты, гориз. скролла нет,
    нижняя навигация на месте
НЕ проверено:
  - EN-вариант интерфейса ленты вживую (словарь есть, профиль стенда ru)
  - «Взять стиль» вживую (у стендовых публикаций style не размечен —
    кнопка честно скрыта; логика та же, что валидированная ранее applyStyleTo)
  - жалоба/скрыть — placeholder не реализован в этом шаге (меню «⋯» из
    mock-версии убрано вместе с mock; вернуть отдельным шагом)
  - деплой не выполнялся; live-backend (8000) не трогался
Риски:
  - backend/main.py теперь отличается от main И от hotfix-ветки — при merge
    hotfix→main→эта ветка будут конфликты в main.py (мои блоки — отдельные
    секции: init_db-вставка + хвост файла, конфликт разрешим)
  - «Для вас» = top (персонализации нет) — задокументировано
  - меню карточки (скрыть/пожаловаться) отсутствует — спек требует его в
    MVP-обвязке модерации, добавить следующим шагом
Следующий шаг: показать владельцу стенд (http://127.0.0.1:5190/feed);
  решить про публикацию на live (нужны эти же миграции на проде)
Verdict: LIVE FEED MVP DONE (стендовая верификация; live-деплой — отдельно)
```

## 2026-07-04 — Стабилизация: вход в Ленту, галерея-публикация, картинки

```text
Дата/время: 2026-07-04 ~01:30 (local)
Ветка: feature/new-ui-v2-clean (worktree wt-new-ui; hotfix-папка не тронута)
Коммит или WIP: этот коммит (восьмой на clean-ветке)
Файлы изменены: frontend/src/App.tsx, frontend/src/newUi.tsx,
  frontend/src/newUi.css, docs/new-ui-v2-review.md
Что сделано:
  1) Галерея не сломана: кнопка «Галерея» старого UI как и раньше →
     setTab('gallery') → рабочий GalleryView (проверено: 3 image-card).
     Мои feed-правки её не меняли.
  2) Кнопка «Лента» рядом с «Галерея»: фиолетово-кислотная .feed-link +
     мягкая пульсация свечения (feedLinkGlow, уважает prefers-reduced-motion);
     RU «Лента» / EN «Feed»; иконка Sparkles. Route: /feed канонический +
     /lenta alias (оба → NewStudio через feedRoute в App.tsx; проверено).
  3) Auth: и старый UI, и Лента используют актуальную AuthV2Modal (email/
     пароль + «Войти через Telegram-бота» + «Войти через MAX»). Старой формы
     нет. Действия Ленты без сессии (лайк/сохранить/повторить/публикация)
     открывают именно её. Проверено: без сессии empty-state «Войдите…» →
     «Войти» → модалка с Telegram и MAX.
  4) Картинки: причина «чёрных блоков» — в ПРОШЛОМ стенде сид писал фейковые
     1×1 прозрачные PNG (прозрачный пиксель на чёрном фоне = чёрный). Реальный
     баг рендера отсутствовал. Меры: (а) стенд пересеян РЕАЛЬНЫМИ файлами из
     backend/media → карточка и detail рендерят настоящее изображение
     (naturalWidth 512, не чёрное); (б) добавлен error-state (onError →
     .nf-img-error «Изображение недоступно») вместо чёрной карточки для
     битых/удалённых файлов; (в) apiUrl() уже держал media-URL корректными
     при VITE_API_BASE_URL. API отдаёт только опубликованные файлы
     (/api/feed/media), приватный /api/media закрыт.
  5) Публикация из РЕАЛЬНОЙ галереи: в модалку просмотра изображения старого
     GalleryView (App.tsx) добавлена кнопка «Опубликовать в ленту» + минимальная
     форма (название, видимость промпта open/partial/hidden, «Разрешить
     Повторить», Опубликовать). Успех → «Опубликовано в ленту» + «Перейти в
     ленту» (→ /feed). Используется чистый feedFetch (cookie-only, без
     X-OneNode-User). Из Ленты «Открыть галерею» и мобильная навигация ведут в
     РЕАЛЬНУЮ галерею через /?open=gallery (App.tsx открывает вкладку и чистит
     параметр). Проверено end-to-end: публикация → toast → работа в /feed.
  6) Empty-state: authed-пусто «Лента пока пустая / Опубликуйте первую работу
     из Галереи» + кнопки «Открыть галерею»/«Создать изображение»; not-authed
     «Войдите, чтобы публиковать работы и сохранять идеи» + «Войти».
     Fake-посты в live не подмешиваются.
  7) RU/EN: Лента/Feed, Повторить/Recreate, Сделать похожее/Make similar,
     Сохранить/Save, Взять стиль/Use style, Опубликовать в ленту/Publish to
     feed, Открыть галерею/Open gallery. «Remix» как главная RU-кнопка не
     используется.
Проверки:
  - rg legacy auth по newUi.tsx → пусто
  - npm run lint → 0; npx tsc -b → OK; npx vite build → 0
  - python -m pytest test_feed_v2.py → 6/6
  - полный backend suite baseline (без изменений): 447 passed / 19 failed —
    те же env-зависимые бот-тесты + 4 устаревших legacy, что и на main
    ДО ветки (зафиксировано в аудите 2026-07-03); новых падений нет
Проверено вручную (стенд backend :8001 временная БД + РЕАЛЬНЫЕ media, vite
  :5190, честная trusted-сессия):
  1. старый / открывается; 2. «Галерея» → рабочая старая галерея (3 карточки),
  не новый UI; 3. «Лента» → /feed; 4. /lenta рендерит ленту; 5. без сессии
  действия → AuthV2Modal с MAX/Telegram; 6. публикация из старой галереи через
  модалку; 7. работа появилась в /feed «Новое»; 8. РЕАЛЬНАЯ картинка в карточке
  и detail (не чёрный блок, не error); 9. лайк ♥1 UI+API; 10. сохранение —
  тот же путь toggleFeedReaction (покрыт test_feed_v2 + like проверен вживую);
  11. «Повторить» → Текст → Изо с подставленным промптом; 12. hidden prompt в
  API = null, текст не утёк; 13. desktop 1440×900 скриншот; 14. mobile 375×812
  скриншот; 15. горизонтального скролла нет.
Что НЕ проверено:
  - реальный вход через MAX/Telegram до конца (бот-딥-link требует настоящих
    токенов/бота; на стенде токены пустые — виден выбор MAX/Telegram, но
    полный бот-цикл не прогонялся)
  - EN-локаль вживую (профиль стенда ru; словарь EN есть)
  - старая галерея на стенде показывает свои thumbnail'ы через relative
    /api/media → 5190 (кросс-origin артефакт стенда; в проде same-origin
    корректно). Публикация и логика галереи при этом работают (JSON с 8001).
  - деплой не выполнялся; live-backend :8000 не трогался (feed-миграции нужно
    выкатить на прод отдельно)
Риски перед деплоем:
  - backend/main.py ветки расходится с main и hotfix — при merge конфликты в
    main.py (мои блоки — отдельные секции init_db + хвост файла)
  - feed-таблицы нужно применить на проде (init_db additive — применятся при
    старте, но нужен бэкап по правилу sqlite-migrations)
  - меню карточки «скрыть/пожаловаться» пока отсутствует — до широкого
    публичного показа желательно (спек требует модерационную обвязку)
  - «Для вас» = top (персонализации нет)
Можно показывать друзьям: ДА — на своём сервере после выката ветки и
  init_db (с бэкапом БД). Локальный публичный показ на проде без выката
  feed-эндпоинтов работать не будет.
Следующий шаг: решение о выкате ветки на прод (или интеграция в hotfix→main),
  затем меню модерации карточки.
Verdict: FEED ACCESS AND PUBLISH FLOW READY (стендовая верификация;
  прод-деплой feed-эндпоинтов — отдельным шагом)
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

