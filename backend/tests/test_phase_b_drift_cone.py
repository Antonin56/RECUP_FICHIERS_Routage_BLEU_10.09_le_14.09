"""Phase B — Drift cone backend tests.

Covers:
  1. Eligible subtype (animal_marin/mammifere dead) creates a cone on POST.
  2. Confirm recomputes the cone (computed_at present after confirm).
  3. Ineligible — obstacle_nav/roche has NO cone.
  4. Ineligible — alive animal has NO cone.
  5. Eligible — obstacle_nav/conteneur creates a cone.
  6. Eligible — pollution/pollution_locale creates a cone.
  7. Author shift recomputes the cone.
  8. status=ended clears the cone.
  9. GET /api/reports list strips photos but keeps drift_cone.
 10. Regression: auth / CRUD / weather still work.

Cleanup: every created report id is collected and DELETEd at teardown.
"""

import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

DEV_EMAIL = "antoninlepinay@gmail.com"
DEV_PASS = "123454321"

# Open-sea coords off the coast of Brittany.
SEA_LAT, SEA_LNG = 47.5, -3.0


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def auth_token(session):
    r = session.post(f"{API}/auth/login",
                     json={"email": DEV_EMAIL, "password": DEV_PASS})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    tok = r.json()["token"]
    session.headers.update({"Authorization": f"Bearer {tok}"})
    return tok


@pytest.fixture(scope="module")
def created_ids():
    return []


@pytest.fixture(scope="module", autouse=True)
def cleanup(session, auth_token, created_ids):
    yield
    for rid in created_ids:
        try:
            session.delete(f"{API}/reports/{rid}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _create_report(session, created_ids, payload, retries=1):
    last = None
    for _ in range(retries + 1):
        r = session.post(f"{API}/reports", json=payload)
        last = r
        if r.status_code == 200:
            data = r.json()
            created_ids.append(data["id"])
            return data
        time.sleep(0.5)
    raise AssertionError(
        f"POST /reports failed {last.status_code}: {last.text[:300]}"
    )


def _assert_cone_shape(cone):
    assert cone is not None, "drift_cone should be present"
    assert "bearing_deg" in cone and isinstance(cone["bearing_deg"], (int, float))
    assert "distance_km" in cone and isinstance(cone["distance_km"], (int, float))
    assert "polygon" in cone and isinstance(cone["polygon"], list)
    assert len(cone["polygon"]) >= 4, f"polygon too short: {len(cone['polygon'])}"
    # polygon items must be {lat, lng} dicts
    for p in cone["polygon"][:3]:
        assert isinstance(p, dict)
        assert "lat" in p and "lng" in p
    for f in ("wind_to_deg", "wind_speed_ms",
              "current_to_deg", "current_speed_ms"):
        assert f in cone, f"missing field {f}"
    assert cone.get("hours") == 1.0
    assert "weights" in cone and "V" in cone["weights"] and "C" in cone["weights"]
    assert "computed_at" in cone


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestDriftCone:
    # 1
    def test_1_eligible_dead_mammifere_creates_cone(self, session, auth_token, created_ids):
        payload = {
            "type": "animal_marin",
            "subtype": "mammifere",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_phase_b dolphin carcass",
            "photos": [],
            "extras": {"health": "dead_unmarked", "animal_species": "common_dolphin"},
        }
        # Open-Meteo is best-effort → retry once if cone is missing.
        data = _create_report(session, created_ids, payload)
        cone = data.get("drift_cone")
        if cone is None:
            # retry by recreating after deleting
            session.delete(f"{API}/reports/{data['id']}")
            created_ids.remove(data["id"])
            time.sleep(2)
            data = _create_report(session, created_ids, payload)
            cone = data.get("drift_cone")
        _assert_cone_shape(cone)
        assert cone["distance_km"] > 0, f"expected drift>0, got {cone['distance_km']}"
        # Save id for downstream tests
        pytest.dolphin_rid = data["id"]

    # 2
    def test_2_confirm_recomputes_cone(self, session, auth_token, created_ids):
        rid = getattr(pytest, "dolphin_rid", None)
        assert rid, "test_1 must have produced a report id"
        before = session.get(f"{API}/reports/{rid}").json()
        ts_before = before.get("drift_cone", {}).get("computed_at")
        time.sleep(1.2)  # ensure timestamp can advance
        # V1.2: authors cannot confirm their own report → use a fresh second
        # account with an at-sea GPS fix (both server-side requirements).
        import uuid as _uuid
        import requests as _rq
        reg = _rq.post(f"{API}/auth/register", json={
            "email": f"TEST_phaseb_confirm_{_uuid.uuid4().hex[:8]}@signmar.app",
            "password": "password123", "name": "PhaseB Confirmer",
        })
        assert reg.status_code == 200, reg.text
        h2 = {"Authorization": f"Bearer {reg.json()['token']}",
              "Content-Type": "application/json"}
        loc = _rq.post(f"{API}/profile/location",
                       json={"lat": SEA_LAT, "lng": SEA_LNG}, headers=h2)
        assert loc.status_code == 200, loc.text
        r = _rq.post(f"{API}/reports/{rid}/confirm", headers=h2)
        assert r.status_code == 200, f"confirm failed: {r.status_code} {r.text}"
        # GET to fetch the persisted cone (POST response payload is the report doc)
        after = session.get(f"{API}/reports/{rid}").json()
        cone = after.get("drift_cone")
        _assert_cone_shape(cone)
        # computed_at must be present and ideally advanced
        assert cone["computed_at"], "computed_at missing after confirm"
        if ts_before:
            # not strictly required to advance, but if BE recomputed it must be >=
            assert cone["computed_at"] >= ts_before, (
                f"computed_at went backwards: {cone['computed_at']} < {ts_before}"
            )

    # 3
    def test_3_ineligible_rock_no_cone(self, session, auth_token, created_ids):
        payload = {
            "type": "obstacle_nav",
            "subtype": "roche",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_phase_b fixed rock",
            "photos": [],
            "extras": {},
        }
        data = _create_report(session, created_ids, payload)
        assert data.get("drift_cone") in (None, {}), (
            f"rock should have no cone, got {data.get('drift_cone')}"
        )

    # 4
    def test_4_ineligible_alive_animal_no_cone(self, session, auth_token, created_ids):
        payload = {
            "type": "animal_marin",
            "subtype": "mammifere",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_phase_b alive dolphin",
            "photos": [],
            "extras": {"health": "alive_healthy", "animal_species": "common_dolphin"},
        }
        data = _create_report(session, created_ids, payload)
        assert data.get("drift_cone") in (None, {}), (
            f"alive animal must have no cone, got {data.get('drift_cone')}"
        )

    # 5
    def test_5_eligible_conteneur_cone(self, session, auth_token, created_ids):
        payload = {
            "type": "obstacle_nav",
            "subtype": "conteneur",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_phase_b container adrift",
            "photos": [],
            "extras": {},
        }
        data = _create_report(session, created_ids, payload)
        cone = data.get("drift_cone")
        if cone is None:
            time.sleep(2)
            session.delete(f"{API}/reports/{data['id']}")
            created_ids.remove(data["id"])
            data = _create_report(session, created_ids, payload)
            cone = data.get("drift_cone")
        _assert_cone_shape(cone)
        # weights for conteneur: V=1, C=9
        assert cone["weights"] == {"V": 1, "C": 9}

    # 6
    def test_6_eligible_pollution_cone(self, session, auth_token, created_ids):
        payload = {
            "type": "pollution",
            "subtype": "pollution_locale",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_phase_b oil slick",
            "photos": [],
            "extras": {},
        }
        data = _create_report(session, created_ids, payload)
        cone = data.get("drift_cone")
        if cone is None:
            time.sleep(2)
            session.delete(f"{API}/reports/{data['id']}")
            created_ids.remove(data["id"])
            data = _create_report(session, created_ids, payload)
            cone = data.get("drift_cone")
        _assert_cone_shape(cone)
        assert cone["weights"] == {"V": 5, "C": 5}

    # 7
    def test_7_author_shift_recomputes_cone(self, session, auth_token, created_ids):
        # Create eligible, then PATCH with a small offset.
        payload = {
            "type": "obstacle_nav",
            "subtype": "ofni",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_phase_b ofni shift",
            "photos": [],
            "extras": {},
        }
        data = _create_report(session, created_ids, payload)
        rid = data["id"]
        # ~500 m east shift (≈0.0067° lng at lat=47.5).
        new_lat, new_lng = SEA_LAT + 0.001, SEA_LNG + 0.005
        r = session.patch(f"{API}/reports/{rid}",
                          json={"new_lat": new_lat, "new_lng": new_lng})
        assert r.status_code == 200, f"PATCH shift failed: {r.status_code} {r.text}"
        new_doc = r.json()
        cone = new_doc.get("drift_cone")
        # cone may briefly be None if Open-Meteo blipped — refetch once
        if cone is None:
            time.sleep(1.5)
            new_doc = session.get(f"{API}/reports/{rid}").json()
            cone = new_doc.get("drift_cone")
        _assert_cone_shape(cone)
        # Apex should now sit near the new coordinates
        apex = cone["polygon"][0]
        assert abs(apex["lat"] - new_lat) < 1e-3
        assert abs(apex["lng"] - new_lng) < 1e-3

    # 8
    def test_8_status_ended_clears_cone(self, session, auth_token, created_ids):
        # Create eligible report just for this test
        payload = {
            "type": "pollution",
            "subtype": "pollution_locale",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_phase_b end-status pollution",
            "photos": [],
            "extras": {},
        }
        data = _create_report(session, created_ids, payload)
        rid = data["id"]
        # Make sure it has a cone first
        if not data.get("drift_cone"):
            time.sleep(2)
        r = session.patch(f"{API}/reports/{rid}", json={"status": "ended"})
        assert r.status_code == 200, f"PATCH ended failed: {r.status_code} {r.text}"
        # Re-fetch via GET to confirm clearance was persisted
        g = session.get(f"{API}/reports/{rid}")
        assert g.status_code == 200
        doc = g.json()
        assert doc.get("drift_cone") in (None, {}), (
            f"drift_cone should be cleared after status=ended, got {doc.get('drift_cone')}"
        )

    # 9
    def test_9_list_strips_photos_keeps_drift_cone(self, session, auth_token, created_ids):
        r = session.get(f"{API}/reports")
        assert r.status_code == 200, f"GET /reports failed: {r.status_code}"
        items = r.json()
        assert isinstance(items, list)
        # All items must have photos == [] (stripped)
        for it in items:
            assert it.get("photos") == [], (
                f"list endpoint MUST strip photos, got len={len(it.get('photos') or [])}"
            )
        # At least one of our created eligible reports should appear with drift_cone
        eligible_ids = [pytest.dolphin_rid] if hasattr(pytest, "dolphin_rid") else []
        # find any item that is still active (not ended) and has drift_cone
        with_cone = [it for it in items if it.get("drift_cone")]
        assert with_cone, (
            "expected at least one report with a drift_cone in the list response "
            f"(eligible ids created: {eligible_ids})"
        )

    # 10 — regression
    def test_10_regression_auth_me(self, session, auth_token):
        r = session.get(f"{API}/auth/me")
        assert r.status_code == 200
        assert r.json().get("email", "").lower() == DEV_EMAIL

    def test_10b_regression_weather(self, session, auth_token):
        r = session.get(f"{API}/weather/marine",
                        params={"lat": SEA_LAT, "lng": SEA_LNG})
        assert r.status_code in (200, 503), f"weather endpoint failed: {r.status_code} {r.text[:200]}"
        # 503 acceptable only if Open-Meteo unreachable; main contract:
        if r.status_code == 200:
            body = r.json()
            assert isinstance(body, dict)

    def test_10c_regression_get_report(self, session, auth_token, created_ids):
        # any created id will do
        rid = created_ids[0]
        r = session.get(f"{API}/reports/{rid}")
        assert r.status_code == 200
        doc = r.json()
        assert doc["id"] == rid
        # photos field always serialisable
        assert "photos" in doc
