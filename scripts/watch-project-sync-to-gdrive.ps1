param(
    [string]$Target = "G:\My Drive\Tugas_Akhir",
    [int]$DebounceSeconds = 5,
    [switch]$SkipInitialSync
)

$ErrorActionPreference = "Stop"

$RepoRoot = [System.IO.Path]::GetFullPath((Resolve-Path (Join-Path $PSScriptRoot "..")))
$SyncScript = Join-Path $PSScriptRoot "sync-project-to-gdrive.ps1"

if (-not (Test-Path $SyncScript)) {
    throw "Missing sync script: $SyncScript"
}

$ExcludedPathFragments = @(
    "\.git\",
    "\.vscode\",
    "\.idea\",
    "\.antigravitycli\",
    "\AWS\",
    "\cloudflared\",
    "\.uv-cache\",
    "\.hf_cache\",
    "\.cache\",
    "\data\",
    "\saves\",
    "\models\",
    "\logs\",
    "\notebooks\.venv\",
    "\node_modules\",
    "\__pycache__\",
    "\.pytest_cache\",
    "\.ruff_cache\",
    "\.ipynb_checkpoints\",
    "\notebooks\build-graph\lancedb_store\",
    "\notebooks\build-graph\test_lancedb\"
)

function Test-ShouldIgnorePath {
    param([string]$Path)

    $NormalizedPath = $Path.Replace("/", "\")
    foreach ($Fragment in $ExcludedPathFragments) {
        if ($NormalizedPath.Contains($Fragment)) {
            return $true
        }
    }

    $Name = [System.IO.Path]::GetFileName($NormalizedPath)
    if ($Name -match '^\.env(\..*)?$') { return $true }
    if ($Name -match '\.(pem|key|log|tmp|temp|bak|db|sqlite|sqlite3|gguf|bin|safetensors|h5|pt|pth)$') { return $true }
    if ($Name -in @("credentials.json", "credentials_new.json", "kg_export.json")) { return $true }

    return $false
}

function Invoke-Sync {
    Write-Host ""
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Sync started..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $SyncScript -Target $Target
    if ($LASTEXITCODE -gt 7) {
        Write-Warning "Sync failed with exit code $LASTEXITCODE"
    } else {
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Sync finished."
    }
}

if (-not $SkipInitialSync) {
    Invoke-Sync
}

$script:PendingSync = $false
$script:LastChangeAt = Get-Date

$Watcher = New-Object System.IO.FileSystemWatcher
$Watcher.Path = $RepoRoot
$Watcher.IncludeSubdirectories = $true
$Watcher.EnableRaisingEvents = $true

$Action = {
    if (Test-ShouldIgnorePath -Path $Event.SourceEventArgs.FullPath) {
        return
    }

    $script:PendingSync = $true
    $script:LastChangeAt = Get-Date
    Write-Host "[$($script:LastChangeAt.ToString('HH:mm:ss'))] Change detected: $($Event.SourceEventArgs.ChangeType) $($Event.SourceEventArgs.FullPath)"
}

$Events = @(
    Register-ObjectEvent -InputObject $Watcher -EventName Created -Action $Action,
    Register-ObjectEvent -InputObject $Watcher -EventName Changed -Action $Action,
    Register-ObjectEvent -InputObject $Watcher -EventName Deleted -Action $Action,
    Register-ObjectEvent -InputObject $Watcher -EventName Renamed -Action $Action
)

Write-Host "Watching project changes..."
Write-Host "  Source: $RepoRoot"
Write-Host "  Target: $Target"
Write-Host "Press Ctrl+C to stop."

try {
    while ($true) {
        Start-Sleep -Seconds 1

        if ($script:PendingSync) {
            $AgeSeconds = ((Get-Date) - $script:LastChangeAt).TotalSeconds
            if ($AgeSeconds -ge $DebounceSeconds) {
                $script:PendingSync = $false
                Invoke-Sync
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
