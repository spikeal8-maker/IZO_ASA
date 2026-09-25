from __future__ import annotations

import copy
import unittest

from tools.d0_executor_probe import evaluate_receipt


HEAD = "a" * 40


def passing_receipt() -> dict:
    return {
        "expectedHead": HEAD,
        "exactHead": HEAD,
        "runnerEnvironment": "github-hosted",
        "runnerOS": "Linux",
        "usedSelfHostedRunner": False,
        "expectedPythonVersion": "3.11.9",
        "pythonVersion": "3.11.9",
        "expectedNodeVersion": "24.14.1",
        "nodeVersion": "24.14.1",
        "npmVersion": "11.0.0",
        "dockerClientVersion": "28.0.0",
        "dockerServerVersion": "28.0.0",
        "dockerBuildxVersion": "github.com/docker/buildx v0.20.0",
        "networkProbes": [
            {"targetClass": "npm_registry", "status": "PASS"},
            {"targetClass": "pypi", "status": "PASS"},
            {"targetClass": "docker_registry", "status": "PASS"},
        ],
        "productionCredentialPresence": False,
        "startedApplication": False,
        "usedD2": False,
    }


class D0ExecutorProbeTests(unittest.TestCase):
    def assert_fail(self, receipt: dict, violation: str) -> None:
        status, violations = evaluate_receipt(receipt)
        self.assertEqual(status, "FAIL")
        self.assertIn(violation, violations)

    def test_wrong_sha_fails(self) -> None:
        receipt = passing_receipt()
        receipt["exactHead"] = "b" * 40
        self.assert_fail(receipt, "EXACT_HEAD_MISMATCH")

    def test_self_hosted_environment_fails(self) -> None:
        receipt = passing_receipt()
        receipt["runnerEnvironment"] = "self-hosted"
        receipt["usedSelfHostedRunner"] = True
        self.assert_fail(receipt, "RUNNER_NOT_GITHUB_HOSTED")

    def test_missing_required_tool_fails(self) -> None:
        receipt = passing_receipt()
        receipt["dockerServerVersion"] = None
        self.assert_fail(receipt, "DOCKER_SERVER_UNAVAILABLE")

    def test_failed_registry_probe_is_not_pass(self) -> None:
        receipt = passing_receipt()
        receipt["networkProbes"] = copy.deepcopy(receipt["networkProbes"])
        receipt["networkProbes"][2]["status"] = "EXTERNAL_VERIFICATION_UNAVAILABLE"
        status, violations = evaluate_receipt(receipt)
        self.assertEqual(status, "FAIL")
        self.assertIn("NETWORK_DOCKER_REGISTRY_NOT_PASS", violations)

    def test_production_credential_present_fails(self) -> None:
        receipt = passing_receipt()
        receipt["productionCredentialPresence"] = True
        self.assert_fail(receipt, "PRODUCTION_CREDENTIAL_PRESENT")

    def test_complete_github_hosted_receipt_passes(self) -> None:
        status, violations = evaluate_receipt(passing_receipt())
        self.assertEqual(status, "PASS")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
