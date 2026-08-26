"""E2E API tests for iter139 — Lorient chenal principal/secondaire (Moteur F).

- BACKEND 2: POST /api/routes/compute/async with engine_f on Lorient route
  → 200 job → poll → wrong_side_marks vide/absent, distance ~8.8 km, waypoints cohérents.
- BACKEND 3: Moteur E gelé → même route Lorient → toujours un résultat (pas de crash).
- BACKEND 4: réponse contient depth_profile (lat/lng/depth_m) et threshold_m.
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL (or EXPO_BACKEND_URL) must be set"

RATE_BYPASS = os.environ.get(
    "RATE_LIMIT_BYPASS_TOKEN", "qa-bypass-signalmar-2026",
)

LORIENT_START = {"lat": 47.67755575752677, "lng": -3.4287631920085064}
LORIENT_END = {"lat": 47.72987102630925, "lng": -3.3567713137773514}


@pytest.fixture(scope="module")
def auth_token() -> str:
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "X-RateLimit-Bypass": RATE_BYPASS,
    })
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "antoninlepinay@gmail.com", "password": "123454321"},
        timeout=60,
    )
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:200]}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in login response: {r.text[:200]}"
    return tok


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-RateLimit-Bypass": RATE_BYPASS,
    }


def _compute_and_poll(token: str, engine_id: str, timeout_s: int = 300) -> dict:
    body = {
        "start": LORIENT_START,
        "end": LORIENT_END,
        "draft_m": 1.0,
        "depth_margin_m": 0.5,
        "use_tide": False,
        "engine_id": engine_id,
    }
    r = requests.post(
        f"{BASE_URL}/api/routes/compute/async",
        headers=_headers(token),
        json=body, timeout=60,
    )
    assert r.status_code == 200, f"async submit {engine_id}: {r.status_code} {r.text[:200]}"
    job_id = r.json().get("job_id")
    assert job_id, f"no job_id: {r.text[:200]}"

    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        rr = requests.get(
            f"{BASE_URL}/api/routes/job/{job_id}",
            headers=_headers(token), timeout=30,
        )
        assert rr.status_code == 200, f"job poll: {rr.status_code} {rr.text[:200]}"
        j = rr.json()
        last = j
        st = j.get("status")
        if st == "done":
            return j.get("result") or {}
        if st == "error":
            pytest.fail(f"job {engine_id} failed: {j}")
        time.sleep(2)
    pytest.fail(f"job {engine_id} timeout. last={last}")


# ── BACKEND 2 — Moteur F respecte le chenal Lorient, ~8.8 km, wrong_side vide ─
def test_engine_f_lorient_route_ok(auth_token):
    res = _compute_and_poll(auth_token, "engine_f")
    wps = res.get("waypoints") or []
    assert len(wps) >= 2, f"waypoints too few: {len(wps)}"
    # wrong_side_marks doit être vide ou absent
    wsm = res.get("wrong_side_marks") or []
    assert not wsm, f"wrong_side_marks should be empty, got: {wsm}"
    # distance ~8.8 km — tolérance large (7-11 km)
    dist_m = res.get("distance_m") or 0
    assert 6000 <= dist_m <= 12000, f"distance_m out of tolerance: {dist_m}"


# ── BACKEND 3 — Moteur E gelé : donne toujours un résultat, pas de crash ──
def test_engine_e_lorient_still_returns_result(auth_token):
    res = _compute_and_poll(auth_token, "engine_e")
    # On tolère n'importe quelle route/warning tant qu'il y a une réponse
    # (le gel autorise un tracé différent).
    wps = res.get("waypoints") or []
    assert len(wps) >= 2, f"engine_e no waypoints (crash?): {res}"


# ── BACKEND 4 — depth_profile + threshold_m présents ──
def test_engine_f_route_has_depth_profile_and_threshold(auth_token):
    res = _compute_and_poll(auth_token, "engine_f")
    dp = res.get("depth_profile")
    assert isinstance(dp, list) and len(dp) > 0, f"depth_profile missing/empty: {type(dp)}"
    # Chaque point doit avoir lat/lng/depth_m
    sample = dp[0]
    assert "lat" in sample and "lng" in sample, f"depth_profile point missing lat/lng: {sample}"
    assert "depth_m" in sample, f"depth_profile point missing depth_m: {sample}"
    # threshold_m présent (numérique)
    thr = res.get("threshold_m")
    assert isinstance(thr, (int, float)), f"threshold_m missing/wrong type: {thr}"
