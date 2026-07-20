"""Shared TEST-ONLY helper (AUTH-LEGACY-001B).

Browsers always send an Origin header on unsafe methods, so cookie-auth
mutations in tests must present an allowlisted Origin to pass the CSRF
boundary. Tests that deliberately model a missing/foreign Origin must NOT
use this helper.
"""

BROWSER_ORIGIN_VALUE = "https://izo.alikinas.ru"
BROWSER_ORIGIN = {"Origin": BROWSER_ORIGIN_VALUE}
