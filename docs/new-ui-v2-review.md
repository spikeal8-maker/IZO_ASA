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

