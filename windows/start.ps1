$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv-windows-py312\Scripts\pythonw.exe"
$FrontendPath = Join-Path $PSScriptRoot "frontend"

if (-not (Test-Path $PythonExe)) {
    throw "尚未安装依赖，请先运行 windows\install.ps1"
}

if (-not (Test-Path (Join-Path $FrontendPath "dist\index.html"))) {
    if (-not (Test-Path (Join-Path $FrontendPath "node_modules"))) {
        & npm.cmd ci --prefix $FrontendPath --cache (Join-Path $ProjectRoot ".npm-cache") --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Vue 前端依赖安装失败。" }
    }
    & npm.cmd --prefix $FrontendPath run build
    if ($LASTEXITCODE -ne 0) { throw "Vue 前端构建失败。" }
}

Start-Process -FilePath $PythonExe -ArgumentList (Join-Path $PSScriptRoot "run.pyw") -WorkingDirectory $ProjectRoot -WindowStyle Hidden

