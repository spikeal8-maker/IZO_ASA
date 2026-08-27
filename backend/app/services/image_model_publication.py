"""Pure publication policy for the OpenRouter image-model catalog."""

from __future__ import annotations

from typing import Any, Callable, Iterable


def _valid_model_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    model_id = value.strip()
    return model_id if "/" in model_id and len(model_id) <= 160 else None


def normalize_config(
    config: dict[str, Any],
    *,
    modes: Iterable[str],
    tiers: Iterable[str],
    quality_presets: Iterable[str],
) -> dict[str, Any]:
    raw_enabled = config.get("enabled") if isinstance(config.get("enabled"), dict) else {}
    raw_defaults = config.get("defaults") if isinstance(config.get("defaults"), dict) else {}
    raw_access = config.get("access") if isinstance(config.get("access"), dict) else {}
    raw_quality = config.get("qualityDefaults") if isinstance(config.get("qualityDefaults"), dict) else {}
    raw_published = config.get("published")
    legacy_published = {
        model_id
        for values in raw_enabled.values()
        if isinstance(values, list)
        for value in values
        if (model_id := _valid_model_id(value))
    }
    published = sorted({
        model_id for value in raw_published if (model_id := _valid_model_id(value))
    }) if isinstance(raw_published, list) else sorted(legacy_published)
    published_set = set(published)
    enabled: dict[str, list[str]] = {}
    defaults: dict[str, str] = {}
    access: dict[str, dict[str, list[str]]] = {}
    quality_defaults: dict[str, dict[str, str]] = {}
    for mode in modes:
        values = raw_enabled.get(mode)
        if isinstance(values, list):
            clean = sorted({
                model_id
                for value in values
                if (model_id := _valid_model_id(value)) and model_id in published_set
            })
            if clean:
                enabled[mode] = clean
        default = _valid_model_id(raw_defaults.get(mode))
        if default in enabled.get(mode, []):
            defaults[mode] = default
        mode_access_raw = raw_access.get(mode) if isinstance(raw_access.get(mode), dict) else {}
        mode_access: dict[str, list[str]] = {}
        for tier in tiers:
            tier_values = mode_access_raw.get(tier)
            if tier == "mini" and not isinstance(tier_values, list):
                tier_values = mode_access_raw.get("basic")
            if isinstance(tier_values, list):
                clean_tier = sorted({
                    model_id
                    for value in tier_values
                    if (model_id := _valid_model_id(value)) and model_id in enabled.get(mode, [])
                })
                if clean_tier:
                    mode_access[tier] = clean_tier
        if mode_access:
            access[mode] = mode_access
        mode_quality_raw = raw_quality.get(mode) if isinstance(raw_quality.get(mode), dict) else {}
        mode_quality = {
            preset: model_id
            for preset in quality_presets
            if (model_id := _valid_model_id(mode_quality_raw.get(preset))) in enabled.get(mode, [])
        }
        if mode_quality:
            quality_defaults[mode] = mode_quality
    for mode, values in enabled.items():
        if mode not in defaults and values:
            defaults[mode] = values[0]
        if defaults.get(mode):
            quality_defaults.setdefault(mode, {})
            for preset in quality_presets:
                quality_defaults[mode].setdefault(preset, defaults[mode])
    return {
        "published": published,
        "enabled": enabled,
        "defaults": defaults,
        "access": access,
        "qualityDefaults": quality_defaults,
    }


def model_allowed(config: dict[str, Any], mode: str, tier: str, model_id: str) -> bool:
    published = config.get("published")
    if isinstance(published, list) and model_id not in published:
        return False
    enabled = config.get("enabled") if isinstance(config.get("enabled"), dict) else {}
    mode_enabled = enabled.get(mode)
    if isinstance(mode_enabled, list) and model_id not in mode_enabled:
        return False
    access = config.get("access") if isinstance(config.get("access"), dict) else {}
    mode_access = access.get(mode) if isinstance(access.get(mode), dict) else {}
    values = mode_access.get(tier) if isinstance(mode_access.get(tier), list) else []
    return model_id in values


def public_access_for_plan(
    plan: str,
    *,
    valid_plans: Iterable[str],
    tariff: dict[str, Any],
    config: dict[str, Any],
    capability_catalog: list[dict[str, Any]] | None,
    mode_labels: dict[str, str],
    quality_presets: Iterable[str],
    option_builder: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    quality_model: Callable[[dict[str, Any], str, str, str], str | None],
) -> dict[str, Any]:
    if plan not in valid_plans:
        plan = "mini"
    capabilities = {item.get("id"): item for item in (capability_catalog or []) if item.get("id")}
    enabled = config.get("enabled") if isinstance(config.get("enabled"), dict) else {}
    access = config.get("access") if isinstance(config.get("access"), dict) else {}
    published_raw = config.get("published")
    if isinstance(published_raw, list):
        published = {model_id for model_id in published_raw if isinstance(model_id, str)}
    else:
        published = {
            model_id
            for mode_access in access.values() if isinstance(mode_access, dict)
            for tier_ids in mode_access.values() if isinstance(tier_ids, list)
            for model_id in tier_ids if isinstance(model_id, str)
        }
        published.update(
            model_id
            for mode_ids in enabled.values() if isinstance(mode_ids, list)
            for model_id in mode_ids if isinstance(model_id, str)
        )
    modes: dict[str, Any] = {}
    for mode in sorted(mode_labels):
        ids = ["server:local_flux_klein"]
        published_ids = ["server:local_flux_klein"]
        mode_access = access.get(mode) if isinstance(access.get(mode), dict) else {}
        mode_enabled = enabled.get(mode) if isinstance(enabled.get(mode), list) else sorted({
            model_id
            for tier_ids in mode_access.values() if isinstance(tier_ids, list)
            for model_id in tier_ids if isinstance(model_id, str)
        })
        for model_id in mode_enabled:
            capability = capabilities.get(model_id)
            compatible = not capability_catalog or (capability is not None and mode in (capability.get("modes") or []))
            if model_id in published and model_id not in published_ids and compatible:
                published_ids.append(model_id)
        tier_ids = mode_access.get(plan) if isinstance(mode_access.get(plan), list) else []
        for model_id in tier_ids:
            if model_id in published_ids and model_id not in ids:
                ids.append(model_id)
        models = [option_builder(model_id, capabilities.get(model_id)) for model_id in ids]
        published_models = [option_builder(model_id, capabilities.get(model_id)) for model_id in published_ids]
        tariff_defaults = tariff.get("model_defaults") if isinstance(tariff.get("model_defaults"), dict) else {}
        presets: dict[str, str] = {}
        for preset in quality_presets:
            default_id = str(tariff_defaults.get(preset) or "server:local_flux_klein")
            if default_id == "server:local_flux_klein" or default_id in ids:
                presets[preset] = default_id
            else:
                fallback = quality_model(config, mode, preset, plan)
                presets[preset] = fallback if fallback in ids else "server:local_flux_klein"
        modes[mode] = {
            "id": mode,
            "label": mode_labels[mode],
            "models": models,
            "publishedModels": published_models,
            "presets": presets,
        }
    return {"plan": plan, "modes": modes}
