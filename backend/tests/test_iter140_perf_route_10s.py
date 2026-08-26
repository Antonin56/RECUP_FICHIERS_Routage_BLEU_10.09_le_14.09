"""iter140 — Perf routing < 10 s (armateur).

Vérifie que POST /api/routes/compute (engine_f) répond en :
- Lorient → Golfe : < 10 s (attendu ~8 s).
- Lorient → La Trinité : < 5 s (attendu ~1,5 s).
- route iter139 Lorient (start entrée port → port) : wrong_side_marks vide.
- Moteur E : sanity 200.
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")

EMAIL = "antoninlepinay@gmail.com"
PWD = "123454321"


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": EMAIL, "password": PWD},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed {r.status_code} {r.text[:200]}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, r.text[:200]
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _compute(h, start, end, engine_id="engine_f", timeout=45):
    body = {
        "start": {"lat": start[0], "lng": start[1]},
        "end": {"lat": end[0], "lng": end[1]},
        "draft_m": 1.0,
        "depth_margin_m": 0.5,
        "use_tide": True,
        "engine_id": engine_id,
    }
    t0 = time.monotonic()
    r = requests.post(f"{BASE_URL}/api/routes/compute", headers=h, json=body,
                      timeout=timeout)
    dt = time.monotonic() - t0
    return r, dt


# Warm-up : 1er calcul après restart peut coûter +1-2 s (chargement grille +
# cache JIT numba disque). On amortit avant les mesures.
def test_00_warmup(h):
    r, dt = _compute(h, (47.72987102630925, -3.3567713137773514),
                     (47.5720, -3.0290))
    print(f"WARMUP dt={dt:.2f}s status={r.status_code}")
    # non bloquant, juste avertir
    assert r.status_code in (200, 422)


# PERF 1 : Lorient → Golfe du Morbihan < 10 s
def test_perf1_lorient_to_golfe_under_10s(h):
    r, dt = _compute(h, (47.72987102630925, -3.3567713137773514),
                     (47.6300, -2.8550))
    print(f"PERF1 status={r.status_code} dt={dt:.2f}s")
    assert r.status_code == 200, r.text[:400]
    data = r.json()
    print(f"PERF1 compute_s={data.get('compute_s')} wp={len(data.get('waypoints') or [])} "
          f"shallow={data.get('shallow_route')} dist_m={data.get('distance_m')}")
    assert dt < 10.0, f"trop lent : {dt:.2f}s ≥ 10 s"
    assert (data.get("compute_s") or 0) < 10.0
    assert data.get("waypoints") and len(data["waypoints"]) >= 2


# PERF 2 : Lorient → La Trinité < 5 s
def test_perf2_lorient_to_trinite_under_5s(h):
    r, dt = _compute(h, (47.72987102630925, -3.3567713137773514),
                     (47.5720, -3.0290))
    print(f"PERF2 status={r.status_code} dt={dt:.2f}s")
    assert r.status_code == 200, r.text[:400]
    data = r.json()
    print(f"PERF2 compute_s={data.get('compute_s')} wp={len(data.get('waypoints') or [])}")
    assert dt < 5.0, f"trop lent : {dt:.2f}s ≥ 5 s"
    assert (data.get("compute_s") or 0) < 5.0


# ROUTE iter139 : entrée port Lorient → port → wrong_side_marks vide
def test_iter139_lorient_wrong_side_empty(h):
    r, dt = _compute(h, (47.67755575752677, -3.4287631920085064),
                     (47.72987102630925, -3.3567713137773514))
    print(f"ITER139 status={r.status_code} dt={dt:.2f}s")
    assert r.status_code == 200, r.text[:400]
    data = r.json()
    wsm = data.get("wrong_side_marks") or []
    print(f"ITER139 wrong_side_marks count={len(wsm)}")
    assert wsm == [], f"wrong_side_marks non vide : {wsm[:3]}"


# SANITÉ Moteur E
def test_sanity_engine_e_200(h):
    r, dt = _compute(h, (47.72987102630925, -3.3567713137773514),
                     (47.5720, -3.0290), engine_id="engine_e")
    print(f"ENGINE_E status={r.status_code} dt={dt:.2f}s")
    assert r.status_code == 200, r.text[:400]
    data = r.json()
    assert data.get("waypoints")
