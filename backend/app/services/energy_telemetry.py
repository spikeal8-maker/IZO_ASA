"""High-frequency, low-overhead energy telemetry for local AI generations.

PowerPanel remains the source of truth for whole-UPS hourly energy.  This
module adds two-second GPU/CPU samples, calibrated against the latest UPS
hour, so short generation spikes and per-job estimates are visible without
writing to CyberPower's database.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import math
import os
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from . import powerpanel


SAMPLE_INTERVAL_SECONDS = 2.0
RAW_RETENTION_DAYS = 7
LOCAL_PROVIDERS = ("comfyui", "local_ltx")
ACTIVE_STATUSES = (
    "queued", "running", "uploading", "sent_to_comfyui", "submitting",
    "pending", "in_progress", "finalizing",
)


def normalize_energy_settings(value: Any) -> dict[str, float]:
    row = value if isinstance(value, dict) else {}
    try:
        rub_per_kwh = float(str(row.get("rub_per_kwh") or 0).replace(",", "."))
    except (TypeError, ValueError):
        rub_per_kwh = 0.0
    return {"rub_per_kwh": round(max(0.0, min(10_000.0, rub_per_kwh)), 4)}


class _NvmlReader:
    """Minimal NVML binding; avoids launching nvidia-smi every two seconds."""

    class _Utilization(ctypes.Structure):
        _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

    def __init__(self) -> None:
        self._lib: Any = None
        self._handles: list[Any] = []
        if os.name != "nt":
            return
        try:
            lib = ctypes.WinDLL("nvml.dll")
            lib.nvmlInit_v2.restype = ctypes.c_int
            lib.nvmlDeviceGetCount_v2.argtypes = [ctypes.POINTER(ctypes.c_uint)]
            lib.nvmlDeviceGetCount_v2.restype = ctypes.c_int
            lib.nvmlDeviceGetHandleByIndex_v2.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
            lib.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
            lib.nvmlDeviceGetPowerUsage.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
            lib.nvmlDeviceGetPowerUsage.restype = ctypes.c_int
            lib.nvmlDeviceGetUtilizationRates.argtypes = [ctypes.c_void_p, ctypes.POINTER(self._Utilization)]
            lib.nvmlDeviceGetUtilizationRates.restype = ctypes.c_int
            if lib.nvmlInit_v2() != 0:
                return
            count = ctypes.c_uint()
            if lib.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0:
                return
            handles: list[Any] = []
            for index in range(min(8, int(count.value))):
                handle = ctypes.c_void_p()
                if lib.nvmlDeviceGetHandleByIndex_v2(index, ctypes.byref(handle)) == 0:
                    handles.append(handle)
            self._lib = lib
            self._handles = handles
        except (AttributeError, OSError):
            self._lib = None
            self._handles = []

    def read(self) -> list[dict[str, float]]:
        if self._lib is None:
            return []
        result: list[dict[str, float]] = []
        for handle in self._handles:
            power = ctypes.c_uint()
            utilization = self._Utilization()
            watts = float(power.value) / 1000.0 if self._lib.nvmlDeviceGetPowerUsage(handle, ctypes.byref(power)) == 0 else 0.0
            gpu_percent = float(utilization.gpu) if self._lib.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(utilization)) == 0 else 0.0
            result.append({"watts": round(max(0.0, watts), 3), "utilization": gpu_percent})
        return result


class _CpuReader:
    def __init__(self) -> None:
        self._previous: tuple[int, int, int] | None = None

    @staticmethod
    def _value(file_time: Any) -> int:
        return (int(file_time.dwHighDateTime) << 32) | int(file_time.dwLowDateTime)

    def read(self) -> float:
        if os.name != "nt":
            return 0.0
        class FileTime(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]
        idle, kernel, user = FileTime(), FileTime(), FileTime()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return 0.0
        current = (self._value(idle), self._value(kernel), self._value(user))
        previous, self._previous = self._previous, current
        if previous is None:
            return 0.0
        idle_delta = current[0] - previous[0]
        total_delta = (current[1] - previous[1]) + (current[2] - previous[2])
        if total_delta <= 0:
            return 0.0
        return round(max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta))), 2)


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _active_local_job_count(conn: sqlite3.Connection) -> int:
    providers = ",".join("?" for _ in LOCAL_PROVIDERS)
    statuses = ",".join("?" for _ in ACTIVE_STATUSES)
    row = conn.execute(
        f"SELECT COUNT(*) FROM jobs WHERE provider IN ({providers}) AND status IN ({statuses})",
        (*LOCAL_PROVIDERS, *ACTIVE_STATUSES),
    ).fetchone()
    return int(row[0] or 0)


def _job_model(settings_json: Any, provider: str) -> str:
    try:
        settings = json.loads(settings_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        settings = {}
    return str(
        settings.get("modelProfile")
        or settings.get("openrouterModel")
        or settings.get("model")
        or settings.get("videoProfile")
        or provider
    )


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))]


def _integrate(rows: list[sqlite3.Row], value: Callable[[sqlite3.Row], float]) -> float:
    if not rows:
        return 0.0
    total_watt_seconds = 0.0
    for index, row in enumerate(rows):
        current = _parse_utc(row["sampled_at"])
        following = _parse_utc(rows[index + 1]["sampled_at"]) if index + 1 < len(rows) else None
        seconds = SAMPLE_INTERVAL_SECONDS if current is None or following is None else (following - current).total_seconds()
        seconds = max(0.25, min(SAMPLE_INTERVAL_SECONDS * 2.5, seconds))
        total_watt_seconds += max(0.0, value(row)) * seconds
    return total_watt_seconds / 3600.0


def reconcile_generation_energy(conn: sqlite3.Connection, *, limit: int = 40) -> int:
    earliest = conn.execute("SELECT MIN(sampled_at) FROM power_samples").fetchone()[0]
    if not earliest:
        return 0
    providers = ",".join("?" for _ in LOCAL_PROVIDERS)
    jobs = conn.execute(
        f"SELECT id,provider,mode,settings_json,COALESCE(started_at,created_at) AS began,completed_at "
        f"FROM jobs WHERE provider IN ({providers}) AND status='completed' AND completed_at IS NOT NULL "
        "AND completed_at>=? AND id NOT IN (SELECT job_id FROM generation_energy_usage) "
        "ORDER BY completed_at LIMIT ?",
        (*LOCAL_PROVIDERS, earliest, max(1, min(200, limit))),
    ).fetchall()
    idle_rows = conn.execute(
        "SELECT gpu_3090_watts,gpu_4070_watts FROM power_samples "
        "WHERE active_local_jobs=0 ORDER BY sampled_at DESC LIMIT 2000"
    ).fetchall()
    idle_3090 = _percentile([float(row[0] or 0) for row in idle_rows], 0.2)
    idle_4070 = _percentile([float(row[1] or 0) for row in idle_rows], 0.2)
    measured_at = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for job in jobs:
        started = _parse_utc(job["began"])
        completed = _parse_utc(job["completed_at"])
        if started is None or completed is None or completed <= started:
            continue
        rows = conn.execute(
            "SELECT * FROM power_samples WHERE sampled_at>=? AND sampled_at<=? ORDER BY sampled_at",
            (started.isoformat(), completed.isoformat()),
        ).fetchall()
        duration = (completed - started).total_seconds()
        minimum_samples = max(2, math.floor(duration / SAMPLE_INTERVAL_SECONDS * 0.35))
        if len(rows) < minimum_samples:
            continue
        gpu_key = "gpu_4070_watts" if job["provider"] == "local_ltx" else "gpu_3090_watts"
        idle_gpu = idle_4070 if gpu_key == "gpu_4070_watts" else idle_3090
        def attributed(row: sqlite3.Row) -> float:
            shared = float(row["overhead_watts"] or 0) / max(1, int(row["active_local_jobs"] or 1))
            return float(row[gpu_key] or 0) + shared
        energy_wh = _integrate(rows, attributed)
        incremental_wh = _integrate(rows, lambda row: max(0.0, float(row[gpu_key] or 0) - idle_gpu))
        watts = [attributed(row) for row in rows]
        conn.execute(
            "INSERT OR IGNORE INTO generation_energy_usage "
            "(job_id,provider,mode,model,started_at,completed_at,duration_seconds,sample_count,average_watts,peak_watts,energy_wh,incremental_wh,measured_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job["id"], job["provider"], job["mode"], _job_model(job["settings_json"], job["provider"]),
             started.isoformat(), completed.isoformat(), round(duration, 3), len(rows),
             round(sum(watts) / len(watts), 3), round(max(watts), 3), round(energy_wh, 6),
             round(incremental_wh, 6), measured_at),
        )
        inserted += int(conn.execute("SELECT changes()").fetchone()[0] or 0)
    return inserted


class PowerTelemetryWorker:
    def __init__(self, *, interval_seconds: float = SAMPLE_INTERVAL_SECONDS) -> None:
        self.interval_seconds = max(1.0, min(10.0, float(interval_seconds)))
        self._task: asyncio.Task[None] | None = None
        self._connect: Callable[[], Any] | None = None
        self._nvml = _NvmlReader()
        self._cpu = _CpuReader()
        self._overhead_watts: float | None = None
        self._ups_reference_watts: float | None = None
        self._ups_reference_at: str | None = None
        self._cycles = 0

    def start(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="power-telemetry")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _refresh_ups_reference(self) -> None:
        samples = powerpanel.read_powerpanel_hourly_samples(days=2)
        if samples:
            latest = samples[-1]
            self._ups_reference_watts = float(latest["average_watts"])
            self._ups_reference_at = str(latest["sampled_at"])

    def _sample(self) -> None:
        if self._connect is None:
            return
        if self._cycles % 30 == 0 or self._ups_reference_watts is None:
            self._refresh_ups_reference()
        gpu = self._nvml.read()
        gpu_3090 = float(gpu[0]["watts"]) if len(gpu) > 0 else 0.0
        gpu_4070 = float(gpu[1]["watts"]) if len(gpu) > 1 else 0.0
        gpu_total = gpu_3090 + gpu_4070
        with self._connect() as conn:
            active_jobs = _active_local_job_count(conn)
            target_overhead = max(30.0, float(self._ups_reference_watts or gpu_total + 120.0) - gpu_total)
            if self._overhead_watts is None:
                self._overhead_watts = target_overhead
            elif active_jobs == 0:
                self._overhead_watts = self._overhead_watts * 0.98 + target_overhead * 0.02
            server_watts = max(gpu_total, float(self._overhead_watts) + gpu_total)
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO power_samples "
                "(sampled_at,server_estimated_watts,ups_reference_watts,overhead_watts,gpu_3090_watts,gpu_4070_watts,cpu_percent,active_local_jobs,source) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (now, round(server_watts, 3), self._ups_reference_watts, round(self._overhead_watts, 3),
                 round(gpu_3090, 3), round(gpu_4070, 3), self._cpu.read(), active_jobs, "ups_calibrated_gpu"),
            )
            if self._cycles % 15 == 0:
                reconcile_generation_energy(conn)
            if self._cycles % 1800 == 0:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=RAW_RETENTION_DAYS)).isoformat()
                conn.execute("DELETE FROM power_samples WHERE sampled_at<?", (cutoff,))
        self._cycles += 1

    async def _run(self) -> None:
        while True:
            started = asyncio.get_running_loop().time()
            try:
                await asyncio.to_thread(self._sample)
            except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
                print(f"power telemetry sample skipped: {type(exc).__name__}")
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.1, self.interval_seconds - elapsed))


def _energy_kwh(rows: list[dict[str, Any]]) -> float:
    return sum(float(row.get("average_watts") or 0) for row in rows) / 1000.0


def build_energy_report(
    conn: sqlite3.Connection,
    *,
    settings: Any,
    now: datetime | None = None,
    realtime_minutes: int = 15,
    period_days: int = 30,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    normalized = normalize_energy_settings(settings)
    rub_per_kwh = normalized["rub_per_kwh"]
    realtime_minutes = max(5, min(60, int(realtime_minutes)))
    period_days = max(1, min(90, int(period_days)))
    cutoff = (current - timedelta(minutes=realtime_minutes)).isoformat()
    realtime_rows = conn.execute(
        "SELECT * FROM power_samples WHERE sampled_at>=? ORDER BY sampled_at",
        (cutoff,),
    ).fetchall()
    realtime = [dict(row) for row in realtime_rows]
    hourly = powerpanel.read_powerpanel_hourly_samples(now=current, days=90)
    local_now = current.astimezone(powerpanel.MOSCOW)
    today = local_now.date().isoformat()
    month = today[:7]
    period_start = (local_now - timedelta(days=period_days)).date().isoformat()
    today_rows = [row for row in hourly if str(row["sampled_at"])[:10] == today]
    month_rows = [row for row in hourly if str(row["sampled_at"])[:7] == month]
    period_rows = [row for row in hourly if str(row["sampled_at"])[:10] >= period_start]
    generation_rows = conn.execute(
        "SELECT * FROM generation_energy_usage ORDER BY completed_at DESC LIMIT 50"
    ).fetchall()
    generation_items = []
    for row in generation_rows:
        item = dict(row)
        item["cost_rub"] = round(float(item["energy_wh"] or 0) / 1000.0 * rub_per_kwh, 6)
        generation_items.append(item)
    today_start_utc = datetime.combine(local_now.date(), datetime.min.time(), tzinfo=powerpanel.MOSCOW).astimezone(timezone.utc).isoformat()
    measured = conn.execute(
        "SELECT "
        "COALESCE(SUM(CASE WHEN active_local_jobs=0 THEN server_estimated_watts ELSE 0 END),0),"
        "COALESCE(SUM(CASE WHEN active_local_jobs>0 THEN server_estimated_watts ELSE 0 END),0),"
        "COUNT(*) FROM power_samples WHERE sampled_at>=?",
        (today_start_utc,),
    ).fetchone()
    idle_kwh = float(measured[0] or 0) * SAMPLE_INTERVAL_SECONDS / 3_600_000.0
    generation_kwh = float(measured[1] or 0) * SAMPLE_INTERVAL_SECONDS / 3_600_000.0
    daily: dict[str, list[float]] = {}
    for row in hourly:
        daily.setdefault(str(row["sampled_at"])[:10], []).append(float(row["average_watts"] or 0))
    daily_timeline = [
        {"date": day, "energy_kwh": round(sum(values) / 1000.0, 4), "cost_rub": round(sum(values) / 1000.0 * rub_per_kwh, 4)}
        for day, values in sorted(daily.items())
    ]
    last = realtime[-1] if realtime else None
    telemetry = powerpanel.read_powerpanel_telemetry(now=current, days=90)
    return {
        "ok": True,
        "settings": normalized,
        "measurement": {
            "realtime_interval_seconds": SAMPLE_INTERVAL_SECONDS,
            "realtime_source": "NVML + калибровка по ИБП",
            "realtime_is_estimate": True,
            "billing_source": "CyberPower PowerPanel Personal",
            "billing_resolution": "1 час",
            "model": telemetry.get("model"),
            "collector_started_at": conn.execute("SELECT MIN(sampled_at) FROM power_samples").fetchone()[0],
        },
        "current": last,
        "realtime": realtime,
        "actual_hourly": hourly[-24 * period_days:],
        "daily": daily_timeline[-period_days:],
        "totals": {
            "today_kwh": round(_energy_kwh(today_rows), 4),
            "today_cost_rub": round(_energy_kwh(today_rows) * rub_per_kwh, 4),
            "month_kwh": round(_energy_kwh(month_rows), 4),
            "month_cost_rub": round(_energy_kwh(month_rows) * rub_per_kwh, 4),
            "period_days": period_days,
            "period_kwh": round(_energy_kwh(period_rows), 4),
            "period_cost_rub": round(_energy_kwh(period_rows) * rub_per_kwh, 4),
            "idle_today_estimated_kwh": round(idle_kwh, 5),
            "generation_today_estimated_kwh": round(generation_kwh, 5),
            "measured_samples_today": int(measured[2] or 0),
        },
        "generations": generation_items,
    }


POWER_TELEMETRY_WORKER = PowerTelemetryWorker()
