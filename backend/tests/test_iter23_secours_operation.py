"""Iteration 23 — Secours activity='operation' (422 → 200) hotfix.

Validates Bug 1: ReportIn.activity Literal extended to include 'operation'.
Spec from review_request:
  POST /api/reports {type:'secours', subtype:'snsm', activity:'operation',
                     lat:47.40, lng:-3.20, description:'Test op'} → 200.
  Also verify 'navigation' still works (regression).
"""
import os
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

MAINT = {"email": "antoninlepinay@gmail.com", "password": "123454321"}


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def maint_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=MAINT, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


class TestSecoursOperation:
    created_ids: list = []

    def test_post_secours_operation_ok(self, maint_token):
        payload = {
            "type": "secours",
            "subtype": "snsm",
            "activity": "operation",
            "lat": 47.40,
            "lng": -3.20,
            "description": "TEST_iter23_secours_operation",
        }
        r = requests.post(f"{BASE_URL}/api/reports", json=payload,
                          headers=_hdr(maint_token), timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body["type"] == "secours"
        assert body["subtype"] == "snsm"
        assert body["activity"] == "operation", f"activity not persisted: {body}"
        TestSecoursOperation.created_ids.append(body["id"])

        # GET-after-POST to verify persistence
        rid = body["id"]
        g = requests.get(f"{BASE_URL}/api/reports/{rid}",
                         headers=_hdr(maint_token), timeout=10)
        assert g.status_code == 200
        assert g.json()["activity"] == "operation"

    def test_post_secours_navigation_regression(self, maint_token):
        payload = {
            "type": "secours",
            "subtype": "snsm",
            "activity": "navigation",
            "lat": 47.41,
            "lng": -3.21,
            "heading": 185,
            "speed_knots": 12,
            "description": "TEST_iter23_secours_navigation",
        }
        r = requests.post(f"{BASE_URL}/api/reports", json=payload,
                          headers=_hdr(maint_token), timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body["activity"] == "navigation"
        assert body["heading"] == 185
        assert body["speed_knots"] == 12
        TestSecoursOperation.created_ids.append(body["id"])

    def test_post_secours_invalid_activity_rejected(self, maint_token):
        """Sanity: garbage activity still 422."""
        payload = {
            "type": "secours",
            "subtype": "snsm",
            "activity": "bogus_value",
            "lat": 47.42,
            "lng": -3.22,
            "description": "TEST_iter23_should_fail",
        }
        r = requests.post(f"{BASE_URL}/api/reports", json=payload,
                          headers=_hdr(maint_token), timeout=15)
        assert r.status_code == 422, f"expected 422, got {r.status_code}"

    def test_cleanup(self, maint_token):
        for rid in TestSecoursOperation.created_ids:
            requests.delete(f"{BASE_URL}/api/reports/{rid}",
                            headers=_hdr(maint_token), timeout=10)
