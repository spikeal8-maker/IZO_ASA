# REL-SVC-001 — service-safe Python для release candidate

Статус: **CODE COMPLETE; TARGETED AND CI COMPONENTS GREEN; CLEAN FULL PENDING;
NOT DEPLOYED**.

## Инцидент

24 августа 2026 года candidate backend прошёл source tests и frontend build,
но после переключения Windows-служба несколько раз завершила процесс. WinSW
зафиксировал, что venv launcher пытался открыть Python из интерактивного
пользовательского профиля. `IZOBackend` работает как `LocalService`, поэтому
такой runtime не является production-safe. Promotion откатил release.

Увеличение 90-секундного ожидания не исправляет причину: процесс не выполнял
долгую инициализацию, а не мог запустить базовый интерпретатор.

## Контракт исправления

- единственный base Python для backend service на этом сервере:
  `C:\IZO_ASA\runtime\python311\python.exe`;
- candidate venv обязан находиться строго в
  `<release>\backend\.venv`;
- `pyvenv.cfg`, фактический `sys.base_prefix`, точные версии
  `backend/requirements.txt`, `pip check` и обязательные импорты проверяются до
  online backup и до остановки служб;
- несовместимый venv обновляется стабильным base Python; зависимости
  устанавливаются только при несовпадении exact pins;
- stdout/stderr package installer не выводится в promotion log, чтобы URL с
  credentials не попал в журнал;
- невозможность исправить candidate завершает promotion на стадии preparation,
  пока предыдущий backend продолжает работать.

## Acceptance

1. Fake candidate с venv из пользовательского профиля отклоняется без repair.
2. Тот же candidate исправляется от заданного service base Python.
3. Повторная проверка идемпотентна.
4. Venv вне точного release backend отвергается.
5. Promoter вызывает проверку до backup/service stop.
6. Focused tests повторяются пять раз.
7. Quick и один Full выполняются на clean candidate.
8. Отдельная installation из exact clean commit копирует проверенный promoter в
   runtime, сохраняет rollback-копию и receipt, не перезапуская службы.
9. Controlled promotion и rollback выполняются последовательно три раза.
10. Exact release identity, local/public health и service process ancestry
    подтверждаются после каждого переключения.

Документ и код не разрешают restart/deploy. AdGuard VPN, FRP, VPS, DNS,
production DB/media и provider traffic вне scope.
