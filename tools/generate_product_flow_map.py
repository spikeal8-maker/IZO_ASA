"""Validate the canonical critical product-flow contract and generate deterministic maps."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
FLOW_KEYS = {
    "id",
    "ownerDomain",
    "capabilityState",
    "userSurface",
    "authState",
    "frontendPaths",
    "apiEndpoints",
    "sourcePaths",
    "durableResults",
    "sideEffects",
    "expectedFailures",
    "automatedEvidence",
    "coverageGap",
    "relatedContextDomains",
    "unknownEdges",
}
CAPABILITY_STATES = {"implemented", "partial", "contract-only", "disabled", "unknown"}
SIDE_EFFECT_STATES = {"none", "known", "unknown"}
SIDE_EFFECT_KEYS = {"billing", "tokens", "data", "media"}
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
FLOW_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:")


class ProductFlowSchemaError(RuntimeError):
    pass


def _error(message: str) -> ProductFlowSchemaError:
    return ProductFlowSchemaError(message)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise _error(f"missing file: {path.as_posix()}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _error(f"invalid JSON/UTF-8: {path.as_posix()}") from exc


def _context_domains(root: Path) -> set[str]:
    payload = _load_json(root / "docs" / "generated" / "context-index.json")
    if not isinstance(payload, dict) or not isinstance(payload.get("cards"), list):
        raise _error("context index must contain cards")
    domains = {
        card.get("domain")
        for card in payload["cards"]
        if isinstance(card, dict) and isinstance(card.get("domain"), str)
    }
    if not domains or None in domains:
        raise _error("context index contains invalid domains")
    return domains


def _backend_routes(root: Path) -> set[tuple[str, str]]:
    payload = _load_json(
        root / "docs" / "generated" / "architecture-inventory.json"
    )
    if not isinstance(payload, dict):
        raise _error("architecture inventory root must be an object")
    routes = payload.get("routes")
    if not isinstance(routes, dict):
        raise _error("architecture inventory routes must be an object")
    items = routes.get("items")
    if not isinstance(items, list):
        raise _error("architecture inventory routes.items must be a list")

    result: set[tuple[str, str]] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise _error(
                f"architecture inventory routes.items[{index}] must be an object"
            )
        if "method" not in item:
            raise _error(
                f"architecture inventory routes.items[{index}] is missing method"
            )
        if "path" not in item:
            raise _error(
                f"architecture inventory routes.items[{index}] is missing path"
            )
        method = item["method"]
        route_path = item["path"]
        if not isinstance(method, str) or not method:
            raise _error(
                f"architecture inventory routes.items[{index}].method must be a non-empty string"
            )
        if not isinstance(route_path, str):
            raise _error(
                f"architecture inventory routes.items[{index}].path must be a string"
            )
        result.add((method, route_path))
    return result


def _repo_path(root: Path, value: Any, *, field: str, allow_unknown: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{field} must contain non-empty repository paths")
    value = value.strip()
    if allow_unknown and value == "unknown":
        return value
    if value == "unknown":
        raise _error(f"{field} does not allow unknown")
    if "\\" in value or value.startswith("/") or WINDOWS_ABSOLUTE_RE.match(value):
        raise _error(f"{field} contains invalid repository path: {value}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise _error(f"{field} contains invalid repository path: {value}")
    candidate = root.joinpath(*parts)
    if not candidate.exists():
        raise _error(f"{field} path does not exist: {value}")
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise _error(f"{field} path escapes repository root: {value}")
    return "/".join(parts)


def _string_list(
    value: Any,
    *,
    field: str,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise _error(f"{field} must be a string array")
    normalized = [item.strip() for item in value]
    if not allow_empty and not normalized:
        raise _error(f"{field} must not be empty")
    if len(normalized) != len(set(normalized)):
        raise _error(f"{field} contains duplicate values")
    return sorted(normalized)


def _repo_path_list(
    root: Path,
    value: Any,
    *,
    field: str,
    allow_unknown: bool = False,
    allow_empty: bool = False,
) -> list[str]:
    values = _string_list(value, field=field, allow_empty=allow_empty)
    if allow_unknown and "unknown" in values and values != ["unknown"]:
        raise _error(f"{field} cannot mix unknown with concrete paths")
    return sorted(
        _repo_path(root, item, field=field, allow_unknown=allow_unknown)
        for item in values
    )


def _normalize_endpoint(value: Any, *, flow_id: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"method", "path"}:
        raise _error(f"{flow_id}.apiEndpoints entries require only method/path")
    method = value.get("method")
    endpoint_path = value.get("path")
    if method not in HTTP_METHODS:
        raise _error(f"{flow_id}.apiEndpoints has invalid HTTP method: {method}")
    if (
        not isinstance(endpoint_path, str)
        or not endpoint_path.startswith("/")
        or any(ch.isspace() for ch in endpoint_path)
    ):
        raise _error(f"{flow_id}.apiEndpoints has invalid path: {endpoint_path!r}")
    return {"method": method, "path": endpoint_path}


def _normalize_flow(
    root: Path,
    raw: Any,
    domains: set[str],
    backend_routes: set[tuple[str, str]],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _error("each flow must be an object")
    unknown = sorted(set(raw) - FLOW_KEYS)
    missing = sorted(FLOW_KEYS - set(raw))
    if unknown:
        raise _error(f"unknown flow keys: {', '.join(unknown)}")
    if missing:
        raise _error(f"missing flow keys: {', '.join(missing)}")

    flow_id = raw["id"]
    if not isinstance(flow_id, str) or not FLOW_ID_RE.fullmatch(flow_id):
        raise _error(f"invalid flow id: {flow_id!r}")

    owner = raw["ownerDomain"]
    if owner not in domains:
        raise _error(f"{flow_id}.ownerDomain is not a canonical context domain: {owner}")

    capability = raw["capabilityState"]
    if capability not in CAPABILITY_STATES:
        raise _error(f"{flow_id}.capabilityState is invalid: {capability}")

    surface = raw["userSurface"]
    if not isinstance(surface, dict) or set(surface) != {"kind", "entryRoute"}:
        raise _error(f"{flow_id}.userSurface requires only kind/entryRoute")
    kind = surface.get("kind")
    entry_route = surface.get("entryRoute")
    if not isinstance(kind, str) or not kind.strip():
        raise _error(f"{flow_id}.userSurface.kind must be non-empty")
    if not isinstance(entry_route, str) or not entry_route.strip():
        raise _error(f"{flow_id}.userSurface.entryRoute must be non-empty")
    entry_route = entry_route.strip()
    if entry_route != "unknown" and not entry_route.startswith("/"):
        raise _error(f"{flow_id}.userSurface.entryRoute must be a route or unknown")

    auth_state = raw["authState"]
    if not isinstance(auth_state, str) or not auth_state.strip():
        raise _error(f"{flow_id}.authState must be non-empty")

    frontend_paths = _repo_path_list(
        root,
        raw["frontendPaths"],
        field=f"{flow_id}.frontendPaths",
        allow_unknown=True,
    )
    source_paths = _repo_path_list(
        root,
        raw["sourcePaths"],
        field=f"{flow_id}.sourcePaths",
    )
    evidence = _repo_path_list(
        root,
        raw["automatedEvidence"],
        field=f"{flow_id}.automatedEvidence",
        allow_empty=True,
    )

    endpoints_raw = raw["apiEndpoints"]
    if not isinstance(endpoints_raw, list) or not endpoints_raw:
        raise _error(f"{flow_id}.apiEndpoints must be a non-empty array")
    endpoints = [_normalize_endpoint(item, flow_id=flow_id) for item in endpoints_raw]
    endpoint_keys = [(item["method"], item["path"]) for item in endpoints]
    if len(endpoint_keys) != len(set(endpoint_keys)):
        raise _error(f"{flow_id}.apiEndpoints contains duplicates")
    for method, endpoint_path in endpoint_keys:
        if (method, endpoint_path) not in backend_routes:
            raise _error(
                f"{flow_id}.apiEndpoints references unknown backend route: "
                f"{method} {endpoint_path}"
            )
    endpoints = sorted(endpoints, key=lambda item: (item["path"], item["method"]))

    durable = _string_list(
        raw["durableResults"],
        field=f"{flow_id}.durableResults",
        allow_empty=True,
    )
    failures = _string_list(
        raw["expectedFailures"],
        field=f"{flow_id}.expectedFailures",
    )
    related = _string_list(
        raw["relatedContextDomains"],
        field=f"{flow_id}.relatedContextDomains",
        allow_empty=True,
    )
    unknown_edges = _string_list(
        raw["unknownEdges"],
        field=f"{flow_id}.unknownEdges",
        allow_empty=True,
    )
    for related_domain in related:
        if related_domain not in domains:
            raise _error(
                f"{flow_id}.relatedContextDomains contains unknown domain: "
                f"{related_domain}"
            )

    side_effects = raw["sideEffects"]
    if not isinstance(side_effects, dict) or set(side_effects) != SIDE_EFFECT_KEYS:
        raise _error(
            f"{flow_id}.sideEffects must contain exactly: "
            + ", ".join(sorted(SIDE_EFFECT_KEYS))
        )
    for key, value in side_effects.items():
        if value not in SIDE_EFFECT_STATES:
            raise _error(f"{flow_id}.sideEffects.{key} is invalid: {value}")

    coverage_gap = raw["coverageGap"]
    if coverage_gap is not None and (
        not isinstance(coverage_gap, str) or not coverage_gap.strip()
    ):
        raise _error(f"{flow_id}.coverageGap must be null or a non-empty string")
    if not evidence and coverage_gap is None:
        raise _error(
            f"{flow_id} requires automatedEvidence or an explicit coverageGap"
        )

    return {
        "id": flow_id,
        "ownerDomain": owner,
        "capabilityState": capability,
        "userSurface": {"kind": kind.strip(), "entryRoute": entry_route},
        "authState": auth_state.strip(),
        "frontendPaths": frontend_paths,
        "apiEndpoints": endpoints,
        "sourcePaths": source_paths,
        "durableResults": durable,
        "sideEffects": {
            key: side_effects[key] for key in sorted(SIDE_EFFECT_KEYS)
        },
        "expectedFailures": failures,
        "automatedEvidence": evidence,
        "coverageGap": (
            coverage_gap.strip() if isinstance(coverage_gap, str) else None
        ),
        "relatedContextDomains": related,
        "unknownEdges": unknown_edges,
    }


def build_map(
    root: Path,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    path = contract_path or root / "architecture" / "product-flows.json"
    if not path.is_absolute():
        path = root / path
    payload = _load_json(path)
    if not isinstance(payload, dict) or set(payload) != {"version", "flows"}:
        raise _error("root schema requires exactly version and flows")
    if payload["version"] != SCHEMA_VERSION:
        raise _error(f"version must be {SCHEMA_VERSION}")
    if not isinstance(payload["flows"], list):
        raise _error("flows must be an array")

    domains = _context_domains(root)
    backend_routes = _backend_routes(root)
    normalized = [
        _normalize_flow(root, flow, domains, backend_routes)
        for flow in payload["flows"]
    ]
    ids = [flow["id"] for flow in normalized]
    if len(ids) != len(set(ids)):
        raise _error("duplicate flow id")
    if ids != sorted(ids):
        raise _error("canonical flows must be sorted by id")

    return {
        "version": SCHEMA_VERSION,
        "flowCount": len(normalized),
        "flows": normalized,
    }


def render_json(product_map: dict[str, Any]) -> str:
    return json.dumps(
        product_map,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_markdown(product_map: dict[str, Any]) -> str:
    lines = [
        "# Generated critical product-flow map",
        "",
        "Generated by python tools/generate_product_flow_map.py. Do not edit manually.",
        "",
        f"Schema version: {product_map['version']}",
        f"Flow count: {product_map['flowCount']}",
        "",
    ]
    for flow in product_map["flows"]:
        surface = flow["userSurface"]
        api = ", ".join(
            f"{item['method']} {item['path']}"
            for item in flow["apiEndpoints"]
        )
        durable = ", ".join(flow["durableResults"]) or "none"
        evidence = ", ".join(flow["automatedEvidence"]) or "none"
        gap = flow["coverageGap"] or "none"
        unknown = "; ".join(flow["unknownEdges"]) or "none"
        effects = ", ".join(
            f"{key}={value}"
            for key, value in sorted(flow["sideEffects"].items())
        )
        lines.extend(
            [
                f"## {flow['id']}",
                "",
                f"- owner: {flow['ownerDomain']}",
                f"- capability: {flow['capabilityState']}",
                f"- entry: {_md(surface['kind'])} / {_md(surface['entryRoute'])}",
                f"- auth: {_md(flow['authState'])}",
                f"- API: {_md(api)}",
                f"- durable result: {_md(durable)}",
                f"- side effects: {_md(effects)}",
                f"- tests: {_md(evidence)}",
                f"- coverage gap: {_md(gap)}",
                f"- unknown edges: {_md(unknown)}",
                "",
            ]
        )
    return "\n".join(lines)


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("architecture/product-flows.json"),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=Path("docs/generated/product-flow-map.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("docs/generated/product-flow-map.md"),
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()

    try:
        product_map = build_map(root, _resolve(root, args.contract))
    except ProductFlowSchemaError as exc:
        print(f"product flow schema error: {exc}")
        return 2

    artifacts = {
        _resolve(root, args.json_output): render_json(product_map),
        _resolve(root, args.markdown_output): render_markdown(product_map),
    }
    if args.check:
        outdated = [
            path.relative_to(root).as_posix()
            for path, expected in artifacts.items()
            if not path.is_file()
            or path.read_text(encoding="utf-8") != expected
        ]
        if outdated:
            for stale in outdated:
                print(f"outdated: {stale}")
            return 1
        print("ok: product flow map")
        return 0

    for output, expected in artifacts.items():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(expected, encoding="utf-8", newline="\n")
        print(f"wrote {output.relative_to(root).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
