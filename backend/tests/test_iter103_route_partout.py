"""
Iter103 — Bug ARMATEUR (22/07/2026, vidéo « je ne peux faire aucune route ») :
toutes les tentatives de route depuis la côte Damgan/Pénerf et vers les ports
du Golfe échouaient (429 côté vieux preview mis à part, le moteur refusait).

Causes racines corrigées (core/routing.py, core/seamarks.py) :
  1. FENÊTRE A* trop petite : le détour nécessaire (sortie du Golfe par
     Port-Navalo) sortait de la bbox départ→arrivée → escalade de fenêtres.
  2. DESTINATION estran/découvrante ou POCHE isolée du MNT (bassin de
     Crouesty) → arrivée ACCROCHÉE à l'eau navigable ATTEIGNABLE (≤ 5 km)
     avec avertissement « arrivée déplacée », au lieu d'un refus sec.
  3. SENS CONVENTIONNEL IALA faux dans les chenaux étroits (gradient bruité)
     → direction déduite du COUPLE rouge/verte (+ axe des balises du même
     côté pour les quinconces), couloir libre garanti entre chaque couple,
     strict réservé aux couples et à la maille fine.
  4. Waypoint grossier tombé dans une poche d'exclusion fine → BACKTRACKING.

À exécuter avant toute livraison, avec test_island_land_mask.py.
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
    "https://maritime-routing-v3.preview.emergentagent.com",
).rstrip("/")
QA = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
ADMIN_USER_ID = "user_0b6070a69154"        # SignalMar (armateur, testeur)

ARRADON = (47.610, -2.825)
HOME_ARMATEUR = {"lat": 47.8632, "lng": -2.3181}   # à terre, loin de la côte


@pytest.fixture(scope="module")
def admin_token():
    return make_jwt(ADMIN_USER_ID)


def _compute(token: str, body: dict) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/api/routes/compute",
        json=body,
        headers={"Authorization": f"Bearer {token}", **QA},
        timeout=120,
    )


# ─── 1. Fenêtre élargie : détours hors bbox départ→arrivée ────────────────
class TestFenetreElargie:
    def test_arradon_penerf_detour_port_navalo(self):
        """Arradon → Pénerf : la sortie du Golfe (Port-Navalo, lng -2.92) est
        HORS bbox [-2.825, -2.655]. Avant : no_route. Après : ~35 km."""
        r = compute_route(*ARRADON, 47.500, -2.655, 1.5, 0.5, 10, 0.0)
        assert 25_000 < r["distance_m"] < 50_000, r["distance_m"]

    def test_arradon_dumet(self):
        r = compute_route(*ARRADON, 47.410, -2.620, 1.5, 0.5, 10, 0.0)
        assert r["distance_m"] > 25_000

    def test_non_regression_routes_directes(self):
        """Les routes qui marchaient restent rapides et directes."""
        r = compute_route(*ARRADON, 47.548, -2.919, 1.5, 0.5, 10, 0.0)
        assert 8_000 < r["distance_m"] < 14_000


# ─── 2. Arrivée déplacée (estran, poche isolée) ───────────────────────────
class TestArriveeDeplacee:
    def test_plage_damgan_maree_haute(self):
        """Destination plage de Damgan à +2.5 m : route livrée jusqu'à l'eau
        navigable, arrivée déplacée annoncée."""
        r = compute_route(*ARRADON, 47.548, -2.578, 1.5, 0.5, 10, 2.5)
        es = r.get("end_snapped")
        assert es and 300 < es["offset_m"] <= 5_000, es
        assert any("arrivée déplacée" in w for w in r["warnings"]), r["warnings"]

    def test_crouesty_poche_mnt(self):
        """Bassin du Crouesty isolé dans le MNT : l'arrivée s'accroche à
        l'eau ATTEIGNABLE (l'entrée), pas à la poche fermée."""
        r = compute_route(*ARRADON, 47.542, -2.895, 1.5, 0.5, 10, 0.0)
        es = r.get("end_snapped")
        assert es and es["offset_m"] <= 1_500, es

    def test_refus_honnete_si_trop_loin(self):
        """Destination en plein champ (> 5 km de toute eau navigable
        atteignable) → toujours un refus explicite, jamais de route fantôme."""
        with pytest.raises(RouteError):
            compute_route(*ARRADON, 47.556, -2.540, 1.5, 0.5, 10, 0.0)


# ─── 3. Chenaux balisés ouverts (IALA couples + couloirs) ─────────────────
class TestChenauxBalises:
    @pytest.mark.parametrize("tide", [0.0, 2.5])
    def test_chenal_de_vannes(self, tide):
        """Le chenal de Vannes ne doit JAMAIS être fermé par son balisage."""
        r = compute_route(*ARRADON, 47.629, -2.762, 1.5, 0.5, 10, tide)
        # 27/07 (iter118) : borne basse 3,3 km — à marée nulle tout le chenal
        # découvre : l'arrivée est déplacée vers le THALWEG le plus proche
        # (préférence profondeur ≤ +400 m, écart minimal 20 m aux balises).
        assert 3_300 < r["distance_m"] < 9_000, r["distance_m"]

    def test_auray_maree_basse(self):
        """Rivière d'Auray à ZH : route jusqu'au point navigable le plus
        proche d'Auray (arrivée déplacée ≤ 5 km)."""
        r = compute_route(*ARRADON, 47.655, -2.955, 1.5, 0.5, 10, 0.0)
        es = r.get("end_snapped")
        assert es and es["offset_m"] <= 5_000, es


# ─── 4. Cas E2E exact armateur (API, compte testeur, départ = domicile) ───
class TestE2EArmateur:
    @pytest.mark.parametrize("name,end", [
        ("plage Damgan", {"lat": 47.548, "lng": -2.578}),
        ("Penvins", {"lat": 47.510, "lng": -2.668}),
        ("riviere Penerf", {"lat": 47.500, "lng": -2.655}),
        ("Billiers/Vilaine", {"lat": 47.525, "lng": -2.485}),
        ("Kervoyal", {"lat": 47.545, "lng": -2.535}),
    ])
    def test_home_vers_cote_locale(self, admin_token, name, end):
        """Position GPS domicile (terre) → côte locale : 200 avec la marée
        réelle intégrée (défaut app). Le cas exact de la vidéo du 22/07."""
        r = _compute(admin_token, {
            "start": HOME_ARMATEUR, "end": end,
            "draft_m": 1.5, "depth_margin_m": 0.5, "lateral_margin_m": 10,
            "use_tide": True,
        })
        assert r.status_code == 200, f"{name}: {r.text[:300]}"
        d = r.json()
        assert len(d["waypoints"]) >= 2
