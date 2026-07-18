# EDGE-001 — checkpoint локального Caddy edge

- Дата: **2026-07-18**
- Статус: **CODE COMPLETE, NOT DEPLOYED**
- Implementation commits: `c278fa5315a3de917b8b778111c1ef4ded581364`,
  `01fd5ab8e7bc16ca43608f4c2c5411e70e22ab79`
- GitHub: оба commit находятся в `origin/main`
- Текущий live release: `07528be0aa53-20260718002811`
- Текущий live frontend: Vite PID 14784 на `127.0.0.1:5173`

## Итог текущего пакета

Production edge реализован в коде, тестах и runbook, но намеренно ещё не включён.
Normal publisher и exact-SHA receipt требуют clean branch `main`. В канонической
папке параллельно находится незакоммиченный mail/UniSender WIP, поэтому обходить
release guard, временно прятать пользовательские файлы или разворачивать из
вспомогательного worktree запрещено.

VPS, FRP, домен, backend, ComfyUI, Ollama, SQLite и media не изменялись. Текущая
топология транспорта остаётся:

`izo.alikinas.ru -> VPS/FRP -> 127.0.0.1:5173`.

EDGE-001 меняет только будущего локального владельца порта 5173 с Vite Preview на
Caddy; VPS/FRP продолжит направлять трафик на тот же loopback port.

## Что реализовано

### Закреплённый runtime

- официальный Caddy `2.11.4`;
- release URL: `https://github.com/caddyserver/caddy/releases/tag/v2.11.4`;
- archive SHA-256:
  `1708333f79e274c7697285afe6d592ab39314e0b131e9ec6bea08ad27df62ebf`;
- executable SHA-256:
  `5cb9ab71e5756ce72840b8234177a2f40c8b4ab47a806b8e841e2b784e9df62b`;
- project-local install `.tools/caddy/2.11.4/caddy.exe`, без глобального PATH;
- installer сначала проверяет archive hash, затем executable hash и version.

### Edge contract

- bind только `127.0.0.1`;
- production port 5173/admin 2019, candidate port 5197/admin 2020;
- разрешены только Host `izo.alikinas.ru`, `127.0.0.1`, `localhost`; остальные
  получают 421;
- `/api`, `/media`, `/feed`, `/gallery`, `/static` принадлежат backend 8000;
- остальные пути обслуживаются из immutable frontend release с SPA fallback;
- HTML получает `no-store`, hashed assets — годовой immutable cache;
- gzip/zstd, security headers, 128 MiB request body limit и bounded timeouts;
- access/runtime logs — JSON с rotation; Authorization, Cookie и чувствительные
  query keys удаляются до записи.

### Release и rollback

- candidate Caddy валидируется и запускается на 5197;
- normal activation использует graceful reload, а не kill/restart;
- первая миграция распознаёт только канонический Vite listener, останавливает его
  после candidate smoke и при activation failure восстанавливает прежний release;
- неизвестный владелец 5173 блокирует действие;
- active manifest меняется только после exact release readiness;
- rollback сначала проверяет candidate и запрещает frontend/backend release
  mismatch; атомарный API A/B rollback относится к REL-002;
- `stop-public.bat` останавливает только доказанно принадлежащие проекту Caddy и
  backend; FRP не трогает.

## Проверки

| Проверка | Результат |
|---|---|
| Caddy focused contracts/integration/publisher/launchers/inventory/verify | **47 passed ×5** |
| Реальный candidate Caddy 5197 поверх active release | PASS; `/`, `/feed`, `/gallery`, `/profile`; blocked Host 421 |
| Pinned binary/config validation | PASS; version и SHA-256 совпадают |
| Hermetic PlanOnly correction | **2 passed ×5** в canonical и PASS в detached audit |
| Clean SHA `01fd5ab` pytest | **1514 passed**, 92 известных warnings, 484.02 s |
| Frontend lint | PASS |
| `tsc -b && vite build` | PASS |
| Release identity/origin isolation/studio resilience | PASS |
| GitHub Actions | run `29647536931`, job `88088183806`, **0 steps**; внешний billing blocker |

Первый clean audit `c278fa5` обнаружил два негерметичных PlanOnly-теста: они читали
локальный `.runtime/active-frontend.json`, отсутствующий в clean checkout. После
исправления detached audit прошёл 1514 tests и все frontend/browser stages. Его
финальный global process guard корректно отказался выдать общий success, потому что
в канонической папке одновременно шёл отдельный mail pytest PID 58520/63460. Этот
процесс не был дочерним процессом EDGE verifier и позднее завершился `1420 passed`.

Receipt не создавался и статус `VERIFIED` не выставлялся.

## Deployment closure

После отдельного завершения и commit mail/UniSender WIP требуется:

1. подтвердить clean `main == origin/main`, отсутствие pytest и активных jobs;
2. выполнить Full/CI verifier на точном объединённом SHA с новым receipt;
3. штатно запустить `start-public.bat` с этим receipt;
4. подтвердить, что 5173 принадлежит pinned Caddy, а 5197/5198/2020 свободны;
5. проверить local и public `/`, `/feed`, `/gallery`, `/api/health`, `/api/version`,
   auth-required 401, Host allow/block, headers, cache, compression и redacted logs;
6. выполнить post-deploy Quick, source snapshot и process leak checks;
7. записать новый release ID, Caddy/backend PID, receipt hash и результаты в этот
   checkpoint и master plan; только затем поставить `VERIFIED`.

## Остаточный риск

- Live пока не изменён и продолжает работать через Vite Preview.
- Windows service/autostart/restart policy остаётся OPS-001.
- Backend immutable A/B slots, drain и full-stack atomic rollback остаются REL-002.
- CI-001 остаётся внешне заблокирован GitHub billing/spending configuration.
- Параллельный mail/UniSender WIP не входит в EDGE commits и должен получить свой
  отдельный review/test/commit.
