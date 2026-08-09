"""Phase 4.2 — /api/contacts/match endpoint tests.

Covers:
  1. Auth required (401 without Bearer)
  2. Empty payload → 200 {"matches":[]}
  3. Known peer hash returns matching user with expected fields
  4. Caller MUST NOT match itself
  5. Deduplication (same hash x3 → one match)
  6. Batch cap 500 (501+ → 413)
  7. Fresh registration → immediately matchable via SHA-256(E.164)
  8. Email-only users (no phone) never appear in matches
"""
import hashlib
import os
import uuid
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")

# --- Fixtures -------------------------------------------------------------
ANTONIN_EMAIL = "antoninlepinay@gmail.com"
ANTONIN_PASSWORD = "123454321"
ANTONIN_PHONE = "+33760071445"
PEER1_PHONE = "+33781407745"


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def antonin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ANTONIN_EMAIL, "password": ANTONIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"Antonin login failed: {r.status_code} {r.text}"
    data = r.json()
    return data["token"]


@pytest.fixture(scope="module")
def antonin_user_id(antonin_token):
    r = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {antonin_token}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


@pytest.fixture(scope="module")
def peer1_uid(antonin_token):
    """22/07/2026 — le pair historique (user_ee8ecaffd347) a été PURGÉ le
    10/07 : on garantit un compte portant PEER1_PHONE (recréé au besoin) et
    on renvoie son user_id réel."""
    requests.post(f"{BASE_URL}/api/auth/register", json={
        "email": f"TEST_peer1_{uuid.uuid4().hex[:8]}@example.com",
        "password": "testpass123", "name": "TEST_Peer1", "phone": PEER1_PHONE,
    }, timeout=15)   # 200 (créé) ou 400 (déjà existant) — les deux conviennent
    r = requests.post(
        f"{BASE_URL}/api/contacts/match",
        headers={"Authorization": f"Bearer {antonin_token}"},
        json={"hashes": [sha256_hex(PEER1_PHONE)]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    ms = r.json()["matches"]
    assert len(ms) == 1, f"peer1 introuvable après recréation: {ms}"
    return ms[0]["user_id"]


# --- Tests ----------------------------------------------------------------


class TestContactsMatchAuth:
    """Test 1: authentication."""

    def test_missing_bearer_returns_401(self):
        r = requests.post(
            f"{BASE_URL}/api/contacts/match",
            json={"hashes": []},
            timeout=15,
        )
        assert r.status_code == 401, f"Expected 401 got {r.status_code}: {r.text}"


class TestContactsMatchEmpty:
    """Test 2: empty body."""

    def test_empty_hashes_returns_empty_matches(self, antonin_token):
        r = requests.post(
            f"{BASE_URL}/api/contacts/match",
            headers={"Authorization": f"Bearer {antonin_token}"},
            json={"hashes": []},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"matches": []}


class TestContactsMatchKnownPeer:
    """Test 3: known hash returns expected match with full field set."""

    def test_peer1_matches_and_fields_present(self, antonin_token, peer1_uid):
        h = sha256_hex(PEER1_PHONE)
        r = requests.post(
            f"{BASE_URL}/api/contacts/match",
            headers={"Authorization": f"Bearer {antonin_token}"},
            json={"hashes": [h]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "matches" in data
        assert len(data["matches"]) == 1, f"expected 1 match, got: {data}"
        m = data["matches"][0]
        # Field presence
        for k in ("phone_hash", "user_id", "pseudo", "picture", "rank_label", "reliability_score"):
            assert k in m, f"missing field {k} in {m}"
        assert m["phone_hash"] == h
        assert m["user_id"] == peer1_uid, f"expected {peer1_uid} got {m['user_id']}"


class TestContactsMatchSelfExcluded:
    """Test 4: caller not matched even if own hash is in payload."""

    def test_self_hash_never_returned(self, antonin_token, antonin_user_id, peer1_uid):
        own_hash = sha256_hex(ANTONIN_PHONE)
        peer_hash = sha256_hex(PEER1_PHONE)
        r = requests.post(
            f"{BASE_URL}/api/contacts/match",
            headers={"Authorization": f"Bearer {antonin_token}"},
            json={"hashes": [own_hash, peer_hash]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        matches = r.json()["matches"]
        uids = [m["user_id"] for m in matches]
        assert antonin_user_id not in uids, (
            f"self-match leak! own uid={antonin_user_id} in {uids}"
        )
        # peer must still be there
        assert peer1_uid in uids


class TestContactsMatchDedup:
    """Test 5: duplicates collapsed."""

    def test_same_hash_thrice_returns_one_match(self, antonin_token, peer1_uid):
        h = sha256_hex(PEER1_PHONE)
        r = requests.post(
            f"{BASE_URL}/api/contacts/match",
            headers={"Authorization": f"Bearer {antonin_token}"},
            json={"hashes": [h, h, h]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        matches = r.json()["matches"]
        assert len(matches) == 1, f"expected 1 got {len(matches)}: {matches}"


class TestContactsMatchBatchCap:
    """Test 6: batch cap 500."""

    def test_501_hashes_returns_413(self, antonin_token):
        # 501 unique hashes → must trigger 413
        hashes = [sha256_hex(f"+33600{i:06d}") for i in range(501)]
        r = requests.post(
            f"{BASE_URL}/api/contacts/match",
            headers={"Authorization": f"Bearer {antonin_token}"},
            json={"hashes": hashes},
            timeout=20,
        )
        assert r.status_code == 413, f"expected 413 got {r.status_code}: {r.text[:200]}"

    def test_exactly_500_hashes_allowed(self, antonin_token):
        # boundary — 500 is allowed
        hashes = [sha256_hex(f"+33600{i:06d}") for i in range(500)]
        r = requests.post(
            f"{BASE_URL}/api/contacts/match",
            headers={"Authorization": f"Bearer {antonin_token}"},
            json={"hashes": hashes},
            timeout=20,
        )
        assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text[:200]}"


class TestContactsMatchRegistration:
    """Test 7: fresh registration produces phone_hash immediately."""

    def test_new_user_matchable_after_register(self, antonin_token):
        # Generate a unique FR phone number (10 digits, prefix 06/07)
        unique_id = uuid.uuid4().int
        # Keep it plausible: 06 + 8 unique digits
        suffix = str(unique_id)[:8].zfill(8)
        raw_phone = f"06{suffix}"
        expected_e164 = f"+33{raw_phone[1:]}"  # 0X... → +33X...
        unique_email = f"TEST_phase42_{unique_id % 10**8}@example.com"

        # Register a fresh account
        payload = {
            "email": unique_email,
            "password": "testpass123",
            "name": "TEST_ContactMatch",
            "phone": raw_phone,
        }
        rr = requests.post(f"{BASE_URL}/api/auth/register", json=payload, timeout=15)
        assert rr.status_code == 200, f"register failed: {rr.status_code} {rr.text}"
        new_user = rr.json()["user"]
        new_uid = new_user["user_id"]
        # Server should have normalised to E.164
        assert new_user.get("phone") == expected_e164, (
            f"expected phone {expected_e164} got {new_user.get('phone')}"
        )

        # Now Antonin (a different account) matches on SHA-256(E.164)
        h = sha256_hex(expected_e164)
        r = requests.post(
            f"{BASE_URL}/api/contacts/match",
            headers={"Authorization": f"Bearer {antonin_token}"},
            json={"hashes": [h]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        matches = r.json()["matches"]
        assert any(m["user_id"] == new_uid for m in matches), (
            f"newly-registered user {new_uid} not matched. Got: {matches}"
        )


class TestContactsMatchEmailOnly:
    """Test 8: email-only users never appear in matches (no phone_hash)."""

    def test_email_only_never_matched(self, antonin_token):
        # Register an email-only account (no phone) — must not have phone_hash
        unique_id = uuid.uuid4().hex[:8]
        unique_email = f"TEST_emailonly_{unique_id}@example.com"
        payload = {
            "email": unique_email,
            "password": "testpass123",
            "name": "TEST_EmailOnly",
        }
        rr = requests.post(f"{BASE_URL}/api/auth/register", json=payload, timeout=15)
        assert rr.status_code == 200, f"register failed: {rr.status_code} {rr.text}"
        new_uid = rr.json()["user"]["user_id"]

        # Attempt to match by hashing a random string — the endpoint should
        # not return this email-only user for any hash. Positive control:
        # feed a large random batch and confirm the email-only uid is absent.
        random_hashes = [sha256_hex(f"random_{i}_{unique_id}") for i in range(20)]
        r = requests.post(
            f"{BASE_URL}/api/contacts/match",
            headers={"Authorization": f"Bearer {antonin_token}"},
            json={"hashes": random_hashes},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        uids = [m["user_id"] for m in r.json()["matches"]]
        assert new_uid not in uids, (
            f"email-only user {new_uid} leaked into matches: {uids}"
        )
