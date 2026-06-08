param(
    [string]$Target = "",
    [switch]$IncludeEnv,
    [switch]$IncludeManualTestData,
    [switch]$SkipGwsApi,
    [string]$DriveRootFolderId = "",
    [string]$DriveRootFolderName = "Tugas_Akhir"
)

$ErrorActionPreference = "Stop"

$RepoRoot = [System.IO.Path]::GetFullPath((Resolve-Path (Join-Path $PSScriptRoot "..")))

function Resolve-GDriveTarget {
    param([string]$RequestedTarget)

    $Candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($RequestedTarget)) {
        $Candidates += $RequestedTarget
    }
    if (-not [string]::IsNullOrWhiteSpace($env:YUNESA_GDRIVE_PROJECT_DIR)) {
        $Candidates += $env:YUNESA_GDRIVE_PROJECT_DIR
    }

    $Candidates += @(
        "G:\My Drive\Tugas_Akhir",
        "G:\MyDrive\Tugas_Akhir",
        (Join-Path $env:USERPROFILE "Google Drive\My Drive\Tugas_Akhir"),
        (Join-Path $env:USERPROFILE "Google Drive\Tugas_Akhir"),
        (Join-Path $env:USERPROFILE "My Drive\Tugas_Akhir")
    )

    foreach ($Candidate in $Candidates) {
        if ([string]::IsNullOrWhiteSpace($Candidate)) {
            continue
        }

        $FullPath = [System.IO.Path]::GetFullPath($Candidate)
        $Parent = Split-Path -Parent $FullPath

        if ((Test-Path -LiteralPath $FullPath) -or (Test-Path -LiteralPath $Parent)) {
            return $FullPath
        }
    }

    throw @"
Cannot resolve Google Drive target folder.

Pass a valid target explicitly, for example:
  .\scripts\sync-kg-notebook-to-gdrive.ps1 -Target "G:\My Drive\Tugas_Akhir"

Or set:
  `$env:YUNESA_GDRIVE_PROJECT_DIR = "G:\My Drive\Tugas_Akhir"

If G: is missing, open Google Drive Desktop and confirm the Drive mount/path first.
"@
}

function Copy-RepoFile {
    param(
        [string]$RelativePath,
        [string]$TargetRoot
    )

    $Source = Join-Path $RepoRoot $RelativePath
    $Destination = Join-Path $TargetRoot $RelativePath

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Required file is missing: $RelativePath"
    }

    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null

    $NeedsCopy = $true
    if (Test-Path -LiteralPath $Destination) {
        $SourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash
        $DestinationHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
        $NeedsCopy = $SourceHash -ne $DestinationHash
    }

    if ($NeedsCopy) {
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
        return [pscustomobject]@{ Path = $RelativePath; Status = "copied" }
    }

    return [pscustomobject]@{ Path = $RelativePath; Status = "unchanged" }
}

function Sync-ManualTestData {
    param([string]$TargetRoot)

    $Source = Join-Path $RepoRoot "data\manual_tests"
    if (-not (Test-Path -LiteralPath $Source)) {
        return
    }

    $Destination = Join-Path $TargetRoot "data\manual_tests"
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    $Args = @(
        $Source,
        $Destination,
        "/E",
        "/FFT",
        "/R:2",
        "/W:2",
        "/NP",
        "/XD", "__pycache__", ".ipynb_checkpoints",
        "/XF", ".env", "*.pem", "*.key", "*.log", "*.tmp", "*.db", "*.sqlite", "*.sqlite3"
    )

    & robocopy @Args | Out-Host
    if ($LASTEXITCODE -gt 7) {
        throw "Manual test data sync failed with robocopy exit code $LASTEXITCODE."
    }
}

$TargetRoot = Resolve-GDriveTarget -RequestedTarget $Target
if ([System.IO.Path]::GetFullPath($TargetRoot) -eq $RepoRoot) {
    throw "Target must be different from the source repository."
}

New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null

$RequiredFiles = @(
    "notebooks\build-graph\yunesa_academic_kg_construction.ipynb",
    "notebooks\build-graph\yunesa_academic_graphrag_groq.ipynb",
    "notebooks\build-graph\yunesa_academic_graphrag_dev.ipynb",
    "notebooks\build-graph\src\yunesa_academic_kg.py",
    "notebooks\build-graph\ieee-thesaurus.ttl",
    "notebooks\build-graph\ieee-taxonomy.ttl",
    "notebooks\README.md"
)

$OptionalFiles = @(
    "notebooks\pyproject.toml",
    "notebooks\uv.lock"
)

if ($IncludeEnv) {
    Write-Warning "Including .env in Google Drive sync. Use this only for private Drive folders."
    $OptionalFiles += ".env"
}

Write-Host "Syncing KG notebook assets to Google Drive..."
Write-Host "  Source: $RepoRoot"
Write-Host "  Target: $TargetRoot"

$Results = @()
foreach ($RelativePath in $RequiredFiles) {
    $Results += Copy-RepoFile -RelativePath $RelativePath -TargetRoot $TargetRoot
}

foreach ($RelativePath in $OptionalFiles) {
    if (Test-Path -LiteralPath (Join-Path $RepoRoot $RelativePath)) {
        $Results += Copy-RepoFile -RelativePath $RelativePath -TargetRoot $TargetRoot
    }
}

if ($IncludeManualTestData) {
    Sync-ManualTestData -TargetRoot $TargetRoot
}

$Results | Format-Table -AutoSize

if (-not $SkipGwsApi) {
    $GwsSyncScript = Join-Path $PSScriptRoot "gws-sync-kg-notebook.mjs"
    if (Test-Path -LiteralPath $GwsSyncScript) {
        Write-Host ""
        Write-Host "Syncing KG notebook assets to Google Drive cloud via gws..."
        $GwsArgs = @(
            $GwsSyncScript,
            "--repo-root",
            $RepoRoot,
            "--root-folder-name",
            $DriveRootFolderName
        )
        if (-not [string]::IsNullOrWhiteSpace($DriveRootFolderId)) {
            $GwsArgs += @("--root-folder-id", $DriveRootFolderId)
        }

        & node @GwsArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Google Drive API sync failed with exit code $LASTEXITCODE. Local DriveFS sync may still have completed."
        }
    } else {
        Write-Warning "Missing gws sync helper: $GwsSyncScript"
    }
}

Write-Host "KG notebook sync completed."
