"""Integration tests — Iter 133 Moteur D bug fix (Vilaine + Illur).

Tests API-level (via public EXPO_PUBLIC_BACKEND_URL):
  1. OTP auth (dev bypass 123456)
  2. GET /api/routing/engines lists engine_d as signalmar.v4
  3. POST /api/routes/compute Vilaine engine_d → wrong_side_marks empty
     (bug fix: Moteur D never lifts reliable sides even in shallow mode)
  4. POST /api/routes/compute Illur engine_d → passes NORTH of Illur
  5. Non-regression Moteur B (figé): Vilaine engine_b → HTTP 200, no
     wrong_side_marks field required (audit is Moteur D-only)

Long computes use POST /compute/async + poll GET /routes/job/{job_id}.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
RL_BYPASS = os.environ.get("RATE_LIMIT_BYPASS_TOKEN", "qa-bypass-signalmar-2026")
TEST_PHONE = "0760071445"
TEST_OTP = "123456"

# Compute is CPU-intensive (up to 3 min). Poll async job with a big budget.
POLL_TIMEOUT_S = 300
POLL_INTERVAL_S = 3

ILLUR_LAT = 47.5827118
ILLUR_LNG = -2.7951316


# ── Session helpers ─────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "X-RateLimit-Bypass": RL_BYPASS,
    })
    return s


@pytest.fixture(scope="module")
def auth_token(session):
    assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL missing"
    r = session.post(f"{BASE_URL}/api/auth/otp/request",
                     json={"phone": TEST_PHONE}, timeout=30)
    assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("sent") is True
    r2 = session.post(f"{BASE_URL}/api/auth/otp/verify",
                      json={"phone": TEST_PHONE, "code": TEST_OTP}, timeout=30)
    assert r2.status_code == 200, f"otp/verify failed: {r2.status_code} {r2.text}"
    payload = r2.json()
    token = payload.get("token")
    assert token, f"no token in verify payload: {payload}"
    return token


@pytest.fixture(scope="module")
def auth_session(session, auth_token):
    session.headers["Authorization"] = f"Bearer {auth_token}"
    return session


# ── Compute helper (async job + poll) ───────────────────────────────────
def _compute_async(sess: requests.Session, body: dict) -> tuple[int, dict]:
    """Fire compute/async, poll job, return (status_code, result_or_detail)."""
    r = sess.post(f"{BASE_URL}/api/routes/compute/async",
                  json=body, timeout=60)
    if r.status_code != 200:
        return r.status_code, {"detail": r.text}
    job_id = r.json().get("job_id")
    assert job_id, f"no job_id in response: {r.text}"

    deadline = time.time() + POLL_TIMEOUT_S
    while time.time() < deadline:
        rj = sess.get(f"{BASE_URL}/api/routes/job/{job_id}", timeout=30)
        if rj.status_code != 200:
            return rj.status_code, {"detail": rj.text}
        data = rj.json()
        st = data.get("status")
        if st == "done":
            return 200, data.get("result") or {}
        if st == "error":
            return data.get("status_code", 500), {"detail": data.get("detail")}
        time.sleep(POLL_INTERVAL_S)
    pytest.fail(f"compute job {job_id} timed out after {POLL_TIMEOUT_S}s")


# ── 1. Engines listing ─────────────────────────────────────────────────
def test_engines_listing(auth_session):
    r = auth_session.get(f"{BASE_URL}/api/routing/engines", timeout=30)
    assert r.status_code == 200, r.text
    engines = r.json()
    # response may be a list or dict; normalize
    if isinstance(engines, dict):
        engines_list = engines.get("engines") or engines.get("items") or []
    else:
        engines_list = engines
    by_id = {e.get("engine_id") or e.get("id"): e for e in engines_list}
    assert "engine_d" in by_id, f"engine_d absent: {list(by_id)}"
    assert "engine_b" in by_id, f"engine_b absent: {list(by_id)}"
    assert by_id["engine_d"].get("algo") == "signalmar.v4"
    assert by_id["engine_b"].get("algo") == "signalmar.v2"
    if "engine_a" in by_id:
        assert by_id["engine_a"].get("algo") == "signalmar.v1"
    if "engine_c" in by_id:
        assert by_id["engine_c"].get("algo") == "signalmar.v3"


# ── 2. Vilaine bug fix (Moteur D) ──────────────────────────────────────
@pytest.fixture(scope="module")
def vilaine_engine_d(auth_session):
    body = {
        "engine_id": "engine_d",
        "start": {"lat": 47.56008860504397, "lng": -2.8533983201895574},
        "end":   {"lat": 47.504648034924834, "lng": -2.3904279112746045},
        "draft_m": 1.5,
        "depth_margin_m": 0.5,
        "use_tide": False,
    }
    return _compute_async(auth_session, body)


def test_vilaine_engine_d_http_200(vilaine_engine_d):
    status, result = vilaine_engine_d
    assert status == 200, f"engine_d Vilaine failed: {status} {result}"


def test_vilaine_engine_d_shallow_flag(vilaine_engine_d):
    _, result = vilaine_engine_d
    # Vilaine dries at low tide → shallow is expected/normal.
    assert result.get("shallow_route") is True, (
        f"expected shallow_route=True for Vilaine (dries at low tide), "
        f"got shallow_route={result.get('shallow_route')}"
    )


def test_vilaine_engine_d_no_wrong_side_marks(vilaine_engine_d):
    """PRIMARY BUG-FIX ASSERTION: no lateral left on the wrong side."""
    _, result = vilaine_engine_d
    wrong = result.get("wrong_side_marks") or []
    assert wrong == [], (
        f"BUG STILL PRESENT: wrong_side_marks not empty on Moteur D "
        f"Vilaine route: {wrong}"
    )


def test_vilaine_engine_d_no_wrong_side_warning(vilaine_engine_d):
    _, result = vilaine_engine_d
    warnings = result.get("warnings") or []
    offenders = [w for w in warnings if "MAUVAIS CÔTÉ" in str(w).upper()
                 or "MAUVAIS COTE" in str(w).upper()]
    assert offenders == [], f"warnings contain MAUVAIS CÔTÉ: {offenders}"


# ── 3. Illur reference (Moteur D) ──────────────────────────────────────
@pytest.fixture(scope="module")
def illur_engine_d(auth_session):
    body = {
        "engine_id": "engine_d",
        "start": {"lat": 47.5455, "lng": -2.9185},
        "end":   {"lat": 47.5870, "lng": -2.7820},
        "draft_m": 1.5,
        "depth_margin_m": 0.5,
        "use_tide": False,
    }
    return _compute_async(auth_session, body)


def test_illur_engine_d_http_200(illur_engine_d):
    status, result = illur_engine_d
    assert status == 200, f"engine_d Illur failed: {status} {result}"


def test_illur_engine_d_no_wrong_side_illur(illur_engine_d):
    _, result = illur_engine_d
    wrong = result.get("wrong_side_marks") or []
    names = [w.get("name") for w in wrong if isinstance(w, dict)]
    assert "Illur" not in names, (
        f"Illur is on wrong side (Moteur D bug): wrong_side_marks={wrong}"
    )


def test_illur_engine_d_route_passes_north_of_illur(illur_engine_d):
    """Closest waypoint to Illur must lie NORTH of the buoy (lat > 47.5827118)."""
    _, result = illur_engine_d
    wps = result.get("waypoints") or []
    assert wps, "no waypoints in Illur route"
    # find closest waypoint to Illur
    best = min(wps, key=lambda w: (w["lat"] - ILLUR_LAT) ** 2
                                   + (w["lng"] - ILLUR_LNG) ** 2)
    # Sanity: closest waypoint must be reasonably near the buoy
    # (otherwise route may not traverse the Illur channel).
    dlat = best["lat"] - ILLUR_LAT
    dlng = best["lng"] - ILLUR_LNG
    dist_m = ((dlat * 110_574.0) ** 2 + (dlng * 74_500.0) ** 2) ** 0.5
    if dist_m > 800.0:
        pytest.skip(f"route does not traverse Illur channel (min dist "
                    f"{dist_m:.0f} m)")
    assert best["lat"] > ILLUR_LAT, (
        f"route passes SOUTH of Illur (wrong side): closest waypoint "
        f"lat={best['lat']} vs Illur lat={ILLUR_LAT}"
    )


# ── 4. Non-regression Moteur B (figé) ──────────────────────────────────
@pytest.fixture(scope="module")
def vilaine_engine_b(auth_session):
    body = {
        "engine_id": "engine_b",
        "start": {"lat": 47.56008860504397, "lng": -2.8533983201895574},
        "end":   {"lat": 47.504648034924834, "lng": -2.3904279112746045},
        "draft_m": 1.5,
        "depth_margin_m": 0.5,
        "use_tide": False,
    }
    return _compute_async(auth_session, body)


def test_vilaine_engine_b_http_200(vilaine_engine_b):
    status, result = vilaine_engine_b
    assert status == 200, f"engine_b Vilaine failed: {status} {result}"


def test_vilaine_engine_b_no_wrong_side_marks_field(vilaine_engine_b):
    """wrong_side_marks audit is Moteur D-only: it MUST NOT exist on B."""
    _, result = vilaine_engine_b
    assert "wrong_side_marks" not in result, (
        "wrong_side_marks leaked into engine_b response (must be D-only): "
        f"{result.get('wrong_side_marks')}"
    )
