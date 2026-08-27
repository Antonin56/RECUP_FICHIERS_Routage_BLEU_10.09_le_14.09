"""Iter143 review extras — vérifs API supplémentaires demandées par la review.

- BACKEND 1 : params engine_h {chenal_radius_m:1000, track_attach_m:3000}
- BACKEND 2 : warnings contient 'Route calée sur la route officielle'
- BACKEND 4 : repli engine_h large→large SANS official_tracks
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


def test_engine_h_params_exposed(token):
    r = requests.get(f"{BASE_URL}/api/routing/engines", headers={
        "Authorization": f"Bearer {token}", **QA}, timeout=30)
    body = r.json()
    engines = body if isinstance(body, list) else body.get("engines") or []
    h = next((e for e in engines if e.get("id") == "engine_h"), None)
    assert h is not None
    params = h.get("params") or h.get("default_params") or {}
    # Vérif souple : les 2 clés doivent être présentes
    keys = set(params.keys())
    assert "chenal_radius_m" in keys or any(
        "chenal" in k for k in keys), f"chenal_radius_m absent : {params}"
    assert "track_attach_m" in keys or any(
        "track" in k for k in keys), f"track_attach_m absent : {params}"
    # Valeurs si présentes
    if "chenal_radius_m" in params:
        assert params["chenal_radius_m"] == 1000, params
    if "track_attach_m" in params:
        assert params["track_attach_m"] == 3000, params


def test_engine_h_lorient_warning_route_officielle(token):
    res = _route(token,
                 {"lat": 47.67755575752677, "lng": -3.4287631920085064},
                 {"lat": 47.72987102630925, "lng": -3.3567713137773514},
                 "engine_h")
    warnings = res.get("warnings") or []
    text = " ".join(str(w) for w in warnings).lower()
    assert "route officielle" in text or "calée" in text or "cal\u00e9" in text, \
        f"warning 'Route calée sur la route officielle' absent : {warnings}"


def test_engine_h_open_sea_fallback_no_tracks(token):
    """BACKEND 4 : large→large → done sans official_tracks (repli Moteur F)."""
    res = _route(token,
                 {"lat": 47.40, "lng": -3.60},
                 {"lat": 47.30, "lng": -3.90}, "engine_h")
    assert len(res.get("waypoints") or []) >= 2
    # Pas de tracks (repli), mais route calculée
    ot = res.get("official_tracks") or []
    assert not ot, f"official_tracks présent alors qu'attendu vide : {ot}"
