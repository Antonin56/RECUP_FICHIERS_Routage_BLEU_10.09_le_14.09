"""
Iter97 (22/07/2026) — Backend validation lot armateur :
  - POST /api/routes/compute Belle-Île ↔ Golfe (routage 2 passes, marge 10 m)
  - Blocage → 422 + blocked_at + partial_waypoints
  - POST /api/routes/manual
  - CRUD /api/routes/saved (POST/GET/DELETE + validations)
  - GET /api/bathy/seamarks
"""
import os
import time

import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://nav-routing-speed.preview.emergentagent.com",
).rstrip("/")
QA = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
PHONE = "0766071445"  # Aslak (dev-bypass)


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    s.headers.update(QA)
    # cooldown-safe : on tente et on attend si besoin
    for _ in range(2):
        s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": PHONE})
        r = s.post(f"{BASE_URL}/api/auth/otp/verify", json={"phone": PHONE, "code": "123456"})
        if r.status_code == 200:
            return r.json()["token"]
        time.sleep(32)
    pytest.skip(f"OTP verify failed: {r.status_code} {r.text}")


def _auth(token):
    return {"Authorization": f"Bearer {token}", **QA}


# ── BACKEND P0 — Belle-Île → Golfe ────────────────────────────────────────
BELLE_ILE = {"lat": 47.348, "lng": -3.148}
GOLFE = {"lat": 47.610, "lng": -2.825}


def test_compute_belle_ile_to_golfe_ok(token):
    r = requests.post(
        f"{BASE_URL}/api/routes/compute",
        json={"start": BELLE_ILE, "end": GOLFE,
              "draft_m": 1.5, "depth_margin_m": 0.5, "lateral_margin_m": 10},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("mode", "auto") == "auto"
    assert len(d["waypoints"]) > 10, len(d["waypoints"])
    # ~40 km attendu — tolérance large
    assert 30_000 <= d["distance_m"] <= 55_000, d["distance_m"]


def test_compute_reverse_direction_ok(token):
    r = requests.post(
        f"{BASE_URL}/api/routes/compute",
        json={"start": GOLFE, "end": BELLE_ILE,
              "draft_m": 1.5, "depth_margin_m": 0.5, "lateral_margin_m": 10},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["waypoints"]) > 10


def test_compute_lateral_margin_50_ok(token):
    r = requests.post(
        f"{BASE_URL}/api/routes/compute",
        json={"start": BELLE_ILE, "end": GOLFE,
              "draft_m": 1.5, "depth_margin_m": 0.5, "lateral_margin_m": 50},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text


def test_compute_lateral_margin_below_min_rejected(token):
    r = requests.post(
        f"{BASE_URL}/api/routes/compute",
        json={"start": BELLE_ILE, "end": GOLFE,
              "draft_m": 1.5, "depth_margin_m": 0.5, "lateral_margin_m": 5},
        headers=_auth(token),
    )
    assert r.status_code == 422, r.text


# ── BACKEND P0 — Blocage : 422 + blocked_at (+ partial_waypoints) ──────────
# 23/07/2026 : l'ancienne destination (Séné, draft 4 m) est désormais
# DÉPLACÉE vers l'eau atteignable (200 + end_snapped) — le 422 ne reste que
# pour une destination SANS eau navigable à ≤ 5 km (ici : terres de Vannes).
def test_compute_end_blocked_returns_422_with_blocked_at(token):
    r = requests.post(
        f"{BASE_URL}/api/routes/compute",
        json={
            "start": {"lat": 47.610, "lng": -2.825},
            "end": {"lat": 47.95, "lng": -2.20},
            "draft_m": 4.0, "depth_margin_m": 0.5, "lateral_margin_m": 100,
        },
        headers=_auth(token),
    )
    assert r.status_code == 422, r.text
    detail = r.json().get("detail", {})
    assert isinstance(detail, dict), r.text
    assert detail.get("code") in ("end_blocked", "no_route", "start_blocked"), detail
    assert "blocked_at" in detail, detail
    ba = detail["blocked_at"]
    assert "lat" in ba and "lng" in ba, ba
    if detail.get("code") == "no_route":
        assert "partial_waypoints" in detail, detail


# ── BACKEND P0 — Route MANUELLE ───────────────────────────────────────────
def test_manual_route_ok(token):
    r = requests.post(
        f"{BASE_URL}/api/routes/manual",
        json={
            "waypoints": [
                {"lat": 47.610, "lng": -2.825},
                {"lat": 47.60, "lng": -2.85},
                {"lat": 47.575, "lng": -2.90},
            ],
            "draft_m": 1.5, "depth_margin_m": 0.5,
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("mode") == "manual", d
    assert d.get("distance_m", 0) > 0, d
    assert isinstance(d.get("depth_profile"), list) and len(d["depth_profile"]) > 0
    assert d.get("threshold_m") == 2.0, d.get("threshold_m")


# ── BACKEND P0 — CRUD /api/routes/saved ───────────────────────────────────
def test_saved_route_crud_and_validation(token):
    hdr = _auth(token)
    payload = {
        "name": "TEST_iter97",
        "mode": "manual",
        "waypoints": [
            {"lat": 47.610, "lng": -2.825},
            {"lat": 47.575, "lng": -2.90},
        ],
        "distance_m": 4200.0,
    }
    # POST
    r = requests.post(f"{BASE_URL}/api/routes/saved", json=payload, headers=hdr)
    assert r.status_code == 200, r.text
    doc = r.json()
    rid = doc["id"]
    assert doc["name"] == "TEST_iter97"
    # GET liste
    r = requests.get(f"{BASE_URL}/api/routes/saved", headers=hdr)
    assert r.status_code == 200
    listing = r.json()
    assert any(x["id"] == rid for x in listing["routes"])
    assert listing["max"] == 20
    # DELETE
    r = requests.delete(f"{BASE_URL}/api/routes/saved/{rid}", headers=hdr)
    assert r.status_code == 200
    # DELETE inexistant → 404
    r = requests.delete(f"{BASE_URL}/api/routes/saved/nonexistent-id-xxx", headers=hdr)
    assert r.status_code == 404
    # POST name vide → 422
    bad = {**payload, "name": ""}
    r = requests.post(f"{BASE_URL}/api/routes/saved", json=bad, headers=hdr)
    assert r.status_code == 422


# ── BACKEND P1 — Seamarks ──────────────────────────────────────────────────
def test_seamarks_bbox_ok():
    r = requests.get(
        f"{BASE_URL}/api/bathy/seamarks",
        params={"bbox": "-2.95,47.53,-2.88,47.57"},
        headers=QA,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert "marks" in d
    if d["marks"]:
        m = d["marks"][0]
        for key in ("lat", "lng", "kind", "category", "colour"):
            assert key in m, m


def test_seamarks_bbox_invalid_422():
    r = requests.get(
        f"{BASE_URL}/api/bathy/seamarks",
        params={"bbox": "not,a,bbox"},
        headers=QA,
    )
    assert r.status_code == 422
