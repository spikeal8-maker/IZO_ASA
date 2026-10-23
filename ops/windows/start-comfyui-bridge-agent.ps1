[CmdletBinding()]
param([ValidateSet("start","stop","status")][string]$Action="status")
$ErrorActionPreference="Stop"
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runtime=Join-Path $env:LOCALAPPDATA "IZO_ASA_Comfy214Runtime"
$token=Join-Path $runtime "bridge.token"
$pidFile=Join-Path $runtime "host-agent.pid"
$embedded=Join-Path ("C:\"+[char]0x0418+[char]0x0418) "ComfyUI-Portable\python_embeded\python.exe"
$script=Join-Path $root "ops\windows\comfyui_bridge_agent.py"
function OwnedProcess {
    if(!(Test-Path -LiteralPath $pidFile)){return $null}
    $pidNumber=[int]([IO.File]::ReadAllText($pidFile).Trim())
    $proc=Get-CimInstance Win32_Process -Filter "ProcessId=$pidNumber" -ErrorAction SilentlyContinue
    if(!$proc){return $null}
    if($proc.ExecutablePath -ne $embedded -or !$proc.CommandLine.Contains("comfyui_bridge_agent.py")){
        throw "PROCESS_OWNERSHIP_FAILED_REFUSE_TO_STOP"
    }
    return $proc
}
if($Action -eq "status"){
    $proc=OwnedProcess
    Write-Output $(if($proc){"RUNNING_PID="+$proc.ProcessId}else{"STOPPED"})
    exit 0
}
if($Action -eq "stop"){
    $proc=OwnedProcess
    if(!$proc){Write-Output "NO_OWNED_AGENT_RUNNING";exit 0}
    Stop-Process -Id $proc.ProcessId -ErrorAction Stop
    Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
    Write-Output "STOPPED_ONLY_OWN_HOST_BRIDGE_AGENT"
    exit 0
}
if(!(Test-Path -LiteralPath $embedded)){throw "OFFICIAL_EMBEDDED_PYTHON_MISSING"}
if(!(Test-Path -LiteralPath $script)){throw "BRIDGE_AGENT_SCRIPT_MISSING"}
[IO.Directory]::CreateDirectory($runtime)|Out-Null
if(!(Test-Path -LiteralPath $token)){throw "BRIDGE_TOKEN_FILE_MISSING_INIT_OFF_REPO"}
if((Get-Item -LiteralPath $token).Length -lt 40){throw "BRIDGE_TOKEN_INVALID"}
$old=OwnedProcess
if($old){Write-Output ("ALREADY_RUNNING_PID="+$old.ProcessId);exit 0}
if(Test-Path -LiteralPath $pidFile){throw "STALE_AGENT_PID_MANUAL_INSPECTION_REQUIRED"}
$stdout=Join-Path $runtime "host-agent.stdout.log"
$stderr=Join-Path $runtime "host-agent.stderr.log"
$args=@("-s",$script,"--bridge","http://127.0.0.1:48216","--comfy","http://127.0.0.1:8188","--token-file",$token)
$proc=Start-Process -FilePath $embedded -ArgumentList $args -WorkingDirectory $root -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
[IO.File]::WriteAllText($pidFile,[string]$proc.Id,[Text.Encoding]::ASCII)
Write-Output ("STARTED_PID="+$proc.Id)
Write-Output ("EVIDENCE_DIR="+$runtime)
