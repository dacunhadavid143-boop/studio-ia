"""Mode « rushes » — monter ses propres images, sans IA vidéo (coût de génération : 0 €).

Entrées : une ou plusieurs vidéos brutes + un fichier de voix off + son texte.
1. Alignement : on retrouve l'instant de chaque mot dans la voix
   (API Forced Alignment d'ElevenLabs si une clé est disponible, sinon estimation locale
   par détection des silences).
2. Découpage des rushes en scènes (détection de changement de plan), en ignorant les passages noirs
   (ex. écran de fin d'un export CapCut).
3. Plan de coupe : un cut au début de chaque phrase, puis environ toutes les 0,6 s sur un début de mot,
   pour un rythme nerveux toujours calé sur la voix.
4. Chaque coupe pioche un moment différent dans les scènes, avec recadrage 9:16, zooms variés
   et ralenti fluide (interpolation de mouvement) sur les plans longs.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import requests

from .config import FPS, H, W, StudioError, log, masquer
from .outils import duree, ffmpeg

API_ALIGN = "https://api.elevenlabs.io/v1/forced-alignment"


# ------------------------------------------------------------------ 1. alignement voix / texte

def aligner(voix: Path, texte: str, cle_api: str | None) -> list[dict]:
    if cle_api:
        log("Alignement", "ElevenLabs Forced Alignment…")
        with open(voix, "rb") as fh:
            r = requests.post(API_ALIGN, headers={"xi-api-key": cle_api},
                              files={"file": (voix.name, fh, "audio/mpeg")}, data={"text": texte}, timeout=300)
        if r.status_code != 200:
            raise StudioError(f"Forced Alignment {r.status_code} : {masquer(r.text[:300])}")
        mots = [{"mot": w["text"].strip(), "debut": w["start"], "fin": w["end"]}
                for w in r.json().get("words", []) if w["text"].strip()]
        if mots:
            return mots
    log("Alignement", "estimation locale (détection des silences)…")
    return estimer_alignement(voix, texte)


def _silences(fichier: Path, seuil_db: int = -35, min_s: float = 0.15) -> list[tuple[float, float]]:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(fichier), "-af",
                        f"silencedetect=noise={seuil_db}dB:d={min_s}", "-f", "null", "-"],
                       capture_output=True, text=True)
    debuts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", p.stderr)]
    fins = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    return list(zip(debuts, fins + [duree(fichier)] * (len(debuts) - len(fins))))


def estimer_alignement(voix: Path, texte: str) -> list[dict]:
    """Sans API : on repère les zones parlées entre les silences, on y associe les phrases,
    puis on répartit les mots d'une phrase au prorata de leur longueur."""
    total = duree(voix)
    sil = _silences(voix)
    zones, t = [], 0.0
    for a, b in sil:
        if a - t > 0.12:
            zones.append((t, a))
        t = b
    if total - t > 0.12:
        zones.append((t, total))
    phrases = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", texte.strip()) if p.strip()]
    if not zones:
        zones = [(0.0, total)]
    # fusionne les zones en trop (petites respirations dans une phrase) avec la zone la plus proche
    while len(zones) > len(phrases) and len(zones) > 1:
        ecarts = [zones[i + 1][0] - zones[i][1] for i in range(len(zones) - 1)]
        i = ecarts.index(min(ecarts))
        zones[i:i + 2] = [(zones[i][0], zones[i + 1][1])]
    if len(zones) < len(phrases):  # moins de pauses que de phrases : une seule zone pour tout le texte
        zones, phrases = [(zones[0][0], zones[-1][1])], [" ".join(phrases)]
    mots = []
    for (a, b), phrase in zip(zones, phrases):
        liste = phrase.split()
        poids = [max(2, len(m)) for m in liste]
        t = a
        for m, p in zip(liste, poids):
            d = (b - a) * p / sum(poids)
            mots.append({"mot": m, "debut": round(t, 3), "fin": round(t + d * 0.92, 3)})
            t += d
    return mots


# ------------------------------------------------------------------ 2. scènes dans les rushes

def _scenes(fichier: Path, seuil: float = 0.3) -> list[float]:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(fichier), "-vf",
                        f"select='gt(scene,{seuil})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", p.stderr)]


def _noirs(fichier: Path) -> list[tuple[float, float]]:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(fichier), "-vf", "blackdetect=d=0.3:pix_th=0.12",
                        "-an", "-f", "null", "-"], capture_output=True, text=True)
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", p.stderr)]


def lister_scenes(rushes: list[Path], duree_min: float = 0.8) -> list[dict]:
    scenes = []
    for f in rushes:
        fin = duree(f)
        bornes = [0.0] + [t for t in _scenes(f) if 0.3 < t < fin - 0.3] + [fin]
        noirs = _noirs(f)
        for a, b in zip(bornes, bornes[1:]):
            # on retire les passages noirs (écran de fin, fondus)
            for na, nb in noirs:
                if na <= a < nb:
                    a = nb
                if na < b <= nb:
                    b = na
            if b - a >= duree_min:
                scenes.append({"fichier": str(f), "debut": a, "fin": b})
    if not scenes:
        raise StudioError("Aucune scène exploitable trouvée dans les rushes.")
    log("Rushes", f"{len(scenes)} scènes exploitables détectées")
    return scenes


# ------------------------------------------------------------------ 3. plan de coupe

def points_de_coupe(mots: list[dict], total: float, rythme: float = 0.6) -> list[float]:
    coupes = [0.0]
    for i, m in enumerate(mots):
        debut_phrase = i > 0 and (mots[i - 1]["mot"].endswith((".", "!", "?", "…"))
                                  or m["debut"] - mots[i - 1]["fin"] > 0.25)
        if i == 0:
            continue
        if debut_phrase or m["debut"] - coupes[-1] >= rythme:
            if m["debut"] - coupes[-1] >= 0.25:
                coupes.append(round(m["debut"], 3))
    return coupes + [total]


# ------------------------------------------------------------------ 4. rendu des plans

def _recadrage(src_w: int, src_h: int, zoom: float, cx: float = 0.5, cy: float = 0.5) -> str:
    # plus grande zone 9:16 contenue dans la source, puis zoom
    if src_w / src_h > W / H:
        ch = src_h
        cw = int(ch * W / H)
    else:
        cw = src_w
        ch = int(cw * H / W)
    cw, ch = int(cw / zoom) // 2 * 2, int(ch / zoom) // 2 * 2
    x = int(min(max(cx * src_w - cw / 2, 0), src_w - cw))
    y = int(min(max(cy * src_h - ch / 2, 0), src_h - ch))
    return f"crop={cw}:{ch}:{x}:{y}"


def _taille(fichier: str) -> tuple[int, int]:
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:stream_side_data=rotation", "-of", "json", fichier],
                       capture_output=True, text=True)
    s = json.loads(p.stdout)["streams"][0]
    w, h = s["width"], s["height"]
    rot = next((abs(int(d.get("rotation", 0))) for d in s.get("side_data_list", [])), 0)
    return (h, w) if rot in (90, 270) else (w, h)


def _moments(scenes: list[dict], fenetre: float = 2.0) -> list[dict]:
    """Découpe les scènes longues en « moments » de ~2 s pour piocher dans toute la vidéo
    (sinon une longue scène n'offrirait que ses premières secondes)."""
    moments = []
    for s in scenes:
        t = s["debut"]
        while t + 0.6 <= s["fin"]:
            moments.append({**s, "debut": t, "fin": min(s["fin"], t + fenetre)})
            t += fenetre
    return moments


def _pas_premier(n: int) -> int:
    """Pas de parcours qui fait sauter d'un endroit éloigné à l'autre sans jamais répéter avant la fin."""
    from math import gcd
    p = max(1, round(n * 0.38))
    while gcd(p, n) != 1:
        p += 1
    return p


def decouper(projet: Path, rushes: list[Path], mots: list[dict], total: float, rythme: float = 0.6) -> list[dict]:
    moments = _moments(lister_scenes(rushes))
    coupes = points_de_coupe(mots, total, rythme)
    dossier = projet / "plans"
    dossier.mkdir(exist_ok=True)
    pas = _pas_premier(len(moments))
    zooms = [1.0, 1.35, 1.15, 1.6]
    tailles = {}
    plans = []
    for k, (a, b) in enumerate(zip(coupes, coupes[1:])):
        d = b - a
        m = moments[(k * pas) % len(moments)]
        vitesse = 0.6 if d >= 1.0 else 1.0                  # ralenti fluide sur les plans longs
        besoin = d * vitesse + 0.1
        debut = max(m["debut"], min(m["debut"], m["fin"] - besoin))
        if m["fichier"] not in tailles:
            tailles[m["fichier"]] = _taille(m["fichier"])
        sw, sh = tailles[m["fichier"]]
        vf = [f"trim={debut:.3f}:{debut + besoin:.3f}", "setpts=PTS-STARTPTS",
              _recadrage(sw, sh, zooms[k % len(zooms)]), f"setpts=PTS/{vitesse}",
              "minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1" if vitesse < 1 else f"fps={FPS}",
              f"scale={W}:{H}:flags=lanczos", "setsar=1", "format=yuv420p"]
        sortie = dossier / f"plan_{k + 1:02d}.mp4"
        ffmpeg(["ffmpeg", "-y", "-i", m["fichier"], "-an", "-vf", ",".join(vf), "-t", f"{d:.3f}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "15", str(sortie)])
        plans.append({"fichier": str(sortie), "duree_cible": d})
    log("Rushes", f"{len(plans)} plans découpés sur le rythme de la voix ({len(moments)} moments disponibles)")
    return plans
