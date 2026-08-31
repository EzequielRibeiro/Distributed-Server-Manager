@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0cap.ps1" %*
exit /b %ERRORLEVEL%
