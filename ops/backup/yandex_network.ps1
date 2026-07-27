Set-StrictMode -Version Latest

function Get-IzoYandexNetworkState {
    [CmdletBinding()]
    param(
        [string]$YandexExecutable = 'C:\Users\admins\AppData\Local\Programs\Yandex\YandexDisk4\YandexDisk4.exe',
        [string]$AdGuardLogRoot = 'C:\ProgramData\AdguardVpn\Logs\service',
        [int]$MaximumLogAgeHours = 168
    )

    $route = Test-NetConnection disk.yandex.ru -Port 443 -InformationLevel Detailed -WarningAction SilentlyContinue
    $configured = $false
    $observed = $false
    $evidenceTimestamp = $null

    if (Test-Path -LiteralPath $AdGuardLogRoot -PathType Container) {
        $minimumWriteTime = (Get-Date).AddHours(-$MaximumLogAgeHours)
        $escapedExecutable = [regex]::Escape($YandexExecutable)
        $logs = Get-ChildItem -LiteralPath $AdGuardLogRoot -Filter '*.log' -File -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $minimumWriteTime -and $_.Length -gt 0 } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 8

        foreach ($log in $logs) {
            $tail = (
                Get-Content -LiteralPath $log.FullName -Tail 100000 -ErrorAction SilentlyContinue
            ) -join "`n"
            if ($tail -match $escapedExecutable) {
                $configured = $true
                if ($null -eq $evidenceTimestamp) {
                    $evidenceTimestamp = $log.LastWriteTime.ToString('o')
                }
            }
            $bypassMatch = [regex]::Match(
                $tail,
                "(?im)^[^\r\n]*(?:action=VPN_CA_FORCE_BYPASS[^\r\n]*appname=$escapedExecutable|appname=$escapedExecutable[^\r\n]*action=VPN_CA_FORCE_BYPASS)[^\r\n]*$"
            )
            if ($bypassMatch.Success) {
                $observed = $true
                $configured = $true
                $timestampMatch = [regex]::Match(
                    $bypassMatch.Value,
                    '\b(?<date>\d{1,2}\.\d{2}\.\d{4})\s+(?<time>\d{1,2}:\d{2}:\d{2}\.\d{3})\b'
                )
                if ($timestampMatch.Success) {
                    $parsedTimestamp = [DateTime]::ParseExact(
                        "$($timestampMatch.Groups['date'].Value) $($timestampMatch.Groups['time'].Value)",
                        'd.MM.yyyy H:mm:ss.fff',
                        [Globalization.CultureInfo]::InvariantCulture
                    )
                    $evidenceTimestamp = $parsedTimestamp.ToString('o')
                } else {
                    $evidenceTimestamp = $log.LastWriteTime.ToString('o')
                }
                break
            }
        }
    }

    [pscustomobject]@{
        HttpsReachable = [bool]$route.TcpTestSucceeded
        ProbeInterface = [string]$route.InterfaceAlias
        AppBypassConfigured = $configured
        AppBypassObserved = $observed
        EvidenceTimestamp = $evidenceTimestamp
    }
}
