---
status: completed
canonical: false
record_role: completed-package-receipt
package: AI-CANONICAL-001
program: IZO_ASA Agent Control Plane
base_sha: ecb02bf84ae21a46711c9b38b61784147fb9fc0a
candidate_sha: 882e2f260f12a44c01e731d928a8b81021ed0d2f
merged_pr: 73
merged_sha: 49a19e271e4e0e71d1fa6f871f828f0a233cfbdf
deployment: none
completed: 2026-08-30
superseded_as_active_task_by: none
---

# AI-CANONICAL-001 — completion receipt

Это завершённый Task Contract и историческое evidence. Он не является текущим
заданием и не входит в ежедневный контекст агента.

## Цель пакета

Создать один непротиворечивый вход для coding-агентов без изменения product-кода,
production, runtime, DB, media или внешних providers.

## Реализовано

- корневой `AGENTS.md` назначен единственной repository-wide policy;
- создан короткий `AI_START_HERE.md`;
- создан `docs/NOW.md` как единственный current-status aggregator/program router;
- Claude, Gemini и Copilot adapters сокращены;
- конфликт absolute workspace path в `CLAUDE.md` устранён;
- `README.md` перестал выполнять роль backlog и называть production prototype;
- `docs/current-status.md` помечен superseded;
- добавлен `tools/test_agent_instructions.py`;
- instruction checks подключены к существующему context/Quick contract.

## Проверка и интеграция

```text
candidate SHA: 882e2f260f12a44c01e731d928a8b81021ed0d2f
GitHub Actions run: 33308355426
PR: #73
merge SHA: 49a19e271e4e0e71d1fa6f871f828f0a233cfbdf
deployment: NOT DEPLOYED
```

Product source under `frontend/**` and `backend/**`, operations, production data,
runtime and providers не изменялись.

## Post-merge findings

Автоматический review завершился после merge и обнаружил:

1. dead path к generated architecture inventory;
2. разные порядки чтения в canonical документах.

Они исправляются отдельным bounded package `AI-CANONICAL-REPAIR-001`, issue
`#74`. Это не меняет факт завершения исходного package, но фиксирует, что его
первый merge не был окончательно непротиворечивым.

## Состояния

```text
IMPLEMENTED: yes
TESTED: yes
COMMITTED: yes
PUSHED/PR: yes, #73
MERGED: yes
DEPLOYED: no
OPERATIONALLY VERIFIED: not applicable
```

Для текущей работы использовать `docs/NOW.md` и owner-approved Task Contract, а
не этот receipt.
