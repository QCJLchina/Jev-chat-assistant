param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv-windows-py312\Scripts\pythonw.exe"
$FrontendPath = Join-Path $PSScriptRoot "frontend"

function Test-FrontendBuildFresh {
    # 构建产物只有在晚于全部输入时才能复用：Vue/TS 源码、构建配置，以及
    # windows\locales —— frontend\src\i18n.ts 直接 import 那些 JSON，
    # 只改翻译而不重建会让界面停留在旧语言。返回 $true 表示可以复用。
    param([string]$Frontend)

    $index = Join-Path $Frontend "dist\index.html"
    if (-not (Test-Path -LiteralPath $index)) { return $false }
    $built = (Get-Item -LiteralPath $index).LastWriteTimeUtc

    $inputs = @()
    $src = Join-Path $Frontend "src"
    if (Test-Path -LiteralPath $src) {
        $inputs += Get-ChildItem -LiteralPath $src -Recurse -File -ErrorAction SilentlyContinue
    }
    foreach ($name in @(
        "package.json", "package-lock.json", "vite.config.ts", "index.html",
        "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json"
    )) {
        $candidate = Join-Path $Frontend $name
        if (Test-Path -LiteralPath $candidate) { $inputs += Get-Item -LiteralPath $candidate }
    }
    $locales = Join-Path $PSScriptRoot "locales"
    if (Test-Path -LiteralPath $locales) {
        $inputs += Get-ChildItem -LiteralPath $locales -Recurse -File -ErrorAction SilentlyContinue
    }

    if (-not $inputs) { return $false }
    $newest = ($inputs | Measure-Object -Property LastWriteTimeUtc -Maximum).Maximum
    # 时间戳相等视为新鲜，避免每次启动都触发一次构建。
    return -not ($newest -gt $built)
}

$frontendFresh = Test-FrontendBuildFresh -Frontend $FrontendPath

if ($CheckOnly) {
    if ($frontendFresh) {
        Write-Host "前端构建产物是最新的。"
        exit 0
    }
    Write-Host "前端构建产物已过期：windows\frontend\src、构建配置或 windows\locales 比 dist\index.html 新。请重新构建（windows\build.ps1 或 npm --prefix windows/frontend run build）。"
    exit 1
}

if (-not (Test-Path $PythonExe)) {
    throw "尚未安装依赖，请先运行 windows\install.ps1"
}

if (-not $frontendFresh) {
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        throw "前端需要重新构建，但未找到 npm.cmd。请安装 Node.js 20 或更高版本后重试。"
    }
    if (-not (Test-Path (Join-Path $FrontendPath "node_modules"))) {
        & npm.cmd ci --prefix $FrontendPath --cache (Join-Path $ProjectRoot ".npm-cache") --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Vue 前端依赖安装失败。" }
    }
    & npm.cmd --prefix $FrontendPath run build
    if ($LASTEXITCODE -ne 0) { throw "Vue 前端构建失败。" }
}

Start-Process -FilePath $PythonExe -ArgumentList (Join-Path $PSScriptRoot "run.pyw") -WorkingDirectory $ProjectRoot -WindowStyle Hidden
