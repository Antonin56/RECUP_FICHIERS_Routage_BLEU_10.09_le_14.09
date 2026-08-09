"""iter117 (27/07/2026) — Analyse vidéo armateur du 27/07 (route Golfe → Vannes).

Consignes armateur :
1. ZONES DE CULTURE MARINE (parcs à huîtres, bouchots) : la route ne doit
   JAMAIS les traverser, même en eau (data/bathy/marine_farms.json, ingérées
   d'OSM — seamark:type=marine_farm + landuse=aquaculture).
2. MARÉE À H+30 MIN : la hauteur utilisée est celle prévue ~30 min après le
   calcul (le bateau n'est pas sur zone avant) — tide.departure_ts ≈ now+30'.
3. Balise No8 (chenal de Vannes) : la route passait DESSUS quand l'arrivée
   déplacée tombait à < 200 m (exemption d'écart minimal levée à tort pour
   un point NON demandé par l'utilisateur) → écart minimal rétabli.
4. Arrivée déplacée : jamais « en plein sur la vasière » — préférence au
   point toujours en eau (fond ≥ tirant + marge au ZH) ou au plus profond.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import time
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

FARMS_PATH = Path(__file__).resolve().parents[1] / "data" / "bathy" / "marine_farms.json"

# Trajet de la vidéo (approché) : entrée du Golfe → port de Vannes, en
# passant au nord de l'île Drenec (zone de parcs à huîtres).
START = {"lat": 47.554, "lng": -2.905}
VANNES_PORT = {"lat": 47.6553, "lng": -2.7594}
NO8 = (47.6294199, -2.7620161)  # beacon_lateral port « No8 », chenal de Vannes


def _mint_token() -> str:
    return subprocess.check_output(
        [
            "python3", "-c",
            "import sys; sys.path.insert(0,'.'); from dotenv import load_dotenv; "
            "load_dotenv(); from core.auth import make_jwt; "
            "print(make_jwt('user_0b6070a69154'))",
        ],
        cwd="/app/backend", text=True,
    ).strip()


@pytest.fixture(scope="module")
def route() -> dict:
    tok = _mint_token()
    r = requests.post(
        f"{BASE_URL}/api/routes/compute",
        json={"start": START, "end": VANNES_PORT,
              "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": True},
        headers={"Authorization": f"Bearer {tok}"},
        timeout=300,
    )
    assert r.status_code == 200, r.text[:400]
    return r.json()


def _samples(wps: list[dict], step_m: float = 25.0):
    for i in range(len(wps) - 1):
        a, b = wps[i], wps[i + 1]
        seg = math.hypot((b["lat"] - a["lat"]) * 110_574.0,
                         (b["lng"] - a["lng"]) * 74_600.0)
        n = max(2, int(seg / step_m))
        for k in range(n + 1):
            t = k / n
            yield a["lat"] + (b["lat"] - a["lat"]) * t, a["lng"] + (b["lng"] - a["lng"]) * t


def _point_in_poly(lat, lng, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def test_farms_data_ingested():
    assert FARMS_PATH.exists(), "marine_farms.json manquant — lancer scripts/ingest_marine_farms.py"
    farms = json.loads(FARMS_PATH.read_text())["farms"]
    assert len(farms) >= 100  # ~235 parcs dans le Morbihan
    # Les parcs au nord de l'île Drenec (vidéo armateur) sont bien présents.
    near_drenec = [
        f for f in farms if f.get("poly")
        and abs(sum(p[0] for p in f["poly"]) / len(f["poly"]) - 47.609) < 0.006
        and abs(sum(p[1] for p in f["poly"]) / len(f["poly"]) + 2.856) < 0.010
    ]
    assert near_drenec, "aucun parc trouvé au nord de Drenec"


def test_route_never_crosses_marine_farms(route):
    farms = [f["poly"] for f in json.loads(FARMS_PATH.read_text())["farms"] if f.get("poly")]
    bad = 0
    for la, lo in _samples(route["waypoints"]):
        for poly in farms:
            if abs(la - poly[0][0]) > 0.03 or abs(lo - poly[0][1]) > 0.05:
                continue
            if _point_in_poly(la, lo, poly):
                bad += 1
                break
    assert bad == 0, f"{bad} échantillon(s) de la route DANS un parc de culture marine"


def test_tide_taken_30min_after_compute(route):
    """29/07/2026 — marée DÉSACTIVÉE du routage (ZH only, décision armateur) :
    plus d'info marée ni d'avertissement « +30 min » dans la réponse."""
    assert route.get("tide") is None
    assert route.get("tide_m") == 0.0
    assert not any("30 min après le calcul" in w for w in route["warnings"]), route["warnings"]


def test_standoff_kept_near_displaced_arrival(route):
    """La route ne passe plus SUR la balise No8 (vidéo 03:39) : l'écart
    minimal n'est plus levé autour d'une arrivée DÉPLACÉE par le moteur."""
    best = min(
        math.hypot((la - NO8[0]) * 110_574.0, (lo - NO8[1]) * 74_600.0)
        for la, lo in _samples(route["waypoints"], 10.0)
    )
    assert best >= 20.0, f"route à {best:.0f} m de la balise No8"


def test_displaced_arrival_not_on_mudflat(route):
    """Arrivée déplacée (port de Vannes non navigable sur les cartes) : le
    point livré doit rester dans le THALWEG du chenal (pool de La Marle ou
    lit du chenal, ≥ −1,8 m ZH) — jamais « en plein sur la vasière »
    (≈ −2,3/−2,5 m ZH, vidéo 07:23)."""
    assert route.get("end_snapped"), "arrivée non déplacée — trajet témoin invalide"
    end_depth = route["depth_profile"][-1]["depth_m"]
    assert end_depth is not None and end_depth >= -1.8, (
        f"arrivée déplacée sur un fond de {end_depth} m (ZH) — vasière"
    )
