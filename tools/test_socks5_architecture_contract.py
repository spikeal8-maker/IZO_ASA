from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_backend_runtime_has_socks_transport_dependency() -> None:
    requirements = (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")

    assert "httpx==0.28.1" in requirements
    assert "socksio==1.0.0" in requirements


def test_socks5_switch_is_loopback_only_and_rollback_protected() -> None:
    script = (ROOT / "ops" / "network" / "configure_socks5_egress.ps1").read_text(
        encoding="utf-8"
    )

    assert 'socks5://127.0.0.1:$ProxyPort' in script
    assert "127.0.0.1,localhost,::1" in script
    assert "AdGuardVpnSvc" in script
    assert "Copy-Item -LiteralPath $ServiceXml" in script
    assert "local-backup.lock" in script
    assert "Wait-Healthy -Uri $LocalHealthUri" in script
    assert "Wait-Healthy -Uri $PublicHealthUri" in script
    assert "Copy-Item -LiteralPath (Join-Path $rollback 'IZOBackend.xml')" in script


def test_architecture_check_requires_direct_frp_and_yandex_routes() -> None:
    script = (ROOT / "ops" / "network" / "check_socks5_architecture.ps1").read_text(
        encoding="utf-8"
    )

    assert "frpc_not_bound_to_physical_interface" in script
    assert "HardwareInterface -eq $true" in script
    assert "yandex_route_not_direct" in script
    assert "socks5_listener_owner_invalid" in script
    assert "public_health_not_ready" in script
