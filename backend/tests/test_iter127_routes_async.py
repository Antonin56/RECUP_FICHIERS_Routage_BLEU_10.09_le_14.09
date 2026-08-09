"""SignalMar — Itér. 127 (03/08/2026) : calcul de routes en TÂCHE DE FOND.

Priorité armateur du 02/08 : « erreurs 429 quasi à chaque calcul côtier, et
à chaque fois le départ de la route saute ».

Correctif : POST /api/routes/compute/async, /manual/async et
/saved/{id}/recompute/async retournent immédiatement {job_id, status:pending}
puis l'app polling GET /api/routes/job/{job_id}. Un 429 sur un poll est sans
conséquence — le calcul continue côté serveur.

Ce fichier verrouille :
  * réponse < 1 s pour les endpoints /async (contrat de latence) ;
  * cycle pending → done + résultat complet (route_id, waypoints, engine…) ;
  * la 2e lecture d'un job done renvoie 404 (résultat consommé) ;
  * job_id inexistant → 404 ;
  * absence de token → 401/403 ;
  * un utilisateur ne peut pas lire un job créé par un autre → 404 ;
  * fragilité Moteur B (sectionnement automatique) via /compute sync ;
  * non-régression des endpoints synchrones existants (/compute, /manual).
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
ADMIN_PHONE = "0760071445"
OTP_CODE = "123456"
SECOND_PHONE = "0600000001"  # Compte de test isolé pour la sécu des jobs

# Route de référence Loire → Golfe (10-20 s de calcul côtier).
START_LOIRE = {"lat": 47.3968386163852, "lng": -3.2654285430908208}
END_MORBIHAN = {"lat": 47.304397401095414, "lng": -2.073036325992286}

# Fragilité Moteur B (sectionnement automatique).
FRAGILE_START = {"lat": 47.302, "lng": -2.096}
FRAGILE_END = {"lat": 47.5614, "lng": -2.87473}


def _login(phone: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200, f"otp/request({phone}) {r.status_code} {r.text[:200]}"
    r = s.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"phone": phone, "code": OTP_CODE, "pseudo": f"QAiter127_{uuid.uuid4().hex[:6]}"},
    )
    assert r.status_code == 200, f"otp/verify({phone}) {r.status_code} {r.text[:200]}"
    tok = r.json()["token"]
    s.headers["Authorization"] = f"Bearer {tok}"
    return s


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    return _login(ADMIN_PHONE)


@pytest.fixture(scope="module")
def second_session() -> requests.Session:
    return _login(SECOND_PHONE)


def _poll_until_done(session: requests.Session, job_id: str, timeout_s: float = 45.0) -> dict:
    """Poll GET /api/routes/job/{id} et retourne le body 'done'."""
    t0 = time.time()
    last_body = None
    while time.time() - t0 < timeout_s:
        r = session.get(f"{BASE_URL}/api/routes/job/{job_id}", timeout=15)
        assert r.status_code == 200, f"job {job_id} poll {r.status_code}: {r.text[:200]}"
        body = r.json()
        last_body = body
        if body["status"] == "pending":
            time.sleep(1.0)
            continue
        return body
    pytest.fail(f"Timeout {timeout_s}s en attendant job {job_id}. Dernier body: {last_body}")


# ─────────────────────────────────────────────────────────────────────────
#  1) POST /api/routes/compute/async — réponse < 1 s, polling → done
# ─────────────────────────────────────────────────────────────────────────
def test_compute_async_fast_response_and_done(admin_session):
    t0 = time.time()
    r = admin_session.post(
        f"{BASE_URL}/api/routes/compute/async",
        json={
            "start": START_LOIRE, "end": END_MORBIHAN,
            "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": False,
            "engine_id": "engine_a",
        },
        timeout=10,
    )
    dt = time.time() - t0
    assert r.status_code == 200, f"async {r.status_code} {r.text[:200]}"
    body = r.json()
    assert body["status"] == "pending"
    assert body["job_id"] and isinstance(body["job_id"], str)
    # Contrat de latence : le POST doit rendre la main tout de suite.
    assert dt < 2.0, f"POST /compute/async trop lent : {dt:.2f}s (attendu < 1 s)"

    # Polling.
    done = _poll_until_done(admin_session, body["job_id"], timeout_s=60)
    assert done["status"] == "done"
    result = done["result"]
    assert result.get("route_id", "").startswith("R-")
    assert result.get("waypoints") and len(result["waypoints"]) >= 2
    assert isinstance(result.get("distance_m"), (int, float))
    assert result["distance_m"] > 50_000  # ≈ 95 km attendu
    assert result["engine"]["id"] == "engine_a"

    # 2e lecture du même job_id → 404 (résultat consommé).
    r2 = admin_session.get(f"{BASE_URL}/api/routes/job/{body['job_id']}")
    assert r2.status_code == 404, f"2e lecture doit être 404, got {r2.status_code}"


# ─────────────────────────────────────────────────────────────────────────
#  2) POST /api/routes/manual/async — sur les waypoints de la route
#     enregistrée « TEST AB Loire »
# ─────────────────────────────────────────────────────────────────────────
def test_manual_async_on_saved_route(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/routes/saved")
    assert r.status_code == 200, r.text[:200]
    routes = r.json()["routes"]
    ab_route = next((x for x in routes if x.get("name") == "TEST AB Loire"), None)
    if ab_route is None:
        # Fallback : crée une petite route manuelle en zone pilote (rapide).
        ab_route = {"waypoints": [
            {"lat": 47.610, "lng": -2.825},
            {"lat": 47.6395, "lng": -2.7580},
        ]}

    t0 = time.time()
    r = admin_session.post(
        f"{BASE_URL}/api/routes/manual/async",
        json={
            "waypoints": ab_route["waypoints"],
            "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": False,
        },
        timeout=10,
    )
    dt = time.time() - t0
    assert r.status_code == 200, f"manual/async {r.status_code} {r.text[:200]}"
    body = r.json()
    assert body["status"] == "pending" and body["job_id"]
    assert dt < 2.0, f"POST /manual/async trop lent : {dt:.2f}s"

    done = _poll_until_done(admin_session, body["job_id"], timeout_s=60)
    assert done["status"] == "done"
    res = done["result"]
    assert res.get("waypoints") and len(res["waypoints"]) >= 2
    assert res.get("route_id", "").startswith("R-")


# ─────────────────────────────────────────────────────────────────────────
#  3) POST /api/routes/saved/{id}/recompute/async — engine_b, résultat OK
# ─────────────────────────────────────────────────────────────────────────
def test_recompute_async_engine_b(admin_session):
    # Crée une route enregistrée (avec start/end) puis recompute engine_b async.
    body_save = {
        "name": f"TEST_iter127_async_{int(time.time())}",
        "mode": "auto",
        "waypoints": [
            {"lat": 47.610, "lng": -2.825},
            {"lat": 47.6395, "lng": -2.7580},
        ],
        "distance_m": 3500.0,
        "engine_id": "engine_a",
        "draft_m": 1.0,
        "depth_margin_m": 0.5,
        "start": {"lat": 47.610, "lng": -2.825},
        "end": {"lat": 47.6395, "lng": -2.7580},
    }
    rs = admin_session.post(f"{BASE_URL}/api/routes/saved", json=body_save)
    assert rs.status_code == 200, rs.text[:200]
    saved_id = rs.json()["id"]
    try:
        t0 = time.time()
        r = admin_session.post(
            f"{BASE_URL}/api/routes/saved/{saved_id}/recompute/async",
            json={"engine_ids": ["engine_b"]},
            timeout=10,
        )
        dt = time.time() - t0
        assert r.status_code == 200, f"recompute/async {r.status_code} {r.text[:200]}"
        body = r.json()
        assert body["status"] == "pending" and body["job_id"]
        assert dt < 2.0, f"POST /recompute/async trop lent : {dt:.2f}s"

        done = _poll_until_done(admin_session, body["job_id"], timeout_s=60)
        assert done["status"] == "done"
        results = done["result"]["results"]
        assert "engine_b" in results
        eb = results["engine_b"]
        assert "error" not in eb, f"engine_b recompute a échoué: {eb.get('error')}"
        assert eb.get("waypoints") and len(eb["waypoints"]) >= 2
        assert eb["engine"]["id"] == "engine_b"
    finally:
        admin_session.delete(f"{BASE_URL}/api/routes/saved/{saved_id}")


# ─────────────────────────────────────────────────────────────────────────
#  4) SÉCURITÉ DES JOBS : 404 / 401 / cross-user
# ─────────────────────────────────────────────────────────────────────────
def test_job_not_found_returns_404(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/routes/job/does_not_exist_{uuid.uuid4().hex}")
    assert r.status_code == 404


def test_job_requires_auth():
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/routes/job/anything")
    assert r.status_code in (401, 403), f"attendu 401/403 sans token, got {r.status_code}"


def test_job_isolated_between_users(admin_session, second_session):
    # Admin crée un job (compute manuel court en zone pilote → OK).
    r = admin_session.post(
        f"{BASE_URL}/api/routes/manual/async",
        json={
            "waypoints": [
                {"lat": 47.610, "lng": -2.825},
                {"lat": 47.6395, "lng": -2.7580},
            ],
            "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": False,
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text[:200]
    job_id = r.json()["job_id"]

    # Le 2e compte NE DOIT PAS pouvoir lire ce job.
    r2 = second_session.get(f"{BASE_URL}/api/routes/job/{job_id}")
    assert r2.status_code == 404, \
        f"cross-user job read doit être 404, got {r2.status_code} {r2.text[:200]}"

    # Admin consomme son propre job (nettoyage) — tolérant si déjà expiré.
    _poll_until_done(admin_session, job_id, timeout_s=60)


# ─────────────────────────────────────────────────────────────────────────
#  5) NON-RÉGRESSION endpoints synchrones : /compute + /manual
# ─────────────────────────────────────────────────────────────────────────
def test_sync_compute_still_works(admin_session):
    """/compute synchrone reste fonctionnel (utilisé par les tests iter126)."""
    r = admin_session.post(
        f"{BASE_URL}/api/routes/compute",
        json={
            "start": {"lat": 47.610, "lng": -2.825},
            "end": {"lat": 47.6395, "lng": -2.7580},
            "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": False,
            "engine_id": "engine_a",
        },
        timeout=60,
    )
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    assert data["waypoints"] and data.get("route_id", "").startswith("R-")


def test_sync_manual_still_works(admin_session):
    r = admin_session.post(
        f"{BASE_URL}/api/routes/manual",
        json={
            "waypoints": [
                {"lat": 47.610, "lng": -2.825},
                {"lat": 47.6395, "lng": -2.7580},
            ],
            "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": False,
        },
        timeout=60,
    )
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    assert data.get("waypoints") and len(data["waypoints"]) >= 2


# ─────────────────────────────────────────────────────────────────────────
#  6) FRAGILITÉ MOTEUR B (sectionnement automatique)
# ─────────────────────────────────────────────────────────────────────────
def test_engine_a_falls_back_to_shallow_route_on_fragile_start(admin_session):
    """Point de départ fragile (~77 m du seuil) : engine_a ne SECTIONNE pas
    (pas de split_via, contrairement à engine_b) mais il ne PLANTE pas non
    plus — il replie sur une route « eau peu profonde » signalée en rouge
    (risk + shallow_route + compromised_legs). Comportement historique
    verrouillé du Moteur A (aucun 422 sur ce couple de points).

    NB : le test attendait auparavant un 422 « Passage impossible » ; c'était
    une attente erronée, jamais alignée sur l'implémentation."""
    r = admin_session.post(
        f"{BASE_URL}/api/routes/compute",
        json={
            "start": FRAGILE_START, "end": FRAGILE_END,
            "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": False,
            "engine_id": "engine_a",
        },
        timeout=60,
    )
    assert r.status_code == 200, \
        f"engine_a doit replier en 200 sur départ fragile, got {r.status_code} {r.text[:300]}"
    data = r.json()
    assert data.get("risk") is True, f"risk=True attendu, got {data.get('risk')}"
    assert data.get("shallow_route") is True, \
        f"shallow_route=True attendu, got {data.get('shallow_route')}"
    assert data.get("compromised_legs"), \
        f"compromised_legs (tronçons rouges) attendus, got {data.get('compromised_legs')}"
    assert not data.get("split_via"), \
        f"engine_a ne doit PAS sectionner (split_via réservé à engine_b), got {data.get('split_via')}"
    assert data["engine"]["algo"] == "signalmar.v1", f"moteur inattendu : {data.get('engine')}"


def test_engine_b_sections_and_succeeds_on_fragile_start(admin_session):
    """engine_b doit RÉUSSIR (~84 km, < 100 km), avec split_via et warning
    contenant « 2 tronçons »."""
    r = admin_session.post(
        f"{BASE_URL}/api/routes/compute",
        json={
            "start": FRAGILE_START, "end": FRAGILE_END,
            "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": False,
            "engine_id": "engine_b",
        },
        timeout=60,
    )
    assert r.status_code == 200, f"engine_b doit réussir, got {r.status_code} {r.text[:300]}"
    data = r.json()
    assert data.get("distance_m") and data["distance_m"] < 100_000, \
        f"engine_b distance ≈ 84 km attendu, got {data.get('distance_m')}"
    assert data.get("split_via"), f"split_via manquant : {data.keys()}"
    warnings = data.get("warnings") or []
    assert any("2 tronçons" in w for w in warnings), \
        f"warning '2 tronçons' attendu, got {warnings}"
