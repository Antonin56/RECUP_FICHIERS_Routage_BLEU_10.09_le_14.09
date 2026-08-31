"""ITER149 — Jobs de routage persistés en base (route_jobs).

Vérifie le fix ITER149 : les jobs de calcul asynchrone (POST
/api/routes/compute/async et /api/routes/manual/async) sont stockés dans
la collection MongoDB ``route_jobs`` (index TTL 900 s) au lieu d'un dict
en mémoire de process. But : plus de 404 « Calcul introuvable (expiré) »
en multi-instances.

Contrat testé :
  1. POST /compute/async → job_id ; poll /job/{job_id} → done avec
     result.distance_m ≈ 8922 m ; aucun 404 pendant le calcul.
  2. PERSISTANCE INTER-PROCESS : après un job done, RESTART backend, puis
     GET /job/{job_id} → toujours done avec le même result.
  3. Base : collection route_jobs contient le doc ; index TTL ts_1
     expireAfterSeconds=900.
  4. Sécurité : job_id inconnu → 404 « Calcul introuvable (expiré) ».
  5. Route manuelle async : POST /manual/async → poll done.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import pytest
import requests
from pymongo import MongoClient

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL") or "").rstrip("/") \
    or "http://localhost:8001"
QA = {"X-RateLimit-Bypass": os.environ.get(
    "RATE_LIMIT_BYPASS_TOKEN", "qa-bypass-signalmar-2026")}
EMAIL = "antoninlepinay@gmail.com"
PWD = "123454321"

# Route de référence ITER144/149
START = {"lat": 47.67755575752677, "lng": -3.4287631920085064}
END = {"lat": 47.72987102630925, "lng": -3.3567713137773514}


def _mongo_env() -> tuple[str, str]:
    """Lit MONGO_URL/DB_NAME depuis backend/.env sans polluer l'env test."""
    url = os.environ.get("MONGO_URL")
    db = os.environ.get("DB_NAME")
    if url and db:
        return url, db
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("MONGO_URL"):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("DB_NAME"):
                db = line.split("=", 1)[1].strip().strip('"').strip("'")
    assert url and db, "MONGO_URL/DB_NAME introuvables"
    return url, db


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", headers=QA, timeout=60,
                      json={"email": EMAIL, "password": PWD})
    assert r.status_code == 200, r.text[:200]
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, r.text[:200]
    return tok


@pytest.fixture(scope="module")
def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", **QA}


@pytest.fixture(scope="module")
def mongo():
    url, db = _mongo_env()
    client = MongoClient(url, serverSelectionTimeoutMS=3000)
    yield client[db]
    client.close()


def _poll_job(auth: dict, job_id: str, timeout_s: float = 60.0) -> dict:
    """Poll /job/{job_id} jusqu'à done/error. Assert : aucun 404 pendant."""
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout_s:
        r = requests.get(f"{BASE_URL}/api/routes/job/{job_id}",
                         headers=auth, timeout=30)
        # Le fix ITER149 garantit : aucun 404 pendant le calcul.
        assert r.status_code != 404, (
            f"404 pendant le calcul (ITER149 régression) : {r.text[:200]}")
        assert r.status_code == 200, r.text[:200]
        last = r.json()
        st = last.get("status")
        if st in ("done", "error"):
            return last
        time.sleep(1.0)
    pytest.fail(f"Job non terminé en {timeout_s}s : {last}")


# ── 1. Compute async → poll done ────────────────────────────────────────
class TestComputeAsync:
    def test_compute_async_returns_job_id_and_completes(
        self, auth: dict, mongo: Any,
    ) -> None:
        body = {
            "start": START, "end": END,
            "draft_m": 1.5, "depth_margin_m": 0.5,
            "use_tide": False, "engine_id": "engine_i",
        }
        r = requests.post(f"{BASE_URL}/api/routes/compute/async",
                          headers=auth, json=body, timeout=30)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert data.get("status") == "pending", data
        job_id = data.get("job_id")
        assert isinstance(job_id, str) and len(job_id) == 32, data

        # Vérifie que le job est bien créé en base (pas en mémoire).
        doc = mongo.route_jobs.find_one({"_id": job_id})
        assert doc is not None, "job absent de MongoDB.route_jobs"
        assert doc.get("uid"), doc
        assert doc.get("status") in ("pending", "done"), doc

        # Poll jusqu'à done.
        final = _poll_job(auth, job_id, timeout_s=90.0)
        assert final.get("status") == "done", final
        res = final.get("result") or {}
        dist = res.get("distance_m")
        assert dist is not None, final
        # Référence smoke : ~8922 m — tolérance large.
        assert 7500 <= float(dist) <= 10500, f"distance inattendue: {dist}"

        # Stocke pour les tests suivants (persistance + relecture).
        pytest.compute_job_id = job_id  # type: ignore[attr-defined]
        pytest.compute_result_dist = float(dist)  # type: ignore[attr-defined]


# ── 2. Persistance INTER-PROCESS : survie au restart ────────────────────
class TestPersistenceAcrossRestart:
    def test_job_survives_backend_restart(
        self, auth: dict, mongo: Any,
    ) -> None:
        """CŒUR du fix ITER149 : le job doit rester lisible après un
        redémarrage complet du backend (équivalent multi-instances)."""
        job_id = getattr(pytest, "compute_job_id", None)
        expected_dist = getattr(pytest, "compute_result_dist", None)
        if not job_id or expected_dist is None:
            pytest.skip("Prérequis : test_compute_async_returns_job_id_and_completes")

        # Confirme d'abord la lecture pré-restart.
        r0 = requests.get(f"{BASE_URL}/api/routes/job/{job_id}",
                          headers=auth, timeout=15)
        assert r0.status_code == 200 and r0.json().get("status") == "done", r0.text[:200]

        # Restart backend via supervisor.
        subprocess.run(["sudo", "supervisorctl", "restart", "backend"],
                       check=True, timeout=30)
        # Attendre que le backend soit de nouveau up.
        t0 = time.time()
        while time.time() - t0 < 30:
            try:
                h = requests.get(f"{BASE_URL}/api/", headers=QA, timeout=3)
                if h.status_code < 500:
                    break
            except requests.RequestException:
                pass
            time.sleep(1.0)
        # Petite marge après réponse.
        time.sleep(2.0)

        # Le job doit être encore lisible (base partagée).
        r = requests.get(f"{BASE_URL}/api/routes/job/{job_id}",
                         headers=auth, timeout=30)
        assert r.status_code == 200, (
            f"Job perdu après restart (fix ITER149 KO) : "
            f"{r.status_code} {r.text[:200]}")
        data = r.json()
        assert data.get("status") == "done", data
        res = data.get("result") or {}
        assert res.get("distance_m") == expected_dist, (
            f"Résultat modifié post-restart : {res.get('distance_m')} "
            f"vs {expected_dist}")


# ── 3. Vérification base + index TTL ─────────────────────────────────────
class TestJobsCollectionAndTTL:
    def test_route_jobs_ttl_index(self, auth: dict, mongo: Any) -> None:
        # Assure la création de l'index (via un premier appel async).
        body = {"start": START, "end": END, "draft_m": 1.5,
                "depth_margin_m": 0.5, "use_tide": False,
                "engine_id": "engine_i"}
        r = requests.post(f"{BASE_URL}/api/routes/compute/async",
                          headers=auth, json=body, timeout=15)
        assert r.status_code == 200, r.text[:200]

        idx = mongo.route_jobs.index_information()
        # Cherche un index sur ``ts`` avec expireAfterSeconds=900.
        ttl_found = False
        for name, spec in idx.items():
            keys = spec.get("key") or []
            if any(k[0] == "ts" for k in keys) and \
                    spec.get("expireAfterSeconds") == 900:
                ttl_found = True
                break
        assert ttl_found, f"Index TTL ts/900s absent : {idx}"


# ── 4. Sécurité : job inconnu / autre utilisateur → 404 ──────────────────
class TestJobSecurity:
    def test_unknown_job_id_returns_404(self, auth: dict) -> None:
        r = requests.get(f"{BASE_URL}/api/routes/job/deadbeef",
                         headers=auth, timeout=15)
        assert r.status_code == 404, r.text[:200]
        detail = (r.json() or {}).get("detail", "")
        assert "introuvable" in detail.lower() or "expiré" in detail.lower(), detail


# ── 5. Route manuelle async ──────────────────────────────────────────────
class TestManualAsync:
    def test_manual_async_completes(self, auth: dict) -> None:
        body = {
            "waypoints": [
                {"lat": 47.6776, "lng": -3.4288},
                {"lat": 47.6893, "lng": -3.3798},
            ],
            "draft_m": 1.5, "depth_margin_m": 0.5, "use_tide": False,
        }
        r = requests.post(f"{BASE_URL}/api/routes/manual/async",
                          headers=auth, json=body, timeout=30)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        job_id = data.get("job_id")
        assert data.get("status") == "pending" and job_id, data

        final = _poll_job(auth, job_id, timeout_s=60.0)
        assert final.get("status") == "done", final
        res = final.get("result") or {}
        assert res.get("distance_m") is not None, res
        assert float(res["distance_m"]) > 0, res
