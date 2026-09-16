from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.generate_architecture_inventory import (
    LegacyAuthUse,
    TaskCall,
    build_inventory,
    collect_environment_inventory,
    collect_file_limits,
    collect_frontend_api_literals,
    collect_legacy_auth_uses,
    collect_symbol_limits,
    collect_task_calls,
    render_json,
    render_markdown,
    validate_legacy_auth_uses,
    validate_policy_semantics,
    validate_registered_tasks,
    validate_reviewed_routes,
)
from tools.generate_backend_map import Route
from tools.architecture_size_contract import evaluate_size_delta, validate_size_contract


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "architecture" / "contract.json"
SCRIPT = ROOT / "tools" / "generate_architecture_inventory.py"


def _policy() -> dict[str, object]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_repository_inventory_is_valid_deterministic_and_semantically_complete() -> None:
    policy = _policy()

    first, first_errors = build_inventory(ROOT, policy)
    second, second_errors = build_inventory(ROOT, policy)

    assert first_errors == []
    assert second_errors == []
    assert first == second
    assert first["source_size_policy"]["trend_window_packages"] == 3
    assert first["source_size_policy"]["trend_growth_percent"] == 15
    assert first["size_trend_evidence"]["status"] == "unknown"
    assert render_json(first) == render_json(second)
    assert render_json(first).count("\n") == 1
    assert render_markdown(first) == render_markdown(second)
    assert first["validation"] == {"status": "ok", "error_count": 0}
    assert first["routes"]["count"] >= 200
    assert first["routes"]["default_process_role"] == "all-dev-current-monolith"
    assert {item["process_role"] for item in first["routes"]["items"]} == {
        "all-dev-current-monolith"
    }
    assert first["tasks"]["worker_count"] == 8
    assert first["tasks"]["ephemeral_count"] == 4
    assert {item["id"] for item in first["tasks"]["items"]} == {
        "generation-consumer",
        "bot-polling",
        "feed-video-publication",
        "avatar-cache",
        "openrouter-catalog-refresh",
        "admin-notification-delivery",
        "social-telegram-delivery",
        "unverified-account-retention",
        "power-telemetry",
        "ollama-residency",
        "gallery-storage-optimization",
        "runtime-alert",
    }
    table_names = {item["name"] for item in first["schema"]["tables"]}
    assert {"users", "auth_sessions", "payments", "token_ledger", "images", "feed_publications", "phone_chat_threads", "phone_chat_messages"} <= table_names
    assert len(first["schema"]["foreign_key_declarations"]) == 2
    assert first["schema"]["foreign_key_declarations"][0]["source"] == (
        "backend/app/database/migrations.py"
    )
    listener_ports = {item["id"]: item["port"] for item in first["listeners"]}
    assert listener_ports == {
        "frontend-edge": 5173,
        "api": 8000,
        "qwen-asr": 8001,
        "comfyui": 8188,
        "ollama": 11434,
    }
    assert first["runtime_guards"]["allowed_full_app_listener_ids"] == ["api"]
    assert first["release_contract"]["python_version"] == "3.11.9"
    assert first["release_contract"]["node_version"] == "24.14.1"
    assert first["release_contract"]["edge_server"] == {
        "name": "caddy",
        "version": "2.11.4",
        "runtime_spec": "ops/caddy/runtime.json",
        "config": "ops/caddy/Caddyfile",
    }
    assert all("value" not in item for item in first["environment"])


def test_generated_repository_artifacts_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok: architecture inventory" in result.stdout


def test_unregistered_task_is_rejected_and_exact_registration_is_accepted(tmp_path: Path) -> None:
    source = tmp_path / "backend" / "app" / "sample.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import asyncio\n\nasync def worker():\n    return None\n\nasync def startup():\n    asyncio.create_task(worker())\n",
        encoding="utf-8",
    )

    calls = collect_task_calls(tmp_path, [source])

    assert calls == [TaskCall("backend/app/sample.py", "startup", "worker", 7)]
    assert validate_registered_tasks(calls, {}) == [
        "unregistered create_task target: backend/app/sample.py::worker"
    ]
    assert validate_registered_tasks(
        calls,
        {"task_registrations": [{"call_source": "backend/app/sample.py", "target": "worker"}]},
    ) == []


def test_legacy_identity_consumer_requires_an_exact_allowlist_entry(tmp_path: Path) -> None:
    source = tmp_path / "backend" / "main.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def request_user_id(request):\n    return request.headers.get('X-OneNode-User') or request.cookies.get('onenode_user')\n",
        encoding="utf-8",
    )

    uses = collect_legacy_auth_uses(tmp_path, [source])

    assert uses == [
        LegacyAuthUse("backend/main.py", "request_user_id", "cookie_read", "onenode_user", 2),
        LegacyAuthUse("backend/main.py", "request_user_id", "header_read", "x-onenode-user", 2),
    ]
    errors = validate_legacy_auth_uses(uses, {})
    assert errors == [
        "unregistered legacy auth consumer: backend/main.py::request_user_id::cookie_read::onenode_user",
        "unregistered legacy auth consumer: backend/main.py::request_user_id::header_read::x-onenode-user",
    ]
    allowlist = {
        "legacy_auth_consumers": [
            {
                "source": use.source,
                "symbol": use.symbol,
                "operation": use.operation,
                "input": use.input,
            }
            for use in uses
        ]
    }
    assert validate_legacy_auth_uses(uses, allowlist) == []


def test_review_route_requires_an_exact_reviewed_exception() -> None:
    route = Route("GET", "/api/admin/sample", "sample", 10, "REVIEW: admin route without detected gate")

    assert validate_reviewed_routes([route], {}) == [
        "unreviewed protected/operational route: GET /api/admin/sample (sample)"
    ]
    assert validate_reviewed_routes(
        [route],
        {"reviewed_routes": [{"method": "GET", "path": "/api/admin/sample", "handler": "sample"}]},
    ) == []


def test_file_and_symbol_budgets_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "class App:\n    def get(self, path):\n        return lambda function: function\n\napp = App()\n\n@app.get('/api/sample')\ndef sample():\n    return {}\n",
        encoding="utf-8",
    )

    _, file_errors = collect_file_limits(
        tmp_path,
        {"file_limits": [{"path": "sample.py", "max_lines": 2}]},
    )
    symbol_rows, symbol_errors = collect_symbol_limits(
        tmp_path,
        {
            "symbol_limits": [
                {
                    "path": "sample.py",
                    "max_top_level_functions": 0,
                    "max_top_level_classes": 0,
                    "max_routes": 0,
                }
            ]
        },
    )

    assert file_errors == ["file line budget exceeded: sample.py has 9, maximum 2"]
    assert symbol_rows[0]["top_level_functions"] == 1
    assert symbol_rows[0]["top_level_classes"] == 1
    assert symbol_rows[0]["routes"] == 1
    assert len(symbol_errors) == 3


def test_environment_inventory_records_names_but_never_default_secret_values(tmp_path: Path) -> None:
    source = tmp_path / "backend" / "app" / "sample.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import os\nTOKEN = os.getenv('SAMPLE_API_TOKEN', 'do-not-copy-this-value')\n",
        encoding="utf-8",
    )

    inventory = collect_environment_inventory(tmp_path, [source])
    rendered = json.dumps(inventory, ensure_ascii=False)

    assert inventory == [
        {"name": "SAMPLE_API_TOKEN", "secret": True, "sources": ["backend/app/sample.py"]}
    ]
    assert "do-not-copy-this-value" not in rendered


def test_frontend_template_api_callers_are_normalized_without_expression_noise(tmp_path: Path) -> None:
    source = tmp_path / "frontend" / "src" / "api.ts"
    source.parent.mkdir(parents=True)
    source.write_text(
        "fetch(`/api/gallery/${encodeURIComponent(imageId)}`)\nfetch('/api/version')\n",
        encoding="utf-8",
    )

    assert collect_frontend_api_literals(tmp_path) == [
        {"path": "/api/gallery/{dynamic}", "sources": ["frontend/src/api.ts"]},
        {"path": "/api/version", "sources": ["frontend/src/api.ts"]},
    ]


def test_semantic_contract_rejects_duplicate_or_unexplained_allowlist_entries() -> None:
    reviewed = {"method": "GET", "path": "/api/admin/sample", "handler": "sample"}
    legacy = {
        "source": "backend/main.py",
        "symbol": "request_user_id",
        "operation": "header_read",
        "input": "x-onenode-user",
    }
    task = {
        "id": "worker",
        "call_source": "backend/main.py",
        "target": "worker",
        "kind": "unknown",
    }

    errors = validate_policy_semantics(
        {
            "default_route_process_role": "",
            "reviewed_routes": [reviewed, reviewed],
            "legacy_auth_consumers": [legacy, legacy],
            "task_registrations": [task, task],
            "integrations": [
                {"id": "provider", "secret_source": ""},
                {"id": "provider", "secret_source": ""},
            ],
            "frontend_entrypoints": ["frontend/src/main.tsx", "frontend/src/main.tsx"],
            "file_limits": [{"path": "backend/main.py"}, {"path": "backend/main.py"}],
            "symbol_limits": [{"path": "backend/main.py"}, {"path": "backend/main.py"}],
        }
    )

    assert "default route process role is missing" in errors
    assert "duplicate reviewed route registration: GET::/api/admin/sample::sample" in errors
    assert "reviewed route rationale is missing: GET::/api/admin/sample::sample" in errors
    assert "duplicate legacy auth registration: backend/main.py::request_user_id::header_read::x-onenode-user" in errors
    assert "duplicate task registration id: worker" in errors
    assert "invalid task kind: worker::unknown" in errors
    assert "task registration field is missing: worker::owner" in errors
    assert "duplicate integration id: provider" in errors
    assert "integration secret source is missing: provider" in errors
    assert "duplicate frontend entrypoint: frontend/src/main.tsx" in errors
    assert "duplicate file limit: backend/main.py" in errors
    assert "duplicate symbol limit: backend/main.py" in errors


def _size_policy() -> dict[str, object]:
    return {
        "file_limits": [{"path": "src/hot.py", "max_lines": 10, "protected": True, "non_growth": True, "owner": "test", "category": "hotspot"}],
        "symbol_limits": [],
        "source_size_policy": {
            "normal_max_lines": 500, "soft_max_lines": 750,
            "trend_window_packages": 3, "trend_growth_percent": 15,
            "roots": ["src"], "extensions": [".py"], "classifications": [],
        },
    }


def _lines(count: int) -> str:
    return "x\n" * count


def test_size_contract_rejects_unknown_metadata_and_preserves_reviewed_fields() -> None:
    policy = _size_policy()
    assert validate_size_contract(policy) == []
    bad = json.loads(json.dumps(policy))
    bad["file_limits"][0]["surprise"] = True
    assert any("unknown keys" in item for item in validate_size_contract(bad))


def test_protected_file_growth_and_extraction_budget_rules() -> None:
    base = _size_policy()
    candidate = json.loads(json.dumps(base))
    growth = evaluate_size_delta(
        base, candidate, changed_paths={"src/hot.py"}, added_paths=set(),
        base_texts={"src/hot.py": _lines(5)}, candidate_texts={"src/hot.py": _lines(6)},
        change_class="feature", size_reviews={},
    )
    assert {item["code"] for item in growth} == {"PROTECTED_FILE_GROWTH"}
    assert evaluate_size_delta(
        base, candidate, changed_paths={"src/hot.py"}, added_paths=set(),
        base_texts={"src/hot.py": _lines(5)}, candidate_texts={"src/hot.py": _lines(5)},
        change_class="feature", size_reviews={},
    ) == []
    candidate["file_limits"][0]["max_lines"] = 4
    assert evaluate_size_delta(
        base, candidate, changed_paths={"src/hot.py"}, added_paths=set(),
        base_texts={"src/hot.py": _lines(5)}, candidate_texts={"src/hot.py": _lines(4)},
        change_class="extraction", size_reviews={},
    ) == []


def test_extraction_without_budget_lowering_and_budget_increase_fail() -> None:
    base = _size_policy()
    unchanged_budget = json.loads(json.dumps(base))
    findings = evaluate_size_delta(
        base, unchanged_budget, changed_paths={"src/hot.py"}, added_paths=set(),
        base_texts={"src/hot.py": _lines(5)}, candidate_texts={"src/hot.py": _lines(4)},
        change_class="extraction", size_reviews={},
    )
    assert {item["code"] for item in findings} == {"PROTECTED_BUDGET_NOT_LOWERED"}
    raised = json.loads(json.dumps(base))
    raised["file_limits"][0]["max_lines"] = 11
    findings = evaluate_size_delta(
        base, raised, changed_paths=set(), added_paths=set(),
        base_texts={}, candidate_texts={}, change_class="feature", size_reviews={},
    )
    assert {item["code"] for item in findings} == {"PROTECTED_BUDGET_INCREASE"}


def test_protected_symbol_growth_fails() -> None:
    base = _size_policy()
    symbol = {
        "path": "src/hot.py", "max_top_level_functions": 10,
        "max_top_level_classes": 10, "max_routes": 10,
        "protected": True, "non_growth": True, "owner": "test", "category": "hotspot",
    }
    base["symbol_limits"] = [symbol]
    candidate = json.loads(json.dumps(base))
    findings = evaluate_size_delta(
        base, candidate, changed_paths={"src/hot.py"}, added_paths=set(),
        base_texts={"src/hot.py": "def one():\n    pass\n"},
        candidate_texts={"src/hot.py": "def one():\n    pass\ndef two():\n    pass\n"},
        change_class="feature", size_reviews={},
    )
    assert "PROTECTED_SYMBOL_GROWTH" in {item["code"] for item in findings}


def test_new_handwritten_source_boundaries_and_review_rationale() -> None:
    base = _size_policy()
    candidate = json.loads(json.dumps(base))
    def codes(lines: int, reviews: dict[str, str] | None = None) -> set[str]:
        findings = evaluate_size_delta(
            base, candidate, changed_paths={"src/new.py"}, added_paths={"src/new.py"},
            base_texts={}, candidate_texts={"src/new.py": _lines(lines)},
            change_class="feature", size_reviews=reviews or {},
        )
        return {item["code"] for item in findings}
    assert codes(500) == set()
    assert codes(501) == {"SIZE_REVIEW_REQUIRED"}
    assert codes(501, {"src/new.py": "Bounded cohesive module; decomposition tracked."}) == set()
    assert codes(750) == {"SIZE_REVIEW_REQUIRED"}
    assert codes(750, {"src/new.py": "Reviewed temporary soft-limit module."}) == set()
    assert codes(751) == {"NEW_SOURCE_HARD_LIMIT_EXCEEDED"}


def test_same_package_classification_cannot_exempt_new_oversized_source() -> None:
    base = _size_policy()
    candidate = json.loads(json.dumps(base))
    candidate["source_size_policy"]["classifications"] = [
        {"pattern": "src/generated/**", "kind": "generated", "rationale": "candidate-only exception"}
    ]
    findings = evaluate_size_delta(
        base, candidate, changed_paths={"architecture/contract.json", "src/generated/huge.py"},
        added_paths={"src/generated/huge.py"}, base_texts={},
        candidate_texts={"src/generated/huge.py": _lines(751)},
        change_class="feature", size_reviews={},
    )
    codes = {item["code"] for item in findings}
    assert "ARCHITECTURE_SIZE_CONTRACT_INVALID" in codes
    assert "NEW_SOURCE_HARD_LIMIT_EXCEEDED" in codes


def test_protected_symbol_budget_increase_fails() -> None:
    base = _size_policy()
    symbol = {
        "path": "src/hot.py", "max_top_level_functions": 10,
        "max_top_level_classes": 10, "max_routes": 10,
        "protected": True, "non_growth": True, "owner": "test", "category": "hotspot",
    }
    base["symbol_limits"] = [symbol]
    candidate = json.loads(json.dumps(base))
    candidate["symbol_limits"][0]["max_routes"] = 11
    findings = evaluate_size_delta(
        base, candidate, changed_paths=set(), added_paths=set(),
        base_texts={}, candidate_texts={}, change_class="feature", size_reviews={},
    )
    assert "PROTECTED_BUDGET_INCREASE" in {item["code"] for item in findings}
