"""Current remediation policy stays fail-closed; historical exceptions are fixtures."""
import copy
import json
from datetime import date
from pathlib import Path

from tools.supply_chain_audit import evaluate_npm_policy
from tools.supply_chain_floor import evaluate_license_policy
from tools.test_supply_chain_audit import _clean_report, _single_finding

POLICY = json.loads((Path(__file__).resolve().parents[1] / "architecture/security-policy.json").read_text(encoding="utf-8"))
TODAY = date(2026, 10, 26)


def test_clean_current_audit_needs_no_high_severity_exception():
    assert POLICY["dependencyMutation"]["allowed"] is False
    assert POLICY["baselineExceptions"] == []
    assert evaluate_npm_policy(_clean_report(), _clean_report(), POLICY, as_of=TODAY)["status"] == "PASS"
    high = _single_finding("browserslist", severity="high", affected_range="<=4.28.6", advisory="GHSA-c83g-rgw3-j3cx")
    assert evaluate_npm_policy(high, _clean_report(), POLICY, as_of=TODAY)["status"] == "FAIL"
    unavailable = {"status": "UNAVAILABLE", "findings": []}
    assert evaluate_npm_policy(unavailable, _clean_report(), POLICY, as_of=TODAY)["status"] == "FAIL"


def test_exact_version_license_review_is_evidenced_scoped_and_expires():
    reviews = POLICY["licenses"]["reviews"]
    assert {item["package"] for item in reviews} == {"Pillow", "socksio"}
    for item in reviews:
        assert len(item["licenseSha256"]) == 64
        assert item["reviewedOn"] == "2026-10-26"
        assert item["sourceUrl"].startswith("https://github.com/")
    clean = {"status": "AVAILABLE", "findings": []}
    report = {"status": "AVAILABLE", "findings": copy.deepcopy(reviews)}
    assert evaluate_license_policy(clean, report, POLICY, as_of=TODAY)["status"] == "PASS"
    report["findings"][0]["resolvedVersion"] = "unreviewed-version"
    assert evaluate_license_policy(clean, report, POLICY, as_of=TODAY)["status"] == "FAIL"
    assert evaluate_license_policy(clean, clean, POLICY, as_of=date(2027, 1, 25))["status"] == "FAIL"
