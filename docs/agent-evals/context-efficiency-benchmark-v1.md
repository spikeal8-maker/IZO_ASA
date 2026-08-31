---
status: proposed
role: repeatable-agent-eval
version: 1
scope: chat-and-admin-routing
production_status_role: none
---

# Context efficiency benchmark v1

Назначение: измерять, помогает ли агентная документация или новый retrieval-tool
реально сокращать чтение IZO_ASA без ухудшения ответа. Этот benchmark не является
архитектурным планом, не разрешает изменение кода и не заменяет `AGENTS.md` или
`AI_START_HERE.md`.

## Правила запуска

- Каждый case выполняется в новом чистом Codex-чате без истории другого case.
- Codex project/cwd: `E:\IZO_ASA_WORKSPACE` или отдельный worktree этого repo.
- Remote должен соответствовать `spikeal8-maker/IZO_ASA`.
- Рабочее дерево чистое; `HEAD` и режим запуска записываются в receipt.
- Codex Memories отключены на время сравнения.
- По возможности используется одна и та же модель и одинаковые настройки.
- Никаких изменений файлов, commits, pushes, provider calls, deploy или restart.
- Реальные tokens записываются только если их показывает клиент/API. Не оценивать
  tokens по размеру текста.

`manual-routing` — текущая документация без нового context CLI.
`candidate-tool` — тот же case после внедрения проверяемого retrieval-tool.

## Что считается предметным файлом

`subjectFiles` — context-карты, generated evidence, source и tests, открытые для
ответа. Обязательные `AGENTS.md`, `AI_START_HERE.md` и `docs/NOW.md` учитываются
отдельно и не входят в лимит предметных файлов.

Broad scan — recursive listing/search по значительной части repo без заранее
ограниченного path, symbol, route или filename. Точечный поиск конкретного
symbol/route broad scan не считается.

Protected full read — чтение целиком `backend/main.py`, `newUi.tsx`,
`LegacyApp.tsx`, `adminModels.tsx`, большого CSS, `backend/SYMBOL_MAP.md` или
`docs/generated/architecture-inventory.json`.

## Case CHAT-SELECTOR-001

Отправить дословно:

```text
Режим: АНАЛИЗ БЕЗ ИЗМЕНЕНИЙ.

Найди, где в desktop chat реализован выбор модели.

Ограничения:
- не менять файлы;
- не делать recursive scan;
- не читать большие монолиты целиком;
- максимум 8 предметных файлов;
- используй canonical routing проекта;
- после ответа остановись.

Покажи:
1. цепочку UI → frontend API → backend → persistence;
2. главный owner-файл;
3. относящиеся targeted tests;
4. что осталось неподтверждённым;
5. все открытые предметные файлы.
```

Критерии правильности:

- выбран domain `chat` и `docs/context/chat.md`;
- найден `DesktopChatWorkspace.tsx` как основной desktop owner;
- показаны shared API и backend chat router/history boundary;
- тесты не выдуманы, неизвестное отмечено явно.

## Case ADMIN-LAST-ADMIN-001

Отправить дословно:

```text
Режим: АНАЛИЗ БЕЗ ИЗМЕНЕНИЙ.

Найди, где реализовано изменение роли пользователя администратором и защита от
снятия роли последнего администратора.

Ограничения:
- не менять файлы;
- не делать recursive scan;
- не читать backend/main.py целиком;
- максимум 8 предметных файлов;
- используй canonical routing и route-level evidence проекта;
- после ответа остановись.

Покажи:
1. route и handler;
2. текущие auth/reason/audit/transaction controls;
3. существующие targeted tests;
4. подтверждён ли concurrent last-admin invariant;
5. все открытые предметные файлы.
```

Критерии правильности:

- выбран domain `admin-control-center`;
- использован `docs/admin-mutation-audit.md`, gap `AM-009`;
- найден route `POST /api/admin/users/{internal_user_id}/role-v2` и symbol
  `admin_role_v2`;
- sequential coverage не выдано за доказательство concurrent invariant.

## Receipt

Для каждого запуска сохранить один YAML-блок:

```yaml
benchmarkVersion: 1
caseId: CHAT-SELECTOR-001
mode: manual-routing
model: exact-model-name
startedAtUtc: 2026-08-31T00:00:00Z
repoRoot: E:\IZO_ASA_WORKSPACE
head: 40-character-git-sha
memoriesEnabled: false
elapsedSeconds: 0
files:
  mandatory: []
  context: []
  generated: []
  source: []
  tests: []
subjectFileCount: 0
protectedFullReads: []
broadScans: 0
repeatedSearches: 0
userCorrections: 0
actualInputTokens: null
actualOutputTokens: null
result:
  domainCorrect: false
  ownerCorrect: false
  testsCorrect: false
  unknownsHonest: false
  noChanges: true
notes: ""
```

Использовать фактические значения. `null` лучше недостоверной оценки.

## Gate одного запуска

Case проходит только если одновременно:

- правильный repo и domain выбраны без ручной коррекции;
- `subjectFileCount <= 8`;
- `protectedFullReads` пуст;
- `broadScans == 0`;
- historical plans не открывались без явного обоснования;
- source не изменён;
- все четыре поля `result.*Correct/unknownsHonest` равны `true`.

## Gate улучшения

Новый retrieval-tool принимается только если на обоих cases:

- качество и safety-gates не ухудшились;
- предметных файлов не стало больше;
- broad scans и protected full reads остаются нулевыми;
- суммарно улучшился хотя бы один измеряемый показатель: фактические tokens,
  elapsed time, subject-file count или repeated searches;
- улучшение не требует нового обязательного документа в ежедневном reading path.

Если измеримого выигрыша нет, tool не расширяется на другие domains.
