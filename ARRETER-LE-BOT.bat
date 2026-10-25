@echo off
title CodeX KillFeed - Arreter
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\controle.ps1" -Action arreter
echo.
pause
