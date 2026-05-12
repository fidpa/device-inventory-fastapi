@echo off
title Example Organization - System information

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem '%~dp0' | Unblock-File" 2>nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0collect-sysinfo.ps1"
