from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.services import energy_telemetry


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE jobs (
          id TEXT PRIMARY KEY, provider TEXT, mode TEXT, status TEXT,
          settings_json TEXT, created_at TEXT, started_at TEXT, completed_at TEXT
        );
        CREATE TABLE power_samples (
          sampled_at TEXT PRIMARY KEY, server_estimated_watts REAL NOT NULL,
          ups_reference_watts REAL, overhead_watts REAL NOT NULL,
          gpu_3090_watts REAL NOT NULL DEFAULT 0, gpu_4070_watts REAL NOT NULL DEFAULT 0,
          cpu_percent REAL NOT NULL DEFAULT 0, active_local_jobs INTEGER NOT NULL DEFAULT 0,
          source TEXT NOT NULL DEFAULT 'ups_calibrated_gpu'
        );
        CREATE TABLE generation_energy_usage (
          job_id TEXT PRIMARY KEY, provider TEXT NOT NULL, mode TEXT NOT NULL, model TEXT NOT NULL,
          started_at TEXT NOT NULL, completed_at TEXT NOT NULL, duration_seconds REAL NOT NULL,
          sample_count INTEGER NOT NULL, average_watts REAL NOT NULL, peak_watts REAL NOT NULL,
          energy_wh REAL NOT NULL, incremental_wh REAL NOT NULL, measured_at TEXT NOT NULL
        );
        """
    )
    return conn


def test_normalize_energy_settings_is_safe():
    assert energy_telemetry.normalize_energy_settings({"rub_per_kwh": "7,5"}) == {"rub_per_kwh": 7.5}
    assert energy_telemetry.normalize_energy_settings({"rub_per_kwh": 8.32119}) == {"rub_per_kwh": 8.3212}
    assert energy_telemetry.normalize_energy_settings({"rub_per_kwh": -1}) == {"rub_per_kwh": 0.0}


def test_completed_local_job_gets_persistent_energy_summary():
    conn = _database()
    began = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)
    completed = began + timedelta(seconds=10)
    for index in range(6):
        sampled = began + timedelta(seconds=index * 2)
        conn.execute(
            "INSERT INTO power_samples VALUES (?,?,?,?,?,?,?,?,?)",
            (sampled.isoformat(), 350, 280, 120, 220 if index else 10, 12, 30, 1 if index else 0, "test"),
        )
    conn.execute(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
        ("job-1", "comfyui", "text_to_image", "completed", '{"modelProfile":"flux_klein_9b"}', began.isoformat(), began.isoformat(), completed.isoformat()),
    )

    assert energy_telemetry.reconcile_generation_energy(conn) == 1
    row = conn.execute("SELECT * FROM generation_energy_usage WHERE job_id='job-1'").fetchone()
    assert row is not None
    assert row["model"] == "flux_klein_9b"
    assert row["sample_count"] == 6
    assert row["peak_watts"] == 340
    assert row["energy_wh"] > 0
    assert energy_telemetry.reconcile_generation_energy(conn) == 0


def test_energy_report_uses_actual_ups_hours_for_cost(monkeypatch):
    conn = _database()
    now = datetime(2026, 8, 22, 10, 30, tzinfo=timezone.utc)
    conn.execute(
        "INSERT INTO power_samples VALUES (?,?,?,?,?,?,?,?,?)",
        (now.isoformat(), 180, 150, 150, 20, 10, 8, 0, "test"),
    )
    monkeypatch.setattr(energy_telemetry.powerpanel, "read_powerpanel_hourly_samples", lambda **_: [
        {"sampled_at": "2026-08-22T08:00:00+03:00", "average_watts": 100.0},
        {"sampled_at": "2026-08-22T09:00:00+03:00", "average_watts": 200.0},
    ])
    monkeypatch.setattr(energy_telemetry.powerpanel, "read_powerpanel_telemetry", lambda **_: {"model": "UT2200EG"})

    report = energy_telemetry.build_energy_report(conn, settings={"rub_per_kwh": 10}, now=now, period_days=1)

    assert report["totals"]["today_kwh"] == 0.3
    assert report["totals"]["today_cost_rub"] == 3.0
    assert report["measurement"]["model"] == "UT2200EG"
    assert report["current"]["server_estimated_watts"] == 180


def test_short_assistant_interval_gets_gpu_4070_energy_estimate():
    conn = _database()
    began = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    for index in range(3):
        conn.execute(
            "INSERT INTO power_samples VALUES (?,?,?,?,?,?,?,?,?)",
            ((began + timedelta(seconds=index * 2)).isoformat(), 300, 250, 180, 10, 80, 20, 0, "test"),
        )
    result = energy_telemetry.estimate_interval_energy(
        conn, started_at=began, completed_at=began + timedelta(seconds=4), gpu_index=1,
    )
    assert result["sample_count"] == 3
    assert result["energy_wh"] > 0
    assert result["incremental_wh"] == 0
