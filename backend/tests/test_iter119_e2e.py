"""
Iter119 e2e tests — hard constraints (gate walls, beacon 15m standoff),
tide/routing decoupling (ZH first, tide fallback only if truncated), marine
farms respected, water depth on tap, saved routes CRUD non-regression.
"""
import json
import math
import os
import sys
import time

import pytest
import requests

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
from core.auth import make_jwt  # noqa: E402

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")

TOKEN = make_jwt("user_0b6070a69154")
HEADERS = {"Authorization": f"Bearer {TOKEN}",
           "Content-Type": "application/json",
           "X-RateLimit-Bypass": os.environ.get("RATE_LIMIT_BYPASS_TOKEN", "qa-bypass-7f3d9a2e4c8b1f60")}

# Known beacons in Golfe du Morbihan
BEACONS = {
    "No6": (47.6281487, -2.7625103),
    "No8": (47.6294199, -2.7620161),
    "Holavre": (47.6082986, -2.8312696),
}

# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------

def _hav(lat1, lng1, lat2, lng2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def _sample_segments(wps, step_m=10.0):
    pts = []
    for i in range(len(wps)-1):
        a, b = wps[i], wps[i+1]
        d = _hav(a["lat"], a["lng"], b["lat"], b["lng"])
        n = max(1, int(d/step_m))
        for k in range(n+1):
            t = k/max(1, n)
            pts.append((a["lat"] + (b["lat"]-a["lat"])*t,
                        a["lng"] + (b["lng"]-a["lng"])*t))
    return pts


def _min_dist_to_point(samples, lat, lng):
    return min(_hav(p[0], p[1], lat, lng) for p in samples)


def _point_in_ring(lat, lng, ring):
    # ring: [[lng,lat], ...] (GeoJSON)
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi + 1e-18) + xi):
            inside = not inside
        j = i
    return inside


def _load_farms():
    """Returns list of exterior rings as [[lng, lat], ...] for point-in-poly checks.
    File format: {"farms": [{"poly": [[lat, lng], ...]}, ...]}"""
    path = "/app/backend/data/bathy/marine_farms.json"
    if not os.path.exists(path):
        return []
    with open(path) as f:
        gj = json.load(f)
    rings = []
    for farm in gj.get("farms", []):
        poly = farm.get("poly") or []
        if len(poly) >= 3:
            # convert [lat,lng] → [lng,lat] to match _point_in_ring expectation
            rings.append([[p[1], p[0]] for p in poly])
    return rings


# -----------------------------------------------------------------------------
# BACKEND P0/P1 tests
# -----------------------------------------------------------------------------

class TestIter119Routing:

    def test_p0_deep_water_route_uses_zh_and_low_tide_warning(self):
        """P0: eau profonde → route calculée à ZH (tide_m=0.0), warning MARÉE BASSE."""
        t0 = time.time()
        r = requests.post(f"{BASE_URL}/api/routes/compute", json={
            "start": {"lat": 47.610, "lng": -2.825},
            "end": {"lat": 47.595, "lng": -2.851},
            "draft_m": 1.5, "depth_margin_m": 0.5, "use_tide": True,
        }, headers=HEADERS, timeout=180)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
        j = r.json()
        assert j.get("tide_m") == 0.0, f"tide_m expected 0.0 (ZH route), got {j.get('tide_m')}"
        assert j.get("threshold_m") == 2.0, f"threshold expected 2.0 (draft+marge), got {j.get('threshold_m')}"
        # 29/07 (routage 100 % ZH, marée désactivée) — plus d'avertissement
        # « marée basse / +30 min » : la route est TOUJOURS au ZH.
        assert elapsed < 30, f"compute too slow: {elapsed:.1f}s"
        print(f"deep_route OK tide={j.get('tide_m')} thr={j.get('threshold_m')} {elapsed:.1f}s")

    def test_p0_vannes_route_avoids_beacons_15m(self):
        """P0: Golfe→Vannes, la route ne passe pas à moins de 15 m des balises No6/No8/Holavre."""
        r = requests.post(f"{BASE_URL}/api/routes/compute", json={
            "start": {"lat": 47.554, "lng": -2.905},
            "end": {"lat": 47.6553, "lng": -2.7594},
            "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": True,
        }, headers=HEADERS, timeout=300)
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
        j = r.json()
        assert j.get("end_snapped") is not None, "end_snapped expected (arrival displaced)"
        wps = j.get("waypoints") or []
        assert len(wps) >= 2, f"no waypoints: {wps}"
        samples = _sample_segments(wps, step_m=10.0)
        dists = {}
        for name, (blat, blng) in BEACONS.items():
            d = _min_dist_to_point(samples, blat, blng)
            dists[name] = d
        print("beacon distances:", dists)
        for name, d in dists.items():
            assert d >= 15.0, f"route passes {d:.1f}m from beacon {name} (<15m)"
        # keep for next test
        pytest.vannes_waypoints = wps
        pytest.vannes_samples = samples

    def test_p0_vannes_route_avoids_marine_farms(self):
        """P0: la route Golfe→Vannes ne traverse aucun parc de culture marine."""
        samples = getattr(pytest, "vannes_samples", None)
        if samples is None:
            r = requests.post(f"{BASE_URL}/api/routes/compute", json={
                "start": {"lat": 47.554, "lng": -2.905},
                "end": {"lat": 47.6553, "lng": -2.7594},
                "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": True,
            }, headers=HEADERS, timeout=300)
            assert r.status_code == 200
            j = r.json()
            wps = j.get("waypoints") or []
            samples = _sample_segments(wps, 10.0)
        polys = _load_farms()
        if not polys:
            pytest.skip("no marine_farms.json data")
        hits = 0
        for (plat, plng) in samples:
            for outer in polys:
                if _point_in_ring(plat, plng, outer):
                    hits += 1
                    break
        assert hits == 0, f"route crosses {hits} marine farm samples"
        print(f"marine_farms OK — 0/{len(samples)} sample crossings, {len(polys)} farms checked")

    def test_p1_no_tide_flag_works(self):
        """P1: use_tide=false → threshold = draft + marge (comportement historique)."""
        r = requests.post(f"{BASE_URL}/api/routes/compute", json={
            "start": {"lat": 47.610, "lng": -2.825},
            "end": {"lat": 47.595, "lng": -2.851},
            "draft_m": 1.5, "depth_margin_m": 0.5, "use_tide": False,
        }, headers=HEADERS, timeout=180)
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
        j = r.json()
        assert j.get("threshold_m") == pytest.approx(2.0, abs=0.01), \
            f"threshold expected 2.0, got {j.get('threshold_m')}"

    def test_p1_manual_route(self):
        r = requests.post(f"{BASE_URL}/api/routes/manual", json={
            "waypoints": [{"lat": 47.610, "lng": -2.825}, {"lat": 47.595, "lng": -2.851}],
            "draft_m": 1.5, "depth_margin_m": 0.5, "use_tide": True,
        }, headers=HEADERS, timeout=120)
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
        j = r.json()
        assert "depth_profile" in j and isinstance(j["depth_profile"], list)
        assert "corridor_m" in j
        assert "warnings" in j

    def test_p1_bathy_depth_water_and_land(self):
        r = requests.get(f"{BASE_URL}/api/bathy/depth?lat=47.60&lng=-2.83",
                         headers=HEADERS, timeout=10)
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
        j = r.json()
        assert "depth_zh_m" in j, f"missing depth_zh_m: {j}"

        r2 = requests.get(f"{BASE_URL}/api/bathy/depth?lat=47.66&lng=-2.76",
                          headers=HEADERS, timeout=10)
        assert r2.status_code == 200
        j2 = r2.json()
        # allow either water=false or a defined 'covered' flag
        assert (j2.get("water") is False) or ("covered" in j2), f"land point should be flagged: {j2}"


class TestIter119SavedRoutes:

    saved_id = None

    def test_p2_saved_routes_crud(self):
        # CREATE
        payload = {
            "name": "TEST_iter119_route",
            "waypoints": [{"lat": 47.610, "lng": -2.825},
                          {"lat": 47.595, "lng": -2.851}],
            "draft_m": 1.5, "depth_margin_m": 0.5,
        }
        r = requests.post(f"{BASE_URL}/api/routes/saved", json=payload,
                          headers=HEADERS, timeout=30)
        assert r.status_code in (200, 201), f"create HTTP {r.status_code}: {r.text[:300]}"
        j = r.json()
        rid = j.get("id") or j.get("_id") or j.get("route_id")
        assert rid, f"missing id in create response: {j}"
        TestIter119SavedRoutes.saved_id = rid

        # LIST
        r2 = requests.get(f"{BASE_URL}/api/routes/saved", headers=HEADERS, timeout=30)
        assert r2.status_code == 200
        items = r2.json()
        # some APIs wrap under 'items' or similar
        arr = items if isinstance(items, list) else items.get("items") or items.get("routes") or []
        assert any((x.get("id") or x.get("_id")) == rid for x in arr), \
            f"created id {rid} not in list"

        # DELETE
        r3 = requests.delete(f"{BASE_URL}/api/routes/saved/{rid}",
                             headers=HEADERS, timeout=30)
        assert r3.status_code in (200, 204), f"delete HTTP {r3.status_code}: {r3.text[:300]}"


class TestIter119NonRegression:

    def test_bathy_coverage(self):
        r = requests.get(f"{BASE_URL}/api/bathy/coverage", headers=HEADERS, timeout=10)
        assert r.status_code == 200

    def test_bathy_seamarks(self):
        r = requests.get(f"{BASE_URL}/api/bathy/seamarks?bbox=-2.78,47.61,-2.75,47.64",
                         headers=HEADERS, timeout=15)
        assert r.status_code == 200
        j = r.json()
        marks = j if isinstance(j, list) else j.get("marks") or j.get("features") or []
        assert len(marks) > 0, f"no seamarks returned: {j}"
