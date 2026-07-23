# IZO_ASA — текущий статус (обновляется каждым пакетом)

Обновлено: 2026-07-23 (экстренный AUTH-BOT-P0 code gate зелёный на feature-ветке).
Исполняемая очередь: [optimization-and-decomposition-plan-20260720.md](optimization-and-decomposition-plan-20260720.md).
Подробное историческое evidence остаётся в
[engineering-optimization-master-plan-20260719.md](engineering-optimization-master-plan-20260719.md)
и checkpoint-документах; сюда длинные логи, PID и receipts не добавляются.

## Git и release

- Status baseline: `777bd66f2b2b07594c9dde9f25fd665151efc5d8` — SHA, на
  котором начат активный пакет.
- Authoritative current HEAD: определяется командой `git rev-parse HEAD`
  (не фиксируется здесь, чтобы поле не устаревало после каждого commit).
- Current live release до закрытия пакета: cutover release
  `777bd66f2b2b07594c9dde9f25fd665151efc5d8`; следующий exact SHA фиксируется
  здесь только после controlled promotion и public smoke.
- Release owner: single-flight через `tools/repository-operation-lock.ps1`
  (`public-release` / `full-verify`); второй параллельный publisher или Full
  verifier физически блокируется.

## Активный и следующий пакет

- Active package: `AUTH-BOT-P0-20260723` = `CODE COMPLETE`, `NOT DEPLOYED`.
  - Branch: `agent/auth-reliability-p0-20260723` от `777bd66`.
  - Причины и rollback: [auth-bot-login-reliability-20260723.md](auth-bot-login-reliability-20260723.md).
  - Focused bot/proxy/webhook suite: 54 passed; high-risk selection 9×5;
    frontend smoke/lint/build и desktop/mobile bot-popup E2E — PASS.
  - Quick из secondary worktree дошёл до live Caddy gate и ожидаемо остановился:
    active cutover release не имеет manifest в пути feature-worktree. Clean-SHA
    CI/Full, merge, deployment и real Telegram/MAX acceptance ещё обязательны.
- `AUTH-LEGACY-001B` = `CODE COMPLETE`.
  - Branch: `auth/csrf-001b-clean` (от восстановленного `origin/main`
    `056b736`; экспериментальная `auth/csrf-repair-001b` не сливалась).
  - Code gate: `verify.ps1 -Mode CI` зелёный (1636 passed, все frontend
    gates PASS) на точном SHA `0bbc2c6296b963259fb99a0bf7d455da80762c2e`.
  - Deployment: `NOT DEPLOYED`.
  - Canonical `verify.ps1 -Mode Full`: `PENDING AFTER MERGE` (live-checks
    применимы только из worktree, владеющего запущенным стеком).
- `AUTH-LEGACY-001A` = `CODE COMPLETE` (route matrix
  [auth-legacy-route-matrix-20260720.md](auth-legacy-route-matrix-20260720.md),
  15 characterization tests).
- Next package: `AUTH-LEGACY-001C` — НЕ начинать без отдельной команды
  владельца.

## Процессное правило гейтов

- Feature-worktree: targeted → `verify.ps1 -Mode CI` → draft PR
  (CI гоняет полный pytest + frontend, но пропускает live ownership checks,
  неприменимые к неразвёрнутому secondary worktree).
- Canonical `main` перед deploy: `verify.ps1 -Mode Full` → exact-SHA receipt
  → отдельная явная авторизация deploy владельцем.
- Code commit пушится в `main` только после зелёного Full на чистом
  локальном SHA.

## Завершённые пакеты (VERIFIED)

| Пакет | Дата | Результат |
|---|---|---|
| `GOV-001` | 2026-07-19 | единые правила агентов |
| `REL-LOCK-001` | 2026-07-20 | single-flight release/Full verification |
| `SEC-DIAG-001` | 2026-07-20 | публичные status endpoints product-safe |
| `BOT-TG-001` | 2026-07-20 | polling health Telegram/MAX, live окно 0 ошибок |
| `BACKUP-NET-001` | 2026-07-20 | backup route зелёный, restore rehearsal OK |
| `PLAN-WIP-001` | 2026-07-20 | AUTH-WIP разобран и описан |
| `WIP-ISOLATE-001` | 2026-07-20 | AUTH-WIP сохранён в handoff, worktree чист |
| `PLAN-SYNC-001` | 2026-07-20 | current-status.md, статусы приведены к факту |
| `CTX-001` | 2026-07-20 | context docs + детерминированный frontend map в Quick |

## Отложенные пакеты

- `MAIL-OPS-001` = `DEFERRED_BY_OWNER` (2026-07-20). UniSender-код остаётся
  `DEPLOYED`; реальная доставка не доказывалась. Возобновление — только по
  команде владельца с тем же operator gate.

## Known local WIP / handoff

- `AUTH-LEGACY-001` — НЕ active code package. Незавершённый WIP сохранён в
  `.runtime/handoffs/AUTH-LEGACY-001-20260720-8922e77/`
  (tracked.patch проверен `git apply --check` на base `8922e77`; SHA-256
  каждого файла записан; манифест описывает разбиение на будущие пакеты
  `AUTH-LEGACY-001A/B/D`).
- Чужие worktrees (`_codex_profile_redesign`, `_codex_face_slider_fix`,
  temp feed-watermark) не тронуты и не входят в этот handoff.

## Blockers

- GitHub Actions: внешний billing/spending blocker — каждый run завершается
  с 0 executed steps. Это не ошибка кода; локальные gates обязательны.
- Открытый [PR #5](https://github.com/spikeal8-maker/IZO_ASA/pull/5)
  (docs/system-overview) и ветка
  `agent/security-hardening-uploads-bots-runtime` ждут решения владельца.

## Последние verified gates

- Full receipt: 1578 passed на `263377f` (2026-07-20, перед последним deploy).
- Quick: 88 passed (2026-07-20, после BACKUP-NET-001).
- Focused: polling health 10×5; lock concurrency 9×5; redaction 4×5;
  backup contract 17.
- Backup: health task Last Result 0, `OverallStatus=OK`,
  verify-only + rehearsal restore успешны (2026-07-20).

## Активный пакет 2026-07-24

- `OR-CATALOG-DAILY-001` — `CODE COMPLETE · VERIFIED (CI) · NOT DEPLOYED`, ветка
  `codex/openrouter-catalog-daily-001`.
- Scope: суточное обнаружение/переоценка OpenRouter, durable diff,
  безопасное billing-состояние и отдельная `/admin/openrouter`.
- Focused backend `115 passed`; single-owner worker `5/5`; общий
  `VERIFY_OK mode=CI`, `1665 passed`; frontend lint/build и E2E green.
- Quick runtime gate не является code failure: локальный test-stack держит
  порт 5173 через Vite, тогда как production-contract ожидает Caddy.
- Production release не изменён; deploy/restart не выполнялись.

## Подготовленный пакет уведомлений и соцсетей

- `ADMIN-NOTIFY-SOCIAL-001` —
  `CODE COMPLETE · VERIFIED (CI) · NOT DEPLOYED`.
- Добавлены durable уведомления администратора, OpenRouter-сводки,
  `/admin/notifications`, подготовительная `/admin/social` и идемпотентный
  social outbox.
- Внешние Telegram/VK/Instagram/OK отправки ещё не включены: credentials,
  delivery worker и реальный operator test являются следующим отдельным
  пакетом. Поэтому UI честно показывает `operational=false`.
- Evidence: backend focused `116 passed`, migration/database focused
  `29 passed`, social outbox idempotency `5/5`, `VERIFY_OK mode=CI`,
  `1668 passed`; frontend lint/build/E2E green.
