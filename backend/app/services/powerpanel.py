"""Read-only CyberPower PowerPanel telemetry for the administrator dashboard."""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


MOSCOW = timezone(timedelta(hours=3), name="Europe/Moscow")
DEFAULT_DB_PATH = Path(
    r"C:\Program Files (x86)\CyberPower PowerPanel Personal\assets\PPPE_Db.db"
)


def configured_database_path() -> Path:
    raw = (os.getenv("POWERPANEL_DB_PATH") or "").strip()
    return Path(raw) if raw else DEFAULT_DB_PATH


def _parse_local(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MOSCOW)
    return parsed.astimezone(MOSCOW)


def _series(rows: list[tuple[datetime, float]], current: datetime) -> dict[str, list[dict[str, Any]]]:
    timeline: dict[str, list[dict[str, Any]]] = {}
    daily: dict[str, list[float]] = defaultdict(list)
    for created_at, watts in rows:
        daily[created_at.date().isoformat()].append(watts)
    timeline["power_watts"] = [
        {"date": day, "value": round(sum(values) / len(values), 1)}
        for day, values in sorted(daily.items())
    ]
    for suffix, hours in (("1h", 1), ("6h", 6), ("12h", 12), ("24h", 24)):
        start = current - timedelta(hours=hours)
        timeline[f"power_watts_{suffix}"] = [
            {"date": created_at.isoformat(), "value": round(watts, 1)}
            for created_at, watts in rows
            if created_at >= start
        ]
    return timeline


def read_powerpanel_telemetry(
    *,
    path: Path | None = None,
    now: datetime | None = None,
    days: int = 90,
) -> dict[str, Any]:
    """Return bounded PowerPanel history without modifying its database."""
    db_path = path or configured_database_path()
    current = (now or datetime.now(timezone.utc)).astimezone(MOSCOW)
    unavailable = {
        "available": False,
        "source": "CyberPower PowerPanel Personal",
        "model": None,
        "current_watts": None,
        "average_watts": None,
        "energy_kwh": None,
        "last_sample_at": None,
        "timeline": {},
    }
    if not db_path.is_file():
        return {**unavailable, "status": "database_not_found"}
    try:
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=1.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        start = (current - timedelta(days=max(1, min(180, days)))).replace(tzinfo=None).isoformat(sep=" ")
        raw_rows = conn.execute(
            "SELECT consumption,createTime FROM EnergyConsumption "
            "WHERE createTime>=? ORDER BY createTime",
            (start,),
        ).fetchall()
        model_row = conn.execute(
            "SELECT Model FROM DeviceLog WHERE Model IS NOT NULL AND Model!='' "
            "ORDER BY LocalTime DESC LIMIT 1"
        ).fetchone()
        conn.close()
    except (OSError, sqlite3.Error):
        return {**unavailable, "status": "read_error"}

    rows: list[tuple[datetime, float]] = []
    for row in raw_rows:
        created_at = _parse_local(row["createTime"])
        try:
            watts = float(row["consumption"])
        except (TypeError, ValueError):
            continue
        if created_at is None or not 0 <= watts <= 100_000:
            continue
        rows.append((created_at, watts))
    if not rows:
        return {**unavailable, "status": "no_samples", "model": model_row["Model"] if model_row else None}

    values = [watts for _, watts in rows]
    return {
        "available": True,
        "status": "ok",
        "source": "CyberPower PowerPanel Personal",
        "model": model_row["Model"] if model_row else None,
        "current_watts": round(values[-1], 1),
        "average_watts": round(sum(values) / len(values), 1),
        "energy_kwh": round(sum(values) / 1000.0, 3),
        "last_sample_at": rows[-1][0].isoformat(),
        "sample_count": len(rows),
        "timeline": _series(rows, current),
    }


def read_powerpanel_hourly_samples(
    *,
    path: Path | None = None,
    now: datetime | None = None,
    days: int = 90,
) -> list[dict[str, Any]]:
    """Return hourly whole-UPS power averages recorded by PowerPanel.

    PowerPanel writes one ``EnergyConsumption`` row per completed hour.  The
    numeric value is the average watts for that hour, so dividing the sum by
    1000 yields kWh for complete hourly rows.
    """
    db_path = path or configured_database_path()
    if not db_path.is_file():
        return []
    current = (now or datetime.now(timezone.utc)).astimezone(MOSCOW)
    start = (current - timedelta(days=max(1, min(180, days)))).replace(tzinfo=None).isoformat(sep=" ")
    try:
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=1.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        raw_rows = conn.execute(
            "SELECT consumption,createTime FROM EnergyConsumption "
            "WHERE createTime>=? ORDER BY createTime",
            (start,),
        ).fetchall()
        conn.close()
    except (OSError, sqlite3.Error):
        return []
    result: list[dict[str, Any]] = []
    for row in raw_rows:
        created_at = _parse_local(row["createTime"])
        try:
            watts = float(row["consumption"])
        except (TypeError, ValueError):
            continue
        if created_at is not None and 0 <= watts <= 100_000:
            result.append({"sampled_at": created_at.isoformat(), "average_watts": round(watts, 3)})
    return result
