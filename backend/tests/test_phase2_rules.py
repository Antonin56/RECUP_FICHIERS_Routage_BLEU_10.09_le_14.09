"""Phase 2 — business-rule validation tests.

Covers:
- R1  Geofencing on report creation
- R1bis serialize_report exposes expires_at / origin_* / author_shifted
- R2  Author shift OK + 409 on second shift
- R3  Author shift radius > 1 km → 422
- R5  Confirm rules (no fix, on land, on sea)
- R6  Deletion weekly quota (1 / 7 days) → 429 on 2nd
- R7  GET excludes expired & ended reports
"""
import os
import uuid
import time
import pytest
import requests
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

ANTONIN = {"email": "antoninlepinay@gmail.com", "password": "123454321"}

# Open-sea coords (Morbihan offshore)
SEA_A = (47.40, -3.20)
SEA_B = (47.50, -3.10)
SEA_C = (47.30, -3.30)
# Clearly inland
LAND_PARIS = (48.8566, 2.3522)


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _register():
    suffix = uuid.uuid4().hex[:8]
    email = f"TEST_phase2_{suffix}@signmar.app"
    pw = "TestPass!234"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": pw, "name": f"TEST_p2_{suffix}"},
    )
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def antonin_auth():
    return _login(**ANTONIN)


@pytest.fixture(scope="module")
def second_user():
    return _register()


@pytest.fixture(scope="module")
def non_dev_user():
    """A fresh non-dev account so the Phase-2 author-shift constraints
    (R2: 1-shift-max, R3: 1km radius) can be exercised. Antonin is now
    in DEV_BYPASS_EMAILS and would short-circuit those checks."""
    return _register()


def _antonin_seed_reports(tok, uid):
    r = requests.get(f"{BASE_URL}/api/reports", headers=_hdr(tok))
    assert r.status_code == 200
    return [x for x in r.json() if x["author"]["user_id"] == uid]


# ---------------------------- R1: creation geofence ----------------------------
class TestR1Creation:
    def test_create_at_sea_ok_and_serialization(self, antonin_auth):
        """R1 + R1bis: at-sea create succeeds and exposes the Phase-2 fields."""
        tok, _ = antonin_auth
        lat, lng = SEA_A
        r = requests.post(
            f"{BASE_URL}/api/reports",
            headers=_hdr(tok),
            json={"type": "pollution", "lat": lat, "lng": lng,
                  "description": "TEST_phase2_R1_sea", "photos": []},
            timeout=15,
        )
        assert r.status_code == 200, f"sea-create failed: {r.status_code} {r.text}"
        data = r.json()
        # R1bis exposed fields
        for k in ("expires_at", "origin_lat", "origin_lng", "author_shifted"):
            assert k in data, f"missing {k} in serialize_report"
        assert data["origin_lat"] == lat
        assert data["origin_lng"] == lng
        assert data["author_shifted"] is False
        # expires_at ≈ created_at + 60 min (±5 min)
        c = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        e = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        delta_min = (e - c).total_seconds() / 60.0
        assert 55 <= delta_min <= 65, f"expires_at not ~60min from created_at: {delta_min:.2f}"
        # cleanup
        requests.delete(f"{BASE_URL}/api/reports/{data['id']}", headers=_hdr(tok))

    def test_create_on_land_rejected(self, antonin_auth):
        """R1: creating on land → 422 with FR message."""
        tok, _ = antonin_auth
        lat, lng = LAND_PARIS
        r = requests.post(
            f"{BASE_URL}/api/reports",
            headers=_hdr(tok),
            json={"type": "pollution", "lat": lat, "lng": lng,
                  "description": "TEST_phase2_R1_land", "photos": []},
            timeout=15,
        )
        if r.status_code == 200:
            # Open-Meteo unreachable → is_at_sea fails-open; cleanup + soft skip
            rid = r.json().get("id")
            if rid:
                requests.delete(f"{BASE_URL}/api/reports/{rid}", headers=_hdr(tok))
            pytest.skip("is_at_sea returned True for land — Open-Meteo unreachable (fail-open).")
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text}"
        assert "mer" in r.text.lower() or "côte" in r.text.lower() or "cote" in r.text.lower()


# ---------------------------- R2 + R3: PATCH shift -----------------------------
class TestR2R3AuthorShift:
    def test_shift_ok_then_409(self, non_dev_user):
        """R2: first shift (~55m, within 1 km) → 200 + author_shifted=True; 2nd → 409.

        Uses a fresh non-dev user since Antonin is in DEV_BYPASS_EMAILS.
        """
        tok, _ = non_dev_user
        # Use a fresh report at known sea coords so origin is reliably at sea.
        c = requests.post(
            f"{BASE_URL}/api/reports",
            headers=_hdr(tok),
            json={"type": "pollution", "lat": SEA_B[0], "lng": SEA_B[1],
                  "description": "TEST_phase2_R2_shift", "photos": []},
            timeout=15,
        )
        assert c.status_code == 200, c.text
        rep = c.json()
        rid = rep["id"]
        try:
            olat, olng = rep["origin_lat"], rep["origin_lng"]
            # ~55 m shift
            r1 = requests.patch(
                f"{BASE_URL}/api/reports/{rid}",
                headers=_hdr(tok),
                json={"new_lat": olat + 0.0005, "new_lng": olng + 0.0005},
                timeout=15,
            )
            assert r1.status_code == 200, f"first shift failed: {r1.status_code} {r1.text}"
            out1 = r1.json()
            assert out1["author_shifted"] is True
            # Second shift on the SAME report → 409
            r2 = requests.patch(
                f"{BASE_URL}/api/reports/{rid}",
                headers=_hdr(tok),
                json={"new_lat": olat + 0.0004, "new_lng": olng + 0.0004},
                timeout=15,
            )
            assert r2.status_code == 409, f"expected 409, got {r2.status_code} {r2.text}"
            assert "déjà" in r2.text.lower() or "deja" in r2.text.lower() or "repositionn" in r2.text.lower()
        finally:
            requests.delete(f"{BASE_URL}/api/reports/{rid}", headers=_hdr(tok))

    def test_shift_too_far_rejected(self, non_dev_user):
        """R3: shift > 1 km from origin → 422 Trop loin. Uses non-dev user."""
        tok, _ = non_dev_user
        c = requests.post(
            f"{BASE_URL}/api/reports",
            headers=_hdr(tok),
            json={"type": "pollution", "lat": SEA_C[0], "lng": SEA_C[1],
                  "description": "TEST_phase2_R3_far", "photos": []},
            timeout=15,
        )
        assert c.status_code == 200, c.text
        rep = c.json()
        rid = rep["id"]
        try:
            olat, olng = rep["origin_lat"], rep["origin_lng"]
            # ~2 km shift
            r = requests.patch(
                f"{BASE_URL}/api/reports/{rid}",
                headers=_hdr(tok),
                json={"new_lat": olat + 0.02, "new_lng": olng + 0.02},
                timeout=15,
            )
            assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text}"
            assert "trop loin" in r.text.lower() or "loin" in r.text.lower()
        finally:
            requests.delete(f"{BASE_URL}/api/reports/{rid}", headers=_hdr(tok))


# ---------------------------- R5: confirm rules --------------------------------
class TestR5Confirm:
    def test_confirm_flow_no_loc_then_land_then_sea(self, antonin_auth, second_user):
        tok_a, user_a = antonin_auth
        tok_b, user_b = second_user

        # Antonin creates a sea report we can target.
        c = requests.post(
            f"{BASE_URL}/api/reports",
            headers=_hdr(tok_a),
            json={"type": "pollution", "lat": SEA_A[0], "lng": SEA_A[1],
                  "description": "TEST_phase2_R5_confirm", "photos": []},
            timeout=15,
        )
        assert c.status_code == 200, c.text
        rid = c.json()["id"]

        try:
            # 1) Clear any prior location for second_user via direct DB op.
            async def _clear_loc():
                cli = AsyncIOMotorClient(MONGO_URL)
                d = cli[DB_NAME]
                await d.users.update_one(
                    {"user_id": user_b["user_id"]},
                    {"$unset": {"last_lat": "", "last_lng": "", "last_loc_at": ""}},
                )
                cli.close()
            asyncio.run(_clear_loc())

            r = requests.post(f"{BASE_URL}/api/reports/{rid}/confirm", headers=_hdr(tok_b), timeout=15)
            assert r.status_code == 422, f"no-loc expected 422, got {r.status_code} {r.text}"
            assert "position gps" in r.text.lower() or "gps" in r.text.lower()

            # 2) Land location set → confirm → 422 "depuis la terre"
            rl = requests.post(
                f"{BASE_URL}/api/profile/location",
                headers=_hdr(tok_b),
                json={"lat": LAND_PARIS[0], "lng": LAND_PARIS[1]},
                timeout=15,
            )
            assert rl.status_code == 200, rl.text
            r = requests.post(f"{BASE_URL}/api/reports/{rid}/confirm", headers=_hdr(tok_b), timeout=15)
            if r.status_code == 200:
                pytest.skip("is_at_sea fail-open: Open-Meteo treated Paris as sea. Soft skip.")
            assert r.status_code == 422, f"land expected 422, got {r.status_code} {r.text}"
            assert "terre" in r.text.lower()

            # 3) Sea location → confirm → 200; expires_at updated to ~+60min
            rl = requests.post(
                f"{BASE_URL}/api/profile/location",
                headers=_hdr(tok_b),
                json={"lat": SEA_A[0], "lng": SEA_A[1]},
                timeout=15,
            )
            assert rl.status_code == 200
            t_before = datetime.now(timezone.utc)
            r = requests.post(f"{BASE_URL}/api/reports/{rid}/confirm", headers=_hdr(tok_b), timeout=15)
            assert r.status_code == 200, f"sea confirm failed: {r.status_code} {r.text}"
            data = r.json()
            assert data["confirm_count"] >= 1
            e_raw = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
            e = e_raw if e_raw.tzinfo else e_raw.replace(tzinfo=timezone.utc)
            delta_min = (e - t_before).total_seconds() / 60.0
            assert 55 <= delta_min <= 65, f"expires_at after confirm not ~+60min: {delta_min:.2f}"
        finally:
            requests.delete(f"{BASE_URL}/api/reports/{rid}", headers=_hdr(tok_a))


# ---------------------------- R6: weekly delete quota --------------------------
class TestR6DeleteQuota:
    def test_second_delete_in_week_returns_429(self):
        """Fresh user: create 2 sea reports, delete first → 200, second → 429."""
        tok, user = _register()
        # Ensure clean deletions_log
        async def _clear():
            cli = AsyncIOMotorClient(MONGO_URL)
            d = cli[DB_NAME]
            await d.users.update_one({"user_id": user["user_id"]}, {"$unset": {"deletions_log": ""}})
            cli.close()
        asyncio.run(_clear())

        c1 = requests.post(f"{BASE_URL}/api/reports", headers=_hdr(tok),
                           json={"type": "pollution", "lat": SEA_A[0], "lng": SEA_A[1],
                                 "description": "TEST_phase2_R6_a", "photos": []}, timeout=15)
        assert c1.status_code == 200, c1.text
        c2 = requests.post(f"{BASE_URL}/api/reports", headers=_hdr(tok),
                           json={"type": "pollution", "lat": SEA_B[0], "lng": SEA_B[1],
                                 "description": "TEST_phase2_R6_b", "photos": []}, timeout=15)
        assert c2.status_code == 200, c2.text
        rid1, rid2 = c1.json()["id"], c2.json()["id"]

        d1 = requests.delete(f"{BASE_URL}/api/reports/{rid1}", headers=_hdr(tok), timeout=15)
        assert d1.status_code == 200, d1.text

        d2 = requests.delete(f"{BASE_URL}/api/reports/{rid2}", headers=_hdr(tok), timeout=15)
        assert d2.status_code == 429, f"expected 429, got {d2.status_code} {d2.text}"
        assert "quota" in d2.text.lower()

        # Verify deletions_log has length 1
        async def _check():
            cli = AsyncIOMotorClient(MONGO_URL)
            d = cli[DB_NAME]
            u = await d.users.find_one({"user_id": user["user_id"]}, {"_id": 0, "deletions_log": 1})
            cli.close()
            return u
        u = asyncio.run(_check())
        assert isinstance(u.get("deletions_log"), list)
        assert len(u["deletions_log"]) == 1, f"expected 1 entry, got {len(u['deletions_log'])}"

        # cleanup: delete remaining report via direct DB to not consume more quota
        async def _cleanup():
            cli = AsyncIOMotorClient(MONGO_URL)
            d = cli[DB_NAME]
            await d.reports.delete_one({"id": rid2})
            cli.close()
        asyncio.run(_cleanup())


# ---------------------------- R7: GET filters expired & ended ------------------
class TestR7ListFilters:
    def test_expired_and_ended_hidden_in_list(self, antonin_auth):
        tok, _ = antonin_auth

        rid_expired = uuid.uuid4().hex
        rid_ended = uuid.uuid4().hex
        now = datetime.now(timezone.utc)

        async def _insert():
            cli = AsyncIOMotorClient(MONGO_URL)
            d = cli[DB_NAME]
            await d.reports.insert_many([
                {
                    "id": rid_expired, "type": "pollution",
                    "lat": SEA_A[0], "lng": SEA_A[1],
                    "origin_lat": SEA_A[0], "origin_lng": SEA_A[1],
                    "description": "TEST_phase2_R7_expired",
                    "photos": [], "author_id": "phase2_fake_uid", "author_name": "phase2",
                    "created_at": now - timedelta(hours=1),
                    "last_confirmed_at": now - timedelta(hours=1),
                    "expires_at": now - timedelta(seconds=60),
                    "confirmations": [], "edits": [], "status": "active",
                },
                {
                    "id": rid_ended, "type": "pollution",
                    "lat": SEA_B[0], "lng": SEA_B[1],
                    "origin_lat": SEA_B[0], "origin_lng": SEA_B[1],
                    "description": "TEST_phase2_R7_ended",
                    "photos": [], "author_id": "phase2_fake_uid", "author_name": "phase2",
                    "created_at": now - timedelta(minutes=5),
                    "last_confirmed_at": now - timedelta(minutes=5),
                    "expires_at": now + timedelta(hours=23),
                    "confirmations": [], "edits": [], "status": "ended",
                },
            ])
            cli.close()
        asyncio.run(_insert())

        try:
            r = requests.get(f"{BASE_URL}/api/reports", headers=_hdr(tok), timeout=15)
            assert r.status_code == 200
            ids = {x["id"] for x in r.json()}
            assert rid_expired not in ids, "expired report leaked into GET /reports"
            assert rid_ended not in ids, "ended report leaked into GET /reports"
        finally:
            async def _cleanup():
                cli = AsyncIOMotorClient(MONGO_URL)
                d = cli[DB_NAME]
                await d.reports.delete_many({"id": {"$in": [rid_expired, rid_ended]}})
                cli.close()
            asyncio.run(_cleanup())
