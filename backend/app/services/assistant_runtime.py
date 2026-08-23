"""Routing, residency and accounting helpers for AI assistant requests."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx

from ..integrations.ollama import (
    ensure_ollama_model_resident,
    fetch_ollama_residency_status,
    unload_ollama_model,
)
from . import energy_telemetry


class PromptRouteError(RuntimeError):
    def __init__(self, routing: dict[str, Any]) -> None:
        super().__init__("Сервис улучшения промпта временно недоступен. Повторите попытку или обратитесь в поддержку.")
        self.routing = routing


def routing_attempt(provider: str, started: datetime, error: Exception | None = None) -> dict[str, Any]:
    completed = datetime.now(timezone.utc)
    item: dict[str, Any] = {
        "provider": provider, "startedAt": started.isoformat(), "completedAt": completed.isoformat(),
        "latencyMs": round((completed - started).total_seconds() * 1000), "ok": error is None,
    }
    if error is not None:
        item["errorType"] = type(error).__name__
    return item


class OllamaResidencyController:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._resident_model: str | None = None
        self._config_loader: Callable[[], dict[str, Any]] | None = None

    async def ensure_model(self, config: dict[str, Any], *, unload_previous: bool = True) -> dict[str, Any]:
        model = str(config.get("localModel") or "gemma4:12b").strip()
        keep_alive_value = os.getenv("OLLAMA_KEEP_ALIVE", "-1").strip() or "-1"
        keep_alive: int | str = int(keep_alive_value) if keep_alive_value.lstrip("+-").isdigit() else keep_alive_value
        timeout = max(60, min(240, int(os.getenv("OLLAMA_WARMUP_TIMEOUT_SECONDS", "180"))))
        async with self._lock:
            previous = self._resident_model
            result = await ensure_ollama_model_resident(model=model, timeout_seconds=timeout, keep_alive=keep_alive)
            self._resident_model = model
            if unload_previous and previous and previous != model:
                try:
                    await unload_ollama_model(model=previous)
                except (httpx.HTTPError, RuntimeError):
                    pass
            return result

    async def sync(self, config: dict[str, Any]) -> dict[str, Any]:
        improve, voice = config["improve"], config["voice"]
        chat = config.get("chat") if isinstance(config.get("chat"), dict) else {}
        if chat and chat.get("enabled") is not False and chat.get("localEnabled") is not False:
            return await self.ensure_model({"localModel": chat.get("localModel")})
        if improve.get("route") in {"local", "auto"}:
            return await self.ensure_model(improve)
        if voice.get("route") in {"local", "auto"}:
            return await self.ensure_model({"localModel": voice.get("localModel")})
        async with self._lock:
            previous, self._resident_model = self._resident_model, None
            status = await fetch_ollama_residency_status()
            running = {str(row.get("name") or row.get("model") or "") for row in status.get("models") or []}
            candidates = {previous, str(chat.get("localModel") or ""), str(improve.get("localModel") or ""), str(voice.get("localModel") or "")}
            released = 0
            for model in sorted(name for name in candidates if name and name in running):
                await unload_ollama_model(model=model)
                released += 1
        return {"ok": True, "model": None, "released": released}

    def start(self, config_loader: Callable[[], dict[str, Any]]) -> None:
        self._config_loader = config_loader
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="ollama-residency")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        delay = 1.0
        while True:
            try:
                if self._config_loader is None:
                    return
                result = await self.sync(self._config_loader())
                delay = 30.0
                if result.get("model") and not result.get("alreadyResident"):
                    print(f"Ollama resident model ready: {result.get('model')} latencyMs={result.get('latencyMs')}")
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                print(f"Ollama residency check failed: {type(exc).__name__}")
                delay = min(300.0, max(30.0, delay * 2.0))
            await asyncio.sleep(delay)


async def route_prompt(
    *,
    request: Any,
    config: dict[str, Any],
    force_provider: str | None,
    ensure_local: Callable[[dict[str, Any]], Awaitable[Any]],
    call_local: Callable[[Any, dict[str, Any]], Awaitable[tuple[str, dict[str, Any]]]],
    call_api: Callable[[Any, dict[str, Any]], Awaitable[tuple[str, dict[str, Any]]]],
    api_default_model: str,
) -> tuple[str, dict[str, Any], str, str]:
    route = force_provider or str(config.get("route") or "local")
    providers = ["local", "api"] if route == "auto" else [route]
    routing: dict[str, Any] = {"requestedRoute": route, "attempts": [], "fallbackUsed": False}
    for index, provider in enumerate(providers):
        started = datetime.now(timezone.utc)
        try:
            if provider == "local":
                await ensure_local(config)
                improved, payload = await call_local(request, config)
                model = str(config.get("localModel") or "gemma4:12b")
            elif provider == "api":
                improved, payload = await call_api(request, config)
                model = str(config.get("apiModel") or api_default_model)
            else:
                raise RuntimeError("Неизвестный маршрут улучшения промпта.")
            routing["attempts"].append(routing_attempt(provider, started))
            routing["fallbackUsed"] = index > 0
            routed_payload = dict(payload) if isinstance(payload, dict) else {}
            routed_payload["_izoRouting"] = routing
            return improved, routed_payload, provider, model
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            routing["attempts"].append(routing_attempt(provider, started, exc))
            if route != "auto":
                raise PromptRouteError(routing) from exc
    routing["fallbackUsed"] = len(routing["attempts"]) > 1
    raise PromptRouteError(routing)


def money_snapshot(
    *, connect: Callable[[], Any], provider: str | None, provider_payload: dict[str, Any] | None,
    routing: dict[str, Any], openrouter_cost: Callable[[dict[str, Any]], float],
    usd_rub_snapshot: Callable[[], dict[str, Any]], usd_fee_rate: float,
    energy_settings: Any,
) -> dict[str, Any]:
    payload = provider_payload if isinstance(provider_payload, dict) else {}
    cost_usd = openrouter_cost(payload) if provider == "api" else 0.0
    base_rate = usd_rub_snapshot().get("rate")
    effective_rate = float(base_rate) * (1 + usd_fee_rate) if isinstance(base_rate, (int, float)) else None
    api_cost_rub = cost_usd * effective_rate if effective_rate is not None else None
    energy_wh = incremental_wh = 0.0
    samples = 0
    with connect() as conn:
        for attempt in routing.get("attempts") or []:
            if not isinstance(attempt, dict) or attempt.get("provider") != "local":
                continue
            try:
                started = datetime.fromisoformat(str(attempt.get("startedAt") or ""))
                completed = datetime.fromisoformat(str(attempt.get("completedAt") or ""))
            except ValueError:
                continue
            estimate = energy_telemetry.estimate_interval_energy(conn, started_at=started, completed_at=completed, gpu_index=1)
            samples += int(estimate.get("sample_count") or 0)
            energy_wh += float(estimate.get("energy_wh") or 0)
            incremental_wh += float(estimate.get("incremental_wh") or 0)
    tariff = energy_telemetry.normalize_energy_settings(energy_settings)["rub_per_kwh"]
    energy_cost_rub = energy_wh / 1000.0 * tariff
    total_rub = (api_cost_rub or 0.0) + energy_cost_rub if api_cost_rub is not None or energy_wh else None
    return {
        "cost_usd": round(cost_usd, 8), "api_cost_rub": round(api_cost_rub, 6) if api_cost_rub is not None else None,
        "effective_usd_rub": round(effective_rate, 6) if effective_rate is not None else None,
        "energy_wh": round(energy_wh, 6), "incremental_energy_wh": round(incremental_wh, 6),
        "energy_sample_count": samples, "energy_cost_rub": round(energy_cost_rub, 6),
        "electricity_rub_per_kwh": tariff, "total_cost_rub": round(total_rub, 6) if total_rub is not None else None,
    }


def usage_report(*, connect: Callable[[], Any], parse_json: Callable[[Any], Any], limit: int = 30) -> dict[str, Any]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    with connect() as conn:
        rows = conn.execute(
            "SELECT event_name,properties_json,created_at FROM event_logs WHERE event_name IN "
            "('prompt_improved','prompt_improve_failed') AND created_at>=? ORDER BY created_at DESC LIMIT 500", (cutoff,),
        ).fetchall()
    recent: list[dict[str, Any]] = []
    totals: dict[str, int | float] = {"successful": 0, "failed": 0, "fallbacks": 0, "cost_usd": 0.0, "cost_rub": 0.0, "energy_wh": 0.0, "energy_cost_rub": 0.0}
    for row in rows:
        properties = parse_json(row["properties_json"])
        properties = properties if isinstance(properties, dict) else {}
        routing = properties.get("routing") if isinstance(properties.get("routing"), dict) else {}
        ok = row["event_name"] == "prompt_improved"
        key = "successful" if ok else "failed"
        totals[key] = int(totals[key]) + 1
        totals["fallbacks"] = int(totals["fallbacks"]) + int(bool(properties.get("fallback_used") or routing.get("fallbackUsed")))
        for key, source in (("cost_usd", "cost_usd"), ("cost_rub", "total_cost_rub"), ("energy_wh", "energy_wh"), ("energy_cost_rub", "energy_cost_rub")):
            totals[key] = float(totals[key]) + float(properties.get(source) or 0)
        if len(recent) < max(1, min(100, limit)):
            recent.append({"createdAt": row["created_at"], "ok": ok, "route": properties.get("requested_route"), "provider": properties.get("provider"), "model": properties.get("model"), "mode": properties.get("mode"), "latencyMs": properties.get("latency_ms"), "fallbackUsed": bool(properties.get("fallback_used") or routing.get("fallbackUsed")), "costUsd": properties.get("cost_usd"), "costRub": properties.get("total_cost_rub"), "energyWh": properties.get("energy_wh"), "energyCostRub": properties.get("energy_cost_rub")})
    return {"periodDays": 30, "totals": {key: round(value, 6) if isinstance(value, float) else value for key, value in totals.items()}, "recent": recent}


OLLAMA_RESIDENCY = OllamaResidencyController()
