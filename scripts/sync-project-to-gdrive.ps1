param(
    [string]$Target = "G:\My Drive\Tugas_Akhir"
)

$ErrorActionPreference = "Stop"

$SourceRoot = [System.IO.Path]::GetFullPath((Resolve-Path (Join-Path $PSScriptRoot "..")))
$TargetRoot = [System.IO.Path]::GetFullPath($Target)

if ($TargetRoot -eq $SourceRoot) {
    throw "Target must be different from the source repository."
}

New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null

$RootExcludedDirs = @(
    ".git",
    ".vscode",
    ".idea",
    ".codex",
    ".cursor",
    ".trae",
    ".qoder",
    ".claude",
    ".vibe",
    ".antigravitycli",
    "AWS",
    "cloudflared",
    ".uv-cache",
    ".hf_cache",
    ".cache",
    "cache",
    "data",
    "saves",
    "saves_dev",
    "models",
    "docker\volumes",
    "neo4j_data",
    "neo4j_logs",
    "neo4j_plugins",
    "neo4j_import",
    "logs",
    "log",
    "tmp",
    "temp",
    "notebooks\.venv",
    "notebooks\build-graph\lancedb_store",
    "notebooks\build-graph\test_lancedb",
    "notebooks\scraping\pipeline_cells",
    "notebooks\scraping\rps_pdfs",
    "academicRAG",
    "strwythura",
    "temp_yuxi_clone",
    "scratch_yuxi"
) | ForEach-Object { Join-Path $SourceRoot $_ }

$NameExcludedDirs = @(
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".ipynb_checkpoints",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "wheels"
)

$ExcludeDirs = @($RootExcludedDirs + $NameExcludedDirs)

$ExcludeFiles = @(
    ".env",
    ".env.local",
    ".env.prod",
    ".env.test",
    ".env.*.local",
    ".bashrc",
    ".bash_profile",
    ".boto",
    ".claude.json",
    ".gitconfig",
    "mup.xml",
    "*.pem",
    "*.key",
    "credentials.json",
    "credentials_new.json",
    "key_base64_for_gitlab.txt",
    "airflow_variables_import.json",
    "kg.env",
    "*.secret*",
    "*.nogit*",
    "*_private",
    "*.private",
    "*.log",
    "*.log.*",
    "*.tmp",
    "*.temp",
    "*.bak",
    "*.backup",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.gguf",
    "*.bin",
    "*.safetensors",
    "*.h5",
    "*.pt",
    "*.pth",
    "kg_export.json",
    "Thumbs.db",
    ".DS_Store",
    "desktop.ini",
    "*.aux",
    "*.out",
    "*.toc",
    "*.lof",
    "*.lot",
    "*.bbl",
    "*.blg",
    "*.synctex",
    "*.synctex.gz",
    "*.fdb_latexmk",
    "*.fls"
)

$RoboArgs = @(
    $SourceRoot,
    $TargetRoot,
    "/E",
    "/FFT",
    "/R:2",
    "/W:2",
    "/NP",
    "/XD"
) + $ExcludeDirs + @("/XF") + $ExcludeFiles

Write-Host "Syncing project to Google Drive..."
Write-Host "  Source: $SourceRoot"
Write-Host "  Target: $TargetRoot"

& robocopy @RoboArgs
$ExitCode = $LASTEXITCODE

if ($ExitCode -gt 7) {
    throw "Robocopy failed with exit code $ExitCode."
}

Write-Host "Sync completed. Robocopy exit code: $ExitCode"
