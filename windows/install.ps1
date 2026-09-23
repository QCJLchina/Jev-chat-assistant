$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv-windows"

if (-not (Test-Path (Join-Path $VenvPath "Scripts\python.exe"))) {
    py -3.11 -m venv $VenvPath
}

$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")

Write-Host "安装完成。运行：windows\start.ps1"

