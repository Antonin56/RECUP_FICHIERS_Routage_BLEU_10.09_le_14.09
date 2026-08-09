"""Phase 1 — author direct edit (PATCH) + author delete (DELETE) tests."""
import os
import uuid
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")

ANTONIN = {"email": "antoninlepinay@gmail.com", "password": "123454321"}


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def antonin_auth():
    return _login(**ANTONIN)


@pytest.fixture(scope="module")
def second_user_auth():
    suffix = uuid.uuid4().hex[:8]
    email = f"TEST_phase1_{suffix}@signmar.app"
    pw = "TestPass!234"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": pw, "name": f"TEST_p1_{suffix}"},
    )
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


# Helper: get one of Antonin's authored reports
def _antonin_report(tok, uid):
    r = requests.get(f"{BASE_URL}/api/reports", headers=_hdr(tok))
    assert r.status_code == 200
    items = r.json()
    mine = [x for x in items if x["author"]["user_id"] == uid]
    assert mine, "Antonin has no reports — run seed_antonin.py"
    return mine[0]


# 1) Antonin PATCH lat/lng → 200 + updated coords
def test_author_patch_coords(antonin_auth):
    tok, user = antonin_auth
    rep = _antonin_report(tok, user["user_id"])
    new_lat = rep["lat"] + 0.001
    new_lng = rep["lng"] + 0.001
    r = requests.patch(
        f"{BASE_URL}/api/reports/{rep['id']}",
        headers=_hdr(tok),
        json={"new_lat": new_lat, "new_lng": new_lng},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert abs(out["lat"] - new_lat) < 1e-9
    assert abs(out["lng"] - new_lng) < 1e-9
    # GET verifies persistence
    g = requests.get(f"{BASE_URL}/api/reports/{rep['id']}", headers=_hdr(tok))
    assert g.status_code == 200
    assert abs(g.json()["lat"] - new_lat) < 1e-9


# 2) Antonin PATCH status=ended → 200
def test_author_patch_status_ended(antonin_auth):
    tok, user = antonin_auth
    rep = _antonin_report(tok, user["user_id"])
    r = requests.patch(
        f"{BASE_URL}/api/reports/{rep['id']}",
        headers=_hdr(tok),
        json={"status": "ended"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"


# 3) Empty body → 400
def test_author_patch_empty(antonin_auth):
    tok, user = antonin_auth
    rep = _antonin_report(tok, user["user_id"])
    r = requests.patch(
        f"{BASE_URL}/api/reports/{rep['id']}",
        headers=_hdr(tok),
        json={},
    )
    assert r.status_code == 400, r.text


# 4) Non-author PATCH → 403
def test_non_author_patch_forbidden(antonin_auth, second_user_auth):
    tok_a, user_a = antonin_auth
    tok_b, _ = second_user_auth
    rep = _antonin_report(tok_a, user_a["user_id"])
    r = requests.patch(
        f"{BASE_URL}/api/reports/{rep['id']}",
        headers=_hdr(tok_b),
        json={"new_lat": rep["lat"] + 0.01, "new_lng": rep["lng"] + 0.01},
    )
    assert r.status_code == 403, r.text


# 5) Non-author DELETE → 403
def test_non_author_delete_forbidden(antonin_auth, second_user_auth):
    tok_a, user_a = antonin_auth
    tok_b, _ = second_user_auth
    rep = _antonin_report(tok_a, user_a["user_id"])
    r = requests.delete(f"{BASE_URL}/api/reports/{rep['id']}", headers=_hdr(tok_b))
    assert r.status_code == 403, r.text


# 6) Author DELETE → 200 then GET → 404. Use a fresh report so we don't lose seeded data.
def test_author_delete_own_report(antonin_auth):
    tok, _ = antonin_auth
    # Create a throwaway report
    create = requests.post(
        f"{BASE_URL}/api/reports",
        headers=_hdr(tok),
        json={
            "type": "pollution",
            "lat": 47.5,
            "lng": -2.9,
            "description": "TEST_phase1_delete",
            "photos": [],
        },
    )
    assert create.status_code == 200, create.text
    rid = create.json()["id"]
    # Delete it
    d = requests.delete(f"{BASE_URL}/api/reports/{rid}", headers=_hdr(tok))
    assert d.status_code == 200, d.text
    assert d.json().get("ok") is True
    # Verify gone
    g = requests.get(f"{BASE_URL}/api/reports/{rid}", headers=_hdr(tok))
    assert g.status_code == 404


# 7) DELETE non-existent → 404 (not 403)
def test_delete_missing_report(antonin_auth):
    tok, _ = antonin_auth
    r = requests.delete(f"{BASE_URL}/api/reports/{uuid.uuid4().hex}", headers=_hdr(tok))
    assert r.status_code == 404
