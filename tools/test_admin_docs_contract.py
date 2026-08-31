"""Executable contracts for the canonical admin guide and change matrix.

The checks compare documentation with product route arrays instead of keeping a
second hard-coded Python route list. They also validate every referenced owner,
test and representative backend endpoint.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "admin-panel-guide.md"
CHANGE_CONTRACT = ROOT / "docs" / "admin-change-contract.md"
ADMIN_APP = ROOT / "frontend" / "src" / "AdminApp.tsx"
MODEL_ROUTES = ROOT / "frontend" / "src" / "adminModelsRoutes.ts"
FRONTEND_PACKAGE = ROOT / "frontend" / "package.json"
SYMBOL_MAP = ROOT / "backend" / "SYMBOL_MAP.md"
MODULAR_ROUTERS_DIR = ROOT / "backend" / "app" / "api" / "routers"

MARKER_PATTERN = "<!-- {name}:start -->(.*?)<!-- {name}:end -->"
RISK_CLASSES = {"low", "standard", "high-assurance", "release-ops"}
RISK_ORDER = {name: index for index, name in enumerate(("low", "standard", "high-assurance", "release-ops"))}


def _marked(text: str, name: str) -> str:
    match = re.search(MARKER_PATTERN.format(name=re.escape(name)), text, re.DOTALL)
    assert match, f"missing marker block: {name}"
    return match.group(1)


def _contract() -> dict[str, object]:
    block = _marked(CHANGE_CONTRACT.read_text(encoding="utf-8"), "admin-change-contract-json")
    match = re.search(r"```json\s*(\{.*\})\s*```", block, re.DOTALL)
    assert match, "admin change contract lacks a JSON code block"
    return json.loads(match.group(1))


def _ts_array(text: str, constant: str) -> str:
    marker = re.search(rf"(?:export\s+)?const\s+{re.escape(constant)}\b", text)
    assert marker, f"missing TypeScript array: {constant}"
    assignment = text.find("=", marker.end())
    start = text.find("[", assignment)
    assert assignment >= 0 and start >= 0, f"invalid TypeScript array: {constant}"

    depth = 0
    quote = ""
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    raise AssertionError(f"unterminated TypeScript array: {constant}")


def _ts_route_rows(path: Path, constant: str, key: str) -> dict[str, tuple[str, str]]:
    block = _ts_array(path.read_text(encoding="utf-8"), constant)
    rows: dict[str, tuple[str, str]] = {}
    for body in re.findall(r"\{([^{}]+)\}", block, re.DOTALL):
        key_match = re.search(rf"\b{re.escape(key)}:\s*'([^']+)'", body)
        label_match = re.search(r"\blabel:\s*'([^']+)'", body)
        path_match = re.search(r"\bpath:\s*'([^']+)'", body)
        if key_match and label_match and path_match:
            row_key = key_match.group(1)
            assert row_key not in rows, f"duplicate TypeScript route id: {constant}:{row_key}"
            rows[row_key] = (label_match.group(1), path_match.group(1))
    assert rows, f"no route rows parsed from {path.name}:{constant}"
    assert len({label for label, _ in rows.values()}) == len(rows), f"duplicate labels in {constant}"
    assert len({route for _, route in rows.values()}) == len(rows), f"duplicate paths in {constant}"
    return rows


def _guide_routes(marker: str) -> dict[str, str]:
    block = _marked(GUIDE.read_text(encoding="utf-8"), marker)
    rows: dict[str, str] = {}
    for line in block.splitlines():
        if not line.startswith("|") or re.match(r"^\|[-| ]+\|$", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2 or not cells[1].startswith("`/admin"):
            continue
        assert cells[0] not in rows, f"duplicate guide route label: {marker}:{cells[0]}"
        rows[cells[0]] = cells[1].strip("`")
    assert rows, f"no guide routes parsed from marker: {marker}"
    assert len(set(rows.values())) == len(rows), f"duplicate guide route path: {marker}"
    return rows


def _contract_routes(key: str) -> dict[str, tuple[str, str]]:
    payload = _contract()
    raw_rows = payload[key]  # type: ignore[index]
    assert isinstance(raw_rows, list)
    assert len({str(row["id"]) for row in raw_rows}) == len(raw_rows), f"duplicate contract ids: {key}"
    assert len({str(row["label"]) for row in raw_rows}) == len(raw_rows), f"duplicate contract labels: {key}"
    if key == "areas":
        rows = {
            str(row["id"]): (str(row["label"]), str(row["entry_route"]))
            for row in raw_rows
        }
    else:
        rows = {
            str(row["id"]): (str(row["label"]), str(row["path"]))
            for row in raw_rows
        }
    assert len({route for _, route in rows.values()}) == len(rows), f"duplicate contract paths: {key}"
    return rows


def _backend_routes() -> set[str]:
    routes = set(re.findall(r"`(/api/[^`]+)`", SYMBOL_MAP.read_text(encoding="utf-8")))
    for router in sorted(MODULAR_ROUTERS_DIR.glob("*.py")):
        text = router.read_text(encoding="utf-8")
        prefix_match = re.search(r"APIRouter\(prefix=[\"']([^\"']+)[\"']", text)
        prefix = prefix_match.group(1) if prefix_match else ""
        for path in re.findall(r"@router\.(?:get|post|put|patch|delete)\([\"']([^\"']+)[\"']", text):
            routes.add(f"{prefix}{path}")
    return routes


def test_top_level_admin_routes_match_source_guide_and_contract() -> None:
    source = _ts_route_rows(ADMIN_APP, "ADMIN_ROUTES", "tab")
    contract = _contract_routes("areas")
    guide = _guide_routes("admin-top-routes")
    assert contract == source
    assert guide == {label: path for label, path in source.values()}


def test_model_routes_match_source_guide_and_contract() -> None:
    cases = (
        ("ADMIN_MODELS_PAGES", "model_pages", "admin-model-routes"),
        ("ADMIN_OPENROUTER_PAGES", "openrouter_pages", "admin-openrouter-routes"),
    )
    for constant, contract_key, guide_marker in cases:
        source = _ts_route_rows(MODEL_ROUTES, constant, "id")
        assert _contract_routes(contract_key) == source
        assert _guide_routes(guide_marker) == {
            label: path for label, path in source.values()
        }


def test_change_matrix_owners_tests_and_api_examples_exist() -> None:
    payload = _contract()
    assert payload["version"] == 1
    discovered_routes = _backend_routes()
    areas = payload["areas"]
    assert isinstance(areas, list) and len(areas) == 10

    for area in areas:
        assert isinstance(area, dict)
        assert area["risk_floor"] in RISK_CLASSES
        assert area["risk_escalates_to"] in RISK_CLASSES
        assert RISK_ORDER[area["risk_escalates_to"]] >= RISK_ORDER[area["risk_floor"]]
        assert area["live_action_risk"] == "release-ops"
        assert area["frontend"] and area["backend"] and area["tests"]
        assert area["api_examples"] and area["required_controls"]
        assert isinstance(area["side_effects"], list)
        assert area["risk_escalates_when"]
        for relative in [*area["frontend"], *area["backend"], *area["tests"]]:
            assert (ROOT / relative).is_file(), f"{area['id']} references missing {relative}"
        for endpoint in area["api_examples"]:
            assert endpoint in discovered_routes, (
                f"{area['id']} API example is absent from backend evidence: {endpoint}"
            )

    by_id = {area["id"]: area for area in areas}
    assert "backend/test_admin_v2.py" in by_id["models"]["tests"]
    for endpoint in (
        "/api/admin/config-ui/reload-v2",
        "/api/admin/config-ui/switch-v2",
        "/api/admin/config-ui/interrupt-v2",
    ):
        assert endpoint in by_id["models"]["api_examples"]
    assert "backend/test_product_consistency_20e2b.py" in by_id["tariffs"]["tests"]
    assert "backend/test_social_providers.py" in by_id["notifications"]["tests"]
    assert "backend/test_social_providers.py" in by_id["social"]["tests"]
    assert "backend/app/services/social_delivery.py" in by_id["social"]["backend"]
    assert "backend/test_social_delivery.py" in by_id["social"]["tests"]
    assert "backend/app/services/bot_workers.py" in by_id["bots"]["backend"]
    assert "backend/test_bot_runtime.py" in by_id["bots"]["tests"]
    assert "backend/test_yookassa_connection_check.py" in by_id["payments"]["tests"]
    assert "/api/admin/payments/check-v2" in by_id["payments"]["api_examples"]
    assert any("config-v2" in gap for gap in by_id["payments"]["coverage_gaps"])
    assert any("mail/test-v2" in gap for gap in by_id["mail"]["coverage_gaps"])
    assert any("audit-logs-v2" in gap for gap in by_id["logs"]["coverage_gaps"])


def test_change_recipes_keep_required_executable_gates() -> None:
    text = CHANGE_CONTRACT.read_text(encoding="utf-8")
    required = (
        "python -m pytest -q tools/test_admin_docs_contract.py",
        "npm --prefix frontend run lint",
        "npm --prefix frontend run build",
        "npm --prefix frontend run e2e:admin-dashboard",
        "pwsh -File tools/verify.ps1 -Mode Quick",
        "backend/test_product_consistency_20e2b.py",
        "backend/test_social_providers.py",
        "backend/test_social_delivery.py",
        "backend/test_bot_runtime.py",
        "backend/test_yookassa_connection_check.py",
        "test_config_ui_reload_requires_reason_clears_cache_and_logs",
        "POST /api/admin/payments/config-v2",
        "POST /api/admin/mail/test-v2",
        "GET /api/admin/audit-logs-v2",
        "fake providers",
        "не запускать как обычный тест",
    )
    for phrase in required:
        assert phrase in text, f"admin change recipe lacks: {phrase}"

    assert not re.search(r"(?i)\b[A-Z]:\\", text), (
        "portable admin change contract must not contain Windows absolute paths"
    )

    scripts = json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8"))["scripts"]
    for script in (
        "lint",
        "build",
        "admin:dev",
        "e2e:admin-dashboard",
        "test:admin-image-publication",
    ):
        assert script in scripts, f"admin change recipe references missing npm script: {script}"
    assert (ROOT / "tools" / "verify.ps1").is_file()
