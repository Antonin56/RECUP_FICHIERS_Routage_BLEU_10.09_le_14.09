"""Phase E.3 — Heading (cap) edit + position DM render regression.

Covers PATCH /api/reports/{rid} extensions:
  1. Author can set heading (200, response.heading=90, heading_edited_at set)
  2. Non-author with reliability ≥ 60 can set heading (200)
  3. Non-author with reliability < 60 → 403 with the "Indice de fiabilité ≥ 60%" detail
  4. PATCH heading on a non-eligible report (obstacle_nav/roche, or alive animal) → 422
  5. PATCH heading > 360 → 422 (Pydantic ge/le validation)
  6. Non-author PATCH with new_lat/new_lng → 403 (position-shift remains author-only)
  7. Non-author PATCH with status:'ended' → 403 (status remains author-only)
  8. Non-author heading edit does NOT bump author_edited_at (only author edits do)
  9. Regression: author position shift still works (200, lat/lng updated)
 10. Regression: author status flip to 'ended' still works (200, status='ended')

Cleanup: every report created here is deleted at teardown.
"""
from __future__ import annotations

import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

DEV_EMAIL = "antoninlepinay@gmail.com"
DEV_PASS = "123454321"
STD_EMAIL = "test@signmar.app"
STD_PASS = "password123"

# Open-sea coords off Brittany (well outside any coastline buffer).
SEA_LAT, SEA_LNG = 47.5, -3.0


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------
def _login(session: requests.Session, email: str, password: str) -> str:
    r = session.post(f"{API}/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        # Auto-register the std user if necessary
        if email == STD_EMAIL:
            session.post(f"{API}/auth/register", json={
                "email": email, "password": password, "name": "Captain Test"
            })
            r = session.post(f"{API}/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def dev_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    tok = _login(s, DEV_EMAIL, DEV_PASS)
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def std_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    tok = _login(s, STD_EMAIL, STD_PASS)
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def std_user_id(std_session):
    r = std_session.get(f"{API}/auth/me")
    assert r.status_code == 200, f"/auth/me failed: {r.status_code}"
    return r.json()["user_id"]


@pytest.fixture(scope="module")
def created_ids():
    return []


@pytest.fixture(scope="module", autouse=True)
def cleanup(dev_session, created_ids):
    yield
    for rid in created_ids:
        try:
            dev_session.delete(f"{API}/reports/{rid}")
        except Exception:
            pass


def _create(dev_session, created_ids, payload):
    r = dev_session.post(f"{API}/reports", json=payload)
    assert r.status_code == 200, f"POST /reports failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    created_ids.append(data["id"])
    return data


# ---------------------------------------------------------------------------
# Reliability helpers — V1.2 made ``reliability_pct`` the single source of
# truth, and it only moves when OTHER users confirm/infirm your reports (no
# longer on report creation). Bumping it organically from a test is therefore
# impossible without a second fleet of accounts, so we set the field directly
# in Mongo and restore the original value at teardown.
# ---------------------------------------------------------------------------
def _mongo_users():
    import os
    from pymongo import MongoClient
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    client = MongoClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]].users


@pytest.fixture(scope="module")
def std_reliable_session(std_session, std_user_id):
    """Returns the std_session AFTER forcing reliability_pct ≥ 60 via a
    direct DB write (restored at teardown)."""
    users = _mongo_users()
    doc = users.find_one({"user_id": std_user_id}, {"_id": 0, "reliability_pct": 1}) or {}
    original = doc.get("reliability_pct")
    users.update_one({"user_id": std_user_id}, {"$set": {"reliability_pct": 70}})
    # Sanity — the API must now report ≥ 60 (serializer + enforcement agree).
    me = std_session.get(f"{API}/auth/me").json()
    new_rel = me.get("reliability_score", 50)
    pytest._std_reliability_created_ids = []
    pytest._std_final_reliability = new_rel
    if new_rel < 60:
        pytest.skip(f"Could not reach reliability ≥ 60 (got {new_rel})")
    yield std_session
    # Restore the pre-test value so other suites see the true state.
    if original is None:
        users.update_one({"user_id": std_user_id}, {"$unset": {"reliability_pct": ""}})
    else:
        users.update_one({"user_id": std_user_id}, {"$set": {"reliability_pct": original}})


@pytest.fixture(scope="module", autouse=True)
def cleanup_std_reports(std_session):
    yield
    ids = getattr(pytest, "_std_reliability_created_ids", []) or []
    for rid in ids:
        try:
            std_session.delete(f"{API}/reports/{rid}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Report-factory fixtures (one shared autorites report; per-test pollution etc.)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def autorites_report(dev_session, created_ids):
    return _create(dev_session, created_ids, {
        "type": "autorites",
        "subtype": None,
        "lat": SEA_LAT,
        "lng": SEA_LNG,
        "description": "TEST_e3 autorites/cap",
        "photos": [],
        "extras": {},
    })


# =========================================================================
# Tests
# =========================================================================
class TestHeadingEditE3:

    # 1
    def test_1_author_can_set_heading(self, dev_session, autorites_report):
        rid = autorites_report["id"]
        r = dev_session.patch(f"{API}/reports/{rid}", json={"heading": 90})
        assert r.status_code == 200, f"PATCH heading=90 failed: {r.status_code} {r.text}"
        data = r.json()
        assert data["heading"] == 90.0, f"expected heading=90, got {data.get('heading')}"
        assert data.get("heading_edited_at"), "heading_edited_at must be set"
        assert data.get("heading_edited_by"), "heading_edited_by must be set"

    # 2
    def test_2_nonauthor_reliable_can_set_heading(
        self, dev_session, std_reliable_session, autorites_report
    ):
        rid = autorites_report["id"]
        r = std_reliable_session.patch(f"{API}/reports/{rid}", json={"heading": 180})
        assert r.status_code == 200, (
            f"reliable non-author PATCH heading=180 failed: "
            f"{r.status_code} {r.text[:300]}"
        )
        data = r.json()
        assert data["heading"] == 180.0

    # 3
    def test_3_nonauthor_unreliable_blocked(self, dev_session, created_ids):
        # Create a fresh autorites report; manually run with a session whose
        # reliability is below 60%. We register a fresh ephemeral user.
        fresh_email = f"e3unreliable_{int(time.time())}@example.com"
        fresh_pass = "password123"
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        reg = s.post(f"{API}/auth/register", json={
            "email": fresh_email, "password": fresh_pass, "name": "E3 Unreliable"
        })
        assert reg.status_code == 200, f"register fresh user failed: {reg.text}"
        tok = reg.json()["token"]
        s.headers.update({"Authorization": f"Bearer {tok}"})
        me = s.get(f"{API}/auth/me").json()
        assert me["reliability_score"] < 60, (
            f"fresh user should have <60 reliability, got {me['reliability_score']}"
        )
        # Use the shared autorites report (created by dev)
        target = _create(dev_session, created_ids, {
            "type": "autorites",
            "subtype": None,
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_e3 autorites/unreliable target",
            "photos": [],
            "extras": {},
        })
        r = s.patch(f"{API}/reports/{target['id']}", json={"heading": 270})
        assert r.status_code == 403, (
            f"expected 403 for unreliable non-author, got {r.status_code} {r.text[:200]}"
        )
        detail = r.json().get("detail", "")
        assert "Indice de fiabilité" in detail or "fiabilité" in detail, (
            f"detail should mention reliability, got: {detail}"
        )

    # 4
    def test_4_heading_blocked_on_non_eligible_type(self, dev_session, created_ids):
        # 4a) obstacle_nav/roche is not in SUBTYPE_DRIFT
        roche = _create(dev_session, created_ids, {
            "type": "obstacle_nav",
            "subtype": "roche",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_e3 roche",
            "photos": [],
            "extras": {},
        })
        r = dev_session.patch(f"{API}/reports/{roche['id']}", json={"heading": 45})
        assert r.status_code == 422, (
            f"expected 422 for roche heading edit, got {r.status_code} {r.text[:200]}"
        )
        assert "cap" in r.json().get("detail", "").lower()

        # 4b) animal_marin/mammifere alive (drift_cone_eligible returns False)
        alive = _create(dev_session, created_ids, {
            "type": "animal_marin",
            "subtype": "mammifere",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_e3 alive mammifere",
            "photos": [],
            "extras": {"health": "alive_healthy"},
        })
        r = dev_session.patch(f"{API}/reports/{alive['id']}", json={"heading": 45})
        assert r.status_code == 422, (
            f"expected 422 for alive animal heading edit, got {r.status_code} {r.text[:200]}"
        )

    # 5
    def test_5_heading_out_of_range_rejected(self, dev_session, autorites_report):
        r = dev_session.patch(
            f"{API}/reports/{autorites_report['id']}", json={"heading": 720}
        )
        assert r.status_code == 422, (
            f"heading=720 should fail Pydantic validation, got {r.status_code}"
        )

    # 6
    def test_6_nonauthor_position_shift_forbidden(
        self, dev_session, std_reliable_session, autorites_report
    ):
        rid = autorites_report["id"]
        r = std_reliable_session.patch(f"{API}/reports/{rid}", json={
            "new_lat": SEA_LAT + 0.001,
            "new_lng": SEA_LNG + 0.001,
        })
        assert r.status_code == 403, (
            f"non-author position shift should be 403, got {r.status_code} {r.text[:200]}"
        )

    # 7
    def test_7_nonauthor_status_change_forbidden(
        self, dev_session, std_reliable_session, autorites_report
    ):
        rid = autorites_report["id"]
        r = std_reliable_session.patch(f"{API}/reports/{rid}", json={"status": "ended"})
        assert r.status_code == 403, (
            f"non-author status change should be 403, got {r.status_code} {r.text[:200]}"
        )

    # 8
    def test_8_nonauthor_heading_edit_does_not_touch_author_edited_at(
        self, dev_session, std_reliable_session, created_ids
    ):
        # Fresh report so we can observe the very-first author_edited_at change.
        target = _create(dev_session, created_ids, {
            "type": "autorites",
            "subtype": None,
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_e3 author_edited_at check",
            "photos": [],
            "extras": {},
        })
        rid = target["id"]
        # initial value (None expected on a fresh report)
        before = dev_session.get(f"{API}/reports/{rid}").json()
        ae_before = before.get("author_edited_at")

        # Non-author edits heading
        r = std_reliable_session.patch(f"{API}/reports/{rid}", json={"heading": 123})
        assert r.status_code == 200, f"non-author heading edit failed: {r.status_code} {r.text[:200]}"

        after = dev_session.get(f"{API}/reports/{rid}").json()
        ae_after = after.get("author_edited_at")
        assert ae_before == ae_after, (
            f"non-author heading edit should NOT bump author_edited_at "
            f"(before={ae_before}, after={ae_after})"
        )
        # Sanity: heading IS updated and heading_edited_by is the std user
        assert after["heading"] == 123.0
        assert after.get("heading_edited_by"), "heading_edited_by must be set"

    # 9
    def test_9_author_position_shift_regression(self, dev_session, created_ids):
        target = _create(dev_session, created_ids, {
            "type": "autorites",
            "subtype": None,
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_e3 shift regression",
            "photos": [],
            "extras": {},
        })
        rid = target["id"]
        new_lat = SEA_LAT + 0.002
        new_lng = SEA_LNG + 0.002
        r = dev_session.patch(f"{API}/reports/{rid}", json={
            "new_lat": new_lat, "new_lng": new_lng
        })
        assert r.status_code == 200, f"author shift failed: {r.status_code} {r.text}"
        data = r.json()
        assert abs(data["lat"] - new_lat) < 1e-5
        assert abs(data["lng"] - new_lng) < 1e-5

    # 10
    def test_10_author_status_end_regression(self, dev_session, created_ids):
        target = _create(dev_session, created_ids, {
            "type": "autorites",
            "subtype": None,
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_e3 status-ended regression",
            "photos": [],
            "extras": {},
        })
        rid = target["id"]
        r = dev_session.patch(f"{API}/reports/{rid}", json={"status": "ended"})
        assert r.status_code == 200, f"status=ended failed: {r.status_code} {r.text}"
        assert r.json()["status"] == "ended"

    # 11 — also test eligibility on drift-eligible (pollution/locale)
    def test_11_heading_ok_on_drift_eligible_pollution(self, dev_session, created_ids):
        target = _create(dev_session, created_ids, {
            "type": "pollution",
            "subtype": "pollution_locale",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_e3 pollution heading",
            "photos": [],
            "extras": {},
        })
        r = dev_session.patch(f"{API}/reports/{target['id']}", json={"heading": 200})
        assert r.status_code == 200, f"pollution heading edit failed: {r.status_code} {r.text[:200]}"
        assert r.json()["heading"] == 200.0
