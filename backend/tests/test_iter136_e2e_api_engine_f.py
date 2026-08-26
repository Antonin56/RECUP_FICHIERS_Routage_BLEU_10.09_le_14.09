"""Iter 136 — E2E API async pour le Moteur F + gel Moteur E + list engines.

Vérifications :
  1. POST /api/routes/compute/async avec engine_id=engine_f puis poll GET
     /api/routes/job/{id} jusqu'à 5 min : status=done, engine.id==engine_f,
     wrong_side_marks vide/absent, end_snapped absent, dernier waypoint == fin
     demandée (< 5 m), AUCUN warning "⚠ MAUVAIS CÔTÉ" ni "⚠ La route passe à ~"
  2. Même appel avec engine_id=engine_e : bug figé — wrong_side_marks contient
     "Truie d'Arradon" et distance_m ≈ 22580 m.
  3. GET /api/routing/engines : liste engine_f (signalmar.v6) + engine_e actif.
"""
from __future__ import annotations

import math
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL") or os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL", "https://signalmar-optimize.preview.emergentagent.com"
).rstrip("/")

HEADERS_BASE = {
    "Content-Type": "application/json",
    "X-RateLimit-Bypass": "qa-bypass-signalmar-2026",
}

START = {"lat": 47.61270864146456, "lng": -2.8246830304036523}
END = {"lat": 47.583795787592805, "lng": -3.0213006511557983}

M_PER_DEG_LAT = 111_320.0


def _m_per_deg_lng(lat: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat))


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        headers=HEADERS_BASE,
        json={"email": "antoninlepinay@gmail.com", "password": "123454321"},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("token")
    assert tok, "no token in response"
    return tok


@pytest.fixture(scope="module")
def auth_headers(token: str) -> dict:
    return {**HEADERS_BASE, "Authorization": f"Bearer {token}"}


def _compute_async(auth_headers: dict, engine_id: str, deadline_s: int = 300) -> dict:
    body = {
        "start": START,
        "end": END,
        "draft_m": 1.0,
        "depth_margin_m": 0.5,
        "lateral_margin_m": 30.0,
        "use_tide": False,
        "engine_id": engine_id,
    }
    r = requests.post(
        f"{BASE_URL}/api/routes/compute/async",
        headers=auth_headers, json=body, timeout=30,
    )
    assert r.status_code == 200, f"compute/async failed: {r.status_code} {r.text[:300]}"
    job_id = r.json()["job_id"]

    deadline = time.time() + deadline_s
    while time.time() < deadline:
        rj = requests.get(
            f"{BASE_URL}/api/routes/job/{job_id}",
            headers=auth_headers, timeout=15,
        )
        # 429 sur poll est acceptable — on retente
        if rj.status_code == 429:
            time.sleep(3)
            continue
        assert rj.status_code == 200, f"poll job failed: {rj.status_code} {rj.text[:300]}"
        data = rj.json()
        st = data.get("status")
        if st == "pending":
            time.sleep(3)
            continue
        if st == "done":
            return data["result"]
        if st == "error":
            pytest.fail(f"engine {engine_id} returned error: {data}")
    pytest.fail(f"job {job_id} for engine {engine_id} did not complete in {deadline_s}s")


class TestEngineFCorrections:
    """Moteur F (signalmar.v6) : bugs corrigés."""

    def test_engine_f_route_arradon_trinite(self, auth_headers):
        result = _compute_async(auth_headers, "engine_f")

        # engine metadata
        engine = result.get("engine") or {}
        assert engine.get("id") == "engine_f", f"engine mismatch: {engine}"
        assert engine.get("algo") == "signalmar.v6", f"algo mismatch: {engine}"

        # no wrong side marks
        wsm = result.get("wrong_side_marks") or []
        assert not wsm, f"wrong_side_marks should be empty for engine_f: {wsm}"

        # no end_snapped (arrivée exacte)
        assert not result.get("end_snapped"), \
            f"end_snapped should be absent: {result.get('end_snapped')}"

        # last waypoint == end demanded (< 5 m)
        wps = result.get("waypoints") or []
        assert len(wps) >= 2
        last = wps[-1]
        d_lat = (last["lat"] - END["lat"]) * M_PER_DEG_LAT
        d_lng = (last["lng"] - END["lng"]) * _m_per_deg_lng(END["lat"])
        dist_end = math.hypot(d_lat, d_lng)
        assert dist_end < 5.0, f"arrivée à {dist_end:.1f} m (attendu < 5 m)"

        # no warnings ⚠ MAUVAIS CÔTÉ / ⚠ La route passe à ~
        warns = result.get("warnings") or []
        bad = [w for w in warns
               if w.startswith("⚠ MAUVAIS CÔTÉ")
               or w.startswith("⚠ La route passe à ~")]
        assert not bad, f"unexpected warnings: {bad}"


class TestEngineEFrozen:
    """Moteur E doit conserver son bug (preuve de gel)."""

    def test_engine_e_still_has_truie_bug(self, auth_headers):
        result = _compute_async(auth_headers, "engine_e")

        engine = result.get("engine") or {}
        assert engine.get("id") == "engine_e"

        wsm = result.get("wrong_side_marks") or []
        names = [(v.get("name") or "") for v in wsm]
        assert any("Truie" in n for n in names), \
            f"engine_e devrait signaler 'Truie d'Arradon' (gel du bug): {names}"

        dist = result.get("distance_m")
        assert dist is not None, "distance_m missing"
        # tolérance ±5% autour de 22580 m (route de gel non modifiable)
        assert 21000 <= dist <= 24500, f"distance_m={dist} hors [21000,24500]"


class TestEnginesList:
    """GET /api/routing/engines liste engine_f (v6) + engine_e actif."""

    def test_engines_list_contains_f_and_e(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/routing/engines",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        data = r.json()
        # peut renvoyer soit une liste, soit {engines: [...]}
        engines = data if isinstance(data, list) else (data.get("engines") or [])
        assert engines, f"no engines in response: {data}"

        by_id = {e.get("id"): e for e in engines}
        assert "engine_f" in by_id, f"engine_f missing: {list(by_id.keys())}"
        assert "engine_e" in by_id, f"engine_e missing: {list(by_id.keys())}"

        ef = by_id["engine_f"]
        assert ef.get("algo") == "signalmar.v6", f"engine_f algo: {ef}"
        # engine_e toujours actif (pas de flag disabled=True explicite)
        ee = by_id["engine_e"]
        assert ee.get("active", True) is not False, f"engine_e not active: {ee}"
