"""Phase A — OTP téléphone (SMS mocké, code fixe 123456).

Couvre :
    * request → account_exists true/false, mock=true, cooldown
    * verify  → création de compte (pseudo requis), login compte existant
    * erreurs → mauvais code, code expiré/consommé, pseudo pris, numéro invalide
    * cooldown 30 s entre deux envois
"""
import os
import uuid

import pytest
import requests

from conftest import BASE_URL

MOCK_CODE = "123456"


def _rand_phone() -> str:
    """Mobile FR aléatoire (06xxxxxxxx) pour isoler chaque run."""
    return "06" + str(uuid.uuid4().int)[:8]


def _cleanup(phone_local: str):
    """Best-effort delete via Mongo (les tests tournent sur le même pod)."""
    try:
        from pymongo import MongoClient
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "signalmar")]
        e164 = "+33" + phone_local.lstrip("0")
        db.users.delete_one({"phone": e164})
        db.otp_codes.delete_one({"phone": e164})
    except Exception:
        pass


@pytest.fixture
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def test_otp_full_signup_then_login(s):
    phone = _rand_phone()
    try:
        # 1) request → nouveau numéro
        r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": phone})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sent"] is True
        assert body["account_exists"] is False
        assert body["mock"] is True

        # 2) verify sans pseudo → 422
        r = s.post(f"{BASE_URL}/api/auth/otp/verify",
                   json={"phone": phone, "code": MOCK_CODE})
        assert r.status_code == 422

        # 3) mauvais code → 401
        r = s.post(f"{BASE_URL}/api/auth/otp/verify",
                   json={"phone": phone, "code": "000000", "pseudo": "PytestOtp"})
        assert r.status_code == 401

        # 4) verify + pseudo → création + JWT
        pseudo = f"Otp{str(uuid.uuid4().hex)[:8]}"
        r = s.post(f"{BASE_URL}/api/auth/otp/verify",
                   json={"phone": phone, "code": MOCK_CODE, "pseudo": pseudo})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["token"]
        assert data["user"]["pseudo"] == pseudo
        assert data["user"]["provider"] == "phone"
        assert data["user"]["phone"] == "+33" + phone.lstrip("0")

        # 5) le code est consommé → re-verify → 410
        r = s.post(f"{BASE_URL}/api/auth/otp/verify",
                   json={"phone": phone, "code": MOCK_CODE})
        assert r.status_code == 410

        # 6) /auth/me fonctionne avec le JWT
        r = s.get(f"{BASE_URL}/api/auth/me",
                  headers={"Authorization": f"Bearer {data['token']}"})
        assert r.status_code == 200
        assert r.json()["pseudo"] == pseudo
    finally:
        _cleanup(phone)


def test_otp_login_existing_seeded_account(s):
    # Compte seedé Phase T : SignalMar / +33760071445.
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": "0760071445"})
    if r.status_code == 429:  # cooldown d'un run précédent
        pytest.skip("cooldown actif sur le numéro seedé")
    assert r.status_code == 200, r.text
    assert r.json()["account_exists"] is True

    r = s.post(f"{BASE_URL}/api/auth/otp/verify",
               json={"phone": "0760071445", "code": MOCK_CODE})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["pseudo"] == "SignalMar"


def test_otp_invalid_phone_rejected(s):
    for bad in ["0123456789", "12345678", "+4479460958", "0812345678"]:
        r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": bad})
        assert r.status_code == 422, f"{bad} → {r.status_code}"


def test_otp_resend_cooldown(s):
    phone = _rand_phone()
    try:
        r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": phone})
        assert r.status_code == 200
        # Le header QA X-RateLimit-Bypass (injecté par conftest) saute aussi
        # le quota par numéro depuis le 11/07 — on le retire pour vérifier
        # que le cooldown reste actif pour un client normal.
        r = s.post(
            f"{BASE_URL}/api/auth/otp/request", json={"phone": phone},
            headers={"X-RateLimit-Bypass": ""},
        )
        assert r.status_code == 429
        assert "Réessayez" in r.json()["detail"]
    finally:
        _cleanup(phone)


def test_otp_pseudo_clash_rejected(s):
    phone = _rand_phone()
    try:
        r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": phone})
        assert r.status_code == 200
        # « SignalMar » appartient au compte seedé → 409.
        r = s.post(f"{BASE_URL}/api/auth/otp/verify",
                   json={"phone": phone, "code": MOCK_CODE, "pseudo": "SignalMar"})
        assert r.status_code == 409
    finally:
        _cleanup(phone)
