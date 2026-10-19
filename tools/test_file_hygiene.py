"""No-network unit tests for the docs and test-size gate."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.file_hygiene import assess, category, inventory


def run(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(f"git {args}: {result.stderr}")
    return result.stdout.strip()


def review_manifest(base: str, path: str) -> str:
    data = {
        "manifestVersion": 1, "id": "REVIEW-001", "baseSha": base,
        "goal": "Bounded compatibility test", "userOutcome": "Preserved regression coverage",
        "beforeScenario": "Existing behavior is characterized", "afterScenario": "Coverage remains explicit",
        "domain": "test-file-policy", "riskClass": "standard", "changeClass": "test",
        "maxProductionFiles": 0, "maxChangedLines": 1000, "nonGoals": ["Production changes"],
        "declaredFiles": [path], "allowedPatterns": [], "forbiddenPatterns": [],
        "protectedFilesTouched": [], "acceptance": ["Focused tests pass"],
        "requiredEvidence": ["Exact-source test report"], "targetedTests": ["Isolated unit tests"],
        "fileGrowthExpectations": ["Reviewed temporary compatibility scope"],
        "forbiddenOperations": ["deploy"], "rollbackBoundary": "Revert the test-only change",
    }
    text = "\n".join(f"{key} = {json.dumps(value)}" for key, value in data.items())
    return text + '\n[[sizeReviews]]\npath = ' + json.dumps(path) + '\nrationale = "Temporary compatibility module while splitting the old suite."\n'


class RepositoryCase:
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        run(self.root, "init", "-q")
        run(self.root, "config", "user.email", "docs@example.invalid")
        run(self.root, "config", "user.name", "fixture")
        self.put("architecture/contract.json", json.dumps({"source_size_policy": {"normal_max_lines": 500, "soft_max_lines": 750}}))
        self.base = self.commit()

    def put(self, path: str, text: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self) -> str:
        run(self.root, "add", "-A")
        run(self.root, "commit", "-qm", "fixture")
        return run(self.root, "rev-parse", "HEAD")

    def assess(self):
        return assess(self.root, self.base, self.commit())

class FileHygieneContractTests(RepositoryCase, unittest.TestCase):
    def test_new_document_limits_both_lines_and_utf8_bytes(self) -> None:
        self.put("docs/good.md", "строка\n" * 180)
        self.assertTrue(self.assess()["passed"])
        self.put("docs/big.md", "х\n" * 201)
        self.assertEqual(self.assess()["findings"][0]["code"], "FILE_SIZE_EXCEEDED")
        self.put("docs/big.md", "слово" * 2500)
        self.assertEqual(self.assess()["findings"][0]["code"], "FILE_SIZE_EXCEEDED")

    def test_new_nav_limit_and_existing_now_policy(self) -> None:
        self.put("docs/README.md", "navigation\n" * 121)
        self.assertEqual(self.assess()["findings"][0]["code"], "FILE_SIZE_EXCEEDED")
        self.put("docs/README.md", "navigation\n" * 100)
        self.put("docs/NOW.md", "status\n" * 130)
        self.assertTrue(self.assess()["passed"])

    def test_generated_context_and_archive_are_excluded(self) -> None:
        for p in ("docs/generated/generated.md", "docs/context/large.md", "archive/docs/snapshot.md"):
            self.put(p, "history\n" * 800)
        self.assertTrue(self.assess()["passed"])

    def test_new_test_hard_limit_and_frontend_classification(self) -> None:
        self.put("backend/test_unit.py", "assert True\n" * 751)
        self.assertEqual(self.assess()["findings"][0]["code"], "FILE_SIZE_EXCEEDED")
        self.put("backend/test_unit.py", "assert True\n" * 40)
        self.put("frontend/e2e-login.mjs", "test('ok', () => {})\n" * 501)
        self.assertEqual(self.assess()["findings"][0]["code"], "TEST_SIZE_REVIEW_REQUIRED")
        self.assertEqual(category("frontend/foo.spec.ts"), "test")
        self.assertEqual(category("frontend/phoneImage.test.ts"), "test")
        self.assertEqual(category("tools/test_quality.py"), "test")
        self.assertEqual(category("TEST_PLAN.md"), "document")
        self.assertIsNone(category("frontend/src/VideoStudio.tsx"))

    def test_review_requires_scoped_task_manifest_rationale(self) -> None:
        self.put("tools/test_review.py", "assert True\n" * 501)
        self.assertEqual(self.assess()["findings"][0]["code"], "TEST_SIZE_REVIEW_REQUIRED")
        self.put("tasks/REVIEW-001.toml", review_manifest(self.base, "tools/test_review.py"))
        self.assertTrue(self.assess()["passed"])

    def test_test_review_byte_hard_limit(self) -> None:
        self.put("frontend/foo.test.ts", "x" * 37000)
        self.put("tasks/REVIEW-001.toml", review_manifest(self.base, "frontend/foo.test.ts"))
        self.assertEqual(self.assess()["findings"][0]["code"], "FILE_SIZE_EXCEEDED")

    def test_existing_oversized_module_may_shrink_but_not_grow(self) -> None:
        self.put("backend/test_legacy.py", "assert True\n" * 800)
        self.base = self.commit()
        self.put("backend/test_legacy.py", "assert True\n" * 801)
        self.assertEqual(self.assess()["findings"][0]["code"], "LEGACY_GROWTH")
        self.put("backend/test_legacy.py", "assert True\n" * 799)
        self.assertTrue(self.assess()["passed"])

    def test_rename_uses_old_path_baseline(self) -> None:
        self.put("docs/old.md", "a\n" * 240)
        self.base = self.commit()
        run(self.root, "mv", "docs/old.md", "docs/new.md")
        self.assertTrue(self.assess()["passed"])
        self.put("docs/new.md", "a\n" * 241)
        self.assertEqual(self.assess()["findings"][0]["code"], "LEGACY_GROWTH")

    def test_added_link_is_checked_older_broken_link_is_grandfathered(self) -> None:
        self.put("docs/old.md", "[historical](missing.md)\n")
        self.base = self.commit()
        self.put("docs/old.md", "[historical](missing.md)\nupdated\n")
        self.assertTrue(self.assess()["passed"])
        self.put("docs/old.md", "[historical](missing.md)\n[broken](new_missing.md)\n")
        self.assertEqual(self.assess()["findings"][0]["code"], "BROKEN_LOCAL_REFERENCE")
        self.put("docs/existing.md", "ok\n")
        self.put("docs/old.md", "[historical](missing.md)\n[valid](existing.md)\n")
        self.assertTrue(self.assess()["passed"])

    def test_deleted_files_do_not_trigger_budget(self) -> None:
        self.put("docs/large.md", "old\n" * 1000)
        self.base = self.commit()
        (self.root / "docs/large.md").unlink()
        self.assertTrue(self.assess()["passed"])

    def test_removing_referenced_document_fails(self) -> None:
        self.put("docs/index.md", "[detail](detail.md)\n")
        self.put("docs/detail.md", "details\n")
        self.base = self.commit()
        (self.root / "docs/detail.md").unlink()
        self.assertEqual(self.assess()["findings"][0]["code"], "BROKEN_LOCAL_REFERENCE")

    def test_fenced_sample_links_do_not_trigger_false_positive(self) -> None:
        self.put("docs/help.md", "```md\n[example](not-a-file.md)\n```\n[real](valid.md)\n")
        self.put("docs/valid.md", "ok\n")
        self.assertTrue(self.assess()["passed"])

    def test_lightweight_workflow_is_hosted_read_only_and_pinned(self) -> None:
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/file-hygiene.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: ubuntu-22.04", workflow)
        self.assertNotIn("runs-on: [self-hosted", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("python -m tools.file_hygiene --base", workflow)
        self.assertIn("python -m unittest -v tools.test_file_hygiene", workflow)
        self.assertIn("github.event.pull_request.head.sha", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("docker run", workflow.lower())
        self.assertNotIn("docker compose", workflow.lower())
        import re
        uses = [x.strip() for x in workflow.splitlines() if x.strip().startswith("uses:")]
        self.assertEqual(len(uses), 3)
        for line in uses:
            self.assertRegex(line, r"uses: actions/[A-Za-z-]+@[0-9a-f]{40}(?: #.*)?$")

    def test_inventory_reports_legacy_without_failure(self) -> None:
        self.put("docs/large.md", "old\n" * 301)
        self.put("backend/test_large.py", "x = True\n" * 801)
        head = self.commit()
        summary = inventory(self.root, head)
        self.assertEqual(summary["grandfathered_over_budget"], 2)
        self.assertEqual(summary["by_kind"]["test"], 1)
        self.assertEqual(summary["by_kind"]["document"], 1)

    def test_non_hex_revision_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "40-hex"):
            assess(self.root, "HEAD^", self.base)


if __name__ == "__main__":
    unittest.main()
