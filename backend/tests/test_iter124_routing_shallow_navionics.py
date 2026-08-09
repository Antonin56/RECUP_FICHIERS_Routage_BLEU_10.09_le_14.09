"""Iter 124 — tests API pour la révision routage « façon Navionics ».

BE1 : POST /api/routes/compute Arradon → barrage Arzal, draft 1.5 marge 0.5
      → 200, shallow_route=true, risk=true, compromised_legs non vide,
      warning « EAU PEU PROFONDE », PAS de clé 'tide', tide_m == 0.0.
BE2 : Route eau profonde Arradon → (47.595,-2.851) → 200, SANS shallow_route,
      SANS risk, threshold_m == 2.0, tide_m == 0.0, pas de warning marée.
BE3 : GET /api/bathy/depth?lat=47.5751&lng=-2.91473 → depth_zh_m prudent
      (≤ 2.0 environ, min 3×3), water=true.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
BYPASS = "qa-bypass-7f3d9a2e4c8b1f60"


def _mint_jwt() -> str:
    out = subprocess.check_output(
        [sys.executable, "-c",
         "import sys;sys.path.insert(0,'.');from dotenv import load_dotenv;"
         "load_dotenv();from core.auth import make_jwt;print(make_jwt('user_0b6070a69154'))"],
        cwd="/app/backend",
    )
    return out.decode().strip()


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_mint_jwt()}",
        "X-RateLimit-Bypass": BYPASS,
    })
    return s


# ── BE1 : route shallow Arradon → Arzal ─────────────────────────────────────
def test_shallow_route_arradon_to_arzal(api):
    r = api.post(f"{BASE_URL}/api/routes/compute", json={
        "start": {"lat": 47.610, "lng": -2.825},
        "end": {"lat": 47.5054, "lng": -2.3910},
        "draft_m": 1.5,
        "depth_margin_m": 0.5,
    }, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("shallow_route") is True, f"shallow_route: {data.get('shallow_route')}"
    assert data.get("risk") is True, f"risk: {data.get('risk')}"
    legs = data.get("compromised_legs")
    assert legs and len(legs) > 0, f"compromised_legs empty: {legs}"
    assert data.get("tide_m") == 0.0, f"tide_m: {data.get('tide_m')}"
    assert "tide" not in data, "clé 'tide' présente"
    warns = data.get("warnings") or []
    assert any("EAU PEU PROFONDE" in w for w in warns), f"pas de warning shallow: {warns}"


# ── BE2 : route eau profonde ────────────────────────────────────────────────
def test_deep_water_route_no_shallow(api):
    r = api.post(f"{BASE_URL}/api/routes/compute", json={
        "start": {"lat": 47.610, "lng": -2.825},
        "end": {"lat": 47.595, "lng": -2.851},
        "draft_m": 1.5,
        "depth_margin_m": 0.5,
    }, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert not data.get("shallow_route"), f"shallow_route inattendu: {data.get('shallow_route')}"
    assert not data.get("risk"), f"risk inattendu: {data.get('risk')}"
    assert data.get("threshold_m") == 2.0, f"threshold_m: {data.get('threshold_m')}"
    assert data.get("tide_m", 0.0) == 0.0, f"tide_m: {data.get('tide_m')}"
    warns = data.get("warnings") or []
    assert not any("marée" in w.lower() or "maree" in w.lower() for w in warns), (
        f"warning marée inattendu: {warns}"
    )


# ── BE3 : bathy/depth pastille prudente ─────────────────────────────────────
def test_bathy_depth_prudent_min3x3(api):
    r = api.get(
        f"{BASE_URL}/api/bathy/depth",
        params={"lat": 47.5751, "lng": -2.91473},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("water") is True, f"water: {d}"
    depth = d.get("depth_zh_m")
    assert depth is not None, f"depth_zh_m manquant: {d}"
    # Min 3×3 : la valeur doit être <= 2.0 (prudente vs 2.4 cellule seule).
    assert depth <= 2.0, f"depth_zh_m={depth} n'est pas assez prudente (attendu ≤ 2.0)"
