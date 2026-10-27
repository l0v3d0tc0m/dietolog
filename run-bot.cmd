@echo off
rem Starts the ingest server and the Telegram bot. Close this window to stop them.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -m app.main
echo.
echo Bot stopped.
pause
