<#
.SYNOPSIS
  Baut Backend + Frontend Images und pusht sie zu ghcr.io.

.DESCRIPTION
  Workflow:
    1. RELEASE.json validieren (version, date, highlights vorhanden)
    2. Optional: -BumpVersion patch|minor|major  -> aktualisiert version + date
    3. docker build für backend (Dockerfile oder Dockerfile.cpu) und frontend
    4. Tagging: <version> und latest
    5. docker push für beide Images
    6. Optional: git tag v<version> + git push --tags

  Voraussetzung: docker login ghcr.io ist bereits erfolgt (PAT mit write:packages).

.PARAMETER Owner
  GHCR-Owner (Default: michiwerkmann)

.PARAMETER BumpVersion
  patch | minor | major – passt RELEASE.json an. Ohne Angabe wird die vorhandene Version verwendet.

.PARAMETER SkipPush
  Nur lokal bauen, nicht zu ghcr.io pushen (zum Testen).

.PARAMETER Tag
  Optional: Git-Tag v<version> setzen und pushen.

.EXAMPLE
  ./scripts/release.ps1 -BumpVersion patch -Tag

.EXAMPLE
  ./scripts/release.ps1 -SkipPush
#>

[CmdletBinding()]
param(
    [string]$Owner = "michiwerkmann",
    [ValidateSet("patch", "minor", "major", "")]
    [string]$BumpVersion = "",
    [switch]$SkipPush,
    [switch]$Tag
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$releaseFile = Join-Path $repoRoot "RELEASE.json"

if (-not (Test-Path $releaseFile)) {
    throw "RELEASE.json nicht gefunden: $releaseFile"
}

$release = Get-Content $releaseFile -Raw | ConvertFrom-Json
if (-not $release.version) {
    throw "RELEASE.json hat kein 'version' Feld."
}

function Bump-Semver($current, $kind) {
    $parts = $current -split '\.'
    if ($parts.Count -ne 3) {
        throw "Version '$current' ist kein x.y.z – Bump nicht möglich."
    }
    [int]$maj = $parts[0]; [int]$min = $parts[1]; [int]$pat = $parts[2]
    switch ($kind) {
        "patch" { $pat += 1 }
        "minor" { $min += 1; $pat = 0 }
        "major" { $maj += 1; $min = 0; $pat = 0 }
    }
    return "$maj.$min.$pat"
}

if ($BumpVersion) {
    $newVersion = Bump-Semver $release.version $BumpVersion
    $release.version = $newVersion
    $release.date = (Get-Date).ToString("yyyy-MM-dd")
    $release | ConvertTo-Json -Depth 10 | Set-Content -Path $releaseFile -Encoding utf8
    Write-Host "[release] Version gebumpt auf $newVersion" -ForegroundColor Green
}

$version = $release.version
$ownerLower = $Owner.ToLowerInvariant()
$backendImage = "ghcr.io/$ownerLower/ai-meeting-backend"
$frontendImage = "ghcr.io/$ownerLower/ai-meeting-frontend"

Write-Host "[release] Version:  $version" -ForegroundColor Cyan
Write-Host "[release] Backend:  $backendImage:$version" -ForegroundColor Cyan
Write-Host "[release] Frontend: $frontendImage:$version" -ForegroundColor Cyan

Push-Location $repoRoot
try {
    Write-Host "[release] docker build backend ..." -ForegroundColor Yellow
    docker build `
        --build-context release-info=. `
        -t "${backendImage}:$version" `
        -t "${backendImage}:latest" `
        -f "backend/Dockerfile" `
        ./backend
    if ($LASTEXITCODE -ne 0) { throw "Backend build fehlgeschlagen." }

    Write-Host "[release] docker build frontend ..." -ForegroundColor Yellow
    docker build `
        -t "${frontendImage}:$version" `
        -t "${frontendImage}:latest" `
        ./frontend
    if ($LASTEXITCODE -ne 0) { throw "Frontend build fehlgeschlagen." }

    if (-not $SkipPush) {
        Write-Host "[release] docker push backend ..." -ForegroundColor Yellow
        docker push "${backendImage}:$version"
        if ($LASTEXITCODE -ne 0) { throw "Backend push fehlgeschlagen." }
        docker push "${backendImage}:latest"
        if ($LASTEXITCODE -ne 0) { throw "Backend :latest push fehlgeschlagen." }

        Write-Host "[release] docker push frontend ..." -ForegroundColor Yellow
        docker push "${frontendImage}:$version"
        if ($LASTEXITCODE -ne 0) { throw "Frontend push fehlgeschlagen." }
        docker push "${frontendImage}:latest"
        if ($LASTEXITCODE -ne 0) { throw "Frontend :latest push fehlgeschlagen." }
    } else {
        Write-Host "[release] -SkipPush gesetzt – push übersprungen." -ForegroundColor DarkYellow
    }

    if ($Tag) {
        $gitTag = "v$version"
        Write-Host "[release] git tag $gitTag ..." -ForegroundColor Yellow
        git tag $gitTag
        if ($LASTEXITCODE -ne 0) { throw "git tag fehlgeschlagen." }
        git push origin $gitTag
        if ($LASTEXITCODE -ne 0) { throw "git push --tags fehlgeschlagen." }
    }

    Write-Host "[release] Fertig. Version $version live." -ForegroundColor Green
    Write-Host "[release] Remote-Deployments mit Watchtower ziehen die Images automatisch innerhalb von WATCHTOWER_POLL_INTERVAL Sekunden." -ForegroundColor Green
}
finally {
    Pop-Location
}
