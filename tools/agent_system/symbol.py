"""Deterministic bounded symbol context from existing repository evidence."""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

MAX_SOURCE_LINES = 80
MAX_RESPONSE_BYTES = 32 * 1024
MAX_RESPONSE_LINES = 250
MAX_SOURCE_LINE_CHARS = 240
BACKEND_MAP = Path("backend/SYMBOL_MAP.md")
FRONTEND_MAP = Path("docs/generated/frontend-map.json")
CONTEXT_INDEX = Path("docs/generated/context-index.json")
ARCHITECTURE_INVENTORY = Path("docs/generated/architecture-inventory.json")
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


class SymbolContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class TsDecl:
    name: str
    kind: str
    start: int
    end: int
    start_index: int
    end_index: int


def _json_file(root: Path, relative: Path) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SymbolContextError(f"generated evidence unreadable: {relative.as_posix()}") from exc
    return value if isinstance(value, dict) else {}


def _safe_path(root: Path, requested: str) -> tuple[str, Path]:
    raw = requested.strip().replace("\\", "/")
    if not raw:
        raise SymbolContextError("path is required")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise SymbolContextError(f"absolute path rejected: {requested}")
    pure = PurePosixPath(raw)
    if any(part == ".." for part in pure.parts):
        raise SymbolContextError(f"path traversal rejected: {requested}")
    relative = pure.as_posix()
    candidate = root.joinpath(*pure.parts)
    if not candidate.exists() or not candidate.is_file():
        raise SymbolContextError(f"path missing: {relative}")
    resolved_root, resolved = root.resolve(), candidate.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise SymbolContextError(f"repository escape rejected: {relative}")
    return relative, resolved


def _classification(root: Path, relative: str) -> str:
    name = PurePosixPath(relative).name.lower()
    if re.search(r"\.min\.(?:js|css|mjs|cjs)$", name):
        return "minified"
    if relative == "backend/SYMBOL_MAP.md" or relative.startswith("docs/generated/"):
        return "generated"
    policy = _json_file(root, ARCHITECTURE_INVENTORY).get("source_size_policy", {})
    for item in policy.get("classifications", []) if isinstance(policy, dict) else []:
        if isinstance(item, dict):
            pattern, kind = str(item.get("pattern", "")), str(item.get("kind", ""))
            if kind in {"generated", "vendor"} and pattern and fnmatch.fnmatchcase(relative, pattern):
                return kind
    if set(PurePosixPath(relative).parts) & {"node_modules", ".venv", "vendor"}:
        return "vendor"
    return "source" if PurePosixPath(relative).suffix.lower() in SOURCE_SUFFIXES else "unsupported"


def _source_window(lines: list[str], start: int, end: int) -> dict[str, Any]:
    actual_end = min(end, start + MAX_SOURCE_LINES - 1, len(lines))
    values = []
    for number in range(start, actual_end + 1):
        text = lines[number - 1]
        if len(text) > MAX_SOURCE_LINE_CHARS:
            text = text[: MAX_SOURCE_LINE_CHARS - 1] + "…"
        values.append({"line": number, "text": text})
    return {"start": start, "end": actual_end, "truncated": actual_end < end, "lines": values}


def _sort_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(routes, key=lambda x: (
        str(x.get("source", "")), str(x.get("method", "")), str(x.get("path", "")),
        str(x.get("predicate", "")), int(x.get("line", 0) or 0),
    ))


def _serialize_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _fit_budget(result: dict[str, Any]) -> dict[str, Any]:
    window = result.get("sourceWindow")
    while True:
        text = _serialize_json(result)
        if len(text.encode("utf-8")) <= MAX_RESPONSE_BYTES and len(text.splitlines()) <= MAX_RESPONSE_LINES:
            return result
        if not isinstance(window, dict) or not window.get("lines"):
            raise SymbolContextError("symbol context exceeds response budget")
        window["lines"].pop()
        window["end"] = window["lines"][-1]["line"] if window["lines"] else window["start"]
        window["truncated"] = True


def render_symbol_context(result: dict[str, Any]) -> str:
    text = _serialize_json(_fit_budget(result))
    if len(text.encode("utf-8")) > MAX_RESPONSE_BYTES or len(text.splitlines()) > MAX_RESPONSE_LINES:
        raise SymbolContextError("symbol context exceeds response budget")
    return text + "\n"


def _backend_map_evidence(root: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    path = root / BACKEND_MAP
    if not path.is_file():
        return {}, []
    symbols: dict[str, dict[str, Any]] = {}
    routes: list[dict[str, Any]] = []
    section = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("## "):
            section = raw[3:].strip().lower()
            continue
        if section.startswith("routes"):
            match = re.match(r"^\|\s*([A-Z]+)\s*\|\s*`([^`]*)`\s*\|\s*`([^`]*)`\s*\|\s*(\d+)\s*\|", raw)
            if match:
                routes.append({"method": match[1], "path": match[2], "handler": match[3],
                               "line": int(match[4]), "source": BACKEND_MAP.as_posix()})
        elif section == "functions":
            match = re.match(r"^\|\s*`([^`]*)`\s*\|\s*([^|]+?)\s*\|\s*(\d+)[–-](\d+)\s*\|$", raw)
            if match:
                symbols[match[1]] = {"kind": match[2].strip(), "start": int(match[3]), "end": int(match[4])}
        elif section == "classes":
            match = re.match(r"^\|\s*`([^`]*)`\s*\|\s*(\d+)[–-](\d+)\s*\|$", raw)
            if match:
                symbols[match[1]] = {"kind": "class", "start": int(match[2]), "end": int(match[3])}
    return symbols, routes


def _frontend_evidence(root: Path, relative: str) -> tuple[list[dict[str, Any]], set[str]]:
    routes, tests = [], set()
    for item in _json_file(root, FRONTEND_MAP).get("routes", []):
        if not isinstance(item, dict):
            continue
        components, entry = [str(v) for v in item.get("components", [])], str(item.get("entry", ""))
        if relative != entry and relative not in components:
            continue
        routes.append({"entry": entry, "paths": sorted(str(v) for v in item.get("paths", [])),
                       "predicate": str(item.get("predicate", "")), "source": FRONTEND_MAP.as_posix()})
        tests.update(str(v) for v in item.get("tests", []) if str(v) != "unknown")
    return routes, tests


def _context_evidence(root: Path, relative: str) -> tuple[list[str], set[str]]:
    domains, tests = [], set()
    for card in _json_file(root, CONTEXT_INDEX).get("cards", []):
        if not isinstance(card, dict) or relative not in card.get("source_paths", []):
            continue
        if card.get("domain"):
            domains.append(str(card["domain"]))
        tests.update(str(v) for v in card.get("test_paths", []) if str(v) != "unknown")
    return sorted(set(domains)), tests


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, root: ast.AST):
        self.root, self.calls, self.loaded_names = root, [], set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node.func)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.loaded_names.add(node.id)


def _python_import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".", 1)[0]] = item.name
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level + (node.module or "")
            for item in node.names:
                if item.name != "*":
                    suffix = f".{item.name}" if node.module else item.name
                    aliases[item.asname or item.name] = prefix + suffix
    return aliases


def _python_kind(node: ast.AST) -> str:
    if isinstance(node, ast.AsyncFunctionDef):
        return "async function"
    if isinstance(node, ast.FunctionDef):
        return "function"
    return "class" if isinstance(node, ast.ClassDef) else type(node).__name__


def _python_routes(node: ast.AST) -> list[dict[str, Any]]:
    routes = []
    for decorator in getattr(node, "decorator_list", []):
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        method = decorator.func.attr.upper()
        arg = decorator.args[0] if decorator.args else None
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"} and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            routes.append({"method": method, "path": arg.value, "line": getattr(node, "lineno", 0),
                           "source": "static-exact-file"})
    return routes


def _python_analysis(root: Path, relative: str, source_path: Path, symbol: str) -> dict[str, Any]:
    text, lines = source_path.read_text(encoding="utf-8"), source_path.read_text(encoding="utf-8").splitlines()
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as exc:
        raise SymbolContextError(f"python parse failed: {relative}:{exc.lineno}") from exc
    matches = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == symbol]
    if not matches:
        raise SymbolContextError(f"symbol not found: {relative}::{symbol}")
    if len(matches) > 1:
        raise SymbolContextError(f"symbol ambiguous: {relative}::{symbol}")
    target = matches[0]
    start, end, kind, routes = target.lineno, target.end_lineno or target.lineno, _python_kind(target), _python_routes(target)
    if relative == "backend/main.py":
        mapped, mapped_routes = _backend_map_evidence(root)
        if symbol in mapped:
            kind, start, end = str(mapped[symbol]["kind"]), int(mapped[symbol]["start"]), int(mapped[symbol]["end"])
        routes = [{k: v for k, v in item.items() if k != "handler"} for item in mapped_routes if item["handler"] == symbol] or routes
    top = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    visitor = _PythonVisitor(target)
    visitor.visit(target)
    named = {f.id for f in visitor.calls if isinstance(f, ast.Name)}
    callees = sorted(name for name in named if name in top and name != symbol)
    callers = []
    for name, node in top.items():
        if name == symbol:
            continue
        other = _PythonVisitor(node)
        other.visit(node)
        if any(isinstance(f, ast.Name) and f.id == symbol for f in other.calls):
            callers.append(name)
    aliases = _python_import_aliases(tree)
    imports = sorted({value for name, value in aliases.items() if name in visitor.loaded_names})
    unknown = ["Python static analysis does not resolve attribute/subscript/dynamic call targets."] if any(
        not isinstance(f, ast.Name) for f in visitor.calls
    ) else []
    return {
        "kind": kind, "declaration": lines[start - 1].strip(), "declarationRange": {"start": start, "end": end},
        "sourceWindow": _source_window(lines, start, end), "imports": imports, "directCallers": sorted(callers),
        "directCallees": callees, "routes": _sort_routes(routes), "unknownEdges": unknown,
    }


_TS_PATTERNS = (
    (re.compile(r"(?m)^(?P<indent>[ \t]*)(?:export\s+default\s+|export\s+)?(?P<async>async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\("), "function"),
    (re.compile(r"(?m)^(?P<indent>[ \t]*)(?:export\s+default\s+|export\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)\b"), "class"),
    (re.compile(r"(?m)^(?P<indent>[ \t]*)(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)[^\n=]*=\s*(?P<async>async\s+)?(?:\([^\n]*?\)|[A-Za-z_$][\w$]*)\s*=>"), "arrow function"),
)


def _mask_ts(text: str) -> str:
    chars, state, quote, escaped, i = list(text), "code", "", False, 0
    while i < len(text):
        c, n = text[i], text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if c == "/" and n in {"/", "*"}:
                chars[i] = chars[i + 1] = " "
                state, i = ("line" if n == "/" else "block"), i + 2
                continue
            if c in {"'", '"', "`"}:
                chars[i], state, quote, escaped = " ", ("template" if c == "`" else "string"), c, False
            i += 1
            continue
        if c == "\n":
            if state == "line":
                state = "code"
            i += 1
            continue
        chars[i] = " "
        if state == "block" and c == "*" and n == "/":
            chars[i + 1], state, i = " ", "code", i + 2
            continue
        if state in {"string", "template"}:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == quote:
                state = "code"
        i += 1
    return "".join(chars)


def _find_code_brace(masked: str, start: int) -> int | None:
    opening = masked.find("{", start)
    if opening < 0:
        return None
    semicolon = masked.find(";", start, opening)
    return None if semicolon >= 0 else opening


def _matching_brace(masked: str, opening: int) -> int | None:
    depth = 0
    for i in range(opening, len(masked)):
        if masked[i] == "{":
            depth += 1
        elif masked[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _ts_decl(text: str, masked: str, match: re.Match[str], base_kind: str) -> TsDecl:
    kind = ("async " + base_kind) if match.groupdict().get("async") else base_kind
    opening = _find_code_brace(masked, match.end())
    if opening is None:
        stop = masked.find("\n", match.end())
        end_index = len(masked) if stop < 0 else stop
    else:
        end_index = _matching_brace(masked, opening)
        if end_index is None:
            raise SymbolContextError(f"unterminated TS/TSX declaration: {match.group('name')}")
    start = text.count("\n", 0, match.start()) + 1
    end = text.count("\n", 0, end_index) + 1
    return TsDecl(match.group("name"), kind, start, end, match.start(), end_index)


def _all_ts_decls(text: str, masked: str) -> dict[str, TsDecl]:
    declarations = {}
    for pattern, kind in _TS_PATTERNS:
        for match in pattern.finditer(masked):
            if not match.group("indent") and match.group("name") not in declarations:
                declarations[match.group("name")] = _ts_decl(text, masked, match, kind)
    return declarations


def _ts_direct_call(masked_body: str, name: str) -> bool:
    return re.search(rf"(?<![\w$.]){re.escape(name)}\s*\(", masked_body) is not None


def _ts_import_bindings(text: str, masked: str) -> list[tuple[str, str]]:
    bindings = []
    pattern = re.compile(r"(?ms)^[ \t]*import\s+(?:type\s+)?(?P<clause>.+?)\s+from\b")
    for match in pattern.finditer(masked):
        clause = match.group("clause").strip()
        source_match = re.match(r"\s*(['\"])(?P<source>[^'\"]+)\1", text[match.end():])
        if not source_match:
            continue
        source = source_match.group("source")
        default = clause.split(",", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", default):
            bindings.append((default, source))
        namespace = re.search(r"\*\s+as\s+([A-Za-z_$][\w$]*)", clause)
        if namespace:
            bindings.append((namespace.group(1), source))
        named = re.search(r"\{(.*?)\}", clause, re.S)
        if named:
            for item in named.group(1).split(","):
                cleaned = re.sub(r"^\s*type\s+", "", item.strip())
                if cleaned:
                    bound = re.split(r"\s+as\s+", cleaned)[-1].strip()
                    if re.fullmatch(r"[A-Za-z_$][\w$]*", bound):
                        bindings.append((bound, source))
    return bindings

def _ts_dependency(relative: str, source: str) -> str:
    if not source.startswith("."):
        return source
    return posixpath.normpath(posixpath.join(PurePosixPath(relative).parent.as_posix(), source))


def _tsx_analysis(root: Path, relative: str, source_path: Path, symbol: str) -> dict[str, Any]:
    text = source_path.read_text(encoding="utf-8")
    masked, lines = _mask_ts(text), text.splitlines()
    declarations = _all_ts_decls(text, masked)
    if symbol not in declarations:
        raise SymbolContextError(f"symbol not found: {relative}::{symbol}")
    target = declarations[symbol]
    body = masked[target.start_index:target.end_index + 1]
    imports = sorted({_ts_dependency(relative, source) for bound, source in _ts_import_bindings(text, masked)
                      if re.search(rf"(?<![\w$]){re.escape(bound)}(?![\w$])", body)})
    callees = sorted(name for name in declarations if name != symbol and _ts_direct_call(body, name))
    callers = []
    for name, declaration in declarations.items():
        other = masked[declaration.start_index:declaration.end_index + 1]
        if name != symbol and _ts_direct_call(other, symbol):
            callers.append(name)
    frontend_routes, frontend_tests = _frontend_evidence(root, relative)

    return {
        "kind": target.kind, "declaration": lines[target.start - 1].strip(),
        "declarationRange": {"start": target.start, "end": target.end},
        "sourceWindow": _source_window(lines, target.start, target.end), "imports": imports,
        "directCallers": sorted(callers), "directCallees": callees, "routes": _sort_routes(frontend_routes),
        "frontendTests": frontend_tests,
        "unknownEdges": ["TS/TSX lexical analysis masks comments/strings/templates and does not resolve member, optional-chain, JSX, hook, higher-order, template-interpolation, or other dynamic call edges."],
    }


def _empty_analysis(classification: str) -> dict[str, Any]:
    return {
        "kind": None, "declaration": None, "declarationRange": None,
        "sourceWindow": {"start": None, "end": None, "truncated": False, "lines": []},
        "imports": [], "directCallers": [], "directCallees": [], "routes": [],
        "unknownEdges": [f"symbol analysis skipped for {classification} classification."],
    }


def build_symbol_context(root: Path, requested_path: str, symbol: str) -> dict[str, Any]:
    root, symbol = root.resolve(), symbol.strip()
    if not symbol:
        raise SymbolContextError("symbol is required")
    relative, source_path = _safe_path(root, requested_path)
    classification = _classification(root, relative)
    domains, context_tests = _context_evidence(root, relative)
    frontend_tests: set[str] = set()
    if classification != "source":
        analysis = _empty_analysis(classification)
    elif source_path.suffix.lower() == ".py":
        analysis = _python_analysis(root, relative, source_path, symbol)
    elif source_path.suffix.lower() in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        analysis = _tsx_analysis(root, relative, source_path, symbol)
        frontend_tests = set(analysis.pop("frontendTests", set()))
    else:
        classification, analysis = "unsupported", _empty_analysis("unsupported")
    result = {
        "schemaVersion": 1, "path": relative, "symbol": symbol, "classification": classification,
        "kind": analysis["kind"], "declaration": analysis["declaration"],
        "declarationRange": analysis["declarationRange"], "sourceWindow": analysis["sourceWindow"],
        "imports": sorted(analysis["imports"]), "directCallers": sorted(analysis["directCallers"]),
        "directCallees": sorted(analysis["directCallees"]), "routes": _sort_routes(analysis["routes"]),
        "tests": sorted(context_tests | frontend_tests), "contextDomains": domains,
        "unknownEdges": sorted(set(analysis["unknownEdges"])),
    }
    return _fit_budget(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent symbol")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--path", required=True)
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args(argv)
    try:
        print(render_symbol_context(build_symbol_context(Path(args.repo_root), args.path, args.symbol)), end="")
        return 0
    except SymbolContextError as exc:
        print(_serialize_json({"error": str(exc), "schemaVersion": 1}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
