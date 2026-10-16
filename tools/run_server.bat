@echo off
REM ELNOC production server - single worker (SQLite). Run at startup via
REM Task Scheduler, or double-click for a foreground run.
REM Public/team URL is whichever front door you put in front (tunnel/VPN);
REM keep ELNOC_BASE_URL in .env pointing at it so message links resolve.
cd /d "%~dp0.."
py -V:3.14 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
