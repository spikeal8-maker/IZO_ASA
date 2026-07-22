# IZO_ASA — handoff текущего Windows-компьютера

- Дата: 2026-07-22
- Пакет: `FINALIZE-MIGRATION-001`
- Source baseline перед handoff-commit:
  `da104e17b8156fbe86424309bc6850a4b0344caa`

Этот документ описывает перенос исходного кода и локального runtime. Он не
содержит секретов и не разрешает менять VPS, FRP, DNS или tunnel. Exact final
main SHA, production release ID, backup manifest и live evidence записываются в
`D:\IZO_ASA_TRANSFER\handoff\FINAL-MIGRATION-REPORT.md` после всех гейтов.

## 1. Источники истины

- Canonical workspace:
  `D:\Google Drive\My progact\Генератор картинок`.
- Единственная integration/deploy ветка: `main`.
- Git remote: `https://github.com/spikeal8-maker/IZO_ASA.git`.
- Правила: `AGENTS.md`.
- Текущий backlog: `docs/engineering-optimization-master-plan-20260719.md`.
- Архитектура: `docs/system-overview.md`, `architecture/contract.json` и
  generated inventories.
- Backup/restore: `docs/backup-restore-runbook-20260713.md`.
- Release: `docs/public-launch.md`.

Не deploy из sibling worktree, symlink target, attachment или временной копии.

## 2. Что закреплено в main

Merged PR до финального handoff: #1, #2, #3, #4, #6, #7, #8, #9 и #10.

Ключевой новый baseline:

- trusted session/CSRF boundary;
- modular bot routers, services and worker runtime;
- Studio Wave 1 modules;
- Gallery/Studio → «Оживить» → `image_to_video` handoff;
- repository operation lock, generated maps and verification gates.

Из PR #5 перенесён только `docs/system-overview.md`; он актуализирован на
текущий source baseline. Старый draft сохранён тегом
`archive/system-overview-draft-20260719`, а PR #5 закрывается как superseded.

Коммиты `38a76ba` и `0ac4eab` не переносились: первый противоречит действующей
градации Quick/CI/Full, второй перекрыт более новым `docs/current-status.md`.
Оба сохранены тегом `archive/main-local-docs-20260721` и all-refs bundle.

## 3. Archive ledger и branch cleanup

Опубликованные archive tags сохраняют точные неслитые вершины:

| Материал | Archive tag |
|---|---|
| local AUTH docs/checkpoint | `archive/main-local-docs-20260721` |
| Studio pre-repair checkpoint | `archive/fe-studio-001a-checkpoint-20260721` |
| gallery patch-equivalent source | `archive/gallery-handoff-patch-equivalent-20260719` |
| profile redesign WIP | `archive/profile-redesign-wip-20260719` |
| old new UI tips | `archive/new-ui-v2-*` |
| experimental CSRF repair | `archive/auth-csrf-repair-001b-20260720` |
| security source tip | `archive/security-hardening-patch-equivalent-20260719` |
| optimization-plan source | `archive/optimization-plan-source-20260720` |
| original overview draft | `archive/system-overview-draft-20260719` |
| detached face-slider WIP | `archive/face-slider-wip-20260711` |
| nine historical stashes | `archive/stash-*` |

После verified bundle, merged docs, successful deploy и green Full cleanup
удаляет local/remote feature, arch, auth, product, docs, agent, hotfix, backup и
temporary handoff branches. Additional clean worktrees удаляются только после
проверки их exact HEAD против main/archive tag. Итоговая ветка — только `main`;
архивы остаются в published tags и bundle.

## 4. Текущие ratchet budgets

| Path | Lines | Maximum |
|---|---:|---:|
| `backend/main.py` | 19 521 | 19 521 |
| `frontend/src/newUi.tsx` | 3 628 | 3 628 |
| `frontend/src/LegacyApp.tsx` | 3 600 | 3 700 |
| `frontend/src/newUi.css` | 3 096 | 3 200 |
| `frontend/src/newStudioV3.css` | 5 876 | 6 000 |

Budget нельзя повышать для прохождения gate. После extraction его снижают в том
же commit.

## 5. Проверка source и release

Targeted documentation gate:

```powershell
git diff --check
python tools/generate_backend_map.py --check
python tools/generate_architecture_inventory.py --check
node tools/generate_frontend_map.mjs --check
python -m pytest -q tools/test_context_docs.py tools/test_generate_architecture_inventory.py
```

Release candidate:

```powershell
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\tools\verify.ps1 -Mode CI -ReceiptPath <receipt>
cmd.exe /d /c start-public.bat
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\tools\check-runtime-listeners.ps1 -RepoRoot .
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\tools\check-caddy-edge.ps1 -RepoRoot . -PublicBaseUrl https://izo.alikinas.ru
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\tools\verify.ps1 -Mode Full
```

Не запускать второй Full/publisher. `CODE COMPLETE`, `DEPLOYED`, `VERIFIED` и
`OPERATIONALLY VERIFIED` фиксируются отдельно.

## 6. External runtime snapshot

Проверено на текущем компьютере:

- Windows 11 Pro, build 26200;
- Python 3.11.9 в project `.venv`;
- Node.js 24.14.1, npm 11.12.1;
- Git 2.55.0.windows.3;
- Caddy 2.11.4 из repository-pinned runtime;
- Ollama 0.32.1 и локальный model store вне Git;
- ComfyUI v0.19.3, local checkout/custom nodes/models вне Git;
- listeners: Caddy 5173, API 8000, optional Qwen ASR 8001, ComfyUI 8188,
  Ollama 11434; все application listeners loopback-only;
- production data: `backend/onenode.sqlite3` и `backend/media`, оба вне Git;
- ComfyUI model directories и Ollama models восстанавливаются отдельно.

Полные Ollama model names, ComfyUI custom nodes, executable paths, GPU/driver,
listener owners и final release identifiers находятся в transfer-файле
`external-runtime-inventory.txt`.

## 7. Что находится вне Git

- production SQLite и media;
- `.env`/environment overrides;
- Windows CurrentUser DPAPI documents;
- ComfyUI, custom nodes, workflows and models;
- Ollama model store;
- optional Qwen ASR environment/cache;
- Caddy runtime binary cache and active release artifacts;
- local/offsite backup roots;
- external FRP/tunnel configuration and provider account state.

GitHub восстанавливает source, но не эти данные. VPS/tunnel в этом handoff не
изменяются.

## 8. Секреты: только имена

Environment/runtime secret names:

- `SESSION_HMAC_SECRET`;
- `RUNTIME_SYNTHETIC_KEY`;
- `OPENROUTER_API_KEY`;
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`;
- `MAX_BOT_TOKEN`, `MAX_WEBHOOK_SECRET`;
- `YOOKASSA_SECRET_KEY`;
- `SMTP_PASSWORD`;
- `UNISENDER_API_KEY`.

DPAPI entry names:

- `openrouter_api_key`;
- `telegram_bot_token`, `telegram_webhook_secret`;
- `max_bot_token`, `max_webhook_secret`;
- `yookassa_secret_key`;
- `smtp_password`;
- `unisender_api_key`.

Значения не копировать в Git, transfer report или chat. CurrentUser DPAPI
привязан к Windows account и компьютеру: на новом ПК все записи вводятся заново
или credentials осознанно ротируются.

## 9. Порядок восстановления на новом ПК

1. Установить Git, Python 3.11, Node.js, NVIDIA driver, ComfyUI, Ollama, Caddy
   runtime через repository flow и необходимые внешние tools.
2. Клонировать `main` из GitHub в новый canonical workspace и проверить handoff
   tag/commit.
3. Создать новую `backend/.venv`; установить `backend/requirements.txt`.
4. Выполнить `npm install` в `frontend` из lockfile.
5. Установить ComfyUI custom nodes/models и Ollama/Qwen models по inventory.
6. Проверить официальный backup штатной `restore_backup.py --verify-only`, затем
   восстановить его в новый пустой каталог/rehearsal.
7. Не запуская два backend против одной БД, переключить `DATABASE_URL` и
   `MEDIA_DIR` на согласованно восстановленные данные.
8. Заново ввести environment/DPAPI secrets под production Windows account.
9. Выполнить CI/Full, listener и local smoke без платной генерации.
10. Только после exact-SHA release и public smoke переводить доменный трафик.

Не переносить `.venv` или `node_modules`: они пересоздаются. Не копировать
открытый `onenode.sqlite3`, WAL/SHM обычной файловой командой. SQLite snapshot
создаётся только Backup API, а restore сначала проходит verify/rehearsal.

## 10. Rollback boundary

Старый компьютер остаётся PRIMARY/rollback owner, пока новый хост не прошёл
restore, one-writer check, exact-SHA deploy, local/public smoke и проверку private
media ownership. Автоматический failover не включать без fencing. Реальный
payment, bot, mail или paid-generation flow требует отдельного operator action.
