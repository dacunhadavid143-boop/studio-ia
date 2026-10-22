"""Étape 2 — Voix off avec ElevenLabs.

On utilise l'endpoint « with-timestamps » : en plus de l'audio, ElevenLabs renvoie
l'instant exact où chaque caractère est prononcé. C'est ce qui permet d'afficher
le texte mot par mot parfaitement synchronisé, sans retouche manuelle.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests

from .config import StudioError, cle, log, masquer, modele_voix
from .direction import choisir_voix
from .outils import duree

API_EL = "https://api.elevenlabs.io"


def _entetes() -> dict:
    return {"xi-api-key": cle("ELEVENLABS_API_KEY")}


def caracteres_vers_mots(alignement: dict | None) -> list[dict]:
    """Transforme l'alignement caractère par caractère en liste de mots {mot, debut, fin}."""
    if not alignement:
        return []
    mots, courant, debut, fin = [], "", None, None
    for c, s, e in zip(alignement["characters"], alignement["character_start_times_seconds"],
                       alignement["character_end_times_seconds"]):
        if c.isspace():
            if courant:
                mots.append({"mot": courant, "debut": debut, "fin": fin})
            courant, debut = "", None
            continue
        if debut is None:
            debut = s
        courant += c
        fin = e
    if courant:
        mots.append({"mot": courant, "debut": debut, "fin": fin})
    return mots


def selection_voix(plan: dict, reglages: dict) -> str:
    if reglages.get("voice_id"):
        return reglages["voice_id"]
    if os.environ.get("ELEVENLABS_VOICE_ID"):
        return os.environ["ELEVENLABS_VOICE_ID"]
    r = requests.get(f"{API_EL}/v1/voices", headers=_entetes(), timeout=60)
    r.raise_for_status()
    voix = r.json().get("voices", [])
    if not voix:
        raise StudioError("Aucune voix disponible sur le compte ElevenLabs.")
    catalogue = [{"voice_id": v["voice_id"], "name": v.get("name"), "labels": v.get("labels"),
                  "description": (v.get("description") or "")[:200]} for v in voix]
    choisie = choisir_voix(catalogue, reglages.get("voix") or plan["voix_recherchee"], reglages["langue"])
    choisie = choisie or voix[0]["voice_id"]
    nom = next((v["name"] for v in catalogue if v["voice_id"] == choisie), "?")
    log("2/5 Voix", f"voix choisie : {nom} ({choisie})")
    return choisie


def generer_voix(projet: Path, plan: dict, reglages: dict) -> dict:
    audio, timing = projet / "voix.mp3", projet / "voix_timing.json"
    if audio.exists() and timing.exists():
        log("2/5 Voix", "déjà fait (voix.mp3)")
        return json.loads(timing.read_text(encoding="utf-8"))

    voice_id = selection_voix(plan, reglages)
    log("2/5 Voix", f"ElevenLabs génère la voix off ({modele_voix()})…")
    corps = {
        "text": plan["script_voix_off"],
        "model_id": modele_voix(),
        "voice_settings": {"stability": reglages["stabilite"], "similarity_boost": 0.8, "style": 0.35,
                           "use_speaker_boost": True, "speed": reglages["vitesse"]},
    }
    if modele_voix() != "eleven_multilingual_v2":
        corps["language_code"] = reglages["langue"][:2]
    r = requests.post(f"{API_EL}/v1/text-to-speech/{voice_id}/with-timestamps",
                      headers={**_entetes(), "content-type": "application/json"},
                      params={"output_format": "mp3_44100_128"}, json=corps, timeout=300)
    if r.status_code != 200:
        raise StudioError(f"ElevenLabs voix {r.status_code} : {masquer(r.text[:400])}")
    data = r.json()
    audio.write_bytes(base64.b64decode(data["audio_base64"]))
    infos = {"voice_id": voice_id, "duree": duree(audio),
             "mots": caracteres_vers_mots(data.get("alignment") or data.get("normalized_alignment"))}
    timing.write_text(json.dumps(infos, ensure_ascii=False, indent=2), encoding="utf-8")
    log("2/5 Voix", f"OK — {infos['duree']:.1f} s")
    return infos
