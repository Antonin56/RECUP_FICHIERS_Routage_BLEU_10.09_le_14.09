"""SignalMar — iter100 (23/07/2026) tests backend :
- Proxy-cache de tuiles SHOM & Seamark (routers/tiles.py)
- Non-régression /api/routes/compute (corridor_m par segment, depth_profile)

OTP dev-bypass Aslak 0766071445 pour /routes/compute (nécessite un token).
"""
from __future__ import annotations

import os
import time

import pytest
import requests


BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://nav-routing-speed.preview.emergentagent.com"

QA_HEADER = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
PHONE = "0766071445"


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", **QA_HEADER})
    return s


@pytest.fixture(scope="module")
def token(api):
    api.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": PHONE})
    time.sleep(0.4)
    r = api.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"phone": PHONE, "code": "123456"},
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


# --- SHOM proxy-cache tests ---------------------------------------------
class TestShomTiles:
    def test_shom_morbihan_ok_png(self, api):
        url = f"{BASE_URL}/api/tiles/shom/morbihan/13/4028/2862.png"
        r = api.get(url)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/png")
        # Real tile > 5 KB (transparent placeholder is < 200 bytes)
        assert len(r.content) > 5_000, f"Tile too small: {len(r.content)}"
        # NB: Cache-Control est réécrit par l'ingress Cloudflare (no-store) —
        # le routeur backend renvoie bien 'public, max-age=…, immutable' mais
        # l'ingress force no-store. À signaler infra si on veut réactiver le
        # cache navigateur, mais le cache DISQUE côté backend (le vrai but)
        # fonctionne — vérifié par le 2e appel < 1.5 s.

    def test_shom_second_call_cached_fast(self, api):
        url = f"{BASE_URL}/api/tiles/shom/morbihan/13/4028/2862.png"
        t0 = time.time()
        r = api.get(url)
        dt = time.time() - t0
        assert r.status_code == 200
        assert len(r.content) > 5_000
        # After first fetch, cache disk read should be << 1 s
        assert dt < 1.5, f"Cached call too slow: {dt:.2f}s"

    def test_shom_atl_ok(self, api):
        # zoom/x/y valides pour la couche Atlantique large
        r = api.get(f"{BASE_URL}/api/tiles/shom/atl/8/125/91.png")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/png")

    def test_shom_unknown_key_404(self, api):
        r = api.get(f"{BASE_URL}/api/tiles/shom/pacific/13/4028/2862.png")
        assert r.status_code == 404

    def test_shom_zoom_out_of_range_422(self, api):
        # ge=3, le=19 → z=2 refusé
        r = api.get(f"{BASE_URL}/api/tiles/shom/morbihan/2/1/1.png")
        assert r.status_code == 422


# --- Seamark proxy-cache tests ------------------------------------------
class TestSeamarkTiles:
    def test_seamark_ok_png(self, api):
        url = f"{BASE_URL}/api/tiles/seamark/13/4028/2862.png"
        r = api.get(url)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/png")
        # Peut être vide (tuile transparente 1×1 si pas de balisage) → juste vérifier le type

    def test_seamark_zoom_out_of_range_422(self, api):
        # ge=3, le=18
        r = api.get(f"{BASE_URL}/api/tiles/seamark/2/0/0.png")
        assert r.status_code == 422


# --- Non-regression routing (corridor_m per segment) --------------------
class TestRoutingCorridor:
    def test_route_compute_returns_corridor_per_segment(self, api, token):
        api.headers.update({"Authorization": f"Bearer {token}"})
        payload = {
            "start": {"lat": 47.554, "lng": -2.951},
            "end": {"lat": 47.51, "lng": -2.93},
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "lateral_margin_m": 10,
        }
        r = api.post(f"{BASE_URL}/api/routes/compute", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "waypoints" in data and len(data["waypoints"]) >= 2
        assert "distance_m" in data and data["distance_m"] > 0
        assert "corridor_m" in data
        # Le lot armateur d'iter100 : corridor_m est une LISTE par segment
        assert isinstance(data["corridor_m"], list), (
            f"corridor_m devrait être une liste par segment, got {type(data['corridor_m'])}"
        )
        assert len(data["corridor_m"]) == max(1, len(data["waypoints"]) - 1)
        for c in data["corridor_m"]:
            assert isinstance(c, (int, float)) and c > 0
        assert "depth_profile" in data
        assert isinstance(data["depth_profile"], list) and len(data["depth_profile"]) > 0
