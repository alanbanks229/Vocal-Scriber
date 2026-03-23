# Purpose:
# - Build the packaged Windows app for Vocal-Scriber.
# - Default behavior builds both the app bundle and, when available, the Inno Setup installer.
# - Use -BundleOnly during debugging when you want faster fail-fast iteration without waiting on installer compression.
param(
    [switch]$BundleOnly
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$assetsDir = Join-Path $repoRoot "build\windows-app\assets"
$specPath = Join-Path $repoRoot "packaging\windows\vocal_scriber_app.spec"
$innoScript = Join-Path $repoRoot "packaging\windows\VocalScriber.iss"
$innoCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)

if (-not (Test-Path $venvPython)) {
    Write-Error "No local .venv found. Run . .\scripts\setup-windows.ps1 first."
}

Set-Location $repoRoot

Write-Host "Generating Windows packaging assets..."
& $venvPython ".\packaging\windows\generate_assets.py" `
    --pyproject ".\pyproject.toml" `
    --output-dir $assetsDir

Write-Host "Checking build tooling..."
& $venvPython -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PyInstaller into .venv ..."
    & $venvPython -m pip install --upgrade pyinstaller
}

Write-Host "Building Vocal-Scriber Windows app bundle..."
& $venvPython -m PyInstaller --noconfirm --clean $specPath
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

if ($BundleOnly) {
    Write-Host ""
    Write-Host "Bundle-only mode enabled. Skipping Inno Setup installer build."
    Write-Host "App bundle: dist\Vocal-Scriber"
    return
}

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
$isccPath = $null
if ($iscc) {
    $isccPath = $iscc.Source
} else {
    foreach ($candidate in $innoCandidates) {
        if (Test-Path $candidate) {
            $isccPath = $candidate
            break
        }
    }
}

if ($isccPath) {
    Write-Host "Building Inno Setup installer..."
    & $isccPath $innoScript
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed."
    }
} else {
    Write-Host "Inno Setup compiler not found. App bundle was built, but installer was skipped."
    Write-Host "Install Inno Setup and rerun this script to generate the installer."
}

Write-Host ""
Write-Host "Windows app build complete."
Write-Host "App bundle: dist\Vocal-Scriber"
Write-Host "Installer:  dist\installer (if Inno Setup was available)"
