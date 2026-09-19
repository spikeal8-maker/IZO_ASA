from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from tools.agent_system.symbol import (
    MAX_RESPONSE_BYTES,
    MAX_RESPONSE_LINES,
    MAX_SOURCE_LINES,
    SymbolContextError,
    build_symbol_context,
    render_symbol_context,
)


ROOT = Path(__file__).resolve().parents[1]


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_public_agent_symbol_plumbing_is_explicit_and_bounded() -> None:
    source = (ROOT / "tools" / "agent.ps1").read_text(encoding="utf-8")
    assert '[string]$Symbol = ""' in source
    assert 'if ($Command -eq "symbol")' in source
    assert "& $python -m tools.agent_system.symbol --repo-root $RepoRoot --path $Path --symbol $Symbol" in source
    assert "-Path is required for agent symbol." in source
    assert "-Symbol is required for agent symbol." in source


def test_real_backend_version_reuses_symbol_map_and_route_evidence() -> None:
    result = build_symbol_context(ROOT, "backend/main.py", "version")
    assert result["path"] == "backend/main.py"
    assert result["symbol"] == "version"
    assert result["classification"] == "source"
    assert result["kind"] in {"function", "async function"}
    assert result["declarationRange"]["start"] == 7886
    assert result["declarationRange"]["end"] >= result["declarationRange"]["start"]
    assert any(
        route.get("method") == "GET"
        and route.get("path") == "/api/version"
        and route.get("source") == "backend/SYMBOL_MAP.md"
        for route in result["routes"]
    )
    assert len(result["sourceWindow"]["lines"]) <= MAX_SOURCE_LINES
    assert result["sourceWindow"]["end"] < 8000


def test_real_newstudio_reuses_frontend_and_context_evidence_without_full_dump() -> None:
    result = build_symbol_context(ROOT, "frontend/src/newUi.tsx", "NewStudio")
    assert result["path"] == "frontend/src/newUi.tsx"
    assert result["symbol"] == "NewStudio"
    assert result["kind"] == "function"
    assert result["declaration"].startswith("export default function NewStudio")
    assert result["declarationRange"]["start"] == 152
    assert result["declarationRange"]["end"] > result["declarationRange"]["start"] + MAX_SOURCE_LINES
    assert result["sourceWindow"]["truncated"] is True
    assert len(result["sourceWindow"]["lines"]) == MAX_SOURCE_LINES
    assert any(route.get("predicate") == "isNewStudioRoute" for route in result["routes"])
    assert "frontend/e2e-studio-resilience.mjs" in result["tests"]
    assert {"chat", "frontend-studio"}.issubset(set(result["contextDomains"]))


def test_real_outputs_are_deterministic_ascii_safe_and_within_global_bounds() -> None:
    first = build_symbol_context(ROOT, "frontend/src/newUi.tsx", "NewStudio")
    second = build_symbol_context(ROOT, "frontend/src/newUi.tsx", "NewStudio")
    assert first == second
    rendered = render_symbol_context(first)
    assert rendered.isascii()
    assert "�" not in rendered
    assert len(rendered.encode("utf-8")) <= MAX_RESPONSE_BYTES
    assert len(rendered.splitlines()) <= MAX_RESPONSE_LINES
    parsed = json.loads(rendered)
    assert parsed["symbol"] == "NewStudio"
    source_line = (ROOT / "frontend/src/newUi.tsx").read_text(encoding="utf-8").splitlines()[152]
    emitted_line = next(item["text"] for item in parsed["sourceWindow"]["lines"] if item["line"] == 153)
    assert emitted_line == source_line


def test_unicode_fixture_roundtrips_through_ascii_safe_json_without_replacement(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/unicode.tsx",
        """export function Greeting() {
  // Привет — тест
  return 'готово'
}
""",
    )
    result = build_symbol_context(tmp_path, "src/unicode.tsx", "Greeting")
    unicode_line = next(item["text"] for item in result["sourceWindow"]["lines"] if item["line"] == 2)
    assert unicode_line == "  // Привет — тест"

    raw = render_symbol_context(result)
    assert raw.isascii()
    assert "�" not in raw
    assert len(raw.encode("utf-8")) <= MAX_RESPONSE_BYTES
    assert len(raw.splitlines()) <= MAX_RESPONSE_LINES

    parsed = json.loads(raw)
    restored = next(item["text"] for item in parsed["sourceWindow"]["lines"] if item["line"] == 2)
    assert restored == "  // Привет — тест"
    assert parsed["sourceWindow"] == result["sourceWindow"]


def test_python_fixture_proves_direct_callers_and_callees(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/sample.py",
        "def beta():\n"
        "    return 1\n\n"
        "def alpha():\n"
        "    return beta()\n",
    )
    alpha = build_symbol_context(tmp_path, "src/sample.py", "alpha")
    beta = build_symbol_context(tmp_path, "src/sample.py", "beta")
    assert alpha["directCallees"] == ["beta"]
    assert alpha["directCallers"] == []
    assert beta["directCallers"] == ["alpha"]
    assert beta["directCallees"] == []


def test_ts_fixture_proves_only_lexically_direct_local_edges(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/sample.tsx",
        "export function beta() { return 1 }\n"
        "export function alpha() { return beta() }\n",
    )
    alpha = build_symbol_context(tmp_path, "src/sample.tsx", "alpha")
    beta = build_symbol_context(tmp_path, "src/sample.tsx", "beta")
    assert alpha["directCallees"] == ["beta"]
    assert beta["directCallers"] == ["alpha"]
    assert alpha["unknownEdges"]


def test_dynamic_python_edge_is_explicitly_unknown(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/dynamic.py",
        "def alpha(obj):\n"
        "    return obj.beta()\n",
    )
    result = build_symbol_context(tmp_path, "src/dynamic.py", "alpha")
    assert result["directCallees"] == []
    assert any("dynamic" in item.lower() or "attribute" in item.lower() for item in result["unknownEdges"])


def test_imports_are_relevant_and_sorted(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/imports.py",
        "import zlib\n"
        "import json\n"
        "import pathlib\n\n"
        "def alpha():\n"
        "    return json.dumps(zlib.compress(b'x'))\n",
    )
    result = build_symbol_context(tmp_path, "src/imports.py", "alpha")
    assert result["imports"] == ["json", "zlib"]


def test_missing_symbol_fails_clearly(tmp_path: Path) -> None:
    _write(tmp_path, "src/sample.py", "def present():\n    return 1\n")
    with pytest.raises(SymbolContextError, match="symbol not found"):
        build_symbol_context(tmp_path, "src/sample.py", "missing")


@pytest.mark.parametrize(
    "requested",
    [
        "/tmp/escape.py",
        "C:/escape.py",
        "../escape.py",
        "src/../../escape.py",
    ],
)
def test_absolute_drive_and_traversal_paths_are_rejected(tmp_path: Path, requested: str) -> None:
    with pytest.raises(SymbolContextError):
        build_symbol_context(tmp_path, requested, "anything")


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = _write(tmp_path, "outside.py", "def escaped():\n    return 1\n")
    link = repo / "link.py"
    try:
        os.symlink(outside, link)
    except OSError as exc:
        pytest.skip(f"symlink unavailable on this platform: {exc}")
    with pytest.raises(SymbolContextError, match="repository escape"):
        build_symbol_context(repo, "link.py", "escaped")


def test_generated_vendor_minified_and_unsupported_are_explicit(tmp_path: Path) -> None:
    _write(tmp_path, "docs/generated/map.py", "def x():\n    return 1\n")
    _write(tmp_path, "vendor/lib.py", "def x():\n    return 1\n")
    _write(tmp_path, "src/app.min.js", "function x(){return 1}")
    _write(tmp_path, "notes.txt", "x")
    cases = {
        "docs/generated/map.py": "generated",
        "vendor/lib.py": "vendor",
        "src/app.min.js": "minified",
        "notes.txt": "unsupported",
    }
    for path, expected in cases.items():
        result = build_symbol_context(tmp_path, path, "x")
        assert result["classification"] == expected
        assert result["kind"] is None
        assert result["sourceWindow"]["lines"] == []
        assert expected in result["unknownEdges"][0]


def test_static_analysis_never_executes_application_source(tmp_path: Path) -> None:
    marker = tmp_path / "executed.txt"
    _write(
        tmp_path,
        "src/noexec.py",
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n\n"
        "def safe():\n"
        "    return 1\n",
    )
    result = build_symbol_context(tmp_path, "src/noexec.py", "safe")
    assert result["kind"] == "function"
    assert not marker.exists()
    source = (ROOT / "tools" / "agent_system" / "symbol.py").read_text(encoding="utf-8")
    assert ".rglob(" not in source
    assert "eval(" not in source
    assert "exec(" not in source
