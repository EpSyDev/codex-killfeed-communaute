# Installer CodeX KillFeed sur un petit serveur loué (VPS, 24h/24)

Ce guide part de zéro. Aucune connaissance Linux n'est nécessaire : tu copies-colles les commandes, dans l'ordre.

**Durée :** 30 minutes environ la première fois.
**Coût :** le prix d'un petit VPS, en général **2 à 6 € par mois**, sans engagement chez la plupart des hébergeurs.

**Il te faut :**
- un serveur DayZ console (PS ou Xbox) loué chez **Nitrado** ;
- être **administrateur** de ton serveur Discord ;
- un PC sous **Windows 10 ou 11** (seulement pour l'installation, il pourra ensuite rester éteint) ;
- le fichier `codex-killfeed-communaute.zip`.

> 🧒 **Comment ça marche, en 30 secondes**
>
> Ton bot est un petit programme qui doit tourner **jour et nuit** pour surveiller ton serveur DayZ. Ton PC, lui, s'éteint. On va donc :
> 1. créer le **bot** sur Discord (son identité : nom, avatar, mot de passe) ;
> 2. récupérer chez **Nitrado** l'autorisation de lire les journaux de ton serveur ;
> 3. louer un **VPS** : un petit ordinateur allumé 24h/24 dans un centre de données ;
> 4. y **installer** le bot, depuis ton PC, avec quelques copier-coller.
>
> 📝 **Avant de commencer :** ouvre le **Bloc-notes** de Windows. Tu vas y coller au fur et à mesure 5 informations (token Discord, token Nitrado, ID de service, adresse du VPS, mot de passe du VPS). Garde-le ouvert jusqu'à la fin, et ne le partage avec personne.

---

## Sommaire

1. [Créer ton bot Discord](#1-créer-ton-bot-discord)
2. [Récupérer tes accès Nitrado](#2-récupérer-tes-accès-nitrado)
3. [Louer ton VPS](#3-louer-ton-vps)
4. [Te connecter au VPS depuis Windows](#4-te-connecter-au-vps-depuis-windows)
5. [Envoyer et installer le bot](#5-envoyer-et-installer-le-bot)
6. [Configurer le bot sur Discord](#6-configurer-le-bot-sur-discord)
7. [Au quotidien](#7-au-quotidien)
8. [Mettre à jour](#8-mettre-à-jour)
9. [Sauvegardes](#9-sauvegardes)
10. [Dépannage](#10-dépannage)

---

## 1. Créer ton bot Discord

C'est **ton** bot : il aura le nom et l'avatar que tu choisis.

1. Va sur <https://discord.com/developers/applications> et connecte-toi.
2. Clique sur **New Application**, donne-lui un nom (par exemple *KillFeed MonServeur*), accepte les conditions, puis **Create**.
3. *(Facultatif)* Dans **General Information**, ajoute une icône.
4. Dans le menu de gauche, ouvre **Bot** :
   - clique sur **Reset Token**, confirme, puis **Copy**. Colle ce token dans ton Bloc-notes.
     > ⚠️ Ce token, c'est le mot de passe de ton bot. Ne le montre à personne et ne le poste jamais sur Discord. S'il fuite, refais *Reset Token*.
   - un peu plus bas, dans **Privileged Gateway Intents**, active **SERVER MEMBERS INTENT** et **MESSAGE CONTENT INTENT**, puis **Save Changes**.
     > Sans ces deux options, le bot refuse de démarrer.
5. Dans le menu de gauche, ouvre **OAuth2**, puis **URL Generator** :
   - dans **Scopes**, coche `bot` et `applications.commands` ;
   - dans **Bot Permissions**, coche `Administrator` ;
   - copie l'URL générée en bas de page, ouvre-la dans ton navigateur, choisis ton serveur Discord et valide.

Ton bot apparaît maintenant hors ligne dans la liste des membres. C'est normal : il s'allumera à l'étape 5.

> **Rôles :** dans *Paramètres du serveur → Rôles*, place le rôle du bot **au-dessus** des rôles qu'il doit gérer (le rôle whitelist, par exemple). Discord interdit à un bot de donner un rôle placé plus haut que le sien.

---

## 2. Récupérer tes accès Nitrado

Il te faut deux informations.

**a) Le token API long-life**

1. Connecte-toi sur <https://server.nitrado.net>.
2. Clique sur ton profil, puis **Mon compte → Developer Portal** (ou **Long-life tokens**).
3. Crée un nouveau token et coche au minimum les droits **service** et **user_info**. Copie-le dans ton Bloc-notes.

> 💡 Conseil : crée un token réservé à ce bot. En cas de souci, tu pourras le révoquer sans toucher au reste.

**b) L'ID de service**

Ouvre ton serveur DayZ sur le site Nitrado et regarde l'adresse dans la barre du navigateur :

```
https://server.nitrado.net/fr-FR/services/17661226/...
                                          ^^^^^^^^
                                          c'est ton ID de service
```

Note ce nombre.

---

## 3. Louer ton VPS

> 🧒 **En clair :** un VPS (*serveur privé virtuel*), c'est un petit ordinateur que tu loues au mois. Il n'a ni écran ni clavier : il vit dans un centre de données, allumé jour et nuit, et tu le pilotes à distance depuis ton PC. Le bot est très léger : **la plus petite offre suffit**.

### 3.1 Choisir l'offre

N'importe quel hébergeur fait l'affaire. Quelques noms connus avec des centres de données en Europe : **OVHcloud**, **IONOS**, **Hetzner**, **Contabo**, **PulseHeberg**. Les prix et les offres changent souvent : compare directement sur leurs sites.

Ce qu'il faut vérifier au moment de commander :

| Critère | Ce qu'il te faut |
|---|---|
| **Système** (*OS*, *image*, *distribution*) | **Ubuntu 24.04** (ou 22.04). Pas Windows, pas Debian, pas CentOS. |
| **Mémoire** (*RAM*) | **1 Go minimum**, 2 Go pour être tranquille. |
| **Processeur** (*vCPU*) | 1 suffit. |
| **Disque** | 10 Go ou plus (le bot occupe moins de 1 Go). |
| **Lieu du centre de données** | En Europe (France, Allemagne…) de préférence. Ça ne change rien pour le bot, mais l'assistance est plus simple. |
| **Engagement** | Choisis un paiement **au mois, sans engagement**, si l'hébergeur le propose. |

> 💡 **Ce que tu n'as PAS besoin de prendre :** panneau d'administration (Plesk, cPanel…), nom de domaine, sauvegardes payantes (le bot fait déjà les siennes, voir l'étape 9), adresse IPv6 en plus, Windows Server. Décoche ces options si elles sont proposées : elles coûtent plus cher et ne servent à rien ici.

### 3.2 Récupérer tes accès

Une fois la commande passée, l'hébergeur prépare la machine (de quelques minutes à quelques heures) puis t'envoie un **e-mail** (ou affiche les infos dans ton espace client). Tu y trouves trois choses à copier dans ton Bloc-notes :

| Info | À quoi ça ressemble |
|---|---|
| **Adresse IP** (IPv4) | 4 nombres séparés par des points, par exemple `51.83.120.45` |
| **Identifiant** (*utilisateur*, *login*) | le plus souvent `root` ou `ubuntu` |
| **Mot de passe** | une suite de caractères compliquée |

👉 Dans la suite du guide, remplace **`TON_IP`** par l'adresse IP et **`TON_LOGIN`** par l'identifiant (`root` ou `ubuntu`).

> 🧒 *Pas de mot de passe dans l'e-mail ?* Certains hébergeurs te le font choisir pendant la commande, ou proposent un bouton **« Réinitialiser le mot de passe »** dans l'espace client. Si on te propose une **clé SSH** à la place, choisis plutôt le mot de passe : c'est plus simple pour ce guide.

Inutile d'ouvrir des ports dans le pare-feu de l'hébergeur : le bot ne fait que des connexions sortantes (vers Discord et Nitrado).

---

## 4. Te connecter au VPS depuis Windows

> 🧒 **En clair :** ton VPS n'a ni écran ni souris. On le pilote **à distance**, en tapant des commandes depuis ton PC, un peu comme si on envoyait des SMS à un robot qui exécute les ordres. L'outil pour taper ces commandes s'appelle **PowerShell**, et il est déjà installé sur Windows. La connexion elle-même s'appelle **SSH**.

### 4.1 Ouvrir PowerShell

1. Clique sur le bouton **Démarrer** de Windows (ou appuie sur la touche ⊞ du clavier).
2. Tape `powershell`.
3. Clique sur **Windows PowerShell** (ou **Terminal**).

Une fenêtre s'ouvre avec une ligne qui ressemble à :

```
PS C:\Users\TonNom>
```

👉 Ça veut dire : « je suis prêt, tape une commande ». Le `PS` signifie que tu es **sur ton PC**.

**Comment copier-coller dans PowerShell :** **clic droit** dans la fenêtre (ou **Ctrl+V**) pour coller, puis **Entrée** pour lancer.

> 💡 Copie toujours les commandes **en entier**. Ne les retape pas à la main : une seule faute de frappe suffit à tout bloquer.

### 4.2 Se connecter

Dans le bloc ci-dessous, remplace `TON_LOGIN` et `TON_IP`, en gardant le `@` au milieu :

```powershell
ssh TON_LOGIN@TON_IP
```

Exemple, avec l'identifiant `root` et l'adresse `51.83.120.45` :

```powershell
ssh root@51.83.120.45
```

**À la toute première connexion**, un message en anglais demande :

```
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

> 🧒 **En clair :** « c'est la première fois que je vois cette machine, tu confirmes que c'est bien la tienne ? »

Tape `yes` (en toutes lettres), puis **Entrée**.

Ensuite, la machine demande le **mot de passe** (`password:`). Colle-le (clic droit) puis **Entrée**.

> ⚠️ **Quand tu colles le mot de passe, rien ne s'affiche.** Pas d'étoiles, rien. C'est normal. Colle **une seule fois**, puis **Entrée**.

> 🧒 **Un message demande de changer le mot de passe** (`You are required to change your password`, `Current password`, `New password`) ? Certains hébergeurs l'imposent à la première connexion. Recolle l'ancien, puis tape deux fois un nouveau mot de passe **long et unique**. Note-le dans ton Bloc-notes.

**Comment savoir que tu es connecté :** la ligne du bas change et ressemble à :

```
root@vps-1234:~#
```

(ou `ubuntu@...:~$`)

🎉 Tu es **sur ton VPS**. Tout ce que tu tapes maintenant s'exécute là-bas, pas sur ton PC.

> 🧒 **Le repère à retenir pour toute la suite :**
> - la ligne commence par `PS C:\...` → tu es **sur ton PC** ;
> - la ligne commence par `root@` ou `ubuntu@` → tu es **sur le VPS**.
>
> Chaque bloc de commande de ce guide indique où le lancer.

### 4.3 Sécuriser le mot de passe (recommandé)

Le mot de passe envoyé par e-mail a pu être lu par d'autres. **Sur le VPS**, tape :

```bash
passwd
```

Tape (deux fois) un nouveau mot de passe **long** : au moins 16 caractères, jamais utilisé ailleurs. Rien ne s'affiche pendant la frappe, c'est normal. Note-le dans ton Bloc-notes.

> 🧒 *En clair :* ton VPS est visible sur Internet, et des robots essaient des mots de passe au hasard toute la journée. Un mot de passe long les arrête. Le script d'installation ajoute en plus **fail2ban**, qui bloque les adresses qui se trompent trop souvent.

Pour quitter le VPS et revenir sur ton PC, tape `exit` puis **Entrée**.

---

## 5. Envoyer et installer le bot

> 🧒 **En clair :** le bot est dans le zip, sur ton PC. Il faut (a) **envoyer** le zip sur le VPS, comme on envoie un colis, puis (b) **l'installer** là-bas.

### 5.1 Envoyer le zip (depuis ton PC)

1. Ouvre une **nouvelle** fenêtre PowerShell (étape 4.1), en plus de celle déjà connectée. Tu as maintenant deux fenêtres :
   - la fenêtre « VPS », dont la ligne commence par `root@` ou `ubuntu@` ;
   - la nouvelle fenêtre « PC », dont la ligne commence par `PS C:\`.
2. Vérifie que `codex-killfeed-communaute.zip` est bien dans ton dossier **Téléchargements**.
3. **Dans la fenêtre « PC »**, colle cette commande en remplaçant `TON_LOGIN` et `TON_IP`, puis **Entrée** :

```powershell
scp "$env:USERPROFILE\Downloads\codex-killfeed-communaute.zip" TON_LOGIN@TON_IP:~
```

Le mot de passe du VPS est demandé : colle-le, puis **Entrée**. Une ligne de progression s'affiche et finit par `100%`. Le colis est arrivé. ✅

### 5.2 Installer (sur le VPS)

**Dans la fenêtre « VPS »**, colle ce bloc **en entier**, puis **Entrée** :

```bash
sudo apt-get update && sudo apt-get install -y unzip
unzip -o codex-killfeed-communaute.zip
cd codex-killfeed-communaute
sudo bash scripts/install.sh
```

> 🧒 **En clair :** ces 4 lignes disent à la machine : « installe l'outil pour ouvrir les zip, ouvre le zip, entre dans le dossier, lance l'installation ». Beaucoup de texte va défiler : c'est normal, laisse faire. Si `sudo` demande un mot de passe, c'est celui du VPS.

Au bout de 1 à 3 minutes, le script te pose **trois questions**, l'une après l'autre :

1. **Token du bot Discord** : colle le token de l'étape 1, puis **Entrée**.
2. **Token Nitrado** : colle le token de l'étape 2, puis **Entrée**.
3. **ID de service Nitrado** : tape le nombre de l'étape 2, puis **Entrée**.

> ⚠️ **Quand tu colles un token, rien ne s'affiche à l'écran.** C'est voulu. Colle une seule fois (clic droit), puis **Entrée**, même si tu ne vois rien.

Le script vérifie chaque réponse en direct :
- ✔ en vert : c'est bon, il passe à la question suivante ;
- ✘ en rouge : il redemande. Recopie le token depuis ton Bloc-notes.

À la fin, tu dois voir :

```
✅ CodeX KillFeed est en ligne !
```

…et ton bot passe **en ligne** (pastille verte) dans la liste des membres de ton serveur Discord. 🎉

Tu peux fermer les deux fenêtres PowerShell et éteindre ton PC : le bot continue de tourner tout seul sur le VPS. Il redémarre aussi tout seul si le VPS redémarre.

---

## 6. Configurer le bot sur Discord

👉 Suis la partie **« Premiers pas »** du fichier [FONCTIONNALITES.md](FONCTIONNALITES.md#premiers-pas-après-linstallation) : `/setup`, puis `/diagnostic`, puis les options. Elle est identique pour toutes les installations, et le fichier liste aussi **toutes les commandes**.

---

## 7. Au quotidien

Connecte-toi au VPS (étape 4.2) : les commandes ci-dessous se tapent dans la fenêtre « VPS ».

| Je veux… | Commande |
|---|---|
| savoir si le bot tourne | `sudo systemctl status codex-killfeed` |
| voir les logs en direct (Ctrl+C pour quitter) | `sudo journalctl -u codex-killfeed -f` |
| redémarrer le bot | `sudo systemctl restart codex-killfeed` |
| arrêter le bot | `sudo systemctl stop codex-killfeed` |
| changer un token | `sudo nano /opt/codex-killfeed/.env` puis redémarrer |

Dans `nano` : modifie la ligne voulue, puis **Ctrl+O**, **Entrée** pour enregistrer et **Ctrl+X** pour quitter.

> 💶 **Pense au renouvellement de ton VPS.** Si le paiement échoue, l'hébergeur coupe la machine (et finit par l'effacer). Un bot hors ligne sans raison ? Regarde d'abord ton espace client.

---

## 8. Mettre à jour

Quand une nouvelle version sort, le bot te prévient dans `#alertes` et dans `/diagnostic`. Télécharge le zip ici, dans ton dossier **Téléchargements** : <https://github.com/EpSyDev/codex-killfeed-communaute/releases/latest> (fichier `codex-killfeed-communaute.zip`, dans la partie **Assets**). Puis :

```powershell
# sur ton PC
scp "$env:USERPROFILE\Downloads\codex-killfeed-communaute.zip" TON_LOGIN@TON_IP:~
```

```bash
# sur le VPS
rm -rf codex-killfeed-communaute
unzip -o codex-killfeed-communaute.zip
cd codex-killfeed-communaute
sudo bash scripts/update.sh
```

Ta configuration et ton historique sont conservés. La base est en plus copiée dans `/opt/codex-killfeed/data/sauvegardes/` juste avant la mise à jour.

---

## 9. Sauvegardes

Le bot copie **chaque jour** sa base (whitelist, comptes liés, historique des kills, réglages) dans `/opt/codex-killfeed/data/backups/`, et garde les 7 derniers jours. `/diagnostic` affiche la date de la dernière copie.

Ces copies restent **sur le VPS** : si l'hébergeur perd la machine, elles disparaissent avec. De temps en temps, rapatrie une copie sur ton PC. Ouvre une fenêtre PowerShell **sur ton PC** et lance (en remplaçant `TON_LOGIN` et `TON_IP`) :

```powershell
scp TON_LOGIN@TON_IP:/opt/codex-killfeed/codex-kit.db "$env:USERPROFILE\Documents\codex-sauvegarde.db"
```

La copie arrive dans ton dossier **Documents**. Garde aussi une copie de ton `.env` (tes tokens) en lieu sûr.

**Remettre une sauvegarde** (sur le VPS) :

```bash
sudo systemctl stop codex-killfeed
ls /opt/codex-killfeed/data/backups/
sudo cp /opt/codex-killfeed/data/backups/codex-kit-AAAA-MM-JJ.db /opt/codex-killfeed/codex-kit.db
sudo chown codex:codex /opt/codex-killfeed/codex-kit.db
sudo systemctl start codex-killfeed
```

(remplace `AAAA-MM-JJ` par la date choisie dans la liste affichée par `ls`)

---

## 10. Dépannage

**Le script dit « Token refusé par Discord »**
Le token a été mal copié ou régénéré depuis. Retourne sur le Developer Portal, fais **Reset Token** et recopie-le.

**Le script dit « Nitrado refuse ce couple token / ID de service »**
Vérifie que l'ID de service est bien le nombre de l'URL (étape 2b), et que ton token a les droits *service*.

**Le script dit « prévu pour Ubuntu/Debian »**
Le VPS a été livré avec un autre système. Dans l'espace client de l'hébergeur, cherche **Réinstaller** (*Reinstall*, *Rebuild*) et choisis **Ubuntu 24.04**. Attention : la réinstallation efface tout le VPS.

**Le bot est en ligne mais les commandes `/` n'apparaissent pas**
Discord peut mettre quelques minutes à les afficher. Ferme et rouvre Discord (Ctrl+R sur PC). Si rien ne change, réinvite le bot avec le scope `applications.commands` (étape 1.5).

**Le bot ne démarre pas, et les logs parlent de « privileged intents »**
Active les deux options **SERVER MEMBERS INTENT** et **MESSAGE CONTENT INTENT** (étape 1.4), puis `sudo systemctl restart codex-killfeed`.

**Aucun kill ne s'affiche**
- Lance `/diagnostic`.
- Vérifie que ton serveur DayZ tourne et que des joueurs sont connectés.
- Vérifie dans Nitrado que les **logs ADM** sont activés dans les paramètres du serveur.
- Regarde les logs : `sudo journalctl -u codex-killfeed -n 100`.

**Les horaires (NO PVP, redémarrages) sont décalés d'une ou deux heures**
`/diagnostic` affiche l'heure de la machine. Si elle est fausse : `sudo timedatectl set-timezone Europe/Paris`, puis `sudo systemctl restart codex-killfeed`.

**`ssh` répond « Permission denied »**
Mauvais identifiant ou mauvais mot de passe. Vérifie `TON_LOGIN` (`root` ou `ubuntu`) dans l'e-mail de l'hébergeur. Mot de passe perdu ? Utilise le bouton **Réinitialiser le mot de passe** de l'espace client.

**`ssh` répond « Connection timed out » ou « Connection refused »**
Vérifie l'adresse IP et que le VPS est bien **démarré** dans l'espace client. Après plusieurs mauvais mots de passe, fail2ban bloque ton adresse pendant 10 minutes : patiente, puis réessaie.

**`ssh` affiche « WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED »**
Normal si tu viens de réinstaller le VPS. Sur ton PC, lance `ssh-keygen -R TON_IP`, puis reconnecte-toi.

**Je veux tout désinstaller**

```bash
sudo systemctl disable --now codex-killfeed
sudo rm /etc/systemd/system/codex-killfeed.service
sudo rm -rf /opt/codex-killfeed
sudo userdel codex
```

Pense ensuite à **résilier le VPS** chez l'hébergeur, sinon il continue d'être facturé.

---

*CodeX KillFeed, créé par EpSy et offert à la communauté.*
