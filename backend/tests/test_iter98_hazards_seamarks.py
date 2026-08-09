"""Iter98 (22/07/2026 lot armateur) — Dangers ingérés + redressement +
seamarks avec dangers.

BACKEND P0 :
  - POST /api/routes/compute Belle-Île → Arradon : 200, ~38-40 km,
    min_depth_m >= threshold, warnings vide/quasi.
  - POST /api/routes/compute Port Navalo → Quiberon (Passage de la
    Teignouse) et sens inverse : 200, min_depth >= 2.0.
  - GET /api/bathy/seamarks bbox Teignouse : marks contient des kind='rock'
    (~31) et 'wreck', rocks ont water_level, wrecks ont depth_m.

BACKEND P1 non-régression :
  - POST /api/routes/manual (3 waypoints) → mode manual.
  - CRUD /api/routes/saved OK.
  - Blocage 422 avec detail.blocked_at (end 47.6435,-2.7590 draft 4.0).
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
QA = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
PHONE = "0766071445"  # Aslak (dev-bypass)


@pytest.fixture(scope="module")
def token() -> str:
    s = requests.Session()
    s.headers.update(QA)
    last = None
    for _ in range(3):
        s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": PHONE})
        r = s.post(
            f"{BASE_URL}/api/auth/otp/verify",
            json={"phone": PHONE, "code": "123456"},
        )
        if r.status_code == 200:
            return r.json()["token"]
        last = r
        time.sleep(32)
    pytest.skip(f"OTP verify failed: {last.status_code} {last.text}")


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", **QA}


# ── BACKEND P0 — Belle-Île → Arradon ──────────────────────────────────────
def test_belle_ile_to_arradon(token):
    r = requests.post(
        f"{BASE_URL}/api/routes/compute",
        json={
            "start": {"lat": 47.348, "lng": -3.148},
            "end": {"lat": 47.610, "lng": -2.825},
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "lateral_margin_m": 10,
        },
        headers=_auth(token),
        timeout=60,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    # distance ~38-40 km : tolérance large 30-55 km
    assert 30_000 <= d["distance_m"] <= 55_000, d["distance_m"]
    # threshold = draft + margin = 2.0
    assert d["threshold_m"] == 2.0, d["threshold_m"]
    # AUCUN passage sous le seuil : min_depth_m >= threshold_m
    assert d["min_depth_m"] >= d["threshold_m"] - 0.05, (
        f"min_depth {d['min_depth_m']} < threshold {d['threshold_m']}"
    )
    warns = d.get("warnings", [])
    # 'warnings vide ou quasi'
    assert len(warns) <= 3, warns


# ── BACKEND P0 — Passage de la Teignouse : Port Navalo → Quiberon ───────
def test_teignouse_navalo_to_quiberon(token):
    r = requests.post(
        f"{BASE_URL}/api/routes/compute",
        json={
            "start": {"lat": 47.545, "lng": -2.921},
            "end": {"lat": 47.4715, "lng": -3.129},
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "lateral_margin_m": 10,
        },
        headers=_auth(token),
        timeout=60,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["threshold_m"] == 2.0
    assert d["min_depth_m"] >= d["threshold_m"] - 0.05, (
        f"min_depth {d['min_depth_m']} < threshold {d['threshold_m']}"
    )


def test_teignouse_quiberon_to_navalo(token):
    r = requests.post(
        f"{BASE_URL}/api/routes/compute",
        json={
            "start": {"lat": 47.4715, "lng": -3.129},
            "end": {"lat": 47.545, "lng": -2.921},
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "lateral_margin_m": 10,
        },
        headers=_auth(token),
        timeout=60,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["min_depth_m"] >= d["threshold_m"] - 0.05, (
        f"min_depth {d['min_depth_m']} < threshold {d['threshold_m']}"
    )


# ── BACKEND P0 — Seamarks + dangers dans une bbox Teignouse ──────────────
def test_seamarks_bbox_teignouse_has_rocks_and_wrecks():
    r = requests.get(
        f"{BASE_URL}/api/bathy/seamarks",
        params={"bbox": "-3.09,47.44,-3.05,47.47"},
        headers=QA,
        timeout=30,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    marks = d.get("marks", [])
    rocks = [m for m in marks if m.get("kind") == "rock"]
    wrecks = [m for m in marks if m.get("kind") == "wreck"]
    # ~31 rocks attendus, tolérance
    assert len(rocks) >= 10, f"rocks count={len(rocks)}"
    # Chaque rock a water_level (peut être vide str mais la clé DOIT exister)
    for rock in rocks:
        assert "water_level" in rock, f"rock without water_level: {rock}"
    # Les wrecks ont depth_m (nombre ou None)
    for w in wrecks:
        assert "depth_m" in w, f"wreck without depth_m: {w}"
        assert w["depth_m"] is None or isinstance(w["depth_m"], (int, float))


# ── BACKEND P1 — Route MANUELLE non-régression ───────────────────────────
def test_manual_route_3_waypoints(token):
    r = requests.post(
        f"{BASE_URL}/api/routes/manual",
        json={
            "waypoints": [
                {"lat": 47.610, "lng": -2.825},
                {"lat": 47.60, "lng": -2.85},
                {"lat": 47.575, "lng": -2.90},
            ],
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
        },
        headers=_auth(token),
        timeout=30,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("mode") == "manual"
    assert d.get("distance_m", 0) > 0
    assert isinstance(d.get("depth_profile"), list) and len(d["depth_profile"]) > 0


# ── BACKEND P1 — CRUD saved routes ────────────────────────────────────────
def test_saved_routes_crud(token):
    hdr = _auth(token)
    payload = {
        "name": "TEST_iter98",
        "mode": "manual",
        "waypoints": [
            {"lat": 47.610, "lng": -2.825},
            {"lat": 47.575, "lng": -2.90},
        ],
        "distance_m": 4200.0,
    }
    r = requests.post(f"{BASE_URL}/api/routes/saved", json=payload, headers=hdr)
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    r = requests.get(f"{BASE_URL}/api/routes/saved", headers=hdr)
    assert r.status_code == 200
    assert any(x["id"] == rid for x in r.json()["routes"])
    r = requests.delete(f"{BASE_URL}/api/routes/saved/{rid}", headers=hdr)
    assert r.status_code == 200


# ── BACKEND P1 — Blocage 422 avec detail.blocked_at ──────────────────────
# 23/07/2026 : destination déplacée vers les terres de Vannes (aucune eau
# navigable ≤ 5 km) — l'ancienne (Séné) est désormais snappée → 200.
def test_route_blocked_returns_422_with_blocked_at(token):
    r = requests.post(
        f"{BASE_URL}/api/routes/compute",
        json={
            "start": {"lat": 47.610, "lng": -2.825},
            "end": {"lat": 47.95, "lng": -2.20},
            "draft_m": 4.0,
            "depth_margin_m": 0.5,
            "lateral_margin_m": 100,
        },
        headers=_auth(token),
        timeout=30,
    )
    assert r.status_code == 422, r.text
    detail = r.json().get("detail")
    assert isinstance(detail, dict), detail
    assert detail.get("code") in ("start_blocked", "end_blocked", "no_route"), detail
    assert "blocked_at" in detail, detail
    ba = detail["blocked_at"]
    assert "lat" in ba and "lng" in ba
