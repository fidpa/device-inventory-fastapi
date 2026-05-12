@echo off
title Example Organization - Printers-Collection
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem '%~dp0' | Unblock-File" 2>nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0collect-printers.ps1"
echo.
echo   Press any key to close...
pause >nul
