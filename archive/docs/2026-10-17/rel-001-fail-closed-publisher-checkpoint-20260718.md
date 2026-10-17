# REL-001 — checkpoint fail-closed publisher

- Дата: **2026-07-18**
- Статус: **VERIFIED**
- Implementation commits: `3747ee13ed3c440e910f791ee462f628ab36a03c`, `07528be0aa53166418f312cbe4586f351a0e2715`
- Развёрнутый code SHA: `07528be0aa53166418f312cbe4586f351a0e2715`
- Развёрнутый release: `07528be0aa53-20260718002811`

## Итог

Обычная production-публикация больше не имеет `SkipVerify`. До candidate build
publisher либо сам выполняет Full gate и создаёт receipt, либо проверяет уже
существующий receipt по exact SHA, clean `main`, freshness, verifier hash и полному
списку обязательных gates.

VPS и FRP не изменялись. Backend, frontend, ComfyUI, Ollama, SQLite и media остаются
на локальном Windows-компьютере.

## Что реализовано

### Exact-SHA verification receipt

Добавлен `tools/release_verification_receipt.py`:

- receipt version/type, уникальный ID и полный Git SHA;
- только clean branch `main`;
- режим `Full` или `CI`;
- timestamps и максимальный TTL 4 часа;
- обязательные py-compile/map/inventory/pytest/frontend gates;
- для Full дополнительно live backend preflight, listener contract и source snapshot;
- SHA-256 текущего `tools/verify.ps1`;
- canonical payload digest и atomic write только в `.runtime/verification`;
- повторная проверка SHA, branch, dirty state, expiry, gates, digest, Python version
  и verifier hash перед candidate build.

`tools/verify.ps1 -ReceiptPath` отказывается работать в Quick mode, вне canonical
directory, поверх существующего receipt, на dirty checkout или не на `main`.

Использованный production receipt:

| Поле | Значение |
|---|---|
| Receipt ID | `07528be0aa53-20260717212726-004d1ececcbd` |
| Mode | `Full` |
| Git SHA | `07528be0aa53166418f312cbe4586f351a0e2715` |
| Gates | 12 |
| Completed UTC | `2026-07-17T21:27:26.428230Z` |
| Expires UTC | `2026-07-18T01:27:26.428230Z` |
| Receipt file SHA-256 | `sha256:43304e33f608341d25e21f1a96c8c0b015f471e6e9e9756e789433752cc9ed66` |

Active frontend manifest содержит путь и hash локального evidence. Публичный
`release.json` содержит только release/SHA, verification kind/mode и evidence hash;
локальный путь, operator и reason туда не попадают.

### Transactional frontend activation

Candidate по-прежнему создаётся в новом immutable directory и проходит browser
smoke на 5197. Новый порядок activation:

1. подготавливается, но не активируется новый manifest;
2. проверяется ownership listener 5173;
3. запускается новый release и проверяется exact release meta;
4. только после readiness выполняется atomic manifest move;
5. при ошибке новый process/candidate удаляется, старый manifest остаётся активным,
   предыдущий listener сохраняется либо запускается повторно;
6. retention cleanup после успешной activation не может превратить готовый release
   в ложный failure.

Backend failure после frontend activation по-прежнему вызывает отдельный
`rollback-frontend-release.ps1` из `start-public.bat`.

### Audited break-glass

`tools/publish-frontend-release-break-glass.ps1` требует:

- operator;
- reason не короче 20 символов;
- точное acknowledgement `I_ACCEPT_UNVERIFIED_RELEASE_RISK`;
- clean `main` и полный SHA.

Команда создаёт single-use authorization на 10 минут и должна записывать
`requested` плюс `completed|failed` в
`.runtime/audit/release-break-glass/release-break-glass.jsonl`. Она запускает весь
штатный `start-public.bat`, а не только frontend, и может объявить успех только при
совпадении active frontend/backend release IDs.

Production break-glass намеренно не использовался. Проверены PlanOnly, отсутствие
side effects, обязательное acknowledgement и source contracts. Реальный emergency
audit появится только при осознанном аварийном использовании.

## Хронология проверки и выпуска

1. Characterization tests сначала зафиксировали отсутствующие receipt,
   break-glass и activation rollback contracts.
2. Основной REL-001 commit `3747ee1` прошёл focused 38/38 пять раз и полный
   CI-mode gate 1505/1505.
3. Exact-SHA Full gate создал receipt для `3747ee1`: 1505/1505, live source snapshot
   стабилен.
4. Первая штатная публикация остановилась сразу после receipt validation:
   launcher Windows PowerShell не предоставил `Get-FileHash`. Candidate directory
   не создавался, frontend/backend release и PIDs не менялись, health оставался 200.
5. `07528be` заменил cmdlet на .NET SHA-256. Тест извлекает эту функцию из реального
   publisher и исполняет её в Windows PowerShell 5.1; hash совпал побайтно.
6. Corrected focused suite 39/39 прошёл пять раз.
7. Новый exact-SHA Full receipt gate прошёл 1506/1506; три safe-window snapshot
   показали active jobs 0, preparing publications 0, ComfyUI 0/0, API connections 0.
8. Штатный `start-public.bat` принял receipt и активировал release
   `07528be0aa53-20260718002811`.

Первый отказ является доказательством fail-closed поведения: active release
`2e447828be09-20260717233010`, frontend PID 34620 и backend PID 46484 сохранились,
candidate directories с префиксом `3747ee1` не осталось.

## Точные проверки

| Проверка | Результат |
|---|---|
| Первичный REL-focused | 38 passed ×5 |
| Windows compatibility REL-focused | 39 passed ×5 |
| Full CI-mode до implementation commit | 1505 passed, 92 warnings, 435.70 s |
| Full receipt gate `3747ee1` | 1505 passed, 92 warnings, 436.26 s; source stable |
| Final Full receipt gate `07528be` | 1506 passed, 92 warnings, 441.34 s; source stable |
| Post-deploy Quick | 69 passed, 33.11 s; source stable |
| Architecture inventory drift | PASS |
| Frontend lint/build | PASS |
| Release/origin/browser resilience | PASS |
| Остаточные pytest processes | 0 |

Post-deploy evidence:

- active frontend/backend release: `07528be0aa53-20260718002811`;
- backend listener PID 49468, exact project-venv parent PID 45576;
- frontend PID 14784 обслуживает только новый immutable directory;
- `/`, `/feed`, `/gallery`, `/api/health`, `/api/version`: HTTP 200 локально и через
  `https://izo.alikinas.ru`;
- root meta, feed/gallery headers, backend/frontend identity и full SHA совпадают;
- `/api/generate`, `/api/gallery`, `/api/me-v2` без сессии: HTTP 401;
- startup log: application startup complete, 0 error/traceback/conflict matches;
- ComfyUI queue 0/0; optional 8001 отсутствует;
- rollback PlanOnly указывает на сохранённый предыдущий release;
- break-glass PlanOnly не создал audit file;
- известное предупреждение Ollama `:::11434` остаётся OPS hardening item.

## GitHub CI

Exact deployed SHA run `29614346436`, job `87996034524`, завершился без runner:
steps 0. Annotation сообщает failed recent account payments либо необходимость
увеличить spending limit. Поэтому CI-001 остаётся `BLOCKED EXTERNALLY`; это не
code-test failure и не зелёный CI.

## Impact и остаточный риск

- Schema/API/auth/tasks: изменений нет.
- Production DB/media: тестами и publisher не изменялись.
- Secrets: receipt и release metadata secret-free; break-glass operator/reason
  остаются только в локальном audit.
- Receipt/audit — локальное integrity evidence, а не криптографически подписанная
  удалённая attestation; независимое хранение относится к CI-001/observability.
- Frontend всё ещё работает через Vite Preview; следующий пакет EDGE-001 заменяет
  его локальным Caddy без изменения VPS.
- Backend source пока загружается из mutable checkout; immutable backend artifact и
  A/B drain/rollback относятся к REL-002.

Documentation-only commit этого checkpoint не требует restart. Развёрнутый
application/tooling code остаётся exact `07528be`.
