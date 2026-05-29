$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $ProjectRoot

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

if (-not (Test-Path ".\config.yml")) {
    Write-Host "config.yml was not found." -ForegroundColor Yellow
    Write-Host "Copy config.example.yml to config.yml, then edit MuMu path, ADB serial, and launch options."
    Write-Host ""
    Write-Host "PowerShell example:"
    Write-Host "  Copy-Item .\config.example.yml .\config.yml"
    exit 1
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Step "Create Python virtual environment .venv"
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        & py -3.11 -m venv .venv
    } else {
        & python -m venv .venv
    }
}

if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment creation failed: $VenvPython was not found"
}

Write-Step "Install/update Python dependencies"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt
& $VenvPython -m pip install -e .

Write-Step "Download external assets"
& $VenvPython -m bangdream_yolo.tools.fetch_assets

Write-Step "Check runtime environment"
& $VenvPython -m bangdream_yolo.tools.check_env

Write-Step "Check startup files"
& $VenvPython -m bangdream_yolo.tools.check_startup

Write-Step "Launch BangDream YOLO"
& $VenvPython -m bangdream_yolo.tools.launch
