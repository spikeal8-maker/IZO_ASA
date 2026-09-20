from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from tools.generate_product_flow_map import (
    ProductFlowSchemaError,
    build_map,
    render_json,
    render_markdown,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "generate_product_flow_map.py"
CONTRACT = ROOT / "architecture" / "product-flows.json"
EXPECTED_FLOW_IDS = [
    "auth-session-lifecycle",
    "gallery-result-lifecycle",
    "generation-job-lifecycle",
    "image-edit-generation",
    "max-trusted-entry",
    "publish-feed-visibility",
    "telegram-trusted-entry",
    "text-to-image-generation",
]


def _sample_flow() -> dict:
    return {
        "id": "alpha-flow",
        "ownerDomain": "alpha",
        "capabilityState": "implemented",
        "userSurface": {"kind": "web", "entryRoute": "/alpha"},
        "authState": "trusted session required",
        "frontendPaths": ["frontend/alpha.ts"],
        "apiEndpoints": [{"method": "POST", "path": "/api/alpha"}],
        "sourcePaths": ["backend/alpha.py"],
        "durableResults": ["alpha row"],
        "sideEffects": {
            "billing": "none",
            "tokens": "none",
            "data": "known",
            "media": "none",
        },
        "expectedFailures": ["invalid alpha request"],
        "automatedEvidence": ["tests/test_alpha.py"],
        "coverageGap": None,
        "relatedContextDomains": ["beta"],
        "unknownEdges": [],
    }


def _make_root(tmp_path: Path, *, flows: list[dict] | None = None) -> Path:
    root = tmp_path
    (root / "architecture").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "generated").mkdir(parents=True, exist_ok=True)
    (root / "frontend").mkdir(exist_ok=True)
    (root / "backend").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)

    (root / "frontend" / "alpha.ts").write_text("export {}\n", encoding="utf-8")
    (root / "backend" / "alpha.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_alpha.py").write_text("def test_alpha(): pass\n", encoding="utf-8")
    (root / "docs" / "generated" / "context-index.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "cardCount": 2,
                "cards": [
                    {"domain": "alpha"},
                    {"domain": "beta"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "docs" / "generated" / "architecture-inventory.json").write_text(
        json.dumps(
            {
                "routes": {
                    "items": [
                        {"method": "POST", "path": "/api/alpha"},
                    ]
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "architecture" / "product-flows.json").write_text(
        json.dumps({"version": 1, "flows": flows or [_sample_flow()]}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return root


def _write_contract(root: Path, payload: dict) -> None:
    (root / "architecture" / "product-flows.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_inventory(root: Path, payload: object) -> None:
    (root / "docs" / "generated" / "architecture-inventory.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def test_repository_product_flow_contract_and_generated_maps_are_current() -> None:
    first = build_map(ROOT)
    second = build_map(ROOT)
    assert first == second
    assert first["version"] == 1
    assert first["flowCount"] == 8
    assert [flow["id"] for flow in first["flows"]] == EXPECTED_FLOW_IDS

    by_id = {flow["id"]: flow for flow in first["flows"]}
    assert by_id["auth-session-lifecycle"]["ownerDomain"] == "backend-auth-bots"
    assert by_id["telegram-trusted-entry"]["ownerDomain"] == "backend-auth-bots"
    assert by_id["max-trusted-entry"]["ownerDomain"] == "backend-auth-bots"
    assert by_id["text-to-image-generation"]["ownerDomain"] == "image-generation"
    assert by_id["text-to-image-generation"]["userSurface"]["entryRoute"] == "/phone/image"

    assert by_id["gallery-result-lifecycle"]["ownerDomain"] == "video-gallery-feed"
    assert by_id["generation-job-lifecycle"]["ownerDomain"] == "image-generation"
    assert by_id["image-edit-generation"]["ownerDomain"] == "image-generation"
    assert by_id["publish-feed-visibility"]["ownerDomain"] == "video-gallery-feed"

    generation_job_api = {
        (item["method"], item["path"])
        for item in by_id["generation-job-lifecycle"]["apiEndpoints"]
    }
    assert ("POST", "/api/jobs/{job_id}/cancel") in generation_job_api

    gallery_api = {
        (item["method"], item["path"])
        for item in by_id["gallery-result-lifecycle"]["apiEndpoints"]
    }
    assert ("POST", "/api/gallery/{image_id}/use-as") in gallery_api
    assert ("DELETE", "/api/gallery/{image_id}") in gallery_api

    publish_api = {
        (item["method"], item["path"])
        for item in by_id["publish-feed-visibility"]["apiEndpoints"]
    }
    assert ("POST", "/api/feed/publications") in publish_api
    assert ("GET", "/api/feed") in publish_api

    assert not any("3d" in flow_id for flow_id in by_id)

    json_path = ROOT / "docs" / "generated" / "product-flow-map.json"
    md_path = ROOT / "docs" / "generated" / "product-flow-map.md"
    assert json_path.read_text(encoding="utf-8") == render_json(first)
    assert md_path.read_text(encoding="utf-8") == render_markdown(first)

    checked = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "ok: product flow map" in checked.stdout


def test_contract_rejects_root_and_flow_schema_drift(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    payload = {"version": 1, "flows": [_sample_flow()], "unexpected": True}
    _write_contract(root, payload)
    with pytest.raises(ProductFlowSchemaError, match="root schema"):
        build_map(root)

    root = _make_root(tmp_path, flows=[_sample_flow()])
    payload = {"version": 1, "flows": [_sample_flow()]}
    payload["flows"][0]["surprise"] = True
    _write_contract(root, payload)
    with pytest.raises(ProductFlowSchemaError, match="unknown flow keys"):
        build_map(root)

    payload = {"version": 1, "flows": [_sample_flow()]}
    del payload["flows"][0]["authState"]
    _write_contract(root, payload)
    with pytest.raises(ProductFlowSchemaError, match="missing flow keys"):
        build_map(root)


def test_contract_rejects_duplicate_invalid_or_unsorted_ids(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    duplicate = [_sample_flow(), deepcopy(_sample_flow())]
    _write_contract(root, {"version": 1, "flows": duplicate})
    with pytest.raises(ProductFlowSchemaError, match="duplicate flow id"):
        build_map(root)

    invalid = _sample_flow()
    invalid["id"] = "Bad_ID"
    _write_contract(root, {"version": 1, "flows": [invalid]})
    with pytest.raises(ProductFlowSchemaError, match="invalid flow id"):
        build_map(root)

    alpha = _sample_flow()
    beta = deepcopy(alpha)
    beta["id"] = "beta-flow"
    _write_contract(root, {"version": 1, "flows": [beta, alpha]})
    with pytest.raises(ProductFlowSchemaError, match="sorted by id"):
        build_map(root)


def test_contract_requires_canonical_domains_and_capability_state(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    flow = _sample_flow()
    flow["ownerDomain"] = "missing-domain"
    _write_contract(root, {"version": 1, "flows": [flow]})
    with pytest.raises(ProductFlowSchemaError, match="ownerDomain"):
        build_map(root)

    flow = _sample_flow()
    flow["relatedContextDomains"] = ["missing-domain"]
    _write_contract(root, {"version": 1, "flows": [flow]})
    with pytest.raises(ProductFlowSchemaError, match="relatedContextDomains"):
        build_map(root)

    flow = _sample_flow()
    flow["capabilityState"] = "production-ready"
    _write_contract(root, {"version": 1, "flows": [flow]})
    with pytest.raises(ProductFlowSchemaError, match="capabilityState"):
        build_map(root)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sourcePaths", ["backend/missing.py"], "sourcePaths path does not exist"),
        ("frontendPaths", ["frontend/missing.ts"], "frontendPaths path does not exist"),
        ("automatedEvidence", ["tests/missing.py"], "automatedEvidence path does not exist"),
    ],
)
def test_contract_rejects_missing_declared_paths(
    tmp_path: Path,
    field: str,
    value: list[str],
    message: str,
) -> None:
    root = _make_root(tmp_path)
    flow = _sample_flow()
    flow[field] = value
    _write_contract(root, {"version": 1, "flows": [flow]})
    with pytest.raises(ProductFlowSchemaError, match=message):
        build_map(root)


def test_unknown_frontend_path_is_explicit_and_cannot_mix_with_real_path(
    tmp_path: Path,
) -> None:
    root = _make_root(tmp_path)
    flow = _sample_flow()
    flow["frontendPaths"] = ["unknown"]
    _write_contract(root, {"version": 1, "flows": [flow]})
    assert build_map(root)["flows"][0]["frontendPaths"] == ["unknown"]

    flow["frontendPaths"] = ["unknown", "frontend/alpha.ts"]
    _write_contract(root, {"version": 1, "flows": [flow]})
    with pytest.raises(ProductFlowSchemaError, match="cannot mix unknown"):
        build_map(root)


def test_contract_rejects_invalid_endpoint_method(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    flow = _sample_flow()
    flow["apiEndpoints"] = [{"method": "TRACE", "path": "/api/alpha"}]
    _write_contract(root, {"version": 1, "flows": [flow]})
    with pytest.raises(ProductFlowSchemaError, match="invalid HTTP method"):
        build_map(root)


def test_existing_backend_endpoint_passes_exact_inventory_match(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    result = build_map(root)
    assert result["flows"][0]["apiEndpoints"] == [
        {"method": "POST", "path": "/api/alpha"}
    ]


def test_missing_backend_endpoint_fails_exact_inventory_match(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    flow = _sample_flow()
    flow["apiEndpoints"] = [{"method": "POST", "path": "/api/not-real"}]
    _write_contract(root, {"version": 1, "flows": [flow]})
    with pytest.raises(
        ProductFlowSchemaError,
        match=r"alpha-flow\.apiEndpoints references unknown backend route: POST /api/not-real",
    ):
        build_map(root)


def test_wrong_http_method_for_existing_backend_path_fails(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    flow = _sample_flow()
    flow["apiEndpoints"] = [{"method": "GET", "path": "/api/alpha"}]
    _write_contract(root, {"version": 1, "flows": [flow]})
    with pytest.raises(
        ProductFlowSchemaError,
        match=r"alpha-flow\.apiEndpoints references unknown backend route: GET /api/alpha",
    ):
        build_map(root)


@pytest.mark.parametrize(
    "inventory",
    [
        [],
        {},
        {"routes": {}},
        {"routes": {"items": "not-a-list"}},
        {"routes": {"items": [None]}},
        {"routes": {"items": [{"path": "/api/alpha"}]}},
        {"routes": {"items": [{"method": "POST"}]}},
    ],
)
def test_malformed_architecture_inventory_fails(
    tmp_path: Path,
    inventory: object,
) -> None:
    root = _make_root(tmp_path)
    _write_inventory(root, inventory)
    with pytest.raises(ProductFlowSchemaError, match="architecture inventory"):
        build_map(root)


def test_frontend_entry_route_is_not_validated_against_frontend_map(
    tmp_path: Path,
) -> None:
    root = _make_root(tmp_path)
    flow = _sample_flow()
    flow["userSurface"]["entryRoute"] = "/phone/image"
    _write_contract(root, {"version": 1, "flows": [flow]})
    assert build_map(root)["flows"][0]["userSurface"]["entryRoute"] == "/phone/image"


def test_contract_requires_automated_evidence_or_explicit_gap(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    flow = _sample_flow()
    flow["automatedEvidence"] = []
    flow["coverageGap"] = None
    _write_contract(root, {"version": 1, "flows": [flow]})
    with pytest.raises(ProductFlowSchemaError, match="automatedEvidence"):
        build_map(root)

    flow["coverageGap"] = "No automated end-to-end coverage yet."
    _write_contract(root, {"version": 1, "flows": [flow]})
    result = build_map(root)
    assert result["flows"][0]["automatedEvidence"] == []
    assert result["flows"][0]["coverageGap"]


def test_generated_outputs_are_deterministic_and_check_detects_drift(
    tmp_path: Path,
) -> None:
    root = _make_root(tmp_path)
    outputs = [
        "--json-output",
        "docs/generated/product-flow-map.json",
        "--markdown-output",
        "docs/generated/product-flow-map.md",
    ]
    generated = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *outputs],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr

    first_json = (root / "docs/generated/product-flow-map.json").read_bytes()
    first_md = (root / "docs/generated/product-flow-map.md").read_bytes()
    generated_again = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *outputs],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert generated_again.returncode == 0
    assert (root / "docs/generated/product-flow-map.json").read_bytes() == first_json
    assert (root / "docs/generated/product-flow-map.md").read_bytes() == first_md

    checked = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *outputs, "--check"],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert checked.returncode == 0

    json_path = root / "docs/generated/product-flow-map.json"
    json_path.write_text(json_path.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    stale = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *outputs, "--check"],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert stale.returncode == 1
    assert "outdated: docs/generated/product-flow-map.json" in stale.stdout


def test_generator_has_no_broad_repository_scan() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert ".rglob(" not in source
    assert "os.walk" not in source
    assert "glob(" not in source


def test_verify_wires_product_flow_check_and_focused_tests() -> None:
    verify = (ROOT / "tools" / "verify.ps1").read_text(encoding="utf-8")
    assert 'generate_product_flow_map.py' in verify
    assert 'VERIFY_PLAN_STEP product_flow_map_check' in verify
    assert 'Invoke-NativeStep -Name "product_flow_map_check"' in verify
    assert '"tools/test_product_flows.py"' in verify
