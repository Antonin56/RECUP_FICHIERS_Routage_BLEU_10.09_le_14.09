"""iter110 — Backend regression tests (24/07/2026 armateur bundle).

Coverage:
- P0 — GET /api/bathy/depth (water true / false / uncovered)
- P0 — POST /api/routes/compute → 422 with detail.fallback_route (waypoints + compromised_from)
- P0 — POST /api/routes/manual across land → compromised_legs + warning
- P0 — POST /api/reports meteo/orage_proche (no drift_cone), obstacle_nav/embarcation_derive (drift_cone)
"""
from __future__ import annotations

import os
import sys

import pytest
import requests

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/app/backend/.env")
from core.auth import make_jwt  # noqa: E402

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
QA = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
ADMIN_USER_ID = "user_0b6070a69154"


@pytest.fixture(scope="module")
def token() -> str:
    return make_jwt(ADMIN_USER_ID)


@pytest.fixture
def auth(token):
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        **QA,
    })
    return s


# ── /api/bathy/depth ──────────────────────────────────────────────────────
class TestBathyDepth:
    def test_depth_at_water_point(self):
        # Public endpoint — Golfe du Morbihan, open water.
        r = requests.get(
            f"{BASE_URL}/api/bathy/depth",
            params={"lat": 47.51, "lng": -2.95}, timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("covered") is True, d
        assert d.get("water") is True, d
        assert d.get("depth_zh_m") is not None
        assert d["depth_zh_m"] > 0, f"depth_zh_m expected > 0, got {d.get('depth_zh_m')}"
        # tide/height_now optional but if present must be coherent.
        if "tide_m" in d and "height_now_m" in d:
            expected = round(d["depth_zh_m"] + d["tide_m"], 1)
            assert abs(d["height_now_m"] - expected) <= 0.11, d

    def test_depth_on_land(self):
        # Land near Sarzeau/Vannes — should still be covered but water=false.
        r = requests.get(
            f"{BASE_URL}/api/bathy/depth",
            params={"lat": 47.55, "lng": -2.88}, timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        # If covered by MNT, must report water:false.
        # Some coastal cells may still be "water:true" if the MNT overlaps —
        # but per spec (49-73 line bathy.py), d < -7m → water:false.
        if d.get("covered") is True:
            assert d.get("water") is False, f"expected water:false on land, got {d}"

    def test_depth_out_of_coverage(self):
        r = requests.get(
            f"{BASE_URL}/api/bathy/depth",
            params={"lat": 49.5, "lng": 0.0}, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"covered": False}


# ── /api/routes/compute — impossible route → fallback ─────────────────────
class TestComputeFallback:
    def test_no_route_returns_fallback(self, auth):
        """29/07 (façon Navionics) — plus de 422+fallback_route quand les
        fonds ne suffisent pas : la route est TRACÉE en mode « eau peu
        profonde » (200, tronçons rouges + risk)."""
        body = {
            "start": {"lat": 47.554, "lng": -2.876},
            "end": {"lat": 47.63, "lng": -2.73},
            "draft_m": 3.8,
            "depth_margin_m": 2.5,
        }
        r = auth.post(f"{BASE_URL}/api/routes/compute", json=body, timeout=120)
        assert r.status_code == 200, (r.status_code, r.text[:400])
        d = r.json()
        assert d.get("shallow_route") is True and d.get("risk") is True
        assert d.get("compromised_legs"), "tronçons rouges attendus (fond < 6,3 m requis)"
        assert len(d["waypoints"]) >= 3
        warns = " | ".join(d.get("warnings") or [])
        assert "EAU PEU PROFONDE" in warns.upper()


# ── /api/routes/manual — waypoints across land → compromised_legs ─────────
class TestManualCompromised:
    def test_manual_across_island(self, auth):
        body = {
            "waypoints": [
                {"lat": 47.62, "lng": -2.87},
                {"lat": 47.585, "lng": -2.845},  # Île aux Moines
                {"lat": 47.55, "lng": -2.82},
            ],
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
        }
        r = auth.post(f"{BASE_URL}/api/routes/manual", json=body, timeout=60)
        assert r.status_code == 200, (r.status_code, r.text[:400])
        d = r.json()
        assert d.get("compromised_legs"), f"compromised_legs empty: {d}"
        warnings = d.get("warnings", [])
        assert any("ROUGE" in w or "rouge" in w for w in warnings), (
            f"missing 'EN ROUGE' warning: warnings={warnings}")


# ── /api/reports — meteo (no drift), obstacle_nav embarcation (drift) ─────
class TestNewReportTypes:
    def _create(self, auth, payload):
        r = auth.post(f"{BASE_URL}/api/reports", json=payload, timeout=30)
        return r

    def _delete(self, auth, rid):
        try:
            auth.delete(f"{BASE_URL}/api/reports/{rid}", timeout=15)
        except Exception:  # noqa: BLE001
            pass

    def test_meteo_orage_proche_no_drift(self, auth):
        payload = {
            "type": "meteo",
            "subtype": "orage_proche",
            "lat": 47.61,
            "lng": -2.83,
            "description": "TEST_iter110 orage proche",
        }
        r = self._create(auth, payload)
        assert r.status_code in (200, 201), (r.status_code, r.text[:400])
        d = r.json()
        rid = d.get("id") or d.get("report", {}).get("id")
        try:
            assert d.get("type") == "meteo" or d.get("report", {}).get("type") == "meteo", d
            drift = d.get("drift_cone") or d.get("report", {}).get("drift_cone")
            assert not drift, f"drift_cone should be absent/empty for meteo, got {drift}"
        finally:
            if rid:
                self._delete(auth, rid)

    def test_embarcation_derive_has_drift(self, auth):
        payload = {
            "type": "obstacle_nav",
            "subtype": "embarcation_derive",
            "lat": 47.61,
            "lng": -2.83,
            "description": "TEST_iter110 embarcation derive",
        }
        r = self._create(auth, payload)
        assert r.status_code in (200, 201), (r.status_code, r.text[:400])
        d = r.json()
        report = d.get("report", d)
        rid = report.get("id")
        try:
            drift = report.get("drift_cone")
            assert drift, f"drift_cone should be present for embarcation_derive, got {report}"
        finally:
            if rid:
                self._delete(auth, rid)
