# IZO ASA — backup и restore runbook для текущего Windows production

Дата проверки: 2026-07-14

## Что защищает этот backup

Backup сохраняет два источника пользовательских данных:

1. Live SQLite из `DATABASE_URL` либо `backend/onenode.sqlite3`.
2. Всё дерево `MEDIA_DIR` либо `backend/media` с сохранением относительных путей.

SQLite снимается только через `sqlite3.Connection.backup()`. Обычное копирование
открытых `.sqlite3`, `-wal` и `-shm` не используется. Копия проходит
`PRAGMA quick_check`, получает SHA-256 и записывается в отдельный snapshot.

Media хранится по SHA-256 в общем `media-objects`. Manifest каждого snapshot
содержит относительный путь, размер и checksum. Одинаковые файлы физически
сохраняются один раз; последующие снимки копируют только новые content objects.
Финальный `COMPLETED` содержит SHA-256 manifest и создаётся последним.

В этот backup намеренно не входят:

- Git repository — он восстанавливается из GitHub;
- `backend/.env`, токены Telegram/MAX и другие plaintext secrets;
- CurrentUser DPAPI OpenRouter document — он не переносим на другой Windows account;
- ComfyUI/Ollama installations и модели;
- VPS и tunnel configuration.

Следовательно, backup содержит пользовательскую БД и изображения, но не является
полным образом компьютера. На новом ПК программы, модели и секреты настраиваются
отдельно, после чего восстанавливаются БД и media.

## Текущая конфигурация

Production sources находятся на физическом диске `D:` (`ST8000NM017B-2TJ103`,
SATA). Backup target находится на другом физическом диске `I:`
(`ST1000LM 035-1RK172`, USB).

Внешний config:

```text
%LOCALAPPDATA%\IZO_ASA\backup.json
```

Он содержит только version и `backup_root=I:\IZO_ASA_Backups`, не содержит
секретов и не входит в Git. Скрипт production-backup отказывается использовать
тот же drive letter, где находятся live DB или media.

Создание config на новом компьютере выполняется один раз:

```powershell
python tools/backup_production.py --create-config --backup-root "I:\IZO_ASA_Backups"
```

Команда не перезаписывает существующий config. Если backup-диск получил другую
букву, нужно осознанно создать новый config после проверки физического диска.

## Ручной backup

Сначала read-only plan:

```powershell
python tools/backup_production.py --plan
```

Ожидается `BACKUP_PLAN_OK` с разными `sourceDrive` и `targetDrive`. Затем:

```powershell
python tools/backup_production.py
```

Успех обозначается только строкой `BACKUP_OK`. Каталог без корректного
`COMPLETED` не является восстановимым snapshot и игнорируется restore tool.

Backend останавливать не нужно: SQLite Backup API создаёт согласованный снимок
при работающем WAL. Media-файл, изменившийся во время чтения, повторяется до трёх
раз; нестабильный файл завершает операцию ошибкой вместо фиксации смешанной версии.

## Проверка и restore rehearsal

Полная проверка последнего snapshot без восстановления:

```powershell
python tools/restore_backup.py --verify-only
```

Безопасная rehearsal создаёт временную отдельную БД/media, проверяет их и удаляет:

```powershell
python tools/restore_backup.py --rehearse
```

Восстановление в постоянный новый пустой каталог:

```powershell
python tools/restore_backup.py --destination "C:\IZO_ASA_restore\2026-07-13"
```

Tool никогда не заменяет live `DATABASE_URL`/`MEDIA_DIR`, отказывается писать в
непустой каталог и не разрешает destination внутри backup root. После успеха в
destination находятся `database.sqlite3`, `media` и `RESTORE_COMPLETED`.

## Перенос или аварийное восстановление

1. Клонировать GitHub repository и установить зафиксированные зависимости.
2. Установить/проверить ComfyUI, Ollama и необходимые модели отдельно.
3. Подключить backup-диск и создать внешний backup config.
4. Выполнить `--verify-only`, затем restore в новый пустой каталог.
5. Не запуская два backend одновременно, остановить старый backend контролируемо.
6. Сохранить повреждённые/старые live DB и media отдельно; не удалять их сразу.
7. Указать `DATABASE_URL` и `MEDIA_DIR` на восстановленные данные либо согласованно
   перенести восстановленные файлы в production paths.
8. Запустить один backend, проверить health, DB ready, models, gallery/feed и
   private-media ownership.
9. Заново ввести/rotated OpenRouter key под целевым Windows account; DPAPI-файл
   со старого ПК не копировать как рабочий secret.
10. Только после live smoke возвращать публичный трафик.

Автоматическая подмена live-файлов специально не реализована: выбор момента
остановки и rollback-копии должен оставаться явной операторской операцией.

## Текущие доказательства

На 2026-07-14 созданы пять completed snapshot. Последний создан перед B7a
startup reconciliation:

```text
snapshot=20260713T221737.032822Z
databaseBytes=565104640
mediaFiles=2394
mediaBytes=244742470
copiedObjects=9
reusedObjects=2385
```

Для него независимо успешны `BACKUP_VERIFY_OK`, SQLite `quick_check`, checksum
pipeline и `BACKUP_REHEARSAL_OK`. После операции production сохранил один listener
и health/database ready. Последующий controlled B7a restart поднял PID 484; snapshot
остался проверенной точкой отката до единственной recovery/refund mutation.

## Автоматизация и offsite

Новый operations-пакет с Task Scheduler, role guard, health state, безопасной
публикацией через Яндекс.Диск и STANDBY rehearsal описан в
`docs/yandex-disk-backup-runbook-20260716.md`.

Автоматический retention по-прежнему выключен до недельного испытания. Сквозное
шифрование пользовательских media также требует отдельного решения владельца и
recovery-key runbook; ключ нельзя хранить рядом с backup.
