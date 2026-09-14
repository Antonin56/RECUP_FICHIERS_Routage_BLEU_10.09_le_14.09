"""Iter 70 — Verify pre-generated TTS catalog serves broad sample of phrases
from Mongo cache with < 1.5 s latency and audio/mpeg body > 5 KB.

Reference phrases come from _catalog_texts() in /app/backend/routers/tts.py
which must match frontend/src/lib/voice-alerts.ts buildAlertText output.
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "").rstrip("/") or \
    "https://nav-routing-speed.preview.emergentagent.com"

PERIM = "dans votre périmètre d'alerte."

# ── FIXED AUTHORITY PHRASES (no speed modulation) ──────────────────────────
FIXED_PHRASES = [
    "Attention, gendarmerie maritime signalée " + PERIM,
    "Attention, affaires maritimes signalées " + PERIM,
    "Attention, police de l'environnement signalée " + PERIM,
    "Attention, douanes maritimes signalées " + PERIM,
    "Attention, autorité maritime signalée " + PERIM,
]

# ── MODULATED SUBJECTS ──────────────────────────────────────────────────────
def _urg(subj: str, acc: str) -> str:
    return f"Attention ! Soyez très vigilant : {subj} {acc} {PERIM}"

def _vig(subj: str, acc: str) -> str:
    return f"Soyez vigilant, {subj} {acc} {PERIM}"

def _calm(subj: str, acc: str) -> str:
    return f"{subj[0].upper()}{subj[1:]} {acc} {PERIM}"

# Broad sample across all subjects + all 3 speed tiers
MODULATED_PHRASES = [
    # Obstacles — roche
    _urg("roche non répertoriée", "signalée"),
    _vig("roche non répertoriée", "signalée"),
    _calm("roche non répertoriée", "signalée"),
    # Obstacles — ofni
    _urg("objet flottant non identifié", "signalé"),
    _vig("objet flottant non identifié", "signalé"),
    # Obstacles — bouée
    _urg("bouée ou matériel de pêche", "signalé"),
    _calm("bouée ou matériel de pêche", "signalé"),
    # Obstacles — conteneur
    _vig("conteneur partiellement immergé", "signalé"),
    _calm("conteneur partiellement immergé", "signalé"),
    # Obstacles — bois
    _vig("bois flottant", "signalé"),
    _calm("bois flottant", "signalé"),
    # Obstacles — fallback
    _urg("obstacle à la navigation", "signalé"),
    _vig("obstacle à la navigation", "signalé"),
    _calm("obstacle à la navigation", "signalé"),
    # Mammifères marins
    _urg("mammifère marin", "signalé"),
    _vig("mammifère marin blessé", "signalé"),
    _urg("mammifère marin mort", "signalé"),
    _calm("mammifère marin mort", "signalé"),
    # Oiseaux
    _urg("oiseau marin blessé", "signalé"),
    _vig("oiseau marin mort", "signalé"),
    # Autres animaux
    _urg("animal marin blessé", "signalé"),
    _calm("animal marin mort", "signalé"),
    # Pollutions
    _urg("pollution locale", "signalée"),
    _vig("pollution locale", "signalée"),
    _urg("pollution importante", "signalée"),
    _calm("pollution importante", "signalée"),
]

ALL_PHRASES = FIXED_PHRASES + MODULATED_PHRASES  # 5 + 26 = 31 phrases


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


class TestCatalogCacheHit:
    """Every phrase × both voices should hit Mongo cache (fast, no OpenAI call)."""

    @pytest.mark.parametrize("voice", ["alloy", "echo"])
    @pytest.mark.parametrize("text", ALL_PHRASES)
    def test_phrase_cache_hit(self, api, text, voice):
        t0 = time.time()
        r = api.post(f"{BASE_URL}/api/tts/alert",
                     json={"text": text, "voice": voice}, timeout=10)
        elapsed_ms = (time.time() - t0) * 1000
        assert r.status_code == 200, \
            f"HTTP {r.status_code} for voice={voice} text={text[:60]!r}"
        assert r.headers.get("content-type", "").startswith("audio/mpeg"), \
            f"bad content-type {r.headers.get('content-type')} for {text[:60]!r}"
        assert len(r.content) > 5_000, \
            f"body only {len(r.content)} bytes for voice={voice} text={text[:60]!r}"
        assert elapsed_ms < 1500, \
            f"SLOW {elapsed_ms:.0f} ms (>1.5 s cache miss?) voice={voice} text={text[:60]!r}"


class TestOnDemandUncachedText:
    """Sanity: a NON-catalog text still works (generates + caches). Not run in
    default suite to avoid burning LLM credits — kept for manual verification.
    """

    @pytest.mark.skip(reason="skipped by default — would trigger fresh OpenAI TTS")
    def test_novel_text_generates(self, api):  # pragma: no cover
        r = api.post(f"{BASE_URL}/api/tts/alert",
                     json={"text": "TEST_NOVEL_" + str(time.time()),
                           "voice": "alloy"}, timeout=15)
        assert r.status_code == 200
