"""
Iter104 — Bug ARMATEUR (23/07/2026, vidéo « toujours impossible de créer une
route automatique ») : le réglage bateau « marge latérale » à 260 m fermait
TOUS les chenaux du Golfe du Morbihan (< 2×260 m de large) → no_route
systématique, et à marée basse le départ Arradon lui-même devenait
start_blocked.

Correctif (routers/routing.py) : RELAXATION AUTOMATIQUE de la marge latérale
par paliers (÷2, plancher 10 m) quand compute_route échoue en no_route /
start_blocked / end_blocked. Le tirant d'eau et la marge de fond restent
STRICTS. La route annonce la réduction (warning + lateral_margin_used_m).
"""
import os
import sys

import pytest
import requests

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/app/backend/.env")
from core.auth import make_jwt  # noqa: E402
from core.routing import RouteError, compute_route  # noqa: E402

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://nav-engine-i.preview.emergentagent.com",
).rstrip("/")
QA = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
ADMIN_USER_ID = "user_0b6070a69154"

ARRADON = (47.610, -2.825)
HOME_ARMATEUR = {"lat": 47.8632, "lng": -2.3181}     # à terre (vidéo)
SORTIE_GOLFE = {"lat": 47.50384, "lng": -2.92983}    # dest 1 de la vidéo
GROIX = {"lat": 47.46402, "lng": -3.59687}           # dest 4 de la vidéo


@pytest.fixture(scope="module")
def admin_token():
    return make_jwt(ADMIN_USER_ID)


def _compute(token: str, body: dict) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/api/routes/compute",
    # 03/08/2026 — moteur ÉPINGLÉ : ce test verrouille le comportement
    # HISTORIQUE (Moteur A / B). Le compte armateur utilise désormais le
    # Moteur C, dont les règles diffèrent volontairement (jamais d'échec,
    # marge 50/20 m propre, sens conventionnel forcé) : sans engine_id
    # explicite, l'API choisirait le moteur ACTIF du compte.
        json={"engine_id": "engine_a", **body},
        headers={"Authorization": f"Bearer {token}", **QA},
        timeout=180,
    )


class TestCoeurMoteur:
    """Documente le comportement du MOTEUR (sans relaxation) : à 260 m le
    Golfe est infranchissable, à 10 m il est ouvert — c'est bien la marge."""

    def test_260m_ferme_le_golfe(self):
        with pytest.raises(RouteError) as exc:
            compute_route(*ARRADON, SORTIE_GOLFE["lat"], SORTIE_GOLFE["lng"],
                          1.5, 0.5, 260.0, tide_m=0.0)
        assert exc.value.code in ("no_route", "start_blocked")

    def test_10m_ouvre_le_golfe(self):
        r = compute_route(*ARRADON, SORTIE_GOLFE["lat"], SORTIE_GOLFE["lng"],
                          1.5, 0.5, 10.0, tide_m=0.0)
        assert len(r["waypoints"]) >= 2
        assert r["distance_m"] > 10_000


class TestRelaxationEndpoint:
    def test_marge_260_relaxee_avec_warning(self, admin_token):
        """Scénario EXACT de la vidéo : départ à terre (fallback Arradon),
        marge 260 m → la route DOIT sortir avec une marge réduite annoncée."""
        r = _compute(admin_token, {
            "start": HOME_ARMATEUR, "end": SORTIE_GOLFE,
            "draft_m": 1.5, "depth_margin_m": 0.5, "lateral_margin_m": 260,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["waypoints"]) >= 2
        assert data["lateral_margin_used_m"] < 260
        assert any("marge latérale réduite" in w for w in data["warnings"])

    def test_longue_route_groix_relaxee(self, admin_token):
        r = _compute(admin_token, {
            "start": HOME_ARMATEUR, "end": GROIX,
            "draft_m": 1.5, "depth_margin_m": 0.5, "lateral_margin_m": 260,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["distance_m"] > 50_000
        assert data["lateral_margin_used_m"] < 260

    def test_pas_de_relaxation_si_inutile(self, admin_token):
        """Marge 10 m (défaut) : aucune relaxation, pas de champ ni warning."""
        r = _compute(admin_token, {
            "start": HOME_ARMATEUR, "end": SORTIE_GOLFE,
            "draft_m": 1.5, "depth_margin_m": 0.5, "lateral_margin_m": 10,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert "lateral_margin_used_m" not in data
        assert not any("marge latérale réduite" in w for w in data["warnings"])

    def test_hors_zone_echec_immediat(self, admin_token):
        """out_of_coverage (Méditerranée) : PAS de retry en cascade → 422."""
        r = _compute(admin_token, {
            "start": HOME_ARMATEUR, "end": {"lat": 43.0, "lng": 6.0},
            "draft_m": 1.5, "depth_margin_m": 0.5, "lateral_margin_m": 260,
        })
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "out_of_coverage"
