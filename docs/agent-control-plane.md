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
воспроизводимой. Это reference document, а не ежедневный обязательный контекст.
Порядок чтения определён только в `AI_START_HERE.md`.

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

Главный принцип: документация объясняет правила, инструменты их проверяют и
обеспечивают.

## 2. Что переиспользуется

Не создавать параллельные реализации:

- корневой `AGENTS.md` и существующий `docs/context/`;
- generated frontend/backend/architecture maps;
- `tools/repository-operation-lock.ps1` и `tools/verify.ps1`;
- временные DB/media roots и fake providers в CI;
- действующие release, backup и production-safety contracts.

## 3. Что не смешивается с базовым контуром

До завершения управляющих пакетов не объединять с ними redesign, массовую
декомпозицию монолитов, миграцию платформы, Maya, deploy/restart, реальные
платежи/webhook/письма/provider calls или массовое перемещение документации.

## 4. Состояние программы

Завершено:

- `AI-CANONICAL-001`: PR `#73`, merge
  `49a19e271e4e0e71d1fa6f871f828f0a233cfbdf`, `NOT DEPLOYED`.
- `AI-CANONICAL-REPAIR-001`: final reviewed head
  `8f1de5a167ca94a334e5df274da479cf0beab0ee`, CI `33312197937`, PR `#75`,
  merge `8e15a89aae71f71eed31a0ef490228cdbc854c7d`, `NOT DEPLOYED`.
- Status closeout tracked by issue `#76`.

Активного implementation package нет. Следующий кандидат:

- `AI-INSTRUCTION-SCOPE-001` — уменьшить постоянный root context и добавить
  scoped `backend/frontend/ops/docs AGENTS.md`.

Он начинается только с отдельного owner-approved Task Contract. Baseline issue
`#71` остаётся read-only экспериментом на старом SHA.

## 5. Последовательность оставшихся пакетов

1. `AI-INSTRUCTION-SCOPE-001`
   - сократить root policy;
   - вынести предметные правила в четыре scoped-файла;
   - измерять полный обязательный context budget.

2. `AI-CONTEXT-SCHEMA-001`
   - metadata schema для существующих трёх context-карт;
   - deterministic generated index и path/fingerprint validation;
   - без новых domain-карт.

3. `AI-CONTEXT-PILOT-001`
   - только `chat` и `admin-models`;
   - bounded `agent context`;
   - повторить соответствующие baseline cases.

4. `AI-SYMBOL-CONTEXT-001`
   - symbol, imports, callers/callees, routes, tests и bounded line window;
   - без чтения гигантских файлов целиком.

5. `AI-CONTEXT-EXPAND-001`
   - images, billing, audio, 3D и release-ops после успешного пилота.

6. `AI-PACKAGE-001`
   - Task Contract schema;
   - shared registry через Git common dir;
   - worktree lifecycle, declared/discovered scope и overlap detection;
   - расширить существующий repository lock, не писать второй.

7. `AI-ENFORCE-001`
   - versioned hooks, package ID/scope guards, integration lock и CI validation.

8. `AI-DEV-ENV-001`
   - temporary DB/media/secrets, fake providers, fixtures, unique ports,
     preview и cleanup receipt.

9. `AI-VERIFY-001`
   - affected-test routing, compact logs, visual/functional evidence и один Full
     на clean integration candidate.

10. `AI-CONTRACT-GRAPH-001`
    - UI → API → service → DB → worker → provider → billing;
    - `unknown` вместо догадок.

11. `AI-EVAL-001`
    - полный cold eval, сравнение с baseline и решение о rollout.

12. `AI-DECOMPOSE-*`
    - постепенное уменьшение `backend/main.py`, `newUi.tsx`,
      `adminModels.tsx`, крупных CSS и legacy boundaries.

Issue `#72` остаётся родительской спецификацией и не исполняется одним агентом.

## 6. Целевая CLI-поверхность

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

Отсутствующая команда не должна имитироваться ручной процедурой, выдаваемой за
техническое enforcement.

## 7. Бюджеты и метрики

```text
core instructions:          ≤ 12–16 KiB
domain + Task Contract:     ≤ 12–16 KiB
bounded source/test context: измеряется отдельно
```

- first-pass acceptance ≥ 70%;
- обычная UI-задача читает < 15 source-файлов;
- незаявленные cross-domain changes = 0;
- direct agent pushes в `main` = 0;
- один Full на integration candidate;
- repeated broad scan без новой причины = 0;
- фактические tokens — только по данным Codex/API.

## 8. Merge и release gates

Каждый package имеет Task Contract/issue и feature branch, не расширяет scope
молча, проходит targeted checks и требуемый Quick, ждёт CI и automated review,
разбирает все findings, передаёт один self-contained PR и не выполняет
production-действия без отдельной авторизации.

`CODE COMPLETE`, `VERIFIED`, `MERGED`, `DEPLOYED` и
`OPERATIONALLY VERIFIED` не объединяются.

## 9. Definition of done программы

Новый агент без истории чата определяет repo/worktree, формирует Task Contract,
получает bounded context, не читает монолиты целиком без причины, не пересекается
с другим package, использует isolated environment, запускает релевантные gates,
предъявляет evidence, передаёт clean commit и проходит eval лучше baseline.
