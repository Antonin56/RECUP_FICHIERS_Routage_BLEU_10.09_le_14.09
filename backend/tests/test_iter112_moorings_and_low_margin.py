"""iter112 (26/07/2026) — Mooring avoidance + moorings in /bathy/seamarks + low_margin on manual routes."""
from __future__ import annotations

import math
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
            "X-RateLimit-Bypass": os.environ.get("RATE_LIMIT_BYPASS_TOKEN", ""),
        }
    )
    return s


def _haversine_m(lat1, lng1, lat2, lng2):
    R = 6371000.0
    p1 = math.radians(lat1); p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _min_dist_polyline_to_point(wps, plat, plng):
    """Approximate min distance (m) from route polyline vertices to a point."""
    dmin = float("inf")
    for w in wps:
        d = _haversine_m(w["lat"], w["lng"], plat, plng)
        if d < dmin:
            dmin = d
    return dmin


class TestMooringsSeamarks:
    """Point 2: /api/bathy/seamarks must include mooring objects."""

    def test_seamarks_includes_moorings(self, api):
        r = api.get(
            f"{BASE_URL}/api/bathy/seamarks",
            params={"bbox": "-2.93,47.54,-2.90,47.56"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "marks" in data
        kinds = {m.get("kind") for m in data["marks"]}
        assert "mooring" in kinds, (
            f"Aucun objet kind='mooring' dans la réponse. Kinds trouvés: {kinds}. "
            f"N marks total: {len(data['marks'])}"
        )
        moorings = [m for m in data["marks"] if m.get("kind") == "mooring"]
        assert len(moorings) > 0
        # Vérifier structure minimale
        m0 = moorings[0]
        assert "id" in m0 and "lat" in m0 and "lng" in m0


class TestMooringAvoidance:
    """Point 1: le routage doit contourner les bouées de mouillage (>45 m)."""

    def test_route_avoids_moorings_cluster(self, api):
        """Route qui devrait contourner le cluster ~47.5487,-2.914."""
        r = api.post(
            f"{BASE_URL}/api/routes/compute",
            json={
                "start": {"lat": 47.556, "lng": -2.917},
                "end": {"lat": 47.541, "lng": -2.909},
                "draft_m": 1.2,
                "depth_margin_m": 0.5,
                "use_tide": False,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        wps = data.get("waypoints", [])
        assert len(wps) >= 2

        # Charger les moorings du cluster
        import json as _json
        mo_all = _json.load(open("/app/backend/data/bathy/moorings.json"))["moorings"]
        cluster = [
            m for m in mo_all
            if 47.545 <= m["lat"] <= 47.552 and -2.917 <= m["lng"] <= -2.910
        ]
        assert len(cluster) > 10, f"Cluster inattendu: {len(cluster)} bouées"

        # Pour chaque bouée du cluster, distance min du tracé > 45 m ?
        # Note: la route ne DOIT PAS s'approcher à <45m d'aucune mooring
        # (sauf exemption 400m autour du départ/arrivée).
        min_by_mooring = []
        for m in cluster:
            d = _min_dist_polyline_to_point(wps, m["lat"], m["lng"])
            # Exemption 400m autour du départ ET de l'arrivée
            d_start = _haversine_m(47.556, -2.917, m["lat"], m["lng"])
            d_end = _haversine_m(47.541, -2.909, m["lat"], m["lng"])
            if d_start < 400 or d_end < 400:
                continue
            min_by_mooring.append((m["id"], d))

        if min_by_mooring:
            worst = min(min_by_mooring, key=lambda x: x[1])
            assert worst[1] >= 45.0, (
                f"Bouée {worst[0]} à seulement {worst[1]:.1f} m du tracé "
                f"(exemption 400m start/end appliquée)."
            )

        # La route ne doit PAS être flaggée through_moorings pour ce cas
        # (destination hors cluster).
        assert not data.get("through_moorings"), (
            "Route flaggée through_moorings alors que la destination est hors cluster."
        )

    def test_route_into_mooring_field_allowed(self, api):
        """Destination DANS le cluster → autorisée (exemption 400m destination)."""
        r = api.post(
            f"{BASE_URL}/api/routes/compute",
            json={
                "start": {"lat": 47.556, "lng": -2.917},
                "end": {"lat": 47.5495, "lng": -2.913},
                "draft_m": 1.2,
                "depth_margin_m": 0.5,
                "use_tide": False,
            },
        )
        # Doit renvoyer 200 (accès autorisé via exemption 400m)
        assert r.status_code == 200, (
            f"Accès à un point dans le champ de mouillage refusé (attendu 200): {r.status_code} {r.text[:200]}"
        )
        data = r.json()
        assert "waypoints" in data and len(data["waypoints"]) >= 2


class TestManualRouteLowMargin:
    """Point 3: /api/routes/manual doit renvoyer low_margin en eaux peu profondes."""

    def test_manual_low_margin_shallow(self, api):
        """Route manuelle dans le Golfe avec draft/margin élevé → low_margin attendu."""
        r = api.post(
            f"{BASE_URL}/api/routes/manual",
            json={
                "waypoints": [
                    {"lat": 47.610, "lng": -2.825},
                    {"lat": 47.585, "lng": -2.85},
                    {"lat": 47.55, "lng": -2.85},
                ],
                "draft_m": 3.5,
                "depth_margin_m": 0.5,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        min_d = data.get("min_depth_m")
        req = 3.5 + 0.5
        if min_d is not None and float(min_d) < 1.5 * req:
            assert "low_margin" in data, (
                f"low_margin absent alors que min_depth_m={min_d} < 1.5×{req}={1.5*req}"
            )
            lm = data["low_margin"]
            assert set(lm.keys()) >= {"min_height_m", "required_m", "alert_at_m", "safe_extra_m"}
            assert lm["required_m"] == pytest.approx(req, abs=0.01)
            assert lm["alert_at_m"] == pytest.approx(1.5 * req, abs=0.01)
        else:
            pytest.skip(
                f"min_depth_m={min_d} ≥ 1.5×{req}=alert_at → low_margin ne s'applique pas ici."
            )

    def test_manual_no_low_margin_deep(self, api):
        """Route manuelle en eaux profondes + petit tirant d'eau → PAS de low_margin."""
        r = api.post(
            f"{BASE_URL}/api/routes/manual",
            json={
                "waypoints": [
                    {"lat": 47.30, "lng": -3.30},
                    {"lat": 47.25, "lng": -3.35},
                    {"lat": 47.20, "lng": -3.40},
                ],
                "draft_m": 0.5,
                "depth_margin_m": 0.3,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "low_margin" not in data, (
            f"low_margin PRÉSENT sur route confortable: {data.get('low_margin')}. "
            f"min_depth_m={data.get('min_depth_m')}"
        )
