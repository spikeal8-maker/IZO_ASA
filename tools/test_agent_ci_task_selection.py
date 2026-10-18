"""Real Task parser/gates with bounded controlled Git evidence; no Git mutations."""
import io
import json
import os
from contextlib import redirect_stderr
from dataclasses import replace
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

from tools.agent_system import enforce as subject
from tools.agent_system.package import AgentPackageError, TaskManifest, render_manifest

BASE, HEAD, BRANCH = "a" * 40, "b" * 40, "agent/new-001"
PATHS = ("tasks/OLD-001.toml", "tasks/NEW-001.toml", "backend/app/owned.py", "src/unowned", "secret/key")


def contract(identifier, base=BASE):
    return TaskManifest(1, identifier, base, "goal", "outcome", "before", "after", ("none",),
        "test-domain", "standard", "architecture", PATHS[:3], (), ("secret/**",), (), 0, 100,
        ("pass",), ("tests",), ("test",), ("bounded",), ("deploy",), "revert test package")


class SelectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ci-task-selection-"); self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name); (self.repo / "tasks").mkdir()
        for identifier, base in (("OLD-001", "c" * 40), ("NEW-001", BASE)):
            (self.repo / "tasks" / (identifier + ".toml")).write_text(render_manifest(contract(identifier, base)), encoding="utf-8")
        self.native, self.remote, self.calls = BRANCH, HEAD, []
        self.evidence = subject.Evidence(tuple(subject.Change("M", (p,)) for p in PATHS), PATHS, 251, (), ())
        for name, value in (("_ensure_commit", None), ("collect_evidence", self.evidence)):
            manager = patch.object(subject, name, return_value=value); setattr(self, name, manager.start()); self.addCleanup(manager.stop)
        manager = patch.object(subject, "_run", side_effect=self.git); manager.start(); self.addCleanup(manager.stop)
        manager = patch.dict(os.environ, {}, clear=True); manager.start(); self.addCleanup(manager.stop)

    def git(self, repo, *args, **kwargs):
        self.assertEqual(repo, self.repo); self.calls.append(args); code, value = 0, ""
        if args == ("merge-base", "--is-ancestor", BASE, "HEAD"): pass
        elif args == ("symbolic-ref", "--quiet", "--short", "HEAD"):
            code, value = (128, "") if self.native is None else (0 if self.native else 1, self.native)
        elif args == ("rev-parse", "HEAD"): value = HEAD
        elif args[:2] == ("rev-parse", "--verify"):
            self.assertTrue(args[2].startswith("refs/remotes/origin/agent/")); code, value = (1, "") if self.remote is None else (0, self.remote)
        else: self.fail("Unexpected Git operation: " + repr(args))
        return CompletedProcess(args, code, value, "")

    def select(self):
        return subject._ci_manifest(self.repo, BASE)

    def test_native_unpublished_branch_selects_parsed_id_and_preserves_complete_evidence(self):
        before = (self.repo / PATHS[0]).read_bytes(); manifest, evidence = self.select()
        self.assertEqual(manifest.id, "NEW-001"); self.assertIs(evidence, self.evidence)
        self.collect_evidence.assert_called_once_with(self.repo, BASE, ci=True)
        self._ensure_commit.assert_called_once_with(self.repo, BASE, fetch_missing=True)
        self.assertFalse(any(call[0] == "rev-parse" for call in self.calls))
        self.assertEqual((self.repo / PATHS[0]).read_bytes(), before)

    def test_ci_pr_push_and_dispatch_require_exact_remote_head(self):
        for self.native in ("", BRANCH):
            for event in ("pull_request", "push", "workflow_dispatch"):
                with self.subTest(event=event, native=self.native), patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": event,
                        "GITHUB_HEAD_REF": BRANCH if event == "pull_request" else "", "GITHUB_REF_NAME": "7/merge" if event == "pull_request" else BRANCH,
                        "GITHUB_REF_TYPE": "branch"}, clear=True):
                    self.assertEqual(self.select()[0].id, "NEW-001")
                    self.assertIn(("rev-parse", "--verify", f"refs/remotes/origin/{BRANCH}^{{commit}}"), self.calls)
                    for self.remote in (None, "d" * 40):
                        with self.assertRaisesRegex(subject.EnforcementError, "PACKAGE_MANIFEST_UNRESOLVED"): self.select()
                    self.remote = HEAD

    def test_unknown_noncanonical_and_mismatched_branches_fail_closed(self):
        for self.native in (None, "", "main", "feature/test", "agent/NEW-001", "agent/new_001", "agent/new-001/child", "agent/unknown"):
            with self.subTest(branch=self.native), self.assertRaisesRegex(subject.EnforcementError, "PACKAGE_MANIFEST_UNRESOLVED"): self.select()
        for environment in ({"GITHUB_EVENT_NAME": "pull_request", "GITHUB_HEAD_REF": "agent/old-001"},
                            {"GITHUB_EVENT_NAME": "push", "GITHUB_HEAD_REF": BRANCH, "GITHUB_REF_NAME": BRANCH},
                            {"GITHUB_EVENT_NAME": "push", "GITHUB_REF_NAME": BRANCH, "GITHUB_REF_TYPE": "tag"}):
            self.native = BRANCH
            with patch.dict(os.environ, environment, clear=True), self.assertRaises(subject.EnforcementError): self.select()

    def test_single_manifest_legacy_feature_branch_and_zero_candidate_contract_are_preserved(self):
        self.native = "feature/legacy"
        self.collect_evidence.return_value = replace(self.evidence, paths=(PATHS[1],))
        self.assertEqual(self.select()[0].id, "NEW-001")
        self.assertFalse(any(call[0] == "symbolic-ref" for call in self.calls))
        self.collect_evidence.return_value = replace(self.evidence, paths=())
        with self.assertRaisesRegex(subject.EnforcementError, "PACKAGE_MANIFEST_UNRESOLVED"): self.select()

    def test_manifest_id_filename_ambiguity_and_selected_base_drift_cannot_be_hidden(self):
        path = self.repo / PATHS[1]
        path.write_text(render_manifest(contract("WRONG-001")), encoding="utf-8")
        with self.assertRaisesRegex(AgentPackageError, "MANIFEST_FILENAME_MISMATCH"): self.select()
        with patch.object(subject, "parse_manifest", return_value=contract("NEW-001")):
            with self.assertRaisesRegex(subject.EnforcementError, "PACKAGE_MANIFEST_UNRESOLVED"): self.select()
        path.write_text(render_manifest(contract("NEW-001", "d" * 40)), encoding="utf-8")
        with self.assertRaisesRegex(subject.EnforcementError, "BASE_SHA_TARGET_DRIFT"): self.select()
        path.write_text(render_manifest(contract("NEW-001")), encoding="utf-8")
        (self.repo / PATHS[0]).write_text("invalid TOML", encoding="utf-8")
        with self.assertRaisesRegex(AgentPackageError, "MANIFEST_PARSE_FAILED"): self.select()

    def test_full_old_and_new_range_still_passes_scope_secret_size_and_budget_gates(self):
        output = io.StringIO()
        with patch.object(subject, "_size_policy_findings", return_value=[{"code": "PROTECTED_FILE_GROWTH"}]) as size, redirect_stderr(output):
            self.assertEqual(subject.run_ci(self.repo, BASE), 2)
        value = json.loads(output.getvalue().split(" ", 1)[1]); codes = {row["code"] for row in value["findings"]}
        self.assertEqual(value["changedPaths"], list(PATHS)); self.assertEqual(value["changedLines"], 251)
        self.assertTrue({"UNDECLARED_PATH", "FORBIDDEN_PATH", "FILE_BUDGET_EXCEEDED", "LOC_BUDGET_EXCEEDED", "PROTECTED_FILE_GROWTH"} <= codes)
        self.assertEqual(size.call_args.args[1].base_sha, BASE); self.assertIs(size.call_args.args[2], self.evidence)


if __name__ == "__main__":
    unittest.main()
