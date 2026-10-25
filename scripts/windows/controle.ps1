# CodeX KillFeed — démarrer / arrêter / voir les journaux (Windows)
param(
    [Parameter(Mandatory = $true)][ValidateSet("demarrer", "arreter", "logs")][string]$Action,
    [string]$NomTache = "CodeX KillFeed"
)

$Racine = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Arreter-Bot {
    if (Get-ScheduledTask -TaskName $NomTache -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $NomTache -ErrorAction SilentlyContinue
    }
    Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*lancer-bot.bat*" -and $_.CommandLine -like "*$Racine*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$Racine\main.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

switch ($Action) {
    "arreter" {
        Arreter-Bot
        Write-Host "Le bot est arrêté. Il redémarrera au prochain démarrage du PC ou de ta session Windows," -ForegroundColor Yellow
        Write-Host "ou quand tu lanceras DEMARRER-LE-BOT.bat."
    }
    "demarrer" {
        if (-not (Get-ScheduledTask -TaskName $NomTache -ErrorAction SilentlyContinue)) {
            Write-Host "Le bot n'est pas encore installé : lance d'abord INSTALLER-WINDOWS.bat." -ForegroundColor Red
            exit 1
        }
        Arreter-Bot
        # Tâche « au démarrage du PC » créée en administrateur : un compte
        # standard peut ne pas avoir le droit de la lancer → lancement direct.
        try { Start-ScheduledTask -TaskName $NomTache -ErrorAction Stop }
        catch {
            $vbs = Join-Path $Racine "scripts\windows\lancer-bot.vbs"
            Start-Process "wscript.exe" -ArgumentList "`"$vbs`"" -WorkingDirectory $Racine
        }
        Write-Host "Le bot démarre (compte 20 secondes avant qu'il soit en ligne sur Discord)." -ForegroundColor Green
    }
    "logs" {
        $log = Join-Path $Racine "data\logs\bot.log"
        if (-not (Test-Path $log)) { Write-Host "Aucun journal pour l'instant : le bot n'a jamais démarré." -ForegroundColor Yellow; exit 0 }
        Write-Host "Journal du bot en direct. Pour quitter : ferme cette fenêtre (ou Ctrl+C)." -ForegroundColor Cyan
        Write-Host ""
        Get-Content $log -Tail 40 -Wait -Encoding UTF8
    }
}
