# Повторная оценка тестового долга — 27 октября 2026

Пакет: GOV-TEST-HEALTH-REVIEW-20261027. Это проект ограниченного решения для
отдельного PR; действие начинается после регистрации пакета, независимого review
и обязательного CI. Дефекты #162–165 не объявляются исправленными.
Основание: [контракт #112](https://github.com/spikeal8-maker/IZO_ASA/issues/112)
допускает известный долг с владельцем, исправлением или ограниченным исключением.

## Решение и ответственность

Предлагается повторно принять только прежний измеренный долг до **2026-10-30**
включительно. Ответственный owner всех четырёх issue — `spikeal8-maker`.
Предметный анализ выполнил агент `runtime_path`; это не подпись владельца и не
GitHub APPROVED. Интегратор проверяет конкретный diff и получает независимое
ревью. Автоматическое следующее продление этим решением не разрешено.

Дата сравнивается существующим auditor с датой `metadata.startedAt` прогона.
Прогон с датой 2026-10-31 снова обязан получить EXPIRED для всех четырёх долгов.
Ранее срока требуется новая оценка при изменении соответствующего lifecycle,
FastAPI/Starlette/httpx, cookie-test или Windows teardown поведения.
Применимость этого условия проверяет интегратор; новый автоматический gate
для изменения зависимостей данным пакетом не добавляется.

## Проверенные доказательства

- Основа policy: `0d134aa20cd0a1d1ca6828622fe6a435c74c415b`.
- Проверенный PR: [#251](https://github.com/spikeal8-maker/IZO_ASA/pull/251),
  exact SHA `e94d4d5e21455bf9809990d5509ad6e5db09d453`.
- [GitHub run 40513117243](https://github.com/spikeal8-maker/IZO_ASA/actions/runs/40513117243),
  job `122219688365`; Windows, Python 3.11.9, pytest 9.0.3.
- Artifact `12740091822`, имя
  `test-health-evidence-e94d4d5e21455bf9809990d5509ad6e5db09d453`.
- SHA-256 ZIP:
  `747e884961c27d283b182a114fd25c8526867efcf50051da875b9396a2405c78`.
- Результат: 2370 passed, 1 skipped, 97 warnings, cleanup 0.
- Unattributed warnings 0; external attempts 0; blocked external attempts 0.
- Retry observability AVAILABLE, rerun reports 0, loaded retry plugins пусто;
  process-leak check PASS. Повторная недетерминированность не измерена.
- Нарушения receipt: только `DEBT_REVIEW_EXPIRED_162`, `_163`, `_164`, `_165`.
- Policy и auditor на основе пакета идентичны проверенному e94d4d5.
  Исторический accepted baseline относится к прежнему SHA/артефакту;
  его происхождение не переписывается новым наблюдением.

Лог job независимо прочитан review-агентом; exact artifact receipt прочитан
интегратором. Сохранённый неуспешный GitHub run остаётся FAILURE.
Новая policy, применённая к старым данным, является ретроспективной оценкой;
она не доказывает успешный CI нового commit и не заменяет его.

## Предметные решения по долгам

### #162 — FastAPI lifecycle

[Issue #162](https://github.com/spikeal8-maker/IZO_ASA/issues/162) остаётся открытым.
Наблюдаются 8 предупреждений: `backend/main.py=4`,
`site-packages/fastapi/applications.py=4`. Deprecated startup/shutdown
`on_event` используется по-прежнему; число не выросло.

Риск: будущая несовместимость lifecycle; поспешная замена может нарушить порядок
startup/shutdown, освобождение ресурсов и единственное владение consumers.
Временное принятие обосновано точным прежним набором и успешными тестами
текущих закреплённых зависимостей. Исправление выполняется отдельным пакетом.
Выход: supported lifespan с сохранёнными failure/shutdown/worker-owner
проверками, уменьшением соответствующих warnings и новым exact-head CI.

### #163 — TestClient compatibility

[Issue #163](https://github.com/spikeal8-maker/IZO_ASA/issues/163) остаётся открытым.
Наблюдается 1 `StarletteDeprecationWarning` в `fastapi/testclient.py`:
предупреждение о переходе TestClient с httpx на httpx2.
Проверенные версии: FastAPI 0.136.3, Starlette 1.7.0, httpx 0.28.1.

Риск: будущая несовместимость тестового транспорта; новая зависимость требует
содержательной проверки совместимости и supply-chain. На закреплённом стеке
нет нового warning или test failure. В этом пакете зависимость не заменяется.
Выход: отдельная совместимая миграция TestClient с auth/session/lifecycle
проверками, исчезновением данного warning и exact-head CI.

### #164 — cookies в тестах

[Issue #164](https://github.com/spikeal8-maker/IZO_ASA/issues/164) остаётся открытым.
Все 88 предупреждений совпадают с baseline по source:

| Файл backend | Количество |
|---|---:|
| test_admin_bots_v2.py | 12 |
| test_admin_password_reset.py | 15 |
| test_admin_v2.py | 8 |
| test_auth_sessions.py | 1 |
| test_generation_protection.py | 16 |
| test_ownership_protection.py | 24 |
| test_prompt_improvement.py | 12 |

Риск: неоднозначное сохранение cookies и изменение межпользовательской
изоляции при механическом переносе в общий cookie jar. Текущие assertions
проходят, состав предупреждений прежний. Suppression не допускается.
Выход: client-level cookies с явной изоляцией клиентов/пользователей,
сохранением auth/CSRF/ownership assertions, снижением всех указанных
категорий и exact-head CI; финансовые сценарии не ослаблять.

### #165 — Windows cleanup

[Issue #165](https://github.com/spikeal8-maker/IZO_ASA/issues/165) остаётся открытым.
Текущий cleanup 0 при прежнем allowance 1 для
`PermissionError / apply-secrets`; process-leak check PASS.

Риск: редкая Windows handle/teardown гонка не исключается одним успешным
наблюдением. Нулевой текущий счётчик не является доказанным исправлением.
Allowance не увеличивается; долг не удаляется из accepted baseline.
Выход: исследовать владельца apply-secrets и teardown, сопоставить необходимые
независимые Windows evidence на точном проверяемом коде; при воспроизведении
исправить освобождение ресурсов без скрытого retry. Закрытие — отдельное
решение с доказательством, а не следствие этой новой даты.

## Чем решение отличается от подстановки дат

Для каждого долга зафиксированы фактический состав, нерешённый риск и условие
выхода. Срок короткий, следующий review не делегирован автоматике.
Все owners сохраняются. Меняются только reason и reviewBy в debtReviews.
Не меняются acceptedBaseline 97/1, его источники/категории, enforcement, auditor,
workflow, код приложения, тестовые assertions и статусы issue.
Новые warnings, рост cleanup, внешний network, rerun или process leak по-прежнему
дают FAIL независимо от срока этой оценки.

## Обязательные проверки принятия

1. Полный diff и равенство policy вне debtReviews; только восемь scalar changes.
2. Неизменённый `tools/test_test_health_audit.py`: focused PASS.
3. Date controls: прежняя policy на 2026-10-27 EXPIRED; новая до 2026-10-30
   не просрочена; 2026-10-31 снова EXPIRED. Это синтетические проверки evaluator.
4. Исходные отрицательные тесты warning/cleanup/network/retry/process остаются.
5. Scope enforcement, file hygiene, независимое diff review и новый hosted CI.
   Их отсутствие оставляет пакет кандидатом.
6. Retrospective replay оригинального artifact сохраняет исходники evidence;
   не переименовывать прежний FAILURE в SUCCESS.

Пакет не утверждает Docker, Linux, provider, deployment или data-recovery
приёмку. Он не смешивается с write-scope PR #251 и не устраняет сами четыре долга.
