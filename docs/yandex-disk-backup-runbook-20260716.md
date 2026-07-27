# IZO ASA: резервирование через Яндекс.Диск

Дата реализации: 2026-07-16; bounded retention включён 2026-07-18.

## Статус

Обновление 2026-07-27: прежняя схема hourly/01:00 заменена на отдельный
контролируемый ночной контур. Локальные проверенные снимки создаются каждые
30 минут, а Яндекс.Диск разрешён только в окне 02:00–05:00 Europe/Moscow.
После 05:00 и при входе пользователя guard отключает постоянный автозапуск и
останавливает клиент. Результат первого реального цикла новой схемы должен быть
зафиксирован отдельно; до него offsite-выгрузка считается
`AWAITING_OPERATIONAL_PROOF`.

Репозиторий содержит полный безопасный контур подготовки и переноса резервных
снимков. Рабочая SQLite никогда не копируется в Яндекс.Диск: сначала
`sqlite3.Connection.backup()` создаёт согласованный локальный snapshot, затем
проверяются `PRAGMA quick_check`, размеры и SHA-256, и только после этого готовый
снимок публикуется в синхронизируемую папку.

Текущий production-компьютер обнаружен как `D2-R2-X`; он является кандидатом на
роль `PRIMARY`, потому что из канонического каталога
`D:\Google Drive\My progact\Генератор картинок` запускается writing backend.
Имя `STANDBY`, выделенный аккаунт Яндекса и наличие Яндекс 360 владелец ещё не
зафиксировал. Автоматизация на PRIMARY установлена и проверена 2026-07-16.

На текущем компьютере:

- live database: `backend\onenode.sqlite3`, 565104640 байт на момент проверки;
- live media: `backend\media`;
- локальный backup: `I:\IZO_ASA_Backups` на отдельном USB-диске;
- `cldflt`: запущена, Automatic;
- Яндекс.Диск 4.21.2.4570 установлен и после входа запустился;
- одновременно запущен legacy-клиент `YandexDisk2.exe` версии 3.2.48.5157;
- `disk.yandex.ru:443` доступен, но маршрут сейчас идёт через `AdGuard VPN`;
- Яндекс.Диск 4 имеет `AutoStart=true` и пользовательский startup-guard;
- backup после входа запускается через `HKCU Run` с задержкой 5 минут, поскольку
  создание `ONLOGON`-задачи без административных прав Windows отклоняет;
- interval-задачи: local backup раз в час, cloud stage раз в сутки в 01:00, health
  каждые 10 минут; все окна PowerShell скрыты;
- `database`, `data` и `recovery` закреплены локально; проверка дала `Offline=0`;
- `E:`: FAT32 около 10 ГБ, поэтому путь из ТЗ `E:\Yandex.Disk` здесь использовать
  нельзя;
- `I:`: NTFS, но это USB-носитель и он не подходит как корень Яндекс.Диска по ТЗ.

Облачная и standby-проверка физически не считаются завершёнными, пока снимок не
появился на втором компьютере и там не прошёл rehearsal.

Клиенты 3.x и 4.x используют разные невложенные корни:
`C:\Users\spike\YandexDisk` и `D:\Yandex.Disk`. Поэтому их параллельная работа
допустима; scripts fail closed только при совпадении или вложенности корней.
Маршрут через AdGuard VPN остаётся предупреждением health: локальная публикация
снимка в sync-папку разрешена, но `OverallStatus` остаётся `ATTENTION` до
настройки split tunneling. Backend, Telegram, Codex и FRP скрипты не меняют.

Регистрация задач выполняется через штатный `schtasks.exe`: без повышения прав
задачи создаются для текущего интерактивного пользователя с уровнем `LIMITED`,
а в повышенном PowerShell — с уровнем `HIGHEST`. Установщик не сообщает успех,
пока не перепроверит наличие каждой ожидаемой задачи.

Локальный backup выполняет до четырёх попыток: первая и ещё три повтора с
интервалом 5 минут. Отдельный тест отказа подтвердил повтор и финальный код `2`.

## Первый опубликованный снимок

16 июля 2026 года первый проверенный снимок
`20260716T005805.698960Z` опубликован в
`D:\Yandex.Disk\IZO_ASA_ServerBackup`:

- база: `565104640` байт;
- медиа: `2436` записи, `260170702` байта;
- manifest SHA-256:
  `1fc18bc620ab363e141a9a30cecd3a55a5bceeed8a0654ce9afebd417b75fe88`;
- `verify_cloud_snapshot` и SQLite quick check прошли;
- клиент Яндекс.Диска зафиксировал загрузки с HTTP `201` и cloud reaction.

Физическая проверка на отдельном STANDBY-компьютере всё ещё обязательна до
присвоения всей схеме статуса disaster-recovery ready.

## Контрольный цикл 2026-07-16

Снимок `20260716T154600.223168Z` прошёл:

- `BACKUP_PLAN_OK`, `BACKUP_OK`, `BACKUP_VERIFY_OK`;
- database `565104640` байт, media `2436` файлов / `259231062` байта;
- `CLOUD_STAGE_OK`;
- фактическую отправку Яндекс-клиентом: 100%, HTTP `201`, cloud reaction received;
- получение в отдельный локальный ReplicaCache и rehearsal:
  `REPLICA_RECEIVE_OK ... rehearsal=ok`.

Это подтверждает код и облачную отправку с PRIMARY, но локальный ReplicaCache на
`D2-R2-X` не заменяет скачивание и rehearsal на отдельном STANDBY.

Дополнительно пять опубликованных снимков подряд прошли локальный
receive/verify/rehearsal:

`20260716T005805.698960Z`, `20260716T144711.184843Z`,
`20260716T145202.941221Z`, `20260716T154600.223168Z`,
`20260716T161102.617690Z`.

Focused suite `tools/test_backup_transport.py` + `tools/test_backup_restore.py`
прошёл пять раз подряд по `17 passed`.

## Компоненты

- `tools/backup_production.py` — plan и локальный согласованный snapshot.
- `tools/restore_backup.py` — verify, rehearsal и restore в пустой каталог.
- `tools/backup_transport.py` — публикация готового snapshot и приём в ReplicaCache.
- `tools/prune_backup_snapshots.py` — dry-run и bounded retention без удаления
  общего `media-objects` или посторонних файлов.
- `ops/backup/run_local_backup.ps1` — PRIMARY-цикл с lock, plan, backup, verify и health.
- `ops/backup/run_local_backup_startup.ps1` — задержанный запуск после входа.
- `ops/backup/stage_cloud_backup.ps1` — ночная публикация в Яндекс.Диск.
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

- `IZO_ASA Local Backup 30m`: каждые 30 минут от SYSTEM; свежесть последнего
  проверенного снимка должна быть менее 45 минут.
- `IZO_ASA Yandex Outbound Nightly`: ежедневно в 02:00, только в интерактивном
  пользовательском контексте и только до 05:00.
- `IZO_ASA Yandex Daytime Guard`: ежедневно в 05:00 и при входе пользователя;
  убирает постоянный автозапуск и останавливает `YandexDisk4.exe`.
- `IZO_ASA Backup Health 10m`: каждые 10 минут.
- параллельный локальный backup блокируется lock-файлом; exit code 3 означает
  contention, поэтому outbound ждёт завершения уже запущенного снимка и не
  создаёт второй экземпляр;
- после каждого успешного local/cloud цикла применяется bounded retention.

Задания выполняются скрыто от интерактивного Windows-пользователя: это необходимо
для пользовательского приложения Яндекс.Диск, но окна PowerShell показываться не
должны. После перезагрузки требуется вход этого пользователя или отдельно
согласованный безопасный автологин.

Только `IZO_ASA Yandex Outbound Nightly` размещает новый snapshot в
синхронизируемой папке и создаёт заметный облачный трафик. Локальный backup пишет
на отдельный локальный диск. Health отдельно фиксирует HTTPS-доступность,
интерфейс обычной пробы, наличие application exclusion и наблюдение
process-specific bypass; эти признаки не подменяют друг друга.

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
# Только в разрешённом окне 02:00-05:00:
& 'C:\IZO_ASA\runtime\run_yandex_outbound_nightly.ps1'
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
45 минут или cloud stage старше 30 часов; STANDBY — при replica старше 120 минут.
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

Retention включён с обязательной проверкой newest snapshot до и после удаления:

- локально сохраняются последние точки в 24 часовых, 14 дневных и 8 недельных
  корзинах;
- в Яндекс.Диске сохраняются последние точки в 30 дневных и 12 месячных корзинах;
- latest snapshot сохраняется безусловно;
- незавершённый snapshot удаляется только через 6 часов;
- общий content-addressed `media-objects` не удаляется автоматически;
- dry-run и applied-отчёты записываются в `C:\IZO_ASA\logs\retention-*.json`.

Первичная controlled-очистка 2026-07-18 сохранила 26 локальных снимков и удалила
189 старых/незавершённых snapshot-каталогов, освободив 99,47 ГБ. В облачном корне
сохранены 3 дневных снимка, удалены 50 прежних почасовых/test snapshots; заявленное
освобождение 26,31 ГБ. После очистки latest local повторно прошёл `BACKUP_VERIFY_OK`.

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

На 2026-07-16 пункты 1-6 не закрыты полностью. Реальная облачная квота не
подтверждена: health намеренно хранит `CloudFreeGB=null`, а не подменяет облачную
квоту свободным местом локального диска. Полная перезагрузка PRIMARY не
выполнялась, чтобы не останавливать живой проект без отдельного согласования.
