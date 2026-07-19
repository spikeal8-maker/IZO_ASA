from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_all_agent_adapters_point_to_authoritative_rules() -> None:
    agents = _read("AGENTS.md")
    assert "source of truth" in agents
    assert "single release owner" in agents
    assert "Do not increase protected-file budgets" in agents
    assert "backend/main.py" in agents
    assert "production db" in agents.lower()
    assert "CODE COMPLETE" in agents
    assert "DEPLOYED" in agents
    assert "OPERATIONALLY VERIFIED" in agents

    for adapter in (
        "CLAUDE.md",
        "GEMINI.md",
        ".github/copilot-instructions.md",
    ):
        content = _read(adapter)
        assert "AGENTS.md" in content, adapter
        assert "authoritative" in content, adapter


def test_claude_adapter_does_not_restore_completed_phase_prohibitions() -> None:
    content = _read("CLAUDE.md")
    stale_prohibitions = (
        "Do not implement payments",
        "Do not implement payments, public feed",
        "Do not split `backend/main.py` into many modules unless explicitly approved",
    )
    for prohibition in stale_prohibitions:
        assert prohibition not in content


def test_current_plan_is_wired_as_source_of_truth() -> None:
    agents = _read("AGENTS.md")
    readme = _read("README.md")
    current_plan = "engineering-optimization-master-plan-20260719.md"
    assert current_plan in agents
    assert current_plan in readme
