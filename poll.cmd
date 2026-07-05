@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_task.ps1" run_poll.py
exit /b %ERRORLEVEL%