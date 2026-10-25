# CodeX KillFeed — mise à jour sur Windows, sans passer par Discord
#
# Deux façons de le lancer :
#   • double-clic sur METTRE-A-JOUR.bat (dans le dossier du bot) ;
#   • depuis n'importe où (version ancienne sans ce fichier, bot hors ligne…),
#     touche Windows + R, puis coller :
#       powershell -ep bypass -c "irm https://raw.githubusercontent.com/EpSyDev/codex-killfeed-communaute/main/scripts/windows/mettre-a-jour.ps1 -OutFile $env:TEMP\maj.ps1; & $env:TEMP\maj.ps1"
#
# Ce que fait le script : trouve le dossier du bot, télécharge la dernière
# version officielle (GitHub), vérifie son empreinte SHA-256, arrête le bot,
# sauvegarde la base et l'ancienne version, remplace les fichiers (jamais
# .env, data, base, venv), met à jour les dépendances, redémarre le bot.

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Depot    = "EpSyDev/codex-killfeed-communaute"
$NomTache = "CodeX KillFeed"
$UA       = "CodeXKillFeed-maj/1.0"

function Etape($t)  { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Ok($t)     { Write-Host "  [OK] $t" -ForegroundColor Green }
function Info($t)   { Write-Host "  $t" }
function Avert($t)  { Write-Host "  [!] $t" -ForegroundColor Yellow }
function Fin($code) {
    Write-Host ""
    Read-Host "Appuie sur Entrée pour fermer cette fenêtre" | Out-Null
    exit $code
}
function Echec($t)  {
    Write-Host ""
    Write-Host "  [ERREUR] $t" -ForegroundColor Red
    Fin 1
}

Write-Host ""
Write-Host "  CodeX KillFeed — mise à jour" -ForegroundColor White

# ── 1. Trouver le dossier du bot ────────────────────────────────────────────
Etape "Recherche du dossier du bot"
function Est-DossierBot($d) {
    return $d -and (Test-Path (Join-Path $d "main.py")) -and (Test-Path (Join-Path $d "INSTALLER-WINDOWS.bat"))
}
$Racine = $null
if ($PSScriptRoot) {
    $candidat = (Resolve-Path (Join-Path $PSScriptRoot "..\..") -ErrorAction SilentlyContinue).Path
    if (Est-DossierBot $candidat) { $Racine = $candidat }
}
if (-not $Racine) {
    $tache = Get-ScheduledTask -TaskName $NomTache -ErrorAction SilentlyContinue
    if ($tache) {
        $d = $tache.Actions | Select-Object -First 1 -ExpandProperty WorkingDirectory
        if (Est-DossierBot $d) { $Racine = $d }
    }
}
if (-not $Racine -and (Est-DossierBot "C:\codex-killfeed-communaute")) { $Racine = "C:\codex-killfeed-communaute" }
if (-not $Racine) {
    Info "Je ne trouve pas le dossier du bot tout seul."
    $d = (Read-Host "Colle le chemin du dossier du bot (par exemple C:\codex-killfeed-communaute)").Trim().Trim('"')
    if (Est-DossierBot $d) { $Racine = (Resolve-Path $d).Path }
    else { Echec "Ce dossier ne contient pas le bot (main.py et INSTALLER-WINDOWS introuvables)." }
}
Ok "Dossier : $Racine"

if (-not (Test-Path (Join-Path $Racine ".env"))) {
    Echec "Le bot n'a jamais été installé dans ce dossier : double-clique d'abord sur INSTALLER-WINDOWS."
}
$venvPy = Join-Path $Racine "venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Echec "Environnement Python absent : double-clique sur INSTALLER-WINDOWS pour réparer l'installation."
}

$fichierVersion = Join-Path $Racine "VERSION"
$actuelle = if (Test-Path $fichierVersion) { (Get-Content $fichierVersion -Raw).Trim() } else { "1.0.0" }

# ── 2. Dernière version publiée ─────────────────────────────────────────────
Etape "Recherche de la dernière version"
try {
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Depot/releases/latest" -UserAgent $UA -TimeoutSec 30
} catch {
    Echec "Impossible de joindre GitHub. Vérifie ta connexion Internet, puis relance."
}
$cible = "$($rel.tag_name)".TrimStart("v", "V")
$asset = $rel.assets | Where-Object { $_.name -eq "codex-killfeed-communaute.zip" } | Select-Object -First 1
if (-not $asset) { Echec "La dernière version n'a pas de fichier zip. Réessaie plus tard." }

function Num($v) {
    $p = @(("$v" -replace '[^0-9.]', '').Split(".") | Where-Object { $_ -ne "" })
    while ($p.Count -lt 3) { $p += "0" }
    try { return [version]($p[0..2] -join ".") } catch { return [version]"0.0.0" }
}
Info "Version installée : $actuelle"
Info "Dernière version  : $cible"
if ((Num $cible) -le (Num $actuelle)) {
    Ok "Le bot est déjà à jour, rien à faire."
    Fin 0
}

# ── 3. Téléchargement et vérification ───────────────────────────────────────
Etape "Téléchargement de la version $cible"
$tmp     = Join-Path $env:TEMP ("codex-maj-" + [guid]::NewGuid().ToString("N"))
$zip     = Join-Path $tmp "maj.zip"
$extrait = Join-Path $tmp "extrait"
New-Item -ItemType Directory -Force $tmp | Out-Null
try {
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UserAgent $UA -TimeoutSec 300 -UseBasicParsing
} catch {
    Echec "Téléchargement impossible. Vérifie ta connexion Internet, puis relance."
}
if ($asset.digest -and "$($asset.digest)".StartsWith("sha256:")) {
    $attendu = "$($asset.digest)".Substring(7).ToLower()
    $obtenu  = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    if ($attendu -ne $obtenu) { Echec "Le fichier téléchargé est abîmé (empreinte différente). Relance la mise à jour." }
    Ok "Fichier téléchargé et vérifié"
} else {
    Avert "GitHub ne fournit pas d'empreinte pour ce fichier : vérification sautée."
}

Expand-Archive -Path $zip -DestinationPath $extrait -Force
$dossiers = @(Get-ChildItem $extrait -Directory)
$source = if ($dossiers.Count -eq 1) { $dossiers[0].FullName } else { $extrait }
if (-not (Test-Path (Join-Path $source "main.py")) -or -not (Test-Path (Join-Path $source "VERSION"))) {
    Echec "Contenu du zip inattendu : mise à jour annulée, rien n'a été modifié."
}
if ((Get-Content (Join-Path $source "VERSION") -Raw).Trim() -ne $cible) {
    Echec "Le zip ne correspond pas à la version annoncée : mise à jour annulée, rien n'a été modifié."
}

# ── 4. Arrêt du bot ─────────────────────────────────────────────────────────
Etape "Arrêt du bot"
if (Get-ScheduledTask -TaskName $NomTache -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $NomTache -ErrorAction SilentlyContinue
}
Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*lancer-bot.bat*" -and $_.CommandLine -like "*$Racine*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$Racine\main.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
Ok "Bot arrêté"

# ── 5. Sauvegardes ──────────────────────────────────────────────────────────
Etape "Sauvegarde de la base et de la version actuelle"
$sauv = Join-Path $Racine "data\backups"
New-Item -ItemType Directory -Force $sauv | Out-Null
foreach ($f in Get-ChildItem $Racine -File | Where-Object { $_.Name -match '\.db(-wal|-shm)?$' }) {
    Copy-Item $f.FullName (Join-Path $sauv ($f.Name -replace '^(.*?)\.db', "`$1-avant-maj-$cible.db")) -Force
}
$ancienne = Join-Path $Racine "data\updates\ancienne-version-$actuelle"
if (Test-Path (Join-Path $Racine "data\updates")) {
    Get-ChildItem (Join-Path $Racine "data\updates") -Directory -Filter "ancienne-version-*" |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
$exclusDossiers = @("data", "venv", ".venv", ".git", "__pycache__")
$exclusFichiers = @(".env", "*.db", "*.db-wal", "*.db-shm", "lancer-bot.vbs")
robocopy $Racine $ancienne /E /XD @exclusDossiers /XF @exclusFichiers /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Echec "Sauvegarde de l'ancienne version impossible : mise à jour annulée, rien n'a été modifié." }
Ok "Sauvegardes dans data\backups et data\updates"

# ── 6. Remplacement des fichiers ────────────────────────────────────────────
Etape "Installation de la version $cible"
# METTRE-A-JOUR.bat est peut-être en cours d'exécution : cmd lit un .bat au
# fil de l'eau, le remplacer maintenant ferait exécuter n'importe quoi.
robocopy $source $Racine /E /XD @exclusDossiers /XF @exclusFichiers "METTRE-A-JOUR.bat" /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) {
    robocopy $ancienne $Racine /E /NFL /NDL /NJH /NJS /NP | Out-Null
    Echec "Copie des nouveaux fichiers impossible : l'ancienne version a été remise. Relance la mise à jour."
}
Ok "Fichiers remplacés (.env, base et données conservés)"

Etape "Mise à jour des dépendances (1 à 3 minutes)"
$ancien = $ErrorActionPreference; $ErrorActionPreference = "Continue"
& $venvPy -m pip install --disable-pip-version-check --quiet -r (Join-Path $Racine "requirements.txt") | Out-Host
$codePip = $LASTEXITCODE
$ErrorActionPreference = $ancien
if ($codePip -ne 0) {
    robocopy $ancienne $Racine /E /NFL /NDL /NJH /NJS /NP | Out-Null
    Avert "Les dépendances n'ont pas pu être installées : l'ancienne version a été remise en place."
    $retourArriere = $true
} else {
    Ok "Dépendances à jour"
    $retourArriere = $false
}

# ── 7. Redémarrage ──────────────────────────────────────────────────────────
Etape "Redémarrage du bot"
$vbs = Join-Path $Racine "scripts\windows\lancer-bot.vbs"
try { Start-ScheduledTask -TaskName $NomTache -ErrorAction Stop }
catch {
    if (Test-Path $vbs) { Start-Process "wscript.exe" -ArgumentList "`"$vbs`"" -WorkingDirectory $Racine }
    else { Avert "Démarrage automatique introuvable : double-clique sur INSTALLER-WINDOWS." }
}
Info "Patience, vérification dans 25 secondes..."
Start-Sleep -Seconds 25
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue

$tourne = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
          Where-Object { $_.CommandLine -like "*$Racine\main.py*" }
if ($retourArriere) {
    Echec "Mise à jour annulée (dépendances). Le bot repart en version $actuelle. Vérifie ta connexion Internet, puis relance."
}
if ($tourne) {
    Write-Host ""
    Write-Host "  [OK] Mise à jour terminée : CodeX KillFeed $cible est en ligne !" -ForegroundColor Green
    Write-Host ""
    Info "Sur Discord, tape /diagnostic : la ligne Version doit afficher $cible."
    Info "Les prochaines fois, tape simplement /maj sur Discord."
    Fin 0
}
Avert "Le bot ne semble pas avoir redémarré. Double-clique sur DEMARRER-LE-BOT, puis regarde VOIR-LES-LOGS."
Fin 1
