"""Pure, fail-closed preflight for future server-owned provider registry routes.

This module makes no network calls, does not reserve funds, and never authorizes
retry of a provider command with accepted or unknown outcome. Admission and
settlement must be rechecked by the transactional runtime before any dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable


KIND_OPERATIONS = {
    "ollama": frozenset({"chat"}),
    "deepseek-direct": frozenset({"chat"}),
    "openrouter": frozenset({
        "chat", "text_to_image", "image_edit", "text_to_video",
        "image_to_video", "asr", "tts",
    }),
    "comfyui": frozenset({"text_to_image", "image_edit", "text_to_video", "image_to_video"}),
}
CLOUD_KINDS = frozenset({"openrouter", "deepseek-direct"})
HEALTH_MAX_AGE_SECONDS = 300
QUOTE_MAX_AGE_SECONDS = 300
MAX_CANDIDATES = 16


@dataclass(frozen=True)
class ModelCapability:
    model_id: str
    operations: frozenset[str]
    billing_mode: str  # "free" or "paid", verified by the backend catalog
    verified: bool


@dataclass(frozen=True)
class ProviderState:
    provider_id: str
    kind: str
    enabled: bool
    health: str
    checked_at: datetime | None
    models: tuple[ModelCapability, ...]


@dataclass(frozen=True)
class PriceQuote:
    provider_id: str
    model_id: str
    operation: str
    usd: Decimal
    verified_at: datetime
    source_verified: bool


@dataclass(frozen=True)
class RouteChoice:
    provider_id: str
    model_id: str


@dataclass(frozen=True)
class AccessContext:
    operation: str
    authorized_routes: frozenset[tuple[str, str, str]]
    paid_allowed: bool
    available_budget_usd: Decimal
    checked_at: datetime


@dataclass(frozen=True)
class RouteEvaluation:
    provider_id: str
    model_id: str
    eligible: bool
    reason: str


@dataclass(frozen=True)
class PreflightReport:
    operation: str
    evaluations: tuple[RouteEvaluation, ...]

    @property
    def candidates_for_further_admission(self) -> tuple[RouteChoice, ...]:
        """Candidates still require an atomic payment/dispatch admission."""
        return tuple(
            RouteChoice(item.provider_id, item.model_id)
            for item in self.evaluations if item.eligible
        )


def _fresh(stamp: datetime | None, now: datetime, seconds: int) -> bool:
    if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
        return False
    age = (now.astimezone(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= seconds


def _valid_amount(value: Decimal, *, allow_zero: bool) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and (value >= 0 if allow_zero else value > 0)


def preflight_routes(
    *,
    providers: Iterable[ProviderState],
    choices: Iterable[RouteChoice],
    quotes: Iterable[PriceQuote],
    access: AccessContext,
) -> PreflightReport:
    """Evaluate ordered candidates without I/O, mutation or retry permission.

    Inputs are trusted, server-owned snapshots; frontend/tenant payloads must
    never supply verified model capabilities, prices or entitlement proof.
    This report is NOT an authorization to send a second provider request.
    """
    if access.operation not in {op for group in KIND_OPERATIONS.values() for op in group}:
        raise ValueError("UNSUPPORTED_OPERATION")
    if (not isinstance(access.checked_at, datetime) or access.checked_at.utcoffset() is None
            or not _valid_amount(access.available_budget_usd, allow_zero=True)):
        raise ValueError("INVALID_TRUSTED_ACCESS_SNAPSHOT")
    choice_rows = tuple(choices)
    if len(choice_rows) > MAX_CANDIDATES:
        raise ValueError("TOO_MANY_ROUTE_CHOICES")
    provider_rows = tuple(providers)
    quote_rows = tuple(quotes)
    evaluations: list[RouteEvaluation] = []
    seen: set[tuple[str, str]] = set()
    for choice in choice_rows:
        route = (choice.provider_id, choice.model_id)
        authorization = (choice.provider_id, choice.model_id, access.operation)
        reason = "ELIGIBLE"
        if route in seen:
            reason = "DUPLICATE_ROUTE"
        elif authorization not in access.authorized_routes:
            reason = "TARIFF_FORBIDDEN"
        else:
            provider_matches = [row for row in provider_rows if row.provider_id == choice.provider_id]
            if len(provider_matches) != 1:
                reason = "PROVIDER_UNAVAILABLE"
            else:
                provider = provider_matches[0]
                catalog_matches = [m for m in provider.models if m.model_id == choice.model_id]
                if provider.enabled is not True:
                    reason = "PROVIDER_DISABLED"
                elif provider.kind not in KIND_OPERATIONS or access.operation not in KIND_OPERATIONS[provider.kind]:
                    reason = "PROVIDER_OPERATION_UNSUPPORTED"
                elif provider.health != "ready" or not _fresh(
                    provider.checked_at, access.checked_at, HEALTH_MAX_AGE_SECONDS
                ):
                    reason = "PROVIDER_HEALTH_UNVERIFIED"
                elif len(catalog_matches) != 1 or catalog_matches[0].verified is not True:
                    reason = "MODEL_UNVERIFIED"
                else:
                    model = catalog_matches[0]
                    if access.operation not in model.operations:
                        reason = "MODEL_OPERATION_UNSUPPORTED"
                    elif model.billing_mode == "free" and provider.kind not in CLOUD_KINDS:
                        reason = "ELIGIBLE"
                    elif model.billing_mode != "paid":
                        reason = "BILLING_MODE_UNVERIFIED"
                    elif access.paid_allowed is not True:
                        reason = "PAID_ACCESS_FORBIDDEN"
                    else:
                        matches = [q for q in quote_rows if (
                            q.provider_id, q.model_id, q.operation
                        ) == authorization]
                        if len(matches) != 1 or matches[0].source_verified is not True:
                            reason = "PRICE_UNVERIFIED"
                        else:
                            quote = matches[0]
                            if not _fresh(quote.verified_at, access.checked_at, QUOTE_MAX_AGE_SECONDS):
                                reason = "PRICE_STALE"
                            elif not _valid_amount(quote.usd, allow_zero=False):
                                reason = "PRICE_INVALID"
                            elif quote.usd > access.available_budget_usd:
                                reason = "BUDGET_EXCEEDED"
        seen.add(route)
        evaluations.append(RouteEvaluation(*route, reason == "ELIGIBLE", reason))
    return PreflightReport(access.operation, tuple(evaluations))
