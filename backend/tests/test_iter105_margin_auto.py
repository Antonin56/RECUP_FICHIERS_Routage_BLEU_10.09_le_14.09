"""
Iter105 — 23/07/2026 (demande armateur) : MODE AUTO de la marge latérale.

Règles validées ici :
  1. lateral_margin_m ABSENT (mode AUTO, défaut app) → le moteur applique le
     plancher 10 m + attraction milieu de chenal : route OK dans le Golfe du
     Morbihan, AUCUN warning de relaxation, AUCUN lateral_margin_used_m.
  2. Mode MANUEL 50 m (valeur réelle de l'armateur) → route OK dans le Golfe.
  3. Mode MANUEL excessif (260 m) → relaxation depuis LA VALEUR CONFIGURÉE
     avec warning indiquant OÙ corriger (« Réglages → Mon bateau »).
  4. Échec définitif (destination sans eau ≤ 5 km) → message 422 enrichi :
     réglage en cause (tirant d'eau + marge de fond) + où le corriger.
"""
import os
import sys

import pytest
import requests

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/app/backend/.env")
from core.auth import make_jwt  # noqa: E402

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://nav-engine-i.preview.emergentagent.com",
).rstrip("/")
QA = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
ADMIN_USER_ID = "user_0b6070a69154"

ARRADON = {"lat": 47.610, "lng": -2.825}
SORTIE_GOLFE = {"lat": 47.50384, "lng": -2.92983}   # dest 1 vidéo armateur
TERRES_VANNES = {"lat": 47.95, "lng": -2.20}        # aucune eau ≤ 5 km


@pytest.fixture(scope="module")
def token():
    return make_jwt(ADMIN_USER_ID)


def _compute(token: str, body: dict) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/api/routes/compute",
    # 03/08/2026 — moteur ÉPINGLÉ : ce test verrouille le comportement
    # HISTORIQUE (Moteur A / B). Le compte armateur utilise désormais le
    # Moteur C, dont les règles diffèrent volontairement (jamais d'échec,
    # marge 50/20 m propre, sens conventionnel forcé) : sans engine_id
    # explicite, l'API choisirait le moteur ACTIF du compte.
        json={"engine_id": "engine_a", "start": ARRADON, "draft_m": 1.5,
              "depth_margin_m": 0.5, **body},
        headers={"Authorization": f"Bearer {token}", **QA},
        timeout=180,
    )


class TestModeAuto:
    def test_auto_golfe_ok_sans_relaxation(self, token):
        """AUTO (champ absent) : le Golfe passe, aucune trace de relaxation."""
        r = _compute(token, {"end": SORTIE_GOLFE})
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["waypoints"]) >= 2
        assert d["distance_m"] > 10_000
        assert "lateral_margin_used_m" not in d
        assert not any("marge latérale réduite" in w for w in d["warnings"])

    def test_auto_null_explicite_equivalent(self, token):
        """lateral_margin_m: null == champ absent (contrat API)."""
        r = _compute(token, {"end": SORTIE_GOLFE, "lateral_margin_m": None})
        assert r.status_code == 200, r.text


class TestModeManuel:
    def test_manuel_50m_golfe_ok(self, token):
        """50 m (réglage réel de l'armateur) : le Golfe passe."""
        r = _compute(token, {"end": SORTIE_GOLFE, "lateral_margin_m": 50})
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["waypoints"]) >= 2

    def test_manuel_260m_relaxe_depuis_valeur_configuree(self, token):
        """260 m : relaxation 260 → X (< 260) + warning avec OÙ corriger."""
        r = _compute(token, {"end": SORTIE_GOLFE, "lateral_margin_m": 260})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["lateral_margin_used_m"] < 260
        w = next(x for x in d["warnings"] if "marge latérale réduite" in x)
        assert "260 m" in w                    # part bien de la valeur configurée
        assert "Mon bateau" in w               # indique où corriger


class TestEchecAvecConseil:
    def test_message_indique_reglage_et_ou_corriger(self, token):
        r = _compute(token, {"end": TERRES_VANNES})
        assert r.status_code == 422, r.text
        det = r.json()["detail"]
        assert det["code"] in ("end_blocked", "no_route")
        assert "blocked_at" in det
        assert "tirant d'eau" in det["message"]
        assert "Mon bateau" in det["message"]
