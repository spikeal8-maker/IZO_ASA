"""Regression checks for both mandatory GitHub Actions contexts (#232)."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
HYGIENE = (ROOT / ".github/workflows/file-hygiene.yml").read_text(encoding="utf-8")
TRUST_EXPRESSION = (
    "github.event_name != 'pull_request' || "
    "(github.event.pull_request.head.repo.full_name == github.repository "
    "&& github.actor == 'spikeal8-maker')"
)



def _runnable_bash() -> str | None:
    """Probe a real Bash executable; Windows' WSL launcher is not sufficient."""
    candidates: list[Path] = []
    if os.name == "nt":
        git_exe = shutil.which("git")
        if git_exe:
            git_root = Path(git_exe).resolve().parent.parent
            candidates.extend((git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe"))
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(variable)
            if root:
                candidates.extend((Path(root) / "Git" / "bin" / "bash.exe", Path(root) / "Git" / "usr" / "bin" / "bash.exe"))

    in_path = shutil.which("bash")
    if in_path:
        candidates.append(Path(in_path))
    for candidate in dict.fromkeys(candidates):
        if not candidate.is_file():
            continue
        try:
            result = subprocess.run(
                [str(candidate), "-c", "printf 'IZO_BASH_READY'"],
                capture_output=True, text=True, check=False, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and result.stdout == "IZO_BASH_READY":
            return str(candidate)
    return None


class RequiredWorkflowGatesTests(unittest.TestCase):
    def test_required_contexts_are_unconditional_jobs(self) -> None:
        for source, job, context in (
            (CI, "verify", "Backend, tooling and frontend gates"),
            (HYGIENE, "check", "Bounded documentation and test file checks"),
        ):
            with self.subTest(job=job):
                header = source.split("\njobs:\n", 1)[1].split("\n    steps:\n", 1)[0]
                self.assertIn(f"  {job}:\n    name: {context}\n", header)
                self.assertNotIn("\n    if:", header)

    def test_all_main_pull_requests_schedule_both_contexts(self) -> None:
        for source in (CI, HYGIENE):
            with self.subTest(workflow=source.splitlines()[0]):
                self.assertIn("pull_request:\n    branches: [main]", source)
                self.assertIn("push:\n    branches: [main]", source)
                self.assertIn("  workflow_dispatch:", source)
                self.assertNotIn("    paths:", source)

    def test_admission_is_pre_checkout_and_fail_closed(self) -> None:
        for source, checkout, rejection in (
            (CI, "- name: Check out repository", 'throw "Untrusted pull request rejected before checkout."'),
            (HYGIENE, "- name: Check out exact source revision", "exit 1"),
        ):
            with self.subTest(checkout=checkout):
                first_step = source.split("    steps:\n", 1)[1].split(checkout, 1)[0]
                self.assertIn("IZO_PR_ALLOWED: ${{ " + TRUST_EXPRESSION + " }}", first_step)
                self.assertIn(rejection, first_step)
                self.assertIn('IZO_PR_ALLOWED -ne "true"' if source == CI else 'IZO_PR_ALLOWED" != "true"', first_step)

    def test_security_floors_and_exact_sha_are_retained(self) -> None:
        self.assertIn("permissions:\n  contents: read", CI)
        self.assertIn("permissions:\n  contents: read", HYGIENE)
        for source in (CI, HYGIENE):
            self.assertNotIn("pull_request_target", source)
            self.assertNotIn("secrets.", source)
            self.assertIn("persist-credentials: false", source)
        self.assertIn("ref: ${{ github.event_name == 'pull_request' && github.event.pull_request.head.sha || github.sha }}", CI)
        self.assertIn('test "$(git rev-parse HEAD)" = "$IZO_HEAD_SHA"', HYGIENE)
        self.assertIn("Enforce reviewed npm audit baseline", CI)
        self.assertIn("Enforce Python licenses and changed-scope secret floor", CI)

    def test_hygiene_untrusted_pr_fails_before_checkout(self) -> None:
        bash = _runnable_bash()
        if bash is None:
            if os.environ.get("GITHUB_ACTIONS") == "true":
                self.fail("CI requires an executable Bash; a nonworking WSL launcher is insufficient")
            self.skipTest("No executable Bash available outside CI")
        block = HYGIENE.split("      - name: Reject untrusted pull request before checkout\n", 1)[1]
        run = block.split("        run: |\n", 1)[1].split(
            "      - name: Check out exact source revision", 1
        )[0]
        script = textwrap.dedent(run).strip()
        for admitted, expected_code in (("true", 0), ("false", 1), ("", 1), ("TRUE", 1)):
            with self.subTest(admitted=admitted):
                env = dict(os.environ, IZO_PR_ALLOWED=admitted)
                result = subprocess.run(
                    [bash, "-c", script], env=env, text=True, capture_output=True, check=False, timeout=10
                )
                self.assertEqual(result.returncode, expected_code, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
