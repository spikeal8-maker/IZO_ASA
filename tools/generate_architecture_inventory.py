"""Generate deterministic architecture inventories without importing the app.

The generator reads Python/TypeScript/static sources and a reviewed semantic
contract. It never imports ``backend.main``, opens SQLite, touches media, or
starts a provider/worker. ``--check`` is therefore safe in CI and against a
running local production checkout.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

try:  # package import in pytest; direct import when executed from tools/
    from .generate_backend_map import Route, dotted_name, parse_source
except ImportError:  # pragma: no cover - exercised by the CLI
    from generate_backend_map import Route, dotted_name, parse_source


REPO_ROOT = Path(__file__).resolve().parents[1]
UPPER_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
API_LITERAL = re.compile(r"/api/[A-Za-z0-9_./{}:$-]+")
CREATE_TABLE = re.compile(
    r"\bCREATE\s+(?:VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
CREATE_INDEX = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
ALTER_TABLE = re.compile(
    r"\bALTER\s+TABLE\s+[`\"\[]?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TaskCall:
    source: str
    enclosing_symbol: str
    target: str
    line: int


@dataclass(frozen=True)
class LegacyAuthUse:
    source: str
    symbol: str
    operation: str
    input: str
    line: int


def relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def production_python_sources(root: Path) -> list[Path]:
    sources = [root / "backend" / "main.py"]
    sources.extend(sorted((root / "backend" / "app").rglob("*.py")))
    return [path for path in sources if path.is_file() and "__pycache__" not in path.parts]


def parse_python(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def awaitable_target(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return "<dynamic>"
    name = dotted_name(node.func)
    if name == "asyncio.to_thread" and node.args:
        nested = dotted_name(node.args[0]) or "<dynamic>"
        return f"asyncio.to_thread:{nested.rsplit('.', 1)[-1]}"
    return name.rsplit(".", 1)[-1] if name else "<dynamic>"


class _TaskVisitor(ast.NodeVisitor):
    def __init__(self, source: str):
        self.source = source
        self.symbols: list[str] = []
        self.calls: list[TaskCall] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.symbols.append(node.name)
        self.generic_visit(node)
        self.symbols.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        name = dotted_name(node.func)
        if name.rsplit(".", 1)[-1] == "create_task" and node.args:
            self.calls.append(
                TaskCall(
                    source=self.source,
                    enclosing_symbol=self.symbols[-1] if self.symbols else "<module>",
                    target=awaitable_target(node.args[0]),
                    line=node.lineno,
                )
            )
        self.generic_visit(node)


def collect_task_calls(root: Path, sources: Iterable[Path] | None = None) -> list[TaskCall]:
    calls: list[TaskCall] = []
    for path in sources or production_python_sources(root):
        visitor = _TaskVisitor(relative_path(root, path))
        visitor.visit(parse_python(path))
        calls.extend(visitor.calls)
    return sorted(calls, key=lambda item: (item.source, item.line, item.target))


def validate_registered_tasks(calls: Iterable[TaskCall], policy: dict[str, Any]) -> list[str]:
    actual = {(call.source, call.target) for call in calls}
    declared = {
        (str(item["call_source"]), str(item["target"]))
        for item in policy.get("task_registrations", [])
    }
    errors = [
        f"unregistered create_task target: {source}::{target}"
        for source, target in sorted(actual - declared)
    ]
    errors.extend(
        f"stale task registration: {source}::{target}"
        for source, target in sorted(declared - actual)
    )
    return errors


class _LegacyAuthVisitor(ast.NodeVisitor):
    def __init__(self, source: str):
        self.source = source
        self.symbols: list[str] = []
        self.uses: list[LegacyAuthUse] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.symbols.append(node.name)
        self.generic_visit(node)
        self.symbols.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        name = dotted_name(node.func).casefold()
        first = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
        if isinstance(first, str):
            value = first.casefold()
            operation = ""
            if value == "x-onenode-user" and ".headers.get" in name:
                operation = "header_read"
            elif value == "onenode_user" and ".cookies.get" in name:
                operation = "cookie_read"
            elif value == "onenode_user" and name.endswith(".set_cookie"):
                operation = "cookie_set"
            elif value == "onenode_user" and name.endswith(".delete_cookie"):
                operation = "cookie_delete"
            if operation:
                self.uses.append(
                    LegacyAuthUse(
                        source=self.source,
                        symbol=self.symbols[-1] if self.symbols else "<module>",
                        operation=operation,
                        input=value,
                        line=node.lineno,
                    )
                )
        self.generic_visit(node)


def collect_legacy_auth_uses(root: Path, sources: Iterable[Path] | None = None) -> list[LegacyAuthUse]:
    uses: list[LegacyAuthUse] = []
    for path in sources or production_python_sources(root):
        visitor = _LegacyAuthVisitor(relative_path(root, path))
        visitor.visit(parse_python(path))
        uses.extend(visitor.uses)
    return sorted(uses, key=lambda item: (item.source, item.line, item.operation))


def validate_legacy_auth_uses(uses: Iterable[LegacyAuthUse], policy: dict[str, Any]) -> list[str]:
    actual = {(use.source, use.symbol, use.operation, use.input) for use in uses}
    declared = {
        (str(item["source"]), str(item["symbol"]), str(item["operation"]), str(item["input"]))
        for item in policy.get("legacy_auth_consumers", [])
    }
    errors = [
        "unregistered legacy auth consumer: " + "::".join(key)
        for key in sorted(actual - declared)
    ]
    errors.extend(
        "stale legacy auth registration: " + "::".join(key)
        for key in sorted(declared - actual)
    )
    return errors


def reviewed_route_key(route: Route | dict[str, Any]) -> tuple[str, str, str]:
    if isinstance(route, Route):
        return route.method, route.path, route.handler
    return str(route["method"]), str(route["path"]), str(route["handler"])


def validate_reviewed_routes(routes: Iterable[Route], policy: dict[str, Any]) -> list[str]:
    actual = {
        reviewed_route_key(route)
        for route in routes
        if route.auth.startswith("REVIEW:")
    }
    declared = {reviewed_route_key(item) for item in policy.get("reviewed_routes", [])}
    errors = [
        f"unreviewed protected/operational route: {method} {path} ({handler})"
        for method, path, handler in sorted(actual - declared)
    ]
    errors.extend(
        f"stale reviewed route registration: {method} {path} ({handler})"
        for method, path, handler in sorted(declared - actual)
    )
    return errors


def _names_with_sources(matches: dict[str, set[str]]) -> list[dict[str, Any]]:
    return [
        {"name": name, "sources": sorted(sources)}
        for name, sources in sorted(matches.items())
    ]


def collect_schema_inventory(root: Path, sources: Iterable[Path]) -> dict[str, Any]:
    tables: dict[str, set[str]] = defaultdict(set)
    indexes: dict[str, set[str]] = defaultdict(set)
    altered: dict[str, set[str]] = defaultdict(set)
    foreign_keys: list[dict[str, Any]] = []
    ddl_sources: set[str] = set()
    for path in sources:
        source = relative_path(root, path)
        for node in ast.walk(parse_python(path)):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            sql = node.value
            table_names = CREATE_TABLE.findall(sql)
            index_names = CREATE_INDEX.findall(sql)
            altered_names = ALTER_TABLE.findall(sql)
            if not (table_names or index_names or altered_names):
                continue
            ddl_sources.add(source)
            for name in table_names:
                tables[name].add(source)
            for name in index_names:
                indexes[name].add(source)
            for name in altered_names:
                altered[name].add(source)
            if re.search(r"\bFOREIGN\s+KEY\b|\bREFERENCES\s+[A-Za-z_]", sql, re.IGNORECASE):
                foreign_keys.append({"source": source, "line": node.lineno})
    return {
        "sources": sorted(ddl_sources),
        "tables": _names_with_sources(tables),
        "indexes": _names_with_sources(indexes),
        "altered_tables": _names_with_sources(altered),
        "foreign_key_declarations": sorted(foreign_keys, key=lambda item: (item["source"], item["line"])),
    }


def _constant_env_argument(node: ast.Call) -> str | None:
    if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
        return None
    value = node.args[0].value
    return value if UPPER_ENV_NAME.fullmatch(value) and "_" in value else None


def collect_environment_inventory(root: Path, sources: Iterable[Path]) -> list[dict[str, Any]]:
    found: dict[str, set[str]] = defaultdict(set)
    helper_names = {"initial_runtime_secret", "_bot_secret_value"}
    for path in sources:
        source = relative_path(root, path)
        for node in ast.walk(parse_python(path)):
            if not isinstance(node, ast.Call):
                continue
            name = dotted_name(node.func)
            candidates: list[str] = []
            if name.endswith("getenv") or name.endswith("environ.get"):
                value = _constant_env_argument(node)
                if value:
                    candidates.append(value)
            elif name.rsplit(".", 1)[-1] == "get" and name.split(".", 1)[0] in {"source", "environment", "env"}:
                value = _constant_env_argument(node)
                if value:
                    candidates.append(value)
            elif name.rsplit(".", 1)[-1] in helper_names:
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        if UPPER_ENV_NAME.fullmatch(argument.value) and "_" in argument.value:
                            candidates.append(argument.value)
            for value in candidates:
                found[value].add(source)
    result = []
    for name, env_sources in sorted(found.items()):
        secret = any(marker in name for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
        result.append({"name": name, "secret": secret, "sources": sorted(env_sources)})
    return result


def frontend_sources(root: Path) -> list[Path]:
    paths: list[Path] = []
    for suffix in ("*.ts", "*.tsx", "*.js", "*.jsx"):
        paths.extend((root / "frontend" / "src").rglob(suffix))
    for suffix in ("*.html", "*.js"):
        paths.extend((root / "backend" / "static").rglob(suffix))
    return sorted({path for path in paths if path.is_file()})


def collect_frontend_api_literals(root: Path) -> list[dict[str, Any]]:
    found: dict[str, set[str]] = defaultdict(set)
    for path in frontend_sources(root):
        source = relative_path(root, path)
        for match in API_LITERAL.finditer(path.read_text(encoding="utf-8")):
            literal = match.group(0).rstrip(".,;:)")
            if "${" in literal:
                literal = literal.split("${", 1)[0] + "{dynamic}"
            found[literal].add(source)
    return [
        {"path": path, "sources": sorted(sources)}
        for path, sources in sorted(found.items())
    ]


def collect_file_limits(root: Path, policy: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in policy.get("file_limits", []):
        relative = str(item["path"])
        path = root / relative
        if not path.is_file():
            errors.append(f"file limit target missing: {relative}")
            continue
        lines = len(path.read_text(encoding="utf-8").splitlines())
        maximum = int(item["max_lines"])
        rows.append({"path": relative, "lines": lines, "max_lines": maximum, "remaining": maximum - lines})
        if lines > maximum:
            errors.append(f"file line budget exceeded: {relative} has {lines}, maximum {maximum}")
    return sorted(rows, key=lambda item: item["path"]), errors


def collect_symbol_limits(root: Path, policy: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in policy.get("symbol_limits", []):
        relative = str(item["path"])
        path = root / relative
        if not path.is_file():
            errors.append(f"symbol limit target missing: {relative}")
            continue
        symbols, routes = parse_source(path)
        counts = {
            "top_level_functions": sum(symbol.kind.endswith("function") for symbol in symbols),
            "top_level_classes": sum(symbol.kind == "class" for symbol in symbols),
            "routes": len(routes),
        }
        row: dict[str, Any] = {"path": relative, **counts}
        for count_name, maximum_name in (
            ("top_level_functions", "max_top_level_functions"),
            ("top_level_classes", "max_top_level_classes"),
            ("routes", "max_routes"),
        ):
            maximum = int(item[maximum_name])
            row[maximum_name] = maximum
            row[f"remaining_{count_name}"] = maximum - counts[count_name]
            if counts[count_name] > maximum:
                errors.append(
                    f"file symbol budget exceeded: {relative} has {counts[count_name]} "
                    f"{count_name}, maximum {maximum}"
                )
        rows.append(row)
    return sorted(rows, key=lambda item: item["path"]), errors


def validate_policy_semantics(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    route_role = str(policy.get("default_route_process_role", "")).strip()
    if not route_role:
        errors.append("default route process role is missing")

    reviewed_keys: set[tuple[str, str, str]] = set()
    for item in policy.get("reviewed_routes", []):
        key = reviewed_route_key(item)
        if key in reviewed_keys:
            errors.append("duplicate reviewed route registration: " + "::".join(key))
        reviewed_keys.add(key)
        if not str(item.get("rationale", "")).strip():
            errors.append("reviewed route rationale is missing: " + "::".join(key))

    legacy_keys: set[tuple[str, str, str, str]] = set()
    for item in policy.get("legacy_auth_consumers", []):
        key = (
            str(item["source"]),
            str(item["symbol"]),
            str(item["operation"]),
            str(item["input"]),
        )
        if key in legacy_keys:
            errors.append("duplicate legacy auth registration: " + "::".join(key))
        legacy_keys.add(key)
        if not str(item.get("rationale", "")).strip():
            errors.append("legacy auth rationale is missing: " + "::".join(key))

    task_ids: set[str] = set()
    task_keys: set[tuple[str, str]] = set()
    required_task_fields = ("owner", "role", "persistence", "startup", "recovery", "watchdog")
    for item in policy.get("task_registrations", []):
        task_id = str(item["id"])
        task_key = (str(item["call_source"]), str(item["target"]))
        if task_id in task_ids:
            errors.append(f"duplicate task registration id: {task_id}")
        if task_key in task_keys:
            errors.append("duplicate task registration target: " + "::".join(task_key))
        task_ids.add(task_id)
        task_keys.add(task_key)
        if item.get("kind") not in {"worker", "ephemeral"}:
            errors.append(f"invalid task kind: {task_id}::{item.get('kind')}")
        for field in required_task_fields:
            if not str(item.get(field, "")).strip():
                errors.append(f"task registration field is missing: {task_id}::{field}")

    integration_ids: set[str] = set()
    for item in policy.get("integrations", []):
        integration_id = str(item["id"])
        if integration_id in integration_ids:
            errors.append(f"duplicate integration id: {integration_id}")
        integration_ids.add(integration_id)
        if not str(item.get("secret_source", "")).strip():
            errors.append(f"integration secret source is missing: {integration_id}")

    for field, items, key_name in (
        ("frontend entrypoint", policy.get("frontend_entrypoints", []), None),
        ("file limit", policy.get("file_limits", []), "path"),
        ("symbol limit", policy.get("symbol_limits", []), "path"),
    ):
        seen: set[str] = set()
        for item in items:
            value = str(item if key_name is None else item[key_name])
            if value in seen:
                errors.append(f"duplicate {field}: {value}")
            seen.add(value)
    return errors


def validate_policy_files(root: Path, policy: dict[str, Any], environment_names: set[str]) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    ports: set[int] = set()
    for listener in policy.get("listeners", []):
        listener_id = str(listener["id"])
        port = int(listener["port"])
        if listener_id in ids:
            errors.append(f"duplicate listener id: {listener_id}")
        if port in ports:
            errors.append(f"duplicate listener port: {port}")
        ids.add(listener_id)
        ports.add(port)
        bind_enforcement = str(listener.get("bind_enforcement", "error"))
        if bind_enforcement not in {"error", "warn"}:
            errors.append(f"invalid listener bind enforcement: {listener_id}::{bind_enforcement}")
        for evidence in listener.get("evidence_files", []):
            if not (root / str(evidence)).is_file():
                errors.append(f"listener evidence file missing: {evidence}")

    runtime_guards = policy.get("runtime_guards", {})
    for listener_id in runtime_guards.get("allowed_full_app_listener_ids", []):
        if str(listener_id) not in ids:
            errors.append(f"full-app listener guard references unknown listener: {listener_id}")
    if not runtime_guards.get("full_app_command_contains"):
        errors.append("full-app listener guard has no command signature")
    if not runtime_guards.get("full_app_process_names"):
        errors.append("full-app listener guard has no process-name allowlist")

    for source in policy.get("frontend_entrypoints", []):
        if not (root / str(source)).is_file():
            errors.append(f"frontend entrypoint missing: {source}")

    for integration in policy.get("integrations", []):
        source = str(integration["source"])
        if not (root / source).is_file():
            errors.append(f"integration source missing: {source}")
        for env_name in [*integration.get("endpoint_env", []), *integration.get("secret_env", [])]:
            if str(env_name) not in environment_names:
                errors.append(f"integration environment input not detected: {integration['id']}::{env_name}")

    release = policy.get("release_contract", {})
    for key in ("python_version_file", "node_version_file"):
        path = str(release.get(key, ""))
        if not path or not (root / path).is_file():
            errors.append(f"release version file missing: {key}={path}")
    for required in release.get("required_files", []):
        if not (root / str(required)).is_file():
            errors.append(f"release contract file missing: {required}")
    return errors


def build_inventory(root: Path, policy: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    root = root.resolve()
    python_sources = production_python_sources(root)
    _, routes = parse_source(root / "backend" / "main.py")
    routes = sorted(routes, key=lambda route: (route.path, route.method, route.handler))
    task_calls = collect_task_calls(root, python_sources)
    legacy_uses = collect_legacy_auth_uses(root, python_sources)
    environment = collect_environment_inventory(root, python_sources)
    environment_names = {item["name"] for item in environment}
    file_limits, file_errors = collect_file_limits(root, policy)
    symbol_limits, symbol_errors = collect_symbol_limits(root, policy)

    errors = []
    errors.extend(validate_policy_semantics(policy))
    errors.extend(validate_reviewed_routes(routes, policy))
    errors.extend(validate_registered_tasks(task_calls, policy))
    errors.extend(validate_legacy_auth_uses(legacy_uses, policy))
    errors.extend(file_errors)
    errors.extend(symbol_errors)
    errors.extend(validate_policy_files(root, policy, environment_names))

    task_occurrences: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for call in task_calls:
        task_occurrences[(call.source, call.target)].append(
            {"enclosing_symbol": call.enclosing_symbol, "line": call.line}
        )
    tasks = []
    for registration in policy.get("task_registrations", []):
        item = dict(registration)
        item["occurrences"] = task_occurrences.get((item["call_source"], item["target"]), [])
        tasks.append(item)

    route_counts = Counter(route.auth for route in routes)
    release = dict(policy.get("release_contract", {}))
    python_version_path = root / str(release.get("python_version_file", ""))
    node_version_path = root / str(release.get("node_version_file", ""))
    release["python_version"] = python_version_path.read_text(encoding="utf-8").strip() if python_version_path.is_file() else None
    release["node_version"] = node_version_path.read_text(encoding="utf-8").strip() if node_version_path.is_file() else None

    inventory = {
        "schema_version": int(policy.get("schema_version", 1)),
        "validation": {"status": "ok" if not errors else "failed", "error_count": len(errors)},
        "routes": {
            "count": len(routes),
            "auth_counts": dict(sorted(route_counts.items())),
            "default_process_role": str(policy.get("default_route_process_role", "unspecified")),
            "items": [
                {
                    **asdict(route),
                    "process_role": str(policy.get("default_route_process_role", "unspecified")),
                }
                for route in routes
            ],
            "reviewed_exceptions": policy.get("reviewed_routes", []),
        },
        "tasks": {
            "registered_count": len(tasks),
            "worker_count": sum(item.get("kind") == "worker" for item in tasks),
            "ephemeral_count": sum(item.get("kind") == "ephemeral" for item in tasks),
            "items": tasks,
        },
        "legacy_auth": {
            "consumer_count": len(legacy_uses),
            "items": [asdict(use) for use in legacy_uses],
        },
        "schema": collect_schema_inventory(root, python_sources),
        "environment": environment,
        "integrations": policy.get("integrations", []),
        "frontend": {
            "entrypoints": policy.get("frontend_entrypoints", []),
            "api_literals": collect_frontend_api_literals(root),
        },
        "listeners": policy.get("listeners", []),
        "runtime_guards": policy.get("runtime_guards", {}),
        "file_limits": file_limits,
        "symbol_limits": symbol_limits,
        "release_contract": release,
        "source_contract": "architecture/contract.json",
    }
    return inventory, errors


def render_json(inventory: dict[str, Any]) -> str:
    return json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(inventory: dict[str, Any]) -> str:
    routes = inventory["routes"]
    tasks = inventory["tasks"]["items"]
    schema = inventory["schema"]
    frontend = inventory["frontend"]
    lines = [
        "# Generated architecture inventory",
        "",
        "Generated by `python tools/generate_architecture_inventory.py`. Do not edit manually.",
        "The machine-readable source of truth is `architecture/contract.json` plus the scanned repository sources.",
        "",
        "## Summary",
        "",
        f"- Routes: {routes['count']}",
        f"- Registered workers: {inventory['tasks']['worker_count']}",
        f"- Registered ephemeral tasks: {inventory['tasks']['ephemeral_count']}",
        f"- SQLite tables: {len(schema['tables'])}",
        f"- SQLite indexes: {len(schema['indexes'])}",
        f"- Foreign-key declarations: {len(schema['foreign_key_declarations'])}",
        f"- Frontend/static API literals: {len(frontend['api_literals'])}",
        f"- Route process role: `{routes['default_process_role']}`",
        "",
        "## Route authorization",
        "",
        "| Static policy | Count |",
        "|---|---:|",
    ]
    for policy, count in routes["auth_counts"].items():
        lines.append(f"| {_md_cell(policy)} | {count} |")

    lines.extend(["", "## Workers and scheduled tasks", "", "| ID | Kind | Owner | Persistence | Recovery | Watchdog |", "|---|---|---|---|---|---|"])
    for item in tasks:
        lines.append(
            "| " + " | ".join(
                _md_cell(item.get(key, ""))
                for key in ("id", "kind", "owner", "persistence", "recovery", "watchdog")
            ) + " |"
        )

    lines.extend(["", "## Listener ownership", "", "| Role | Bind | Port | Required locally | Owner command requirements |", "|---|---|---:|---|---|"])
    for item in inventory["listeners"]:
        requirements = ", ".join([*item.get("process_names", []), *item.get("command_contains", [])])
        lines.append(f"| {_md_cell(item['id'])} | `{item['bind']}` | {item['port']} | {str(bool(item.get('required_local'))).lower()} | {_md_cell(requirements)} |")

    lines.extend(["", "## SQLite declarations", "", "### Tables", "", ", ".join(f"`{item['name']}`" for item in schema["tables"]), "", "### Indexes", "", ", ".join(f"`{item['name']}`" for item in schema["indexes"]), ""])

    lines.extend(["## External integrations and secret sources", "", "| Integration | Source | Endpoint configuration | Secret inputs | Secret source |", "|---|---|---|---|---|"])
    for item in inventory["integrations"]:
        lines.append(
            f"| {_md_cell(item['id'])} | `{_md_cell(item['source'])}` | "
            f"{_md_cell(', '.join(item.get('endpoint_env', [])) or 'none')} | "
            f"{_md_cell(', '.join(item.get('secret_env', [])) or 'none')} | {_md_cell(item.get('secret_source', ''))} |"
        )

    lines.extend(["", "## Legacy identity compatibility consumers", "", "| Source | Symbol | Operation | Input |", "|---|---|---|---|"])
    for item in inventory["legacy_auth"]["items"]:
        lines.append(f"| `{item['source']}` | `{item['symbol']}` | {item['operation']} | `{item['input']}` |")

    lines.extend(["", "## Frontend entrypoints", ""])
    lines.extend(f"- `{item}`" for item in frontend["entrypoints"])
    lines.extend(["", "## Frontend/static API literals", "", "| Literal | Sources |", "|---|---|"])
    for item in frontend["api_literals"]:
        lines.append(f"| `{_md_cell(item['path'])}` | {_md_cell(', '.join(item['sources']))} |")

    lines.extend(["", "## Large-file budgets", "", "| Path | Current | Maximum | Remaining |", "|---|---:|---:|---:|"])
    for item in inventory["file_limits"]:
        lines.append(f"| `{item['path']}` | {item['lines']} | {item['max_lines']} | {item['remaining']} |")

    lines.extend(["", "## Symbol budgets", "", "| Path | Functions | Maximum | Classes | Maximum | Routes | Maximum |", "|---|---:|---:|---:|---:|---:|---:|"])
    for item in inventory["symbol_limits"]:
        lines.append(
            f"| `{item['path']}` | {item['top_level_functions']} | {item['max_top_level_functions']} | "
            f"{item['top_level_classes']} | {item['max_top_level_classes']} | "
            f"{item['routes']} | {item['max_routes']} |"
        )

    release = inventory["release_contract"]
    lines.extend(
        [
            "",
            "## Release identity baseline",
            "",
            f"- Python: `{release.get('python_version')}` from `{release.get('python_version_file')}`",
            f"- Node.js: `{release.get('node_version')}` from `{release.get('node_version_file')}`",
            "- Required future manifest fields: " + ", ".join(f"`{item}`" for item in release.get("future_manifest_fields", [])),
            "- Known gaps:",
        ]
    )
    lines.extend(f"  - {item}" for item in release.get("known_gaps", []))
    lines.append("")
    return "\n".join(lines)


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--policy", type=Path, default=Path("architecture/contract.json"))
    parser.add_argument("--json-output", type=Path, default=Path("docs/generated/architecture-inventory.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("docs/generated/architecture-inventory.md"))
    parser.add_argument("--check", action="store_true", help="Fail if generated artifacts differ from the repository.")
    args = parser.parse_args()

    root = args.root.resolve()
    policy_path = _resolve(root, args.policy)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    inventory, errors = build_inventory(root, policy)
    if errors:
        for error in errors:
            print(f"architecture contract error: {error}")
        return 2

    artifacts = {
        _resolve(root, args.json_output): render_json(inventory),
        _resolve(root, args.markdown_output): render_markdown(inventory),
    }
    if args.check:
        outdated = []
        for path, expected in artifacts.items():
            current = path.read_text(encoding="utf-8") if path.is_file() else ""
            if current != expected:
                outdated.append(relative_path(root, path))
        if outdated:
            for path in outdated:
                print(f"outdated: {path}")
            return 1
        print("ok: architecture inventory")
        return 0

    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {relative_path(root, path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
