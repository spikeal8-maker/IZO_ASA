"""Offline adversarial characterization of the route eligibility contract.

No backend main import, provider I/O, payments, network, secrets or SQLite.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path


SOURCE = Path(__file__).resolve().parent / "app/services/provider_route_preflight.py"
spec = importlib.util.spec_from_file_location("provider_route_preflight_contract", SOURCE)
assert spec is not None and spec.loader is not None
contract = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = contract
spec.loader.exec_module(contract)

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


class RoutePreflightTests(unittest.TestCase):
    def model(self, model_id="ornith:9b", operations=("chat",), mode="free", verified=True):
        return contract.ModelCapability(model_id, frozenset(operations), mode, verified)

    def provider(self, *, id="local", kind="ollama", enabled=True, health="ready",
                 checked_at=NOW, models=None):
        if models is None:
            models = (self.model(),)
        return contract.ProviderState(id, kind, enabled, health, checked_at, tuple(models))

    def choice(self, provider_id="local", model_id="ornith:9b"):
        return contract.RouteChoice(provider_id, model_id)

    def access(self, *, operation="chat", permitted=None, paid_allowed=False,
               budget="0", checked_at=NOW):
        if permitted is None:
            permitted = {("local", "ornith:9b", "chat")}
        return contract.AccessContext(operation, frozenset(permitted),
                                      paid_allowed, Decimal(budget), checked_at)

    def quote(self, *, id="openrouter", model="provider/verified",
              operation="chat", usd="0.04", verified_at=NOW, source_verified=True):
        return contract.PriceQuote(id, model, operation, Decimal(usd),
                                   verified_at, source_verified)

    def run_gate(self, *, providers=None, choices=None, quotes=(), access=None):
        return contract.preflight_routes(
            providers=(self.provider(),) if providers is None else providers,
            choices=(self.choice(),) if choices is None else choices,
            quotes=quotes, access=self.access() if access is None else access,
        )

    def assert_reason(self, expected, **kwargs):
        result = self.run_gate(**kwargs)
        self.assertEqual(result.evaluations[0].reason, expected)
        self.assertEqual(len(result.candidates_for_further_admission),
                         int(expected == "ELIGIBLE"))
        return result

    def test_verified_local_and_ordered_route(self):
        report = self.assert_reason("ELIGIBLE")
        self.assertEqual(report.candidates_for_further_admission, (self.choice(),))
        self.assertEqual(report.operation, "chat")

    def test_preference_order_filters_disallowed_without_reordering(self):
        choices = (self.choice("ghost", "missing"), self.choice(),
                   self.choice("cloud", "provider/verified"))
        cloud = self.provider(id="cloud", kind="openrouter",
                              models=(self.model("provider/verified", mode="paid"),))
        access = self.access(permitted={
            ("local", "ornith:9b", "chat"),
            ("cloud", "provider/verified", "chat"),
        }, paid_allowed=True, budget="0.10")
        quote = self.quote(id="cloud")
        report = self.run_gate(providers=(cloud, self.provider()), choices=choices,
                               quotes=(quote,), access=access)
        self.assertEqual([r.reason for r in report.evaluations],
                         ["TARIFF_FORBIDDEN", "ELIGIBLE", "ELIGIBLE"])
        self.assertEqual(report.candidates_for_further_admission,
                         (self.choice(), self.choice("cloud", "provider/verified")))

    def test_denies_untrusted_or_absent_entitlement(self):
        self.assert_reason("TARIFF_FORBIDDEN", access=self.access(permitted=set()))

    def test_disabled_and_unavailable_and_stale_health(self):
        for provider, expected in (
            (self.provider(enabled=False), "PROVIDER_DISABLED"),
            (self.provider(health="unknown"), "PROVIDER_HEALTH_UNVERIFIED"),
            (self.provider(checked_at=NOW - timedelta(seconds=301)), "PROVIDER_HEALTH_UNVERIFIED"),
            (self.provider(checked_at=NOW + timedelta(seconds=1)), "PROVIDER_HEALTH_UNVERIFIED"),
            (self.provider(checked_at=datetime(2026, 10, 22)), "PROVIDER_HEALTH_UNVERIFIED"),
        ):
            with self.subTest(provider=provider):
                self.assert_reason(expected, providers=(provider,))

    def test_duplicate_unknown_and_missing_models_fail_closed(self):
        self.assert_reason("PROVIDER_UNAVAILABLE", providers=())
        self.assert_reason("PROVIDER_UNAVAILABLE", providers=(self.provider(), self.provider()))
        self.assert_reason("MODEL_UNVERIFIED", providers=(self.provider(models=()),))
        self.assert_reason("MODEL_UNVERIFIED", providers=(self.provider(models=(
            self.model(), self.model(),
        )),))
        self.assert_reason("MODEL_UNVERIFIED", providers=(self.provider(models=(
            self.model(verified=False),
        )),))

    def test_modality_and_provider_kind_must_both_match(self):
        self.assert_reason("MODEL_OPERATION_UNSUPPORTED", providers=(self.provider(
            models=(self.model(operations=("asr",)),),
        ),))
        self.assert_reason("PROVIDER_OPERATION_UNSUPPORTED", providers=(self.provider(
            kind="deepseek-direct",
        ),), access=self.access(operation="text_to_video", permitted={
            ("local", "ornith:9b", "text_to_video"),
        }))
        self.assert_reason("PROVIDER_OPERATION_UNSUPPORTED", providers=(self.provider(
            kind="mystery",
        ),))

    def test_paid_cloud_requires_real_entitlement_quote_and_budget(self):
        cloud = self.provider(id="openrouter", kind="openrouter",
                              models=(self.model("provider/verified", mode="paid"),))
        choice = self.choice("openrouter", "provider/verified")
        access = self.access(permitted={("openrouter", "provider/verified", "chat")},
                             paid_allowed=True, budget="0.05")
        self.assert_reason("ELIGIBLE", providers=(cloud,), choices=(choice,),
                           quotes=(self.quote(),), access=access)
        self.assert_reason("PAID_ACCESS_FORBIDDEN", providers=(cloud,), choices=(choice,),
                           quotes=(self.quote(),), access=self.access(
                               permitted={("openrouter", "provider/verified", "chat")},
                               paid_allowed=False, budget="0.05"))
        self.assert_reason("PRICE_UNVERIFIED", providers=(cloud,), choices=(choice,),
                           access=access)
        self.assert_reason("PRICE_UNVERIFIED", providers=(cloud,), choices=(choice,),
                           quotes=(self.quote(source_verified=False),), access=access)
        self.assert_reason("PRICE_UNVERIFIED", providers=(cloud,), choices=(choice,),
                           quotes=(self.quote(), self.quote()), access=access)
        self.assert_reason("BUDGET_EXCEEDED", providers=(cloud,), choices=(choice,),
                           quotes=(self.quote(),), access=self.access(
                               permitted={("openrouter", "provider/verified", "chat")},
                               paid_allowed=True, budget="0.039"))

    def test_price_bad_stale_future_zero_negative_and_nan(self):
        cloud = self.provider(id="openrouter", kind="openrouter",
                              models=(self.model("provider/verified", mode="paid"),))
        args = {"providers": (cloud,), "choices": (self.choice("openrouter", "provider/verified"),),
                "access": self.access(permitted={("openrouter", "provider/verified", "chat")},
                                      paid_allowed=True, budget="1")}
        for quote, expected in (
            (self.quote(usd="0"), "PRICE_INVALID"),
            (self.quote(usd="-1"), "PRICE_INVALID"),
            (self.quote(usd="NaN"), "PRICE_INVALID"),
            (self.quote(usd="Infinity"), "PRICE_INVALID"),
            (self.quote(verified_at=NOW - timedelta(seconds=301)), "PRICE_STALE"),
            (self.quote(verified_at=NOW + timedelta(seconds=1)), "PRICE_STALE"),
        ):
            with self.subTest(price=quote):
                self.assert_reason(expected, quotes=(quote,), **args)

    def test_cloud_models_cannot_silently_turn_free(self):
        for kind in ("openrouter", "deepseek-direct"):
            with self.subTest(kind=kind):
                cloud = self.provider(id="cloud", kind=kind,
                                      models=(self.model("provider/free", mode="free"),))
                self.assert_reason("BILLING_MODE_UNVERIFIED", providers=(cloud,),
                                   choices=(self.choice("cloud", "provider/free"),),
                                   access=self.access(permitted={
                                       ("cloud", "provider/free", "chat"),
                                   }))
        self.assert_reason("BILLING_MODE_UNVERIFIED", providers=(self.provider(
            models=(self.model(mode="unknown"),),
        ),))

    def test_duplicate_candidates_are_not_executed_twice(self):
        report = self.run_gate(choices=(self.choice(), self.choice()))
        self.assertEqual([r.reason for r in report.evaluations],
                         ["ELIGIBLE", "DUPLICATE_ROUTE"])
        self.assertEqual(len(report.candidates_for_further_admission), 1)

    def test_image_and_video_routes_need_exact_operations(self):
        for kind, operation, mode, quote_needed in (
            ("openrouter", "text_to_image", "paid", True),
            ("comfyui", "text_to_video", "free", False),
        ):
            with self.subTest(kind=kind, operation=operation):
                provider = self.provider(id="gpu", kind=kind, models=(
                    self.model("gpu/verified", operations=(operation,), mode=mode),
                ))
                access = self.access(operation=operation, permitted={
                    ("gpu", "gpu/verified", operation),
                }, paid_allowed=True, budget="2")
                quotes = (self.quote(id="gpu", model="gpu/verified",
                                     operation=operation),) if quote_needed else ()
                self.assert_reason("ELIGIBLE", providers=(provider,),
                                   choices=(self.choice("gpu", "gpu/verified"),),
                                   quotes=quotes, access=access)
                wrong = "image_edit" if operation == "text_to_video" else "text_to_video"
                self.assert_reason("MODEL_OPERATION_UNSUPPORTED", providers=(provider,),
                                   choices=(self.choice("gpu", "gpu/verified"),),
                                   quotes=quotes, access=self.access(operation=wrong, permitted={
                                       ("gpu", "gpu/verified", wrong),
                                   }, paid_allowed=True, budget="2"))

    def test_wrong_price_quote_cannot_approve_a_different_operation(self):
        cloud = self.provider(id="openrouter", kind="openrouter",
                              models=(self.model("provider/verified", mode="paid"),))
        args = {"providers": (cloud,),
                "choices": (self.choice("openrouter", "provider/verified"),),
                "access": self.access(permitted={
                    ("openrouter", "provider/verified", "chat"),
                }, paid_allowed=True, budget="1")}
        for quote in (self.quote(operation="asr"),
                      self.quote(model="provider/different"),
                      self.quote(id="deepseek-direct")):
            with self.subTest(quote=quote):
                self.assert_reason("PRICE_UNVERIFIED", quotes=(quote,), **args)

    def test_invalid_access_snapshot_and_operation_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_OPERATION"):
            self.run_gate(access=self.access(operation="file_delete"))
        for value in ("-1", "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "INVALID_TRUSTED_ACCESS_SNAPSHOT"):
                self.run_gate(access=self.access(budget=value))
        with self.assertRaisesRegex(ValueError, "INVALID_TRUSTED_ACCESS_SNAPSHOT"):
            self.run_gate(access=self.access(checked_at=datetime(2026, 10, 22)))

    def test_hard_cap_on_number_of_candidates(self):
        with self.assertRaisesRegex(ValueError, "TOO_MANY_ROUTE_CHOICES"):
            self.run_gate(choices=(self.choice(),) * 17)

    def test_pure_result_is_immutable_and_does_not_grant_send(self):
        report = self.run_gate()
        with self.assertRaises(FrozenInstanceError):
            report.evaluations[0].eligible = False
        with self.assertRaises(AttributeError):
            report.evaluations.append(self.choice())
        self.assertFalse(hasattr(report, "dispatch"))
        self.assertFalse(hasattr(report, "authorize_retry"))


if __name__ == "__main__":
    unittest.main()
