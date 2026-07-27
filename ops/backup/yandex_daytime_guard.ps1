Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runName = 'Yandex.Disk.4'

Remove-ItemProperty -Path $runKey -Name $runName -ErrorAction SilentlyContinue
if (-not (Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue)) { exit 0 }

Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue |
    ForEach-Object { [void]$_.CloseMainWindow() }
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    if (-not (Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue)) { exit 0 }
    Start-Sleep -Seconds 1
}
Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
if (Get-Process -Name YandexDisk4 -ErrorAction SilentlyContinue) {
    throw 'Yandex.Disk could not be stopped by the daytime guard.'
}
exit 0
