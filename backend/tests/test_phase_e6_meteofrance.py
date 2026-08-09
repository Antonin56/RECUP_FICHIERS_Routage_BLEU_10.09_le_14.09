"""Phase E.6 — Météo-France AROME/ARPEGE integration tests.

Runs against the live backend on http://localhost:8001 (internal) since the
integration hits Météo-France directly. We follow the review request steps
1→8 in order.
"""
from __future__ import annotations

import os
import time

import pytest
import requests

# NOTE: We use the internal 8001 URL for backend-only tests (ingress can
# add extra latency and, for MF, timing matters).
BASE_URL = "http://localhost:8001"
EMAIL = "antoninlepinay@gmail.com"
PASSWORD = "123454321"

# Shared state across tests (order matters).
_state: dict = {}


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# ── 1) Health ping ──────────────────────────────────────────────────────────
def test_1_health_ping(s):
    r = s.get(f"{BASE_URL}/api/diagnostics/ping", timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True
    assert isinstance(data.get("ts"), str) and len(data["ts"]) > 10


# ── 2) Login ────────────────────────────────────────────────────────────────
def test_2_login(s):
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no access_token in {data}"
    _state["token"] = tok


# ── 3) MF diagnostic — coastal (AROME expected) ─────────────────────────────
def test_3_meteofrance_coastal_arome(s):
    t0 = time.perf_counter()
    r = s.get(
        f"{BASE_URL}/api/diagnostics/meteofrance",
        params={"lat": 47.65, "lng": -2.75, "clear_cache": "true"},
        timeout=60,
    )
    elapsed = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200, r.text
    d = r.json()
    print(f"\n[STEP3] latency_ms={d.get('latency_ms')} elapsed_client_ms={elapsed:.0f}")
    print(f"[STEP3] model_picked={d.get('model_picked')} wind={d.get('wind')}")
    print(f"[STEP3] errors={d.get('errors')} eccodes={d.get('eccodes')}")

    assert d.get("env_configured") is True
    assert isinstance(d.get("eccodes"), str) and d["eccodes"]
    assert d["model_picked"] == "AROME"

    wind = d.get("wind")
    if wind is None:
        pytest.fail(f"MF/Open-Meteo BOTH failed: errors={d.get('errors')}")

    assert wind["speed_ms"] > 0
    to_deg = wind.get("to_deg")
    assert to_deg is not None and 0 <= float(to_deg) <= 360
    src = wind.get("source", "")
    # PASS conditions per review: MF source preferred but Open-Meteo fallback OK.
    if "Open-Meteo" in src:
        print(f"[STEP3][OBSERVATION] MF unavailable → Open-Meteo fallback used ({src})")
        _state["mf_fallback"] = True
    else:
        assert ("AROME 1.3km" in src) or ("ARPEGE 0.1°" in src), f"unexpected source {src}"
        assert wind.get("u_ms") is not None
        assert wind.get("v_ms") is not None
        assert wind.get("cached") is False
        assert d.get("token", {}).get("ok") is True
        assert isinstance(d.get("cache", {}).get("after"), list) and len(d["cache"]["after"]) >= 1
        assert d.get("errors") == []

    # Latency budget: server-side latency_ms only (not client-side).
    lat_ms = d.get("latency_ms") or 0
    assert lat_ms < 6000, f"latency_ms={lat_ms} exceeds 6000ms budget"


# ── 4) Cache hit ────────────────────────────────────────────────────────────
def test_4_cache_hit(s):
    if _state.get("mf_fallback"):
        pytest.skip("MF fell back to Open-Meteo on step 3 — no MF cache to hit")
    # Small pause to ensure previous write is committed.
    time.sleep(0.5)
    r = s.get(
        f"{BASE_URL}/api/diagnostics/meteofrance",
        params={"lat": 47.65, "lng": -2.75},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    print(f"\n[STEP4] latency_ms={d.get('latency_ms')} wind={d.get('wind')}")
    wind = d.get("wind") or {}
    assert wind.get("cached") is True, f"expected cached=true, got wind={wind}"
    lat_ms = d.get("latency_ms") or 0
    assert lat_ms < 300, f"cache-hit latency {lat_ms}ms too high"


# ── 5) Offshore point — ARPEGE fallback ─────────────────────────────────────
def test_5_offshore_arpege(s):
    r = s.get(
        f"{BASE_URL}/api/diagnostics/meteofrance",
        params={"lat": 45.0, "lng": -15.0, "clear_cache": "true"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    print(f"\n[STEP5] model_picked={d.get('model_picked')} wind={d.get('wind')}")
    print(f"[STEP5] errors={d.get('errors')} latency_ms={d.get('latency_ms')}")
    assert d["model_picked"] == "ARPEGE"
    wind = d.get("wind")
    if wind is None:
        pytest.fail(f"MF/Open-Meteo BOTH failed offshore: errors={d.get('errors')}")
    assert wind["speed_ms"] > 0
    src = wind.get("source", "")
    if "Open-Meteo" in src:
        print(f"[STEP5][OBSERVATION] ARPEGE unavailable → Open-Meteo fallback ({src})")
        _state["mf_offshore_fallback"] = True
    else:
        assert "ARPEGE 0.1°" in src, f"expected ARPEGE 0.1° source, got {src}"


# ── 6) Cache stats ──────────────────────────────────────────────────────────
def test_6_cache_stats(s):
    r = s.get(f"{BASE_URL}/api/diagnostics/meteofrance/cache", timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    print(f"\n[STEP6] cache stats={d}")
    assert d.get("ok") is True

    if _state.get("mf_fallback") and _state.get("mf_offshore_fallback"):
        pytest.skip("Both MF fetches fell back to Open-Meteo — no MF cache expected")

    assert d.get("total", 0) >= 1  # at least one MF hit expected if not full fallback
    by_source = d.get("by_source") or {}
    mf_present = any(k in by_source for k in ("AROME 1.3km", "ARPEGE 0.1° Europe"))
    assert mf_present, f"expected AROME or ARPEGE in by_source, got {by_source}"


# ── 7) Report with drift cone (integration) ─────────────────────────────────
def test_7_report_creation_with_drift_cone(s):
    token = _state.get("token")
    assert token, "login must run first"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "lat": 47.6,
        "lng": -2.8,
        "type": "obstacle_nav",
        "subtype": "ofni",
        "description": "TEST_MF_wind",
        "photos": [],
    }
    r = requests.post(f"{BASE_URL}/api/reports", json=body, headers=headers, timeout=30)
    assert r.status_code in (200, 201), r.text
    created = r.json()
    print(f"\n[STEP7] created keys={list(created.keys())}")
    rid = created.get("id") or created.get("_id")
    assert rid, f"no id in response {created}"
    _state["rid"] = rid

    # drift_cone may be computed synchronously OR via background task.
    # Poll GET /api/reports/{id} for a few seconds.
    got = None
    for i in range(15):
        gr = requests.get(f"{BASE_URL}/api/reports/{rid}", timeout=15)
        assert gr.status_code == 200, gr.text
        got = gr.json()
        if got.get("drift_cone"):
            break
        time.sleep(1.0)

    print(f"[STEP7] final drift_cone={got.get('drift_cone')}")
    dc = got.get("drift_cone")
    assert dc, f"drift_cone missing after polling: {got}"
    assert dc.get("wind_speed_ms", 0) > 0
    wtd = dc.get("wind_to_deg")
    assert wtd is not None and 0 <= float(wtd) <= 360
    assert dc.get("current_speed_ms") is not None
    poly = dc.get("polygon") or []
    assert len(poly) >= 3, f"polygon has <3 points: {poly}"


# ── 8) Regression ───────────────────────────────────────────────────────────
def test_8a_auth_me(s):
    token = _state.get("token")
    assert token
    r = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert "email" in d, f"no email field: {d}"


def test_8b_reports_list(s):
    r = requests.get(f"{BASE_URL}/api/reports", timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    # accept either list, or dict with items
    if isinstance(d, dict):
        items = d.get("items") or d.get("results") or d.get("data")
        assert isinstance(items, list), f"unexpected shape: {d}"
    else:
        assert isinstance(d, list)
