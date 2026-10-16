@echo off
REM ELNOC Quick Log — Ctrl+Shift+L companion, no-install path (no AutoHotkey needed).
REM Opens the small desktop pane with the active window title as device hint.
REM To bind Ctrl+Shift+L to this file: right-click it > Create shortcut >
REM right-click the shortcut > Properties > Shortcut key > press Ctrl+Shift+L > OK.
REM (Pin the shortcut to taskbar/Start so the key works OS-wide.)
setlocal
if "%ELNOC_BASE_URL%"=="" set ELNOC_BASE_URL=http://noc-elnoc.local:8000
where pyw >nul 2>nul
if %errorlevel%==0 (
  pyw "%~dp0ELNOC_Pane.py"
  exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%~dp0ELNOC_Pane.py"
  exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ELNOC_QuickLog.ps1"
