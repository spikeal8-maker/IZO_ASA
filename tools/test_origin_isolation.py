from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vite_uses_one_exact_public_host_allowlist() -> None:
    source = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")

    assert "allowedHosts: true" not in source
    assert "const exactAllowedHosts = ['izo.alikinas.ru'] as const" in source
    assert source.count("allowedHosts: [...exactAllowedHosts]") == 2
    assert "['.alikinas.ru']" not in source


def test_all_repository_uvicorn_launchers_disable_implicit_proxy_rewrite() -> None:
    public_source = (ROOT / "start-public.bat").read_text(encoding="utf-8")
    assert "restart-backend.ps1" in public_source
    assert not [
        line for line in public_source.splitlines() if "uvicorn" in line and "main:app" in line
    ]

    direct_source = (ROOT / "tools" / "start-local-test-stack.ps1").read_text(
        encoding="utf-8"
    )
    direct_commands = [
        line for line in direct_source.splitlines() if "uvicorn" in line and "main:app" in line
    ]
    assert direct_commands
    start_block = direct_source[
        direct_source.index("$backendProcess = Start-Process") :
        direct_source.index("$health = Wait-HttpJson")
    ]
    assert "--no-proxy-headers" in start_block
    assert "--proxy-headers" not in start_block.replace("--no-proxy-headers", "")

    restart_source = (ROOT / "tools" / "restart-backend.ps1").read_text(encoding="utf-8")
    assert '"--no-proxy-headers")' in restart_source
    assert "RequireProxyIsolation" in restart_source
    assert 'TRUST_PROXY_HEADERS = "true"' in restart_source


def test_origin_probe_is_a_post_build_full_and_ci_gate() -> None:
    verifier = (ROOT / "tools" / "verify.ps1").read_text(encoding="utf-8")

    build_index = verifier.index('Invoke-NativeStep -Name "frontend_build"')
    probe_index = verifier.index('Invoke-NativeStep -Name "frontend_origin_isolation"')
    assert build_index < probe_index
    assert 'ArgumentList @("run", "check:origin")' in verifier


def test_origin_probe_contract_checks_allowed_blocked_and_loopback_hosts() -> None:
    source = (ROOT / "tools" / "check_frontend_origin_isolation.mjs").read_text(encoding="utf-8")

    assert "izo.alikinas.ru" in source
    assert "sub.izo.alikinas.ru" in source
    assert "evil.example" in source
    assert "127.0.0.1" in source
    assert "ORIGIN_ISOLATION_OK" in source
