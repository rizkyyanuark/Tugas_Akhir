param(
    [string]$Target = "C:\tmp\Tugas_Akhir_Colab_KG"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$TargetRoot = [System.IO.Path]::GetFullPath($Target)
$TempRoot = [System.IO.Path]::GetFullPath("C:\tmp")
$BuildGraphTarget = Join-Path $TargetRoot "notebooks\build-graph"
$SrcTarget = Join-Path $BuildGraphTarget "src"

$RequiredFiles = @(
    "notebooks\build-graph\yunesa_academic_kg_construction.ipynb",
    "notebooks\build-graph\src\yunesa_academic_kg.py",
    "notebooks\build-graph\ieee-thesaurus.ttl",
    "notebooks\build-graph\ieee-taxonomy.ttl",
    "notebooks\README.md"
)

foreach ($RelativePath in $RequiredFiles) {
    $Source = Join-Path $RepoRoot $RelativePath
    if (-not (Test-Path $Source)) {
        throw "Required file is missing: $RelativePath"
    }
}

if ((Test-Path $TargetRoot) -and $TargetRoot.StartsWith($TempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    Remove-Item -LiteralPath $TargetRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $SrcTarget | Out-Null

Copy-Item -LiteralPath (Join-Path $RepoRoot "notebooks\build-graph\yunesa_academic_kg_construction.ipynb") -Destination $BuildGraphTarget
Copy-Item -LiteralPath (Join-Path $RepoRoot "notebooks\build-graph\src\yunesa_academic_kg.py") -Destination $SrcTarget
Copy-Item -LiteralPath (Join-Path $RepoRoot "notebooks\build-graph\ieee-thesaurus.ttl") -Destination $BuildGraphTarget
Copy-Item -LiteralPath (Join-Path $RepoRoot "notebooks\build-graph\ieee-taxonomy.ttl") -Destination $BuildGraphTarget
Copy-Item -LiteralPath (Join-Path $RepoRoot "notebooks\README.md") -Destination (Join-Path $TargetRoot "README.md")

$ReadmePath = Join-Path $TargetRoot "COLAB_USAGE.md"
$ColabUsageLines = @(
    "# YUNESA Academic KG - Google Drive Bundle",
    "",
    "Upload/copy this folder to Google Drive as:",
    "",
    "````text",
    "MyDrive/Tugas_Akhir/",
    "````",
    "",
    "Expected structure:",
    "",
    "````text",
    "MyDrive/Tugas_Akhir/",
    "  notebooks/",
    "    build-graph/",
    "      yunesa_academic_kg_construction.ipynb",
    "      ieee-thesaurus.ttl",
    "      ieee-taxonomy.ttl",
    "      src/",
    "        yunesa_academic_kg.py",
    "````",
    "",
    "In Colab Secrets, add:",
    "",
    "- ``SUPABASE_URL``",
    "- ``SUPABASE_SERVICE_ROLE_KEY`` or ``SUPABASE_KEY``",
    "",
    "Do not upload ``.env`` or API keys to Google Drive.",
    "",
    "If your Drive folder is not ``MyDrive/Tugas_Akhir``, run this before the notebook bootstrap cell:",
    "",
    "````python",
    "import os",
    "os.environ[`"YUNESA_PROJECT_DIR`"] = `"/content/drive/MyDrive/YOUR_FOLDER_NAME`"",
    "````"
)
Set-Content -LiteralPath $ReadmePath -Value $ColabUsageLines -Encoding UTF8

$ZipPath = "$TargetRoot.zip"
if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path (Join-Path $TargetRoot "*") -DestinationPath $ZipPath -Force

Write-Host "Colab KG bundle prepared:"
Write-Host "  Folder: $TargetRoot"
Write-Host "  Zip:    $ZipPath"
