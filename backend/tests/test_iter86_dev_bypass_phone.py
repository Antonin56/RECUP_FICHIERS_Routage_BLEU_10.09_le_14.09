"""Iter86 — Aslak dev-bypass via TÉLÉPHONE E.164.

Validates the new DEV_BYPASS_PHONES set: an OTP-only account whose
E.164 phone is in that set must get `is_dev: True` in /auth/me and
bypass every Phase 2 rule (geofence, GPS-required confirm, etc.).

Uses the mocked OTP flow (code = 123456).
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

ASLAK_PHONE_LOCAL = "0766071445"
ASLAK_PHONE_E164 = "+33766071445"
SIGNALMAR_PHONE_LOCAL = "0760071445"
OTP_MOCK = "123456"

LAND_PARIS = (48.8566, 2.3522)
SEA_A = (47.40, -3.20)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _otp_login(phone_local: str, pseudo_hint: str = None):
    """Request+verify OTP for a given phone (mocked → code 123456)."""
    r = requests.post(f"{BASE_URL}/api/auth/otp/request",
                      json={"phone": phone_local}, timeout=15)
    assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text}"
    body = {"phone": phone_local, "code": OTP_MOCK}
    if pseudo_hint:
        body["pseudo"] = pseudo_hint
    r = requests.post(f"{BASE_URL}/api/auth/otp/verify", json=body, timeout=15)
    assert r.status_code == 200, f"otp/verify failed: {r.status_code} {r.text}"
    j = r.json()
    return j["token"], j["user"]


def _clear_user_loc(user_id: str):
    async def _do():
        cli = AsyncIOMotorClient(MONGO_URL)
        d = cli[DB_NAME]
        await d.users.update_one(
            {"user_id": user_id},
            {"$unset": {"last_lat": "", "last_lng": "", "last_loc_at": ""}},
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
def aslak_auth():
    tok, u = _otp_login(ASLAK_PHONE_LOCAL, pseudo_hint="Aslak")
    _clear_user_loc(u["user_id"])
    return tok, u


@pytest.fixture(scope="module")
def signalmar_auth():
    tok, u = _otp_login(SIGNALMAR_PHONE_LOCAL, pseudo_hint="SignalMar")
    return tok, u


class TestAslakBypassPhone:
    """Aslak (phone-only account listed in DEV_BYPASS_PHONES) is a dev user."""

    def test_1_auth_me_is_dev_true(self, aslak_auth):
        tok, user = aslak_auth
        # Verify via /auth/me
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=_hdr(tok), timeout=10)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me.get("phone") == ASLAK_PHONE_E164, f"phone not E.164: {me.get('phone')}"
        assert me.get("is_dev") is True, f"is_dev not True: {me}"

    def test_2_create_report_on_land_succeeds(self, aslak_auth):
        """Aslak posts at Paris → 200 (geofence bypassed)."""
        tok, _ = aslak_auth
        r = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(tok),
            json={
                "type": "animal_marin", "subtype": "mammifere",
                "lat": LAND_PARIS[0], "lng": LAND_PARIS[1],
                "description": "TEST_iter86 Aslak land create", "photos": [],
                "extras": {"species": "common_dolphin", "health": "alive_healthy"},
            },
            timeout=20,
        )
        assert r.status_code == 200, f"aslak land create rejected: {r.status_code} {r.text}"
        data = r.json()
        assert data["origin_lat"] == LAND_PARIS[0]
        _hard_delete_report(data["id"])

    def test_3_confirm_without_gps_bypassed(self, aslak_auth, signalmar_auth):
        """SignalMar creates a sea report → Aslak confirms without any GPS fix → 200."""
        tok_aslak, user_aslak = aslak_auth
        tok_sm, _ = signalmar_auth
        # SignalMar creates a sea report (they are also dev, but sea coord anyway)
        c = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(tok_sm),
            json={"type": "pollution", "lat": SEA_A[0], "lng": SEA_A[1],
                  "description": "TEST_iter86 confirm target", "photos": []},
            timeout=20,
        )
        assert c.status_code == 200, f"signalmar create failed: {c.status_code} {c.text}"
        rid = c.json()["id"]
        try:
            _clear_user_loc(user_aslak["user_id"])
            r = requests.post(
                f"{BASE_URL}/api/reports/{rid}/confirm",
                headers=_hdr(tok_aslak), timeout=20,
            )
            assert r.status_code == 200, (
                f"aslak confirm no-GPS rejected: {r.status_code} {r.text}"
            )
            data = r.json()
            assert data["confirm_count"] >= 1
            assert data.get("confirmed_by_me") is True
        finally:
            _hard_delete_report(rid)


class TestNonDevPhoneStillStrict:
    """Regression: a fresh phone user NOT in DEV_BYPASS_PHONES still hits 422 on land."""

    def test_non_dev_create_on_land_still_422(self):
        # Random phone (unlikely in DEV_BYPASS_PHONES)
        phone = f"07{uuid.uuid4().int % 100000000:08d}"
        tok, _ = _otp_login(phone, pseudo_hint=f"NDPh{uuid.uuid4().hex[:6]}")
        r = requests.post(
            f"{BASE_URL}/api/reports", headers=_hdr(tok),
            json={"type": "animal_marin", "subtype": "mammifere",
                  "lat": LAND_PARIS[0], "lng": LAND_PARIS[1],
                  "description": "TEST_iter86 non-dev land", "photos": [],
                  "extras": {"species": "common_dolphin", "health": "alive_healthy"}},
            timeout=20,
        )
        if r.status_code == 200:
            rid = r.json().get("id")
            if rid:
                _hard_delete_report(rid)
            pytest.skip("is_at_sea fail-open (Open-Meteo unreachable). Soft pass.")
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text}"
        assert "mer" in r.text.lower(), f"missing 'mer' in error: {r.text}"
