# IZO_ASA — текущий статус (обновляется каждым пакетом)

Обновлено: 2026-07-20 (AUTH-LEGACY-001A завершён).
Исполняемая очередь: [optimization-and-decomposition-plan-20260720.md](optimization-and-decomposition-plan-20260720.md).
Подробное историческое evidence остаётся в
[engineering-optimization-master-plan-20260719.md](engineering-optimization-master-plan-20260719.md)
и checkpoint-документах; сюда длинные логи, PID и receipts не добавляются.

## Git и release

- Status baseline: `bd7b5ab8e9cbe11e72051560cd3aab833ea3bcb9` — SHA, на
  котором начат активный пакет.
- Authoritative current HEAD: определяется командой `git rev-parse HEAD`
  (не фиксируется здесь, чтобы поле не устаревало после каждого commit).
- Current live release: `263377ff0d5d-20260720115826`
  (backend + frontend identity совпадают; активирован 2026-07-20 через
  locked publisher по exact-SHA receipt).
- Release owner: single-flight через `tools/repository-operation-lock.ps1`
  (`public-release` / `full-verify`); второй параллельный publisher или Full
  verifier физически блокируется.

## Активный и следующий пакет

- Active package: none.
- `AUTH-LEGACY-001A` = `CODE COMPLETE` (route matrix
  [auth-legacy-route-matrix-20260720.md](auth-legacy-route-matrix-20260720.md),
  15 characterization tests; runtime не менялся; deploy не требуется).
- Next package: `AUTH-LEGACY-001B` — НЕ начинать без отдельной команды
  владельца.

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
