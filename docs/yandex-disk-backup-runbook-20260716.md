# IZO ASA: резервирование через Яндекс.Диск

Дата реализации: 2026-07-16

## Статус

Репозиторий содержит полный безопасный контур подготовки и переноса резервных
снимков. Рабочая SQLite никогда не копируется в Яндекс.Диск: сначала
`sqlite3.Connection.backup()` создаёт согласованный локальный snapshot, затем
проверяются `PRAGMA quick_check`, размеры и SHA-256, и только после этого готовый
снимок публикуется в синхронизируемую папку.

Текущий production-компьютер обнаружен как `D2-R2-X`; он является кандидатом на
роль `PRIMARY`, потому что из канонического каталога
`D:\Google Drive\My progact\Генератор картинок` запускается writing backend.
Имя `STANDBY`, выделенный аккаунт Яндекса и наличие Яндекс 360 владелец ещё не
зафиксировал. До этого установщик задач не запускался.

На текущем компьютере:

- live database: `backend\onenode.sqlite3`, 565104640 байт на момент проверки;
- live media: `backend\media`;
- прежний локальный backup: `I:\IZO_ASA_Backups`;
- `cldflt`: запущена, Automatic;
- Яндекс.Диск 4.21.2.4570 установлен и после входа запустился;
- одновременно запущен legacy-клиент `YandexDisk2.exe` версии 3.2.48.5157;
- `disk.yandex.ru:443` доступен, но маршрут сейчас идёт через `AdGuard VPN`;
- `E:`: FAT32 около 10 ГБ, поэтому путь из ТЗ `E:\Yandex.Disk` здесь использовать
  нельзя;
- `I:`: NTFS, но это USB-носитель и он не подходит как корень Яндекс.Диска по ТЗ.

Облачная и standby-проверка физически не считаются завершёнными, пока снимок не
появился на втором компьютере и там не прошёл rehearsal.

Одновременный запуск legacy-клиента и Диска 4 является текущим блокером. Скрипты
fail closed: cloud staging и установка расписания откажутся продолжать, пока
`YandexDisk2.exe` активен. Клиент не был автоматически остановлен или удалён,
поскольку сначала нужно подтвердить, какую папку и аккаунт он обслуживает.
Маршрут через AdGuard VPN — второй блокер: stage/install также fail closed до
настройки split tunneling для Яндекс.Диска. Backend, Telegram, Codex и FRP эти
скрипты из VPN не исключают и сетевые настройки сами не меняют.

## Компоненты

- `tools/backup_production.py` — plan и локальный согласованный snapshot.
- `tools/restore_backup.py` — verify, rehearsal и restore в пустой каталог.
- `tools/backup_transport.py` — публикация готового snapshot и приём в ReplicaCache.
- `ops/backup/run_local_backup.ps1` — PRIMARY-цикл с lock, plan, backup, verify и health.
- `ops/backup/stage_cloud_backup.ps1` — почасовая публикация в Яндекс.Диск.
- `ops/backup/receive_cloud_backup.ps1` — получение на STANDBY и rehearsal.
- `ops/backup/check_backup_health.ps1` — freshness/process/space health.
- `ops/backup/install_backup_automation.ps1` — конфигурация и Task Scheduler.
- `ops/backup/check_server_role.ps1` — запрет writing backend на STANDBY.

`start-public.bat` вызывает role guard. Если `server-role.json` отсутствует, текущий
запуск сохраняет обратную совместимость. Если файл существует и роль не PRIMARY,
writing backend не стартует.

## Формат данных

Локально:

```text
<backup_root>\
  snapshots\<snapshot_id>\
    database.sqlite3
    manifest.json
    COMPLETED
  manifests\<snapshot_id>.json
  media-objects\<sha-prefix>\<sha256>
```

В Яндекс.Диске:

```text
IZO_ASA_ServerBackup\
  database\snapshots\<snapshot_id>\
    database.sqlite3
    COMPLETED
  recovery\manifests\<snapshot_id>.json
  data\media-objects\<sha-prefix>\<sha256>
```

`COMPLETED` содержит SHA-256 manifest и создаётся последним. Повторная публикация
завершённого снимка только проверяет его и не изменяет. `.env`, `-wal`, `-shm`,
ключи, токены и credentials не входят ни в manifest, ни в transport.

## Подготовка PRIMARY

1. Установить официальный Яндекс.Диск 4.x и подтвердить тариф Яндекс 360.
2. Войти в выделенный аккаунт, включить 2FA и автозапуск.
3. Выбрать корень на постоянном внутреннем NTFS-диске и режим «Хранить на компьютере».
4. Убедиться, что `YandexDisk4.exe` запущен и синхронизация не на паузе.
5. Выбрать отдельный локальный backup root. Он не должен быть на диске live DB/media.
6. Запустить установщик из PowerShell с правами администратора:

```powershell
& '.\ops\backup\install_backup_automation.ps1' `
  -Role PRIMARY `
  -YandexRoot 'F:\Yandex.Disk\IZO_ASA_ServerBackup' `
  -BackupRoot 'I:\IZO_ASA_Backups'
```

Установщик проверяет NTFS, фиксированный диск для Яндекс.Диска, наличие live DB,
media и Python, затем создаёт:

```text
C:\IZO_ASA\config\server-role.json
C:\IZO_ASA\config\backup.json
C:\IZO_ASA\config\backup-operations.json
C:\IZO_ASA\runtime\*.ps1
C:\IZO_ASA\health\backup-current.json
```

Перед записью можно выполнить ту же команду с `-WhatIf`.

## Расписание PRIMARY

- `IZO_ASA Local Backup 15m`: каждые 15 минут и при старте Windows с задержкой 5 минут.
- `IZO_ASA Cloud Stage Hourly`: один раз в час.
- `IZO_ASA Backup Health 10m`: каждые 10 минут.
- ошибки задания повторяются через 5 минут, максимум три раза;
- параллельный локальный backup блокируется lock-файлом;
- retention автоматически не включён.

Задания выполняются от интерактивного Windows-пользователя: это необходимо для
пользовательского приложения Яндекс.Диск. После перезагрузки требуется вход этого
пользователя или отдельно согласованный безопасный автологин.

## Подготовка STANDBY

На втором компьютере установить тот же Яндекс.Диск и дождаться полной локальной
синхронизации, затем:

```powershell
& '.\ops\backup\install_backup_automation.ps1' `
  -Role STANDBY `
  -YandexRoot 'D:\Yandex.Disk\IZO_ASA_ServerBackup' `
  -ReplicaCache 'E:\IZO_ASA_ReplicaCache' `
  -RehearsalRoot 'E:\IZO_ASA_RestoreTest'
```

STANDBY получает снимок в отдельный ReplicaCache, проверяет все SHA-256 и SQLite,
и только потом создаёт локальный `COMPLETED`. Ежедневное задание выполняет полное
восстановление во временный каталог. Автозапуск backend, FRP и запись обратно в
облачный backup не настраиваются.

## Ручные проверки

PRIMARY:

```powershell
& 'C:\IZO_ASA\runtime\run_local_backup.ps1'
& 'C:\IZO_ASA\runtime\stage_cloud_backup.ps1'
& 'C:\IZO_ASA\runtime\check_backup_health.ps1'
```

STANDBY:

```powershell
& 'C:\IZO_ASA\runtime\receive_cloud_backup.ps1'
& 'C:\IZO_ASA\runtime\receive_cloud_backup.ps1' -Rehearse
& 'C:\IZO_ASA\runtime\check_backup_health.ps1'
```

Допустимые признаки успеха: `LOCAL_BACKUP_CYCLE_OK`, `CLOUD_STAGE_OK`,
`REPLICA_RECEIVE_OK ... rehearsal=ok`, `BACKUP_HEALTH_OK`.

## Health и аварийное восстановление

`C:\IZO_ASA\health\backup-current.json` получает время последнего local/verified/
cloud/replica события, snapshot id, размеры, SHA manifest, доступность Яндекс.Диска,
свободное место и список ошибок. PRIMARY переходит в ATTENTION при local старше
30 минут или cloud stage старше 90 минут; STANDBY — при replica старше 120 минут.
Одновременный запуск `YandexDisk2.exe` также всегда даёт ATTENTION.

## Последняя локальная проверка

На 2026-07-16 выполнен production-safe цикл без остановки backend:

```text
BACKUP_PLAN_OK databaseBytes=565104640 mediaFiles=2436 mediaBytes=260170702
BACKUP_OK snapshot=20260716T005805.698960Z copiedObjects=96 reusedObjects=2340
BACKUP_VERIFY_OK snapshot=20260716T005805.698960Z
BACKUP_REHEARSAL_OK snapshot=20260716T005805.698960Z
```

Это подтверждает локальный RPO-снимок и восстановимость на `I:`, но не заменяет
испытание реальной синхронизации и второго компьютера.

Health-файл не является распределённой блокировкой. При аварии оператор обязан
сначала физически исключить возвращение старого PRIMARY, выполнить verify и restore
в новый пустой каталог, проверить приложение и только затем вручную переключать
публичный трафик. Автоматического failover без fencing нет.

## Retention

Автоматическое удаление намеренно отсутствует до недельного испытания. Это
соответствует ТЗ: удаление в синхронизируемой папке распространяется на облако и
STANDBY. После пяти успешных циклов и недели наблюдения retention реализуется
отдельным изменением с защитой последнего и минимум трёх проверенных снимков.

## Персональные данные и шифрование

Пользовательские изображения в этой схеме попадают в Яндекс.Диск без отдельного
end-to-end encryption. До production offsite владелец должен либо явно принять
этот режим хранения, либо выбрать проверенное клиентское шифрование. Собственный
криптоалгоритм не разрабатывается; recovery key хранится отдельно от Яндекс.Диска.

Официальные ограничения клиента сверены по документации Яндекса:

- [установка и требование тарифа Яндекс 360](https://yandex.ru/support/yandex-360/customers/disk/4/windows/ru/start);
- [размещение sync-папки и параллельная работа версий 3/4](https://yandex.ru/support/yandex-360/customers/disk/4/windows/ru/synchronization/folder).

## Критерий завершения физического внедрения

Кодовая реализация готова, но эксплуатационная работа завершается только после:

1. подтверждения PRIMARY, STANDBY и выделенного Яндекс-аккаунта;
2. проверки Яндекс 360 и свободного места;
3. пяти циклов backup → stage → sync → receive → verify;
4. успешного rehearsal на STANDBY;
5. проверки перезапуска обоих компьютеров и восстановления после обрыва интернета;
6. фиксации фактических RPO/RTO в итоговом отчёте.
