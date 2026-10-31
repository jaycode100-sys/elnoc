@echo off
:: ELNOC launcher — runs without a console window
:: Double-click this file to start ELNOC desktop app.
:: Uses pythonw.exe so no cmd window flashes.

setlocal
set "REPO_DIR=%~dp0"
cd /d "%REPO_DIR%"

:: Try the built one-file exe first (no Python needed at all)
if exist "dist\ELNOC.exe" (
    start "" "dist\ELNOC.exe"
    exit /b
)

:: Fall back to pythonw (no console window) if exe not built
if exist "run_desktop.py" (
    pythonw run_desktop.py
    exit /b
)

echo ELNOC not found. Build first: .\build_elnoc_onefile.ps1
pause
