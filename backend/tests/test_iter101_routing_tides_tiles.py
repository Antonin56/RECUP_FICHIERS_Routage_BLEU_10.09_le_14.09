"""Iter101 — armateur 22-23/07/2026 : validation backend.

Couvre :
- ROUTAGE : Er Lannic évité, Arradon→Port-Maria (aller/retour), Arradon→Houat.
- MARÉES : Arradon/Vannes/Port-Navalo doivent DIFFÉRER, retard Arradon vs
  Port-Navalo ≈ 1h45-2h, champ source contient « calibré ».
- TUILES : shom/morbihan et seamark → 200 image/png (non-régression).
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import pytest
import requests


BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")

_TOKEN_FILE = Path("/app/tmp_token.txt")
JWT = _TOKEN_FILE.read_text().strip() if _TOKEN_FILE.exists() else ""


@pytest.fixture
def auth_client():
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {JWT}",
    })
    return s


def _hav_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _parse_hhmm_to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


# ── ROUTAGE ────────────────────────────────────────────────────────────

class TestRouting:

    def test_er_lannic_avoided(self, auth_client):
        """Larmor-Baden → Port-Navalo doit éviter Er Lannic (47.5661,-2.8985)
        d'au moins ~150 m latéralement (contrainte armateur)."""
        payload = {
            "start": {"lat": 47.5789, "lng": -2.8935},
            "end":   {"lat": 47.5486, "lng": -2.9186},
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "lateral_margin_m": 10,
        }
        r = auth_client.post(f"{BASE_URL}/api/routes/compute", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "waypoints" in data and len(data["waypoints"]) >= 2
        er_lannic = (47.5661, -2.8985)
        min_dist = min(_hav_m(er_lannic, (w["lat"], w["lng"])) for w in data["waypoints"])
        assert min_dist >= 150, (
            f"Waypoint trop proche d'Er Lannic ({min_dist:.0f} m < 150 m)"
        )

    def test_arradon_to_port_maria_forward(self, auth_client):
        payload = {
            "start": {"lat": 47.610, "lng": -2.825},
            "end":   {"lat": 47.478, "lng": -3.122},
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "lateral_margin_m": 10,
        }
        r = auth_client.post(f"{BASE_URL}/api/routes/compute", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("waypoints") and d.get("distance_m", 0) > 0

    def test_arradon_to_port_maria_return(self, auth_client):
        payload = {
            "start": {"lat": 47.478, "lng": -3.122},
            "end":   {"lat": 47.610, "lng": -2.825},
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "lateral_margin_m": 10,
        }
        r = auth_client.post(f"{BASE_URL}/api/routes/compute", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("waypoints") and d.get("distance_m", 0) > 0

    def test_arradon_to_houat(self, auth_client):
        payload = {
            "start": {"lat": 47.610, "lng": -2.825},
            "end":   {"lat": 47.392, "lng": -2.955},
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "lateral_margin_m": 10,
        }
        r = auth_client.post(f"{BASE_URL}/api/routes/compute", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("waypoints") and d.get("distance_m", 0) > 0


# ── MARÉES ─────────────────────────────────────────────────────────────

class TestTides:

    @pytest.fixture(scope="class")
    def tides(self):
        s = requests.Session()
        s.headers["Content-Type"] = "application/json"
        arradon = s.get(f"{BASE_URL}/api/tides/nearest", params={"lat": 47.618, "lng": -2.822}).json()
        vannes = s.get(f"{BASE_URL}/api/tides/nearest", params={"lat": 47.641, "lng": -2.775}).json()
        pn = s.get(f"{BASE_URL}/api/tides/nearest", params={"lat": 47.5486, "lng": -2.9186}).json()
        return {"arradon": arradon, "vannes": vannes, "port-navalo": pn}

    def test_ports_are_different_locations(self, tides):
        assert tides["arradon"]["port"]["id"] == "arradon"
        assert tides["vannes"]["port"]["id"] == "vannes"
        assert tides["port-navalo"]["port"]["id"] == "port-navalo"

    def test_source_says_calibre(self, tides):
        for k in ("arradon", "vannes", "port-navalo"):
            src = str(tides[k].get("source", ""))
            assert "calibr" in src.lower(), f"{k}: source={src!r} doit contenir 'calibré'"

    def test_arradon_delay_vs_portnavalo(self, tides):
        """Sur la PREMIÈRE PM (ou PM du même jour), Arradon doit être en retard
        d'environ 1h45 à 2h30 sur Port-Navalo."""
        def first_pm(payload):
            for day in payload.get("days", []):
                for ev in day.get("events", []):
                    if ev.get("type") == "PM":
                        return day["date"], ev
            return None, None

        d_ar, pm_ar = first_pm(tides["arradon"])
        d_pn, pm_pn = first_pm(tides["port-navalo"])
        assert pm_ar and pm_pn, "PM manquante dans les payloads"
        # Cherchons la PM Arradon du MÊME jour que Port-Navalo
        pm_pn_min = _parse_hhmm_to_min(pm_pn["time"])
        best_gap = None
        for day in tides["arradon"].get("days", []):
            for ev in day["events"]:
                if ev["type"] != "PM":
                    continue
                gap = _parse_hhmm_to_min(ev["time"]) - pm_pn_min
                if day["date"] == d_pn:
                    if best_gap is None or abs(gap) < abs(best_gap):
                        best_gap = gap
        assert best_gap is not None, "Aucune PM Arradon le même jour que Port-Navalo"
        # 1h45 = 105 min, 2h30 = 150 min. Tolérance large (calibration ±15 min).
        assert 90 <= best_gap <= 165, (
            f"Retard Arradon vs Port-Navalo = {best_gap} min (attendu 90-165)"
        )

    def test_ports_do_not_return_same_values(self, tides):
        """Les 3 ports NE doivent PLUS renvoyer les mêmes heures/hauteurs."""
        def sig(payload):
            days = payload.get("days", [])
            if not days:
                return None
            evs = days[0].get("events", [])
            return tuple((e["type"], e["time"], e["height_m"]) for e in evs)

        s_ar = sig(tides["arradon"])
        s_va = sig(tides["vannes"])
        s_pn = sig(tides["port-navalo"])
        assert s_ar != s_pn, "Arradon == Port-Navalo (bug marée non corrigé)"
        assert s_va != s_pn, "Vannes == Port-Navalo (bug marée non corrigé)"


# ── TUILES ─────────────────────────────────────────────────────────────

class TestTiles:

    def test_shom_morbihan_tile(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/tiles/shom/morbihan/13/4028/2862.png")
        assert r.status_code == 200, r.text
        ctype = r.headers.get("content-type", "")
        assert ctype.startswith("image/png"), f"content-type={ctype}"
        assert len(r.content) > 100

    def test_seamark_tile(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/tiles/seamark/13/4028/2862.png")
        assert r.status_code == 200, r.text
        ctype = r.headers.get("content-type", "")
        assert ctype.startswith("image/png"), f"content-type={ctype}"
        assert len(r.content) > 50
