$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv-windows"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    py -3.11 -m venv $VenvPath
}

& $PythonExe -m pip install -r (Join-Path $PSScriptRoot "requirements-dev.txt")
Push-Location $ProjectRoot
try {
    & $PythonExe -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name "Jev微信助手" `
        --paths $ProjectRoot `
        --collect-all rapidocr_onnxruntime `
        --collect-all uiautomation `
        --hidden-import win32timezone `
        (Join-Path $PSScriptRoot "run.pyw")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 构建失败（退出码 $LASTEXITCODE）。请先关闭正在运行的 Jev微信助手.exe 后重试。"
    }
}
finally {
    Pop-Location
}

Write-Host "构建完成：dist\Jev微信助手\Jev微信助手.exe"
