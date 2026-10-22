"""Étape 4 — Musique.

Deux moteurs :
1. Eleven Music (API ElevenLabs) : musique instrumentale générée à partir d'un prompt texte,
   licence commerciale selon l'abonnement.
2. Synthèse locale (gratuite, hors ligne) : une bande-son « dark cinématique » calculée
   en Python (numpy). Les impacts sont placés exactement au début de chaque phrase de la
   voix off, ce qu'aucun générateur externe ne garantit. 100 % libre de droits.
"""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import requests

from .config import StudioError, cle, log, masquer, modele_musique
from .outils import ffmpeg

API_EL = "https://api.elevenlabs.io"
SR = 44100


# ------------------------------------------------------------------ 1. Eleven Music (API)

def generer_eleven_music(sortie: Path, prompt: str, duree_s: float) -> Path:
    log("4/5 Musique", f"Eleven Music compose la musique ({modele_musique()})…")
    r = requests.post(
        f"{API_EL}/v1/music",
        headers={"xi-api-key": cle("ELEVENLABS_API_KEY"), "content-type": "application/json"},
        params={"output_format": "mp3_44100_128"},
        json={"prompt": prompt[:4000], "music_length_ms": int(max(10, math.ceil(duree_s + 2)) * 1000),
              "model_id": modele_musique(), "force_instrumental": True},
        timeout=600,
    )
    if r.status_code != 200:
        raise StudioError(f"Eleven Music {r.status_code} : {masquer(r.text[:400])}")
    sortie.write_bytes(r.content)
    return sortie


# ------------------------------------------------------------------ 2. Synthèse locale

def debuts_de_phrases(mots: list[dict], pause_min: float = 0.2) -> list[float]:
    """Repère le début de chaque phrase : premier mot, ou mot qui suit une pause / un point."""
    debuts = []
    for i, m in enumerate(mots):
        if i == 0 or mots[i - 1]["mot"].endswith((".", "!", "?", "…")) \
                or m["debut"] - mots[i - 1]["fin"] >= pause_min:
            debuts.append(round(m["debut"], 3))
    return debuts


def synthetiser(sortie: Path, duree_s: float, impacts: list[tuple[float, float]],
                style: str = "lourd", graine: int = 7) -> Path:
    """Compose une bande-son.

    impacts : liste de (instant en s, force 0..1.5) -> un coup grave 808 + impact cinéma à chaque instant.
    style   : 'lourd' (dark trap lent, cloches) ou 'atmo' (piano sombre, souffle, impacts discrets).
    """
    rng = np.random.default_rng(graine)
    n = int(SR * (duree_s + 0.4))
    t = np.arange(n) / SR

    def env(L, a, d):
        x = np.arange(L) / SR
        return np.minimum(1, x / a) * np.exp(-x / d)

    def passe_bas(x, k):
        return np.convolve(x, np.ones(k) / k, "same")

    def placer(sig, debut):
        z = np.zeros(n)
        i = int(debut * SR)
        j = min(n, i + len(sig))
        if i < n:
            z[i:j] = sig[: j - i]
        return z

    def norm(x):
        actif = x[np.abs(x) > 1e-4]
        return x / (np.sqrt(np.mean(actif ** 2)) + 1e-12) if actif.size else x

    def boom(d=2.4, f0=140, f1=36):
        L = int(SR * d)
        x = np.arange(L) / SR
        f = f1 + (f0 - f1) * np.exp(-x / 0.06)
        return np.tanh(2.6 * np.sin(2 * np.pi * np.cumsum(f) / SR)) * env(L, 0.003, 0.8)

    def impact(d=2.8):
        L = int(SR * d)
        return passe_bas(rng.standard_normal(L), 35) * env(L, 0.003, 0.4)

    def note(f, d=3.0, dec=1.2):
        L = int(SR * d)
        x = np.arange(L) / SR
        s = sum(a * np.sin(2 * np.pi * f * k * x) * np.exp(-x * (0.8 + k * 0.6))
                for k, a in [(1, 1), (2, 0.45), (3, 0.2)])
        return s * env(L, 0.003, dec)

    def nappe(freqs):
        s = np.zeros(n)
        for f in freqs:
            for det in (-0.25, 0, 0.25):
                ph = (f + det) * t + rng.uniform(0, 1)
                s += 2 * (ph % 1) - 1
        s = passe_bas(passe_bas(s, 100), 100)
        return s * np.minimum(1, t / 1.5) * np.minimum(1, (t[-1] - t) / 0.8)

    def reverb(x, d=3.0):
        L = int(SR * d)
        xx = np.arange(L) / SR
        ir = passe_bas(rng.standard_normal(L), 20) * np.exp(-xx / (d / 6))
        ir /= np.sqrt(np.sum(ir ** 2))
        N = len(x) + L
        return np.fft.irfft(np.fft.rfft(x, N) * np.fft.rfft(ir, N))[: len(x)]

    gamme = [146.83, 130.81, 116.54, 110.0, 98.0, 87.31, 73.42]  # ré mineur descendant
    booms = sum((placer(boom() * f, s) for s, f in impacts), np.zeros(n))
    chocs = sum((placer(impact() * f, s) for s, f in impacts), np.zeros(n))
    notes = sum((placer(note(gamme[i % len(gamme)]), s) for i, (s, _) in enumerate(impacts)), np.zeros(n))
    fond = nappe([36.71, 55.0] if style == "atmo" else [36.71, 55.0, 73.42])

    if style == "atmo":
        souffle = passe_bas(rng.standard_normal(n), 200) * np.minimum(1, t / 1.5)
        mix = norm(booms) + norm(chocs) * 10 ** (-8 / 20) + norm(notes) * 10 ** (-9 / 20) \
            + norm(fond) * 10 ** (-12 / 20) + norm(souffle) * 10 ** (-26 / 20)
    else:
        mix = norm(booms) + norm(chocs) * 10 ** (-9 / 20) + norm(notes) * 10 ** (-16 / 20) \
            + norm(fond) * 10 ** (-14 / 20)
    mix = mix + reverb(norm(notes) + norm(chocs)) * 10 ** (-10 / 20)
    mix = np.tanh(mix / np.max(np.abs(mix)) * 1.4)
    stereo = np.stack([mix, np.roll(mix, 180)], 1) * np.minimum(1, (t[-1] - t) / 0.6)[:, None]
    stereo /= np.max(np.abs(stereo)) * 1.12

    wav = sortie.with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())
    ffmpeg(["ffmpeg", "-y", "-i", str(wav), "-b:a", "192k", str(sortie)])
    wav.unlink()
    return sortie


def generer_musique(projet: Path, plan: dict, timing: dict, total: float, moteur: str,
                    envie: str | None = None, style: str = "lourd") -> Path | None:
    sortie = projet / "musique.mp3"
    if sortie.exists():
        log("4/5 Musique", "déjà fait (musique.mp3)")
        return sortie
    if moteur == "aucune":
        return None
    if moteur == "eleven":
        prompt = f"{envie}. {plan['prompt_musique']}" if envie else plan["prompt_musique"]
        return generer_eleven_music(sortie, prompt, total)
    log("4/5 Musique", "synthèse locale calée sur les phrases de la voix…")
    debuts = debuts_de_phrases(timing["mots"]) or [0.0]
    impacts = [(s, 0.9) for s in debuts] + [(min(timing["duree"] + 0.2, total - 0.5), 1.1)]
    return synthetiser(sortie, total, impacts, style=style)
