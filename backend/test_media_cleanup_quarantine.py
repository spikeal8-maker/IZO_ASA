from __future__ import annotations

import json

import main
import media_cleanup_plan
import media_cleanup_quarantine


def test_quarantine_moves_candidate_and_writes_manifest(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(main, "MEDIA", media)
    candidate = media / "old" / "orphan.png"
    candidate.parent.mkdir()
    candidate.write_bytes(b"gallery residue")

    monkeypatch.setattr(
        media_cleanup_plan,
        "build_cleanup_plan",
        lambda **_kwargs: {
            "created_at": "2026-07-11T00:00:00+00:00",
            "candidate_summary": {"count": 1, "bytes": 15, "human": "15 B", "truncated_to": 1},
            "source_audit": {"issues": []},
            "selected_kinds": ["original_or_input"],
            "protected_kinds": sorted(media_cleanup_plan.PROTECTED_KINDS),
            "candidates": [{"file": "old/orphan.png", "bytes": 15, "kind": "original_or_input", "reason": "unreferenced"}],
        },
    )

    quarantine = tmp_path / "quarantine"
    result = media_cleanup_quarantine.quarantine_cleanup(quarantine, apply=True)

    assert result["mode"] == "quarantine"
    assert result["moved_summary"]["count"] == 1
    assert not candidate.exists()
    assert (quarantine / "old" / "orphan.png").read_bytes() == b"gallery residue"
    manifest = json.loads((quarantine / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["moved"][0]["sha256"] == result["moved"][0]["sha256"]


def test_quarantine_is_blocked_by_source_issues(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(main, "MEDIA", media)
    candidate = media / "keep.png"
    candidate.write_bytes(b"keep")
    monkeypatch.setattr(
        media_cleanup_plan,
        "build_cleanup_plan",
        lambda **_kwargs: {
            "created_at": "2026-07-11T00:00:00+00:00",
            "candidate_summary": {"count": 1, "bytes": 4, "human": "4 B", "truncated_to": 1},
            "source_audit": {"issues": ["missing_active_refs"]},
            "selected_kinds": ["original_or_input"],
            "protected_kinds": [],
            "candidates": [{"file": "keep.png", "bytes": 4, "kind": "original_or_input", "reason": "unreferenced"}],
        },
    )

    result = media_cleanup_quarantine.quarantine_cleanup(tmp_path / "quarantine", apply=True)

    assert result["mode"] == "blocked"
    assert result["moves_files"] is False
    assert candidate.exists()
    assert not (tmp_path / "quarantine").exists()


def test_quarantine_must_be_outside_media(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(main, "MEDIA", media)
    monkeypatch.setattr(
        media_cleanup_plan,
        "build_cleanup_plan",
        lambda **_kwargs: {
            "created_at": "2026-07-11T00:00:00+00:00",
            "candidate_summary": {},
            "source_audit": {"issues": []},
            "selected_kinds": [],
            "protected_kinds": [],
            "candidates": [],
        },
    )

    try:
        media_cleanup_quarantine.quarantine_cleanup(media / "quarantine")
    except ValueError as exc:
        assert "outside MEDIA_DIR" in str(exc)
    else:
        raise AssertionError("Expected quarantine path validation")
