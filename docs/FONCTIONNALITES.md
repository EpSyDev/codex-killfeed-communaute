# CodeX KillFeed — fonctionnalités et commandes

Ce fichier présente tout ce que fait le bot et **toutes ses commandes slash** (`/`).
Version : voir le fichier `VERSION`, ou la ligne **Version** de `/diagnostic`.

> 🧒 **En clair :** les commandes marquées 🔒 sont réservées aux **administrateurs** du serveur Discord : les autres membres ne les voient même pas. Les commandes marquées 👥 sont ouvertes à tout le monde. Les réponses du bot sont en général **visibles par toi seul** (message « Seul toi peux voir ceci »).

---

## Sommaire

1. [Premiers pas après l'installation](#premiers-pas-après-linstallation)
2. [Ce que fait le bot](#ce-que-fait-le-bot)
3. [Les salons du bot](#les-salons-du-bot)
4. [Toutes les commandes](#toutes-les-commandes)
5. [Exemples de réglages](#exemples-de-réglages)
6. [Bon à savoir](#bon-à-savoir)

---

## Premiers pas après l'installation

Sur ton serveur Discord, une fois le bot **en ligne** (pastille verte) :

1. Tape `/setup`.
   - Laisse le champ `token` **vide** : le bot utilise celui de son fichier `.env`. Taper un token dans Discord, c'est risquer qu'il fuite.
   - `role_whitelist` *(facultatif)* : le rôle qui verra le salon de demande de whitelist (par exemple `@Joueurs`). Utile seulement si ton serveur est en whitelist.
   - Si ton compte Nitrado gère plusieurs serveurs DayZ, le bot te demande lequel configurer.
2. Le bot crée une catégorie **📡 CodeX — NomDuServeur** avec ses salons (voir [Les salons du bot](#les-salons-du-bot)).
3. Tape `/diagnostic` : tout doit être ✅. Chaque ligne en ❌ dit quoi corriger.
4. *(Facultatif)* Ajuste le bot à ton serveur :
   - `/salons` pour ajouter ou retirer des salons ;
   - `/filter` pour choisir les événements affichés ;
   - `/wl-panel` si ton serveur est en whitelist ;
   - `/autoban` et `/restart` pour la modération et les redémarrages automatiques.

Les premiers événements arrivent dès qu'il se passe quelque chose en jeu, avec 10 à 30 secondes de décalage (le temps que Nitrado publie ses journaux).

---

## Ce que fait le bot

### 💀 KillFeed en direct

Le bot lit les journaux **ADM** de ton serveur Nitrado et publie chaque événement dans le bon salon :

| Événement | Salon |
|---|---|
| Kill PVP : tueur, victime, arme, distance, coups encaissés, positions (masquables) | `morts-pvp` |
| Mort PVE : zombie, animal, chute, faim, soif, saignement… | `morts-pve` |
| Suicide | `morts-pve` |
| Perte et reprise de conscience (KO) *(masquées par défaut)* | `morts-pve` |
| Connexion, déconnexion | `connexions` |
| Construction, démontage, clôture repliée, barbelés, abri | `constructions` *(optionnel)* |
| Objet posé, enterré, déterré | `placements` *(optionnel)* |
| Drapeau hissé, abaissé | `drapeaux` *(optionnel)* |

À la fin de chaque session du serveur (nouveau fichier ADM), le journal complet est publié dans `logs-adm`, réservé aux admins.

### 🛡️ Whitelist

- Ajout et retrait de joueurs directement dans la whitelist **Nitrado** (`/whitelist`, `/dewhitelist`).
- **Salon public de demande** (`/wl-panel`) :
  1. le joueur clique sur un bouton et tape son pseudo PSN / Xbox ;
  2. la demande arrive dans `logs-whitelist` avec les boutons **Approuver** / **Refuser** ;
  3. à l'approbation, le joueur est ajouté sur Nitrado, reçoit le rôle choisi (option `role_approuve`) et un message privé.
- Un joueur qui **quitte le Discord** est retiré automatiquement de la whitelist.
- `/link` permet à chaque joueur de lier son pseudo de jeu à son compte Discord.

### 📊 Statistiques

- `/joueur` : fiche complète d'un joueur (kills PVP, morts, ratio K/D, plus long kill, première venue, dernière connexion, temps de jeu, arme favorite, victime préférée, « bête noire »).
- `/top` : classement sur 1 à 30 jours (kills, ratio K/D, plus longs kills, temps de jeu, morts).
- `/stats` : résumé rapide des événements.
- **Classement de la semaine** publié automatiquement chaque **dimanche à 20 h** dans `statistiques`.

Tout est calculé à partir des vrais événements des journaux ADM : aucun score inventé. Le temps de jeu additionne les sessions connexion → déconnexion.

### 📡 Surveillance du serveur

- Le **salon vocal** de la catégorie affiche l'état en direct : `🟢 En-Ligne • 12/60`, `🟠 Redémarrage…` ou `🔴 Hors-ligne`. Mise à jour toutes les 5 minutes (Discord n'autorise pas plus souvent).
- **Alertes** dans `alertes` (réservé aux admins) :
  - 🔴 serveur arrêté depuis au moins 10 minutes, puis 🟢 quand il revient ;
  - ⚠️ journaux ADM figés depuis 30 minutes alors que des joueurs sont connectés (le KillFeed ne reçoit plus rien), puis ✅ quand ils repartent.
- Les alertes se taisent pendant 15 minutes après un redémarrage lancé par le bot.

### 🔨 Modération

- **Bans manuels** : `/ban`, `/unban`, `/bans`, directement sur la banlist **Nitrado**. Un joueur banni est aussi retiré de la whitelist.
- **Auto-ban NO PVP** : tout joueur qui tue un autre joueur est banni automatiquement. Peut être limité à des **plages horaires** (par exemple PVP interdit en semaine de 8 h à 18 h).
- **Auto-ban suicide** : tout joueur qui se suicide est banni automatiquement.
- **Exceptions** : une liste de joueurs jamais bannis, par règle (admins, testeurs…).
- Chaque ban automatique est signalé dans `alertes`, avec la commande pour l'annuler.
- **Nitrado ne répond pas ?** Le ban n'est pas perdu : il est **mis en attente**, retenté toutes les 5 minutes, affiché dans `/bans` et confirmé dans `alertes` une fois appliqué.

### 🔄 Redémarrages planifiés

- Redémarrages automatiques à heures fixes (`/restart planifier`), tous les jours ou certains jours seulement.
- Redémarrage ponctuel avec compte à rebours (`/restart maintenant`).
- **Annonces** dans `annonces` à 15, 5 et 1 minute avant, puis « redémarrage en cours ».

### 🧰 Entretien automatique

- **Sauvegarde quotidienne** de la base du bot dans `data/backups` (les 7 derniers jours sont gardés).
- **Version** affichée dans `/diagnostic`. Le bot vérifie une fois par jour les [versions publiées](https://github.com/EpSyDev/codex-killfeed-communaute/releases) : quand une nouvelle sort, `/diagnostic` et `alertes` le signalent (une seule fois).
- **Mise à jour en un clic** avec `/maj` :
  1. le bot télécharge la version officielle et vérifie son empreinte ;
  2. il sauvegarde la base et la version actuelle, puis remplace ses fichiers ;
  3. il redémarre tout seul et confirme le résultat dans `alertes`.

  Ton `.env`, ta base et tes données ne sont jamais touchés. Si quelque chose échoue, l'ancienne version est remise en place automatiquement.
- Un salon supprimé par erreur est recréé par `/refresh` (sauf ceux désactivés exprès avec `/salons`).
- Les vieux événements sont purgés chaque nuit pour garder la base légère.

---

## Les salons du bot

Tous les salons sont rangés dans la catégorie **📡 CodeX — NomDuServeur**.

> ⚠️ **Par défaut, les salons texte créés par `/setup` sont visibles seulement par le propriétaire du serveur Discord** (et le bot). C'est voulu : tu choisis ce que les joueurs voient. Pour ouvrir un salon (par exemple `morts-pvp`) : clic droit sur le salon → **Modifier le salon** → **Permissions** → ajoute le rôle de tes joueurs (ou `@everyone`) avec **Voir le salon** ✅ et **Envoyer des messages** ❌.

| Salon | Créé | Visible par défaut par | Contenu |
|---|---|---|---|
| 💀 `morts-pvp` | au `/setup` | propriétaire (à ouvrir) | kills PVP |
| ☠️ `morts-pve` | au `/setup` | propriétaire (à ouvrir) | morts PVE, suicides, KO |
| 🎮 `connexions` | au `/setup` | propriétaire (à ouvrir) | connexions, déconnexions |
| 📄 `logs-adm` | au `/setup` | propriétaire | journal ADM complet de chaque session |
| 🔊 salon vocal d'état | au `/setup` | tout le monde (on ne peut pas s'y connecter) | `🟢 En-Ligne • 12/60` |
| 📋 `logs-whitelist` | au `/setup` si `role_whitelist`, ou via `/salons` | propriétaire | demandes de whitelist, suivi |
| `demande-whitelist` | via `/wl-panel installer` | le rôle choisi | bouton de demande pour les joueurs |
| 🔨 `constructions` | via `/salons` | comme la catégorie | bases construites, démontées |
| 📦 `placements` | via `/salons` | comme la catégorie | objets posés, enterrés, déterrés |
| 🚩 `drapeaux` | via `/salons` | comme la catégorie | drapeaux hissés, abaissés |
| 🚨 `alertes` | au premier besoin, ou via `/salons` | admins uniquement | serveur hors ligne, logs figés, bans, nouvelle version |
| 📢 `annonces` | au premier redémarrage planifié, ou via `/salons` | tout le monde (lecture seule) | comptes à rebours des redémarrages |
| 📊 `statistiques` | au premier dimanche, ou via `/salons` | tout le monde (lecture seule) | classement de la semaine |

> 🧒 *Tu ne veux pas d'un salon ?* `/salons` → choisis-le → **Désactiver**. Il est supprimé, et le bot ne le recrée plus jamais tout seul.
>
> *Tu as supprimé un salon par erreur ?* `/refresh` le recrée.

---

## Toutes les commandes

Entre `< >` : paramètre **obligatoire**. Entre `[ ]` : paramètre **facultatif**. Discord propose les paramètres au fur et à mesure que tu tapes : pas besoin de les retenir.

### ⚙️ Configuration

| Commande | Accès | Ce qu'elle fait |
|---|---|---|
| `/setup [token] [role_whitelist]` | 🔒 | Configure le bot : vérifie Nitrado, crée la catégorie et les salons, démarre le KillFeed. Laisse `token` vide. |
| `/salons <salon> <Activer\|Désactiver>` | 🔒 | Crée ou supprime un salon optionnel : constructions, placements, drapeaux, logs-whitelist, alertes, annonces, statistiques. |
| `/filter` | 🔒 | Boutons pour afficher ou masquer : pertes de conscience, suicides, enterrements, positions dans les kills PVP. |
| `/refresh` | 🔒 | Resynchronise le bot (salons, cache, permissions) et signale les permissions manquantes. À lancer si tu as déplacé ou renommé des salons. |
| `/diagnostic` | 🔒 | Bilan de santé : Discord, base de données, token Nitrado, KillFeed, version, dernière sauvegarde, heure de la machine. **La commande à lancer en premier en cas de souci.** |
| `/status` | 👥 | Statut du KillFeed. |
| `/stop` | 🔒 | Arrête le KillFeed sur ce serveur Discord (relance avec `/setup`). |
| `/maj` | 🔒 | Installe la dernière version du bot en un clic : téléchargement, vérification, sauvegarde, redémarrage (1 à 2 minutes hors ligne). Configuration et données conservées. Le résultat est confirmé dans `alertes`. |
| `/purge-guild` | 🔒 | ⚠️ Supprime **définitivement** les données du bot pour ce serveur Discord (historique, réglages). Demande confirmation. |

### 🛡️ Whitelist

| Commande | Accès | Ce qu'elle fait |
|---|---|---|
| `/whitelist <psn_id> [discord_id] [discord_name]` | 🔒 | Ajoute un joueur à la whitelist Nitrado. Respecte la casse exacte du pseudo. |
| `/dewhitelist <psn_id>` | 🔒 | Retire un joueur de la whitelist. |
| `/wl` | 🔒 | Publie la whitelist Nitrado actuelle dans `logs-whitelist`. |
| `/wl-panel <installer\|reposter\|retirer> [role] [role_approuve]` | 🔒 | Gère le salon public de demande. `installer` demande `role` (qui voit le salon). `role_approuve` = rôle donné aux joueurs acceptés. `reposter` renvoie le bouton, `retirer` supprime le salon. |
| `/link <psn_id>` | 👥 | Le joueur lie son pseudo de jeu à son compte Discord. |

### 📊 Statistiques

| Commande | Accès | Ce qu'elle fait |
|---|---|---|
| `/joueur <pseudo>` | 👥 | Fiche d'un joueur. Le pseudo se complète automatiquement. |
| `/top [jours] [public]` | 👥 | Classement sur `jours` (1 à 30, 7 par défaut). `public: True` l'affiche à tout le salon. |
| `/stats [jours]` | 👥 | Résumé : nombre de PVP, PVE, suicides, top tueurs, plus souvent tués. |
| `/kills [nombre]` | 👥 | Les derniers événements (10 maximum). |

### 🔨 Bans

| Commande | Accès | Ce qu'elle fait |
|---|---|---|
| `/ban <pseudo> [raison]` | 🔒 | Bannit sur Nitrado et retire de la whitelist. La raison est notée dans `alertes`. Mis en attente si Nitrado ne répond pas. |
| `/unban <pseudo>` | 🔒 | Débannit (ou annule un ban en attente). Ne remet **pas** en whitelist : utilise `/whitelist` ensuite si besoin. |
| `/bans` | 🔒 | Liste des bannis, plus les bans en attente. |

### 🚫 Auto-bans

| Commande | Accès | Ce qu'elle fait |
|---|---|---|
| `/autoban activer <NO PVP\|Suicide> <Activer\|Désactiver>` | 🔒 | Active ou coupe une règle. |
| `/autoban horaires <Ajouter une plage\|Tout effacer> [jours] [debut] [fin]` | 🔒 | Plages horaires du NO PVP. Sans aucune plage, le NO PVP s'applique **24 h/24**. |
| `/autoban exception <regle> <Ajouter\|Retirer> <pseudo>` | 🔒 | Joueurs jamais bannis par cette règle. |
| `/autoban etat` | 🔒 | Résumé : règles actives, exceptions, plages horaires, NO PVP actif en ce moment ou non. |

### 🔄 Redémarrages

| Commande | Accès | Ce qu'elle fait |
|---|---|---|
| `/restart planifier <heure> [jours]` | 🔒 | Ajoute un redémarrage récurrent, par exemple `06:00` tous les jours. |
| `/restart retirer <heure>` | 🔒 | Supprime un redémarrage planifié. |
| `/restart liste` | 🔒 | Redémarrages planifiés et 3 prochains passages. |
| `/restart maintenant [delai]` | 🔒 | Redémarre dans `delai` minutes (0 à 60, 5 par défaut), avec annonces. |
| `/restart annuler` | 🔒 | Annule le redémarrage ponctuel en attente. |

### Écrire les jours et les heures

Dans `/autoban horaires` et `/restart planifier` :

| Tu écris | Ça veut dire |
|---|---|
| `tous` | tous les jours |
| `semaine` | du lundi au vendredi |
| `week-end` | samedi et dimanche |
| `lun-ven`, `ven-dim` | une suite de jours (`ven-lun` = vendredi, samedi, dimanche, lundi) |
| `lun,mer,ven` | des jours précis, séparés par des virgules |
| `08:00`, `8h`, `8h30` | une heure |
| `24:00` *(en fin de plage NO PVP)* | jusqu'à minuit |

Une plage dont la fin est **avant** le début passe minuit : `22:00` → `06:00` = de 22 h le soir à 6 h le lendemain matin.

---

## Exemples de réglages

**Serveur PVE strict** (aucun PVP, jamais) :
```
/autoban activer regle:NO PVP etat:Activer
/autoban exception regle:NO PVP action:Ajouter pseudo:MonPseudoAdmin
```

**PVP seulement le week-end** (NO PVP en semaine, toute la journée) :
```
/autoban activer regle:NO PVP etat:Activer
/autoban horaires action:Ajouter une plage jours:semaine debut:00:00 fin:24:00
```

**PVP interdit la nuit** :
```
/autoban horaires action:Ajouter une plage jours:tous debut:23:00 fin:08:00
```

**Redémarrage toutes les 6 heures** :
```
/restart planifier heure:00:00
/restart planifier heure:06:00
/restart planifier heure:12:00
/restart planifier heure:18:00
```

**Serveur en whitelist avec demandes publiques** :
```
/wl-panel action:installer role:@Joueurs role_approuve:@Survivant
/salons salon:logs-whitelist action:Activer
```

---

## Bon à savoir

- **Les horaires suivent l'horloge de la machine qui fait tourner le bot** (NO PVP, redémarrages, classement du dimanche). `/diagnostic` affiche cette heure : si elle est décalée, corrige le fuseau horaire de la machine.
- **Un joueur déjà connecté peut rester en jeu jusqu'au prochain redémarrage du serveur** après son ban : Nitrado applique ses réglages au démarrage. Combine avec `/restart maintenant` si c'est urgent.
- **Les pseudos doivent être écrits comme dans les journaux** du serveur (même casse). Les commandes `/joueur`, `/ban`, `/autoban exception` complètent automatiquement les pseudos déjà vus.
- **Le rôle du bot doit être au-dessus** des rôles qu'il donne (`role_approuve`), dans *Paramètres du serveur → Rôles*.
- **1 bot = 1 serveur Discord = 1 serveur DayZ.** Pour plusieurs serveurs DayZ, installe plusieurs bots.
- **Un souci ?** `/diagnostic` d'abord. Le détail complet est dans le journal du bot (`data/logs/bot.log`).

---

*CodeX KillFeed, créé par EpSy et offert à la communauté.*
