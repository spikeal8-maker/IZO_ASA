"""Cold workflow and build-input gates preserve the six original D1/D2 installs."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / ".github/workflows/docker-clean-install.yml").read_text(encoding="utf-8")
        self.source = self.text.split("  source:\n", 1)[1].split("\n  install:\n", 1)[0]
        self.install = self.text.split("  install:\n", 1)[1].split("\n  d3:\n", 1)[0]
        self.d3 = self.text.split("  d3:\n", 1)[1]

    def test_original_six_installations_time_limit_and_non_cancellation_are_retained(self):
        self.assertIn("cancel-in-progress: false", self.text)
        self.assertIn("timeout-minutes: 45", self.install)
        self.assertIn("fail-fast: false", self.install)
        self.assertIn("replica: [1, 2]", self.install)
        self.assertIn('python -m tools.docker_clean_install --source-sha "$GITHUB_SHA" --base-sha "$ACCEPTANCE_BASE" --replica "$REPLICA" --evidence-dir "$RUNNER_TEMP/docker-evidence" --extended', self.install)
        self.assertNotIn("continue-on-error", self.text)
        self.assertNotIn("|| true", self.text)

    def test_source_gate_contains_browser_io_and_private_ledger_and_retains_worker_contract(self):
        for path in ("tools/test_docker_d3_browser_io.mjs", "tools/test_docker_d3_browser_contracts.mjs",
                     "tools/test_docker_d3_process.py", "tools/test_docker_d3_image_ledger.py",
                     "tools/test_docker_d3_audio_fixture.py", "tools/test_docker_d3_ledger.py",
                     "tools/test_docker_d3_install.py", "backend/test_generation_worker_claims.py",
                     "backend/test_audio_protocol_runtime.py", "backend/test_local_video_job_history.py",
                     "backend/test_video_cancellation_fence.py",
                     "backend/test_api.py::test_public_health_is_minimal_and_does_not_expose_runtime_details"):
            self.assertIn(path, self.source)
        self.assertIn("node --test", self.source)
        self.assertIn("node-version: 24.14.1", self.source)
        self.assertIn("npm --prefix frontend run test:phone-audio", self.source)

    def test_artifacts_are_same_run_attempt_and_admission_precedes_runtime_setup(self):
        self.assertIn("needs: [source, install]", self.d3)
        self.assertIn("timeout-minutes: 45", self.d3)
        self.assertLess(self.d3.index("docker_d3_install admit"), self.d3.index("npm ci"))
        self.assertLess(self.d3.index("docker_d3_install admit"), self.d3.index("docker_d3_install run"))
        self.assertIn("--signal=INT --kill-after=180s 1800s", self.d3)
        for name in ("clean-linux-1", "clean-linux-2", "clean-images"):
            self.assertIn(name + "-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}", self.d3)
        self.assertNotIn("github-token:", self.d3)
        self.assertNotIn("merge-multiple:", self.d3)
        self.assertTrue(all(re.fullmatch(r"[a-f0-9]{40}", item) for item in re.findall(r"uses: [^@\s]+@([^\s]+)", self.text)))

    def test_audio_and_chat_providers_are_explicit_build_inputs_and_default_profile_unchanged(self):
        dockerfile = (ROOT / "ops/docker/dev/Dockerfile.backend").read_text()
        ignore = (ROOT / "ops/docker/dev/Dockerfile.backend.dockerignore").read_text().splitlines()
        for name in ("docker_shadow_fixture.py", "docker_shadow_provider.py", "docker_d3_chat_video_provider.py",
                     "docker_d3_audio_provider.py", "docker_d3_audio_fixture.py"):
            self.assertIn("tools/" + name, dockerfile)
            self.assertIn("!tools/" + name, ignore)
        for rule in ("**/.env", "**/.env.*", "**/*.sqlite*", "**/*.db*", "**/media/**", "**/secrets/**"):
            self.assertIn(rule, ignore)
        overlay = (ROOT / "ops/docker/dev/compose.d3-audio.yml").read_text()
        self.assertEqual([line.strip() for line in overlay.splitlines() if line.strip() and not line.startswith("#")],
                         ["services:", "backend:", "environment:", "IZO_SHADOW_FIXTURE: controlled-audio-v1"])
