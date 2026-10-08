# Assistant de conversation Jev (Windows PC)

[简体中文](../README.md) | [English](README.en.md) | [Français](README.fr.md) | [Русский](README.ru.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

**Version : v1.4.0**

## Nouveautés v1.4.0

- **Relire avant l’analyse** : modifiez le texte, les interlocuteurs et l’ordre, ajoutez ou supprimez des messages. L’analyse commence après confirmation. Le texte original et les compléments initiaux restent contrôlés ; les brouillons restent en mémoire.
- **Objectif de réponse** : réponse générale, refus poli, clarification, clôture du sujet ou apaisement du conflit. Compatible avec la longueur, le ton et la langue ; conservé pour la session et figé à la confirmation.
- **Reformulation individuelle** : plus court, plus naturel ou plus délicat, avec annulation et nouvelle tentative. Toute modification efface les scores ; reclassement manuel. Les réponses peuvent uniquement être copiées.

Ce projet est un réaménagement pour Windows PC basé sur la banque de questions de jugement et le flux d'analyse du projet open source https://github.com/Liyucheng1997/332_lab-jev-chat.

La version Windows permet de sélectionner une zone de conversation sur le bureau, de reconnaître le texte visible via l'OCR local, puis d'analyser la conversation avec Jev. Vous pouvez aussi configurer un modèle de réponse pour générer trois réponses candidates, que Jev classe ensuite. Les réponses candidates sont uniquement destinées à la consultation et à la copie — elles ne sont jamais remplies ni envoyées automatiquement.

[Télécharger v1.4.0 pour Windows](https://github.com/QCJLchina/Jev-chat-assistant/releases/tag/v1.4.0)

## Nouveautés de v1.3.1

- **Contexte complet** : tous les messages sont analysés par défaut ; vous pouvez choisir les 10, 20 ou 50 derniers. Les échanges antérieurs sont ajoutés avant les messages actuels, puis la sélection est appliquée. Le corps des messages retenus et le contexte explicatif sont limités ensemble à 20 000 caractères : réduisez la sélection ou le texte si nécessaire, sans troncature silencieuse. Les statistiques indiquent le total, les messages utilisés, les caractères, la limite choisie et les messages omis. Les contrôles des transactions couvrent toute la saisie, y compris les messages omis, les échanges antérieurs et le contexte explicatif.
- **Échanges antérieurs et contexte explicatif** : les préfixes `我：` / `对方：` et `me:` / `other:` sont acceptés pour les échanges antérieurs ; le contexte explicatif ne constitue pas un message. Ces compléments restent uniquement en mémoire et peuvent être effacés manuellement. Ils sont effacés au changement de fenêtre cible liée ou à la fermeture de l’application. Un changement de contact dans la même fenêtre ne peut pas être détecté automatiquement : effacez les compléments avant de changer de conversation.
- **Suivi de fenêtre** : les nouvelles installations utilisent le suivi de fenêtre par défaut. Les zones fixes existantes conservent le mode Zone fixe de l’écran, même après une nouvelle sélection ; choisissez Suivre la fenêtre avant de sélectionner à nouveau pour activer le suivi. Dans ce mode, le déplacement de la fenêtre déplace la sélection. Le suivi entre écrans de DPI différents fonctionne uniquement si la géométrie de la fenêtre reste cohérente. Une variation de taille supérieure à 2 DIP impose une nouvelle sélection. Après fermeture de la cible ou redémarrage de l’application, confirmez une fenêtre candidate avant de rétablir la liaison.
- **Capture à la demande** : l’OCR est exécuté au clic sur Analyser, sans OCR continu en arrière-plan ni capture en arrière-plan des fenêtres réduites ou masquées. Restaurez la fenêtre et rendez la zone de conversation visible.

## Fonctionnalités publiées de v1.3.0 (comportement historique)

- **Coller le texte d’une conversation** : aucune sélection de zone nécessaire. Les préfixes `我：` / `对方：` et `me:` / `other:` sont pris en charge ; les préfixes anglais sont insensibles à la casse et les deux formes de deux-points sont acceptées. La saisie est limitée à 20 000 caractères ; l’analyse utilise les 10 derniers messages, mais les contrôles de sécurité des transactions portent sur la saisie complète.
- **Annuler et reprendre aux étapes sauvegardées** : les évaluations et réponses candidates déjà obtenues sont conservées ; la reprise commence à la première étape inachevée. Les candidates restent copiables si le classement échoue. Une nouvelle tentative réutilise la configuration figée de la tâche initiale, notamment les notes de relation, le modèle et les préférences de réponse. Relancez une analyse pour appliquer de nouveaux réglages. L’annulation arrête les étapes suivantes et ignore les résultats périmés, mais une requête HTTP en cours peut encore se terminer ou expirer.
- **Préférences de réponse** : enregistrez des préférences globales de longueur, de ton et de langue, avec des ajustements temporaires pour la session sur la page d’accueil. La langue des réponses est indépendante de celle de l’interface : chinois simplifié, anglais, français, russe, japonais et coréen, ou suivi de la langue de l’interface. Le texte des conversations et les résultats des étapes restent en mémoire ; aucun historique local des conversations n’est enregistré.

## Prérequis

- Windows 10/11 (x64)
- Microsoft Edge WebView2 Runtime
- Python 3.12, Node.js 20+ et npm pour exécuter depuis les sources ou compiler
- Une clé API TypeSafe / Jev à la première utilisation ; la clé du modèle de réponse est facultative

## Installation et lancement

Ouvrez PowerShell à la racine du dépôt :

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install.ps1
powershell -ExecutionPolicy Bypass -File .\windows\start.ps1
```

À la première utilisation, saisissez votre clé API Jev dans la page de paramètres. Pour générer des réponses candidates, ajoutez également une configuration de modèle de réponse, sa clé API et le nom du modèle.

## Langues de l'interface

Chinois simplifié, English, Français, Русский, 日本語 et 한국어 sont pris en charge. Sélectionnez la « Langue de l'interface » dans la page de paramètres : elle est enregistrée et appliquée immédiatement, sans redémarrage et sans soumettre les autres paramètres non enregistrés. Les nouveaux utilisateurs suivent par défaut la langue d'interface de Windows, avec repli sur l'anglais pour les langues système non prises en charge ; les utilisateurs existants conservent le chinois simplifié après la mise à niveau.

Cette localisation couvre l'interface, les messages et les libellés des résultats d'analyse. Le texte des conversations et les notes de relation saisies par l'utilisateur ne sont pas traduits, et l'OCR reste inchangé. Les réponses candidates suivent une préférence de langue distincte : chinois simplifié, anglais, français, russe, japonais ou coréen, ou la langue de l’interface.

## Utilisation

1. Ouvrez la fenêtre de conversation à assister et entrez dans une conversation textuelle classique.
2. Cliquez sur « Sélectionner la zone de conversation » et faites glisser pour couvrir les messages.
3. Cliquez sur « Capturer et relire », corrigez les messages et choisissez l’objectif, puis cliquez sur « Confirmer et analyser ».
4. Vérifiez et copiez une candidate appropriée, puis décidez vous-même de l'envoi.

Le programme ne lit jamais les bases de données de conversation, ne manipule pas les zones de saisie et n'envoie rien automatiquement. Les transferts d'argent, les paquets rouges et tout contenu transactionnel sont bloqués par les contrôles de sécurité. Les images, les messages vocaux et les cartes citées ne peuvent pas encore être restitués de manière fiable.

## Compilation

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
```

Résultat : `dist\Jev对话助手\Jev对话助手.exe`. PyInstaller regroupe les ressources Vue, les modèles OCR et le runtime Python, et produit également l'assistant de mise à jour `update_helper.exe` (à distribuer à côté de l'exécutable principal). Conservez le dossier `_internal` voisin lors de la distribution ; l'ordinateur cible doit aussi disposer de Microsoft Edge WebView2 Runtime.

## Mises à jour intégrées

L'application peut récupérer ses mises à jour elle-même. Quelques secondes après le lancement, elle vérifie silencieusement les GitHub Releases ; lorsqu'une nouvelle version existe, une bannière apparaît en haut de la page d'accueil, et vous pouvez aussi vérifier manuellement dans « Version et mises à jour » des paramètres. Cette vérification interroge uniquement `api.github.com` pour connaître le numéro de la dernière version — aucun contenu de conversation n'est envoyé.

Après confirmation, l'application télécharge l'archive en arrière-plan (avec progression et annulation), vérifie son SHA256 (activé lorsque la publication inclut un `SHA256SUMS.txt` ; sinon repli sur un contrôle de taille) et l'extrait dans un dossier temporaire. En cliquant sur « Redémarrer et installer », le programme principal se ferme ; l'assistant `update_helper.exe` remplace atomiquement le répertoire d'installation et redémarre la nouvelle version. En cas d'échec, un retour à l'ancienne version est effectué. Les réglages et données sont dans `%APPDATA%` et ne sont pas affectés par la mise à jour.

## Confidentialité

- L'OCR s'exécute localement ; après avoir lancé l'analyse, le texte reconnu est envoyé à TypeSafe Jev.
- Avec un modèle de réponse activé, le texte de la conversation et le jugement Jev sont envoyés au service choisi pour générer les réponses candidates.
- Les clés API sont stockées dans le Gestionnaire d'informations d'identification de Windows ; `%APPDATA%\JevChatAssistant\settings.json` ne contient que des réglages non secrets.
- La liste des modèles et les tests de connexion n'envoient jamais de contenu de conversation.

Pour la configuration, les détails d'utilisation et les limites, voir [`windows/README.md`](../windows/README.md).
