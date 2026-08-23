from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.services import powerpanel


def test_read_powerpanel_telemetry_is_bounded_and_read_only(tmp_path):
    db_path = tmp_path / "powerpanel.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE EnergyConsumption (id INTEGER PRIMARY KEY, consumption FLOAT, createTime DATETIME);"
        "CREATE TABLE DeviceLog (id INTEGER PRIMARY KEY, Model TEXT, LocalTime DATETIME);"
    )
    conn.execute("INSERT INTO DeviceLog (Model,LocalTime) VALUES ('UT2200EG','2026-08-22 12:00:00')")
    conn.execute("INSERT INTO EnergyConsumption (consumption,createTime) VALUES (350,'2026-08-22 11:00:04')")
    conn.execute("INSERT INTO EnergyConsumption (consumption,createTime) VALUES (410,'2026-08-22 12:00:04')")
    conn.commit()
    conn.close()

    payload = powerpanel.read_powerpanel_telemetry(
        path=db_path,
        now=datetime(2026, 8, 22, 10, 30, tzinfo=timezone.utc),
    )

    assert payload["available"] is True
    assert payload["model"] == "UT2200EG"
    assert payload["current_watts"] == 410
    assert payload["average_watts"] == 380
    assert payload["energy_kwh"] == 0.76
    assert len(payload["timeline"]["power_watts_6h"]) == 2
    assert sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM EnergyConsumption").fetchone()[0] == 2


def test_read_powerpanel_missing_database_is_explicit(tmp_path):
    payload = powerpanel.read_powerpanel_telemetry(path=tmp_path / "missing.db")
    assert payload["available"] is False
    assert payload["status"] == "database_not_found"


def test_read_powerpanel_hourly_samples_returns_bounded_chronological_rows(tmp_path):
    db_path = tmp_path / "powerpanel.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE EnergyConsumption (id INTEGER PRIMARY KEY, consumption FLOAT, createTime DATETIME)")
    conn.executemany(
        "INSERT INTO EnergyConsumption (consumption,createTime) VALUES (?,?)",
        [(200, "2026-08-20 08:00:00"), (320, "2026-08-22 11:00:00"), (410, "2026-08-22 12:00:00")],
    )
    conn.commit()
    conn.close()

    rows = powerpanel.read_powerpanel_hourly_samples(
        path=db_path,
        now=datetime(2026, 8, 22, 10, 30, tzinfo=timezone.utc),
        days=1,
    )

    assert [row["average_watts"] for row in rows] == [320.0, 410.0]
    assert rows[0]["sampled_at"] < rows[1]["sampled_at"]
