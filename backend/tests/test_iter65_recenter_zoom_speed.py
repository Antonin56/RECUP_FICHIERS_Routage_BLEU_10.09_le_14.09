"""Iteration 65 — Recenter grace + heading/speed switch + zoom_btn_pos.

Covers:
  1. PATCH /api/reports/{id} with {heading:90, speed_knots:12} on an
     'autorites' report (activity=stationary) → response has heading=90,
     speed_knots=12, activity='navigation'.
  2. PATCH /api/reports/{id} with only {heading:45} on an autorites report
     (no prior speed) → activity='navigation' AND speed_knots defaults to 10.
  3. PUT /api/profile/preferences with {zoom_btn_pos:{x:120,y:-80}} → 200,
     response contains zoom_btn_pos, then GET /api/auth/me → persisted.
  4. Regression: PUT /api/profile/preferences with only notify_radius_km
     still works.
"""
from __future__ import annotations

import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

# Admin dev-bypass account (OTP mocked → code always 123456)
ADMIN_PHONE = "0760071445"
ADMIN_OTP = "123456"

# Off French coast (Loire-Atlantique / near Le Croisic) — well at sea.
SEA_LAT = 47.32
SEA_LNG = -2.55


# ─── Auth helpers ──────────────────────────────────────────────────────────
def _admin_login(s: requests.Session) -> str:
    s.post(f"{API}/auth/otp/request", json={"phone": ADMIN_PHONE})
    r = s.post(
        f"{API}/auth/otp/verify",
        json={"phone": ADMIN_PHONE, "code": ADMIN_OTP},
    )
    assert r.status_code == 200, f"OTP verify failed: {r.status_code} {r.text[:250]}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    tok = _admin_login(s)
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def created_ids():
    return []


@pytest.fixture(scope="module", autouse=True)
def _cleanup(admin_session, created_ids):
    yield
    for rid in created_ids:
        try:
            admin_session.delete(f"{API}/reports/{rid}")
        except Exception:
            pass


def _create_autorites_stationary(admin_session, created_ids, description: str) -> dict:
    payload = {
        "type": "autorites",
        "subtype": "gendarmerie_maritime",
        "lat": SEA_LAT,
        "lng": SEA_LNG,
        "description": description,
        "photos": [],
        "activity": "stationary",
        "extras": {},
    }
    r = admin_session.post(f"{API}/reports", json=payload)
    assert r.status_code == 200, f"POST /reports failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    created_ids.append(data["id"])
    # Sanity — activity is stored
    assert data.get("activity") == "stationary", (
        f"expected activity=stationary at creation, got {data.get('activity')}"
    )
    return data


# ─── 1. heading + speed → switches activity to 'navigation' ───────────────
class TestHeadingSpeedSwitch:
    def test_1_heading_and_speed_switch_to_navigation(
        self, admin_session, created_ids
    ):
        rpt = _create_autorites_stationary(
            admin_session, created_ids, "TEST_iter65 heading+speed"
        )
        rid = rpt["id"]
        r = admin_session.patch(
            f"{API}/reports/{rid}", json={"heading": 90, "speed_knots": 12}
        )
        assert r.status_code == 200, (
            f"PATCH heading+speed failed: {r.status_code} {r.text[:300]}"
        )
        data = r.json()
        assert data["heading"] == 90.0, f"heading expected 90, got {data.get('heading')}"
        assert data["speed_knots"] == 12.0, (
            f"speed_knots expected 12, got {data.get('speed_knots')}"
        )
        assert data["activity"] == "navigation", (
            f"activity expected 'navigation', got {data.get('activity')}"
        )

        # Verify persisted via GET
        g = admin_session.get(f"{API}/reports/{rid}")
        assert g.status_code == 200
        gdata = g.json()
        assert gdata["heading"] == 90.0
        assert gdata["speed_knots"] == 12.0
        assert gdata["activity"] == "navigation"

    def test_2_heading_only_defaults_speed_to_10(
        self, admin_session, created_ids
    ):
        rpt = _create_autorites_stationary(
            admin_session, created_ids, "TEST_iter65 heading-only default speed"
        )
        # Confirm no prior speed
        assert not rpt.get("speed_knots"), (
            f"fresh report should have no speed, got {rpt.get('speed_knots')}"
        )
        rid = rpt["id"]
        r = admin_session.patch(f"{API}/reports/{rid}", json={"heading": 45})
        assert r.status_code == 200, (
            f"PATCH heading only failed: {r.status_code} {r.text[:300]}"
        )
        data = r.json()
        assert data["heading"] == 45.0
        assert data["activity"] == "navigation", (
            f"activity expected 'navigation', got {data.get('activity')}"
        )
        assert data.get("speed_knots") == 10.0, (
            f"default speed_knots expected 10, got {data.get('speed_knots')}"
        )

    def test_3_heading_on_control_activity_also_switches(
        self, admin_session, created_ids
    ):
        """Also verify activity='control' → 'navigation' with default speed."""
        payload = {
            "type": "autorites",
            "subtype": "gendarmerie_maritime",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_iter65 control -> navigation",
            "photos": [],
            "activity": "control",
            "extras": {},
        }
        r = admin_session.post(f"{API}/reports", json=payload)
        assert r.status_code == 200, f"POST failed: {r.status_code} {r.text[:300]}"
        rid = r.json()["id"]
        created_ids.append(rid)
        r2 = admin_session.patch(
            f"{API}/reports/{rid}", json={"heading": 200, "speed_knots": 7}
        )
        assert r2.status_code == 200, f"PATCH failed: {r2.status_code} {r2.text[:300]}"
        d = r2.json()
        assert d["activity"] == "navigation"
        assert d["heading"] == 200.0
        assert d["speed_knots"] == 7.0


# ─── 3. zoom_btn_pos preferences ──────────────────────────────────────────
class TestZoomBtnPosPreferences:
    def test_1_put_preferences_zoom_btn_pos(self, admin_session):
        payload = {"zoom_btn_pos": {"x": 120, "y": -80}}
        r = admin_session.put(f"{API}/profile/preferences", json=payload)
        assert r.status_code == 200, (
            f"PUT preferences zoom_btn_pos failed: {r.status_code} {r.text[:300]}"
        )
        data = r.json()
        assert "zoom_btn_pos" in data, (
            f"response missing zoom_btn_pos key. keys={list(data.keys())[:20]}"
        )
        z = data["zoom_btn_pos"]
        assert z is not None, "zoom_btn_pos is None after PUT"
        assert float(z["x"]) == 120.0, f"x expected 120, got {z.get('x')}"
        assert float(z["y"]) == -80.0, f"y expected -80, got {z.get('y')}"

    def test_2_auth_me_returns_zoom_btn_pos(self, admin_session):
        r = admin_session.get(f"{API}/auth/me")
        assert r.status_code == 200, f"GET /auth/me failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "zoom_btn_pos" in data, (
            f"/auth/me missing zoom_btn_pos. keys={list(data.keys())[:30]}"
        )
        z = data.get("zoom_btn_pos")
        assert z is not None, "/auth/me returned zoom_btn_pos=None; PUT did not persist"
        assert float(z["x"]) == 120.0, f"persisted x != 120 ({z.get('x')})"
        assert float(z["y"]) == -80.0, f"persisted y != -80 ({z.get('y')})"

    def test_3_regression_notify_radius_only(self, admin_session):
        """Regression: PUT with only notify_radius_km still works and does NOT
        wipe zoom_btn_pos (partial update semantics)."""
        r = admin_session.put(
            f"{API}/profile/preferences", json={"notify_radius_km": 25}
        )
        assert r.status_code == 200, (
            f"PUT notify_radius_km failed: {r.status_code} {r.text[:250]}"
        )
        data = r.json()
        assert float(data.get("notify_radius_km") or 0) == 25.0, (
            f"notify_radius_km expected 25, got {data.get('notify_radius_km')}"
        )
        # zoom_btn_pos should still be there (partial update, not full replace)
        z = data.get("zoom_btn_pos")
        assert z is not None, "zoom_btn_pos wiped by partial PUT — should be preserved"
        assert float(z["x"]) == 120.0 and float(z["y"]) == -80.0

    def test_4_zoom_btn_pos_update_overwrites(self, admin_session):
        """Second PUT with new x/y overwrites the previous position."""
        r = admin_session.put(
            f"{API}/profile/preferences",
            json={"zoom_btn_pos": {"x": 40.5, "y": 12}},
        )
        assert r.status_code == 200, (
            f"PUT overwrite failed: {r.status_code} {r.text[:300]}"
        )
        z = r.json().get("zoom_btn_pos")
        assert z and float(z["x"]) == 40.5 and float(z["y"]) == 12.0
        # And persistence via /auth/me
        me = admin_session.get(f"{API}/auth/me").json()
        assert float(me["zoom_btn_pos"]["x"]) == 40.5
        assert float(me["zoom_btn_pos"]["y"]) == 12.0
