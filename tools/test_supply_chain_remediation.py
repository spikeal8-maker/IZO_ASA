"""Current remediation policy stays fail-closed; historical exceptions are fixtures."""
import copy
import json
from datetime import date
from pathlib import Path

import pytest

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
    dates = {"Pillow": "2026-10-26", "socksio": "2026-10-26", "cryptography": "2026-11-08"}
    assert len(reviews) == len(dates)
    assert {item["package"] for item in reviews} == set(dates)
    for item in reviews:
        assert len(item["licenseSha256"]) == 64
        assert item["reviewedOn"] == dates[item["package"]]
        assert item["sourceUrl"].startswith("https://github.com/")
    clean = {"status": "AVAILABLE", "findings": []}
    report = {"status": "AVAILABLE", "findings": copy.deepcopy(reviews)}
    assert evaluate_license_policy(clean, report, POLICY, as_of=TODAY)["status"] == "PASS"
    report["findings"][0]["resolvedVersion"] = "unreviewed-version"
    assert evaluate_license_policy(clean, report, POLICY, as_of=TODAY)["status"] == "FAIL"
    assert evaluate_license_policy(clean, clean, POLICY, as_of=date(2027, 1, 25))["status"] == "FAIL"


def _cryptography_review():
    return next(item for item in POLICY["licenses"]["reviews"] if item["package"] == "cryptography")


def test_cryptography_review_pins_verified_artifact_and_review_window():
    review = _cryptography_review()
    expected = {
        "ecosystem": "backend",
        "package": "cryptography",
        "resolvedVersion": "50.0.2",
        "license": "Apache-2.0 OR BSD-3-Clause",
        "classification": "unknown",
        "issue": "#281",
        "owner": "spikeal8-maker",
        "reviewedOn": "2026-11-08",
        "reviewBy": "2027-02-06",
        "verifiedLicense": "Apache-2.0 OR BSD-3-Clause",
        "sourceUrl": "https://github.com/pyca/cryptography/blob/4dda5c7fe4ae71b8925f2551910a0ef959df9c7a/LICENSE",
        "licenseSha256": "3e0c7c091a948b82533ba98fd7cbb40432d6f1a9acbf85f5922d2f99a93ae6bb",
        "artifactSha256": "7b46165bb56eb4704e2eaaf86f3c940d19154535d9b0ca7d6d590b04060e00d5",
    }
    assert {key: review[key] for key in expected} == expected


@pytest.mark.parametrize("field,value", [
    ("resolvedVersion", "50.0.3"),
    ("license", "Apache-2.0 AND BSD-3-Clause"),
    ("classification", "production"),
    ("ecosystem", "frontend"),
    ("package", "cryptography-other"),
])
def test_cryptography_review_rejects_changed_tuple(field, value):
    finding = copy.deepcopy(_cryptography_review())
    finding[field] = value
    clean = {"status": "AVAILABLE", "findings": []}
    report = {"status": "AVAILABLE", "findings": [finding]}
    result = evaluate_license_policy(clean, report, POLICY, as_of=date(2026, 11, 8))
    assert result["status"] == "FAIL"
    assert any(item.startswith("LICENSE_REVIEW_REQUIRED:") for item in result["violations"])


def test_cryptography_review_expiry_is_independent_of_older_reviews():
    policy = copy.deepcopy(POLICY)
    policy["licenses"]["reviews"] = [copy.deepcopy(_cryptography_review())]
    clean = {"status": "AVAILABLE", "findings": []}
    report = {"status": "AVAILABLE", "findings": copy.deepcopy(policy["licenses"]["reviews"])}
    assert evaluate_license_policy(clean, report, policy, as_of=date(2027, 2, 6))["status"] == "PASS"
    expired = evaluate_license_policy(clean, report, policy, as_of=date(2027, 2, 7))
    assert expired["status"] == "FAIL"
    assert expired["violations"] == ["EXPIRED_LICENSE_REVIEW[0]:2027-02-06"]
