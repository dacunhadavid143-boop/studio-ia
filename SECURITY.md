# Sécurité

## Gestion des clés API

| Mesure | Détail |
|---|---|
| **Aucune clé dans le code** | Les clés sont lues uniquement depuis les variables d'environnement (`studio_ia/config.py`, fonction `cle()`). |
| **Fichier `.env` local, jamais publié** | `.gitignore` exclut `.env` et toutes ses variantes. Seul `.env.example` (vide) est versionné. |
| **Masquage dans les messages** | Toute clé connue est remplacée par `<NOM masquée>` avant d'être affichée (fonction `masquer()`), y compris dans les erreurs renvoyées par les API. |
| **Détection automatique des fuites** | Hook `pre-commit` [gitleaks](https://github.com/gitleaks/gitleaks) en local + scan gitleaks dans la CI GitHub à chaque push. |
| **Tests sans clé** | Toute la suite de tests tourne sans aucune clé API, donc aucune clé n'est nécessaire dans la CI. |

## Robustesse et maîtrise des coûts

- **Plafond de budget** : avant toute génération vidéo payante, le coût est estimé ; au-delà de `--budget-max` (10 $ par défaut), l'exécution s'arrête.
- **Validation humaine** : le script et le découpage sont affichés et doivent être validés avant de dépenser quoi que ce soit (sauf `--oui`).
- **Cache par étape** : chaque résultat (script, voix, plans, musique) est sauvegardé ; une relance ne repaie jamais une étape déjà faite.
- **Téléchargements** : HTTPS obligatoire, taille plafonnée (500 Mo), écriture atomique.
- **Pas de shell** : ffmpeg est appelé avec une liste d'arguments (`subprocess.run([...])`), jamais via une chaîne interprétée par un shell : pas d'injection de commande possible.
- **Sous-titres** : les caractères de contrôle du format ASS (`{ } \`) sont retirés du texte avant incrustation.

## Si une clé a fuité

1. Révoque-la immédiatement depuis la console du fournisseur (Anthropic, ElevenLabs, fal.ai).
2. Crée une nouvelle clé et mets-la dans `.env`.
3. Supprimer le commit ne suffit pas : l'historique Git garde la clé. La révocation est la seule vraie protection.
