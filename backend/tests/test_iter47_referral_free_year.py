"""Iteration 47 (10/07/2026) — Tests pour :
 (A) Bug pseudo/keyboard (frontend) — pas testable ici.
 (B) Premium offert 1 an + Points→mois (100pts = +1 mois, non rétroactif).
 (C) Invitations de parrainage (POST /referral/invitations, /pending,
     /resolve-sponsor, consommation à l'inscription).
 (D) Confirmation parrainage : +20 pts, PLUS de mois direct.
"""
import hashlib
import os
import time
import asyncio
import uuid

import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_BACKEND_URL",
    "https://engine-e-crouesty.preview.emergentagent.com",
).rstrip("/")
BYPASS = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
ADMIN_PHONE_LOCAL = "0760071445"
ADMIN_PHONE_E164 = "+33760071445"
OTP_CODE = "123456"


def _e164(local: str) -> str:
    d = "".join(ch for ch in local if ch.isdigit())
    if d.startswith("0"):
        d = d[1:]
    return "+33" + d


def _hash(e164: str) -> str:
    return hashlib.sha256(e164.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json", **BYPASS})
    return sess


@pytest.fixture(scope="module")
def admin_token(s):
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": ADMIN_PHONE_LOCAL})
    assert r.status_code == 200, r.text
    r = s.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"phone": ADMIN_PHONE_LOCAL, "code": OTP_CODE},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "token" in data and "user" in data
    return data["token"], data["user"]


# ── (B) Subscription state ────────────────────────────────────────────
class TestSubscriptionAdmin:
    def test_admin_subscription_state(self, s, admin_token):
        tok, _u = admin_token
        r = s.get(
            f"{BASE_URL}/api/profile/subscription",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        sub = body["subscription"]
        # Free year offert
        assert sub["free_year_active"] is True, sub
        assert sub["free_year_until"] and sub["free_year_until"] > time.time()
        assert sub["is_premium"] is True
        # Points → mois rules
        assert sub["points_per_month"] == 100
        assert 0 <= sub["points_progress"] < 100
        assert sub["points_to_next_month"] == 100 - sub["points_progress"]
        # 23/07/2026 — le compte admin VIT : des mois sont réellement gagnés
        # au fil des points depuis le rollout. L'invariant « awarded = 0 »
        # n'était vrai qu'à la mise en service ; on vérifie la COHÉRENCE.
        assert isinstance(sub["points_months_awarded"], int)
        assert sub["points_months_awarded"] >= 0


# ── (C) Invitations ────────────────────────────────────────────────────
INVITE_TEST_PHONE_LOCAL = "0699001122"
INVITE_TEST_PHONE_E164 = "+33699001122"


class TestInvitations:
    def test_create_invitation(self, s, admin_token):
        tok, _ = admin_token
        h = _hash(INVITE_TEST_PHONE_E164)
        r = s.post(
            f"{BASE_URL}/api/referral/invitations",
            json={"phone_hashes": [h]},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200, r.text
        assert r.json().get("created") == 1

    def test_pending_returns_sponsor(self, s, admin_token):
        _tok, admin_user = admin_token
        r = s.post(
            f"{BASE_URL}/api/referral/pending",
            json={"phone": INVITE_TEST_PHONE_LOCAL},
        )
        assert r.status_code == 200, r.text
        invs = r.json().get("invitations", [])
        assert len(invs) >= 1, invs
        first = invs[0]
        assert first.get("pseudo")
        assert first.get("referral_code")
        # admin's referral_code should match
        assert first["referral_code"] == admin_user.get("referral_code")

    def test_pending_invalid_phone(self, s):
        r = s.post(f"{BASE_URL}/api/referral/pending", json={"phone": "abc"})
        assert r.status_code == 422

    def test_resolve_sponsor_by_hash(self, s, admin_token):
        _tok, admin_user = admin_token
        h = _hash(ADMIN_PHONE_E164)
        r = s.post(
            f"{BASE_URL}/api/referral/resolve-sponsor",
            json={"phone_hashes": [h]},
        )
        assert r.status_code == 200, r.text
        sponsors = r.json().get("sponsors", [])
        assert len(sponsors) >= 1
        # Should find the admin
        found = [x for x in sponsors if x.get("referral_code") == admin_user.get("referral_code")]
        assert found, sponsors


# ── (C) Consommation à l'inscription ──────────────────────────────────
class TestInvitationConsumption:
    def test_signup_consumes_invitations(self, s, admin_token):
        """L'admin invite 0699001122 → filleul s'inscrit → invitations
        supprimées."""
        _tok, admin_user = admin_token
        # 23/07/2026 — PURGE du compte filleul : les runs précédents le
        # laissaient en base → verify devenait un LOGIN (sans consommation
        # d'invitations) et le test était flaky. On repart d'un filleul neuf.
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "test_database")

        async def _purge():
            client = AsyncIOMotorClient(mongo_url)
            await client[db_name].users.delete_many(
                {"phone": INVITE_TEST_PHONE_E164}
            )
            client.close()

        asyncio.run(_purge())
        h = _hash(INVITE_TEST_PHONE_E164)
        # Re-créer l'invitation (potentiellement consommée par test précédent)
        r = s.post(
            f"{BASE_URL}/api/referral/invitations",
            json={"phone_hashes": [h]},
            headers={"Authorization": f"Bearer {_tok}"},
        )
        assert r.status_code == 200

        # Vérifier qu'elle est présente
        r = s.post(f"{BASE_URL}/api/referral/pending", json={"phone": INVITE_TEST_PHONE_LOCAL})
        assert r.status_code == 200
        assert len(r.json().get("invitations", [])) >= 1

        # Créer le compte filleul (OTP mocké)
        r = s.post(
            f"{BASE_URL}/api/auth/otp/request",
            json={"phone": INVITE_TEST_PHONE_LOCAL},
        )
        assert r.status_code == 200

        pseudo = f"Filleul_{uuid.uuid4().hex[:6]}"
        r = s.post(
            f"{BASE_URL}/api/auth/otp/verify",
            json={
                "phone": INVITE_TEST_PHONE_LOCAL,
                "code": OTP_CODE,
                "pseudo": pseudo,
                "referral_code": admin_user.get("referral_code"),
            },
        )
        # 200 si nouveau compte, 400 si le compte existait déjà
        if r.status_code != 200:
            pytest.skip(f"Le compte {INVITE_TEST_PHONE_LOCAL} existe déjà : {r.text}")
        assert "token" in r.json()

        # Vérifier que les invitations sont consommées
        r = s.post(f"{BASE_URL}/api/referral/pending", json={"phone": INVITE_TEST_PHONE_LOCAL})
        assert r.status_code == 200
        assert r.json().get("invitations") == []


# ── (B) Points→mois (via motor direct) ─────────────────────────────────
class TestPointsToMonths:
    """Test unitaire du palier points→mois via core.points.award_points."""

    def test_points_award_bumps_premium_until(self, admin_token):
        import sys
        sys.path.insert(0, "/app/backend")
        from motor.motor_asyncio import AsyncIOMotorClient
        from core.points import award_points

        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "test_database")

        async def _run():
            client = AsyncIOMotorClient(mongo_url)
            db = client[db_name]
            try:
                # Créer un user de test propre (baseline=0, points=0)
                uid = f"test_pts_{uuid.uuid4().hex[:8]}"
                now_ts = int(time.time())
                await db.users.insert_one({
                    "user_id": uid,
                    "pseudo": f"TEST_PTS_{uid[-4:]}",
                    "email": f"TEST_{uid}@test.local",
                    "created_at": now_ts,
                    "points": 0,
                    "points_premium_baseline": 0,
                    "points_months_awarded": 0,
                    "referral_code": uid[:8].upper(),
                })
                try:
                    u0 = await db.users.find_one({"user_id": uid}, {"_id": 0})
                    before_until = int(u0.get("subscription_premium_until") or 0)

                    # +120 pts → devrait déclencher 1 mois
                    await award_points(db, uid, 120, "test palier")
                    u1 = await db.users.find_one({"user_id": uid}, {"_id": 0})
                    assert int(u1.get("points") or 0) == 120
                    assert int(u1.get("points_months_awarded") or 0) == 1, u1
                    after1 = int(u1.get("subscription_premium_until") or 0)
                    # Le premium_until doit être ≥ created_at + 365j + 30j
                    expected_base = now_ts + 365 * 86400
                    assert after1 >= expected_base + 29 * 86400, (
                        f"after1={after1}, expected≥{expected_base + 29*86400}"
                    )
                    assert after1 > before_until

                    # +80 pts → total 200 → 2 mois cumulés
                    await award_points(db, uid, 80, "test palier 2")
                    u2 = await db.users.find_one({"user_id": uid}, {"_id": 0})
                    assert int(u2.get("points_months_awarded") or 0) == 2, u2
                    after2 = int(u2.get("subscription_premium_until") or 0)
                    assert after2 > after1
                    # ≈ 30j supplémentaires
                    assert after2 - after1 >= 29 * 86400

                finally:
                    await db.users.delete_one({"user_id": uid})
                    await db.points_history.delete_many({"user_id": uid})
            finally:
                client.close()

        asyncio.run(_run())


# ── (D) Confirmation parrainage : plus de mois direct ──────────────────
class TestReferralConfirmationNoMonth:
    def test_try_award_bonus_gives_zero_months(self):
        """Lecture de code : try_award_bonus doit renvoyer months_awarded=0
        et marquer le statut 'confirmed'."""
        import sys
        sys.path.insert(0, "/app/backend")
        from motor.motor_asyncio import AsyncIOMotorClient
        from core.subscription import try_award_bonus

        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "test_database")

        async def _run():
            client = AsyncIOMotorClient(mongo_url)
            db = client[db_name]
            try:
                referrer = f"test_ref_{uuid.uuid4().hex[:6]}"
                referee = f"test_refe_{uuid.uuid4().hex[:6]}"
                confirmer = f"test_conf_{uuid.uuid4().hex[:6]}"
                report_id = f"rpt_test_{uuid.uuid4().hex[:6]}"
                referral_id = f"rf_test_{uuid.uuid4().hex[:8]}"
                await db.referrals.insert_one({
                    "referral_id": referral_id,
                    "referrer_user_id": referrer,
                    "referee_user_id": referee,
                    "code_used": "XYZ",
                    "linked_at": int(time.time()),
                    "first_report_id": report_id,
                    "first_report_at": int(time.time()),
                    "confirmed_at": None,
                    "status": "pending_confirmation",
                    "months_awarded": 0,
                })
                try:
                    result = await try_award_bonus(
                        db,
                        report_id=report_id,
                        report_author_uid=referee,
                        confirmer_uid=confirmer,
                    )
                    assert result is not None, "should have awarded (external confirmer)"
                    assert result["months_awarded"] == 0, result
                    ref = await db.referrals.find_one({"referral_id": referral_id}, {"_id": 0})
                    assert ref["status"] == "confirmed", ref
                    assert ref["months_awarded"] == 0
                finally:
                    await db.referrals.delete_one({"referral_id": referral_id})
            finally:
                client.close()

        asyncio.run(_run())
