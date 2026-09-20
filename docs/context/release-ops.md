---
status: canonical
domain: release-ops
read_when: ["release-ops","release","deploy","promotion","rollback"]
source_paths: ["docs/production-release-runbook.md","ops/release/README.md","ops/release/promote-project-release.ps1","ops/release/recovery-service-guard.ps1","tools/release_verification_receipt.py"]
test_paths: ["tools/test_release_resilience_scripts.py","tools/test_release_verification_receipt.py","tools/test_install_project_promoter.py","tools/test_frontend_release_identity.py"]
related_domains: ["unknown"]
forbidden_paths: ["unknown"]
owner: release-ops
context_role: scoped-domain-map
updated: 2026-09-19
---
# Context: release operations

## Назначение

Эта карточка маршрутизирует production release, promotion и rollback задачи.
Главный production contract: `docs/production-release-runbook.md`.
Context package не разрешает никаких production mutations.

## Release state vocabulary

Не смешивать следующие состояния:

- CODE COMPLETE — source implementation закончена в рабочей branch/commit.
- PUSHED — commit опубликован в remote repository.
- CANDIDATE PREPARED — verified exact SHA подготовлен updater/release tooling.
- DEPLOYED — candidate фактически установлен production promoter.
- VERIFIED — требуемые technical gates после установки прошли.
- OPERATIONALLY VERIFIED — production/runtime evidence подтверждает реальное состояние.

GitHub merge, HTTP 200 или существование candidate сами по себе не означают DEPLOYED.

## Владение

- `docs/production-release-runbook.md` — canonical operator procedure.
- `ops/release/README.md` — tracked promoter overview and invariants.
- `ops/release/promote-project-release.ps1` — tracked production promoter source.
- `ops/release/recovery-service-guard.ps1` — bounded recovery service guard.
- `tools/release_verification_receipt.py` — exact-SHA verification receipt contract.

## Production promoter boundary

Tracked promoter source находится в repository:
`ops/release/promote-project-release.ps1`.

Installed promoter живёт вне repository checkout в production runtime.
Tracked source и installed copy должны совпадать по canonical verification contract.
Promoter требует exact candidate identity и fail-closed preflight gates.

Repository-local bootstrap/restart helpers нельзя автоматически считать production promotion commands.
В частности, локальные helper scripts не заменяют installed production promoter.

## Candidate preparation

Candidate preparation следует runbook и exact-SHA verification.
Verification receipt является secret-free integrity/freshness contract.
Receipt должен соответствовать exact checkout SHA и canonical verifier.
Истёкший или несовпадающий receipt является hard stop.

## Promotion boundary

Promotion имеет mutable production window.
До неё должны пройти identity, candidate, promoter и safety gates.
Promoter владеет controlled service/config switch.
Package context не должен запускать promoter ради проверки документации.

## Rollback boundary

Automatic rollback восстанавливает code/configuration boundary.
Additive live database не перезаписывается автоматическим file copy.
Database restore является отдельной rehearsed operator action.
После rollback нужно снова проверить previous exact release.

## Recovery boundary

Stopped-backend recovery является специальной operator procedure.
Она требует owned maintenance guard и точных preconditions.
Нельзя превращать recovery steps в обычный development shortcut.
Нельзя вручную удалять maintenance evidence для прохождения gate.

## Runtime/service ownership

Release process может управлять установленными `IZOBackend` и `IZOCaddy` только в разрешённом elevated release scope.
Этот context slice таких разрешений не даёт.
Наблюдение repository source не доказывает текущий service state.

## Границы

- Не выполнять deploy.
- Не выполнять restart.
- Не останавливать/запускать services.
- Не обращаться к production DB.
- Не менять FRP.
- Не менять DNS.
- Не менять VPN.
- Не выполнять provider calls.
- Не изменять production candidate markers.
- Не создавать release receipt без предусмотренного verifier workflow.

## Release verification receipt

`tools/release_verification_receipt.py` связывает receipt с:
- exact Git SHA;
- branch;
- clean checkout;
- verification mode;
- required gates;
- verifier hash;
- freshness window.

Receipt не заменяет production operational verification.
CI receipt и production installation являются разными evidence classes.

## Focused tests

- `tools/test_release_resilience_scripts.py`
- `tools/test_release_verification_receipt.py`
- `tools/test_install_project_promoter.py`
- `tools/test_frontend_release_identity.py`

Использовать focused tests для source contracts.
Live service lifecycle требует отдельного approved release-ops execution.

## Safety

- Не трогать `C:\IZO_ASA` в обычном coding package.
- Не запускать installed promoter.
- Не запускать service mutation helpers.
- Не читать или изменять production DB.
- Не менять network/tunnel/VPN configuration.
- Не использовать production secrets.
- Один failed promotion не повторять циклом.

## Unknowns

Repository source сам по себе не подтверждает:
- текущий deployed SHA;
- service status;
- active release identity;
- candidate status;
- public route health;
- rollback success;
- FRP connectivity;
- production DB health.

Для этих утверждений нужен датированный operational evidence.

## Minimal handoff

Перед реальной release operation отдельно фиксировать:
- exact source SHA;
- CI result;
- verification receipt;
- candidate identity;
- installed promoter identity;
- pre-release identity;
- rollback boundary;
- service/listener state;
- local/public route checks;
- remaining blockers.

Эта карточка остаётся routing/safety map и не является разрешением на production action.
