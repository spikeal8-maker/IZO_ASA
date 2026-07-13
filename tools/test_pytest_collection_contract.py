from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_SCRIPT = ROOT / "tools" / "acceptance_generation_test.py"


def test_pytest_collects_only_explicit_test_prefix_files() -> None:
    config = (ROOT / "pytest.ini").read_text(encoding="utf-8")

    assert "python_files = test_*.py" in config
    assert not ACCEPTANCE_SCRIPT.name.startswith("test_")


def test_acceptance_script_uses_declared_http_client_dependency() -> None:
    tree = ast.parse(ACCEPTANCE_SCRIPT.read_text(encoding="utf-8"))
    imports = {
        node.names[0].name.split(".", 1)[0]
        for node in tree.body
        if isinstance(node, ast.Import)
    }
    requirements = (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8").casefold()

    assert "requests" not in imports
    assert "httpx" in imports
    assert "httpx==" in requirements
