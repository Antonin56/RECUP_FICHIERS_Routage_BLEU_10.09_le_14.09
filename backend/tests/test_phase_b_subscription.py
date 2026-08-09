"""Phase B — Subscription bonus (viral referral rewards) tests.

Covers the flow:
  register(with referral_code) → first report → external confirm → +1 month

Also verifies the anti-farm guard (same-group confirmer), the 10-pending
cap, the 12-confirmed cap, and the older +20 grade referral bonus.

Uses sync pymongo (no pytest-asyncio required).
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

# Load env from both frontend (for BASE_URL) and backend (for MONGO_URL).
load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

TEST_PASSWORD = "123454321"

ANTONIN_EMAIL = "antoninlepinay@gmail.com"
MYLENE_EMAIL = "mylene.audebert@gmail.com"
ANTHONY_EMAIL = "niosso.aq@gmail.com"

# Open-sea point (Bay of Biscay) — passes the is_at_sea gate.
SEA_LAT, SEA_LNG = 46.0, -3.0

STATE: dict = {}


def _post(path, json=None, token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return requests.post(f"{BASE_URL}{path}", json=json, headers=h, timeout=30)


def _get(path, token=None):
    h = {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return requests.get(f"{BASE_URL}{path}", headers=h, timeout=30)


def _login(email, password=TEST_PASSWORD):
    r = _post("/api/auth/login", {"email": email, "password": password})
    if r.status_code == 401:
        # 22/07/2026 — les comptes de test ont été PURGÉS le 10/07 (voir
        # memory/test_credentials.md) : recréation idempotente à la volée.
        reg = _register(email, email.split("@")[0], phone=_fresh_phone())
        assert reg.status_code in (200, 400), f"register {email}: {reg.status_code} {reg.text}"
        r = _post("/api/auth/login", {"email": email, "password": password})
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _register(email, name, referral_code=None, phone=None):
    payload = {"email": email, "password": TEST_PASSWORD, "name": name}
    if referral_code:
        payload["referral_code"] = referral_code
    if phone:
        payload["phone"] = phone
    return _post("/api/auth/register", payload)


def _fresh_phone():
    """Unique valid FR phone (+33 6 XX XX XX XX) for tests. The DB has a
    unique-sparse index on ``phone`` that treats null as a value, so every
    test user must have a distinct phone even though real signups can omit it."""
    n = uuid.uuid4().int % 100_000_000
    return f"+336{n:08d}"


def _fresh_email(prefix="phb"):
    return f"TEST_{prefix}_{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture(scope="module")
def db():
    assert MONGO_URL and DB_NAME, "MONGO_URL/DB_NAME env vars missing"
    cli = MongoClient(MONGO_URL)
    return cli[DB_NAME]


@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown(db):
    tok, u = _login(ANTONIN_EMAIL)
    STATE["antonin_token"] = tok
    STATE["antonin_uid"] = u["user_id"]

    m_tok, m_u = _login(MYLENE_EMAIL)
    STATE["mylene_token"] = m_tok
    STATE["mylene_uid"] = m_u["user_id"]
    assert _post(
        "/api/profile/location", {"lat": SEA_LAT, "lng": SEA_LNG}, token=m_tok
    ).status_code == 200

    a_tok2, a_u2 = _login(ANTHONY_EMAIL)
    STATE["anthony_token"] = a_tok2
    STATE["anthony_uid"] = a_u2["user_id"]
    assert _post(
        "/api/profile/location", {"lat": SEA_LAT, "lng": SEA_LNG}, token=a_tok2
    ).status_code == 200

    # Reset Antonin's referrals + subscription counters.
    db.referrals.delete_many({"referrer_user_id": STATE["antonin_uid"]})
    db.users.update_one(
        {"user_id": STATE["antonin_uid"]},
        {"$set": {
            "subscription_bonus_months_confirmed": 0,
            "subscription_bonus_months_pending": 0,
        }, "$unset": {"subscription_premium_until": ""}},
    )
    # Drop any leftover fresh users from prior runs.
    db.users.delete_many({"email": {"$regex": "^TEST_phb_.*@example\\.com$"}})
    db.users.delete_many({"email": {"$regex": "^TEST_t[0-9]_.*@example\\.com$"}})
    db.users.delete_many({"email": {"$regex": "^TEST_t[0-9]{1,2}_.*@example\\.com$"}})
    STATE["fresh_uids"] = []

    yield

    # Teardown.
    fresh_uids = STATE.get("fresh_uids", [])
    if fresh_uids:
        db.users.delete_many({"user_id": {"$in": fresh_uids}})
        db.referrals.delete_many({"referee_user_id": {"$in": fresh_uids}})
        db.group_members.delete_many({"user_id": {"$in": fresh_uids}})
        db.reports.delete_many({"author_id": {"$in": fresh_uids}})
    if STATE.get("group_id"):
        db.groups.delete_one({"group_id": STATE["group_id"]})
        db.group_members.delete_many({"group_id": STATE["group_id"]})
    db.referrals.delete_many({"referrer_user_id": STATE["antonin_uid"]})
    db.users.update_one(
        {"user_id": STATE["antonin_uid"]},
        {"$set": {
            "subscription_bonus_months_confirmed": 0,
            "subscription_bonus_months_pending": 0,
        }, "$unset": {"subscription_premium_until": ""}},
    )


# ── T1 ────────────────────────────────────────────────────────────────
def _points_total(sub: dict) -> int:
    """Total de points « grade parrainage » = paliers déjà convertis en mois
    (100 pts) + progression courante (règle du 10/07/2026)."""
    return int(sub["points_months_awarded"]) * 100 + int(sub["points_progress"])


def test_01_subscription_snapshot_initial():
    r = _get("/api/profile/subscription", token=STATE["antonin_token"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert "subscription" in body and "referrals" in body
    s = body["subscription"]
    assert s["bonus_months_confirmed"] == 0
    assert s["bonus_months_pending"] == 0
    assert s["cap_pending"] == 10
    # Règles du 10/07/2026 : plus de plafond « mois confirmés » (cap_confirmed
    # supprimé — les mois viennent des paliers de points) ; l'année Premium
    # offerte court depuis created_at → un compte < 1 an est premium.
    assert "cap_confirmed" not in s
    assert s["points_per_month"] == 100
    assert s["free_year_active"] is True
    assert s["is_premium"] is True
    assert isinstance(body["referrals"], list)


def test_02_register_with_referral_creates_pending():
    r = _get("/api/profile/referral", token=STATE["antonin_token"])
    assert r.status_code == 200, r.text
    code = r.json()["referral_code"]
    assert code
    STATE["antonin_code"] = code

    email = _fresh_email("t2")
    reg = _register(email, "T2 Referee", referral_code=code, phone=_fresh_phone())
    assert reg.status_code == 200, reg.text
    referee = reg.json()
    STATE["ref_t2_token"] = referee["token"]
    STATE["ref_t2_uid"] = referee["user"]["user_id"]
    STATE["fresh_uids"].append(STATE["ref_t2_uid"])

    sub = _get("/api/profile/subscription", token=STATE["antonin_token"]).json()
    assert sub["subscription"]["bonus_months_pending"] == 1, sub
    assert any(
        rf["referee"]["user_id"] == STATE["ref_t2_uid"] and rf["status"] == "pending_report"
        for rf in sub["referrals"]
    ), sub


def test_03_first_report_moves_to_pending_confirmation():
    payload = {
        "type": "obstacle_nav",
        "lat": SEA_LAT,
        "lng": SEA_LNG,
        "subtype": "ovni",
        "description": "TEST_PHB obstacle",
    }
    r = _post("/api/reports", payload, token=STATE["ref_t2_token"])
    assert r.status_code == 200, r.text
    STATE["report_t3_id"] = r.json()["id"]

    sub = _get("/api/profile/subscription", token=STATE["antonin_token"]).json()
    ref = next(
        rf for rf in sub["referrals"]
        if rf["referee"]["user_id"] == STATE["ref_t2_uid"]
    )
    assert ref["status"] == "pending_confirmation", sub
    assert sub["subscription"]["bonus_months_confirmed"] == 0


def test_04_external_confirmer_confirms_referral_and_pays_points():
    """Règle du 10/07/2026 : le mois Premium direct est REMPLACÉ par +20 pts
    au parrain (paliers de 100 pts → mois). Le statut passe « confirmed »."""
    before = _get("/api/profile/subscription", token=STATE["antonin_token"]).json()
    pts_before = _points_total(before["subscription"])

    r = _post(
        f"/api/reports/{STATE['report_t3_id']}/confirm",
        token=STATE["mylene_token"],
    )
    assert r.status_code == 200, r.text

    sub = _get("/api/profile/subscription", token=STATE["antonin_token"]).json()
    s = sub["subscription"]
    assert s["bonus_months_confirmed"] == 0, s          # plus de mois directs
    assert s["bonus_months_pending"] == 0, s
    assert _points_total(s) == pts_before + 20, s        # +20 pts parrainage
    STATE["pts_after_t4"] = _points_total(s)

    ref = next(
        rf for rf in sub["referrals"]
        if rf["referee"]["user_id"] == STATE["ref_t2_uid"]
    )
    assert ref["status"] == "confirmed"
    assert ref["months_awarded"] == 0


def test_05_second_confirm_is_idempotent():
    r = _post(
        f"/api/reports/{STATE['report_t3_id']}/confirm",
        token=STATE["anthony_token"],
    )
    assert r.status_code == 200, r.text
    sub = _get("/api/profile/subscription", token=STATE["antonin_token"]).json()
    # Bonus parrainage one-shot par filleul : pas de double paiement.
    assert _points_total(sub["subscription"]) == STATE["pts_after_t4"]
    assert sub["subscription"]["bonus_months_confirmed"] == 0


def test_06_internal_confirmer_blocked(db):
    r = _post("/api/groups", {"name": "TEST_PHB group"}, token=STATE["antonin_token"])
    assert r.status_code == 200, r.text
    g = r.json()
    STATE["group_id"] = g["group_id"]
    invite_code = g["invite_code"]

    email = _fresh_email("t6")
    reg = _register(email, "T6 Referee", referral_code=STATE["antonin_code"], phone=_fresh_phone())
    assert reg.status_code == 200, reg.text
    t6_tok = reg.json()["token"]
    t6_uid = reg.json()["user"]["user_id"]
    STATE["fresh_uids"].append(t6_uid)

    r = _post(f"/api/groups/join/{invite_code}", token=t6_tok)
    assert r.status_code == 200, r.text

    r = _post("/api/reports", {
        "type": "obstacle_nav", "lat": SEA_LAT, "lng": SEA_LNG,
        "subtype": "ovni", "description": "TEST_PHB t6",
    }, token=t6_tok)
    assert r.status_code == 200, r.text
    rid_t6 = r.json()["id"]

    # Confirmation INTERNE (le parrain est dans le groupe du filleul) : le
    # STATUT du parrainage ne bouge pas (anti-farm), même si les +20 pts
    # one-shot du filleul partent dès la 1re confirmation par un tiers.
    r = _post(f"/api/reports/{rid_t6}/confirm", token=STATE["antonin_token"])
    assert r.status_code == 200, r.text
    sub = _get("/api/profile/subscription", token=STATE["antonin_token"]).json()
    ref = next(rf for rf in sub["referrals"] if rf["referee"]["user_id"] == t6_uid)
    assert ref["status"] == "pending_confirmation", ref
    assert ref["months_awarded"] == 0

    # Confirmation EXTERNE → statut « confirmed », toujours 0 mois direct.
    r = _post(f"/api/reports/{rid_t6}/confirm", token=STATE["mylene_token"])
    assert r.status_code == 200, r.text
    sub = _get("/api/profile/subscription", token=STATE["antonin_token"]).json()
    ref = next(rf for rf in sub["referrals"] if rf["referee"]["user_id"] == t6_uid)
    assert ref["status"] == "confirmed", ref
    assert ref["months_awarded"] == 0
    assert sub["subscription"]["bonus_months_confirmed"] == 0


def test_07_pending_cap(db):
    # Reset slate so the count is deterministic (11 exact new signups).
    db.referrals.delete_many({"referrer_user_id": STATE["antonin_uid"]})
    db.users.update_one(
        {"user_id": STATE["antonin_uid"]},
        {"$set": {"subscription_bonus_months_pending": 0}},
    )

    statuses = []
    for i in range(11):
        email = _fresh_email(f"t7_{i:02d}")
        reg = _register(email, f"T7 #{i}", referral_code=STATE["antonin_code"], phone=_fresh_phone())
        assert reg.status_code == 200, reg.text
        uid = reg.json()["user"]["user_id"]
        STATE["fresh_uids"].append(uid)
        doc = db.referrals.find_one(
            {"referee_user_id": uid}, {"_id": 0, "status": 1},
        )
        assert doc is not None, f"no referral created for #{i}"
        statuses.append(doc["status"])

    assert statuses[:10] == ["pending_report"] * 10, statuses
    assert statuses[10] == "rejected_farm", statuses

    sub = _get("/api/profile/subscription", token=STATE["antonin_token"]).json()
    assert sub["subscription"]["bonus_months_pending"] == 10, sub


def test_08_confirmed_cap(db):
    db.referrals.delete_many({"referrer_user_id": STATE["antonin_uid"]})
    db.users.update_one(
        {"user_id": STATE["antonin_uid"]},
        {"$set": {
            "subscription_bonus_months_confirmed": 12,
            "subscription_bonus_months_pending": 0,
        }},
    )

    email = _fresh_email("t8")
    reg = _register(email, "T8", referral_code=STATE["antonin_code"], phone=_fresh_phone())
    assert reg.status_code == 200, reg.text
    tok = reg.json()["token"]
    uid = reg.json()["user"]["user_id"]
    STATE["fresh_uids"].append(uid)

    r = _post("/api/reports", {
        "type": "obstacle_nav", "lat": SEA_LAT, "lng": SEA_LNG,
        "subtype": "ovni", "description": "TEST_PHB t8",
    }, token=tok)
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    r = _post(f"/api/reports/{rid}/confirm", token=STATE["mylene_token"])
    assert r.status_code == 200, r.text

    sub = _get("/api/profile/subscription", token=STATE["antonin_token"]).json()
    assert sub["subscription"]["bonus_months_confirmed"] == 12, sub
    ref = next(rf for rf in sub["referrals"] if rf["referee"]["user_id"] == uid)
    assert ref["status"] == "confirmed", ref
    assert ref["months_awarded"] == 0, ref  # no overflow


def test_09_grade_referral_bonus_regression(db):
    before = db.users.find_one(
        {"user_id": STATE["antonin_uid"]}, {"_id": 0, "points": 1},
    )
    pts_before = int((before or {}).get("points") or 0)

    email = _fresh_email("t9")
    reg = _register(email, "T9", referral_code=STATE["antonin_code"], phone=_fresh_phone())
    assert reg.status_code == 200, reg.text
    tok = reg.json()["token"]
    uid = reg.json()["user"]["user_id"]
    STATE["fresh_uids"].append(uid)

    r = _post("/api/reports", {
        "type": "obstacle_nav", "lat": SEA_LAT, "lng": SEA_LNG,
        "subtype": "ovni", "description": "TEST_PHB t9",
    }, token=tok)
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    conf = _post(f"/api/reports/{rid}/confirm", token=STATE["mylene_token"])
    assert conf.status_code == 200, conf.text
    assert conf.json().get("referral_bonus_paid") is True, conf.json()

    after = db.users.find_one(
        {"user_id": STATE["antonin_uid"]}, {"_id": 0, "points": 1},
    )
    pts_after = int((after or {}).get("points") or 0)
    assert pts_after - pts_before >= 20, (pts_before, pts_after)
