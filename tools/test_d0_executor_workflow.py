from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "d0-executor-proof.yml"
PINNED_USE = re.compile(r"uses:\s+[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}(?:\s+#.*)?$")


class D0ExecutorWorkflowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = WORKFLOW.read_text(encoding="utf-8")

    def test_runner_and_exact_checkout_contract(self) -> None:
        self.assertIn("runs-on: ubuntu-24.04", self.source)
        self.assertNotIn("runs-on: self-hosted", self.source)
        self.assertIn("runner.environment", self.source)
        self.assertIn("github.event.pull_request.head.sha", self.source)
        self.assertIn("github.sha", self.source)
        self.assertIn("persist-credentials: false", self.source)
        self.assertIn("fetch-depth: 0", self.source)

    def test_every_action_is_pinned_to_full_sha(self) -> None:
        use_lines = [line.strip() for line in self.source.splitlines() if "uses:" in line]
        self.assertEqual(len(use_lines), 4)
        for line in use_lines:
            self.assertRegex(line, PINNED_USE)

    def test_pinned_project_toolchain_and_safe_proof(self) -> None:
        self.assertIn("python-version-file: .python-version", self.source)
        self.assertIn("node-version-file: .node-version", self.source)
        self.assertIn("package-manager-cache: false", self.source)
        self.assertIn("d0-executor-receipt.json", self.source)
        self.assertIn("d0-executor-evidence-", self.source)
        self.assertIn("tools/d0_executor_probe.py", self.source)
        self.assertNotIn("secrets.", self.source)

    def test_workflow_does_not_start_application_or_use_d2(self) -> None:
        lowered = self.source.lower()
        for forbidden in (
            "docker compose up",
            "docker-compose up",
            "docker run ",
            "uvicorn ",
            "npm run dev",
            "desktop commander",
            "remote desktop",
            "d2-r2-x",
        ):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
