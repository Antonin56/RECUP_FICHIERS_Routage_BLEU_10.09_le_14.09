"""SignalMar — Itér. 126 (02/08/2026) : tests **API** multi-moteurs.

Couvre les 5 exigences backend du review_request :
  * GET /api/routing/engines — engine_a + engine_b, is_admin=True pour admin.
  * POST /api/routes/compute — engine_a vs engine_b sur la route Fernais 25.
    B : 0 warning contenant 'balise', A : au moins 1 ; B <= A * 1.01 en
    distance, B.min_depth_m >= A.min_depth_m - 0.05.
  * POST /api/routes/saved (avec start/end) puis /saved/{id}/recompute —
    engine_a + engine_b : les 2 doivent réussir (aucun 'error' dans results).
  * Non-régression zone pilote (Morbihan) — waypoints A == B strict.
  * POST /api/routing/engines/duplicate (admin) — ID engine_c indépendant du
    nom, PATCH pour renommer → ID inchangé, DELETE pour nettoyer.
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
ADMIN_PHONE = "0760071445"
OTP_CODE = "123456"

START_LOIRE = {"lat": 47.30330604878526, "lng": -2.0971425094619605}
END_MORBIHAN = {"lat": 47.56115369856387, "lng": -2.8754832035414895}

PILOTE_START = {"lat": 47.610, "lng": -2.825}
PILOTE_END = {"lat": 47.6395, "lng": -2.7580}


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    # OTP request + verify (mocked, code 123456)
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": ADMIN_PHONE})
    assert r.status_code == 200, f"otp/request {r.status_code} {r.text[:200]}"
    r = s.post(f"{BASE_URL}/api/auth/otp/verify",
               json={"phone": ADMIN_PHONE, "code": OTP_CODE})
    assert r.status_code == 200, f"otp/verify {r.status_code} {r.text[:200]}"
    data = r.json()
    token = data["token"]
    s.headers["Authorization"] = f"Bearer {token}"
    return s


# ── (1) GET /api/routing/engines ─────────────────────────────────────────
def test_list_engines_a_b_admin(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/routing/engines")
    assert r.status_code == 200, r.text
    data = r.json()
    ids = [e["id"] for e in data["engines"]]
    assert "engine_a" in ids
    assert "engine_b" in ids
    assert data["is_admin"] is True
    # verify algos are correctly bound
    by_id = {e["id"]: e for e in data["engines"]}
    assert by_id["engine_a"]["algo"] == "signalmar.v1"
    assert by_id["engine_b"]["algo"] == "signalmar.v2"


# ── (2) compute engine_a vs engine_b — Fernais 25 correction ─────────────
@pytest.fixture(scope="module")
def compute_a_b(admin_session):
    body = {
        "start": START_LOIRE, "end": END_MORBIHAN,
        "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": False,
    }
    ra = admin_session.post(f"{BASE_URL}/api/routes/compute",
                            json={**body, "engine_id": "engine_a"}, timeout=60)
    rb = admin_session.post(f"{BASE_URL}/api/routes/compute",
                            json={**body, "engine_id": "engine_b"}, timeout=60)
    assert ra.status_code == 200, f"engine_a compute {ra.status_code} {ra.text[:300]}"
    assert rb.status_code == 200, f"engine_b compute {rb.status_code} {rb.text[:300]}"
    return ra.json(), rb.json()


def test_compute_engine_meta(compute_a_b):
    a, b = compute_a_b
    assert a.get("route_id", "").startswith("R-")
    assert b.get("route_id", "").startswith("R-")
    assert a["engine"]["id"] == "engine_a"
    assert a["engine"]["algo"] == "signalmar.v1"
    assert b["engine"]["id"] == "engine_b"
    assert b["engine"]["algo"] == "signalmar.v2"


def test_engine_b_zero_balise_warning(compute_a_b):
    a, b = compute_a_b
    a_bal = [w for w in (a.get("warnings") or []) if "balise" in w.lower()]
    b_bal = [w for w in (b.get("warnings") or []) if "balise" in w.lower()]
    # A must contain at least one 'balise' warning (Fernais/No23 bug)
    assert len(a_bal) >= 1, f"engine_a doit avoir >=1 warning 'balise', got {a.get('warnings')}"
    # B must have 0
    assert len(b_bal) == 0, f"engine_b doit avoir 0 warning 'balise', got {b_bal}"


def test_engine_b_no_degradation(compute_a_b):
    a, b = compute_a_b
    assert b["distance_m"] <= a["distance_m"] * 1.01, \
        f"B dist {b['distance_m']} > A dist * 1.01 = {a['distance_m']*1.01}"
    assert b["min_depth_m"] >= a["min_depth_m"] - 0.05, \
        f"B min_depth {b['min_depth_m']} < A min_depth {a['min_depth_m']} - 0.05"


# ── (3) saved + recompute A+B — bug 'zone non navigable' corrigé ─────────
def test_saved_recompute_a_and_b_no_error(admin_session, compute_a_b):
    a, _ = compute_a_b
    # Save the route WITH start/end fields (new 02/08 requirement)
    save_body = {
        "name": f"TEST_iter126_{int(time.time())}",
        "mode": "auto",
        "waypoints": a["waypoints"],
        "distance_m": a["distance_m"],
        "engine_id": "engine_a",
        "engine_name": a["engine"]["name"],
        "algo_id": a["engine"]["algo"],
        "draft_m": 1.0,
        "depth_margin_m": 0.5,
        # lateral_margin_m ABSENT → mode AUTO (repli à 150m était le bug)
        "start": START_LOIRE,
        "end": END_MORBIHAN,
    }
    rs = admin_session.post(f"{BASE_URL}/api/routes/saved", json=save_body)
    assert rs.status_code == 200, f"save {rs.status_code} {rs.text[:300]}"
    saved = rs.json()
    saved_id = saved["id"]
    try:
        rr = admin_session.post(
            f"{BASE_URL}/api/routes/saved/{saved_id}/recompute",
            json={"engine_ids": ["engine_b", "engine_a"]},
            timeout=90,
        )
        assert rr.status_code == 200, f"recompute {rr.status_code} {rr.text[:400]}"
        data = rr.json()
        results = data["results"]
        assert set(results.keys()) == {"engine_a", "engine_b"}
        for eid, res in results.items():
            assert "error" not in res, \
                f"{eid} recompute renvoie une erreur: {res.get('error')}"
            assert res.get("waypoints") and len(res["waypoints"]) >= 2, \
                f"{eid} recompute: tracé vide ({len(res.get('waypoints') or [])} wp)"
            assert res["engine"]["id"] == eid
    finally:
        admin_session.delete(f"{BASE_URL}/api/routes/saved/{saved_id}")


# ── (4) non-régression zone pilote — Morbihan maille 20 m ────────────────
def test_pilote_zone_a_equals_b(admin_session):
    body = {
        "start": PILOTE_START, "end": PILOTE_END,
        "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": False,
    }
    ra = admin_session.post(f"{BASE_URL}/api/routes/compute",
                            json={**body, "engine_id": "engine_a"}, timeout=60)
    rb = admin_session.post(f"{BASE_URL}/api/routes/compute",
                            json={**body, "engine_id": "engine_b"}, timeout=60)
    assert ra.status_code == 200, ra.text[:300]
    assert rb.status_code == 200, rb.text[:300]
    a, b = ra.json(), rb.json()
    assert a["waypoints"] == b["waypoints"], \
        "Zone pilote (maille 20m) : les waypoints A et B doivent être IDENTIQUES."


# ── (5) duplicate + rename + delete — ID stable indépendant du nom ───────
def test_duplicate_rename_delete_engine(admin_session):
    dup_name = f"TEST_iter126_dup_{int(time.time())}"
    r = admin_session.post(
        f"{BASE_URL}/api/routing/engines/duplicate",
        json={"source_id": "engine_a", "name": dup_name},
    )
    assert r.status_code == 200, f"duplicate {r.status_code} {r.text[:300]}"
    clone = r.json()["engine"]
    new_id = clone["id"]
    try:
        # ID must be independent of the name : format engine_[a-z]{1,2}
        assert new_id.startswith("engine_"), f"ID inattendu: {new_id}"
        suffix = new_id[len("engine_"):]
        assert suffix.isalpha() and 1 <= len(suffix) <= 2, \
            f"ID non alphabetique/court: {new_id}"
        assert new_id not in ("engine_a", "engine_b")
        # Not a slug of the name
        assert "test" not in new_id.lower(), \
            f"ID ne doit PAS être dérivé du nom : {new_id}"

        # Rename → id unchanged
        new_name = f"{dup_name}_RENAMED"
        r2 = admin_session.patch(
            f"{BASE_URL}/api/routing/engines/{new_id}",
            json={"name": new_name},
        )
        assert r2.status_code == 200, r2.text[:300]
        renamed = r2.json()["engine"]
        assert renamed["id"] == new_id, "L'ID ne doit PAS changer au renommage."
        assert renamed["name"] == new_name
    finally:
        rd = admin_session.delete(f"{BASE_URL}/api/routing/engines/{new_id}")
        assert rd.status_code == 200, f"delete cleanup failed: {rd.text[:200]}"
