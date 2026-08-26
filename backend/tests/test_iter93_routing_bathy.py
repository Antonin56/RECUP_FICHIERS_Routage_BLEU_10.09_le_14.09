"""
Iter93 — V2 N1 : isobathes + moteur de route sûre.
Backend : routers/bathy.py (GET /api/bathy/isobaths, /coverage) et
routers/routing.py (POST /api/routes/compute) sur MNT SHOM Morbihan 20 m.
"""
import os

import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://signalmar-optimize.preview.emergentagent.com",
).rstrip("/")
QA_BYPASS = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
ADMIN_PHONE = "0760071445"

# Points de test (Golfe du Morbihan) :
WATER_A = {"lat": 47.543, "lng": -2.921}   # entrée du Golfe (Port-Navalo)
WATER_B = {"lat": 47.617, "lng": -2.828}   # près d'Arradon
INLAND = {"lat": 47.69, "lng": -2.75}      # campagne au nord de Vannes
OUT = {"lat": 43.3, "lng": 5.3}            # Méditerranée : hors couverture (zone étendue 23/07 : façade Ouest)


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    s.headers.update(QA_BYPASS)
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": ADMIN_PHONE})
    assert r.status_code == 200, r.text
    r = s.post(f"{BASE_URL}/api/auth/otp/verify", json={"phone": ADMIN_PHONE, "code": "123456"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}", **QA_BYPASS}


class TestBathyCoverage:
    def test_coverage(self):
        r = requests.get(f"{BASE_URL}/api/bathy/coverage", headers=QA_BYPASS)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["available"] is True
        b = d["bounds"]
        assert b["west"] < -3.3 and b["east"] > -2.4
        assert b["south"] < 47.21 and b["north"] > 47.72


class TestIsobaths:
    def test_golfe_z13(self):
        r = requests.get(
            f"{BASE_URL}/api/bathy/isobaths",
            params={"bbox": "-2.95,47.52,-2.75,47.64", "z": 13},
            headers=QA_BYPASS,
        )
        assert r.status_code == 200, r.text
        fc = r.json()
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) > 10
        f = fc["features"][0]
        assert f["geometry"]["type"] == "LineString"
        assert f["properties"]["depth"] in fc["levels"]

    def test_levels_depend_on_zoom(self):
        r10 = requests.get(f"{BASE_URL}/api/bathy/isobaths",
                           params={"bbox": "-2.95,47.52,-2.75,47.64", "z": 10},
                           headers=QA_BYPASS).json()
        r14 = requests.get(f"{BASE_URL}/api/bathy/isobaths",
                           params={"bbox": "-2.95,47.52,-2.75,47.64", "z": 14},
                           headers=QA_BYPASS).json()
        assert len(r14["levels"]) > len(r10["levels"])
        assert 1.0 in r14["levels"] and 1.0 not in r10["levels"]

    def test_bad_bbox_422(self):
        r = requests.get(f"{BASE_URL}/api/bathy/isobaths",
                         params={"bbox": "nope", "z": 12}, headers=QA_BYPASS)
        assert r.status_code == 422

    def test_huge_bbox_empty(self):
        r = requests.get(f"{BASE_URL}/api/bathy/isobaths",
                         params={"bbox": "-10,40,10,55", "z": 6}, headers=QA_BYPASS)
        assert r.status_code == 200
        assert r.json()["features"] == []


class TestRouteCompute:
    def _body(self, start, end, **kw):
        return {
            "start": start, "end": end,
            "draft_m": kw.get("draft_m", 1.5),
            "depth_margin_m": kw.get("depth_margin_m", 0.5),
    # 03/08/2026 — moteur ÉPINGLÉ : ce test verrouille le comportement
    # HISTORIQUE (Moteur A / B). Le compte armateur utilise désormais le
    # Moteur C, dont les règles diffèrent volontairement (jamais d'échec,
    # marge 50/20 m propre, sens conventionnel forcé) : sans engine_id
    # explicite, l'API choisirait le moteur ACTIF du compte.
            "lateral_margin_m": kw.get("lateral_margin_m", 100),
            "engine_id": kw.get("engine_id", "engine_a"),
        }

    def test_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/routes/compute",
                          json=self._body(WATER_A, WATER_B), headers=QA_BYPASS)
        assert r.status_code in (401, 403)

    def test_golfe_route_ok(self, token):
        r = requests.post(f"{BASE_URL}/api/routes/compute",
                          json=self._body(WATER_A, WATER_B), headers=_auth(token))
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["waypoints"]) >= 2
        assert d["distance_m"] > 5000
        assert d["threshold_m"] == 2.0
        # Toute la route respecte le seuil (tolérance 0.25 m : l'arrondi des
        # virages est validé sur le masque décimé ~30 m, la grille 20 m peut
        # être quelques cm dessous — couvert par la marge + warning).
        assert d["min_depth_m"] is not None and d["min_depth_m"] >= d["threshold_m"] - 0.25
        # Profil : points avec lat/lng + profondeur, distances croissantes.
        prof = d["depth_profile"]
        assert len(prof) > 20
        assert all("lat" in p and "lng" in p for p in prof)
        assert prof[0]["d_m"] == 0.0 and prof[-1]["d_m"] == d["distance_m"]

    def test_end_on_land_422(self, token):
        r = requests.post(f"{BASE_URL}/api/routes/compute",
                          json=self._body(WATER_A, INLAND), headers=_auth(token))
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] in ("end_blocked", "no_route")

    def test_out_of_coverage_422(self, token):
        r = requests.post(f"{BASE_URL}/api/routes/compute",
                          json=self._body(WATER_A, OUT), headers=_auth(token))
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "out_of_coverage"

    def test_deep_draft_still_routes_or_fails_cleanly(self, token):
        r = requests.post(
            f"{BASE_URL}/api/routes/compute",
            json=self._body(WATER_A, WATER_B, draft_m=4, depth_margin_m=3, lateral_margin_m=200),
            headers=_auth(token),
        )
        assert r.status_code in (200, 422), r.text
        if r.status_code == 200:
            d = r.json()
            assert d["min_depth_m"] >= d["threshold_m"]
        else:
            assert r.json()["detail"]["code"] in ("no_route", "start_blocked", "end_blocked")
