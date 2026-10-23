# Build ELNOC as a single-click Windows desktop app
# Run in PowerShell from repo root: .\build_elnoc_onefile.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== ELNOC Desktop Build ===" -ForegroundColor Cyan
Set-Location $PSScriptRoot

# use Python 3.14
$py = "py"
& $py -V:3.14 -m pip install -r requirements-desktop.txt

Write-Host "`n[1/3] Cleaning previous build..." -ForegroundColor Yellow
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host "[2/3] Building single-folder app with PyInstaller..." -ForegroundColor Yellow
# Build as folder first (faster, less AV false positives). Can switch to --onefile later if desired.
& $py -V:3.14 -m PyInstaller `
  --name ELNOC `
  --windowed `
  --noconfirm `
  --add-data "app;app" `
  --add-data "templates;templates" `
  --add-data "static;static" `
  --add-data "data;data" `
  --add-data ".env;.env" `
  --hidden-import uvicorn.logging `
  --hidden-import uvicorn.loops `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols `
  --hidden-import uvicorn.protocols.http `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.lifespan `
  --hidden-import uvicorn.lifespan.on `
  --hidden-import webview `
  run_desktop.py

Write-Host "[3/3] Done" -ForegroundColor Green
Write-Host "`nOutput: .\dist\ELNOC\ELNOC.exe" -ForegroundColor Cyan
Write-Host "Create a desktop shortcut to that .exe — double click and it runs with no cmd window." -ForegroundColor Cyan
