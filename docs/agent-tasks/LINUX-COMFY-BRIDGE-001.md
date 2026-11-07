# LINUX-COMFY-BRIDGE-001 — ограниченный доступ к ComfyUI через 1Panel

## Назначение и границы

Пакет добавляет транспорт к одному согласованному частному ComfyUI для существующего
адаптера IZO_ASA. Очередь, задания, пользовательская авторизация, сохранение изображений
и учёт остаются в приложении. `backend/main.py` и чужой OpenRouter scope не изменяются.
Регистрацию scope определяет [Task Contract](../../tasks/LINUX-COMFY-BRIDGE-001.toml).

Профиль применяется только к закрытому тестовому проекту с его текущими тестовыми томами.
Он не разрешает запуск исторического outbox, работу с платными API или смену публичного домена.
Серверная идемпотентность, запрет повторного исполнения исторических операций и передача
владения внешними операциями остаются отдельными обязательными условиями пользовательского релиза.

## Сеть и протокол

Backend UID 10001, web UID 101 и proxy UID 10002 разделяют сетевой namespace guard.
Guard сохраняет loopback, ответы established/related, запрет IPv6 и default DROP.
Явный профиль `comfyui-private-v1` добавляет только UID 10002 → один literal RFC1918 IPv4:TCP-port.
Без профиля правила идентичны прежним. Healthcheck продолжает сравнивать полную таблицу nft.
Root guard сбрасывает UID/capabilities до готовности приложения.

Proxy использует тот же точный image digest, что guard. Отдельного четвёртого образа нет.
У proxy нет опубликованных портов, томов, SQLite, медиа, ключей или Docker socket.
Backend обращается к `http://127.0.0.1:18188`; выход к провайдеру выполняет только proxy.
Частный upstream сейчас использует HTTP: loopback URL приложения не означает сквозной TLS.
Активация требует явного `--accept-private-http` и проверенного доступа к выбранному LAN endpoint.

Режим `capabilities` разрешает только необходимые GET. Очередь возвращается только счётчиками,
каталог — только разрешёнными именами 4B, object_info — только нужными именами узлов.
Чужие templates/prompts/config, аргументы запуска и cookies не передаются приложению.
`generate-t2i-4b` дополнительно допускает POST `/prompt`, GET `/history/{prompt_id}` и `/view`.

Принимается точная существующая T2I топология из десяти узлов. Разрешены
`flux-2-klein-4b-fp8.safetensors`, `qwen_3_4b.safetensors`, `flux2-vae.safetensors`,
batch 1, четыре шага, размеры 256–1024 с кратностью 16. Дополнительные узлы, input keys,
другие связи, LoRA, загрузка файлов, редактирование, видео и 9B в этом профиле недоступны.
Template провайдера может содержать исходное имя 9B; POST проверяется после штатного выбора 4B адаптером.
`COMFYUI_NATIVE4B_ONLY=true`, `COMFYUI_REQUIRED=true`, `COMFYUI_MOCK_FALLBACK=false` обязательны.

Всегда запрещены `/interrupt`, `/free`, изменение очереди, перечисление/удаление history,
управление сервером/custom nodes, CONNECT, redirects и произвольные destinations.
Authorization/Cookie и upstream Location/Set-Cookie не проксируются.
Число обслуживаемых соединений, время, заголовки, JSON и изображения ограничены;
неоднозначное HTTP framing и JSON с повторными ключами/NaN отклоняются.

## Принадлежность результатов

Оператор выбирает постоянный уникальный namespace вида `izo-` плюс 16–60 безопасных символов.
Его необходимо сохранить при перезапуске, обновлении и восстановлении Compose.
Proxy добавляет namespace к `client_id`, а SaveImage сохраняет результат в
namespace / исходный client_id приложения / image. Произвольные пути не принимаются.

History допускается только для конкретного UUID с совпадающими prompt tuple, client_id,
T2I графом, SaveImage prefix и выходными файлами. Приложению возвращаются только собственные
outputs и ограниченный status. `/view` допускает только PNG типа output внутри namespace.
Проверка не зависит от памяти proxy, поэтому сохраняется после холодного старта.
Пустой ответ history остаётся пустым; proxy никогда не отправляет prompt повторно.

Это принадлежность на уровне экземпляра. Приватность между пользователями проверяет backend.
Namespace не заменяет auth провайдера, idempotency ledger или durable provider submission journal.
Запрет глобального interrupt означает, что уже начавшаяся отменённая операция может завершиться
на провайдере; интерфейс не должен выдавать её за прерванную на GPU.

## Один ZIP и точная версия

Существующий format 2 / synthetic-runtime сохраняет три сервиса/образа, `model_execution=false`
и `production_authorized=false`. Его installer и validators не изменяют профиль автоматически.
Builder добавляет только три пассивных файла в обычный hashed inventory:

- `profiles/compose.comfyui-shadow.yml` — opt-in overlay, JSON также является допустимым YAML.
- `docker_comfy_bridge_profile.py` — renderer/validator без lifecycle или сетевых вызовов.
- `profiles/LINUX-COMFY-BRIDGE-001.md` — этот контракт оператора.

Для нового кандидата application SHA и tooling SHA должны совпасть. Образы, frontend,
release-manifest, ZIP inventory и ожидаемые SHA/release проходят прежние проверки.
Неполный набор passive assets отклоняется; старый источник без всех трёх сохраняет прежний ZIP.

## Применение через 1Panel

1. Сохранить точные байты принятого исходного Compose и его SHA-256. Это доверенный baseline;
   существующий init-db command привязан к этому pin и сохраняется без изменения.
2. Собрать/проверить канонический ZIP существующим builder. Загрузить образы и развернуть его
   frontend в соседний каталог `frontend-` с точным release ID через разрешённые операции 1Panel.
3. Вызвать bundled renderer с `--bundle`, `--manifest-sha256`, `--base-compose`, `--base-sha256`,
   `--expect-source`, `--expect-release`, `--frontend`, `--upstream-ip`, `--upstream-port`,
   `--namespace`, `--mode capabilities`, `--accept-private-http`. При nginx bind нужен `--nginx-sha256`.
   Если Engine использует OCI manifest digest, передать pinned `--images` JSON и `--images-sha256`;
   разрешены только config/manifest identities из существующего portable image manifest.
4. Сохранить stdout как кандидат. Renderer ничего не устанавливает и не меняет файлы/тома.
   Выполнить настоящий Compose render и повторить validator с `--check-compose` и `--check-sha256`.
   Любые дополнительные изменения effective Compose отклоняются.
5. Внести проверенный Compose через штатное управление проектом 1Panel. Проверить image labels,
   nft readback, отсутствие прямого egress у backend/web и разрешённые GET через proxy.
6. Только после допуска конкретной тестовой операции повторить render с `--mode generate-t2i-4b`.
   Проверить настоящий UI → backend → provider → сохранённое изображение и однократный ledger.
   Отдельно проверить недоступность остальных режимов; отсутствие mock не является их готовностью.
7. Для возврата применить сохранённый предыдущий Compose через 1Panel, сохранив собственные тома.
   Это ручной возврат конфигурации. Исторические и чужие тома не затрагиваются.

Для следующего совместимого релиза используются тот же проверенный baseline и namespace,
новые pinned image/frontend identities и повторная проверка effective Compose.
Core synthetic installer не управляет opt-in пятью сервисами native 1Panel проекта;
его диагностические ограничения не ослабляются и не объявляются проверкой этого профиля.

## Проверки исходного кода

```bash
python -m pytest -q tools/test_comfyui_proxy_policy.py tools/test_comfyui_guard_profile.py tools/test_docker_comfy_bridge_profile.py tools/test_docker_test_bundle_build.py
```

Тесты используют временные файлы и локальный fake HTTP server. Они доказывают policy,
изоляцию namespace, холодный рестарт proxy, identity/drift rejection и неизменность synthetic ZIP.
Они не являются свидетельством реальной GPU-генерации, входа владельца или публичной миграции.
