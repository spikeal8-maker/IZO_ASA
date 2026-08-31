"""Tests for the bounded IZO_ASA agent-efficiency eval harness."""
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "agent_efficiency_eval.py"
SPEC = importlib.util.spec_from_file_location("agent_efficiency_eval", MODULE_PATH)
assert SPEC and SPEC.loader
eval_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eval_tool)


EXPECTED_CASES = {
    "chat-model-selector",
    "admin-last-admin-race",
    "studio-text-to-image",
}


def _receipt(case_id: str) -> dict[str, object]:
    case = eval_tool.CASES[case_id]
    payload = eval_tool.template(case_id)
    payload.update({
        "runId": f"{case_id}-run-1",
        "startedAt": "2026-08-31T18:00:00+03:00",
        "repoHead": "f1ee842f41f2192e71db7f754ad1500190e1547f",
        "subjectFilesOpened": list(case["opened"]),
        "resultAnchors": list(case["anchors"]),
        "testsProposed": list(case["tests"]),
        "toolCalls": 4,
        "elapsedSeconds": 60,
        "result": "pass",
    })
    return payload


def test_fixed_cases_are_small_and_concrete() -> None:
    assert set(eval_tool.CASES) == EXPECTED_CASES
    for case in eval_tool.CASES.values():
        assert 1 <= case["limit"] <= 8
        assert case["opened"] and case["anchors"] and case["tests"]
        assert "Открой не более" in case["task"]


def test_prompts_are_read_only_cold_and_bounded() -> None:
    for case_id in EXPECTED_CASES:
        text = eval_tool.prompt(case_id)
        assert "АНАЛИЗ БЕЗ ИЗМЕНЕНИЙ" in text
        assert "Memory отключена" in text
        assert "Никакого recursive scan" in text
        assert "После ответа остановись" in text


def test_clean_receipts_pass_all_gates() -> None:
    for case_id in EXPECTED_CASES:
        result = eval_tool.validate(_receipt(case_id))
        assert result["caseId"] == case_id
        assert result["gatePassed"] is True
        assert result["violations"] == []
        assert result["tokenDataKnown"] is False


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


def test_reported_pass_with_missing_evidence_fails_gate() -> None:
    payload = _receipt("admin-last-admin-race")
    payload["resultAnchors"] = []
    result = eval_tool.validate(payload)
    assert result["gatePassed"] is False
    assert any(item.startswith("missing-anchors") for item in result["violations"])
    assert "reported-pass-with-violations" in result["violations"]


def test_absolute_paths_and_fake_token_estimates_are_invalid_receipts() -> None:
    payload = _receipt("studio-text-to-image")
    payload["subjectFilesOpened"] = [r"E:\IZO_ASA_WORKSPACE\docs\context\frontend-studio.md"]
    try:
        eval_tool.validate(payload)
    except eval_tool.InvalidReceipt as exc:
        assert "repository-relative" in str(exc)
    else:
        raise AssertionError("absolute path must be rejected")

    payload = _receipt("studio-text-to-image")
    payload["inputTokens"] = "bytes/4"
    try:
        eval_tool.validate(payload)
    except eval_tool.InvalidReceipt as exc:
        assert "inputTokens" in str(exc)
    else:
        raise AssertionError("estimated token string must be rejected")


def test_templates_use_ignored_runtime_receipts() -> None:
    assert ".runtime/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
