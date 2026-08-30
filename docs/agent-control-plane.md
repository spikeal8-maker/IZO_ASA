---
status: active-program
canonical: true
daily_context: false
program: IZO_ASA Agent Control Plane
updated: 2026-08-30
repository: spikeal8-maker/IZO_ASA
---

# IZO_ASA Agent Control Plane

## 1. Назначение

Программа делает работу разработчиков и AI-агентов ограниченной, проверяемой и
воспроизводимой. Это program/reference document, а не ежедневный обязательный
контекст. Порядок чтения для coding-задач определён только в
`AI_START_HERE.md`.

Целевой цикл:

```text
запрос владельца
→ Task Contract
→ domain и risk class
→ ограниченный context packet
→ отдельный worktree и package ownership
→ изолированная тестовая среда
→ изменение в заявленном scope
→ targeted verification и пользовательское evidence
→ один clean commit интегратору
→ обновление context/eval по фактическому drift
```

Главный принцип:

> Документация объясняет правила. Инструменты проверяют и обеспечивают их.

## 2. Что переиспользуется

Не создавать параллельные реализации существующих механизмов:

- корневой `AGENTS.md`;
- существующий `docs/context/`;
- generated frontend/backend/architecture maps;
- `tools/repository-operation-lock.ps1`;
- `tools/verify.ps1`;
- временные DB/media roots и fake providers в CI;
- действующие release, backup и production-safety contracts.

## 3. Что не смешивается с базовым контуром

До завершения управляющих пакетов не объединять с ними:

- redesign продукта;
- массовую декомпозицию `backend/main.py`, `newUi.tsx` или CSS;
- миграцию на Linux/PostgreSQL/Docker;
- установку Maya;
- deploy/restart;
- реальные платежи, webhook, письма или provider calls;
- массовое перемещение исторической документации.

3D получает domain-карту и eval-кейс. Maya остаётся отдельным продуктовым
пакетом.

## 4. Состояние программы

Завершено:

- `AI-CANONICAL-001` — единая policy/entry/status route; PR `#73`, merge
  `49a19e271e4e0e71d1fa6f871f828f0a233cfbdf`, `NOT DEPLOYED`.
- `AI-CANONICAL-REPAIR-001` — устранение post-merge review findings и
  синхронизация canonical статусов; issue `#74`; считается завершённым после
  merge source version, содержащей этот текст.

Отдельно сохраняется baseline:

- `AI-EVAL-BASELINE-001`, issue `#71`, выполняется тремя независимыми read-only
  сессиями на SHA `ecb02bf84ae21a46711c9b38b61784147fb9fc0a`.

Следующий кандидат:

- `AI-INSTRUCTION-SCOPE-001` — уменьшить постоянный root context и добавить
  scoped `backend/frontend/ops/docs AGENTS.md`.

## 5. Последовательность оставшихся пакетов

1. `AI-INSTRUCTION-SCOPE-001`
   - сократить root policy;
   - вынести предметные правила в четыре scoped-файла;
   - измерять полный обязательный context budget.

2. `AI-CONTEXT-SCHEMA-001`
   - metadata schema для существующих трёх context-карт;
   - deterministic generated index;
   - path/fingerprint validation;
   - без новых domain-карт.

3. `AI-CONTEXT-PILOT-001`
   - только `chat` и `admin-models`;
   - bounded `agent context`;
   - повторить соответствующие baseline cases.

4. `AI-SYMBOL-CONTEXT-001`
   - выдавать symbol, imports, callers/callees, routes, tests и ограниченный
     line window;
   - не читать гигантские файлы целиком.

5. `AI-CONTEXT-EXPAND-001`
   - расширить доказавшую эффективность схему на images, billing, audio, 3D и
     release-ops.

6. `AI-PACKAGE-001`
   - Task Contract schema;
   - shared registry через Git common dir;
   - worktree lifecycle;
   - declared/discovered scope и overlap detection;
   - расширить существующий repository lock, не писать второй.

7. `AI-ENFORCE-001`
   - versioned hooks;
   - package ID и scope guards;
   - integration lock;
   - CI validation.

8. `AI-DEV-ENV-001`
   - temporary DB/media/secrets;
   - fake providers;
   - fixtures, unique ports, preview и cleanup receipt.

9. `AI-VERIFY-001`
   - affected-test routing;
   - compact logs;
   - visual/functional evidence;
   - один Full на clean integration candidate.

10. `AI-CONTRACT-GRAPH-001`
    - UI → API → service → DB → worker → provider → billing;
    - `unknown` вместо догадок.

11. `AI-EVAL-001`
    - полный cold eval;
    - сравнение с baseline;
    - решение о rollout.

12. `AI-DECOMPOSE-*`
    - постепенное уменьшение `backend/main.py`, `newUi.tsx`,
      `adminModels.tsx`, крупных CSS и legacy boundaries.

Широкий issue `#72` остаётся родительской спецификацией и не передаётся одному
агенту целиком.

## 6. Единый пользовательский CLI

Целевая поверхность:

```powershell
.\tools\agent.ps1 doctor
.\tools\agent.ps1 context -Domain chat
.\tools\agent.ps1 symbol -Path backend/main.py -Symbol phone_chat_ollama
.\tools\agent.ps1 start -Manifest .\tasks\CHAT-001.yaml
.\tools\agent.ps1 status
.\tools\agent.ps1 scope-add -Path frontend/src/example.tsx -Reason "..."
.\tools\agent.ps1 env-up
.\tools\agent.ps1 verify
.\tools\agent.ps1 finish
.\tools\agent.ps1 eval -Suite smoke
```

Команды внедряются поэтапно. Отсутствующая команда не должна имитироваться
ручной процедурой, выдаваемой за техническое enforcement.

## 7. Бюджеты и метрики

Целевые бюджеты:

```text
core instructions:          ≤ 12–16 KiB
domain + Task Contract:     ≤ 12–16 KiB
bounded source/test context: измеряется отдельно
```

Метрики:

- first-pass acceptance ≥ 70%;
- обычная UI-задача читает < 15 source-файлов;
- незаявленные cross-domain changes = 0;
- direct agent pushes в `main` = 0;
- один Full на integration candidate;
- repeated broad scan без новой причины = 0;
- фактические tokens — только по данным Codex/API.

## 8. Merge и release gates

Каждый package:

- имеет отдельный Task Contract/issue и feature branch;
- не расширяет scope молча;
- проходит targeted checks и требуемый Quick;
- ждёт завершения CI и automated review;
- устраняет или обоснованно отклоняет все findings;
- передаёт один self-contained commit/PR;
- не выполняет deploy/restart без отдельной авторизации.

Состояния `CODE COMPLETE`, `VERIFIED`, `MERGED`, `DEPLOYED` и
`OPERATIONALLY VERIFIED` не объединяются.

## 9. Definition of done программы

Новый агент без истории чата:

1. определяет правильный repo/worktree;
2. формирует Task Contract до product changes;
3. получает bounded domain/symbol context;
4. не читает монолиты целиком без причины;
5. не пересекается с другим package;
6. использует isolated DB/providers/ports;
7. запускает релевантные проверки;
8. предъявляет evidence пользовательского результата;
9. передаёт один clean commit интегратору;
10. оставляет drift report;
11. проходит eval лучше baseline;
12. не может незаметно обойти основные safety/scope gates.
