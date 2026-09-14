"""
Iter102 — Bug ARMATEUR (23/07/2026) : départ posé À TERRE près de
Locmariaquer → le snap accrochait une POCHE d'eau isolée du MNT et le
moteur levait un "no_route" trompeur au lieu d'un "start_blocked".

Fix : TRAP_POCKET_KM2 + trap_check dans _solve_leg passe 1
(core/routing.py). Compte testeur : fallback Arradon se déclenche
désormais ; compte normal : reçoit un vrai start_blocked (422).

Regression coverage for:
- POST /api/routes/compute cas exact armateur (start Locmariaquer terre)
- use_tide=true non-régression marée
- Départ hors zone pilote (Ploërmel) → fallback Arradon
- Compte normal départ à terre → 422 start_blocked
- Compte normal départ en mer → 200 normal
- Non-régression blocage réel en cours de route → 422 no_route
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
    "https://nav-routing-speed.preview.emergentagent.com",
).rstrip("/")
QA = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
ADMIN_USER_ID = "user_0b6070a69154"        # SignalMar (admin/testeur)
NORMAL_USER_ID = "user_a5b6e415faea"       # TestDiag51 (non testeur)

# Points du bug armateur
LOCMARIAQUER_TERRE = {"lat": 47.57, "lng": -2.94}
DEST_GOLFE_SUD = {"lat": 47.52, "lng": -2.95}
PLOERMEL = {"lat": 47.86, "lng": -2.32}      # hors zone pilote (dans les terres)
ARRADON_EN_MER = {"lat": 47.61, "lng": -2.825}
PENERF_DECOUVRANT = {"lat": 47.50, "lng": -2.62}

BODY_DEFAULT = {"draft_m": 1.5, "depth_margin_m": 0.5, "lateral_margin_m": 10}
ARRADON_WP = {"lat": 47.61, "lng": -2.825}


@pytest.fixture(scope="module")
def admin_token():
    return make_jwt(ADMIN_USER_ID)


@pytest.fixture(scope="module")
def normal_token():
    return make_jwt(NORMAL_USER_ID)


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
        timeout=60,
    )


# ─── BUG FIX : cas exact armateur (compte testeur, départ à terre) ────────
class TestArmateurBugTester:
    def test_start_on_land_locmariaquer_falls_back_to_nearest_water(self, admin_token):
        """Cas EXACT armateur : départ Locmariaquer terre → route depuis l'eau
        navigable la plus proche (23/07, remplace le fallback Arradon) au lieu
        du no_route trompeur d'avant le fix."""
        r = _compute(admin_token, {
            "start": LOCMARIAQUER_TERRE, "end": DEST_GOLFE_SUD, **BODY_DEFAULT,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        w0 = d["waypoints"][0]
        assert (w0["lat"], w0["lng"]) != (LOCMARIAQUER_TERRE["lat"], LOCMARIAQUER_TERRE["lng"])
        assert d["distance_m"] > 2_000 and d["distance_m"] < 20_000, d["distance_m"]
        assert any("remplacé par" in w for w in d["warnings"]), d["warnings"]

    def test_start_on_land_with_use_tide_true(self, admin_token):
        """29/07 (routage 100 % ZH) — use_tide est IGNORÉ : plus d'info tide
        dans la réponse. Départ estran → route « eau peu profonde » (rouge)
        depuis le point demandé, ou remplacement testeur."""
        r = _compute(admin_token, {
            "start": LOCMARIAQUER_TERRE, "end": DEST_GOLFE_SUD,
            **BODY_DEFAULT, "use_tide": True,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("tide") is None, "info marée inattendue (routage ZH only)"
        replaced = any("remplacé par" in w for w in d["warnings"])
        w0 = d["waypoints"][0]
        near_start = (abs(w0["lat"] - LOCMARIAQUER_TERRE["lat"]) < 0.01
                      and abs(w0["lng"] - LOCMARIAQUER_TERRE["lng"]) < 0.01)
        assert replaced or near_start, (d["warnings"], w0)

    def test_start_out_of_coverage_ploermel_falls_back_to_arradon(self, admin_token):
        """Départ hors zone (Ploërmel, dans les terres) → fallback out_of_coverage."""
        r = _compute(admin_token, {
            "start": PLOERMEL, "end": DEST_GOLFE_SUD, **BODY_DEFAULT,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        # 29/07 (IALA cardinales 300 m) — le 1er waypoint peut être ajusté de
        # quelques dizaines de mètres par le snap fin : on vérifie la
        # PROXIMITÉ d'Arradon (< 100 m), pas l'égalité exacte.
        w0 = d["waypoints"][0]
        import math as _math
        dd = _math.hypot((w0["lat"] - ARRADON_WP["lat"]) * 110_574.0,
                         (w0["lng"] - ARRADON_WP["lng"]) * 75_000.0)
        assert dd < 100.0, w0
        assert any("Arradon" in w for w in d["warnings"])


# ─── COMPTE NORMAL : pas de fallback, vrai start_blocked ──────────────────
class TestNormalAccountNoFallback:
    def test_start_on_land_returns_422_start_blocked(self, normal_token):
        """29/07 (façon Navionics) — départ sur l'ESTRAN (découvrant) : la
        route est désormais TRACÉE en mode « eau peu profonde » (tronçons
        rouges + risk). Le refus sec start_blocked ne reste que pour la
        TERRE FRANCHE (bourg de Locmariaquer, fond < -7 m dans le MNT)."""
        # a) Estran (LOCMARIAQUER_TERRE ≈ -0,8 m ZH) → 200 rouge.
        r = _compute(normal_token, {
            "start": LOCMARIAQUER_TERRE, "end": DEST_GOLFE_SUD, **BODY_DEFAULT,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("shallow_route") is True and d.get("risk") is True, d.get("warnings")
        assert d.get("compromised_legs"), "tronçons rouges attendus (départ estran)"
        # b) Terre franche loin de l'eau (Vannes intra-muros, > 400 m du
        #    port : hors rayon de snap) → 422 start_blocked inchangé.
        r2 = _compute(normal_token, {
            "start": {"lat": 47.658, "lng": -2.760}, "end": DEST_GOLFE_SUD,
            **BODY_DEFAULT,
        })
        assert r2.status_code == 422, r2.text
        det = r2.json()["detail"]
        assert det["code"] == "start_blocked", det
        assert "non navigable" in det["message"].lower() or "Départ" in det["message"]

    def test_start_at_sea_returns_normal_route(self, normal_token):
        """Non-régression compte normal départ en mer → 200 route normale."""
        r = _compute(normal_token, {
            "start": ARRADON_EN_MER, "end": DEST_GOLFE_SUD, **BODY_DEFAULT,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["waypoints"]) >= 2
        assert d["distance_m"] > 1000


# ─── NON-RÉGRESSION : blocage réel en cours de route ─────────────────────
class TestRealBlockageNoRegression:
    def test_real_blockage_returns_422_not_500(self, normal_token):
        """Départ en mer → destination réellement inaccessible (Pénerf
        découvrant avec draft 1.5 sans marée) : JAMAIS 500.
        22/07/2026 — nouveau contrat « arrivée déplacée » : le moteur livre
        désormais une route jusqu'à l'eau navigable ATTEIGNABLE la plus
        proche (200 + end_snapped + warning) au lieu d'un refus sec. Le 422
        (no_route/end_blocked) reste valide si aucune eau à moins de 5 km."""
        r = _compute(normal_token, {
            "start": ARRADON_EN_MER, "end": PENERF_DECOUVRANT, **BODY_DEFAULT,
        })
        assert r.status_code in (200, 422), r.text
        if r.status_code == 200:
            d = r.json()
            assert d.get("end_snapped"), d
            assert d["end_snapped"]["offset_m"] > 300
            assert any("arrivée déplacée" in w for w in d["warnings"]), d["warnings"]
        else:
            det = r.json()["detail"]
            assert det["code"] in ("no_route", "end_blocked"), det
            assert "blocked_at" in det, det
