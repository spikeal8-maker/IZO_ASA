from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .generate_backend_map import HTTP_METHODS, ROUTE_DECORATOR_BASES, dotted_name
except ImportError:  # pragma: no cover
    from generate_backend_map import HTTP_METHODS, ROUTE_DECORATOR_BASES, dotted_name

FILE_LIMIT_KEYS = {"path", "max_lines", "protected", "non_growth", "owner", "category"}
SYMBOL_LIMIT_KEYS = {
    "path", "max_top_level_functions", "max_top_level_classes", "max_routes",
    "protected", "non_growth", "owner", "category",
}
SOURCE_POLICY_KEYS = {"normal_max_lines", "soft_max_lines", "trend_window_packages", "trend_growth_percent", "roots", "extensions", "classifications"}
CLASSIFICATION_KEYS = {"pattern", "kind", "rationale"}
CLASSIFICATION_KINDS = {"generated", "vendor"}


@dataclass(frozen=True)
class PathClassification:
    pattern: str
    kind: str
    rationale: str

@dataclass(frozen=True)
class SourceSizePolicy:
    normal_max_lines: int
    soft_max_lines: int
    trend_window_packages: int
    trend_growth_percent: int
    roots: tuple[str, ...]
    extensions: tuple[str, ...]
    classifications: tuple[PathClassification, ...]


def normalize_repo_path(value: str, *, allow_subtree: bool = False) -> str:
    raw = str(value).strip().replace("\\", "/")
    subtree = raw.endswith("/**")
    if subtree:
        if not allow_subtree:
            raise ValueError("subtree-not-allowed")
        raw = raw[:-3].rstrip("/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("invalid-path")
    parts = PurePosixPath(raw).parts
    if any(part in {"", ".", ".."} for part in parts) or any(ch in raw for ch in "*?[]"):
        raise ValueError("invalid-path")
    normalized = "/".join(parts)
    return normalized + ("/**" if subtree else "")


def _matches(pattern: str, path: str) -> bool:
    subtree = pattern.endswith("/**")
    prefix = pattern[:-3].rstrip("/") if subtree else pattern
    return path == prefix or (subtree and path.startswith(prefix + "/"))

def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _metadata_errors(item: dict[str, Any], allowed: set[str], label: str) -> list[str]:
    errors: list[str] = []
    try:
        normalize_repo_path(str(item.get("path", "")))
    except ValueError:
        errors.append(f"{label} path is invalid")
    unknown = sorted(set(item) - allowed)
    if unknown:
        errors.append(f"{label} has unknown keys: {','.join(unknown)}")
    for key in ("protected", "non_growth"):
        if not isinstance(item.get(key), bool):
            errors.append(f"{label} field must be boolean: {key}")
    for key in ("owner", "category"):
        if not _nonempty(item.get(key)):
            errors.append(f"{label} field is missing: {key}")
    return errors


def validate_size_contract(policy: dict[str, Any], *, require_policy: bool = True, require_metadata: bool = True) -> list[str]:
    errors: list[str] = []
    for item in policy.get("file_limits", []):
        label = f"file limit {item.get('path', '<missing>')}"
        if require_metadata:
            errors.extend(_metadata_errors(item, FILE_LIMIT_KEYS, label))
        if not isinstance(item.get("max_lines"), int) or item.get("max_lines", -1) < 0:
            errors.append(f"{label} max_lines must be a non-negative integer")
    for item in policy.get("symbol_limits", []):
        label = f"symbol limit {item.get('path', '<missing>')}"
        if require_metadata:
            errors.extend(_metadata_errors(item, SYMBOL_LIMIT_KEYS, label))
        for key in ("max_top_level_functions", "max_top_level_classes", "max_routes"):
            if not isinstance(item.get(key), int) or item.get(key, -1) < 0:
                errors.append(f"{label} {key} must be a non-negative integer")
    raw = policy.get("source_size_policy")
    if raw is None:
        return errors + (["source_size_policy is missing"] if require_policy else [])
    if not isinstance(raw, dict):
        return errors + ["source_size_policy must be an object"]
    unknown = sorted(set(raw) - SOURCE_POLICY_KEYS)
    if unknown:
        errors.append("source_size_policy has unknown keys: " + ",".join(unknown))
    normal, soft = raw.get("normal_max_lines"), raw.get("soft_max_lines")
    if not isinstance(normal, int) or normal < 1:
        errors.append("source_size_policy normal_max_lines must be a positive integer")
    if not isinstance(soft, int) or not isinstance(normal, int) or soft < normal:
        errors.append("source_size_policy soft_max_lines must be >= normal_max_lines")
    for key in ("trend_window_packages", "trend_growth_percent"):
        if not isinstance(raw.get(key), int) or raw.get(key, 0) <= 0:
            errors.append(f"source_size_policy {key} must be a positive integer")
    for key in ("roots", "extensions"):
        values = raw.get(key)
        if not isinstance(values, list) or not values or not all(_nonempty(item) for item in values):
            errors.append(f"source_size_policy {key} must be a non-empty string list")
        elif len(set(values)) != len(values):
            errors.append(f"source_size_policy {key} contains duplicates")
    for root in raw.get("roots", []) if isinstance(raw.get("roots"), list) else []:
        try:
            normalize_repo_path(root)
        except ValueError:
            errors.append(f"source_size_policy invalid root: {root}")
    for extension in raw.get("extensions", []) if isinstance(raw.get("extensions"), list) else []:
        if not extension.startswith(".") or extension != extension.lower() or "/" in extension:
            errors.append(f"source_size_policy invalid extension: {extension}")
    classifications = raw.get("classifications", [])
    if not isinstance(classifications, list):
        errors.append("source_size_policy classifications must be a list")
        classifications = []
    seen_patterns: set[str] = set()
    for entry in classifications:
        if not isinstance(entry, dict):
            errors.append("source classification must be an object")
            continue
        unknown = sorted(set(entry) - CLASSIFICATION_KEYS)
        if unknown:
            errors.append("source classification has unknown keys: " + ",".join(unknown))
        try:
            pattern = normalize_repo_path(entry.get("pattern", ""), allow_subtree=True)
        except ValueError:
            errors.append(f"source classification invalid pattern: {entry.get('pattern', '')}")
            continue
        if pattern in seen_patterns:
            errors.append(f"duplicate source classification: {pattern}")
        seen_patterns.add(pattern)
        if entry.get("kind") not in CLASSIFICATION_KINDS:
            errors.append(f"source classification invalid kind: {pattern}")
        if not _nonempty(entry.get("rationale")):
            errors.append(f"source classification rationale is missing: {pattern}")
    return errors


def source_size_policy(policy: dict[str, Any]) -> SourceSizePolicy | None:
    raw = policy.get("source_size_policy")
    if not isinstance(raw, dict):
        return None
    classifications = tuple(
        PathClassification(normalize_repo_path(item["pattern"], allow_subtree=True), item["kind"], item["rationale"].strip())
        for item in raw.get("classifications", [])
    )
    return SourceSizePolicy(
        int(raw["normal_max_lines"]), int(raw["soft_max_lines"]),
        int(raw["trend_window_packages"]), int(raw["trend_growth_percent"]),
        tuple(normalize_repo_path(item) for item in raw["roots"]),
        tuple(str(item) for item in raw["extensions"]), classifications,
    )

def classification_kind(policy: dict[str, Any], path: str) -> str | None:
    parsed = source_size_policy(policy)
    if parsed is None:
        return None
    for item in parsed.classifications:
        if _matches(item.pattern, path):
            return item.kind
    return None


def is_generated_or_vendor(policy: dict[str, Any], path: str) -> bool:
    return classification_kind(policy, path) in CLASSIFICATION_KINDS


def is_handwritten_source(policy: dict[str, Any], path: str) -> bool:
    parsed = source_size_policy(policy)
    if parsed is None or is_generated_or_vendor(policy, path):
        return False
    pure = PurePosixPath(path)
    if pure.suffix.lower() not in parsed.extensions:
        return False
    return any(path == root or path.startswith(root + "/") for root in parsed.roots)


def text_line_count(text: str) -> int:
    return len(text.splitlines())


def python_symbol_counts(text: str, filename: str = "<source>") -> dict[str, int]:
    tree = ast.parse(text, filename=filename)
    functions = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in tree.body)
    classes = sum(isinstance(node, ast.ClassDef) for node in tree.body)
    routes = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            name = dotted_name(decorator.func)
            if "." not in name:
                continue
            base = name.split(".", 1)[0]
            method = name.rsplit(".", 1)[-1].lower()
            if base in ROUTE_DECORATOR_BASES and method in HTTP_METHODS:
                routes += 1
                break
    return {
        "top_level_functions": functions,
        "top_level_classes": classes,
        "routes": routes,
    }


def file_limit_map(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["path"]): item for item in policy.get("file_limits", [])}


def symbol_limit_map(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["path"]): item for item in policy.get("symbol_limits", [])}


def collect_file_limits(root: Path, policy: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in policy.get("file_limits", []):
        relative = str(item["path"])
        path = root / relative
        if not path.is_file():
            errors.append(f"file limit target missing: {relative}")
            continue
        lines = text_line_count(path.read_text(encoding="utf-8"))
        maximum = int(item["max_lines"])
        row = {"path": relative, "lines": lines, "max_lines": maximum, "remaining": maximum - lines}
        row.update({key: item[key] for key in ("protected", "non_growth", "owner", "category") if key in item})
        rows.append(row)
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
        counts = python_symbol_counts(path.read_text(encoding="utf-8"), str(path))
        row: dict[str, Any] = {"path": relative, **counts}
        row.update({key: item[key] for key in ("protected", "non_growth", "owner", "category") if key in item})
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


def _finding(code: str, *, path: str = "", detail: str = "") -> dict[str, str]:
    item = {"code": code}
    if path:
        item["path"] = path
    if detail:
        item["detail"] = detail
    return item


def _protected(item: dict[str, Any]) -> bool:
    # Pre-STAB-SIZE contracts had no metadata; existing limits bootstrap as protected.
    return bool(item.get("protected", True)) and bool(item.get("non_growth", True))


def evaluate_size_delta(
    base_policy: dict[str, Any],
    candidate_policy: dict[str, Any],
    *,
    changed_paths: set[str],
    added_paths: set[str],
    base_texts: dict[str, str],
    candidate_texts: dict[str, str],
    change_class: str,
    size_reviews: dict[str, str],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    contract_errors = validate_size_contract(candidate_policy)
    for error in contract_errors:
        findings.append(_finding("ARCHITECTURE_SIZE_CONTRACT_INVALID", detail=error))
    if contract_errors:
        return findings
    base_files = file_limit_map(base_policy)
    candidate_files = file_limit_map(candidate_policy)
    for path, base_item in base_files.items():
        if not _protected(base_item):
            continue
        candidate_item = candidate_files.get(path)
        if candidate_item is None:
            findings.append(_finding("ARCHITECTURE_SIZE_CONTRACT_INVALID", path=path, detail="protected file limit removed"))
            continue
        if not _protected(candidate_item):
            findings.append(_finding("ARCHITECTURE_SIZE_CONTRACT_INVALID", path=path, detail="protected/non-growth downgraded"))
            continue
        base_max = int(base_item["max_lines"])
        candidate_max = int(candidate_item["max_lines"])
        exception_only = change_class == "architecture-exception" and path not in changed_paths
        if candidate_max > base_max and not exception_only:
            findings.append(_finding("PROTECTED_BUDGET_INCREASE", path=path, detail=f"base={base_max} candidate={candidate_max}"))
        if path not in changed_paths or path not in base_texts or path not in candidate_texts:
            continue
        base_lines = text_line_count(base_texts[path])
        candidate_lines = text_line_count(candidate_texts[path])
        if change_class == "extraction":
            if candidate_lines >= base_lines:
                findings.append(_finding("PROTECTED_EXTRACTION_NOT_SHRINKING", path=path, detail=f"base={base_lines} candidate={candidate_lines}"))
            elif candidate_max != candidate_lines:
                findings.append(_finding("PROTECTED_BUDGET_NOT_LOWERED", path=path, detail=f"candidate_lines={candidate_lines} max={candidate_max}"))
        elif candidate_lines > base_lines:
            findings.append(_finding("PROTECTED_FILE_GROWTH", path=path, detail=f"base={base_lines} candidate={candidate_lines}"))
    base_symbols = symbol_limit_map(base_policy)
    candidate_symbols = symbol_limit_map(candidate_policy)
    dimensions = (
        ("top_level_functions", "max_top_level_functions"),
        ("top_level_classes", "max_top_level_classes"),
        ("routes", "max_routes"),
    )
    for path, base_item in base_symbols.items():
        if not _protected(base_item):
            continue
        candidate_item = candidate_symbols.get(path)
        if candidate_item is None or not _protected(candidate_item):
            findings.append(_finding("ARCHITECTURE_SIZE_CONTRACT_INVALID", path=path, detail="protected symbol limit removed/downgraded"))
            continue
        for _dimension, maximum_name in dimensions:
            base_max = int(base_item[maximum_name])
            candidate_max = int(candidate_item[maximum_name])
            exception_only = change_class == "architecture-exception" and path not in changed_paths
            if candidate_max > base_max and not exception_only:
                findings.append(_finding("PROTECTED_BUDGET_INCREASE", path=path, detail=f"{maximum_name}: base={base_max} candidate={candidate_max}"))
        if path not in changed_paths or path not in base_texts or path not in candidate_texts:
            continue
        before = python_symbol_counts(base_texts[path], path)
        after = python_symbol_counts(candidate_texts[path], path)
        for dimension, _maximum_name in dimensions:
            if after[dimension] > before[dimension]:
                findings.append(_finding("PROTECTED_SYMBOL_GROWTH", path=path, detail=f"{dimension}: base={before[dimension]} candidate={after[dimension]}"))
    base_source_policy = base_policy.get("source_size_policy")
    candidate_source_policy = candidate_policy.get("source_size_policy")
    if base_source_policy is not None and candidate_source_policy != base_source_policy and change_class != "architecture-exception":
        findings.append(_finding("ARCHITECTURE_SIZE_CONTRACT_INVALID", path="architecture/contract.json", detail="source_size_policy mutation requires architecture-exception"))
    parsed = source_size_policy(base_policy)
    if parsed is not None:
        for path in sorted(added_paths):
            if not is_handwritten_source(base_policy, path) or path not in candidate_texts:
                continue
            lines = text_line_count(candidate_texts[path])
            if lines <= parsed.normal_max_lines:
                continue
            if lines <= parsed.soft_max_lines:
                if not size_reviews.get(path, "").strip():
                    findings.append(_finding("SIZE_REVIEW_REQUIRED", path=path, detail=f"lines={lines} soft_max={parsed.soft_max_lines}"))
                continue
            findings.append(_finding("NEW_SOURCE_HARD_LIMIT_EXCEEDED", path=path, detail=f"lines={lines} max={parsed.soft_max_lines}"))
    return findings


def measurement_paths(
    base_policy: dict[str, Any], changed_paths: set[str], added_paths: set[str]
) -> tuple[set[str], set[str]]:
    protected = {
        path for path, item in file_limit_map(base_policy).items()
        if _protected(item) and path in changed_paths
    }
    protected.update(
        path for path, item in symbol_limit_map(base_policy).items()
        if _protected(item) and path in changed_paths
    )
    candidate = set(protected)
    if source_size_policy(base_policy) is not None:
        candidate.update(path for path in added_paths if is_handwritten_source(base_policy, path))
    return protected, candidate
