$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv-windows\Scripts\pythonw.exe"

if (-not (Test-Path $PythonExe)) {
    throw "尚未安装依赖，请先运行 windows\install.ps1"
}

Start-Process -FilePath $PythonExe -ArgumentList (Join-Path $PSScriptRoot "run.pyw") -WorkingDirectory $ProjectRoot -WindowStyle Hidden

