"""Policy gates for destructive or repairing startup storage maintenance."""

from __future__ import annotations

from collections.abc import Mapping


def startup_storage_maintenance_allowed(environment: Mapping[str, str]) -> bool:
    """Never let a pytest TestClient startup mutate the configured media tree."""
    if environment.get("PYTEST_CURRENT_TEST"):
        return False
    return environment.get("IZO_DISABLE_STARTUP_STORAGE_MAINTENANCE", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }
