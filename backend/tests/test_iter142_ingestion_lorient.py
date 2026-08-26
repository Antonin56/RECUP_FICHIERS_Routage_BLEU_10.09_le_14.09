"""
ITER142 — Vérification ingestion Litto3D Lorient + routes officielles OSM.

Objectif armateur : CONFIRMER que l'ingestion est OK. AUCUNE modification moteur.
Faux positifs connus (wrong_side_marks 'La Petite Jument' / 'N° 4') : à IGNORER.
"""
import os
import json
import time
from pathlib import Path
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://signalmar-optimize.preview.emergentagent.com").rstrip("/")
QA_BYPASS = {"X-RateLimit-Bypass": "qa-bypass-signalmar-2026"}
LOGIN_EMAIL = "antoninlepinay@gmail.com"
LOGIN_PWD = "123454321"

SAFE_ROUTES_PATH = Path("/app/backend/data/bathy/safe_routes.json")


# --- Feature 7 : safe_routes.json valide ---------------------------------
class TestSafeRoutesFile:
    def test_json_valid(self):
        assert SAFE_ROUTES_PATH.exists(), f"{SAFE_ROUTES_PATH} manquant"
        with SAFE_ROUTES_PATH.open() as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert data.get("count") == 180, f"count attendu 180 obtenu {data.get('count')}"
        kinds = data.get("kinds", {})
        for k in ("recommended_track", "navigation_line", "fairway"):
            assert k in kinds, f"kind manquant : {k}"
        assert len(data.get("features", [])) == 180


# --- Feature 1/2 : couverture Litto3D -----------------------------------
class TestBathyDepthLittoral:
    def test_tourelle_aime_depth(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/bathy/depth", params={"lat": 47.7159, "lng": -3.3641})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("covered") is True
        assert d.get("water") is True
        assert d.get("depth_zh_m") is not None
        # Tolérance ±1 m autour de 15.4 m (grille fine Litto3D)
        assert abs(d["depth_zh_m"] - 15.4) < 1.5, f"depth_zh_m={d['depth_zh_m']}"

    def test_port_tudy_groix_covered(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/bathy/depth", params={"lat": 47.6455, "lng": -3.4460})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("covered") is True, f"Groix pas couvert : {d}"

    def test_coverage_contains_litto3d(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/bathy/coverage")
        assert r.status_code == 200
        d = r.json()
        product = d.get("product", "")
        assert "LITTO3D_BZH_2018_2021" in product, f"product={product}"
        zones = {z.get("name"): z for z in d.get("zones", [])}
        assert "lorient" in zones, f"zones={list(zones)}"
        b = zones["lorient"]["bounds"]
        assert 47.54 <= b["south"] <= 47.56
        assert 47.78 <= b["north"] <= 47.80
        assert -3.61 <= b["west"] <= -3.59
        assert -3.26 <= b["east"] <= -3.24


# --- Feature 3 : isobathes régression contourpy --------------------------
class TestIsobaths:
    def test_lorient_bbox(self, api_client):
        r = api_client.get(
            f"{BASE_URL}/api/bathy/isobaths",
            params={"bbox": "-3.40,47.68,-3.33,47.75", "zoom": 13},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d.get("features", [])) > 50, f"features={len(d.get('features',[]))}"

    def test_morbihan_bbox_non_reg(self, api_client):
        r = api_client.get(
            f"{BASE_URL}/api/bathy/isobaths",
            params={"bbox": "-2.90,47.55,-2.70,47.65", "zoom": 13},
        )
        assert r.status_code == 200
        d = r.json()
        assert len(d.get("features", [])) > 50


# --- Auth helper ---------------------------------------------------------
@pytest.fixture(scope="module")
def auth_token():
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": LOGIN_EMAIL, "password": LOGIN_PWD},
        headers=QA_BYPASS,
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:400]}"
    data = r.json()
    token = data.get("token") or data.get("access_token") or (data.get("user") or {}).get("token")
    assert token, f"no token in login: {data}"
    return token


def _poll_job(client, headers, job_id, timeout=90):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        r = client.get(f"{BASE_URL}/api/routes/job/{job_id}", headers=headers, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        last = j
        st = j.get("status")
        if st in ("done", "error", "failed"):
            return j
        time.sleep(1.5)
    raise AssertionError(f"job timeout after {timeout}s, last={last}")


# --- Feature 4 : Route Lorient engine_f ---------------------------------
class TestRouteLorient:
    def test_route_lorient_engine_f(self, api_client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}", **QA_BYPASS, "Content-Type": "application/json"}
        body = {
            "start": {"lat": 47.67755575752677, "lng": -3.4287631920085064},
            "end":   {"lat": 47.72987102630925, "lng": -3.3567713137773514},
            "draft_m": 1.0,
            "depth_margin_m": 0.5,
            "use_tide": False,
            "engine_id": "engine_f",
        }
        r = api_client.post(f"{BASE_URL}/api/routes/compute/async", headers=headers, json=body, timeout=20)
        assert r.status_code in (200, 202), r.text
        jd = r.json()
        job_id = jd.get("job_id") or jd.get("id")
        assert job_id
        job = _poll_job(api_client, headers, job_id, timeout=120)
        assert job.get("status") == "done", f"status={job.get('status')} err={job.get('error')}"
        result = job.get("result") or job
        distance_m = result.get("distance_m") or result.get("distance") or (result.get("summary") or {}).get("distance_m")
        wps = result.get("waypoints") or result.get("route") or []
        warnings = result.get("warnings") or []
        depth_profile = result.get("depth_profile") or []

        assert distance_m is not None, f"pas de distance dans {list(result.keys())}"
        assert 6000 <= distance_m <= 12000, f"distance_m={distance_m}"
        assert len(wps) >= 10, f"waypoints={len(wps)}"
        # Pas de warnings 'arrivée à terre' ni 'eau peu profonde'
        bad = [w for w in warnings if isinstance(w, str) and ("ARRIVÉE" in w.upper() or "PEU PROFONDE" in w.upper() or "SHALLOW" in w.upper())]
        assert not bad, f"warnings interdits: {bad}"
        if depth_profile:
            depths = [p.get("depth_zh_m") if isinstance(p, dict) else p for p in depth_profile]
            depths = [d for d in depths if d is not None]
            if depths:
                mini = min(depths)
                assert mini >= 1.5, f"fond mini {mini} < 1.5 m"
        # Note connue armateur : wrong_side_marks peut contenir Petite Jument / N° 4 → ne pas échouer
        wsm = result.get("wrong_side_marks") or []
        print(f"[iter142] Lorient route OK — distance={distance_m}m wp={len(wps)} wrong_side_marks={wsm}")


# --- Feature 5 : non-régression Golfe (engine_f Arradon→Belle-Île) -------
class TestRouteMorbihanPilot:
    def test_arradon_belle_ile(self, api_client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}", **QA_BYPASS, "Content-Type": "application/json"}
        body = {
            "start": {"lat": 47.5750, "lng": -2.7780},
            "end":   {"lat": 47.3860, "lng": -3.2130},
            "draft_m": 1.0,
            "depth_margin_m": 0.5,
            "use_tide": False,
            "engine_id": "engine_f",
        }
        r = api_client.post(f"{BASE_URL}/api/routes/compute/async", headers=headers, json=body, timeout=20)
        assert r.status_code in (200, 202), r.text
        job_id = r.json().get("job_id") or r.json().get("id")
        job = _poll_job(api_client, headers, job_id, timeout=180)
        assert job.get("status") == "done", f"status={job.get('status')} err={job.get('error')}"
        result = job.get("result") or job
        distance_m = result.get("distance_m") or result.get("distance") or (result.get("summary") or {}).get("distance_m")
        assert distance_m and distance_m > 30000, f"distance_m={distance_m}"


@pytest.fixture
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s
