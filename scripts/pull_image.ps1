param(
    [Parameter(Mandatory=$true)]
    [string]$ImageTag
)

$ErrorActionPreference = "Stop"

Write-Host "Pulling image: $ImageTag" -ForegroundColor Green

$slashCount = ($ImageTag -split '/' | Measure-Object).Count - 1

switch ($slashCount) {
    0 {
        $mirrorUrl = "m.daocloud.io/docker.io/library"
        Write-Host "Image format: Official image (no prefix)" -ForegroundColor Cyan
    }
    1 {
        $mirrorUrl = "m.daocloud.io/docker.io"
        Write-Host "Image format: Hub repository (one prefix)" -ForegroundColor Cyan
    }
    default {
        $mirrorUrl = "m.daocloud.io"
        Write-Host "Image format: Third-party registry (multiple prefixes)" -ForegroundColor Cyan
    }
}

$fullMirrorUrl = "$mirrorUrl/$ImageTag"
Write-Host "Mirror URL: $fullMirrorUrl" -ForegroundColor Yellow

try {
    Write-Host "Step 1: Pulling image from mirror..." -ForegroundColor Blue
    docker pull $fullMirrorUrl

    Write-Host "Step 2: Tagging image with original name..." -ForegroundColor Blue
    docker tag $fullMirrorUrl $ImageTag

    Write-Host "Step 3: Removing mirror tag..." -ForegroundColor Blue
    docker rmi $fullMirrorUrl

    Write-Host "`nProcess completed successfully!" -ForegroundColor Green
} catch {
    Write-Host "`nError occurred: $_" -ForegroundColor Red
    exit 1
}
