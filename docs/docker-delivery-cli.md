# IZO_ASA — Docker delivery: read-only plan/doctor и журнал проблем

**Статус:** кандидат пакета DOCKER-DELIVERY-PLAN-001; не инсталлятор, не релиз.
**Программа:** [#238](https://github.com/spikeal8-maker/IZO_ASA/issues/238) → [#247](https://github.com/spikeal8-maker/IZO_ASA/issues/247).
**Исходный main при создании:** 0d134aa20cd0a1d1ca6828622fe6a435c74c415b.
**Проверено на D2-R2:** 27 октября 2026, Windows + Docker Desktop Linux containers.

## 1. Реализованный ограниченный инструмент

tools/docker_delivery_probe.py и tools/docker_delivery_plan.py работают с одним
репозиторием и не дублируют backend, Windows promoter или Docker Shadow runner.
Они подходят для Python 3.11+ на Windows и Linux при наличии Docker CLI.
Операции install, update, backup, restore, rollback, retire **не реализованы**.

- doctor читает выбранный **явный** Docker context: ID двигателя (наружу — только SHA-256),
  OSType, Docker/Compose versions и количество ресурсов целевой установки.
- plan дополнительно читает локальный JSON-манифест и проверяет SHA, immutable
  OCI-digests и диапазон схемы. Для новой свободной установки возвращает READY,
  что означает **готовность плана**, не разрешение на установку.
- plan откажет при существующих ресурсах выбранного namespace или непроверенных
  метках. Обновления заблокированы до отдельного проверенного installed receipt,
  текущей SQLite schema и согласованного backup/stop/rollback.
- Оба режима не читают БД, медиа, секреты и raw environment, не выполняют docker exec.
  Только docker info, compose version, ps, volume/network ls и узкий label inspect.
  Запрещены запуск/удаление/перезапуск, prune, создание сетей и изменения Windows.
- Подпроцесс Docker получает явный context, ограниченный набор переменных ОС;
  DOCKER_HOST, COMPOSE_*, proxy-настройки и provider credentials не наследуются.
  stdout содержит только нормализованный JSON; stdout/stderr Docker не цитируются.

### Команды

Windows PowerShell (в корне проверенного checkout):

    python -m tools.docker_delivery_plan doctor --context desktop-linux --installation isoas

Linux (в корне проверенного checkout при наличии Docker context default):

    python3 -m tools.docker_delivery_plan doctor --context default --installation isoas

Для plan нужно дополнительно передать --manifest с путём к **заранее
верифицированному** JSON-манифесту. Команда не скачивает его и не создаёт
release bundle. Release-фабрика ещё не внедрена — поэтому полноценный
production plan пока не имеет доверенного входного артефакта.

Схема JSON (ровно четыре поля без дополнительных ключей):

- manifest_version: число 1;
- source_sha: 40 шестнадцатеричных символов нижнего регистра;
- schema_compatibility: min_version и max_version, положительные целые,
  диапазон включительный;
- images: роли backend и web обязательны, guard/worker необязательны;
  каждой роли соответствует registry/repository + @sha256: + 64 hex,
  без тега latest, пароля и переменной окружения.

Этот plan не делает сетевую загрузку образов, не проверяет подпись/доверие
манифеста, свободное место и порты. Они явно перечислены в remaining_gates.

### Exit codes

| Код | Значение | Следующее действие |
| --- | --- | --- |
| 0 | OBSERVED для doctor или READY только для плана | Остальные gates ещё не пройдены |
| 2 | INVALID_INPUT | Исправить параметры/манифест; Docker не изменён |
| 3 | TARGET_UNAVAILABLE | Проверить доступ к context/Engine; ничего не перезапускать |
| 4 | OWNERSHIP_CONFLICT | Не присваивать чужие volumes, расследовать вручную |
| 5 | INCOMPATIBLE_RELEASE | Нет доказательств схемы/обновления либо несовместимый Engine |

Машинный интерфейс выводит **одну JSON-строку**, без списка путей, приватных
ID, ключей, stacktrace или сырого docker inspect. Любой отказ — BLOCKED.
Ни один код не вызывает изменение Docker.

## 2. Факты с тестового Windows D2-R2 (без приватных данных)

- На хосте ранее работали ASA Lab, Publikator и отдельные IZO/Shadow.
  Namespace isoas на момент doctor отсутствовал: 0 контейнеров,
  0 томов, 0 сетей. Чужие имена/labels не считаются своей установкой.
- Docker Server 29.8.2 Linux, Compose 5.6.0; инструмент выполнил
  doctor в реальном desktop-linux и не изменил ресурс.
- Историческая изолированная Preprod #217 имеет 59 пользователей,
  1949 записей изображений, 60 видео, 1851 заданий и 2590 медиа.
  Это **тестовая копия**, не подтверждённая production БД.
- Перед экспериментом создан SQLite hot snapshot и копия всех медиа с
  SHA-256; репетиция восстановления в отдельных томах:
  integrity_check=ok, foreign_key_check=0, 2590 файлов сверены.
- Новый локальный объединённый кандидат f51c316176bf2609ccb9271c00a358a7b1f02768
  собран из #217 + main, **не опубликован в GitHub**.
  Shadow на loopback 48414/48415: три контейнера healthy,
  исторические данные в **своих** томах; публичная лента 89 уникальных
  элементов/3 страницы, public media Range=206, guest gallery/admin=401.
- Все реальные платные провайдеры, webhook, mail, Telegram/MAX и host GPU
  для этого нового Shadow остаются выключенными. Положительное
  authenticated Studio→GPU→gallery/ledger **не проверено**.

## 3. Журнал проблем и решений

| ID | Проблема и подтверждение | Решение / состояние |
| --- | --- | --- |
| D2-01 | Много разных Compose-проектов с похожими именами | Namespace + labels + ID обязательны; глобальная очистка запрещена. Открыто для installer |
| D2-02 | Из read-only Windows bind обычный SQLite mode=ro отказал в открытии | Offline immutable=1 для завершённого hot snapshot прошёл; не применять к live SQLite |
| D2-03 | При восстановлении Linux UID/GID каталогов не совпал с 10001 | Ограниченный restore helper CHOWN/FOWNER/DAC_OVERRIDE, затем non-root проверка. Production helper ещё не принят |
| D2-04 | Пустой backend автоматически создаёт avatars и .owner.lock | Подтверждено, что каталог пуст и lock незанят; учесть в restore preflight |
| D2-05 | /api/version сообщает unmanaged, backend_commit=null, frontend_build=unknown | OCI SHA-метки проверены, но release identity не принят. Нужен проверяемый manifest |
| D2-06 | #217 — Draft, не часть main, локальный merge без текстовых конфликтов | Локальный кандидат; CI/review/совместимость ещё не доказаны |
| D2-07 | В системном Python 3.13 отсутствовал pytest | Использован уже существующий изолированный каталог pytest, глобальные пакеты не менялись |
| D2-08 | Тестовая подмена Docker первоначально игнорировала Compose label filter | Исправлен фейковый runner, runtime guard не ослаблялся; повторные тесты зелёные |
| D2-09 | На Windows создание symlink может быть ограничено | Тест ссылки пропущен на Windows, обязательная проверка на Linux CI |
| D2-10 | После обновления Pillow 13/npm fixes пересобраны backend/frontend/guard | Локальная сборка прошла, но не эквивалентна exact-HEAD hosted CI |
| D2-11 | Настоящие install/update/rollback, clean Linux install и signed release | Не реализованы; следующий bounded package после приёмки planner |
| D2-12 | Веб/API healthy, но настоящие модели и биллинг не проверены | Нельзя объявлять production Docker-релиз успешным |
| D2-13 | GitHub: 6 alerts (4 high/1 moderate/1 low) | Нужна security-проверка, не диагноз PR |
| D2-14 | Первоначальный argparse мог вывести сырой неверный аргумент и не-JSON отказ | Исправлено: безопасный однострочный BLOCKED JSON, без отражения значения; добавлен regression test |
| D2-15 | Между stat и чтением могла произойти подмена манифеста | Проверки fd, inode, mtime/ctime и размера; отказ при FIFO/симлинке, нужен exact-SHA CI |
| D2-16 | Windows: lstat/fstat дают разный стабильный ctime | ctime проверяется внутри каждого API; 15 регрессий, 100/100 файлов Windows |

Исторические user data, идентификаторы, SQLite, media, cookies, API tokens,
ключи, приватные логи/адреса и полные docker inspect в этот публичный
репозиторий не выгружаются.

## 4. Следующий безопасный этап

После exact-SHA CI и независимой проверки данного Draft PR выполнить
следующую ограниченную задачу #247: доверенный release-manifest и
install/update/restore-check с атомарным receipt, ownership lock,
backup/rollback и idempotency. Только затем проверить Windows Docker Desktop
на собственной установке isoas, повторный install/update, и аналогичную
тестовую поставку на Linux. Никаких изменений ASA Lab, Publikator, Windows
production, Docker Desktop daemon или сетевых настроек хоста без отдельного
разрешения.
