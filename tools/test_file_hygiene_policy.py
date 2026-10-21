"""Scope validation, classification, and fail-closed policy tests."""
import json
import unittest

from tools.file_hygiene import category
from tools.test_file_hygiene import RepositoryCase, review_manifest, run


class PolicyCases(RepositoryCase, unittest.TestCase):
    def test_fixture_helpers_and_jsx_are_bounded(self):
        for path in ("backend/tests/conftest.py", "tests/helpers.py", "frontend/__tests__/data.json",
                     "frontend/test_helpers/auth.ts", "frontend/editor.test.jsx", "frontend/editor.spec.mts"):
            self.assertEqual(category(path), "test")
        self.assertIsNone(category("tools/test_health_audit.py"))

    def test_renaming_fixture_to_archive_then_back_does_not_reset_budget(self):
        self.put("archive/a.md", "old\n" * 400)
        self.base = self.commit()
        (self.root / "docs").mkdir()
        run(self.root, "mv", "archive/a.md", "docs/a.md")
        self.assertEqual(self.assess()["findings"][0]["code"], "FILE_SIZE_EXCEEDED")

    def test_stale_manifest_cannot_approve_current_size_exception(self):
        self.put("tools/test_x.py", "assert True\n" * 501)
        self.put("tasks/REVIEW-001.toml", review_manifest("f" * 40, "tools/test_x.py"))
        codes = {x["code"] for x in self.assess()["findings"]}
        self.assertIn("SIZE_REVIEW_BASE_MISMATCH", codes)

    def test_duplicate_review_is_rejected_by_canonical_parser(self):
        path = "tools/test_x.py"
        source = review_manifest(self.base, path)
        source += '\n[[sizeReviews]]\npath="tools/test_x.py"\nrationale="Duplicate review must not silently replace the original."\n'
        self.put(path, "assert True\n" * 501)
        self.put("tasks/REVIEW-001.toml", source)
        self.assertEqual(self.assess()["findings"][0]["code"], "MANIFEST_INVALID")

    def test_review_outside_declared_scope_is_rejected(self):
        source = review_manifest(self.base, "tools/test_x.py")
        source = source.replace('declaredFiles = ["tools/test_x.py"]', 'declaredFiles = ["docs/a.md"]')
        self.put("tools/test_x.py", "assert True\n" * 501)
        self.put("tasks/REVIEW-001.toml", source)
        self.assertEqual(self.assess()["findings"][0]["code"], "SIZE_REVIEW_OUTSIDE_SCOPE")

    def test_byte_growth_of_old_file_is_not_hidden_by_line_shrink(self):
        self.put("docs/old.md", "x\n" * 300)
        self.base = self.commit()
        self.put("docs/old.md", "extra text\n" * 299)
        self.assertEqual(self.assess()["findings"][0]["code"], "LEGACY_GROWTH")

    def test_full_canonical_manifest_validation_is_used(self):
        path = "tools/test_x.py"
        source = review_manifest(self.base, path).replace('riskClass = "standard"', 'riskClass = "unvalidated"')
        self.put(path, "assert True\n" * 501)
        self.put("tasks/REVIEW-001.toml", source)
        self.assertEqual(self.assess()["findings"][0]["code"], "MANIFEST_INVALID")

    def test_line_policy_cannot_be_weakened_in_the_same_diff(self):
        self.put("architecture/contract.json", json.dumps({"source_size_policy": {"normal_max_lines": 900, "soft_max_lines": 1200}}))
        self.put("tools/test_x.py", "assert True\n" * 801)
        self.assertEqual(self.assess()["findings"][0]["code"], "FILE_SIZE_EXCEEDED")
