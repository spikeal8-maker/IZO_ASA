from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


TERM_MONTHS = (1, 3, 6, 12)
DEFAULT_TERM_DISCOUNTS = {1: 0, 3: 5, 6: 10, 12: 15}
TARIFF_PACKAGE_RE = re.compile(
    r"^tariff_(free|mini|plus|pro|business)(?:_(3|6|12)m)?$"
)


def add_calendar_months(value: datetime, months: int) -> datetime:
    if months < 0:
        raise ValueError("months must be non-negative")
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def package_code(plan: str, months: int) -> str:
    if months not in TERM_MONTHS:
        raise ValueError("unsupported tariff term")
    return f"tariff_{plan}" if months == 1 else f"tariff_{plan}_{months}m"


def parse_package_code(code: str) -> tuple[str, int] | None:
    match = TARIFF_PACKAGE_RE.fullmatch(str(code or "").strip().lower())
    if not match:
        return None
    return match.group(1), int(match.group(2) or 1)


def normalize_term_settings(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, Mapping) else {}
    raw_discounts = source.get("discount_percent")
    raw_discounts = raw_discounts if isinstance(raw_discounts, Mapping) else {}
    discounts: dict[str, int] = {}
    for months in TERM_MONTHS:
        value = raw_discounts.get(str(months), raw_discounts.get(months, DEFAULT_TERM_DISCOUNTS[months]))
        try:
            percent = int(value)
        except (TypeError, ValueError):
            percent = DEFAULT_TERM_DISCOUNTS[months]
        discounts[str(months)] = max(0, min(percent, 60))
    discounts["1"] = 0
    try:
        estimated_cost = float(source.get("estimated_token_cost_rub", 0) or 0)
    except (TypeError, ValueError):
        estimated_cost = 0.0
    return {
        "discount_percent": discounts,
        "estimated_token_cost_rub": round(max(0.0, min(estimated_cost, 1_000_000.0)), 4),
    }


@dataclass(frozen=True)
class TariffOffer:
    months: int
    monthly_price_rub: int
    discount_percent: int
    base_total_rub: int
    price_total_rub: int
    savings_rub: int
    included_tokens: int
    effective_token_price_rub: float | None
    estimated_cost_rub: float | None
    estimated_profit_rub: float | None
    estimated_margin_percent: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "months": self.months,
            "monthly_price_rub": self.monthly_price_rub,
            "discount_percent": self.discount_percent,
            "base_total_rub": self.base_total_rub,
            "price_total_rub": self.price_total_rub,
            "savings_rub": self.savings_rub,
            "included_tokens": self.included_tokens,
            "effective_token_price_rub": self.effective_token_price_rub,
            "estimated_cost_rub": self.estimated_cost_rub,
            "estimated_profit_rub": self.estimated_profit_rub,
            "estimated_margin_percent": self.estimated_margin_percent,
        }


def build_offer(
    *,
    monthly_price_rub: int,
    monthly_tokens: int,
    months: int,
    discount_percent: int,
    estimated_token_cost_rub: float = 0,
) -> TariffOffer:
    if months not in TERM_MONTHS:
        raise ValueError("unsupported tariff term")
    monthly_price = max(0, int(monthly_price_rub))
    tokens = max(0, int(monthly_tokens)) * months
    discount = max(0, min(int(discount_percent), 60))
    base_total = monthly_price * months
    total = max(0, int(round(base_total * (100 - discount) / 100)))
    savings = base_total - total
    effective = round(total / tokens, 4) if tokens else None
    estimated_cost = round(tokens * max(0.0, float(estimated_token_cost_rub)), 2) if estimated_token_cost_rub > 0 else None
    profit = round(total - estimated_cost, 2) if estimated_cost is not None else None
    margin = round(profit / total * 100, 2) if profit is not None and total > 0 else None
    return TariffOffer(
        months=months,
        monthly_price_rub=monthly_price,
        discount_percent=discount,
        base_total_rub=base_total,
        price_total_rub=total,
        savings_rub=savings,
        included_tokens=tokens,
        effective_token_price_rub=effective,
        estimated_cost_rub=estimated_cost,
        estimated_profit_rub=profit,
        estimated_margin_percent=margin,
    )


def prorated_monthly_tokens(monthly_tokens: int, days: int) -> int:
    if monthly_tokens <= 0 or days <= 0:
        return 0
    return max(1, (int(monthly_tokens) * int(days) + 29) // 30)
