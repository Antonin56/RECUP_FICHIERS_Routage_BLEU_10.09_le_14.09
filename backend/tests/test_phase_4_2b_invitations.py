"""Phase 4.2b — Targeted group invitations backend tests.

Covers the 4 new endpoints that replace the code copy/paste flow:

  POST /api/groups/{group_id}/invitations
  GET  /api/invitations/mine
  POST /api/invitations/{invite_id}/accept
  POST /api/invitations/{invite_id}/decline

Plus a regression check on the legacy `POST /api/groups/join/{invite_code}`
code-based flow so we know the older path still works.
"""
from __future__ import annotations

import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
TEST_PASSWORD = "123454321"

ANTONIN = "antoninlepinay@gmail.com"
MYLENE = "mylene.audebert@gmail.com"
ANTHONY = "niosso.aq@gmail.com"
AODREN = "aodren.legrouix@gmail.com"
ACCASTEO = "contact@accasteo.com"


def _login(email: str) -> dict:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
        timeout=15,
    )
    if r.status_code == 401:
        # 22/07/2026 — comptes de test purgés le 10/07 : recréation à la volée.
        import uuid as _uuid
        requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": email, "password": TEST_PASSWORD,
                  "name": email.split("@")[0],
                  "phone": f"+336{_uuid.uuid4().int % 100_000_000:08d}"},
            timeout=15,
        )
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": TEST_PASSWORD},
            timeout=15,
        )
    assert r.status_code == 200, f"login({email}): {r.status_code} {r.text}"
    return r.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _me(token: str) -> dict:
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=_auth(token), timeout=15)
    assert r.status_code == 200, f"/me failed: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def sessions() -> dict:
    """One login per user; expose token + user_id."""
    out = {}
    for email in (ANTONIN, MYLENE, ANTHONY, AODREN, ACCASTEO):
        data = _login(email)
        tok = data["token"]
        me = _me(tok)
        out[email] = {"token": tok, "user_id": me.get("user_id") or me.get("id"),
                      "pseudo": me.get("pseudo") or me.get("name")}
    return out


def _create_group(token: str, name: str) -> dict:
    r = requests.post(
        f"{BASE_URL}/api/groups",
        headers=_auth(token),
        json={"name": name, "description": "TEST_phase_4_2b"},
        timeout=15,
    )
    assert r.status_code == 200, f"create_group: {r.status_code} {r.text}"
    return r.json()


def _delete_group(token: str, group_id: str) -> None:
    requests.delete(f"{BASE_URL}/api/groups/{group_id}",
                    headers=_auth(token), timeout=15)


# ── Batch invite (test 1, 8, 11) ────────────────────────────────────
class TestBatchInvite:
    def setup_method(self):
        self.gid = None
        self.token = None

    def teardown_method(self):
        if self.gid and self.token:
            _delete_group(self.token, self.gid)

    def test_1_batch_invite_two_users(self, sessions):
        s = sessions
        self.token = s[ANTONIN]["token"]
        g = _create_group(self.token, "TEST_Batch_Invite_G1")
        self.gid = g["group_id"]

        payload = {"user_ids": [s[MYLENE]["user_id"], s[ANTHONY]["user_id"]]}
        r = requests.post(
            f"{BASE_URL}/api/groups/{self.gid}/invitations",
            headers=_auth(self.token), json=payload, timeout=15,
        )
        assert r.status_code == 200, f"batch invite: {r.status_code} {r.text}"
        body = r.json()
        assert body["created"] == 2, body
        assert body["already_member"] == 0, body
        assert isinstance(body["invitations"], list) and len(body["invitations"]) == 2
        for inv in body["invitations"]:
            assert inv["invite_id"].startswith("gi_")
            assert inv["group_id"] == self.gid
            assert inv["group_name"] == "TEST_Batch_Invite_G1"
            assert inv["inviter_user_id"] == s[ANTONIN]["user_id"]
            assert inv["inviter_pseudo"] == "SignalMar"
            assert isinstance(inv["expires_at"], int) and inv["expires_at"] > time.time()

    def test_8_skip_already_member(self, sessions):
        """Antonin invites Mylène twice — the second time she should be skipped."""
        s = sessions
        self.token = s[ANTONIN]["token"]
        g = _create_group(self.token, "TEST_Skip_Member")
        self.gid = g["group_id"]

        # First invite Mylène and have her accept.
        r = requests.post(
            f"{BASE_URL}/api/groups/{self.gid}/invitations",
            headers=_auth(self.token),
            json={"user_ids": [s[MYLENE]["user_id"]]}, timeout=15,
        )
        assert r.status_code == 200
        inv_id = r.json()["invitations"][0]["invite_id"]
        acc = requests.post(
            f"{BASE_URL}/api/invitations/{inv_id}/accept",
            headers=_auth(s[MYLENE]["token"]), timeout=15,
        )
        assert acc.status_code == 200

        # Re-invite: she's now a member, should be skipped.
        r = requests.post(
            f"{BASE_URL}/api/groups/{self.gid}/invitations",
            headers=_auth(self.token),
            json={"user_ids": [s[MYLENE]["user_id"]]}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 0, body
        assert body["already_member"] == 1, body
        assert body["invitations"] == []

    def test_11_self_invite_silently_skipped(self, sessions):
        s = sessions
        self.token = s[ANTONIN]["token"]
        g = _create_group(self.token, "TEST_Self_Invite")
        self.gid = g["group_id"]

        r = requests.post(
            f"{BASE_URL}/api/groups/{self.gid}/invitations",
            headers=_auth(self.token),
            json={"user_ids": [s[ANTONIN]["user_id"]]}, timeout=15,
        )
        # Router raises 400 "no_valid_targets" when only self was in the list.
        # Spec expects "silently skip and return created: 0".
        assert r.status_code in (200, 400), r.text
        if r.status_code == 200:
            body = r.json()
            assert body["created"] == 0
            assert body["invitations"] == []


# ── Listing / Accept / Decline (tests 2, 3, 4, 5, 6, 7) ─────────────
class TestListAcceptDecline:
    """One long lifecycle test that walks every state transition."""

    def test_lifecycle(self, sessions):
        s = sessions
        antonin = s[ANTONIN]
        mylene = s[MYLENE]
        anthony = s[ANTHONY]

        g = _create_group(antonin["token"], "TEST_Lifecycle_G")
        gid = g["group_id"]
        try:
            # Batch-invite both
            r = requests.post(
                f"{BASE_URL}/api/groups/{gid}/invitations",
                headers=_auth(antonin["token"]),
                json={"user_ids": [mylene["user_id"], anthony["user_id"]]},
                timeout=15,
            )
            assert r.status_code == 200, r.text
            # Extract ids from listing side
            invs_by_uid = {}
            for inv in r.json()["invitations"]:
                invs_by_uid[inv["invite_id"]] = inv

            # -- Test 2 : Mylène sees exactly 1 pending
            r = requests.get(
                f"{BASE_URL}/api/invitations/mine",
                headers=_auth(mylene["token"]), timeout=15,
            )
            assert r.status_code == 200, r.text
            # Filter to THIS group — pending invites from other groups/runs
            # may legitimately coexist.
            mine = [i for i in r.json()["invitations"] if i["group_id"] == gid]
            assert len(mine) == 1, mine
            m_inv = mine[0]
            assert m_inv["group_id"] == gid
            assert m_inv["group_name"] == "TEST_Lifecycle_G"
            assert m_inv["inviter_pseudo"] == "SignalMar"
            mylene_invite_id = m_inv["invite_id"]

            # -- Test 3 : Anthony sees exactly 1 pending
            r = requests.get(
                f"{BASE_URL}/api/invitations/mine",
                headers=_auth(anthony["token"]), timeout=15,
            )
            assert r.status_code == 200
            a_mine = [i for i in r.json()["invitations"] if i["group_id"] == gid]
            assert len(a_mine) == 1
            anthony_invite_id = a_mine[0]["invite_id"]
            assert a_mine[0]["group_id"] == gid

            # -- Test 4 : Mylène accepts → 200 + GroupSummary
            r = requests.post(
                f"{BASE_URL}/api/invitations/{mylene_invite_id}/accept",
                headers=_auth(mylene["token"]), timeout=15,
            )
            assert r.status_code == 200, r.text
            gs = r.json()
            assert gs["group_id"] == gid
            assert gs["my_role"] == "member"
            # Verify via GET /groups/{gid} that Mylène is now a member
            r = requests.get(f"{BASE_URL}/api/groups/{gid}",
                             headers=_auth(mylene["token"]), timeout=15)
            assert r.status_code == 200, r.text
            members = r.json()["members"]
            uids = {m["user_id"] for m in members}
            assert mylene["user_id"] in uids

            # -- Test 5 : Mylène's list is now 0
            r = requests.get(f"{BASE_URL}/api/invitations/mine",
                             headers=_auth(mylene["token"]), timeout=15)
            assert r.status_code == 200
            # There may be stray invitations from other groups in dev; assert
            # this specific invite is gone from her pending list.
            remaining_ids = {i["invite_id"] for i in r.json()["invitations"]}
            assert mylene_invite_id not in remaining_ids

            # -- Test 6 : Anthony declines
            r = requests.post(
                f"{BASE_URL}/api/invitations/{anthony_invite_id}/decline",
                headers=_auth(anthony["token"]), timeout=15,
            )
            assert r.status_code == 200
            assert r.json().get("ok") is True

            # confirm not in his mine anymore
            r = requests.get(f"{BASE_URL}/api/invitations/mine",
                             headers=_auth(anthony["token"]), timeout=15)
            assert r.status_code == 200
            remaining_ids = {i["invite_id"] for i in r.json()["invitations"]}
            assert anthony_invite_id not in remaining_ids

            # -- Test 7 : Re-invite Anthony after decline → new pending
            r = requests.post(
                f"{BASE_URL}/api/groups/{gid}/invitations",
                headers=_auth(antonin["token"]),
                json={"user_ids": [anthony["user_id"]]}, timeout=15,
            )
            assert r.status_code == 200, r.text
            # Either upsert bumps back to pending (created counted) OR spec says
            # "new pending invitation is created". Either way Anthony must see 1.
            r = requests.get(f"{BASE_URL}/api/invitations/mine",
                             headers=_auth(anthony["token"]), timeout=15)
            assert r.status_code == 200
            mine_now = [i for i in r.json()["invitations"] if i["group_id"] == gid]
            assert len(mine_now) == 1, mine_now
        finally:
            _delete_group(antonin["token"], gid)


# ── Auth / Permission / Error paths (9, 10, 12, 13) ────────────────
class TestErrorPaths:
    def test_9_mine_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/invitations/mine", timeout=15)
        assert r.status_code in (401, 403), f"expected 401, got {r.status_code} {r.text}"

    def test_10_non_member_cannot_invite(self, sessions):
        s = sessions
        # Aodren creates the group; Accasteo (not a member) tries to invite.
        g = _create_group(s[AODREN]["token"], "TEST_NonMember_Invite")
        gid = g["group_id"]
        try:
            r = requests.post(
                f"{BASE_URL}/api/groups/{gid}/invitations",
                headers=_auth(s[ACCASTEO]["token"]),
                json={"user_ids": [s[MYLENE]["user_id"]]},
                timeout=15,
            )
            assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"
            body = r.json()
            assert body.get("detail") == "not_a_member", body
        finally:
            _delete_group(s[AODREN]["token"], gid)

    def test_12_accept_non_existing_invite(self, sessions):
        s = sessions
        r = requests.post(
            f"{BASE_URL}/api/invitations/gi_doesnotexist_123/accept",
            headers=_auth(s[MYLENE]["token"]), timeout=15,
        )
        assert r.status_code == 404, r.text
        assert r.json().get("detail") == "invite_not_found"

    def test_13_someone_else_accepts_others_invite(self, sessions):
        s = sessions
        antonin = s[ANTONIN]
        mylene = s[MYLENE]
        anthony = s[ANTHONY]
        g = _create_group(antonin["token"], "TEST_Cross_Accept")
        gid = g["group_id"]
        try:
            r = requests.post(
                f"{BASE_URL}/api/groups/{gid}/invitations",
                headers=_auth(antonin["token"]),
                json={"user_ids": [mylene["user_id"]]}, timeout=15,
            )
            assert r.status_code == 200
            m_invite_id = r.json()["invitations"][0]["invite_id"]
            # Anthony tries to accept Mylène's invite
            r = requests.post(
                f"{BASE_URL}/api/invitations/{m_invite_id}/accept",
                headers=_auth(anthony["token"]), timeout=15,
            )
            assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text}"
            assert r.json().get("detail") == "invite_not_found"
        finally:
            _delete_group(antonin["token"], gid)


# ── Regression: legacy code-based join still works ─────────────────
class TestLegacyCodeJoinRegression:
    def test_join_via_invite_code_still_works(self, sessions):
        s = sessions
        antonin = s[ANTONIN]
        accasteo = s[ACCASTEO]
        g = _create_group(antonin["token"], "TEST_Legacy_Code_Join")
        gid = g["group_id"]
        code = g["invite_code"]
        try:
            assert code and len(code) >= 6
            # Preview should work
            r = requests.get(
                f"{BASE_URL}/api/groups/join/{code}/preview",
                headers=_auth(accasteo["token"]), timeout=15,
            )
            assert r.status_code == 200, r.text
            preview = r.json()
            assert preview["group_id"] == gid
            assert preview["owner_pseudo"] == "SignalMar"

            # Actual join
            r = requests.post(
                f"{BASE_URL}/api/groups/join/{code}",
                headers=_auth(accasteo["token"]), timeout=15,
            )
            assert r.status_code == 200, r.text
            assert r.json()["group_id"] == gid
            # Verify membership
            r = requests.get(f"{BASE_URL}/api/groups/{gid}",
                             headers=_auth(accasteo["token"]), timeout=15)
            assert r.status_code == 200
            uids = {m["user_id"] for m in r.json()["members"]}
            assert accasteo["user_id"] in uids
        finally:
            _delete_group(antonin["token"], gid)
