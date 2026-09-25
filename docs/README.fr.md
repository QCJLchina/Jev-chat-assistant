# Assistant de conversation Jev (Windows PC)

[简体中文](../README.md) | [English](README.en.md) | [Français](README.fr.md) | [Русский](README.ru.md) | [日本語](README.ja.md)

**Version : v1.1.1**

Ce projet est un réaménagement pour Windows PC basé sur la banque de questions de jugement et le flux d'analyse du projet open source https://github.com/Liyucheng1997/332_lab-jev-chat.

La version Windows permet de sélectionner une zone de conversation sur le bureau, de reconnaître le texte visible via UI Automation et l'OCR local, puis d'analyser la conversation avec Jev. Vous pouvez aussi configurer un modèle de réponse pour générer trois réponses candidates, que Jev classe ensuite. Les réponses candidates sont uniquement destinées à la consultation et à la copie — elles ne sont jamais remplies ni envoyées automatiquement.

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

Chinois simplifié, English, Français, Русский et 日本語 sont pris en charge. Sélectionnez la « Langue de l'interface » dans la page de paramètres : elle est enregistrée et appliquée immédiatement, sans redémarrage et sans soumettre les autres paramètres non enregistrés. Les nouveaux utilisateurs suivent par défaut la langue d'interface de Windows, avec repli sur l'anglais pour les langues système non prises en charge ; les utilisateurs existants conservent le chinois simplifié après la mise à niveau.

Cette localisation couvre uniquement l'interface, les messages et les libellés des résultats d'analyse. Le texte des conversations, les notes de relation saisies par l'utilisateur et les réponses candidates restent dans leur langue d'origine ; l'OCR et la génération de réponses en chinois restent inchangés.

## Utilisation

1. Ouvrez la fenêtre de conversation à assister et entrez dans une conversation textuelle classique.
2. Cliquez sur « Sélectionner la zone de conversation » et faites glisser pour couvrir les messages.
3. Cliquez sur « Analyser la sélection actuelle » pour voir le jugement Jev et les réponses candidates.
4. Vérifiez et copiez une candidate appropriée, puis décidez vous-même de l'envoi.

Le programme ne lit jamais les bases de données de conversation, ne manipule pas les zones de saisie et n'envoie rien automatiquement. Les transferts d'argent, les paquets rouges et tout contenu transactionnel sont bloqués par les contrôles de sécurité. Les images, les messages vocaux et les cartes citées ne peuvent pas encore être restitués de manière fiable.

## Compilation

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
```

Résultat : `dist\Jev对话助手\Jev对话助手.exe`. Conservez le dossier `_internal` voisin lors de la distribution ; l'ordinateur cible doit aussi disposer de Microsoft Edge WebView2 Runtime.

## Confidentialité

- L'OCR s'exécute localement ; après avoir lancé l'analyse, le texte reconnu est envoyé à TypeSafe Jev.
- Avec un modèle de réponse activé, le texte de la conversation et le jugement Jev sont envoyés au service choisi pour générer les réponses candidates.
- Les clés API sont stockées dans le Gestionnaire d'informations d'identification de Windows ; `%APPDATA%\JevChatAssistant\settings.json` ne contient que des réglages non secrets.
- La liste des modèles et les tests de connexion n'envoient jamais de contenu de conversation.

Pour la configuration, les détails d'utilisation et les limites, voir [`windows/README.md`](../windows/README.md).
