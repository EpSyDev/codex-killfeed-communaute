# CodeX KillFeed — installation ou mise à jour sur Windows
#
# Lancé par INSTALLER-WINDOWS.bat (double-clic). Rejouable sans risque :
# ne touche jamais à un .env, une base ou des données déjà présents.
#
# Paramètres réservés aux tests : -DiscordToken -NitradoToken -ServiceId
# -SansVerification -SansTache -NomTache

param(
    [string]$DiscordToken = "",
    [string]$NitradoToken = "",
    [string]$ServiceId    = "",
    [switch]$SansVerification,
    [switch]$SansTache,
    [string]$NomTache = "CodeX KillFeed"
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Racine = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$UA     = "CodeXKillFeed-installateur/1.0"

function Etape($t)  { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Ok($t)     { Write-Host "  [OK] $t" -ForegroundColor Green }
function Info($t)   { Write-Host "  $t" }
function Avert($t)  { Write-Host "  [!] $t" -ForegroundColor Yellow }
function Echec($t)  {
    Write-Host ""
    Write-Host "  [ERREUR] $t" -ForegroundColor Red
    Write-Host ""
    exit 1
}

# Lance une commande externe sans que ses messages d'erreur fassent planter le script
function Executer([string]$exe, [string[]]$arguments) {
    $ancien = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    # Out-Host : le texte s'affiche à l'écran mais n'est PAS renvoyé par la fonction
    # (sinon $code contiendrait tout le texte au lieu du seul code de retour)
    try { & $exe @arguments | Out-Host; return $LASTEXITCODE }
    finally { $ErrorActionPreference = $ancien }
}

function Lire-Secret([string]$question) {
    $s = Read-Host $question -AsSecureString
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b).Trim().Trim('"') }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

Write-Host ""
Write-Host "  CodeX KillFeed — installation sur Windows" -ForegroundColor White
Write-Host "  Dossier : $Racine"

# ── 0. Le dossier est-il au bon endroit ? ───────────────────────────────────
Etape "Vérification du dossier"
if ($Racine -match "OneDrive") {
    Echec "Le dossier est dans OneDrive, qui synchronise le fichier de données en continu et peut le corrompre.`n  Déplace tout le dossier à la racine du disque (par exemple C:\codex-killfeed-communaute), puis relance."
}
if ($Racine -notmatch '^[\x20-\x7E]+$') {
    Echec "Le chemin du dossier contient des accents ou des caractères spéciaux.`n  Déplace tout le dossier à la racine du disque (par exemple C:\codex-killfeed-communaute), puis relance."
}
Ok "Dossier correct"

# ── 1. Python ───────────────────────────────────────────────────────────────
Etape "Recherche de Python (version 3.10 ou plus récente)"
function Trouver-Python {
    $candidats = @(
        @("py", "-3.12"), @("py", "-3.13"), @("py", "-3.11"), @("py", "-3.10"),
        @("py", "-3"), @("python")
    )
    foreach ($c in $candidats) {
        $exe = $c[0]
        $pArgs = @()
        if ($c.Count -gt 1) { $pArgs = @($c[1..($c.Count - 1)]) }
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $ancien = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $v = & $exe @pArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            $code = $LASTEXITCODE
        } catch { $code = 1 }
        finally { $ErrorActionPreference = $ancien }
        if ($code -eq 0 -and "$v" -match '^3\.(\d+)$' -and [int]$Matches[1] -ge 10) {
            return @{ Exe = $exe; Args = $pArgs; Version = "$v" }
        }
    }
    return $null
}
$py = Trouver-Python
if (-not $py) {
    Echec "Python est introuvable.`n  Installe Python 3.13 (voir l'étape 3 du guide : commande winget, ou python.org),`n  puis relance INSTALLER-WINDOWS.bat."
}
Ok "Python $($py.Version) trouvé"

# ── 2. Environnement et dépendances ─────────────────────────────────────────
Etape "Installation des dépendances (1 à 3 minutes, beaucoup de texte va défiler)"
$venvPy = Join-Path $Racine "venv\Scripts\python.exe"

# Arrêt d'une éventuelle ancienne version en cours d'exécution (cas d'une mise à jour)
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
Arreter-Bot

if (-not (Test-Path $venvPy)) {
    $code = Executer $py.Exe ($py.Args + @("-m", "venv", (Join-Path $Racine "venv")))
    if ($code -ne 0 -or -not (Test-Path $venvPy)) { Echec "Impossible de créer l'environnement Python." }
}
$code = Executer $venvPy @("-m", "pip", "install", "--disable-pip-version-check", "--quiet", "--upgrade", "pip")
$code = Executer $venvPy @("-m", "pip", "install", "--disable-pip-version-check", "-r", (Join-Path $Racine "requirements.txt"))
if ($code -ne 0) {
    Echec "L'installation des dépendances a échoué.`n  Vérifie ta connexion Internet. Si ton Python est très récent (3.15 ou plus), installe plutôt Python 3.13 (voir l'étape 3 du guide), puis relance."
}
Ok "Dépendances installées"

# ── 3. Configuration (.env) ─────────────────────────────────────────────────
Etape "Configuration"
$envFile = Join-Path $Racine ".env"

function Verifier-Discord([string]$token) {
    try {
        $r = Invoke-RestMethod -Uri "https://discord.com/api/v10/users/@me" -UserAgent $UA `
             -Headers @{ Authorization = "Bot $token" } -TimeoutSec 20
        return $r
    } catch { return $null }
}
function Verifier-Nitrado([string]$token, [string]$id) {
    try {
        Invoke-RestMethod -Uri "https://api.nitrado.net/services/$id/gameservers" -UserAgent $UA `
            -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 20 | Out-Null
        return $true
    } catch { return $false }
}

if (Test-Path $envFile) {
    Avert ".env déjà présent : conservé tel quel (tes tokens ne sont pas redemandés)."
} else {
    Info "Colle tes identifiants quand on te les demande."
    Info "Tu verras des étoiles (*) ou rien du tout : c'est normal. Colle, puis appuie sur Entrée."
    Write-Host ""

    $bot = $null
    while ($true) {
        if (-not $DiscordToken) { $DiscordToken = Lire-Secret "Token du bot Discord" }
        if ($SansVerification) { break }
        $bot = Verifier-Discord $DiscordToken
        if ($bot) { Ok "Token Discord valide (bot : $($bot.username))"; break }
        Write-Host "  [X] Token refusé par Discord. Recopie-le (Developer Portal > Bot > Reset Token)." -ForegroundColor Red
        $DiscordToken = ""
    }

    while ($true) {
        if (-not $NitradoToken) { $NitradoToken = Lire-Secret "Token Nitrado long-life" }
        if (-not $ServiceId)    { $ServiceId = (Read-Host "ID de service Nitrado (le nombre dans l'adresse de ton serveur)") -replace '[^0-9]', '' }
        if ($SansVerification) { break }
        if (Verifier-Nitrado $NitradoToken $ServiceId) { Ok "Accès Nitrado valide"; break }
        Write-Host "  [X] Nitrado refuse ce couple token / ID de service. Vérifie les deux." -ForegroundColor Red
        $NitradoToken = ""; $ServiceId = ""
    }

    $contenu = @(
        "# CodeX KillFeed - configuration (ne partage JAMAIS ce fichier)",
        "DISCORD_TOKEN=$DiscordToken",
        "NITRADO_TOKEN=$NitradoToken",
        "NITRADO_SERVER_ID=$ServiceId",
        "LOG_LEVEL=INFO",
        ""
    ) -join "`r`n"
    # UTF-8 SANS BOM : un BOM casserait le nom de la première variable
    [IO.File]::WriteAllText($envFile, $contenu, (New-Object Text.UTF8Encoding($false)))
    Ok ".env créé"

    # Les deux options Discord qui font refuser le démarrage si elles sont éteintes
    if ($bot) {
        try {
            $app = Invoke-RestMethod -Uri "https://discord.com/api/v10/oauth2/applications/@me" -UserAgent $UA `
                   -Headers @{ Authorization = "Bot $DiscordToken" } -TimeoutSec 20
            $f = [int64]$app.flags
            $membres = (($f -band 16384) -ne 0) -or (($f -band 32768) -ne 0)
            $contenuMsg = (($f -band 262144) -ne 0) -or (($f -band 524288) -ne 0)
            if (-not $membres -or -not $contenuMsg) {
                Avert "Sur le Discord Developer Portal (page Bot), il faut activer :"
                if (-not $membres)    { Avert "   - SERVER MEMBERS INTENT" }
                if (-not $contenuMsg) { Avert "   - MESSAGE CONTENT INTENT" }
                Avert "   puis cliquer sur Save Changes. Sans ça, le bot refusera de démarrer."
            } else {
                Ok "Options Discord (Privileged Gateway Intents) activées"
            }
        } catch { }
    }
}

# ── 4. Dossiers de données ──────────────────────────────────────────────────
New-Item -ItemType Directory -Force (Join-Path $Racine "data\logs") | Out-Null

if ($SansTache) { Etape "Terminé (mode test, pas de démarrage automatique)"; exit 0 }

# ── 5. Démarrage automatique avec Windows ───────────────────────────────────
Etape "Démarrage automatique avec Windows"
$bat = Join-Path $Racine "scripts\windows\lancer-bot.bat"
$vbs = Join-Path $Racine "scripts\windows\lancer-bot.vbs"
# Le .vbs lance le .bat sans afficher de fenêtre noire
$vbsTexte = 'CreateObject("Wscript.Shell").Run "cmd /c """"' + $bat + '""""", 0, False'
[IO.File]::WriteAllText($vbs, $vbsTexte, [Text.Encoding]::ASCII)

$utilisateur = "$env:USERDOMAIN\$env:USERNAME"

# Option : démarrage dès l'allumage du PC, sans ouvrir de session (utile après
# une coupure de courant ou une mise à jour Windows qui redémarre la nuit).
# Demande les droits administrateur → fenêtre de confirmation Windows (UAC).
Info "Par défaut, le bot démarre quand tu ouvres ta session Windows."
Info "Option : le démarrer dès l'allumage du PC, même sans ouvrir de session"
Info "(conseillé si le PC redémarre seul : coupure de courant, mises à jour Windows)."
$auBoot = $false
$rep = Read-Host "Démarrer le bot dès l'allumage du PC ? Windows va demander une confirmation administrateur (O/N)"
if ($rep -match '^[oOyY]') {
    $retour = Join-Path $env:TEMP "codex-tache-$([guid]::NewGuid().ToString('N')).txt"
    $script = Join-Path $Racine "scripts\windows\tache-demarrage.ps1"
    try {
        Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$script`"",
            "-NomTache", "`"$NomTache`"", "-Racine", "`"$Racine`"",
            "-Utilisateur", "`"$utilisateur`"", "-Retour", "`"$retour`""
        )
        $res = if (Test-Path $retour) { (Get-Content $retour -Raw).Trim() } else { "aucune réponse" }
        Remove-Item $retour -ErrorAction SilentlyContinue
        if ($res -eq "ok") { $auBoot = $true }
        else { Avert "Démarrage à l'allumage impossible ($res)." }
    } catch {
        Avert "Confirmation administrateur refusée."
    }
    if (-not $auBoot) { Avert "On garde le démarrage à l'ouverture de session." }
}

if ($auBoot) {
    Ok "Le bot démarrera tout seul à chaque allumage du PC (1 minute après), même sans session ouverte"
} else {
    $action    = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`"" -WorkingDirectory $Racine
    $declencheur = New-ScheduledTaskTrigger -AtLogOn -User $utilisateur
    $reglages  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                 -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId $utilisateur -LogonType Interactive -RunLevel Limited
    try {
        Register-ScheduledTask -TaskName $NomTache -Action $action -Trigger $declencheur `
            -Settings $reglages -Principal $principal -Force | Out-Null
        Ok "Le bot démarrera tout seul à chaque ouverture de ta session Windows"
    } catch {
        # Cas d'une tâche « au démarrage » créée avant en administrateur : un
        # compte standard n'a pas le droit de la remplacer → on la garde.
        Avert "Tâche existante conservée (créée en administrateur) : le bot garde son démarrage actuel."
    }
}

# ── 6. Mise en veille ───────────────────────────────────────────────────────
Etape "Mise en veille du PC"
Info "Si le PC se met en veille, le bot s'arrête. Il vaut mieux désactiver la veille quand le PC est branché."
$rep = Read-Host "Désactiver la mise en veille quand le PC est branché ? (O/N)"
if ($rep -match '^[oOyY]') {
    $c1 = Executer "powercfg" @("/change", "standby-timeout-ac", "0")
    $c2 = Executer "powercfg" @("/change", "hibernate-timeout-ac", "0")
    if ($c1 -eq 0 -and $c2 -eq 0) { Ok "Veille désactivée (sur secteur)" }
    else { Avert "Impossible de le faire automatiquement : suis l'étape 'Empêcher la veille' du guide." }
} else {
    Avert "Veille laissée telle quelle : pense à la désactiver à la main (voir le guide)."
}

# ── 7. Démarrage et vérification ────────────────────────────────────────────
Etape "Démarrage du bot"
try { Start-ScheduledTask -TaskName $NomTache }
catch { Start-Process "wscript.exe" -ArgumentList "`"$vbs`"" -WorkingDirectory $Racine }
Info "Patience, vérification dans 20 secondes..."
Start-Sleep -Seconds 20

$tourne = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
          Where-Object { $_.CommandLine -like "*$Racine\main.py*" }
$log = Join-Path $Racine "data\logs\bot.log"
$dernieres = @()
if (Test-Path $log) { $dernieres = Get-Content $log -Tail 8 -Encoding UTF8 }

if ($tourne -and ($dernieres -join "`n") -match "Connect") {
    Write-Host ""
    Write-Host "  [OK] CodeX KillFeed est en ligne !" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Prochaine étape, sur ton Discord :  /setup   puis   /diagnostic"
} elseif ($tourne) {
    Write-Host ""
    Avert "Le bot tourne, mais je n'ai pas encore vu sa connexion à Discord. Dernières lignes du journal :"
    $dernieres | ForEach-Object { Write-Host "    $_" }
    Info "Patiente une minute et regarde si le bot est en ligne sur ton Discord."
} else {
    Write-Host ""
    Write-Host "  [ERREUR] Le bot ne tourne pas. Dernières lignes du journal :" -ForegroundColor Red
    $dernieres | ForEach-Object { Write-Host "    $_" }
    exit 1
}
