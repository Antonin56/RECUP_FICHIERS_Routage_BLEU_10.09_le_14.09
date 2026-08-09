"""ITER 129 EXTENDED — Tests supplémentaires demandés par la review request.

Compléments au fichier test_iter129_engine_c_rules.py (déjà 11/11 verts) :
- règles accessibles à un utilisateur NON-admin (TestDiag51)
- couples de points supplémentaires (Golfe + FRAGILE + inter-bassins)
- réversibilité sur 3 couples
- mode manuel avec engine_c
- non-régression déterministe engine_b
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
ADMIN_PHONE = "0760071445"
USER_PHONE = "0699887766"  # TestDiag51 (non-admin)
OTP_CODE = "123456"

ILLUR_SEA = {"lat": 47.5720, "lng": -2.8300}
ILLUR_LAND = {"lat": 47.5905, "lng": -2.7850}
GOLFE_A = {"lat": 47.6180, "lng": -2.8250}
GOLFE_B = {"lat": 47.5430, "lng": -2.9200}
FRAGILE_START = {"lat": 47.302, "lng": -2.096}
FRAGILE_END = {"lat": 47.5614, "lng": -2.87473}


def _login(phone: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200, r.text[:200]
    r = s.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"phone": phone, "code": OTP_CODE,
              "pseudo": f"QAiter129x_{uuid.uuid4().hex[:6]}"},
    )
    assert r.status_code == 200, r.text[:200]
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s


@pytest.fixture(scope="module")
def admin() -> requests.Session:
    return _login(ADMIN_PHONE)


@pytest.fixture(scope="module")
def user() -> requests.Session:
    return _login(USER_PHONE)


def _compute(session, start, end, engine_id, **kw) -> dict:
    payload = {
        "start": start, "end": end,
        "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": False,
        "engine_id": engine_id, **kw,
    }
    r = session.post(f"{BASE_URL}/api/routes/compute", json=payload, timeout=180)
    assert r.status_code == 200, f"{engine_id} → {r.status_code} {r.text[:400]}"
    return r.json()


def _geom(res: dict) -> list[tuple[float, float]]:
    return [(round(w["lat"], 6), round(w["lng"], 6)) for w in res["waypoints"]]


# ── Ouverture à TOUS les utilisateurs ────────────────────────────────────
def test_rules_endpoint_accessible_to_non_admin(user):
    r = user.get(f"{BASE_URL}/api/routing/rules", timeout=30)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["rules"]["applies_to"] == "signalmar.v3"
    p = body["params"]
    assert p["margin_default_m"] == 50.0
    assert p["margin_reduced_m"] == 20.0
    assert p["force_conventional_direction"] is True


def test_engine_c_visible_to_non_admin_in_engines_list(user):
    r = user.get(f"{BASE_URL}/api/routing/engines", timeout=30)
    assert r.status_code == 200, r.text[:300]
    engines = {e["id"]: e for e in r.json()["engines"]}
    assert "engine_c" in engines, f"Moteur C invisible pour NON-admin : {list(engines)}"
    assert engines["engine_c"]["algo"] == "signalmar.v3"
    assert engines["engine_c"]["active"] is True


def test_non_admin_can_compute_with_engine_c(user):
    res = _compute(user, ILLUR_SEA, ILLUR_LAND, "engine_c")
    assert res["engine"]["algo"] == "signalmar.v3"
    assert "engine_rules" in res


# ── Couples multiples : jamais d'échec + champs propres ──────────────────
@pytest.mark.parametrize("start,end,label", [
    (ILLUR_SEA, ILLUR_LAND, "Illur SEA→LAND"),
    (GOLFE_A, GOLFE_B, "Golfe A→B"),
    (FRAGILE_START, FRAGILE_END, "Inter-bassins Loire→Golfe"),
])
def test_engine_c_never_fails_on_multiple_couples(user, start, end, label):
    res = _compute(user, start, end, "engine_c")
    assert res.get("waypoints"), f"[{label}] tracé vide"
    warnings_joined = " || ".join(res.get("warnings") or [])
    assert "Passage impossible" not in warnings_joined, f"[{label}] ne doit jamais échouer"
    # Marge latérale bornée à 20 ou 50 (règle 3)
    used = res.get("lateral_margin_used_m")
    assert used in (50.0, 20.0), f"[{label}] marge inattendue : {used}"
    # leg_margin_m fourni avec la bonne longueur
    legs = res.get("leg_margin_m")
    n = len(res["waypoints"]) - 1
    assert isinstance(legs, list) and len(legs) == n, f"[{label}] leg_margin_m : {legs}"
    # Indices compromised_legs dans les bornes + motif attendu
    reasons = res.get("leg_reasons") or {}
    for i in res.get("compromised_legs") or []:
        assert 0 <= i < n, f"[{label}] index rouge hors bornes : {i}"
        assert reasons.get(str(i)) in ("shallow", "low_margin"), \
            f"[{label}] tronçon {i} sans motif valide : {reasons.get(str(i))}"
    # Cohérence low_margin : tout leg <= 20 doit être compromis low_margin
    for i, m in enumerate(legs):
        if m is not None and m <= 20.0:
            assert i in (res.get("compromised_legs") or []), \
                f"[{label}] tronçon {i} marge={m} pas dans compromised_legs"
            assert reasons.get(str(i)) == "low_margin"


# ── Réversibilité multi-couples ──────────────────────────────────────────
@pytest.mark.parametrize("a,b,label", [
    (ILLUR_SEA, ILLUR_LAND, "Illur"),
    (GOLFE_A, GOLFE_B, "Golfe"),
    (FRAGILE_START, FRAGILE_END, "Inter-bassins"),
])
def test_engine_c_reversible_geometry(user, a, b, label):
    fwd = _compute(user, a, b, "engine_c")
    bwd = _compute(user, b, a, "engine_c")
    g1 = _geom(fwd)
    g2 = list(reversed(_geom(bwd)))
    assert g1 == g2, f"[{label}] géométrie non identique dans les deux sens"
    assert fwd["distance_m"] == bwd["distance_m"], f"[{label}] distance divergente"


# ── Non-régression Moteurs A/B (gelés) — champs Moteur C interdits ───────
def test_engine_a_does_not_expose_engine_c_fields(user):
    res = _compute(user, ILLUR_SEA, ILLUR_LAND, "engine_a")
    assert res["engine"]["algo"] == "signalmar.v1"
    for key in ("engine_rules", "leg_margin_m", "leg_reasons",
                "low_margin_legs", "side_fixed", "wrong_side_marks"):
        assert key not in res, f"engine_a ne doit PAS exposer {key}"


def test_engine_b_does_not_expose_engine_c_fields(user):
    res = _compute(user, ILLUR_SEA, ILLUR_LAND, "engine_b")
    assert res["engine"]["algo"] == "signalmar.v2"
    for key in ("engine_rules", "leg_margin_m", "leg_reasons"):
        assert key not in res, f"engine_b ne doit PAS exposer {key}"


def test_engine_b_deterministic(user):
    r1 = _compute(user, ILLUR_SEA, ILLUR_LAND, "engine_b")
    r2 = _compute(user, ILLUR_SEA, ILLUR_LAND, "engine_b")
    assert _geom(r1) == _geom(r2), "Moteur B doit rester déterministe"


# ── Route MANUELLE avec engine_c : waypoints imposés ─────────────────────
def test_manual_route_engine_c_preserves_waypoints(user):
    wps = [
        {"lat": 47.6100, "lng": -2.8500},
        {"lat": 47.6050, "lng": -2.8300},
        {"lat": 47.6000, "lng": -2.8100},
    ]
    r = user.post(
        f"{BASE_URL}/api/routes/manual",
        json={
            "waypoints": wps, "draft_m": 1.0, "depth_margin_m": 0.5,
            "engine_id": "engine_c", "use_tide": False,
        },
        timeout=120,
    )
    assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
    res = r.json()
    assert res["engine"]["algo"] == "signalmar.v3"
    got = [(round(w["lat"], 4), round(w["lng"], 4)) for w in res["waypoints"]]
    expected = [(round(w["lat"], 4), round(w["lng"], 4)) for w in wps]
    assert got == expected, f"Manual engine_c a modifié les waypoints : {got} vs {expected}"
