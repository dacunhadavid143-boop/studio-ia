"""Étape 1 — Direction artistique avec Claude.

Claude reçoit l'idée brute et renvoie un plan structuré (JSON validé par schéma) :
texte de la voix off, découpage en plans, prompts vidéo, prompt musique, voix idéale.
L'usage d'un « outil » (tool use) force une sortie JSON exploitable par le reste du pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

from .config import StudioError, cle, log, masquer, modele_claude

API_CLAUDE = "https://api.anthropic.com/v1/messages"

SCHEMA_PLAN = {
    "name": "plan_video",
    "description": "Plan complet d'une vidéo courte verticale.",
    "input_schema": {
        "type": "object",
        "properties": {
            "titre": {"type": "string", "description": "Titre court du projet"},
            "script_voix_off": {
                "type": "string",
                "description": "Texte exact lu par la voix off. Phrases courtes, hook fort dans les 2 premières "
                               "secondes, ponctuation travaillée pour les pauses.",
            },
            "personnage": {
                "type": "string",
                "description": "EN ANGLAIS : description visuelle précise et identique pour tous les plans "
                               "(garantit la cohérence du personnage). Vide si aucun personnage.",
            },
            "style_visuel": {"type": "string", "description": "EN ANGLAIS : lumière, étalonnage, objectif, ambiance."},
            "plans": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "EN ANGLAIS : action + cadrage + mouvement caméra."},
                        "duree": {"type": "number", "description": "Durée à l'écran en secondes (1.2 à 8)."},
                    },
                    "required": ["prompt", "duree"],
                },
            },
            "prompt_musique": {"type": "string", "description": "EN ANGLAIS : musique instrumentale, sans nom d'artiste."},
            "voix_recherchee": {"type": "string", "description": "Voix idéale (genre, timbre, énergie)."},
        },
        "required": ["titre", "script_voix_off", "personnage", "style_visuel", "plans",
                     "prompt_musique", "voix_recherchee"],
    },
}

CONSIGNE_SYSTEME = (
    "Tu es réalisateur et copywriter de vidéos courtes virales (TikTok, Reels, Shorts). "
    "Tu écris des voix off percutantes et des découpages de plans faciles à générer par une IA vidéo : "
    "un seul sujet clair par plan, actions physiques lisibles, mouvement caméra précis, "
    "pas de texte à l'écran, pas de foule. Format vertical 9:16."
)


def appeler_claude(messages, systeme, outils=None, choix_outil=None, max_tokens=4000) -> dict:
    corps = {"model": modele_claude(), "max_tokens": max_tokens, "system": systeme, "messages": messages}
    if outils:
        corps["tools"] = outils
    if choix_outil:
        corps["tool_choice"] = choix_outil
    r = requests.post(
        API_CLAUDE,
        headers={"x-api-key": cle("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json=corps, timeout=300,
    )
    if r.status_code != 200:
        raise StudioError(f"Claude API {r.status_code} : {masquer(r.text[:400])}")
    return r.json()


def ecrire_plan(projet: Path, brief: dict) -> dict:
    """Produit (ou relit depuis le cache) le plan de la vidéo."""
    fichier = projet / "plan.json"
    if fichier.exists():
        log("1/5 Script", "déjà fait (plan.json)")
        return json.loads(fichier.read_text(encoding="utf-8"))

    log("1/5 Script", f"Claude écrit le script et le découpage ({modele_claude()})…")
    mots_par_s = 2.4 if brief["langue"].startswith("fr") else 2.6
    demande = (
        f"Idée : {brief['idee']}\n"
        f"Durée cible : {brief['duree']} s (≈ {int(brief['duree'] * mots_par_s)} mots de voix off maximum)\n"
        f"Langue : {brief['langue']}\n"
        f"Voix souhaitée : {brief.get('voix') or 'à toi de choisir'}\n"
        f"Ton : {brief.get('ton') or 'à toi de choisir'}\n"
        + (f"Texte imposé (à utiliser tel quel) : {brief['texte']}\n" if brief.get("texte") else "")
        + (f"Musique souhaitée : {brief['musique']}\n" if brief.get("musique") else "")
        + "Varie les plans (gros plans, larges, ralentis, détails) et fais monter l'intensité vers la fin."
    )
    rep = appeler_claude([{"role": "user", "content": demande}], CONSIGNE_SYSTEME,
                         outils=[SCHEMA_PLAN], choix_outil={"type": "tool", "name": "plan_video"})
    plan = next(b["input"] for b in rep["content"] if b["type"] == "tool_use")
    if brief.get("texte"):
        plan["script_voix_off"] = brief["texte"]
    fichier.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def afficher_plan(plan: dict) -> None:
    print("\n" + "=" * 60 + f"\n🎬  {plan['titre']}\n" + "=" * 60)
    print(f"\n🎙️  VOIX OFF ({plan['voix_recherchee']}) :\n{plan['script_voix_off']}\n")
    print(f"👤  Personnage : {plan['personnage'] or '—'}\n🎨  Style : {plan['style_visuel']}\n")
    for i, p in enumerate(plan["plans"], 1):
        print(f"  Plan {i} ({p['duree']}s) : {p['prompt']}")
    print(f"\n🎵  Musique : {plan['prompt_musique']}\n" + "=" * 60 + "\n")


def choisir_voix(catalogue: list[dict], description: str, langue: str) -> str | None:
    """Demande à Claude la voix la plus adaptée dans le catalogue ElevenLabs du compte."""
    rep = appeler_claude(
        [{"role": "user", "content": f"Voix recherchée : {description}\nLangue : {langue}\nCatalogue :\n"
                                     + json.dumps(catalogue, ensure_ascii=False)
                                     + "\nRéponds UNIQUEMENT avec le voice_id le plus adapté."}],
        "Tu choisis la meilleure voix dans un catalogue. Réponse = un voice_id, rien d'autre.",
        max_tokens=60,
    )
    texte = "".join(b.get("text", "") for b in rep["content"])
    return next((v["voice_id"] for v in catalogue if v["voice_id"] in texte), None)
