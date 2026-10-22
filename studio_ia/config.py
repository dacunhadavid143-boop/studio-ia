"""Configuration, secrets et constantes partagées.

Règle de sécurité : aucune clé API n'est jamais écrite dans le code.
Les clés sont lues uniquement depuis les variables d'environnement
(ou un fichier .env local, ignoré par Git).
"""
from __future__ import annotations

import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# Format de sortie : vertical TikTok / Reels / Shorts
W, H, FPS = 1080, 1920, 30

# Modèles vidéo disponibles via fal.ai (durées acceptées par chaque modèle, en secondes)
VIDEO_MODELS = {
    "kling": {"id": "fal-ai/kling-video/v3/pro/text-to-video", "durees": list(range(3, 16))},
    "veo": {"id": "fal-ai/veo3.1", "durees": [4, 6, 8]},
    "veo-fast": {"id": "fal-ai/veo3.1/fast", "durees": [4, 6, 8]},
}

# Prix indicatifs en $ par seconde de vidéo générée (sans audio natif).
# Sert uniquement à afficher une estimation avant de dépenser : à mettre à jour si les tarifs changent.
PRIX_PAR_SECONDE = {"kling": 0.112, "veo": 0.40, "veo-fast": 0.15}

CLES_REQUISES = {
    "ANTHROPIC_API_KEY": "Claude (écriture du script)",
    "ELEVENLABS_API_KEY": "ElevenLabs (voix off + musique)",
    "FAL_KEY": "fal.ai (génération des plans vidéo)",
}


class StudioError(RuntimeError):
    """Erreur « propre » affichée à l'utilisateur sans trace technique."""


def charger_env(fichier: Path | None = None) -> None:
    """Charge un fichier .env (clé=valeur) sans écraser les variables déjà définies."""
    fichier = fichier or RACINE / ".env"
    if not fichier.exists():
        return
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, val = ligne.split("=", 1)
        os.environ.setdefault(cle.strip(), val.strip().strip('"').strip("'"))


def cle(nom: str) -> str:
    """Retourne une clé API ou lève une erreur claire si elle manque."""
    valeur = os.environ.get(nom, "").strip()
    if not valeur:
        usage = CLES_REQUISES.get(nom, "")
        raise StudioError(f"Clé manquante : {nom} {f'({usage})' if usage else ''}. "
                          "Ajoute-la dans le fichier .env (voir .env.example).")
    return valeur


def masquer(texte: str) -> str:
    """Retire toute clé API connue d'un texte avant de l'afficher (messages d'erreur, logs)."""
    for nom in CLES_REQUISES:
        v = os.environ.get(nom)
        if v and len(v) > 6:
            texte = texte.replace(v, f"<{nom} masquée>")
    return texte


def modele_claude() -> str:
    return os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")


def modele_voix() -> str:
    return os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")


def modele_musique() -> str:
    return os.environ.get("ELEVENLABS_MUSIC_MODEL", "music_v2_5")


def log(etape: str, msg: str) -> None:
    print(f"[{etape}] {masquer(msg)}", flush=True)
