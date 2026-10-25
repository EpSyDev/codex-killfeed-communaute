@echo off
title CodeX KillFeed - Demarrer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\controle.ps1" -Action demarrer
echo.
pause
