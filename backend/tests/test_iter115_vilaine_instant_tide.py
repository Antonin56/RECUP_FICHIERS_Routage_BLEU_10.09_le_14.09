"""iter115 (26/07/2026) — Marée à l'INSTANT T + Vilaine « Foireuse 3 ».

Retour armateur : route Arradon → Vilaine (47.4969, -2.3846, quasi sur le
barrage d'Arzal) coupée à Tréhiguier (~3,7 km « à vue ») alors que le chenal
était en eau. Causes corrigées :
1. marée = hauteur AU MOMENT DU CALCUL (plus le mini de la fenêtre) ;
2. nearest_reachable validé pleine résolution (renvoyait un point À TERRE) ;
3. dernier recours = règles de côté du balisage latéral levées (sens
   conventionnel FAUX dans la Vilaine : demi-disques en travers du chenal) ;
4. plafond de troncature « arrivée déplacée » adaptatif (15 % du trajet) ;
5. dernier recours aussi tenté quand l'arrivée est déplacée de > 800 m.
"""
from __future__ import annotations

import datetime as dt
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

ARRADON = {"lat": 47.61, "lng": -2.825}
FOIREUSE = {"lat": 47.4969, "lng": -2.3846}  # destination armateur (barrage)


def _mint_token() -> str:
    return subprocess.check_output(
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


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {_mint_token()}"
    return s


def _dist_m(a: dict, b: dict) -> float:
    return math.hypot(
        (a["lat"] - b["lat"]) * 111_320.0,
        (a["lng"] - b["lng"]) * 111_320.0 * math.cos(math.radians(a["lat"])),
    )


def _compute(api, departure_ts: float):
    return api.post(
        f"{BASE_URL}/api/routes/compute",
        json={
            "start": ARRADON,
            "end": FOIREUSE,
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "lateral_margin_m": 50,
            "use_tide": True,
            "departure_ts": departure_ts,
        },
        timeout=240,
    )


def _next_high_tide_ts(api) -> float:
    """Prochain instant (demain) où la marée à Arradon est ≥ 2,0 m."""
    import asyncio
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.tides import tide_window  # noqa: E402

    base = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)

    async def _scan():
        best_ts, best_h = None, -99.0
        for hh in range(0, 24, 2):
            ts = base.replace(hour=hh, minute=0, second=0, microsecond=0).timestamp()
            tw = await tide_window(ARRADON["lat"], ARRADON["lng"], ts, 1.0)
            h = (tw or {}).get("height_start_m")
            if h is not None and h > best_h:
                best_ts, best_h = ts, h
        return best_ts, best_h

    best_ts, best_h = asyncio.run(_scan())
    assert best_ts is not None and best_h >= 2.0, f"pas de pleine mer trouvée (max {best_h})"
    return best_ts


def test_vilaine_route_reaches_near_barrage_at_high_tide(api):
    """29/07/2026 (révision « façon Navionics ») — le routage est 100 % au ZH
    et, quand rien ne passe, la route est TRACÉE QUAND MÊME en mode « eau peu
    profonde » : la Vilaine remonte jusqu'au barrage avec des tronçons ROUGES
    (compromised_legs) + risk=True, quelle que soit la marée."""
    r = api.post(
        f"{BASE_URL}/api/routes/compute",
        json={
            "start": ARRADON,
            "end": FOIREUSE,
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
        },
        timeout=240,
    )
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    last = j["waypoints"][-1]
    d_end = _dist_m(last, FOIREUSE)
    assert d_end <= 1500.0, f"arrivée encore à {d_end:.0f} m (attendu ≤ 1500 m)"
    assert j.get("shallow_route") is True
    assert j.get("risk") is True
    assert j.get("compromised_legs"), "tronçons rouges attendus (lit de la Vilaine < besoin au ZH)"
    warns = " | ".join(j.get("warnings") or [])
    assert "EAU PEU PROFONDE" in warns.upper()


def test_tide_warning_always_present_with_tide(api):
    """29/07/2026 — marée DÉSACTIVÉE du routage (ZH only) : plus aucune info
    ni avertissement marée dans la réponse, même avec use_tide=True."""
    # Route triviale en eau profonde du Golfe (Arradon → île aux Moines).
    r = api.post(
        f"{BASE_URL}/api/routes/compute",
        json={
            "start": ARRADON,
            "end": {"lat": 47.595, "lng": -2.851},
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "use_tide": True,
        },
        timeout=240,
    )
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    assert j.get("tide") is None, "info marée inattendue (routage ZH only)"
    assert j.get("tide_m") == 0.0
    warns = " | ".join(j.get("warnings") or [])
    assert "30 min après le calcul" not in warns
