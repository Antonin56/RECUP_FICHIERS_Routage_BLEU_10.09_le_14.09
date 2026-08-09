"""Phase T (mode DEV, 11/07/2026) — bascule de comptes ouverte à tous.

Contrat DEV :
  * GET  /api/dev/test-accounts : tout utilisateur connecté voit TOUS les
    comptes (user_id, email, phone, pseudo, picture, points, is_current).
  * POST /api/dev/switch-account {target_user_id} : bascule vers n'importe
    quel compte existant ; 404 si inconnu ; 401 sans token.

⚠️ TODO AVANT PUBLICATION : ces endpoints seront restreints à l'admin
(+ recherche par téléphone) — ces tests devront alors être mis à jour.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")

ADMIN_EMAIL = "antoninlepinay@gmail.com"
ADMIN_PASSWORD = "123454321"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _register_random() -> tuple[str, dict]:
    """Crée un compte standard jetable → (token, user)."""
    email = f"phaseT_{uuid.uuid4().hex[:10]}@example.com"
    phone = f"+3399{uuid.uuid4().int % 100000000:08d}"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "password123",
              "name": "PhaseT Dev", "phone": phone},
        timeout=15,
    )
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return data["token"], data["user"]


@pytest.fixture(scope="module")
def admin_token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


class TestListAccountsDev:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/dev/test-accounts", timeout=10)
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_admin_sees_all_accounts_with_current_first(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/dev/test-accounts",
            headers=_auth(admin_token), timeout=15,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        data = r.json()
        accts = data["accounts"]
        assert len(accts) >= 1
        currents = [a for a in accts if a.get("is_current")]
        assert len(currents) == 1
        assert currents[0]["user_id"] == data["current_user_id"]
        # Compte courant en premier.
        assert accts[0]["is_current"] is True
        for a in accts:
            for k in ("user_id", "email", "phone", "pseudo", "picture",
                      "points", "is_current"):
                assert k in a, f"missing key {k} in {a}"

    def test_standard_account_rejected_since_purge(self):
        """10/07/2026 — PURGE : la whitelist du switcher ne contient plus que
        l'admin. Un compte standard fraîchement créé reçoit 403."""
        token, _user = _register_random()
        r = requests.get(
            f"{BASE_URL}/api/dev/test-accounts",
            headers=_auth(token), timeout=15,
        )
        assert r.status_code == 403, f"{r.status_code} {r.text}"


class TestSwitchAccountDev:
    def test_requires_auth(self):
        r = requests.post(
            f"{BASE_URL}/api/dev/switch-account",
            json={"target_user_id": "whatever"}, timeout=10,
        )
        assert r.status_code == 401

    def test_standard_cannot_switch_since_purge(self):
        """10/07/2026 — PURGE : un compte standard (hors whitelist) ne peut
        plus utiliser le switcher → 403."""
        token, _user = _register_random()
        r = requests.post(
            f"{BASE_URL}/api/dev/switch-account",
            headers=_auth(token),
            json={"target_user_id": "user_0b6070a69154"}, timeout=15,
        )
        assert r.status_code == 403, f"{r.status_code} {r.text}"

    def test_unknown_target_is_404(self, admin_token):
        r = requests.post(
            f"{BASE_URL}/api/dev/switch-account",
            headers=_auth(admin_token),
            json={"target_user_id": "no-such-user-xyz"}, timeout=15,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"
        assert (r.json() or {}).get("detail") == "target_not_found"
