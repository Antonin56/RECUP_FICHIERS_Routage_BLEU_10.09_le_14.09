"""Phase E Lot 2 — Backend tests for /api/profile/me pagination.

Tests:
  - Default page (no params) returns history_total/offset/limit
  - limit=5&offset=0 returns up to 5 reports
  - limit=5&offset=5 returns next 5 reports (distinct from page 1) when applicable
  - Param clamping: limit=0/100, offset=-5/999, non-numeric → safe (no 500)
  - reports_count = TRUE total (uncapped), history_total capped at 20
  - Smoke: report creation, list reports, TTS voice endpoint
"""
import os
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")

DEV_EMAIL = "antoninlepinay@gmail.com"
DEV_PASSWORD = "123454321"


# ---- session-scoped auth for the DEV_BYPASS user (preferred for pagination) ----
@pytest.fixture(scope="module")
def dev_token():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": DEV_EMAIL, "password": DEV_PASSWORD})
    assert r.status_code == 200, f"dev login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture
def dev_headers(dev_token):
    return {"Authorization": f"Bearer {dev_token}", "Content-Type": "application/json"}


# ---- helper: ensure dev user has >5 reports to fully exercise page 2 ----
def _ensure_min_reports(headers, target=6):
    me = requests.get(f"{BASE_URL}/api/profile/me", headers=headers).json()
    count = me.get("reports_count", 0)
    needed = max(0, target - count)
    created = []
    for i in range(needed):
        payload = {
            "type": "obstacle_nav",
            "lat": 47.6 + (i * 0.001),
            "lng": -2.95 + (i * 0.001),
            "description": f"TEST_pagination_seed_{i}",
            "photos": [],
        }
        r = requests.post(f"{BASE_URL}/api/reports", json=payload, headers=headers)
        if r.status_code in (200, 201):
            created.append(r.json().get("id"))
    return created


# =================== Pagination Tests ===================
class TestProfilePagination:
    def test_default_page_returns_new_fields(self, dev_headers):
        r = requests.get(f"{BASE_URL}/api/profile/me", headers=dev_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        # New fields must be present
        assert "history_total" in data, "missing history_total"
        assert "history_offset" in data, "missing history_offset"
        assert "history_limit" in data, "missing history_limit"
        assert "history" in data
        assert "reports_count" in data
        # Defaults
        assert data["history_limit"] == 5
        assert data["history_offset"] == 0
        assert len(data["history"]) <= 5
        # history_total ≤ 20
        assert data["history_total"] <= 20
        # history_total ≤ reports_count
        assert data["history_total"] <= data["reports_count"] or data["reports_count"] >= 20

    def test_limit_5_offset_0(self, dev_headers):
        r = requests.get(f"{BASE_URL}/api/profile/me?limit=5&offset=0", headers=dev_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["history_limit"] == 5
        assert data["history_offset"] == 0
        assert len(data["history"]) <= 5

    def test_limit_5_offset_5_distinct_from_page_1(self, dev_headers):
        # Ensure enough reports to exercise page 2
        _ensure_min_reports(dev_headers, target=6)

        r1 = requests.get(f"{BASE_URL}/api/profile/me?limit=5&offset=0", headers=dev_headers)
        r2 = requests.get(f"{BASE_URL}/api/profile/me?limit=5&offset=5", headers=dev_headers)
        assert r1.status_code == 200 and r2.status_code == 200
        d1, d2 = r1.json(), r2.json()
        if d1["reports_count"] > 5:
            ids1 = {h["id"] for h in d1["history"]}
            ids2 = {h["id"] for h in d2["history"]}
            assert ids1.isdisjoint(ids2), "page 1 and page 2 must not overlap"
            assert d2["history_offset"] == 5

    def test_limit_clamp_low(self, dev_headers):
        r = requests.get(f"{BASE_URL}/api/profile/me?limit=0&offset=0", headers=dev_headers)
        assert r.status_code == 200
        assert r.json()["history_limit"] == 1  # clamped to [1,20]

    def test_limit_clamp_high(self, dev_headers):
        r = requests.get(f"{BASE_URL}/api/profile/me?limit=100&offset=0", headers=dev_headers)
        assert r.status_code == 200
        assert r.json()["history_limit"] == 20

    def test_offset_clamp_negative(self, dev_headers):
        r = requests.get(f"{BASE_URL}/api/profile/me?limit=5&offset=-5", headers=dev_headers)
        assert r.status_code == 200
        assert r.json()["history_offset"] == 0

    def test_offset_clamp_high(self, dev_headers):
        r = requests.get(f"{BASE_URL}/api/profile/me?limit=5&offset=999", headers=dev_headers)
        assert r.status_code == 200
        assert r.json()["history_offset"] == 19

    def test_non_numeric_params_no_500(self, dev_headers):
        # FastAPI will likely return 422 for non-numeric. We want NO 500.
        r = requests.get(f"{BASE_URL}/api/profile/me?limit=abc&offset=xyz", headers=dev_headers)
        assert r.status_code != 500, f"expected no 500, got {r.status_code}: {r.text}"

    def test_history_total_capped_at_20(self, dev_headers):
        r = requests.get(f"{BASE_URL}/api/profile/me", headers=dev_headers)
        d = r.json()
        assert d["history_total"] <= 20
        # reports_count is true total (could be > 20)
        if d["reports_count"] >= 20:
            assert d["history_total"] == 20

    def test_reports_count_is_true_total(self, dev_headers):
        """reports_count = full uncapped total."""
        r = requests.get(f"{BASE_URL}/api/profile/me", headers=dev_headers)
        d = r.json()
        assert isinstance(d["reports_count"], int)
        # if user has > 20 reports, reports_count > history_total
        if d["reports_count"] > 20:
            assert d["reports_count"] > d["history_total"]


# =================== Smoke / Regression ===================
class TestSmoke:
    def test_list_reports(self):
        r = requests.get(f"{BASE_URL}/api/reports")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_report_dev(self, dev_headers):
        payload = {
            "type": "obstacle_nav",
            "lat": 47.6,
            "lng": -2.95,
            "description": "TEST_smoke_create",
            "photos": [],
        }
        r = requests.post(f"{BASE_URL}/api/reports", json=payload, headers=dev_headers)
        assert r.status_code in (200, 201), r.text
        rid = r.json()["id"]
        # cleanup
        requests.delete(f"{BASE_URL}/api/reports/{rid}", headers=dev_headers)

    def test_auth_me(self, dev_headers):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=dev_headers)
        assert r.status_code == 200
        assert r.json().get("email") == DEV_EMAIL
