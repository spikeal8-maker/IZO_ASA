"""Normal admin model/settings checks inside an already admitted fresh fixture."""
from copy import deepcopy
import math

from tools.docker_shadow_product import ProductError

SETTINGS = "/api/admin/settings"
MODELS = "/api/admin/models-page?local=0"
CATALOG = "/api/admin/openrouter/catalog/status-v2"
KEY = "openrouter_economy"
DEFAULTS = {"minMarginPercent": 40, "tokenRub": 5}


def require(value, code):
    if not value:
        raise ProductError(code)


def economy(value):
    result = {key: value.get(key, default) for key, default in DEFAULTS.items()}
    require(all(type(item) in (int, float) and math.isfinite(item) for item in result.values())
            and 0 <= result["minMarginPercent"] <= 95 and .01 <= result["tokenRub"] <= 100000,
            "ADMIN_MODELS_ECONOMY_INVALID")
    return result


def saved(admin):
    settings = admin.request("GET", SETTINGS)
    require(isinstance(settings, dict), "ADMIN_MODELS_SETTINGS_INVALID")
    require(KEY not in settings or isinstance(settings[KEY], dict), "ADMIN_MODELS_SETTING_INVALID")
    return deepcopy(settings.get(KEY))


def model_page(admin):
    value = admin.request("GET", MODELS)
    cloud = value.get("openrouter", {})
    require(isinstance(value.get("catalog"), list) and bool(value["catalog"])
            and all(isinstance(item, dict) for item in value["catalog"])
            and isinstance(value.get("matrix"), list) and isinstance(value.get("economy"), dict)
            and cloud.get("keyConfigured") is False
            and cloud.get("catalogState", {}).get("source") == "fallback"
            and isinstance(cloud.get("capabilityCatalog"), list)
            and isinstance(cloud.get("backendPricing"), list)
            and isinstance(cloud.get("exchange"), dict) and cloud["exchange"].get("rate") is None
            and isinstance(cloud.get("economy"), dict), "ADMIN_MODELS_OFFLINE_PAGE_INVALID")
    return value


def prove_models(probe, row):
    require(getattr(probe, "fresh_fixture", False) is True and all(
        probe.checks.get(name, {}).get("status") == "PASS"
        for name in ("bootstrap", "simulatorSafety", "adminRights")), "ADMIN_MODELS_FRESH_ADMISSION_REQUIRED")
    admin = probe.admin
    clients = (probe.flow.owner, probe.flow.other)
    accounts = [probe.snapshot(client) for client in clients]
    original = saved(admin)
    baseline = deepcopy(DEFAULTS if original is None else original)
    before = economy(baseline)
    changed = {**baseline, "minMarginPercent": before["minMarginPercent"] + (
        1 if before["minMarginPercent"] < 94 else -1)}
    row.update(baselineCreatedInFreshFixture=original is None, settingRoundtrip="NOT_RUN",
               settingCleanup="NOT_RUN", accountInvariance="NOT_RUN", liveProvider="NOT_RUN")
    try:
        if original is None:
            admin.request("POST", SETTINGS + "/" + KEY, {"settings": baseline})
        require(saved(admin) == baseline, "ADMIN_MODELS_BASELINE_NOT_PERSISTED")
        first = model_page(admin)
        require(economy(first["openrouter"]["economy"]) == before, "ADMIN_MODELS_BASELINE_READ_MISMATCH")
        catalog = admin.request("GET", CATALOG)
        require(catalog.get("ok") is True and catalog.get("catalog", {}).get("source") == "fallback"
                and type(catalog["catalog"].get("modelCount")) is int
                and catalog["catalog"]["modelCount"] == len(first["openrouter"]["capabilityCatalog"]),
                "ADMIN_MODELS_CATALOG_INVALID")
        for client, status in ((clients[0], 403), (clients[1], 403), (probe.flow.guest, 401)):
            for path in (SETTINGS, MODELS, CATALOG):
                client.request("GET", path, expected=(status,))
            client.request("POST", SETTINGS + "/" + KEY, {"settings": changed}, expected=(status,))
        admin.request("POST", SETTINGS + "/" + KEY, {"settings": changed})
        require(saved(admin) == changed, "ADMIN_MODELS_SETTING_NOT_PERSISTED")
        observed = model_page(admin)
        require(economy(observed["openrouter"]["economy"]) == economy(changed),
                "ADMIN_MODELS_DERIVED_READ_STALE")
        row.update(settingRoundtrip="PASS", modelPage="PASS", catalogSource="fallback",
                   catalogModels=catalog["catalog"]["modelCount"], ordinaryUser=403, guest=401,
                   inferenceEconomics="NOT_VERIFIED", rateAvailable=False)
    finally:
        failed = False
        try:
            admin.request("POST", SETTINGS + "/" + KEY, {"settings": baseline})
            require(saved(admin) == baseline and economy(model_page(admin)["openrouter"]["economy"]) == before,
                    "ADMIN_MODELS_BASELINE_RESTORE_MISMATCH")
            row["settingCleanup"] = "PASS"
        except Exception:
            row["settingCleanup"], failed = "FAIL", True
        try:
            require([probe.snapshot(client) for client in clients] == accounts, "ADMIN_MODELS_ACCOUNT_CHANGED")
            row["accountInvariance"] = "PASS"
        except Exception:
            row["accountInvariance"], failed = "FAIL", True
        if failed:
            raise ProductError("ADMIN_MODELS_CLEANUP_FAILED") from None
