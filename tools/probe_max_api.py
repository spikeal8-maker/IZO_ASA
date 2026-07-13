"""Sanitized read-only MAX `/me` TLS/API readiness probe."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import load_local_env  # noqa: E402
from app.integrations.max_tls import build_max_http_verify, normalize_max_tls_trust_store  # noqa: E402


async def probe_max_api(
    *,
    base_url: str,
    token: str,
    trust_store: str,
    timeout_seconds: float = 15,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[int, str]:
    verify: Any = build_max_http_verify(trust_store)
    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=True,
        verify=verify,
        transport=transport,
    ) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/me",
            headers={"Authorization": token},
        )
    return response.status_code, response.http_version


def main() -> int:
    load_local_env(BACKEND)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("MAX_API_BASE_URL", "https://platform-api2.max.ru"))
    parser.add_argument("--trust-store", default=os.getenv("MAX_TLS_TRUST_STORE", "system"))
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()

    token = os.getenv("MAX_BOT_TOKEN", "").strip()
    if not token:
        print("MAX_API_PROBE_ERROR reason=token_not_configured")
        return 2
    trust_store = normalize_max_tls_trust_store(args.trust_store)
    host = urlparse(args.base_url).hostname or "invalid"
    try:
        status, http_version = asyncio.run(probe_max_api(
            base_url=args.base_url,
            token=token,
            trust_store=trust_store,
            timeout_seconds=args.timeout,
        ))
    except Exception as exc:
        print(f"MAX_API_PROBE_ERROR host={host} trustStore={trust_store} error={type(exc).__name__}")
        return 3
    print(f"MAX_API_PROBE_OK host={host} trustStore={trust_store} status={status} http={http_version}")
    return 0 if status == 200 else 4


if __name__ == "__main__":
    raise SystemExit(main())
