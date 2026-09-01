Set-StrictMode -Version Latest

function ConvertTo-IzoFullPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if (-not $Path.Trim()) {
        throw "$Label is empty."
    }
    return [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($Path.Trim()))
}

function Get-IzoServiceExecutablePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathName
    )

    $expanded = [Environment]::ExpandEnvironmentVariables($PathName.Trim())
    $match = [regex]::Match($expanded, '^\s*(?:"([^"]+)"|(\S+))')
    if (-not $match.Success) {
        throw "IZOBackend service executable could not be parsed from PathName."
    }
    $path = if ($match.Groups[1].Success) { $match.Groups[1].Value } else { $match.Groups[2].Value }
    return ConvertTo-IzoFullPath -Path $path -Label "IZOBackend service executable"
}

function ConvertTo-IzoNormalizedArguments {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Arguments
    )

    return ([regex]::Replace($Arguments.Trim(), '\s+', ' '))
}

function Get-IzoProcessArguments {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandLine
    )

    $match = [regex]::Match($CommandLine.Trim(), '^\s*(?:"[^"]+"|\S+)\s*(.*)$')
    if (-not $match.Success) {
        throw "Installed backend launcher command line could not be parsed."
    }
    return ConvertTo-IzoNormalizedArguments -Arguments $match.Groups[1].Value
}

function Assert-IzoInstalledBackendServiceOwnership {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ListenerProcess,
        [Parameter(Mandatory = $true)]
        [object]$LauncherProcess,
        [Parameter(Mandatory = $true)]
        [object]$Service,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedReleaseRoot,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedBasePython,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedServiceExecutable,
        [string]$ExpectedServiceName = "IZOBackend"
    )

    if ([string]$Service.Name -ne $ExpectedServiceName) {
        throw "Backend service identity is unexpected: $([string]$Service.Name)"
    }
    if ([string]$Service.State -ne "Running" -or [int]$Service.ProcessId -le 0) {
        throw "Backend service $ExpectedServiceName is not running with an owned process."
    }
    if ([int]$ListenerProcess.ParentProcessId -ne [int]$LauncherProcess.ProcessId) {
        throw "Backend listener is not a child of the inspected launcher process."
    }
    if ([int]$LauncherProcess.ParentProcessId -ne [int]$Service.ProcessId) {
        throw "Backend launcher is not owned by the running $ExpectedServiceName service."
    }

    $listenerExecutable = ConvertTo-IzoFullPath -Path ([string]$ListenerProcess.ExecutablePath) -Label "Backend listener executable"
    if (-not [IO.Path]::GetFileName($listenerExecutable).Equals("python.exe", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backend listener is not a Python executable: $listenerExecutable"
    }
    $requiredBasePython = ConvertTo-IzoFullPath -Path $ExpectedBasePython -Label "Installed backend base Python"
    if (-not (Test-Path -LiteralPath $requiredBasePython -PathType Leaf)) {
        throw "Installed backend base Python was not found: $requiredBasePython"
    }
    if (-not $listenerExecutable.Equals($requiredBasePython, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backend listener does not match the configured service base Python."
    }
    $launcherExecutable = ConvertTo-IzoFullPath -Path ([string]$LauncherProcess.ExecutablePath) -Label "Backend launcher executable"

    $serviceExecutable = Get-IzoServiceExecutablePath -PathName ([string]$Service.PathName)
    $requiredServiceExecutable = ConvertTo-IzoFullPath -Path $ExpectedServiceExecutable -Label "Installed backend service executable"
    if (-not $serviceExecutable.Equals($requiredServiceExecutable, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backend service executable is outside the installed runtime location."
    }
    if (-not (Test-Path -LiteralPath $serviceExecutable -PathType Leaf)) {
        throw "Backend service executable was not found: $serviceExecutable"
    }
    $serviceConfigPath = [IO.Path]::ChangeExtension($serviceExecutable, ".xml")
    if (-not (Test-Path -LiteralPath $serviceConfigPath -PathType Leaf)) {
        throw "Backend service XML was not found: $serviceConfigPath"
    }

    [xml]$serviceConfig = Get-Content -LiteralPath $serviceConfigPath -Raw
    if ([string]$serviceConfig.service.id -ne $ExpectedServiceName) {
        throw "Backend service XML identity does not match $ExpectedServiceName."
    }

    $configuredExecutable = ConvertTo-IzoFullPath -Path ([string]$serviceConfig.service.executable) -Label "Backend service XML executable"
    if (-not $configuredExecutable.Equals($launcherExecutable, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backend launcher does not match the service XML executable."
    }
    $workingDirectory = ConvertTo-IzoFullPath -Path ([string]$serviceConfig.service.workingdirectory) -Label "Backend service working directory"
    if (-not [IO.Path]::GetFileName($workingDirectory).Equals("backend", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backend service working directory is not a release backend directory."
    }
    $configuredVenvPython = [IO.Path]::GetFullPath((Join-Path $workingDirectory ".venv\Scripts\python.exe"))
    if (-not $configuredExecutable.Equals($configuredVenvPython, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backend service XML executable is outside its release virtual environment."
    }

    $releaseRoot = Split-Path -Parent $workingDirectory
    $releaseDirectorySha = Split-Path -Leaf $releaseRoot
    $gitCommitNodes = @($serviceConfig.service.env | Where-Object { [string]$_.name -eq "GIT_COMMIT" })
    if ($gitCommitNodes.Count -ne 1) {
        throw "Backend service XML must declare exactly one GIT_COMMIT."
    }
    $configuredSha = [string]$gitCommitNodes[0].value
    if ($configuredSha -notmatch '^[0-9a-fA-F]{40}$' -or -not $configuredSha.Equals($releaseDirectorySha, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backend service XML release SHA does not match its immutable release directory."
    }
    $installedReleaseRoot = ConvertTo-IzoFullPath -Path $ExpectedReleaseRoot -Label "Installed release root"
    $requiredWorkingDirectory = [IO.Path]::GetFullPath((Join-Path (Join-Path $installedReleaseRoot $configuredSha) "backend"))
    if (-not $workingDirectory.Equals($requiredWorkingDirectory, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backend service working directory is outside the installed release root."
    }

    $configuredArguments = ConvertTo-IzoNormalizedArguments -Arguments ([string]$serviceConfig.service.arguments)
    $launcherArguments = Get-IzoProcessArguments -CommandLine ([string]$LauncherProcess.CommandLine)
    if (-not $configuredArguments.Equals($launcherArguments, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backend launcher arguments do not match the service XML contract."
    }

    return [pscustomobject]@{
        RuntimeOwnership = "installed-windows-service"
        RuntimeLauncherProcessId = [int]$LauncherProcess.ProcessId
        RuntimeLauncherExecutablePath = $launcherExecutable
        ReleaseSha = $configuredSha.ToLowerInvariant()
        ServiceConfigPath = $serviceConfigPath
    }
}
