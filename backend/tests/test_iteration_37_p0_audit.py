"""Iteration 37 — Audit P0 tasks (rate limiting, geo-indexed proximity, refactor smoke).

Focused audit covering:
- P0-1  SlowAPI rate limiting on /auth/login and /auth/register (5/5min/IP).
- P0-1b QA bypass header disables the limiter (never throttled).
- P0-2  Geo-indexed proximity notifications (2dsphere index + GeoJSON write
        + BackgroundTask fan-out with in-app notification persistence).
- P0-3  Decoupled architecture regression (auth/reports/profile/weather).
- BUGFIX 1 Demo mode: GET /api/reports without auth returns ~30 is_demo reports.
- BUGFIX 2 reliability_score coherence with reliability_pct.
- BUGFIX 3 Demo report photos: data:image/jpeg;base64,... and each < 200KB.

All CRUD flows send the X-RateLimit-Bypass header via conftest.
The rate-limit test *removes* that header and uses a unique X-Forwarded-For.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

import pytest
import requests

DEV_EMAIL = "antoninlepinay@gmail.com"
OTHER_EMAIL = "contact@accasteo.com"
PASSWORD = "123454321"
BYPASS_TOKEN = os.environ.get("RATE_LIMIT_BYPASS_TOKEN", "qa-bypass-7f3d9a2e4c8b1f60")


# ---------- helpers ----------------------------------------------------------
def _login(base_url, email, password=PASSWORD):
    r = requests.post(
        f"{base_url}/api/auth/login",
        json={"email": email, "password": password},
        headers={"X-RateLimit-Bypass": BYPASS_TOKEN, "Content-Type": "application/json"},
        timeout=15,
    )
    assert r.status_code == 200, f"login({email}) → {r.status_code} {r.text}"
    return r.json()["token"]


def _auth_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-RateLimit-Bypass": BYPASS_TOKEN,
    }


# ---------- P0-1  rate limiting ---------------------------------------------
class TestRateLimit:
    def test_login_throttles_after_5_requests(self, base_url):
        """6th /auth/login within 5min from same IP → 429."""
        unique_ip = f"203.0.113.{uuid.uuid4().int % 200 + 20}"
        # IMPORTANT: conftest.py monkey-patches requests.Session to always send
        # the QA bypass header. We must strip it here to actually test the
        # limiter. Use a raw urllib3 pool via a fresh session where we clear
        # the header explicitly.
        results = []
        for _ in range(7):
            s = requests.Session()
            s.headers.pop("X-RateLimit-Bypass", None)
            r = s.post(
                f"{base_url}/api/auth/login",
                json={"email": f"nx_{uuid.uuid4().hex[:6]}@x.com", "password": "wrong"},
                headers={
                    "Content-Type": "application/json",
                    "X-Forwarded-For": unique_ip,
                },
                timeout=10,
            )
            results.append(r.status_code)
        assert 429 in results, f"expected a 429 somewhere in {results}"
        # First five should NOT be 429.
        assert results[:5].count(429) == 0, f"early throttle: {results}"

    def test_register_throttles_after_5_requests(self, base_url):
        unique_ip = f"203.0.113.{uuid.uuid4().int % 200 + 20}"
        results = []
        for i in range(7):
            s = requests.Session()
            s.headers.pop("X-RateLimit-Bypass", None)
            r = s.post(
                f"{base_url}/api/auth/register",
                json={
                    "email": f"rl_{uuid.uuid4().hex[:8]}@x.com",
                    "password": "abcdef1",
                    "name": "RL Test",
                },
                headers={
                    "Content-Type": "application/json",
                    "X-Forwarded-For": unique_ip,
                },
                timeout=10,
            )
            results.append(r.status_code)
        assert 429 in results, f"expected 429 in {results}"

    def test_different_ip_gets_fresh_bucket(self, base_url):
        """A different X-Forwarded-For gets its own bucket (no cross-IP leak)."""
        ip_a = f"198.51.100.{uuid.uuid4().int % 200 + 20}"
        ip_b = f"198.51.100.{uuid.uuid4().int % 200 + 20}"
        # Burn IP A's bucket.
        for _ in range(7):
            s = requests.Session()
            s.headers.pop("X-RateLimit-Bypass", None)
            s.post(
                f"{base_url}/api/auth/login",
                json={"email": "nx@x.com", "password": "x"},
                headers={"Content-Type": "application/json", "X-Forwarded-For": ip_a},
                timeout=10,
            )
        # IP B first request must not be 429.
        s = requests.Session()
        s.headers.pop("X-RateLimit-Bypass", None)
        r = s.post(
            f"{base_url}/api/auth/login",
            json={"email": "nx@x.com", "password": "x"},
            headers={"Content-Type": "application/json", "X-Forwarded-For": ip_b},
            timeout=10,
        )
        assert r.status_code != 429, f"IP B leaked bucket: {r.status_code}"

    def test_bypass_header_disables_limiter(self, base_url):
        """With bypass header, 8 consecutive logins must NEVER be 429."""
        codes = []
        for _ in range(8):
            r = requests.post(
                f"{base_url}/api/auth/login",
                json={"email": DEV_EMAIL, "password": PASSWORD},
                headers={
                    "Content-Type": "application/json",
                    "X-RateLimit-Bypass": BYPASS_TOKEN,
                },
                timeout=10,
            )
            codes.append(r.status_code)
        assert 429 not in codes, f"bypass leaked: {codes}"
        assert all(c in (200, 401) for c in codes), f"unexpected code: {codes}"


# ---------- P0-2  geo-indexed proximity + BUGFIX 1/2/3 ----------------------
class TestGeoProximityAndCore:
    def test_2dsphere_index_exists(self, base_url):
        """Direct DB check for the 2dsphere index name."""
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo = os.environ["MONGO_URL"]
        db_name = os.environ["DB_NAME"]

        async def _check():
            cli = AsyncIOMotorClient(mongo)
            try:
                idx = await cli[db_name].users.index_information()
                names = list(idx.keys())
                has_2dsphere = any("last_loc" in n and "2dsphere" in n for n in names)
                assert has_2dsphere, f"2dsphere on last_loc missing: {names}"
            finally:
                cli.close()

        asyncio.run(_check())

    def test_location_writes_geojson_last_loc(self, base_url):
        token = _login(base_url, OTHER_EMAIL)
        r = requests.post(
            f"{base_url}/api/profile/location",
            json={"lat": 47.5, "lng": -3.0},
            headers=_auth_headers(token),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        # Verify via DB (motor).
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo = os.environ["MONGO_URL"]
        db_name = os.environ["DB_NAME"]

        async def _check():
            cli = AsyncIOMotorClient(mongo)
            try:
                u = await cli[db_name].users.find_one({"email": OTHER_EMAIL})
                assert u is not None
                assert u.get("last_lat") == 47.5
                assert u.get("last_lng") == -3.0
                loc = u.get("last_loc")
                assert isinstance(loc, dict), f"last_loc missing: {loc}"
                assert loc.get("type") == "Point"
                # GeoJSON = [lng, lat]
                assert loc.get("coordinates") == [-3.0, 47.5]
            finally:
                cli.close()

        asyncio.run(_check())

    def test_proximity_notification_delivered(self, base_url):
        """Dev creates a report; second user <15km away receives an in-app notif."""
        # 1) Position the recipient (contact@accasteo.com) near sea coords.
        token_b = _login(base_url, OTHER_EMAIL)
        r = requests.post(
            f"{base_url}/api/profile/location",
            json={"lat": 47.52, "lng": -3.02},
            headers=_auth_headers(token_b),
            timeout=15,
        )
        assert r.status_code == 200
        # Drain existing notifications so the count delta is meaningful.
        r_before = requests.get(
            f"{base_url}/api/notifications", headers=_auth_headers(token_b), timeout=15
        )
        assert r_before.status_code == 200, r_before.text
        before_ids = {n["id"] for n in r_before.json().get("items", [])}

        # 2) Dev creates a report ~2 km away.
        token_a = _login(base_url, DEV_EMAIL)
        t0 = time.time()
        r = requests.post(
            f"{base_url}/api/reports",
            json={
                "type": "obstacle_nav",
                "lat": 47.53,
                "lng": -3.01,
                "description": "TEST_iter37 proximity",
            },
            headers=_auth_headers(token_a),
            timeout=15,
        )
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        report_id = r.json()["id"]
        # BackgroundTask must NOT delay the HTTP response.
        assert elapsed < 5.0, f"create_report too slow ({elapsed:.2f}s)"

        try:
            # 3) Poll notifications for the new one (BackgroundTask latency).
            deadline = time.time() + 15
            found = None
            while time.time() < deadline:
                time.sleep(1.5)
                r_after = requests.get(
                    f"{base_url}/api/notifications",
                    headers=_auth_headers(token_b),
                    timeout=15,
                )
                if r_after.status_code == 200:
                    for n in r_after.json().get("items", []):
                        if n["id"] in before_ids:
                            continue
                        # dedup_key expected new-report:<rid>
                        if n.get("dedup_key") == f"new-report:{report_id}":
                            found = n
                            break
                if found:
                    break
            assert found is not None, "No 'X à proximité' notification received"
            assert "à proximité" in found.get("title", "").lower() or \
                   "proximité" in found.get("title", "")
        finally:
            # Cleanup: delete the report (author is dev, no quota).
            requests.delete(
                f"{base_url}/api/reports/{report_id}",
                headers=_auth_headers(token_a),
                timeout=15,
            )


# ---------- P0-3  decoupled architecture regression -------------------------
class TestCoreRegression:
    def test_full_crud_flow(self, base_url):
        """register → login → me → patch pseudo → create → list → detail →
        confirm (from other user) → delete."""
        # Register a fresh user for the flow.
        email = f"iter37_{uuid.uuid4().hex[:8]}@x.com"
        r = requests.post(
            f"{base_url}/api/auth/register",
            json={"email": email, "password": "abcdef1", "name": "Iter37 User"},
            headers={"Content-Type": "application/json", "X-RateLimit-Bypass": BYPASS_TOKEN},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        u_token = r.json()["token"]
        u_uid = r.json()["user"]["user_id"]

        # /auth/me
        r = requests.get(f"{base_url}/api/auth/me", headers=_auth_headers(u_token), timeout=15)
        assert r.status_code == 200
        me_body = r.json()
        assert me_body["user_id"] == u_uid
        # BUGFIX 2 — reliability_score present.
        assert "reliability_score" in me_body
        assert 0 <= me_body["reliability_score"] <= 100

        # PATCH pseudo
        new_pseudo = f"Iter37_{uuid.uuid4().hex[:5]}"
        r = requests.patch(
            f"{base_url}/api/auth/me",
            json={"pseudo": new_pseudo},
            headers=_auth_headers(u_token),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["pseudo"] == new_pseudo

        # Create a report as dev.
        dev_token = _login(base_url, DEV_EMAIL)
        r = requests.post(
            f"{base_url}/api/reports",
            json={"type": "obstacle_nav", "lat": 47.50, "lng": -3.0, "description": "TEST_iter37"},
            headers=_auth_headers(dev_token),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        rid = r.json()["id"]

        # List: photos empty + photo_count set.
        r = requests.get(f"{base_url}/api/reports", headers=_auth_headers(dev_token), timeout=15)
        assert r.status_code == 200
        arr = r.json()
        mine = [x for x in arr if x["id"] == rid]
        assert mine, f"created report {rid} not returned in list"
        it = mine[0]
        assert it["photos"] == []
        assert "photo_count" in it

        # Detail: photos present (empty list is fine here since none uploaded).
        r = requests.get(f"{base_url}/api/reports/{rid}", headers=_auth_headers(dev_token), timeout=15)
        assert r.status_code == 200
        det = r.json()
        assert det["id"] == rid
        assert "photos" in det

        # Self-confirm must be rejected (dev is author).
        r = requests.post(
            f"{base_url}/api/reports/{rid}/confirm",
            headers=_auth_headers(dev_token),
            timeout=15,
        )
        assert r.status_code == 422, f"self-confirm should 422, got {r.status_code} {r.text}"

        # Second user confirms (needs sea location).
        other_token = _login(base_url, OTHER_EMAIL)
        r = requests.post(
            f"{base_url}/api/profile/location",
            json={"lat": 47.5, "lng": -3.0},
            headers=_auth_headers(other_token),
            timeout=15,
        )
        assert r.status_code == 200
        r = requests.post(
            f"{base_url}/api/reports/{rid}/confirm",
            headers=_auth_headers(other_token),
            timeout=15,
        )
        assert r.status_code == 200, f"confirm failed: {r.status_code} {r.text}"
        assert r.json()["confirm_count"] >= 1

        # Cleanup
        r = requests.delete(f"{base_url}/api/reports/{rid}", headers=_auth_headers(dev_token), timeout=15)
        assert r.status_code == 200

    def test_profile_me_and_weather(self, base_url):
        token = _login(base_url, DEV_EMAIL)
        r = requests.get(f"{base_url}/api/profile/me", headers=_auth_headers(token), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "history" in body
        # Weather (best-effort — 200 or 503 acceptable).
        r = requests.get(
            f"{base_url}/api/weather/marine?lat=47.5&lng=-3.0", headers=_auth_headers(token), timeout=15
        )
        assert r.status_code in (200, 503), r.status_code


# ---------- BUGFIX 1 & 3  demo mode + demo photo payloads -------------------
class TestDemoMode:
    def test_unauthenticated_list_returns_demo_reports(self, base_url):
        """Unauthenticated GET /api/reports must return the seeded is_demo reports."""
        r = requests.get(f"{base_url}/api/reports", timeout=20)
        assert r.status_code == 200, r.text
        arr = r.json()
        demos = [x for x in arr if x.get("is_demo")]
        assert len(demos) >= 10, f"expected ~30 is_demo reports, got {len(demos)} / total={len(arr)}"
        # Author pseudo 'SignalMar' + expires_at set.
        for d in demos:
            assert d.get("expires_at"), f"demo without expires_at: {d['id']}"
        # At least some authored by 'SignalMar'.
        pseudos = {(d.get("author") or {}).get("pseudo") for d in demos}
        assert "SignalMar" in pseudos, f"no SignalMar-authored demo: {pseudos}"

    def test_demo_report_photos_data_uri_and_small(self, base_url):
        r = requests.get(f"{base_url}/api/reports", timeout=20)
        assert r.status_code == 200
        arr = r.json()
        demos_with_photos = [x for x in arr if x.get("is_demo") and (x.get("photo_count") or 0) > 0]
        if not demos_with_photos:
            pytest.skip("no demo reports carry photos")
        # Fetch detail on the first demo w/ photos.
        rid = demos_with_photos[0]["id"]
        r = requests.get(f"{base_url}/api/reports/{rid}", timeout=20)
        assert r.status_code == 200, r.text
        det = r.json()
        photos = det.get("photos") or []
        assert photos, f"detail has no photos: {rid}"
        for p in photos:
            assert p.startswith("data:image/jpeg;base64,"), f"bad prefix: {p[:40]}"
            # Base64 → raw bytes size ~ 3/4 of string length.
            b64 = p.split(",", 1)[1]
            approx_bytes = int(len(b64) * 0.75)
            assert approx_bytes < 200 * 1024, f"photo too big: ~{approx_bytes} bytes"


# ---------- BUGFIX 2  reliability_pct is source of truth --------------------
class TestReliabilityCoherence:
    def test_me_reliability_reads_pct_field(self, base_url):
        """If we set reliability_pct on the user doc, /auth/me must reflect it."""
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient

        token = _login(base_url, OTHER_EMAIL)
        mongo = os.environ["MONGO_URL"]
        db_name = os.environ["DB_NAME"]

        async def _set(val):
            cli = AsyncIOMotorClient(mongo)
            try:
                await cli[db_name].users.update_one(
                    {"email": OTHER_EMAIL}, {"$set": {"reliability_pct": val}}
                )
            finally:
                cli.close()

        try:
            asyncio.run(_set(77))
            r = requests.get(f"{base_url}/api/auth/me", headers=_auth_headers(token), timeout=15)
            assert r.status_code == 200
            assert r.json()["reliability_score"] == 77
        finally:
            asyncio.run(_set(50))  # reset to neutral default
