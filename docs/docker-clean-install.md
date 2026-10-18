---
status: candidate
role: docker-clean-install-runbook
updated: 2026-10-17
repository: spikeal8-maker/IZO_ASA
task_contract: tasks/DOCKER-ACCEPTANCE-REPAIR-001.toml
production_change_authorized: false
---

# Независимая установка и проверка Docker

Пакет объединяет существующие PR #186 и #191 относительно main
`d1ee3a0ac5114ec08f4a8daee9cf6e41e97d6a7a`. Их исходные коммиты остаются
предками интеграционной ветки. Критерии: `docs/docker-delivery-acceptance.md`.

## Исполнитель и запуск

Workflow `.github/workflows/docker-clean-install.yml` запускается при push
в `agent/docker-acceptance-repair-001` и вручную. Он использует временные
GitHub-hosted Ubuntu 24.04 VM с правами `contents: read` и точным checkout SHA.
Проверка Task Contract и секретов выполняется перед сборкой приложения.
Общий Windows-исполнитель этим workflow не запускается.

Две matrix-задачи работают на разных VM. Каждая последовательно строит три
образа из exact checkout и выполняет три прогона на новых SQLite/media volumes.
Второй и третий прогоны той же VM используют проверенные immutable image IDs.

Повтор завершённого SHA: Actions → Re-run all jobs; attempt меняется.
Новый SHA запускается через push. Ручной workflow_dispatch доступен после
появления workflow в default branch. Зависимости и Chromium загружает workflow.

Драйвер требует exact source/base SHA, replica 1|2 и новый evidence-dir внутри
RUNNER_TEMP; общий или неподтверждённый host запрещён. Context default,
Unix socket, engine ID и machine hash проверяются при действиях. Сеть и Docker
хоста не меняются. Занятый порт завершает запуск ошибкой.

Команда внутри подтверждённой временной VM:

```bash
python -m tools.docker_clean_install --source-sha "$GITHUB_SHA" \
  --base-sha "$ACCEPTANCE_BASE" --replica 1 \
  --evidence-dir "$RUNNER_TEMP/docker-evidence" --extended
```

Это приёмочная установка с последующей очисткой. Адреса `origin` и `apiOrigin`
записываются в `run-N/receipt.json`. Для постоянного DEV/Shadow применяется
существующий `tools.docker_shadow`, а не обход проверки одноразовой VM.

## Что выполняется

| Критерий | Исполняемое доказательство |
|---|---|
| Д1-01 | Чистый exact checkout, source/config hash, локальные image IDs и размеры |
| Д1-02 | Настоящая готовность API, изолированная сеть, Chromium и SHA веб-страницы |
| Д1-03 | Два пользователя через регистрацию API; вход, выход, неверный пароль, чужие объекты |
| Д1-04 | UI/API → очередь → обработчик → ComfyUI HTTP fixture → файл → галерея → учёт |
| Д1-05 | Сохранённая галерея, избранное и повторное использование изображения |
| Д1-06 | Разрешённая публикация, гостевая лента, pending moderation и приватность |
| Д1-07 | Пересоздание с теми же volumes; сессии, баланс, журнал, медиа и публикации |
| Д1-08 | Desktop/mobile screenshots, ограниченные редактированные журналы, собственная очистка |

Провайдер включается только явным `compose.acceptance.yml`, слушает loopback
в сети backend и живёт 300 секунд. Control token остаётся в памяти, выдаётся
безопасная квитанция. `COMFYUI_MOCK_FALLBACK=false`; обычный backend CMD сохранён.

Фикстура заменяет только модель. Авторизация, очередь, файлы, SQLite,
галерея, публикации и финансовый учёт принадлежат приложению. Браузер
не подменяет API; дополнительные внешние запросы браузера блокируются.
Доступ к приватному изображению проверяется отдельным гостевым контекстом.

Стабильный ключ `APP_ENV=test` позволяет проверить сохранность сессий;
поставка и резервирование production-секрета здесь не подтверждаются.

## Доказательства и сбои

`clean-source-…` содержит gates и pytest. `clean-linux-…`: summary, run-N/receipt,
topology, provider, SQLite/media, foreign-before/after, screenshots и redacted logs.
Имена artifacts включают source SHA, run ID и attempt; срок — 14 дней.
Фактические runs и ограничения публикуются в PR.

Неуспешный прогон не повторяется скрыто. Следующий push/attempt получает
отдельный набор артефактов. Уже существующий каталог evidence не перезаписывается.
Пропавшая квитанция, screenshot, журнал или незавершённая очистка не дают PASS.

Очистка требует свежего project и повторной проверки labels перед удалением
своих контейнеров, сети и volumes. Images/build cache завершаются вместе с VM;
global prune отсутствует. Обычный Shadow `down` сохраняет volumes.

## Аварии, копия и дополнительные функции

`--extended` запускает дополнительные пробы после Д1 каждой из трёх установок.
Все `run-N/receipt.json` и расширенные результаты сохраняются. После измеренного
extended FAIL следующая свежая установка допускается только при Д1 PASS, полной
квитанции и успешной очистке сессий/ресурсов и сравнении чужих ресурсов.
Иной сбой останавливает цикл. Общий `FAIL`/ненулевой exit остаётся, если любой
прогон не PASS; поздний успех не заменяет ранний FAIL.

| Проверка | Действие и граница |
|---|---|
| Д2-01 | Удержание настоящего задания у провайдера, SIGKILL своего backend, два recreate; refund, ledger и отсутствие повторного submit |
| Д2-02 | Два одинаковых Idempotency-Key, число jobs/charges и повторная отмена |
| Д2-03 | Два реальных consumers одного процесса и duplicate wake; второй OS process отдельно не проверен |
| Д2-04 | Пауза owned backend, RO source volumes, SQLite Backup API; два новых restore volumes, API persistence и строгий source-after guard |
| Д2-05 | Повреждённая SQLite, изменённый media и отсутствующий completion marker отклоняются до записи в целевые volumes |
| Д2-06 | Запрет записи media в восстановленной копии, реальная генерация, отсутствие результата/двойного списания; права восстанавливаются |
| Д3 | Health, chat history, fixture TTS, video config, Phone jobs API; два владельца, running/queued, RAM/CPU и refund |
| Admin | Fresh project: bootstrap, права, cached models, обратимая economy setting; local checkout/success/cancel/refund и adversarial replay |

Архив резервной копии передаётся в пределах VM через память и временные файлы;
SQLite, cookies, пароли и backup payload не публикуются в Actions artifacts.
Расширенные JSON находятся в `run-N/extended/`. Общий статус Д3 остаётся
`PARTIAL` при непроверенном model inference, даже если все доступные API прошли.

Quiesce/Phone/modelEconomics: runtime `NOT_RUN`.

Согласованная копия использует `QUIESCED_APPLICATION`, не zero-downtime.
Исходный CID/image/volumes закреплены; helper читает два RO mounts без сети.
Обе source-пробы и restore проходят в одном окне паузы; ни одна таблица не
исключается. WAL/SHM читаются через `mode=ro`, без `immutable`. Finally отдельно
удаляет helper и возобновляет исходный backend; ошибка сохраняет FAIL/receipt.

Квитанции дополнительно содержат продолжительность build по сервисам и up,
повторную готовность, 12 GET latency samples, размеры образов, CPU/RAM snapshots,
объём файлов SQLite/media и время до наблюдаемого завершения fixture jobs.
Это ограниченные измерения CPU-фикстуры, не GPU benchmark и не нагрузочный SLA.

## Сохранённые попытки

История D1 PASS, D2/Д3 FAIL, source/Full failures, исходные ZIP и SHA256 —
[PR #193](https://github.com/spikeal8-maker/IZO_ASA/pull/193) и predecessor
[#192](https://github.com/spikeal8-maker/IZO_ASA/pull/192).

Admin overlay изменяет только одноразовый код, флаг simulator и собственный
loopback origin. Код живёт в памяти; полный config сравнивается до запуска.
Отчёты исключают credentials и payment payload; все сессии и собственные
ресурсы закрываются, чужие ресурсы сравниваются. Live effects не включаются.

## Границы результата

Начальная топология содержит один прикладной процесс и встроенный обработчик.
Д1 не подтверждает Д2/Д3. Cross-process role
не подтверждается одним backend; Phone factory API имеет отдельную HTTP-пробу. Chat inference в этой конфигурации
заблокирован недоступным Ollama; TTS возвращает контролируемый PCM, не живой голос.
Администраторские действия измеряются отдельно; 3D остаётся `NOT_VERIFIED`.

Живые ComfyUI/Ollama/Qwen, платные API, SMTP, Telegram/MAX, реальные платежи
и production не проверяются этим workflow. Статус таких подключений —
`NOT_VERIFIED`, пока нет отдельного разрешённого испытания. Адрес loopback
принадлежит VM исполнителя и недоступен владельцу после завершения job.
Production-переход #126 остаётся отдельным согласованным этапом.
