"""Interface en ligne de commande.

Deux modes :
  IA      : python -m studio_ia "idée de vidéo" --voix "..." --duree 20
  RUSHES  : python -m studio_ia --rushes brut.mov --voix-fichier voix.mp3 --texte "..."
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import direction, montage, musique, rushes, video, voix
from .config import RACINE, VIDEO_MODELS, StudioError, charger_env, masquer
from .outils import duree, slug, verifier_outils


def _arguments() -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="studio_ia", description="Une idée (ou des rushes) -> une vidéo verticale finie.")
    ap.add_argument("idee", nargs="?", help="Idée de la vidéo (mode IA)")
    g = ap.add_argument_group("contenu")
    g.add_argument("--voix", help="Voix souhaitée : 'homme grave calme'…")
    g.add_argument("--ton", help="Ton du texte : 'stoïcien', 'dur et direct'…")
    g.add_argument("--texte", help="Texte de voix off imposé (obligatoire en mode rushes)")
    g.add_argument("--musique", help="Envie musicale (pour Eleven Music)")
    g.add_argument("--duree", type=int, default=20, help="Durée cible en secondes (mode IA)")
    g.add_argument("--langue", default="fr")
    g = ap.add_argument_group("sources")
    g.add_argument("--modele", choices=list(VIDEO_MODELS), default=os.environ.get("VIDEO_MODEL", "kling"))
    g.add_argument("--rushes", nargs="+", type=Path, help="Tes propres vidéos (mode rushes)")
    g.add_argument("--voix-fichier", type=Path, help="Voix off déjà enregistrée (mp3/wav)")
    g.add_argument("--voice-id", help="Voix ElevenLabs précise")
    g.add_argument("--vitesse", type=float, default=1.0)
    g.add_argument("--stabilite", type=float, default=0.4)
    g.add_argument("--moteur-musique", choices=["synthese", "eleven", "aucune"], default="synthese",
                   help="synthese = locale et gratuite (défaut), eleven = Eleven Music, aucune")
    g.add_argument("--style-musique", choices=["lourd", "atmo"], default="lourd")
    g = ap.add_argument_group("montage")
    g.add_argument("--look", choices=list(montage.LOOKS), default="vhs")
    g.add_argument("--exposition", type=float, default=1.0)
    g.add_argument("--impact", type=float, default=1.0)
    g.add_argument("--rythme", type=float, default=0.6, help="Durée visée d'un plan en mode rushes (s)")
    g.add_argument("--police", default=os.environ.get("SUB_FONT", "Oswald"))
    g.add_argument("--mode-texte", choices=["mot", "groupe"], default="mot")
    g.add_argument("--position", choices=["centre", "bas"], default="centre")
    g.add_argument("--casse", choices=["min", "maj"], default="min")
    g.add_argument("--taille-texte", type=int)
    g.add_argument("--volume-musique", type=float, default=0.30)
    g.add_argument("--sans-sous-titres", action="store_true")
    g = ap.add_argument_group("exécution")
    g.add_argument("--projet", type=Path, help="Reprendre un projet existant (seules les étapes manquantes sont refaites)")
    g.add_argument("--budget-max", type=float, default=float(os.environ.get("BUDGET_MAX_USD", 10)),
                   help="Refuse de lancer la génération vidéo si l'estimation dépasse ce montant ($)")
    g.add_argument("--oui", action="store_true", help="Ne pas demander de confirmation")
    g.add_argument("--plan-seulement", action="store_true", help="Écrire le script sans rien générer (gratuit)")
    g.add_argument("--paralleles", type=int, default=4)
    return ap.parse_args()


def _style(a) -> montage.StyleMontage:
    return montage.StyleMontage(look=a.look, exposition=a.exposition, impact=a.impact, police=a.police,
                                mode_texte=a.mode_texte, position=a.position, taille=a.taille_texte,
                                casse=a.casse, sous_titres=not a.sans_sous_titres, volume_musique=a.volume_musique)


def _dossier_projet(a, nom: str) -> Path:
    if a.projet:
        p = a.projet.resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    p = RACINE / "projets" / f"{time.strftime('%Y%m%d_%H%M%S')}_{slug(nom)[:30]}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def mode_rushes(a) -> Path:
    if not (a.voix_fichier and a.texte):
        raise StudioError("Le mode rushes demande --voix-fichier et --texte.")
    projet = _dossier_projet(a, a.texte)
    voix_mp3 = projet / "voix.mp3"
    if not voix_mp3.exists():
        from .outils import ffmpeg
        ffmpeg(["ffmpeg", "-y", "-i", str(a.voix_fichier), "-b:a", "192k", str(voix_mp3)])
    timing_f = projet / "voix_timing.json"
    if timing_f.exists():
        timing = json.loads(timing_f.read_text(encoding="utf-8"))
    else:
        mots = rushes.aligner(voix_mp3, a.texte, os.environ.get("ELEVENLABS_API_KEY"))
        timing = {"duree": duree(voix_mp3), "mots": mots}
        timing_f.write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
    st = _style(a)
    total = timing["duree"] + st.marge_fin
    plans = rushes.decouper(projet, a.rushes, timing["mots"], total, a.rythme)
    mus = musique.generer_musique(projet, {"prompt_musique": a.musique or ""}, timing, total,
                                  a.moteur_musique, a.musique, a.style_musique)
    return montage.monter(projet, plans, timing, mus, st, f"{slug(a.texte)}.mp4")


def mode_ia(a) -> Path | None:
    if not a.idee and not a.projet:
        a.idee = input("💡 Idée de la vidéo : ").strip()
    projet = _dossier_projet(a, a.idee or "projet")
    brief_f = projet / "brief.json"
    if brief_f.exists():
        brief = json.loads(brief_f.read_text(encoding="utf-8"))
    else:
        brief = {k: getattr(a, k) for k in ("idee", "voix", "ton", "texte", "musique", "duree", "langue")}
        brief_f.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📁 Projet : {projet}")

    plan = direction.ecrire_plan(projet, brief)
    direction.afficher_plan(plan)
    if a.plan_seulement:
        print(f"Script prêt (gratuit). Pour générer : python -m studio_ia --projet \"{projet}\"")
        return None

    # Garde-fou budget : on estime avant de dépenser quoi que ce soit en vidéo
    total_estime = brief["duree"] + 1.0
    estimation = video.estimer_cout(video.ajuster_plans(plan, total_estime, a.modele), a.modele)
    print(f"💰 Estimation vidéo : ~{estimation:.2f} $ ({a.modele}) — plafond : {a.budget_max:.2f} $")
    if estimation > a.budget_max:
        raise StudioError("Estimation au-dessus du plafond. Augmente --budget-max ou réduis la durée.")
    if not a.oui and not (projet / "voix.mp3").exists():
        if input("Lancer la génération ? (o/n) : ").strip().lower() not in ("o", "oui", "y", ""):
            print(f"OK. Modifie {projet / 'plan.json'} puis relance avec --projet.")
            return None

    reglages = {"voix": brief.get("voix"), "langue": brief["langue"], "voice_id": a.voice_id,
                "vitesse": a.vitesse, "stabilite": a.stabilite}
    timing = voix.generer_voix(projet, plan, reglages)
    st = _style(a)
    total = timing["duree"] + st.marge_fin
    plans = video.preparer_plans(projet, plan, total, a.modele)
    plans = video.generer_plans(projet, plan, plans, a.modele, a.paralleles)
    mus = musique.generer_musique(projet, plan, timing, total, a.moteur_musique, brief.get("musique"),
                                  a.style_musique)
    return montage.monter(projet, plans, timing, mus, st, f"{slug(plan['titre'])}.mp4")


def main() -> None:
    charger_env()
    a = _arguments()
    try:
        verifier_outils()
        final = mode_rushes(a) if a.rushes else mode_ia(a)
        if final:
            print(f"\n✅ Vidéo prête : {final}\n")
    except StudioError as e:
        print(f"❌ {masquer(str(e))}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrompu. Relance avec --projet pour reprendre là où tu en étais.")
        sys.exit(130)
