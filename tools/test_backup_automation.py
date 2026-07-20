from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_primary_cloud_stage_is_nightly_and_old_hourly_task_is_removed() -> None:
    installer = (ROOT / "ops" / "backup" / "install_backup_automation.ps1").read_text(
        encoding="utf-8"
    )

    assert "-Name 'IZO_ASA Cloud Stage Daily 01h'" in installer
    assert "-Schedule DAILY -StartTime '01:00' -StartWhenAvailable" in installer
    assert "$obsoleteTasks.Add('IZO_ASA Cloud Stage Hourly')" in installer
    assert "-Name 'IZO_ASA Cloud Stage Hourly' -Script" not in installer


def test_backup_tasks_run_hidden_and_cloud_health_allows_daily_schedule() -> None:
    installer = (ROOT / "ops" / "backup" / "install_backup_automation.ps1").read_text(
        encoding="utf-8"
    )
    health = (ROOT / "ops" / "backup" / "check_backup_health.ps1").read_text(
        encoding="utf-8"
    )

    assert "-WindowStyle Hidden" in installer
    assert "Hidden = $true" in installer
    assert "LastCloudStage 1560 'cloud_stage_older_than_26_hours'" in health


def test_local_backup_is_hourly_and_old_quarter_hour_task_is_removed() -> None:
    installer = (ROOT / "ops" / "backup" / "install_backup_automation.ps1").read_text(
        encoding="utf-8"
    )
    health = (ROOT / "ops" / "backup" / "check_backup_health.ps1").read_text(
        encoding="utf-8"
    )

    assert "-Name 'IZO_ASA Local Backup Hourly'" in installer
    assert "-Schedule HOURLY -Modifier 1 -StartWhenAvailable" in installer
    assert "$obsoleteTasks.Add('IZO_ASA Local Backup 15m')" in installer
    assert "LastLocalBackup 120 'local_backup_older_than_2_hours'" in health


def test_yandex_route_check_requires_proven_egress_split() -> None:
    """BACKUP-NET-001: the owner-approved AdGuard exclusion splits traffic
    inside the tunnel, so the check must prove the split functionally and
    fail closed when either egress probe is unavailable."""
    health = (ROOT / "ops" / "backup" / "check_backup_health.ps1").read_text(
        encoding="utf-8"
    )

    assert "$routedViaAdguardVpn -and $yandexEgressSplit -ne $true" in health
    assert "'yandex_routed_through_adguard_vpn'" in health
    assert "YandexEgressSplitActive" in health
    # Raw egress addresses are compared in memory only, never persisted.
    assert "$health['YandexEgress']" not in health
    assert "generalEgress'] =" not in health
