# IZO_ASA Phone — обязательный план мобильной платформы

**Дата решения владельца:** 2026-08-24

**Статус:** `APPROVED SPECIFICATION; IMPLEMENTATION IN PROGRESS`

**Область:** `/phone`, общие Phone API и интеграция мобильных изображений,
видео, чата, звука и 3D в действующий продукт IZO_ASA.

**Приоритет правил:** `AGENTS.md` выше этого документа. Глобальный инженерный
план остаётся выше отдельных feature-пакетов. Этот документ является источником
истины для продуктового и технического поведения мобильной платформы.

Документ не разрешает deploy, restart, изменение production DB/media/secrets,
реальный платный provider-вызов, отправку публикаций или изменение AdGuard VPN,
FRP, VPS, DNS и домена. Каждое такое действие требует отдельного разрешения и
собственного evidence.

---

## 1. Решение владельца и конечный результат

`/phone` становится полноценной мобильной частью основного проекта, а не
отдельным демонстрационным сайтом. Визуальный язык согласованного телефонного
шаблона сохраняется, но демонстрационные элементы заменяются общими реальными
данными и функциями IZO_ASA.

Мобильная платформа включает пять равноправных рабочих областей:

1. изображения;
2. видео;
3. чат;
4. звук;
5. 3D-моделирование.

Каждая область использует одну авторизацию, один каталог моделей, одну систему
заданий, одну галерею, один финансовый ledger, общие уведомления, историю,
публикацию и административную аналитику.

Целевой результат считается достигнутым только тогда, когда пользователь может
начать операцию на телефоне, закрыть или обновить страницу, вернуться, получить
проверяемый результат, увидеть правильное списание и найти материал в своей
истории/галерее.

---

## 2. Подтверждённая исходная точка

Исходная точка ниже является timestamped evidence, а не вечным описанием
production. Перед каждым пакетом она проверяется заново.

На 2026-08-24:

- `/phone` открывает React-компонент, который встраивает отдельный
  `phone-prototype.html` через iframe;
- значительная часть телефонного интерфейса находится в `phone-runtime.js`, а
  не в feature-компонентах основного React-приложения;
- серверная логика телефонного чата существует, но активный release также
  содержит временный loopback sidecar;
- отдельных полноценных маршрутов `/phone/image`, `/phone/video`,
  `/phone/chat`, `/phone/audio`, `/phone/3d` нет;
- реальной 3D-генерации, 3D-provider adapter, 3D-viewer, 3D asset contract и
  3D-биллинга в проекте нет;
- кандидат `5062e1c166427cae9239dc3e3c1fb614f86c684a` совпадает с canonical
  `main`, но его promotion 2026-08-24 был откатан после того, как `IZOBackend`
  не достиг `Running` за 90 секунд;
- предыдущий release после отката остался доступен, но это не закрывает причину
  отказа нового backend.

Перед кодом пакет обязан обновить эти факты: `HEAD`, `origin/main`, active
release, promotion receipt, health, service owner и наличие параллельного
publisher/Full verification.

---

## 3. Неизменяемые архитектурные решения

### 3.1. Один продукт, без второго приложения

- Phone UI реализуется внутри текущего React/Vite-приложения.
- Iframe, отдельный runtime HTML и sidecar являются временными переходными
  механизмами и не расширяются новой бизнес-логикой.
- Удалять их можно только после characterization tests и подтверждённого
  функционального паритета.
- Desktop UI не переписывается ради Phone UI. Общая логика извлекается в
  shared modules, а представления остаются адаптированными к своим экранам.

### 3.2. Модульный монолит

- Новая backend-логика располагается в `backend/app/*`.
- `backend/main.py` остаётся composition/compatibility shell.
- Не создаются отдельные микросервисы для каждой вкладки.
- SQLite остаётся источником долговечного состояния до срабатывания
  измеряемого scale trigger из глобального плана.

### 3.3. Сервер является источником истины

Браузер не является источником истины для:

- незавершённых заданий;
- финансового состояния;
- истории чатов;
- provider task id;
- публикаций;
- приватных медиа;
- реального статуса результата.

Локальное состояние браузера используется только для безопасных черновиков и
предпочтений интерфейса.

### 3.4. Provider-neutral интеграции

Внешние и локальные реализации подключаются через адаптеры. Пользовательский
API и UI не содержат обязательной зависимости от названия конкретного
провайдера. Технические идентификаторы видны только администратору.

### 3.5. Реальное качество вместо button-smoke

Нажатие кнопки и HTTP 200 не являются приёмкой. Для каждого режима проверяется
содержательный результат, формат, воспроизводимость, владение, история,
списание и восстановление после прерывания.

---

## 4. Целевая схема

```text
Phone React App Shell
  ├─ /phone/image
  ├─ /phone/video
  ├─ /phone/chat
  ├─ /phone/audio
  └─ /phone/3d
          │
          ▼
Phone API v1 / shared application services
  ├─ trusted session and ownership
  ├─ model capability catalog
  ├─ durable generation jobs and job events
  ├─ media assets and derivatives
  ├─ gallery/history/feed/publication adapters
  ├─ token reservation/settlement/refund
  └─ provider usage and admin analytics
          │
          ▼
ComfyUI / OpenRouter / Ollama / video providers / audio providers / 3D providers
```

Планируемый namespace новых контрактов — `/api/phone/v1`. Существующие API не
дублируются автоматически: Phone facade вызывает существующий domain service
или получает тонкий совместимый adapter. Публичная версия API меняется только
через документированную совместимость.

---

## 5. Общий мобильный App Shell

App Shell отвечает только за:

- trusted session и состояние входа;
- общую шапку, баланс и профиль;
- маршрутизацию и возврат назад;
- нижнюю навигацию и центральное меню;
- notification host;
- modal/drawer/fullscreen host;
- загрузку и выбор материалов;
- восстановление активных заданий;
- общую обработку offline/reconnect;
- feature flags.

Обязательные маршруты:

| Маршрут | Назначение |
|---|---|
| `/phone` | безопасный redirect на последний или стартовый раздел |
| `/phone/image` | создание и изменение изображений |
| `/phone/video` | создание и просмотр видео |
| `/phone/chat` | сохраняемые диалоги и инструменты |
| `/phone/audio` | речь, распознавание и звуковые результаты |
| `/phone/3d` | генерация и просмотр 3D |

3D не втискивается шестой мелкой кнопкой в нижнюю панель. До подтверждения
частоты использования он доступен как полноценный пункт центрального меню,
прямой маршрут и карточка создания. Решение о постоянной кнопке принимается по
телеметрии и пользовательской проверке.

Каждый маршрут поддерживает прямое открытие и refresh без сброса в корень.

---

## 6. Общие серверные контракты

### 6.1. Capability-каталог моделей

UI получает безопасное описание модели:

- публичное название и короткое русское назначение;
- modality и поддерживаемые операции;
- форматы/соотношения сторон/разрешения/длительности;
- разрешённые входные материалы;
- поддержку звука, прозрачности, маски, face reference, 3D texture/refine;
- ограничения размера;
- тип и прогноз списываемых токенов;
- доступность по тарифу и feature flag.

Техническое имя, provider route, checkpoint, workflow и себестоимость не
передаются обычному пользователю.

### 6.2. Долговечные задания

Единый минимальный state machine:

```text
created -> queued -> running -> processing -> completed
                     ├────────> failed
                     └────────> cancelled
```

Переходы идемпотентны. Каждый job хранит owner, modality, operation, model,
входы, provider id, этапы, timestamps, результат, безопасную ошибку,
финансовые ссылки и correlation id.

In-process очередь только будит worker. Источник истины — SQLite. Lease,
watchdog, retry и restart recovery соответствуют глобальному `WORK-001`.

Клиент получает прогресс через SSE; bounded polling является fallback. Refresh,
reconnect и повторный вход не создают второе задание.

### 6.3. Медиа

Общий asset contract различает:

- пользовательский оригинал;
- приватный результат;
- оптимизированный derivative;
- preview/poster/thumbnail;
- опубликованную копию ленты;
- provider temporary file.

Каждый приватный read проверяет owner. Удаление из пользовательской галереи не
удаляет опубликованную копию ленты. Retention, избранное и автоочистка
используют существующие продуктовые правила и получают regression tests для
каждой новой modality.

### 6.4. Финансовый цикл

```text
quote -> reserve -> run -> settle actual usage
                       └-> fail/cancel -> refund unused reservation
```

Одна операция не может списаться дважды. Сохраняются:

- дневные и основные пользовательские токены раздельно;
- provider currency и фактическая стоимость;
- локальная энергия, когда измерение достоверно;
- цена для пользователя;
- возврат;
- маржа;
- причина ручной корректировки.

Финансовая транзакция реализуется через общую boundary из `BILL-001`, а не
локальным SQL маршрута.

---

## 7. Контракт раздела «Чат»

Обязательный первый продуктовый уровень:

- список сохраняемых диалогов;
- создать, переименовать, удалить и продолжить диалог;
- server-built ограниченный контекст;
- лимит контекста в токенах/символах, отдельно от локального Ollama `num_ctx`;
- выбор разрешённой текстовой модели;
- интернет-поиск с компактными источниками;
- инструменты генерации изображения и видео;
- дальнейшие инструменты звука и 3D через тот же tool protocol;
- удержание микрофона для записи, отпускание для завершения;
- копирование, редактирование и повтор запроса;
- отсутствие сырого tool JSON, system prompt и внутренних ошибок в ответе;
- точный учёт input/output/tool usage.

Ответы форматируются как пользовательский текст. Погода и другие актуальные
данные принимаются только при реальном вызове поиска с источниками. Tool result
показывает готовый материал и действия, а не технический промпт.

---

## 8. Контракт раздела «Изображения»

В область входят:

- text-to-image;
- image-to-image;
- объединённые изменение и совмещение;
- рисование, маска и полноэкранный холст;
- face reference и фактическая сила LoRA;
- стили и шаблоны из действующего продукта;
- outpaint/расширение;
- удаление фона;
- разрешения до 4K только по capability;
- история преобразований;
- скачать, поделиться, оживить, опубликовать и очистить preview.

Quality acceptance проверяет не только создание файла:

- прозрачность после удаления фона;
- изменение только замаскированной области;
- увеличение холста при outpaint;
- различимый эффект нескольких положений face slider;
- фактические размеры и aspect ratio;
- отсутствие ненужного CPU/model reload для локальной выбранной модели;
- полный fit результата в preview, fullscreen zoom и pinch.

---

## 9. Контракт раздела «Видео»

Поддерживаемые продуктовые режимы:

- text-to-video;
- image-to-video;
- первый и последний кадр;
- сборка по референсам.

Таймер начинается при подтверждённом создании пользовательского задания и
заканчивается после появления воспроизводимого файла. UI отдельно показывает
очередь, provider processing и доставку результата.

Acceptance проверяет:

- фактическую длительность, разрешение и aspect ratio;
- наличие и воспроизводимость audio track, если он заказан;
- вертикальный и широкий preview без crop;
- встроенное и полноэкранное воспроизведение;
- refresh/reconnect recovery;
- timeout/cancel без повреждения следующего задания;
- возврат при отказе;
- пост и story delivery по разрешённым каналам;
- отображение в истории, галерее, ленте и CRM.

Локальное видео остаётся выключаемым capability/feature flag и не блокирует
работу внешних моделей.

---

## 10. Контракт раздела «Звук»

MVP:

- text-to-speech;
- запись при удержании;
- speech-to-text;
- выбор разрешённого голоса;
- воспроизведение, повтор, скачивание и удаление;
- история и галерея;
- передача результата в видеоредактор.

Музыка, клонирование голоса и очистка записи являются отдельными пакетами с
отдельными consent, abuse и тарифными правилами.

---

## 11. Контракт раздела «3D-моделирование»

### 11.1. Обязательный provider spike

До production-кода выполняется bounded benchmark минимум двух доступных
provider adapters на одном наборе запросов:

- предмет;
- персонаж;
- объект с тонкими деталями;
- текст-to-3D;
- image-to-3D.

Фиксируются качество geometry, texture, topology, время, сбои, цена, output
formats, commercial terms, moderation, cancel/retry и provider data retention.
Результат — документированное решение и fake adapter contract. Реальный
платный benchmark требует отдельного разрешения.

### 11.2. MVP

- text-to-3D;
- image-to-3D;
- явные стадии geometry/preview и texture/refine;
- durable provider job;
- GLB как основной web-preview format;
- rotate, zoom, pan, reset camera и fullscreen;
- безопасные presets света и фона;
- poster/thumbnail для истории и галереи;
- оптимизированный mobile derivative;
- скачивание поддерживаемых export formats;
- quote/reserve/settle/refund;
- отображение в CRM и admin model catalog.

Предварительные mobile budgets до измерения на целевых телефонах:

- GLB derivative: до 20 MB;
- geometry: ориентир до 150 000 triangles;
- textures: до 2K;
- тяжёлый оригинал не загружается автоматически в ленте.

Budget является стартовой гипотезой. Он утверждается или изменяется после
измерения first frame, FPS, memory и crash rate на реальных устройствах.

### 11.3. 3D v2 вне MVP

- multi-view input;
- retexture;
- remesh/decimation;
- OBJ/FBX/STL/USDZ/3MF по capability;
- подготовка к 3D-печати;
- rigging;
- animation;
- локальный 3D provider после отдельной hardware/cost проверки.

Rigging и animation не блокируют выпуск работающего 3D MVP.

### 11.4. Безопасность 3D

- owner-check для модели, textures, archives и exports;
- проверка размера и типа до распаковки;
- защита от archive/path traversal и decompression bombs;
- provider URL не становится постоянной публичной ссылкой;
- preview в feed является отдельным публичным derivative;
- удаление приватного оригинала не ломает уже опубликованный derivative;
- parser/viewer не получает произвольный executable content.

---

## 12. Админка, наблюдаемость и поддержка

Admin model catalog получает modality `text`, `image`, `video`, `audio`, `3d`
и capability/status/cost для каждой модели.

Для каждого job администратор видит:

- пользователя и correlation id;
- operation/model/provider;
- безопасный prompt/input summary;
- timestamps всех этапов;
- пользовательское списание и возврат;
- provider/local cost;
- media preview;
- retry/cancel/recovery events;
- публичные delivery events;
- безопасную причину ошибки и ссылку на закрытый log event.

Пользователь не видит отсутствие денег на provider account, stack trace,
внутренний URL, состояние ключа провайдера или filename модели. Он получает сообщение о
временном техническом сбое, сохранённое задание/возврат и путь в поддержку.

Метрики:

- jobs по modality/model/status;
- queue/run/delivery latency;
- provider failure и timeout rate;
- duplicate prevention;
- token reservation/refund;
- себестоимость и маржа;
- mobile Web Vitals;
- 3D first-frame/FPS/load failure;
- crash/reconnect/recovery rate.

---

## 13. UX-инварианты

- Согласованный визуальный шаблон `/phone` сохраняет цвета, форму навигации и
  общий характер интерфейса.
- Размеры не копируются слепо, если они нарушают доступность или перекрывают
  контент на реальном телефоне.
- Основное действие доступно большим пальцем, но не перекрывает результат.
- Иконка без постоянной подписи получает accessible name и подсказку по
  длительному удержанию.
- Drawer закрывается крестиком, backdrop, системным Back и безопасным swipe.
- Toast виден независимо от текущей прокрутки, различает success/warning/error,
  доступен screen reader и может быть закрыт.
- Media сохраняет aspect ratio. `object-fit: cover` не используется там, где
  пользователь должен оценивать полный результат.
- Keyboard, safe-area, browser bars, 200% text zoom и landscape входят в
  responsive acceptance.
- Дневные токены отображаются жёлтым, основные/платные — фиолетовым во всех
  списках, quote и подтверждениях.

---

## 14. Реальная проверка

### 14.1. Уровни проверки

1. Unit/contract tests с fake providers.
2. Integration tests на временной SQLite и временных media roots.
3. Focused browser tests на кандидате.
4. Quick gate завершённого пакета.
5. Один Full gate clean release candidate.
6. После отдельно разрешённого deploy — точный release identity и local/public
   browser acceptance.
7. Для внешней или локальной генерации — отдельный статус
   `OPERATIONALLY VERIFIED` после реального redacted flow.

### 14.2. Обязательная браузерная матрица

- Android Chrome на реальном телефоне;
- iPhone Safari либо явно отмеченный временный blocker при отсутствии
  устройства;
- desktop Chrome для диагностики;
- `390x844` и `430x932` автоматизированные viewports;
- slow network, reconnect и refresh;
- keyboard open/close;
- authenticated и guest states;
- недостаток каждого типа токенов;
- provider error/timeout;
- повторное нажатие и две операции в очереди.

### 14.3. Содержательные проверки

| Область | Что доказывает результат |
|---|---|
| Чат | актуальный поиск имеет источники; tool скрывает JSON; контекст восстанавливается |
| Изображения | формат, размер и запрошенное редактирование проверены, а не только файл существует |
| Видео | файл декодируется, длительность/разрешение верны, заказанный звук существует |
| Звук | файл воспроизводится, речь распознаваема, запись прекращается при отпускании |
| 3D | GLB загружается, first frame появляется, rotate/zoom работают, export скачивается |
| Деньги | reserve/settle/refund согласованы с job и admin ledger |
| История | refresh/login восстанавливает результат без дубликатов |

Автотест не совершает реальный платный вызов. Реальный user/provider smoke
запускается отдельно, ограниченно и с явным разрешением.

---

## 15. Порядок реализации

Этапы ниже являются epics, а не разрешением на один большой commit. Каждый epic
разбивается на bounded packages по шаблону глобального плана, обычно не более
12 production-файлов.

| Порядок | Epic | Результат | Блокирует следующий |
|---:|---|---|---:|
| 0 | `REL-SVC-001` | доказана автономная публикация backend и rollback | да |
| 1 | `PHONE-ARCH-001` | API/state/capability/media/billing contracts и characterization | да |
| 2 | `PHONE-SHELL-001` | React App Shell и пять deep-link маршрутов без расширения iframe | да |
| 3 | `PHONE-CORE-001` | durable jobs, progress, recovery и media integration | да |
| 4 | `PHONE-CHAT-004` | чат перенесён с временного runtime/sidecar и принят | нет |
| 5 | `PHONE-IMAGE-001` | изображения и редактор имеют mobile parity | нет |
| 6 | `PHONE-VIDEO-001` | видео имеет mobile parity и recovery | нет |
| 7 | `PHONE-AUDIO-001` | звук MVP | нет |
| 8 | `PHONE-3D-SPIKE-001` | выбран provider-neutral 3D contract | да для 3D |
| 9 | `PHONE-3D-MVP-001` | text/image-to-3D и GLB viewer | нет |
| 10 | `PHONE-3D-V2-001` | расширенные 3D-функции по отдельным решениям | нет |
| 11 | `PHONE-ROLLOUT-001` | staged rollout, метрики и rollback rehearsal | завершение |

`PHONE-CHAT-004`, `PHONE-IMAGE-001`, `PHONE-VIDEO-001` и `PHONE-AUDIO-001`
могут выполняться в другом порядке только после завершения общих этапов 0–3 и
при отсутствии пересечения owner/files. 3D MVP всегда следует после 3D spike.

---

## 16. Шаблон каждого кодового пакета

До изменения кода агент обязан заполнить:

```text
ID:
Цель пользователя:
Owner:
Исходный SHA:
Текущее подтверждённое поведение:
Файлы в scope:
Файлы вне scope:
API/schema/UI contracts:
Acceptance:
Targeted tests:
Real browser acceptance:
Rollback boundary:
Migration required: yes/no
Deployment required: yes/no
Provider operation required: yes/no
```

Если цель, acceptance или rollback нельзя сформулировать — код не начинается.

---

## 17. Feature flags и выпуск

Каждая новая область проходит:

```text
disabled -> admin only -> test accounts -> percentage cohort -> enabled
```

Флаг отключает новые запуски, но не уничтожает уже созданные задания и
результаты. Откат frontend/backend не должен делать новые schema rows
нечитаемыми; migrations только additive.

Release считается успешным только при совпадении:

- clean canonical `main == origin/main`;
- verification receipt SHA;
- frontend/backend release identity;
- active release manifest;
- service/process owner;
- local health;
- public health;
- browser acceptance нужного маршрута.

Ручное копирование файлов в active release запрещено.

---

## 18. Definition of Done мобильной платформы

Программа не завершена, пока:

- iframe и sidecar остаются источником новой бизнес-логики;
- отсутствует хотя бы один из пяти рабочих маршрутов;
- refresh теряет активное задание или историю;
- UI самостоятельно решает стоимость/возможности модели;
- существует двойное списание либо неизвестный возврат;
- приватный media read не проверяет owner;
- 3D не имеет mobile derivative и безопасного viewer;
- admin/CRM не могут связать результат, job, расходы и пользователя;
- нет реальной браузерной проверки результата;
- нет rollback boundary и staged feature flag;
- состояние названо `VERIFIED` без точного evidence.

Отдельный epic считается завершённым только после выполнения применимых пунктов
`AGENTS.md`, локальных gates, документации, commit/push и честного разделения
`CODE COMPLETE`, `DEPLOYED`, `VERIFIED`, `OPERATIONALLY VERIFIED`.

---

## 19. Изменение этого решения

Новая просьба владельца может изменить приоритет, UX или функциональность. В
таком случае тот же пакет обязан:

1. обновить этот документ;
2. указать, какое прежнее решение заменено;
3. обновить acceptance и риски;
4. сохранить уже подтверждённые инварианты безопасности, данных и экономики;
5. не выдавать намерение за реализованный статус.

Точный первый implementation package после принятия документа —
`REL-SVC-001`: воспроизвести и устранить расхождение между успешно проверенным
кандидатом и запуском `IZOBackend` как production-службы. До его завершения
новая бизнес-логика Phone не публикуется.

## 20. Журнал реализации

- `REL-SVC-001`: **OPERATIONALLY INSTALLED** — service-safe promoter установлен
  из clean commit, исходный и runtime hash совпали, службы не перезапускались,
  локальный и публичный health вернули 200.
- `PHONE-ARCH-001`: **CODE COMPLETE; NOT DEPLOYED** — добавлен authenticated
  `/api/phone/v1/platform`, server-owned feature flags и общие frontend types,
  transport и route contract. Подробности:
  [phone-architecture-contract-20260824.md](phone-architecture-contract-20260824.md).
- `PHONE-SHELL-001`: **CODE COMPLETE; NOT DEPLOYED** — нативные React routes,
  общий shell, навигация, меню, offline/error/auth states и mobile browser E2E.
  Подробности:
  [phone-shell-implementation-20260824.md](phone-shell-implementation-20260824.md).
- `PHONE-CORE-001`: **CODE COMPLETE; NOT DEPLOYED** — единый authenticated
  facade активных image/video jobs, owner check, безопасные статусы, recovery
  без повторного запуска, общие media/billing helpers и mobile E2E. Подробности:
  [phone-core-implementation-20260824.md](phone-core-implementation-20260824.md).
- `PHONE-CHAT-001`: **CODE COMPLETE; NOT DEPLOYED; LIVE PROVIDER ACCEPTANCE
  PENDING ROLLOUT** — сохраняемые диалоги, модели и контекст, минималистичный
  React UX, web/image tools, удержание микрофона, tool recovery и mobile E2E.
  Подробности:
  [phone-chat-implementation-20260824.md](phone-chat-implementation-20260824.md).
- `PHONE-IMAGE-001A`: **CODE COMPLETE; NOT DEPLOYED; LIVE GENERATION
  ACCEPTANCE PENDING ROLLOUT** — нативное создание, изменение/совмещение,
  рисование, capability-driven форматы, история, fullscreen zoom/pinch и
  mobile E2E. Полный epic остаётся открытым до маски, расширения, удаления фона
  и face-reference. Подробности:
  [phone-image-implementation-20260824.md](phone-image-implementation-20260824.md).
