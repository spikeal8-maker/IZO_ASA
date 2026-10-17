# Task Contract: один действующий формат

Формат и проверку определяет существующий `tools/agent_system/package.py`,
а не этот пример. Порядок входа находится только в [AI_START_HERE.md](../AI_START_HERE.md).
Задание создаётся в `tasks/` с именем, совпадающим с полем `id`.

## Полный пример схемы, не активное задание

Ниже валидный TOML для небольшого изменения документации. Его base — конкретный
исследованный Git-срез; для нового задания нужны свежий main и собственные
согласованные цель/scope. Пример не разрешает менять названный файл сам по себе.

```toml
manifestVersion = 1
id = "DOC-EXAMPLE-001"
baseSha = "d1ee3a0ac5114ec08f4a8daee9cf6e41e97d6a7a"
goal = "Clarify the documentation contract"
userOutcome = "A developer can find the correct verification command"
beforeScenario = "The current command needs clarification"
afterScenario = "The documented command and tool agree"
nonGoals = ["Application, deployment and data changes"]
domain = "documentation"
riskClass = "low"
changeClass = "documentation"
declaredFiles = ["docs/documentation-standards.md"]
allowedPatterns = []
forbiddenPatterns = ["backend/**", "frontend/**", "ops/**"]
protectedFilesTouched = []
maxProductionFiles = 0
maxChangedLines = 80
acceptance = ["References resolve and focused checks pass"]
requiredEvidence = ["Exact base/head, diff and test result"]
targetedTests = ["Portable instruction and Markdown checks"]
fileGrowthExpectations = ["Stay within the current document budget"]
forbiddenOperations = ["deploy", "restart", "production-data"]
rollbackBoundary = "Revert this documentation-only change"
```

## Проверка и создание package

Сохранить свой полностью заполненный TOML в отдельный draft-файл. Проверить его
через `parse_manifest`, затем использовать существующий `agent start --manifest`
из `tools.agent_system.package`. Точные параметры существующего CLI:

```bash
python -m tools.agent_system.package --help
python -m tools.agent_system.package start --help
```

`start` проверяет свежий base, создаёт отдельную ветку/worktree и регистрирует
ownership. Нельзя подделывать ownership-файл или активировать старый completed manifest.
`sizeReviews` при необходимости задаётся в этом же валидном Task Contract;
оно не заменяет независимое ревью, CI и объявление разрешённых путей.
