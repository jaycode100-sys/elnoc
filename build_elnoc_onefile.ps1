# Build ELNOC as a single-click Windows desktop app
# Run in PowerShell from repo root: .\build_elnoc_onefile.ps1
# (If execution policy blocks it: powershell -ExecutionPolicy Bypass -File .\build_elnoc_onefile.ps1)
#
# Output: dist\ELNOC.exe   (one file - send this to a friend; they double-click and ELNOC opens)
#
# For a true installer (Start Menu shortcut + uninstaller, like Spotify/Telegram),
# see build_elnoc_installer.ps1 which wraps this .exe in Inno Setup.

$ErrorActionPreference = "Stop"

Write-Host "=== ELNOC Desktop Build (single-file) ===" -ForegroundColor Cyan
Set-Location $PSScriptRoot

$py = "py"
# Redirect inside cmd so pip's stderr chatter (upgrade notices etc.) can never
# trip $ErrorActionPreference = "Stop" in Windows PowerShell 5.1.
cmd /c "py -m pip install -r requirements-desktop.txt >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: pip install had issues; continuing anyway..." -ForegroundColor Yellow
}

Write-Host "`n[1/3] Cleaning previous build..." -ForegroundColor Yellow
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host "[2/3] Building single-file ELNOC.exe with PyInstaller..." -ForegroundColor Yellow
# --onefile bundles everything into ONE .exe. Extracts to a temp folder on run.
py make_version.py
& $py -m PyInstaller `
  --name ELNOC `
  --onefile `
  --windowed `
  --icon ELNOC.ico `
  --version-file version_elnoc.txt `
  --noconfirm `
  --add-data "app;app" `
  --add-data "data;data" `
  --add-data ".env;.env" `
  --add-data "ELNOC.ico;." `
  --add-data "ELNOC.png;." `
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

if (-not (Test-Path "dist\ELNOC.exe")) {
    Write-Host "PyInstaller build FAILED." -ForegroundColor Red
    exit 1
}

$appData = [Environment]::GetFolderPath("LocalApplicationData")
Write-Host "[3/3] Done" -ForegroundColor Green
Write-Host "`nOutput: .\dist\ELNOC.exe" -ForegroundColor Cyan
Write-Host "Send this single .exe to a friend - they double-click and ELNOC opens (no install, no cmd window)." -ForegroundColor Cyan
Write-Host "First run copies the database to $appData\ELNOC\elnoc.db so SQLite can write." -ForegroundColor Yellow
# Explicit success: anything else lets PyInstaller's unreliable exit code bubble
# up to the calling script (which treats non-zero as catastrophic).
exit 0
