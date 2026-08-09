"""iter111 (25/07/2026) — Règle 150% + safety_extra_m regen + régression.

Bugs vidéo armateur : la « route dangereuse » doit renvoyer low_margin quand
la hauteur d'eau minimale du profil (fond + marée) < 1.5 × (draft + margin).
Un rappel avec safety_extra_m: 2 doit soit renvoyer une route sans low_margin
(marge augmentée), soit un 422 propre si impossible.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "EXPO_(PUBLIC_)BACKEND_URL must be set"


def _mint_token() -> str:
    out = subprocess.check_output(
        [
            "python3",
            "-c",
            "import sys; sys.path.insert(0,'.'); from dotenv import load_dotenv; "
            "load_dotenv(); from core.auth import make_jwt; "
            "print(make_jwt('user_0b6070a69154'))",
        ],
        cwd="/app/backend",
        text=True,
    ).strip()
    return out


@pytest.fixture(scope="module")
def api():
    token = _mint_token()
    s = requests.Session()
    s.headers.update(
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60",
        }
    )
    return s


# ── Règle des 150% : LOW_MARGIN ──────────────────────────────────────────
class TestLowMarginRule:
    """POST /api/routes/compute doit renvoyer 'low_margin' quand min_h < 1.5 × req."""

    payload_shallow = {
        "start": {"lat": 47.610, "lng": -2.825},
        "end": {"lat": 47.55, "lng": -2.75},
        "draft_m": 3.5,
        "depth_margin_m": 1.5,
    }

    def test_low_margin_present_when_tight(self, api):
        r = api.post(f"{BASE_URL}/api/routes/compute", json=self.payload_shallow)
        # 2 cas légitimes :
        # - 200 avec low_margin : la route existe mais est à faible marge.
        # - 422 no_route : profondeur totalement insuffisante (draft+margin=5m
        #   dans le Morbihan → très plausible). Dans ce cas on ne peut pas
        #   tester low_margin, on saute.
        if r.status_code == 422:
            body = r.json().get("detail", {})
            pytest.skip(
                f"Route impossible avec draft+margin=5m (code={body.get('code')}) "
                "→ on ne peut pas déclencher low_margin. Test skippé."
            )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "low_margin" in data, (
            f"low_margin ABSENT alors que draft+margin={self.payload_shallow['draft_m']+self.payload_shallow['depth_margin_m']}m. "
            f"depth_profile min={min([p.get('depth_m',999) for p in data.get('depth_profile',[])],default='n/a')}. "
            f"Réponse: {data.get('warnings',[])[:2]}"
        )
        lm = data["low_margin"]
        assert set(lm.keys()) >= {"min_height_m", "required_m", "alert_at_m", "safe_extra_m"}
        assert lm["safe_extra_m"] == 2.0
        assert lm["required_m"] == pytest.approx(5.0, abs=0.01)
        assert lm["alert_at_m"] == pytest.approx(7.5, abs=0.01)
        assert lm["min_height_m"] < lm["alert_at_m"]

    def test_safety_extra_removes_low_margin_or_422(self, api):
        """safety_extra_m: 2 → soit route ré-calculée SANS low_margin, soit 422 propre."""
        payload = {**self.payload_shallow, "safety_extra_m": 2}
        r = api.post(f"{BASE_URL}/api/routes/compute", json=payload)
        if r.status_code == 422:
            body = r.json()
            assert "detail" in body
            detail = body["detail"]
            assert "code" in detail
            # Message doit être propre (non trace/500)
            assert "message" in detail
            return
        assert r.status_code == 200, r.text
        data = r.json()
        assert "low_margin" not in data, (
            f"low_margin PRÉSENT après safety_extra_m: 2 : {data.get('low_margin')}"
        )

    def test_comfortable_route_no_low_margin(self, api):
        """Bateau petit + eaux profondes → PAS de low_margin."""
        payload = {
            "start": {"lat": 47.55, "lng": -3.10},
            "end": {"lat": 47.48, "lng": -3.15},
            "draft_m": 0.5,
            "depth_margin_m": 0.3,
        }
        r = api.post(f"{BASE_URL}/api/routes/compute", json=payload)
        if r.status_code == 422:
            pytest.skip(f"Route impossible ({r.json()}). Test skippé.")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "low_margin" not in data, (
            f"low_margin ne devrait PAS être présent sur route confortable. "
            f"Got: {data['low_margin']}"
        )


# ── Régression backend : nominal + manual + saved CRUD + bathy + 422 ──
class TestRegression:
    def test_compute_nominal_no_low_margin(self, api):
        """Route standard Arradon → Ile aux Moines, draft normal."""
        r = api.post(
            f"{BASE_URL}/api/routes/compute",
            json={
                "start": {"lat": 47.610, "lng": -2.825},
                "end": {"lat": 47.585, "lng": -2.85},
                "draft_m": 1.2,
                "depth_margin_m": 0.5,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "waypoints" in data and len(data["waypoints"]) >= 2
        assert "distance_m" in data and data["distance_m"] > 0

    def test_routes_manual(self, api):
        r = api.post(
            f"{BASE_URL}/api/routes/manual",
            json={
                "waypoints": [
                    {"lat": 47.610, "lng": -2.825},
                    {"lat": 47.60, "lng": -2.83},
                    {"lat": 47.58, "lng": -2.85},
                ],
                "draft_m": 1.2,
                "depth_margin_m": 0.5,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "distance_m" in data
        assert "depth_profile" in data

    def test_saved_routes_crud(self, api):
        # Create
        payload = {
            "name": "TEST_iter111",
            "mode": "manual",
            "waypoints": [
                {"lat": 47.610, "lng": -2.825},
                {"lat": 47.60, "lng": -2.83},
            ],
            "distance_m": 500.0,
        }
        rc = api.post(f"{BASE_URL}/api/routes/saved", json=payload)
        assert rc.status_code == 200, rc.text
        rid = rc.json()["id"]

        # List
        rl = api.get(f"{BASE_URL}/api/routes/saved")
        assert rl.status_code == 200
        ids = [r["id"] for r in rl.json()["routes"]]
        assert rid in ids

        # Delete
        rd = api.delete(f"{BASE_URL}/api/routes/saved/{rid}")
        assert rd.status_code == 200
        assert rd.json().get("ok") is True

        # Verify deletion
        rl2 = api.get(f"{BASE_URL}/api/routes/saved")
        ids2 = [r["id"] for r in rl2.json()["routes"]]
        assert rid not in ids2

    def test_bathy_depth(self, api):
        r = api.get(
            f"{BASE_URL}/api/bathy/depth",
            params={"lat": 47.51, "lng": -2.95},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("covered") is True
        # water or land, both accepted; just structure check
        assert "depth_zh_m" in d

    def test_fallback_422_dest_far_inland(self, api):
        """Destination à terre très éloignée → 422 propre."""
        r = api.post(
            f"{BASE_URL}/api/routes/compute",
            json={
                "start": {"lat": 47.610, "lng": -2.825},
                "end": {"lat": 47.65, "lng": -2.60},  # inland Vannes
                "draft_m": 1.2,
                "depth_margin_m": 0.5,
            },
        )
        # Accept 200 with warnings OR 422
        assert r.status_code in (200, 422), r.text
        if r.status_code == 422:
            body = r.json()
            assert "detail" in body
            assert "code" in body["detail"]
