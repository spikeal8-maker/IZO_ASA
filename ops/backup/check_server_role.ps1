[CmdletBinding()]
param([string]$RoleConfig = 'C:\IZO_ASA\config\server-role.json')

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $RoleConfig -PathType Leaf)) {
    Write-Host 'SERVER_ROLE_NOT_CONFIGURED'
    exit 0
}
$role = Get-Content -LiteralPath $RoleConfig -Raw | ConvertFrom-Json
if ($role.role -ne 'PRIMARY' -or $role.databaseWriter -ne $true) {
    Write-Error 'This computer is not PRIMARY. Refusing to start a writing backend.'
    exit 41
}
Write-Host 'SERVER_ROLE_PRIMARY_OK'
exit 0
