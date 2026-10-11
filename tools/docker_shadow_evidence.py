"""Read-only, redacted before/after evidence for an owned shadow operation."""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from tools.docker_shadow import OWNER, Shadow

WINDOWS_SNAPSHOT = r'''
$ErrorActionPreference = 'Stop'
$env:PSModulePath = Join-Path $PSHOME 'Modules'
$allProcesses = @(Get-CimInstance Win32_Process)
$services = @(Get-CimInstance Win32_Service | Where-Object {
    $_.Name -in @('IZOBackend','IZOCaddy') -or $_.Name -match 'frp'
} | Sort-Object Name)
$ownedIds = @($services.ProcessId)
do {
    $previous = $ownedIds.Count
    $ownedIds = @($ownedIds + @($allProcesses | Where-Object {
        $_.ParentProcessId -in $ownedIds
    } | ForEach-Object { $_.ProcessId }) | Sort-Object -Unique)
} while ($ownedIds.Count -ne $previous)
$processes = @($allProcesses | Where-Object { $_.ProcessId -in $ownedIds } | Sort-Object ProcessId)
$configs = @()
foreach ($svc in $services) {
    $exe = if ($svc.PathName -match '^"([^"]+)"') { $matches[1] } else { ($svc.PathName -split ' ')[0] }
    $xmlPath = [IO.Path]::ChangeExtension($exe, '.xml')
    if (Test-Path -LiteralPath $xmlPath) {
        $configs += @{ source=$svc.Name+':service-definition'; sha256=(Get-FileHash -LiteralPath $xmlPath -Algorithm SHA256).Hash }
        if ($svc.Name -match 'Caddy|frp') {
            $definition = [xml](Get-Content -LiteralPath $xmlPath -Raw)
            $arguments = [string]$definition.service.arguments
            if ($arguments -notmatch '(?:--config|-c)(?:=|\s+)(?:"([^"]+)"|(\S+))') { throw 'ROUTING_CONFIG_NOT_IDENTIFIED' }
            $configPath = if ($matches[1]) { $matches[1] } else { $matches[2] }
            $configPath = $configPath.Replace('%BASE%', (Split-Path -Parent $xmlPath))
            if (-not [IO.Path]::IsPathRooted($configPath)) { throw 'ROUTING_CONFIG_PATH_NOT_ABSOLUTE' }
            $configs += @{ source=$svc.Name+':routing'; sha256=(Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash }
        }
    } else { throw 'SERVICE_DEFINITION_UNAVAILABLE' }
}
if (-not ($services | Where-Object Name -eq 'IZOBackend') -or -not ($services | Where-Object Name -eq 'IZOCaddy')) { throw 'PRODUCTION_SERVICE_NOT_IDENTIFIED' }
@{
 services=@($services | ForEach-Object { @{name=$_.Name; state=$_.State; pid=$_.ProcessId} })
 processes=@($processes | ForEach-Object { @{name=$_.Name; pid=$_.ProcessId; parent=$_.ParentProcessId; started=$_.CreationDate.ToUniversalTime().ToString('o')} })
 listeners=@(Get-NetTCPConnection -State Listen | Where-Object { $_.OwningProcess -in $ownedIds } | Sort-Object LocalAddress,LocalPort,OwningProcess | ForEach-Object { @{address=$_.LocalAddress; port=$_.LocalPort; pid=$_.OwningProcess} })
 routingConfigHashes=@($configs | Sort-Object source)
} | ConvertTo-Json -Depth 8 -Compress
'''


def snapshot(shadow: Shadow) -> dict:
    result = {'checkedAt': datetime.now(timezone.utc).isoformat(), 'status': 'FAIL'}
    encoded = base64.b64encode(WINDOWS_SNAPSHOT.encode('utf-16-le')).decode('ascii')
    windows = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                              encoded], capture_output=True, text=True, timeout=60)
    if windows.returncode:
        raise RuntimeError('PRODUCTION_METADATA_CAPTURE_FAILED')
    result['windows'] = json.loads(windows.stdout)
    fields = ('release_id', 'backend_commit', 'frontend_build',
              'frontend_asset_manifest_hash', 'started_at')
    opener = build_opener(ProxyHandler({}))
    result['versions'] = {}
    for url in ('http://127.0.0.1:8000/api/version', 'https://izo.alikinas.ru/api/version'):
        with opener.open(url, timeout=15) as response:
            data = json.load(response)
        result['versions'][url] = {key: data[key] for key in fields}
    foreign = {}
    for kind, command in (('containers', ('ps', '-aq')), ('networks', ('network', 'ls', '-q')),
                          ('volumes', ('volume', 'ls', '-q'))):
        ids = shadow.docker(*command).split()
        entries = json.loads(shadow.docker(*(('inspect',) if kind == 'containers' else
                            (command[0], 'inspect')), *ids)) if ids else []
        rows = []
        for entry in entries:
            labels = entry.get('Config', {}).get('Labels') if kind == 'containers' else entry.get('Labels')
            if (labels or {}).get('io.izo.owner') == OWNER:
                continue
            row = {'id': entry.get('Id', entry.get('Name')), 'name': entry['Name']}
            if kind == 'containers':
                row.update(image=entry['Image'], started=entry['State']['StartedAt'],
                           running=entry['State']['Running'], pid=entry['State']['Pid'])
            rows.append(row)
        foreign[kind] = sorted(rows, key=lambda row: row['id'])
    result['foreignDocker'] = foreign
    result['status'] = 'CAPTURED'
    return result


def compare(before: dict, after: dict) -> dict:
    if before.get('status') != 'CAPTURED' or after.get('status') != 'CAPTURED':
        raise RuntimeError('PRODUCTION_SNAPSHOT_INCOMPLETE')
    checks = {key: before[key] == after[key] for key in ('versions', 'windows', 'foreignDocker')}
    return {'status': 'PROVEN' if all(checks.values()) else 'FAIL', 'checks': checks,
            'scope': 'New controlled shadow operations only; original historical baseline unavailable.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = snapshot(Shadow(args.project, args.source_sha))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print('PRODUCTION_SNAPSHOT_CAPTURED')
