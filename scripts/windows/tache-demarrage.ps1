# CodeX KillFeed — tâche planifiée « au démarrage du PC »
#
# Lancé par installer.ps1 avec les droits administrateur (fenêtre UAC) :
# une tâche qui démarre AVANT l'ouverture de session (S4U = « exécuter même si
# l'utilisateur n'est pas connecté », sans enregistrer de mot de passe) ne peut
# être créée que par un administrateur.
#
# Écrit le résultat dans $Retour (« ok » ou le message d'erreur) : la fenêtre
# élevée se ferme toute seule, l'installeur lit ce fichier pour savoir.

param(
    [Parameter(Mandatory = $true)][string]$NomTache,
    [Parameter(Mandatory = $true)][string]$Racine,
    [Parameter(Mandatory = $true)][string]$Utilisateur,
    [Parameter(Mandatory = $true)][string]$Retour
)

$ErrorActionPreference = "Stop"
try {
    $vbs = Join-Path $Racine "scripts\windows\lancer-bot.vbs"
    $action   = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`"" -WorkingDirectory $Racine
    # Deux déclencheurs : au démarrage du PC (cas normal) + à l'ouverture de
    # session (relance si quelqu'un a arrêté le bot puis se reconnecte).
    # MultipleInstances IgnoreNew empêche deux bots en parallèle.
    $boot     = New-ScheduledTaskTrigger -AtStartup
    $boot.Delay = "PT1M"   # laisse le réseau se connecter
    $logon    = New-ScheduledTaskTrigger -AtLogOn -User $Utilisateur
    $reglages = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId $Utilisateur -LogonType S4U -RunLevel Limited
    Register-ScheduledTask -TaskName $NomTache -Action $action -Trigger @($boot, $logon) `
        -Settings $reglages -Principal $principal -Force | Out-Null
    [IO.File]::WriteAllText($Retour, "ok")
} catch {
    [IO.File]::WriteAllText($Retour, "$($_.Exception.Message)")
}
