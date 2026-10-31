# Build the ELNOC Windows installer with Inno Setup
# Run in PowerShell from repo root: .\build_elnoc_installer.ps1
# (If execution policy blocks it: powershell -ExecutionPolicy Bypass -File .\build_elnoc_installer.ps1)
#
# Output: Output\ELNOC-Setup.exe  (Start Menu shortcut + uninstaller, like Spotify/Telegram)
#
# Requires:
#   - Python + PyInstaller   (produces dist\ELNOC.exe, see build_elnoc_onefile.ps1)
#   - Inno Setup 6           (ISCC.exe, auto-detected; install via: winget install -e JRSoftware.InnoSetup)

# PS 5.1 quirk: with ErrorActionPreference=Stop, ANY stderr line from a child
# process becomes a terminating error (even when 2>$null is applied). PyInstaller
# and pip both chatter to stderr, so we run with Continue and verify outcomes
# explicitly via $LASTEXITCODE / file existence instead.
$ErrorActionPreference = "Continue"

Write-Host "=== ELNOC Installer Build (Inno Setup) ===" -ForegroundColor Cyan
Set-Location $PSScriptRoot

# [1/2] Ensure dist\ELNOC.exe exists (build it first if missing)
if (-not (Test-Path "dist\ELNOC.exe")) {
    Write-Host "[1/2] dist\ELNOC.exe missing - running PyInstaller build..." -ForegroundColor Yellow
    & powershell -ExecutionPolicy Bypass -File ".\build_elnoc_onefile.ps1" 2>$null
    # PyInstaller sometimes returns a non-zero exit code despite completing;
    # the authoritative check is whether the exe exists.
    if (-not (Test-Path "dist\ELNOC.exe")) {
        Write-Host "PyInstaller build FAILED." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[1/2] dist\ELNOC.exe already exists - skipping PyInstaller build." -ForegroundColor Yellow
}

# Sign the PyInstaller executable before it gets embedded in the installer
& powershell -ExecutionPolicy Bypass -File ".\sign_elnoc.ps1" -Files "dist\ELNOC.exe" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Signing dist\ELNOC.exe FAILED. Run .\sign_elnoc.ps1 to see details." -ForegroundColor Red
    exit 1
}

# [2/2] Compile the installer with Inno Setup's command-line compiler
Write-Host "[2/2] Compiling installer with Inno Setup..." -ForegroundColor Yellow
$isccCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 5\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Host "Inno Setup not found. Install it with:  winget install -e JRSoftware.InnoSetup" -ForegroundColor Red
    exit 1
}

& $iscc "build_elnoc_installer.iss"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Inno Setup compile FAILED." -ForegroundColor Red
    exit 1
}

# Sign the final installer
& powershell -ExecutionPolicy Bypass -File ".\sign_elnoc.ps1" -Files "Output\ELNOC-Setup.exe" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Signing Output\ELNOC-Setup.exe FAILED. Run .\sign_elnoc.ps1 to see details." -ForegroundColor Red
    exit 1
}

Write-Host "[2/2] Done" -ForegroundColor Green
Write-Host "`nOutput: .\Output\ELNOC-Setup.exe" -ForegroundColor Cyan
Write-Host "Includes Start Menu shortcut, optional desktop icon, and an uninstaller." -ForegroundColor Cyan
Write-Host "The app itself seeds %LOCALAPPDATA%\ELNOC\elnoc.db on first run." -ForegroundColor Yellow
