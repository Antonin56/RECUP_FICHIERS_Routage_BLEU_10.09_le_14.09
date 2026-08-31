"""ITER148 — E2E API validation référence armateur (engine_i, Lorient large → port).

Route validée par l'armateur :
  start (47.677..., -3.428...) → end (47.729..., -3.356...)
  draft 1.5, margin 0.5, use_tide False

Vérifie :
- official_tracks non vide
- wrong_side_marks == []
- compromised_legs absent/vide
- risk absent/falsy
- fond mini du depth_profile ≥ 7.0
- 8800 ≤ distance_m ≤ 9100
- warnings contient 'écrêtée à votre besoin d'eau' et 'Lacunes de données bathy'
- GET /api/routing/engines : engine_i et engine_f listés
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://localhost:8001").rstrip("/")
QA = {"X-RateLimit-Bypass": "qa-bypass-signalmar-2026"}

START = {"lat": 47.67755575752677, "lng": -3.4287631920085064}
END = {"lat": 47.72987102630925, "lng": -3.3567713137773514}


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        headers=QA,
        timeout=60,
        json={"email": "antoninlepinay@gmail.com", "password": "123454321"},
    )
    assert r.status_code == 200, r.text[:300]
    return r.json().get("token") or r.json().get("access_token")


def test_engines_i_and_f_listed(token):
    r = requests.get(
        f"{BASE_URL}/api/routing/engines",
        headers={"Authorization": f"Bearer {token}", **QA},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    engines = body if isinstance(body, list) else body.get("engines") or []
    ids = {e.get("id") for e in engines}
    assert "engine_i" in ids, f"engine_i absent: {ids}"
    assert "engine_f" in ids, f"engine_f absent: {ids}"


def test_engine_i_ref_armateur_lorient(token):
    h = {"Authorization": f"Bearer {token}", **QA}
    r = requests.post(
        f"{BASE_URL}/api/routes/compute/async",
        headers=h,
        timeout=60,
        json={
            "start": START,
            "end": END,
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "use_tide": False,
            "engine_id": "engine_i",
        },
    )
    assert r.status_code == 200, r.text[:300]
    jid = r.json()["job_id"]

    deadline = time.time() + 240
    result = None
    while time.time() < deadline:
        j = requests.get(
            f"{BASE_URL}/api/routes/job/{jid}", headers=h, timeout=30
        ).json()
        st = j.get("status")
        if st == "done":
            result = j.get("result") or {}
            break
        assert st != "error", str(j)[:400]
        time.sleep(2)
    assert result is not None, "timeout job"

    # official_tracks non vide
    assert result.get("official_tracks"), (
        f"official_tracks vide/absent: {result.get('official_tracks')!r}"
    )

    # wrong_side_marks vide
    wsm = result.get("wrong_side_marks") or []
    assert wsm == [], f"wrong_side_marks non vide : {wsm}"

    # compromised_legs absent/vide
    cl = result.get("compromised_legs")
    assert not cl, f"compromised_legs non vide : {cl}"

    # risk absent/falsy
    risk = result.get("risk")
    assert not risk, f"risk non falsy : {risk!r}"

    # distance dans [8800; 9100]
    d = result.get("distance_m") or 0
    assert 8800 <= d <= 9100, f"distance_m hors bornes : {d}"

    # fond mini du depth_profile ≥ 7.0
    dp = result.get("depth_profile") or []
    depths = [
        p.get("depth_m")
        for p in dp
        if isinstance(p, dict) and p.get("depth_m") is not None
    ]
    assert depths, f"depth_profile vide: {len(dp)}"
    dmin = min(depths)
    assert dmin >= 7.0, f"fond mini {dmin:.2f} m < 7.0"

    # warnings attendus
    warns = result.get("warnings") or []
    joined = " || ".join(w if isinstance(w, str) else str(w) for w in warns)
    assert "écrêtée à votre besoin d'eau" in joined, (
        f"warning écrêtage absent: {warns}"
    )
    assert "Lacunes de données bathy" in joined, (
        f"warning lacunes bathy absent: {warns}"
    )
