"""Scope validation, classification, and fail-closed policy tests."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.agent_system import enforce
from tools.file_hygiene import category
from tools.file_hygiene_git import Change, GitTree
from tools.file_hygiene_reviews import read_reviews
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

    def test_multiple_manifests_select_actual_git_branch_without_losing_size_gate(self):
        run(self.root, "checkout", "-qb", "agent/review-001")
        self.put("tools/test_x.py", "assert True\n" * 501)
        self.put("tasks/REVIEW-001.toml", review_manifest(self.base, "tools/test_x.py"))
        self.put("tasks/OLD-001.toml", review_manifest(self.base, "tools/test_old.py").replace('REVIEW-001', 'OLD-001'))
        with patch.dict("os.environ", {key: "" for key in ("GITHUB_ACTIONS", "GITHUB_EVENT_NAME", "GITHUB_HEAD_REF", "GITHUB_REF_NAME", "GITHUB_REF_TYPE")}):
            self.assertEqual(self.assess()["findings"], [])
            self.put("tools/test_x.py", "assert True\n" * 751)
            self.assertIn("FILE_SIZE_EXCEEDED", {row["code"] for row in self.assess()["findings"]})


class TaskSelectionCases(unittest.TestCase):
    BASE, HEAD = "a" * 40, "b" * 40

    def setUp(self):
        self.data = {f"tasks/{name}-001.toml": review_manifest(self.BASE, f"tools/test_{name.lower()}.py")
                     .replace('id = "REVIEW-001"', f'id = "{name}-001"').encode() for name in ("OLD", "NEW")}
        for name, value in (("_ci_source_branch", "agent/new-001"), ("_git_text", self.HEAD)):
            manager = patch.object(enforce, name, return_value=value)
            setattr(self, name, manager.start()); self.addCleanup(manager.stop)

    def read(self, revision=None, duplicate=False):
        tree = GitTree.__new__(GitTree); tree.repo, tree.revision = Path.cwd(), revision or self.HEAD
        tree.files = {path: ("100644", str(i)) for i, path in enumerate(self.data)}
        tree._data = {str(i): value for i, value in enumerate(self.data.values())}
        delta = [Change("M", path) for path in self.data]
        return read_reviews(tree, self.BASE, delta + delta[-1:] if duplicate else delta)

    def test_current_tracked_contract_selects_only_its_own_review(self):
        reviews, errors = self.read()
        self.assertEqual(errors, []); self.assertEqual(set(reviews), {"tools/test_new.py"})
        self._git_text.assert_called_once_with(Path.cwd(), "rev-parse", "HEAD")
        self._ci_source_branch.assert_called_once_with(Path.cwd())

    def test_historical_tree_alias_and_missing_head_do_not_use_current_branch(self):
        for revision in ("c" * 40, "HEAD"):
            with self.subTest(revision=revision):
                self.assertEqual(self.read(revision), ({}, [{"code": "AMBIGUOUS_CURRENT_MANIFEST"}]))
        self._git_text.side_effect = enforce.EnforcementError("GIT_FAILED")
        self.assertEqual(self.read(), ({}, [{"code": "AMBIGUOUS_CURRENT_MANIFEST"}]))
        self._ci_source_branch.assert_not_called()

    def test_branch_failure_unknown_and_duplicate_authority_are_not_approvals(self):
        self._ci_source_branch.side_effect = enforce.EnforcementError("PACKAGE_MANIFEST_UNRESOLVED")
        self.assertEqual(self.read(), ({}, [{"code": "AMBIGUOUS_CURRENT_MANIFEST"}]))
        self._ci_source_branch.side_effect = None; self._ci_source_branch.return_value = "agent/absent-001"
        self.assertEqual(self.read(), ({}, [{"code": "AMBIGUOUS_CURRENT_MANIFEST"}]))
        self._ci_source_branch.return_value = "agent/new-001"
        self.assertEqual(self.read(duplicate=True), ({}, [{"code": "AMBIGUOUS_CURRENT_MANIFEST"}]))

    def test_nested_task_cannot_supply_canonical_branch_authority(self):
        self.data["tasks/nested/NEW-001.toml"] = self.data.pop("tasks/NEW-001.toml")
        self.assertEqual(self.read(), ({}, [{"code": "AMBIGUOUS_CURRENT_MANIFEST"}]))

    def test_all_parsing_base_and_selected_scope_guards_still_apply(self):
        original = dict(self.data)
        cases = [("tasks/OLD-001.toml", b"invalid TOML", "MANIFEST_INVALID"),
                 ("tasks/NEW-001.toml", original["tasks/NEW-001.toml"].replace(b'NEW-001', b'WRONG-001'), "MANIFEST_INVALID"),
                 ("tasks/OLD-001.toml", original["tasks/OLD-001.toml"].replace(self.BASE.encode(), b'f' * 40), "SIZE_REVIEW_BASE_MISMATCH")]
        for replacement in (b'declaredFiles = ["docs/a.md"]', b'forbiddenPatterns = ["tools/**"]'):
            token = b'declaredFiles = ["tools/test_new.py"]' if replacement.startswith(b'declared') else b'forbiddenPatterns = []'
            cases.append(("tasks/NEW-001.toml", original["tasks/NEW-001.toml"].replace(token, replacement), "SIZE_REVIEW_OUTSIDE_SCOPE"))
        for path, data, expected in cases:
            self.data = {**original, path: data}
            with self.subTest(code=expected, path=path):
                reviews, errors = self.read(); self.assertEqual(reviews, {})
                self.assertIn(expected, {item["code"] for item in errors})

    def test_single_historical_legacy_manifest_and_zero_candidates_are_unchanged(self):
        del self.data["tasks/OLD-001.toml"]
        reviews, errors = self.read("c" * 40)
        self.assertEqual(errors, []); self.assertEqual(set(reviews), {"tools/test_new.py"})
        self.data = {}; self.assertEqual(self.read(), ({}, []))
        self._git_text.assert_not_called(); self._ci_source_branch.assert_not_called()
