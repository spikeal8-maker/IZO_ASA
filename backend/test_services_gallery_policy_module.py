from __future__ import annotations

import inspect

import app.services.gallery_policy as gallery_policy_module
from app.services.gallery_policy import (
    build_gallery_quota,
    gallery_eviction_target,
    normalize_gallery_plan,
)


PLAN_ORDER = ("free", "mini", "plus", "pro", "business")


def tariff(*, slots: int = 20) -> dict:
    return {
        "daily_tokens": 10,
        "openrouter_monthly_tokens": 30,
        "gallery_slots": slots,
        "video_enabled": 1,
        "video_slots": 4,
    }


def test_gallery_policy_has_no_framework_database_or_storage_dependencies() -> None:
    source = inspect.getsource(gallery_policy_module).lower()

    for forbidden in ("fastapi", "pydantic", "sqlite3", "httpx", "os.environ", "pathlib", "import main"):
        assert forbidden not in source


def test_plan_normalization_preserves_known_values_and_falls_back_to_mini() -> None:
    assert normalize_gallery_plan("PLUS", PLAN_ORDER) == "plus"
    assert normalize_gallery_plan(" free ", PLAN_ORDER) == "mini"
    assert normalize_gallery_plan(None, PLAN_ORDER) == "mini"
    assert normalize_gallery_plan("vip", PLAN_ORDER) == "mini"
    assert normalize_gallery_plan(123, PLAN_ORDER) == "mini"


def test_quota_payload_preserves_exact_legacy_fields_below_limit() -> None:
    assert build_gallery_quota(plan="free", tariff=tariff(slots=20), gallery_used=3) == {
        "plan": "free",
        "daily_tokens": 10,
        "openrouter_monthly_tokens": 30,
        "gallery_slots": 20,
        "video_enabled": True,
        "video_slots": 4,
        "gallery_used": 3,
        "gallery_free": 17,
        "gallery_full": False,
    }


def test_quota_at_exact_limit_is_full_and_targets_one_eviction() -> None:
    quota = build_gallery_quota(plan="mini", tariff=tariff(slots=20), gallery_used=20)

    assert quota["gallery_free"] == 0
    assert quota["gallery_full"] is True
    assert gallery_eviction_target(quota) == 1


def test_over_limit_quota_clamps_free_and_targets_two_evictions() -> None:
    quota = build_gallery_quota(plan="mini", tariff=tariff(slots=20), gallery_used=23)

    assert quota["gallery_free"] == 0
    assert quota["gallery_full"] is True
    assert gallery_eviction_target(quota) == 2


def test_zero_slot_quota_is_full_but_never_requests_eviction() -> None:
    quota = build_gallery_quota(plan="free", tariff=tariff(slots=0), gallery_used=0)

    assert quota["gallery_full"] is True
    assert gallery_eviction_target(quota) == 0


def test_eviction_target_accepts_legacy_string_values_and_safe_missing_defaults() -> None:
    assert gallery_eviction_target({"gallery_slots": "5", "gallery_used": "4"}) == 0
    assert gallery_eviction_target({"gallery_slots": "5", "gallery_used": "5"}) == 1
    assert gallery_eviction_target({"gallery_slots": "5", "gallery_used": "6"}) == 2
    assert gallery_eviction_target({}) == 0
