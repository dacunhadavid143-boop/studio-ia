"""Étape 3 — Génération des plans vidéo (Kling 3.0 / Veo 3.1 via fal.ai).

Points clés :
- les durées des plans sont recalculées pour couvrir exactement la durée de la voix ;
- chaque prompt est enrichi automatiquement avec la description du personnage et le style,
  pour garder une cohérence visuelle d'un plan à l'autre ;
- les plans sont générés en parallèle, avec 3 tentatives chacun ;
- un plan déjà téléchargé n'est jamais régénéré (pas de double facturation).
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import time
from pathlib import Path

from .config import PRIX_PAR_SECONDE, VIDEO_MODELS, StudioError, cle, log
from .outils import telecharger

NEGATIF = "blur, distortion, low quality, extra limbs, deformed hands, text, watermark"


def ajuster_plans(plan: dict, total: float, modele: str) -> list[dict]:
    """Met à l'échelle les durées proposées par Claude pour couvrir `total` secondes.

    duree_cible = durée réellement utilisée au montage
    duree_gen   = durée facturée (arrondie à une durée acceptée par le modèle)
    """
    autorisees = VIDEO_MODELS[modele]["durees"]
    plans = [dict(p) for p in plan["plans"]] or [{"prompt": "slow cinematic shot", "duree": 5}]
    echelle = total / (sum(p["duree"] for p in plans) or 1)
    for p in plans:
        cible = p["duree"] * echelle
        p["duree_gen"] = next((d for d in autorisees if d >= cible), autorisees[-1])
        p["duree_cible"] = min(cible, p["duree_gen"])
    # si un plan est plus long que le maximum du modèle, on complète avec des plans supplémentaires
    while sum(p["duree_cible"] for p in plans) < total - 0.05:
        manque = total - sum(p["duree_cible"] for p in plans)
        source = plans[len(plans) % len(plan["plans"] or plans)]
        d = next((x for x in autorisees if x >= manque), autorisees[-1])
        plans.append({**source, "duree_gen": d, "duree_cible": min(manque, d)})
    return plans


def estimer_cout(plans: list[dict], modele: str) -> float:
    return sum(p["duree_gen"] for p in plans) * PRIX_PAR_SECONDE.get(modele, 0)


def construire_prompt(plan: dict, plan_video: dict) -> str:
    morceaux = [plan_video["prompt"]]
    if plan.get("personnage"):
        morceaux.append(f"Main character: {plan['personnage']}.")
    morceaux.append(f"Style: {plan['style_visuel']}. Vertical 9:16 framing, photorealistic, "
                    "no text, no subtitles, no logos.")
    return " ".join(morceaux)


def _parametres(modele: str, prompt: str, duree: int) -> dict:
    if modele == "kling":
        return {"prompt": prompt, "duration": str(duree), "aspect_ratio": "9:16",
                "generate_audio": False, "negative_prompt": NEGATIF}
    return {"prompt": prompt, "duration": f"{duree}s", "aspect_ratio": "9:16", "resolution": "1080p",
            "generate_audio": False, "negative_prompt": NEGATIF}


def generer_clip(modele: str, prompt: str, duree: int, sortie: Path) -> Path:
    import fal_client  # importé ici pour que les tests tournent sans la dépendance

    derniere_erreur = None
    for tentative in range(3):
        try:
            res = fal_client.subscribe(VIDEO_MODELS[modele]["id"], arguments=_parametres(modele, prompt, duree))
            return telecharger(res["video"]["url"], sortie)
        except Exception as e:  # noqa: BLE001 - on retente quelle que soit l'erreur réseau/API
            derniere_erreur = e
            time.sleep(5 * (tentative + 1))
    raise StudioError(f"échec génération {sortie.name} : {derniere_erreur}")


def preparer_plans(projet: Path, plan: dict, total: float, modele: str) -> list[dict]:
    fichier = projet / "plans.json"
    if fichier.exists():
        plans = json.loads(fichier.read_text(encoding="utf-8"))
    else:
        plans = ajuster_plans(plan, total, modele)
        fichier.write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")
    dossier = projet / "plans"
    dossier.mkdir(exist_ok=True)
    for i, p in enumerate(plans, 1):
        p["fichier"] = str(dossier / f"plan_{i:02d}.mp4")
    return plans


def generer_plans(projet: Path, plan: dict, plans: list[dict], modele: str, paralleles: int = 4) -> list[dict]:
    cle("FAL_KEY")  # vérifie la présence de la clé (fal_client la lit lui-même dans l'environnement)
    a_faire = [(i, p) for i, p in enumerate(plans, 1) if not Path(p["fichier"]).exists()]
    log("3/5 Vidéo", f"{len(plans)} plans, {len(a_faire)} à générer avec {modele}…")
    with cf.ThreadPoolExecutor(max_workers=paralleles) as ex:
        futurs = {ex.submit(generer_clip, modele, construire_prompt(plan, p), p["duree_gen"],
                            Path(p["fichier"])): i for i, p in a_faire}
        for f in cf.as_completed(futurs):
            try:
                f.result()
                log("3/5 Vidéo", f"plan {futurs[f]} ✓")
            except Exception as e:  # noqa: BLE001
                log("3/5 Vidéo", f"plan {futurs[f]} ✗ {e}")
    manquants = [p for p in plans if not Path(p["fichier"]).exists()]
    if manquants:
        raise StudioError(f"{len(manquants)} plan(s) non générés. Relance avec --projet {projet} "
                          "pour réessayer uniquement ceux-là.")
    return plans
