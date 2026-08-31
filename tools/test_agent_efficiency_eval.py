"""Tests for the bounded IZO_ASA agent-efficiency eval harness."""
from __future__ import annotations

import importlib.util
import json
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


def _receipt(case_id: str, repo_head: str = "f1ee842f41f2192e71db7f754ad1500190e1547f") -> dict[str, object]:
    case = eval_tool.CASES[case_id]
    payload = eval_tool.template(case_id)
    payload.update({
        "runId": f"{case_id}-run-1",
        "startedAt": "2026-08-31T18:00:00+03:00",
        "repoHead": repo_head,
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
    fingerprints = set()
    for case_id, case in eval_tool.CASES.items():
        assert 1 <= case["limit"] <= 8
        assert case["opened"] and case["anchors"] and case["tests"]
        assert "Открой не более" in case["task"]
        fingerprint = eval_tool.case_fingerprint(case_id)
        assert fingerprint.startswith("sha256:") and len(fingerprint) == 71
        fingerprints.add(fingerprint)
    assert len(fingerprints) == len(EXPECTED_CASES)


def test_prompts_are_read_only_cold_and_bounded() -> None:
    for case_id in EXPECTED_CASES:
        text = eval_tool.prompt(case_id)
        assert "АНАЛИЗ БЕЗ ИЗМЕНЕНИЙ" in text
        assert "Memory отключена" in text
        assert "Никакого recursive scan" in text
        assert "После ответа остановись" in text


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


def test_changed_fingerprint_fake_tokens_and_missing_provenance_are_invalid() -> None:
    payload = _receipt("studio-text-to-image")
    payload["caseFingerprint"] = "sha256:" + ("0" * 64)
    try:
        eval_tool.validate(payload)
    except eval_tool.InvalidReceipt as exc:
        assert "caseFingerprint" in str(exc)
    else:
        raise AssertionError("wrong case fingerprint must be rejected")

    payload = _receipt("studio-text-to-image")
    payload["inputTokens"] = "bytes/4"
    try:
        eval_tool.validate(payload)
    except eval_tool.InvalidReceipt as exc:
        assert "inputTokens" in str(exc)
    else:
        raise AssertionError("estimated token string must be rejected")

    payload = _receipt("studio-text-to-image")
    payload["inputTokens"] = 123
    try:
        eval_tool.validate(payload)
    except eval_tool.InvalidReceipt as exc:
        assert "tokenSource" in str(exc)
    else:
        raise AssertionError("numeric tokens without Codex/API provenance must be rejected")


def test_absolute_paths_are_invalid_receipts() -> None:
    payload = _receipt("studio-text-to-image")
    payload["subjectFilesOpened"] = [r"E:\IZO_ASA_WORKSPACE\docs\context\frontend-studio.md"]
    try:
        eval_tool.validate(payload)
    except eval_tool.InvalidReceipt as exc:
        assert "repository-relative" in str(exc)
    else:
        raise AssertionError("absolute path must be rejected")


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
    try:
        eval_tool.summarize(tmp_path)
    except eval_tool.InvalidReceipt as exc:
        assert "incomplete case set" in str(exc)
    else:
        raise AssertionError("incomplete case set must be rejected")


def test_templates_use_ignored_runtime_receipts() -> None:
    assert ".runtime/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
