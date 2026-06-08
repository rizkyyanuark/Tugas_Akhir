param(
    [string]$Target = "",
    [int]$DebounceSeconds = 4,
    [switch]$SkipInitialSync,
    [switch]$IncludeEnv,
    [switch]$IncludeManualTestData,
    [switch]$SkipGwsApi,
    [string]$DriveRootFolderId = "",
    [string]$DriveRootFolderName = "Tugas_Akhir"
)

$ErrorActionPreference = "Stop"

$RepoRoot = [System.IO.Path]::GetFullPath((Resolve-Path (Join-Path $PSScriptRoot "..")))
$SyncScript = Join-Path $PSScriptRoot "sync-kg-notebook-to-gdrive.ps1"

if (-not (Test-Path -LiteralPath $SyncScript)) {
    throw "Missing sync script: $SyncScript"
}

function Get-RelativePath {
    param([string]$Path)

    $FullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $FullPath.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $null
    }

    return $FullPath.Substring($RepoRoot.Length).TrimStart("\").Replace("/", "\")
}

function Test-RelevantPath {
    param([string]$Path)

    $RelativePath = Get-RelativePath -Path $Path
    if ([string]::IsNullOrWhiteSpace($RelativePath)) {
        return $false
    }

    if ($RelativePath.StartsWith("notebooks\build-graph\outputs\", [System.StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }
    if ($RelativePath.Contains("\.ipynb_checkpoints\")) {
        return $false
    }
    if ($RelativePath.Contains("\__pycache__\")) {
        return $false
    }

    $ExactPaths = @(
        "notebooks\build-graph\yunesa_academic_kg_construction.ipynb",
        "notebooks\build-graph\yunesa_academic_graphrag_groq.ipynb",
        "notebooks\build-graph\yunesa_academic_graphrag_dev.ipynb",
        "notebooks\build-graph\ieee-thesaurus.ttl",
        "notebooks\build-graph\ieee-taxonomy.ttl",
        "notebooks\build-graph\src\yunesa_academic_kg.py",
        "notebooks\README.md",
        "notebooks\pyproject.toml",
        "notebooks\uv.lock"
    )

    foreach ($ExactPath in $ExactPaths) {
        if ($RelativePath.Equals($ExactPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    if ($IncludeManualTestData -and $RelativePath.StartsWith("data\manual_tests\", [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }

    return $false
}

function Invoke-KGSync {
    $Args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $SyncScript)
    if (-not [string]::IsNullOrWhiteSpace($Target)) {
        $Args += @("-Target", $Target)
    }
    if ($IncludeEnv) {
        $Args += "-IncludeEnv"
    }
    if ($IncludeManualTestData) {
        $Args += "-IncludeManualTestData"
    }
    if ($SkipGwsApi) {
        $Args += "-SkipGwsApi"
    }
    if (-not [string]::IsNullOrWhiteSpace($DriveRootFolderId)) {
        $Args += @("-DriveRootFolderId", $DriveRootFolderId)
    }
    if (-not [string]::IsNullOrWhiteSpace($DriveRootFolderName)) {
        $Args += @("-DriveRootFolderName", $DriveRootFolderName)
    }

    Write-Host ""
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] KG sync started..."
    & powershell.exe @Args
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "KG sync command exited with code $LASTEXITCODE"
    } else {
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] KG sync finished."
    }
}

if (-not $SkipInitialSync) {
    Invoke-KGSync
}

$script:PendingSync = $false
$script:LastChangeAt = Get-Date

$Watcher = New-Object System.IO.FileSystemWatcher
$Watcher.Path = $RepoRoot
$Watcher.IncludeSubdirectories = $true
$Watcher.EnableRaisingEvents = $true

$Action = {
    if (-not (Test-RelevantPath -Path $Event.SourceEventArgs.FullPath)) {
        return
    }

    $script:PendingSync = $true
    $script:LastChangeAt = Get-Date
    $RelativePath = Get-RelativePath -Path $Event.SourceEventArgs.FullPath
    Write-Host "[$($script:LastChangeAt.ToString('HH:mm:ss'))] KG change detected: $($Event.SourceEventArgs.ChangeType) $RelativePath"
}

$Events = @(
    Register-ObjectEvent -InputObject $Watcher -EventName Created -Action $Action,
    Register-ObjectEvent -InputObject $Watcher -EventName Changed -Action $Action,
    Register-ObjectEvent -InputObject $Watcher -EventName Deleted -Action $Action,
    Register-ObjectEvent -InputObject $Watcher -EventName Renamed -Action $Action
)

Write-Host "Watching KG notebook assets for Google Drive sync..."
Write-Host "  Source: $RepoRoot"
if (-not [string]::IsNullOrWhiteSpace($Target)) {
    Write-Host "  Target: $Target"
} elseif (-not [string]::IsNullOrWhiteSpace($env:YUNESA_GDRIVE_PROJECT_DIR)) {
    Write-Host "  Target: $env:YUNESA_GDRIVE_PROJECT_DIR"
} else {
    Write-Host "  Target: auto-resolved by sync script"
}
Write-Host "Press Ctrl+C to stop."

try {
    while ($true) {
        Start-Sleep -Seconds 1

        if ($script:PendingSync) {
            $AgeSeconds = ((Get-Date) - $script:LastChangeAt).TotalSeconds
            if ($AgeSeconds -ge $DebounceSeconds) {
                $script:PendingSync = $false
                Invoke-KGSync
            }
        }
    }
}
finally {
    foreach ($EventSubscription in $Events) {
        Unregister-Event -SubscriptionId $EventSubscription.Id -ErrorAction SilentlyContinue
    }
    $Watcher.Dispose()
}
