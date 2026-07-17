from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools import release_verification_receipt as receipts


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    (repo / "tools" / "verify.ps1").write_text("Write-Host verify\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".runtime/\n", encoding="utf-8")
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "receipt-tests@example.invalid")
    _git(repo, "config", "user.name", "Receipt Tests")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")
    return repo, _git(repo, "rev-parse", "HEAD")


def _write(repo: Path, *, now: datetime) -> Path:
    output = repo / ".runtime" / "verification" / "receipt.json"
    receipts.write_receipt(
        root=repo,
        output_path=output,
        mode="Full",
        started_at=now - timedelta(minutes=5),
        completed_at=now,
        duration_seconds=300.0,
        summary={"ok": True, "mode": "Full"},
    )
    return output


def test_receipt_round_trip_is_exact_sha_clean_fresh_and_complete(tmp_path: Path) -> None:
    repo, sha = _repo(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    output = _write(repo, now=now)

    payload = receipts.validate_receipt(
        root=repo,
        receipt_path=output,
        expected_sha=sha,
        now=now + timedelta(minutes=1),
    )

    assert payload["receipt_version"] == 1
    assert payload["receipt_type"] == "release-verification"
    assert payload["git_sha"] == sha
    assert payload["branch"] == "main"
    assert payload["dirty"] is False
    assert payload["mode"] == "Full"
    assert set(receipts.REQUIRED_RELEASE_GATES).issubset(payload["gates"])


@pytest.mark.parametrize("field,value", [("git_sha", "0" * 40), ("dirty", True), ("gates", [])])
def test_receipt_rejects_tampered_release_contract(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    repo, sha = _repo(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    output = _write(repo, now=now)
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload[field] = value
    output.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(receipts.ReceiptError):
        receipts.validate_receipt(root=repo, receipt_path=output, expected_sha=sha, now=now)


def test_receipt_rejects_expiry_dirty_checkout_and_outside_runtime(tmp_path: Path) -> None:
    repo, sha = _repo(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    output = _write(repo, now=now)

    with pytest.raises(receipts.ReceiptError, match="expired"):
        receipts.validate_receipt(
            root=repo,
            receipt_path=output,
            expected_sha=sha,
            now=now + timedelta(hours=5),
        )

    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="clean"):
        receipts.validate_receipt(root=repo, receipt_path=output, expected_sha=sha, now=now)

    with pytest.raises(receipts.ReceiptError, match="canonical verification directory"):
        receipts.write_receipt(
            root=repo,
            output_path=tmp_path / "outside.json",
            mode="Full",
            started_at=now,
            completed_at=now,
            duration_seconds=0.0,
            summary={"ok": True},
        )
