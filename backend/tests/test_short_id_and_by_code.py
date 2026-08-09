"""Backend tests for the new short_id + by-code feature (12/07/2026).

Covers:
- POST /api/reports returns short_id (8 uppercase alphanum, no I/L/O/0/1)
- GET  /api/reports/{id} exposes short_id
- GET  /api/reports/by-code/{code} → case-insensitive, 422 (<4), 404 (unknown)
- GET  /api/reports list includes short_id per item
"""
import os
import re
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ["EXPO_PUBLIC_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"

# 8 chars, alphabet without I/L/O/0/1.
SHORT_RE = re.compile(r"^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{8}$")
ADMIN_PHONE = "0760071445"
OTP_CODE = "123456"


@pytest.fixture(scope="module")
def token():
    # Request OTP + verify with mocked code
    r = requests.post(f"{API}/auth/otp/request", json={"phone": ADMIN_PHONE}, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.post(
        f"{API}/auth/otp/verify",
        json={"phone": ADMIN_PHONE, "code": OTP_CODE},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    tok = r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def created_report(auth_headers):
    """Create one report at sea to run positive assertions against."""
    payload = {
        "type": "autre",
        "lat": 47.3,
        "lng": -3.2,
        "description": "TEST_short_id fixture",
        "photos": [],
    }
    r = requests.post(f"{API}/reports", json=payload, headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "id" in data and "short_id" in data, data
    return data


# ── short_id format on create ────────────────────────────────────────────
class TestCreateReportShortId:
    def test_create_returns_valid_short_id(self, created_report):
        sid = created_report["short_id"]
        assert isinstance(sid, str)
        assert SHORT_RE.match(sid), f"short_id malformed: {sid!r}"

    def test_detail_returns_same_short_id(self, created_report, auth_headers):
        rid = created_report["id"]
        r = requests.get(f"{API}/reports/{rid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail.get("short_id") == created_report["short_id"]
        assert SHORT_RE.match(detail["short_id"])


# ── by-code resolver ──────────────────────────────────────────────────────
class TestByCodeResolver:
    def test_by_code_uppercase(self, created_report, auth_headers):
        code = created_report["short_id"]
        r = requests.get(f"{API}/reports/by-code/{code}", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("id") == created_report["id"]
        assert body.get("short_id") == code
        assert "type" in body

    def test_by_code_case_insensitive(self, created_report, auth_headers):
        code = created_report["short_id"].lower()
        r = requests.get(f"{API}/reports/by-code/{code}", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("id") == created_report["id"]

    def test_by_code_unknown_returns_404_french(self, auth_headers):
        r = requests.get(f"{API}/reports/by-code/ZZZZ9999", headers=auth_headers, timeout=15)
        assert r.status_code == 404, r.text
        detail = r.json().get("detail", "")
        # French message
        assert "Aucun" in detail or "aucun" in detail, detail

    def test_by_code_too_short_returns_422(self, auth_headers):
        r = requests.get(f"{API}/reports/by-code/ABC", headers=auth_headers, timeout=15)
        assert r.status_code == 422, r.text


# ── list serializer includes short_id ────────────────────────────────────
class TestListSerializer:
    def test_list_reports_includes_short_id(self, auth_headers, created_report):
        r = requests.get(
            f"{API}/reports",
            headers=auth_headers,
            params={"lat": 47.3, "lng": -3.2, "radius_km": 500},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list) and len(items) > 0
        # Every item should carry a short_id (backfilled on read for legacy docs,
        # freshly generated for new ones).
        missing = [it for it in items if not it.get("short_id")]
        assert not missing, f"{len(missing)} items missing short_id"
        # All valid format.
        bad = [it["short_id"] for it in items if not SHORT_RE.match(it["short_id"] or "")]
        assert not bad, f"malformed short_ids: {bad[:5]}"

    def test_created_report_visible_in_list(self, auth_headers, created_report):
        r = requests.get(
            f"{API}/reports",
            headers=auth_headers,
            params={"lat": 47.3, "lng": -3.2, "radius_km": 500},
            timeout=20,
        )
        assert r.status_code == 200
        ids = {it["id"]: it.get("short_id") for it in r.json()}
        assert created_report["id"] in ids
        assert ids[created_report["id"]] == created_report["short_id"]
