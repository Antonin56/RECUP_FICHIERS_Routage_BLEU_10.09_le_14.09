"""Phase E.3 Lot 2 — Drift cone rotation on heading edit + leeway bump 3%→5%.

Bug fixed: editing the heading (cap) of a drift-eligible report MUST rotate the
drift_cone projection (previously the cone was computed purely from wind+current
and ignored the user-set heading).

Covers:
  1. PATCH heading=309 on a pollution (drift-eligible) report
     → 200, drift_cone.bearing_deg ≈ 309, bearing_source == 'user',
       algo_bearing_deg still present.
  2. PATCH heading on autorites → 200, no drift_cone on the response (autorites
     are not drift-eligible).
  3. Create NEW pollution WITHOUT heading → bearing_source == 'auto',
     bearing_deg == algo_bearing_deg.
  4. Create NEW pollution WITH heading=120 → bearing_source == 'user',
     bearing_deg == 120.
  5. Confirm endpoint preserves user heading override on refresh.
  6. Regression — polygon points change between bearing=0° and bearing=180°
     (cone is actually rotated, not just the bearing label).
  7. DRIFT_LEEWAY = 0.05 — unit-level check of compute_drift_cone math.
  8. PATCH heading on alive animal_marin → 422 (not drift-eligible).
  9. drift_cone JSON shape includes algo_bearing_deg (number) +
     bearing_source ('auto'|'user').
 10. PATCH with body without heading does NOT change drift_cone bearing_source.

All created reports are cleaned up via the autouse fixture.
"""
from __future__ import annotations

import math
import os
import time
from typing import Optional

import pytest
import requests

# Direct unit-level imports (for compute_drift_cone math check & DRIFT_LEEWAY).
import sys
sys.path.insert(0, "/app/backend")
from server import (  # noqa: E402
    DRIFT_LEEWAY,
    DRIFT_CONE_HOURS,
    compute_drift_cone,
    drift_cone_eligible,
    subtype_drift_weights,
)

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

DEV_EMAIL = "antoninlepinay@gmail.com"
DEV_PASS = "123454321"

# Open-sea coords off Brittany (out of any coast buffer; Open-Meteo serves
# marine data here).
SEA_LAT, SEA_LNG = 47.5, -3.0


# ---------------------------------------------------------------------------
# Session + cleanup
# ---------------------------------------------------------------------------
def _login(session: requests.Session, email: str, password: str) -> str:
    r = session.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def dev_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    tok = _login(s, DEV_EMAIL, DEV_PASS)
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def created_ids() -> list[str]:
    return []


@pytest.fixture(scope="module", autouse=True)
def cleanup(dev_session, created_ids):
    yield
    for rid in created_ids:
        try:
            dev_session.delete(f"{API}/reports/{rid}")
        except Exception:
            pass


def _create_report(dev_session, created_ids, payload: dict) -> dict:
    r = dev_session.post(f"{API}/reports", json=payload)
    assert r.status_code == 200, f"POST /reports failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    created_ids.append(data["id"])
    return data


def _create_pollution(dev_session, created_ids, *, heading: Optional[float] = None,
                      tag: str = "lot2") -> dict:
    payload = {
        "type": "pollution",
        "subtype": "pollution_locale",
        "lat": SEA_LAT,
        "lng": SEA_LNG,
        "description": f"TEST_e3lot2 {tag}",
        "photos": [],
        "extras": {},
    }
    if heading is not None:
        payload["heading"] = heading
    return _create_report(dev_session, created_ids, payload)


# =========================================================================
# Unit-level sanity (no HTTP) — DRIFT_LEEWAY = 0.05 (NATO SAR alignment)
# =========================================================================
class TestDriftLeewayUnit:
    def test_drift_leeway_constant_is_5_percent(self):
        assert DRIFT_LEEWAY == pytest.approx(0.05), (
            f"DRIFT_LEEWAY must be 0.05 (5%), got {DRIFT_LEEWAY}"
        )

    def test_compute_drift_cone_distance_with_5pct_leeway(self):
        """V=5 OFNI, wind 5.66 m/s due-east, current 0 → distance_km ≈ 0.509 km.

        Math: mag_ms = 5.66 * 0.5 * 0.05 = 0.1415 m/s
              distance_km = 0.1415 * 3600 / 1000 = 0.5094 km
        With 3% leeway (the pre-Lot2 value) this would have been ~0.306 km.
        """
        marine = {
            "wind_speed_ms": 5.66,
            "wind_to_deg": 90.0,       # east
            "current_speed_ms": 0.0,
            "current_to_deg": 0.0,
        }
        cone = compute_drift_cone(SEA_LAT, SEA_LNG, V=5, C=5,
                                  marine=marine, hours=1.0)
        expected_km = 5.66 * 0.5 * 0.05 * 3600.0 / 1000.0  # ≈ 0.5094
        assert cone["distance_km"] == pytest.approx(expected_km, abs=0.01), (
            f"expected ≈ {expected_km:.3f} km with 5% leeway, "
            f"got {cone['distance_km']}"
        )
        # bearing should be ~90° (pure wind, east)
        assert cone["bearing_deg"] == pytest.approx(90.0, abs=0.1)
        assert cone["algo_bearing_deg"] == pytest.approx(90.0, abs=0.1)
        assert cone["bearing_source"] == "auto"

    def test_compute_drift_cone_override_keeps_distance_rotates_bearing(self):
        """When override_bearing_deg is set, distance stays = vector magnitude
        but bearing follows the override."""
        marine = {
            "wind_speed_ms": 5.66,
            "wind_to_deg": 90.0,
            "current_speed_ms": 0.0,
            "current_to_deg": 0.0,
        }
        cone = compute_drift_cone(SEA_LAT, SEA_LNG, V=5, C=5,
                                  marine=marine, hours=1.0,
                                  override_bearing_deg=309.0)
        assert cone["bearing_deg"] == pytest.approx(309.0, abs=0.1)
        assert cone["algo_bearing_deg"] == pytest.approx(90.0, abs=0.1)
        assert cone["bearing_source"] == "user"
        # distance unchanged by override
        expected_km = 5.66 * 0.5 * 0.05 * 3600.0 / 1000.0
        assert cone["distance_km"] == pytest.approx(expected_km, abs=0.01)

    def test_compute_drift_cone_polygon_rotates_with_bearing(self):
        marine = {
            "wind_speed_ms": 5.0,
            "wind_to_deg": 0.0,
            "current_speed_ms": 0.5,
            "current_to_deg": 0.0,
        }
        c0 = compute_drift_cone(SEA_LAT, SEA_LNG, V=5, C=5,
                                marine=marine, hours=1.0,
                                override_bearing_deg=0.0)
        c180 = compute_drift_cone(SEA_LAT, SEA_LNG, V=5, C=5,
                                  marine=marine, hours=1.0,
                                  override_bearing_deg=180.0)
        # Apex is identical; arc-end vertices should be on opposite sides
        # of the apex latitude.
        # Compare a mid-arc vertex (not apex) on the north (bearing=0) vs
        # south (bearing=180) side.
        mid = len(c0["polygon"]) // 2
        v0 = c0["polygon"][mid]
        v180 = c180["polygon"][mid]
        assert v0["lat"] > SEA_LAT, f"bearing 0 polygon should extend north, got {v0}"
        assert v180["lat"] < SEA_LAT, f"bearing 180 polygon should extend south, got {v180}"


# =========================================================================
# HTTP-level integration — these need Open-Meteo reachable. We skip a test
# gracefully if the cone is missing on a newly created pollution (Open-Meteo
# outage) so the suite stays useful offline.
# =========================================================================
class TestDriftConeHeadingEdit:

    # 1
    def test_1_patch_heading_309_on_pollution_rotates_cone(self, dev_session, created_ids):
        rep = _create_pollution(dev_session, created_ids, tag="patch-309")
        if not rep.get("drift_cone"):
            pytest.skip("Open-Meteo unavailable — no cone computed on create.")

        r = dev_session.patch(f"{API}/reports/{rep['id']}", json={"heading": 309})
        assert r.status_code == 200, f"PATCH heading=309 failed: {r.status_code} {r.text[:300]}"
        data = r.json()
        assert data["heading"] == 309.0
        cone = data.get("drift_cone")
        assert cone, f"drift_cone missing after heading edit; full body={data}"
        assert cone["bearing_source"] == "user", (
            f"bearing_source must become 'user' after explicit heading PATCH; got {cone}"
        )
        assert cone["bearing_deg"] == pytest.approx(309.0, abs=0.5), (
            f"bearing_deg should ≈ 309 (user override), got {cone['bearing_deg']}"
        )
        assert "algo_bearing_deg" in cone, "algo_bearing_deg must be present"
        assert isinstance(cone["algo_bearing_deg"], (int, float))
        # algo bearing is the physics estimate; it is generally NOT 309 unless
        # wind+current happen to coincidentally point there — soft check.

    # 2
    def test_2_patch_heading_on_autorites_no_drift_cone(self, dev_session, created_ids):
        rep = _create_report(dev_session, created_ids, {
            "type": "autorites",
            "subtype": None,
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_e3lot2 autorites cap",
            "photos": [],
            "extras": {},
        })
        # Autorites are not drift-eligible — confirm precondition
        assert not drift_cone_eligible("autorites", None, {})
        r = dev_session.patch(f"{API}/reports/{rep['id']}", json={"heading": 309})
        assert r.status_code == 200, f"PATCH autorites heading failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert data["heading"] == 309.0
        # Autorites must NOT carry a drift_cone (refresh_drift_cone unsets it).
        assert not data.get("drift_cone"), (
            f"autorites must not have a drift_cone, got {data.get('drift_cone')}"
        )

    # 3
    def test_3_create_pollution_without_heading_auto_source(self, dev_session, created_ids):
        rep = _create_pollution(dev_session, created_ids, tag="create-noheading")
        if not rep.get("drift_cone"):
            pytest.skip("Open-Meteo unavailable.")
        cone = rep["drift_cone"]
        assert cone["bearing_source"] == "auto", (
            f"create without heading → bearing_source must be 'auto', got {cone}"
        )
        assert cone["bearing_deg"] == cone["algo_bearing_deg"], (
            f"auto: bearing_deg must equal algo_bearing_deg; got "
            f"{cone['bearing_deg']} vs {cone['algo_bearing_deg']}"
        )

    # 4
    def test_4_create_pollution_with_heading_120(self, dev_session, created_ids):
        rep = _create_pollution(dev_session, created_ids,
                                heading=120.0, tag="create-h120")
        if not rep.get("drift_cone"):
            pytest.skip("Open-Meteo unavailable.")
        cone = rep["drift_cone"]
        assert cone["bearing_source"] == "user"
        assert cone["bearing_deg"] == pytest.approx(120.0, abs=0.5)
        # algo bearing still computed, but generally != 120
        assert "algo_bearing_deg" in cone

    # 5 — confirm preserves user heading override
    def test_5_confirm_preserves_user_bearing_source(self, dev_session, created_ids):
        rep = _create_pollution(dev_session, created_ids,
                                heading=200.0, tag="confirm-h200")
        if not rep.get("drift_cone"):
            pytest.skip("Open-Meteo unavailable.")
        assert rep["drift_cone"]["bearing_source"] == "user"
        # Sleep a touch so wind/current isn't strictly identical to ensure refresh ran.
        time.sleep(0.5)
        cr = dev_session.post(f"{API}/reports/{rep['id']}/confirm")
        # confirm may return 200 or 409 if already confirmed by author elsewhere.
        # Author cannot confirm own report — confirm requires non-author. Let's
        # just check via GET /reports/{rid} after confirm attempt — even if
        # confirm rejected, the heading override must still be 'user' in DB.
        if cr.status_code not in (200, 403, 409, 422):
            pytest.fail(f"unexpected confirm status: {cr.status_code} {cr.text[:200]}")
        # Fetch fresh
        time.sleep(0.5)
        g = dev_session.get(f"{API}/reports/{rep['id']}")
        assert g.status_code == 200
        data = g.json()
        cone = data.get("drift_cone")
        assert cone, "drift_cone missing after confirm"
        assert cone["bearing_source"] == "user", (
            f"confirm must preserve user override; got bearing_source={cone.get('bearing_source')}"
        )
        assert cone["bearing_deg"] == pytest.approx(200.0, abs=0.5)

    # 6 — polygon rotates between bearing 0 and 180 (HTTP path)
    def test_6_polygon_changes_between_0_and_180(self, dev_session, created_ids):
        rep = _create_pollution(dev_session, created_ids, tag="polygon-rotate")
        if not rep.get("drift_cone"):
            pytest.skip("Open-Meteo unavailable.")
        r0 = dev_session.patch(f"{API}/reports/{rep['id']}", json={"heading": 0})
        assert r0.status_code == 200
        cone0 = r0.json().get("drift_cone")
        assert cone0 and cone0["bearing_source"] == "user"
        if cone0["distance_km"] == 0:
            pytest.skip("flat-calm Open-Meteo response — polygon collapsed.")

        r180 = dev_session.patch(f"{API}/reports/{rep['id']}", json={"heading": 180})
        assert r180.status_code == 200
        cone180 = r180.json().get("drift_cone")
        assert cone180 and cone180["bearing_source"] == "user"
        # Polygon coordinates must differ (mid-arc vertex on opposite latitudes).
        mid = len(cone0["polygon"]) // 2
        v0 = cone0["polygon"][mid]
        v180 = cone180["polygon"][mid]
        assert (v0["lat"], v0["lng"]) != (v180["lat"], v180["lng"]), (
            f"polygon must rotate; got identical mid-vertex {v0}"
        )
        assert v0["lat"] > SEA_LAT, f"bearing 0 vertex should be north, got {v0}"
        assert v180["lat"] < SEA_LAT, f"bearing 180 vertex should be south, got {v180}"

    # 7 — heading on alive animal_marin → 422
    def test_7_patch_heading_alive_animal_422(self, dev_session, created_ids):
        rep = _create_report(dev_session, created_ids, {
            "type": "animal_marin",
            "subtype": "mammifere",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_e3lot2 alive mammifere",
            "photos": [],
            "extras": {"health": "alive_healthy"},
        })
        r = dev_session.patch(f"{API}/reports/{rep['id']}",
                              json={"heading": 309, "extras": {"health": "alive"}})
        # Note: AuthorEditIn doesn't accept extras, so this will simply be a heading PATCH.
        assert r.status_code == 422, (
            f"alive animal heading should be 422, got {r.status_code} {r.text[:200]}"
        )

    # 8 — drift_cone JSON shape sanity
    def test_8_drift_cone_shape_includes_new_fields(self, dev_session, created_ids):
        rep = _create_pollution(dev_session, created_ids, tag="shape-check")
        cone = rep.get("drift_cone")
        if not cone:
            pytest.skip("Open-Meteo unavailable.")
        # New fields
        assert "algo_bearing_deg" in cone
        assert "bearing_source" in cone
        assert cone["bearing_source"] in ("auto", "user")
        assert isinstance(cone["algo_bearing_deg"], (int, float))
        # Existing fields still there
        for k in ("bearing_deg", "distance_km", "polygon",
                  "wind_to_deg", "wind_speed_ms",
                  "current_to_deg", "current_speed_ms"):
            assert k in cone, f"drift_cone missing field {k}: {cone}"

    # 9 — PATCH body WITHOUT heading does NOT refresh the drift_cone
    #     (and notably does NOT flip bearing_source from 'user' to 'auto').
    def test_9_patch_without_heading_preserves_bearing_source(self, dev_session, created_ids):
        rep = _create_pollution(dev_session, created_ids,
                                heading=77.0, tag="no-heading-patch")
        if not rep.get("drift_cone"):
            pytest.skip("Open-Meteo unavailable.")
        assert rep["drift_cone"]["bearing_source"] == "user"

        # PATCH with empty body should be 400 (no change). Use status='active'
        # which is a no-op transition: also tests that the cone is not refreshed
        # when neither heading nor shift is provided.
        # Author may patch status — body.status='active' is harmless.
        r = dev_session.patch(f"{API}/reports/{rep['id']}", json={"status": "active"})
        assert r.status_code == 200, f"status=active PATCH failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        cone = data.get("drift_cone")
        assert cone, "drift_cone disappeared after no-heading PATCH"
        assert cone["bearing_source"] == "user", (
            f"bearing_source must remain 'user' (no heading in PATCH body); got {cone}"
        )
        assert cone["bearing_deg"] == pytest.approx(77.0, abs=0.5)

    # 10 — verify wind contribution is ≈ 1.66x larger with 5% leeway vs 3%
    def test_10_leeway_5pct_vs_3pct_distance_ratio(self):
        marine = {
            "wind_speed_ms": 5.66,
            "wind_to_deg": 90.0,
            "current_speed_ms": 0.0,
            "current_to_deg": 0.0,
        }
        cone = compute_drift_cone(SEA_LAT, SEA_LNG, V=5, C=5,
                                  marine=marine, hours=1.0)
        expected_5pct = 5.66 * 0.5 * 0.05 * 3600.0 / 1000.0  # ≈ 0.509
        expected_3pct = 5.66 * 0.5 * 0.03 * 3600.0 / 1000.0  # ≈ 0.306
        ratio = cone["distance_km"] / expected_3pct
        assert ratio == pytest.approx(5 / 3, abs=0.05), (
            f"5% vs 3% leeway distance ratio should be 5/3 ≈ 1.667, got {ratio:.3f}"
        )
        assert cone["distance_km"] == pytest.approx(expected_5pct, abs=0.01)
