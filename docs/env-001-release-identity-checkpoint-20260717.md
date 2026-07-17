# ENV-001 — checkpoint неизменяемой production identity

- Дата: **2026-07-17**
- Статус: **VERIFIED**
- Code baseline и развёрнутый commit: `2e447828be098a58513c978bc07aa64e4f694b4b`
- Развёрнутый release: `2e447828be09-20260717233010`
- Последующее состояние: publisher-risk закрыт [REL-001 checkpoint](rel-001-fail-closed-publisher-checkpoint-20260718.md); текущий live release указан в master plan

## Результат

Действующий локальный Windows production теперь имеет одну доказуемую identity для
backend, frontend bundle, HTML marker и статических backend-shells. Application
workload не переносился на VPS, существующая конфигурация FRP не изменялась.

| Контракт | Проверенный результат |
|---|---|
| Checkout | чистый `main`, code SHA `2e447828be098a58513c978bc07aa64e4f694b4b` |
| Release manifest | version 1, dirty=false, полный SHA, UTC build time, hash/count frontend assets, точные Python/Node и schema range |
| Backend identity | `/api/version` сообщает только manifest identity; release и полный SHA совпадают с active frontend manifest |
| Public health | `/api/health` минимален: readiness, app и release ID |
| Detailed health | перенесён в trusted-admin `/api/admin/runtime-health-v2` |
| Frontend identity | immutable bundle содержит точный release в HTML meta и JavaScript |
| Static shells | `/feed` и `/gallery` возвращают точный `X-IZO-Release` |
| Python ownership | listener PID 46484 — base Python 3.11.9; прямой parent PID 40124 — точный `backend/.venv/Scripts/python.exe` launcher |
| Frontend process | PID 34620 обслуживает только `.runtime/releases/frontend/2e447828be09-20260717233010` |
| Public ingress | `https://izo.alikinas.ru` возвращает тот же release через существующий FRP; VPS не менялся |

## Реализация

### `87c5d0c` — фундамент immutable identity

- добавлены `backend/app/release_identity.py` и строгая проверка manifest;
- добавлены `tools/build_release_manifest.py` и хеширование frontend assets;
- exact identity внедрена Vite в frontend meta и JavaScript;
- production import/startup fail closed при dirty, несовпадающем, несовместимом
  release либо Python вне project `.venv`;
- public health сокращён, trusted-admin runtime diagnostics отделён;
- добавлены контракты candidate frontend publication, backend restart и frontend
  rollback;
- unmanaged autostart bootstrap удалён, реальная локальная FRP-топология
  задокументирована.

### `29fb7ed` — корректировка ownership смешанных routes

Первый реальный candidate smoke выявил, что `/feed` и `/gallery` — backend static
shells через Vite proxy, а не frontend-owned SPA documents. Candidate-проверка теперь
требует release meta только от frontend-owned routes, backend shells проверяет по
status до activation и по `X-IZO-Release` после backend activation.

### `2e44782` — корректировка Windows virtual-environment ownership

Windows оставляет `backend/.venv/Scripts/python.exe` redirector/launcher, а порт
8000 держит дочерний base interpreter. Restart guard принимает только доказанную
прямую цепочку:

`exact project venv launcher -> python.exe listener -> exact uvicorn command`

Listener/launcher PIDs, listener executable и ownership mode сохраняются в
`.runtime/active-backend.json`. При отказе candidate cleanup останавливает дочерний
listener только после доказательства этой связи.

## Хронология безопасной активации

1. Candidate из `87c5d0c` не прошёл browser smoke до activation из-за неверной
   модели ownership смешанных routes. Старые backend/frontend PIDs не изменились,
   failed candidate удалён.
2. После `29fb7ed` frontend candidate и backend health прошли, но первоначальный
   guard отклонил допустимый Windows venv child listener. Backend и frontend rollback
   восстановили прежний доступный release.
3. Перед повтором обнаружена реальная пользовательская генерация. Deployment ждал,
   пока задание покинет active set. Затем ComfyUI остановился независимо, задание
   стало failed, ComfyUI был восстановлен до следующей release-попытки.
4. `2e44782` добавил строгую parent/child ownership-проверку. Три последовательных
   safe-window snapshot показали 0 active jobs, 0 preparing publications, очередь
   ComfyUI 0/0 и 0 backend API connections.
5. Controlled launcher активировал `2e447828be09-20260717233010`; все
   post-activation identity/auth checks прошли.

Обе неуспешные попытки являются evidence отката, а не успешными релизами. Они
обнаружили дефекты до объявления production-ready и позволили закрыть их тестами.

## Проверки

| Gate | Результат |
|---|---|
| Project `.venv` dependency check | Python 3.11.9, exact `backend/requirements.txt`, `pip check` PASS |
| Critical release set | 58 tests, 5 последовательных проходов |
| Launcher/recovery set | 23 tests, 5 последовательных проходов |
| Mixed route ownership set | 14 tests, 5 последовательных проходов |
| Real candidate browser route smoke | все обязательные routes, 5 последовательных проходов |
| Final Windows venv regression set | `tools/test_restart_backend_script.py tools/test_launchers.py tools/test_release_resilience_scripts.py`: 19 tests, 5 последовательных проходов |
| Full isolated gate | `tools/verify.ps1 -Mode CI`: 1497 passed, 92 известных deprecation warnings; lint, TypeScript/Vite build, release identity, origin isolation и browser resilience PASS; 431.11 s |
| Post-deploy live gate | `tools/verify.ps1 -Mode Quick`: 63 passed; `windows-venv-child` preflight, listener contract и стабильный source snapshot PASS; 27.85 s |
| Residual pytest processes | 0 |

Post-deploy локальные и публичные probes подтвердили:

- `/`, `/feed`, `/gallery`, `/api/health`, `/api/version`: HTTP 200;
- root meta, feed/gallery headers, backend release и frontend release равны
  `2e447828be09-20260717233010`;
- без сессии `/api/generate`, `/api/gallery`, `/api/me-v2`: HTTP 401;
- очередь ComfyUI: running 0, pending 0;
- startup logs: application startup complete, 0 совпадений error/traceback/polling
  conflict во время observation;
- optional Qwen ASR port 8001 отсутствует; остаётся известное предупреждение:
  Ollama слушает `:::11434`, а не только loopback.

## GitHub

Все implementation commits отправлены в `origin/main` по действующему direct-main
workflow. Run `29611341429` для exact deployed SHA, job `87986493899`, не выполнил
ни одного runner step. GitHub annotation сообщает failed recent account payments
либо необходимость увеличить spending limit. Следовательно:

- локальные проверки зелёные;
- GitHub CI **не зелёный** и одновременно **не является code-test failure**;
- CI-001 остаётся `BLOCKED EXTERNALLY`, пока billing/spending не исправлен и новый
  exact-SHA run не выполнит все обязательные steps.

## Impact и остаточный риск

- Schema: DDL/migration отсутствуют; live `user_version=1` находится в manifest
  range 1..1.
- API: `/api/health` намеренно минимизирован; `/api/version` manifest-backed;
  detailed runtime health доступен только trusted admin.
- Auth: новый legacy auth path не добавлен; unauthenticated smoke остаётся 401.
- Tasks: worker ownership в этом пакете не декомпозировался; startup/recovery
  остаются под существующими characterization tests.
- Data/media: tests и release tooling не изменяли production DB/media.
- Rollback: candidate rejection и frontend/backend availability rollback реально
  сработали. Immutable artifact старого backend и drain switch ещё отсутствуют —
  это REL-002.
- Historical publisher residual: на момент ENV-001 `start-public.bat` использовал
  `-SkipVerify`; обычный bypass удалён последующим REL-001, audited break-glass и
  exact-SHA receipt реализованы.
- Edge: frontend production всё ещё обслуживает Vite Preview. После завершённого
  REL-001 следующий пакет — EDGE-001 с локальным Caddy.

Для documentation-only commit этого checkpoint restart не требуется. Развёрнутый
application code остаётся точно `2e44782`.
