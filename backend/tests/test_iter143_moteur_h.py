"""Tests iter143 — MOTEUR H (routes officielles + faux couples), 26/08/2026.

GO armateur : « Moteur H qui suit les routes officielles et corrige les faux
couples ». Moteurs A-G inchangés (non-régression testée par les suites 136-140).
"""
from __future__ import annotations

import math
import os
import time

import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL") or "").rstrip("/") \
    or "http://localhost:8001"
QA = {"X-RateLimit-Bypass": os.environ.get(
    "RATE_LIMIT_BYPASS_TOKEN", "qa-bypass-signalmar-2026")}

LORIENT_START = {"lat": 47.67755575752677, "lng": -3.4287631920085064}
LORIENT_END = {"lat": 47.72987102630925, "lng": -3.3567713137773514}


# ── Unitaires : réseau des routes officielles ─────────────────────────────
def test_network_loaded_and_clipped():
    from core import safe_routes
    net = safe_routes.get_network()
    assert net is not None and len(net.nodes) > 1000

def test_plan_lorient_attaches_passes():
    from core import safe_routes
    plan = safe_routes.plan_tracks(
        (LORIENT_START["lat"], LORIENT_START["lng"]),
        (LORIENT_END["lat"], LORIENT_END["lng"]), 3000)
    assert len(plan) >= 1
    L = sum(safe_routes._d_m(a, b)
            for a, b in zip(plan[0]["pts"], plan[0]["pts"][1:]))
    assert L > 3000, f"chemin trop court: {L}"

def test_plan_belle_ile_arradon_uses_teignouse():
    from core import safe_routes
    plan = safe_routes.plan_tracks((47.3480, -3.1520), (47.6280, -2.8230), 3000)
    assert len(plan) >= 2, "Teignouse + Golfe attendus"

def test_plan_open_sea_returns_empty():
    from core import safe_routes
    assert safe_routes.plan_tracks((47.40, -3.60), (47.30, -3.90), 3000) == []


# ── Unitaires : faux couples corrigés (Moteur H = dir_coherence) ──────────
def test_jument_direction_corrigee_en_mode_h():
    from core.seamarks import (
        DIR_COHERENCE_V6, SIDE_ABSOLUTE, SIDE_ABSOLUTE_V6, get_seamarks)
    sm = get_seamarks()
    t1 = SIDE_ABSOLUTE.set(True); t2 = SIDE_ABSOLUTE_V6.set(True)
    t3 = DIR_COHERENCE_V6.set(True)
    try:
        for name in ("La Petite Jument", "N° 4"):
            m = [x for x in sm.marks if x.get("name") == name
                 and 47.6 < x["lat"] < 47.8 and -3.5 < x["lng"] < -3.3][0]
            d = sm.mark_dir_confident(m)
            assert d is not None
            cap = math.degrees(math.atan2(d[0], d[1])) % 360
            # sens conventionnel ENTRANT (nord ± 90°) — plus jamais 186°/240°
            assert cap < 90 or cap > 270, f"{name}: cap {cap:.0f}° inversé"
    finally:
        DIR_COHERENCE_V6.reset(t3); SIDE_ABSOLUTE_V6.reset(t2)
        SIDE_ABSOLUTE.reset(t1)


# ── E2E API : Moteur H ────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", headers=QA, timeout=60,
                      json={"email": "antoninlepinay@gmail.com",
                            "password": "123454321"})
    assert r.status_code == 200, r.text[:200]
    return r.json().get("token") or r.json().get("access_token")


def _route(token: str, start: dict, end: dict, engine: str) -> dict:
    h = {"Authorization": f"Bearer {token}", **QA}
    r = requests.post(f"{BASE_URL}/api/routes/compute/async", headers=h,
                      timeout=60, json={
                          "start": start, "end": end, "draft_m": 1.0,
                          "depth_margin_m": 0.5, "use_tide": False,
                          "engine_id": engine})
    assert r.status_code == 200, r.text[:200]
    jid = r.json()["job_id"]
    deadline = time.time() + 240
    while time.time() < deadline:
        j = requests.get(f"{BASE_URL}/api/routes/job/{jid}", headers=h,
                         timeout=30).json()
        if j.get("status") == "done":
            return j.get("result") or {}
        assert j.get("status") != "error", str(j)[:300]
        time.sleep(2)
    pytest.fail("timeout job")


def test_engine_h_listed(token):
    r = requests.get(f"{BASE_URL}/api/routing/engines", headers={
        "Authorization": f"Bearer {token}", **QA}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    engines = body if isinstance(body, list) else body.get("engines") or []
    assert any(e.get("id") == "engine_h" for e in engines), engines


def test_engine_h_lorient_tracks_et_zero_mauvais_cote(token):
    res = _route(token, LORIENT_START, LORIENT_END, "engine_h")
    assert len(res.get("waypoints") or []) >= 10
    assert res.get("official_tracks"), "route non calée sur les pointillés"
    wsm = res.get("wrong_side_marks") or []
    assert wsm == [], f"faux couples non corrigés : {wsm}"
    assert 6000 <= (res.get("distance_m") or 0) <= 13000


def test_engine_f_intact_lorient(token):
    """Non-régression : le Moteur F rend toujours sa route (tracks ignorés)."""
    res = _route(token, LORIENT_START, LORIENT_END, "engine_f")
    assert len(res.get("waypoints") or []) >= 2
    assert not res.get("official_tracks")
