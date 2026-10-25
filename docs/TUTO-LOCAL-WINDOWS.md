# Faire tourner CodeX KillFeed sur ton PC Windows (gratuit)

Ce guide part de zéro. Aucune connaissance en informatique n'est nécessaire : tu fais des clics et des copier-coller, dans l'ordre.

**Durée :** 20 minutes environ.
**Coût :** 0 €.

> 🧒 **Comment ça marche, en 30 secondes**
>
> Ton bot est un petit programme qui surveille ton serveur DayZ et écrit les événements dans Discord. Pour ça, il doit **tourner en permanence**. Ici, on le fait tourner **sur ton propre PC**, en arrière-plan, sans fenêtre : tu n'as rien à garder ouvert.
>
> 📝 **Avant de commencer :** ouvre le **Bloc-notes** de Windows. Tu vas y coller 3 informations (token Discord, token Nitrado, ID de service Nitrado). Garde-le ouvert jusqu'à la fin, et ne le partage avec personne.

## ⚠️ À savoir avant de choisir cette solution

Le bot ne fonctionne **que quand ton PC est allumé et connecté à Internet**. Concrètement :

| Situation | Conséquence |
|---|---|
| Tu éteins le PC | Le bot est hors ligne. |
| Le PC se met en veille | Le bot est hors ligne (on désactive la veille à l'étape 6). |
| Windows redémarre pour une mise à jour | Le bot repart tout seul (option « démarrage à l'allumage », étape 5) ou quand tu rouvres ta session. |
| Ta box Internet coupe | Le bot est hors ligne, puis revient tout seul. |

👉 Cette solution est idéale si **ton PC reste allumé de toute façon** (PC fixe, PC de jeu…). Sinon, regarde plutôt le guide [TUTO-VPS.md](TUTO-VPS.md) : un petit serveur loué 2 à 6 € par mois, allumé 24h/24.

**Il te faut :**
- un serveur DayZ console (PS ou Xbox) loué chez **Nitrado** ;
- être **administrateur** de ton serveur Discord ;
- un PC sous **Windows 10 ou 11**, avec une connexion Internet ;
- le fichier `codex-killfeed-communaute.zip`.

---

## Sommaire

1. [Créer ton bot Discord](#1-créer-ton-bot-discord)
2. [Récupérer tes accès Nitrado](#2-récupérer-tes-accès-nitrado)
3. [Installer Python](#3-installer-python)
4. [Placer le dossier au bon endroit](#4-placer-le-dossier-au-bon-endroit)
5. [Lancer l'installation](#5-lancer-linstallation)
6. [Empêcher la mise en veille](#6-empêcher-la-mise-en-veille)
7. [Configurer le bot sur Discord](#7-configurer-le-bot-sur-discord)
8. [Au quotidien](#8-au-quotidien)
9. [Mettre à jour](#9-mettre-à-jour)
10. [Sauvegarder](#10-sauvegarder)
11. [Dépannage](#11-dépannage)
12. [Désinstaller](#12-désinstaller)

---

## 1. Créer ton bot Discord

C'est **ton** bot : il aura le nom et l'avatar que tu choisis.

👉 **Suis l'étape 1 du guide VPS** : [TUTO-VPS.md, étape 1](TUTO-VPS.md#1-créer-ton-bot-discord). Elle est identique, quel que soit l'endroit où le bot tournera.

À la fin de cette étape, tu dois avoir :
- ✅ ton **token Discord**, collé dans ton Bloc-notes ;
- ✅ les deux options **SERVER MEMBERS INTENT** et **MESSAGE CONTENT INTENT** activées ;
- ✅ le bot **invité** sur ton serveur Discord (il apparaît « hors ligne » dans la liste des membres : c'est normal).

## 2. Récupérer tes accès Nitrado

👉 **Suis l'étape 2 du guide VPS** : [TUTO-VPS.md, étape 2](TUTO-VPS.md#2-récupérer-tes-accès-nitrado).

À la fin de cette étape, tu dois avoir dans ton Bloc-notes :
- ✅ ton **token Nitrado** ;
- ✅ ton **ID de service** (un nombre, par exemple `17661226`).

---

## 3. Installer Python

> 🧒 **En clair :** Python est le « moteur » qui fait tourner le bot. Il est gratuit et ne fait rien tout seul : il attend simplement qu'on lui demande de lancer le bot.

**Première chose : regarde si tu l'as déjà.** Appuie sur la touche **⊞** du clavier, tape `powershell`, ouvre **Windows PowerShell**. Dans la fenêtre qui s'ouvre, tape :

```powershell
py -0
```

puis **Entrée**. Si tu vois une ligne qui contient `3.10`, `3.11`, `3.12` ou `3.13`, **c'est bon, passe à l'étape 4**. Si tu vois une erreur du genre « le terme 'py' n'est pas reconnu », il faut l'installer :

**Méthode simple (recommandée) :** dans cette même fenêtre PowerShell, copie-colle cette commande (clic droit pour coller), puis **Entrée** :

```powershell
winget install --id Python.Python.3.13 -e --accept-package-agreements --accept-source-agreements
```

Attends la fin (1 à 2 minutes). Si Windows demande l'autorisation de modifier l'appareil, clique sur **Oui**. Quand tu vois `Installé correctement` (ou `Successfully installed`), **ferme la fenêtre PowerShell**.

> **`winget` n'est pas reconnu ?** Passe à la méthode manuelle ci-dessous.

**Méthode manuelle (si winget ne marche pas) :**

1. Va sur <https://www.python.org/downloads/windows/>.
2. Cherche la ligne **Python 3.13.x** dans la liste (pas la version la plus récente affichée en gros : on a vérifié la 3.13).
3. Clique sur **Windows installer (64-bit)** et lance le fichier téléchargé.
4. ⚠️ **Sur le premier écran, coche la case en bas « Add python.exe to PATH »**, puis clique sur **Install Now**.
5. Quand c'est fini, clique sur **Close**.

---

## 4. Placer le dossier au bon endroit

> 🧒 **En clair :** le bot va vivre dans un dossier de ton PC, qu'il ne faudra plus déplacer ensuite. On le met à la **racine du disque C:**, un endroit simple et sûr.
>
> ⚠️ **Surtout pas dans le Bureau, les Documents ou les Téléchargements** : sur beaucoup de PC, ces dossiers sont synchronisés par **OneDrive**, qui peut abîmer le fichier de données du bot.

1. Ouvre ton dossier **Téléchargements** et fais un **clic droit** sur `codex-killfeed-communaute.zip`.
2. Clique sur **Extraire tout…** (sur Windows 11 : *Afficher plus d'options* si besoin).
3. Dans la fenêtre, **efface** le chemin proposé et tape : `C:\`
4. Coche **Afficher les fichiers extraits une fois l'opération terminée**, puis clique sur **Extraire**.

Tu obtiens un dossier **`C:\codex-killfeed-communaute`**. À l'intérieur, tu dois voir notamment :

- `INSTALLER-WINDOWS`
- `DEMARRER-LE-BOT`
- `ARRETER-LE-BOT`
- `VOIR-LES-LOGS`

> **Tu as un dossier dans un dossier** (`C:\codex-killfeed-communaute\codex-killfeed-communaute`) ? Ouvre le dossier du dessous, sélectionne tout (**Ctrl+A**), coupe (**Ctrl+X**), reviens dans `C:\codex-killfeed-communaute`, colle (**Ctrl+V**), et supprime le dossier vide.

---

## 5. Lancer l'installation

> 🧒 **En clair :** un seul double-clic. Le programme d'installation prépare tout, te demande tes 3 informations, vérifie qu'elles sont correctes, et démarre le bot.

1. Dans `C:\codex-killfeed-communaute`, **double-clique** sur **`INSTALLER-WINDOWS`**.

2. **Un écran bleu « Windows a protégé votre ordinateur » apparaît ?** C'est normal : le fichier vient d'un zip téléchargé, et Windows se méfie par principe de tout ce qu'il ne connaît pas. Clique sur **Informations complémentaires**, puis sur **Exécuter quand même**.

3. Une fenêtre noire s'ouvre et affiche des étapes avec `==>`. Laisse faire : l'installation des composants prend **1 à 3 minutes**, et beaucoup de texte défile. C'est normal.

4. Le programme te pose **trois questions**, l'une après l'autre :

   | Question affichée | Ce que tu réponds |
   |---|---|
   | **Token du bot Discord** | colle le token Discord de ton Bloc-notes, puis **Entrée** |
   | **Token Nitrado long-life** | colle le token Nitrado, puis **Entrée** |
   | **ID de service Nitrado** | tape le nombre (par exemple `17661226`), puis **Entrée** |

   > ⚠️ **Quand tu colles un token, tu vois des étoiles (`*`) ou rien du tout.** C'est voulu, pour que personne ne puisse le lire par-dessus ton épaule. Colle **une seule fois** (clic droit dans la fenêtre), puis **Entrée**, même si tu ne vois rien.

   Le programme **vérifie chaque réponse en direct** :
   - `[OK] Token Discord valide (bot : …)` → c'est bon, il passe à la suite ;
   - `[X] Token refusé…` → il redemande. Recopie le token depuis ton Bloc-notes.

5. S'il te prévient de **SERVER MEMBERS INTENT** ou **MESSAGE CONTENT INTENT** (en jaune), retourne sur le Developer Portal de Discord (page **Bot**), active ces options, clique sur **Save Changes**, puis relance l'installation (double-clic sur `INSTALLER-WINDOWS`, rien n'est perdu).

6. **« Démarrer le bot dès l'allumage du PC ? (O/N) »** → tape `O` puis **Entrée** (conseillé).

   Windows affiche alors une fenêtre **« Voulez-vous autoriser cette application à apporter des modifications ? »** → clique sur **Oui**.

   > 🧒 **En clair :** avec `O`, le bot démarre **une minute après l'allumage du PC**, même si personne n'ouvre la session Windows (pratique après une coupure de courant ou une mise à jour Windows la nuit). Avec `N`, il démarre seulement quand tu ouvres ta session.
   >
   > Ton compte Windows n'a pas les droits administrateur, ou tu as cliqué sur **Non** ? Pas grave : le programme le dit et garde le démarrage à l'ouverture de session.

7. **« Désactiver la mise en veille quand le PC est branché ? (O/N) »** → tape `O` puis **Entrée**. (Si ça échoue, on le fait à la main à l'étape 6 du guide.)

8. Le programme démarre le bot et attend 20 secondes. À la fin, tu dois voir :

   ```
   [OK] CodeX KillFeed est en ligne !
   ```

   …et ton bot passe **en ligne** (pastille verte) dans la liste des membres de ton serveur Discord. 🎉

Tu peux fermer la fenêtre noire : le bot continue de tourner en arrière-plan, sans fenêtre.

> 🧒 **Et quand je redémarre mon PC ?** Le bot repart tout seul : une minute après l'allumage si tu as répondu `O` à la question du démarrage, sinon dès que tu **ouvres ta session Windows** (mot de passe ou code PIN). Tu n'as rien à lancer.

---

## 6. Empêcher la mise en veille

Si le script l'a déjà fait (tu as répondu `O`), tu peux sauter cette étape. Sinon :

- **Windows 11 :** **Paramètres** → **Système** → **Alimentation** (ou *Alimentation et batterie*) → **Écran, veille et mise en veille prolongée**. À la ligne **« Sur secteur, mettre mon appareil en veille après »**, choisis **Jamais**.
- **Windows 10 :** **Paramètres** → **Système** → **Alimentation et mise en veille**. Dans **Veille**, à la ligne **« Sur le secteur, mettre en veille après »**, choisis **Jamais**.

> 🧒 *Les noms exacts peuvent changer un peu selon ta version de Windows. Tu cherches seulement l'option de veille « sur secteur » / « quand l'appareil est branché ».*

Tu peux laisser l'**écran** s'éteindre : seule la veille de l'ordinateur arrête le bot.

---

## 7. Configurer le bot sur Discord

👉 **Suis la partie « Premiers pas »** du fichier [FONCTIONNALITES.md](FONCTIONNALITES.md#premiers-pas-après-linstallation) : `/setup`, puis `/diagnostic`, puis les options. Elle est identique pour toutes les installations, et le fichier liste aussi **toutes les commandes**.

---

## 8. Au quotidien

Dans le dossier `C:\codex-killfeed-communaute`, **double-clique** sur :

| Je veux… | Je double-clique sur |
|---|---|
| **arrêter** le bot | `ARRETER-LE-BOT` |
| le **redémarrer** | `DEMARRER-LE-BOT` |
| voir son **journal** en direct (pour comprendre un souci) | `VOIR-LES-LOGS` |
| changer un token | ouvre `.env` avec le Bloc-notes (clic droit → *Ouvrir avec* → *Bloc-notes*), change la ligne, enregistre, puis double-clique sur `DEMARRER-LE-BOT` |

> 🧒 **Le bot s'arrête de lui-même ?** S'il plante, il se relance tout seul au bout de 30 secondes. Il ne s'arrête vraiment que si tu éteins le PC, si tu fermes ta session Windows (sauf avec le démarrage à l'allumage), ou si tu double-cliques sur `ARRETER-LE-BOT`.
>
> 🗄️ **Sauvegardes :** chaque jour, le bot copie sa base dans `data\backups` (les 7 derniers jours sont gardés). En cas de pépin, arrête le bot, remplace `codex-kit.db` par la copie du jour voulu (renommée `codex-kit.db`), puis redémarre.

> ⚠️ **Après une mise à jour Windows qui redémarre le PC** : si tu as choisi le démarrage à l'allumage, le bot repart tout seul. Sinon, il reste éteint tant que personne n'a ouvert la session Windows. Pour changer d'avis, relance simplement `INSTALLER-WINDOWS` (rien n'est perdu).

---

## 9. Mettre à jour

Quand une nouvelle version sort, le bot te prévient dans `#alertes` et dans `/diagnostic`.

**La méthode simple (à partir de la version 1.2) :** sur Discord, tape **`/maj`**, puis clique sur **Installer maintenant**. Le bot se met à jour tout seul, redémarre et confirme dans `#alertes` (1 à 2 minutes hors ligne). Tes réglages et tes données sont conservés.

> 🧒 **En clair :** `/maj`, c'est le bouton « mettre à jour » du bot. Il fait lui-même le téléchargement, la sauvegarde et le redémarrage.

**La méthode manuelle** (version plus ancienne que la 1.2, ou si `/maj` ne marche pas). Télécharge le zip ici : <https://github.com/EpSyDev/codex-killfeed-communaute/releases/latest> (fichier `codex-killfeed-communaute.zip`, dans la partie **Assets**), puis :

0. Double-clique sur **`ARRETER-LE-BOT`** (on ne remplace pas les fichiers d'un bot en marche).
1. **Extrais le nouveau zip dans `C:\`**, comme à l'étape 4.
2. Windows demande ce qu'il faut faire des fichiers qui existent déjà : clique sur **Remplacer les fichiers dans la destination**.
3. Double-clique sur **`INSTALLER-WINDOWS`**.

Ta configuration (`.env`) et tes données (whitelist, historique, réglages) sont **conservées** : elles ne sont pas dans le zip, donc rien ne les écrase. Le programme ne te redemande pas tes tokens.

---

## 10. Sauvegarder

Toutes les données du bot (whitelist, comptes liés, historique des kills, réglages) tiennent dans **un seul fichier** : **`codex-kit.db`**, dans `C:\codex-killfeed-communaute`.

Pour sauvegarder, **copie** ce fichier, ainsi que **`.env`** (tes tokens), sur une clé USB ou un autre disque.

> ⚠️ Ne mets jamais le `.env` dans un endroit partagé (Drive, mail, Discord) : il contient les mots de passe de ton bot.

---

## 11. Dépannage

**« Windows a protégé votre ordinateur » au double-clic**
Normal. Clique sur **Informations complémentaires**, puis **Exécuter quand même**.

**`[ERREUR] Python est introuvable`**
Python n'est pas installé, ou il a été installé pendant que la fenêtre était ouverte. Refais l'étape 3, **ferme** toutes les fenêtres, puis relance `INSTALLER-WINDOWS`.

**`[ERREUR] Le dossier est dans OneDrive` / `contient des accents`**
Déplace le dossier `codex-killfeed-communaute` à la racine du disque : `C:\codex-killfeed-communaute` (étape 4), puis relance.

**`[ERREUR] L'installation des dépendances a échoué`**
Vérifie ta connexion Internet. Si tu as une version de Python très récente (3.15 ou plus), installe la 3.13 (étape 3) et relance.

**`[X] Token refusé par Discord`**
Le token est mal copié ou a été régénéré. Sur le Developer Portal, page **Bot**, fais **Reset Token** et recopie-le **en entier**.

**`[X] Nitrado refuse ce couple token / ID de service`**
Vérifie que l'ID de service est bien le nombre de l'adresse du serveur (étape 2) et que ton token a les droits *service*.

**Le bot est « hors ligne » sur Discord**
- Ton PC est-il allumé, et as-tu ouvert ta session Windows ?
- Double-clique sur `DEMARRER-LE-BOT`, attends 30 secondes.
- Double-clique sur `VOIR-LES-LOGS` : la dernière ligne indique la cause (token refusé, option Discord manquante…).

**Les logs parlent de « privileged intents »**
Active **SERVER MEMBERS INTENT** et **MESSAGE CONTENT INTENT** sur le Developer Portal (page **Bot**), clique sur **Save Changes**, puis double-clique sur `DEMARRER-LE-BOT`.

**Les commandes `/` n'apparaissent pas dans Discord**
Discord peut mettre quelques minutes. Ferme et rouvre Discord (**Ctrl+R**). Sinon, réinvite le bot avec les deux cases `bot` et `applications.commands` (étape 1).

**Aucun kill ne s'affiche**
Tape `/diagnostic`, vérifie que des joueurs sont connectés, et que les **logs ADM** sont activés dans les paramètres Nitrado.

**Mon antivirus bloque quelque chose**
Le bot n'est pas signé numériquement (c'est un projet communautaire gratuit). Si ton antivirus bloque le dossier, ajoute `C:\codex-killfeed-communaute` à ses exceptions.

---

## 12. Désinstaller

1. Double-clique sur `ARRETER-LE-BOT`.
2. Ouvre PowerShell (touche **⊞**, tape `powershell`, **Entrée**) et colle :

   ```powershell
   Unregister-ScheduledTask -TaskName "CodeX KillFeed" -Confirm:$false
   ```

   > 🧒 *Cette commande retire le démarrage automatique.*
3. **Supprime** le dossier `C:\codex-killfeed-communaute` (après avoir sauvegardé `codex-kit.db` si tu veux garder tes données).
4. Sur le Developer Portal de Discord, tu peux aussi supprimer l'application du bot.

---

*CodeX KillFeed, créé par EpSy et offert à la communauté.*
