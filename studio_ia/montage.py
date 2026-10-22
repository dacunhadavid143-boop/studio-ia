"""Étape 5 — Montage automatique avec ffmpeg.

1. Chaque plan est recadré en 1080x1920, étalonné (look) et reçoit un effet « impact » au cut.
2. Les plans sont assemblés bout à bout.
3. Le texte est incrusté mot par mot à partir des timestamps de la voix.
4. Mixage audio : la musique baisse automatiquement quand la voix parle (ducking par sidechain),
   puis normalisation à -14 LUFS, le niveau recommandé par les plateformes sociales.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import FPS, H, W, log
from .outils import duree, ffmpeg

LOOKS = {
    # Noir & blanc façon VHS : aberration chromatique, léger flou, vignette lourde, grain
    "vhs": "hue=s=0,eq=contrast=1.18:brightness=-0.05:gamma=0.9,format=gbrp,rgbashift=rh=-5:bh=5:rv=1,"
           "gblur=sigma=0.7,unsharp=5:5:0.6,vignette=angle=PI/3.2,noise=alls=10:allf=t,format=yuv420p",
    # Sombre, contrasté, désaturé, teinte froide
    "sombre": "eq=contrast=1.25:brightness=-0.06:saturation=0.55:gamma=0.92,"
              "colorbalance=bs=0.06:bm=0.02:bh=-0.02,vignette=angle=PI/4,noise=alls=7:allf=t",
    "noir-blanc": "hue=s=0,eq=contrast=1.35:brightness=-0.04,vignette=angle=PI/4,noise=alls=8:allf=t",
    "naturel": "null",
}


@dataclass
class StyleMontage:
    look: str = "vhs"
    exposition: float = 1.0          # >1 éclaircit des images sombres (gamma)
    impact: float = 1.0              # force du zoom/flash à chaque cut, 0 = aucun
    police: str = "Oswald"
    mode_texte: str = "mot"          # 'mot' (un mot à la fois) ou 'groupe' (1-3 mots surlignés)
    position: str = "centre"         # 'centre' ou 'bas'
    taille: int | None = None
    contour: int = 8
    casse: str = "min"               # 'min' ou 'maj'
    sous_titres: bool = True
    volume_musique: float = 0.30
    marge_fin: float = 1.0           # secondes d'image après la fin de la voix


def effet_impact(force: float) -> str:
    """Zoom « punch » qui se relâche en 0,22 s + flash blanc de 0,1 s au début du plan."""
    if force <= 0:
        return "null"
    z = 0.10 * force
    return (f"scale=w='trunc({W}*(1+{z:.3f}*max(0,1-t/0.22))/2)*2'"
            f":h='trunc({H}*(1+{z:.3f}*max(0,1-t/0.22))/2)*2':eval=frame,crop={W}:{H},"
            f"eq=brightness='{0.35 * force:.3f}*max(0,1-t/0.10)':eval=frame")


def _temps_ass(t: float) -> str:
    t = max(0.0, t)
    h, reste = divmod(t, 3600)
    m, s = divmod(reste, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _nettoyer(mot: str, casse: str) -> str:
    # on retire les caractères de contrôle du format ASS ({, }, \) : aucune « injection » de balises
    m = re.sub(r"[{}\\]", "", mot)
    if casse == "maj":
        return m.upper()
    return m.lower().rstrip(".,;:!?…")


def ecrire_sous_titres(mots: list[dict], chemin: Path, st: StyleMontage) -> None:
    alignement, marge = (5, 0) if st.position == "centre" else (2, 620)
    taille = st.taille or (175 if st.mode_texte == "mot" else 110)
    entete = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Main,{st.police},{taille},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,2,0,1,"
        f"{st.contour},0,{alignement},60,60,{marge},1\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lignes = []
    if st.mode_texte == "mot":
        apparition = r"{\fad(70,0)\fscx112\fscy112\t(0,110,\fscx100\fscy100)}"
        for i, m in enumerate(mots):
            suivant = mots[i + 1]["debut"] if i + 1 < len(mots) else m["fin"] + 0.6
            fin = suivant if suivant - m["fin"] < 0.45 else m["fin"] + 0.3  # pas de mot figé pendant un long silence
            lignes.append(f"Dialogue: 0,{_temps_ass(m['debut'])},{_temps_ass(fin)},Main,,0,0,0,,"
                          f"{apparition}{_nettoyer(m['mot'], st.casse)}")
    else:
        groupes, courant = [], []
        for m in mots:
            courant.append(m)
            if len(courant) >= 3 or re.search(r"[.!?…,;:]$", m["mot"]):
                groupes.append(courant)
                courant = []
        if courant:
            groupes.append(courant)
        for gi, g in enumerate(groupes):
            fin_groupe = groupes[gi + 1][0]["debut"] if gi + 1 < len(groupes) else g[-1]["fin"] + 0.4
            for wi, m in enumerate(g):
                fin = g[wi + 1]["debut"] if wi + 1 < len(g) else fin_groupe
                texte = " ".join((r"{\c&H00D7FF&}" + _nettoyer(x["mot"], st.casse) + r"{\r}") if xi == wi
                                 else _nettoyer(x["mot"], st.casse) for xi, x in enumerate(g))
                lignes.append(f"Dialogue: 0,{_temps_ass(m['debut'])},{_temps_ass(fin)},Main,,0,0,0,,{texte}")
    chemin.write_text(entete + "\n".join(lignes) + "\n", encoding="utf-8")


def monter(projet: Path, plans: list[dict], timing: dict, musique: Path | None,
           st: StyleMontage, nom_final: str) -> Path:
    log("5/5 Montage", "recadrage 9:16, étalonnage et effets…")
    dossier = projet / "montage"
    dossier.mkdir(exist_ok=True)
    morceaux = []
    for i, p in enumerate(plans, 1):
        source = Path(p["fichier"])
        d = min(p["duree_cible"], duree(source))
        sortie = dossier / f"n_{i:02d}.mp4"
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1,"
              f"eq=gamma={st.exposition},{LOOKS[st.look]},{effet_impact(st.impact if i > 1 else 0)},format=yuv420p")
        ffmpeg(["ffmpeg", "-y", "-i", str(source), "-t", f"{d:.3f}", "-an", "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "18", str(sortie)])
        morceaux.append(sortie.name)

    (dossier / "liste.txt").write_text("".join(f"file '{m}'\n" for m in morceaux), encoding="utf-8")
    ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "liste.txt", "-c", "copy", "video_brute.mp4"],
           cwd=dossier)

    total = timing["duree"] + st.marge_fin
    filtre_texte = "null"
    if timing.get("mots") and st.sous_titres:
        ecrire_sous_titres(timing["mots"], dossier / "sous_titres.ass", st)
        filtre_texte = "ass=sous_titres.ass"

    log("5/5 Montage", "mixage voix + musique (ducking) et texte…")
    entrees = ["-i", "video_brute.mp4", "-i", str((projet / "voix.mp3").resolve())]
    if musique:
        entrees += ["-i", str(Path(musique).resolve())]
        audio = (f"[1:a]aresample=48000,apad,atrim=0:{total:.3f},asplit=2[v1][sc];"
                 f"[2:a]aresample=48000,atrim=0:{total:.3f},volume={st.volume_musique},"
                 f"afade=t=out:st={max(0, total - 1.2):.3f}:d=1.2[m];"
                 f"[m][sc]sidechaincompress=threshold=0.04:ratio=4:attack=40:release=350[md];"
                 f"[v1][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        audio = f"[1:a]aresample=48000,apad,atrim=0:{total:.3f},loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    filtre = f"[0:v]{filtre_texte},trim=0:{total:.3f},setpts=PTS-STARTPTS[v];{audio}"
    final = projet / nom_final
    ffmpeg(["ffmpeg", "-y", *entrees, "-filter_complex", filtre, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final.resolve())], cwd=dossier)
    return final
