$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv-windows-py312"

if (-not (Test-Path (Join-Path $VenvPath "Scripts\python.exe"))) {
    $PythonVersion = & python --version 2>&1
    if ($LASTEXITCODE -eq 0 -and "$PythonVersion" -match "Python 3\.12") {
        & python -m venv $VenvPath
    }
    elseif (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv venv --python 3.12 $VenvPath
    }
    if (-not (Test-Path (Join-Path $VenvPath "Scripts\python.exe"))) { throw "需要 PATH 中的 Python 3.12 或 uv 管理的 Python 3.12。" }
}

$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "未找到 Node.js/npm，请先安装 Node.js 20 或更高版本。"
}
$FrontendPath = Join-Path $PSScriptRoot "frontend"
$NpmCache = Join-Path $ProjectRoot ".npm-cache"
& npm.cmd ci --prefix $FrontendPath --cache $NpmCache --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw "Vue 前端依赖安装失败。" }
& npm.cmd --prefix $FrontendPath run build
if ($LASTEXITCODE -ne 0) { throw "Vue 前端构建失败。" }
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv pip install --python $PythonExe -r (Join-Path $PSScriptRoot "requirements.txt")
}
else {
    & $PythonExe -m ensurepip --upgrade
    & $PythonExe -m pip install --upgrade pip
    & $PythonExe -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
}
if ($LASTEXITCODE -ne 0) { throw "Python 依赖安装失败。" }

Write-Host "安装完成。运行：windows\start.ps1"

