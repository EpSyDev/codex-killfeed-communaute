@echo off
rem CodeX KillFeed - boucle de lancement (relance le bot s'il s'arrete)
set "RACINE=%~dp0..\.."
pushd "%RACINE%"
set "RACINE=%CD%"
if not exist "%RACINE%\data\logs" mkdir "%RACINE%\data\logs"

:boucle
rem Journal technique : on le vide quand il depasse 5 Mo
for %%F in ("%RACINE%\data\logs\console.log") do if %%~zF gtr 5000000 del "%%F"
"%RACINE%\venv\Scripts\python.exe" "%RACINE%\main.py" >> "%RACINE%\data\logs\console.log" 2>&1
rem Pause de 30 secondes avant de relancer (ping : timeout ne marche pas sans console)
ping -n 31 127.0.0.1 >nul
goto boucle
