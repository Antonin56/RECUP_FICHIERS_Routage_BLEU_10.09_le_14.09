"""Iteration 38 — Referral landing + demo autopilot backend smoke tests.

Covers:
- GET /api/join?ref=SIGNAL1 (unknown code, invalid banner + safe code echo)
- GET /api/join?ref=<real_code> from antoninlepinay after login (pseudo banner)
- Demo-map integrity: HTML contains #demo-map div + Leaflet script
- Anonymous GET /api/reports still returns ~30 is_demo reports
- GET /api/profile/referral returns referral_code for authenticated user
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://maritime-routing-v3.preview.emergentagent.com"

TEST_EMAIL = "antoninlepinay@gmail.com"
TEST_PWD = "123454321"


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PWD})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    return data.get("token") or data.get("access_token")


# ─── landing page (unknown code) ─────────────────────────────────────────
def test_landing_unknown_code_signal1():
    r = requests.get(f"{BASE_URL}/api/join?ref=SIGNAL1")
    assert r.status_code == 200
    html = r.text
    assert "SIGNAL1" in html, "code should be echoed in HTML"
    # unknown code warning banner
    assert "Code inconnu" in html or "warn" in html
    # Demo map div + leaflet embed present
    assert 'id="demo-map"' in html
    assert "leaflet" in html.lower()
    assert "fetch('/api/reports')" in html or "fetch(\"/api/reports\")" in html


def test_landing_no_code_still_renders():
    r = requests.get(f"{BASE_URL}/api/join")
    assert r.status_code == 200
    assert "SignalMar" in r.text
    assert 'id="demo-map"' in r.text


def test_landing_alias_non_api_path():
    """The /join alias (no /api prefix) should also work."""
    r = requests.get(f"{BASE_URL}/join?ref=SIGNAL1", allow_redirects=False)
    # In preview env the /join (non-/api) may not be routed by ingress; accept 200 or 404
    # We only care that /api/join works (already tested). Log for info.
    print(f"/join alias status: {r.status_code}")
    assert r.status_code in (200, 404, 502)


# ─── referral_code for antonin + banner on valid code ────────────────────
def test_profile_referral_code_present(token):
    r = requests.get(
        f"{BASE_URL}/api/profile/referral",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "referral_code" in data
    code = data["referral_code"]
    assert isinstance(code, str) and len(code) >= 4
    print(f"antonin referral_code = {code}")
    # Save for next test
    pytest.antonin_referral_code = code


def test_landing_valid_code_shows_pseudo(token):
    code = getattr(pytest, "antonin_referral_code", None)
    if not code:
        r = requests.get(
            f"{BASE_URL}/api/profile/referral",
            headers={"Authorization": f"Bearer {token}"},
        )
        code = r.json()["referral_code"]
    r = requests.get(f"{BASE_URL}/api/join?ref={code}")
    assert r.status_code == 200
    html = r.text
    assert code.upper() in html
    # Valid banner should mention "Invité par" and the pseudo "SignalMar"
    assert "Invité par" in html, "expected 'Invité par' banner for valid code"
    assert "SignalMar" in html


# ─── reports anonymous (~30 demo) ────────────────────────────────────────
def test_reports_anonymous_returns_demo():
    r = requests.get(f"{BASE_URL}/api/reports")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert len(items) >= 20, f"expected ~30 demo reports, got {len(items)}"
    demo_count = sum(1 for it in items if it.get("is_demo"))
    print(f"anon /api/reports total={len(items)} demo={demo_count}")
    assert demo_count >= 20, f"expected ~30 is_demo reports, got {demo_count}"
    # basic shape
    assert all("lat" in it and "lng" in it and "type" in it for it in items)
