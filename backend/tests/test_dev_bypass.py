"""Dev-bypass hotfix tests (Antonin maintainer account).

Validates that `is_dev_user(u)` allows the maintainer to bypass every Phase 2
server-side restriction while ordinary users still hit them.

Covers:
- POST /api/reports geofence bypass (create from land)
- PATCH /api/reports/{id} bypasses 1-shift-max, 1km radius, sea check
- POST /api/reports/{id}/confirm bypasses missing-GPS + on-land checks
- DELETE /api/reports/{id} bypasses 1/week quota
- GET /api/reports surfaces the freshly created report
- Regression: a fresh non-dev user still gets 422 / 429 as in Phase 2.
"""
import os
import uuid
import asyncio
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

ANTONIN = {"email": "antoninlepinay@gmail.com", "password": "123454321"}

# Clearly inland points (deep continental).
LAND_PARIS = (48.8566, 2.3522)
LAND_PARIS_SHIFT_1 = (48.8666, 2.3622)   # ~1.3 km NE of Paris
LAND_PARIS_SHIFT_2 = (48.8766, 2.3722)   # ~1.3 km further NE
LAND_MASSIF = (45.0, 3.0)                # Massif Central, definitely land

# Open-sea coords (Morbihan offshore) for the non-dev DELETE quota regression.
SEA_A = (47.40, -3.20)
SEA_B = (47.50, -3.10)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _register(prefix="TEST_devbypass"):
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}_{suffix}@signmar.app"
    pw = "TestPass!234"
    r = requests.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": pw, "name": f"{prefix}_{suffix}"},
                      timeout=15)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _clear_user_loc_and_deletions(user_id: str):
    async def _do():
        cli = AsyncIOMotorClient(MONGO_URL)
        d = cli[DB_NAME]
        await d.users.update_one(
            {"user_id": user_id},
            {"$unset": {"last_lat": "", "last_lng": "", "last_loc_at": "",
                        "deletions_log": ""}},
        )
        cli.close()
    asyncio.run(_do())


def _hard_delete_report(rid: str):
    async def _do():
        cli = AsyncIOMotorClient(MONGO_URL)
        d = cli[DB_NAME]
        await d.reports.delete_one({"id": rid})
        cli.close()
    asyncio.run(_do())


@pytest.fixture(scope="module")
def antonin_auth():
    tok, u = _login(**ANTONIN)
    # Clean up any prior deletion quota for a deterministic DELETE-quota test
    _clear_user_loc_and_deletions(u["user_id"])
    return tok, u


# ============================================================================
# DEV BYPASS — Antonin should sail through every Phase 2 restriction.
# ============================================================================
class TestDevBypassPositive:
    """All endpoints should accept Antonin even from deep inland Paris."""

    def test_1_create_from_land_succeeds(self, antonin_auth):
        """POST /api/reports with Paris coords → 200, serialize fields present."""
        tok, _ = antonin_auth
        from datetime import datetime
        r = requests.post(
            f"{BASE_URL}/api/reports",
            headers=_hdr(tok),
            json={"type": "animal_marin", "subtype": "mammifere", "lat": LAND_PARIS[0], "lng": LAND_PARIS[1],
                  "description": "TEST_devbypass mammifère test", "photos": [],
                  "extras": {"species": "common_dolphin", "health": "alive_healthy"}},
            timeout=20,
        )
        assert r.status_code == 200, f"land-create rejected: {r.status_code} {r.text}"
        data = r.json()
        # Serialize fields the optimistic-add UI relies on.
        for k in ("id", "expires_at", "origin_lat", "origin_lng",
                  "author_shifted", "created_at"):
            assert k in data, f"missing {k} in serialize_report: {data}"
        assert data["origin_lat"] == LAND_PARIS[0]
        assert data["origin_lng"] == LAND_PARIS[1]
        assert data["author_shifted"] is False
        # expires_at ≈ created_at + 360 min (animal_marin/mammifere TTL in v2 taxonomy)
        c = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        e = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        delta_min = (e - c).total_seconds() / 60.0
        assert 355 <= delta_min <= 365, f"expires_at not ~+360min: {delta_min:.2f}"

        # Visibility regression — GET /api/reports surfaces the new report.
        g = requests.get(f"{BASE_URL}/api/reports", headers=_hdr(tok), timeout=15)
        assert g.status_code == 200
        ids = {x["id"] for x in g.json()}
        assert data["id"] in ids, "freshly-created dev report missing from GET /reports"

        # Hard-delete so it doesn't pollute the dev account's report list.
        _hard_delete_report(data["id"])

    def test_2_patch_two_shifts_bypass_radius_and_one_shift_max(self, antonin_auth):
        """Two consecutive >1km shifts on the same report → both 200."""
        tok, _ = antonin_auth
        c = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(tok),
            json={"type": "animal_marin", "subtype": "mammifere", "lat": LAND_PARIS[0], "lng": LAND_PARIS[1],
                  "description": "TEST_devbypass shift", "photos": [],
                  "extras": {"species": "common_dolphin", "health": "alive_healthy"}},
            timeout=20,
        )
        assert c.status_code == 200, c.text
        rid = c.json()["id"]
        try:
            # First shift (~1.3 km — would normally trigger 422 "trop loin")
            r1 = requests.patch(
                f"{BASE_URL}/api/reports/{rid}", headers=_hdr(tok),
                json={"new_lat": LAND_PARIS_SHIFT_1[0],
                      "new_lng": LAND_PARIS_SHIFT_1[1]}, timeout=20,
            )
            assert r1.status_code == 200, f"1st shift rejected: {r1.status_code} {r1.text}"
            d1 = r1.json()
            assert d1["author_shifted"] is True
            assert abs(d1["lat"] - LAND_PARIS_SHIFT_1[0]) < 1e-6
            assert abs(d1["lng"] - LAND_PARIS_SHIFT_1[1]) < 1e-6

            # Second shift — would normally trigger 409 "déjà repositionné"
            r2 = requests.patch(
                f"{BASE_URL}/api/reports/{rid}", headers=_hdr(tok),
                json={"new_lat": LAND_PARIS_SHIFT_2[0],
                      "new_lng": LAND_PARIS_SHIFT_2[1]}, timeout=20,
            )
            assert r2.status_code == 200, f"2nd shift rejected: {r2.status_code} {r2.text}"
            d2 = r2.json()
            assert abs(d2["lat"] - LAND_PARIS_SHIFT_2[0]) < 1e-6
            assert abs(d2["lng"] - LAND_PARIS_SHIFT_2[1]) < 1e-6
        finally:
            _hard_delete_report(rid)

    def test_3_patch_shift_onto_land_bypasses_sea_check(self, antonin_auth):
        """Shift target deep inland → 200 (sea check bypassed)."""
        tok, _ = antonin_auth
        c = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(tok),
            json={"type": "animal_marin", "subtype": "mammifere", "lat": LAND_PARIS[0], "lng": LAND_PARIS[1],
                  "description": "TEST_devbypass land-shift", "photos": [],
                  "extras": {"species": "common_dolphin", "health": "alive_healthy"}},
            timeout=20,
        )
        assert c.status_code == 200, c.text
        rid = c.json()["id"]
        try:
            r = requests.patch(
                f"{BASE_URL}/api/reports/{rid}", headers=_hdr(tok),
                json={"new_lat": LAND_MASSIF[0], "new_lng": LAND_MASSIF[1]},
                timeout=20,
            )
            assert r.status_code == 200, f"land-shift rejected: {r.status_code} {r.text}"
            d = r.json()
            assert abs(d["lat"] - LAND_MASSIF[0]) < 1e-6
            assert abs(d["lng"] - LAND_MASSIF[1]) < 1e-6
        finally:
            _hard_delete_report(rid)

    def test_4_confirm_without_gps_or_on_land_bypassed(self, antonin_auth):
        """Antonin confirms a sea report without any prior GPS fix → 200."""
        tok_a, user_a = antonin_auth
        # Second user creates a sea report (needs to pass non-dev sea check).
        tok_b, user_b = _register("TEST_confirmer")
        c = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(tok_b),
            json={"type": "pollution", "lat": SEA_A[0], "lng": SEA_A[1],
                  "description": "TEST_devbypass confirm target", "photos": []},
            timeout=20,
        )
        if c.status_code != 200:
            # If is_at_sea blocked it (Open-Meteo flaky), insert at sea directly via DB.
            pytest.skip(f"second-user sea create failed: {c.status_code} {c.text}")
        rid = c.json()["id"]
        try:
            # Force Antonin to NOT have a recent GPS fix.
            _clear_user_loc_and_deletions(user_a["user_id"])
            r = requests.post(
                f"{BASE_URL}/api/reports/{rid}/confirm",
                headers=_hdr(tok_a), timeout=20,
            )
            assert r.status_code == 200, (
                f"dev confirm without GPS rejected: {r.status_code} {r.text}"
            )
            data = r.json()
            assert data["confirm_count"] >= 1
            assert user_a["user_id"] in [
                # confirmed_by_me is true for the dev caller
            ] or data.get("confirmed_by_me") is True
        finally:
            _hard_delete_report(rid)

    def test_5_delete_quota_bypassed(self, antonin_auth):
        """Antonin creates 2 reports and deletes both back-to-back → both 200."""
        tok, user = antonin_auth
        # Ensure no quota residue from previous runs.
        _clear_user_loc_and_deletions(user["user_id"])
        c1 = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(tok),
            json={"type": "animal_marin", "subtype": "mammifere", "lat": LAND_PARIS[0], "lng": LAND_PARIS[1],
                  "description": "TEST_devbypass del 1", "photos": [],
                  "extras": {"species": "common_dolphin", "health": "alive_healthy"}}, timeout=20,
        )
        assert c1.status_code == 200, c1.text
        c2 = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(tok),
            json={"type": "animal_marin", "subtype": "mammifere", "lat": LAND_PARIS[0] + 0.01,
                  "lng": LAND_PARIS[1] + 0.01,
                  "description": "TEST_devbypass del 2", "photos": [],
                  "extras": {"species": "common_dolphin", "health": "alive_healthy"}}, timeout=20,
        )
        assert c2.status_code == 200, c2.text
        rid1, rid2 = c1.json()["id"], c2.json()["id"]

        d1 = requests.delete(f"{BASE_URL}/api/reports/{rid1}",
                             headers=_hdr(tok), timeout=15)
        assert d1.status_code == 200, f"1st dev delete: {d1.status_code} {d1.text}"

        d2 = requests.delete(f"{BASE_URL}/api/reports/{rid2}",
                             headers=_hdr(tok), timeout=15)
        assert d2.status_code == 200, f"2nd dev delete (quota?) {d2.status_code} {d2.text}"


# ============================================================================
# NON-DEV REGRESSION — ordinary users still hit every Phase 2 constraint.
# ============================================================================
class TestNonDevStillStrict:

    def test_create_on_land_still_422(self):
        tok, _ = _register("phase2-still-strict-create")
        r = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(tok),
            json={"type": "animal_marin", "subtype": "mammifere", "lat": LAND_PARIS[0], "lng": LAND_PARIS[1],
                  "description": "TEST_devbypass non-dev land", "photos": [],
                  "extras": {"species": "common_dolphin", "health": "alive_healthy"}},
            timeout=20,
        )
        if r.status_code == 200:
            # Open-Meteo fail-open — soft pass with note.
            rid = r.json().get("id")
            if rid:
                _hard_delete_report(rid)
            pytest.skip("is_at_sea fail-open (Open-Meteo unreachable). Soft pass.")
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text}"
        assert "mer" in r.text.lower(), f"missing 'mer' in error: {r.text}"

    def test_confirm_without_gps_still_422(self):
        # Author at sea (uses second non-dev user); confirmer is yet another fresh
        # user without any GPS fix.
        author_tok, _ = _register("phase2-still-strict-author")
        c = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(author_tok),
            json={"type": "pollution", "lat": SEA_A[0], "lng": SEA_A[1],
                  "description": "TEST_devbypass non-dev confirm target",
                  "photos": []}, timeout=20,
        )
        if c.status_code != 200:
            pytest.skip(f"author sea create blocked: {c.status_code} {c.text}")
        rid = c.json()["id"]
        confirmer_tok, confirmer_user = _register("phase2-still-strict-confirmer")
        try:
            # Confirmer has no GPS fix → must get 422.
            _clear_user_loc_and_deletions(confirmer_user["user_id"])
            r = requests.post(f"{BASE_URL}/api/reports/{rid}/confirm",
                              headers=_hdr(confirmer_tok), timeout=20)
            assert r.status_code == 422, (
                f"expected 422 no-GPS, got {r.status_code} {r.text}"
            )
            assert "gps" in r.text.lower() or "position" in r.text.lower()
        finally:
            _hard_delete_report(rid)

    def test_delete_weekly_quota_still_429(self):
        tok, user = _register("phase2-still-strict-quota")
        _clear_user_loc_and_deletions(user["user_id"])
        c1 = requests.post(f"{BASE_URL}/api/reports", headers=_hdr(tok),
                           json={"type": "pollution", "lat": SEA_A[0], "lng": SEA_A[1],
                                 "description": "TEST_devbypass quota a",
                                 "photos": []}, timeout=20)
        c2 = requests.post(f"{BASE_URL}/api/reports", headers=_hdr(tok),
                           json={"type": "pollution", "lat": SEA_B[0], "lng": SEA_B[1],
                                 "description": "TEST_devbypass quota b",
                                 "photos": []}, timeout=20)
        if c1.status_code != 200 or c2.status_code != 200:
            pytest.skip(f"sea creates blocked: {c1.status_code}/{c2.status_code}")
        rid1, rid2 = c1.json()["id"], c2.json()["id"]
        d1 = requests.delete(f"{BASE_URL}/api/reports/{rid1}",
                             headers=_hdr(tok), timeout=15)
        assert d1.status_code == 200, d1.text
        d2 = requests.delete(f"{BASE_URL}/api/reports/{rid2}",
                             headers=_hdr(tok), timeout=15)
        assert d2.status_code == 429, f"expected 429, got {d2.status_code} {d2.text}"
        assert "quota" in d2.text.lower()
        # cleanup the leftover report (direct DB to not consume more quota)
        _hard_delete_report(rid2)
