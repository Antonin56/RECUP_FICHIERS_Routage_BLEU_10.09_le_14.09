"""Iter 79 (15/07/2026) — Backend deny + confirm proximity source.

Scope:
 (a) deny by 2nd user on FRESH unconfirmed report → effect=removed
 (b) deny by 3rd user after a confirm → effect=ttl_reduced (exp <= now+15 min)
 (c) deny on own report → 422
 (d) deny on OLD unconfirmed report → effect=none
 (e) confirm with body {source:'proximity'} → confirmer_points_awarded == 1
     and denials wiped ([]).
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://routing-offline.preview.emergentagent.com"
RL_BYPASS = "qa-bypass-7f3d9a2e4c8b1f60"
ADMIN_PHONE = "0760071445"
OTP_CODE = "123456"

# Offshore point off Belle-Île — ~50 km from coast (safe for is_at_sea).
OFFSHORE_LAT = 47.20
OFFSHORE_LNG = -3.60


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "X-RateLimit-Bypass": RL_BYPASS,
    })
    return s


def _otp_login(phone: str, pseudo: str | None = None) -> tuple[str, dict]:
    s = _session()
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": phone}, timeout=15)
    assert r.status_code == 200, f"otp/request {phone} → {r.status_code} {r.text[:200]}"
    body = {"phone": phone, "code": OTP_CODE}
    if pseudo:
        body["pseudo"] = pseudo
    r = s.post(f"{BASE_URL}/api/auth/otp/verify", json=body, timeout=15)
    assert r.status_code == 200, f"otp/verify {phone} → {r.status_code} {r.text[:200]}"
    data = r.json()
    return data["token"], data["user"]


def _auth_session(token: str) -> requests.Session:
    s = _session()
    s.headers["Authorization"] = f"Bearer {token}"
    return s


@pytest.fixture(scope="module")
def admin_ctx():
    tok, u = _otp_login(ADMIN_PHONE)
    return {"token": tok, "user": u, "s": _auth_session(tok)}


@pytest.fixture(scope="module")
def user2_ctx():
    # Whitelisted-ish test account (not in DEV_BYPASS but usable for deny/confirm).
    # Use 0699999901 as agent requested; auto-create if unknown.
    tok, u = _otp_login("0699999901", pseudo="TestIter79A")
    return {"token": tok, "user": u, "s": _auth_session(tok)}


@pytest.fixture(scope="module")
def user3_ctx():
    tok, u = _otp_login("0699999902", pseudo="TestIter79B")
    return {"token": tok, "user": u, "s": _auth_session(tok)}


def _create_report_admin(admin_ctx, description: str = "TEST_ITER79") -> dict:
    s = admin_ctx["s"]
    payload = {
        "type": "obstacle_nav",
        "lat": OFFSHORE_LAT,
        "lng": OFFSHORE_LNG,
        "description": description,
        "photos": [],
        "subtype": "ofni",
        "extras": {},
    }
    r = s.post(f"{BASE_URL}/api/reports", json=payload, timeout=20)
    assert r.status_code == 200, f"create → {r.status_code} {r.text[:300]}"
    return r.json()


def _cleanup(admin_ctx, rid: str):
    try:
        admin_ctx["s"].delete(f"{BASE_URL}/api/reports/{rid}", timeout=10)
    except Exception:
        pass


# ── (a) deny on a fresh unconfirmed report by ANOTHER user → removed ──
def test_a_deny_fresh_unconfirmed_removes(admin_ctx, user2_ctx):
    rep = _create_report_admin(admin_ctx, "TEST_ITER79_a")
    rid = rep["id"]
    try:
        r = user2_ctx["s"].post(f"{BASE_URL}/api/reports/{rid}/deny", timeout=15)
        assert r.status_code == 200, f"deny → {r.status_code} {r.text[:200]}"
        data = r.json()
        assert data.get("effect") == "removed", data
        # Verify: report disappears from GET /api/reports
        list_r = admin_ctx["s"].get(f"{BASE_URL}/api/reports", timeout=15).json()
        ids = {x["id"] for x in list_r}
        assert rid not in ids, f"Report {rid} still visible after deny=removed"
        # Detail still exists but expires_at is in the past
        det = admin_ctx["s"].get(f"{BASE_URL}/api/reports/{rid}", timeout=10)
        assert det.status_code == 200
    finally:
        _cleanup(admin_ctx, rid)


# ── (b) deny after a confirm → ttl_reduced ────────────────────────────
def test_b_deny_after_confirm_ttl_reduced(admin_ctx, user2_ctx, user3_ctx):
    rep = _create_report_admin(admin_ctx, "TEST_ITER79_b")
    rid = rep["id"]
    try:
        # Confirm by user2 (not dev-bypassed → needs at-sea last known loc).
        # Push a fresh at-sea location for user2 first.
        loc_r = user2_ctx["s"].post(
            f"{BASE_URL}/api/profile/location",
            json={"lat": OFFSHORE_LAT, "lng": OFFSHORE_LNG},
            timeout=10,
        )
        assert loc_r.status_code == 200, f"profile/location u2 → {loc_r.status_code} {loc_r.text[:200]}"
        conf = user2_ctx["s"].post(
            f"{BASE_URL}/api/reports/{rid}/confirm",
            json={},  # classical confirm — full points
            timeout=15,
        )
        assert conf.status_code == 200, f"confirm u2 → {conf.status_code} {conf.text[:300]}"
        cdata = conf.json()
        assert cdata.get("confirm_count", 0) >= 1

        # Deny by user3 → confirmed within 30 min → should be ttl_reduced
        r = user3_ctx["s"].post(f"{BASE_URL}/api/reports/{rid}/deny", timeout=15)
        assert r.status_code == 200, f"deny u3 → {r.status_code} {r.text[:200]}"
        ddata = r.json()
        assert ddata.get("effect") == "ttl_reduced", ddata

        # Verify expires_at is ≤ now + 15 min
        det = admin_ctx["s"].get(f"{BASE_URL}/api/reports/{rid}", timeout=10).json()
        exp_raw = det.get("expires_at")
        assert exp_raw, "no expires_at"
        # Parse ISO with tz
        try:
            exp_dt = datetime.fromisoformat(exp_raw.replace("Z", "+00:00"))
        except Exception:
            exp_dt = datetime.fromisoformat(exp_raw)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        delta = (exp_dt - datetime.now(timezone.utc)).total_seconds()
        assert delta <= 16 * 60, f"expires_at too far in the future (Δ={delta:.0f}s)"
    finally:
        _cleanup(admin_ctx, rid)


# ── (c) deny on own report → 422 ──────────────────────────────────────
def test_c_deny_own_report_422(admin_ctx):
    rep = _create_report_admin(admin_ctx, "TEST_ITER79_c")
    rid = rep["id"]
    try:
        r = admin_ctx["s"].post(f"{BASE_URL}/api/reports/{rid}/deny", timeout=15)
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text[:200]}"
    finally:
        _cleanup(admin_ctx, rid)


# ── (d) deny old unconfirmed report → effect=none ─────────────────────
def test_d_deny_old_report_effect_none(admin_ctx, user2_ctx):
    """We piggyback on a freshly created report and monkey-patch its created_at
    via a direct DB write is out of scope — instead we simulate freshness by
    querying an EXISTING old report from GET /api/reports.

    Fallback: since we may not have any old report handy, we assert the
    contract on a synthetic path by patching the report through PATCH is
    impossible → so we craft one via admin then verify effect=none only if
    the age of an existing report > 30 min AND no recent confirmation.
    """
    # Try to fetch an old report from the public list (min_age_hours=1 forces
    # created_at > 1h ago).
    r = admin_ctx["s"].get(
        f"{BASE_URL}/api/reports?min_age_hours=1&radius_km=20000",
        timeout=15,
    )
    assert r.status_code == 200, r.text[:200]
    items = r.json()
    old_rep = None
    for it in items:
        # Skip our own admin reports (deny 422)
        if it.get("author", {}).get("user_id") == admin_ctx["user"]["user_id"]:
            continue
        # last_confirmed_at must also be > 30 min ago
        lca = it.get("last_confirmed_at")
        if not lca:
            old_rep = it
            break
        try:
            lca_dt = datetime.fromisoformat(lca.replace("Z", "+00:00"))
        except Exception:
            continue
        if lca_dt.tzinfo is None:
            lca_dt = lca_dt.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - lca_dt).total_seconds() > 30 * 60:
            old_rep = it
            break
    if not old_rep:
        pytest.skip("no old-enough report available to test effect=none")
    rid = old_rep["id"]
    r = user2_ctx["s"].post(f"{BASE_URL}/api/reports/{rid}/deny", timeout=15)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    # Either "none" (age > 30 min and last confirm > 30 min ago) OR "already"
    # if user2 already denied it (from previous runs).
    assert data.get("effect") == "none", data


# ── (e) confirm with body {source:'proximity'} → +1 pt, denials reset ─
def test_e_confirm_proximity_source(admin_ctx, user2_ctx, user3_ctx):
    rep = _create_report_admin(admin_ctx, "TEST_ITER79_e")
    rid = rep["id"]
    try:
        # First: seed a denial (from user3) to check confirm wipes denials.
        # user3 deny — must be fresh so effect ttl_reduced or removed.
        # If removed → we can't confirm afterwards, so we skip denial seed
        # when it would be removed. To keep test deterministic: give user2
        # a confirm FIRST so the next deny is ttl_reduced (age<30 min, has confirms).
        # push at-sea loc for user2
        loc = user2_ctx["s"].post(
            f"{BASE_URL}/api/profile/location",
            json={"lat": OFFSHORE_LAT, "lng": OFFSHORE_LNG},
            timeout=10,
        )
        assert loc.status_code == 200

        # user2 initial classical confirm to make the report "confirmed" so a
        # subsequent user3 deny reduces TTL rather than removing.
        conf0 = user2_ctx["s"].post(
            f"{BASE_URL}/api/reports/{rid}/confirm", json={}, timeout=15,
        )
        assert conf0.status_code == 200, conf0.text[:300]

        # user3 deny → ttl_reduced (denials=[user3])
        d = user3_ctx["s"].post(f"{BASE_URL}/api/reports/{rid}/deny", timeout=15)
        assert d.status_code == 200, d.text[:200]
        assert d.json().get("effect") == "ttl_reduced"

        # Now: another confirm by yet another user (admin can't self-confirm).
        # Use user2 again — but they already confirmed, so points_awarded=0
        # and denials should still reset. Instead: use user3 (who denied) —
        # confirm by user3 should be accepted (denial is a separate list).
        # Push at-sea loc for user3
        loc3 = user3_ctx["s"].post(
            f"{BASE_URL}/api/profile/location",
            json={"lat": OFFSHORE_LAT, "lng": OFFSHORE_LNG},
            timeout=10,
        )
        assert loc3.status_code == 200

        conf = user3_ctx["s"].post(
            f"{BASE_URL}/api/reports/{rid}/confirm",
            json={"source": "proximity"},
            timeout=15,
        )
        assert conf.status_code == 200, conf.text[:300]
        cdata = conf.json()
        assert cdata.get("confirmer_points_awarded") == 1, cdata

        # Verify denials wiped by re-fetching detail (denials not exposed in
        # serialize_report; check via mongo through a subsequent deny attempt —
        # if denials were reset, user3 could deny again). Simpler: expose via
        # /api/reports/{id} raw. We check confirm_count went up and query a
        # follow-up deny by user2 (not yet a denier) — result should not be
        # 'already' AND effect should be one of ttl_reduced/removed based on
        # fresh state. Sufficient signal: response contract already satisfied.
        # Additionally poke a 2nd deny attempt by user3 which SHOULD be
        # blocked by "already" (their id is already in denials list history)
        # UNLESS denials were reset. Given the code resets denials=[], a
        # follow-up deny by user3 should return effect (not already=True).
        d2 = user3_ctx["s"].post(f"{BASE_URL}/api/reports/{rid}/deny", timeout=15)
        assert d2.status_code == 200, d2.text[:200]
        d2data = d2.json()
        assert d2data.get("already") is not True, f"denials NOT reset after confirm: {d2data}"
    finally:
        _cleanup(admin_ctx, rid)
