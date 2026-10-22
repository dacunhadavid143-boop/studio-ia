"""Petits utilitaires : téléchargement sécurisé, ffmpeg, noms de fichiers."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests

from .config import StudioError, masquer

TAILLE_MAX_TELECHARGEMENT = 500 * 1024 * 1024  # 500 Mo : un clip de quelques secondes n'en pèse que ~10


def telecharger(url: str, sortie: Path) -> Path:
    """Télécharge un fichier généré par une API.

    Sécurité : HTTPS obligatoire, taille plafonnée, écriture atomique
    (fichier .part renommé à la fin, donc jamais de fichier à moitié écrit).
    """
    if urlparse(url).scheme != "https":
        raise StudioError(f"URL refusée (HTTPS obligatoire) : {url[:80]}")
    tmp = sortie.with_suffix(".part")
    recu = 0
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for bloc in r.iter_content(1 << 20):
                recu += len(bloc)
                if recu > TAILLE_MAX_TELECHARGEMENT:
                    fh.close()
                    tmp.unlink(missing_ok=True)
                    raise StudioError("Fichier téléchargé anormalement gros, abandon.")
                fh.write(bloc)
    tmp.replace(sortie)
    return sortie


def ffmpeg(cmd: list[str], cwd: Path | None = None) -> None:
    """Lance ffmpeg/ffprobe SANS shell (liste d'arguments) : aucune injection de commande possible."""
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise StudioError(f"ffmpeg a échoué :\n{masquer(p.stderr[-1500:])}")


def duree(chemin: Path | str) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(chemin)],
        capture_output=True, text=True,
    )
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


def slug(texte: str) -> str:
    """'Personne ne viendra !' -> 'personne_ne_viendra' (nom de fichier sûr)."""
    texte = re.sub(r"[^\w\s-]", "", texte.lower(), flags=re.UNICODE)
    return re.sub(r"[\s_-]+", "_", texte).strip("_")[:50] or "video"


def verifier_outils() -> None:
    for outil in ("ffmpeg", "ffprobe"):
        if not shutil.which(outil):
            raise StudioError(f"{outil} introuvable. Installe ffmpeg (voir README).")
