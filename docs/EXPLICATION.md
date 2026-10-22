# studio-ia, expliqué simplement

*Ce document sert à comprendre et à présenter le projet, par exemple à un employeur, sans lire de code.*

---

## Le pitch en 30 secondes

> « Je publie deux vidéos par jour sur TikTok. Le montage me prenait des heures et j'utilisais des images dont je n'avais pas les droits.
> J'ai donc conçu un outil qui fait travailler plusieurs intelligences artificielles à la chaîne, comme une petite équipe de production :
> un **scénariste** (Claude), un **comédien voix off** (ElevenLabs), un **cadreur** (Kling ou Veo), un **compositeur** et un **monteur** (ffmpeg).
> Je donne une idée ou mes propres images, et je récupère une vidéo prête à publier, avec mon identité visuelle.
> J'ai aussi travaillé sur les **coûts** (de ~225 € à ~40 € par mois pour mon rythme, voire 0 € de génération avec mes propres images) et sur la **sécurité** des clés d'accès. »

---

## 1. Le problème de départ

- **Temps** : une vidéo de 20 secondes, c'est écrire un texte, enregistrer une voix, trouver des plans, couper, synchroniser le texte, mixer. Ça représente plusieurs heures.
- **Droits d'image** : utiliser des vidéos trouvées en ligne expose à des retraits et bloque toute monétisation.
- **Identité** : chaque vidéo doit garder le même style (noir et blanc VHS, police Oswald, texte mot par mot, voix grave).

## 2. La solution : une chaîne de production automatisée

L'outil enchaîne **5 étapes**. Chacune est confiée à l'outil le plus adapté :

| # | Rôle « humain » | Outil | Ce qu'il fait concrètement |
|---|---|---|---|
| 1 | Scénariste / réalisateur | **Claude** (Anthropic) | Écrit le texte de la voix off, découpe la vidéo en plans et rédige les consignes pour les autres IA. |
| 2 | Comédien voix off | **ElevenLabs** | Lit le texte avec une voix réaliste et indique **à quel moment exact chaque mot est prononcé**. |
| 3 | Cadreur | **Kling 3.0 / Veo 3.1** | Génère les plans vidéo à partir des consignes, au format vertical. |
| 4 | Compositeur | **Eleven Music** ou **moteur maison** | Crée une musique d'ambiance. Le moteur maison place un « boum » au début de chaque phrase. |
| 5 | Monteur / étalonneur | **ffmpeg** | Assemble, coupe, applique le style, affiche le texte mot par mot et mixe le son. |

Il existe aussi un **mode « rushes »** : à la place de l'étape 3, l'outil monte **mes propres vidéos**. C'est gratuit et sans aucun problème de droits.

---

## 3. Chaque brique, une par une

### 🧠 Étape 1 : la direction artistique (`direction.py`)
- **Entrée** : une idée (« un boxeur seul à l'aube, ton stoïque »), une durée, un type de voix.
- **Sortie** : un *plan de tournage* structuré, avec le texte, la liste des plans, la description du personnage, le style visuel et le prompt de musique.
- **Pourquoi c'est malin** : on oblige Claude à répondre dans un **format strict (schéma JSON)**. Le reste du programme peut donc le lire sans erreur. C'est la différence entre « discuter avec une IA » et « intégrer une IA dans un logiciel ».
- **Cohérence visuelle** : la même description du personnage est ajoutée automatiquement à chaque plan, pour que ce soit le même gars d'un plan à l'autre.

### 🎙️ Étape 2 : la voix off (`voix.py`)
- ElevenLabs renvoie l'audio **et l'horodatage de chaque lettre**. L'outil le regroupe en mots : « silence » commence à 0,72 s et finit à 1,30 s.
- **Pourquoi c'est important** : c'est ce qui permet d'afficher le texte **parfaitement synchronisé**, sans aucun calage à la main.
- Claude peut aussi **choisir lui-même la voix** la plus adaptée dans le catalogue du compte.

### 🎥 Étape 3 : les plans vidéo (`video.py`)
- Les durées des plans sont **recalculées** pour couvrir exactement la durée de la voix.
- Tous les plans sont générés **en même temps** (en parallèle), ce qui fait gagner plusieurs minutes.
- En cas d'échec réseau, l'outil **réessaie 3 fois**.
- **Avant de dépenser**, il **estime le coût** et refuse de dépasser un plafond fixé.

### 🎞️ Mode rushes : monter ses propres images (`rushes.py`)
1. **Alignement** : retrouver à quel moment chaque mot est dit dans un fichier audio existant (via l'API d'ElevenLabs, ou une estimation locale qui repère les silences).
2. **Détection de scènes** : l'outil repère les changements de plan dans la vidéo brute et ignore les passages noirs, comme l'écran de fin d'un export CapCut.
3. **Plan de coupe** : un cut au début de chaque phrase, puis environ toutes les 0,6 s, toujours sur un début de mot. C'est ce qui donne le rythme nerveux typique de TikTok.
4. **Variété** : chaque cut pioche un moment différent de la vidéo, avec des recadrages et zooms variés, et des **ralentis fluides** (l'outil invente les images intermédiaires).

### 🎵 Étape 4 : la musique (`musique.py`)
- **Option payante** : Eleven Music compose un morceau à partir d'une description.
- **Option gratuite** : un **synthétiseur écrit en Python**. Il calcule une basse, des impacts, une nappe sombre et des notes de piano, et **place un impact pile au début de chaque phrase de la voix**. C'est libre de droits, puisque la musique est générée par le programme.

### ✂️ Étape 5 : le montage (`montage.py`)
- **Recadrage** automatique au format vertical 1080×1920.
- **Étalonnage** : le « look » de la chaîne (noir et blanc, effet VHS avec franges rouge/bleu, grain, vignette).
- **Effet impact** : à chaque cut, un léger zoom qui se relâche et un flash très court donnent la sensation que l'image « tape ».
- **Texte** : un mot à la fois au centre, en police Oswald avec contour noir, et une courte apparition en fondu.
- **Mixage** :
  - la musique **baisse automatiquement quand la voix parle** et remonte dans les silences (technique de radio appelée *ducking*) ;
  - le volume final est calé à **-14 LUFS**, le niveau attendu par les plateformes, ce qui évite que la vidéo soit trop faible ou trop forte.

---

## 4. Les choix techniques, et pourquoi

| Choix | Raison |
|---|---|
| **Une chaîne d'étapes fixe** plutôt que des « agents autonomes » | Prévisible, économique, facile à déboguer. Les agents seraient utiles pour la qualité (critique du texte, contrôle du rendu), pas pour le cœur du pipeline. |
| **Cache par étape** | Si l'étape 4 plante, on ne repaie pas les étapes 1 à 3. Économie directe d'argent. |
| **Validation humaine avant dépense** | L'utilisateur voit le texte, les plans et le coût estimé avant de payer quoi que ce soit. |
| **ffmpeg** pour le montage | Outil standard de l'industrie, gratuit et scriptable. Aucun logiciel de montage payant n'est nécessaire. |
| **Plusieurs fournisseurs interchangeables** | Kling ou Veo, Eleven Music ou synthèse : on change d'outil avec une option, sans réécrire le code. On n'est jamais bloqué par un seul fournisseur. |

## 5. La sécurité

- **Les clés d'accès aux IA** (l'équivalent de mots de passe payants) ne sont **jamais dans le code**. Elles sont dans un fichier local `.env` que Git refuse de publier.
- Si une erreur s'affiche, les clés sont **automatiquement masquées**.
- **gitleaks** vérifie à chaque envoi sur GitHub qu'aucun secret n'a fuité.
- Les **tests automatiques** tournent sans aucune clé.
- Le programme ne passe jamais par un « shell » pour lancer ffmpeg, ce qui ferme une faille classique (l'injection de commandes).

## 6. Les résultats chiffrés

| | Avant | Avec studio-ia |
|---|---|---|
| Temps de montage d'une vidéo | plusieurs heures | quelques minutes (validation comprise) |
| Coût mensuel (2 vidéos/jour, 100 % IA) | ~225 € en génération à la seconde | ~40 € avec l'abonnement et une bibliothèque de clips |
| Coût mensuel (mode rushes) | n/a | **0 € de génération** (seulement la voix, dès 6 $/mois) |
| Droits d'image | images de tiers | images générées ou tournées soi-même |

## 7. Les limites, en toute honnêteté

- Les IA vidéo peuvent produire des plans ratés (mains déformées, visage qui change). D'où la validation humaine, et la piste du contrôle qualité automatique.
- En mode rushes, le recadrage est centré : il ne suit pas encore le sujet.
- Les tarifs des IA changent souvent. Ils sont centralisés dans un seul fichier pour être faciles à mettre à jour.

## 8. Questions qu'on peut te poser, et quoi répondre

**« Qu'est-ce que tu as fait toi, concrètement ? »**
J'ai défini le besoin et le style, choisi et comparé les outils (qualité et prix), validé chaque étape sur de vraies vidéos, et piloté l'optimisation des coûts. Le code a été écrit avec l'assistance de Claude. Je sais expliquer et modifier chaque brique.

**« Pourquoi plusieurs IA plutôt qu'une seule ? »**
Aucune IA n'est la meilleure partout. Chacune est spécialisée, et l'intérêt du projet est de les **faire collaborer** avec des données précises : l'horodatage de la voix pilote à la fois le texte, les cuts et la musique.

**« Comment tu maîtrises les coûts ? »**
J'estime avant de dépenser, avec un plafond. Un cache évite de repayer une étape. Il existe un mode gratuit avec mes propres images, et une musique synthétisée sans licence.

**« Et si une clé API fuit ? »**
Elle n'est jamais dans le code, elle est masquée dans les logs, et un scan automatique bloque les fuites. En cas de doute, on la révoque chez le fournisseur et on en crée une nouvelle.
