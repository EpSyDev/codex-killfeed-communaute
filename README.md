# CodeX KillFeed — édition communautaire

Bot Discord gratuit et open source pour serveurs **DayZ console (PS / Xbox) hébergés chez Nitrado**.
Tu l'héberges toi-même, avec ton propre bot : ton nom, ton avatar, tes données.

Créé par **EpSy** et offert à la communauté DayZ francophone.

## Ce qu'il fait

- **KillFeed en direct** : kills PVP (arme, distance, coups encaissés, positions), morts PVE (zombies, animaux, faim, soif, saignement…), mises KO, suicides, enterrements, connexions et déconnexions.
- **Whitelist** synchronisée avec Nitrado : `/whitelist`, `/dewhitelist`, `/wl`, salon public de demande avec validation par un admin, `/link` pour lier un pseudo PSN/Xbox à un compte Discord.
- **Statistiques** : `/joueur` (kills, morts, ratio, temps de jeu, arme favorite), `/top` (classement sur 1 à 30 jours), classement de la semaine publié chaque dimanche à 20 h dans `#statistiques`.
- **Surveillance** : salon vocal « 🟢 En-Ligne • 12/60 » mis à jour toutes les 5 minutes ; alerte dans `#alertes` (salon réservé aux admins) si le serveur tombe ou si les logs ADM ne bougent plus alors que des joueurs sont connectés.
- **Modération** : `/ban`, `/unban`, `/bans` directement sur la banlist Nitrado ; auto-ban NO PVP (avec plages horaires) et auto-ban suicide via `/autoban`, avec liste d'exceptions.
- **Redémarrages planifiés** : `/restart planifier 06:00`, compte à rebours à 15, 5 et 1 minute dans `#annonces`, `/restart maintenant` pour un redémarrage ponctuel.
- **Entretien automatique** : sauvegarde quotidienne de la base dans `data/backups` (7 jours gardés), version affichée et nouvelles versions signalées dans `/diagnostic`.
- **Salons optionnels** via `/salons` : constructions, placements, drapeaux, logs-whitelist, alertes, annonces, statistiques.
- **Commandes** : `/setup`, `/salons`, `/filter`, `/status`, `/kills`, `/stats`, `/joueur`, `/top`, `/ban`, `/unban`, `/bans`, `/autoban`, `/restart`, `/diagnostic`, `/stop`, `/purge-guild`.

Les horaires (NO PVP, redémarrages, classement du dimanche) suivent l'horloge de la machine qui fait tourner le bot : `/diagnostic` l'affiche.

📥 **Télécharger la dernière version :** [codex-killfeed-communaute.zip](https://github.com/EpSyDev/codex-killfeed-communaute/releases/latest) (partie *Assets* de la page)

📖 **Toutes les fonctionnalités et toutes les commandes :** [docs/FONCTIONNALITES.md](docs/FONCTIONNALITES.md)

## Installer

Deux façons de faire tourner le bot, avec chacune son guide pas à pas :

| Je veux… | Guide |
|---|---|
| un bot qui tourne **24h/24 sans que mon PC reste allumé** (petit serveur loué, 2 à 6 €/mois) | **[docs/TUTO-VPS.md](docs/TUTO-VPS.md)** |
| le faire tourner **sur mon PC Windows** (gratuit, mais le PC doit rester allumé) | **[docs/TUTO-LOCAL-WINDOWS.md](docs/TUTO-LOCAL-WINDOWS.md)** : un double-clic sur `INSTALLER-WINDOWS` |

Tu as déjà un serveur Linux (Ubuntu 22.04 ou 24.04) ? Alors c'est simplement :

```bash
sudo bash scripts/install.sh
```

Le script installe Python, demande et vérifie tes tokens, puis crée un service qui démarre tout seul et redémarre en cas de crash.

## Limites de cette version

- **1 bot = 1 serveur Discord = 1 serveur DayZ.** Pour plusieurs serveurs, installe plusieurs bots.
- **Pas de dashboard web.** Tout se règle via les commandes Discord.
- Les événements arrivent avec 10 à 30 secondes de décalage, le temps que Nitrado publie ses logs.

## Structure

```
main.py              point d'entrée
bot/                 commandes Discord, embeds, whitelist
backend/             lecture des logs ADM Nitrado, base SQLite
migrations/          schéma de la base (créé automatiquement)
assets/              icônes des embeds
scripts/install.sh   installation Ubuntu (service systemd)
scripts/update.sh    mise à jour en gardant config et données
scripts/windows/     installation sur PC Windows (lancée par INSTALLER-WINDOWS.bat)
.env.example         modèle de configuration
```
