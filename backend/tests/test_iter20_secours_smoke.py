"""Iteration 20 — Secours POST smoke + TTL check (hotfix review).

Spec from the review_request:
    POST /api/reports {type:'secours', subtype:'snsm', activity:'navigation',
                       lat:47.45, lng:-3.05, heading:185, speed_knots:22}
    as Antonin → 200, report carries all fields, expires_at = now+1h
    (default secours TTL).
"""
import os
import time
from datetime import datetime, timezone
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


class TestSecoursSmoke:
    """POST as dev-bypass user with full activity/navigation payload."""

    created_id: str = ""

    def test_post_secours_snsm_navigation_ok(self, maint_token):
        payload = {
            "type": "secours",
            "subtype": "snsm",
            "activity": "navigation",
            "lat": 47.45,
            "lng": -3.05,
            "heading": 185,
            "speed_knots": 22,
            "description": "TEST_iter20_secours_smoke",
        }
        before = int(time.time())
        r = requests.post(f"{BASE_URL}/api/reports", json=payload,
                          headers=_hdr(maint_token), timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body["type"] == "secours"
        assert body["subtype"] == "snsm"
        assert body["activity"] == "navigation"
        assert body["heading"] == 185
        assert body["speed_knots"] == 22
        # Default secours TTL is 1h ⇒ expires_at ≈ now + 3600s (allow ±5 min drift).
        exp = body.get("expires_at")
        assert exp, "expires_at missing in response"
        try:
            exp_ts = int(datetime.fromisoformat(exp.replace("Z", "+00:00")).timestamp())
        except Exception:
            exp_ts = int(datetime.fromisoformat(exp).replace(tzinfo=timezone.utc).timestamp())
        delta = exp_ts - before
        assert 3300 <= delta <= 3900, f"TTL out of range: {delta}s"
        TestSecoursSmoke.created_id = body["id"]

    def test_cleanup_smoke_report(self, maint_token):
        rid = TestSecoursSmoke.created_id
        if not rid:
            pytest.skip("no id to clean")
        r = requests.delete(f"{BASE_URL}/api/reports/{rid}",
                            headers=_hdr(maint_token), timeout=10)
        assert r.status_code in (200, 204), f"delete failed: {r.status_code} {r.text}"
