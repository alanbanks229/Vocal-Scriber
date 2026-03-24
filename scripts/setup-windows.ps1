$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$venvDir = Join-Path $repoRoot ".venv"

if ($MyInvocation.InvocationName -ne ".") {
    Write-Host "Run this script with: . .\scripts\setup-windows.ps1"
    exit 1
}

Set-Location $repoRoot

function Test-PythonCommand {
    param(
        [string[]]$CommandParts
    )

    try {
        $args = @()
        if ($CommandParts.Length -gt 1) {
            $args += $CommandParts[1..($CommandParts.Length - 1)]
        }
        $args += @("-c", "import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
        $null = & $CommandParts[0] @args 2>$null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

if ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-PythonCommand @("py", "-3.11"))) {
    $pythonLauncher = @("py", "-3.11")
} elseif ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-PythonCommand @("py", "-3"))) {
    $pythonLauncher = @("py", "-3")
} elseif ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-PythonCommand @("python"))) {
    $pythonLauncher = @("python")
} else {
    Write-Error "Python 3.11+ is required but was not found."
    Write-Host "If you use the Windows launcher, install it with: py install 3.11"
}

if (-not (Test-Path $venvDir)) {
    Write-Host "Creating virtual environment in .venv ..."
    $pythonArgs = @()
    if ($pythonLauncher.Length -gt 1) {
        $pythonArgs += $pythonLauncher[1..($pythonLauncher.Length - 1)]
    }
    $pythonArgs += @("-m", "venv", $venvDir)
    & $pythonLauncher[0] @pythonArgs
} else {
    Write-Host "Using existing virtual environment in .venv ..."
}

$activateScript = Join-Path $venvDir "Scripts\Activate.ps1"
. $activateScript
python -m pip install --upgrade pip setuptools wheel
python -m pip install --upgrade torch --index-url https://download.pytorch.org/whl/cu130
python -m pip install --no-build-isolation -e ".[windows]"

Write-Host ""
Write-Host "Virtual environment is active."
Write-Host "Run the app with: python -m vocal_scriber --debug"
