"""Read-only historical backtest for cloud-quote-v1.

Usage: python tools/backtest_cloud_quotes.py PATH_TO_DATABASE
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.cloud_quote import build_cloud_quote, finalize_shadow_quote, summarize_shadow_quotes  # noqa: E402


def parsed(value: Any) -> dict[str, Any]:
    try:
        result = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return result if isinstance(result, dict) else {}


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in conn.execute(
        "SELECT mode,width,height,settings_json,created_at FROM images "
        "WHERE provider='openrouter' ORDER BY created_at"
    ):
        settings = parsed(row["settings_json"])
        billing = settings.get("openrouterBilling") if isinstance(settings.get("openrouterBilling"), dict) else {}
        result.append({
            "product": "image",
            "createdAt": row["created_at"],
            "shape": (
                settings.get("openrouterModel") or billing.get("modelId"), row["mode"],
                billing.get("billingWidth") or row["width"], billing.get("billingHeight") or row["height"],
                billing.get("inputImageCount") or 0,
            ),
            "billing": billing,
            "actual": number(billing.get("actualCostUsd")) or number(settings.get("openrouterCostUsd")),
        })
    for row in conn.execute(
        "SELECT mode,settings_json,created_at FROM jobs WHERE provider='openrouter' "
        "AND mode IN ('text_to_video','image_to_video','first_last_frame','reference_to_video') ORDER BY created_at"
    ):
        settings = parsed(row["settings_json"])
        billing = settings.get("openrouterBilling") if isinstance(settings.get("openrouterBilling"), dict) else {}
        result.append({
            "product": "video",
            "createdAt": row["created_at"],
            "shape": (
                settings.get("openrouterModel") or billing.get("modelId"), row["mode"], settings.get("duration"),
                settings.get("resolution"), settings.get("aspectRatio"), bool(settings.get("generateAudio")),
                billing.get("inputImageCount") or 0,
            ),
            "billing": billing,
            "actual": number(billing.get("actualCostUsd")) or number(settings.get("openrouterCostUsd")),
        })
    return sorted(result, key=lambda row: str(row.get("createdAt") or ""))


def backtest(items: list[dict[str, Any]]) -> dict[str, Any]:
    history: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    quotes: list[dict[str, Any]] = []
    token_deltas: list[float] = []
    actual_rows = 0
    for item in items:
        actual = item["actual"]
        if actual is not None:
            actual_rows += 1
        billing = item["billing"]
        official = number(billing.get("catalogEstimatedCostUsd")) or number(billing.get("estimatedCostUsd"))
        exchange = number(billing.get("exchangeRate"))
        token_rub = number(billing.get("tokenRub"))
        if official is None or exchange is None or token_rub is None or actual is None:
            if actual is not None:
                history[item["shape"]].insert(0, actual)
            continue
        fee = billing.get("usdFeePercent")
        if not isinstance(fee, (int, float)):
            effective = number(billing.get("effectiveUsdRub"))
            fee = ((effective / exchange) - 1) * 100 if effective is not None else 30
        quote = build_cloud_quote(
            official_cost_usd=official,
            comparable_actual_costs_usd=history[item["shape"]],
            provider_minimum_usd=number(billing.get("minimumCostUsd")),
            exchange_rate=exchange,
            funding_reserve_percent=float(fee),
            minimum_margin_percent=float(billing.get("minMarginPercent") or 40),
            token_rub=token_rub,
            minimum_tokens=1,
            observed_at=item["createdAt"],
        )
        finalized = finalize_shadow_quote(quote, actual)
        finalized["product"] = item["product"]
        quotes.append(finalized)
        legacy = number(billing.get("chargedTokens"))
        if legacy is not None:
            token_deltas.append(float(quote["reservedTokens"]) - legacy)
        history[item["shape"]].insert(0, actual)
    summary = summarize_shadow_quotes(quotes)
    summary.update({
        "historicalActualRows": actual_rows,
        "backtestedRows": len(quotes),
        "coveragePercent": round(len(quotes) / actual_rows * 100, 2) if actual_rows else 0,
        "averageTokenDelta": round(sum(token_deltas) / len(token_deltas), 4) if token_deltas else None,
        "maxTokenIncrease": round(max(token_deltas), 4) if token_deltas else None,
        "maxTokenDecrease": round(min(token_deltas), 4) if token_deltas else None,
        "byProduct": {
            product: summarize_shadow_quotes([row for row in quotes if row.get("product") == product])
            for product in ("image", "video")
        },
    })
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    uri = f"file:{args.database.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        print(json.dumps(backtest(records(conn)), ensure_ascii=False, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
