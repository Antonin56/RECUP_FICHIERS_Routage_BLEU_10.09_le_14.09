"""
E2E public-URL API tests for iter138 armateur QA audit fixes.
Covers: engines frozen + algo_version, strict engine_id resolution, job re-read,
P0 arrivée à terre snap, error codes (OTP/bbox/notification/duplicate reports),
dev switch gate.
"""
import os
import time
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
BYPASS = os.environ.get("RATE_LIMIT_BYPASS_TOKEN", "qa-bypass-signalmar-2026")
EMAIL = "antoninlepinay@gmail.com"
PASSWORD = "123454321"

HDR = {"Content-Type": "application/json", "X-RateLimit-Bypass": BYPASS}


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers=HDR,
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    tok = data.get("token") or data.get("access_token") or data.get("jwt")
    assert tok, f"no token in login response: {data}"
    return tok


@pytest.fixture(scope="module")
def auth_hdr(token):
    return {**HDR, "Authorization": f"Bearer {token}"}


# -------- Gel moteurs --------
class TestEnginesFrozen:
    def test_engines_expose_frozen_and_algo_version(self, auth_hdr):
        r = requests.get(f"{BASE_URL}/api/routing/engines", headers=auth_hdr, timeout=20)
        assert r.status_code == 200, r.text[:300]
        engines = r.json()
        # list or dict
        if isinstance(engines, dict) and "engines" in engines:
            engines = engines["engines"]
        assert isinstance(engines, list) and len(engines) >= 6
        by_id = {e["id"]: e for e in engines}
        for eid in ("engine_a", "engine_b", "engine_c", "engine_d", "engine_e"):
            assert eid in by_id, f"missing {eid}"
            assert by_id[eid].get("frozen") is True, f"{eid} not frozen: {by_id[eid]}"
            assert by_id[eid].get("algo_version"), f"{eid} missing algo_version"
        assert by_id["engine_f"].get("frozen") is False
        assert by_id["engine_f"].get("algo_version")

    def test_rename_frozen_engine_refused(self, auth_hdr):
        r = requests.patch(
            f"{BASE_URL}/api/routing/engines/engine_b",
            json={"name": "QA_PROBE"},
            headers=auth_hdr, timeout=20,
        )
        assert 400 <= r.status_code < 500, f"expected 4xx, got {r.status_code} {r.text[:200]}"

    def test_deactivate_frozen_engine_refused(self, auth_hdr):
        r = requests.post(
            f"{BASE_URL}/api/routing/engines/engine_e/active",
            json={"active": False},
            headers=auth_hdr, timeout=20,
        )
        assert 400 <= r.status_code < 500, f"expected 4xx, got {r.status_code} {r.text[:200]}"

    def test_include_inactive_admin(self, auth_hdr):
        r = requests.get(
            f"{BASE_URL}/api/routing/engines?include_inactive=true",
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 200


# -------- Résolution stricte --------
class TestStrictEngineResolution:
    def test_unknown_engine_404(self, auth_hdr):
        r = requests.post(
            f"{BASE_URL}/api/routes/compute/async",
            json={
                "start": {"lat": 47.5455, "lng": -2.9185},
                "end":   {"lat": 47.5870, "lng": -2.7820},
                "draft_m": 1.5,
                "depth_margin_m": 0.5,
                "engine_id": "engine_inexistant",
            },
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text[:200]}"

    def test_recompute_unknown_saved_route_404(self, auth_hdr):
        r = requests.post(
            f"{BASE_URL}/api/routes/saved/id_inexistant_xyz_123/recompute/async",
            json={"engine_ids": ["engine_f"]},
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text[:200]}"


# -------- Job relisible --------
def _poll_job(auth_hdr, job_id, timeout_s=300):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/api/routes/job/{job_id}", headers=auth_hdr, timeout=30)
        assert r.status_code == 200, f"job poll {r.status_code} {r.text[:200]}"
        js = r.json()
        st = js.get("status")
        if st in ("done", "error", "failed"):
            return js
        time.sleep(2.0)
    raise AssertionError(f"job {job_id} did not finish in {timeout_s}s")


class TestJobRereadable:
    def test_job_readable_after_done_multiple_reads(self, auth_hdr):
        r = requests.post(
            f"{BASE_URL}/api/routes/compute/async",
            json={
                "start": {"lat": 47.5455, "lng": -2.9185},
                "end":   {"lat": 47.5870, "lng": -2.7820},
                "draft_m": 1.5,
                "depth_margin_m": 0.5,
                "engine_id": "engine_f",
            },
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code in (200, 202), f"{r.status_code} {r.text[:300]}"
        job_id = r.json().get("job_id") or r.json().get("id")
        assert job_id, r.text[:300]
        first = _poll_job(auth_hdr, job_id)
        assert first["status"] == "done", first
        assert first.get("result")
        # Re-read twice
        for i in range(2):
            r2 = requests.get(f"{BASE_URL}/api/routes/job/{job_id}", headers=auth_hdr, timeout=20)
            assert r2.status_code == 200, f"re-read #{i}: {r2.status_code} {r2.text[:200]}"
            js2 = r2.json()
            assert js2.get("status") == "done"
            assert js2.get("result"), f"result missing on re-read #{i}"


# -------- P0 arrivée à terre --------
class TestP0ArriveeATerre:
    @pytest.fixture(scope="class")
    def _f_result(self, auth_hdr):
        r = requests.post(
            f"{BASE_URL}/api/routes/compute/async",
            json={
                "start": {"lat": 47.515, "lng": -2.93},
                "end":   {"lat": 47.548, "lng": -2.905},
                "draft_m": 1.5,
                "depth_margin_m": 0.5,
                "engine_id": "engine_f",
            },
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code in (200, 202), r.text[:300]
        job_id = r.json().get("job_id") or r.json().get("id")
        js = _poll_job(auth_hdr, job_id)
        assert js["status"] == "done", js
        return js["result"]

    def test_end_snapped_arrivee_a_terre(self, _f_result):
        es = _f_result.get("end_snapped") or {}
        assert es.get("reason") == "arrivee_a_terre", f"end_snapped={es}"

    def test_min_depth_safe(self, _f_result):
        min_d = _f_result.get("min_depth_m")
        assert min_d is not None
        assert min_d >= -3.5, f"min_depth_m {min_d} < -3.5"

    def test_warning_present(self, _f_result):
        warnings = _f_result.get("warnings") or []
        joined = " | ".join(warnings)
        assert any(w.startswith("⚠ ARRIVÉE DEMANDÉE À TERRE") for w in warnings), f"warnings={warnings}"

    def test_engine_e_regression_bug_frozen(self, auth_hdr):
        r = requests.post(
            f"{BASE_URL}/api/routes/compute/async",
            json={
                "start": {"lat": 47.515, "lng": -2.93},
                "end":   {"lat": 47.548, "lng": -2.905},
                "draft_m": 1.5,
                "depth_margin_m": 0.5,
                "engine_id": "engine_e",
            },
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code in (200, 202), r.text[:300]
        job_id = r.json().get("job_id") or r.json().get("id")
        js = _poll_job(auth_hdr, job_id)
        assert js["status"] == "done", js
        result = js["result"]
        min_d = result.get("min_depth_m")
        # Bug historique attendu (moteur E figé)
        assert min_d is not None
        assert min_d < -5, f"engine_e expected historic bug min_depth < -5, got {min_d}"


# -------- Codes d'erreur --------
class TestErrorCodes:
    def test_otp_wrong_code_400(self):
        # request first (mock — should succeed)
        r1 = requests.post(
            f"{BASE_URL}/api/auth/otp/request",
            json={"phone": "0699999999"},
            headers=HDR, timeout=20,
        )
        # request may 200 or 429; just ensure verify with wrong code → 400
        r = requests.post(
            f"{BASE_URL}/api/auth/otp/verify",
            json={"phone": "0699999999", "code": "000000"},
            headers=HDR, timeout=20,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:200]} (req={r1.status_code})"

    def test_bbox_inverted_422(self, auth_hdr):
        # bbox param inverted (lng_min>lng_max, lat_min>lat_max)
        r = requests.get(
            f"{BASE_URL}/api/bathy/seamarks?bbox=-2.8,47.7,-2.9,47.6",
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text[:200]}"

    def test_notification_unknown_404(self, auth_hdr):
        r = requests.post(
            f"{BASE_URL}/api/notifications/id_inconnu_zzz/read",
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text[:200]}"

    def test_duplicate_report_returns_duplicate_true(self, auth_hdr):
        payload = {
            "type": "obstacle_nav",
            "lat": 47.55 + (time.time() % 1) * 0.0001,
            "lng": -2.92,
            "description": "QA duplicate iter138",
        }
        r1 = requests.post(f"{BASE_URL}/api/reports", json=payload, headers=auth_hdr, timeout=20)
        # 1st either 200/201
        assert r1.status_code in (200, 201), f"first: {r1.status_code} {r1.text[:200]}"
        # 2nd within 90s — same type/pos
        r2 = requests.post(f"{BASE_URL}/api/reports", json=payload, headers=auth_hdr, timeout=20)
        assert r2.status_code in (200, 201, 409), f"second: {r2.status_code} {r2.text[:200]}"
        body = r2.json()
        assert body.get("duplicate") is True, f"expected duplicate=true, got {body}"


# -------- /api/dev gate --------
class TestDevSwitchGate:
    def test_dev_switch_reachable_when_enabled(self, auth_hdr):
        # ALLOW_DEV_SWITCH=true in backend/.env
        r = requests.get(f"{BASE_URL}/api/dev/test-accounts", headers=auth_hdr, timeout=15)
        # Either 200 or 401/403 depending on auth semantics — main requirement: gate present, not 404
        assert r.status_code != 404, f"dev route missing: {r.status_code} {r.text[:200]}"
