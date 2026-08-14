from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlsplit

import httpx


DEFAULT_TARGETS = (
    "https://openrouter.ai/",
    "https://api.telegram.org/",
)


def _safe_target(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("probe targets must be credential-free HTTPS URLs")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe external HTTPS through a local SOCKS5 proxy.")
    parser.add_argument("--proxy-url", required=True)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("targets", nargs="*", default=list(DEFAULT_TARGETS))
    args = parser.parse_args()

    proxy = urlsplit(args.proxy_url)
    if proxy.scheme not in {"socks5", "socks5h"} or proxy.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("proxy must be a loopback SOCKS5 URL")

    results: list[dict[str, object]] = []
    ok = True
    with httpx.Client(proxy=args.proxy_url, timeout=args.timeout, follow_redirects=True, trust_env=False) as client:
        for raw_target in args.targets:
            target = _safe_target(raw_target)
            hostname = urlsplit(target).hostname or ""
            try:
                response = client.get(target)
                reachable = response.status_code < 500
                results.append(
                    {
                        "host": hostname,
                        "reachable": reachable,
                        "status_code": response.status_code,
                    }
                )
                ok = ok and reachable
            except Exception as exc:  # provider/network error is returned without secrets
                results.append(
                    {
                        "host": hostname,
                        "reachable": False,
                        "error_type": type(exc).__name__,
                    }
                )
                ok = False

    print(json.dumps({"ok": ok, "targets": results}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
