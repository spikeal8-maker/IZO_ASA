# Канонический Docker-кандидат

Контракт: [DOCKER-CANONICAL-CANDIDATE-002](../tasks/DOCKER-CANONICAL-CANDIDATE-002.toml).
Используются существующие builder и installer формата 2 с явным профилем
`synthetic-runtime`. Это тестовый кандидат, не разрешение рабочего выпуска.
Фактические результаты относятся только к SHA, archive hashes и image IDs
конкретных receipts; наличие этой инструкции не означает выполненную приёмку.

## Исходники и ограничения

Предыдущий канонический кандидат: `96314d9414df2954d3d8abbf3db20cf2e5e7dce0`.
Текущий application SHA равен точному HEAD приёмочного workflow. Оба значения
закреплены в producer receipt и плане версии 2; данные receipt не выбирают
ожидаемый исходник. Старый checkout B не предоставляет HTTP-клиент.

Из семи Docker-входов пять равны донору
`1030abdafc32a0f11fbc4a6593acd435eb1bbdfd`. В web ignore добавлены три SQLite
sidecar exclusions; в web/guard ignore — по три ограничения родительских
поддеревьев. Реальный BuildKit экспортирует временные синтетические fixtures:
web — только frontend inputs и nginx, guard — только guard source.
Этот probe не заменяет сборку настоящих application Dockerfiles.

Backend/frontend, backend Dockerfile, базовый Compose, зависимости и три
installer-модуля не изменяются. Старые format-1 проверки сохраняются.

## Один комплект на двух ОС

Linux producer собирает Linux/amd64 images и включает их в `release-B.zip`.
Windows Docker Desktop в режиме Linux containers и Linux Docker Engine
получают **те же байты ZIP**, manifest и три image IDs, без второй пересборки.
Нужны Python 3.11+ и Docker с Compose v2+. Git/Node/npm получателю не нужны.

Из доверенного workflow artifact передаются `producer.json`, `context.json`,
`release-A.zip`, `release-A.receipt.json`, `release-B.zip` и
`release-B.receipt.json` и неизменённый `docker_test_bundle_format.py`
из закреплённого tooling. Producer receipt проверяется по независимому job
output hash; затем проверяются receipt, archive и manifest hashes. Сам по себе
хеш внутри того же скачанного комплекта не является подписью выпуска.
Artifacts ограничены сроком хранения workflow; это не постоянный registry.

На каждом хосте используются новый отдельный state directory и собственные
installation/Engine identities. Установленное состояние между хостами не
копируется. Project и loopback ports заданы bundle; занятые ресурсы не удаляются.

## Проверка пакета и Windows

SHA256 `release-B.zip` берётся из отдельно опубликованного отчёта точного
workflow run, а не из соседнего receipt. Перед распаковкой проверяется hash
переданного штатного format-модуля; затем его `extract()` проверяет ZIP pin,
private snapshot, имена, размеры и типы файлов. Это существующий extractor.
`incoming-B` должен отсутствовать. Команды выполняются в каталоге комплекта.

```powershell
$izoRoot = (Get-Location).Path
$izoExpected = (Read-Host 'SHA256 release-B.zip from exact run report').Trim().ToLowerInvariant()
$izoExtractor = Join-Path $izoRoot 'docker_test_bundle_format.py'
if ($izoExpected -cnotmatch '^[0-9a-f]{64}$') { throw 'ARCHIVE_PIN_REQUIRED' }
if ((Get-FileHash -LiteralPath $izoExtractor -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'b15ae6c08bd9cbea0ac508aefe06d599524ab3dc581380dd4aef2de826896d00') { throw 'EXTRACTOR_PIN_MISMATCH' }
python -B -c "import sys; from pathlib import Path; from docker_test_bundle_format import extract; extract(Path('release-B.zip'),sys.argv[1],Path('incoming-B'))" $izoExpected
if ($LASTEXITCODE -ne 0) { throw 'ARCHIVE_EXTRACT_FAILED' }
$izoManifestB = (Get-FileHash -LiteralPath (Join-Path $izoRoot 'incoming-B\bundle.json') -Algorithm SHA256).Hash.ToLowerInvariant()
python -B .\incoming-B\docker_test_bundle_runtime.py verify --manifest-sha256 $izoManifestB
if ($LASTEXITCODE -ne 0) { throw 'BUNDLE_VERIFY_FAILED' }
$izoState = Join-Path $izoRoot 'installed'
python -B .\incoming-B\docker_test_bundle_runtime.py install --manifest-sha256 $izoManifestB --context desktop-linux --state-dir $izoState --test-only
if ($LASTEXITCODE -ne 0) { throw 'CANONICAL_INSTALL_FAILED' }
```

Повтор из постоянного release directory после удаления входной распаковки:

```powershell
$izoRuntime = Join-Path $izoState ('releases\' + $izoManifestB + '\docker_test_bundle_runtime.py')
python -B $izoRuntime install --manifest-sha256 $izoManifestB --context desktop-linux --state-dir $izoState --test-only
if ($LASTEXITCODE -ne 0) { throw 'CANONICAL_REPEAT_FAILED' }
```

## Linux

Из соответствующего каталога того же комплекта на Linux:

```bash
set -euo pipefail
read -r -p 'SHA256 release-B.zip from exact run report: ' izo_expected
python3 -B - <<'PYVERIFY'
import hashlib
from pathlib import Path
pin = "b15ae6c08bd9cbea0ac508aefe06d599524ab3dc581380dd4aef2de826896d00"
if hashlib.sha256(Path("docker_test_bundle_format.py").read_bytes()).hexdigest() != pin:
    raise SystemExit("EXTRACTOR_PIN_MISMATCH")
PYVERIFY
python3 -B -c 'import sys; from pathlib import Path; from docker_test_bundle_format import extract; extract(Path("release-B.zip"),sys.argv[1],Path("incoming-B"))' "$izo_expected"
izo_manifest_b="$(python3 -c 'import hashlib; from pathlib import Path; print(hashlib.sha256(Path("incoming-B/bundle.json").read_bytes()).hexdigest())')"
python3 -B incoming-B/docker_test_bundle_runtime.py verify --manifest-sha256 "$izo_manifest_b"
python3 -B incoming-B/docker_test_bundle_runtime.py install --manifest-sha256 "$izo_manifest_b" --context default --state-dir "$PWD/installed" --test-only
python3 -B "installed/releases/$izo_manifest_b/docker_test_bundle_runtime.py" install --manifest-sha256 "$izo_manifest_b" --context default --state-dir "$PWD/installed" --test-only
```

## Обновление, возврат и данные

Существующий installer использует ту же команду `install` с дополнительным
`--allow-code-update`. Для возврата выбирается проверенный manifest A; для
обновления снова выбирается B. Это **ручной возврат кода**, не автоматический
rollback БД. Поддерживается совместимая схема 7; idle/ownership/volume guards
обязательны. Ошибка не разрешает повторное создание или удаление чужих томов.

Существующая 11-этапная матрица проверяет два аккаунта, девять заданий и
однократные job-linked charges, права на private media, 420 секунд работы,
restart/recreate, down/reinstall без удаления томов и B→A→B. Hashes результатов,
сессии и volume generation/CreatedAt должны сохраняться. Browser UI проверяется
отдельно: API-тест не доказывает фактическое отображение интерфейса.

## Что не подтверждает этот профиль

`synthetic-runtime` явно использует mock fallback и отключённые реальные
providers. Успешное тестовое задание не подтверждает выполнение настоящей
модели. Для рабочего использования нужен отдельно принятый путь реального
обработчика; запрещено обходить TEST-only validation ради зелёного результата.

CI PR265 прошёл pytest/frontend verification, но test-health gate отверг
истёкшие reviews #162–165. Исходный run остаётся FAILURE. Автоматическое
продление этих сроков запрещено прежним governance-решением; данный пакет
policy и пороги не изменяет. Обязательные CI/review остаются условиями merge.
Рабочий сервер переключается отдельно, после подтверждённого переноса данных.
