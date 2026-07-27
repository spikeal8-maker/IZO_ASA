from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "ops" / "backup"


def read_script(name: str) -> str:
    return (BACKUP / name).read_text(encoding="utf-8")


def test_primary_schedule_uses_30m_local_backup_and_bounded_yandex_window() -> None:
    installer = read_script("install_backup_automation.ps1")

    assert "-Name 'IZO_ASA Local Backup 30m'" in installer
    assert "-Schedule MINUTE -Modifier 30" in installer
    assert "New-ScheduledTaskTrigger -Daily -At '02:00'" in installer
    assert "'IZO_ASA Yandex Outbound Nightly'" in installer
    assert "New-ScheduledTaskTrigger -Daily -At '05:00'" in installer
    assert "New-ScheduledTaskTrigger -AtLogOn" in installer
    assert "'IZO_ASA Yandex Daytime Guard'" in installer


def test_old_backup_tasks_are_removed_and_standby_tasks_are_disabled() -> None:
    installer = read_script("install_backup_automation.ps1")

    for task in (
        "IZO_ASA Local Backup 15m",
        "IZO_ASA Local Backup Hourly",
        "IZO_ASA Cloud Stage Hourly",
        "IZO_ASA Cloud Stage Daily 01h",
    ):
        assert f"$obsoleteTasks.Add('{task}')" in installer
    for task in (
        "IZO_ASA Replica Receive Hourly",
        "IZO_ASA Replica Rehearsal Daily",
        "IZO_ASA Cloud Backup Stage",
    ):
        assert f"$disabledTasks.Add('{task}')" in installer
    assert "Disable-ScheduledTask -TaskName $taskName" in installer


def test_backup_health_matches_primary_freshness_and_window_policy() -> None:
    health = read_script("check_backup_health.ps1")

    assert "LastLocalBackup 45 'local_backup_older_than_45_minutes'" in health
    assert "LastCloudStage 1800 'cloud_stage_older_than_30_hours'" in health
    assert "'yandex_disk_not_running_during_nightly_window'" in health
    assert "'yandex_disk_running_outside_nightly_window'" in health
    assert "YandexAppBypassConfigured" in health
    assert "YandexAppBypassConfirmed" in health


def test_outbound_waits_for_contended_local_backup_and_does_not_retry_it() -> None:
    outbound = read_script("run_yandex_outbound_nightly.ps1")

    assert "$backupExit -eq 3" in outbound
    assert "BACKUP_WAIT reason=already_running" in outbound
    assert "No fresh verified local backup became available before cloud staging." in outbound
    assert outbound.count("Invoke-LoggedPowerShell -Phase 'local-backup'") == 1
    assert "PHASE_START phase=$Phase" in outbound
    assert "PHASE_END phase=$Phase exitCode=$($process.ExitCode)" in outbound


def test_yandex_network_gate_uses_configured_and_observed_app_bypass_evidence() -> None:
    helper = read_script("yandex_network.ps1")
    stage = read_script("stage_cloud_backup.ps1")
    health = read_script("check_backup_health.ps1")

    assert "VPN_CA_FORCE_BYPASS" in helper
    assert "AppBypassConfigured" in helper
    assert "AppBypassObserved" in helper
    for script in (stage, health):
        assert "$network.ProbeInterface -match '(?i)AdGuard.*VPN'" in script
        assert "-not $network.AppBypassConfigured" in script
    assert "process-specific bypass was not observed" in stage


def test_yandex_is_not_persistently_autostarted() -> None:
    installer = read_script("install_backup_automation.ps1")
    outbound = read_script("run_yandex_outbound_nightly.ps1")
    guard = read_script("yandex_daytime_guard.ps1")

    assert "Remove-ItemProperty -Path $runKey -Name 'IZO_ASA_YandexDisk4'" in installer
    assert "Remove-ItemProperty -Path $runKey -Name $runName" in outbound
    assert "Remove-ItemProperty -Path $runKey -Name $runName" in guard
    assert "Stop-Process -Force" in guard


def test_installer_is_safe_to_run_outside_the_yandex_window() -> None:
    installer = read_script("install_backup_automation.ps1")

    assert "YandexDisk4.exe must be running before installation." not in installer
    assert ". $networkScript" in installer
    assert "-not $network.AppBypassConfigured" in installer
