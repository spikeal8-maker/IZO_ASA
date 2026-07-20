"""HTTP security middleware composition (AUTH-LEGACY-001B seam).

One installer owns the whole HTTP boundary so ``backend/main.py`` keeps a
single call instead of the individual ``add_middleware`` blocks.

Effective processing order (outermost first):

1. ``RequestBodyLimitMiddleware`` — an oversized body is rejected before any
   further processing.
2. ``TrustedHostMiddleware`` — the Host header is validated next.
3. ``CORSMiddleware`` — explicit allowlisted origins; a wildcard origin with
   credentials is rejected by browsers and unsafe, so the allowlist comes
   from ``HttpSecurityPolicy`` (env ``CORS_ALLOWED_ORIGINS`` or the known
   dev + tunnel origins). ``allow_credentials`` stays true for cookie auth.
4. ``CsrfOriginMiddleware`` — cookie-authenticated unsafe requests must
   present an exactly allowlisted Origin (see ``app.security.csrf``).
5. Application routes.

Starlette applies ``add_middleware`` outside-in (the LAST added middleware is
the outermost), so the installer adds them in reverse order. The order is
pinned by tests, not by assumption.
"""
from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware
from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware

try:
    from .csrf import CsrfOriginMiddleware
    from .http_requests import RequestBodyLimitMiddleware
except ImportError:  # Direct `python backend/main.py` execution.
    from app.security.csrf import CsrfOriginMiddleware
    from app.security.http_requests import RequestBodyLimitMiddleware


def install_http_security_middleware(
    app: Starlette,
    *,
    policy,
    request_body_max_bytes: int,
) -> None:
    """Install the full HTTP security boundary on ``app``.

    ``policy`` is an ``HttpSecurityPolicy`` (duck-typed to avoid an import
    cycle): it provides ``cors_allowed_origins``, ``trusted_hosts`` and the
    three sensitive cookie names.
    """
    app.add_middleware(
        CsrfOriginMiddleware,
        allowed_origins=list(policy.cors_allowed_origins),
        sensitive_cookie_names=[
            policy.session_cookie_name,
            policy.refresh_cookie_name,
            policy.bot_login_challenge_cookie_name,
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(policy.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(policy.trusted_hosts))
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=request_body_max_bytes)
