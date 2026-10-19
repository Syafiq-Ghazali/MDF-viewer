# Run from any directory: powershell -ExecutionPolicy Bypass -File .\tools\build.ps1
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install .[dev] first; see README.md.'
}
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -m PyInstaller --noconfirm --clean --windowed --onedir `
        --name MDFViewer --paths src --collect-data asammdf --collect-submodules chardet `
        --exclude-module asammdf.gui --exclude-module tkinter `
        --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
        run_viewer.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    Write-Host "Built: $projectRoot\dist\MDFViewer\MDFViewer.exe"
}
finally {
    Pop-Location
}
