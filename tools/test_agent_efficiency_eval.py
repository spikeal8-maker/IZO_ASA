"""Tests for the bounded IZO_ASA agent-efficiency eval harness."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "agent_efficiency_eval.py"
SPEC = importlib.util.spec_from_file_location("agent_efficiency_eval", MODULE_PATH)
assert SPEC and SPEC.loader
eval_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eval_tool)
ORIGINAL_ASSERT_CLEAN = eval_tool._assert_clean_checkout


EXPECTED_CASES = {
    "chat-model-selector",
    "admin-last-admin-race",
    "studio-text-to-image",
}


@pytest.fixture(autouse=True)
def _isolate_unit_receipts_from_developer_wip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eval_tool, "_assert_clean_checkout", lambda: None)


def _receipt(case_id: str) -> dict[str, object]:
    case = eval_tool.CASES[case_id]
    payload = eval_tool.template(case_id)
    payload.update({
        "subjectFilesOpened": list(case["opened"]),
        "resultAnchors": list(case["anchors"]),
        "testsProposed": list(case["tests"]),
        "toolCalls": 4,
        "elapsedSeconds": 60,
        "result": "pass",
    })
    return payload


def test_fixed_cases_are_small_concrete_and_fingerprinted() -> None:
    assert set(eval_tool.CASES) == EXPECTED_CASES
    prompt_fingerprints = set()
    rubric_fingerprints = set()
    for case_id, case in eval_tool.CASES.items():
        assert 1 <= case["limit"] <= 8
        assert case["opened"] and case["anchors"] and case["tests"]
        assert "Открой не более" in case["task"]
        rendered = eval_tool.prompt(case_id)
        expected_prompt = "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        assert eval_tool.case_fingerprint(case_id) == expected_prompt
        prompt_fingerprints.add(expected_prompt)
        rubric = eval_tool.rubric_fingerprint(case_id)
        assert rubric.startswith("sha256:") and len(rubric) == 71
        rubric_fingerprints.add(rubric)
    assert len(prompt_fingerprints) == len(EXPECTED_CASES)
    assert len(rubric_fingerprints) == len(EXPECTED_CASES)


def test_rubric_fingerprint_covers_global_gate_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    case_id = "chat-model-selector"
    original_routing = set(eval_tool.ROUTING_FILES)
    original = eval_tool.rubric_fingerprint(case_id)
    rules = eval_tool.evaluator_rules()
    assert rules["version"] == eval_tool.EVALUATOR_RULES_VERSION
    assert rules["requiredRoutingFiles"] == sorted(eval_tool.ROUTING_FILES)
    assert rules["protectedFullReads"] == sorted(eval_tool.PROTECTED_FULL_READS)
    assert rules["tokenSources"] == list(eval_tool.TOKEN_SOURCES)
    assert "reported-pass-requires-zero-violations" in rules["rules"]

    monkeypatch.setattr(
        eval_tool,
        "ROUTING_FILES",
        {*original_routing, "docs/EXTRA-ROUTING.md"},
    )
    assert eval_tool.rubric_fingerprint(case_id) != original

    monkeypatch.setattr(eval_tool, "ROUTING_FILES", original_routing)
    version_baseline = eval_tool.rubric_fingerprint(case_id)
    assert version_baseline == original
    monkeypatch.setattr(eval_tool, "EVALUATOR_RULES_VERSION", 2)
    assert eval_tool.rubric_fingerprint(case_id) != version_baseline


def test_prompts_are_read_only_cold_and_bounded() -> None:
    for case_id in EXPECTED_CASES:
        text = eval_tool.prompt(case_id)
        assert "АНАЛИЗ БЕЗ ИЗМЕНЕНИЙ" in text
        assert "Memory отключена" in text
        assert "Никакого recursive scan" in text
        assert "После ответа остановись" in text


def test_template_captures_actual_head_and_run_identity() -> None:
    payload = eval_tool.template("chat-model-selector")
    assert payload["repoHead"] == eval_tool._git_head()
    assert payload["runId"].startswith("chat-model-selector-")
    assert payload["startedAt"]
    assert payload["caseFingerprint"] == eval_tool.case_fingerprint("chat-model-selector")
    assert payload["rubricFingerprint"] == eval_tool.rubric_fingerprint("chat-model-selector")


def test_dirty_checkout_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eval_tool, "_git_status_porcelain", lambda: " M AGENTS.md")
    with pytest.raises(eval_tool.InvalidReceipt, match="checkout must be clean"):
        ORIGINAL_ASSERT_CLEAN()


def test_clean_receipts_pass_all_gates_and_keep_tokens() -> None:
    for case_id in EXPECTED_CASES:
        payload = _receipt(case_id)
        payload["inputTokens"] = 100
        payload["cachedInputTokens"] = 20
        payload["outputTokens"] = 10
        payload["tokenSource"] = "codex-ui"
        payload["tokenEvidence"] = "Codex session usage panel"
        result = eval_tool.validate(payload)
        assert result["caseId"] == case_id
        assert result["gatePassed"] is True
        assert result["violations"] == []
        assert result["inputTokens"] == 100
        assert result["cachedInputTokens"] == 20
        assert result["outputTokens"] == 10


def test_bad_agent_behavior_is_recorded_not_rejected() -> None:
    payload = _receipt("chat-model-selector")
    payload.update({
        "result": "fail",
        "largeFilesReadFully": ["backend/main.py"],
        "broadScans": ["recursive repository scan"],
        "repeatedSearches": 2,
        "ownerCorrections": 1,
    })
    result = eval_tool.validate(payload)
    assert result["gatePassed"] is False
    assert any(item.startswith("protected-full-read") for item in result["violations"])
    assert "broad-scans:1" in result["violations"]
    assert "repeated-searches:2" in result["violations"]
    assert "owner-corrections:1" in result["violations"]
    assert result["subjectFiles"] == 2
    assert any(
        item.startswith("full-read-not-listed-as-subject")
        for item in result["violations"]
    )


def test_reported_pass_with_missing_evidence_fails_gate() -> None:
    payload = _receipt("admin-last-admin-race")
    payload["resultAnchors"] = []
    result = eval_tool.validate(payload)
    assert result["gatePassed"] is False
    assert any(item.startswith("missing-anchors") for item in result["violations"])
    assert "reported-pass-with-violations" in result["violations"]


def test_changed_fingerprints_fake_tokens_and_missing_provenance_are_invalid() -> None:
    payload = _receipt("studio-text-to-image")
    payload["caseFingerprint"] = "sha256:" + ("0" * 64)
    with pytest.raises(eval_tool.InvalidReceipt, match="caseFingerprint"):
        eval_tool.validate(payload)

    payload = _receipt("studio-text-to-image")
    payload["rubricFingerprint"] = "sha256:" + ("0" * 64)
    with pytest.raises(eval_tool.InvalidReceipt, match="rubricFingerprint"):
        eval_tool.validate(payload)

    payload = _receipt("studio-text-to-image")
    payload["inputTokens"] = "bytes/4"
    with pytest.raises(eval_tool.InvalidReceipt, match="inputTokens"):
        eval_tool.validate(payload)

    payload = _receipt("studio-text-to-image")
    payload["inputTokens"] = 123
    with pytest.raises(eval_tool.InvalidReceipt, match="tokenSource"):
        eval_tool.validate(payload)


def test_receipt_must_match_actual_checkout_head() -> None:
    payload = _receipt("chat-model-selector")
    payload["repoHead"] = "0" * 40
    with pytest.raises(eval_tool.InvalidReceipt, match="current checkout HEAD"):
        eval_tool.validate(payload)


def test_absolute_paths_are_invalid_receipts() -> None:
    payload = _receipt("studio-text-to-image")
    payload["subjectFilesOpened"] = [r"E:\IZO_ASA_WORKSPACE\docs\context\frontend-studio.md"]
    with pytest.raises(eval_tool.InvalidReceipt, match="repository-relative"):
        eval_tool.validate(payload)


def test_equivalent_relative_paths_cannot_bypass_protected_read_gate() -> None:
    payload = _receipt("admin-last-admin-race")
    payload["result"] = "fail"
    payload["subjectFilesOpened"].append("./backend//main.py")
    payload["largeFilesReadFully"] = ["./backend//main.py"]
    result = eval_tool.validate(payload)
    assert result["subjectFiles"] == 3
    assert "protected-full-read:backend/main.py" in result["violations"]
    assert eval_tool._normalize_path("./backend//main.py", "path") == "backend/main.py"


def test_extra_routing_entries_count_as_subject_reads() -> None:
    payload = _receipt("chat-model-selector")
    payload["result"] = "fail"
    payload["routingFilesOpened"].append("backend/main.py")
    result = eval_tool.validate(payload)
    assert result["gatePassed"] is False
    assert result["subjectFiles"] == 2
    assert any(
        item.startswith("extra-routing-as-subject")
        for item in result["violations"]
    )


def test_proposed_tests_require_exact_paths() -> None:
    payload = _receipt("studio-text-to-image")
    payload["testsProposed"] = [
        "frontend/e2e-critical-prompts.mjs",
        "frontend/e2e-generate.mjs.not-a-file",
    ]
    payload["result"] = "fail"
    result = eval_tool.validate(payload)
    assert "missing-test-hints:frontend/e2e-generate.mjs" in result["violations"]

    payload = _receipt("admin-last-admin-race")
    payload["testsProposed"] = [
        "backend/test_admin_actions.py::test_self_demotion_and_last_admin_blocked"
    ]
    assert eval_tool.validate(payload)["gatePassed"] is True


def test_summary_requires_all_cases_same_sha_and_preserves_token_totals(tmp_path: Path) -> None:
    for index, case_id in enumerate(sorted(EXPECTED_CASES), start=1):
        payload = _receipt(case_id)
        payload["inputTokens"] = index * 100
        payload["cachedInputTokens"] = None
        payload["outputTokens"] = index * 10
        payload["tokenSource"] = "codex-api"
        payload["tokenEvidence"] = "API usage object"
        (tmp_path / f"{case_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    result = eval_tool.summarize(tmp_path)
    assert result["receiptCount"] == 3
    assert result["gatesPassed"] == 3
    assert result["tokenTotals"]["inputTokens"] == {
        "knownReceipts": 3,
        "value": 600,
    }
    assert result["tokenTotals"]["cachedInputTokens"] == {
        "knownReceipts": 0,
        "value": None,
    }
    assert result["tokenSources"]["codex-api"] == 3

    (tmp_path / "studio-text-to-image.json").unlink()
    with pytest.raises(eval_tool.InvalidReceipt, match="incomplete case set"):
        eval_tool.summarize(tmp_path)


def test_templates_use_ignored_runtime_receipts() -> None:
    assert ".runtime/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
