@echo off
title CodeX KillFeed - Journal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\controle.ps1" -Action logs
