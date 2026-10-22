"""Tests du pipeline — aucun appel réseau, aucune clé API requise."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from studio_ia import config, montage, musique, rushes, video
from studio_ia.voix import caracteres_vers_mots

FFMPEG = shutil.which("ffmpeg") is not None


# ------------------------------------------------------------------ sécurité

def test_cle_manquante_donne_une_erreur_claire(monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    with pytest.raises(config.StudioError, match="FAL_KEY"):
        config.cle("FAL_KEY")


def test_les_cles_sont_masquees(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-123456")
    assert "sk-ant-secret-123456" not in config.masquer("erreur avec sk-ant-secret-123456")


def test_aucun_secret_dans_le_depot():
    """Cherche des motifs de vraies clés (longues) dans tous les fichiers versionnables."""
    import re
    motifs = [r"sk-ant-[A-Za-z0-9_-]{30,}", r"sk_[a-f0-9]{40,}", r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
              r"[0-9a-f]{12}:[0-9a-f]{32}"]
    racine = Path(__file__).resolve().parent.parent
    for f in list(racine.rglob("*.py")) + list(racine.rglob("*.md")) + list(racine.glob(".env*")):
        texte = f.read_text(encoding="utf-8", errors="ignore")
        for m in motifs:
            assert not re.search(m, texte), f"secret potentiel dans {f.name}"


def test_env_est_ignore_par_git():
    gitignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text()
    assert ".env" in gitignore.splitlines()


def test_sous_titres_sans_injection(tmp_path):
    mots = [{"mot": "{\\pos(0,0)}piège", "debut": 0.0, "fin": 0.5}]
    montage.ecrire_sous_titres(mots, tmp_path / "s.ass", montage.StyleMontage())
    ligne = [l for l in (tmp_path / "s.ass").read_text().splitlines() if l.startswith("Dialogue")][0]
    assert "\\pos" not in ligne and "piège" in ligne


# ------------------------------------------------------------------ logique

def test_alignement_caracteres_vers_mots():
    al = {"characters": list("Saute. Frappe"),
          "character_start_times_seconds": [i * 0.1 for i in range(13)],
          "character_end_times_seconds": [i * 0.1 + 0.1 for i in range(13)]}
    mots = caracteres_vers_mots(al)
    assert [m["mot"] for m in mots] == ["Saute.", "Frappe"]
    assert mots[1]["debut"] == pytest.approx(0.7)


def test_les_plans_couvrent_toute_la_voix():
    plan = {"plans": [{"prompt": "a", "duree": 1.5}, {"prompt": "b", "duree": 1.5}]}
    plans = video.ajuster_plans(plan, 20.0, "veo")  # Veo : 8 s max par plan -> plans ajoutés
    assert sum(p["duree_cible"] for p in plans) == pytest.approx(20.0, abs=0.06)
    assert all(p["duree_gen"] in (4, 6, 8) for p in plans)


def test_estimation_de_cout():
    assert video.estimer_cout([{"duree_gen": 5}, {"duree_gen": 5}], "kling") == pytest.approx(1.12)


def test_coupes_sur_les_debuts_de_phrase():
    mots = [{"mot": "Travaille", "debut": 0.0, "fin": 0.5}, {"mot": "en", "debut": 0.55, "fin": 0.7},
            {"mot": "silence.", "debut": 0.72, "fin": 1.3}, {"mot": "Disparais", "debut": 1.7, "fin": 2.3}]
    coupes = rushes.points_de_coupe(mots, 3.0, rythme=0.6)
    assert 1.7 in coupes and coupes[0] == 0.0 and coupes[-1] == 3.0


def test_debuts_de_phrases_pour_la_musique():
    mots = [{"mot": "Saute.", "debut": 0.1, "fin": 0.5}, {"mot": "Frappe.", "debut": 1.0, "fin": 1.4}]
    assert musique.debuts_de_phrases(mots) == [0.1, 1.0]


# ------------------------------------------------------------------ bout en bout (ffmpeg)

def _media(cmd):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *cmd], check=True)


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg absent")
def test_montage_complet(tmp_path):
    (tmp_path / "plans").mkdir()
    _media(["-f", "lavfi", "-i", "sine=frequency=180:duration=3", str(tmp_path / "voix.mp3")])
    plans = []
    for i in range(2):
        f = tmp_path / "plans" / f"plan_{i}.mp4"
        _media(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24:duration=3", str(f)])
        plans.append({"fichier": str(f), "duree_cible": 2.0})
    timing = {"duree": 3.0, "mots": [{"mot": "Travaille", "debut": 0.2, "fin": 0.8},
                                     {"mot": "dur.", "debut": 1.5, "fin": 2.0}]}
    mus = musique.synthetiser(tmp_path / "musique.mp3", 4.0, [(0.2, 0.9), (1.5, 1.0)])
    final = montage.monter(tmp_path, plans, timing, mus, montage.StyleMontage(police="DejaVu Sans"), "test.mp4")
    sortie = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                             "-of", "json", str(final)], capture_output=True, text=True).stdout
    video_stream = [s for s in json.loads(sortie)["streams"] if "width" in s][0]
    assert (video_stream["width"], video_stream["height"]) == (1080, 1920)
