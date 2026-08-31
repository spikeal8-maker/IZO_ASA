"""Executable contract for the bounded critical admin mutation audit."""
from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs" / "admin-mutation-audit.md"
TASK = ROOT / "docs" / "agent-tasks" / "ADMIN-MUTATION-AUDIT-001.md"
CHANGE_CONTRACT = ROOT / "docs" / "admin-change-contract.md"
CONTEXT = ROOT / "docs" / "context" / "admin-control-center.md"
GUIDE = ROOT / "docs" / "admin-panel-guide.md"
MAIN = ROOT / "backend" / "main.py"
SYMBOL_MAP = ROOT / "backend" / "SYMBOL_MAP.md"

MARKER = re.compile(
    r"<!-- admin-mutation-audit-json:start -->.*?```json\s*(\{.*?\})\s*```.*?"
    r"<!-- admin-mutation-audit-json:end -->",
    re.DOTALL,
)
ROUTE_ROW = re.compile(
    r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|",
    re.MULTILINE,
)
EXPECTED_ROUTES = {
    ("POST", "/api/admin/users/{internal_user_id}/block-v2", "admin_block_user_v2"),
    ("POST", "/api/admin/users/{internal_user_id}/unblock-v2", "admin_unblock_user_v2"),
    ("POST", "/api/admin/users/{internal_user_id}/password-reset-v2", "admin_password_reset_v2"),
    ("POST", "/api/admin/users/{internal_user_id}/role-v2", "admin_role_v2"),
    ("POST", "/api/admin/users/{internal_user_id}/tokens-v2", "admin_tokens_v2"),
    ("POST", "/api/admin/users/{internal_user_id}/discount-v2", "admin_discount_v2"),
    ("POST", "/api/admin/users/{internal_user_id}/plan-v2", "admin_plan_v2"),
    ("POST", "/api/admin/users/{internal_user_id}/profile-v2", "admin_profile_v2"),
    ("POST", "/api/admin/payments/{payment_id}/simulate-v2", "admin_simulate_payment_v2"),
    ("POST", "/api/admin/payments/reconcile-v2", "admin_reconcile_payments_v2"),
    ("POST", "/api/admin/payments/notifications/process-v2", "admin_process_payment_notifications_v2"),
    ("POST", "/api/admin/users/{internal_user_id}/invoices-v2", "admin_create_invoice_v2"),
    ("POST", "/api/admin/invoices/{invoice_id}/mark-paid-v2", "admin_mark_invoice_paid_v2"),
    ("POST", "/api/admin/invoices/{invoice_id}/cancel-v2", "admin_cancel_invoice_v2"),
    ("POST", "/api/admin/payments/{payment_id}/refund-v2", "admin_refund_payment_v2"),
    ("POST", "/api/admin/users/{internal_user_id}/bonus-v2", "admin_bonus_grant_v2"),
    ("POST", "/api/admin/users/{internal_user_id}/bonus/{bonus_id}/cancel-v2", "admin_bonus_cancel_v2"),
    ("POST", "/api/admin/users/{internal_user_id}/apply-promo-v2", "admin_apply_promo_v2"),
    ("POST", "/api/admin/users/{internal_user_id}/referral-reward-v2", "admin_referral_reward_v2"),
}
EVIDENCE_ARTIFACT_PATHS = {
    "backend/main.py",
    "backend/SYMBOL_MAP.md",
    "backend/test_admin_v2.py",
    "backend/test_admin_password_reset.py",
    "backend/test_admin_actions.py",
    "backend/test_product_consistency_20e2b.py",
    "backend/test_billing_simulator_checkout_v2.py",
    "backend/test_billing_notification_outbox.py",
    "backend/test_billing_v2.py",
    "backend/test_promo_bonus_referral_v2.py",
}
REASON_GAP_ROUTES = {
    ("POST", "/api/admin/payments/{payment_id}/simulate-v2", "admin_simulate_payment_v2"),
    ("POST", "/api/admin/payments/reconcile-v2", "admin_reconcile_payments_v2"),
    (
        "POST",
        "/api/admin/payments/notifications/process-v2",
        "admin_process_payment_notifications_v2",
    ),
}
AUDIT_PARTIAL_ROUTES = {
    ("POST", "/api/admin/payments/{payment_id}/simulate-v2", "admin_simulate_payment_v2"),
    ("POST", "/api/admin/payments/reconcile-v2", "admin_reconcile_payments_v2"),
    (
        "POST",
        "/api/admin/payments/notifications/process-v2",
        "admin_process_payment_notifications_v2",
    ),
}


def _payload() -> dict[str, object]:
    match = MARKER.search(AUDIT.read_text(encoding="utf-8"))
    assert match, "admin mutation audit lacks its marked JSON contract"
    return json.loads(match.group(1))


def _route_key(route: dict[str, object]) -> tuple[str, str, str]:
    return str(route["method"]), str(route["path"]), str(route["symbol"])


def _main_functions(source: str) -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    tree = ast.parse(source, filename=str(MAIN))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }


def _source_fingerprint(
    source: str,
    node: ast.AsyncFunctionDef | ast.FunctionDef,
) -> str:
    lines = source.splitlines(keepends=True)
    start_line = min([node.lineno, *(item.lineno for item in node.decorator_list)])
    assert node.end_lineno is not None
    segment = "".join(lines[start_line - 1 : node.end_lineno])
    return "sha256:" + hashlib.sha256(segment.encode("utf-8")).hexdigest()


def _artifact_fingerprint(relative: str) -> str:
    source = (ROOT / relative).read_text(encoding="utf-8")
    return "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()


def _decorated_routes(
    node: ast.AsyncFunctionDef | ast.FunctionDef,
) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "app":
            continue
        if decorator.func.attr not in {"get", "post", "put", "patch", "delete"}:
            continue
        if decorator.args and isinstance(decorator.args[0], ast.Constant):
            routes.add((decorator.func.attr.upper(), str(decorator.args[0].value)))
    return routes


def _call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            names.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            names.add(child.func.attr)
    return names


def _has_db_context(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, (ast.With, ast.AsyncWith)):
            continue
        for item in child.items:
            expr = item.context_expr
            if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "db":
                return True
    return False


def _test_functions(path: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _string_candidates(node: ast.AST) -> set[str]:
    candidates: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            candidates.add(child.value)
        elif isinstance(child, ast.JoinedStr):
            parts: list[str] = []
            for value in child.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    parts.append("__route_parameter__")
            candidates.add("".join(parts))
    return candidates


def _route_pattern(path: str) -> re.Pattern[str]:
    parts: list[str] = []
    cursor = 0
    for parameter in re.finditer(r"\{[^{}]+\}", path):
        parts.append(re.escape(path[cursor : parameter.start()]))
        parts.append(r"[^/?#]+")
        cursor = parameter.end()
    parts.append(re.escape(path[cursor:]))
    return re.compile(r"^" + "".join(parts) + r"(?:\?[^#]*)?(?:#.*)?$")


def test_audit_has_exact_bounded_scope_and_summary() -> None:
    payload = _payload()
    assert payload["version"] == 1
    assert payload["scope"] == "critical-compatibility-identity-crm-finance-v1"
    assert re.fullmatch(r"[0-9a-f]{40}", str(payload["source_sha"]))
    assert payload["source_fingerprint_algorithm"] == "sha256-decorated-source-v1"
    assert payload["evidence_artifact_algorithm"] == "sha256-normalized-text-v1"
    artifacts = payload["evidence_artifacts"]
    assert isinstance(artifacts, list)
    assert {str(item["path"]) for item in artifacts} == EVIDENCE_ARTIFACT_PATHS
    for artifact in artifacts:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", str(artifact["fingerprint"]))
        assert artifact["fingerprint"] == _artifact_fingerprint(str(artifact["path"]))
    routes = payload["routes"]
    assert isinstance(routes, list)
    assert {_route_key(route) for route in routes} == EXPECTED_ROUTES
    assert all(
        re.fullmatch(r"sha256:[0-9a-f]{64}", str(route["source_fingerprint"]))
        for route in routes
    )
    statuses = Counter(str(route["status"]) for route in routes)
    assert dict(statuses) == payload["summary"] == {"verified": 6, "partial": 7, "gap": 6}

    all_admin_mutations = {
        (method, path, symbol)
        for method, path, symbol in ROUTE_ROW.findall(SYMBOL_MAP.read_text(encoding="utf-8"))
        if path.startswith("/api/admin/") and method in {"POST", "PUT", "PATCH", "DELETE"}
    }
    assert EXPECTED_ROUTES < all_admin_mutations, "audit must remain an explicit bounded subset"
    assert len(all_admin_mutations) == 58
    assert len(all_admin_mutations - EXPECTED_ROUTES) == 39


def test_audited_routes_match_symbol_map_and_source_decorators() -> None:
    payload = _payload()
    symbol_rows = set(ROUTE_ROW.findall(SYMBOL_MAP.read_text(encoding="utf-8")))
    main_source = MAIN.read_text(encoding="utf-8")
    functions = _main_functions(main_source)
    for route in payload["routes"]:
        key = _route_key(route)
        assert key in symbol_rows, f"route is absent from generated symbol evidence: {key}"
        method, path, symbol = key
        assert symbol in functions, f"missing backend symbol: {symbol}"
        assert (method, path) in _decorated_routes(functions[symbol]), (
            f"source decorator differs from audit: {method} {path} -> {symbol}"
        )
        assert route["source_fingerprint"] == _source_fingerprint(
            main_source, functions[symbol]
        ), f"audited handler changed without refreshing evidence: {symbol}"


def test_every_route_keeps_trusted_admin_reason_audit_and_db_boundary() -> None:
    payload = _payload()
    functions = _main_functions(MAIN.read_text(encoding="utf-8"))
    for route in payload["routes"]:
        symbol = str(route["symbol"])
        node = functions[symbol]
        calls = _call_names(node)
        attrs = {child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)}
        assert route["auth"] == "verified" and "require_trusted_admin" in calls, symbol
        if _route_key(route) in REASON_GAP_ROUTES:
            assert route["reason"] == "gap-whitespace-only-accepted", symbol
            assert "reason" in attrs and "_billing_reason" not in calls, symbol
        else:
            assert route["reason"] == "verified" and (
                "reason" in attrs or "_billing_reason" in calls
            ), symbol
        if _route_key(route) in AUDIT_PARTIAL_ROUTES:
            assert route["audit"] == "partial-post-effect", symbol
        else:
            assert route["audit"] == "verified", symbol
        assert "record_audit_log" in calls, symbol
        assert _has_db_context(node), f"{symbol} lacks an explicit db context"
        assert route["transaction"] in {"atomic-local", "split-provider-db"}


def test_route_test_nodes_exist_and_at_least_one_exercises_the_route() -> None:
    payload = _payload()
    parsed_files: dict[Path, dict[str, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    source_text: dict[Path, str] = {}
    for route in payload["routes"]:
        nodes = route["test_nodes"]
        assert isinstance(nodes, list) and nodes, f"{route['symbol']} has no test nodes"
        route_pattern = _route_pattern(str(route["path"]))
        route_is_exercised = False
        for node_id in nodes:
            relative, separator, function_name = str(node_id).partition("::")
            assert separator and relative.startswith("backend/test_")
            path = ROOT / relative
            assert path.is_file(), f"missing test file: {relative}"
            parsed_files.setdefault(path, _test_functions(path))
            source_text.setdefault(path, path.read_text(encoding="utf-8"))
            assert function_name in parsed_files[path], f"missing test node: {node_id}"
            node = parsed_files[path][function_name]
            route_is_exercised = route_is_exercised or any(
                route_pattern.fullmatch(candidate)
                for candidate in _string_candidates(node)
            )
        assert route_is_exercised, f"no declared test node exercises {route['path']}"


def test_route_template_matching_does_not_confuse_block_and_unblock() -> None:
    pattern = _route_pattern("/api/admin/users/{internal_user_id}/block-v2")
    assert pattern.fullmatch("/api/admin/users/test-user/block-v2")
    assert not pattern.fullmatch("/api/admin/users/test-user/unblock-v2")


def test_gap_links_and_remediation_are_complete() -> None:
    payload = _payload()
    routes = payload["routes"]
    gaps = payload["gaps"]
    gap_by_id = {str(gap["id"]): gap for gap in gaps}
    assert len(gap_by_id) == len(gaps)
    assert set(gap_by_id) == {
        "AM-001",
        "AM-002",
        "AM-003",
        "AM-004",
        "AM-005",
        "AM-006",
        "AM-007",
        "AM-008",
        "AM-009",
    }
    maintenance_gap = gap_by_id["AM-005"]
    assert "explicit operator authorization" in maintenance_gap["remediation"]
    assert "redacted receipt" in maintenance_gap["remediation"]
    assert "durable pre-action command/audit intent" in maintenance_gap["remediation"]
    assert "every listed maintenance route" in maintenance_gap["remediation"]
    assert any(
        "blocked without explicit operator authorization" in required
        for required in maintenance_gap["required_tests"]
    )
    required_tests = maintenance_gap["required_tests"]
    assert any("crash after committed simulate effect" in required for required in required_tests)
    assert any("crash after committed reconcile effect" in required for required in required_tests)
    assert any("crash after notification send" in required for required in required_tests)
    known_method_paths = {f"{route['method']} {route['path']}" for route in routes}

    for gap_id, gap in gap_by_id.items():
        assert gap["priority"] in {"P1", "P2"}
        assert gap["title"] and gap["evidence"] and gap["remediation"]
        assert isinstance(gap["required_tests"], list) and gap["required_tests"]
        assert set(gap["routes"]) <= known_method_paths, f"{gap_id} references out-of-scope route"

    for route in routes:
        route_gaps = route["gap_ids"]
        assert route["risk"] and route["replay"] and route["test_evidence"]
        if route["status"] == "verified":
            assert route_gaps == []
        else:
            assert route_gaps, f"{route['symbol']} is non-verified without a gap"
        method_path = f"{route['method']} {route['path']}"
        for gap_id in route_gaps:
            assert gap_id in gap_by_id
            assert method_path in gap_by_id[gap_id]["routes"]


def test_task_contract_keeps_product_and_live_actions_out_of_scope() -> None:
    text = TASK.read_text(encoding="utf-8")
    required = (
        "package_mode: bounded-discovery",
        "risk_class: high-assurance",
        "ровно 19",
        "backend/main.py",
        "production DB/media/secrets/runtime",
        "live payment/refund",
        "Rollback ограничен",
    )
    for phrase in required:
        assert phrase in text


def test_admin_docs_route_critical_mutations_through_the_audit() -> None:
    change_text = CHANGE_CONTRACT.read_text(encoding="utf-8")
    context_text = CONTEXT.read_text(encoding="utf-8")
    guide_text = GUIDE.read_text(encoding="utf-8")
    assert "python -m pytest -q tools/test_admin_mutation_audit.py" in change_text
    assert "docs/admin-mutation-audit.md" in change_text
    assert "docs/admin-mutation-audit.md" in context_text
    assert "Ещё 39" in context_text
    assert "routes вне его scope нельзя считать прошедшими" in context_text
    assert "docs/admin-mutation-audit.md" in guide_text
    assert "tools/test_admin_mutation_audit.py" in guide_text
    assert "Ещё 39" in guide_text
