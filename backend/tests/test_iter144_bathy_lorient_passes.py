"""ITER144 — Bug armateur « Passage impossible » à La Petite Jument.

Contexte : la grille bathy_lorient.npy contenait des artefacts lidar
(cellules 0.4-1.1 m dans l'axe des passes de la rade de Lorient) qui
provoquaient le rejet des routes tirant 1.5 m + marge 0.5 m sans marée,
alors que la passe réelle fait 10-20 m.

Fix appliqué (DONNÉES uniquement) : nettoyage natif ∈ [-0.5, 3 m)
contredit par ATL100 ≥ 6 m + rebouchage des lacunes quand ATL100 ≥ 6 m,
puis re-bake des îles. Aucun code moteur touché.

Ce test vérifie :
  1. Le bug est corrigé (routes courtes/moyennes/longues passent).
  2. Le Moteur H reste OK (routes officielles + wrong_side_marks vide).
  3. Les données bathy (fond de la passe ≥ 6 m, vrais dangers préservés).
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL") or "").rstrip("/") \
    or "http://localhost:8001"
QA = {"X-RateLimit-Bypass": os.environ.get(
    "RATE_LIMIT_BYPASS_TOKEN", "qa-bypass-signalmar-2026")}

EMAIL = "antoninlepinay@gmail.com"
PWD = "123454321"


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", headers=QA, timeout=60,
                      json={"email": EMAIL, "password": PWD})
    assert r.status_code == 200, r.text[:200]
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, r.text[:200]
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}",
            "Content-Type": "application/json", **QA}


def _route_async(h, start, end, engine="engine_f",
                 draft=1.5, margin=0.5, use_tide=False, timeout=240):
    body = {"start": start, "end": end,
            "draft_m": draft, "depth_margin_m": margin,
            "use_tide": use_tide, "engine_id": engine}
    r = requests.post(f"{BASE_URL}/api/routes/compute/async",
                      headers=h, json=body, timeout=60)
    assert r.status_code == 200, r.text[:300]
    jid = r.json().get("job_id")
    assert jid, r.text[:200]
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        j = requests.get(f"{BASE_URL}/api/routes/job/{jid}",
                         headers=h, timeout=30).json()
        last = j
        if j.get("status") == "done":
            return j.get("result") or {}
        if j.get("status") == "error":
            pytest.fail(f"job error: {str(j)[:400]}")
        time.sleep(2)
    pytest.fail(f"timeout job (last={str(last)[:300]})")


# ── 1. BUG PRINCIPAL : passes de Lorient ouvertes à tirant 1,5 ─────────────

def test_bug_a_kernevel_marina_to_larmor(h):
    """(a) Kernével marina → Larmor plage : done, distance 3-6 km."""
    res = _route_async(
        h,
        {"lat": 47.7160, "lng": -3.3685},
        {"lat": 47.7050, "lng": -3.3950},
        engine="engine_f", draft=1.5, margin=0.5, use_tide=False,
    )
    dist = res.get("distance_m") or 0
    print(f"BUG-A kernevel→larmor dist_m={dist} wp={len(res.get('waypoints') or [])}")
    assert res.get("waypoints"), f"pas de waypoints : {str(res)[:300]}"
    assert 3000 <= dist <= 6000, f"distance hors bornes : {dist}"


def test_bug_b_kernevel_entree_grand_chenal(h):
    """(b) Kernével entrée → grand chenal : done."""
    res = _route_async(
        h,
        {"lat": 47.7148, "lng": -3.3660},
        {"lat": 47.7180, "lng": -3.3630},
        engine="engine_f", draft=1.5, margin=0.5, use_tide=False,
    )
    dist = res.get("distance_m") or 0
    print(f"BUG-B kernevel→chenal dist_m={dist} wp={len(res.get('waypoints') or [])}")
    assert res.get("waypoints"), f"pas de waypoints : {str(res)[:300]}"


def test_bug_c_large_to_port_lorient(h):
    """(c) Large → port : done, distance 6-13 km, fond mini ≥ 1.9 m."""
    res = _route_async(
        h,
        {"lat": 47.67755575752677, "lng": -3.4287631920085064},
        {"lat": 47.72987102630925, "lng": -3.3567713137773514},
        engine="engine_f", draft=1.5, margin=0.5, use_tide=False,
    )
    dist = res.get("distance_m") or 0
    profile = res.get("depth_profile") or []
    depths = [p.get("depth_m") for p in profile
              if isinstance(p, dict) and isinstance(p.get("depth_m"), (int, float))]
    d_min = min(depths) if depths else None
    print(f"BUG-C large→port dist_m={dist} wp={len(res.get('waypoints') or [])} "
          f"depth_min={d_min}")
    assert res.get("waypoints"), f"pas de waypoints : {str(res)[:300]}"
    assert 6000 <= dist <= 13000, f"distance hors bornes : {dist}"
    assert d_min is not None, "depth_profile vide"
    assert d_min >= 1.9, f"fond mini {d_min:.2f} < 1.9 m"


# ── 2. Même route (c) avec engine_h ──────────────────────────────────────

def test_bug_c_engine_h_official_tracks(h):
    """(c) engine_h : done avec official_tracks non vide et wrong_side_marks = []."""
    res = _route_async(
        h,
        {"lat": 47.67755575752677, "lng": -3.4287631920085064},
        {"lat": 47.72987102630925, "lng": -3.3567713137773514},
        engine="engine_h", draft=1.5, margin=0.5, use_tide=False,
    )
    tracks = res.get("official_tracks") or []
    wsm = res.get("wrong_side_marks") or []
    print(f"BUG-C engine_h tracks={len(tracks)} wsm={len(wsm)} "
          f"dist_m={res.get('distance_m')}")
    assert res.get("waypoints"), f"pas de waypoints : {str(res)[:300]}"
    assert tracks, "official_tracks vide"
    assert wsm == [], f"wrong_side_marks non vide : {wsm[:3]}"


# ── 3. Données bathy : axe passe ≥ 6 m, vrais dangers préservés ──────────

def test_bathy_axe_passe_jument_citadelle_ok():
    """Axe de la passe La Petite Jument ↔ Citadelle : depth_zh_m ≥ 6 m.

    Avant fix : 0.45 m / NaN (artefacts lidar). Après fix : ≥ 6 m.
    """
    r = requests.get(f"{BASE_URL}/api/bathy/depth",
                     params={"lat": 47.7100, "lng": -3.3670},
                     headers=QA, timeout=30)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    print(f"BATHY axe-passe: {data}")
    assert data.get("covered") is True
    assert data.get("water") is True, f"attendu water=True : {data}"
    d = data.get("depth_zh_m")
    assert isinstance(d, (int, float)) and d >= 6.0, \
        f"depth_zh_m attendu ≥ 6 m, obtenu {d}"


def test_bathy_pengarne_danger_preserve():
    """Tourelle Pengarne : les vrais dangers ne doivent PAS avoir été effacés.

    Doit renvoyer valeur < 0 (danger) ou NaN/terre (water=False).
    """
    r = requests.get(f"{BASE_URL}/api/bathy/depth",
                     params={"lat": 47.7288, "lng": -3.3612},
                     headers=QA, timeout=30)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    print(f"BATHY pengarne: {data}")
    # Soit terre (water=False) soit valeur négative
    water = data.get("water")
    d = data.get("depth_zh_m")
    is_land = water is False
    is_neg = isinstance(d, (int, float)) and d < 0
    is_nan = d is None
    assert is_land or is_neg or is_nan, \
        f"vrai danger effacé : {data} (attendu terre / négatif / NaN)"
