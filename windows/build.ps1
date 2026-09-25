$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv-windows-py312"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$FrontendPath = Join-Path $PSScriptRoot "frontend"
$NpmCache = Join-Path $ProjectRoot ".npm-cache"

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "未找到 Node.js/npm，请先安装 Node.js 20 或更高版本。"
}
& npm.cmd ci --prefix $FrontendPath --cache $NpmCache --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw "Vue 前端依赖安装失败。" }
& npm.cmd --prefix $FrontendPath run build
if ($LASTEXITCODE -ne 0) { throw "Vue 前端构建失败。" }

if (-not (Test-Path $PythonExe)) {
    $PythonVersion = & python --version 2>&1
    if ($LASTEXITCODE -eq 0 -and "$PythonVersion" -match "Python 3\.12") {
        & python -m venv $VenvPath
    }
    elseif (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv venv --python 3.12 $VenvPath
    }
    if (-not (Test-Path $PythonExe)) { throw "需要 PATH 中的 Python 3.12 或 uv 管理的 Python 3.12。" }
}

if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv pip install --python $PythonExe -r (Join-Path $PSScriptRoot "requirements-dev.txt")
}
else {
    & $PythonExe -m ensurepip --upgrade
    & $PythonExe -m pip install -r (Join-Path $PSScriptRoot "requirements-dev.txt")
}
if ($LASTEXITCODE -ne 0) { throw "Python 构建依赖安装失败。" }
Push-Location $ProjectRoot
try {
    & $PythonExe -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name "Jev对话助手" `
        --paths $ProjectRoot `
        --paths $PSScriptRoot `
        --collect-all rapidocr_onnxruntime `
        --collect-all uiautomation `
        --collect-all webview `
        --add-data "$(Join-Path $FrontendPath 'dist');frontend\dist" `
        --add-data "$(Join-Path $PSScriptRoot 'locales');locales" `
        --hidden-import webview.platforms.edgechromium `
        --hidden-import win32timezone `
        (Join-Path $PSScriptRoot "run.pyw")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 构建失败（退出码 $LASTEXITCODE）。请先关闭正在运行的 Jev对话助手.exe 后重试。"
    }
}
finally {
    Pop-Location
}

Write-Host "构建完成：dist\Jev对话助手\Jev对话助手.exe"
